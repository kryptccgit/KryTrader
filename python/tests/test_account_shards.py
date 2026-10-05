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
    dbfile = tmp_path / "shards-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(kalshi_auth, "_current_env", "demo", raising=False)
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
    _authed(monkeypatch, None)
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] is None


def test_absent_breakdown_is_null_not_all_zero(snapshot_env, monkeypatch):
    _authed(monkeypatch, {})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] is None


def test_unauthenticated_reports_no_split(snapshot_env, monkeypatch):
    monkeypatch.setattr(service.STATE, "auth_ok", False, raising=False)
    monkeypatch.setattr(
        trader, "cached_shard_balances", lambda env=None: {0: 500.0, 2: 25.0})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] is None


def test_known_split_carries_index_and_exchange_name(snapshot_env, monkeypatch):
    _authed(monkeypatch, {0: 1204.5, 2: 0.0})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] == {
        "0": {"name": "general", "cashUsd": 1204.5},
        "2": {"name": "crypto", "cashUsd": 0.0},
    }


def test_affirmative_zero_survives(snapshot_env, monkeypatch):
    _authed(monkeypatch, {0: 0.0, 2: 0.0})
    snap = run(service._build_account_snapshot())
    assert snap["shardCash"] == {
        "0": {"name": "general", "cashUsd": 0.0},
        "2": {"name": "crypto", "cashUsd": 0.0},
    }


def test_transfer_url_follows_the_active_environment(snapshot_env, monkeypatch):
    _authed(monkeypatch, {0: 10.0, 2: 10.0})

    monkeypatch.setattr(kalshi_auth, "_current_env", "demo", raising=False)
    demo = run(service._build_account_snapshot())["shardTransferUrl"]

    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    prod = run(service._build_account_snapshot())["shardTransferUrl"]

    assert demo != prod
    assert "kalshi.com" in prod
    assert demo.startswith("https://")
