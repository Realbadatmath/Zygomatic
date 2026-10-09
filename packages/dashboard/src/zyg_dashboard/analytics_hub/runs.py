# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The run ledger: output-file first write, state path, enrich_runs()."""

from __future__ import annotations

import os
from zyg_dashboard import metrics_hub as mh

from .constants import API, ASSET_KINDS, CONTENT_KINDS, INFER_MAX_S, INFER_MIN_S, RUNTIME, _zyg_log


# ── runs, durations, per-run cost ────────────────────────────────────────────

_OUTDIR_MIN: dict = {}


def _outdir_first_write(path):
    """Earliest file mtime under a kids-music output dir (cached by the state file's mtime)."""
    try:
        d = mh._read_json(path)
        od = d.get('output_dir') if isinstance(d, dict) else None
        if not od or not os.path.isdir(od):
            return None
        key = (path, os.path.getmtime(path))
        if key in _OUTDIR_MIN:
            return _OUTDIR_MIN[key]
        mn = None
        for root, _, files in os.walk(od):
            for f in files:
                try:
                    m = os.path.getmtime(os.path.join(root, f))
                except OSError as _exc:
                    _zyg_log.debug('skipping output file with unreadable mtime: %s', _exc)
                    continue
                mn = m if mn is None or m < mn else mn
        _OUTDIR_MIN[key] = mn
        return mn
    except Exception:
        return None


def _state_path(r):
    src = r.get('source')
    if src == 'pipeline_state':
        return os.path.join(RUNTIME, f'pipeline_{r["id"]}_state.json')
    if src == 'storyteller_state':
        return os.path.join(RUNTIME, f'storyteller_{r["id"]}_state.json')
    return None


def enrich_runs(now):
    """Runs with a duration basis and their attributed API cost."""
    runs, meta = mh.collect_runs(now)
    llm = mh.collect_llm(now)
    cost_by_pid: dict = {}
    tokens_by_pid: dict = {}
    replayed_by_pid: dict = {}
    for c in llm['rows']:
        if not c['pid']:
            continue
        t = (c['tin'] or 0) + (c['tout'] or 0)
        if c.get('replayed'):  # answered from the bank — never spent here
            replayed_by_pid[c['pid']] = replayed_by_pid.get(c['pid'], 0) + t
            continue
        tokens_by_pid[c['pid']] = tokens_by_pid.get(c['pid'], 0) + t
        if c['provider'] in API and c['cost']:
            cost_by_pid[c['pid']] = cost_by_pid.get(c['pid'], 0.0) + c['cost']
    out = []
    for r in runs:
        r = dict(r)
        dur, basis = r.get('duration_s'), 'recorded'
        if dur is None and r['status'] in ('completed', 'failed') and r['started']:
            if r['kind'] == 'kidsmusic':
                p = _state_path(r)
                first = _outdir_first_write(p) if p else None
                if first and INFER_MIN_S <= r['started'] - first <= INFER_MAX_S:
                    dur, basis = r['started'] - first, 'inferred (start − first output file)'
            else:
                d = r['mtime'] - r['started']
                if INFER_MIN_S <= d <= INFER_MAX_S:
                    dur, basis = d, 'inferred (last state write − start)'
        if dur is None:
            basis = 'missing'
        r['duration_s'], r['duration_basis'] = dur, basis
        r['api_cost_usd'] = cost_by_pid.get(r['id'], 0.0)
        r['llm_tokens'] = tokens_by_pid.get(r['id'], 0)
        r['replayed_tokens'] = replayed_by_pid.get(r['id'], 0)
        r['is_content'] = r['kind'] in CONTENT_KINDS
        r['is_asset'] = r['kind'] in ASSET_KINDS
        out.append(r)
    return out, meta, llm
