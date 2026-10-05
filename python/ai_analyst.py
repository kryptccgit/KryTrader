from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

import kalshi_auth

logger = logging.getLogger("ai_analyst")

PROVIDERS = ("anthropic", "openai")

SECRET_NAMES = {
    "anthropic": "ai_anthropic_key",
    "openai": "ai_openai_key",
}

MODELS = {
    "anthropic": (
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-haiku-4-5",
    ),
    "openai": (
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-5.4",
        "gpt-5.4-mini",
    ),
}
DEFAULT_MODEL = {"anthropic": "claude-opus-5", "openai": "gpt-5.5"}

PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

_WEB_SEARCH_MODERN = "web_search_20260209"
_WEB_SEARCH_BASIC = "web_search_20250305"
_MODERN_SEARCH_MODELS = {"claude-opus-5", "claude-sonnet-5", "claude-opus-4-8"}

_MAX_TOKENS = 4000
_TIMEOUT_SEC = 180.0

_SYSTEM = """You are a prediction-market analyst embedded in a Kalshi trading terminal. \
A trader has opened one market and asked what you make of it.

HOW TO READ THE DATA YOU ARE GIVEN
A field rendered as "--" is ABSENT: nobody published that number. It is not \
zero. Kalshi reports no-bid as a zero and never-traded as a zero, so this \
terminal strips those to "--" before you see them. Never reason about a "--" \
as if it were 0, and never fill one in with an assumption. Say the number is \
missing and say what that costs your analysis.
Each price carries its source. A quote marked cached or stale is evidence \
about a moment that has passed; weigh it as such.
Prices are in cents and are probabilities: 62c means the market prices this at \
roughly 62%.

WHAT TO PRODUCE
Explain what is actually driving this market, what the current price implies, \
and what the resolution rules literally say -- resolution criteria are where \
prediction markets most often surprise people who traded the headline instead \
of the terms.
Give a directional read: your own fair value in cents, a range around it, and \
whether the market looks cheap, rich, or fair against it. If you do not have \
enough to justify a number, return null for the fair value and say why. A \
null is a real answer here. A made-up 50 is not.
You are not placing an order and must not tell the trader to. No position \
sizing, no entries, no "buy this".

OUTPUT
Reply with ONE JSON object and nothing else -- no prose before it, no code \
fence around it:
{
  "summary": "2-4 sentences: what this market is and where it stands.",
  "drivers": [{"heading": "short label", "body": "1-3 sentences"}],
  "resolutionNotes": "What the rules literally require, and any trap in them. \
null if the rules were not provided.",
  "fairValueCents": 41,
  "fairValueLowCents": 33,
  "fairValueHighCents": 49,
  "verdict": "cheap" | "rich" | "fair" | "unclear",
  "confidence": "low" | "medium" | "high",
  "wouldChangeMyMind": ["A specific observable that would move your estimate"]
}
fairValueCents, fairValueLowCents and fairValueHighCents are integers 1-99, or \
null. verdict is "unclear" whenever fairValueCents is null. Give 2-5 drivers \
and 2-4 wouldChangeMyMind entries."""


def _norm_provider(v: Any) -> str:
    p = str(v or "").strip().lower()
    return p if p in PROVIDERS else "anthropic"


def normalize_model(provider: str, model: Any) -> str:
    provider = _norm_provider(provider)
    m = str(model or "").strip()
    return m if m in MODELS[provider] else DEFAULT_MODEL[provider]


def save_key(provider: str, key: str) -> bool:
    provider = _norm_provider(provider)
    name = SECRET_NAMES[provider]
    key = str(key or "").strip()
    if key:
        kalshi_auth.save_secret(name, key)
    else:
        kalshi_auth.clear_secret(name)
    try:
        import logscrub
        logscrub.refresh_known_secrets()
    except Exception:
        pass
    return kalshi_auth.has_secret(name)


def has_key(provider: str) -> bool:
    return kalshi_auth.has_secret(SECRET_NAMES[_norm_provider(provider)])


def _read_key(provider: str) -> Optional[str]:
    return kalshi_auth.read_secret(SECRET_NAMES[_norm_provider(provider)])


def status(cfg: Optional[dict] = None) -> dict:
    cfg = cfg or {}
    provider = _norm_provider(cfg.get("ai_provider"))
    return {
        "provider": provider,
        "model": normalize_model(provider, cfg.get("ai_model")),
        "webSearch": bool(cfg.get("ai_web_search")),
        "hasKey": has_key(provider),
        "keys": {p: kalshi_auth.has_secret(SECRET_NAMES[p]) for p in PROVIDERS},
        "models": {p: list(MODELS[p]) for p in PROVIDERS},
        "providers": list(PROVIDERS),
    }


def _c(v: Any) -> str:
    if v is None:
        return "--"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "--"
    return f"{f:.1f}c" if f % 1 else f"{f:.0f}c"


def _n(v: Any) -> str:
    if v is None:
        return "--"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _txt(v: Any) -> str:
    s = str(v).strip() if v is not None else ""
    return s or "--"


def _source_note(market: dict) -> str:
    srcs = market.get("sources") or {}
    if not isinstance(srcs, dict) or not srcs:
        return ""
    parts = []
    for field, src in sorted(srcs.items()):
        if isinstance(src, dict):
            src = src.get("source") or src.get("kind")
        if src:
            parts.append(f"{field}={src}")
    return ("  sources: " + ", ".join(parts)) if parts else ""


def _market_line(m: dict, prefix: str = "") -> str:
    lines = [f"{prefix}{_txt(m.get('ticker'))} | {_txt(m.get('title'))}"]
    if m.get("yesSubTitle"):
        lines.append(f"{prefix}  YES means: {_txt(m.get('yesSubTitle'))}")
    lines.append(
        f"{prefix}  yes bid {_c(m.get('yesBid'))} / yes ask {_c(m.get('yesAsk'))}"
        f" | no bid {_c(m.get('noBid'))} / no ask {_c(m.get('noAsk'))}"
    )
    lines.append(
        f"{prefix}  mid {_c(m.get('midCents'))} | spread {_c(m.get('spreadCents'))}"
        f" | last {_c(m.get('lastPrice'))} | previous {_c(m.get('previousPrice'))}"
    )
    lines.append(
        f"{prefix}  volume {_n(m.get('volume'))} | 24h volume {_n(m.get('volume24h'))}"
        f" | open interest {_n(m.get('openInterest'))}"
    )
    mins = m.get("minutesToClose")
    when = f"{_n(mins)} minutes from now" if mins is not None else "--"
    lines.append(
        f"{prefix}  status {_txt(m.get('status'))} | closes {_txt(m.get('closeTime'))} ({when})"
    )
    return "\n".join(lines)


def render_market(detail: dict) -> str:
    market = (detail.get("market") or {}) if isinstance(detail, dict) else {}
    event = detail.get("event") or {}
    series = detail.get("series") or {}
    risk = detail.get("risk") or {}
    book = detail.get("book") or {}
    position = detail.get("position") or {}

    out = ["THE MARKET", _market_line(market)]
    note = _source_note(market)
    if note:
        out.append(note)

    drift = detail.get("quoteDriftCents")
    if drift is not None:
        out.append(
            f"  NOTE: the market record's quote and the order book disagreed by "
            f"{_c(drift)} when both were read -- this market is moving faster than a page load."
        )

    if event:
        out.append("")
        out.append("THE EVENT")
        out.append(f"  {_txt(event.get('title'))}")
        if event.get("subTitle"):
            out.append(f"  {_txt(event.get('subTitle'))}")
        out.append(f"  category: {_txt(event.get('category'))}")
        sibs = event.get("siblings") or []
        if sibs:
            out.append(
                f"  {len(sibs)} sibling market(s) in this event -- the rest of the "
                "distribution this one is a leg of:"
            )
            for s in sibs[:25]:
                out.append(_market_line(s, prefix="    "))

    if series:
        out.append("")
        out.append("THE SERIES")
        out.append(f"  {_txt(series.get('title'))} (frequency: {_txt(series.get('frequency'))})")

    checks = risk.get("checks") or []
    if checks or risk.get("rulesPrimary"):
        out.append("")
        out.append("RESOLUTION")
        if risk.get("rulesPrimary"):
            out.append(f"  primary rules: {_txt(risk.get('rulesPrimary'))}")
        if risk.get("rulesSecondary"):
            out.append(f"  secondary rules: {_txt(risk.get('rulesSecondary'))}")
        for src in (risk.get("settlementSources") or []):
            if isinstance(src, dict):
                out.append(f"  settles from: {_txt(src.get('name'))}")
        out.append(
            f"  resolution-risk score: {_txt(risk.get('score'))}"
            f" ({_n(risk.get('resolvedCount'))} of {_n(risk.get('totalCount'))} checks resolved)"
        )
        if risk.get("scoreNote"):
            out.append(f"  {_txt(risk.get('scoreNote'))}")
        for ch in checks:
            if not isinstance(ch, dict):
                continue
            out.append(
                f"  [{_txt(ch.get('verdict'))}] {_txt(ch.get('label'))}: {_txt(ch.get('detail'))}"
            )

    yes_levels = (book.get("yes") or []) if isinstance(book, dict) else []
    no_levels = (book.get("no") or []) if isinstance(book, dict) else []
    if yes_levels or no_levels:
        out.append("")
        out.append("ORDER BOOK -- resting BIDS on each side (price x contracts, best first)")
        out.append("  A YES ask is a NO bid mirrored: yesAsk = 100 - bestNoBid.")
        out.append(
            "  yes: "
            + (", ".join(f"{_c(l.get('priceCents'))}x{_n(l.get('contracts'))}"
                         for l in yes_levels[:8] if isinstance(l, dict)) or "--")
        )
        out.append(
            "  no:  "
            + (", ".join(f"{_c(l.get('priceCents'))}x{_n(l.get('contracts'))}"
                         for l in no_levels[:8] if isinstance(l, dict)) or "--")
        )
        out.append(
            f"  depth: yes {_n(book.get('yesDepthContracts'))}"
            f" / no {_n(book.get('noDepthContracts'))}"
            f" | source {_txt(book.get('source'))}"
            + ("  STALE: " + _txt(book.get("note")) if book.get("stale") else "")
        )

    if position:
        out.append("")
        out.append("THE TRADER'S CURRENT POSITION IN THIS MARKET")
        out.append(
            f"  {_n(position.get('contracts'))} contracts {_txt(position.get('side'))}"
            f" | average cost {_c(position.get('avgCostCents'))}"
            f" | mark {_c(position.get('markCents'))}"
            f" | unrealised ${_txt(position.get('unrealizedUsd'))}"
        )
        if not position.get("reconciled"):
            out.append(
                f"  UNRECONCILED against Kalshi's fills ledger: {_txt(position.get('reconcileNote'))}."
                " The average cost above is unknown, not break-even -- do not compute a"
                " profit from it."
            )
        out.append(
            "  They already own this. Say what that means for the read; do not "
            "tell them to add, trim, or exit."
        )

    errs = detail.get("errors") or []
    if errs:
        out.append("")
        out.append("PANELS THAT FAILED TO LOAD (their data is missing, not empty)")
        for e in errs:
            if isinstance(e, dict):
                out.append(f"  {_txt(e.get('panel'))}: {_txt(e.get('message'))}")

    out.append("")
    out.append(f"Data fetched at {_txt(detail.get('fetchedAt'))}.")
    return "\n".join(out)


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.M)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    body = _FENCE.sub("", text).strip()
    start = body.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(body)):
        ch = body[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(body[start:i + 1])
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _cents_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 99 else None


def _one_of(v: Any, allowed: tuple, dflt: str) -> str:
    s = str(v or "").strip().lower()
    return s if s in allowed else dflt


def _insights(v: Any) -> list:
    out = []
    if isinstance(v, list):
        for item in v[:8]:
            if isinstance(item, dict):
                heading = str(item.get("heading") or "").strip()
                body = str(item.get("body") or "").strip()
            else:
                heading, body = "", str(item or "").strip()
            if body:
                out.append({"heading": heading or "Note", "body": body})
    return out


def _strings(v: Any) -> list:
    if not isinstance(v, list):
        return []
    return [str(s).strip() for s in v[:8] if str(s or "").strip()]


def _shape(parsed: Optional[dict], raw: str) -> dict:
    if not parsed:
        return {
            "summary": "",
            "drivers": [],
            "resolutionNotes": None,
            "fairValueCents": None,
            "fairValueLowCents": None,
            "fairValueHighCents": None,
            "verdict": "unclear",
            "confidence": "low",
            "wouldChangeMyMind": [],
            "raw": raw or "",
        }

    fair = _cents_or_none(parsed.get("fairValueCents"))
    low = _cents_or_none(parsed.get("fairValueLowCents"))
    high = _cents_or_none(parsed.get("fairValueHighCents"))
    if low is not None and high is not None and low > high:
        low, high = high, low
    verdict = _one_of(parsed.get("verdict"), ("cheap", "rich", "fair", "unclear"), "unclear")
    if fair is None:
        verdict = "unclear"

    return {
        "summary": str(parsed.get("summary") or "").strip(),
        "drivers": _insights(parsed.get("drivers")),
        "resolutionNotes": (str(parsed.get("resolutionNotes")).strip()
                            if parsed.get("resolutionNotes") else None),
        "fairValueCents": fair,
        "fairValueLowCents": low,
        "fairValueHighCents": high,
        "verdict": verdict,
        "confidence": _one_of(parsed.get("confidence"), ("low", "medium", "high"), "low"),
        "wouldChangeMyMind": _strings(parsed.get("wouldChangeMyMind")),
        "raw": None,
    }


def _cost_usd(model: str, in_tok: Optional[int], out_tok: Optional[int]) -> Optional[float]:
    price = PRICING.get(model)
    if not price or in_tok is None or out_tok is None:
        return None
    return round(in_tok / 1e6 * price[0] + out_tok / 1e6 * price[1], 4)


class AiError(Exception):
    pass


def anthropic_error(e: Exception, model: str) -> AiError:
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return AiError("That Anthropic API key was rejected. Check it in Settings.")
    if isinstance(e, anthropic.PermissionDeniedError):
        return AiError("That Anthropic key is valid but not allowed to use this model.")
    if isinstance(e, anthropic.NotFoundError):
        return AiError(f"Anthropic has no model called {model}. Pick another in Settings.")
    if isinstance(e, anthropic.RateLimitError):
        return AiError("Anthropic rate-limited this key. Wait a moment and try again.")
    if isinstance(e, anthropic.APITimeoutError):
        return AiError("Anthropic did not answer in time. Try again, or turn web search off.")
    if isinstance(e, anthropic.APIConnectionError):
        return AiError("Could not reach Anthropic. Check the connection and try again.")
    if isinstance(e, anthropic.APIStatusError):
        return AiError(f"Anthropic returned {e.status_code}: {_first_line(str(e))}")
    return AiError(f"Anthropic call failed: {_first_line(str(e))}")


def openai_error(e: Exception, model: str) -> AiError:
    import openai
    if isinstance(e, openai.AuthenticationError):
        return AiError("That OpenAI API key was rejected. Check it in Settings.")
    if isinstance(e, openai.PermissionDeniedError):
        return AiError("That OpenAI key is valid but not allowed to use this model.")
    if isinstance(e, openai.NotFoundError):
        return AiError(f"OpenAI has no model called {model}. Pick another in Settings.")
    if isinstance(e, openai.RateLimitError):
        return AiError("OpenAI rate-limited this key. Wait a moment and try again.")
    if isinstance(e, openai.APITimeoutError):
        return AiError("OpenAI did not answer in time. Try again, or turn web search off.")
    if isinstance(e, openai.APIConnectionError):
        return AiError("Could not reach OpenAI. Check the connection and try again.")
    if isinstance(e, openai.APIStatusError):
        return AiError(f"OpenAI returned {e.status_code}: {_first_line(str(e))}")
    return AiError(f"OpenAI call failed: {_first_line(str(e))}")


def _call_anthropic(key: str, model: str, prompt: str, web_search: bool) -> dict:
    import anthropic

    tools = []
    if web_search:
        kind = _WEB_SEARCH_MODERN if model in _MODERN_SEARCH_MODELS else _WEB_SEARCH_BASIC
        tools.append({"type": kind, "name": "web_search", "max_uses": 6})

    client = anthropic.Anthropic(api_key=key, timeout=_TIMEOUT_SEC, max_retries=2)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            thinking={"type": "adaptive"},
            tools=tools or anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        raise anthropic_error(e, model) from e

    if getattr(resp, "stop_reason", None) == "refusal":
        raise AiError("Claude declined to analyse this market.")

    text_parts, citations = [], []
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text or "")
            for cite in (getattr(block, "citations", None) or []):
                url = getattr(cite, "url", None)
                if url:
                    citations.append({
                        "title": str(getattr(cite, "title", "") or url),
                        "url": str(url),
                    })

    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "input_tokens", None)
    out_tok = getattr(usage, "output_tokens", None)
    return {
        "text": "\n".join(text_parts).strip(),
        "citations": citations,
        "inputTokens": in_tok,
        "outputTokens": out_tok,
        "costUsd": _cost_usd(model, in_tok, out_tok),
    }


def _call_openai(key: str, model: str, prompt: str, web_search: bool) -> dict:
    import openai

    tools = [{"type": "web_search"}] if web_search else []

    client = openai.OpenAI(api_key=key, timeout=_TIMEOUT_SEC, max_retries=2)
    try:
        resp = client.responses.create(
            model=model,
            instructions=_SYSTEM,
            input=prompt,
            max_output_tokens=_MAX_TOKENS,
            tools=tools or openai.NOT_GIVEN,
        )
    except openai.APIError as e:
        raise openai_error(e, model) from e

    citations = []
    for item in (getattr(resp, "output", None) or []):
        for part in (getattr(item, "content", None) or []):
            for ann in (getattr(part, "annotations", None) or []):
                if getattr(ann, "type", None) == "url_citation":
                    url = getattr(ann, "url", None)
                    if url:
                        citations.append({
                            "title": str(getattr(ann, "title", "") or url),
                            "url": str(url),
                        })

    usage = getattr(resp, "usage", None)
    return {
        "text": (getattr(resp, "output_text", None) or "").strip(),
        "citations": citations,
        "inputTokens": getattr(usage, "input_tokens", None),
        "outputTokens": getattr(usage, "output_tokens", None),
        "costUsd": None,
    }


def _first_line(s: str) -> str:
    line = (s or "").strip().splitlines()[0] if (s or "").strip() else ""
    return line[:200]


def _dedupe_citations(cites: list) -> list:
    seen, out = set(), []
    for c in cites:
        url = c.get("url")
        if url and url not in seen:
            seen.add(url)
            out.append(c)
    return out[:12]


def analyze(detail: dict, cfg: Optional[dict] = None) -> dict:
    cfg = cfg or {}
    provider = _norm_provider(cfg.get("ai_provider"))
    model = normalize_model(provider, cfg.get("ai_model"))
    web_search = bool(cfg.get("ai_web_search"))

    key = _read_key(provider)
    if not key:
        label = "Anthropic" if provider == "anthropic" else "OpenAI"
        raise AiError(f"Set your {label} API key in Settings to analyse markets.")

    market = (detail.get("market") or {}) if isinstance(detail, dict) else {}
    ticker = str(market.get("ticker") or "")
    if not ticker:
        raise AiError("No market to analyse.")

    prompt = render_market(detail)
    started = time.time()
    if provider == "anthropic":
        res = _call_anthropic(key, model, prompt, web_search)
    else:
        res = _call_openai(key, model, prompt, web_search)
    elapsed = time.time() - started

    text = res["text"]
    parsed = _extract_json(text)
    if parsed is None and text:
        logger.info(
            "[ai] %s/%s returned prose rather than JSON for %s; showing it raw",
            provider, model, ticker,
        )

    body = _shape(parsed, text)
    logger.info(
        "[ai] analysed %s via %s/%s in %.1fs (websearch=%s, verdict=%s)",
        ticker, provider, model, elapsed, web_search, body["verdict"],
    )
    return {
        "ticker": ticker,
        "provider": provider,
        "model": model,
        "webSearchUsed": web_search,
        "citations": _dedupe_citations(res["citations"]),
        "inputTokens": res["inputTokens"],
        "outputTokens": res["outputTokens"],
        "costUsd": res["costUsd"],
        "elapsedSec": round(elapsed, 1),
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **body,
    }
