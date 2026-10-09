# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The named steps of the ``kanban_status`` route body.

Moved verbatim from ``bp_pipeline_api_steps.py`` lines 532-1098 by the
2026-10-06 modularization split.
"""

import json
import logging as _zyg_logging
import os

from zyg_workflows.char_state_service import (
    _char_derive_pipeline_stage,
    _contact_sheet_derive_stage,
    _creature_derive_pipeline_stage,
    _normalize_char_model_family,
)
from zyg_workflows.pipeline_common import _parse_pipeline_model_family

from .stage_maps import _SPORTS_VIDEO_STATUS

# Bound by assignment, not by ``from .stage_maps import _zyg_log``: the name is
# the same singleton either way, and an assigned global keeps the moved code's
# original method-call form.
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api_steps')


def _step_debug_event_lines(raw_events, msg_limit=140):
    """``(errors, events)`` as formatted ``[ts] [stage] msg`` lines.

    The contact-sheet, character and creature branches each had a byte-identical
    copy of this loop; the only thing that ever differed was the name of the
    local list.
    """
    errors, events = [], []
    for _cev in raw_events:
        _clvl = str(_cev.get('level', 'INFO')).upper()
        _cline = f'[{_cev.get("ts", "?")}] [{_cev.get("stage", "?")}] {str(_cev.get("msg", ""))[:msg_limit]}'
        if _clvl in ('WARN', 'WARNING', 'ERROR', 'CRITICAL'):
            errors.append(_cline)
        else:
            events.append(_cline)
    return errors, events


def _step_hydrate_job_caches(gui_state, char_reload, creature_reload, contact_sheet_reload):
    """Hydrate char + creature + contact-sheet jobs from disk once per process."""
    if not gui_state._CHAR_GEN_RELOAD_DONE:
        try:
            char_reload()
        except Exception as _exc:
            _zyg_log.warning('character job hydrate from disk failed, board shows live jobs only: %s', _exc)
        gui_state._CHAR_GEN_RELOAD_DONE = True
    if not gui_state._CREATURE_GEN_RELOAD_DONE:
        try:
            creature_reload()
        except Exception as _exc:
            _zyg_log.warning('creature job hydrate from disk failed, board shows live jobs only: %s', _exc)
        gui_state._CREATURE_GEN_RELOAD_DONE = True
    if not gui_state._CONTACT_SHEET_RELOAD_DONE:
        # Reload once per process, like the char/creature hydrates above. The
        # old unconditional per-request reload replaced live job dicts with
        # disk snapshots, severing them from their worker threads (stage froze
        # at the snapshot; approve API then 400'd on a stale stage).
        try:
            contact_sheet_reload()
        except Exception as _exc:
            _zyg_log.warning('contact-sheet job hydrate from disk failed, board shows live jobs only: %s', _exc)
        gui_state._CONTACT_SHEET_RELOAD_DONE = True


def _step_pick_contact_sheet_job(contact_sheet_jobs, worker_alive):
    """The newest contact-sheet job with a LIVE worker, or None.

    Stale disk ``running`` does not count: the caller yields the board to an
    active storyteller/documentary/video job instead.
    """
    for csj in sorted(contact_sheet_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
        if csj.get('status') != 'running':
            continue
        _cid_cs = (csj.get('char_id') or '').strip()
        if _cid_cs and worker_alive(_cid_cs):
            return csj
    return None


def _step_contact_sheet_payload(active_cs_job, runtime_payload, card_times):
    """The /api/kanban/status body for a running contact-sheet job."""
    _stage = _contact_sheet_derive_stage(active_cs_job)
    _cs_mf = _parse_pipeline_model_family(active_cs_job.get('model_family', 'flux'))
    _ORDER = [
        'sheet_generate',
        'awaiting_approval',
        'tile_crop',
        'identity_qc',
        'captions',
        'lora_training',
        'angle_expansion',
        'lora_refine',
        'done',
    ]
    _idx = _ORDER.index(_stage) if _stage in _ORDER else 0
    _sheet_done = _idx > 0
    _approve_done = _idx > 1 or bool(active_cs_job.get('approved'))
    _crop_done = _idx > 2
    _idqc_done = _idx > 3
    _cap_done = _idx > 4
    _lora_done = _idx > 5
    _angle_done = _idx > 6
    _lora_run = _stage == 'lora_training'
    _angle_run = _stage == 'angle_expansion'
    _refine_run = _stage == 'lora_refine'
    _is_done = _stage == 'done' or active_cs_job.get('status') == 'done'

    _lora_card = 'SimpleTuner SDXL LoRA Training' if _cs_mf == 'sdxl' else 'SimpleTuner FLUX LoRA Training'
    # VLM Defect Judge runs as a substage of identity_qc (2026-07-16):
    # 'vlm_judge' while judging; regen substages mean the judge pass is over.
    _cs_substage = str(active_cs_job.get('sheet_substage') or '')
    _vlm_run = _stage == 'identity_qc' and _cs_substage == 'vlm_judge'
    _vlm_done = _idqc_done or (_stage == 'identity_qc' and _cs_substage.startswith('idqc_regen'))
    cs_cards = {
        'Contact Sheet Generation': 'done' if _sheet_done else ('running' if _stage == 'sheet_generate' else 'queued'),
        'Awaiting Approval': 'done' if _approve_done else ('running' if _stage == 'awaiting_approval' else 'queued'),
        'Tile Crop': 'done' if _crop_done else ('running' if _stage == 'tile_crop' else 'queued'),
        'Identity QC (ArcFace)': 'done' if _idqc_done else ('running' if _stage == 'identity_qc' else 'queued'),
        'VLM Defect Judge': 'done' if _vlm_done else ('running' if _vlm_run else 'queued'),
        'Caption Generation': 'done' if _cap_done else ('running' if _stage == 'captions' else 'queued'),
        _lora_card: 'done' if _lora_done else ('running' if _lora_run else 'queued'),
        'Angle Expansion (LoRA v1)': 'done' if _angle_done else ('running' if _angle_run else 'queued'),
        'LoRA Refine (v2)': 'done' if _is_done else ('running' if _refine_run else 'queued'),
        # Real since 2026-07-18 (run_qc_safety_valve): shows the actual
        # post-training acceptance-test outcome instead of a phantom card.
        'QC Safety Valve': (
            'done'
            if (active_cs_job.get('qc_safety_valve') or {}).get('verdict')
            else ('running' if _cs_substage == 'qc_safety_valve' and not _is_done else 'queued')
        ),
    }
    # Training disabled (2026-07-16 sheet-workflow hardening): the three
    # training cards must never show 'done' for a run that skipped them.
    _cs_lora_disabled = bool(active_cs_job.get('lora_training_disabled'))
    if not _cs_lora_disabled:
        _cs_lora_disabled = os.environ.get(
            'ZYG_CONTACT_SHEET_LORA_TRAINING',
            '0',
        ).strip().lower() not in ('1', 'true', 'yes', 'on')
    if _cs_lora_disabled and not (_lora_run or _angle_run or _refine_run):
        cs_cards[_lora_card] = 'queued'
        cs_cards['Angle Expansion (LoRA v1)'] = 'queued'
        cs_cards['LoRA Refine (v2)'] = 'queued'
    _cs_err, _cs_ev = _step_debug_event_lines(active_cs_job.get('debug_events') or [])
    return {
        'pipeline': {
            'status': 'running',
            'current_stage': _stage.replace('_', ' ').title(),
            'started': active_cs_job.get('started'),
            'job_id': active_cs_job.get('char_id', ''),
            'department': 'contact_sheet_creation',
            'model_family': _cs_mf,
            **runtime_payload(active_cs_job, True),
        },
        'cards': cs_cards,
        'card_times': card_times(active_cs_job, cs_cards),
        'errors': _cs_err[-30:],
        'events': _cs_ev[-50:],
        'template': 'contact_sheet_creation',
        'model_family': _cs_mf,
        'is_test': False,
    }


def _step_pick_char_job(char_gen_jobs, runtime_dir, reconcile):
    """The character-generation job that owns the board, or None.

    Character generation takes Kanban priority while running (even if a
    storyteller pipeline is also in-flight — users expect the Character
    Creation board). A live job wins; otherwise the newest ``running`` state
    file on disk is adopted into ``char_gen_jobs``.
    """
    active_char_job = None
    for cj in sorted(char_gen_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
        if cj.get('status') == 'running':
            active_char_job = cj
            break
    if active_char_job is None:
        import glob as _glob_ch

        for path in sorted(
            _glob_ch.glob(os.path.join(runtime_dir, 'char_gen_*.json')),
            key=os.path.getmtime,
            reverse=True,
        ):
            try:
                with open(path, encoding='utf-8') as _fh:
                    cj = json.load(_fh)
                if cj.get('status') == 'running':
                    cid = (cj.get('char_id') or '').strip()
                    live = char_gen_jobs.get(cid) if cid else None
                    if live is not None and live.get('status') == 'running':
                        active_char_job = live
                    else:
                        active_char_job = cj
                        if cid:
                            char_gen_jobs[cid] = cj
                    break
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('character state file %s unreadable, skipped: %s', path, _exc)
                continue

    if active_char_job:
        cid = (active_char_job.get('char_id') or '').strip()
        if cid:
            live = char_gen_jobs.get(cid)
            if live is not None:
                active_char_job = reconcile(live)
            else:
                active_char_job = reconcile(dict(active_char_job))
                char_gen_jobs[cid] = active_char_job
    return active_char_job


def _step_char_payload(active_char_job, runtime_payload, card_times):
    """The /api/kanban/status body for a running character-generation job."""
    # Map char gen stage → kanban card status (timeline-aware)
    _stage = _char_derive_pipeline_stage(active_char_job)
    _char_mf = _normalize_char_model_family(
        active_char_job.get('model_family'),
        active_char_job.get('params') or {},
        {},
    )
    _STAGE_ORDER = ['blender_render', 'flux_fallback', 'captions', 'lora_training', 'preview_render', 'done']
    _render_done = _stage not in ('blender_render', 'flux_fallback')
    _caption_done = _stage not in ('blender_render', 'flux_fallback', 'captions')
    _lora_running = _stage == 'lora_training'
    _preview_running = _stage == 'preview_render'
    _is_done = _stage == 'done'
    _st_idx = _STAGE_ORDER.index(_stage) if _stage in _STAGE_ORDER else 0
    _pr_idx = _STAGE_ORDER.index('preview_render')
    _preview_done = _is_done or _st_idx > _pr_idx

    _lora_card = 'SimpleTuner SDXL LoRA Training' if _char_mf == 'sdxl' else 'SimpleTuner FLUX LoRA Training'
    _trained = 'done' if (_is_done or _preview_running or _preview_done) else ('running' if _lora_running else 'queued')
    char_cards = {
        'Blender 4.3.2 Headless Render': 'done'
        if _render_done
        else ('running' if _stage == 'blender_render' else 'queued'),
        'FLUX Character Render': 'running'
        if (_stage == 'flux_fallback' and _char_mf != 'sdxl')
        else ('done' if _render_done else 'queued'),
        'Caption Generation': 'done' if _caption_done else ('running' if _stage == 'captions' else 'queued'),
        _lora_card: _trained,
        'SimpleTuner FLUX LoRA Training': _trained,
        'FLUX LoRA Training (identity — required for SDXL path)': _trained,
        'SimpleTuner SDXL LoRA Training': _trained,
        'IPAdapter-Only Mode (LoRA timeout fallback)': 'queued',
    }
    if _char_mf == 'sdxl':
        char_cards['SDXL Preview Render'] = 'running' if _preview_running else ('done' if _preview_done else 'queued')
    # On the FLUX board the fallback card covers the Blender-unavailable path
    # only, so there is no preview card to add.
    _char_errors, _char_events = _step_debug_event_lines(active_char_job.get('debug_events') or [])
    return {
        'pipeline': {
            'status': 'running',
            'current_stage': _stage.replace('_', ' ').title(),
            'started': active_char_job.get('started'),
            'ended': active_char_job.get('ended'),
            'job_id': active_char_job.get('char_id', ''),
            'department': 'character_creation',
            'topic': '',
            'user_name': '',
            'url': '',
            'model_family': _char_mf,
            **runtime_payload(active_char_job, True),
        },
        'cards': char_cards,
        'card_times': card_times(active_char_job, char_cards),
        'errors': _char_errors[-30:],
        'events': _char_events[-50:],
        'template': 'character_creation',
        'model_family': _char_mf,
        'is_test': False,
    }


def _step_pick_creature_job(creature_gen_jobs, runtime_dir, live_states):
    """The creature job that owns the board, or None — live first, then disk."""
    for crj in sorted(creature_gen_jobs.values(), key=lambda j: j.get('started', '') or '', reverse=True):
        if crj.get('status') in live_states:
            return crj
    import glob as _glob_cr

    for path in sorted(
        _glob_cr.glob(os.path.join(runtime_dir, 'creature_gen_*.json')),
        key=os.path.getmtime,
        reverse=True,
    ):
        try:
            with open(path, encoding='utf-8') as _fh:
                crj = json.load(_fh)
            if crj.get('status') in live_states:
                cid = (crj.get('creature_id') or '').strip()
                live = creature_gen_jobs.get(cid) if cid else None
                if live is not None and live.get('status') in live_states:
                    return live
                if cid:
                    creature_gen_jobs[cid] = crj
                return crj
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('creature state file %s unreadable, skipped: %s', path, _exc)
            continue
    return None


def _step_creature_payload(active_creature_job, stage, cards, runtime_payload, card_times):
    """The /api/kanban/status body for a live creature job.

    ``cards`` is built by the caller from its own card-title table so the board
    titles stay in ``bp_pipeline_api.py``, where the wiring test reads them.
    """
    _cr_status = active_creature_job.get('status')
    _cr_errors, _cr_events = _step_debug_event_lines(active_creature_job.get('debug_events') or [])
    _cr_stage_label = (active_creature_job.get('current_stage') or stage).replace('_', ' ').title()
    if _cr_status == 'awaiting_review':
        _cr_stage_label = 'Sheet Review — awaiting operator approval'
    _train_family = active_creature_job.get('train_family') or 'klein'
    return {
        'pipeline': {
            'status': 'running' if _cr_status == 'running' else _cr_status,
            'current_stage': _cr_stage_label,
            'started': active_creature_job.get('started'),
            'ended': active_creature_job.get('ended'),
            'job_id': active_creature_job.get('creature_id', ''),
            'department': 'creature',
            'topic': (active_creature_job.get('directive') or '')[:120],
            'user_name': '',
            'url': '',
            'model_family': _train_family,
            'sheet_path': active_creature_job.get('sheet_path'),
            'sheet_report': active_creature_job.get('sheet_report'),
            'review_pending': _cr_status == 'awaiting_review',
            **runtime_payload(active_creature_job, _cr_status == 'running'),
        },
        'cards': cards,
        'card_times': card_times(active_creature_job, cards),
        'errors': _cr_errors[-30:],
        'events': _cr_events[-50:],
        'template': 'creature_creation',
        'model_family': _train_family,
        'is_test': False,
    }


def _step_creature_stage_and_cards(active_creature_job, stage_order, card_table, refresh, mark_stale):
    """``(stage, cards)`` for a live creature job, from its own stage order."""
    active_creature_job = refresh(active_creature_job)
    mark_stale(active_creature_job)
    stage = _creature_derive_pipeline_stage(active_creature_job)
    if stage == 'reference_gen':  # legacy May-2026 state files
        stage = 'sheet'
    _cr_status = active_creature_job.get('status')
    _st_idx = stage_order.index(stage) if stage in stage_order else 0
    cards = {}
    for _ci, (_key, _card) in enumerate(card_table):
        if stage == 'done' or _cr_status in ('completed', 'done'):
            cards[_card] = 'done'
        elif _ci < _st_idx:
            cards[_card] = 'done'
        elif _ci == _st_idx:
            cards[_card] = 'error' if _cr_status in ('failed', 'error') else 'running'
        else:
            cards[_card] = 'queued'
    return active_creature_job, stage, cards


def _step_standalone_video_payload():
    """The board payload for a shell-driven VACE run, or None.

    2026-08-01. These renders (scene20_*, The Second Ledger) are driven by a
    shell script, NOT by POST /api/internal/pipeline/start, so they never enter
    ``_workflow_jobs`` and every check above them is blind to them. Measured
    while scene20_v13 was actively sampling on the GPU, this endpoint returned
        {"template":"documentary","pipeline":null,"cards":{}}
    and kanban_main.js then forces every card to 'queued' — the reported
    "I never see an actual workflow active in the kanban boards".
    State is read from the run logbook on disk (see kanban_video_status), so it
    survives a GUI restart and needs no change to the running render.
    """
    try:
        from zyg_dashboard import kanban_video_status as _kvs

        _video_payload = _kvs.kanban_payload()
    except Exception as _exc:
        # Never let the standalone board break the endpoint.
        _zyg_log.warning('standalone VACE board unavailable, falling back to the job registry: %s', _exc)
        _video_payload = None
    if not _video_payload:
        return None
    _video_payload.setdefault('errors', [])
    _video_payload.setdefault('events', [])
    _video_payload['is_test'] = False
    return _video_payload


def _normalize_timeline_status(raw_status):
    """A ``stage_timeline`` status as the board's four card states."""
    if raw_status in ('completed', 'success', 'done'):
        return 'done'
    if raw_status in ('failed', 'error'):
        return 'error'
    if raw_status == 'running':
        return 'running'
    return 'queued'


def _step_timeline_lookup(active_job, current_stage):
    """``(tl_map, tl_order, cur_idx)`` — the board's authoritative stage table.

    ``tl_map``: stage_name.lower() → 'running' | 'completed' | 'failed' | 'queued'
    ``tl_order``: those names in the order the timeline lists them.
    """
    tl_map = {}
    tl_order = []
    for entry in active_job.get('stage_timeline') or []:
        name = entry.get('name', '')
        st = entry.get('status', 'queued')
        tl_map[name.lower()] = st
        tl_order.append(name.lower())

    # Also fold in job['stages'] (crime pipeline uses nested agent dicts)
    for sname, sdata in (active_job.get('stages') or {}).items():
        key = sname.lower()
        if key not in tl_map:
            # Flat scholarly entry: {'status': 'completed'}
            if isinstance(sdata, dict) and 'status' in sdata and not any(isinstance(v, dict) for v in sdata.values()):
                tl_map[key] = sdata.get('status', 'queued')
                tl_order.append(key)
            # Nested crime entry: {'agent-id': {'status': 'completed'}}
            elif isinstance(sdata, dict):
                statuses = [v.get('status', 'queued') for v in sdata.values() if isinstance(v, dict)]
                if statuses:
                    if any(s == 'running' for s in statuses):
                        tl_map[key] = 'running'
                    elif any(s == 'failed' for s in statuses):
                        tl_map[key] = 'failed'
                    elif all(s in ('completed', 'success', 'done') for s in statuses):
                        tl_map[key] = 'completed'
                    else:
                        tl_map[key] = 'queued'
                    tl_order.append(key)

    # Current stage index in the ordered list
    cur_idx = -1
    if current_stage:
        cs_lower = current_stage.lower()
        for i, n in enumerate(tl_order):
            if cs_lower in n or n in cs_lower:
                cur_idx = i
                break
    return tl_map, tl_order, cur_idx


def _step_resolve_board_cards(stage_map, tl_map, tl_order, cur_idx, pipeline_status):
    """``(cards, card_keys)`` for the focused run's board.

    The matched timeline key is returned per card so the card's Started/Duration
    clock can be read from the SAME timeline row the status came from — a card
    must never show one stage's status beside another stage's start time. Cards
    whose stage never matched a row are absent from ``card_keys`` and so get no
    clock at all.
    """

    def resolve_card(frags):
        for frag in frags:
            for key, st in tl_map.items():
                if frag in key:
                    return _normalize_timeline_status(st), key
            # Fragment not in timeline yet — check if we've passed it by position
            for _i, key in enumerate(tl_order):
                if frag in key:
                    # Stage is in the timeline but not yet started → queued
                    return 'queued', key
        # Not in timeline at all — infer from position relative to current stage
        if cur_idx >= 0:
            # All cards before current stage → done; after → queued
            for frag in frags:
                for i, key in enumerate(tl_order):
                    if frag in key:
                        return ('done' if i < cur_idx else 'queued'), key
        return ('queued' if pipeline_status == 'running' else 'idle'), None

    _resolved = {prompt: resolve_card(frags) for prompt, frags in stage_map.items()}
    cards = {p: st for p, (st, _k) in _resolved.items()}
    card_keys = {p: k for p, (_st, k) in _resolved.items() if k}
    return cards, card_keys


def _step_peer_run(peer_job, stage_map):
    """One same-department peer as a row of card cells under THIS board."""
    _c_tl_map = {}
    _c_tl_order = []
    for _entry in peer_job.get('stage_timeline') or []:
        _n = _entry.get('name', '').lower()
        _c_tl_map[_n] = _entry.get('status', 'queued')
        _c_tl_order.append(_n)
    _c_ps = peer_job.get('status', 'idle')
    _c_cs = (peer_job.get('current_stage') or '').lower()
    _c_cur = -1
    for _i, _n in enumerate(_c_tl_order):
        if _c_cs and (_c_cs in _n or _n in _c_cs):
            _c_cur = _i
            break

    def _c_resolve(frags):
        for f in frags:
            for k, s in _c_tl_map.items():
                if f in k:
                    return _normalize_timeline_status(s)
        if _c_cur >= 0:
            for f in frags:
                for i, k in enumerate(_c_tl_order):
                    if f in k:
                        return 'done' if i < _c_cur else 'queued'
        return 'queued' if _c_ps == 'running' else 'idle'

    return {
        'pipeline_id': peer_job.get('pipeline_id', ''),
        'user_name': peer_job.get('user_name', ''),
        'topic': peer_job.get('scholarly_topic', ''),
        'started': peer_job.get('started', ''),
        'cards': {p: _c_resolve(f) for p, f in stage_map.items()},
    }


def _step_live_tail(active_job, same_dept_jobs):
    """``(errors, events)`` for the Live Tail — the focused run plus 7 peers.

    errors_cleared_at_index is set by /api/kanban/clear_errors — only show
    events that arrived AFTER the user last clicked Clear in the UI.
    When multiple concurrent scholarly pipelines are running, aggregate events
    from all of them and prefix each line with a short pipeline tag so the
    user can tell which pipeline each log line belongs to.
    """
    _lt_jobs = [(active_job, None)]  # (job, label_override) — primary has no prefix
    # Deliberately NOT the full concurrent-run list: the board can paint 100
    # peers as cells, but interleaving 100 jobs' debug events makes the tail
    # unreadable and the payload huge. The tail stays at the 8 most recent.
    for _cjob in same_dept_jobs[:7]:
        _tag = (_cjob.get('pipeline_id') or '')[:6]
        _lt_jobs.append((_cjob, f'[{_tag}]'))

    errors = []
    events = []
    for _lt_job, _lt_tag in _lt_jobs:
        _cleared = int(_lt_job.get('errors_cleared_at_index', 0))
        _lt_evs = _lt_job.get('debug_events') or []
        for ev in _lt_evs[_cleared:]:
            # DEFENSIVE BY DESIGN, not by taste. The contract is that a runner
            # appends dicts {level, ts, stage, msg} — but this route reads the
            # ACTIVE job's events whoever wrote them, so one runner appending a
            # bare string took the WHOLE dashboard down with an AttributeError,
            # not just its own board (16 real 500s in flask.log on 2026-08-29,
            # two of them after the job had already finished). A status route
            # cannot be allowed to fail on the shape of a log line: a
            # non-conforming entry is rendered as text and flagged, so the
            # offending runner is visible instead of fatal.
            if not isinstance(ev, dict):
                events.append(f'[?] {_lt_tag + " " if _lt_tag else ""}[malformed event] {str(ev)[:120]}')
                continue
            lvl = str(ev.get('level', '')).upper()
            ts = ev.get('ts', '?')
            stage = ev.get('stage', '?')
            msg = str(ev.get('msg', ''))[:120]
            tag = f'{_lt_tag} ' if _lt_tag else ''
            line = f'[{ts}] {tag}[{stage}] {msg}'
            if lvl in ('WARN', 'WARNING', 'ERROR', 'CRITICAL'):
                errors.append(line)
            else:
                events.append(line)
    return errors[-30:], events[-50:]  # cap at 30 / 50


def _step_sports_video_status():
    """The sports-video pipeline's status file, so the kanban Templates view can
    display it. Absent or half-written → an empty dict, same as before."""
    try:
        with open(_SPORTS_VIDEO_STATUS) as _svf:
            return json.load(_svf)
    except FileNotFoundError:
        # The sports-video pipeline is optional and usually not installed.
        _zyg_log.debug('sports-video status file absent at %s', _SPORTS_VIDEO_STATUS)
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('sports-video status unreadable, reporting none: %s', _exc)
    return {}
