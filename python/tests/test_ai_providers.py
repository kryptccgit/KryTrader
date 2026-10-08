"""OpenRouter, Gemini, Ollama and LM Studio: every path, against a mocked httpx.

Nothing here touches the network: ai_providers routes every request through
`_TRANSPORT`, which these tests replace with an httpx.MockTransport. What is
pinned, per provider:

  1. The model is shown the same thing whoever it is. Absent fields reach the
     prompt as "--", and the system prompt that says "--" is not zero lands
     where THAT provider reads a system prompt.
  2. What comes back goes through the same safety: a fair value outside
     1..99 is None, a verdict with no number is "unclear", prose is kept raw.
  3. Each failure is a sentence the user can act on: a rejected key, a local
     server that is not running, a model that is not pulled, an empty credit
     balance.
  4. Autopilot runs on any tool-capable model under the same budgets, and
     refuses a model that cannot call tools BEFORE anything is recorded.
  5. Keys stay where keys go: a header (never a URL), the encrypted store
     (never settings.json), and never a log line.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import ai_analyst as ai
import ai_providers as ap

OR_KEY = "sk-" + "or-v1-" + "0f" * 32
GEMINI_KEY = "AI" + "za" + "SyN0tAR3alG00gleK3yXXXXXXXXXXXXXXXX"
assert len(GEMINI_KEY) == 39

CHAT = {
    "openrouter": ("POST", "/api/v1/chat/completions"),
    "lmstudio": ("POST", "/v1/chat/completions"),
    "ollama": ("POST", "/api/chat"),
    "gemini": ("POST", "/v1beta/models/gemini-3.8-flash:generateContent"),
}
LMS_MODEL = "qwen2.5-7b-instruct"

GOOD = {
    "summary": "A weather market two days out.",
    "drivers": [{"heading": "Front", "body": "A front arrives Thursday."}],
    "resolutionNotes": "Settles on the NWS daily total.",
    "fairValueCents": 41, "fairValueLowCents": 33, "fairValueHighCents": 49,
    "verdict": "cheap", "confidence": "medium",
    "wouldChangeMyMind": ["The Wednesday model run"],
}


def J(status: int, body) -> callable:
    return lambda req: httpx.Response(status, json=body)


class Router:
    """A tiny request router. Each route is a callable(request) -> Response,
    or a list of them consumed in order."""

    def __init__(self):
        self.routes: dict = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, handler) -> None:
        self.routes[(method, path)] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        h = self.routes.get((request.method, request.url.path))
        if h is None:
            return httpx.Response(404, json={"error": f"no route {request.url.path}"})
        if isinstance(h, list):
            h = h.pop(0) if len(h) > 1 else h[0]
        return h(request)

    def bodies(self, method: str, path: str) -> list[dict]:
        return [json.loads(r.content or b"{}") for r in self.requests
                if r.method == method and r.url.path == path]


def _down(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture
def net(monkeypatch):
    r = Router()
    monkeypatch.setattr(ap, "_TRANSPORT", httpx.MockTransport(r))
    ap._LISTED.clear()
    keys = {"openrouter": OR_KEY, "gemini": GEMINI_KEY}
    monkeypatch.setattr(ai, "_read_key", lambda p: keys.get(p))
    monkeypatch.setattr(ai, "has_key", lambda p: p in keys)
    r.on("GET", "/api/v0/models", J(200, {"data": [
        {"id": "text-embedding-nomic", "type": "embeddings", "state": "not-loaded"},
        {"id": LMS_MODEL, "type": "llm", "state": "loaded",
         "loaded_context_length": 32768, "max_context_length": 32768},
    ]}))
    yield r
    ap._LISTED.clear()


def reply(provider: str, text: str, *, usage: bool = True) -> dict:
    if provider in ("openrouter", "lmstudio"):
        msg = {"role": "assistant", "content": text}
        if provider == "openrouter":
            msg["annotations"] = [{"type": "url_citation", "url_citation": {
                "url": "https://www.weather.gov/x", "title": "NWS"}}]
        out = {"choices": [{"message": msg, "finish_reason": "stop"}]}
        if usage:
            out["usage"] = {"prompt_tokens": 1200, "completion_tokens": 300}
            if provider == "openrouter":
                out["usage"]["cost"] = 0.0021
        return out
    if provider == "ollama":
        out = {"message": {"role": "assistant", "content": text}, "done": True}
        if usage:
            out.update(prompt_eval_count=1200, eval_count=300)
        return out
    out = {"candidates": [{
        "content": {"role": "model", "parts": [{"text": text}]},
        "finishReason": "STOP",
        "groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://vertexaisearch.example/r1", "title": "weather.gov"}}]},
    }]}
    if usage:
        out["usageMetadata"] = {"promptTokenCount": 1200, "candidatesTokenCount": 250,
                                "thoughtsTokenCount": 50}
    return out


def _detail():
    return {
        "market": {
            "ticker": "KXRAIN-26", "title": "Will it rain?",
            "yesSubTitle": "Above 1 inch",
            "yesBid": None, "yesAsk": 44, "noBid": 56, "noAsk": None,
            "lastPrice": None, "previousPrice": None,
            "midCents": None, "spreadCents": None,
            "volume": None, "volume24h": None, "openInterest": None,
            "status": "active", "closeTime": None, "minutesToClose": None,
        },
        "event": None, "series": None, "risk": {}, "book": None,
        "position": None, "errors": [], "fetchedAt": "2026-10-06T12:00:00Z",
    }


def _cfg(provider: str, **kw) -> dict:
    return {"ai_provider": provider, "ai_model": "", "ai_web_search": False, **kw}


def _analyze(net, provider: str, text: str, **cfg):
    net.on(*CHAT[provider], J(200, reply(provider, text)))
    return ai.analyze(_detail(), _cfg(provider, **cfg))


def _sent(provider: str, body: dict) -> tuple[str, str]:
    """(system prompt, user prompt) as THIS provider reads them."""
    if provider == "gemini":
        assert body["contents"][0]["role"] == "user"
        return (body["systemInstruction"]["parts"][0]["text"],
                body["contents"][0]["parts"][0]["text"])
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    return body["messages"][0]["content"], body["messages"][1]["content"]


PROVIDERS = ("openrouter", "gemini", "ollama", "lmstudio")



@pytest.mark.parametrize("provider", PROVIDERS)
def test_absent_fields_reach_every_provider_as_dashes(net, provider):
    _analyze(net, provider, json.dumps(GOOD))
    body = net.bodies(*CHAT[provider])[0]
    system, user = _sent(provider, body)
    assert "is ABSENT" in system and "It is not zero" in system
    assert "yes bid --" in user and "no ask --" in user and "last --" in user
    assert "0c" not in user
    assert "yes ask 44c" in user



@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_clean_reply_parses_the_same_everywhere(net, provider):
    got = _analyze(net, provider, json.dumps(GOOD))
    assert got["provider"] == provider
    assert got["fairValueCents"] == 41
    assert (got["fairValueLowCents"], got["fairValueHighCents"]) == (33, 49)
    assert got["verdict"] == "cheap" and got["raw"] is None
    assert got["inputTokens"] == 1200 and got["outputTokens"] == 300
    if provider in ("ollama", "lmstudio"):
        assert got["costUsd"] == 0.0
        assert got["model"] in ("llama3.1:8b", LMS_MODEL)
    elif provider == "openrouter":
        assert got["costUsd"] == 0.0021
    else:
        assert got["costUsd"] is None


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_fair_value_outside_the_band_is_none_everywhere(net, provider):
    got = _analyze(net, provider, json.dumps({**GOOD, "fairValueCents": 100}))
    assert got["fairValueCents"] is None
    assert got["verdict"] == "unclear"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_verdict_with_no_number_is_unclear_everywhere(net, provider):
    got = _analyze(net, provider, json.dumps({**GOOD, "fairValueCents": None,
                                               "verdict": "rich"}))
    assert got["fairValueCents"] is None and got["verdict"] == "unclear"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_prose_is_kept_raw_everywhere(net, provider):
    got = _analyze(net, provider, "I think it is about even, honestly.")
    assert got["raw"].startswith("I think") and got["fairValueCents"] is None


@pytest.mark.parametrize("provider", ("ollama", "lmstudio", "openrouter"))
def test_a_draft_inside_reasoning_never_beats_the_answer(net, provider):
    """qwen3 / deepseek-r1 think out loud, drafts included. The parser takes
    the first {...}; the draft's 50 must not become the fair value."""
    text = ('<think>first guess {"fairValueCents": 50, "verdict": "fair"} hmm</think>'
            + json.dumps(GOOD))
    got = _analyze(net, provider, text)
    assert got["fairValueCents"] == 41 and got["verdict"] == "cheap"


def test_a_reply_cut_off_mid_thought_is_not_an_answer(net):
    got = _analyze(net, "ollama", '<think>so maybe {"fairValueCents": 50')
    assert got["fairValueCents"] is None and got["raw"]



def test_openrouter_search_uses_the_web_plugin_and_keeps_citations(net):
    got = _analyze(net, "openrouter", json.dumps(GOOD), ai_web_search=True)
    body = net.bodies(*CHAT["openrouter"])[0]
    assert body["plugins"] == [{"id": "web", "max_results": 5}]
    assert got["webSearchUsed"] is True
    assert got["citations"] == [{"title": "NWS", "url": "https://www.weather.gov/x"}]


def test_gemini_search_is_google_grounding_with_its_own_citations(net):
    got = _analyze(net, "gemini", json.dumps(GOOD), ai_web_search=True)
    body = net.bodies(*CHAT["gemini"])[0]
    assert body["tools"] == [{"google_search": {}}]
    assert got["webSearchUsed"] is True
    assert got["citations"][0]["title"] == "weather.gov"


@pytest.mark.parametrize("provider", ("ollama", "lmstudio"))
def test_a_local_model_never_claims_it_searched(net, provider):
    got = _analyze(net, provider, json.dumps(GOOD), ai_web_search=True)
    assert got["webSearchUsed"] is False
    body = net.bodies(*CHAT[provider])[0]
    assert "tools" not in body and "plugins" not in body
    assert ai.status(_cfg(provider, ai_web_search=True))["webSearch"] is False



def _err(net, provider, handler) -> str:
    net.on(*CHAT[provider], handler)
    with pytest.raises(ai.AiError) as e:
        ai.analyze(_detail(), _cfg(provider))
    return str(e.value)


def test_openrouter_rejected_key(net):
    msg = _err(net, "openrouter", J(401, {"error": {"code": 401, "message": "User not found."}}))
    assert "OpenRouter rejected the key" in msg


def test_openrouter_out_of_credits_is_not_called_a_rate_limit(net):
    msg = _err(net, "openrouter", J(402, {"error": {"code": 402, "message": "Insufficient credits"}}))
    assert "out of credits" in msg and ":free" in msg


def test_openrouter_error_inside_a_200(net):
    msg = _err(net, "openrouter", J(200, {"error": {"code": 401, "message": "No auth"}}))
    assert "OpenRouter rejected the key" in msg


def test_gemini_bad_key_is_a_400_and_still_reads_as_a_bad_key(net):
    """The reason this is the native API: Google sends a bad key as HTTP 400.
    A status-code mapper would say "bad request"."""
    msg = _err(net, "gemini", J(400, {"error": {
        "code": 400, "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
        "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                     "reason": "API_KEY_INVALID"}]}}))
    assert "Google rejected that Gemini API key" in msg


def test_gemini_quota(net):
    msg = _err(net, "gemini", J(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                 "message": "Quota exceeded"}}))
    assert "quota" in msg.lower() and "per day" in msg


def test_gemini_refusal_is_said_not_shown_as_an_empty_analysis(net):
    msg = _err(net, "gemini", J(200, {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}))
    assert "declined" in msg


def test_ollama_not_running(net):
    msg = _err(net, "ollama", _down)
    assert "Ollama isn't running" in msg and "`ollama serve`" in msg


def test_ollama_model_not_pulled(net):
    msg = _err(net, "ollama", J(404, {"error": 'model "llama3.1:8b" not found, try pulling it first'}))
    assert msg == "llama3.1:8b isn't pulled in Ollama: run `ollama pull llama3.1:8b`."


def test_lmstudio_not_running(net):
    net.on("GET", "/api/v0/models", _down)
    net.on("GET", "/v1/models", _down)
    msg = _err(net, "lmstudio", _down)
    assert "LM Studio's local server isn't running" in msg


def test_lmstudio_with_nothing_downloaded(net):
    net.on("GET", "/api/v0/models", J(200, {"data": []}))
    msg = _err(net, "lmstudio", J(200, reply("lmstudio", "{}")))
    assert "no chat model downloaded" in msg


def test_lmstudio_context_too_small_is_refused_before_sending(net):
    """LM Studio loads a model with a fixed window and, past it, truncates.
    The prompt is refused up front, with the fix, rather than cut."""
    net.on("GET", "/api/v0/models", J(200, {"data": [
        {"id": LMS_MODEL, "type": "llm", "state": "loaded", "loaded_context_length": 2048}]}))
    msg = _err(net, "lmstudio", J(200, reply("lmstudio", json.dumps(GOOD))))
    assert "2,048-token context" in msg and "larger context length" in msg
    assert net.bodies(*CHAT["lmstudio"]) == []


def test_ollama_context_is_set_explicitly_and_overflow_refused(net, monkeypatch):
    """Ollama truncates from the FRONT -- the system prompt -- when a prompt
    overflows its default window. So the window is asked for explicitly, and
    a prompt too big for it never leaves."""
    _analyze(net, "ollama", json.dumps(GOOD))
    assert net.bodies(*CHAT["ollama"])[0]["options"]["num_ctx"] == ap._OLLAMA_CTX
    monkeypatch.setattr(ap, "_OLLAMA_CTX", 1000)
    msg = _err(net, "ollama", J(200, reply("ollama", json.dumps(GOOD))))
    assert "too big" in msg
    assert len(net.bodies(*CHAT["ollama"])) == 1


def test_a_cloud_provider_without_a_key_never_calls_out(net, monkeypatch):
    monkeypatch.setattr(ai, "_read_key", lambda p: None)
    for provider in ("openrouter", "gemini"):
        with pytest.raises(ai.AiError) as e:
            ai.analyze(_detail(), _cfg(provider))
        assert "Settings" in str(e.value)
    assert net.requests == []



def test_the_gemini_key_goes_in_a_header_never_the_url(net):
    _analyze(net, "gemini", json.dumps(GOOD))
    req = next(r for r in net.requests if r.method == "POST")
    assert req.headers["x-goog-api-key"] == GEMINI_KEY
    assert GEMINI_KEY not in str(req.url) and "key=" not in str(req.url)


def test_openrouter_sends_the_key_and_no_attribution_headers(net):
    """HTTP-Referer / X-Title put an app on OpenRouter's public usage
    rankings: reporting usage to a third party (invariant 4)."""
    _analyze(net, "openrouter", json.dumps(GOOD))
    req = next(r for r in net.requests if r.method == "POST")
    assert req.headers["authorization"] == f"Bearer {OR_KEY}"
    assert "http-referer" not in req.headers and "x-title" not in req.headers


def test_local_providers_send_no_credentials(net):
    for provider in ("ollama", "lmstudio"):
        _analyze(net, provider, json.dumps(GOOD))
    for r in net.requests:
        assert "authorization" not in r.headers and "x-goog-api-key" not in r.headers


def test_every_request_goes_to_a_hardcoded_host(net):
    for provider in PROVIDERS:
        _analyze(net, provider, json.dumps(GOOD))
        ai.check_provider(provider, _cfg(provider))
    hosts = {ap.stat_host(r.url) for r in net.requests}
    assert hosts <= {"openrouter.ai", "generativelanguage.googleapis.com",
                     "127.0.0.1:11434", "127.0.0.1:1234"}, hosts


def test_a_redirect_is_never_followed_with_a_key_on_it(net):
    """httpx strips Authorization on a cross-origin redirect but not
    x-goog-api-key; following one could hand a key to whatever host it named."""
    net.on(*CHAT["gemini"], lambda req: httpx.Response(
        302, headers={"location": "https://evil.example.com/steal"}))
    with pytest.raises(ai.AiError):
        ai.analyze(_detail(), _cfg("gemini"))
    assert all(r.url.host != "evil.example.com" for r in net.requests)


@pytest.mark.parametrize("provider,bad", [
    ("gemini", "../../v1/files"),
    ("gemini", "gemini-2.5-flash/../x"),
    ("gemini", "gemini-2.5-flash:generateContent?key=x"),
    ("openrouter", "http://evil.example.com/x"),
    ("openrouter", "a" * 300),
    ("ollama", "llama3\nHost: evil"),
    ("lmstudio", " "),
])
def test_a_malformed_model_id_never_travels(provider, bad):
    """The model id is the one free-form string the renderer contributes, and
    Gemini's lands in the URL path. Bad shape -> the provider default."""
    assert ai.normalize_model(provider, bad) == ai.DEFAULT_MODEL[provider]


@pytest.mark.parametrize("provider,good", [
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
    ("gemini", "models/gemini-2.5-pro"),
    ("ollama", "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"),
    ("lmstudio", "lmstudio-community/qwen2.5-7b-instruct"),
])
def test_real_model_ids_are_accepted(provider, good):
    assert ai.normalize_model(provider, good) == good.replace("models/", "")


def test_keys_go_to_the_encrypted_store_and_local_providers_take_none(monkeypatch):
    import kalshi_auth
    saved = {}
    monkeypatch.setattr(kalshi_auth, "save_secret", lambda n, v: saved.__setitem__(n, v))
    monkeypatch.setattr(kalshi_auth, "has_secret", lambda n: n in saved)
    assert ai.save_key("openrouter", OR_KEY) is True
    assert ai.save_key("gemini", GEMINI_KEY) is True
    assert saved == {"ai_openrouter_key": OR_KEY, "ai_gemini_key": GEMINI_KEY}
    for local in ("ollama", "lmstudio"):
        with pytest.raises(ValueError):
            ai.save_key(local, "anything")


def test_no_ai_key_has_a_settings_json_home():
    """settings.json is copied in the clear by profile export and the
    version-change backup, so no key-ish ai_* setting may exist there."""
    from config import DEFAULT_CONFIG
    assert not [k for k in DEFAULT_CONFIG
                if k.startswith("ai_") and ("key" in k or "token" in k)]
    cfg = merge_with_defaults({"ai_provider": OR_KEY})
    assert cfg["ai_provider"] == "anthropic"


def test_the_new_keys_are_redacted_by_value_and_by_shape(monkeypatch):
    import kalshi_auth
    import logscrub
    secrets = {"ai_openrouter_key": OR_KEY, "ai_gemini_key": GEMINI_KEY}
    monkeypatch.setattr(kalshi_auth, "read_secret", lambda n: secrets.get(n))
    monkeypatch.setattr(kalshi_auth, "_load_api_key", lambda: None)
    try:
        logscrub.refresh_known_secrets()
        line = f"calling with {OR_KEY} then {GEMINI_KEY}"
        out = logscrub.scrub(line)
        assert OR_KEY not in out and GEMINI_KEY not in out
        logscrub.set_known_secrets([])
        other_or = "sk-" + "or-v1-" + "ab" * 32
        other_g = "AI" + "za" + "Sy" + "Q" * 33
        anth = "sk-" + "ant-api03-" + "Z" * 40
        out = logscrub.scrub(f"bad key {other_or} / {other_g} / {anth}")
        assert other_or not in out and other_g not in out and anth not in out
        plain = "order 5b1e7a4c-1f0e-4c4e-9d8e-0a0b0c0d0e0f filled 10 @ 44c on KXRAIN-26"
        assert logscrub.scrub(plain) == plain
    finally:
        logscrub.set_known_secrets([])


def test_status_says_what_each_provider_can_do_and_never_a_key(net):
    st = ai.status(_cfg("ollama"))
    assert st["hasKey"] is True
    assert st["keys"]["ollama"] is False
    caps = st["capabilities"]
    assert caps["ollama"]["local"] and not caps["ollama"]["needsKey"]
    assert caps["ollama"]["webSearch"] is False and caps["lmstudio"]["webSearch"] is False
    assert caps["openrouter"]["webSearch"] and caps["gemini"]["webSearch"]
    assert set(st["providers"]) == set(ai.PROVIDERS)
    assert OR_KEY not in repr(st) and GEMINI_KEY not in repr(st)



def _billed(net) -> list:
    return [r for r in net.requests
            if "chat" in r.url.path or "generateContent" in r.url.path
            or r.url.path.endswith("/messages") or r.url.path.endswith("/responses")]


def test_check_openrouter_ok_lists_models_and_tool_support(net):
    net.on("GET", "/api/v1/key", J(200, {"data": {"label": "x", "limit_remaining": 4.2}}))
    net.on("GET", "/api/v1/models", J(200, {"data": [
        {"id": "google/gemini-2.5-flash", "supported_parameters": ["tools", "max_tokens"],
         "context_length": 1048576},
        {"id": "some/no-tools-model", "supported_parameters": ["max_tokens"]},
    ]}))
    res = ai.check_provider("openrouter", _cfg("openrouter"))
    assert res["ok"] is True and res["tools"] is True
    assert res["models"] == ["google/gemini-2.5-flash", "some/no-tools-model"]
    assert "accepted the key" in res["message"]
    assert _billed(net) == []
    assert "some/no-tools-model" in ai.status(_cfg("openrouter"))["models"]["openrouter"]


def test_check_openrouter_bad_key_and_empty_credit(net):
    net.on("GET", "/api/v1/key", J(401, {"error": {"code": 401, "message": "No auth"}}))
    res = ai.check_provider("openrouter", _cfg("openrouter"))
    assert res["ok"] is False and "OpenRouter rejected the key" in res["message"]
    net.on("GET", "/api/v1/key", J(200, {"data": {"limit_remaining": 0}}))
    res = ai.check_provider("openrouter", _cfg("openrouter"))
    assert res["ok"] is False and "credits" in res["message"]


def test_check_gemini_lists_only_text_models_and_strips_the_prefix(net):
    net.on("GET", "/v1beta/models", J(200, {"models": [
        {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemma-3-27b-it", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-nano-banana-2.1", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-transcribe", "supportedGenerationMethods": ["generateContent"]},
    ]}))
    res = ai.check_provider("gemini", _cfg("gemini"))
    assert res["ok"] is True
    assert res["models"] == ["gemini-3.8-flash", "gemma-3-27b-it",
                             "gemini-nano-banana-2.1", "gemini-3.5-transcribe"]
    info = {m["id"]: m["tools"] for m in res["modelInfo"]}
    assert info == {"gemini-3.8-flash": True, "gemma-3-27b-it": False,
                    "gemini-nano-banana-2.1": False, "gemini-3.5-transcribe": False}
    assert net.requests[0].headers["x-goog-api-key"] == GEMINI_KEY
    assert _billed(net) == []


def test_gemini_defaults_are_models_a_new_key_can_use():
    """Google serves the 2.5 models only to keys that used them before. With
    2.5 as the default, every NEW Gemini key failed its first Analyse."""
    assert not ap.DEFAULT_MODEL["gemini"].startswith("gemini-2.5")
    assert not any(m.startswith("gemini-2.5") for m in ap.SUGGESTED["gemini"])
    assert ap.DEFAULT_MODEL["gemini"] in ap.SUGGESTED["gemini"]
    assert all(ap.valid_model("gemini", m) for m in ap.SUGGESTED["gemini"])
    assert ap.clean_model("gemini", "gemini-2.5-flash") == "gemini-2.5-flash"


def test_test_connection_fails_when_the_configured_model_is_not_listed(net):
    """Test connection used to say "accepted the key" while the model Analyse
    would send was not one the key can use -- then the first real call 404'd."""
    net.on("GET", "/v1beta/models", J(200, {"models": [
        {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
    ]}))
    res = ai.check_provider("gemini", _cfg("gemini", ai_model="gemini-9-imaginary"))
    assert res["ok"] is False
    assert "gemini-9-imaginary" in res["message"] and "isn't among" in res["message"]
    assert res["models"] == ["gemini-3.8-flash"]
    assert _billed(net) == []


def test_a_listed_25_model_gets_the_new_key_warning(net):
    net.on("GET", "/v1beta/models", J(200, {"models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
    ]}))
    res = ai.check_provider("gemini", _cfg("gemini", ai_model="gemini-2.5-flash"))
    assert res["ok"] is True
    assert "only to keys that used them before" in res["message"]


def test_a_gemini_model_error_carries_googles_reason(net):
    net.on(*CHAT["gemini"], J(404, {"error": {
        "code": 404, "status": "NOT_FOUND",
        "message": "This model is no longer available to new users."}}))
    with pytest.raises(ai.AiError) as e:
        ai.analyze(_detail(), _cfg("gemini"))
    assert "no longer available to new users" in str(e.value)
    assert "  " not in str(e.value)


def test_check_gemini_bad_key(net):
    net.on("GET", "/v1beta/models", J(400, {"error": {
        "code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT",
        "details": [{"reason": "API_KEY_INVALID"}]}}))
    res = ai.check_provider("gemini", _cfg("gemini"))
    assert res["ok"] is False and "Google rejected" in res["message"]


def test_check_ollama_down_not_pulled_and_ok(net):
    net.on("GET", "/api/tags", _down)
    res = ai.check_provider("ollama", _cfg("ollama"))
    assert res["ok"] is False and "`ollama serve`" in res["message"]

    net.on("GET", "/api/tags", J(200, {"models": [{"model": "qwen3:8b", "details": {}}]}))
    res = ai.check_provider("ollama", _cfg("ollama", ai_model="llama3.1:8b"))
    assert res["ok"] is False and "`ollama pull llama3.1:8b`" in res["message"]
    assert res["models"] == ["qwen3:8b"]

    net.on("POST", "/api/show", J(200, {"capabilities": ["completion", "tools"]}))
    res = ai.check_provider("ollama", _cfg("ollama", ai_model="qwen3:8b"))
    assert res["ok"] is True and res["tools"] is True
    assert "Autopilot can use it" in res["message"]
    assert _billed(net) == []


def test_check_ollama_untagged_name_means_latest(net):
    net.on("GET", "/api/tags", J(200, {"models": [{"model": "mistral-nemo:latest"}]}))
    net.on("POST", "/api/show", J(200, {"capabilities": ["completion"]}))
    res = ai.check_provider("ollama", _cfg("ollama", ai_model="mistral-nemo"))
    assert res["ok"] is True and res["tools"] is False
    assert "can't call tools" in res["message"]


def test_check_lmstudio_falls_back_to_the_openai_listing(net):
    net.on("GET", "/api/v0/models", J(404, {"error": "Unexpected endpoint"}))
    net.on("GET", "/v1/models", J(200, {"data": [{"id": LMS_MODEL, "object": "model"}]}))
    res = ai.check_provider("lmstudio", _cfg("lmstudio"))
    assert res["ok"] is True and res["models"] == [LMS_MODEL]
    assert _billed(net) == []


def test_check_anthropic_uses_the_free_listing(net, monkeypatch):
    monkeypatch.setattr(ai, "_read_key", lambda p: "sk-test")
    net.on("GET", "/v1/models", J(401, {"type": "error", "error": {
        "type": "authentication_error", "message": "invalid x-api-key"}}))
    res = ai.check_provider("anthropic", _cfg("anthropic"))
    assert res["ok"] is False and "That Anthropic API key was rejected" in res["message"]
    assert net.requests[0].headers["x-api-key"] == "sk-test"
    net.on("GET", "/v1/models", J(200, {"data": [{"id": "claude-opus-5"}, {"id": "x"}]}))
    res = ai.check_provider("anthropic", _cfg("anthropic"))
    assert res["ok"] is True and res["models"] == ["claude-opus-5"]
    assert _billed(net) == []


def test_check_without_a_key_makes_no_request(net, monkeypatch):
    monkeypatch.setattr(ai, "_read_key", lambda p: None)
    res = ai.check_provider("gemini", {})
    assert res["ok"] is False and "Settings" in res["message"]
    assert net.requests == []


def test_check_an_unknown_provider():
    res = ai.check_provider("http://evil.example.com")
    assert res["ok"] is False and "Unknown" in res["message"]



import autopilot
import db
import mcp_server
from config import merge_with_defaults


@pytest.fixture
def pilot(net):
    db.init_db()
    with db.get_db() as conn:
        for t in ("autopilot_runs", "ai_forecasts", "mcp_orders"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    st = {"cfg": {"autopilot_enabled": True, "mcp_trade_mode": "off"}}
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(st["cfg"])),
                         is_authed=lambda: False, emit=None, rpc=None,
                         submit=None, cancel=None, notify_phone=None)
    autopilot.STATE.running = False
    autopilot.STATE.last_error = None
    return st


def _pcfg(st, provider, model=""):
    st["cfg"].update(ai_provider=provider, ai_model=model)
    return merge_with_defaults(dict(st["cfg"]))


def _run(cfg):
    return asyncio.run(autopilot.run_once(cfg, "manual"))


def _tool_turn(provider, name="get_status", usage=True, tokens=1000):
    if provider in ("openrouter", "lmstudio"):
        out = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": name, "arguments": "{}"}}]},
            "finish_reason": "tool_calls"}]}
        if usage:
            out["usage"] = {"prompt_tokens": tokens, "completion_tokens": 50, "cost": 0.001}
        return out
    if provider == "ollama":
        out = {"message": {"role": "assistant", "content": "",
                           "tool_calls": [{"function": {"name": name, "arguments": {}}}]},
               "done": True}
        if usage:
            out.update(prompt_eval_count=tokens, eval_count=50)
        return out
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": name, "args": {}}, "thoughtSignature": "sig-abc"}]},
        "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": tokens, "candidatesTokenCount": 50}}


def _final_turn(provider, text="Nothing worth trading.", usage=True):
    r = reply(provider, text, usage=usage)
    if provider == "openrouter" and usage:
        r["usage"]["cost"] = 0.002
    return r


def _tools_ok(net):
    net.on("POST", "/api/show", J(200, {"capabilities": ["completion", "tools"]}))
    net.on("GET", "/api/v1/models", J(200, {"data": [
        {"id": "google/gemini-2.5-flash", "supported_parameters": ["tools"],
         "context_length": 1048576},
        {"id": "some/no-tools-model", "supported_parameters": ["max_tokens"]}]}))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_autopilot_runs_through_the_mcp_rails_on_every_provider(net, pilot, provider):
    _tools_ok(net)
    net.on(*CHAT[provider], [J(200, _tool_turn(provider)), J(200, _final_turn(provider))])
    res = _run(_pcfg(pilot, provider))
    assert res["ok"], res
    r = autopilot.runs(1)[0]
    assert r["provider"] == provider and r["status"] == "ok" and r["steps"] == 1
    assert r["tools"][0]["tool"] == "get_status" and r["tools"][0]["ok"]
    assert "worth trading" in r["summary"]
    assert r["inputTokens"] == 2200 and r["outputTokens"] == 350
    if provider in ("ollama", "lmstudio"):
        assert r["costUsd"] == 0.0
    elif provider == "openrouter":
        assert r["costUsd"] == pytest.approx(0.003)
    else:
        assert r["costUsd"] is None

    bodies = net.bodies(*CHAT[provider])
    first, second = bodies[0], bodies[1]
    if provider == "gemini":
        names = {d["name"] for d in first["tools"][0]["functionDeclarations"]}
    else:
        names = {t["function"]["name"] for t in first["tools"]}
    assert names == {t.name for t in mcp_server.visible_tools(_pcfg(pilot, provider))}
    assert "place_order" not in names
    if provider == "gemini":
        assert second["contents"][1]["parts"][0]["thoughtSignature"] == "sig-abc"
        fr = second["contents"][2]["parts"][0]["functionResponse"]
        assert fr["name"] == "get_status" and "result" in fr["response"]
    elif provider == "ollama":
        assert second["messages"][-1]["role"] == "tool"
        assert second["messages"][-1]["tool_name"] == "get_status"
    else:
        assert second["messages"][-1]["role"] == "tool"
        assert second["messages"][-1]["tool_call_id"] == "c1"


def test_gemini_tool_schemas_are_cut_to_what_gemini_accepts(net, pilot):
    net.on(*CHAT["gemini"], J(200, _final_turn("gemini")))
    _run(_pcfg(pilot, "gemini"))
    decls = net.bodies(*CHAT["gemini"])[0]["tools"][0]["functionDeclarations"]
    blob = json.dumps(decls)
    assert "additionalProperties" not in blob and "$schema" not in blob
    status = next(d for d in decls if d["name"] == "get_status")
    assert "parameters" not in status


@pytest.mark.parametrize("provider,setup,needle", [
    ("ollama", lambda n: n.on("POST", "/api/show", J(200, {"capabilities": ["completion"]})),
     "can't call tools"),
    ("ollama", lambda n: n.on("POST", "/api/show", J(200, {"modelfile": "..."})),
     "Update Ollama"),
    ("ollama", lambda n: n.on("POST", "/api/show", J(404, {"error": "model 'llama3.1:8b' not found"})),
     "ollama pull"),
    ("ollama", lambda n: n.on("POST", "/api/show", _down), "ollama serve"),
    ("lmstudio", lambda n: n.on("GET", "/api/v0/models", J(200, {"data": [
        {"id": "nomic-embed", "type": "embeddings"}]})), "no chat model"),
])
def test_autopilot_refuses_a_model_without_tools_up_front(net, pilot, provider, setup, needle):
    setup(net)
    res = _run(_pcfg(pilot, provider))
    assert not res["ok"] and needle in res["message"], res["message"]
    assert autopilot.runs(1) == []
    assert net.bodies(*CHAT[provider]) == []
    assert autopilot.STATE.last_error == res["message"]


def test_autopilot_refuses_an_openrouter_model_without_tools(net, pilot):
    _tools_ok(net)
    res = _run(_pcfg(pilot, "openrouter", "some/no-tools-model"))
    assert not res["ok"] and "cannot call tools" in res["message"]
    assert autopilot.runs(1) == [] and net.bodies(*CHAT["openrouter"]) == []


def test_autopilot_refuses_a_gemma_model_on_gemini(net, pilot):
    res = _run(_pcfg(pilot, "gemini", "gemma-3-27b-it"))
    assert not res["ok"] and "cannot call tools" in res["message"]
    assert net.requests == []


def test_run_now_refuses_with_the_reason_instead_of_starting(net, pilot, monkeypatch):
    import service
    net.on("POST", "/api/show", J(200, {"capabilities": ["completion"]}))
    _pcfg(pilot, "ollama")
    monkeypatch.setattr(service.STATE, "cfg", dict(pilot["cfg"]))
    res = asyncio.run(service._h_autopilot_run_now({}))
    assert res["ok"] is False and "can't call tools" in res["message"]


def test_a_cloud_provider_without_a_key_is_blocked(net, pilot, monkeypatch):
    monkeypatch.setattr(ai, "has_key", lambda p: False)
    assert "No OpenRouter key" in autopilot.blocked_reason(_pcfg(pilot, "openrouter"))
    assert autopilot.blocked_reason(_pcfg(pilot, "ollama")) is None


@pytest.mark.parametrize("provider", ("ollama", "openrouter", "gemini"))
def test_the_daily_token_budget_binds_on_every_provider(net, pilot, provider):
    _tools_ok(net)
    pilot["cfg"]["autopilot_daily_token_budget"] = 50_000
    net.on(*CHAT[provider], [J(200, _tool_turn(provider, tokens=30_000))])
    _run(_pcfg(pilot, provider))
    r = autopilot.runs(1)[0]
    assert r["status"] == "budget"
    assert len(net.bodies(*CHAT[provider])) == 2
    res = _run(_pcfg(pilot, provider))
    assert not res["ok"] and "token budget" in res["message"]


def test_the_step_limit_binds_on_a_local_provider(net, pilot):
    pilot["cfg"]["autopilot_max_steps"] = 3
    net.on(*CHAT["lmstudio"], [J(200, _tool_turn("lmstudio"))])
    _run(_pcfg(pilot, "lmstudio"))
    r = autopilot.runs(1)[0]
    assert r["status"] == "steps" and r["steps"] == 3
    assert r["model"] == LMS_MODEL


def test_missing_usage_is_estimated_counted_and_said(net, pilot):
    """A local server that reports no usage must not make the token budget
    count zero. The run counts an estimate and its report says so."""
    _tools_ok(net)
    net.on(*CHAT["ollama"], [J(200, _tool_turn("ollama", usage=False)),
                             J(200, _final_turn("ollama", usage=False))])
    _run(_pcfg(pilot, "ollama"))
    r = autopilot.runs(1)[0]
    assert r["status"] == "ok"
    assert r["inputTokens"] > 1000 and r["outputTokens"] > 0
    assert "estimates from text length" in r["summary"]


def test_an_overflowing_local_conversation_stops_instead_of_being_truncated(
        net, pilot, monkeypatch):
    _tools_ok(net)
    cfg = _pcfg(pilot, "ollama")
    run = autopilot._Run(cfg, "manual")
    opening = ap._OllamaToolChat(None, "llama3.1:8b", run.system(), run.tools(),
                                 "Run now. Today is 2026-10-06 12:00 UTC.").request_size()
    monkeypatch.setattr(ap, "_OLLAMA_AGENT_CTX", opening + ap._MAX_TOKENS + 40)
    net.on(*CHAT["ollama"], [J(200, _tool_turn("ollama"))])
    _run(cfg)
    r = autopilot.runs(1)[0]
    assert r["status"] == "context" and r["steps"] == 1
    assert "outgrew" in r["summary"]
    assert len(net.bodies(*CHAT["ollama"])) == 1


def test_autopilot_status_names_the_provider_and_its_token_source(net, pilot):
    st = autopilot.status(_pcfg(pilot, "ollama"))
    assert st["providerLabel"] == "Ollama"
    assert "this machine" in st["tokenAccounting"]


def test_a_provider_error_mid_run_is_recorded_as_the_users_sentence(net, pilot):
    _tools_ok(net)
    net.on(*CHAT["ollama"], [J(200, _tool_turn("ollama")), _down])
    res = _run(_pcfg(pilot, "ollama"))
    assert not res["ok"] and "`ollama serve`" in res["message"]
    assert autopilot.runs(1)[0]["status"] == "error"



def _schema_problems(node, path="", root=True) -> list:
    """Anything Gemini's `parameters` would 400 on."""
    out = []
    if not isinstance(node, dict):
        return out
    for k in node:
        if k not in ap._GEMINI_SCHEMA_KEYS:
            out.append(f"{path}: key {k}")
    if node.get("type") == "object" and not node.get("properties") and not root:
        out.append(f"{path}: OBJECT with no properties")
    for pk, pv in (node.get("properties") or {}).items():
        out += _schema_problems(pv, f"{path}.{pk}", False)
    if "items" in node:
        out += _schema_problems(node["items"], f"{path}[]", False)
    for i, br in enumerate(node.get("anyOf") or []):
        out += _schema_problems(br, f"{path}|{i}", False)
    return out


def test_every_mcp_tool_schema_is_one_gemini_accepts():
    """A nested open-ended object (a config patch) is a 400 for the WHOLE
    request on Gemini, so Autopilot died on its first turn whenever the
    research or settings tools were switched on. Every registered tool --
    including the opt-in workbench ones -- must convert cleanly."""
    import mcp_workbench
    converted = {}
    for t in mcp_server.TOOLS:
        paths: list = []
        schema = ap.gemini_schema(t.spec()["inputSchema"], (), paths)
        assert _schema_problems(schema) == [], (t.name, _schema_problems(schema))
        if paths:
            converted[t.name] = paths
    assert converted["update_engine_config"] == [("patch",)]
    for name in ("backtest_crypto15m", "backtest_signal_following", "backtest_script"):
        assert ("config_patch",) in converted[name], name


def test_gemini_decodes_a_string_patch_back_into_the_object_the_tool_expects(net):
    tool = {"name": "update_engine_config", "description": "Change settings.",
            "inputSchema": {"type": "object", "properties": {
                "patch": {"type": "object"}, "apply_partial": {"type": "boolean"}},
                "required": ["patch"]}}
    chat = ap.open_tool_chat("gemini", GEMINI_KEY, "gemini-3.8-flash", "sys", [tool], "go")
    decl = chat.fn_tools[0]["functionDeclarations"][0]
    assert decl["parameters"]["properties"]["patch"]["type"] == "string"
    raw_args = {"patch": '{"scan_interval_sec": 30}', "apply_partial": True}
    net.on(*CHAT["gemini"], J(200, {"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": "update_engine_config", "args": raw_args},
         "thoughtSignature": "sig"}]}, "finishReason": "STOP"}]}))
    turn = chat.send()
    assert turn.calls[0].args == {"patch": {"scan_interval_sec": 30}, "apply_partial": True}
    assert turn.raw["parts"][0]["functionCall"]["args"]["patch"] == '{"scan_interval_sec": 30}'
    bad = {"patch": "not json"}
    ap._decode_json_args(bad, ("patch",))
    assert bad == {"patch": "not json"}



def test_an_openrouter_choice_error_ends_the_run_as_an_error_not_ok(net, pilot):
    _tools_ok(net)
    net.on(*CHAT["openrouter"], [J(200, _tool_turn("openrouter")), J(200, {
        "choices": [{"finish_reason": "error",
                     "error": {"code": 502, "message": "Upstream provider went away"},
                     "message": {"role": "assistant", "content": ""}}],
        "usage": {"prompt_tokens": 700, "completion_tokens": 5}})])
    res = _run(_pcfg(pilot, "openrouter"))
    assert not res["ok"] and "Upstream provider went away" in res["message"]
    r = autopilot.runs(1)[0]
    assert r["status"] == "error"
    assert r["inputTokens"] == 1000 + 700


def test_a_reply_cut_off_before_anything_is_said_is_not_ok(net, pilot):
    _tools_ok(net)
    net.on(*CHAT["openrouter"], [J(200, {
        "choices": [{"finish_reason": "length",
                     "message": {"role": "assistant", "content": ""}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 4000}})])
    res = _run(_pcfg(pilot, "openrouter"))
    assert not res["ok"] and "ran out of output tokens" in res["message"]
    assert autopilot.runs(1)[0]["status"] == "error"



def test_lmstudio_guard_ignores_the_architectural_max_of_an_unloaded_model(net):
    """A model that isn't loaded has no window yet; LM Studio's JIT load
    picks its own (often 4k). The 128k architectural max used to stand in."""
    net.on("GET", "/api/v0/models", J(200, {"data": [
        {"id": LMS_MODEL, "type": "llm", "state": "not-loaded",
         "max_context_length": 131072}]}))
    msg = _err(net, "lmstudio", J(200, reply("lmstudio", json.dumps(GOOD))))
    assert "isn't loaded" in msg and "Load it" in msg
    assert net.bodies(*CHAT["lmstudio"]) == []
    info = ap.cached_models("lmstudio")[0]
    assert info.context is None and info.public()["maxContext"] == 131072


def test_lmstudio_guard_does_not_trust_a_stale_listing(net):
    """Reloaded in LM Studio with a 2k window since the listing was cached:
    the guard re-reads before trusting it."""
    import time as _t
    ap._LISTED["lmstudio"] = (_t.time() - 300, [ap.ModelInfo(
        id=LMS_MODEL, tools=True, context=32768, loaded=True, kind="llm")])
    net.on("GET", "/api/v0/models", J(200, {"data": [
        {"id": LMS_MODEL, "type": "llm", "state": "loaded", "loaded_context_length": 2048}]}))
    msg = _err(net, "lmstudio", J(200, reply("lmstudio", json.dumps(GOOD))))
    assert "2,048-token context" in msg
    assert net.bodies(*CHAT["lmstudio"]) == []


def test_lmstudio_without_a_reported_window_assumes_a_small_one(net):
    net.on("GET", "/api/v0/models", J(404, {"error": "Unexpected endpoint"}))
    net.on("GET", "/v1/models", J(200, {"data": [{"id": LMS_MODEL, "object": "model"}]}))
    msg = _err(net, "lmstudio", J(200, reply("lmstudio", json.dumps(GOOD))))
    assert "didn't report the context" in msg
    assert net.bodies(*CHAT["lmstudio"]) == []
