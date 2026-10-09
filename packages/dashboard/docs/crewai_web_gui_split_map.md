<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# crewai_web_gui/ split map — which section lives in which module

Wave-1 modularization (2026-10-06). `src/zyg_dashboard/crewai_web_gui.py` (5,102
lines) became the package `src/zyg_dashboard/crewai_web_gui/`; the single file is
deleted. **The import path did not change**, so none of the 138 files that mention
`crewai_web_gui` — including the 31 that do
`from zyg_dashboard.crewai_web_gui import ...` — needed editing.

Every module below is a **verbatim contiguous move** of one of the file's own
sections. Zero logic edits, zero renames: the numeric constants, the LoRA
calibration tables, the loopback bypass list and the provenance comments are the
spec. Proof is mechanical — each original line range is asserted to be a literal
substring of its new module *after* `ruff format` ran (see "Byte-for-byte" below).

## The twelve section modules, in import order

| module | original lines | lines | what it holds |
|---|---|---|---|
| `_bootstrap.py` | 30–356 | 353 | the CUDA allocator env vars, the `__main__` module alias, the venv `sys.path` insertion, the two `.env` loads, the Anthropic SDK audit install, the CPU cap, the HF_TOKEN bootstrap, the shared runtime semaphores, `app` itself, `require_flask_secret`, the `.env` permission hardening, the rate limiter |
| `security.py` | 357–818 | 503 | the 429 handler, the CSRF check, `_is_loopback` with the complete loopback-only session-auth bypass list, the `require_login` `before_request` hook, the canonical-data paths, the dashboard error-log push, the CPU/GPU model-list readers |
| `pages.py` | 819–1182 | 414 | the dual timeline orchestrator, the CPU/GPU model lists out of `ai_model_agent_mapping`, `_load_all_tools`, the `gui.controller` import at the point where `class CrewAIController` used to stand, `/login` and `/`, `_render_dashboard_tab`, the restore-jobs-from-disk startup pass |
| `hardware.py` | 1183–1539 | 378 | `_apply_gpu_power_limit` and its startup application, the subprocess-registry and VRAM-manager re-export markers, the FLUX pipeline caches, the documentary-cinematic style LoRA switch, the visual-style LoRA table with its licence provenance |
| `pipelines.py` | 1540–1950 | 452 | `_start_video_pipeline_internal`, `_start_manga_pipeline_internal`, `_start_creature_pipeline_internal`, `_start_storyteller_pipeline_internal`, and the section banners of the video / Ken Burns / Storyteller tranches that moved to `zyg_workflows` in 2026-07 |
| `contact_sheet.py` | 1951–2568 | 665 | the three manifest-state mutators, the `runtime.register` call that hands the pipelines the three hooks only a running dashboard has, the start-payload parser, `_contact_sheet_launch_run`, the character-preview sweep state |
| `telemetry_gpu.py` | 2569–2839 | 313 | the clipfarm starter, the runtime log rotation, GPU process attribution |
| `telemetry_proc.py` | 2840–3229 | 433 | CPU/RAM process attribution, the disk sweep, the background telemetry sampler (importing it starts the `telemetry-sampler` daemon thread, exactly as original line 3225 did) |
| `zero.py` | 3230–3755 | 555 | `CANONICAL_LLMS`, `DEPENDENCIES_CONFIG`, `get_agent_config`, the Agent Zero legacy shape, the Google-Trends topic pools with the sports blocklist, the Zero kanban sequential queue and its auto-mode scheduler |
| `claude_clips.py` | 3756–4043 | 334 | `_halt_all_pipeline_activity` / `_clear_pipeline_halt`, the `runtime.register` call for the GUI-backed hooks, the Claude collaboration layer |
| `theme.py` | 4044–4559 | 539 | the agent-config display-name lookups, the favicon / apple-touch-icon probes, the dashboard config and theme block with `_theme_version` and the cache-header `after_request`, the smoke-test script table, the HuggingFace `.env` path, the channel-data-retrieval probe, the sports / templates-store / clips-output paths |
| `registration.py` | 4560–4865 | 328 | the bottom block: every blueprint import and `register_blueprint`, and every engine re-export. Still the **last** thing the package imports |

## The three non-section files

| file | lines | what it is |
|---|---|---|
| `__init__.py` | 712 | the original module docstring (lines 7–28, verbatim), the twelve re-export blocks in original order, the tolerant copies and forward-reference write-backs described below, and `__all__` (lines 4866–4967, verbatim — 91 names, unchanged) |
| `__main__.py` | 181 | the `if __name__ == '__main__':` serve entry (lines 4968–5102, verbatim) |
| `_origin.py` | 18 | `ORIGINAL_FILE` — the path `crewai_web_gui.py` had |

## Why `__init__.py` is 712 lines and not a one-liner

It is the shared namespace of the circular blueprint contract (`from
zyg_dashboard.crewai_web_gui import X`, `getattr(_main_mod, 'X')`), so it re-binds
**every** name the single file bound — public and underscore alike — and does it in
the original top-to-bottom order. That order is load-bearing twice over: the
module-level side effects (the telemetry sampler thread, the three
`runtime.register` calls, the blueprint registrations) must run in sequence, and
each `from .mod import (...)` binds its names on the package *before* the next
module is imported — which is what lets `registration` and the `bp_*` modules it
pulls in read every global defined above them off `zyg_dashboard.crewai_web_gui`.

`# ruff: noqa: F401` at the top records that every name there is a re-export.

### Tolerant copies — a soft absence stays soft

Four names in `_bootstrap`, one in `pages`, one in `contact_sheet` and six in
`theme` are bound on only one branch of a `try/except` or an `if`. In the single
file, a failed optional import simply meant the module had no such attribute; a
strict `from .mod import X` would turn that into a hard `ImportError`. So they are
copied across only `if hasattr(...)`:

- `_bootstrap`: `_load_dotenv`, `_llm_audit`, `_cpu_cap`, `_env_mode`
- `pages`: `_here`
- `contact_sheet`: `_CHAR_DEFAULT_MODEL_FAMILY` (also *read* at line 120 and
  normalized at 2424 — the earlier value is imported into the chunk, which is why
  `contact_sheet.py` carries `F811` in its file-level `noqa`)
- `theme`: `init_safety_audit`, `_dc_dir`, `_dc_project_root`, `_dc_layouts`,
  `_cdr`, `_cdr_e_str`

`except ... as e` names are deliberately **not** re-exported: Python deletes them
when the handler ends, so they were never attributes of the single module either.

### Forward references — 27 write-backs

In one file, a function defined at line 1600 could call a global first bound at
line 4623, because the name resolved at **call** time in the one module namespace.
Split across modules, each moved body resolves globals in its *own* module, so the
later binder has to be written back into the earlier module. `__init__.py` does
that with `setattr(sys.modules[...], name, globals()[name])` immediately after the
binding module is imported — nothing is created, it hands over the very object the
single global held, and none of these names is ever rebound.

| bound by | written back into | names |
|---|---|---|
| `claude_clips` | `contact_sheet`, `pipelines`, `telemetry_gpu` | `_clear_pipeline_halt` |
| `registration` | `claude_clips` | `_char_save_state`, `_creature_save_state`, `_evict_all_ollama_models`, `_kill_all_subprocs`, `_release_pipeline_vram` |
| `registration` | `contact_sheet` | `_ZPUB_PENDING_LOCK`, `_bg_contact_sheet_pipeline`, `_contact_sheet_save_state`, `_contact_sheet_state_path`, `_parse_pipeline_model_family`, `_zpub_pending_load`, `_zpub_pending_save` |
| `registration` | `pages` | `_pipeline_current_stage_from_job`, `_resolve_pipeline_public_status` |
| `registration` | `pipelines` | `_creature_save_state`, `_creature_state_path`, `_normalize_pipeline_options`, `_parse_pipeline_model_family`, `_run_creature_training`, `_run_storyteller_pipeline`, `_run_video_pipeline` |
| `registration` | `telemetry_gpu` | `_run_clipfarm_pipeline` |
| `registration` | `telemetry_proc` | `_comfy_vram_used_mb`, `_gpu_work_active` |

ruff cannot see a `setattr`, so each receiving module carries `F821` in its
file-level `# ruff: noqa:` line with that reason spelled out. The alternative —
deferred in-function imports, as the `gui/` split used — would have edited the
moved bodies, which this split forbids.

## `global` statements: two, both honored

`grep -n '^\s*global '` on the original found exactly two live `global`
statements, and the rule ("that name's mutable state and all its mutators stay in
ONE module") is satisfied for both without any boundary being moved:

- `_log_rotate_last_check` (defined 2693, `global` at 2700 in `_rotate_runtime_logs`
  at 2696) — all inside `telemetry_gpu.py` (2569–2839).
- `_PROC_CPU_PREV`, `_PROC_PREV_TS` (defined 2907–2908, `global` at 2915 in
  `_sample_top_processes` at 2913) — all inside `telemetry_proc.py` (2840–3229).

## `__file__` and `__name__` are rebound, deliberately

The package sits one directory deeper than the file did, and two identities were
derived from the file's location:

- **`__file__`** — 26 call sites in the moved sections build a path from
  `os.path.dirname(__file__)` and mean the `zyg_dashboard` package directory. Every
  module here (and `__main__.py`) sets `__file__ = ORIGINAL_FILE` from `_origin.py`
  before the moved code runs, so every resolved path stays byte-identical.
- **`__name__`** — `_bootstrap.py` rebinds it to `'zyg_dashboard.crewai_web_gui'`
  because `Flask(__name__, static_folder='static', static_url_path='/static')`
  derives the app's `root_path` from it. That also keeps
  `logging.getLogger(__name__)` and the `sys.modules[__name__]` alias identical to
  the original.

Both are header lines in the generated modules, above the verbatim body — no moved
line was touched.

## `python -m zyg_dashboard.crewai_web_gui` still serves

All three launchers start the dashboard that way
(`deploy/systemd/user/crewai-gui.service`, `deploy/dashboard_launcher.sh`,
`deploy/docker-entrypoint.sh`). `-m` on a package runs its `__main__.py`, so the
`if __name__ == '__main__':` block moved there verbatim and the command keeps its
meaning. Importing the package still starts nothing that listens — the
`require_flask_secret()` refusal is in `__main__.py`, at serve time, as before.

## Byte-for-byte

Fifteen original line ranges (the twelve sections, the docstring, the `__all__`
block, the serve entry) were each asserted to be a literal substring of the module
that received them, **after** `uv run --no-sync ruff format`. All fifteen pass, and
the ranges are gapless: everything the original held except its 6-line SPDX header
(lines 1–6, re-emitted in every new module) and line 29 (blank) is inside one of
them.

One deviation, in six files: `ruff format` trims blank lines at end of file, so a
section that ended on the original's section-separating blank lines keeps one fewer
of them (`hardware`, `pipelines`, `contact_sheet`, `telemetry_gpu`, `zero`,
`theme`). Whitespace only; no statement differs.

## Namespace: a static superset check, not an import

The `gates.py` recipe prefers an import-based namespace diff. It is not available
here: crewai is deliberately uninstalled on this machine while Ollama **is**
reachable, which makes `import zyg_dashboard.crewai_web_gui` die in
`gui/controller.py`'s `setup_agents` (`CrewAILLM` is `None`) — and the import would
start the telemetry sampler and the blueprint watcher daemons besides. The brief
forbids it.

So the comparison was made on the AST: of the 434 module-level names the original
bound (minus `except`-handler names, which Python deletes, and `__main__`-only
names), **all 434** are bound or tolerantly copied by the package `__init__`, which
binds 445. `__all__` is unchanged, 91 names, and every one of them resolves.

## What was NOT done

No importer was edited, no test was touched, no dependency was added, nothing was
"improved". `crewai` stays out of `packages/dashboard/pyproject.toml` on purpose
(chromadb advisories). The pre-existing failures
`test_pbmetrics.py::test_render_is_short_of_the_anchor_in_frame` and
`test_stills_seal.py::test_picture_studio_module_imports` are untouched and
unrelated.
