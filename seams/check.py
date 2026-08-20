"""Check olite's seams against loom. Exits non-zero when something needs a decision.

Three questions, none of which a person can answer reliably from memory:
  DRIFT   loom's text changed since we last audited this seam
  MISSING the registry names an olite symbol that no longer exists
  ORPHAN  olite emits a prompt block that no seam accounts for

ORPHAN is the one that matters most: it is how an unanchored addition -- text
invented during a port rather than carried from loom -- becomes visible.
"""

import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import extract  # noqa: E402

LOOM = pathlib.Path(os.environ.get("LOOM_ROOT", pathlib.Path.home() / "loom"))
ROOT = pathlib.Path(__file__).resolve().parent.parent


def olite_prompt_symbols():
    """Every prompt constant and block builder olite defines.

    Deliberately broader than "what BLOCKS composes": text invented during a port is
    the thing being hunted, and it is just as unanchored sitting in an uncomposed
    constant. Keyed off definitions so it cannot be silently defeated by a refactor.
    """
    text = (ROOT / "brain/olite/prompt.py").read_text()
    consts = re.findall(r'^([A-Z][A-Z_0-9]{2,}) = (?:"""|\'\'\')', text, re.M)
    builders = re.findall(r"^def ([a-z_]+_block)\(", text, re.M)
    return set(consts) | set(builders)


def main():
    registry = json.loads((ROOT / "seams/registry.json").read_text())["seams"]
    problems = []

    for row in registry:
        loom_meta = row.get("loom")
        if loom_meta:
            path = LOOM / loom_meta["file"]
            if not path.exists():
                problems.append(("MISSING", row["id"], f"loom file absent: {loom_meta['file']}"))
                continue
            text = path.read_text()
            src = extract.ts_symbol(text, loom_meta["symbol"])
            if src is None:
                src = extract.ts_const(text, loom_meta["symbol"])
            if src is not None and loom_meta.get("section"):
                src = extract.section(src, loom_meta["section"])
            if src is None:
                problems.append(("MISSING", row["id"], f"loom symbol gone: {loom_meta['symbol']}"))
            elif extract.fingerprint(src) != loom_meta["fingerprint"]:
                problems.append(("DRIFT", row["id"],
                                 f"{loom_meta['symbol']} changed upstream -- re-audit, then re-record"))
        olite_meta = row.get("olite")
        if olite_meta:
            text = (ROOT / olite_meta["file"]).read_text()
            if extract.py_symbol(text, olite_meta["symbol"]) is None:
                problems.append(("MISSING", row["id"], f"olite symbol gone: {olite_meta['symbol']}"))

    anchored = {r["olite"]["symbol"] for r in registry if r.get("olite")}
    for name in sorted(olite_prompt_symbols() - anchored):
        problems.append(("ORPHAN", f"prompt.{name}",
                         "emitted but not in the registry -- name its loom anchor, or label it ADDED"))

    for kind, seam, detail in problems:
        print(f"{kind:8s} {seam:48s} {detail}")
    print(f"\n{len(registry)} seams checked, {len(problems)} need attention")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
