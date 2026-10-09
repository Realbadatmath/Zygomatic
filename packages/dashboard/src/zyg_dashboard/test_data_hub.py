# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_data_hub.py — the Metrics > Test Data collector and store (:5000/metrics, subtab
Test Data). 2026-09-22.

One card per test that was actually performed. A test is recorded as a single JSON file in
data/runtime/test_data/<id>.json; this module validates those files, and `section_test_data`
turns them into the kanban payload the board draws (static/js/dashboard_testdata.js). The
frontend only draws — every number, label and unit is decided here, so the card, the chart,
the tooltip and the table twin cannot disagree.

Recording a test (the only way a card appears):

    from zyg_dashboard import test_data_hub as td
    td.record({
        'title': 'VRAM headroom at 4 concurrent renders',
        'question': 'Does a 4th concurrent render still fit in 24 GB?',
        'lane': 'capacity',                       # performance|quality|capacity|reliability|other
        'status': 'fail',                         # pass|fail|mixed|inconclusive|baseline|running
        'verdict': 'The 4th render spills at 24.6 GB peak.',
        'method': ['nvidia-smi sampled at 2 Hz', 'one render added every 60 s'],
        'headline': {'value': 24.6, 'fmt': 'gb', 'label': 'peak VRAM', 'sub': 'card holds 24.0'},
        'chart': {
            'title': 'Peak VRAM per concurrency level',
            'kind': 'columns',
            'x': {'label': 'concurrent renders', 'type': 'number', 'values': [1, 2, 3, 4]},
            'y': {'label': 'peak VRAM', 'unit': 'gb'},
            'series': [{'id': 'peak', 'label': 'Peak VRAM', 'values': [7.1, 13.0, 19.2, 24.6]}],
            'refs': [{'label': 'card limit', 'value': 24.0, 'kind': 'limit'}],
        },
        'facts': [{'label': 'Samples', 'value': 482, 'fmt': 'int'}],
        'table': {'columns': [{'t': 'Renders'}, {'t': 'Peak GB', 'r': True}],
                  'rows': [['1', '7.1'], ['2', '13.0']]},
        'notes': ['…how it was measured…'],
        'sources': [{'source': 'nvidia-smi', 'path': '/tmp/…/vram.csv'}],
    })

or from the shell:  `python3 test_data_hub.py record --file rec.json`  /  `… record --stdin`.
Other CLI verbs: `list`, `show <id>`, `rm <id>`, `section [--days N]`, `validate <file>`.

Honesty rules, the same ones the rest of the hub follows ([[feedback_measure_before_claim]]):
a card states its own null or baseline (`null_model`) and its limitations; a status of
`baseline` means "measured, no pass criterion"; `inconclusive` means the test ran but does
not answer its question. Nothing here infers a result from a missing field — a record that
does not validate is shipped as a broken card naming the reason, never silently dropped.

Hot-reloaded by metrics_hub.section('test_data') when this file's mtime changes.
"""

from __future__ import annotations

import hashlib
import json
import logging as _zyg_logging
import os
import re
import sys
import time
from datetime import datetime

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = os.path.dirname(os.path.abspath(__file__))  # the zyg_dashboard package dir

try:
    from zyg_dashboard import metrics_hub as mh

    RUNTIME = mh.RUNTIME
    TZ = mh.TZ
    DAY = mh.DAY
except Exception:  # standalone (CLI without the hub)
    from datetime import timezone

    mh = None
    RUNTIME = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or os.path.join(CREWS, 'data', 'runtime')
    TZ = timezone.utc
    DAY = 86400


STORE = os.environ.get('ZYG_TEST_DATA_DIR') or os.path.join(RUNTIME, 'test_data')

# Kanban lanes. A record may name any lane id; an unknown one is appended as its own lane
# (title-cased) rather than being folded into "other", so a new kind of test is never hidden.
LANES = [
    {'id': 'performance', 'label': 'Speed & throughput', 'hint': 'how fast, how much per hour', 'core': True},
    {'id': 'quality', 'label': 'Quality & accuracy', 'hint': 'does the output hold up', 'core': True},
    {'id': 'capacity', 'label': 'Capacity & resources', 'hint': 'VRAM, RAM, disk, cost ceilings', 'core': True},
    {
        'id': 'reliability',
        'label': 'Reliability & correctness',
        'hint': 'does it do the right thing, every time',
        'core': True,
    },
    {'id': 'other', 'label': 'Other', 'hint': 'everything else'},
]
LANE_IDS = [l['id'] for l in LANES]

STATUSES = {
    'pass': {'label': 'Pass', 'tone': 'good', 'icon': '✓'},
    'fail': {'label': 'Fail', 'tone': 'critical', 'icon': '✕'},
    'mixed': {'label': 'Mixed', 'tone': 'warning', 'icon': '~'},
    'inconclusive': {'label': 'Inconclusive', 'tone': 'warning', 'icon': '?'},
    'baseline': {'label': 'Baseline', 'tone': 'neutral', 'icon': '▤'},
    'running': {'label': 'Running', 'tone': 'open', 'icon': '▸'},
    'broken': {'label': 'Unreadable record', 'tone': 'critical', 'icon': '!'},
}

# Units the frontend can format. Anything else is printed as a plain number + the unit text.
UNITS = (
    'number',
    'int',
    'pct',
    'ratio',
    'x',
    'ms',
    's',
    'min',
    'h',
    'b',
    'kb',
    'mb',
    'gb',
    'tokens',
    'usd',
    'eur',
    'fps',
    'hz',
    'c',
    'w',
    'kwh',
    'px',
    'score',
    'count',
)
CHART_KINDS = ('line', 'columns', 'scatter', 'area')
X_TYPES = ('number', 'category', 'time')


# ── small helpers ────────────────────────────────────────────────────────────
def _iso(ts):
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), TZ).isoformat(timespec='seconds')
    except Exception:
        return None


def _parse_ts(v):
    """iso string or epoch -> epoch seconds (None when unreadable)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError as _exc:
        _zyg_log.debug('%r is not an epoch number, trying iso: %s', s, _exc)
    try:
        d = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        return d.timestamp()
    except Exception:
        return None


def _slug(s, maxlen=60):
    s = re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()).strip('-')
    return (s[:maxlen].rstrip('-')) or 'test'


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float('inf'), float('-inf')):
        return None
    return f


def _str_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if str(x).strip()]


# ── validation ───────────────────────────────────────────────────────────────
class TestRecordError(ValueError):
    """A record that cannot be drawn honestly."""


def _clean_series(s, n, where, errors):
    out = {
        'id': str(s.get('id') or _slug(s.get('label') or 'series')),
        'label': str(s.get('label') or s.get('id') or 'series'),
        'values': [_num(v) for v in (s.get('values') or [])],
    }
    if len(out['values']) != n:
        errors.append(f'{where}: series {out["id"]!r} has {len(out["values"])} values for {n} x points')
    for k in ('lo', 'hi'):
        if s.get(k) is not None:
            vals = [_num(v) for v in s[k]]
            if len(vals) != n:
                errors.append(f'{where}: series {out["id"]!r} {k} has {len(vals)} values for {n} x points')
            else:
                out[k] = vals
    if s.get('kind') in ('line', 'columns', 'scatter', 'area'):
        out['kind'] = s['kind']
    if s.get('style') in ('dashed', 'thin', 'dotted'):
        out['style'] = s['style']
    if s.get('axis') == 'y2':
        out['axis'] = 'y2'
    if s.get('color'):
        out['color'] = str(s['color'])
    if s.get('note'):
        out['note'] = str(s['note'])
    return out


def _clean_axis(a, default_unit='number'):
    a = a or {}
    unit = str(a.get('unit') or default_unit)
    return {
        'label': str(a.get('label') or ''),
        'unit': unit,
        'known_unit': unit in UNITS,
        'min': _num(a.get('min')),
        'max': _num(a.get('max')),
        'log': bool(a.get('log')),
    }


def _clean_chart(chart, where, errors):
    if not isinstance(chart, dict):
        errors.append(f'{where}: not an object')
        return None
    x = chart.get('x') or {}
    xvals = list(x.get('values') or [])
    if not xvals:
        errors.append(f'{where}: x.values is empty — a card needs a graph with at least one point')
    xtype = (
        x.get('type')
        if x.get('type') in X_TYPES
        else ('number' if all(_num(v) is not None for v in xvals) and xvals else 'category')
    )
    out = {
        'title': str(chart.get('title') or ''),
        'kind': chart.get('kind') if chart.get('kind') in CHART_KINDS else 'line',
        'stacked': bool(chart.get('stacked')),
        'x': {
            'label': str(x.get('label') or ''),
            'type': xtype,
            'values': [(_num(v) if xtype == 'number' else str(v)) for v in xvals],
            'unit': str(x.get('unit') or ''),
        },
        'y': _clean_axis(chart.get('y')),
        'series': [],
        'refs': [],
        'vrefs': [],
        'note': str(chart.get('note') or ''),
    }
    if chart.get('y2'):
        out['y2'] = _clean_axis(chart.get('y2'))
    n = len(out['x']['values'])
    for s in chart.get('series') or []:
        out['series'].append(_clean_series(s or {}, n, where, errors))
    if not out['series']:
        errors.append(f'{where}: no series')
    for r in chart.get('refs') or []:
        v = _num((r or {}).get('value'))
        if v is None:
            continue
        out['refs'].append(
            {
                'label': str(r.get('label') or ''),
                'value': v,
                'kind': r.get('kind') if r.get('kind') in ('limit', 'null', 'target', 'baseline') else 'target',
                'axis': 'y2' if r.get('axis') == 'y2' else 'y',
            }
        )
    for r in chart.get('vrefs') or []:
        out['vrefs'].append({'label': str((r or {}).get('label') or ''), 'at': r.get('at')})
    return out


def _clean_fact(f):
    f = f or {}
    return {
        'label': str(f.get('label') or ''),
        'value': f.get('value'),
        'fmt': str(f.get('fmt') or 'text'),
        'sub': str(f.get('sub') or ''),
    }


def _clean_table(t, where, errors):
    if not t:
        return None
    cols = [
        {'t': str((c or {}).get('t') if isinstance(c, dict) else c), 'r': bool(isinstance(c, dict) and c.get('r'))}
        for c in (t.get('columns') or [])
    ]
    rows = [[('' if c is None else str(c)) for c in (r or [])] for r in (t.get('rows') or [])]
    if cols and any(len(r) != len(cols) for r in rows):
        errors.append(f'{where}: a table row does not have {len(cols)} cells')
    return {'columns': cols, 'rows': rows, 'note': str(t.get('note') or '')}


def validate(rec, strict=True):
    """Return (clean_record, errors). Raises TestRecordError on strict + errors."""
    errors = []
    if not isinstance(rec, dict):
        raise TestRecordError('a test record must be a JSON object')
    title = str(rec.get('title') or '').strip()
    if not title:
        errors.append('title is required')
    status = rec.get('status') or 'baseline'
    if status not in STATUSES:
        errors.append(f'status {status!r} is not one of {", ".join(sorted(k for k in STATUSES if k != "broken"))}')
        status = 'baseline'
    lane = str(rec.get('lane') or 'other')
    run_at = _parse_ts(rec.get('run_at')) or time.time()
    chart = _clean_chart(rec.get('chart'), 'chart', errors)
    charts = [c for c in (_clean_chart(c, f'charts[{i}]', errors) for i, c in enumerate(rec.get('charts') or [])) if c]
    head = rec.get('headline') or {}
    clean = {
        'id': str(rec.get('id') or '').strip()
        or f'{datetime.fromtimestamp(run_at, TZ).strftime("%Y%m%d-%H%M")}-{_slug(title)}',
        'title': title,
        'question': str(rec.get('question') or ''),
        'lane': lane,
        'status': status,
        'tags': _str_list(rec.get('tags')),
        'run_at': _iso(run_at),
        'run_at_ts': run_at,
        'duration_s': _num(rec.get('duration_s')),
        'run_by': str(rec.get('run_by') or ''),
        'command': str(rec.get('command') or ''),
        'environment': dict(rec.get('environment') or {}),
        'headline': {
            'value': head.get('value'),
            'fmt': str(head.get('fmt') or 'number'),
            'label': str(head.get('label') or ''),
            'sub': str(head.get('sub') or ''),
        },
        'verdict': str(rec.get('verdict') or ''),
        'method': _str_list(rec.get('method')),
        'chart': chart,
        'charts': charts,
        'facts': [_clean_fact(f) for f in (rec.get('facts') or [])],
        'table': _clean_table(rec.get('table'), 'table', errors),
        'notes': _str_list(rec.get('notes')),
        'limitations': _str_list(rec.get('limitations')),
        'null_model': str(rec.get('null_model') or ''),
        'sources': [
            {
                'source': str((s or {}).get('source') or ''),
                'path': str((s or {}).get('path') or ''),
                'note': str((s or {}).get('note') or ''),
            }
            for s in (rec.get('sources') or [])
        ],
        'raw': rec.get('raw') if isinstance(rec.get('raw'), (dict, list)) else None,
        'recorded_at': str(rec.get('recorded_at') or '') or None,
        'schema': 1,
    }
    if strict and errors:
        raise TestRecordError('; '.join(errors))
    return clean, errors


# ── store ────────────────────────────────────────────────────────────────────
def _ensure_store():
    os.makedirs(STORE, exist_ok=True)
    return STORE


def path_for(test_id):
    return os.path.join(STORE, f'{_slug(test_id, 120)}.json')


def record(rec=None, **kw):
    """Validate and write one test record. Returns the stored path.

    An id already in the store is overwritten only with replace=True; otherwise the new
    record gets a -2, -3 … suffix, so re-running a test never silently rewrites history."""
    if rec is None:
        rec = {}
    if kw:
        rec = dict(rec, **{k: v for k, v in kw.items() if k not in ('replace',)})
    replace = bool(kw.get('replace') or (isinstance(rec, dict) and rec.pop('replace', False)))
    clean, _ = validate(rec, strict=True)
    _ensure_store()
    base = _slug(clean['id'], 120)
    p = path_for(base)
    if os.path.exists(p) and not replace:
        i = 2
        while os.path.exists(path_for(f'{base}-{i}')):
            i += 1
        base = f'{base}-{i}'
        p = path_for(base)
    clean['id'] = base
    clean['recorded_at'] = _iso(time.time())
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(clean, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, p)
    return p


def load_all():
    """Every record in the store, newest run first. An unreadable file becomes a `broken`
    card carrying its reason — never dropped."""
    out = []
    if not os.path.isdir(STORE):
        return out
    for name in sorted(os.listdir(STORE)):
        if not name.endswith('.json') or name.endswith('.tmp'):
            continue
        p = os.path.join(STORE, name)
        try:
            st = os.stat(p)
        except OSError as _exc:
            _zyg_log.warning('record %s not statable, dropped from the store listing: %s', p, _exc)
            continue
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            clean, errors = validate(raw, strict=False)
        except Exception as exc:  # noqa: BLE001
            out.append(
                {
                    'id': name[:-5],
                    'title': name[:-5],
                    'question': '',
                    'lane': 'other',
                    'status': 'broken',
                    'tags': [],
                    'run_at': _iso(st.st_mtime),
                    'run_at_ts': st.st_mtime,
                    'headline': {'value': None, 'fmt': 'text', 'label': '', 'sub': ''},
                    'verdict': '',
                    'method': [],
                    'chart': None,
                    'charts': [],
                    'facts': [],
                    'table': None,
                    'notes': [],
                    'limitations': [],
                    'sources': [],
                    'errors': [f'{type(exc).__name__}: {exc}'],
                    'file': p,
                    'file_bytes': st.st_size,
                }
            )
            continue
        clean['errors'] = errors
        if errors:
            clean['status'] = 'broken' if clean.get('chart') is None else clean['status']
        clean['file'] = p
        clean['file_bytes'] = st.st_size
        clean['file_mtime'] = _iso(st.st_mtime)
        out.append(clean)
    out.sort(key=lambda r: r.get('run_at_ts') or 0, reverse=True)
    return out


def delete(test_id):
    p = path_for(test_id)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


def _data_version(files):
    h = hashlib.sha1(usedforsecurity=False)
    for p, mtime, size in files:
        h.update(f'{os.path.basename(p)}:{mtime:.3f}:{size}|'.encode())
    return h.hexdigest()[:12]


# ── payload ──────────────────────────────────────────────────────────────────
def section_test_data(days=30, now=None, fresh=False):
    now = now or time.time()
    records = load_all()
    since = 0 if not days else now - days * DAY
    shown = [r for r in records if (r.get('run_at_ts') or 0) >= since]
    hidden = len(records) - len(shown)

    lanes = [dict(l) for l in LANES]
    known = set(LANE_IDS)
    for r in shown:
        lid = r.get('lane') or 'other'
        if lid not in known:
            known.add(lid)
            lanes.append(
                {'id': lid, 'label': lid.replace('_', ' ').title(), 'hint': 'recorded under a lane of its own'}
            )

    cards = []
    for r in shown:
        c = dict(r)
        c['lane'] = r.get('lane') if r.get('lane') in known else 'other'
        c['status_label'] = STATUSES.get(r.get('status'), STATUSES['baseline'])['label']
        c['status_tone'] = STATUSES.get(r.get('status'), STATUSES['baseline'])['tone']
        c['age_s'] = round(now - (r.get('run_at_ts') or now))
        c.pop('run_at_ts', None)
        cards.append(c)

    by_status = {}
    for r in shown:
        by_status[r.get('status')] = by_status.get(r.get('status'), 0) + 1
    decided = by_status.get('pass', 0) + by_status.get('fail', 0)

    files = []
    if os.path.isdir(STORE):
        for name in sorted(os.listdir(STORE)):
            if name.endswith('.json'):
                p = os.path.join(STORE, name)
                try:
                    st = os.stat(p)
                except OSError as _exc:
                    _zyg_log.debug('record %s not statable, left out of the file stats: %s', p, _exc)
                    continue
                files.append((p, st.st_mtime, st.st_size))
    last_write = max((m for _, m, _ in files), default=None)

    return {
        'lanes': lanes,
        'cards': cards,
        'summary': {
            'tests': len(shown),
            'tests_all_time': len(records),
            'hidden_by_range': hidden,
            'by_status': by_status,
            'pass_rate_pct': round(100.0 * by_status.get('pass', 0) / decided, 1) if decided else None,
            'decided': decided,
            'last_run_at': shown[0]['run_at'] if shown else None,
            'first_run_at': shown[-1]['run_at'] if shown else None,
            'broken': by_status.get('broken', 0),
        },
        'statuses': STATUSES,
        'store': {
            'dir': STORE,
            'files': len(files),
            'bytes': sum(s for _, _, s in files),
            'last_write': _iso(last_write),
        },
        'sources': [
            {
                'source': 'test records',
                'path': STORE,
                'files': len(files),
                'last_write': _iso(last_write),
                'age_s': round(now - last_write) if last_write else None,
            }
        ],
        'data_version': _data_version(files),
        'how': [
            'A card exists only for a test that was actually performed; the record is written when the test finishes.',
            'Every number on a card comes from its record file — the board computes nothing.',
            'A record that fails validation is shown as an unreadable card naming the reason, never dropped.',
            f'Records live in {STORE} (one JSON file per test) and can be re-read, corrected or removed by hand.',
        ],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else 'section'
    if cmd == 'record':
        if '--stdin' in argv:
            payload = json.load(sys.stdin)
        else:
            i = argv.index('--file') if '--file' in argv else None
            if i is None:
                _zyg_log.warning('usage: test_data_hub.py record (--file rec.json | --stdin) [--replace]')
                return 2
            with open(argv[i + 1], 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
        if '--replace' in argv:
            payload['replace'] = True
        items = payload if isinstance(payload, list) else [payload]
        for it in items:
            _zyg_log.info(record(it))
        return 0
    if cmd == 'validate':
        with open(argv[2], 'r', encoding='utf-8') as fh:
            _, errors = validate(json.load(fh), strict=False)
        _zyg_log.info('\n'.join(errors) if errors else 'ok')
        return 1 if errors else 0
    if cmd == 'list':
        for r in load_all():
            _zyg_log.info(f'{r["run_at"]}  {r["status"]:<12} {r["lane"]:<12} {r["id"]}  {r["title"]}')
        return 0
    if cmd == 'show':
        for r in load_all():
            if r['id'] == argv[2]:
                _zyg_log.info(json.dumps(r, indent=1, ensure_ascii=False, default=str))
                return 0
        _zyg_log.warning(f'no test {argv[2]!r}')
        return 1
    if cmd == 'rm':
        _zyg_log.info('removed' if delete(argv[2]) else 'not found')
        return 0
    days = int(argv[argv.index('--days') + 1]) if '--days' in argv else 30
    _zyg_log.info(json.dumps(section_test_data(days), indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli(sys.argv))
