# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .base import (
    ZYG_COMFY_URL,
    _AMS,
    _RUNTIME,
    _hhmm,
    _load_json,
    _parse_iso,
    _parse_job_start_time,
    _slug_to_id,
    ams_now,
    bar_id_for,
    datetime,
    model_registry,
    os,
    time,
    timedelta,
)
from .durations import (
    DEFAULT_DURATIONS,
    PIPELINE_AGENT,
    _PIPELINE_FALLBACK_MODEL,
    _STATE_FILE_TYPES,
    _pipeline_total,
    _stage_model,
    get_duration_table,
)
import logging as _zyg_logging_split

_zyg_log = _zyg_logging_split.getLogger('zyg_dashboard.schedule_service')

# ── entry factory ────────────────────────────────────────────────────────────


def _entry(
    *,
    eid: str,
    source: str,
    kind: str,
    ptype: str,
    stage: str,
    label: str,
    start: datetime,
    end: datetime,
    progress: float | None = None,
    status: str = '',
    reserved: bool = True,
    agent: str | None = None,
    slug: str | None = None,
    device: str | None = None,
    priority: str = 'High',
) -> dict:
    if slug is None or device is None:
        slug2, dev2 = _stage_model(ptype, stage)
        slug = slug or slug2
        device = device or dev2
    agent = agent or PIPELINE_AGENT.get(ptype, 'Zero')
    reg_scope = 'gpu' if device == 'gpu' else 'cpu'
    mid = _slug_to_id(reg_scope).get(slug, '')
    reg = model_registry(reg_scope, include_deprecated=True)
    vram = (reg.get(mid) or {}).get('vram_required_mb')
    return {
        'id': eid,
        'source': source,
        'kind': kind,  # active | scheduled | queued | awaiting-approval | manual
        'pipeline': ptype,
        'stage': stage,
        'label': label,
        'agent': agent,
        'model': slug,
        'model_id': mid,
        'bar_id': bar_id_for(agent, slug),
        'device': device,
        'date': start.astimezone(_AMS).strftime('%Y-%m-%d'),
        'start_time': _hhmm(start),
        'end_time': _hhmm(end),
        'start_iso': start.astimezone(_AMS).isoformat(timespec='seconds'),
        'end_iso': end.astimezone(_AMS).isoformat(timespec='seconds'),
        'progress': None if progress is None else round(max(0.0, min(100.0, progress)), 1),
        'status': status,
        'reserved': reserved,
        'vram_mb': vram,
        'priority': priority,
    }


_TERMINAL = ('done', 'failed', 'error', 'cancelled', 'canceled', 'stopped', 'completed', 'parked', 'paused')


def _is_terminal(status: str) -> bool:
    return (status or '').strip().lower() in _TERMINAL


# ── live entries ─────────────────────────────────────────────────────────────


def _remaining_stages(ptype: str, current: str, order: list[str], table: dict) -> float:
    """Seconds expected from the START of *current* stage to pipeline end."""
    durs = table.get(ptype) or {}
    try:
        idx = order.index(current)
    except ValueError:
        return _pipeline_total(ptype, table)
    rest = 0.0
    for st in order[idx:]:
        rest += float(durs.get(st, 300))
    return rest or 300.0


def _live_from_job(
    ptype: str,
    jid: str,
    job: dict,
    table: dict,
    now: datetime,
    stage_order: list[str] | None = None,
) -> dict | None:
    status = str(job.get('status') or '')
    if _is_terminal(status):
        return None
    stage = str(job.get('stage') or job.get('current_stage') or 'running')
    if _is_terminal(stage):
        return None
    # Completion artifacts count as terminal even when the file never wrote a
    # status key (storyteller state files record video_path/ended only) —
    # without this, finished runs resurrect as active reserved windows for 12h.
    if job.get('ended') or job.get('video_path'):
        return None
    # find current stage start from the timeline; fall back to job start
    started = None
    for s in reversed(job.get('stage_timeline') or []):
        if s.get('status') == 'running' or s.get('ended_at') is None:
            started = _parse_iso(s.get('started_at'))
            if started:
                break
    started = started or _parse_iso(job.get('started') or job.get('started_at')) or now
    # a job whose last heartbeat is ancient is an orphan, not an active run
    if (now - started) > timedelta(hours=12):
        return None
    durs = table.get(ptype) or {}
    stage_expected = float(durs.get(stage, 600))
    if stage_order:
        # 2026-07-19: with per-stage forecast blocks now drawn on their own
        # model columns, the live bar covers ONLY the current stage — the old
        # full-remaining span double-painted the run over its own forecasts.
        # Pipelines without a stage order keep the whole-run estimate.
        remaining = stage_expected
    else:
        remaining = max(stage_expected, _pipeline_total(ptype, table) * 0.4)
    eta = started + timedelta(seconds=remaining)
    if eta <= now:
        eta = now + timedelta(minutes=10)  # over budget — keep a live sliver
    elapsed = (now - started).total_seconds()
    progress = min(99.0, 100.0 * elapsed / stage_expected) if stage_expected else None
    label = job.get('label') or job.get('scholarly_topic') or job.get('story_prompt') or ''
    label = f'{ptype}:{jid[:12]}' + (f' — {str(label)[:60]}' if label else f' [{stage}]')
    return _entry(
        eid=f'live_{ptype}_{jid}',
        source='live',
        kind='active',
        ptype=ptype,
        stage=stage,
        label=label,
        start=started,
        end=eta,
        progress=progress,
        status=status or 'running',
    )


def _history_from_timeline(ptype: str, jid: str, job: dict, now: datetime) -> list[dict]:
    """Completed-stage blocks for TODAY (2026-07-19).

    Finished stages used to vanish from the grid the moment the live bar moved
    on — the owner wants the day to read as a record: every completed stage
    stays drawn (teal 'history' bars) until the next day starts. Entries carry
    their real timeline start/end; the grid's date filter retires them
    automatically at midnight. reserved=False — the time already passed.
    """
    out: list[dict] = []
    today = now.astimezone(_AMS).date()
    for i, s in enumerate(job.get('stage_timeline') or []):
        st_start = _parse_iso(s.get('started_at'))
        st_end = _parse_iso(s.get('ended_at'))
        if not st_start or not st_end or st_end <= st_start:
            continue
        if st_end.astimezone(_AMS).date() != today and st_start.astimezone(_AMS).date() != today:
            continue
        stage = str(s.get('name') or '')
        out.append(
            _entry(
                eid=f'hist_{ptype}_{jid}_{i}',
                source='stage_history',
                kind='history',
                ptype=ptype,
                stage=stage,
                label=f'{ptype}:{jid[:12]} ✓ {stage}',
                start=st_start,
                end=st_end,
                status=str(s.get('status') or 'completed'),
                reserved=False,
                priority='Low',
            )
        )
    return out


def _forecast_from_job(
    ptype: str,
    jid: str,
    job: dict,
    table: dict,
    now: datetime,
    stage_order: list[str],
) -> list[dict]:
    """Projected per-stage blocks for a LIVE run's remaining stages (2026-07-19).

    The live entry shows only the currently-executing stage on its model's
    column — nothing previewed where the run goes next (ArcFace QC,
    SimpleTuner training, …). Walk the remaining stage order with the measured
    duration table, drop one 'forecast' block per stage on that stage's own
    model column, and re-anchor the whole chain to the sliding end of the
    current stage on every refresh — when Qwen overruns, every downstream
    block shifts right automatically. reserved=True: the old design reserved
    the run's whole remaining span (on the wrong single column); the forecast
    chain carries that reservation on the RIGHT columns, so manual-entry
    conflict blocking does not regress.
    """
    status = str(job.get('status') or '')
    if _is_terminal(status):
        return []
    stage = str(job.get('stage') or job.get('current_stage') or '')
    st_key = stage.strip().lower().replace(' ', '_')
    try:
        idx = stage_order.index(st_key)
    except ValueError:
        return []
    durs = table.get(ptype) or {}
    started = None
    for s in reversed(job.get('stage_timeline') or []):
        if s.get('status') == 'running' or s.get('ended_at') is None:
            started = _parse_iso(s.get('started_at'))
            if started:
                break
    started = started or _parse_iso(job.get('started') or job.get('started_at')) or now
    cursor = started + timedelta(seconds=float(durs.get(st_key, 600)))
    if cursor < now:
        # Current stage is over budget — the chain hangs off 'now' and keeps
        # sliding right until the stage actually finishes.
        cursor = now + timedelta(minutes=2)
    out: list[dict] = []
    label_base = f'{ptype}:{jid[:12]}'
    for st in stage_order[idx + 1 :]:
        # Floor at 3 min: sub-minute measured stages (tile_crop ~10s, captions
        # ~20s) collapsed to identical hh:mm start/end, which the grid renderer
        # used to read as a midnight crossing → 24h overflow bar (2026-07-19).
        dur = max(180.0, float(durs.get(st, 300)))
        end = cursor + timedelta(seconds=dur)
        out.append(
            _entry(
                eid=f'forecast_{ptype}_{jid}_{st}',
                source='live_forecast',
                kind='forecast',
                ptype=ptype,
                stage=st,
                label=f'{label_base} ⟶ {st} (projected)',
                start=cursor,
                end=end,
                status='forecast',
                reserved=True,
                priority='Low',
            )
        )
        cursor = end
    return out


_CS_STAGE_ORDER = [
    'sheet_generate',
    'awaiting_approval',
    'tile_crop',
    'identity_qc',
    'captions',
    'lora_training',
    'angle_expansion',
    'lora_refine',
]


def build_live_entries(registries: dict | None = None) -> list[dict]:
    """Normalize every live run into schedule entries. *registries* may carry
    the GUI's in-memory dicts; persisted runtime files fill the gaps."""
    registries = registries or {}
    now = ams_now()
    table = get_duration_table()
    out: list[dict] = []
    seen: set[str] = set()

    def _add(e: dict | None, eid: str | None = None):
        if e is None:
            # Terminal/ignored in-memory job: still record its id so the file
            # sweep below cannot resurrect the same run from its state file.
            if eid:
                seen.add(eid)
            return
        if e['id'] not in seen:
            seen.add(e['id'])
            out.append(e)

    def _norm_ptype(raw: str) -> str:
        pt = (raw or 'video').lower()
        if pt in ('scholarly', 'crime'):
            return 'documentary'
        if pt not in DEFAULT_DURATIONS and pt not in _PIPELINE_FALLBACK_MODEL:
            return 'video'
        return pt

    # in-memory registries first (freshest)
    for jid, job in (registries.get('contact_sheet_jobs') or {}).items():
        _live_cs = _live_from_job('contact_sheet', str(jid), job, table, now, _CS_STAGE_ORDER)
        _add(_live_cs, f'live_contact_sheet_{jid}')
        if _live_cs is not None:
            for _fc in _forecast_from_job('contact_sheet', str(jid), job, table, now, _CS_STAGE_ORDER):
                _add(_fc)
        for _h in _history_from_timeline('contact_sheet', str(jid), job, now):
            _add(_h)
    for jid, job in (registries.get('char_gen_jobs') or {}).items():
        _add(_live_from_job('char_gen', str(jid), job, table, now), f'live_char_gen_{jid}')
        for _h in _history_from_timeline('char_gen', str(jid), job, now):
            _add(_h)
    for jid, job in (registries.get('creature_jobs') or {}).items():
        _add(_live_from_job('creature', str(jid), job, table, now), f'live_creature_{jid}')
        for _h in _history_from_timeline('creature', str(jid), job, now):
            _add(_h)
    for jid, job in (registries.get('workflow_jobs') or {}).items():
        ptype = _norm_ptype(str(job.get('pipeline_type') or job.get('type') or job.get('department') or 'video'))
        _add(_live_from_job(ptype, str(jid), job, table, now), f'live_{ptype}_{jid}')
        for _h in _history_from_timeline(ptype, str(jid), job, now):
            _add(_h)

    # LoRA training via trainer status callable
    training_fn = registries.get('training_status_fn')
    if callable(training_fn):
        try:
            for st in training_fn() or []:
                if not st or st.get('done') or st.get('failed'):
                    continue
                total = int(st.get('total_steps') or 0)
                step = int(st.get('step') or 0)
                if total <= 0:
                    continue
                fam = str(st.get('model_family') or 'flux').lower()
                slug = 'simpletuner-sdxl-lora' if fam == 'sdxl' else 'simpletuner-flux-lora'
                start = end = None
                # Prefer the trainer's own real 'start_time'/'eta_s' fields
                # (added 2026-08-09 to TrainingJob.to_dict()) over the guessed
                # per-step constants below — a measured ETA beats a hardcoded
                # average. Wrapped defensively: these fields may be briefly
                # absent for a job in flight during the deploy that adds them,
                # or for a job recovered from disk with no live status, so any
                # failure here must fall through to the old heuristic, never
                # raise.
                if st.get('eta_s') is not None and st.get('start_time') is not None:
                    try:
                        real_start = _parse_job_start_time(st.get('start_time'))
                        real_eta_s = float(st.get('eta_s'))
                        if real_start is not None and real_eta_s >= 0:
                            start = real_start
                            end = now + timedelta(seconds=max(60, real_eta_s))
                    except (TypeError, ValueError):
                        start = end = None
                if start is None or end is None:
                    # Fallback heuristic — only reached when the real fields
                    # are absent. qwen has no dedicated constant here and
                    # falls into the flux/else bucket; qwen's real per-step
                    # cost is substantially higher than flux's (larger
                    # model), so 3.2 is a rough placeholder for qwen only
                    # until the real eta_s/start_time fields are present.
                    per_step = 1.1 if fam == 'sdxl' else 3.2
                    start = now - timedelta(seconds=step * per_step)
                    end = now + timedelta(seconds=max(60, (total - step) * per_step))
                _add(
                    _entry(
                        eid=f'live_training_{st.get("char_id", "?")}_{fam}',
                        source='live',
                        kind='active',
                        ptype='training',
                        stage=f'LoRA training ({fam})',
                        label=f'LoRA {fam} {st.get("char_id", "")[:12]} {step}/{total}',
                        start=start,
                        end=end,
                        slug=slug,
                        device='gpu',
                        progress=100.0 * step / total,
                        status='training',
                    )
                )
        except Exception as _exc:
            _zyg_log.warning(
                'a LoRA training state was unreadable, its lane entry is missing from the timeline: %s', _exc
            )

    # persisted runtime files → orphan sweep (covers GUI restarts / other procs)
    import glob as _glob

    for pat, ptype in _STATE_FILE_TYPES:
        for f in _glob.glob(os.path.join(_RUNTIME, pat)):
            try:
                if time.time() - os.path.getmtime(f) > 12 * 3600:
                    continue
            except OSError as _exc:
                _zyg_log.debug('%s not statable, skipped in the orphan sweep: %s', f, _exc)
                continue
            d = _load_json(f, None)
            if not isinstance(d, dict):
                continue
            # Sweep ids must match the in-memory registry keys or one running
            # job renders twice: workflow-run files key by pipeline_id,
            # char-keyed files by char_id, creature files by creature_id.
            _id_keys = {
                'documentary': ('pipeline_id',),
                'storyteller': ('pipeline_id',),
                'contact_sheet': ('char_id',),
                'char_gen': ('char_id',),
                'creature': ('creature_id', 'char_id'),
            }.get(ptype, ('pipeline_id', 'char_id'))
            jid = next((str(d[k]) for k in _id_keys if d.get(k)), os.path.basename(f))
            pt = _norm_ptype(str(d.get('department') or ptype)) if ptype in ('documentary', 'storyteller') else ptype
            _live_fs = _live_from_job(pt, jid, d, table, now, _CS_STAGE_ORDER if pt == 'contact_sheet' else None)
            _add(_live_fs)
            if _live_fs is not None and pt == 'contact_sheet':
                for _fc in _forecast_from_job(pt, jid, d, table, now, _CS_STAGE_ORDER):
                    _add(_fc)
            # Completed stages stay on the grid for the rest of the day —
            # emitted for terminal runs too (a run that finished at 05:46
            # should still read on the schedule at 18:00).
            for _h in _history_from_timeline(pt, jid, d, now):
                _add(_h)
    return out


_comfy_q_cache: dict = {'ts': 0.0, 'val': {'running': None, 'pending': None}}


def comfy_queue_depth() -> dict:
    now = time.time()
    if now - _comfy_q_cache['ts'] < 15:
        return dict(_comfy_q_cache['val'])
    try:
        import requests as _req

        r = _req.get(f'{ZYG_COMFY_URL}/queue', timeout=1.5)
        q = r.json()
        val = {
            'running': len(q.get('queue_running') or []),
            'pending': len(q.get('queue_pending') or []),
        }
    except Exception:
        val = {'running': None, 'pending': None}
    _comfy_q_cache.update(ts=now, val=val)
    return dict(val)
