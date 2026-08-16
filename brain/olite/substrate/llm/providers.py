"""Which endpoint olite talks to, and what that endpoint's properties are.

Modelled on pi's `createProvider`: an entry names its dialect, its base URL, where its
key comes from, and the models it serves. olite adds `limits`, because an endpoint's
caps are facts the brain has to plan around rather than discover in production.
"""

import os

# Requested per reply when nothing narrower applies.
DEFAULT_MAX_TOKENS = 16384
# Assumed when neither the model nor the provider states one.
DEFAULT_CONTEXT_WINDOW = 128000
DEFAULT_RATE_LIMIT = 30


class Limits:
    """What an endpoint refuses, as opposed to what a model cannot do."""

    def __init__(self, max_tokens=None, max_tool_bytes=None, max_tools=None):
        self.max_tokens = max_tokens
        self.max_tool_bytes = max_tool_bytes
        self.max_tools = max_tools


class Model:
    def __init__(self, id, context_window=None, max_tokens=None, compat=None):
        self.id = id
        self.context_window = context_window
        self.max_tokens = max_tokens
        self.compat = compat or {}


class Provider:
    def __init__(
        self,
        id,
        name=None,
        api="openai-completions",
        base_url=None,
        auth_env=None,
        limits=None,
        models=None,
        context_window=None,
        rate_limit=None,
        compat=None,
    ):
        self.id = id
        self.name = name or id
        self.api = api
        self.base_url = base_url
        self.auth_env = auth_env
        self.limits = limits or Limits()
        self.models = models or {}
        self.context_window = context_window
        self.rate_limit = rate_limit
        self.compat = compat or {}

    def model(self, model_id):
        """The named model, or a bare record so an unknown id still resolves."""
        return self.models.get(model_id) or Model(model_id)


# Galaxy's own caps, read from lib/galaxy/webapps/galaxy/api/plugins.py. Hard-coded
# because Galaxy exposes no endpoint for them; revisit if it ever does.
GALAXY = Provider(
    id="galaxy",
    name="Galaxy chat proxy",
    limits=Limits(max_tokens=8192, max_tool_bytes=16384, max_tools=128),
)

GEMINI = Provider(
    id="gemini",
    name="Google Gemini",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    auth_env="GEMINI_KEY",
    # Free tier is 5 requests/minute; measured, not read off a docs page.
    rate_limit=5,
    models={
        "gemini-3.7-flash": Model("gemini-3.7-flash", context_window=1_000_000),
        "gemini-3.1-flash-lite": Model("gemini-3.1-flash-lite", context_window=1_000_000),
    },
)

DEEPSEEK = Provider(
    id="deepseek",
    name="DeepSeek",
    base_url="https://api.deepseek.com/v1",
    auth_env="DEEPSEEK_KEY",
    models={"deepseek-v4-flash": Model("deepseek-v4-flash", context_window=1_000_000)},
)

# llama.cpp and Ollama both serve here and ignore the model name, so the window is a
# property of whatever is loaded rather than of any model id.
LOCAL = Provider(
    id="local",
    name="Local OpenAI-compatible server",
    base_url="http://127.0.0.1:11434/v1",
    context_window=32000,
)

REGISTRY = {p.id: p for p in (GALAXY, GEMINI, DEEPSEEK, LOCAL)}


class Target:
    """One resolved endpoint: everything a request needs, already reconciled."""

    def __init__(self, provider, model, base_url, api_key, context_window, max_tokens, rate_limit):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.context_window = context_window
        self.max_tokens = max_tokens
        self.rate_limit = rate_limit

    @property
    def api(self):
        return self.provider.api

    @property
    def limits(self):
        return self.provider.limits

    def compat(self, key, default=None):
        """Model settings win over provider settings."""
        if key in self.model.compat:
            return self.model.compat[key]
        return self.provider.compat.get(key, default)


def _first(*values):
    for value in values:
        if value:
            return value
    return None


def resolve(config):
    """The endpoint this config points at.

    `ai_provider` names a registry entry; failing that a base URL means a custom
    provider, as in pi; failing that it is Galaxy's proxy.
    """
    config = config or {}
    named = config.get("ai_provider")
    base_url = config.get("ai_base_url")

    if named:
        provider = REGISTRY.get(named)
        if provider is None:
            known = ", ".join(sorted(REGISTRY))
            raise ValueError(f"Unknown ai_provider {named!r}. Known: {known}.")
    elif base_url:
        provider = Provider(id="custom", name="Custom endpoint", base_url=base_url)
    else:
        provider = GALAXY

    model = provider.model(config.get("ai_model"))
    max_tokens = min(
        _first(config.get("ai_max_tokens"), model.max_tokens, DEFAULT_MAX_TOKENS),
        provider.limits.max_tokens or DEFAULT_MAX_TOKENS,
    )
    return Target(
        provider=provider,
        model=model,
        base_url=_first(base_url, provider.base_url),
        api_key=_first(config.get("ai_api_key"), _from_env(provider.auth_env)),
        context_window=_first(
            config.get("ai_context_window"),
            model.context_window,
            provider.context_window,
            DEFAULT_CONTEXT_WINDOW,
        ),
        max_tokens=max_tokens,
        rate_limit=_first(config.get("ai_rate_limit"), provider.rate_limit, DEFAULT_RATE_LIMIT),
    )


def _from_env(name):
    return os.environ.get(name) if name else None
