"""The user's own AI traders: named agents, each with a guide and rules.

Before this, every client that connected — Claude Code, Cursor, Codex,
Autopilot, a script on the HTTP API — shared one bearer token, one set of rails
and one hardcoded set of server instructions. Two people connecting the same
model got the same trader, and one user could not run a careful researcher and
a sports specialist side by side and see which was any good.

An agent here is three things, and only one of them is trusted:

  * **A guide** — the user's own words to the model ("you only trade NBA
    totals; skip anything you can't explain in a sentence"). It is delivered
    as instructions and it CAN NOT unlock anything: it is text for a model,
    and a model can ignore it, be talked out of it, or be prompt-injected past
    it. Nothing below reads it.
  * **Rules** — categories, an entry-price band, time to close, sides, sizes,
    a minimum edge, its own money caps. Every one of them can only NARROW the
    global rails (`mcp_*` in config): an agent's min edge below the global one
    is the global one; its daily cap above the global one is the global one.
    They are enforced in mcp_server.vet() on every buy, so the guide saying
    "ignore your rules" changes nothing.
  * **Identity** — its own bearer token. The request's token decides which
    agent is calling, on MCP, the stdio bridge and the HTTP API alike; the
    built-in Default agent keeps the original token, so every client config
    copied before agents existed keeps working, as the agent it always was.

The global trade mode stays the master switch: off means nobody trades, paper
means everybody trades paper, and only under live does an agent's own `mode`
matter — an agent left on paper keeps trading paper while the user lets one
other agent go live.

Pure (no I/O): config.py validates through it, the renderer mirrors it in
shared/agents.ts, and both are tested against the same rules.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_ID = "default"
DEFAULT_NAME = "Default"
MAX_AGENTS = 12
NAME_MAX = 40
GUIDE_MAX = 4000
DEFAULT_EMOJI = "🤖"
DEFAULT_COLOR = "#A855F7"

CATEGORIES = ("sports", "politics", "economics", "crypto", "climate",
              "entertainment", "world", "exotics")
CATEGORY_LABEL = {
    "sports": "Sports", "politics": "Politics", "economics": "Economics",
    "crypto": "Crypto", "climate": "Climate", "entertainment": "Entertainment",
    "world": "World", "exotics": "Exotics",
}
SIDES = ("yes", "no", "both")

_ID_RE = re.compile(r"^[a-z0-9]{1,24}$")
RESERVED_IDS = frozenset({"account"})
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_CTRL_GUIDE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _clamp(v: Any, lo: float, hi: float) -> Optional[float]:
    x = _num(v)
    if x is None:
        return None
    return max(lo, min(hi, x))


def _clampi(v: Any, lo: int, hi: int) -> Optional[int]:
    x = _clamp(v, lo, hi)
    return None if x is None else int(round(x))


def clean_name(raw: Any, fallback: str = "Agent") -> str:
    s = _CTRL.sub("", re.sub(r"[\t\n\r\v\f\u2028\u2029]", " ", str(raw or "")))
    s = re.sub(r"\s+", " ", s).strip()[:NAME_MAX].strip()
    return s or fallback


def clean_guide(raw: Any) -> str:
    s = _CTRL_GUIDE.sub("", str(raw or "")).replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()[:GUIDE_MAX]


def _clean_emoji(raw: Any) -> str:
    s = _CTRL.sub("", str(raw or "")).strip()
    return s[:8] if s else DEFAULT_EMOJI


def _cats(raw: Any) -> Optional[list]:
    if not isinstance(raw, list):
        return None
    out = []
    for c in raw:
        c = str(c or "").strip().lower()
        if c in CATEGORIES and c not in out:
            out.append(c)
    return out or None


def clean_rules(raw: Any) -> dict:
    """Every rule optional; an absent or unreadable one is no rule (None).

    Clamped, never trusted: settings.json is user-editable and an imported
    agent file came from someone else. None of these can loosen a global rail
    whatever value they hold — see effective_rails()."""
    r = raw if isinstance(raw, dict) else {}
    out: dict = {
        "categoriesAllow": _cats(r.get("categoriesAllow")),
        "categoriesDeny": _cats(r.get("categoriesDeny")),
        "minPriceCents": _clampi(r.get("minPriceCents"), 1, 99),
        "maxPriceCents": _clampi(r.get("maxPriceCents"), 1, 99),
        "minHoursToClose": _clamp(r.get("minHoursToClose"), 0, 24 * 365),
        "maxHoursToClose": _clamp(r.get("maxHoursToClose"), 0, 24 * 365),
        "sides": r.get("sides") if r.get("sides") in SIDES else "both",
        "maxContractsPerMarket": _clampi(r.get("maxContractsPerMarket"), 0, 100_000),
        "maxOpenPositions": _clampi(r.get("maxOpenPositions"), 0, 200),
        "minEdgeCents": _clamp(r.get("minEdgeCents"), 0, 50),
        "dailySpendUsd": _clamp(r.get("dailySpendUsd"), 0, 1e7),
        "maxOrderUsd": _clamp(r.get("maxOrderUsd"), 0, 1e6),
    }
    return out


def default_agent(mode: str = "paper") -> dict:
    return {
        "id": DEFAULT_ID, "name": DEFAULT_NAME, "emoji": DEFAULT_EMOJI,
        "color": DEFAULT_COLOR, "createdAt": None, "updatedAt": None,
        "guide": "", "rules": clean_rules({}),
        "mode": "live" if mode == "live" else "paper", "enabled": True,
    }


def _ts(v: Any) -> Optional[str]:
    s = _CTRL.sub("", str(v or "")).strip()[:40]
    return s or None


def clean_agent(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    aid = str(raw.get("id") or "").strip().lower()
    if not _ID_RE.match(aid) or aid in RESERVED_IDS:
        return None
    color = str(raw.get("color") or "")
    en = raw.get("enabled", True)
    return {
        "id": aid,
        "name": clean_name(raw.get("name"), DEFAULT_NAME if aid == DEFAULT_ID else "Agent"),
        "emoji": _clean_emoji(raw.get("emoji")),
        "color": color if _COLOR_RE.match(color) else DEFAULT_COLOR,
        "createdAt": _ts(raw.get("createdAt")),
        "updatedAt": _ts(raw.get("updatedAt")),
        "guide": clean_guide(raw.get("guide")),
        "rules": clean_rules(raw.get("rules")),
        "mode": "live" if raw.get("mode") == "live" else "paper",
        "enabled": en if isinstance(en, bool) else False,
    }


def validate_agents(raw: Any, trade_mode: str) -> list[dict]:
    """The agent list as config stores it. Default is always present and
    always first; ids are unique; at most MAX_AGENTS.

    A config with no list at all is a config from before agents existed. Its
    Default inherits the global mode — a user who had agents trading live
    keeps them live after the upgrade, exactly as before; a list that exists
    is never rewritten that way."""
    if not isinstance(raw, list):
        return [default_agent("live" if trade_mode == "live" else "paper")]
    out: list[dict] = []
    seen: set = set()
    for item in raw:
        a = clean_agent(item)
        if a is None or a["id"] in seen:
            continue
        seen.add(a["id"])
        out.append(a)
    default = next((a for a in out if a["id"] == DEFAULT_ID), None)
    if default is None:
        default = default_agent("paper")
    rest = [a for a in out if a["id"] != DEFAULT_ID]
    return [default] + rest[:MAX_AGENTS - 1]


def agents(cfg: dict) -> list[dict]:
    return validate_agents(cfg.get("mcp_agents"), str(cfg.get("mcp_trade_mode") or "off"))


def get(cfg: dict, agent_id: Optional[str]) -> Optional[dict]:
    aid = agent_id or DEFAULT_ID
    return next((a for a in agents(cfg) if a["id"] == aid), None)


def valid_id(agent_id: Any) -> bool:
    return (isinstance(agent_id, str) and bool(_ID_RE.match(agent_id))
            and agent_id not in RESERVED_IDS)


def token_secret(agent_id: str) -> str:
    """Default keeps the original secret name, so the token every existing
    client config carries is Default's token — nothing to migrate."""
    if agent_id == DEFAULT_ID:
        return "mcp_token"
    if not valid_id(agent_id):
        raise ValueError("bad agent id")
    return f"mcp_token_{agent_id}"


def effective_mode(global_mode: str, agent: Optional[dict]) -> str:
    """The global mode is the master. off -> nobody trades; paper ->
    everybody paper; live -> only an agent whose own mode is live."""
    if global_mode not in ("paper", "live") or agent is None:
        return "off"
    if global_mode == "paper":
        return "paper"
    return "live" if agent.get("mode") == "live" else "paper"


def effective_rails(global_rails: dict, agent: Optional[dict]) -> dict:
    """The rails that bind this agent: each the STRICTER of the global value
    and the agent's own. A rule can narrow; nothing here can widen."""
    r = (agent or {}).get("rules") or {}
    out = dict(global_rails)
    if r.get("maxOrderUsd") is not None:
        out["maxOrderUsd"] = min(out["maxOrderUsd"], float(r["maxOrderUsd"]))
    if r.get("dailySpendUsd") is not None:
        out["dailySpendUsd"] = min(out["dailySpendUsd"], float(r["dailySpendUsd"]))
    if r.get("minEdgeCents") is not None:
        out["minEdgeCents"] = max(out["minEdgeCents"], float(r["minEdgeCents"]))
    return out


def map_category(raw: Any) -> Optional[str]:
    """Kalshi's own category string -> our canonical id, or None.

    None when Kalshi published none or one we cannot map: a keyword guess
    (categorize_by_keywords falls back to "world") would let an agent told
    "Sports only" buy into a market the guess got wrong."""
    s = str(raw or "").strip()
    if not s:
        return None
    if s.lower() in CATEGORIES:
        return s.lower()
    from categorize import KALSHI_CATEGORY_MAP, KALSHI_CATEGORY_MAP_CI
    return KALSHI_CATEGORY_MAP.get(s) or KALSHI_CATEGORY_MAP_CI.get(s.lower())


def hours_to_close(close_time: Any, now: Optional[datetime] = None) -> Optional[float]:
    if not close_time:
        return None
    try:
        s = str(close_time).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (dt - now).total_seconds() / 3600.0


def _cat_list(cats: list) -> str:
    names = [CATEGORY_LABEL.get(c, c) for c in cats]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def _hours_txt(h: float) -> str:
    if h >= 72 and abs(h / 24 - round(h / 24)) < 1e-9:
        return f"{int(round(h / 24))} days"
    return f"{h:g}h"


def entry_blockers(agent: dict, *, side: str, price_cents: float,
                   category: Optional[str], hours_left: Optional[float]) -> list[str]:
    """The agent's decision rules for one BUY, as refusals naming the agent.
    Pure. Exits are never checked here: an agent may always close what it
    opened, whatever its rules say now."""
    r = agent.get("rules") or {}
    who = f"{agent.get('name') or 'This agent'}'s rules"
    out: list[str] = []
    allow = r.get("categoriesAllow") or []
    deny = r.get("categoriesDeny") or []
    if allow or deny:
        if category is None:
            out.append(f"{who}: trades by category, and Kalshi publishes no category "
                       f"this app can map for this market, so it can't be checked. No trade.")
        elif allow and category not in allow:
            out.append(f"{who}: only {_cat_list(allow)} markets; this one is "
                       f"{CATEGORY_LABEL.get(category, category)}.")
        elif category in deny:
            out.append(f"{who}: never {CATEGORY_LABEL.get(category, category)} markets.")
    name = agent.get("name") or "this agent"
    lo, hi = r.get("minPriceCents"), r.get("maxPriceCents")
    if lo is not None and price_cents < lo:
        out.append(f"{who}: entry at {price_cents:g}¢ is below {name}'s {lo:g}¢ minimum.")
    if hi is not None and price_cents > hi:
        out.append(f"{who}: entry at {price_cents:g}¢ is above {name}'s {hi:g}¢ max.")
    mx, mn = r.get("maxHoursToClose"), r.get("minHoursToClose")
    if mx is not None or mn is not None:
        if hours_left is None:
            out.append(f"{who}: trades by time to close, and this market has no close "
                       f"time to check. No trade.")
        else:
            left = (f"{hours_left / 24:.1f} days" if hours_left >= 48
                    else f"{max(hours_left, 0):.1f}h")
            if mx is not None and hours_left > mx:
                out.append(f"{who}: closes in {left}; {name} trades "
                           f"≤{_hours_txt(mx)} to close.")
            if mn is not None and hours_left < mn:
                out.append(f"{who}: closes in {left}; {name} wants at "
                           f"least {_hours_txt(mn)} to close.")
    sides = r.get("sides") or "both"
    if sides in ("yes", "no") and side != sides:
        out.append(f"{who}: buys {sides.upper()} only.")
    return out


def rules_summary(agent: dict, rails: dict, mode: str) -> list[str]:
    """The hard rules in plain sentences, for the model (instructions,
    get_my_agent, Autopilot's prompt) and the editor's preview. The model is
    told them so it does not spend calls on orders that will be refused —
    telling it is a courtesy; vet() is the rule."""
    r = agent.get("rules") or {}
    out: list[str] = []
    if r.get("categoriesAllow"):
        out.append(f"Only {_cat_list(r['categoriesAllow'])} markets.")
    if r.get("categoriesDeny"):
        out.append(f"Never {_cat_list(r['categoriesDeny'])} markets.")
    lo, hi = r.get("minPriceCents"), r.get("maxPriceCents")
    if lo is not None and hi is not None:
        out.append(f"Entry price between {lo:g}¢ and {hi:g}¢.")
    elif lo is not None:
        out.append(f"Entry price at least {lo:g}¢.")
    elif hi is not None:
        out.append(f"Entry price at most {hi:g}¢.")
    if r.get("maxHoursToClose") is not None:
        out.append(f"Only markets that close within {_hours_txt(r['maxHoursToClose'])}.")
    if r.get("minHoursToClose") is not None:
        out.append(f"Only markets at least {_hours_txt(r['minHoursToClose'])} from closing.")
    if (r.get("sides") or "both") != "both":
        out.append(f"Buys {r['sides'].upper()} only.")
    if r.get("maxOpenPositions") == 0 or r.get("maxContractsPerMarket") == 0:
        out.append("No positions: this agent records forecasts only and places no orders.")
    else:
        if r.get("maxContractsPerMarket") is not None:
            out.append(f"At most {r['maxContractsPerMarket']} contracts in any one market.")
        if r.get("maxOpenPositions") is not None:
            out.append(f"At most {r['maxOpenPositions']} open positions of its own.")
    out.append(f"Minimum edge after Kalshi's fee: {rails['minEdgeCents']:g}¢ per contract "
               f"against its own forecast.")
    out.append(f"Money caps: ${rails['maxOrderUsd']:,.2f} per order, "
               f"${rails['dailySpendUsd']:,.2f} per UTC day.")
    out.append({"off": "Trading is OFF: it can read markets and record forecasts only.",
                "paper": "Mode: PAPER — real order books, imaginary money.",
                "live": "Mode: LIVE — orders spend the user's real Kalshi balance."}[mode])
    out.append("Rules govern new buys. Selling to exit what it opened is always allowed.")
    return out


def is_customised(agent: dict) -> bool:
    """Default with no guide and no rule is the agent every client got before
    agents existed; its instructions stay exactly what they were."""
    if agent.get("id") != DEFAULT_ID or agent.get("guide"):
        return True
    r = agent.get("rules") or {}
    return any(v not in (None, "both") for v in r.values())


def instructions(base: str, agent: Optional[dict], rails: dict, mode: str) -> str:
    """The MCP `initialize` instructions for one agent: the server's own
    rules, then who it is, the user's guide, and its hard rules."""
    if agent is None or not is_customised(agent):
        return base
    parts = [base, "", f"YOU ARE: {agent['name']} — one of the user's own named agents "
             f"in Krypt Trader."]
    if agent.get("guide"):
        parts += ["", "THE USER'S GUIDE FOR YOU (how they want you to think and decide):",
                  agent["guide"]]
    parts += ["", "YOUR HARD RULES (enforced by the app; an order that breaks one is "
              "refused, so don't place it):"]
    parts += [f"- {s}" for s in rules_summary(agent, rails, mode)]
    return "\n".join(parts)


def public_view(agent: dict, rails: dict, mode: str) -> dict:
    """What get_my_agent returns: the agent as the model should know it."""
    return {
        "id": agent["id"], "name": agent["name"], "emoji": agent.get("emoji"),
        "mode": mode, "configuredMode": agent.get("mode"),
        "enabled": agent.get("enabled", True),
        "guide": agent.get("guide") or "",
        "rules": {k: v for k, v in (agent.get("rules") or {}).items()
                  if v is not None and not (k == "sides" and v == "both")},
        "effectiveRails": {k: rails[k] for k in ("maxOrderUsd", "dailySpendUsd",
                                                   "minEdgeCents", "maxOpenPositions",
                                                   "dailyLossUsd", "forecastTtlMin")
                           if k in rails},
        "rulesInWords": rules_summary(agent, rails, mode),
    }


def server_name(agent: dict) -> str:
    """The name a client files this server under. Default keeps the name
    every existing config uses; the others get their own, so connecting two
    agents to one client adds a second server instead of replacing the first.
    [a-z0-9-] only: it lands in a shell command and a TOML table key."""
    if agent.get("id") == DEFAULT_ID:
        return "krypt-trader"
    slug = re.sub(r"[^a-z0-9]+", "-", str(agent.get("name") or "").lower()).strip("-")[:20].strip("-")
    return f"krypt-trader-{slug}-{agent['id'][:6]}" if slug else f"krypt-trader-{agent['id']}"
