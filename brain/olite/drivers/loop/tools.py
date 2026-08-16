"""Tool surface for the loop driver."""

import json
import logging

from olite.substrate import Confirmation

from . import confusables, galaxy_destructive, galaxy_tools, gtn, notebook

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


def _skills_fetch_schema(skills):
    """Orbit's `skills_fetch` signature: addressed by repo-relative path, not by name."""
    return {
        "type": "function",
        "function": {
            "name": "skills_fetch",
            "description": (
                "Fetch operational know-how from a skills repo. The system prompt's "
                '"Skills repositories" section lists the available repos and the '
                "canonical paths inside each. If `repo` is omitted, the first repo is used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "enum": skills.names(),
                        "description": "Name of the skills repo. Omit to use the default (first) repo.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path inside the repo, e.g. "
                            "'collection-manipulation/SKILL.md', "
                            "'galaxy-integration/mcp-reference/gotchas.md'."
                        ),
                    },
                },
                "required": ["path"],
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
    def __init__(self, substrate, processes=None, skills=None, confirmation=None):
        self.substrate = substrate
        self.processes = processes
        self.skills = skills
        # How the surface reaches the user for an approval. Unavailable by default,
        self.confirmation = confirmation or Confirmation()
        # Renderable artifacts produced by tools this turn (e.g. a chart from a
        self.artifacts = []

    def schemas(self):
        tools = [RUN_PYTHON]
        tools.extend(galaxy_tools.tool_schemas(self.substrate.manifest))
        tools.extend(notebook.tool_schemas(self.substrate.manifest))
        # GTN is public training material on one allowlisted host, not Galaxy, so it
        tools.extend(gtn.tool_schemas())
        tools.append(FINISH)
        if self.skills and self.skills.names():
            tools.append(_skills_fetch_schema(self.skills))
        if self.processes and self.processes.names():
            tools.append(_run_process_schema(self.processes))
        return tools

    def _missing_required(self, name, args):
        """Required parameters the call left out, per the schema it was given."""
        schema = next((t for t in self.schemas() if t["function"]["name"] == name), None)
        if schema is None:
            return []  # unknown name: not ours to validate, and it may still fold
        required = schema["function"].get("parameters", {}).get("required") or []
        return [key for key in required if key not in args]

    async def dispatch(self, name, args):
        logger.info("tool %s(%s)", name, _brief(args))
        missing = self._missing_required(name, args)
        if missing:
            logger.info("  -> missing required %s", missing)
            return f"Tool '{name}' was not called: missing required parameter(s): {', '.join(missing)}."
        try:
            result = await self._dispatch(name, args)
            logger.info("  -> %s", _brief(result))
            return result
        except Exception as e:
            logger.warning("tool %s raised: %s", name, e)
            return f"Tool '{name}' raised: {e}"

    async def _dispatch(self, name, args):
        # Destructive Galaxy ops are refused before anything else, for the reason
        destructive = galaxy_destructive.classify(name, args)
        if destructive is not None:
            refusal = await self._gate_destructive(name, destructive)
            if refusal is not None:
                return refusal

        if name == "run_python":
            return self.substrate.local.run(args.get("code", ""))
        if name == "run_process":
            return await self._run_process(args)
        if name == "skills_fetch":
            return self._skills_fetch(args)
        if name == "finish":
            return args.get("summary", "done")
        handler = galaxy_tools.get_handler(name) or notebook.get_handler(name)
        if handler:
            return json.dumps(await handler(self.substrate.galaxy, args), default=str)
        gtn_handler = gtn.get_handler(name)
        if gtn_handler:
            return json.dumps(await gtn_handler(args), default=str)
        # Last resort before giving up: the name may be right but spelled with
        folded = self._fold_tool_name(name)
        if folded:
            logger.info("tool name %r folded to %r (unicode confusables)", name, folded)
            return await self._dispatch(folded, args)
        return f"Unknown tool: {name}"

    async def _gate_destructive(self, name, op):
        """Why this destructive operation must not run, or None if the user said yes."""
        headline = galaxy_destructive.describe(op)
        if not self.confirmation.available:
            logger.warning("refused destructive op %s: no way to ask", name)
            return (
                f"Refused: {headline} There is no interactive session to approve it. "
                "Tell the user what you wanted to do and let them do it in the Galaxy interface."
            )
        if not await self.confirmation.ask("Confirm destructive operation", headline):
            logger.info("user declined destructive op %s", name)
            return f"Refused: {headline} The user declined."
        logger.warning("user approved destructive op %s: %s", name, op["kind"])
        return None

    def _fold_tool_name(self, name):
        """The advertised tool `name` was meant to be, or None."""
        if not confusables.has_confusables(name or ""):
            return None
        advertised = [t["function"]["name"] for t in self.schemas()]
        return confusables.find_match(name, advertised)

    def _skills_fetch(self, args):
        """Second half of progressive disclosure: hand over one file, whole."""
        path = args.get("path")
        repo_name = args.get("repo")
        if not self.skills:
            return "Error: No skills repos are available."
        repo = self.skills.find(repo_name)
        if repo is None:
            return f"Error: Skills repo \"{repo_name}\" is not configured. Available: {', '.join(self.skills.names())}."
        text = repo.read(path)
        if text is None:
            return (
                f'Error: Failed to fetch "{path}" from {repo.name}. '
                "Check the path against the skills router in the system prompt."
            )
        return text

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
