# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The run ledger: every pipeline / character job on disk, classified and bucketed."""

from __future__ import annotations

import glob
import os
import re
import time
from datetime import datetime, timedelta

from .constants import DAY, RUNTIME, STALE_AFTER_S, TZ
from .helpers import _UNREADABLE, _cached, _is_test_id, _iso, _num, _prune, _read_json, _short, _ts

# ── runs: every pipeline / character job on disk ─────────────────────────────

KIND_LABELS = {
    'scholarly': 'Scholarly documentary',
    'kidsmusic': 'Kids music',
    'storyteller': 'Storyteller',
    'tokitoki': 'TokiToki',
    'remix_ai': 'Remix AI',
    'crime': 'Crime documentary',
    'stocks': 'Stocks',
    'clipfarm': 'Clipfarm',
    'video': 'Video pipeline',
    'manga': 'Manga',
    'character': 'Character generation',
    'creature': 'Creature generation',
    'contact_sheet': 'Contact sheets',
    'unknown': 'Unlabelled (legacy)',
    # A pre-emptive BRAIN run: every text Claude call of an episode, recorded and banked,
    # then stopped before the first image. It is not an episode and never counts as one.
    'scholarly-preempt': 'Documentary brain (pre-emptive bank)',
}
# Chart families in FIXED order — the frontend assigns colour by this identity,
# never by rank, so a range change cannot repaint a pipeline.
FAMILIES = ('scholarly', 'kidsmusic', 'characters', 'remix_ai', 'tokitoki', 'storyteller', 'crime')
FAMILY_LABELS = {
    'scholarly': 'Scholarly',
    'kidsmusic': 'Kids music',
    'characters': 'Characters',
    'remix_ai': 'Remix AI',
    'tokitoki': 'TokiToki',
    'storyteller': 'Storyteller',
    'crime': 'Crime',
    'other': 'Other',
}
_KIND_FAMILY = {'character': 'characters', 'creature': 'characters', 'contact_sheet': 'characters'}

STATUSES = ('completed', 'failed', 'open', 'stale', 'cancelled', 'unknown')
_DONE = frozenset({'completed', 'complete', 'done', 'success', 'succeeded', 'finished', 'ok', 'delivered'})
_FAIL = frozenset({'failed', 'fail', 'error', 'errored', 'crashed', 'exception', 'killed', 'timeout', 'timed_out'})
_CANCEL = frozenset({'cancelled', 'canceled', 'declined', 'aborted', 'stopped', 'archived', 'rejected', 'skipped'})
_OPEN = frozenset(
    {'running', 'in_progress', 'queued', 'pending', 'started', 'paused', 'generating', 'training', 'rendering'}
)

STATUS_RULES = [
    'completed / failed / cancelled: the state file records that outcome.',
    'in progress: recorded as running/queued/paused (or no end yet) with a state write in the last 12 h.',
    'stale: claims to be in progress, or never recorded an end, and has not written state for 12 h+.',
    'unrecorded: an end time exists but no outcome and no evidence of one.',
    'inferred: no status field (older schemas) — failed when an error is stored, completed when a '
    'final video path is stored. Counted in the totals, flagged separately.',
    'success rate = completed / (completed + failed); stale and unrecorded runs are not in it.',
]


def _family(kind):
    fam = _KIND_FAMILY.get(kind, kind)
    return fam if fam in FAMILIES else 'other'


def _norm_stage(name):
    """Collapse per-run stage labels ("LoRA Training: FLUX rank 16") to stable names."""
    n = (name or '').split(':')[0].strip()
    up = n.upper()
    if 'LORA' in up:
        return 'LoRA training (FLUX)' if 'FLUX' in up else 'LoRA training (SDXL)' if 'SDXL' in up else 'LoRA training'
    if 'Preview Render' in n:
        return 'Preview render'
    if 'Character Render' in n or 'Blender' in n:
        return 'Character render'
    if 'Caption' in n:
        return 'Caption generation'
    return n or '(unnamed)'


def _stages(d):
    out = []
    for st in d.get('stage_timeline') or []:
        if not isinstance(st, dict):
            continue
        raw = str(st.get('name') or st.get('stage') or '')
        el = _num(st.get('elapsed_s'))
        start, end = _ts(st.get('started_at')), _ts(st.get('ended_at'))
        if el is None and start and end and end >= start:
            el = end - start
        extra = st.get('extra') if isinstance(st.get('extra'), dict) else {}
        out.append(
            {
                'name': _norm_stage(raw),
                'raw': raw[:60],
                'elapsed': el,
                'status': str(st.get('status') or '').lower(),
                'end': end,
                'steps': extra.get('total_steps') if isinstance(extra.get('total_steps'), int) else None,
            }
        )
    return out


def _run_record(d, path, kind, rid, title, **extra):
    stages = _stages(d)
    err = d.get('error')
    rec = {
        'id': str(rid),
        'kind': kind,
        'title': _short(title, 90),
        'status_raw': str(d.get('status') or '').strip(),
        'started': _ts(d.get('started') or d.get('created_at')),
        'ended': _ts(d.get('ended') or d.get('finished_at') or d.get('completed_at')),
        'last_stage_end': max((s['end'] for s in stages if s['end']), default=None),
        'current_stage': _short(d.get('current_stage') or d.get('stage'), 60),
        'has_error': bool(err),
        'error': _short(err),
        'has_output': False,
        'synthesized': False,
        'stages': [(s['name'], s['elapsed'], s['status']) for s in stages],
        'mtime': os.path.getmtime(path),
    }
    rec.update(extra)
    return rec, stages


def _load_pipeline_state(path):
    d = _read_json(path)
    if not isinstance(d, dict):
        raise ValueError('state is not an object')
    base = os.path.basename(path)
    is_st = base.startswith('storyteller_')
    rid = d.get('pipeline_id') or re.sub(r'^(pipeline|storyteller)_|_state\.json$', '', base)
    kind = (
        str(d.get('department') or d.get('pipeline_type') or ('storyteller' if is_st else 'unknown')).strip().lower()
        or 'unknown'
    )
    params = d.get('params') if isinstance(d.get('params'), dict) else {}
    result = d.get('result') if isinstance(d.get('result'), dict) else {}
    title = (
        d.get('scholarly_topic')
        or d.get('essay_title')
        or d.get('story_title')
        or d.get('topic')
        or params.get('title')
        or params.get('topic')
        or d.get('youtube_title')
        or ''
    )
    receipts = d.get('gate_receipts') if isinstance(d.get('gate_receipts'), dict) else None
    vlm = d.get('vlm_gate_stats') if isinstance(d.get('vlm_gate_stats'), dict) else None
    rec, _ = _run_record(
        d,
        path,
        kind,
        rid,
        title,
        source='storyteller_state' if is_st else 'pipeline_state',
        has_output=bool(d.get('video_path') or result.get('video_path') or result.get('video')),
        gate_receipts={
            k: {'ran': bool(v.get('ran')), 'reason': _short(v.get('reason'), 80)}
            for k, v in receipts.items()
            if isinstance(v, dict)
        }
        if receipts
        else None,
        vlm={k: v for k, v in vlm.items() if isinstance(v, (int, float)) and not isinstance(v, bool)} if vlm else None,
    )
    return rec


def _load_char_gen(path):
    d = _read_json(path)
    params = d.get('params') if isinstance(d.get('params'), dict) else {}
    rid = d.get('char_id') or re.sub(r'^char_gen_|\.json$', '', os.path.basename(path))
    rec, stages = _run_record(
        d,
        path,
        'character',
        rid,
        params.get('name') or rid,
        source='char_gen',
        # _backfill_char_gen_states_from_bibles writes these with bible timestamps —
        # their "duration" is bible created->updated, not a generation run.
        synthesized=bool(d.get('backfilled') or d.get('timestamps_synthesized')),
        model_family=str(d.get('model_family') or params.get('model_family') or 'unknown').strip().lower(),
        render_mode=str(d.get('render_mode') or 'unknown'),
        image_count=d.get('image_count') if isinstance(d.get('image_count'), int) else None,
    )
    rec['lora'] = [(s['raw'], s['elapsed'], s['status'], s['steps']) for s in stages if 'LORA' in s['raw'].upper()]
    return rec


def _load_creature_gen(path):
    d = _read_json(path)
    params = d.get('params') if isinstance(d.get('params'), dict) else {}
    rid = d.get('creature_id') or d.get('char_id') or re.sub(r'^creature_gen_|\.json$', '', os.path.basename(path))
    rec, _ = _run_record(
        d,
        path,
        'creature',
        rid,
        params.get('name') or d.get('name') or rid,
        source='creature_gen',
        model_family=str(d.get('model_family') or params.get('model_family') or 'unknown').lower(),
    )
    return rec


def _load_contact_sheet(path):
    d = _read_json(path)
    rid = re.sub(r'^contact_sheet_|\.json$', '', os.path.basename(path))
    rec, _ = _run_record(
        d,
        path,
        'contact_sheet',
        rid,
        d.get('char_id') or rid,
        source='contact_sheet',
        model_family=str(d.get('model_family') or 'unknown').lower(),
        cells_done=d.get('sheet_cells_done') if isinstance(d.get('sheet_cells_done'), int) else None,
        cells_total=d.get('sheet_cells_total') if isinstance(d.get('sheet_cells_total'), int) else None,
    )
    return rec


_RUN_SOURCES = (
    ('pipeline_*_state.json', _load_pipeline_state),
    ('storyteller_*_state.json', _load_pipeline_state),
    ('char_gen_*.json', _load_char_gen),
    ('creature_gen_*.json', _load_creature_gen),
    ('contact_sheet_*.json', _load_contact_sheet),
)


def _classify(rec, now):
    """-> (status, inferred, claims_running). See STATUS_RULES."""
    raw = rec['status_raw'].lower()
    last_write = max(rec['mtime'], rec.get('last_stage_end') or 0)
    fresh = now - last_write < STALE_AFTER_S
    if raw in _DONE:
        return 'completed', False, False
    if raw in _FAIL:
        return 'failed', False, False
    if raw in _CANCEL:
        return 'cancelled', False, False
    if raw in _OPEN:
        return ('open' if fresh else 'stale'), False, True
    if raw:
        return 'unknown', False, False  # unrecognised vocabulary: say so, don't guess
    if rec['has_error']:
        return 'failed', True, False
    if rec['has_output']:
        return 'completed', True, False
    if rec['ended']:
        return 'unknown', False, False
    return ('open' if fresh else 'stale'), False, False


def collect_runs(now=None):
    now = now or time.time()
    by_loader: dict = {}
    for pattern, loader in _RUN_SOURCES:
        paths = [p for p in glob.glob(os.path.join(RUNTIME, pattern)) if not p.endswith('_serial_state.json')]
        by_loader.setdefault(loader, []).extend(paths)
    runs, tests, synthesized, unreadable = [], 0, 0, []
    for loader, paths in by_loader.items():
        _prune(loader, paths)
        for p in paths:
            rec = _cached(p, loader)
            if not isinstance(rec, dict):
                unreadable.append({'file': os.path.basename(p), 'error': _UNREADABLE.get(p, '')})
                continue
            if _is_test_id(rec['id']):
                tests += 1
                continue
            if rec.get('synthesized'):
                # 95 of 170 char_gen records (2026-09-11) were written by the bible backfill with
                # status 'done' and bible timestamps: characters that exist, but not observed runs.
                synthesized += 1
                continue
            r = dict(rec)
            r['status'], r['inferred'], r['claims_running'] = _classify(rec, now)
            r['family'] = _family(rec['kind'])
            r['t'] = rec['started'] or rec['mtime']
            r['last_write'] = max(rec['mtime'], rec.get('last_stage_end') or 0)
            end = rec['ended'] or rec.get('last_stage_end')
            dur = end - rec['started'] if rec['started'] and end and end >= rec['started'] else None
            if dur is None:
                dur = sum(e for _, e, _ in rec['stages'] if e) or None
            r['duration_s'] = dur
            runs.append(r)
    runs.sort(key=lambda r: r['t'], reverse=True)
    return runs, {'excluded_test_runs': tests, 'excluded_synthesized': synthesized, 'unreadable': unreadable}


def _window(days, now):
    return now - days * DAY if days else None


def _bucketing(since, now, earliest):
    start = since if since else (earliest or now)
    weekly = (now - start) > 120 * DAY
    d = datetime.fromtimestamp(start, TZ).date()
    end = datetime.fromtimestamp(now, TZ).date()
    if weekly:
        d -= timedelta(days=d.weekday())
    step = timedelta(days=7 if weekly else 1)
    keys = []
    while d <= end:
        keys.append(d.isoformat())
        d += step
    return keys, weekly


def _bucket_of(ts, weekly):
    d = datetime.fromtimestamp(ts, TZ).date()
    if weekly:
        d -= timedelta(days=d.weekday())
    return d.isoformat()


def _run_row(r):
    return {
        'id': r['id'][:36],
        'kind': r['kind'],
        'label': KIND_LABELS.get(r['kind'], r['kind'].replace('_', ' ').title()),
        'family': r['family'],
        'title': r['title'],
        'status': r['status'],
        'status_raw': r['status_raw'],
        'inferred': r['inferred'],
        'started': _iso(r['started']),
        'last_write': _iso(r['last_write']),
        'duration_s': round(r['duration_s']) if r['duration_s'] else None,
        'error': r['error'][:140],
        'current_stage': r['current_stage'],
    }


def _runs_daily(runs, since, now, earliest):
    keys, weekly = _bucketing(since, now, earliest)
    idx = {k: i for i, k in enumerate(keys)}
    series = {f: [0] * len(keys) for f in FAMILIES + ('other',)}
    for r in runs:
        i = idx.get(_bucket_of(r['t'], weekly))
        if i is not None:
            series[r['family']][i] += 1
    return {
        'bucket': 'week' if weekly else 'day',
        'keys': keys,
        'series': [
            {'id': f, 'label': FAMILY_LABELS[f], 'values': series[f]} for f in FAMILIES + ('other',) if any(series[f])
        ],
    }
