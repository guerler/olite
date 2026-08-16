# End-to-end checks

Drives the real page — real worker, real brain, real modal — with the provider and
Galaxy replaced by one stub. Deterministic, and it costs no provider quota, so it can
run as often as you like.

It exists because the pieces it covers cannot be unit-tested. The destructive-op gate
and Stop both hinge on a **round trip across the worker boundary**: the brain parks a
turn on a promise, a message from the main thread resolves it, and a message arriving
*during* a run is delivered only because the worker's event loop is free between the
awaits inside the Python coroutine. The Python tests cover the decisions; this covers
the wiring, and it caught two defects the unit tests could not see — a refused
destructive call rendering as a green successful card, and a stopped turn also
printing "the model ended the turn without a reply. Ask again, or rephrase."

```bash
node e2e/stub.cjs &                      # provider + Galaxy, on :8099
GALAXY_ROOT=http://127.0.0.1:8099 LLM_ROOT=http://127.0.0.1:8099 \
  LLM_PATH=/v1 LLM_KEY=stub LLM_MODEL=stub-model npm run dev &
node e2e/confirm-drive.cjs               # exits non-zero if any check fails
```

Screenshots land next to the driver's `OUT` path. Look at them — a check can pass on
a page that renders nothing.

`stub.cjs` scripts itself through `/__script?name=…` (`confirm`, `slow`) and reports
every Galaxy request it received at `/__seen`, which is what makes "declining sends
nothing to Galaxy" an assertion about the network rather than about the UI.
