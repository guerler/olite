"""Which endpoint a config resolves to, and what that endpoint's properties are."""

import pytest

from olite.substrate.llm import REGISTRY, Limits, Model, Provider, get_adapter, resolve
from olite.substrate.llm.providers import DEFAULT_CONTEXT_WINDOW, DEFAULT_MAX_TOKENS


# --- resolution ----------------------------------------------------------------


def test_galaxy_is_the_default():
    """Production reaches the model through Galaxy's proxy, not a provider."""
    target = resolve({})
    assert target.provider.id == "galaxy"
    assert target.base_url is None


def test_a_named_provider_supplies_its_own_endpoint():
    target = resolve({"ai_provider": "gemini", "ai_model": "gemini-3.7-flash"})
    assert target.base_url.endswith("/v1beta/openai")
    assert target.context_window == 1_000_000


def test_a_base_url_alone_means_a_custom_provider():
    """pi's rule: the presence of a base URL marks a custom entry."""
    target = resolve({"ai_base_url": "http://example.invalid/v1"})
    assert target.provider.id == "custom"
    assert target.base_url == "http://example.invalid/v1"


def test_an_unknown_provider_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        resolve({"ai_provider": "nope"})
    assert "nope" in str(e.value) and "gemini" in str(e.value)


def test_an_explicit_base_url_overrides_the_provider_default():
    target = resolve({"ai_provider": "gemini", "ai_base_url": "http://proxy.invalid/v1"})
    assert target.base_url == "http://proxy.invalid/v1"


# --- the numbers the endpoint supplies -------------------------------------------


def test_galaxys_token_cap_reaches_the_request():
    """The proxy caps max_tokens at 8192; asking for more just gets clamped."""
    target = resolve({"ai_max_tokens": 16384})
    assert target.max_tokens == 8192


def test_a_model_supplies_its_own_window_so_nothing_has_to_be_configured():
    assert resolve({"ai_provider": "gemini", "ai_model": "gemini-3.7-flash"}).context_window == 1_000_000


def test_a_provider_supplies_a_window_when_the_model_is_unknown():
    """llama.cpp ignores the model name, so the window belongs to the server."""
    assert resolve({"ai_provider": "local", "ai_model": "whatever.gguf"}).context_window == 32000


def test_config_still_wins_over_everything():
    target = resolve({"ai_provider": "local", "ai_context_window": 8000})
    assert target.context_window == 8000


def test_an_unknown_everything_falls_back_to_the_defaults():
    target = resolve({"ai_base_url": "http://x.invalid", "ai_model": "mystery"})
    assert target.context_window == DEFAULT_CONTEXT_WINDOW
    assert target.max_tokens == DEFAULT_MAX_TOKENS


def test_the_rate_limit_comes_from_the_endpoint():
    """Measured: Gemini's free tier is 5/minute, which is a property of the endpoint."""
    assert resolve({"ai_provider": "gemini"}).rate_limit == 5
    assert resolve({"ai_provider": "deepseek"}).rate_limit == 30
    assert resolve({"ai_provider": "gemini", "ai_rate_limit": 60}).rate_limit == 60


# --- the dialect seam ------------------------------------------------------------


def test_every_registered_provider_names_a_dialect_that_exists():
    for provider in REGISTRY.values():
        assert get_adapter(provider.api) is not None


def test_an_unknown_dialect_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        get_adapter("anthropic-messages")
    assert "anthropic-messages" in str(e.value)


def test_the_adapter_builds_and_parses_one_round_trip():
    target = resolve({"ai_provider": "gemini", "ai_model": "gemini-3.7-flash", "ai_api_key": "k"})
    adapter = get_adapter(target.api)

    body = adapter.build_request(target, [{"role": "user", "content": "hi"}], tools=None)
    assert body["model"] == "gemini-3.7-flash"
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS
    assert adapter.url(target).endswith("/chat/completions")
    assert adapter.headers(target)["Authorization"] == "Bearer k"

    reply = adapter.parse_reply(
        {
            "choices": [{"finish_reason": "stop", "message": {"content": "hello", "tool_calls": []}}],
            "usage": {"total_tokens": 12},
        }
    )
    assert reply.content == "hello"
    assert reply.finish_reason == "stop"
    assert reply.usage["total_tokens"] == 12


def test_a_provider_can_opt_out_of_sampling_parameters():
    """Some models reject temperature and top_p; that is a provider fact."""
    plain = Provider(id="p", base_url="http://x.invalid")
    picky = Provider(id="q", base_url="http://x.invalid", compat={"sampling": False})
    adapter = get_adapter("openai-completions")

    from olite.substrate.llm.providers import Target

    def target_for(provider):
        return Target(provider, Model("m"), "http://x.invalid", None, 1000, 100, 30)

    assert "temperature" in adapter.build_request(target_for(plain), [], None)
    assert "temperature" not in adapter.build_request(target_for(picky), [], None)


def test_a_model_setting_beats_a_provider_setting():
    provider = Provider(id="p", compat={"sampling": True})
    model = Model("m", compat={"sampling": False})
    from olite.substrate.llm.providers import Target

    assert Target(provider, model, None, None, 1000, 100, 30).compat("sampling") is False


# --- endpoint limits the brain can act on ----------------------------------------


def test_an_oversized_tool_schema_is_caught_before_the_request():
    """Galaxy rejects the whole request, not the offending tool, so we check first."""
    target = resolve({})
    adapter = get_adapter(target.api)
    fat = {"function": {"name": "huge", "description": "x" * 20000}}

    assert adapter.oversized_tools(target, [fat])
    assert adapter.oversized_tools(target, [{"function": {"name": "ok"}}]) == []


def test_an_endpoint_without_a_stated_cap_accepts_anything():
    target = resolve({"ai_base_url": "http://x.invalid"})
    adapter = get_adapter(target.api)
    assert adapter.oversized_tools(target, [{"function": {"name": "huge", "description": "x" * 99999}}]) == []


def test_galaxys_limits_are_recorded():
    limits = REGISTRY["galaxy"].limits
    assert (limits.max_tokens, limits.max_tool_bytes, limits.max_tools) == (8192, 16384, 128)
    assert isinstance(limits, Limits)
