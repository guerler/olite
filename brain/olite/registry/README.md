# registry — what olite knows

Skills and processes are the same shelf ("how to do a task") at two maturities on
one spectrum of rigidity:

- **skills (soft): markdown guidance for the open loop.** Prose know-how injected
  into the system prompt. The model *may* follow it; it can still adapt. This is
  Orbit's approach, and Orbit's `galaxy-skills` are reusable here now that the loop's
  tool names match galaxy-mcp. Use a skill when the task is *guidance* — "how uploads
  work", "which op lists histories", "the usual analysis shape."
- **processes (hard): crystallized `agent.yml` deterministic procedures.** A frozen
  graph with schema-bounded LLM decisions and deterministic transforms, invoked by
  the loop as one reliable tool via `run_process`. The model *cannot* deviate. Use a
  process when the task must be *deterministic/validated/bounded* — a procedure a
  markdown skill cannot guarantee (e.g. reproduce ~65 chart transforms and emit a
  valid Vega-Lite spec every time: `visualize_dataset`).

Pick the form by need: guidance → skill; a procedure that must run the same way every
time → process. A task can also start as a skill and crystallize into a process once
it is proven and worth freezing. Both are governed by the same capability manifest.

## processes (present)

Crystallized `agent.yml` graphs, authored under `processes/` and loaded by
`ProcessRegistry` (`processes.py`). Each declares `id`, `description`, and
`when_to_use`. The loop reaches one through the `run_process` tool, which runs it
on the graph driver over the same substrate, so it inherits the session's
capability manifest. `run_process` is advertised only when processes are registered,
and its description lists them.

Shipped:
- **`lineage_report`** (`processes/lineage_report.yml`): fetch source dataset ->
  `traverse` upstream (dataset -> creating_job -> inputs/outputs) -> `reasoning`
  narrative -> `lineage.mermaid` materializer -> `terminal`. Exercises executor +
  traverse + reasoning + materializer + terminal.
- **`visualize_dataset`** (`processes/visualize_dataset.yml`): the absorbed vintent
  pipeline. Fetch + profile a dataset, four state-derived `planner` decisions
  (intent, extract, shell, params), deterministic transforms, then compile a
  Vega-Lite chart returned as a typed artifact. Its leaves live under `vintent/` and
  are registered by `vintent_bridge.py`.

Materializers and schema-builders used by processes register in code
(`materializers.py` + `vintent_bridge.py`, via `register_materializer` /
`register_builder`). Import is lazy: the graph engine and registrations load only
when `run_process` first runs.

Add a process by dropping an `agent.yml` in `processes/` (shipped via
`package-data`). A process starts life as an ad hoc loop task; once proven, it is
frozen here.

## skills

Markdown know-how in `skills/`, loaded by `SkillRegistry` and appended to the system
prompt as routing hints. Shipped: `skills/visualization.md` (points the loop at the
`visualize_dataset` process). Add one by dropping a `.md` file in `skills/`.
