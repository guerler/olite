# Seam registry

Every point where olite touches Orbit is a **seam**. `registry.json` records one row per
seam: loom's anchor (file, symbol, optional sub-section), **the condition under which loom
emits it**, olite's counterpart, a label, and a fingerprint of loom's text at audit time.

Run it:

```bash
npm run seams          # or: python3 seams/check.py
LOOM_ROOT=~/loom npm run seams
```

Three failures, each meaning something different:

- **DRIFT** — loom's text changed since we recorded it. Re-read it, decide whether olite
  should follow, then `python3 seams/build_registry.py` to re-record. This is what makes
  pulling a newer Orbit produce a change list instead of a memory exercise.
- **MISSING** — the registry names a symbol that no longer exists on one side.
- **ORPHAN** — olite defines prompt text that no seam accounts for. Either name its loom
  anchor or label it `ADDED`. This exists because text invented during a port is invisible
  otherwise: it reads like everything around it.

## Labels

`PORTED` carried over · `REPLACED` loom's mechanism is impossible here, something else does
the job · `DIVERGED` we chose differently and owe an argument · `MISSING` loom has it, olite
does not, no argument yet · `NA` cannot apply.

## Why conditions are recorded, not just content

loom gates nine of its sixteen prompt blocks. A row that records only *what a block says*
loses *when loom says it* — and an instruction detached from its trigger reads like general
advice. That is not hypothetical: "read the bound history" is resume-only in loom, was
recorded without its trigger, and landed in olite as advice for every plan. It changed
first-turn behaviour across the eval matrix before anything caught it.
