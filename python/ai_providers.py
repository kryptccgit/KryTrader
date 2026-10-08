"""The AI providers beyond the two SDK paths: OpenRouter, Gemini, Ollama, LM Studio.

Why this is not one "OpenAI-compatible" client pointed at four base URLs:
the reasons ai_analyst keeps Anthropic and OpenAI apart apply here too, and
two of these providers would be quietly wrong through a shim.

  * **Gemini** speaks its own REST API. Google does offer an OpenAI-compatible
    endpoint, and it was the shorter path, but it is the wrong one for this
    app on the two things that make an error actionable or an analysis
    honest. A bad Gemini key comes back as HTTP **400** with
    `reason: API_KEY_INVALID`, not 401 -- a status-code mapper reads that as
    "bad request" and the user goes hunting for a bug instead of a typo. And
    web search (Google Search grounding) returns its sources as
    `groundingMetadata`, which the compatibility layer does not carry, so the
    panel would show a searched answer with no citations. Natively we also get
    `supportedGenerationMethods` in the free model listing, and the key goes
    in the `x-goog-api-key` header, never in a URL query string that could end
    up in a logged request line.
  * **Ollama** is called on its native `/api/chat`, not its `/v1` shim,
    because only the native API takes `options.num_ctx`. Ollama's default
    context is a few thousand tokens and it truncates silently from the FRONT
    of the conversation when a prompt overflows -- which drops the system
    prompt, the one telling the model that "--" is absent, not zero
    (invariant 8). We set the window explicitly and refuse a prompt that
    would not fit rather than let it be cut.
  * **OpenRouter and LM Studio** really are Chat Completions servers, so they
    share one transport. They still differ in auth, web search, cost
    reporting and in what each failure means, which is what the capability
    table and the error table below are for.

Rules this module holds:

  * No URLs or hosts from callers (invariant 3). Every base URL is a
    constant here. Callers name a provider id and a model id; a model id is
    shape-checked before it travels, and Gemini's -- which lands in the URL
    PATH -- may not contain a slash at all.
  * Local means local: the two local providers are reached on 127.0.0.1
    (not "localhost", which on Windows can resolve to ::1 first while Ollama
    listens on IPv4 only, so a running server reads as "not running"), with
    the environment's proxy settings ignored so a corporate proxy cannot
    swallow a loopback call.
  * Redirects are never followed. httpx strips `Authorization` on a
    cross-origin redirect but knows nothing about `x-goog-api-key`, so a
    followed redirect could carry a Gemini key to whatever host it named.
  * Model listings and key checks use free endpoints only. Nothing here makes
    a billed call to answer "is my key right?".
  * No attribution headers. OpenRouter invites `HTTP-Referer` / `X-Title` so
    apps appear in its public usage rankings; that is this app reporting its
    usage to a third party, which invariant 4 rules out.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

import httpx

if TYPE_CHECKING:
    import httpx2

logger = logging.getLogger("ai_providers")


class AiError(Exception):
    """Carries a message already written for a user, not a stack trace."""



ANTHROPIC_BASE = "https://api.anthropic.com"
OPENAI_BASE = "https://api.openai.com"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com"
OLLAMA_BASE = "http://127.0.0.1:11434"
LMSTUDIO_BASE = "http://127.0.0.1:1234"

_TRANSPORT: Optional[httpx.BaseTransport] = None



@dataclass(frozen=True)
class Caps:
    label: str
    local: bool
    needs_key: bool
    web_search: bool
    web_search_how: str
    tools: str
    tools_how: str
    tokens: str
    pricing: str
    catalogue: str
    models_endpoint: str


CAPS: dict[str, Caps] = {
    "anthropic": Caps(
        label="Anthropic", local=False, needs_key=True,
        web_search=True, web_search_how="Anthropic's server-side web_search tool",
        tools="all", tools_how="every curated Claude model calls tools",
        tokens="reported by Anthropic", pricing="published", catalogue="curated",
        models_endpoint="GET api.anthropic.com/v1/models (free)"),
    "openai": Caps(
        label="OpenAI", local=False, needs_key=True,
        web_search=True, web_search_how="the Responses API web_search tool",
        tools="all", tools_how="every curated GPT model calls tools",
        tokens="reported by OpenAI", pricing="none", catalogue="curated",
        models_endpoint="GET api.openai.com/v1/models (free)"),
    "openrouter": Caps(
        label="OpenRouter", local=False, needs_key=True,
        web_search=True,
        web_search_how="OpenRouter's documented `web` plugin; citations come back "
                       "as url_citation annotations. Billed by OpenRouter per search.",
        tools="per-model",
        tools_how="the model listing's supported_parameters must include \"tools\"",
        tokens="reported by OpenRouter", pricing="provider", catalogue="listed",
        models_endpoint="GET openrouter.ai/api/v1/models (public) + /key (free)"),
    "gemini": Caps(
        label="Google Gemini", local=False, needs_key=True,
        web_search=True, web_search_how="Google Search grounding (the google_search tool)",
        tools="per-model",
        tools_how="Gemini-family text models call functions; Gemma, embedding, "
                  "image, TTS and live-audio models do not (by model family)",
        tokens="reported by Google", pricing="none", catalogue="listed",
        models_endpoint="GET generativelanguage.googleapis.com/v1beta/models (free)"),
    "ollama": Caps(
        label="Ollama", local=True, needs_key=False,
        web_search=False, web_search_how="none: a local model has no search",
        tools="per-model",
        tools_how="/api/show must list \"tools\" in the model's capabilities",
        tokens="counted by Ollama on this machine (prompt_eval_count / eval_count)",
        pricing="free", catalogue="listed",
        models_endpoint="GET 127.0.0.1:11434/api/tags (installed models)"),
    "lmstudio": Caps(
        label="LM Studio", local=True, needs_key=False,
        web_search=False, web_search_how="none: a local model has no search",
        tools="per-model",
        tools_how="any chat model (LM Studio wraps models without native tool "
                  "support in its own tool format); embedding models cannot",
        tokens="counted by LM Studio on this machine (usage block)",
        pricing="free", catalogue="listed",
        models_endpoint="GET 127.0.0.1:1234/api/v0/models (downloaded models)"),
}

HTTP_PROVIDERS = ("openrouter", "gemini", "ollama", "lmstudio")



def _cloud_errors(label: str, settings_fix: str) -> dict[str, str]:
    return {
        "no_key": f"Set your {label} API key in Settings to use {label}.",
        "auth": f"{label} rejected the key. Check it in {settings_fix}.",
        "permission": f"That {label} key is valid but not allowed to use {{model}}.",
        "quota": f"{label} says this key is out of quota. {{detail}}",
        "rate": f"{label} rate-limited this key. Wait a moment and try again.",
        "model": f"{label} has no model called {{model}}. Pick another in Settings "
                 f"(Test connection lists the ones your key can use).",
        "down": f"Could not reach {label}. Check the connection and try again.",
        "timeout": f"{label} did not answer in time. Try again, or turn web search off.",
        "server": f"{label} had a server error ({{status}}). Try again shortly.",
        "refused": f"{label}'s model declined to answer this one.",
        "no_tools": f"{{model}} on {label} cannot call tools, and Autopilot works "
                    f"only through tools. Pick a tool-capable model in Settings.",
        "bad_response": f"{label} sent back something that isn't a model reply.",
        "other": f"{label} returned {{status}}: {{detail}}",
    }


ERRORS: dict[str, dict[str, str]] = {
    "anthropic": {
        **_cloud_errors("Anthropic", "Settings"),
        "auth": "That Anthropic API key was rejected. Check it in Settings.",
    },
    "openai": {
        **_cloud_errors("OpenAI", "Settings"),
        "auth": "That OpenAI API key was rejected. Check it in Settings.",
    },
    "openrouter": {
        **_cloud_errors("OpenRouter", "Settings"),
        "auth": "OpenRouter rejected the key. Check it in Settings, or make a "
                "new one at openrouter.ai/keys.",
        "quota": "Your OpenRouter account is out of credits (or this key hit its "
                 "credit limit). Add credits at openrouter.ai, or pick a model "
                 "ending in :free.",
        "permission": "OpenRouter's moderation refused this request: {detail}",
    },
    "gemini": {
        **_cloud_errors("Google Gemini", "Settings"),
        "auth": "Google rejected that Gemini API key. Check it in Settings, or "
                "make a new one at aistudio.google.com/apikey.",
        "model": "Google Gemini won't serve {model} to this key. {detail} "
                 "New Gemini keys can't use the 2.5 models; pick a current one "
                 "(gemini-3.8-flash) in Settings.",
        "permission": "That Gemini key can't use {model}: the Generative "
                      "Language API may not be enabled for its Google Cloud "
                      "project. {detail}",
        "quota": "Gemini quota is used up for this key (free-tier limits are per "
                 "minute and per day). Wait, or enable billing on the key's project.",
        "rate": "Gemini quota is used up for this key (free-tier limits are per "
                "minute and per day). Wait, or enable billing on the key's project.",
        "region": "Google says the Gemini API isn't available for this key's "
                  "location: {detail}",
    },
    "ollama": {
        "no_key": "",
        "down": "Ollama isn't running: start it with `ollama serve` (or open the "
                "Ollama app), then try again.",
        "model": "{model} isn't pulled in Ollama: run `ollama pull {model}`.",
        "no_tools": "{model} can't call tools in Ollama, and Autopilot works only "
                    "through tools. Pick a model that can (llama3.1, qwen3, "
                    "mistral-nemo...) and `ollama pull` it.",
        "tools_unknown": "Ollama didn't say whether {model} can call tools (it "
                         "reports capabilities from v0.6 on). Update Ollama, then "
                         "try again.",
        "timeout": "Ollama didn't finish in time. A large model on CPU can be "
                   "slower than that; try a smaller one.",
        "memory": "Ollama couldn't load {model}: {detail}",
        "context": "This prompt (~{detail} tokens) is too big for the context "
                   "window Krypt asks Ollama for. Nothing was sent.",
        "refused": "The model declined to answer this one.",
        "server": "Ollama had an error ({status}): {detail}",
        "bad_response": "Ollama sent back something that isn't a model reply.",
        "other": "Ollama returned {status}: {detail}",
        "auth": "Ollama refused the request ({status}): {detail}",
        "permission": "Ollama refused the request ({status}): {detail}",
        "quota": "Ollama refused the request ({status}): {detail}",
        "rate": "Ollama is busy. Try again in a moment.",
    },
    "lmstudio": {
        "no_key": "",
        "down": "LM Studio's local server isn't running: in LM Studio open the "
                "Developer tab and start the server (or run `lms server start`).",
        "model": "LM Studio has no model called {model}. Download or load it in "
                 "LM Studio (or `lms get {model}`), then pick it in Settings.",
        "no_models": "LM Studio is running but has no chat model downloaded. "
                     "Get one in LM Studio's Discover tab (or `lms get qwen2.5-7b-instruct`).",
        "no_tools": "{model} is an embedding model; it can't chat or call tools. "
                    "Pick a chat model in Settings.",
        "timeout": "LM Studio didn't finish in time. A large model on CPU can be "
                   "slower than that; try a smaller one.",
        "context": "{detail} Reload the model in LM Studio with a larger context "
                   "length, or pick a model that has one.",
        "refused": "The model declined to answer this one.",
        "server": "LM Studio had an error ({status}): {detail}",
        "bad_response": "LM Studio sent back something that isn't a model reply.",
        "other": "LM Studio returned {status}: {detail}",
        "auth": "LM Studio refused the request ({status}): {detail}",
        "permission": "LM Studio refused the request ({status}): {detail}",
        "quota": "LM Studio refused the request ({status}): {detail}",
        "rate": "LM Studio is busy. Try again in a moment.",
        "memory": "LM Studio couldn't load {model}: {detail}",
    },
}


def error(provider: str, kind: str, model: Optional[str] = None,
          detail: str = "", status: Any = "") -> AiError:
    table = ERRORS.get(provider) or ERRORS["openrouter"]
    tmpl = table.get(kind) or table.get("other") or "{detail}"
    msg = tmpl.format(model=model or "that model", detail=detail or "", status=status)
    return AiError(re.sub(r" {2,}", " ", msg).strip())


def _first_line(s: str) -> str:
    s = (s or "").strip()
    return s.splitlines()[0][:200] if s else ""


def _detail(data: Any, text: str) -> str:
    """The human part of an error body, whichever way this provider spells it:
    {"error": {"message"}} (OpenAI-style, Gemini), {"error": "..."} (Ollama),
    or a one-element list of either (Google's compatibility layer)."""
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error")
        msg = None
        if isinstance(err, dict):
            msg = err.get("message") or err.get("status")
        elif isinstance(err, str):
            msg = err
        else:
            msg = data.get("message")
        if msg:
            return _first_line(str(msg))
    return _first_line(text or "")


def _gemini_reasons(data: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(data, list) and data:
        data = data[0]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        if err.get("status"):
            out.add(str(err["status"]))
        for d in err.get("details") or []:
            if isinstance(d, dict) and d.get("reason"):
                out.add(str(d["reason"]))
    return out


def classify(provider: str, status: int, data: Any, detail: str) -> str:
    """HTTP failure -> an error kind from the table. Per provider, because
    the same status means different things on different services."""
    low = (detail or "").lower()
    if provider == "gemini":
        reasons = _gemini_reasons(data)
        if "API_KEY_INVALID" in reasons or "api key not valid" in low or "api key expired" in low:
            return "auth"
        if status == 400 and "location" in low:
            return "region"
    if provider == "ollama":
        if "does not support tools" in low:
            return "no_tools"
        if status == 404 or ("not found" in low and "pull" in low):
            return "model"
        if "memory" in low:
            return "memory"
    if provider == "lmstudio":
        if "context" in low and ("length" in low or "overflow" in low or "exceed" in low):
            return "context"
        if status == 404 or ("model" in low and ("not found" in low or "no models loaded" in low
                                                 or "does not exist" in low)):
            return "model"
        if "failed to load" in low or "memory" in low:
            return "memory"
    if provider == "openrouter":
        if status == 400 and "not a valid model" in low:
            return "model"
    if status == 401:
        return "auth"
    if status == 402:
        return "quota"
    if status == 403:
        return "permission"
    if status == 404:
        return "model"
    if status == 429:
        return "rate"
    if status in (408, 504, 524):
        return "timeout"
    if status >= 500:
        return "server"
    return "other"



def stat_host(url: Any) -> str:
    """The Privacy panel's key for a URL: the host, plus the port when it is
    not the scheme's default. Both local servers are 127.0.0.1, and "Ollama
    on :11434" and "LM Studio on :1234" are different disclosures."""
    u = httpx.URL(str(url))
    return f"{u.host}:{u.port}" if u.port else (u.host or "")


def _note(url: Any, ok: bool, ms: float, err: str = "") -> None:
    try:
        import kalshi_api
        kalshi_api.note_call(stat_host(url), ok=ok, ms=ms, error=err)
    except Exception:
        pass


def _count_hooks() -> dict:
    """Sync twin of kalshi_api.counting_hooks(): every AI request shows up in
    the Privacy panel's per-host counts, including the SDK calls (see
    counted_client), so the AI rows are a real count rather than a partial
    one."""
    def _on_request(request) -> None:
        request.extensions["_krypt_t0"] = time.monotonic()

    def _on_response(response) -> None:
        t0 = response.request.extensions.get("_krypt_t0")
        ok = response.status_code < 400
        _note(response.request.url, ok, (time.monotonic() - t0) * 1000 if t0 else 0.0,
              "" if ok else f"HTTP {response.status_code}")

    return {"request": [_on_request], "response": [_on_response]}


def counted_client(timeout: float, *, transport: Any = None) -> "httpx2.Client":
    """The HTTP client handed to the Anthropic and OpenAI SDKs, so their
    calls are counted per host like everything else.

    An `httpx2.Client`, not an `httpx.Client`: anthropic 1.x is built on
    httpx2 and isinstance-checks the client it is handed, so the plain httpx
    client this used to return made EVERY Anthropic call -- the default
    provider, the Analyse button and every Autopilot run -- die with a
    TypeError before a request was sent. openai 3.x takes either; httpx2 is
    the one both accept. The fake SDKs in the tests accepted anything, which
    is how it shipped; tests/test_ai_sdk_clients.py and `service.py
    --selftest` now build the REAL clients with this.

    Redirects stay off, as everywhere in this module: the SDKs' own default
    client follows them, and an `x-api-key` header is not one an HTTP client
    knows to strip on a cross-origin hop.

    The caller owns the client and closes it after the call; the SDK's
    `close()` closes it too. `transport` is for tests and the selftest only.
    """
    import httpx2
    kw: dict = {"timeout": timeout, "event_hooks": _count_hooks(),
                "follow_redirects": False}
    if transport is not None:
        kw["transport"] = transport
    return httpx2.Client(**kw)


def sdk_selfcheck() -> list[str]:
    """Build the REAL Anthropic and OpenAI clients on counted_client and send
    one request each through a mock transport. Returns failures, [] when fine.

    Offline by construction. Shared by the pytest and `service.py --selftest`
    so a frozen build whose SDK rejects our client type -- or whose bundle
    lost a module the request path imports lazily (httpx2's transport pulls
    in httpcore2 and truststore at construction) -- fails at build time
    rather than on the user's first Analyse click."""
    import httpx2
    failures: list[str] = []
    seen: list[str] = []

    def _handler(request):
        seen.append(str(request.url.host))
        if request.url.path.endswith("/messages"):
            return httpx2.Response(200, json={
                "id": "msg_selftest", "type": "message", "role": "assistant",
                "model": "selftest", "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1}})
        return httpx2.Response(200, json={
            "id": "resp_selftest", "object": "response", "created_at": 0,
            "model": "selftest", "status": "completed", "output": [],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": []})

    counted: list[str] = []
    real_note = globals()["_note"]

    def _spy(url, ok, ms, err=""):
        counted.append(stat_host(url))

    globals()["_note"] = _spy
    try:
        for sdk_name in ("anthropic", "openai"):
            try:
                sdk = __import__(sdk_name)
                cls = sdk.Anthropic if sdk_name == "anthropic" else sdk.OpenAI
                http = counted_client(5.0)
                try:
                    cls(api_key="selftest", max_retries=0, http_client=http)
                finally:
                    http.close()
            except Exception as e:
                failures.append(f"{sdk_name} client on counted_client: "
                                f"{type(e).__name__}: {e}")
        try:
            import anthropic
            with anthropic.Anthropic(
                    api_key="selftest", max_retries=0,
                    http_client=counted_client(5.0, transport=httpx2.MockTransport(_handler))) as c:
                c.messages.create(model="selftest", max_tokens=1,
                                  messages=[{"role": "user", "content": "x"}])
        except Exception as e:
            failures.append(f"anthropic mocked call: {type(e).__name__}: {e}")
        try:
            import openai
            with openai.OpenAI(
                    api_key="selftest", max_retries=0,
                    http_client=counted_client(5.0, transport=httpx2.MockTransport(_handler))) as c:
                c.responses.create(model="selftest", input="x")
        except Exception as e:
            failures.append(f"openai mocked call: {type(e).__name__}: {e}")
    finally:
        globals()["_note"] = real_note
    for host in ("api.anthropic.com", "api.openai.com"):
        if host in seen and host not in counted:
            failures.append(f"a call to {host} was not counted for the Privacy panel")
    return failures


def _http(provider: str, method: str, url: str, *, headers: Optional[dict] = None,
          body: Optional[dict] = None, params: Optional[dict] = None,
          timeout: float = 30.0, model: Optional[str] = None) -> Any:
    """One request, with every failure turned into a sentence for the user."""
    local = CAPS[provider].local
    t0 = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=3.0 if local else 10.0),
            transport=_TRANSPORT,
            trust_env=not local,
            follow_redirects=False,
            event_hooks=_count_hooks(),
        ) as client:
            r = client.request(method, url, headers=headers, json=body, params=params)
    except httpx.ConnectTimeout as e:
        _note(url, False, (time.monotonic() - t0) * 1000, "unreachable")
        raise error(provider, "down", model) from e
    except httpx.TimeoutException as e:
        _note(url, False, (time.monotonic() - t0) * 1000, "timed out")
        raise error(provider, "timeout", model) from e
    except httpx.HTTPError as e:
        _note(url, False, (time.monotonic() - t0) * 1000, "unreachable")
        raise error(provider, "down", model) from e

    try:
        data = r.json()
    except ValueError:
        data = None
    if r.status_code >= 400:
        det = _detail(data, r.text)
        raise error(provider, classify(provider, r.status_code, data, det), model,
                    det, r.status_code)
    if 300 <= r.status_code < 400:
        raise error(provider, "other", model, "unexpected redirect", r.status_code)
    if data is None:
        raise error(provider, "bad_response", model)
    if isinstance(data, dict) and isinstance(data.get("error"), (dict, str)) \
            and not data.get("choices") and not data.get("candidates") \
            and not data.get("message") and not data.get("data") and not data.get("models"):
        code = data["error"].get("code") if isinstance(data["error"], dict) else None
        det = _detail(data, "")
        st = code if isinstance(code, int) else 400
        raise error(provider, classify(provider, st, data, det), model, det, st)
    return data


def _headers(provider: str, key: Optional[str]) -> dict:
    if provider == "anthropic":
        return {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
    if provider == "gemini":
        return {"x-goog-api-key": key or ""}
    if provider in ("openai", "openrouter"):
        return {"Authorization": f"Bearer {key or ''}"}
    return {}



SUGGESTED: dict[str, tuple] = {
    "openrouter": (
        "google/gemini-2.5-flash",
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-5",
        "deepseek/deepseek-chat-v3.1",
        "meta-llama/llama-3.3-70b-instruct",
    ),
    "gemini": ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"),
    "ollama": ("llama3.1:8b", "qwen3:8b", "mistral-nemo"),
    "lmstudio": (),
}
DEFAULT_MODEL: dict[str, str] = {
    "openrouter": "google/gemini-2.5-flash",
    "gemini": "gemini-3.8-flash",
    "ollama": "llama3.1:8b",
    "lmstudio": "",
}

_MODEL_RE = {
    "openrouter": re.compile(r"^[A-Za-z0-9~][A-Za-z0-9._:/@+-]{0,159}$"),
    "gemini": re.compile(r"^[a-z0-9][a-z0-9.-]{0,99}$"),
    "ollama": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$"),
    "lmstudio": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$"),
}


def valid_model(provider: str, model: Any) -> bool:
    m = str(model or "").strip()
    rx = _MODEL_RE.get(provider)
    if not rx or not m or ".." in m or "//" in m:
        return False
    return bool(rx.match(m))


def clean_model(provider: str, model: Any) -> str:
    m = str(model or "").strip()
    if provider == "gemini" and m.startswith("models/"):
        m = m[len("models/"):]
    return m if valid_model(provider, m) else DEFAULT_MODEL.get(provider, "")


@dataclass
class ModelInfo:
    id: str
    tools: Optional[bool] = None
    context: Optional[int] = None
    loaded: Optional[bool] = None
    kind: Optional[str] = None
    max_context: Optional[int] = None

    def public(self) -> dict:
        return {"id": self.id, "tools": self.tools, "context": self.context,
                "maxContext": self.max_context, "loaded": self.loaded}


_LISTED: dict[str, tuple[float, list[ModelInfo]]] = {}
_LIST_TTL = 600.0


def cached_models(provider: str) -> list[ModelInfo]:
    hit = _LISTED.get(provider)
    return list(hit[1]) if hit else []


def list_models(provider: str, key: Optional[str] = None, *,
                fresh: bool = False) -> list[ModelInfo]:
    """The provider's own catalogue, from a free endpoint."""
    hit = _LISTED.get(provider)
    if hit and not fresh and time.time() - hit[0] < _LIST_TTL:
        return list(hit[1])
    out = _fetch_models(provider, key)
    _LISTED[provider] = (time.time(), out)
    return list(out)


def _fetch_models(provider: str, key: Optional[str]) -> list[ModelInfo]:
    if provider == "anthropic":
        data = _http(provider, "GET", f"{ANTHROPIC_BASE}/v1/models",
                     headers=_headers(provider, key), params={"limit": 100})
        return [ModelInfo(id=str(m.get("id")), tools=True)
                for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
    if provider == "openai":
        data = _http(provider, "GET", f"{OPENAI_BASE}/v1/models",
                     headers=_headers(provider, key))
        return [ModelInfo(id=str(m.get("id")), tools=True)
                for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
    if provider == "openrouter":
        data = _http(provider, "GET", f"{OPENROUTER_BASE}/models")
        out = []
        for m in data.get("data") or []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            params = m.get("supported_parameters")
            out.append(ModelInfo(
                id=str(m["id"]),
                tools=("tools" in params) if isinstance(params, list) else None,
                context=_int_or_none(m.get("context_length"))))
        return sorted(out, key=lambda x: x.id)
    if provider == "gemini":
        out, token = [], None
        for _ in range(5):
            params = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            data = _http(provider, "GET", f"{GEMINI_BASE}/v1beta/models",
                         headers=_headers(provider, key), params=params)
            for m in data.get("models") or []:
                if not isinstance(m, dict):
                    continue
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                mid = str(m.get("name") or "")
                mid = mid[len("models/"):] if mid.startswith("models/") else mid
                if valid_model("gemini", mid):
                    out.append(ModelInfo(id=mid, tools=_gemini_tools(mid),
                                         context=_int_or_none(m.get("inputTokenLimit"))))
            token = data.get("nextPageToken")
            if not token:
                break
        return out
    if provider == "ollama":
        data = _http(provider, "GET", f"{OLLAMA_BASE}/api/tags")
        out = []
        for m in data.get("models") or []:
            if isinstance(m, dict) and (m.get("model") or m.get("name")):
                fam = str(((m.get("details") or {}).get("family")) or "")
                out.append(ModelInfo(id=str(m.get("model") or m.get("name")),
                                     kind="embedding" if "bert" in fam else None))
        return out
    if provider == "lmstudio":
        try:
            data = _http(provider, "GET", f"{LMSTUDIO_BASE}/api/v0/models")
        except AiError:
            data = _http(provider, "GET", f"{LMSTUDIO_BASE}/v1/models")
        out = []
        for m in data.get("data") or []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            kind = str(m.get("type") or "") or None
            is_embed = kind == "embeddings" or "embed" in str(m["id"]).lower()
            state = m.get("state")
            out.append(ModelInfo(
                id=str(m["id"]),
                tools=False if is_embed else True,
                context=_int_or_none(m.get("loaded_context_length")),
                max_context=_int_or_none(m.get("max_context_length")),
                loaded=(state == "loaded") if state else None,
                kind="embedding" if is_embed else kind))
        return out
    raise AiError(f"Unknown AI provider: {provider}")


def _installed(provider: str, ids: list, model: str) -> bool:
    """Ollama treats an untagged name as `:latest`, and lists it that way; a
    user who typed `llama3.1` has `llama3.1:latest` installed, not nothing."""
    if model in ids:
        return True
    return provider == "ollama" and ":" not in model and f"{model}:latest" in ids


def _int_or_none(v: Any) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _gemini_tools(model: str) -> bool:
    """Function calling by model family. The listing does not say, so this is
    a family rule and is labelled as one in the capability table."""
    m = model.lower()
    if not m.startswith("gemini-"):
        return False
    return not any(bad in m for bad in ("embedding", "image", "tts", "-live",
                                        "native-audio", "audio-dialog",
                                        "transcribe", "nano-banana"))


def _ollama_show(model: str) -> dict:
    return _http("ollama", "POST", f"{OLLAMA_BASE}/api/show",
                 body={"model": model}, model=model)


def resolve_model(provider: str, model: str) -> str:
    """The empty LM Studio id means "the chat model you have loaded". Resolved
    from its own listing; a local call that costs nothing."""
    if provider != "lmstudio" or model:
        return model
    models = [m for m in list_models("lmstudio") if m.kind != "embedding"]
    if not models:
        raise error("lmstudio", "no_models")
    loaded = [m for m in models if m.loaded]
    return (loaded or models)[0].id


def tool_support(provider: str, key: Optional[str], model: str) -> tuple[bool, str]:
    """(can this model call tools, why not). Asked BEFORE Autopilot starts, so
    a model that cannot use tools is refused up front with a reason rather
    than failing on its first turn with a run half-recorded."""
    if CAPS[provider].tools == "all":
        return True, ""
    try:
        model = resolve_model(provider, model)
        if provider == "ollama":
            info = _ollama_show(model)
            caps = info.get("capabilities")
            if not isinstance(caps, list):
                return False, str(error("ollama", "tools_unknown", model))
            if "tools" not in caps:
                return False, str(error("ollama", "no_tools", model))
            return True, ""
        if provider == "gemini":
            if not _gemini_tools(model):
                return False, str(error("gemini", "no_tools", model))
            return True, ""
        listed = {m.id: m for m in list_models(provider, key)}
        info = listed.get(model)
        if info is None:
            return False, str(error(provider, "model", model))
        if info.tools is False or (provider == "openrouter" and info.tools is None):
            return False, str(error(provider, "no_tools", model))
        return True, ""
    except AiError as e:
        return False, str(e)



def check(provider: str, key: Optional[str], model: Optional[str] = None) -> dict:
    """{ok, message, models?, ...} using free endpoints only.

    `ok` means "an analysis on this provider with this model would get as far
    as the model": key accepted (cloud), server up and model present (local).
    Never a billed completion -- a test button that costs money is one people
    stop pressing."""
    caps = CAPS[provider]
    if caps.needs_key and not key:
        return {"ok": False, "message": str(error(provider, "no_key")),
                "provider": provider}
    try:
        note = ""
        if provider == "openrouter":
            info = _http(provider, "GET", f"{OPENROUTER_BASE}/key",
                         headers=_headers(provider, key))
            d = info.get("data") if isinstance(info, dict) else None
            remaining = d.get("limit_remaining") if isinstance(d, dict) else None
            if isinstance(remaining, (int, float)) and remaining <= 0:
                return {"ok": False, "provider": provider,
                        "message": str(error(provider, "quota"))}
        models = list_models(provider, key, fresh=True)
    except AiError as e:
        return {"ok": False, "message": str(e), "provider": provider}

    ids = [m.id for m in models]
    sel = model if model is not None else DEFAULT_MODEL.get(provider, "")
    out: dict = {"ok": True, "provider": provider, "models": ids,
                 "modelInfo": [m.public() for m in models],
                 "webSearch": caps.web_search}

    if caps.local:
        chat = [m for m in models if m.kind != "embedding"]
        if not chat:
            out["ok"] = False
            out["message"] = (str(error("lmstudio", "no_models")) if provider == "lmstudio"
                              else "Ollama is running but has no models pulled: run "
                                   f"`ollama pull {DEFAULT_MODEL['ollama']}`.")
            return out
        if sel and not _installed(provider, ids, sel):
            out["ok"] = False
            out["message"] = (f"{caps.label} is running, but " + str(error(provider, "model", sel)))
            return out
        target = sel or resolve_model(provider, sel)
        ok_tools, why = tool_support(provider, key, target)
        out["tools"] = ok_tools
        out["message"] = (f"{caps.label} is running with {len(chat)} model(s). "
                          f"{target}: " + ("can call tools, so Autopilot can use it."
                                           if ok_tools else why))
        return out

    if sel and ids and sel not in ids:
        out["ok"] = False
        out["reason"] = "model"
        out["message"] = (f"{caps.label} accepted the key, but {sel} isn't among the "
                          f"{len(ids)} model(s) it can use. Pick one from the list "
                          f"in Settings.")
        return out
    if provider == "gemini" and sel.startswith("gemini-2.5"):
        note = (f" Note: Google serves the 2.5 models only to keys that used them "
                f"before; if Analyse says {sel} isn't available, pick "
                f"{DEFAULT_MODEL['gemini']}.")
    if caps.tools == "per-model" and sel:
        ok_tools, _why = tool_support(provider, key, sel)
        out["tools"] = ok_tools
        note += (" It can call tools, so Autopilot can use it." if ok_tools
                 else f" {sel} can't call tools, so Autopilot won't run on it.")
    out["message"] = f"{caps.label} accepted the key. {len(ids)} model(s) available.{note}"
    return out



_MAX_TOKENS = 4000
_GEMINI_MAX_TOKENS = 16384
_OLLAMA_CTX = 16384
_OLLAMA_PREDICT = 6144
_OLLAMA_AGENT_CTX = 32768


def est_tokens(obj: Any) -> int:
    """A deliberately pessimistic token estimate (~3.5 chars/token) for the
    two places a count must exist and the provider did not give one: the
    context guard, and a local Autopilot turn with no usage block."""
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return int(len(s) / 3.5) + 1


def _chat_endpoint(provider: str, key: Optional[str]) -> tuple[str, dict]:
    if provider == "openrouter":
        return f"{OPENROUTER_BASE}/chat/completions", _headers(provider, key)
    if provider == "lmstudio":
        return f"{LMSTUDIO_BASE}/v1/chat/completions", {}
    raise AiError(f"{provider} is not a Chat Completions provider")


_LMS_FRESH_SEC = 30.0
_LMS_ASSUMED_CTX = 4096


def _lmstudio_window(model: str) -> tuple[Optional[int], str]:
    """(loaded context, why it is unknown). Re-lists when the cached entry
    is stale, missing, or not marked loaded."""
    def find() -> tuple[Optional[ModelInfo], Optional[float]]:
        hit = _LISTED.get("lmstudio")
        if not hit:
            return None, None
        return next((m for m in hit[1] if m.id == model), None), time.time() - hit[0]

    info, age = find()
    if (info is None or info.loaded is not True or info.context is None
            or age is None or age > _LMS_FRESH_SEC):
        try:
            list_models("lmstudio", fresh=True)
        except AiError:
            pass
        info, age = find()
    if info is not None and info.loaded and info.context:
        return info.context, ""
    return None, ("not_loaded" if info is not None and info.loaded is False else "unknown")


def _lmstudio_problem(model: str, need: int) -> Optional[str]:
    """The `context` error's detail when `need` tokens would not fit the
    window LM Studio has (or may have) for `model`, else None."""
    ctx, why = _lmstudio_window(model)
    if ctx is not None:
        if need > ctx:
            return (f"LM Studio has {model} loaded with a {ctx:,}-token context; this "
                    f"prompt needs ~{need:,} with room for the reply.")
        return None
    if need <= _LMS_ASSUMED_CTX:
        return None
    if why == "not_loaded":
        return (f"{model} isn't loaded in LM Studio, so the context it would be "
                f"loaded with is unknown (LM Studio's default is often "
                f"{_LMS_ASSUMED_CTX:,} tokens); this prompt needs ~{need:,}. Load it "
                f"in LM Studio first.")
    return (f"LM Studio didn't report the context {model} is loaded with (its "
            f"/api/v0 listing does, from LM Studio 0.3.6; update if yours is "
            f"older); this prompt needs ~{need:,}, more than the "
            f"{_LMS_ASSUMED_CTX:,} it may have.")


def _lmstudio_guard(model: str, tokens: int, reply: int) -> None:
    why = _lmstudio_problem(model, tokens + reply)
    if why:
        raise error("lmstudio", "context", model, why)


def _openrouter_cost(usage: Any) -> Optional[float]:
    """OpenRouter reports its own charge for the call (usage accounting), in
    USD credits. That is a price the provider published for this exact call,
    so it is shown; absent, the cost is None, not 0."""
    if isinstance(usage, dict):
        c = usage.get("cost")
        if isinstance(c, (int, float)) and c >= 0:
            return round(float(c), 6)
    return None


def call(provider: str, key: Optional[str], model: str, system: str, prompt: str,
         web_search: bool, timeout: float) -> dict:
    """One analysis. Returns {text, citations, inputTokens, outputTokens,
    costUsd, webSearchUsed}. The text goes back through ai_analyst's single
    parser, the same one the SDK providers use -- parsing safety is not a
    per-provider property."""
    caps = CAPS[provider]
    if caps.needs_key and not key:
        raise error(provider, "no_key")
    web = bool(web_search and caps.web_search)
    model = resolve_model(provider, model)
    if provider in ("openrouter", "lmstudio"):
        return _call_chat(provider, key, model, system, prompt, web, timeout)
    if provider == "ollama":
        return _call_ollama(model, system, prompt, timeout)
    if provider == "gemini":
        return _call_gemini(key, model, system, prompt, web, timeout)
    raise AiError(f"Unknown AI provider: {provider}")


def _call_chat(provider: str, key: Optional[str], model: str, system: str, prompt: str,
               web: bool, timeout: float) -> dict:
    url, headers = _chat_endpoint(provider, key)
    body: dict = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "max_tokens": _MAX_TOKENS,
    }
    if provider == "openrouter":
        body["usage"] = {"include": True}
        if web:
            body["plugins"] = [{"id": "web", "max_results": 5}]
    if provider == "lmstudio":
        _lmstudio_guard(model, est_tokens(system + prompt), _MAX_TOKENS)
    data = _http(provider, "POST", url, headers=headers, body=body,
                 timeout=timeout, model=model)
    choice = ((data.get("choices") or [None])[0]) or {}
    if not isinstance(choice, dict):
        raise error(provider, "bad_response", model)
    if isinstance(choice.get("error"), dict):
        det = _detail(choice, "")
        raise error(provider, classify(provider, 400, choice, det), model, det, 400)
    msg = choice.get("message") or {}
    if choice.get("finish_reason") == "content_filter" and not msg.get("content"):
        raise error(provider, "refused", model)
    citations = []
    for ann in msg.get("annotations") or []:
        if isinstance(ann, dict) and ann.get("type") == "url_citation":
            uc = ann.get("url_citation") or ann
            url_ = uc.get("url") if isinstance(uc, dict) else None
            if url_:
                citations.append({"title": str(uc.get("title") or url_), "url": str(url_)})
    usage = data.get("usage") or {}
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return {
        "text": str(content or "").strip(),
        "citations": citations,
        "inputTokens": _int_or_none(usage.get("prompt_tokens")),
        "outputTokens": _int_or_none(usage.get("completion_tokens")),
        "costUsd": _openrouter_cost(usage) if provider == "openrouter" else 0.0,
        "webSearchUsed": web,
    }


def _call_ollama(model: str, system: str, prompt: str, timeout: float) -> dict:
    need = est_tokens(system + prompt)
    if need + _OLLAMA_PREDICT > _OLLAMA_CTX:
        raise error("ollama", "context", model, f"{need:,}")
    data = _http("ollama", "POST", f"{OLLAMA_BASE}/api/chat", body={
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": _OLLAMA_CTX, "num_predict": _OLLAMA_PREDICT},
    }, timeout=timeout, model=model)
    msg = data.get("message") or {}
    return {
        "text": str(msg.get("content") or "").strip(),
        "citations": [],
        "inputTokens": _int_or_none(data.get("prompt_eval_count")),
        "outputTokens": _int_or_none(data.get("eval_count")),
        "costUsd": 0.0,
        "webSearchUsed": False,
    }


_GEMINI_REFUSALS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION",
                    "IMAGE_SAFETY"}


def _gemini_url(model: str) -> str:
    if not valid_model("gemini", model):
        raise error("gemini", "model", model)
    return f"{GEMINI_BASE}/v1beta/models/{model}:generateContent"


def _gemini_text(cand: dict) -> str:
    parts = ((cand.get("content") or {}).get("parts")) or []
    return "".join(p.get("text", "") for p in parts
                   if isinstance(p, dict) and not p.get("thought")).strip()


def _gemini_usage(data: dict) -> tuple[Optional[int], Optional[int]]:
    u = data.get("usageMetadata") or {}
    i = _int_or_none(u.get("promptTokenCount"))
    o = _int_or_none(u.get("candidatesTokenCount"))
    t = _int_or_none(u.get("thoughtsTokenCount"))
    if o is not None or t is not None:
        o = (o or 0) + (t or 0)
    return i, o


def _call_gemini(key: Optional[str], model: str, system: str, prompt: str,
                 web: bool, timeout: float) -> dict:
    body: dict = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": _GEMINI_MAX_TOKENS},
    }
    if web:
        body["tools"] = [{"google_search": {}}]
    data = _http("gemini", "POST", _gemini_url(model), headers=_headers("gemini", key),
                 body=body, timeout=timeout, model=model)
    block = (data.get("promptFeedback") or {}).get("blockReason")
    cands = data.get("candidates") or []
    cand = cands[0] if cands and isinstance(cands[0], dict) else {}
    text = _gemini_text(cand)
    if block or (not text and cand.get("finishReason") in _GEMINI_REFUSALS):
        raise AiError(f"Gemini declined to analyse this market "
                      f"({block or cand.get('finishReason')}).")
    citations = []
    for ch in ((cand.get("groundingMetadata") or {}).get("groundingChunks")) or []:
        web_ = ch.get("web") if isinstance(ch, dict) else None
        if isinstance(web_, dict) and web_.get("uri"):
            citations.append({"title": str(web_.get("title") or web_["uri"]),
                              "url": str(web_["uri"])})
    i, o = _gemini_usage(data)
    return {"text": text, "citations": citations, "inputTokens": i, "outputTokens": o,
            "costUsd": None, "webSearchUsed": web}



@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str = ""
    calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Optional[float] = None
    refusal: bool = False
    estimated: bool = False
    raw: Any = None
    failed: Optional[str] = None


def _args(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    try:
        parsed = json.loads(v or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class ToolChat:
    """One Autopilot conversation on one provider. send() is blocking; the
    caller runs it off the event loop."""

    provider = ""

    def __init__(self, key: Optional[str], model: str, system: str,
                 tools: list[dict], first_user: str):
        self.key = key
        self.model = model
        self.system = system
        self.tools = tools
        self.first_user = first_user

    def send(self) -> Turn:
        raise NotImplementedError

    def add_results(self, turn: Turn, results: list[tuple]) -> None:
        raise NotImplementedError

    def request_size(self) -> int:
        raise NotImplementedError

    def context_problem(self) -> Optional[str]:
        """A sentence when the next request would not fit the model's window,
        else None. Checked before every turn: the local servers truncate
        rather than refuse, and what they cut first is the system prompt."""
        return None

    def _usage(self, i: Optional[int], o: Optional[int], reply: Any) -> tuple[int, int, bool]:
        if i is None or o is None:
            return (i if i is not None else self.request_size(),
                    o if o is not None else est_tokens(reply), True)
        return i, o, False


class _ChatCompletionsToolChat(ToolChat):
    def __init__(self, provider: str, *a, **kw):
        super().__init__(*a, **kw)
        self.provider = provider
        self.url, self.headers = _chat_endpoint(provider, self.key)
        self.messages: list = [{"role": "system", "content": self.system},
                               {"role": "user", "content": self.first_user}]
        self.fn_tools = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description") or "",
            "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}}
            for t in self.tools]

    def _body(self) -> dict:
        body = {"model": self.model, "messages": self.messages, "tools": self.fn_tools,
                "max_tokens": _MAX_TOKENS}
        if self.provider == "openrouter":
            body["usage"] = {"include": True}
        return body

    def request_size(self) -> int:
        return est_tokens(self._body())

    def context_problem(self) -> Optional[str]:
        need = self.request_size() + _MAX_TOKENS
        if self.provider == "lmstudio":
            why = _lmstudio_problem(self.model, need)
            return str(error("lmstudio", "context", self.model, why)) if why else None
        ctx = next((m.context for m in cached_models("openrouter")
                    if m.id == self.model), None)
        if ctx and need > ctx:
            return (f"The conversation (~{need:,} tokens) outgrew {self.model}'s "
                    f"{ctx:,}-token context window.")
        return None

    def send(self) -> Turn:
        data = _http(self.provider, "POST", self.url, headers=self.headers,
                     body=self._body(), timeout=120.0, model=self.model)
        choice = ((data.get("choices") or [None])[0]) or {}
        if not isinstance(choice, dict):
            raise error(self.provider, "bad_response", self.model)
        msg = choice.get("message") or {}
        if not isinstance(msg, dict):
            msg = {}
        calls = []
        for n, tc in enumerate(msg.get("tool_calls") or []):
            fn = (tc or {}).get("function") or {}
            if fn.get("name"):
                calls.append(ToolCall(id=str(tc.get("id") or f"call_{n}"),
                                      name=str(fn["name"]), args=_args(fn.get("arguments"))))
        usage = data.get("usage") or {}
        i, o, est = self._usage(_int_or_none(usage.get("prompt_tokens")),
                                _int_or_none(usage.get("completion_tokens")), msg)
        text = str(msg.get("content") or "").strip()
        failed = None
        if isinstance(choice.get("error"), dict) or choice.get("finish_reason") == "error":
            det = _detail(choice, "") or "the model stopped with an error"
            failed = str(error(self.provider, classify(self.provider, 400, choice, det),
                               self.model, det, 400))
        elif choice.get("finish_reason") == "length" and not calls and not text:
            failed = (f"{CAPS[self.provider].label}: {self.model} ran out of output "
                      f"tokens before replying. Try again, or pick a model with a "
                      f"larger output limit.")
        return Turn(
            text=text, calls=[] if failed else calls,
            input_tokens=i, output_tokens=o, estimated=est, raw=msg,
            cost=(_openrouter_cost(usage) if self.provider == "openrouter" else 0.0),
            refusal=(choice.get("finish_reason") == "content_filter" and not calls),
            failed=failed)

    def add_results(self, turn: Turn, results: list[tuple]) -> None:
        msg = dict(turn.raw or {})
        keep = {"role": "assistant", "content": msg.get("content") or "",
                "tool_calls": msg.get("tool_calls") or []}
        if self.provider == "openrouter" and msg.get("reasoning_details"):
            keep["reasoning_details"] = msg["reasoning_details"]
        self.messages.append(keep)
        for call_, text, _is_err in results:
            self.messages.append({"role": "tool", "tool_call_id": call_.id, "content": text})


class _OllamaToolChat(ToolChat):
    provider = "ollama"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.messages: list = [{"role": "system", "content": self.system},
                               {"role": "user", "content": self.first_user}]
        self.fn_tools = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description") or "",
            "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}}
            for t in self.tools]

    def _body(self) -> dict:
        return {"model": self.model, "messages": self.messages, "tools": self.fn_tools,
                "stream": False,
                "options": {"num_ctx": _OLLAMA_AGENT_CTX, "num_predict": _MAX_TOKENS}}

    def request_size(self) -> int:
        return est_tokens(self._body())

    def context_problem(self) -> Optional[str]:
        need = self.request_size() + _MAX_TOKENS
        if need > _OLLAMA_AGENT_CTX:
            return (f"The conversation (~{need:,} tokens) outgrew the "
                    f"{_OLLAMA_AGENT_CTX:,}-token window Krypt asks Ollama for. "
                    f"Ollama would silently drop the start of it, instructions "
                    f"included, so the run stopped here.")
        return None

    def send(self) -> Turn:
        data = _http("ollama", "POST", f"{OLLAMA_BASE}/api/chat", body=self._body(),
                     timeout=180.0, model=self.model)
        msg = data.get("message") or {}
        calls = []
        for n, tc in enumerate(msg.get("tool_calls") or []):
            fn = (tc or {}).get("function") or {}
            if fn.get("name"):
                calls.append(ToolCall(id=str(tc.get("id") or f"call_{n}"),
                                      name=str(fn["name"]), args=_args(fn.get("arguments"))))
        i, o, est = self._usage(_int_or_none(data.get("prompt_eval_count")),
                                _int_or_none(data.get("eval_count")), msg)
        return Turn(text=str(msg.get("content") or "").strip(), calls=calls,
                    input_tokens=i, output_tokens=o, estimated=est, cost=0.0, raw=msg)

    def add_results(self, turn: Turn, results: list[tuple]) -> None:
        msg = dict(turn.raw or {})
        msg["role"] = "assistant"
        self.messages.append(msg)
        for call_, text, _is_err in results:
            self.messages.append({"role": "tool", "content": text, "tool_name": call_.name})


_GEMINI_SCHEMA_KEYS = {"type", "format", "description", "nullable", "enum", "properties",
                       "required", "items", "minItems", "maxItems", "minimum", "maximum",
                       "anyOf", "title", "minLength", "maxLength", "pattern"}


_JSON_ARG_NOTE = " Send this as a JSON object encoded in a string, e.g. \"{\\\"key\\\": 1}\"."


def gemini_schema(s: Any, _path: tuple = (), _json_paths: Optional[list] = None) -> Any:
    """JSON Schema -> the OpenAPI subset Gemini's `parameters` accepts.

    An open-ended object ({"type": "object"} with no properties -- a config
    patch, whose keys are the user's settings) is a 400 for the WHOLE request
    on Gemini: "properties: should be non-empty for OBJECT type". Autopilot
    on Gemini died on its first turn whenever the research or settings tools
    were switched on. Such a node is declared as a STRING holding JSON
    instead, its path recorded in `_json_paths`, and the Gemini tool chat
    decodes it back to an object before the tool sees it -- so the handlers
    and their validation are unchanged. `parametersJsonSchema` would accept
    the object as-is, but Gemini 3 is reported to answer an open-ended nested
    object there with an empty {} -- a silently dropped patch is worse than
    an encoded one."""
    if not isinstance(s, dict):
        return s
    out: dict = {}
    for k, v in s.items():
        if k not in _GEMINI_SCHEMA_KEYS:
            continue
        if k == "type" and isinstance(v, list):
            kinds = [t for t in v if t != "null"]
            out["type"] = kinds[0] if kinds else "string"
            if "null" in v:
                out["nullable"] = True
        elif k == "properties" and isinstance(v, dict):
            out[k] = {pk: gemini_schema(pv, _path + (pk,), _json_paths)
                      for pk, pv in v.items()}
        elif k == "items":
            out[k] = gemini_schema(v, _path + ("[]",), _json_paths)
        elif k == "anyOf" and isinstance(v, list):
            out[k] = [gemini_schema(x) for x in v]
        elif k == "enum":
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                out[k] = v
        else:
            out[k] = v
    if out.get("type") == "object" and "required" in out and "properties" in out:
        out["required"] = [r for r in out["required"] if r in out["properties"]]
    if _path and out.get("type") == "object" and not out.get("properties"):
        out.pop("properties", None)
        out.pop("required", None)
        out["type"] = "string"
        out["description"] = (str(out.get("description") or "").rstrip()
                              + _JSON_ARG_NOTE).strip()
        if _json_paths is not None:
            _json_paths.append(_path)
    return out


def _decode_json_args(args: Any, path: tuple) -> None:
    """Undo gemini_schema's object-as-string at `path`, in place. A string
    that is not a JSON object is left as it is, for the tool's own
    validation to refuse in its own words."""
    if not path:
        return
    head, rest = path[0], path[1:]
    if head == "[]":
        if isinstance(args, list):
            for i, item in enumerate(args):
                if rest:
                    _decode_json_args(item, rest)
                elif isinstance(item, str):
                    args[i] = _json_object_or(item)
        return
    if not isinstance(args, dict) or head not in args:
        return
    if rest:
        _decode_json_args(args[head], rest)
    elif isinstance(args[head], str):
        args[head] = _json_object_or(args[head])


def _json_object_or(s: str) -> Any:
    try:
        v = json.loads(s)
    except (TypeError, ValueError):
        return s
    return v if isinstance(v, dict) else s


class _GeminiToolChat(ToolChat):
    provider = "gemini"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.contents: list = [{"role": "user", "parts": [{"text": self.first_user}]}]
        decls = []
        self.json_args: dict[str, list] = {}
        for t in self.tools:
            d = {"name": t["name"], "description": t.get("description") or ""}
            paths: list = []
            params = gemini_schema(t.get("inputSchema") or {}, (), paths)
            if paths:
                self.json_args[t["name"]] = paths
            if params.get("properties"):
                d["parameters"] = params
            decls.append(d)
        self.fn_tools = [{"functionDeclarations": decls}] if decls else []

    def _body(self) -> dict:
        body = {"systemInstruction": {"parts": [{"text": self.system}]},
                "contents": self.contents,
                "generationConfig": {"maxOutputTokens": _GEMINI_MAX_TOKENS}}
        if self.fn_tools:
            body["tools"] = self.fn_tools
        return body

    def request_size(self) -> int:
        return est_tokens(self._body())

    def send(self) -> Turn:
        data = _http("gemini", "POST", _gemini_url(self.model),
                     headers=_headers("gemini", self.key), body=self._body(),
                     timeout=120.0, model=self.model)
        cands = data.get("candidates") or []
        cand = cands[0] if cands and isinstance(cands[0], dict) else {}
        content = cand.get("content") or {"role": "model", "parts": []}
        calls = []
        for n, p in enumerate(content.get("parts") or []):
            fc = p.get("functionCall") if isinstance(p, dict) else None
            if isinstance(fc, dict) and fc.get("name"):
                args = copy.deepcopy(_args(fc.get("args")))
                for path in self.json_args.get(str(fc["name"]), ()):
                    _decode_json_args(args, path)
                calls.append(ToolCall(id=str(fc.get("id") or f"call_{n}"),
                                      name=str(fc["name"]), args=args))
        i, o = _gemini_usage(data)
        i, o, est = self._usage(i, o, content)
        blocked = bool((data.get("promptFeedback") or {}).get("blockReason")) or (
            cand.get("finishReason") in _GEMINI_REFUSALS and not calls)
        return Turn(text=_gemini_text(cand), calls=calls, input_tokens=i,
                    output_tokens=o, estimated=est, cost=None, refusal=blocked,
                    raw=content)

    def add_results(self, turn: Turn, results: list[tuple]) -> None:
        content = dict(turn.raw or {})
        content["role"] = "model"
        self.contents.append(content)
        parts = []
        for call_, text, is_err in results:
            resp = {"error": text} if is_err else {"result": text}
            fr: dict = {"name": call_.name, "response": resp}
            if call_.id and not call_.id.startswith("call_"):
                fr["id"] = call_.id
            parts.append({"functionResponse": fr})
        self.contents.append({"role": "user", "parts": parts})


def open_tool_chat(provider: str, key: Optional[str], model: str, system: str,
                   tools: list[dict], first_user: str) -> ToolChat:
    model = resolve_model(provider, model)
    if provider in ("openrouter", "lmstudio"):
        return _ChatCompletionsToolChat(provider, key, model, system, tools, first_user)
    if provider == "ollama":
        return _OllamaToolChat(key, model, system, tools, first_user)
    if provider == "gemini":
        return _GeminiToolChat(key, model, system, tools, first_user)
    raise AiError(f"{provider} has no tool loop here")
