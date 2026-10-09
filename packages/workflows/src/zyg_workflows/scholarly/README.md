# `zyg_workflows.scholarly` — the stages of the scholarly documentary pipeline

`_run_scholarly_pipeline` used to be one 11 000-line function in
`zyg_workflows.pipeline_scholarly`. It is now a 259-line driver that builds two
objects and calls twenty-six functions; everything else lives here. This file
says how a run flows through those functions and what to do to add, move or
change one. `SPLIT_LOG.md` next to it is the history — four tasks, what each
moved, and every spot where a pure move was not possible.

## The shape of a run

```
pipeline_scholarly._run_scholarly_pipeline(job, …)
  │  prologue — job record, out_dir, options, the pre-emptive bank
  ├─ stage_55_run_glue(job, pipeline_state, pipeline_id, state_file) -> RunGlue
  ├─ stage_56_staleness_gate(glue, __file__, _MODULE_IMPORTED_AT)
  ├─ ctx = RunContext(…)                       # run inputs + the glue closures
  ├─ try:
  │    stage_01_topic_setup(ctx) … stage_19_burn_subtitles(ctx)
  ├─ except StopIteration:  stage_71_on_user_stop(glue, marker)
  ├─ except Exception:      stage_72_on_error(glue, marker, exc)
  └─ finally:               stage_73_finalise(glue, pbank, preempt_token)
```

Twenty-one pipeline stage functions covering the monolith's nineteen `# ── Stage
N …` markers (marker 11, the FLUX still factory, became three), in one straight
line, with no conditional between them but the `StageExit` test:

| module | functions | what |
| --- | --- | --- |
| `stages_01_18.py` | `stage_01` … `stage_09` | topic setup, research, script, fact check, visual tagging, turning points, emotion curve, the pre-image TTS pass, time-locked scene descriptions |
| `stages_19_36.py` | `stage_10`, `stage_12` … `stage_19` | FLUX prompt vocabulary and slot arithmetic, hand QC, rhythm refresh, LTX motion, video assembly, music bed, colour grade, book intro, burnt-in subtitles |
| `stages_37_54.py` | `stage_11`, `stage_11b`, `stage_11c` | the FLUX still factory: the prompt batch, the pre-flight, and the per-slot generate/judge/retry loop |
| `stages_37_54_flux_setup.py` | `setup_flux_prelude`, `setup_flux_pipes`, `setup_gates` | `stage_11c`'s setup: torch and GPU exclusivity, the pipes, the FluxWorker hand-off, IP-Adapter, ControlNet, the loop-state and gate fields |
| `stages_37_54_flux_loop.py` | `run_slot_loop`, `finish_flux_stage` | `stage_11c`'s body: the per-slot loop with its reviews and `_gate_receipt`, then the repair pass, the teardown, the upscales and the manifest |
| `stages_55_73.py` | `stage_55`, `stage_56`, `stage_71`, `stage_72`, `stage_73` | the run scaffold — not a `# ── Stage N …` block of the monolith but the machinery around them |

The module names are the *monolith block ranges* of the split chain, not stage
numbers; `stages_19_36.py` holds stages 10 and 12-19. Do not rename them — the
`SPLIT_LOG.md` entries, this table and `scripts/check_free_names.py`'s
`stages_*.py` glob all key off them.

The *stage* numbers are likewise the split chain's, not the pipeline's. The
pipeline's own user-visible stage labels — the `'Stage 3.5'`, `'Stage 4b'`
strings in `_log(…)` and `job['current_stage']` — are unchanged and do not line
up with the function names. `stage_13_tts_rhythm_refresh` logs under
`'Stage 4b: Rhythm Refresh'`. The `# ── Stage 4: …` banner comment that opened
the moved block is still the first line of each function body, so the mapping is
readable at the top of every stage.

## The two shared objects

**`RunContext`** (`context.py`) carries every local that crosses a stage
boundary — run inputs (`job`, `pipeline_id`, `out_dir`, the `_sch_*` option
blocks), the scaffold closures the stages call, and the stage products one stage
writes and a later one reads. Every field defaults, grouped by the stage that
first writes it, so a new stage appends its fields without touching the
construction site. Two fields default to `UNSET` and not `None` because the code
feature-detects them with `except NameError:` — read `_Unset`'s docstring before
touching those.

`StageExit` is in the same module: a stage function cannot `return` for its
caller, so a `return value` that used to leave `_run_scholarly_pipeline` becomes
`return StageExit(value)`, and the driver does

```python
_preempt_exit = stage_11b_flux_preflight(ctx)
if isinstance(_preempt_exit, StageExit):
    return _preempt_exit.value
```

**`RunGlue`** (`stages_55_73.py`) carries the eleven helpers the prologue used to
define as nested `def`s — `_log`, `_save`, `_debug`, `_done`, `_stage_start`,
`_should_stop`, `_assert_not_stopped`, `_gate_receipt`, `_flux_lever_guard` and
the gate registry behind them. They are closures over the job, the state file
and the gate dict, so they cannot become module-level functions; one factory
builds them and hands them back on a dataclass. The driver unpacks that
dataclass into the same plain local names it used before, and passes the same
objects on to `RunContext`, so a stage calls the very `_log` the monolith called.

## The import direction

`pipeline_scholarly` imports the stage modules **inside**
`_run_scholarly_pipeline`; the stage modules import helpers out of
`pipeline_scholarly` **at module level**. Only one direction can be
module-level or the cycle closes at import time — do not "tidy" the lazy imports
up to the top of `pipeline_scholarly.py`. `__init__.py` deliberately re-exports
nothing for the same reason.

## Writing a stage function

Each stage is a pure move of a `# ── Stage N …` block, with a head and a tail of
glue and nothing changed in between:

```python
def stage_13_tts_rhythm_refresh(ctx):
    _debug = ctx._debug          # head: one plain local per field the block reads,
    _log = ctx._log              #       alphabetical, so the body is untouched
    job = ctx.job
    narration_script = ctx.narration_script
    # ── Stage 4: TTS Narration (rhythm refresh …) ────────────────────────────
    …                            # the monolith's statements, verbatim
    ctx._sch_voice = _sch_voice  # tail: one store per local a later stage reads
    ctx.tts_duration = tts_duration
```

Plain locals in the head, not `ctx.x` throughout the body: the blocks define
nested `def`s and `lambda`s that close over these names, and a closure cannot
capture an attribute. It also keeps the diff to the head and the tail, which is
what makes the move reviewable.

To add a stage:

1. write `stage_NN_<slug>(ctx)` in the stage module whose range it belongs to;
2. add the fields it reads from earlier stages — if they are not there yet — and
   the fields it publishes, to `RunContext`, in the group of the stage that
   first writes them;
3. call it from `_run_scholarly_pipeline`'s `try:` in position, and add the name
   to that module's lazy import list;
4. if it can end the run, `return StageExit(value)` and test for it at the call
   site;
5. append a `SPLIT_LOG.md` entry.

## House rules inside this package

* single quotes; run `.tools/venv/bin/ruff format` on what you edit;
* no `localhost`/`127.0.0.1`/`/home/...` literals — `zyg_workflows.paths` roots
  and `pipeline_config._OLLAMA_BASE_URL`;
* `argv[0]` of a subprocess is `zyg_workflows.bin.exe('ffmpeg')`, never the bare
  name;
* an `except` that swallows says in its log line **what failed and what the run
  loses by it** — never `'suppressed %s: %s'`. Narrow `except Exception` to the
  real types; keep it only for third-party error trees (torch, diffusers, the
  Postgres driver, the worker client) with `# noqa: BLE001 — <reason>`;
* `stage_11c_flux_image_loop` was 3 500 lines and is not under the `func_len`
  gate. It is now a ~150-line skeleton over `stages_37_54_flux_setup` and
  `stages_37_54_flux_loop`; do not grow it back. New work in the still factory
  goes in its own function in one of those modules — and every `stages_37_54*.py`
  is capped at 800 lines.

## Verification

```sh
T=/home/zygomatic/repos/.tools/venv/bin
cd /home/zygomatic/repos/zygomatic-workflows
$T/python -m compileall -q src/zyg_workflows
$T/ruff check src/zyg_workflows/scholarly src/zyg_workflows/pipeline_scholarly.py
$T/python scripts/check_free_names.py
$T/python scripts/func_len.py src/zyg_workflows/pipeline_scholarly.py 300
$T/python scripts/func_len.py src/zyg_workflows/scholarly/stages_55_73.py 400
```

`check_free_names.py` is the gate that matters: a stage that lost a monolith
local is not a syntax error, it is a `NameError` minutes into a GPU run. It
checks that every global a `stage_*` function reads resolves in its module, that
every `ctx.<name>` is a declared `RunContext` field, and that every field read
somewhere is written somewhere. Its three blind spots are listed at the end of
`SPLIT_LOG.md`; read them before trusting a green run.
