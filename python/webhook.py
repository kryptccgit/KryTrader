from __future__ import annotations

import os as _os

APP_VERSION = _os.environ.get("KRYPT_APP_VERSION", "")

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_ALLOWED_WEBHOOK_HOSTS = frozenset({"discord.com"})


def _is_allowed_webhook(url: str) -> bool:
    try:
        u = urlparse(url)
    except (ValueError, TypeError):
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in _ALLOWED_WEBHOOK_HOSTS

COLOR = {
    "placed":   0x6366F1,
    "filled":   0x22C55E,
    "partial":  0xF1C40F,
    "canceled": 0x95A5A6,
    "gone":     0x7F8C8D,
    "error":    0xEF4444,
    "won":      0x22C55E,
    "lost":     0xEF4444,
    "na":       0x71717A,
    "startup":  0xA855F7,
    "shutdown": 0x52525B,
    "stats":    0x6366F1,
}

EMOJI = {
    "placed":   "📥",
    "filled":   "✅",
    "partial":  "🟡",
    "canceled": "⏱️",
    "gone":     "👻",
    "error":    "⚠️",
    "won":      "🎯",
    "lost":     "💔",
    "na":       "—",
    "startup":  "🚀",
    "shutdown": "⏹️",
    "stats":    "📊",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_cents(v) -> str:
    if v is None:
        return "—"
    return f"{int(round(float(v)))}¢"


def _describe_url(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
    except Exception:
        return "unparseable"
    if p.hostname:
        return f"{p.scheme or 'no-scheme'}://{p.hostname}"
    return f"unparseable, {len(url or '')} chars"


async def _post(url: str, payload: dict) -> None:
    if not url:
        return
    if not _is_allowed_webhook(url):
        logger.warning(
            "Refusing to send webhook to non-Discord/insecure URL "
            f"({_describe_url(url)}); only https Discord webhooks are allowed."
        )
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            )
        if r.status_code >= 300:
            logger.debug(f"discord webhook HTTP {r.status_code}: {r.text[:160]}")
    except Exception as e:
        logger.debug(f"discord webhook failed: {e}")


def _krypt_footer(env: str, pos_id: int | str = "?", coid: str = "") -> dict:
    return {
        "text": f"Krypt Trader · {env.upper()} · pos#{pos_id}"
        + (f" · {coid[:14]}" if coid else "")
    }


def event_embed(kind: str, pos: dict, env: str, note: str = "") -> dict:
    src = (pos.get("signal_source") or "?").upper()
    ticker = pos.get("ticker") or "?"
    title = pos.get("title") or ""
    direction = (pos.get("direction") or "?").upper()
    emoji = EMOJI.get(kind, "•")

    if kind == "placed":
        header = "Order Placed"
    elif kind == "filled":
        header = "Filled"
    elif kind == "partial":
        header = "Partial Fill"
    elif kind == "canceled":
        header = "Canceled"
    elif kind == "gone":
        header = "Disappeared"
    elif kind == "error":
        header = "Order Error"
    elif kind == "won":
        header = "Won"
    elif kind == "lost":
        header = "Lost"
    else:
        header = kind.title()

    embed: dict = {
        "title": f"{emoji} {header} · {src}",
        "color": COLOR.get(kind, 0x6366F1),
        "timestamp": _now_iso(),
        "footer": _krypt_footer(env, pos.get("id", "?"), pos.get("client_order_id", "")),
        "fields": [],
    }

    desc = [f"**{ticker}** · {direction}"]
    if title:
        desc.append(title[:240])
    embed["description"] = "\n".join(desc)

    target = int(pos.get("target_contracts") or 0)
    filled = int(pos.get("filled_contracts") or 0)
    cost = float(pos.get("cost_usd") or 0)
    avg = pos.get("avg_fill_price_cents")
    limit = pos.get("limit_price_cents")
    edge = float(pos.get("edge_pts") or 0)
    conf = float(pos.get("confidence") or 0)

    if kind == "placed":
        embed["fields"] = [
            {"name": "Size",
             "value": f"{target} @ {_fmt_cents(limit)} = ${target*(limit or 0)/100:.2f}",
             "inline": True},
            {"name": "Edge / Conf",
             "value": f"+{edge:.1f} / {conf:.1f}", "inline": True},
            {"name": "Balance",
             "value": f"${float(pos.get('balance_before_usd') or 0):.2f}",
             "inline": True},
        ]
    elif kind in ("filled", "partial"):
        embed["fields"] = [
            {"name": "Got",
             "value": f"{filled}/{target} @ {_fmt_cents(avg)} (${cost:.2f})",
             "inline": True},
            {"name": "Limit", "value": _fmt_cents(limit), "inline": True},
        ]
    elif kind in ("canceled", "gone"):
        reason = note or pos.get("error") or "stale"
        embed["fields"] = [
            {"name": "Reason", "value": str(reason)[:1000], "inline": False},
        ]
    elif kind == "error":
        embed["fields"] = [
            {"name": "Details", "value": str(pos.get("error") or "unknown")[:1000], "inline": False},
        ]
    elif kind in ("won", "lost"):
        pnl = float(pos.get("pnl_usd") or 0)
        settle = float(pos.get("settlement_usd") or 0)
        pct = (pnl / cost * 100) if cost > 0 else 0
        embed["fields"] = [
            {"name": "P&L",
             "value": f"**${pnl:+.2f}**" + (f"  ({pct:+.1f}%)" if cost > 0 else ""),
             "inline": True},
            {"name": "Bought",
             "value": f"{filled} @ {_fmt_cents(avg)} = ${cost:.2f}" if filled else "—",
             "inline": True},
            {"name": "Settlement", "value": f"${settle:.2f}", "inline": True},
        ]
    return embed


def whale_embed(whale: dict) -> dict:
    cat = whale.get("category", "?")
    title = whale.get("title", whale.get("ticker", ""))
    side = (whale.get("taker_side") or "yes").upper()
    price = float(whale.get("price") or 0)
    dollar = float(whale.get("dollar_value") or 0)
    conf = float(whale.get("confidence") or 0)
    return {
        "title": f"🐳 Whale · {cat.title()}",
        "color": 0xA855F7,
        "timestamp": _now_iso(),
        "description": f"**{title[:240]}**\n{side} @ {price*100:.0f}¢ · ${dollar:,.0f}",
        "fields": [
            {"name": "Confidence", "value": f"{conf:.1f}%", "inline": True},
            {"name": "Edge", "value": f"+{conf - price*100:.1f} pts", "inline": True},
        ],
        "footer": {"text": "Krypt Trader · Whale Scanner"},
    }


def momentum_embed(alert: dict) -> dict:
    cat = alert.get("category", "?")
    title = alert.get("title", alert.get("ticker", ""))
    direction = (alert.get("direction") or "yes").upper()
    price = float(alert.get("price") or 0)
    conf = float(alert.get("confidence") or 0)
    sig = alert.get("signal_type", "")
    implied = (price if direction == "YES" else 1 - price) * 100
    return {
        "title": f"📈 Momentum · {cat.title()}",
        "color": 0xEC4899,
        "timestamp": _now_iso(),
        "description": f"**{title[:240]}**\n{direction} @ market {price*100:.0f}¢ · {sig}",
        "fields": [
            {"name": "Confidence", "value": f"{conf:.1f}%", "inline": True},
            {"name": "Edge", "value": f"+{conf - implied:.1f} pts", "inline": True},
        ],
        "footer": {"text": "Krypt Trader · Momentum Scanner"},
    }




async def send_event(url: str, kind: str, pos: dict, env: str, note: str = "") -> None:
    if not url:
        return
    payload = {"username": "Krypt Trader", "embeds": [event_embed(kind, pos, env, note)]}
    await _post(url, payload)


async def send_whale(url: str, whale: dict) -> None:
    if not url:
        return
    payload = {"username": "Krypt Trader · Whale", "embeds": [whale_embed(whale)]}
    await _post(url, payload)


async def send_momentum(url: str, alert: dict) -> None:
    if not url:
        return
    payload = {"username": "Krypt Trader · Momentum", "embeds": [momentum_embed(alert)]}
    await _post(url, payload)


async def send_startup(url: str, env: str, balance_usd: float, portfolio_usd: float) -> None:
    if not url:
        return
    embed = {
        "title": f"{EMOJI['startup']} Krypt Trader online",
        "color": COLOR["startup"],
        "timestamp": _now_iso(),
        "description": (
            f"Env **{env.upper()}** · Cash **${balance_usd:.2f}** · "
            f"Portfolio **${portfolio_usd:.2f}**"
        ),
        "footer": {"text": "krypt.cc/tools/trader"},
    }
    await _post(url, {"username": "Krypt Trader", "embeds": [embed]})


async def send_shutdown(url: str, note: str = "clean exit") -> None:
    if not url:
        return
    embed = {
        "title": f"{EMOJI['shutdown']} Krypt Trader offline",
        "color": COLOR["shutdown"],
        "timestamp": _now_iso(),
        "description": str(note)[:1000],
    }
    await _post(url, {"username": "Krypt Trader", "embeds": [embed]})


def _fmt_pnl(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:.2f}"


def stats_embed(snap: dict, env: str) -> dict:
    cash = float(snap.get("cashUsd") or 0)
    port = float(snap.get("portfolioUsd") or 0)
    total = float(snap.get("totalUsd") or 0)
    today_pnl = float(snap.get("todayPnlUsd") or 0)
    session_pnl = float(snap.get("sessionPnlUsd") or 0)
    alltime_pnl = float(snap.get("alltimePnlUsd") or 0)
    realized_pnl = float(snap.get("realizedPnlUsd") or 0)
    unrealized = float(snap.get("unrealizedPnlUsd") or 0)
    wins = int(snap.get("wins") or 0)
    losses = int(snap.get("losses") or 0)
    win_rate = float(snap.get("winRate") or 0)
    open_count = int(snap.get("openCount") or 0)
    pending_count = int(snap.get("pendingCount") or 0)
    total_opened = int(snap.get("totalOpened") or 0)
    today_wins = int(snap.get("todayWins") or 0)
    today_losses = int(snap.get("todayLosses") or 0)
    roi = float(snap.get("roiPct") or 0)
    session_roi = float(snap.get("sessionRoiPct") or 0)

    color = (
        COLOR["won"] if today_pnl > 0
        else COLOR["lost"] if today_pnl < 0
        else COLOR["stats"]
    )
    return {
        "title": f"{EMOJI['stats']} Krypt Trader · Hourly Stats",
        "color": color,
        "timestamp": _now_iso(),
        "description": (
            f"**{env.upper()}** · Total **${total:.2f}** "
            f"(cash ${cash:.2f} · portfolio ${port:.2f})"
        ),
        "fields": [
            {"name": "Today P&L", "value": _fmt_pnl(today_pnl), "inline": True},
            {"name": "Session P&L",
             "value": f"{_fmt_pnl(session_pnl)} ({session_roi:+.2f}%)",
             "inline": True},
            {"name": "All-time P&L",
             "value": f"{_fmt_pnl(alltime_pnl)} ({roi:+.2f}%)",
             "inline": True},
            {"name": "Realized", "value": _fmt_pnl(realized_pnl), "inline": True},
            {"name": "Unrealized", "value": _fmt_pnl(unrealized), "inline": True},
            {"name": "Today W/L",
             "value": f"{today_wins} / {today_losses}", "inline": True},
            {"name": "All-time W/L",
             "value": f"{wins} / {losses}", "inline": True},
            {"name": "Win rate", "value": f"{win_rate:.1f}%", "inline": True},
            {"name": "Open / Pending",
             "value": f"{open_count} / {pending_count}", "inline": True},
            {"name": "Total opened",
             "value": f"{total_opened}", "inline": True},
        ],
        "footer": {"text": f"Krypt Trader · {env.upper()} · Hourly Stats"},
    }


async def send_stats(url: str, snap: dict, env: str) -> None:
    if not url:
        return
    payload = {
        "username": "Krypt Trader · Stats",
        "appVersion": APP_VERSION,
        "embeds": [stats_embed(snap, env)],
    }
    await _post(url, payload)
