"""Drive olite's brain headlessly for one scenario."""

import asyncio
import json
import os

from olite import prompt
from olite.drivers import LoopDriver
from olite.registry import ProcessRegistry, SkillRegistry
from olite.runtime import _inject_context
from olite.substrate import Substrate
from olite.substrate.llm import REGISTRY


class StubGalaxy:
    """A Galaxy that answers plausibly and records what was asked."""

    def __init__(self):
        self.calls = []

    async def get(self, path):
        self.calls.append(("GET", path))
        if "api/histories" in path:
            return [{"id": "hist1", "name": "Eval history", "state": "ok"}]
        if "api/tools" in path:
            return []
        if "api/pages" in path:
            return []
        return {}

    async def post(self, path, body=None):
        self.calls.append(("POST", path, body))
        if path.endswith("api/pages"):
            return {"id": "page1", "slug": (body or {}).get("slug"), "title": (body or {}).get("title")}
        return {"id": "obj1", "jobs": [{"id": "job1", "state": "new"}]}

    async def put(self, path, body=None):
        self.calls.append(("PUT", path, body))
        return {"id": "obj1"}

    async def delete(self, path):
        self.calls.append(("DELETE", path))
        return {}


class RunResult:
    def __init__(self, messages, logs, tools_called, error=None, status_code=None):
        self.messages = messages
        self.logs = logs
        self.tools_called = tools_called
        self.error = error
        # The provider's HTTP status, preserved so grading never sniffs the message.
        self.status_code = status_code

    @property
    def chat_text(self):
        """Everything the agent said, in order — what a user would have read."""
        return "\n\n".join(
            m.get("content") or "" for m in self.messages if m.get("role") == "assistant" and m.get("content")
        )


def build_config(model):
    """Resolve through the brain's provider registry, so evals and the app agree."""
    base = model.get("baseUrl") or ""
    if base.startswith("${") and base.endswith("}"):
        base = os.environ.get(base[2:-1], "")
    config = {
        "galaxy_root": "http://stub.invalid/",
        "ai_provider": model.get("provider"),
        "ai_model": model["model"],
        # Write is granted, or "did not execute" would assert about an unadvertised tool.
        "capabilities": ["llm", "local", "read", "write"],
    }
    if base:
        config["ai_base_url"] = base.rstrip("/")
    key = _api_key(model)
    if key:
        config["ai_api_key"] = key
    return config


def _api_key(model):
    """The registry names the env var; envRequires is the fallback for custom entries."""
    provider = REGISTRY.get(model.get("provider"))
    if provider and provider.auth_env:
        return os.environ.get(provider.auth_env, "")
    for name in model.get("envRequires", []):
        if name.endswith("_KEY"):
            return os.environ.get(name, "")
    return ""


async def _run(scenario, model):
    substrate = Substrate(build_config(model))
    # No catalog init: these scenarios exercise the loop, not the graph driver.
    substrate.galaxy = StubGalaxy()

    processes = ProcessRegistry().load_packaged()
    skills = SkillRegistry().load_packaged()
    driver = LoopDriver(substrate, processes, skills)

    context = "\n\n".join(t for t in (prompt.system_text(), skills.router_text()) if t)
    transcripts = _inject_context(
        [{"role": "system", "content": scenario.get("systemPrompt", "You are olite.")}], context
    )

    tools_called = []
    messages = transcripts
    logs = []
    for turn in scenario["inputs"]:
        messages = [*messages, {"role": "user", "content": turn}]
        result = await driver.run(messages, lambda ev: _note(ev, tools_called))
        messages = result.get("messages") or messages
        logs.extend(result.get("logs") or [])
    return RunResult(messages, logs, tools_called)


def _note(event, sink):
    if event.get("type") == "tool_start" and event.get("name"):
        sink.append(event["name"])


def run_scenario(scenario, model):
    timeout = (scenario.get("timeoutMs") or 150_000) / 1000

    async def guarded():
        return await asyncio.wait_for(_run(scenario, model), timeout=timeout)

    try:
        return asyncio.run(guarded())
    except asyncio.TimeoutError:
        return RunResult([], [], [], error=f"timed out after {timeout:.0f}s")
    except Exception as e:  # a provider error is a run outcome, not a harness crash
        return RunResult(
            [], [], [], error=f"{type(e).__name__}: {e}", status_code=getattr(e, "status_code", None)
        )


def load_scenarios(root, only=None):
    out = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, "scenario.json")
        if not os.path.isfile(path):
            continue
        if only and only not in entry:
            continue
        with open(path) as f:
            data = json.load(f)
        data["id"] = entry
        out.append(data)
    return out
