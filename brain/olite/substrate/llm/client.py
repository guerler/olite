"""The `llm`-gated port the loop calls: resolve an endpoint, send, parse."""

import copy
import logging
from dataclasses import replace

from ..http import http
from .api import get_adapter
from .providers import resolve

logger = logging.getLogger(__name__)


class Llm:
    def __init__(self, config, manifest):
        self.config = config
        self.manifest = manifest
        self.target = resolve(config)
        self.adapter = get_adapter(self.target.api)
        # The rate comes from the endpoint; one bucket per session, shared by scoped views.
        from ..rate_limiter import TokenBucketRateLimiter

        self._limiter = TokenBucketRateLimiter.from_requests_per_minute(self.target.rate_limit)
        logger.info(
            "llm target: provider=%s model=%s window=%d max_tokens=%d",
            self.target.provider.id,
            self.target.model.id,
            self.target.context_window,
            self.target.max_tokens,
        )

    async def init(self):
        """Ask the endpoint for its context window, when the provider says to."""
        if not self.target.provider.probe_window or self.config.get("ai_context_window"):
            return self
        window = await _probe_window(self.target.base_url)
        if window:
            self.target = replace(self.target, context_window=window)
            logger.info("probed context window: %d", window)
        return self

    def scoped(self, manifest):
        """A narrower view sharing the same rate limiter, so scoping cannot bypass it."""
        view = copy.copy(self)
        view.manifest = manifest
        return view

    async def complete(
        self,
        messages,
        tools=None,
        tool_choice=None,
        parallel_tools=True,
        cancellation=None,
        on_retry=None,
    ):
        self.manifest.require("llm")
        oversized = self.adapter.oversized_tools(self.target, tools)
        if oversized:
            # This endpoint rejects the whole request, not the offending tool.
            names = ", ".join(f"{name} ({size} bytes)" for name, size in oversized)
            raise ValueError(f"Tool schema too large for {self.target.provider.name}: {names}")
        await self._limiter.acquire()
        payload = await http.request(
            method="POST",
            url=self.adapter.url(self.target),
            headers=self.adapter.headers(self.target),
            body=self.adapter.build_request(self.target, messages, tools, tool_choice, parallel_tools),
            signal=cancellation.signal if cancellation else None,
            on_retry=on_retry,
        )
        return self.adapter.parse_reply(payload)


async def _probe_window(base_url):
    """llama.cpp's /props; any other server simply does not answer it."""
    if not base_url:
        return None
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        props = await http.request(method="GET", url=f"{root}/props")
    except Exception:
        logger.debug("context-window probe failed", exc_info=True)
        return None
    settings = (props or {}).get("default_generation_settings") or {}
    window = settings.get("n_ctx")
    return window if isinstance(window, int) and window > 0 else None
