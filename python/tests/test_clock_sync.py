from __future__ import annotations

import threading
import time

import kalshi_auth


def test_now_ms_does_not_block_on_periodic_resync(monkeypatch):
    monkeypatch.setattr(kalshi_auth, "_last_sync", 0.0)
    monkeypatch.setattr(kalshi_auth, "_sync_in_progress", False)
    monkeypatch.setattr(kalshi_auth, "_server_offset_ms", 0)

    gate = threading.Event()
    calls = {"n": 0}

    def slow_sync(force=False):
        calls["n"] += 1
        gate.wait(2.0)
        return 0

    monkeypatch.setattr(kalshi_auth, "sync_server_time", slow_sync)

    t0 = time.perf_counter()
    val = kalshi_auth.now_ms()
    elapsed = time.perf_counter() - t0

    assert isinstance(val, int)
    assert elapsed < 0.5, f"now_ms blocked for {elapsed:.2f}s on the resync"

    kalshi_auth.now_ms()

    gate.set()
    for _ in range(200):
        with kalshi_auth._sync_lock:
            done = not kalshi_auth._sync_in_progress
        if done:
            break
        time.sleep(0.01)

    assert calls["n"] == 1
    assert kalshi_auth._sync_in_progress is False


def test_now_ms_skips_resync_within_interval(monkeypatch):
    monkeypatch.setattr(kalshi_auth, "_last_sync", time.time())
    monkeypatch.setattr(kalshi_auth, "_sync_in_progress", False)
    monkeypatch.setattr(kalshi_auth, "_server_offset_ms", 1234)

    calls = {"n": 0}
    monkeypatch.setattr(
        kalshi_auth, "sync_server_time",
        lambda force=False: calls.__setitem__("n", calls["n"] + 1),
    )

    val = kalshi_auth.now_ms()
    assert isinstance(val, int)
    assert calls["n"] == 0
