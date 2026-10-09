# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The knob rack, the effect-type roster and the tweak/slot cleaners."""

from zyg_workflows.sfx_merger.constants import MAX_ITEMS, MAX_SLOTS, _SR

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ── the knob rack ─────────────────────────────────────────────────────────────
# Same shape as voice_studio.RACKS so the tab draws it with the same knob code.
# Every knob at its default collapses the chain to a bare resample: an untouched
# layer is the library file, level for level.
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
                'hint': 'Semitones, length unchanged (rubberband).',
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
                'hint': 'Varispeed: pitch AND length together, like slowing a tape. '
                '0.5 = an octave down and twice as long.',
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
                'metallic; the classic sound-design mangler.',
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
# 'tweak' (the ffmpeg-filter rack above) plus, when plugin_host loaded cleanly,
# real VST3 DSP plugins (see plugin_host.py: LSP Plugins, isolated in a worker
# subprocess). A slot is either empty or holds one instance of an entry here.
# plugin_host degrades to EFFECT_TYPES=[] on any failure (missing pedalboard,
# moved plugin file, …) rather than taking this module down with it.
try:
    from zyg_workflows import plugin_host

    _PLUGIN_EFFECT_TYPES = plugin_host.EFFECT_TYPES
except Exception:  # noqa: BLE001
    plugin_host = None
    _PLUGIN_EFFECT_TYPES = []
# sfx_fx.py (2026-09-02) is the full effect roster — 63 ffmpeg-backed blocks
# declared in exactly this shape. Same degrade-don't-die contract as plugin_host:
# if it cannot be imported the tab keeps the Tweaker and says so.
try:
    from zyg_workflows import sfx_fx

    _FX_EFFECT_TYPES = sfx_fx.EFFECT_TYPES
except Exception as _e:  # noqa: BLE001
    sfx_fx = None
    _FX_EFFECT_TYPES = []
    _zyg_log.info(f'[SFX-MERGER] sfx_fx unavailable - {_e}')

EFFECT_TYPES = (
    [{'id': 'tweak', 'title': 'Tweaker', 'cat': 'core', 'racks': RACKS}] + _FX_EFFECT_TYPES + _PLUGIN_EFFECT_TYPES
)
_EFFECT_BY_ID = {e['id']: e for e in EFFECT_TYPES}
# Each effect type owns its own key namespace — a plugin's 'ratio' and
# Tweaker's 'gain' never have to avoid colliding with each other — so cleaning
# a slot's tweak dict always goes through the SPEC OF ITS OWN TYPE, not one
# global flattened dict (that only ever worked because 'tweak' used to be the
# only effect type in existence).
_PARAMS_BY_TYPE = {'tweak': _PARAMS}
for _e in _FX_EFFECT_TYPES + _PLUGIN_EFFECT_TYPES:
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
    """Clamp an incoming tweak dict onto typ's own spec. Unknown keys are
    dropped, missing keys take the default, so two clients that agree on the
    knobs always hash to the same stem."""
    t = t if isinstance(t, dict) else {}
    out = {}
    for k, p in _params_for(typ).items():
        v = t.get(k, p['def'])
        if p['type'] == 'toggle':
            if isinstance(v, str):
                v = v.strip().lower() in ('1', 'true', 'on', 'yes')
            out[k] = bool(v)
            continue
        if p['type'] == 'select':
            # stored as the INDEX into the option list, so a slot's tweak dict
            # stays numeric and two clients hash to the same stem
            try:
                i = int(round(float(v)))
            except (TypeError, ValueError):
                i = int(p['def'])
            out[k] = max(0, min(len(p.get('opts') or [None]) - 1, i))
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
    """Wrap a pre-slots flat tweak dict as one 'tweak' slot — [] if it was never
    touched, so an old untouched layer still shows an empty mixer, not a
    Tweaker sitting at its defaults."""
    if not isinstance(t, dict) or _is_default(clean_tweak(t)):
        return []
    return [{'type': 'tweak', 'tweak': clean_tweak(t)}]


def clean_slots(raw):
    """Clamp an incoming slot list onto the spec: unknown effect types are
    dropped, each slot's own params go through clean_tweak scoped to ITS type,
    and the list is capped at MAX_SLOTS. A bare tweak dict (pre-slots clients,
    old localStorage, v1 recipes) is accepted and migrated in place."""
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
