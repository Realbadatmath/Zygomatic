<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# gui/ split map — which name lives in which module

Round 2 of the dashboard god-module split (2026-10-06), same pattern as the
`gamesim/` and `video_studio/` packages: every entry below is a **verbatim move**
of a contiguous section of `crewai_web_gui.py` into
`src/zyg_dashboard/gui/`. No logic was rewritten.

`crewai_web_gui.py` re-imports every moved name, so it stays the shared namespace
of the circular blueprint contract and all 28 `bp_*` / pipeline importers resolve
unchanged (`from zyg_dashboard.crewai_web_gui import X` and
`getattr(_main_mod, 'X')`). `__all__` is unchanged and still complete.

`crewai_web_gui.py`: 5,397 → 5,086 lines. `gui/` adds 683 lines across 7 files.

## Where to look for a name

| name | new module |
|---|---|
| `ZoneInfo` | `gui/timeutil.py` |
| `_AMS_TZ` | `gui/timeutil.py` |
| `_ams_iso` | `gui/timeutil.py` (import site; owned by `zyg_workflows.runtime.ams_iso`) |
| `_ams_now` | `gui/timeutil.py` (import site; owned by `zyg_workflows.runtime`) |
| `_parse_iso_to_ams` | `gui/timeutil.py` (import site; owned by `zyg_workflows.runtime`) |
| `API_ADAPTER_AVAILABLE` | `gui/telemetry.py` |
| `API_DEV_MODE`, `API_DEV_TOKEN` | `gui/telemetry.py` |
| `api_get_agents`, `create_approval`, `get_active_schedule`, `get_approval_queue`, `get_integrity_gate`, `get_job_runs`, `get_schedule_pause_state`, `get_schedule_requests`, `get_security_controls`, `get_telemetry`, `set_schedule_pause`, `submit_schedule_request`, `terminate_job_run`, `update_security_control` | `gui/telemetry.py` (the `api_adapter` probe block) |
| `LOGIN_DEBUG`, `PAGE_LOAD_DEBUG`, `BACKEND_DEBUG` | `gui/telemetry.py` |
| `SESSION_VALIDITY_TOKEN` | `gui/telemetry.py` |
| `_login_debug`, `_backend_debug`, `_page_load_debug` | `gui/telemetry.py` |
| `runtime.register(backend_debug=...)` | `gui/telemetry.py` (the call moved with the function) |
| `_TELEMETRY_CACHE` | `gui/telemetry.py` (import site; owned by `zyg_workflows.runtime.TELEMETRY_CACHE`) |
| `_read_local_telemetry` | `gui/telemetry.py` |
| `_get_gpu_bar_mapping`, `_get_cpu_bar_mapping` | `gui/telemetry.py` |
| `_RUNTIME_DIR` + its `os.makedirs` | `gui/runtime_state.py` (import site; owned by `zyg_workflows.pipeline_config`) |
| `_runtime_path` | `gui/runtime_state.py` (import site; owned by `zyg_workflows.runtime`) |
| `_workflow_jobs` | `gui/runtime_state.py` (import site; owned by `zyg_workflows.runtime.workflow_jobs`) |
| `_char_gen_jobs`, `_contact_sheet_jobs`, `_creature_gen_jobs` | `gui/runtime_state.py` (import sites; owned by `zyg_workflows.runtime`) |
| `_workflow_pipeline_worker_alive` | `gui/runtime_state.py` (import site; owned by `zyg_workflows.runtime`) |
| `_reconcile_stale_workflow_jobs` | `gui/runtime_state.py` (import site; owned by `zyg_workflows.runtime`) |
| `_load_json`, `_save_json` | `gui/runtime_state.py` |
| `_ZERO_PUBLIC_TOKEN` | `gui/zero_store.py` |
| `block_spectator_mutation` | `gui/zero_store.py` |
| `AGENT_ZERO_CONFIG_PATH`, `_zero_load_config` | `gui/zero_store.py` |
| `ZERO_TASK_STATE_PATH` | `gui/zero_store.py` |
| `ZERO_AUDIT_PATH`, `_zero_audit_log` | `gui/zero_store.py` (import site; owned by `zyg_dashboard.appcore`) |
| `_start_scholarly_pipeline_internal` | `gui/scholarly.py` |
| `_start_crime_pipeline_internal` (alias of the above) | `gui/scholarly.py` |
| `CrewAILLM`, `Ollama`, `OLLAMA_AVAILABLE` | `gui/controller.py` (the crewai.LLM / Ollama probe) |
| `_OLLAMA_BASE_URL` | `gui/controller.py` (import site; owned by `zyg_workflows.pipeline_config`) |
| `Agent`, `Crew`, `Process`, `Task` | `gui/controller.py` (guarded import; see "crewai is optional" below) |
| `_PREFERRED_MODELS`, `_pick_ollama_model` | `gui/controller.py` |
| `_HEAVY_REASONING_KEYWORDS`, `_pick_model_for_agent` | `gui/controller.py` |
| `CrewAIController` | `gui/controller.py` |
| `controller` (the one process-wide instance) + `runtime.register(controller=...)` | `gui/controller.py` |
| the `infrastructure_tools.register_agent_executor` block | `gui/controller.py` |
| `_ControlPlaneUnavailable` | `gui/controller.py` |

## What deliberately stayed in crewai_web_gui.py

`app` (the Flask object), `limiter.init_app(app)`, `ratelimit_handler`,
`require_login` / `_require_csrf` / `_is_loopback` and the loopback bypass list,
`login_page`, `index`, `_render_dashboard_tab`, `_load_canonical_json`,
`_get_all_tools` / `_load_all_tools`, the telemetry sampler thread, the log
rotation and process/disk samplers, the whole Agent Zero batch/kanban section,
the contact-sheet and pipeline launchers other than scholarly, `__all__`, and the
bottom blueprint-import / registration block. The `bp_*.py` importers were not
touched.

## Import order is load-bearing

`gui/timeutil.py`, `gui/telemetry.py`, `gui/runtime_state.py`,
`gui/zero_store.py` and `gui/scholarly.py` have no import-time dependency back on
`crewai_web_gui`, so `crewai_web_gui.py` re-imports them in one block near the
top, and `gui/__init__.py` re-exports them.

**`gui/controller.py` is the exception.** It instantiates `controller` at import
time, and `CrewAIController.setup_agents` reaches back into `crewai_web_gui` for
`_load_canonical_json` and `_get_all_tools` (a function-local import, resolved at
call time). So `crewai_web_gui.py` imports it from the point in the file where
`class CrewAIController` used to stand — after those two are defined — and
`gui/__init__.py` deliberately does **not** import it.

`gui/scholarly.py` uses the same function-local import for the five collaborators
`_start_scholarly_pipeline_internal` reaches for (`_VALID_VISUAL_STYLES`,
`_clear_pipeline_halt`, `_normalize_pipeline_options`,
`_parse_pipeline_model_family`, `_run_scholarly_pipeline`), which all still live
on `crewai_web_gui`.

## Names rebound via `global` — none of the moved ones

The rebinding audit (`grep -n 'global ' crewai_web_gui.py`) found exactly two
live `global` statements, and **neither names a moved symbol**:

- `_log_rotate_last_check` — rebound in `_rotate_runtime_logs`; the log-rotation
  section stayed in `crewai_web_gui.py`.
- `_PROC_CPU_PREV`, `_PROC_PREV_TS` — rebound in `_sample_top_processes`; the
  process sampler stayed in `crewai_web_gui.py`.

Three further hits are inert markers left by the 2026-07-17 pass
(`pass  # (global stmt removed: names moved to gui_state)`).

So no moved name is ever rebound, and **every** moved name is safely re-exported
*by value*. There is no by-reference-only name in this split: nothing needed the
"expose the module, not the value" treatment. The mutable shared state that would
have needed it (`gui_state._*`, `zyg_workflows.runtime.workflow_jobs`, the
semaphores) is already owned by another module and reached through it.

## crewai is optional again

Before this split, `crewai_web_gui.py:109` held an unguarded
`from crewai import Agent, Task, Crew, Process`, so importing the module — and
therefore every test that wants a route — required crewai to be installed.

That import is gone. The four names are now bound inside `gui/controller.py`'s
existing `try: from crewai import LLM as CrewAILLM / except ImportError:` probe
(they are `None` when crewai is absent), which keeps the re-export surface
`bp_pipeline_api.py` reads (`from zyg_dashboard.crewai_web_gui import Crew,
Process, Task`) intact without making crewai mandatory. `Crew`/`Process`/`Task`
are re-imported a second time *inside* the `register_agent_executor` try block, so
the registration is skipped — not half-done with `None` classes — when crewai is
missing.

All 5,086 lines of `crewai_web_gui.py` and all 7 `gui/` modules now import with no
crewai installed.

## Acceptance: the bare import, with nothing installed and nothing exported

`python -c "import zyg_dashboard.crewai_web_gui"` with no crewai and **no
environment variables at all** now exits 0. Three blockers were cleared for it:

1. `packages/workflows/src/zyg_workflows/stage_runner.py:16` —
   `from crewai import Crew, Process, Task` is now wrapped in
   `try/except ImportError` with `Crew = Process = Task = None`, the same
   sentinel shape `gui/controller.py` uses. `_run_stage_agent` — the only
   consumer of the three names — raises
   `RuntimeError('crewai is not installed: …')` on entry when they are `None`,
   so the failure happens at **call** time, never at import time. The check sits
   *before* the function's own `except Exception` bookkeeping block, which would
   otherwise have swallowed it into a `{'status': 'failed'}` dict.
2. Two exec-by-path loaders still read source files from
   `src/zyg_dashboard/` that the monorepo split moved next to `zyg_workflows`.
   Both now resolve the file from the package that owns it
   (`os.path.dirname(zyg_workflows.__file__)`); the `spec_from_file_location` /
   `exec_module` mechanism is untouched, only the path changed.
   - `crewai_web_gui.py`'s `ai_model_agent_mapping` loader
   - `Schedule/timeline_orchestrator_dual.py`'s `add_entry_timeline` loader

   `ai_model_agent_mapping.py` and `add_entry_timeline.py` exist **only** in
   `packages/workflows/src/zyg_workflows/` — there is no duplicate copy under
   `zyg_dashboard` to prefer.
3. The `FLASK_SECRET_KEY` refusal moved from import time to serve time, the rule
   of commit `bbc1a97` ('Importing a module never requires ffmpeg'). `app.secret_key`
   is set from the environment and simply stays `None` when the variable is absent;
   `crewai_web_gui.require_flask_secret()` raises the **same** `RuntimeError`
   message and is called from every serve entry:
   - `crewai_web_gui.py`'s `if __name__ == '__main__':` block, before `app.run` —
     this is what all three deployment entries run (`deploy/docker-entrypoint.sh`,
     `deploy/dashboard_launcher.sh`, `deploy/systemd/user/crewai-gui.service`, all
     `python -m zyg_dashboard.crewai_web_gui`)
   - `production_server.create_production_app()`, the single chokepoint of both the
     Waitress path and the Flask-dev fallback

   There is **no default key anywhere**. `create_production_app` used to override
   the key with the literal `'your-secret-key-change-this'`; that line is gone, so
   the production server now refuses to start instead of serving signed cookies
   under a published secret.

With the import succeeding, `tests/api/conftest.py`'s `ModuleNotFoundError` skip no
longer fires and the dashboard suite went from **96 passed / 509 skipped** to
**563 passed / 42 skipped** (`pytest -q -m "not gpu and not service"`, exit 0).
Two real defects surfaced in the newly-running tests and were fixed:

- `bp_kidsmusic.py:204` answered 500 on `/api/internal/kidsmusic/status`:
  `__import__('zyg_workflows.pipeline_kidsmusic').STAGES` returns the **top-level**
  `zyg_workflows` package, which has no `STAGES`. Now `importlib.import_module`.
- `tests/test_seal_gates.py`'s two route tests used an anonymous client against
  `/api/internal/pipeline/status/`, which is not one of the loopback-only bypass
  prefixes, so they answered 401. They now carry a session, like
  `tests/api/conftest.py`'s `dash_admin`.

Both test harnesses (`tests/api/conftest.py` and `tests/test_seal_gates.py`)
`setdefault` a throwaway `FLASK_SECRET_KEY`: the import does not need one, but
signing the session cookie the route tests carry does.

2026-10-06: acceptance re-verified — bare `import zyg_dashboard.crewai_web_gui`
with no `FLASK_SECRET_KEY` and no crewai succeeds, and the dashboard suite runs
563 passed / 42 skipped / 1 deselected.
