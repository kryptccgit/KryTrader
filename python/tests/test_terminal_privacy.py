"""The privacy catalogue must stay true.

A panel that names most of the hosts is worse than no panel at all: it converts
"I did not check" into "I checked and it was fine". So this walks every source
file and asserts that every https:// and wss:// literal the app can actually
call is either named in `terminal.HOSTS` or explicitly excused here with a
reason.

If this fails, the fix is to update the catalogue — never to widen the
exclusions without one.
"""
from __future__ import annotations

import re
from pathlib import Path

import kalshi_api
import terminal

PY_DIR = Path(__file__).resolve().parents[1]

EXCUSED = {
    "kalshi.com": "documentation / market links, opened in your browser",
    "docs.kalshi.com": "documentation link",
    "help.kalshi.com": "documentation link",
    "krypt.cc": "our own site, opened in your browser from About",
    "x.com": "share link, opened in your browser",
    "discord.gg": "community invite, opened in your browser",
    "www.youtube.com": "link, opened in your browser",
    "python.org.": "a URL inside a comment",
    "polymarket.com": "market link, opened in your browser",
}

_URL = re.compile(r"(?:https?|wss)://([A-Za-z0-9.-]+(?::\d+)?)")


def _hosts_in_sources() -> set[str]:
    found: set[str] = set()
    for path in PY_DIR.glob("*.py"):
        if path.name.startswith(("live_", "test_")):
            continue
        for host in _URL.findall(path.read_text(encoding="utf-8")):
            found.add(host)
    return found


def test_every_host_the_backend_can_call_is_named_in_the_panel():
    named = {h["host"] for h in terminal.HOSTS}
    unaccounted = _hosts_in_sources() - named - set(EXCUSED)
    assert not unaccounted, (
        "These hosts appear in python/ but are not in terminal.HOSTS, so the "
        "Privacy panel would under-report what this app contacts: "
        f"{sorted(unaccounted)}"
    )


def test_the_catalogue_does_not_name_hosts_that_do_not_exist():
    in_source = _hosts_in_sources()
    stale = [h["host"] for h in terminal.HOSTS if h["host"] not in in_source]
    assert not stale, f"catalogued but not referenced anywhere: {stale}"


def test_every_entry_says_what_it_sends_and_whether_it_is_required():
    for h in terminal.HOSTS:
        assert h["purpose"] and len(h["purpose"]) > 20, h["host"]
        assert h["when"], h["host"]
        assert h["sends"], h["host"]
        assert isinstance(h["required"], bool), h["host"]
        if not h["required"]:
            assert h["optional_off"], h["host"]


def test_the_discord_webhook_is_named_as_sending_your_trading_elsewhere():
    d = next(h for h in terminal.HOSTS if h["host"] == "discord.com")
    assert d["required"] is False
    for word in ("balance", "P&L", "positions"):
        assert word in d["sends"] or word in d["purpose"], word


def test_nothing_reports_home():
    """The app used to post anonymous P&L to four Krypt-owned Discord webhooks
    on a ~30-minute timer, on by default. It was removed. This pins the
    absence: no module, no hardcoded webhook URL anywhere in the backend, and
    no host entry claiming otherwise."""
    from pathlib import Path
    py = Path(__file__).resolve().parents[1]
    assert not (py / "leaderboard.py").exists()

    offenders = []
    for path in py.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "discord.com/api/webhooks" in text:
            offenders.append(path.name)
        if "leaderboard" in text.lower():
            offenders.append(f"{path.name} (mentions leaderboard)")
    assert not offenders, offenders

    d = next(h for h in terminal.HOSTS if h["host"] == "discord.com")
    blob = f"{d['purpose']} {d['when']} {d['sends']}".lower()
    assert "leaderboard" not in blob
    assert "nothing is sent to us" in blob



NOT_REQUESTED = {
    "kalshi.com": "sign-up / referral link, opened in the user's browser",
    "docs.kalshi.com": "documentation URL cited in comments",
    "help.kalshi.com": "documentation URL cited in comments",
    "polymarket.com": "site link shown next to a cross-venue quote",
    "espn.com": "named in a comment about where a settlement source comes from",
    "krypt.cc": "our site: a User-Agent string and a webhook embed footer, "
                "never a request target",
    "api.example.com": "placeholder in a docstring/test fixture",
    "x.com": "social link",
    "www.youtube.com": "guide video link",
    "youtube.com": "guide video link",
    "github.com": "repository link",
    "localhost": "the app's own backend",
    "127.0.0.1": "the app's own backend",
}

TRACKERS = (
    "google-analytics", "googletagmanager", "analytics.google",
    "sentry.io", "ingest.sentry", "bugsnag", "posthog", "mixpanel",
    "amplitude.com", "segment.io", "segment.com", "api.segment",
    "datadoghq", "newrelic.com", "rollbar.com", "logrocket.com",
    "fullstory.com", "hotjar.com", "matomo.cloud", "plausible.io",
    "umami.is",
)


def _literal_hosts(root):
    """Every https?://host literal in a directory tree, with where it came
    from."""
    import re
    pat = re.compile(r"https?://([A-Za-z0-9._-]+(?::\d+)?)")
    found = {}
    for path in sorted(root.rglob("*.py")):
        parts = set(path.parts)
        if parts & {".venv", "build", "dist", "__pycache__", "data", "tests"}:
            continue
        for host in pat.findall(path.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(host.lower().rstrip("."), set()).add(path.name)
    return found


def test_every_reachable_host_is_disclosed():
    """A host the backend can reach but the Privacy screen does not name is,
    from the user's side, indistinguishable from telemetry. Adding one means
    adding a catalogue entry describing what it sends and how to stop it."""
    from pathlib import Path
    py = Path(__file__).resolve().parents[1]
    named = {h["host"] for h in terminal.HOSTS}

    undisclosed = {
        host: sorted(files)
        for host, files in _literal_hosts(py).items()
        if host not in named and host not in NOT_REQUESTED
    }
    assert not undisclosed, (
        "undisclosed outbound host(s). Either add a terminal.HOSTS entry "
        "saying what it sends and how to turn it off, or — if the app never "
        "actually requests it — add it to NOT_REQUESTED with a reason: "
        f"{undisclosed}")


def test_no_analytics_endpoint_anywhere():
    """No crash reporter, no analytics SDK, no product-metrics pipe — in the
    backend, the Electron main process, or the renderer."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    hits = []
    for sub in ("python", "src", "electron", "shared", "scripts"):
        for path in (root / sub).rglob("*"):
            if not path.is_file() or path.suffix not in {
                    ".py", ".ts", ".tsx", ".js", ".mjs", ".html", ".css"}:
                continue
            if set(path.parts) & {".venv", "node_modules", "build", "dist",
                                  "__pycache__", "data", "tests"}:
                continue
            low = path.read_text(encoding="utf-8", errors="replace").lower()
            for name in TRACKERS:
                if name in low:
                    hits.append(f"{path.name}: {name}")
    assert not hits, hits


def test_nothing_reports_home_on_a_timer():
    """The leaderboard fired from the scanner loop's scheduler. Nothing in the
    service should post to a host we control on a timer again."""
    from pathlib import Path
    svc = (Path(__file__).resolve().parents[1] / "service.py").read_text(
        encoding="utf-8", errors="replace")
    assert "leaderboard" not in svc.lower()
    for marker in ("stats_webhook_url", "enable_discord"):
        assert marker in svc, marker


def test_discord_rich_presence_stays_on_and_stays_dumb():
    """Rich Presence is deliberate marketing, not telemetry, and it must NOT be
    removed by a future privacy sweep — including one of mine. It is how the
    app gets found.

    Two properties matter. It stays unconditional: started at app-ready with no
    setting gating it. And it stays account-blind: the payload names the app,
    never the account. Adding balance/P&L/ticker to the presence would turn a
    marketing string into a broadcast of the user's book to their friends list.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    rpc = (root / "electron" / "system" / "discord.ts").read_text(
        encoding="utf-8", errors="replace")
    main = (root / "electron" / "main.ts").read_text(
        encoding="utf-8", errors="replace")

    assert "setActivity" in rpc, "rich presence was removed"
    assert "startDiscordRpc()" in main, "rich presence is no longer started"
    start_line = next(ln for ln in main.splitlines() if "startDiscordRpc()" in ln)
    assert "if" not in start_line, f"presence became conditional: {start_line}"

    low = rpc.lower()
    for leak in ("balance", "pnl", "p&l", "position", "ticker", "profit",
                 "portfolio", "getbalance"):
        assert leak not in low, f"rich presence would broadcast {leak!r}"


def test_the_perps_api_hosts_are_catalogued():
    named = {h["host"] for h in terminal.HOSTS}
    assert "external-api.kalshi.com" in named


def test_no_retired_demo_host_remains():
    """Kalshi's demo exchange is gone from the app: no demo host in the
    catalogue or anywhere in the backend's source."""
    named = {h["host"] for h in terminal.HOSTS}
    assert not any("demo" in h for h in named)
    for py in PY_DIR.glob("*.py"):
        assert "demo.kalshi.co" not in py.read_text(encoding="utf-8"), py.name
        assert "demo-api.kalshi.co" not in py.read_text(encoding="utf-8"), py.name


def test_every_ai_provider_host_is_disclosed_and_local_ones_say_so():
    """Each AI provider's hardcoded base is named in the catalogue, by the
    same host key the call counter uses, and the two that run on this machine
    say so — "the model runs locally" is the whole privacy argument for them,
    and a reader should not have to know what 127.0.0.1 means."""
    import ai_providers
    named = {h["host"]: h for h in terminal.HOSTS}
    for base in (ai_providers.ANTHROPIC_BASE, ai_providers.OPENAI_BASE,
                 ai_providers.OPENROUTER_BASE, ai_providers.GEMINI_BASE,
                 ai_providers.OLLAMA_BASE, ai_providers.LMSTUDIO_BASE):
        key = ai_providers.stat_host(base)
        assert key in named, key
        assert named[key]["required"] is False, key
    for base in (ai_providers.OLLAMA_BASE, ai_providers.LMSTUDIO_BASE):
        h = named[ai_providers.stat_host(base)]
        assert "on this machine" in h["purpose"], h["host"]
        assert "no key" in h["sends"].lower(), h["host"]
    for base in (ai_providers.OPENROUTER_BASE, ai_providers.GEMINI_BASE):
        assert "key" in named[ai_providers.stat_host(base)]["sends"].lower()


def test_ai_calls_are_counted_under_the_catalogued_host(monkeypatch):
    """The counter must key a local call by host:port, or both local servers
    land in one '127.0.0.1' row the catalogue does not name — which the panel
    would then show as an UNLISTED host."""
    import httpx

    import ai_providers
    kalshi_api.NET_STATS.clear()
    monkeypatch.setattr(ai_providers, "_TRANSPORT", httpx.MockTransport(
        lambda req: httpx.Response(200, json={"models": []})))
    ai_providers._LISTED.clear()
    ai_providers.list_models("ollama", fresh=True)
    monkeypatch.setattr(terminal.kalshi_ws, "stats", lambda: {})
    rep = terminal.network_report()
    assert rep["unlisted"] == []
    row = next(r for r in rep["hosts"] if r["host"] == "127.0.0.1:11434")
    assert row["calls"] == 1


def test_calls_are_counted_per_host():
    kalshi_api.NET_STATS.clear()
    kalshi_api.note_call("api.elections.kalshi.com", ok=True, ms=120.0)
    kalshi_api.note_call("api.elections.kalshi.com", ok=False, ms=90.0, error="HTTP 429")
    st = kalshi_api.net_stats()["api.elections.kalshi.com"]
    assert st["calls"] == 2 and st["errors"] == 1
    assert st["avgMs"] == 105.0
    assert st["lastError"] == "HTTP 429"


def test_a_host_with_no_calls_is_still_listed(monkeypatch):
    kalshi_api.NET_STATS.clear()
    monkeypatch.setattr(terminal.kalshi_ws, "stats", lambda: {})
    rep = terminal.network_report()
    assert len(rep["hosts"]) == len(terminal.HOSTS)
    assert all(r["calls"] is None for r in rep["hosts"])
    assert all(r["errors"] is None for r in rep["hosts"])
    assert rep["totalCalls"] == 0
    assert rep["unlisted"] == []


def test_an_uncatalogued_call_is_surfaced_rather_than_hidden(monkeypatch):
    kalshi_api.NET_STATS.clear()
    kalshi_api.note_call("tracker.example.com", ok=True, ms=10.0)
    monkeypatch.setattr(terminal.kalshi_ws, "stats", lambda: {})
    rep = terminal.network_report()
    assert [u["host"] for u in rep["unlisted"]] == ["tracker.example.com"]
    assert rep["totalCalls"] == 1


def test_host_parsing_handles_ports_and_paths():
    assert kalshi_api._host_of("https://api.example.com/a/b?c=1") == "api.example.com"
    assert kalshi_api._host_of("wss://ws.example.com:443/x") == "ws.example.com:443"
