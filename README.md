# olite

**olite** is a **client-only** Galaxy co-scientist delivered as a Charts visualization
plugin. The agent loop runs entirely in the browser: it reaches the LLM through Galaxy's
chat proxy, runs local Python in Pyodide, and orchestrates real Galaxy jobs through the
Galaxy API. There is no per-user server container.

## Architecture

The agent brain is a Python package (`brain/olite/`) that runs **inside Pyodide**, layered
substrate / drivers / registry. Full map: **[`LAYOUT.md`](./LAYOUT.md)**.

| Layer | Role | Where |
|---|---|---|
| **substrate** | what it can touch: capability manifest, `run_python` (Pyodide), scoped Galaxy catalog, LLM chat proxy | `brain/olite/substrate/` |
| **drivers** | how it decides: `loop/` (open-ended, Orbit parity, default); `graph/` (polaris runner, deferred) | `brain/olite/drivers/` |
| **registry** | what it knows: skills (markdown) + processes (`agent.yml`); deferred | `brain/olite/registry/` |
| Charts shell | boots the Pyodide worker, renders the transcript, owns Stop and the confirm modal | `src/main.ts`, `src/pyodide/` |

- **LLM**: in production the loop POSTs to `{root}api/plugins/olite/chat/completions`
  (Galaxy's chat proxy: Galaxy-managed key, OpenAI-compatible). In dev, `<ai_api_base_url>`
  is `/llm`, which vite proxies to whatever `LLM_ROOT` points at.
- **Local compute**: `run_python` executes in the same Pyodide interpreter the brain runs
  in (numpy/pandas available, state persists across calls).
- **Remote compute + storage**: the scoped, capability-gated catalog hits the Galaxy API
  with the user's session. Reads are available now; writes are gated and enabled targeted.
- **Substrate origin**: `substrate/` is adopted from the `polaris` Charts plugin (`core/` +
  `api/`) and owned here, since polaris is unpublished. The capability gate is factored into
  `Catalog` + `CapabilityManifest`.

## Running it locally

Three ways, cheapest first. All of them need `npm install` once.

### 1. No Galaxy, no LLM, no quota — the end-to-end checks

Deterministic, free, and the fastest way to see the whole thing work. One stub answers as
both the provider and Galaxy.

```bash
node e2e/stub.cjs &
GALAXY_ROOT=http://127.0.0.1:8099 LLM_ROOT=http://127.0.0.1:8099 \
  LLM_PATH=/v1 LLM_KEY=stub LLM_MODEL=stub-model \
  LLM_CONTEXT_WINDOW=40000 LLM_KEEP_RECENT_TOKENS=20 npm run dev &
LLM_CONTEXT_WINDOW=40000 node e2e/confirm-drive.cjs
```

Drop the last line and open http://localhost:5173 to click around by hand instead. See
[`e2e/README.md`](./e2e/README.md).

### 2. Real model, no Galaxy, no browser — the eval harness

Grades planning behaviour headlessly against a real provider. See
[`evals/README.md`](./evals/README.md).

```bash
python3 evals/run.py smoke --delay 0
```

### 3. Real Galaxy and a real model

```bash
GALAXY_ROOT=http://127.0.0.1:8080 GALAXY_KEY=<galaxy-api-key> \
LLM_ROOT=https://generativelanguage.googleapis.com LLM_PATH=/v1beta/openai \
LLM_KEY="$GEMINI_KEY" LLM_MODEL=gemini-3.7-flash \
npm run dev
```

Then open http://localhost:5173, or `?dataset_id=<id>` to start with a dataset in scope.

**Set `GALAXY_KEY`.** The plugin is served from vite, not from inside Galaxy, so the
session cookie does not apply and the proxy appends the key to every `/api` call instead.
Without it you get an anonymous session: reads succeed but return nothing of yours, and
writes are 403. Get a key from Galaxy under User -> Preferences -> Manage API Key.

The plugin does **not** need to be registered in Galaxy for this: `<ai_api_base_url>` is
`/llm`, so the model is reached through vite rather than through Galaxy's chat proxy. Only
a production install needs the registration.

### Things that will bite

- `npm run dev` rebuilds the Pyodide assets and the brain wheel first, so the first start
  takes minutes. Plain `npx vite` skips the build and serves what is already there.
- **Editing `brain/` Python does nothing until the wheel is rebuilt** — `npm run build:olite`,
  then reload. Vite only watches `src/`.
- Provider keys usually live in `~/.zshrc`, which a non-interactive shell does not read;
  `source ~/.zshrc` first.
- Point `LLM_CONTEXT_WINDOW` at your model's real window. It defaults to 128k, and olite
  has no way to discover it.

## Tests

```bash
npm test                 # vitest + pytest
npx tsc --noEmit
```

## Scope

- No local shell or filesystem — Galaxy is the OS, and `run_python` is Pyodide only.
- No server-side brain, and no per-user container. That is the GxIT shape olite replaces.

## Credit

olite reuses the design and assets of **Orbit** / **Loom** (the co-scientist brain) and the
`vintent` / `polaris` Charts plugins (Pyodide substrate). It is a re-target of that work to
a client-only Charts plugin, not a replacement.
