"""Whole-layer seams: things compared as a *set* rather than symbol by symbol.

The per-symbol rows in registry.json cover prompt text. These cover the three layers that
were audited by hand and would otherwise rot the same way the prompt audit did: loom's eval
scenarios, the Galaxy tool surface, and the vendored skills corpus.

Each layer stores the upstream state it was certified against, so `check.py` runs offline.
Refreshing that state (`--refresh`) is the deliberate act of re-certifying.
"""

import ast
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import extract  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _fp(text):
    return hashlib.sha256(" ".join((text or "").split()).encode()).hexdigest()[:16]


def loom_scenarios(loom_root):
    """Fingerprint every loom scenario, so a changed or added scenario is visible."""
    out = {}
    base = pathlib.Path(loom_root) / "evals/scenarios"
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        f = d / "scenario.json"
        if f.exists():
            out[d.name] = _fp(f.read_text())
    return out


def mcp_tool_table(server_py):
    """name -> fingerprint of (description, parameter names) for each @mcp.tool."""
    tree = ast.parse(pathlib.Path(server_py).read_text())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any("tool" in ast.unparse(d) for d in node.decorator_list):
                doc = (ast.get_docstring(node) or "").strip()
                args = sorted(a.arg for a in node.args.args if a.arg != "self")
                out[node.name] = _fp(doc + "|" + ",".join(args))
    return out


def olite_tool_table():
    sys.path.insert(0, str(ROOT / "brain"))
    from olite.drivers.loop import galaxy_tools as gt

    out = {}
    for t in gt.TOOLS:
        fn = t["schema"].get("function", t["schema"])
        desc = fn.get("description", "")
        props = sorted((fn.get("parameters") or {}).get("properties") or {})
        out[t["name"]] = _fp(desc + "|" + ",".join(props))
    return out


def skills_manifest():
    """The vendored Orbit corpus: lock pin plus a hash per file."""
    lock = json.loads((ROOT / "skills.lock.json").read_text())
    base = ROOT / "brain/olite/registry/skills/galaxy-skills"
    files = {}
    for f in sorted(base.rglob("*.md")):
        files[str(f.relative_to(base))] = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
    return {"repo": lock["repo"], "ref": lock["ref"], "sha": lock["sha"], "files": files}
