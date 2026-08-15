"""The loop driver: olite's open-ended agent loop (Orbit parity)."""

import json
import logging

from .tools import ToolSurface

logger = logging.getLogger(__name__)

# Neither pi nor loom caps the number of turns: pi's loop runs until the model stops
MAX_STEPS = 40
# The provider's finish reason when the output hit the token limit. pi checks for it
TRUNCATED = "length"
TRUNCATED_ERROR = (
    'Tool call "{name}" was not executed: the response hit the output token limit, so '
    "its arguments may be truncated. Re-issue the tool call with complete arguments."
)
# Arguments that are not valid JSON are reported back the same way rather than
MALFORMED_ARGS_ERROR = 'Tool call "{name}" was not executed: its arguments are not valid JSON ({detail}).'
# Tool results are NOT truncated, matching Orbit: `skills_fetch` returns the fetched


class LoopDriver:
    def __init__(self, substrate, processes=None, skills=None):
        self.substrate = substrate
        self.tools = ToolSurface(substrate, processes, skills)

    async def run(self, transcripts, on_event=None):
        messages = [dict(m) for m in transcripts]
        logs = []
        done = False
        exhausted = True  # cleared by whichever branch ends the loop deliberately

        for _ in range(MAX_STEPS):
            reply = await self.substrate.llm.complete(messages, tools=self.tools.schemas())
            choice = reply.get("choices", [{}])[0]
            message = choice.get("message", {})
            truncated = choice.get("finish_reason") == TRUNCATED
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
                exhausted = False
                break

            terminating = []
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name")
                call_id = call.get("id")

                refusal = None
                args = {}
                if truncated:
                    refusal = TRUNCATED_ERROR.format(name=name)
                else:
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError as e:
                        refusal = MALFORMED_ARGS_ERROR.format(name=name, detail=e)

                # Live tool progress: mirror the pi tool_execution_start/end boundary
                _emit(on_event, {"type": "tool_start", "id": call_id, "name": name})
                if refusal is not None:
                    logs.append(f"refuse {name}: {refusal}")
                    content = refusal
                else:
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

                # Only an executed `finish` ends the loop. A refused one was never
                terminating.append(name == "finish" and refusal is None)

            # pi ends the turn only when EVERY call in the batch asked to
            if terminating and all(terminating):
                done = True
                exhausted = False
                break

        return {
            "logs": logs,
            "messages": messages,
            "done": done,
            # The turn hit MAX_STEPS with the model still calling tools. The shell
            "exhausted": exhausted,
            "artifacts": self.tools.artifacts,
        }


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
