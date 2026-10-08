"""Shared entry-rule engine used by every trading module (the main bot and
the 15-minute crypto module both compose user-defined entry rules over their
own signal fields).

A rule-set is a list of {field, op, value} conditions ANDed together. The
caller builds a plain `values` dict (field-name -> number) from whatever signal
it has; this module is agnostic about which fields exist. Keeping it here means
the crypto module and the main bot can never drift in how a rule is evaluated.
"""
from __future__ import annotations

from typing import Any

RULE_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def evaluate_rules(values: dict, rules: list) -> tuple[bool, str]:
    """Evaluate a user-composed entry rule-set against a values dict. Each
    condition is {field, op, value}; field names a key in `values`. ALL
    conditions must hold (AND). Returns (enter?, reason).

    An empty rule-set never enters (a strategy with no conditions shouldn't
    fire blindly). A field missing from `values` rejects rather than trading
    on absent data. A malformed condition is skipped, not fatal."""
    if not rules:
        return False, "no entry rules set"
    for c in rules:
        if not isinstance(c, dict):
            continue
        field = c.get("field")
        fn = RULE_OPS.get(c.get("op"))
        if not field or fn is None:
            continue
        av = values.get(field)
        if av is None:
            return False, f"{field} unavailable"
        try:
            av_f, v_f = float(av), float(c.get("value"))
        except (TypeError, ValueError):
            return False, f"{field} not numeric"
        if not fn(av_f, v_f):
            return False, f"{field} {av_f:.3g} not {c.get('op')} {v_f:g}"
    return True, "rules pass"


def sanitize_rules(raw: Any, allowed_fields, *, limit: int = 30) -> list[dict[str, Any]]:
    """Coerce a user-supplied rule list into clean {field, op, value} dicts:
    drop non-dicts, unknown fields, bad ops, and non-numeric values; cap the
    count. Used by config validation so the running engine always sees a sane
    rule-set regardless of what the renderer or an imported profile sent."""
    clean: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return clean
    allowed = set(allowed_fields)
    for c in raw[:limit]:
        if not isinstance(c, dict):
            continue
        f = str(c.get("field") or "")
        op = str(c.get("op") or "")
        if f not in allowed or op not in RULE_OPS:
            continue
        try:
            v = float(c.get("value"))
        except (TypeError, ValueError):
            continue
        clean.append({"field": f, "op": op, "value": v})
    return clean
