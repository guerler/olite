"""The loop driver: olite's open-ended agent loop (Orbit parity)."""

import json
import logging

from olite.substrate import Cancellation

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
# pi's wording for a call dropped because the run was aborted.
ABORTED_ERROR = "Operation aborted"
# Tool results are NOT truncated, matching Orbit: `skills_fetch` returns the fetched


class LoopDriver:
    def __init__(self, substrate, processes=None, skills=None, confirmation=None):
        self.substrate = substrate
        self.tools = ToolSurface(substrate, processes, skills, confirmation)

    async def run(self, transcripts, on_event=None, cancellation=None):
        messages = [dict(m) for m in transcripts]
        logs = []
        done = False
        exhausted = True  # cleared by whichever branch ends the loop deliberately
        aborted = False
        cancellation = cancellation or Cancellation()

        for _ in range(MAX_STEPS):
            if cancellation.aborted:
                aborted, exhausted = True, False
                break

            try:
                reply = await self.substrate.llm.complete(
                    messages, tools=self.tools.schemas(), cancellation=cancellation
                )
            except Exception:
                # A cancelled fetch raises. Whether this exception IS the abort is
                if not cancellation.aborted:
                    raise
                aborted, exhausted = True, False
                break

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
                if cancellation.aborted:
                    # pi checks the signal between tools and stops executing. It can
                    refusal = ABORTED_ERROR
                elif truncated:
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
                    content, is_error = refusal, True
                else:
                    logs.append(f"call {name}({_brief(args)})")
                    outcome = await self.tools.dispatch(name, args)
                    logs.append(f"  -> {_brief(outcome.content)}")
                    content, is_error = outcome.text, outcome.is_error
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": content,
                    }
                )
                # `is_error` rides the event as pi carries `isError` on
                _emit(
                    on_event,
                    {"type": "tool_end", "id": call_id, "name": name, "content": content, "is_error": is_error},
                )

                # Only an executed `finish` ends the loop. A refused one was never
                terminating.append(name == "finish" and refusal is None)

            # pi ends the turn only when EVERY call in the batch asked to
            if terminating and all(terminating):
                done = True
                exhausted = False
                break

            if cancellation.aborted:
                aborted, exhausted = True, False
                break

        return {
            "logs": logs,
            "messages": messages,
            "done": done,
            # The user pressed Stop. Distinct from `exhausted`: one is the user
            "aborted": aborted,
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
