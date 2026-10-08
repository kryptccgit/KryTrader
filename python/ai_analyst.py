"""AI market analysis. The user brings their own key (or their own machine);
we bring the context.

Six providers, and deliberately not one "OpenAI-compatible" shim pointed at
all of them. A shim would have to lie about most of them: the APIs differ in
where the system prompt goes, how web search is declared (or whether it
exists), what a citation looks like, and which failure means "your key is
wrong" versus "try again later" versus "start the server". Every one of those
is something this module has to get right for the error to be actionable.

  * Anthropic and OpenAI keep their own SDK call paths here
    (`_call_anthropic`, `_call_openai`).
  * OpenRouter, Gemini, Ollama and LM Studio live in `ai_providers`, which
    holds a per-provider capability table (web search, tool calling, token
    accounting, pricing) and a per-provider error table. OpenRouter and LM
    Studio share a Chat Completions transport because they really are that
    API; Gemini and Ollama use their native APIs, for reasons written down
    there.

What is NOT per provider is the parsing. Every reply, whoever produced it,
goes through the same `_extract_json` and `_shape`: a fair value outside 1..99
is None, a verdict with no number is "unclear", absent inputs were "--". A
local 8B model is exactly the kind of model that writes a confident 50, so the
safety cannot be something one provider path does and another forgets.

Three rules this module inherits from the rest of the terminal:

  * A number nobody could produce is None (invariant 1). That applies to the
    model's own output too: `fair_value_cents` is None when it declines to
    commit, never 50. It applies to our cost estimate, which is None for
    OpenAI because we do not have published per-token prices for those models
    and a plausible-looking guess is worse than an em dash.
  * The model is told which numbers are missing, in those words. The market
    payload renders an absent quote as "--", never as 0, and the system prompt
    says what that means. Kalshi sends `yes_bid: 0` for "no bid"; handing that
    to a model as a zero produces confident analysis of a price that does not
    exist.
  * No URLs or hosts from the renderer (invariant 3). The renderer names a
    ticker, a provider id and a model id. Provider hosts come from the SDKs
    or from constants in ai_providers; the only knob is a boolean for whether
    the model may search the web at all.

The output is advisory and says so. It never places an order: the trade ticket
is reached the same way it always was, by a human deciding to.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any, Optional

import ai_providers
import kalshi_auth
from ai_providers import CAPS, AiError

logger = logging.getLogger("ai_analyst")

PROVIDERS = ("anthropic", "openai", "openrouter", "gemini", "ollama", "lmstudio")
LOCAL_PROVIDERS = tuple(p for p in PROVIDERS if CAPS[p].local)

SECRET_NAMES = {
    "anthropic": "ai_anthropic_key",
    "openai": "ai_openai_key",
    "openrouter": "ai_openrouter_key",
    "gemini": "ai_gemini_key",
}

CURATED = ("anthropic", "openai")
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
    **{p: ai_providers.SUGGESTED[p] for p in ai_providers.HTTP_PROVIDERS},
}
DEFAULT_MODEL = {"anthropic": "claude-opus-5", "openai": "gpt-5.5",
                 **ai_providers.DEFAULT_MODEL}

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
    """A model string we are willing to send. Anything unrecognised falls back
    to the provider's default rather than travelling to the API, so a stale
    saved setting degrades to a working call instead of a 404."""
    provider = _norm_provider(provider)
    if provider not in CURATED:
        return ai_providers.clean_model(provider, model)
    m = str(model or "").strip()
    return m if m in MODELS[provider] else DEFAULT_MODEL[provider]


def needs_key(provider: str) -> bool:
    return CAPS[_norm_provider(provider)].needs_key


def save_key(provider: str, key: str) -> bool:
    provider = _norm_provider(provider)
    if provider not in SECRET_NAMES:
        raise ValueError(f"{CAPS[provider].label} runs on this machine and takes no key")
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
    """Whether a key is STORED. False for a local provider, which has none."""
    name = SECRET_NAMES.get(_norm_provider(provider))
    return bool(name) and kalshi_auth.has_secret(name)


def ready(provider: str) -> bool:
    """Whether a call could be attempted: a key is stored, or none is needed.
    Whether the local server is actually up is check_provider's question --
    that needs a network call, and this is read on every status poll."""
    return has_key(provider) or not needs_key(provider)


def _read_key(provider: str) -> Optional[str]:
    name = SECRET_NAMES.get(_norm_provider(provider))
    return kalshi_auth.read_secret(name) if name else None


def _models_for(provider: str) -> list:
    """The curated list, or the suggestions plus whatever the last free
    listing returned. Never a network call: status() is polled."""
    base = list(MODELS[provider])
    if provider in CURATED:
        return base
    listed = [m.id for m in ai_providers.cached_models(provider)]
    return listed + [m for m in base if m not in listed] if listed else base


def capabilities(provider: str) -> dict:
    c = CAPS[_norm_provider(provider)]
    return {"label": c.label, "local": c.local, "needsKey": c.needs_key,
            "webSearch": c.web_search, "webSearchHow": c.web_search_how,
            "tools": c.tools, "toolsHow": c.tools_how, "tokens": c.tokens,
            "pricing": c.pricing, "catalogue": c.catalogue,
            "modelsEndpoint": c.models_endpoint}


def status(cfg: Optional[dict] = None) -> dict:
    """What Settings and the market panel both render. Deliberately says
    nothing about the key beyond whether one exists."""
    cfg = cfg or {}
    provider = _norm_provider(cfg.get("ai_provider"))
    return {
        "provider": provider,
        "model": normalize_model(provider, cfg.get("ai_model")),
        "webSearch": bool(cfg.get("ai_web_search")) and CAPS[provider].web_search,
        "hasKey": ready(provider),
        "keys": {p: has_key(p) for p in PROVIDERS},
        "models": {p: _models_for(p) for p in PROVIDERS},
        "providers": list(PROVIDERS),
        "capabilities": {p: capabilities(p) for p in PROVIDERS},
        "prices": {m: {"inPerMTok": i, "outPerMTok": o} for m, (i, o) in PRICING.items()},
    }


def check_provider(provider: str, cfg: Optional[dict] = None) -> dict:
    """{ok, message, models?} for one provider, from FREE endpoints only: a
    model listing (and, for OpenRouter, its key-info endpoint). Never a billed
    completion. Blocking; call it off the loop.

    The connection-health panel calls this by name; keep the name and shape."""
    p = str(provider or "").strip().lower()
    if p not in PROVIDERS:
        return {"ok": False, "provider": p, "message": f"Unknown AI provider: {p or '--'}"}
    cfg = cfg or {}
    model = (normalize_model(p, cfg.get("ai_model"))
             if _norm_provider(cfg.get("ai_provider")) == p else DEFAULT_MODEL[p])
    res = ai_providers.check(p, _read_key(p), model)
    if p in CURATED and res.get("ok"):
        listed = set(res.get("models") or [])
        res["models"] = [m for m in MODELS[p] if m in listed] or list(MODELS[p])
        res.pop("modelInfo", None)
    res.setdefault("provider", p)
    res["model"] = model
    return res


def tool_support(provider: str, model: Any) -> tuple[bool, str]:
    """Whether Autopilot can run on this provider/model -- it works only
    through tools. Blocking (a local call or a free listing)."""
    p = _norm_provider(provider)
    return ai_providers.tool_support(p, _read_key(p), normalize_model(p, model))



def _c(v: Any) -> str:
    """A cent price, or the em dash that means nobody published one."""
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
    """Per-field provenance, collapsed to one line (invariant 2). The model
    should know a 40c it is reasoning about came from a cache."""
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
    """MarketDetail -> the text the model reads. Absent stays absent."""
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
    """First balanced {...} in the reply, parsed.

    Prompt-directed JSON rather than a provider structured-output mode, because
    the two providers spell that differently and Anthropic rejects it outright
    alongside citations -- which is exactly the combination web search
    produces. One lenient parser is one code path that behaves the same with
    search on and off; when it fails the caller still shows the raw reply.
    """
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
    """1..99 or None. Everything else -- 0, 100, "maybe", a bare null -- is
    None, because a price outside the tradable band is not a fair value the
    trader can act on and pretending otherwise is the failure this whole file
    is trying to avoid."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or not (1.0 <= f <= 99.0):
        return None
    return int(round(f))


def _probability_shaped(*vals: Any) -> bool:
    """True when the model answered in probabilities, not cents: some value
    is a fraction strictly between 0 and 1. Then EVERY number in the answer
    is suspect -- a 1.0 beside a 0.55 is 100%, not 1c -- so none is used."""
    for v in vals:
        if isinstance(v, bool) or v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f) and 0.0 < f < 1.0:
            return True
    return False


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
    """The AiAnalysis body. When parsing failed every field is empty and `raw`
    carries the reply, so the panel can show what the model actually said
    rather than an error that throws the analysis away."""
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

    raw_fair = parsed.get("fairValueCents")
    raw_low = parsed.get("fairValueLowCents")
    raw_high = parsed.get("fairValueHighCents")
    if _probability_shaped(raw_fair, raw_low, raw_high):
        fair = low = high = None
    else:
        fair = _cents_or_none(raw_fair)
        low = _cents_or_none(raw_low)
        high = _cents_or_none(raw_high)
    if low is not None and high is not None and low > high:
        low, high = high, low
    if fair is not None and low is not None and high is not None \
            and not (low <= fair <= high):
        fair = None
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





def anthropic_error(e: Exception, model: str) -> AiError:
    """A provider exception -> a message a user can act on. Shared with the
    autopilot's tool loop, so "your key is wrong" reads the same everywhere.
    Order matters: the timeout class is a subclass of the connection class."""
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

    http = ai_providers.counted_client(_TIMEOUT_SEC)
    try:
        client = anthropic.Anthropic(api_key=key, timeout=_TIMEOUT_SEC, max_retries=2,
                                     http_client=http)
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
    finally:
        http.close()

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

    http = ai_providers.counted_client(_TIMEOUT_SEC)
    try:
        client = openai.OpenAI(api_key=key, timeout=_TIMEOUT_SEC, max_retries=2,
                               http_client=http)
        resp = client.responses.create(
            model=model,
            instructions=_SYSTEM,
            input=prompt,
            max_output_tokens=_MAX_TOKENS,
            tools=tools or openai.NOT_GIVEN,
        )
    except openai.APIError as e:
        raise openai_error(e, model) from e
    finally:
        http.close()

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


_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_THINK_OPEN = re.compile(r"<(think|thinking|reasoning)>", re.I)


def _strip_reasoning(text: str) -> str:
    out = _THINK.sub("", text or "")
    m = _THINK_OPEN.search(out)
    if m:
        out = out[:m.start()]
    return out.strip()


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
    """Analyse one already-fetched market. Blocking; call it off the loop.

    `detail` is the MarketDetail the terminal already has on screen -- we
    re-render it rather than re-fetch, so the model is looking at exactly the
    numbers the trader is.
    """
    cfg = cfg or {}
    provider = _norm_provider(cfg.get("ai_provider"))
    model = normalize_model(provider, cfg.get("ai_model"))
    web_search = bool(cfg.get("ai_web_search"))

    key = _read_key(provider)
    if needs_key(provider) and not key:
        raise AiError(f"Set your {CAPS[provider].label} API key in Settings to analyse markets.")

    market = (detail.get("market") or {}) if isinstance(detail, dict) else {}
    ticker = str(market.get("ticker") or "")
    if not ticker:
        raise AiError("No market to analyse.")

    prompt = render_market(detail)
    started = time.time()
    if provider == "anthropic":
        res = _call_anthropic(key, model, prompt, web_search)
    elif provider == "openai":
        res = _call_openai(key, model, prompt, web_search)
    else:
        model = ai_providers.resolve_model(provider, model)
        res = ai_providers.call(provider, key, model, _SYSTEM, prompt, web_search,
                                _TIMEOUT_SEC)
    web_used = bool(res.get("webSearchUsed", web_search))
    elapsed = time.time() - started

    text = res["text"]
    parsed = _extract_json(_strip_reasoning(text))
    if parsed is None and text:
        logger.info(
            "[ai] %s/%s returned prose rather than JSON for %s; showing it raw",
            provider, model, ticker,
        )

    body = _shape(parsed, text)
    logger.info(
        "[ai] analysed %s via %s/%s in %.1fs (websearch=%s, verdict=%s)",
        ticker, provider, model, elapsed, web_used, body["verdict"],
    )
    return {
        "ticker": ticker,
        "provider": provider,
        "model": model,
        "webSearchUsed": web_used,
        "citations": _dedupe_citations(res["citations"]),
        "inputTokens": res["inputTokens"],
        "outputTokens": res["outputTokens"],
        "costUsd": res["costUsd"],
        "elapsedSec": round(elapsed, 1),
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **body,
    }
