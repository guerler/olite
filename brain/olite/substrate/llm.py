"""LLM access through the Galaxy chat proxy."""

import logging

from .completions import completions_post
from .rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT = 30


class Llm:
    def __init__(self, config, manifest):
        self.config = config
        self.manifest = manifest
        rate = config.get("ai_rate_limit", DEFAULT_RATE_LIMIT)
        self._limiter = TokenBucketRateLimiter.from_requests_per_minute(rate)

    async def complete(self, messages, tools=None, tool_choice=None, parallel_tools=True):
        self.manifest.require("llm")
        await self._limiter.acquire()
        payload = {
            "ai_base_url": self.config.get("ai_base_url"),
            "ai_api_key": self.config.get("ai_api_key"),
            "ai_model": self.config.get("ai_model"),
            "messages": messages,
            "parallel_tools": parallel_tools,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        return await completions_post(payload)
