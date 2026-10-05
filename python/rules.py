from __future__ import annotations

from typing import Any

RULE_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def evaluate_rules(values: dict, rules: list) -> tuple[bool, str]:
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
