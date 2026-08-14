# olite layout

olite is a **client-only** Galaxy co-scientist delivered as a Charts visualization
plugin. The agent runs entirely in the browser (Python brain inside Pyodide), uses
Galaxy as compute + storage, and needs **no Galaxy Interactive Tool**. Goal: cover
the same functionality as Orbit, without an IT.

This file is the code-level map. Paths below are relative to the repository root.

## Two sides

```
src/              Vue/JS shell (the Charts plugin): loads Pyodide, seeds the
                  prompt, renders the transcript, calls the brain.
brain/            Python package -> wheel -> loaded into Pyodide. The agent.
static/olite.xml  plugin manifest (data_sources, ai_prompt, entry_point)
```

The shell (`src/`) is thin. All agent logic is in `brain/`, run inside Pyodide;
`src/pyodide-runner.ts` calls `from olite import run` and awaits the result.

## The brain: three layers

```
brain/olite/
  runtime.py            run(config, inputs): build Substrate, run a driver

  substrate/            LAYER 1 — what it can touch (the shared kernel)
    substrate.py          Substrate facade = manifest + local + galaxy + catalog + llm
    manifest.py           CapabilityManifest — the gate (default ["llm","local","read"])
    local.py              LocalPython — run_python in Pyodide
    galaxy_http.py        GalaxyHttp — direct, capability-gated Galaxy REST (loop tools)
    catalog.py            Catalog — scoped, capability-gated Galaxy op catalog (graph)
    llm.py                Llm — LLM (Galaxy chat proxy, or direct via ai_base_url)
    galaxy.py             GalaxyApi provider (OpenAPI catalog, prefix + method scope)
    openapi.py            OpenApiCatalog (prefix/method allowlist)
    openapi_ops.py        openapi_get (openapi_post added when write is enabled)
    api.py providers.py http.py completions.py rate_limiter.py retry.py exceptions.py

  drivers/              LAYER 2 — how it decides
    loop/                 LoopDriver (default): open-ended, Orbit parity
      galaxy_tools.py       Orbit named tools (galaxy-mcp surface) over GalaxyHttp
    graph/                GraphDriver: polaris engine over the catalog (agent.yml)

  registry/            LAYER 3 — what it knows
    processes.py          ProcessRegistry: loads agent.yml graphs
    processes/*.yml       crystallized processes (lineage_report, visualize_dataset)
    materializers.py      in-code materializers (lineage.mermaid) + imports the bridge
    vintent_bridge.py     absorbed vintent leaves as materializers + schema-builders
    vintent/              vintent's pure leaves (profiler, processes, shells) unchanged
    skills.py             SkillRegistry: markdown injected into the system prompt
    skills/*.md           routing hints (visualization -> run_process visualize_dataset)

  (drivers/graph/builders.py: schema-builder registry for state-derived planner schemas)
  (src/artifacts/: typed artifact rendering, vega-lite via vega-embed,
   mermaid via mermaid; dispatch on `kind`, one branch per renderer)
```

vintent (a natural-language-to-chart plugin) is fully absorbed here as the
`visualize_dataset` process: its pure leaves live under `registry/vintent/` unchanged,
its orchestration was dropped, and olite's graph driver runs the pipeline. Tests:
`brain/tests/leaves/` (ported vintent leaf tests) + `brain/tests/test_visualize_dataset.py`.

Adopted from polaris (not a dependency; polaris is unpublished, so its substrate is
copied in and owned here): `core/*` and `api/*` became `substrate/*`. The capability
gate, factored out of polaris's `Registry.call_api`, now lives in `Catalog` +
`CapabilityManifest`, used uniformly by both drivers.

## Two Galaxy surfaces, one gate

The loop and the graph reach Galaxy through different surfaces, matched to their
purpose; both pass the same `CapabilityManifest`.

- **Loop (open agent) → Orbit named tools.** `drivers/loop/galaxy_tools.py` clones
  galaxy-mcp's tool surface (get_histories, run_tool, invoke_workflow, pages, IWC, …)
  as thin wrappers over `GalaxyHttp` (direct REST). This is Orbit-faithful, so Orbit's
  skills/prompts/evals apply, and it's the only way to reach Galaxy's central agent
  routes (`run_tool` = POST /api/tools etc.) which are legacy routes absent from the
  OpenAPI spec. Each tool is tagged read/write; write tools are advertised only when
  `write` is granted. The 45th galaxy-mcp tool (`connect`) is implicit — the session
  is already authenticated. Each tool's model-facing description is galaxy-mcp's own
  docstring, verbatim (`galaxy_tool_docs.py`). `ai_prompt` (in `olite.xml`) is
  olite's own base instructions — NOT Orbit's; importing Orbit's is open work (see
  `orbit-faithfulness.md` in the thesis notes).
- **Graph (crystallized agent.yml) → scoped catalog.** The `Catalog` (auto-derived
  from the OpenAPI spec, prefix/method/capability-scoped) is where declared, bounded
  op sets are the point — a process names exactly the ops it touches. `visualize_dataset`
  and `lineage_report` use it.

So "an agent is a manifest over a scoped op set" is a crystallization property (graph),
while the open agent gets Orbit's ergonomic named tools (loop). Tests:
`brain/tests/test_galaxy_tools.py`.

## The capability manifest

One contract at every scale: a **session** runs under a manifest, a **process**
declares the manifest it needs, an installed **plugin** is approved for a manifest.
The substrate enforces it: `Catalog.call` checks the op's required capability, and
`LocalPython` / `Llm` require `local` / `llm`.

- Default = `["llm", "local", "read"]` (reason + Pyodide + read-only Galaxy).
- **Write is never default.** It is granted explicitly and targeted (see below).
- `CapabilityManifest(None)` takes that default; `CapabilityManifest([])` grants
  nothing. The two must stay distinct or the narrowest manifest becomes the widest.

**Per-process least privilege (the middle scale).** A process declares
`capabilities:` in its yml; `run_process` runs it on `Substrate.scoped(declared)`,
whose grant is the **intersection** of the session's manifest with the declaration.
Intersection, not union, is the guarantee: a declaration can only subtract, so it
holds even for a process definition this deployment did not author — a process file
can never be an escalation vector. Both packaged processes declare `["llm","read"]`,
so neither can write even in a write-enabled session.

A scoped view shares the parent's service state rather than rebuilding it. That is
load-bearing: a fresh `LocalPython` would wipe the Pyodide namespace, a fresh `Llm`
would hand the scoped run its own rate budget (scoping as a rate-limit bypass), and
a fresh `Catalog` would refetch the OpenAPI spec on every call. Tests:
`brain/tests/test_least_privilege.py`.

## Read / write status

The two surfaces gate writes differently but under the same manifest.

- **Loop (named tools)**: each tool in `galaxy_tools.py` is tagged `read` or `write`.
  `tool_schemas(manifest)` advertises only the tools whose capability the manifest
  grants, and `GalaxyHttp.post/put/delete` require `write` at call time. So write
  tools are invisible and non-callable without the grant; grow the surface by adding
  a tool, not by editing an allowlist.
- **Graph (scoped catalog)**: reads cover the MCP parity surface — `galaxy.PREFIXES`
  is widened past polaris's set (histories/datasets/jobs/tools/workflows) to add
  users, invocations, dataset_collections, pages, configuration, version, whoami.
  Writes are double-gated: `galaxy.py` resolves a POST op only if it is in
  `WRITE_ALLOWLIST` **and** the manifest grants `write`; non-allowlisted POSTs are
  `unknown_api_op`, allowlisted-but-ungranted are `capability_denied`.

## Build / run

- `npm run build` -> `build:pyodide` (Pyodide assets) + `build:olite`
  (`brain/` -> `olite-*.whl`, copied into `static/pyodide/`) + `vite build`.
- Dev: `GALAXY_ROOT=... GALAXY_KEY=... npm run dev` (Vite proxies `/api` to Galaxy).
- The substrate is boot-tolerant: if Galaxy/openapi is unreachable, `local` + `llm`
  still work and catalog calls report the provider is unavailable.

## Verified

An offline CPython harness (stubbed LLM http + catalog) confirms: imports resolve,
the manifest gates (write off, `local` required, `CapabilityError` when revoked),
`run_python` runs (real numpy), and the loop composes `run_python` + `galaxy_api` +
`finish` end to end.

## Crystallization (graph driver)

`drivers/graph/` is the polaris engine adopted and owned here, running an `agent.yml`
over the substrate. Handlers' `call_api` / `reason` go through the substrate's
`Registry`, so graph execution shares the capability gate and rate limit. Verified by
`scratchpad/olite_graph_check.py` (executor -> reasoning -> terminal, `$ref`/emit
resolved, `{state, last}` returned). Materializers register in code; import is lazy.

## run_process bridge + first process (present)

The loop's `run_process(name, inputs)` tool (advertised only when processes exist)
runs a crystallized `agent.yml` on the graph driver over the same substrate. The
first process, `lineage_report`, reconstructs a dataset's upstream provenance
(`executor` -> `traverse` -> `reasoning` -> `lineage.mermaid` materializer ->
`terminal`). Verified end to end by `scratchpad/olite_process_check.py`: the loop
invokes run_process, the graph traverses a real lineage, and returns datasets, jobs,
a narrative, and a Mermaid diagram.

## Deferred (documented seams, not stubs of speculative code)

- The notebook — Orbit's `notebook.md` (plan + working memory) has no olite
  equivalent. The intended replacement is a Galaxy Page; the API surface is already
  in the tool set (`create_page` / `update_page`), the record discipline is not.
- Progressive-disclosure skills — `SkillRegistry` concatenates every skill into the
  system prompt eagerly. Orbit's format is frontmatter + on-demand body, which is
  what makes a corpus the size of `galaxyproject/galaxy-skills` affordable.
- GTN tools — Orbit has native GTN discovery/fetch; olite has none.
- Wider write parity — grow `WRITE_ALLOWLIST` op by op (invoke_workflow, upload,
  create_page) as parity needs them, each an explicit grantable capability.

See `orbit-faithfulness.md` in the thesis notes for the full component audit.
