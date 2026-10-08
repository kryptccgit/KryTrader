"""Sandboxed compile/exec for user strategy scripts.

A user script is ordinary Python that defines `decide(ctx)` (plus optional
`on_start(state)` / `on_fill(position, state)` / `on_settle(position, state)`
hooks). In the default sandboxed mode the script is validated at the AST
level BEFORE it is compiled: no imports, no dunder access, no classes, and
every free name must resolve to something the sandbox injects (curated
builtins, `math`, `statistics`, `state`, `log`, `ctx`). Execution is wrapped
in a line-count + wall-clock budget (sys.settrace) so a busy-loop script is
killed deterministically instead of wedging the engine loop.

HONESTY: this is a guardrail against accidental damage and naive-malicious
scripts, not a hard security boundary — CPython sandboxes are escapable by a
determined attacker. Trusted mode ("full Python") skips the AST validation
entirely and runs with the same privileges as the trading engine, in the
process that holds the decrypted Kalshi API key. The UI says exactly that before
letting a user flip a script to trusted.
"""
from __future__ import annotations

import ast
import builtins as _builtins
import hashlib
import math
import statistics
import sys
import time
from typing import Any, Callable, Optional

MAX_CODE_BYTES = 128 * 1024
HOOK_NAMES = ("decide", "manage", "decide_signal", "supervise",
              "on_start", "on_fill", "on_settle")
ENTRY_HOOKS = ("decide", "manage", "decide_signal", "supervise")

MAX_TRACE_EVENTS = 200_000


class ScriptError(Exception):
    """A script failed validation, compilation, or raised at runtime."""


class ScriptBudgetExceeded(ScriptError):
    """A hook call exceeded its CPU/time budget (busy loop guard)."""



SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
    "round": round, "sorted": sorted, "reversed": reversed,
    "enumerate": enumerate, "range": range, "zip": zip, "map": map,
    "filter": filter, "any": any, "all": all,
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "dict": dict, "set": set, "tuple": tuple,
    "divmod": divmod, "pow": pow, "isinstance": isinstance,
    "repr": repr, "print": None,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError,
    "ZeroDivisionError": ZeroDivisionError, "StopIteration": StopIteration,
    "ArithmeticError": ArithmeticError, "RuntimeError": RuntimeError,
    "True": True, "False": False, "None": None,
}

INJECTED_GLOBALS = ("math", "statistics", "state", "log", "ctx")

_FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "input", "getattr", "setattr",
    "delattr", "vars", "globals", "locals", "type", "super", "breakpoint",
    "object", "memoryview", "bytearray", "bytes", "__import__", "help",
    "exit", "quit", "dir", "id", "hash", "iter", "next", "callable",
    "classmethod", "staticmethod", "property", "frozenset", "format",
}

_FORBIDDEN_ATTRS = {
    "f_back", "f_globals", "f_locals", "f_builtins", "f_code", "f_trace",
    "f_lineno", "f_lasti", "f_valuestack", "f_restricted",
    "gi_frame", "gi_code", "gi_yieldfrom", "gi_running", "gi_suspended",
    "cr_frame", "cr_code", "cr_await", "cr_running", "cr_origin", "cr_suspended",
    "ag_frame", "ag_code", "ag_await", "ag_running",
    "tb_frame", "tb_next", "tb_lasti", "tb_lineno",
    "func_globals", "func_code", "func_dict", "func_closure",
    "func_defaults", "func_builtins", "mro",
    "format", "format_map",
}




def parse_header(code: str) -> dict:
    """Read the `# krypt-script v1` metadata header from the top comment
    block: name / description lines. Missing header is not fatal (the save
    path fills defaults) but the AI import flow requires it."""
    meta = {"version": None, "name": "", "description": ""}
    for line in code.splitlines()[:15]:
        s = line.strip()
        if not s.startswith("#"):
            if s:
                break
            continue
        body = s.lstrip("#").strip()
        low = body.lower()
        if low.startswith("krypt-script"):
            meta["version"] = body.split()[-1] if len(body.split()) > 1 else "v1"
        elif low.startswith("name:"):
            meta["name"] = body[5:].strip()
        elif low.startswith("description:"):
            meta["description"] = body[12:].strip()
    return meta


def find_ctx_fields(code: str) -> list[str]:
    """Static scan of the ctx fields a script reads (`ctx["x"]` and
    `ctx.get("x")`), so validation can warn when a field isn't recorded in
    ticks (it would be None in backtest — fail-closed, same as rules)."""
    fields: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name) and node.value.id == "ctx"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            fields.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ctx"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            fields.add(node.args[0].value)
    return sorted(fields)




def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the script itself binds anywhere (coarse module-wide scope:
    good enough to decide whether a loaded name is the script's own)."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            args = node.args
            for a in (args.args + args.posonlyargs + args.kwonlyargs):
                bound.add(a.arg)
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            args = node.args
            for a in (args.args + args.posonlyargs + args.kwonlyargs):
                bound.add(a.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            for t in ast.walk(node.target):
                if isinstance(t, ast.Name):
                    bound.add(t.id)
    return bound


def validate_sandboxed(code: str) -> list[str]:
    """AST whitelist validation for sandboxed scripts. Returns a list of
    human-readable errors (empty = valid). Whitelist-first: unknown free
    names are rejected here, at save time, not at 3am mid-trade."""
    errors: list[str] = []
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return [f"script exceeds {MAX_CODE_BYTES // 1024}KB"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error line {e.lineno}: {e.msg}"]

    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            errors.append(
                f"line {line}: imports are not allowed in sandboxed scripts "
                "(math and statistics are already available; flip the script "
                "to Trusted for full Python)"
            )
        elif isinstance(node, ast.ClassDef):
            errors.append(f"line {line}: classes are not supported — use dicts and functions")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            errors.append(f"line {line}: global/nonlocal is not allowed — use the `state` dict")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            errors.append(f"line {line}: async syntax is not supported")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                errors.append(f"line {line}: dunder name '{node.id}' is not allowed")
            elif node.id in _FORBIDDEN_CALLS:
                errors.append(f"line {line}: '{node.id}' is not available in sandboxed scripts")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                errors.append(
                    f"line {line}: underscore attribute '.{node.attr}' is not allowed"
                )
            elif node.attr in _FORBIDDEN_ATTRS:
                errors.append(
                    f"line {line}: attribute '.{node.attr}' is not allowed in "
                    "sandboxed scripts (use f-strings instead of .format; frame/"
                    "generator introspection is blocked)"
                )
        elif isinstance(node, ast.arg):
            if node.arg.startswith("__"):
                errors.append(f"line {line}: dunder argument '{node.arg}' is not allowed")
        elif isinstance(node, ast.keyword):
            if node.arg and node.arg.startswith("__"):
                errors.append(f"line {line}: dunder keyword '{node.arg}' is not allowed")

    if not errors:
        allowed = set(SAFE_BUILTINS) | set(INJECTED_GLOBALS)
        bound = _bound_names(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                    and node.id not in allowed and node.id not in bound):
                errors.append(
                    f"line {getattr(node, 'lineno', '?')}: unknown name "
                    f"'{node.id}' (not a sandbox builtin and never assigned)"
                )

    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if not defined & set(ENTRY_HOOKS):
        errors.append(
            "script must define at least one of: decide(ctx), "
            "manage(position, ctx), decide_signal(signal), supervise(app)"
        )
    return errors


def validate(code: str, *, trusted: bool = False) -> list[str]:
    """Full validation for a script in its declared mode. Trusted scripts get
    syntax + contract checks only (they are full Python by design)."""
    if not trusted:
        return validate_sandboxed(code)
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return [f"script exceeds {MAX_CODE_BYTES // 1024}KB"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error line {e.lineno}: {e.msg}"]
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if not defined & set(ENTRY_HOOKS):
        return ["script must define at least one of: decide(ctx), "
                "manage(position, ctx), decide_signal(signal), supervise(app)"]
    return []




def _make_tracer(deadline: float, max_events: int):
    count = 0

    def tracer(frame, event, arg):
        nonlocal count
        count += 1
        if count > max_events:
            raise ScriptBudgetExceeded(
                f"script exceeded its per-call CPU budget ({max_events} steps)"
            )
        if count % 64 == 0 and time.perf_counter() > deadline:
            raise ScriptBudgetExceeded("script exceeded its per-call time budget")
        return tracer

    return tracer


def call_budgeted(fn: Callable, *args: Any, budget_ms: float = 50.0,
                  traced: bool = True) -> Any:
    """Call a script hook under the line/time budget. `traced=False` (trusted
    mode) runs the hook bare — the caller is responsible for coarser
    containment (thread timeouts live, wall caps in backtest)."""
    if not traced:
        return fn(*args)
    deadline = time.perf_counter() + budget_ms / 1000.0
    tracer = _make_tracer(deadline, MAX_TRACE_EVENTS)
    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        return fn(*args)
    finally:
        sys.settrace(old)




def code_hash(code: str, trusted: bool) -> str:
    h = hashlib.sha256()
    h.update(b"trusted:" if trusted else b"sandboxed:")
    h.update(code.encode("utf-8", "replace"))
    return h.hexdigest()


class CompiledScript:
    """A compiled script module: its hooks, persistent state dict, and log
    sink. One instance per (script, code-hash, trusted-flag)."""

    def __init__(self, script_id: str, code: str, *, trusted: bool,
                 log_sink: Optional[Callable[[str], None]] = None,
                 state: Optional[dict] = None):
        self.script_id = script_id
        self.trusted = bool(trusted)
        self.hash = code_hash(code, trusted)
        self.state: dict = state if isinstance(state, dict) else {}
        self._log_lines: list[str] = []
        self._log_sink = log_sink
        self._log_count = 0

        errors = validate(code, trusted=trusted)
        if errors:
            raise ScriptError("; ".join(errors[:5]))

        def _log(*parts: Any) -> None:
            self._log_count += 1
            if self._log_count > 2000:
                return
            msg = " ".join(str(p) for p in parts)[:400]
            self._log_lines.append(msg)
            if len(self._log_lines) > 200:
                del self._log_lines[:100]
            if self._log_sink:
                try:
                    self._log_sink(msg)
                except Exception:
                    pass

        if trusted:
            g: dict[str, Any] = {"__builtins__": _builtins.__dict__}
        else:
            builtins = dict(SAFE_BUILTINS)
            builtins["print"] = _log
            g = {"__builtins__": builtins}
        g.update({
            "math": math, "statistics": statistics,
            "state": self.state, "log": _log,
        })
        self.globals = g

        code_obj = compile(code, f"<script:{script_id[:8]}>", "exec")
        call_budgeted(
            eval, code_obj, g, budget_ms=100.0, traced=not trusted,
        )
        self.hooks: dict[str, Callable] = {}
        for name in HOOK_NAMES:
            fn = g.get(name)
            if callable(fn):
                self.hooks[name] = fn
        if not set(self.hooks) & set(ENTRY_HOOKS):
            raise ScriptError(
                "script must define at least one of: decide, manage, "
                "decide_signal, supervise")

    def drain_logs(self) -> list[str]:
        out = self._log_lines[:]
        self._log_lines.clear()
        return out

    def call(self, hook: str, *args: Any, budget_ms: float = 50.0) -> Any:
        """Invoke a hook under budget. Raises ScriptError subclasses on any
        failure — callers isolate (disable the script), never crash."""
        fn = self.hooks.get(hook)
        if fn is None:
            return None
        try:
            return call_budgeted(fn, *args, budget_ms=budget_ms,
                                 traced=not self.trusted)
        except ScriptBudgetExceeded:
            raise
        except Exception as e:
            raise ScriptError(f"{hook}() raised {type(e).__name__}: {e}") from e
