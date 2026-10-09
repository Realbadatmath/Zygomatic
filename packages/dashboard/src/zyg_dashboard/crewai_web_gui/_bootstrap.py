#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The load-bearing bootstrap: the import block, the environment preparation, the Flask app.

Lines 30-356 of the original single-file module: the CUDA allocator env vars, the
two ``.env`` loads, the Anthropic SDK audit install, the CPU cap, the HF_TOKEN
bootstrap, the shared runtime semaphores, ``app`` itself, ``require_flask_secret``,
the ``.env`` permission hardening and the rate limiter.

``app`` carries the dotted name of the package, so ``app.logger`` keeps its channel,
and its ``root_path`` is pinned to ``zyg_dashboard.paths.PKG_DIR`` — the directory
where ``static/`` and ``templates/`` live.
"""

# ruff: noqa: E402,F401  verbatim move: the original import order is load-bearing,
# and every name here is read back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.

from zyg_dashboard import paths as _dash_paths

import atexit
import glob
import hashlib
import hmac
import html as html_module
import importlib.util
import json
import logging as _zyg_logging
import os
import secrets
import shutil
import stat as _stat_mod
import sys
import threading
import time
import uuid
from datetime import timedelta

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.crewai_web_gui')  # channel kept from the pre-split module

# CUDA allocator: expandable segments prevent fragmentation OOM when the
# FLUX transformer denoising loop leaves reserved-but-freed blocks in the pool,
# then the VAE decode needs a contiguous 144 MB block.  Must be set before any
# CUDA memory operation.
if 'PYTORCH_CUDA_ALLOC_CONF' not in os.environ:
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

# 2026-07-17 modularization: a sys.modules['zyg_dashboard.crewai_web_gui'] alias stood
# here for the days this file was started as a script and so registered only as
# `__main__`. The package's __main__.py is the serve entry now, the module is always
# imported under its real name, and the alias had nothing left to point at.
# 2026-07-17 heavy-tranche modularization: shared mutable pipeline state lives in gui_state
from zyg_workflows import gui_state  # noqa: E402  kept at the old import site

# 2026-10-05 layering: the pipelines no longer import this module. They call
# zyg_workflows.runtime, whose hooks this file registers (the runtime.register
# calls below) and whose shared objects (workflow_jobs, NVENC_SEM) it reuses.
from zyg_workflows import runtime  # noqa: E402  kept at the old import site
from zyg_workflows.bin import exe  # noqa: E402  kept at the old import site
from zyg_workflows.paths import (  # noqa: E402  kept at the old import site
    BIND_HOST,
    ZYG_DASHBOARD_URL,
    ZYG_OLLAMA_URL,  # noqa: F401  re-export: gui/controller.py took the last use in this file
    ZYG_REDIS_URL,
    tmp_dir,
)

# The venv site-packages path the pre-split module inserted on sys.path when it was
# started with a bare python3. The directory has never existed under the package
# layout, so the insert is gone; the constant stays because the package __init__
# re-exports it.
_VENV_SP = str(_dash_paths.PKG_DIR.parent / '.venv' / 'lib' / 'python3.12' / 'site-packages')

# Load root .env so env vars are always available even on manual/bare restarts.
# override=False: never clobber values already injected by start_production.sh.
_ROOT_ENV = str(_dash_paths.PKG_DIR.parent.parent / '.env')  # packages/dashboard/.env
try:
    from dotenv import load_dotenv as _load_dotenv

    if os.path.isfile(_ROOT_ENV):
        _load_dotenv(_ROOT_ENV, override=False)
except ImportError as _exc:
    _zyg_log.warning('python-dotenv missing, the root .env is not loaded: %s', _exc)

import requests  # noqa: E402,F401  re-export: gui/controller.py took the last use in this file
from flask import (  # noqa: E402  the original import order is load-bearing
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    redirect,
    session,
    url_for,
)
from zyg_dashboard.appcore import get_remote_address  # noqa: E402,F401  moved to appcore, kept at the old import site

# 2026-10-06 round-2 split: `from crewai import Agent, Task, Crew, Process` stood here and was the
# only unguarded crewai import in the file, so importing this module required crewai to be installed.
# The four names are used exclusively by the controller section, which now lives in gui/controller.py
# and imports them inside the function / the try block that needs them. crewai is optional again.
from zyg_dashboard.cors import apply_cors  # noqa: E402  after the sys.path setup above

# 2026-10-05 layering: the pipeline constants and the shared runtime objects
# below were defined in this file and from-imported by zyg_workflows — the
# base library importing the application above it. They live in the base
# library now and are imported back here, so each still has ONE definition.
from zyg_workflows.pipeline_config import (  # noqa: E402
    _CHANNEL_VOICES_PATH,
    _CHAR_DEFAULT_MODEL_FAMILY,
    _CLIPFARM_STAGES,
    _FLUX_PERF_TELEMETRY_PATH,
    _RUNTIME_DIR,
    _VOICE_LIBRARY_PATH,
    _caveman_kw,
    _dsl,
)
from zyg_workflows.runtime import _agent_log  # noqa: E402

# ── 2026-10-06 round-2 split: the gui/ package ───────────────────────────────
# The sections below moved VERBATIM out of this file into zyg_dashboard.gui.*
# (see packages/dashboard/docs/gui_split_map.md for the name -> module table) and
# are re-imported here, because this module is the shared namespace of the
# circular blueprint contract: the 28 bp_* / pipeline importers read these names
# off `zyg_dashboard.crewai_web_gui`, so every one of them must still resolve.
# gui.controller is NOT imported here — it instantiates `controller` at import
# time and reaches back for _load_canonical_json / _get_all_tools, so it is
# imported further down, from the point where the class used to stand.
from zyg_dashboard.gui.runtime_state import (  # noqa: E402,F401  re-exports, read off this module
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _load_json,
    _reconcile_stale_workflow_jobs,
    _runtime_path,
    _save_json,
    _workflow_jobs,
    _workflow_pipeline_worker_alive,
)
from zyg_dashboard.gui.scholarly import (  # noqa: E402,F401  re-exports, read off this module
    _start_crime_pipeline_internal,
    _start_scholarly_pipeline_internal,
)
from zyg_dashboard.gui.telemetry import (  # noqa: E402,F401  re-exports, read off this module
    API_ADAPTER_AVAILABLE,
    API_DEV_MODE,
    API_DEV_TOKEN,
    BACKEND_DEBUG,
    LOGIN_DEBUG,
    PAGE_LOAD_DEBUG,
    SESSION_VALIDITY_TOKEN,
    _backend_debug,
    _get_cpu_bar_mapping,
    _get_gpu_bar_mapping,
    _login_debug,
    _page_load_debug,
    _read_local_telemetry,
    _TELEMETRY_CACHE,
    api_get_agents,
    create_approval,
    get_active_schedule,
    get_approval_queue,
    get_integrity_gate,
    get_job_runs,
    get_schedule_pause_state,
    get_schedule_requests,
    get_security_controls,
    get_telemetry,
    set_schedule_pause,
    submit_schedule_request,
    terminate_job_run,
    update_security_control,
)
from zyg_dashboard.gui.timeutil import (  # noqa: E402,F401  re-exports, read off this module
    ZoneInfo,
    _AMS_TZ,
    _ams_iso,
    _ams_now,
    _parse_iso_to_ams,
)
from zyg_dashboard.gui.zero_store import (  # noqa: E402,F401  re-exports, read off this module
    AGENT_ZERO_CONFIG_PATH,
    ZERO_AUDIT_PATH,
    ZERO_TASK_STATE_PATH,
    _ZERO_PUBLIC_TOKEN,
    _zero_audit_log,
    _zero_load_config,
    block_spectator_mutation,
)

# 2026-10-05 layering: _caveman_kw moved to zyg_workflows.pipeline_config

# Load .env so ANTHROPIC_API_KEY and other secrets reach os.environ at runtime.
# override=False means already-set vars (e.g. FLASK_SECRET_KEY set at shell startup) are not clobbered.
_dotenv_path = str(_dash_paths.PKG_DIR.parent.parent / '.env')  # packages/dashboard/.env
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_dotenv_path, override=False)
except ImportError as _exc:
    _zyg_log.warning('python-dotenv missing, %s is not loaded: %s', _dotenv_path, _exc)

# Instrument the Anthropic SDK before any pipeline module imports it, so EVERY
# messages.create in the process is recorded without a call site having to ask.
# An AST audit on 2026-08-20 found 39 of 45 LLM call sites unlogged; opt-in
# logging is what allowed that, so this is deliberately not opt-in.
try:
    from zyg_workflows import llm_audit as _llm_audit

    _llm_audit.install(log_fn=lambda m: _zyg_log.info(m))
except Exception as _audit_e:  # never block startup on auditing
    _zyg_log.info(f'[llm_audit] not installed: {_audit_e!r}')

# Pin this process (Flask + all Python threads + forked children) to the shared
# core ceiling. This used to hardcode set(range(21)) — 21 cores — which SILENTLY
# WIDENED the 0-19 mask inherited from the cap script, in every process that
# imports this module. One number, defined once, in cpu_cap.
try:
    from zyg_workflows import cpu_cap as _cpu_cap

    _cpu_cap.apply_to_self()
except Exception as _exc:
    _zyg_log.warning('cpu cap not applied, this process keeps the inherited affinity: %s', _exc)


def _bootstrap_hf_token_from_env_file() -> None:
    """Prefer .env HF_TOKEN over a stale process environment (fine-grained tokens)."""
    try:
        with open(_dotenv_path, 'r', encoding='utf-8') as _hf_fh:
            for _hf_line in _hf_fh:
                _hf_line = _hf_line.strip()
                if _hf_line.startswith('HF_TOKEN='):
                    _hf_tok = _hf_line[len('HF_TOKEN=') :].strip().strip('"').strip("'")
                    if _hf_tok:
                        os.environ['HF_TOKEN'] = _hf_tok
                    return
    except Exception as _exc:
        _zyg_log.warning('HF_TOKEN not bootstrapped from %s, hub downloads stay anonymous: %s', _dotenv_path, _exc)


_bootstrap_hf_token_from_env_file()

# Prevent CUDA allocator fragmentation.
# Default PyTorch allocator uses fixed-size segments; when a model partially fills a segment
# and then OOMs, the reserved-but-unused tail becomes unreachable by subsequent allocations.
# expandable_segments:True allows the allocator to grow/shrink segments, eliminating the
# "30 MB free but 64 MB needed as a contiguous block" OOM class entirely.
# Must be set before any CUDA context is created (torch is imported lazily here, so this works).
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')

# Limit concurrent NVENC sessions — RTX consumer GPUs cap at 5 by default;
# holding 1 slot in reserve avoids "cannot allocate memory" failures under parallel load.
# Owned by zyg_workflows.runtime so the GUI and the pipelines share ONE semaphore.
_NVENC_SEM = runtime.NVENC_SEM

# 2026-10-05 layering: _KB_ENCODE_WAIT_MIN_S moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _KB_ENCODE_WAIT_PER_DUR_S moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _KB_ENCODE_WAIT_PAD_S moved to zyg_workflows.pipeline_config
from zyg_workflows.pipeline_config import _KB_THREAD_STAGGER_S  # noqa: E402,F401  kept at the old definition site


# 2026-07-17 heavy-tranche: _kb_encode_wait_seconds moved to encode_utils.py
# Cap concurrent post-process passes (outro overlay + bleep + loudnorm) — each is a ffmpeg
# process that can use GPU memory. 2 at a time keeps VRAM safe alongside NVENC encodes.
from zyg_workflows.runtime import POSTPROC_SEM as _POSTPROC_SEM  # noqa: E402,F401  kept at the old definition site

# Serializes GPU-heavy model stages across concurrent pipelines.
# Prevents two threads from loading FLUX (~35 GB) + WAN (~28 GB) simultaneously on 48 GB card.
from zyg_workflows.runtime import GPU_PIPELINE_LOCK as _GPU_PIPELINE_LOCK  # noqa: E402,F401  kept at the old definition site

# 2026-10-05 layering: _FORCE_CPU_POST_ENCODE moved to zyg_workflows.pipeline_config


# 2026-07-17 heavy-tranche: _cq_for_crf moved to encode_utils.py


# 2026-07-17 heavy-tranche: _nvenc_vcodec_args moved to encode_utils.py


# 2026-07-17 heavy-tranche: _x264_vcodec_args moved to encode_utils.py


# 2026-07-17 heavy-tranche: _ffmpeg_run_nvenc_first moved to encode_utils.py


# 2026-07-17 heavy-tranche: _ffmpeg_popen_nvenc_first moved to encode_utils.py


# 2026-10-06 round-2 split: _AMS_TZ moved to zyg_dashboard.gui.timeutil
# 2026-10-05 layering: _ams_now, _ams_iso, _parse_iso_to_ams moved to zyg_workflows.runtime
# (their dashboard-side import site is zyg_dashboard.gui.timeutil now)


app = Flask(
    # Flask names app.logger after the import name: channel kept from the pre-split module.
    'zyg_dashboard.crewai_web_gui',
    static_folder='static',
    static_url_path='/static',
    # Flask would derive root_path from the importing module's file, which is one
    # directory deeper than the zyg_dashboard package. Pinning it to the package
    # directory keeps templates/ and static/ where they are.
    root_path=str(_dash_paths.PKG_DIR),
)  # static/ (lowercase since 2026-10-08) — the folder name is case-sensitive on Linux
app.config['TEMPLATES_AUTO_RELOAD'] = True  # always re-read templates from disk; no restart needed after template edits
# Importing a module never requires the environment (the rule from commit bbc1a97,
# 'Importing a module never requires ffmpeg'). So the missing-secret refusal is NOT
# raised here: `app.secret_key` stays None and every serve entry calls
# `require_flask_secret()` first, which refuses to start. There is no default key —
# absence still means the dashboard will not serve, it just means it can be imported.
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)


def require_flask_secret():
    """Refuse to serve without a real FLASK_SECRET_KEY. Called by every serve entry."""
    if not app.secret_key:
        raise RuntimeError(
            'FLASK_SECRET_KEY environment variable is not set. '
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )


# ── .env permissions hardening — runs at import time, not just __main__ ──────
_env_path = str(_dash_paths.PKG_DIR.parent / '.env')  # packages/dashboard/src/.env
if os.path.exists(_env_path):
    _env_mode = os.stat(_env_path).st_mode
    if _env_mode & (_stat_mod.S_IRGRP | _stat_mod.S_IROTH | _stat_mod.S_IWGRP | _stat_mod.S_IWOTH):
        try:
            os.chmod(_env_path, 0o600)
            _zyg_log.info(f'[SECURITY] .env was {oct(_env_mode & 0o777)} — auto-corrected to 600.')
        except OSError as _e:
            _zyg_log.info(
                f'[SECURITY WARNING] .env has loose permissions {oct(_env_mode & 0o777)} and could not be fixed: {_e}'
            )
# ─────────────────────────────────────────────────────────────────────────────

# 2026-10-06 round-2 split: _ZERO_PUBLIC_TOKEN moved to zyg_dashboard.gui.zero_store


# Rate limiting: coarse at proxy, fine-grained in app for sensitive endpoints
# 2026-10-06 layering: _rate_limit_key and the Limiter moved to zyg_dashboard.appcore
from zyg_dashboard.appcore import _rate_limit_key  # noqa: E402,F401  kept at the old definition site
from zyg_dashboard.appcore import limiter  # noqa: E402  kept at the old definition site

limiter.init_app(app)

# Hand the Flask app and the rate limiter to the pipelines' runtime seam. The
# behavioural hooks follow further down, once the functions they bind exist.
runtime.register(app=app, limiter=limiter)
