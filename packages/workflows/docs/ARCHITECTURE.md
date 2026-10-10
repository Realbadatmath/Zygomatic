<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Architecture

How the four Zygomatic packages fit together, where the data goes, and the one import rule
that keeps the base library usable on its own. The four were separate repositories until
2026-10-05 and still carry those names as directories under `packages/`.

## The four packages

| package | Python package | runs | what it owns |
| --- | --- | --- | --- |
| `workflows` | `zyg_workflows` | nothing by itself; it is imported | the pipelines, the studio option surfaces, the service adapters, the QC and licence gates, the geometry stack |
| `dashboard` | `zyg_dashboard` | the operator GUI, the kanban board, the hub, the session tree | the web application, the job registry wiring, `deploy/` |
| `zero-public` | `zyg_zero` | the public site | the public pages, nomologin, medusa |
| `creator-nexus` | `zyg_nexus` | its own site | the creator nexus package and `site/` |

All four are installed editable into one virtual environment during development, so an import of
`zyg_workflows` from the dashboard resolves to the working tree, not to a copy.

## Ports and endpoints

Every endpoint is an environment variable with a loopback default, declared in
`src/zyg_workflows/paths.py`. `BIND_HOST` defaults to `127.0.0.1`: nothing in the workflow layer
is meant to be reachable from the network.

| variable | default | what answers there |
| --- | --- | --- |
| `ZYG_DASHBOARD_URL` | `http://127.0.0.1:5000` | the operator GUI (`zyg_dashboard`) |
| `ZYG_PUBLIC_URL` | `http://127.0.0.1:5001` | the public site (`zyg_zero`) |
| `ZYG_KANBAN_URL` | `http://127.0.0.1:8899` | the kanban and studio board (`zyg_dashboard`) |
| `ZYG_COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI, not part of these repositories |
| `ZYG_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama, not part of these repositories |
| `ZYG_SESSION_TREE_URL` | `http://127.0.0.1:7100` | the agent job board (`zyg_dashboard`) |
| `ZYG_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis, not part of these repositories |

`pgdb.py` holds the PostgreSQL connection pool used for job and asset state in the production
configuration.

## Data flow

```
operator action in the dashboard (:5000 or the board on :8899)
        |
        v
runtime hook registry  (zyg_workflows.runtime)
   the dashboard has registered its job registry, audit log, benchmark and CSRF
   implementations here at boot; headless, the safe defaults apply
        |
        v
pipeline module  (pipeline_scholarly, pipeline_storyteller, pipeline_kids_*, ...)
   registers a job in runtime.workflow_jobs, runs the work on a daemon thread,
   updates the job status as it goes
        |
        +--> service adapters --> ComfyUI :8188 / Ollama :11434 / Blender / local GPU
        |
        +--> QC and licence gates (qc_contract, anatomy_qc, identity_qc_service,
        |    licence_provenance): a gate may stop the run
        |
        v
data root  (ZYG_DATA_ROOT, ZYG_OUTPUT_ROOT)
   renders, stills, clips, LoRAs, job state, receipts, the Zero audit trail.
   Never inside the repository.
        |
        v
public site (:5001) serves what was published out of that root
```

Three properties of that flow are worth stating explicitly:

- **The dashboard never computes.** It starts jobs and reads their status out of the shared
  registry. The work is in `zyg_workflows`.
- **Nothing is written into the package.** Every output path derives from a `paths.py` constant.
  A checkout is read-only at runtime apart from the scratch directory from `tmp_dir()`.
- **The gates are in the producing layer, not the serving layer.** A frame that fails identity QC
  or the licence gate never reaches the data root, so the public site cannot publish it by
  accident.

## The import contract

Machine-checked by import-linter. The layers contract in `.importlinter` declares, highest layer
first:

```
zyg_dashboard
zyg_zero | zyg_nexus
zyg_workflows
```

A layers contract forbids every upward import, so:

- `zyg_dashboard`, `zyg_zero` and `zyg_nexus` may import `zyg_workflows`.
- `zyg_workflows` may import **none** of the three.
- `zyg_zero` and `zyg_nexus` sit in the same layer, so neither may import the other, and neither
  may import `zyg_dashboard`.

`lint-imports` is a step in `scripts/scan.sh` and in `.github/workflows/ci.yml`, so a violation is
a failing gate rather than a review comment.

Why it matters beyond tidiness: if the base library imported the application on top of it, then
running a pipeline from cron, from a test or from a CLI would require the Flask application and
its whole import graph to exist. The contract is what makes the library independently usable, and
it is what the hook registry below was built to satisfy.

## The runtime hook registry

`src/zyg_workflows/runtime.py`.

The problem it solves is historical and concrete. Pipelines used to reach up into
`zyg_dashboard.crewai_web_gui` for the job registry, the audit log, the CSRF helper and the
benchmark recorders: exactly the forbidden direction. Deleting those calls was not an option,
because with the GUI running they do real work, and inlining the GUI's behaviour would have
duplicated it.

`runtime.py` is the seam. It owns the genuinely shared objects outright and exposes every
GUI-provided behaviour as a module-level hook with a safe headless default:

| hook | headless default | with the dashboard registered |
| --- | --- | --- |
| `workflow_jobs` | a dict owned here | the same dict; the dashboard binds its own name to this object, so both sides mutate one registry |
| `NVENC_SEM` | a semaphore of 4, owned here | the same semaphore (consumer GPUs cap NVENC sessions, one slot is held in reserve) |
| `app`, `limiter` | `None` | the Flask app and its rate limiter |
| `ensure_csrf_token()` | returns `''` (no session to protect) | the real CSRF token |
| `zero_audit_log()` | appends to `ZYG_DATA_ROOT/zero_audit.jsonl` | the dashboard's audit writer |
| `clear_pipeline_halt()` | clears the stop flag through `pipeline_control` | the same, plus the GUI state |
| `gpu_work_active()` | `False` (nothing tracks the GPU) | the dashboard's live GPU bookkeeping |
| `record_token_usage()`, `bm_record()`, `bm_record_pipeline()`, `bench_replay_get()` | no-ops and cache misses | the real accounting and the replay cache |
| `download_assets_background()` | no-op | the background asset downloader |
| `preempt_bank` | `None`, which callers must read as "no brief available" | the pre-emptive generation bank |

Two rules when using it:

- **Call through the module.** `runtime.bm_record(...)`, never
  `from zyg_workflows.runtime import bm_record`. A from-import binds the default at import time
  and goes stale the moment the dashboard registers.
- **Register by name.** `register(**hooks)` raises `KeyError` on an unknown name, so a typo is a
  boot failure instead of a dashboard that silently behaves as if it were headless.

`runtime.py` also holds the timezone helpers the whole package timestamps with (`ams_now()`,
`ams_iso()`, Europe/Amsterdam, falling back to tz-aware UTC if tzdata is missing, never naive)
and `runtime_dir()` for transient pipeline state under the data root.

## The scholarly stage package

`src/zyg_workflows/scholarly/`.

`_run_scholarly_pipeline` was one ~11 000-line function. It is now a 259-line driver in
`pipeline_scholarly.py` that builds two objects and calls twenty-six stage functions; the stage
bodies live in the package:

| module | holds |
| --- | --- |
| `context.py` | `RunContext`, the dataclass carrying every local that crosses a stage boundary, and `StageExit` |
| `stages_01_18.py` | `stage_01` … `stage_09`: topic setup, research, script, fact check, visual tagging, turning points, emotion curve, pre-image TTS, time-locked scene descriptions |
| `stages_19_36.py` | `stage_10`, `stage_12` … `stage_19`: FLUX prompt vocabulary, hand QC, rhythm refresh, LTX motion, assembly, music bed, grade, intro, subtitles |
| `stages_37_54.py` | `stage_11`, `stage_11b`, `stage_11c`: the FLUX still factory — prompt batch, pre-flight, per-slot generate/judge/retry loop |
| `stages_55_73.py` | `stage_55`, `stage_56`, `stage_71`, `stage_72`, `stage_73`: the run scaffold and `RunGlue` |

Two things about it constrain anything built on top:

- **The import direction is fixed.** `pipeline_scholarly` imports the stage modules *inside*
  `_run_scholarly_pipeline`; the stage modules import out of `pipeline_scholarly` at module
  level. Only one of the two can be module-level or the cycle closes at import time, so the lazy
  imports must not be tidied up to the top of the file.
- **A stage cannot return for its caller.** What used to be `return value` out of the monolith is
  `return StageExit(value)`, tested for at the call site.

The module names are the *monolith block ranges* of the split, not stage numbers, and the stage
numbers are the split's, not the pipeline's user-visible `'Stage 4b'` labels. The package's own
`README.md` is the working document — how to write a stage, which gate to run
(`scripts/check_free_names.py`) and what it cannot see — and `SPLIT_LOG.md` is the history.

## Paths, settings and executables

Three small modules that the rest of the package is expected to go through, and that import
nothing from it, so they are safe to import anywhere:

- **`paths.py`** — every filesystem root and service URL, each read from its own `ZYG_*` variable
  with the production value as the fallback, so an unconfigured checkout behaves like the legacy
  installation. The set is now complete: nothing else in the package names a directory. Everything
  hangs off `ZYG_HOME` (default `Path.home()`) — `ZYG_CREWS_ROOT` and its `ZYG_DATA_ROOT` /
  `ZYG_OUTPUT_ROOT`, `ZYG_MODELS_ROOT` with `ZYG_COMFY_ROOT`, `ZYG_FLUX_ROOT` and
  `ZYG_REALESRGAN_ROOT` under it, plus `ZYG_LORA_DATASETS`, `ZYG_LORA_OUTPUTS` and
  `ZYG_MODELS_DIR`. The ComfyUI sub-directories (`ZYG_COMFY_INPUT`, `ZYG_COMFY_OUTPUT`,
  `ZYG_COMFY_MODELS_ROOT`, `ZYG_COMFY_LORA_DIR`) each fall back under `ZYG_COMFY_ROOT`
  independently, never through one of their siblings. Bind address is `BIND_HOST`, the external
  programs are `BLENDER_BIN` and `bin.exe()`, and scratch space is `tmp_dir(sub)`, which creates
  `$ZYG_TMP_DIR/sub` mode `0700` — the only directory the module creates, and the only disk access
  at import time is the PATH lookup for Blender. Setting `ZYG_HOME` alone relocates an entire
  installation; the per-root variables exist for the cases where one tree lives elsewhere.
- **`settings.py`** — the registry of every `ZYG_*` feature flag, **generated** from the source
  that reads it by `scripts/gen_settings.py` (which also writes `.env.example` and
  `docs/configuration.md`). `settings.get(name, cast)` returns the environment value or the
  registered default; `settings.check()` warns about `ZYG_*` names nothing reads, so a typo'd flag
  is visible instead of silently inert. `gen_settings.py --check` fails when the three generated
  files no longer match the source — add an environment read and you must regenerate.
- **`bin.py`** — `exe('ffmpeg')` resolves an external program to an absolute path: the
  `ZYG_BIN_FFMPEG` override first, then `shutil.which`, then `MissingExecutable` naming the binary
  and its override variable. It is the first element of every subprocess argument list, so the
  program a job runs is explicit and an operator can point one at a specific build. The current
  interpreter is `sys.executable`, not `exe('python')`.

The rule that follows: no module hardcodes a path, a host:port or a bare program name. That rule
is now enforced rather than aspirational — `scripts/scan.sh` greps `src`, `deploy`, `site`,
`tests` and `scripts` for home-directory literals and private IP ranges and **fails** the gate on
a single hit (the scanner excludes only itself, since it has to spell the pattern out). Scripts,
tests, shell helpers and the tracked data indices are all keyed to the roots above.
`paths.LEGACY_PREFIXES` survives as the translation table from each pre-migration literal to the
constant that replaced it, with the call-site counts at the time of the move: it is what an
operator reads to port an out-of-tree config, not a list of outstanding work.

## Extension seams

Two registries let a capability be added without touching the module that loads it:

- **Architecture Studio families.** One basename in five places: `arch_ext/<family>.js` for
  geometry and labels, `arch_ext/<family>.json` for the library rail,
  `arch_assistant_ext/<family>.py` for the assistant's tools and prompt,
  `arch_blender_ext/<family>.py` for Blender geometry, and `tests_arch_ext/test_<family>.py` for
  the proof. `src/zyg_workflows/arch_ext/README.md` documents the seam and names the files you
  must not edit for a family; `src/zyg_workflows/arch_ext/CAPABILITIES.md` is generated from the
  live registries by the test sweep.
- **Studio ops.** `mesh_studio_ops/` for Mesh Studio and `studio_ext/` for the other studios: the
  page holds no tool list, so declaring an op is enough for it to appear in the rail.

`plugin_host.py` and `plugin_worker.py` run third-party plugin code out of process;
`skill_sandbox.py` and `skill_sandbox_runner.py` do the same for agent skills.
