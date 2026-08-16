"""The `llm`-gated port the loop calls: resolve an endpoint, send, parse."""

import copy
import logging

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
        # The rate comes from the endpoint; the bucket stays owned here so a scoped
        # view cannot hand a process a fresh budget.
        from ..rate_limiter import TokenBucketRateLimiter

        self._limiter = TokenBucketRateLimiter.from_requests_per_minute(self.target.rate_limit)
        logger.info(
            "llm target: provider=%s model=%s window=%d max_tokens=%d",
            self.target.provider.id,
            self.target.model.id,
            self.target.context_window,
            self.target.max_tokens,
        )

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
