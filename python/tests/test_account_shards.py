"""The account snapshot's per-exchange cash split.

`totalUsd` is what the ACCOUNT holds. It is not what any single order can
spend: Kalshi allocates collateral per exchange shard and never rebalances it
for retail, so an order fills only against the shard hosting its market and the
rejection does not say which shard it meant. The snapshot therefore carries the
split, and the top bar renders it beside the total.

The defect worth pinning is not the happy path. It is the UNKNOWN one:
`trader.cached_shard_balances` returns None when no balance read has succeeded
yet, and {} when the response carried no breakdown at all (a
subaccount-restricted key). Rendering either as "every exchange holds $0.00"
would put a confident zero in the chrome of every screen — and $0.00 on the
exchange you are about to trade is exactly the reading that makes a user go
move money they did not need to move.
"""
from __future__ import annotations

import asyncio

import pytest

import db
import kalshi_auth
import service
import trader


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def snapshot_env(tmp_path, monkeypatch):
    """An empty ledger in the paper scope, with the balance cache under our control."""
    dbfile = tmp_path / "shards-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    monkeypatch.setattr(trader, "_balance_cache", {}, raising=False)

    async def _noop(*a, **kw):
        return (0, 0)
    monkeypatch.setattr(trader, "refresh_balance", _noop)
    yield


def _authed(monkeypatch, shards):
    monkeypatch.setattr(service.STATE, "auth_ok", True, raising=False)
    monkeypatch.setattr(
        trader, "cached_shard_balances", lambda env=None: shards)


def test_unknown_split_is_null_not_all_zero(snapshot_env, monkeypatch):
    """None means we have not read it. It must NOT become a row of $0.00."""
    _authed(monkeypatch, None)
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] is None


def test_absent_breakdown_is_null_not_all_zero(snapshot_env, monkeypatch):
    """{} is what a subaccount-restricted key returns — also unknown, not
    empty. cached_shard_balances already collapses it to None; this pins that
    the snapshot does not resurrect it as a falsy-but-present dict."""
    _authed(monkeypatch, {})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] is None


def test_unauthenticated_reports_no_split(snapshot_env, monkeypatch):
    """Without verified credentials there is no account to split. A stale
    cache from a previous env must not leak into the snapshot."""
    monkeypatch.setattr(service.STATE, "auth_ok", False, raising=False)
    monkeypatch.setattr(
        trader, "cached_shard_balances", lambda env=None: {0: 500.0, 2: 25.0})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] is None


def test_known_split_carries_index_and_exchange_name(snapshot_env, monkeypatch):
    """Keyed by INDEX, because a transfer is addressed by index — mapping a
    display name back to one is a lookup that can fail. The name rides along
    so the UI never has to hardcode Kalshi's naming."""
    _authed(monkeypatch, {0: 1204.5, 2: 0.0})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] == {
        "0": {"name": "general", "cashUsd": 1204.5},
        "2": {"name": "crypto", "cashUsd": 0.0},
    }


def test_affirmative_zero_survives(snapshot_env, monkeypatch):
    """A shard we READ as empty is a fact, and the one the user most needs:
    it is why their crypto order was refused. Only an unread split is null."""
    _authed(monkeypatch, {0: 0.0, 2: 0.0})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] == {
        "0": {"name": "general", "cashUsd": 0.0},
        "2": {"name": "crypto", "cashUsd": 0.0},
    }


def test_transfer_url_is_sent_with_the_data(snapshot_env, monkeypatch):
    """Sent with the data rather than hardcoded in the renderer (which names
    no hosts). There is one Kalshi web host."""
    _authed(monkeypatch, {0: 10.0, 2: 10.0})
    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    prod = run(service._build_account_snapshot())["shardTransferUrl"]
    assert prod == "https://kalshi.com/account/exchange-indexes"


def test_balance_not_read_yet_is_unknown(snapshot_env, monkeypatch):
    _authed(monkeypatch, None)
    snap = run(service._build_account_snapshot())
    assert snap["balanceKnown"] is False


def test_unauthenticated_balance_is_unknown_even_with_a_cache(snapshot_env, monkeypatch):
    """A cached figure from before the key failed is not this key's balance."""
    monkeypatch.setattr(service.STATE, "auth_ok", False, raising=False)
    trader._balance_cache["paper"] = {"cents": 118, "portfolio_cents": 0, "at": 0}
    snap = run(service._build_account_snapshot())
    assert snap["balanceKnown"] is False


def test_a_read_balance_is_known_and_used(snapshot_env, monkeypatch):
    _authed(monkeypatch, None)
    trader._balance_cache["paper"] = {"cents": 118, "portfolio_cents": 0, "at": 0}
    snap = run(service._build_account_snapshot())
    assert snap["balanceKnown"] is True
    assert snap["cashUsd"] == pytest.approx(1.18)
