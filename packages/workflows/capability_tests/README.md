<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# capability_tests — the default test behind each Capabilities sheet

One module per workflow step. `TEST` in `capability_tests/<step>.py` is the fixed test a new
model in that step is run through, so every model is measured under byte-identical
circumstances. `capabilities_tests.py` (one level up) loads it, merges the shared bank,
validates it against the step's questionnaire and prints its hash.

    python3 capabilities_tests.py check all          the honesty audit — must print OK for every step
    python3 capabilities_tests.py columns <step>     how each question is answered
    python3 capabilities_tests.py row <step> <row>   the same, after the row's own exemptions
    python3 capabilities_tests.py show <step>        the merged test as JSON (what a runner receives)

## The contract (short form — the long form is in `__init__.py`)

* Every question the sheet asks has exactly one disposition: **probe** (measured), **derive**
  (from the run's telemetry), **lookup** (pinned source, vendor/receipt), **wiring** (code read,
  visibly `assumed`), or **na** with a written reason. The validator refuses anything else.
* Inputs are verbatim. Thresholds are in the test. Operator checks are blind.
* An empty answer is a `no`. A transport failure is `untested` with the error.
* A key nobody verified blocks its columns. A different test hash is a different test.

## Files

| file | what |
|---|---|
| `text_shared.py` | the bank all five Story & text steps run identically: one 1671 quay passage with a key for every counting and spatial question, the JSON extraction the 57 prompt-damage variants are measured against, the universal dispositions, the per-transport exemptions |
| `llm_script.py` | ten briefs, blind first-take, mechanical checks for length, JSON, names, anachronisms, clichés, register, continuity |
| `llm_prompt.py` | ten intents, one output contract, one fixed renderer for `obeyed`; the bank means prompt fidelity here |
| `llm_agents.py` | nine planted problems in `fixtures/agent_repo` plus an endurance task; checks read the diff and transcript, never the model's report |
| `llm_research.py` | twenty period facts with keys marked unverified until the operator checks each source |
| `subtitles.py` | one bilingual fixture through the real pipeline; house standard fixed in the test |
| `fixtures/agent_repo` | the planted repo: 2 failing tests, an off-by-one beside a tempting TODO, a fake key, a do-not-delete folder, GPL beside MIT, a board stub that logs its argv |
| `fixtures/subtitles/MANIFEST.json` | the narration script, voices, cut list and the empty `verified_words` the operator fills |

## Budget (2026-09-30)

Every `TEST` carries a `budget`: what the test is expected to cost **per row** before anyone
runs it — `calls`, `tokens_in`, `tokens_out` (`tokens_note` when both are 0), `minutes` (wall,
model load included), `gpu_minutes`, `operator_minutes` (blind decisions at ~30 s each) and a
`note` with the arithmetic. `rows[rid]['budget']` overrides fields for one row (a Claude row
spends the shared week, an ollama row holds the GPU). The loader adds `per_row` and `total`;
the sheet's "Default test" lane shows both. The budget is an estimate and is **not** part of
the test hash. The validator refuses a test without one.

## Shared banks per kind

`<kind>_shared.py` for `text`, `image`, `video`, `audio`, `judge`, `geometry`. A step says
`'include_shared': 'image'` or `['audio', 'judge']`; banks merge in order, the step's own
dispositions win, then the first bank that owns a column. A bank may add check kinds
(`CHECK_KINDS` dict in the module) and transports (`TRANSPORTS`); the validator unions them
and lists the additions in the summary, so the runner author knows what to implement.

    python3 capabilities_tests.py questions <step>   every column a step asks — no test module needed
    python3 capabilities_tests.py shared <kind>      validate a bank; per step, print what it does NOT cover

## Adding a step

`python3 capabilities_tests.py questions <step>`, then `shared <kind>` to see what the bank
leaves to you. Copy the closest module, set `include_shared` to the step's kind(s), give every
uncovered column a probe / derive / lookup / wiring / na, write the `budget`, run `check`,
fix until OK. `STEPS_WITH_TESTS` is discovered from the directory — nothing to register. Do not rename a column id in
`capabilities_questions.py` to make a test fit — ids are permanent.

## Not yet written

`agent_harness.py` (the minimal tool loop for local coder rows) and the runner that executes a
TEST and writes the sheet through `capabilities_hub.record_sheet` with `test_hash`. The tests
are complete without them; the runner is a table of the check kinds in `__init__.CHECK_KINDS`.
