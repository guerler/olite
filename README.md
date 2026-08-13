# olite

**olite** is a **client-only** Galaxy co-scientist delivered as a Charts visualization
plugin. The agent loop runs entirely in the browser: it reaches the LLM through Galaxy's
chat proxy, runs local Python in Pyodide, and orchestrates real Galaxy jobs through the
Galaxy API. There is no per-user server container.

This build is the **kill-gate spike**. Its only job is to answer one binary question:

> Can a client-only agent loop reliably drive Pyodide **and** Galaxy end to end,
> with no server-side brain?

**GO** if the loop completes one real task (local Pyodide compute → real Galaxy tool run,
polled to completion) in the browser. **NO-GO** otherwise. There is no GxIT fallback.

## Architecture

The agent brain is a Python package (`brain/olite/`) that runs **inside Pyodide**, layered
substrate / drivers / registry. Full map: **[`LAYOUT.md`](./LAYOUT.md)**.

| Layer | Role | Where |
|---|---|---|
| **substrate** | what it can touch: capability manifest, `run_python` (Pyodide), scoped Galaxy catalog, LLM chat proxy | `brain/olite/substrate/` |
| **drivers** | how it decides: `loop/` (open-ended, Orbit parity, default); `graph/` (polaris runner, deferred) | `brain/olite/drivers/` |
| **registry** | what it knows: skills (markdown) + processes (`agent.yml`); deferred | `brain/olite/registry/` |
| Charts shell | loads Pyodide, seeds the prompt, renders the transcript | `src/Plugin.vue`, `src/App.vue`, `src/pyodide/` |

- **LLM**: the loop POSTs to `{root}api/plugins/olite/chat/completions` (Galaxy's existing
  chat proxy: Galaxy-managed key, injects the plugin's `ai_prompt`, OpenAI-compatible). No
  new endpoint, no BYOK.
- **Local compute**: `run_python` executes in the same Pyodide interpreter the brain runs
  in (numpy/pandas available, state persists across calls).
- **Remote compute + storage**: the scoped, capability-gated catalog hits the Galaxy API
  with the user's session. Reads are available now; writes are gated and enabled targeted.
- **Substrate origin**: `substrate/` is adopted from the `polaris` Charts plugin (`core/` +
  `api/`) and owned here, since polaris is unpublished. The capability gate is factored into
  `Catalog` + `CapabilityManifest`.

## Run the spike

Point the dev server at a running Galaxy that has the `olite` plugin registered (so the
chat proxy can resolve its `ai_prompt` and inference key), then:

```bash
npm install
GALAXY_ROOT=http://127.0.0.1:8080 GALAXY_KEY=<your-api-key> npm run dev
```

`npm run dev` builds the Pyodide assets and the `olite` wheel, then serves the plugin.
Vite proxies `/api` to `GALAXY_ROOT` (appending `?key=` when `GALAXY_KEY` is set), so both
the chat proxy and the Galaxy API calls are authenticated.

On load, olite seeds a default task (local `run_python` mean + `galaxy_list_histories`,
then `finish`). Type a follow-up in the chat to close the full loop, e.g.:

> Compute a quick stat on the dataset locally, then run a real tool on it in Galaxy and
> poll until it finishes.

Watch the console: each `call <tool>(...)` / `-> <result>` line is one loop step. If it
reaches `finish` after a real `galaxy_run_tool` + `galaxy_get_job … "state": "ok"`, that
is **GO**.

### Offline loop check (no browser, no Galaxy)

`brain/olite/agent.py` + `tools.py` can be exercised in CPython by stubbing the HTTP layer
with canned `tool_calls` (patch `http` in `olite.core.completions` and `olite.tools`). This
validates the loop mechanics and `run_python` independently of Pyodide and Galaxy.

## Scope caps (spike)

- Tools are capped at Galaxy list / submit / poll + Pyodide `run_python` + `finish`.
- No local shell / filesystem — Galaxy is the OS.
- No Galaxy API that hosts the brain (that is the GxIT shape; rejected by design).

## Credit

olite reuses the design and assets of **Orbit** / **Loom** (the co-scientist brain) and the
`vintent` / `polaris` Charts plugins (Pyodide substrate). It is a re-target of that work to
a client-only Charts plugin, not a replacement.
