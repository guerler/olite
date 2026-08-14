"""Tool surface for the loop driver."""

import json
import logging

from . import galaxy_tools

logger = logging.getLogger(__name__)


def _brief(value, limit=300):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


RUN_PYTHON = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Run Python locally in the browser (Pyodide). numpy and pandas are available; "
            "state persists across calls. Returns the last expression value and stdout. "
            "This runs in the browser, NOT on Galaxy - it cannot import galaxy."
        ),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
}

FINISH = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Call when the task is complete, with a short summary.",
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
}


def _run_process_schema(processes):
    return {
        "type": "function",
        "function": {
            "name": "run_process",
            "description": (
                "Run a crystallized process: a validated, multi-step pipeline. "
                "Prefer these over improvising when one fits.\nAvailable:\n" + processes.catalog_text()
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": processes.names()},
                    "inputs": {"type": "object", "description": "Process inputs."},
                },
                "required": ["name", "inputs"],
            },
        },
    }


class ToolSurface:
    def __init__(self, substrate, processes=None):
        self.substrate = substrate
        self.processes = processes
        # Renderable artifacts produced by tools this turn (e.g. a chart from a
        self.artifacts = []

    def schemas(self):
        tools = [RUN_PYTHON]
        tools.extend(galaxy_tools.tool_schemas(self.substrate.manifest))
        tools.append(FINISH)
        if self.processes and self.processes.names():
            tools.append(_run_process_schema(self.processes))
        return tools

    async def dispatch(self, name, args):
        logger.info("tool %s(%s)", name, _brief(args))
        try:
            result = await self._dispatch(name, args)
            logger.info("  -> %s", _brief(result))
            return result
        except Exception as e:
            logger.warning("tool %s raised: %s", name, e)
            return f"Tool '{name}' raised: {e}"

    async def _dispatch(self, name, args):
        if name == "run_python":
            return self.substrate.local.run(args.get("code", ""))
        if name == "run_process":
            return await self._run_process(args)
        if name == "finish":
            return args.get("summary", "done")
        handler = galaxy_tools.get_handler(name)
        if handler:
            return json.dumps(await handler(self.substrate.galaxy, args), default=str)
        return f"Unknown tool: {name}"

    async def _run_process(self, args):
        proc = self.processes.get(args.get("name")) if self.processes else None
        if not proc:
            return json.dumps({"error": f"unknown process: {args.get('name')}"})
        from olite.drivers.graph import GraphDriver
        import olite.registry.materializers  # noqa: F401  (registers materializers + vintent bridge)

        # Least privilege: the process runs under its own declared manifest,
        substrate = self.substrate.scoped(proc.capabilities)
        result = await GraphDriver(substrate).run(proc.graph, args.get("inputs") or {})
        last = result.get("last") or {}
        # Surface a failed graph to the model rather than returning a bare null.
        if last.get("ok") is False:
            return json.dumps({"ok": False, "error": last.get("error")})
        output = last.get("result")
        # A process may return a renderable artifact. Route it to the shell out of
        if isinstance(output, dict) and isinstance(output.get("artifact"), dict):
            art = dict(output["artifact"])
            self.artifacts.append(art)
            payload = {k: v for k, v in output.items() if k != "artifact"}
            payload["ok"] = True
            payload["artifact"] = {"kind": art.get("kind"), "title": art.get("title")}
            return json.dumps(payload, default=str)
        return json.dumps(output)
