"""The graph driver's registry: the interface the handlers expect, composed over"""

import json
import logging

from olite.substrate.retry import retry_async

from .agents import Agents
from .exceptions import NodeExecutionError

logger = logging.getLogger(__name__)

REASON_MAX_RETRIES = 3
REASON_INITIAL_BACKOFF = 2.0


class Registry:
    def __init__(self, substrate):
        self.substrate = substrate
        self.agents = Agents()

    # --- API: delegate to the capability-gated catalog ---

    async def call_api(self, ctx, spec):
        return await self.substrate.catalog.call(spec["target"], spec.get("input", {}))

    # --- Reasoning: text output ---

    async def reason(self, prompt, input):
        messages = [
            {
                "role": "user",
                "content": (
                    prompt
                    + "\n\nRespond with TEXT ONLY.\n"
                    + "Do not include JSON, markdown, or structured data.\n"
                    + "Do not include explanations about your reasoning process."
                ),
            },
            {"role": "user", "content": json.dumps(input)},
        ]

        async def attempt():
            reply = await self.substrate.llm.complete(messages)
            content = reply.get("choices", [{}])[0].get("message", {}).get("content")
            if not content or not content.strip():
                raise NodeExecutionError("Reasoning node produced empty output")
            return content

        def on_retry(e, attempt_no, backoff):
            logger.warning("reason retry %d/%d in %ss: %s", attempt_no, REASON_MAX_RETRIES, backoff, e)

        try:
            return await retry_async(
                attempt,
                max_retries=REASON_MAX_RETRIES,
                initial_backoff=REASON_INITIAL_BACKOFF,
                retryable=lambda e: not isinstance(e, NodeExecutionError),
                on_retry=on_retry,
            )
        except NodeExecutionError:
            raise
        except Exception as e:
            raise NodeExecutionError(f"Reasoning failed after {REASON_MAX_RETRIES} attempts: {e}")

    # --- Reasoning: structured JSON output (raw string for the caller to parse) ---

    async def reason_structured(self, prompt, schema):
        schema_str = json.dumps(schema, indent=2)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a structured output assistant. "
                    "You MUST respond with valid JSON only, no additional text. "
                    "Your response must conform to the provided schema."
                ),
            },
            {"role": "user", "content": f"{prompt}\n\nRequired JSON Schema:\n{schema_str}"},
        ]
        reply = await self.substrate.llm.complete(messages)
        content = reply.get("choices", [{}])[0].get("message", {}).get("content")
        if not content or not content.strip():
            raise NodeExecutionError("LLM returned empty content")
        return _unfence(content)


def _unfence(content):
    """Return the JSON body of an LLM reply, unwrapping a ```json ... ``` code fence."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    newline = text.find("\n")
    text = text[newline + 1:] if newline != -1 else text[3:]
    fence = text.rfind("```")
    if fence != -1:
        text = text[:fence]
    return text.strip()
