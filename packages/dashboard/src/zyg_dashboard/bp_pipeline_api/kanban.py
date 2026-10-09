# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Moved verbatim out of bp_pipeline_api.py (lines 1047-1347) when that 1,782-line module
# became this package. Zero logic edits: the bodies below are byte-for-byte the original.

import logging as _zyg_logging
from flask import (
    jsonify,
    request,
)
from zyg_dashboard import bp_pipeline_api_steps as _steps
from zyg_dashboard.cors import apply_cors
from zyg_workflows import gui_state

from zyg_workflows.char_state_service import (
    _char_reconcile_job_state,
    _char_reload_jobs_from_disk,
    _contact_sheet_reload_jobs_from_disk,
    _contact_sheet_worker_alive,
    _creature_reload_jobs_from_disk,
)
from zyg_workflows.pipeline_runtime import card_times as _card_times
from zyg_workflows.vram_manager import _workflow_job_gpu_active

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _SUBPROC_LOCK,
    _SUBPROC_REGISTRY,
    limiter,
)
from zyg_dashboard.gui.runtime_state import (  # noqa: E402
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _runtime_path,
    _workflow_jobs,
    _workflow_pipeline_worker_alive,
)


from zyg_dashboard.bp_pipeline_api import bp  # the Blueprint the package __init__ creates
from zyg_dashboard.bp_pipeline_api.status import _runtime_payload

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api')


@bp.route('/api/kanban/status')
@limiter.exempt
def kanban_status():
    """Public endpoint for Kanban board — returns per-card job status for the active Clipfarm pipeline.
    Handles both the scholarly pipeline (flat stage dict) and the crime/standard pipeline
    (nested agent dict).  Uses stage_timeline as the authoritative source of truth.
    Always returns CORS headers.

    The card-title taxonomy, the per-department board pick and the four payload
    bodies live in ``bp_pipeline_api_steps``; what is left here is the order in
    which the boards claim priority, the job registry reads, and the response.
    """
    # Find most recent active or latest job (``running`` must have a live worker thread)
    #
    # 2026-10-02: the board auto-picks ONE job and renders that job's department
    # template, and `concurrent_runs` below only ever lists peers in the SAME
    # department. A documentary and a children's song running at the same time
    # therefore showed as ONE run — whichever started later — with no sign the
    # other existed. `?pipeline_id=` lets the operator pin the board to a
    # specific run so the "also running" chips can switch to it.
    active_job = None
    _focus_pid = (request.args.get('pipeline_id') or '').strip()
    if _focus_pid and _focus_pid in _workflow_jobs:
        active_job = _workflow_jobs[_focus_pid]
    for job in (
        () if active_job else sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True)
    ):
        if _workflow_job_gpu_active(job):
            active_job = job
            break
    if active_job is None:
        for job in sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
            if job.get('status') == 'running':
                _pid_stale = (job.get('pipeline_id') or '').strip()
                if _pid_stale and not _workflow_pipeline_worker_alive(_pid_stale):
                    job = dict(job)
                    job['status'] = 'stopped'
                    job['error'] = job.get('error') or 'Stale after restart (no live worker)'
                    job['current_stage'] = None
                    _workflow_jobs[_pid_stale] = job
                continue
    if active_job is None:
        for job in sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
            active_job = job
            break

    _steps._step_hydrate_job_caches(
        gui_state,
        _char_reload_jobs_from_disk,
        _creature_reload_jobs_from_disk,
        _contact_sheet_reload_jobs_from_disk,
    )

    pipeline_running = bool(active_job and _workflow_job_gpu_active(active_job))

    # Contact sheet Kanban only when a live worker is running — not stale disk ``running``.
    # Yield to an active storyteller/documentary/video job in _workflow_jobs.
    active_cs_job = None
    if not pipeline_running:
        active_cs_job = _steps._step_pick_contact_sheet_job(_contact_sheet_jobs, _contact_sheet_worker_alive)
    if active_cs_job and active_cs_job.get('status') == 'running':
        resp = jsonify(_steps._step_contact_sheet_payload(active_cs_job, _runtime_payload, _card_times))
        apply_cors(resp, request)
        return resp

    # Character generation takes Kanban priority while running (even if a storyteller
    # pipeline is also in-flight — users expect the Character Creation board).
    active_char_job = _steps._step_pick_char_job(_char_gen_jobs, _runtime_path(''), _char_reconcile_job_state)

    pipeline_running = active_job and active_job.get('status') == 'running'

    if active_char_job and active_char_job.get('status') == 'running':
        resp = jsonify(_steps._step_char_payload(active_char_job, _runtime_payload, _card_times))
        apply_cors(resp, request)
        return resp

    # Creature LoRA training — Kanban priority after character creation.
    _CR_LIVE = ('running', 'awaiting_review')
    active_creature_job = _steps._step_pick_creature_job(_creature_gen_jobs, _runtime_path(''), _CR_LIVE)

    if active_creature_job and active_creature_job.get('status') in _CR_LIVE:
        # 2026-08-25 sheet workflow cards (names must match kanban_main.js
        # creature_creation prompts and creature_training_service.STAGES_ORDER).
        # The table stays HERE, next to the approve/reject routes it belongs to:
        # tests/test_creature_board_wiring.py reads these titles out of this file.
        from zyg_workflows.char_state_service import CREATURE_STAGE_ORDER as _CR_ORDER
        from zyg_workflows.char_state_service import (
            _creature_refresh_external as _cr_fresh_kb,
            _creature_mark_stale as _cr_stale_kb,
        )

        _CR_CARDS = [
            ('creature_brief', 'Creature Brief'),
            ('anchor', 'Reference Anchor'),
            ('sheet', 'Multi-Angle Sheet'),
            ('sheet_qc', 'Sheet QC'),
            ('sheet_review', 'Sheet Review'),
            ('captions', 'Caption Generation'),
            ('lora_training', 'LoRA Training'),
            ('preview_render', 'Preview Render'),
        ]
        active_creature_job, _stage, creature_cards = _steps._step_creature_stage_and_cards(
            active_creature_job,
            _CR_ORDER,
            _CR_CARDS,
            _cr_fresh_kb,
            _cr_stale_kb,
        )
        resp = jsonify(
            _steps._step_creature_payload(
                active_creature_job,
                _stage,
                creature_cards,
                _runtime_payload,
                _card_times,
            )
        )
        apply_cors(resp, request)
        return resp

    # ── Standalone VACE video runs (scene20_*, The Second Ledger) ─────────────
    # Gated on `not pipeline_running` so a genuine GUI pipeline always wins.
    if not pipeline_running:
        _video_payload = _steps._step_standalone_video_payload()
        if _video_payload:
            resp = jsonify(_video_payload)
            apply_cors(resp, request)
            return resp

    if not active_job:
        # Same keys as the live payload — a client that reads other_runs/live_runs
        # must not have to special-case the idle board.
        resp = jsonify(
            {
                'pipeline': None,
                'cards': {},
                'card_times': {},
                'errors': [],
                'template': 'documentary',
                'model_family': '',
                'concurrent_runs': [],
                'other_runs': [],
                'live_runs': 0,
                'focused_run': '',
            }
        )
        apply_cors(resp, request)
        return resp

    dept = (active_job.get('department') or 'scholarly').lower()
    _mf = active_job.get('model_family') or 'flux'
    KANBAN_STAGE_MAP, template_name = _steps._step_stage_map_for_department(dept, _mf, active_job)

    pipeline_status = active_job.get('status', 'idle')
    current_stage = active_job.get('current_stage', '')

    # ── Build a stage lookup from stage_timeline (most reliable source) ──────
    tl_map, tl_order, cur_idx = _steps._step_timeline_lookup(active_job, current_stage)
    cards, _card_keys = _steps._step_resolve_board_cards(
        KANBAN_STAGE_MAP,
        tl_map,
        tl_order,
        cur_idx,
        pipeline_status,
    )
    # Cards whose stage never matched a timeline row get no clock at all —
    # ``_card_keys.get`` returns None, which equals no entry name.
    card_times = _card_times(active_job, cards, match=lambda card, name: name == _card_keys.get(card))

    # ── Concurrent runs of the same pipeline type ──────────────────────────
    # Was 7 more (8 total), which is what the board's hand-tuned palette held.
    # With 40 pipelines actually running, the board showed 8 and silently
    # dropped the rest — the kanban read as an 8-wide machine (operator,
    # 2026-09-23). The board now derives colours past 8 and packs peers into a
    # grid, so the only remaining ceiling is this one.
    KANBAN_MAX_CONCURRENT_RUNS = 100  # focused run + 99 peers
    concurrent_runs = []
    _same_dept_jobs = [
        j
        for j in sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True)
        if j is not active_job
        and (j.get('department') or 'scholarly').lower() == dept
        and (_workflow_job_gpu_active(j) or j.get('status') == 'running')
    ]
    for _cjob in _same_dept_jobs[: KANBAN_MAX_CONCURRENT_RUNS - 1]:
        concurrent_runs.append(_steps._step_peer_run(_cjob, KANBAN_STAGE_MAP))

    # ── Runs in OTHER departments ─────────────────────────────────────────
    # `concurrent_runs` above is same-department only, and it has to be: a peer
    # is painted as a row of cells under THIS board's cards, and a children's
    # song has no "Stage 3.5" to paint. But those peers were the only thing the
    # payload admitted to, so a run in another department was invisible — the
    # board showed a one-job machine while two pipelines were burning GPU
    # (operator, 2026-10-02). These carry no card map on purpose: they are a
    # name, a department and a stage, enough for the board to say "also running"
    # and to switch to them, and nothing that would fake a card state.
    _other_runs = []
    for _ojob in sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
        if _ojob is active_job:
            continue
        if (_ojob.get('department') or 'scholarly').lower() == dept:
            continue
        if not (_workflow_job_gpu_active(_ojob) or _ojob.get('status') == 'running'):
            continue
        _other_runs.append(
            {
                'pipeline_id': _ojob.get('pipeline_id', ''),
                'department': (_ojob.get('department') or 'scholarly').lower(),
                'status': _ojob.get('status', ''),
                'current_stage': _ojob.get('current_stage') or '',
                'started': _ojob.get('started', ''),
                'topic': _ojob.get('scholarly_topic', '') or _ojob.get('directive', '')[:80],
                'user_name': _ojob.get('user_name', ''),
            }
        )

    # ── Collect debug events for live tail — errors and info separately ──────
    errors, events = _steps._step_live_tail(active_job, _same_dept_jobs)

    # Include sports-video pipeline status so the kanban Templates view can display it
    _sv_status = _steps._step_sports_video_status()

    resp = jsonify(
        {
            'pipeline': {
                'status': pipeline_status,
                'current_stage': current_stage,
                'started': active_job.get('started'),
                'ended': active_job.get('ended'),
                'job_id': active_job.get('pipeline_id', ''),
                'department': active_job.get('department', ''),
                'topic': active_job.get('scholarly_topic', ''),
                'user_name': active_job.get('user_name', ''),
                'url': active_job.get('url', ''),
                'model_family': _mf,
                **_runtime_payload(active_job, pipeline_status == 'running'),
            },
            'cards': cards,
            'card_times': card_times,
            'errors': errors,
            'events': events,
            'template': template_name,
            'model_family': _mf,
            'is_test': bool(active_job.get('is_test', False)),
            'sports_video': _sv_status,
            'concurrent_runs': concurrent_runs,
            'other_runs': _other_runs,
            # What the board is showing against what is actually live, so the UI can
            # never again imply a one-job machine while three pipelines are running.
            'live_runs': 1 + len(concurrent_runs) + len(_other_runs),
            'focused_run': active_job.get('pipeline_id', ''),
        }
    )
    apply_cors(resp, request)
    return resp


@bp.route('/api/kanban/clear_errors', methods=['POST', 'OPTIONS'])
@limiter.exempt
def kanban_clear_errors():
    """Set a watermark on the active job so /api/kanban/status only returns
    debug events that arrive *after* this call.  The UI Clear button calls this."""
    if request.method == 'OPTIONS':
        resp = jsonify({'ok': True})
        apply_cors(resp, request)
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp
    # Find the most-recent job (running first, then latest by start time)
    active_job = None
    for job in sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
        if job.get('status') == 'running':
            active_job = job
            break
    if active_job is None:
        for job in sorted(_workflow_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
            active_job = job
            break
    if active_job is not None:
        # Watermark at current event count — everything up to now is cleared
        active_job['errors_cleared_at_index'] = len(active_job.get('debug_events', []))
    resp = jsonify({'ok': True})
    apply_cors(resp, request)
    return resp


@bp.route('/api/subprocesses')
@limiter.exempt
def api_subprocesses():
    """GET list of all tracked worker subprocesses and their status."""
    with _SUBPROC_LOCK:
        entries = sorted(_SUBPROC_REGISTRY.values(), key=lambda x: x.get('started', ''), reverse=True)
    return jsonify({'subprocesses': entries})


@bp.route('/api/subprocesses/<int:pid>')
def get_subprocess_by_pid(pid):
    with _SUBPROC_LOCK:
        entry = _SUBPROC_REGISTRY.get(pid)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    return jsonify(dict(entry))
