# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / presets, and the payload the page draws both bars from.

Moved verbatim out of the old single-file creature_fx.py (lines 6019-6089).
"""

from __future__ import annotations

import json
import os
import time
import uuid

from zyg_workflows.creature_fx.base import CELL_PX, OPS, PRESETS, RUNTIME
from zyg_workflows.creature_fx.ops_dock import OP_BY_ID
from zyg_workflows.creature_fx.resolve import BASE_CREATURES, comfy_up
from zyg_workflows.creature_fx.compiler import normalise_stack
from zyg_workflows.creature_fx.writes import _write_json


# ── presets ─────────────────────────────────────────────────────────────────
def load_presets():
    try:
        with open(PRESETS, encoding='utf-8') as fh:
            return (json.load(fh) or {}).get('presets', [])
    except (OSError, ValueError):
        return []


def save_preset(name, stack, note=''):
    name = str(name or '').strip()[:60]
    if not name:
        return {'ok': False, 'error': 'a preset needs a name'}
    rows, dropped = normalise_stack(stack)
    if not rows:
        return {'ok': False, 'error': 'nothing to save'}
    ps = load_presets()
    rec = {
        'id': uuid.uuid4().hex[:10],
        'name': name,
        'note': str(note or '')[:400],
        'when': time.strftime('%Y-%m-%d %H:%M'),
        'stack': rows,
        'ops': [OP_BY_ID[r['op']]['lb'] for r in rows],
    }
    ps = [p for p in ps if p.get('name') != name] + [rec]
    os.makedirs(RUNTIME, exist_ok=True)
    _write_json(PRESETS, {'presets': ps[-200:]})
    return {'ok': True, 'preset': rec, 'dropped': dropped}


def delete_preset(pid):
    ps = [p for p in load_presets() if p.get('id') != str(pid or '')]
    os.makedirs(RUNTIME, exist_ok=True)
    _write_json(PRESETS, {'presets': ps})
    return {'ok': True, 'presets': ps}


# ── what the page draws both bars from ──────────────────────────────────────
def ops_payload():
    """The single source of truth for what exists, what it is called, what it
    does, what it looks like and what knobs it has.

    The page holds no tool list: add an op above and it appears in the rail with
    its icon and its panel without a line of the page changing."""
    secs, order = {}, []
    for o in OPS:
        key = (o['bar'], o['sec'])
        if key not in secs:
            secs[key] = []
            order.append(key)
        secs[key].append({k: v for k, v in o.items() if k not in ('fn', 'pfn')})
    return {
        'ok': True,
        'sections': [{'bar': bar, 'sec': sec, 'items': secs[(bar, sec)]} for bar, sec in order],
        'presets': load_presets(),
        'comfy': comfy_up(),
        'cell_px': CELL_PX,
        'base_creatures': BASE_CREATURES,
        'counts': {
            'side': sum(1 for o in OPS if o['bar'] == 'side'),
            'dock': sum(1 for o in OPS if o['bar'] == 'dock'),
            'generative': sum(1 for o in OPS if o['cls'] == 'edit'),
            'deterministic': sum(1 for o in OPS if o['cls'] == 'pix'),
            'total': len(OPS),
        },
        'bands': sorted(_BANDS),
    }


_BANDS = ('front', 'quarter', 'side', 'back', 'top', 'close', 'wide', 'detail')
