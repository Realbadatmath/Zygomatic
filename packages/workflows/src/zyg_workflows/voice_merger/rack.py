# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  # this module keeps the original top import block for its siblings and the package

import hashlib
import json
import logging as _zyg_logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from zyg_workflows import paths
from zyg_workflows.bin import exe

_HERE = str(paths.PKG_DIR)
_WORK = str(paths.DATA_DIR / 'runtime' / 'voice_merger')
_SR = 48000
_MERGED_CAT = 'voice_mix'
_REC_CAT = 'voice_recorded'
_LIB_CATS = (_MERGED_CAT, _REC_CAT)
MAX_ITEMS = 40
MAX_SLOTS = 10
_FF_TIMEOUT = 120
_MIX_TTL = 3 * 86400
_STEM_TTL = 14 * 86400
_BUDGET_BYTES = 6 * 1024**3
_SWEEP_EVERY = 120.0
_SWEEP = {'ts': 0.0}
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_MAX_LAYER_S = 600.0
_MAX_MIX_S = 600.0
_MAX_START_S = 600.0
_RENDER_SEM = threading.BoundedSemaphore(3)
_REL_RE = re.compile(r'^(stems|mixes)/[a-f0-9]{16,40}\.wav$')
_TAKE_FN_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,62}\|[a-f0-9]{16,40}$')
_CLIP_FN_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,62}\|seed/[A-Za-z0-9._/-]{1,200}\.(wav|mp3)$')

# ── the knob rack ─────────────────────────────────────────────────────────────
# Same shape as sfx_merger.RACKS — a layer of voice takes wants the same
# gain/pan/pitch/trim/tone/space controls a layer of sfx does. Duplicated
# rather than imported: this module is meant to stand alone (see module doc).
RACKS = [
    {
        'id': 'level',
        'title': 'LEVEL',
        'sub': 'Where this layer sits in the merge.',
        'params': [
            {
                'key': 'gain',
                'type': 'knob',
                'label': 'Gain',
                'def': 0.0,
                'min': -36.0,
                'max': 12.0,
                'step': 0.5,
                'unit': 'dB',
                'hint': 'Level of this layer in the merge.',
            },
            {
                'key': 'pan',
                'type': 'knob',
                'label': 'Pan',
                'def': 0,
                'min': -100,
                'max': 100,
                'step': 1,
                'unit': '%',
                'hint': 'Left / right placement (equal-power).',
            },
        ],
    },
    {
        'id': 'pitch',
        'title': 'PITCH & TIME',
        'sub': 'Pitch holds length; Tape moves both; Speed holds pitch.',
        'params': [
            {
                'key': 'pitch_st',
                'type': 'knob',
                'label': 'Pitch',
                'def': 0.0,
                'min': -24.0,
                'max': 24.0,
                'step': 0.5,
                'unit': 'st',
                'hint': 'Semitones, length unchanged (rubberband). This is a delivery '
                'move on the MIX, separate from the identity knobs on the '
                'voice itself — it can push a take out of its measured band.',
            },
            {
                'key': 'tape',
                'type': 'knob',
                'label': 'Tape',
                'def': 1.000,
                'min': 0.25,
                'max': 4.0,
                'step': 0.01,
                'unit': '×',
                'hint': 'Varispeed: pitch AND length together, like slowing a tape.',
            },
            {
                'key': 'speed',
                'type': 'knob',
                'label': 'Speed',
                'def': 1.000,
                'min': 0.5,
                'max': 2.0,
                'step': 0.01,
                'unit': '×',
                'hint': 'Length only, pitch unchanged.',
            },
            {'key': 'reverse', 'type': 'toggle', 'label': 'Reverse', 'def': False, 'hint': 'Play the layer backwards.'},
        ],
    },
    {
        'id': 'trim',
        'title': 'TRIM & FADES',
        'sub': 'Cut from either end; fade what is left.',
        'params': [
            {
                'key': 'trim_in',
                'type': 'knob',
                'label': 'Cut head',
                'def': 0.0,
                'min': 0.0,
                'max': 30.0,
                'step': 0.01,
                'unit': 's',
                'hint': 'Seconds removed from the start.',
            },
            {
                'key': 'trim_out',
                'type': 'knob',
                'label': 'Cut tail',
                'def': 0.0,
                'min': 0.0,
                'max': 30.0,
                'step': 0.01,
                'unit': 's',
                'hint': 'Seconds removed from the end.',
            },
            {
                'key': 'fade_in',
                'type': 'knob',
                'label': 'Fade in',
                'def': 0,
                'min': 0,
                'max': 5000,
                'step': 10,
                'unit': 'ms',
                'hint': '',
            },
            {
                'key': 'fade_out',
                'type': 'knob',
                'label': 'Fade out',
                'def': 0,
                'min': 0,
                'max': 5000,
                'step': 10,
                'unit': 'ms',
                'hint': '',
            },
        ],
    },
    {
        'id': 'tone',
        'title': 'TONE (Hz)',
        'sub': 'Low cut off at 20 Hz, high cut off at 20 kHz, shelves off at 0 dB.',
        'params': [
            {
                'key': 'hpf',
                'type': 'knob',
                'label': 'Low cut',
                'def': 20,
                'min': 20,
                'max': 2000,
                'step': 1,
                'unit': 'Hz',
                'hint': 'High-pass: removes rumble below this frequency.',
            },
            {
                'key': 'lpf',
                'type': 'knob',
                'label': 'High cut',
                'def': 20000,
                'min': 500,
                'max': 20000,
                'step': 10,
                'unit': 'Hz',
                'hint': 'Low-pass: dulls everything above this frequency.',
            },
            {
                'key': 'bass',
                'type': 'knob',
                'label': 'Bass 120',
                'def': 0.0,
                'min': -12.0,
                'max': 12.0,
                'step': 0.5,
                'unit': 'dB',
                'hint': 'Low shelf at 120 Hz.',
            },
            {
                'key': 'treble',
                'type': 'knob',
                'label': 'Treble 6k',
                'def': 0.0,
                'min': -12.0,
                'max': 12.0,
                'step': 0.5,
                'unit': 'dB',
                'hint': 'High shelf at 6 kHz.',
            },
            {
                'key': 'freq_shift',
                'type': 'knob',
                'label': 'Freq shift',
                'def': 0,
                'min': -2000,
                'max': 2000,
                'step': 5,
                'unit': 'Hz',
                'hint': 'Shifts every partial by a fixed number of Hz — inharmonic, '
                'metallic; not a natural voice move, but useful for a '
                'radio/comms layer under a scene.',
            },
        ],
    },
    {
        'id': 'space',
        'title': 'SPACE',
        'sub': 'A hint of room. 0 % bypasses.',
        'params': [
            {
                'key': 'room',
                'type': 'knob',
                'label': 'Room',
                'def': 0,
                'min': 0,
                'max': 100,
                'step': 1,
                'unit': '%',
                'hint': '',
            },
            {
                'key': 'room_ms',
                'type': 'knob',
                'label': 'Room size',
                'def': 60,
                'min': 15,
                'max': 250,
                'step': 1,
                'unit': 'ms',
                'hint': 'First reflection delay. Small = cabin, large = hall.',
            },
        ],
    },
]
_PARAMS = {p['key']: p for r in RACKS for p in r['params']}

# ── effect types (the mixer's slot picker) ─────────────────────────────────────
# Real VST3 DSP (see plugin_host.py) is genuinely shared infrastructure, not
# merger-specific — reused here exactly as sfx_merger reuses it.
try:
    from zyg_workflows import plugin_host

    _PLUGIN_EFFECT_TYPES = plugin_host.EFFECT_TYPES
except Exception:  # noqa: BLE001
    plugin_host = None
    _PLUGIN_EFFECT_TYPES = []

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_merger')

EFFECT_TYPES = [{'id': 'tweak', 'title': 'Tweaker', 'racks': RACKS}] + _PLUGIN_EFFECT_TYPES
_EFFECT_BY_ID = {e['id']: e for e in EFFECT_TYPES}
_PARAMS_BY_TYPE = {'tweak': _PARAMS}
for _e in _PLUGIN_EFFECT_TYPES:
    _PARAMS_BY_TYPE[_e['id']] = {p['key']: p for r in _e['racks'] for p in r['params']}


def _params_for(typ):
    return _PARAMS_BY_TYPE.get(typ, _PARAMS)


def defaults(typ='tweak'):
    return {k: p['def'] for k, p in _params_for(typ).items()}


def spec():
    return {
        'racks': RACKS,
        'effect_types': EFFECT_TYPES,
        'defaults': defaults(),
        'sr': _SR,
        'max_items': MAX_ITEMS,
        'max_slots': MAX_SLOTS,
    }


def clean_tweak(t, typ='tweak'):
    t = t if isinstance(t, dict) else {}
    out = {}
    for k, p in _params_for(typ).items():
        v = t.get(k, p['def'])
        if p['type'] == 'toggle':
            if isinstance(v, str):
                v = v.strip().lower() in ('1', 'true', 'on', 'yes')
            out[k] = bool(v)
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = float(p['def'])
        if v != v:  # NaN
            v = float(p['def'])
        v = max(float(p['min']), min(float(p['max']), v))
        step = float(p.get('step') or 0)
        if step:
            v = float(p['min']) + round((v - float(p['min'])) / step) * step
        out[k] = round(v, 4)
    return out


def _is_default(t, typ='tweak'):
    d = defaults(typ)
    ps = _params_for(typ)
    return all(
        (bool(t[k]) == bool(d[k])) if ps[k]['type'] == 'toggle' else abs(float(t[k]) - float(d[k])) < 1e-9 for k in d
    )


def _slots_from_legacy(t):
    if not isinstance(t, dict) or _is_default(clean_tweak(t)):
        return []
    return [{'type': 'tweak', 'tweak': clean_tweak(t)}]


def clean_slots(raw):
    if isinstance(raw, dict):
        return _slots_from_legacy(raw)
    if not isinstance(raw, list):
        return []
    out = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        typ = str(s.get('type') or '')
        if typ not in _EFFECT_BY_ID:
            continue
        out.append({'type': typ, 'tweak': clean_tweak(s.get('tweak'), typ)})
        if len(out) >= MAX_SLOTS:
            break
    return out
