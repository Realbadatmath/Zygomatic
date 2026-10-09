# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The three Approval Queue toggles: their volumes, batches and unit hours."""

from __future__ import annotations

import os
import re
from zyg_dashboard import metrics_hub as mh

from .constants import CREWS, RUNTIME


# ── approval queue: toggles, volumes, batches ────────────────────────────────


def _pick_count():
    """_ZERO_POOL_PICK_COUNT from crewai_web_gui.py — the documentary batch size — read from
    source so the scenario follows a code change without an edit here."""
    try:
        # crewai_web_gui is a package since 2026-10; the constant sits in its zero module
        with open(os.path.join(CREWS, 'crewai_web_gui', 'zero.py'), encoding='utf-8', errors='replace') as fh:
            m = re.search(r'^_ZERO_POOL_PICK_COUNT\s*=\s*(\d+)', fh.read(), re.M)
            return int(m.group(1)) if m else 6
    except OSError:
        return 6


def _batch_counts(obj, list_keys=('topics', 'episodes', 'songs', 'items')):
    counts = {'scheduled': 0, 'in_production': 0, 'done': 0, 'failed': 0, 'other': 0}
    if not isinstance(obj, dict):
        return counts, 0
    items = None
    for k in list_keys:
        if isinstance(obj.get(k), list):
            items = obj[k]
            break
    if items is None:
        return counts, 0
    for it in items:
        st = str((it or {}).get('status') or '').lower()
        if st in ('scheduled', 'queued', 'ready', 'pending'):
            counts['scheduled'] += 1
        elif st in ('in_production', 'running', 'started'):
            counts['in_production'] += 1
        elif st in ('done', 'completed', 'complete'):
            counts['done'] += 1
        elif st in ('failed', 'error', 'blocked'):
            counts['failed'] += 1
        else:
            counts['other'] += 1
    return counts, len(items)


def approval_queue(unit_s: dict):
    """The three Approval Queue toggles with the per-day volume their code produces while ON."""

    def load(name):
        try:
            return mh._read_json(os.path.join(RUNTIME, name)) or {}
        except Exception:
            return {}

    templates = load('storyteller_templates.json')
    tpl_enabled = sum(1 for t in (templates.get('templates') or []) if isinstance(t, dict) and t.get('enabled', True))
    picks = _pick_count()
    mel_per_day = max(1, min(20, int(os.environ.get('ZYG_MELODY_PER_DAY', '5'))))
    toggles = [
        {
            'id': 'documentary',
            'label': 'Documentary (Zero auto mode)',
            'kind': 'scholarly',
            'enabled': bool(load('zero_auto_mode.json').get('enabled')),
            'per_day': picks / 2.0,
            'rule': f'{picks} topics per batch, next batch 2 days after the previous one completes',
            'source': 'data/runtime/zero_auto_mode.json · crewai_web_gui._ZERO_POOL_PICK_COUNT',
            'batch': _batch_counts(load('zero_kanban_batch.json')),
        },
        {
            'id': 'storyteller',
            'label': 'Storyteller daily serial',
            'kind': 'storyteller',
            'enabled': bool(load('storyteller_daily.json').get('enabled')),
            'per_day': float(tpl_enabled),
            'rule': f'one episode per enabled template per day ({tpl_enabled} enabled)',
            'source': 'data/runtime/storyteller_daily.json · storyteller_templates.json',
            'batch': _batch_counts(load('storyteller_daily_batch.json')),
        },
        {
            'id': 'melody',
            'label': 'Melody (kids songs)',
            'kind': 'kidsmusic',
            'enabled': bool(load('melody_daily.json').get('enabled')),
            'per_day': float(mel_per_day),
            'rule': f'{mel_per_day} songs per day (ZYG_MELODY_PER_DAY)',
            'source': 'data/runtime/melody_daily.json · bp_melody_daily._MEL_PER_DAY',
            'batch': _batch_counts(load('melody_daily_batch.json')),
        },
    ]
    for t in toggles:
        u = unit_s.get(t['kind'])
        t['unit_s'] = u
        t['hours_per_day'] = round(t['per_day'] * u / 3600, 2) if u else None
        counts, n = t['batch']
        t['batch'] = counts | {'items': n}
    return toggles
