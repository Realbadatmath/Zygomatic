# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stage_runner — the ClipFarm stage preflights, prompt log and agent runner.

Was a single 2,949-line module; split 2026-10-06 into the sections it already
carried, with no logic change.  The import path is unchanged: everything the
file defined is re-exported here, so ``from zyg_workflows.stage_runner import
_log_prompt`` and ``stage_runner.os`` resolve exactly as before.

    prompts.py             _TEST_ID_PREFIXES_FALLBACK, _is_test_pid, _log_prompt,
                           _register_prompt                       (55-68, 71-172, 359-476)
    subject.py             _classify_subject_type, _build_framework_block  (175-356)
    agents.py              _run_stage_agent, _pf_agents_active,
                           _pf_agents_done                        (479-618)
    preflight.py           _stage_preflight: _save/_log_* and the stage dispatch (621-653)
    stage1.py              _pf_stage_1                            (655-689)
    stage3.py              _pf_stage_3                            (691-805)
    stage4a.py             _pf_stage_4a                           (807-1022)
    stage4b.py             _pf_stage_4b                           (1024-2643, less the four below)
    stage4b_keywords.py    _make_keyword_tables                   (1061-1238)
    stage4b_models.py      _make_github_models                    (1331-1727)
    stage4b_post.py        _make_post_process_clip                (1870-2077)
    stage4b_render.py      _make_render_clip                      (2213-2510)
    tasks.py               _build_task_desc                       (2646-2747)
    health.py              _load_workflow_overrides, _check_workflow_health (2750-2827)
    delivery.py            _scp_output_to_windows                 (2830-2949)
"""

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
import subprocess
import sys
import threading
from zyg_workflows import gui_state

try:
    from crewai import Crew, Process, Task
except ImportError:  # crewai is optional: importing this module must never need it
    Crew = Process = Task = None
from zyg_workflows import http_json, paths, runtime
from zyg_workflows.narrator_voice_service import _get_narrator_voice, _vid_to_channel_id
from zyg_workflows.bin import exe
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.pipeline_config import (
    _caveman_kw,
    _dsl,
    _NARRATOR_OUTRO,
    _OLLAMA_BASE_URL,
    _SENSITIVE_TOPIC_KEYWORDS,
)
from zyg_workflows.runtime import (
    _AGENT_LOG_LOCK,
    _agent_log,
    _ams_iso,
    _ams_now,
    _NVENC_SEM,
    _ollama_semaphore,
    _parse_iso_to_ams,
    _POSTPROC_SEM,
    _record_token_usage,
    _runtime_path,
    workflow_jobs as _workflow_jobs,
)
from zyg_workflows.subproc_registry import _finish_subproc, _register_marker, _register_subproc, _update_marker
from zyg_workflows.tts_service import _bleep_audio_in_clip, _mask_bad_words, _sanitize_title, _tts_shared
from zyg_workflows.vram_manager import _wait_ollama_unload
import logging as _zyg_logging

import sys as _sys
import types as _types

from zyg_workflows.stage_runner import agents as _s_agents
from zyg_workflows.stage_runner import delivery as _s_delivery
from zyg_workflows.stage_runner import health as _s_health
from zyg_workflows.stage_runner import preflight as _s_preflight
from zyg_workflows.stage_runner import prompts as _s_prompts
from zyg_workflows.stage_runner import stage1 as _s_stage1
from zyg_workflows.stage_runner import stage3 as _s_stage3
from zyg_workflows.stage_runner import stage4a as _s_stage4a
from zyg_workflows.stage_runner import stage4b as _s_stage4b
from zyg_workflows.stage_runner import stage4b_keywords as _s_stage4b_keywords
from zyg_workflows.stage_runner import stage4b_models as _s_stage4b_models
from zyg_workflows.stage_runner import stage4b_post as _s_stage4b_post
from zyg_workflows.stage_runner import stage4b_render as _s_stage4b_render
from zyg_workflows.stage_runner import subject as _s_subject
from zyg_workflows.stage_runner import tasks as _s_tasks

from zyg_workflows.stage_runner.prompts import (
    _is_test_pid,
    _log_prompt,
    _register_prompt,
    _TEST_ID_PREFIXES_FALLBACK,
)
from zyg_workflows.stage_runner.subject import _build_framework_block, _classify_subject_type
from zyg_workflows.stage_runner.agents import _pf_agents_active, _pf_agents_done, _run_stage_agent
from zyg_workflows.stage_runner.preflight import _stage_preflight
from zyg_workflows.stage_runner.stage1 import _pf_stage_1
from zyg_workflows.stage_runner.stage3 import _pf_stage_3
from zyg_workflows.stage_runner.stage4a import _pf_stage_4a
from zyg_workflows.stage_runner.stage4b import _pf_stage_4b
from zyg_workflows.stage_runner.stage4b_keywords import _make_keyword_tables
from zyg_workflows.stage_runner.stage4b_models import _make_github_models
from zyg_workflows.stage_runner.stage4b_post import _make_post_process_clip
from zyg_workflows.stage_runner.stage4b_render import _make_render_clip
from zyg_workflows.stage_runner.tasks import _build_task_desc
from zyg_workflows.stage_runner.health import _check_workflow_health, _load_workflow_overrides
from zyg_workflows.stage_runner.delivery import _scp_output_to_windows

_zyg_log = _zyg_logging.getLogger(__name__)

# Never defined at module scope in crewai_web_gui.py either, so the ``getattr``
# this replaces always yielded None, and both uses in the sections are guarded by it.
_srt_path = None

_SECTIONS = (
    _s_prompts,
    _s_subject,
    _s_agents,
    _s_preflight,
    _s_stage1,
    _s_stage3,
    _s_stage4a,
    _s_stage4b,
    _s_stage4b_keywords,
    _s_stage4b_models,
    _s_stage4b_post,
    _s_stage4b_render,
    _s_tasks,
    _s_health,
    _s_delivery,
)


class _OneNamespace(_types.ModuleType):
    """The package answers rebinding the way the single file did.

    The old module was one namespace: ``monkeypatch.setattr(stage_runner,
    '_runtime_path', …)`` changed what every function in the file saw, and
    test_scp_seal_gate.py leans on exactly that before calling
    ``_scp_output_to_windows``.  Split across sections, each section holds its
    own binding, so a setattr on the package alone would be invisible to the
    code that reads the name.  Setting an attribute here therefore also rebinds
    it in every section that holds it — one namespace again, by delegation.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _mod in self.__dict__.get('_SECTIONS') or ():
            if name in _mod.__dict__:
                _mod.__dict__[name] = value

    def __delattr__(self, name):
        super().__delattr__(name)
        for _mod in self.__dict__.get('_SECTIONS') or ():
            _mod.__dict__.pop(name, None)


_sys.modules[__name__].__class__ = _OneNamespace

# Every name imported above is re-exported, not used here: this package IS the module
# the split replaced, so `__all__` declares the surface instead of a file-level noqa.
__all__ = [
    'json',
    'os',
    'subprocess',
    'sys',
    'threading',
    'gui_state',
    'http_json',
    'paths',
    'runtime',
    '_get_narrator_voice',
    '_vid_to_channel_id',
    'exe',
    '_seal',
    '_caveman_kw',
    '_dsl',
    '_NARRATOR_OUTRO',
    '_OLLAMA_BASE_URL',
    '_SENSITIVE_TOPIC_KEYWORDS',
    '_AGENT_LOG_LOCK',
    '_agent_log',
    '_ams_iso',
    '_ams_now',
    '_NVENC_SEM',
    '_ollama_semaphore',
    '_parse_iso_to_ams',
    '_POSTPROC_SEM',
    '_record_token_usage',
    '_runtime_path',
    '_workflow_jobs',
    '_finish_subproc',
    '_register_marker',
    '_register_subproc',
    '_update_marker',
    '_bleep_audio_in_clip',
    '_mask_bad_words',
    '_sanitize_title',
    '_tts_shared',
    '_wait_ollama_unload',
    '_is_test_pid',
    '_log_prompt',
    '_register_prompt',
    '_TEST_ID_PREFIXES_FALLBACK',
    '_build_framework_block',
    '_classify_subject_type',
    '_pf_agents_active',
    '_pf_agents_done',
    '_run_stage_agent',
    '_stage_preflight',
    '_pf_stage_1',
    '_pf_stage_3',
    '_pf_stage_4a',
    '_pf_stage_4b',
    '_make_keyword_tables',
    '_make_github_models',
    '_make_post_process_clip',
    '_make_render_clip',
    '_build_task_desc',
    '_check_workflow_health',
    '_load_workflow_overrides',
    '_scp_output_to_windows',
]
