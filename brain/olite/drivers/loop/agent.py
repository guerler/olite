"""The loop driver: olite's open-ended agent loop (Orbit parity)."""

import json
import logging

from .tools import ToolSurface

logger = logging.getLogger(__name__)

MAX_STEPS = 12
# Tool results are NOT truncated, matching Orbit: `skills_fetch` returns the fetched


class LoopDriver:
    def __init__(self, substrate, processes=None, skills=None):
        self.substrate = substrate
        self.tools = ToolSurface(substrate, processes, skills)

    async def run(self, transcripts, on_event=None):
        messages = [dict(m) for m in transcripts]
        logs = []
        done = False

        for _ in range(MAX_STEPS):
            reply = await self.substrate.llm.complete(messages, tools=self.tools.schemas())
            message = reply.get("choices", [{}])[0].get("message", {})
            tool_calls = message.get("tool_calls") or []

            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )

            if not tool_calls:
                if message.get("content"):
                    logs.append(f"assistant: {message['content']}")
                break

            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name")
                call_id = call.get("id")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                # Live tool progress: mirror the pi tool_execution_start/end boundary
                _emit(on_event, {"type": "tool_start", "id": call_id, "name": name})
                logs.append(f"call {name}({_brief(args)})")
                result = await self.tools.dispatch(name, args)
                logs.append(f"  -> {_brief(result)}")

                content = result if isinstance(result, str) else json.dumps(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": content,
                    }
                )
                _emit(on_event, {"type": "tool_end", "id": call_id, "name": name, "content": content})

                if name == "finish":
                    done = True

            if done:
                break

        return {"logs": logs, "messages": messages, "done": done, "artifacts": self.tools.artifacts}


def _emit(on_event, event):
    """Deliver a progress event to the optional listener; never let it break the loop."""
    if on_event is None:
        return
    try:
        on_event(event)
    except Exception:
        logger.debug("on_event listener raised", exc_info=True)


def _brief(value, limit=200):
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[:limit] + "…"
