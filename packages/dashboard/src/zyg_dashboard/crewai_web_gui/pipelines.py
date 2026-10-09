#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The pipeline start helpers the API blueprints call.

Lines 1540-1950 of the original module, verbatim: ``_start_video_pipeline_internal``,
``_start_manga_pipeline_internal``, ``_start_creature_pipeline_internal`` and
``_start_storyteller_pipeline_internal``, with the section banners of the video,
Ken Burns and Storyteller tranches that moved to zyg_workflows in 2026-07.
"""

# ruff: noqa: E402,F401  verbatim move: the original import order is load-bearing,
# and every name here is read back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.

from zyg_dashboard.crewai_web_gui._bootstrap import (
    _ams_iso,
    _creature_gen_jobs,
    _workflow_jobs,
    _zyg_log,
    json,
    os,
    threading,
    uuid,
)
from zyg_dashboard.crewai_web_gui.security import _push_error_log
from zyg_dashboard.crewai_web_gui.hardware import _VALID_VISUAL_STYLES
from zyg_dashboard.crewai_web_gui.claude_clips import _clear_pipeline_halt
from zyg_workflows.char_state_service.creature import _creature_save_state, _creature_state_path
from zyg_workflows.pipeline_common import (
    _normalize_pipeline_options,
    _parse_pipeline_model_family,
    _run_creature_training,
)
from zyg_workflows.pipeline_storyteller import _run_storyteller_pipeline
from zyg_workflows.pipeline_video import _run_video_pipeline

# ── Video Pipeline ─────────────────────────────────────────────────────────────


def _start_video_pipeline_internal(
    directive: str = None,
    image_paths: list = None,
    video_duration_minutes: float = 0.5,
    narration_enabled: bool = False,
    visual_style: str = 'cinematic',
    scene_mode: str = 'independent',
    ending_text: str = '',
    model_family: str = 'sdxl',
    pipeline_options: dict | None = None,
    char_id: str = '',
) -> dict:
    """Start the Video pipeline in a background thread. Returns job info."""
    _clear_pipeline_halt()
    pipeline_id = str(uuid.uuid4())
    _stop_event = threading.Event()
    # Validate visual_style
    if visual_style not in _VALID_VISUAL_STYLES:
        visual_style = 'cinematic'
    if scene_mode not in ('independent', 'continuous'):
        scene_mode = 'independent'
    _workflow_jobs[pipeline_id] = {
        'status': 'running',
        'pipeline_id': pipeline_id,
        'department': 'video',
        'started': _ams_iso(),
        'current_stage': None,
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
        'stop_event': _stop_event,
        'image_paths': image_paths or [],
        'narration_enabled': narration_enabled,
        'visual_style': visual_style,
        'scene_mode': scene_mode,
        'ending_text': ending_text.strip(),
        'model_family': _parse_pipeline_model_family(model_family),
        'pipeline_options': _normalize_pipeline_options(pipeline_options),
        'char_id': (char_id or '').strip(),
    }
    threading.Thread(
        target=_run_video_pipeline,
        args=(
            pipeline_id,
            directive,
            image_paths or [],
            video_duration_minutes,
            narration_enabled,
            visual_style,
            scene_mode,
            ending_text.strip(),
        ),
        daemon=True,
        name=f'video-pipeline-{pipeline_id[:8]}',
    ).start()
    return {'job_id': pipeline_id, 'status': 'running'}


def _start_manga_pipeline_internal(
    directive: str = None,
    image_paths: list = None,
    video_duration_minutes: float = 0.5,
    narration_enabled: bool = False,
    scene_mode: str = 'independent',
    ending_text: str = '',
    model_family: str = 'sdxl',
    pipeline_options: dict | None = None,
) -> dict:
    """Start the Manga/comic pipeline — FLUX panels + Ken Burns, no WAN."""
    _clear_pipeline_halt()
    pipeline_id = str(uuid.uuid4())
    _stop_event = threading.Event()
    if scene_mode not in ('independent', 'continuous'):
        scene_mode = 'independent'
    _workflow_jobs[pipeline_id] = {
        'status': 'running',
        'pipeline_id': pipeline_id,
        'department': 'manga',
        'started': _ams_iso(),
        'current_stage': None,
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
        'stop_event': _stop_event,
        'image_paths': image_paths or [],
        'narration_enabled': narration_enabled,
        'visual_style': 'manga',
        'scene_mode': scene_mode,
        'ending_text': ending_text.strip(),
        'model_family': _parse_pipeline_model_family(model_family),
        'pipeline_options': _normalize_pipeline_options(pipeline_options),
    }
    threading.Thread(
        target=_run_video_pipeline,
        args=(
            pipeline_id,
            directive,
            image_paths or [],
            video_duration_minutes,
            narration_enabled,
            'manga',
            scene_mode,
            ending_text.strip(),
        ),
        daemon=True,
        name=f'manga-pipeline-{pipeline_id[:8]}',
    ).start()
    return {'job_id': pipeline_id, 'status': 'running'}


def _start_creature_pipeline_internal(
    directive: str = None,
    image_paths: list = None,
    video_duration_minutes: float = 0.5,
    narration_enabled: bool = False,
    model_family: str = 'flux',
    pipeline_options: dict | None = None,
    creature_options: dict | None = None,
    resume_creature_id: str | None = None,
    phase: str = 'full',
) -> dict:
    """Start Creature Creation — judged multi-angle sheet → review gate → LoRA.

    2026-08-25: ``creature_options`` {source: reference|scratch, angles:
    standard|compact, review_gate: bool}; ``resume_creature_id`` + phase='train'
    resumes a run parked at awaiting_review (the approve endpoint)."""
    _clear_pipeline_halt()
    from zyg_workflows import creature_training_service as _cts_opts

    if resume_creature_id:
        creature_id = resume_creature_id
        job = _creature_gen_jobs.get(creature_id)
        if job is None:
            try:
                with open(_creature_state_path(creature_id), encoding='utf-8') as _fh:
                    job = json.load(_fh)
                _creature_gen_jobs[creature_id] = job
            except Exception:
                return {'error': f'creature {creature_id} not found', 'status': 'rejected'}
        from zyg_workflows.char_state_service import _creature_worker_alive, _creature_mark_stale

        _creature_mark_stale(job)
        if _creature_worker_alive(creature_id):
            return {'error': f'creature {creature_id} already has a live worker', 'status': 'rejected'}
        if phase == 'train' and job.get('status') != 'awaiting_review':
            return {
                'error': f'creature {creature_id} is {job.get("status")}, not awaiting_review',
                'status': 'rejected',
            }
        if phase != 'train' and job.get('status') not in ('interrupted', 'failed', 'stopped', 'awaiting_review'):
            return {
                'error': f'creature {creature_id} is {job.get("status")}; only interrupted/failed/stopped runs resume',
                'status': 'rejected',
            }
        _was_status = job.get('status')
        job['status'] = 'running'
        job['stop_event'] = threading.Event()
        job['error'] = None
        job['approved'] = _ams_iso()
        job['phase'] = phase
        # 2026-08-26 — ownership re-stamp. A job once run by
        # scripts/creature_worker.py keeps worker.mode == 'standalone' in its
        # state file FOR EVER, and _creature_refresh_external re-reads that file
        # on every status poll and replaces the registry entry. An in-GUI resume
        # of such a job therefore had its live dict swapped out from under the
        # worker thread: the thread mutated an orphan, _creature_save_state kept
        # snapshotting the stale disk copy, and a run that finished and parked at
        # awaiting_review was then read back as 'interrupted'. This resume runs
        # HERE, so say so. pid stays None on purpose — liveness for an in-GUI run
        # is its thread, and stamping this PID would make every dead run look
        # alive to _creature_mark_stale.
        job['worker'] = {'pid': None, 'mode': 'in_gui', 'started': _ams_iso(), 'phase': phase}
        # a resumed run reuses brief.json verbatim (operator locks + captions
        # stay stable) — creature_training_service._brief_for_run keys on this
        job['resumed'] = _ams_iso()
        # Flag + log the idle span this resume ends: the pipeline runtime
        # excludes it, so a wall clock longer than the runtime always has a
        # recorded reason behind it (see pipeline_runtime.record_pause).
        try:
            from zyg_workflows.pipeline_runtime import pause_log_line, record_pause

            _pause = record_pause(
                job,
                resumed_at=job['resumed'],
                reason=(
                    'operator gate — sheet review'
                    if _was_status == 'awaiting_review'
                    else f'worker not running (job was {_was_status})'
                ),
            )
            if _pause:
                _pline = pause_log_line(job, _pause)
                job.setdefault('debug_events', []).append(
                    {'ts': job['resumed'], 'level': 'WARN', 'stage': 'Runtime', 'msg': _pline}
                )
                _push_error_log('WARN', 'Runtime', _pline, entity_id=creature_id)
        except Exception as _exc:
            _zyg_log.warning('resume bookkeeping for %s incomplete: %s', creature_id, _exc)
        _creature_save_state(creature_id)
        threading.Thread(
            target=_run_creature_training,
            args=(creature_id, job.get('directive') or '', job.get('image_paths') or []),
            kwargs={'phase': phase},
            daemon=True,
            name=f'creature-train-{creature_id[:8]}',
        ).start()
        return {'job_id': creature_id, 'creature_id': creature_id, 'status': 'running', 'phase': phase}
    creature_id = uuid.uuid4().hex[:12]
    _creature_stop = threading.Event()
    _creature_gen_jobs[creature_id] = {
        'creature_id': creature_id,
        'status': 'running',
        'stop_event': _creature_stop,
        'stage': 'creature_brief',
        'current_stage': 'Creature Brief',
        'started': _ams_iso(),
        'directive': (directive or '').strip(),
        'image_paths': image_paths or [],
        'model_family': _parse_pipeline_model_family(model_family),
        'pipeline_options': _normalize_pipeline_options(pipeline_options),
        'creature_options': _cts_opts.normalize_options(creature_options),
        'phase': phase,
        'error': None,
        'debug_events': [],
        'stage_timeline': [],
        'department': 'creature',
    }
    _creature_save_state(creature_id)
    threading.Thread(
        target=_run_creature_training,
        args=(creature_id, directive, image_paths or []),
        kwargs={'phase': phase},
        daemon=True,
        name=f'creature-train-{creature_id[:8]}',
    ).start()
    return {'job_id': creature_id, 'creature_id': creature_id, 'status': 'running', 'phase': phase}


# 2026-07-17 heavy-tranche: _run_creature_training moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _creature_state_path moved to char_state_service.py


# 2026-07-17 heavy-tranche: _creature_save_state moved to char_state_service.py


# 2026-07-17 heavy-tranche: _creature_stage_key moved to char_state_service.py


# 2026-07-17 heavy-tranche: _creature_derive_pipeline_stage moved to char_state_service.py


# 2026-07-17 heavy-tranche: _creature_reload_jobs_from_disk moved to char_state_service.py


# 2026-07-17 heavy-tranche: _run_video_pipeline moved to pipeline_video.py


from zyg_workflows.pipeline_config import _BOOK_PNG  # noqa: E402,F401  kept at the old definition site
from zyg_workflows.pipeline_config import _BOOK_FONT  # noqa: E402,F401  kept at the old definition site


# 2026-07-17 heavy-tranche: _make_book_intro moved to pipeline_video.py


# 2026-07-17 heavy-tranche: _normalize_word_timings_for_subs moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _align_narration_word_timings moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _burn_subtitles moved to pipeline_video.py


# 2026-07-17 heavy-tranche: _title_from_directive moved to pipeline_scholarly.py


# 2026-07-17 heavy-tranche: _research_title_matches_directive moved to pipeline_scholarly.py


# 2026-07-17 heavy-tranche: _scholarly_duration_targets moved to pipeline_scholarly.py


# 2026-07-17 heavy-tranche: _run_scholarly_pipeline moved to pipeline_scholarly.py


# ══════════════════════════════════════════════════════════════════════════════
# ── Module-level Ken Burns renderer — shared by scholarly + storyteller ───────
# The scholarly pipeline also defines a local closure version that closes over
# _SLIDE_W/_SLIDE_H (1920×1080). This module-level version accepts slide
# dimensions as explicit parameters so the Storyteller pipeline can use a
# different resolution (1280×720) without code duplication.
# 2026-07-17 heavy-tranche: _render_kb_pil_shared moved to pipeline_scholarly.py


# ── Storyteller Pipeline ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


def _start_storyteller_pipeline_internal(
    directive: str = None,
    char_id: str = None,
    character_params: dict = None,
    voice_style: str = 'narration',
    narrator_voice: str = '',
    character_voice: str = '',
    clip_duration_minutes: float = 10.0,
    era_start: int = None,
    era_end: int = None,
    camera_mode: str = 'automatic',
    story_prompt: str = '',
    visual_style: str = 'cinematic',
    narration_enabled: bool = True,
    user_name: str = '',
    model_family: str = 'flux',
    pipeline_options: dict | None = None,
) -> dict:
    """Start the Storyteller pipeline in a background thread. Returns job info."""
    _clear_pipeline_halt()
    _mf_run = _parse_pipeline_model_family(model_family)
    if char_id:
        from zyg_workflows import character_lora_family as _clf_start

        _lora_dir = os.path.expanduser(f'~/lora-outputs/storyteller_chars/{char_id}')
        _fams = _clf_start.char_lora_families_for_dir(_lora_dir)
        if _fams and _mf_run not in _fams:
            return {
                'error': (
                    f'Character {char_id[:8]} has LoRA for '
                    f'{", ".join(_fams)} but this run uses {_mf_run.upper()}. '
                    f'Choose a {_mf_run.upper()} character or switch image backend.'
                ),
                'status': 'rejected',
                'char_id': char_id,
                'model_family': _mf_run,
                'lora_families': _fams,
            }

    pipeline_id = str(uuid.uuid4())
    _stop_event = threading.Event()
    if visual_style not in _VALID_VISUAL_STYLES:
        visual_style = 'cinematic'

    _workflow_jobs[pipeline_id] = {
        'status': 'running',
        'pipeline_id': pipeline_id,
        'department': 'storyteller',
        'started': _ams_iso(),
        'current_stage': None,
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
        'stop_event': _stop_event,
        'char_id': char_id or '',
        'character_params': character_params or {},
        'voice_style': voice_style,
        'narrator_voice': narrator_voice,
        'character_voice': character_voice,
        'clip_duration_minutes': clip_duration_minutes,
        'era_start': era_start,
        'era_end': era_end,
        'camera_mode': camera_mode,
        'story_prompt': story_prompt,
        'visual_style': visual_style,
        'narration_enabled': narration_enabled,
        'user_name': user_name,
        'model_family': _mf_run,
        'pipeline_options': _normalize_pipeline_options(pipeline_options),
    }
    threading.Thread(
        target=_run_storyteller_pipeline,
        args=(pipeline_id,),
        daemon=True,
        name=f'storyteller-pipeline-{pipeline_id[:8]}',
    ).start()
    return {'job_id': pipeline_id, 'status': 'running', 'model_family': _mf_run}


# 2026-07-17 heavy-tranche: _run_storyteller_pipeline moved to pipeline_storyteller.py


# 2026-07-17 heavy-tranche: _synthesise_tts moved to tts_service.py


# ══════════════════════════════════════════════════════════════════════════════
# ── Creature library internal API routes ─────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# 2026-07-17 heavy-tranche: api_internal_creature_list moved to bp_storyteller.py


# ══════════════════════════════════════════════════════════════════════════════
# ── Storyteller internal API routes ──────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# 2026-07-17 heavy-tranche: api_internal_storyteller_list_chars moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: _char_train_lora_for_family moved to char_state_service.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_analyze_character_photo moved to bp_storyteller.py
