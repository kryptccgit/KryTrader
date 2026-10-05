from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("crossvenue")

CONFIDENT = 0.55
CANDIDATE = 0.34

STOP = {
    "will", "the", "a", "an", "be", "is", "are", "to", "of", "in", "on", "at",
    "by", "for", "and", "or", "this", "that", "it", "there", "before", "after",
    "than", "with", "from", "vs", "v", "have", "has", "had", "do", "does",
    "any", "up", "down", "out", "get", "who", "what", "when", "next", "win",
    "wins", "won", "winner", "nominee", "nomination", "election", "elections",
    "presidential", "president", "presidency", "market", "markets", "party",
    "above", "below", "over", "under", "between", "end", "close", "closing",
}

_WORD = re.compile(r"[a-z0-9$.']+")
_PROPER = re.compile(r"(?<!^)(?<![.!?]\s)\b([A-Z][A-Za-z.'\-]{1,})")


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall((text or "").lower()):
        w = w.strip(".'")
        if len(w) > 1 and w not in STOP:
            out.append(w)
    return out


def proper_nouns(text: str) -> set[str]:
    out: set[str] = set()
    for w in _PROPER.findall(text or ""):
        wl = w.lower().strip(".'-")
        if len(wl) > 1 and wl not in STOP:
            out.add(wl)
    return out


_NUMBER = re.compile(r"\$?\s?([0-9][0-9,]*(?:\.[0-9]+)?)")


def numbers(text: str) -> set[float]:
    out: set[float] = set()
    for raw in _NUMBER.findall(text or ""):
        try:
            out.add(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


_OFFICE_PATTERNS = [
    ("vice_president", r"vice[\s-]?presid|\bvp\b"),
    ("president", r"presiden"),
    ("senate", r"\bsenat"),
    ("house", r"\bhouse of representatives\b|\bcongressional\b"),
    ("governor", r"\bgovernor\b|\bgubernatorial\b"),
    ("mayor", r"\bmayor\b|\bmayoral\b"),
]

_STAGE_PATTERNS = [
    ("nomination", r"\bnominee\b|\bnominat|\bprimary\b|\bprimaries\b"),
    ("general_election", r"\bgeneral election\b|win the [^.]{0,24}election\b"
                         r"|\bbe elected\b|\bbecome (?:the )?president\b"),
]


_NAME_CONJUNCTION = re.compile(
    r"[A-Z][A-Za-z.'-]+\s+and\s+[A-Z][A-Za-z.'-]+")


def conjoins_names(text: str) -> bool:
    return bool(_NAME_CONJUNCTION.search(text or ""))


def _first_match(text: str, patterns: list[tuple[str, str]]) -> Optional[str]:
    t = (text or "").lower()
    for name, pattern in patterns:
        if re.search(pattern, t):
            return name
    return None


def office(text: str) -> Optional[str]:
    return _first_match(text, _OFFICE_PATTERNS)


def stage(text: str) -> Optional[str]:
    return _first_match(text, _STAGE_PATTERNS)


_DIRECTION_PATTERNS = [
    ("above", r"\babove\b|\bover\b|\bgreater\b|\bhigher\b|\bexceed|\bat least\b|\bor more\b|\bup\b"),
    ("below", r"\bbelow\b|\bunder\b|\bless\b|\blower\b|\bbeneath\b|\bat most\b|\bor fewer\b|\bor less\b|\bdown\b"),
]

_NEGATION = re.compile(
    r"\bnot\b|\bno longer\b|\bnever\b|\bfail(?:s|ed)? to\b|\bwithout\b|\bn't\b")


def direction(text: str) -> Optional[str]:
    t = (text or "").lower()
    hits = [name for name, pat in _DIRECTION_PATTERNS if re.search(pat, t)]
    return hits[0] if len(hits) == 1 else None


def negated(text: str) -> bool:
    return bool(_NEGATION.search((text or "").lower()))


def build_idf(docs: list[list[str]]) -> dict[str, float]:
    df: Counter = Counter()
    for d in docs:
        for t in set(d):
            df[t] += 1
    n = max(1, len(docs))
    return {t: math.log(n / (1 + c)) + 1.0 for t, c in df.items()}


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _discriminators(toks: list[str], idf: dict[str, float]) -> set[str]:
    uniq = set(toks)
    if not uniq:
        return set()
    top = max(idf.get(t, 1.0) for t in uniq)
    cut = max(top * 0.62, 2.0)
    return {t for t in uniq if idf.get(t, 1.0) >= cut}


def _phrase(items) -> str:
    vals = [str(x) for x in sorted(items)][:3]
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    return ", ".join(vals[:-1]) + " and " + vals[-1]


def _num_phrase(items) -> str:
    def fmt(x: float) -> str:
        return str(int(x)) if float(x).is_integer() else str(x)
    return _phrase([fmt(x) for x in sorted(items)])


def score_pair(
    k_text: str, p_text: str, idf: dict[str, float],
    k_close: Any = None, p_close: Any = None,
) -> tuple[float, list[str]]:
    kt, pt = tokens(k_text), tokens(p_text)
    ka, pa = set(kt), set(pt)
    if not ka or not pa:
        return 0.0, ["nothing to compare"]

    shared = ka & pa
    w_shared = sum(idf.get(t, 1.0) for t in shared)
    w_all = sum(idf.get(t, 1.0) for t in ka | pa)
    conf = (w_shared / w_all) if w_all else 0.0
    why: list[str] = []

    kd, pd = _discriminators(kt, idf), _discriminators(pt, idf)
    if kd and pd:
        shared_d = kd & pd
        kp, pp = proper_nouns(k_text), proper_nouns(p_text)
        only_k = {t for t in (kd - pd) & kp if idf.get(t, 1.0) >= 3.0}
        only_p = {t for t in (pd - kd) & pp if idf.get(t, 1.0) >= 3.0}

        if only_k and only_p:
            conf *= 0.12
            why.append(
                f"different names ({_phrase(only_k)} vs {_phrase(only_p)})")
        elif shared_d:
            conf = min(1.0, conf + 0.22)
            why.append(f"both name {_phrase(shared_d)}")
        else:
            conf *= 0.15
            why.append(
                f"no shared key terms ({_phrase(kd)} vs {_phrase(pd)})")

    k_nums, p_nums = numbers(k_text), numbers(p_text)
    only_kn, only_pn = k_nums - p_nums, p_nums - k_nums
    if only_kn and only_pn:
        conf *= 0.35
        why.append(
            f"different numbers ({_num_phrase(only_kn)} vs {_num_phrase(only_pn)})")
    elif k_nums and p_nums and (k_nums & p_nums):
        why.append(f"same numbers ({_num_phrase(k_nums & p_nums)})")

    k_off, p_off = office(k_text), office(p_text)
    if k_off and p_off and k_off != p_off:
        conf *= 0.10
        why.append(f"different office: {k_off.replace('_', ' ')} vs "
                   f"{p_off.replace('_', ' ')}")
    k_stage, p_stage = stage(k_text), stage(p_text)
    if k_stage and p_stage and k_stage != p_stage:
        conf *= 0.10
        why.append(f"different stage: {k_stage.replace('_', ' ')} vs "
                   f"{p_stage.replace('_', ' ')}")
    elif bool(k_stage) != bool(p_stage):
        conf *= 0.45
        stated = (k_stage or p_stage).replace("_", " ")
        why.append(f"only one side says it is about the {stated}")

    k_dir, p_dir = direction(k_text), direction(p_text)
    if k_dir and p_dir and k_dir != p_dir:
        conf *= 0.05
        why.append(f"opposite directions: {k_dir} vs {p_dir}")

    if negated(k_text) != negated(p_text):
        conf *= 0.05
        why.append("one side asks for the opposite outcome")

    if conjoins_names(k_text) != conjoins_names(p_text):
        conf *= 0.20
        why.append("one side combines two names, the other names one")

    kdt, pdt = _parse_dt(k_close), _parse_dt(p_close)
    if kdt and pdt:
        days = abs((kdt - pdt).total_seconds()) / 86400.0
        if days <= 2:
            conf = min(1.0, conf + 0.10)
            why.append("same close date")
        elif days > 30:
            conf *= 0.4
            why.append(f"close dates {days:.0f} days apart")
    else:
        why.append("close dates could not be compared")

    return round(max(0.0, min(1.0, conf)), 3), why


def find_matches(
    kalshi_market: dict, poly_markets: list[dict], limit: int = 4,
) -> list[dict]:
    k_text = " ".join(filter(None, [
        kalshi_market.get("title") or "",
        kalshi_market.get("yesSubTitle") or "",
    ]))
    p_texts = [(p.get("question") or "") for p in poly_markets]
    idf = build_idf([tokens(k_text)] + [tokens(t) for t in p_texts])

    scored: list[dict] = []
    for p, p_text in zip(poly_markets, p_texts):
        conf, why = score_pair(
            k_text, p_text, idf,
            kalshi_market.get("closeTime"), p.get("endDate"),
        )
        if conf < CANDIDATE:
            continue
        scored.append({
            "confidence": conf,
            "confident": conf >= CONFIDENT,
            "reasons": why,
            "market": p,
        })
    scored.sort(key=lambda x: -x["confidence"])
    return scored[:limit]


def compare(kalshi_market: dict, poly_market: dict) -> dict:
    k_bid, k_ask = kalshi_market.get("yesBid"), kalshi_market.get("yesAsk")
    p_bid, p_ask = poly_market.get("yesBid"), poly_market.get("yesAsk")

    def _mid(b, a):
        return round((b + a) / 2.0, 2) if (b is not None and a is not None) else None

    k_mid, p_mid = _mid(k_bid, k_ask), _mid(p_bid, p_ask)
    diff = round(k_mid - p_mid, 2) if (k_mid is not None and p_mid is not None) else None

    cheaper = None
    if k_ask is not None and p_ask is not None:
        if abs(k_ask - p_ask) >= 0.5:
            cheaper = "kalshi" if k_ask < p_ask else "polymarket"
        else:
            cheaper = "neither"

    return {
        "kalshiBid": k_bid, "kalshiAsk": k_ask, "kalshiMid": k_mid,
        "polyBid": p_bid, "polyAsk": p_ask, "polyMid": p_mid,
        "differenceCents": diff,
        "cheaperToBuyYes": cheaper,
        "askDifferenceCents": (
            round(abs(k_ask - p_ask), 2)
            if (k_ask is not None and p_ask is not None) else None
        ),
    }


VENUE_NOTE = (
    "These are two different venues, not two windows onto one market. Kalshi is "
    "a CFTC-regulated US exchange: contracts settle under published exchange "
    "rules against named sources, and member funds sit in segregated accounts. "
    "Polymarket is an on-chain venue settling through the UMA optimistic "
    "oracle, where a resolution is proposed and can be disputed by token "
    "holders. Two markets asking the same question in English can still settle "
    "differently — so a price difference here is a price difference, not free "
    "money, and it is never presented as one."
)
