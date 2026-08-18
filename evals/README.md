# olite evals

Scenario-driven behavioural tests, ported from loom's `evals/`. The unit suites in
`brain/tests` and `src/*.test.ts` check that the machinery is correct; these check
that the **agent behaves like Orbit** — which is the claim the project actually
rests on, and the one thing a unit test cannot answer.

```bash
python evals/run.py                    # every scenario x every available model
python evals/run.py plan-creation      # filter scenarios by substring
python evals/run.py --model gemini     # filter models by substring
python evals/run.py --json out.json    # write transcripts + chat text + failures, pass or fail
python evals/run.py --delay 5          # extra pacing on top of the provider's own
```

**Pacing.** Each model resolves through the brain's provider registry, so the run is
throttled at the endpoint's own rate — Gemini's free tier is 5 requests/minute, and
that number lives in `providers.py`. `--delay` adds more on top and defaults to none.
A per-day quota is a different thing and no amount of pacing fixes it. A quota-limited
run is reported as `quota`,
counted in its own column, **not graded, and does not fail the suite** — an exhausted
account is a fact about the key, not about the agent, and must never be readable as
a behavioural failure.

## How it runs

loom spawns `loom --mode json` and parses its event stream. olite needs no
subprocess: the brain is a Python package, so `lib/harness.py` assembles the same
pieces `runtime.run` assembles and awaits the driver in-process — faster, no browser,
and the whole transcript is in hand.

**Galaxy is stubbed; the LLM is real.** These scenarios grade planning behaviour, and
a live Galaxy would add a second source of failure without adding signal. The stub
answers plausibly rather than erroring, because a tool that fails teaches the model to
stop calling tools, which would confound the measurement.

The stub keeps the **full 46-tool surface advertised**. loom trims to
`--tools read,write,edit` for its plan scenarios; olite deliberately does not, because
a live run showed the model behaves differently with the whole surface in context
(~16k tokens of schemas) than with a handful — trimming would measure a condition
olite never runs in. It also makes runs slower, which is why the two-turn plan scenarios
allow 7 minutes rather than loom's 2.5.

## Models

`models.json` is the matrix. A model whose `envRequires` are unset is **skipped, not
failed**, so a local run works without every credential. Every entry is
OpenAI-compatible, which is also how olite reaches Galaxy's chat proxy in production,
so adding a provider is a JSON entry and no code change.

| id | needs |
|---|---|
| `gemini-3.7-flash` | `GEMINI_KEY` (free tier is enough) |
| `gemini-3.1-flash-lite` | `GEMINI_KEY` |
| `deepseek-v4-flash` | `DEEPSEEK_KEY` |
| `local-llama` | `LOCAL_LLM_URL` (+ optional `LOCAL_LLM_KEY`) |

Keys come from the environment. Note `~/.zshrc` is not read by non-interactive
shells — `source ~/.zshrc` first, or put the export in `~/.zshenv`.

## Dimensions

Runs are graded on loom's four decision-correctness dimensions rather than a single
pass/fail, because "did it behave like Orbit" is not one question:

- **validity** — a well-formed `## Plan X: <title> [routing]` block with enough
  described steps. The gate: a model that cannot emit a parseable plan fails
  everything downstream.
- **routing** — did it pick the right tag? Scenarios name the *correct* answers, so a
  wrong route is graded wrong rather than waved through. olite routes `[galaxy]` and
  `[remote]` only; the parser still accepts `local` and `hybrid` so a wrong route is
  a routing failure and not a parse failure.
- **tools** — did it name a plausible analysis tool? A generous allow-set per assay,
  a coarse heuristic rather than an oracle.
- **behavior** — contract checks needing no Galaxy: does an underspecified prompt
  produce a question rather than a fabricated plan, and does the approval gate hold
  (`doesNotExecute`).

## One deliberate difference from loom

loom reads plans from "wherever they land" — notebook or chat — because its matrix
models collapse its four-stage gate in different ways and it did not want to grade
process. olite reads from **chat**, because its gate is explicit that the draft is
drawn in chat and only an *approved* plan reaches the record. A scenario that never
approves anything should therefore find nothing on the record, and that is a property
worth grading rather than papering over.

## What this is not

Not a correctness oracle. `mentionsOneOf` checks that a plan names a plausible tool
for the assay, not that the analysis is right — loom leaves that to a judge layer and
so does this. And the suite says nothing about execution: every scenario stops at or
before approval, so nothing here exercises a real Galaxy job.
