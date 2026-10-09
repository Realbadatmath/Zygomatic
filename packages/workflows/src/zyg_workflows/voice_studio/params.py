# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.params — the parameter spec — RACKS, defaults(), sanitize(), is_default().

Moved verbatim from voice_studio.py lines 861-1258 (2026-10-06 split).
"""

from __future__ import annotations

import os

from zyg_workflows.voice_studio.constants import (
    _CHATTERBOX_PY,
)


# ─────────────────────────────────────────────────────────── parameter spec
# One source of truth: the GUI builds its knob panel from this, the renderer
# reads the same dict, and sanitize() clamps anything a caller invents.
RACKS = [
    {
        'id': 'engine',
        'title': 'ENGINE',
        'sub': 'Who renders the line, and how hard it acts. Delivery — not identity.',
        'params': [
            # Default follows what is INSTALLED: the Chatterbox venv was deleted
            # in the 2026-10-02 disk sweep, and a tab whose default engine is
            # missing renders nothing on every click (found 2026-10-03 while
            # building the Ubi bench). IndexTTS-2 is the house primary anyway.
            {
                'key': 'engine',
                'type': 'select',
                'label': 'Engine',
                'def': 'chatterbox' if os.path.isfile(_CHATTERBOX_PY) else 'indextts2',
                'options': [
                    {'v': 'chatterbox', 'l': 'Chatterbox (MIT)'},
                    {'v': 'indextts2', 'l': 'IndexTTS-2 (house primary)'},
                ],
                'hint': 'Chatterbox is the operator pick for Abel — its timbre won a '
                'blind listen against IndexTTS-2. Both are zero-shot cloners of '
                'the same frozen seed.',
            },
            {
                'key': 'device',
                'type': 'select',
                'label': 'Device',
                'def': 'auto',
                'options': [{'v': 'auto', 'l': 'auto'}, {'v': 'cuda', 'l': 'cuda'}, {'v': 'cpu', 'l': 'cpu'}],
                'only': 'chatterbox',
                'hint': 'CPU is ~4–6 s per WORD. Keep a preview line short if the GPU is busy.',
            },
            {
                'key': 'eng_seed',
                'type': 'int',
                'label': 'Seed',
                'def': 1672,
                'min': 0,
                'max': 999999,
                'step': 1,
                'hint': 'Sampling seed. Same seed + same knobs = the same take, which '
                'is what makes an A/B comparison mean anything.',
            },
            {
                'key': 'cb_exaggeration',
                'type': 'knob',
                'label': 'Exaggeration',
                'def': 0.30,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'only': 'chatterbox',
                'hint': 'Emotional push. Above ~0.6 Abel starts performing instead of recounting.',
            },
            {
                'key': 'cb_cfg_weight',
                'type': 'knob',
                'label': 'CFG weight',
                'def': 0.40,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'only': 'chatterbox',
                'hint': 'Adherence to the reference. LOWER this if the read rushes — '
                'Chatterbox is known to run fast (measured 221 wpm vs the '
                '150–210 sanity band).',
            },
            {
                'key': 'cb_temperature',
                'type': 'knob',
                'label': 'Temperature',
                'def': 0.70,
                'min': 0.05,
                'max': 1.50,
                'step': 0.01,
                'only': 'chatterbox',
                'hint': 'Sampling spread. High = more varied, less repeatable.',
            },
            {
                'key': 'ix_emo_alpha',
                'type': 'knob',
                'label': 'Emotion α',
                'def': 0.60,
                'min': 0.0,
                'max': 1.0,
                'step': 0.01,
                'only': 'indextts2',
                'hint': 'How much emotion IndexTTS-2 infers. Lower it for a calmer read '
                '— the briefing channels run 0.35.',
            },
            {
                'key': 'ix_emo_text',
                'type': 'toggle',
                'label': 'Emotion from text',
                'def': True,
                'only': 'indextts2',
                'hint': 'Off = flat, literal delivery regardless of what the words say.',
            },
        ],
    },
    {
        'id': 'source',
        'title': 'SOURCE — seed shaping',
        'sub': 'Reshapes the reference wav before the cloner sees it. This changes '
        'WHO is speaking. The frozen seed on disk is never modified.',
        'params': [
            {
                'key': 'seed_k',
                'type': 'knob',
                'label': 'Seed k (size)',
                'def': 1.000,
                'min': 0.850,
                'max': 1.200,
                'step': 0.002,
                'unit': '×',
                'hint': 'Resample. Raises pitch AND shrinks the vocal tract together — '
                'k>1 is younger and smaller, k<1 is older and bigger. This is '
                'the knob that can accidentally shrink Abel into female tract '
                'territory.',
            },
            {
                'key': 'seed_m',
                'type': 'knob',
                'label': 'Seed m (pitch)',
                'def': 1.000,
                'min': 0.700,
                'max': 1.500,
                'step': 0.005,
                'unit': '×',
                'hint': 'Formant-preserved pitch shift. The frozen seed already carries '
                'm=1.45; this is ON TOP of it. k and m are not independent: '
                'preservation holds going DOWN but not going UP, so m>1 drags '
                'the formants along and VTL saturates near 14.4 cm — the same '
                'ceiling that made two seed candidates read female.',
            },
        ],
    },
    {
        'id': 'shape',
        'title': 'RENDER SHAPE',
        'sub': 'Applied after synthesis, to the recording. Same two levers as the '
        'seed rack, because the DSP is the same — measured on this box, not '
        'assumed.',
        'params': [
            {
                'key': 'size',
                'type': 'knob',
                'label': 'Size k',
                'def': 1.000,
                'min': 0.800,
                'max': 1.250,
                'step': 0.005,
                'unit': '×',
                'hint': 'Resample: moves pitch AND vocal tract together, fully and '
                'predictably. Measured on Abel: k=1.10 → F0 155→170 Hz, VTL '
                '15.94→14.49 cm; k=0.90 → 139 Hz / 16.49 cm. This is the knob '
                'that makes the speaker BIGGER or SMALLER.',
            },
            {
                'key': 'pitch_st',
                'type': 'knob',
                'label': 'Pitch m',
                'def': 0.0,
                'min': -6.0,
                'max': 6.0,
                'step': 0.1,
                'unit': 'st',
                'hint': 'Rubberband with formant=preserved. It is NOT symmetric on this '
                'ffmpeg build and pretending otherwise would mislabel the knob: '
                'pitching DOWN really does hold the tract (−1.9 st → 140 Hz but '
                'VTL only 15.94→16.04), pitching UP drags the tract up with it, '
                'identical to a plain resample (+1.7 st → 170 Hz / 14.46 cm). So '
                'downward is a pitch-only move; upward is a size move in '
                'disguise. Watch the VTL meter.',
            },
            {
                'key': 'tempo',
                'type': 'knob',
                'label': 'Tempo',
                'def': 1.000,
                'min': 0.750,
                'max': 1.350,
                'step': 0.005,
                'unit': '×',
                'hint': 'Pace only — pitch and formants untouched.',
            },
        ],
    },
    {
        'id': 'tone',
        'title': 'TONE',
        'sub': 'Fixed-frequency EQ. Every band at 0 dB bypasses the filter entirely.',
        'params': [
            {
                'key': 'hpf',
                'type': 'knob',
                'label': 'Rumble cut',
                'def': 20,
                'min': 20,
                'max': 160,
                'step': 1,
                'unit': 'Hz',
                'hint': 'High-pass. OFF at 20 Hz — the default, so a defaults render is '
                'exactly what production narration would produce. 70–90 Hz is '
                'the usual working setting.',
            },
            {
                'key': 'warmth',
                'type': 'knob',
                'label': 'Warmth 200',
                'def': 0.0,
                'min': -8.0,
                'max': 8.0,
                'step': 0.1,
                'unit': 'dB',
                'hint': "Chest weight. Too much and a teenage voice gets a man's body.",
            },
            {
                'key': 'body',
                'type': 'knob',
                'label': 'Body 450',
                'def': 0.0,
                'min': -8.0,
                'max': 8.0,
                'step': 0.1,
                'unit': 'dB',
                'hint': 'Cut here to clear boxiness.',
            },
            {
                'key': 'mid',
                'type': 'knob',
                'label': 'Mid 1.2k',
                'def': 0.0,
                'min': -8.0,
                'max': 8.0,
                'step': 0.1,
                'unit': 'dB',
                'hint': 'Nasal/honk range.',
            },
            {
                'key': 'presence',
                'type': 'knob',
                'label': 'Presence 3.5k',
                'def': 0.0,
                'min': -8.0,
                'max': 8.0,
                'step': 0.1,
                'unit': 'dB',
                'hint': 'Intelligibility and closeness. Push with the de-esser, not without it.',
            },
            {
                'key': 'air',
                'type': 'knob',
                'label': 'Air 9k',
                'def': 0.0,
                'min': -8.0,
                'max': 8.0,
                'step': 0.1,
                'unit': 'dB',
                'hint': 'High shelf. Adds breath; also adds cloner hiss.',
            },
        ],
    },
    {
        'id': 'dynamics',
        'title': 'DYNAMICS',
        'sub': 'Both bypass at 0.',
        'params': [
            {
                'key': 'deess',
                'type': 'knob',
                'label': 'De-ess',
                'def': 0,
                'min': 0,
                'max': 100,
                'step': 1,
                'unit': '%',
                'hint': 'Sibilance control. Needed once Presence or Air goes up.',
            },
            {
                'key': 'comp',
                'type': 'knob',
                'label': 'Compress',
                'def': 0,
                'min': 0,
                'max': 100,
                'step': 1,
                'unit': '%',
                'hint': 'Evens the read. 0 % → ratio 1:1 → filter omitted; 100 % → 4:1 at −30 dB.',
            },
        ],
    },
    {
        'id': 'space',
        'title': 'SPACE',
        'sub': 'A hint of room. Narration bakes into the scene mix later, so keep '
        'this small — the ambience bed is where the world lives.',
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
                'hint': 'Two-tap early reflection. 0 % bypasses.',
            },
            {
                'key': 'room_ms',
                'type': 'knob',
                'label': 'Room size',
                'def': 45,
                'min': 15,
                'max': 140,
                'step': 1,
                'unit': 'ms',
                'hint': 'First reflection delay. Small = tight cabin, large = hall.',
            },
        ],
    },
    {
        'id': 'output',
        'title': 'OUTPUT',
        'sub': 'Two-pass EBU R128 — never single-pass, which runs a dynamic AGC that mangles deliberate pauses.',
        'params': [
            {
                'key': 'lufs',
                'type': 'knob',
                'label': 'Loudness',
                'def': -16.0,
                'min': -24.0,
                'max': -10.0,
                'step': 0.5,
                'unit': 'LUFS',
                'hint': '−16 is the house narration STEM target; the finished master '
                'lands at −14 after the bed and duck.',
            },
            {
                'key': 'tp',
                'type': 'knob',
                'label': 'True peak',
                'def': -1.5,
                'min': -3.0,
                'max': -0.5,
                'step': 0.1,
                'unit': 'dBTP',
                'hint': 'Ceiling.',
            },
        ],
    },
]

_PARAMS = {p['key']: p for r in RACKS for p in r['params']}


def defaults() -> dict:
    return {k: p['def'] for k, p in _PARAMS.items()}


def sanitize(params: dict) -> dict:
    """Clamp/coerce a caller-supplied dict onto the spec. Unknown keys are dropped,
    missing keys take their default — a preset written by an older revision still
    loads."""
    out = defaults()
    for k, v in (params or {}).items():
        spec = _PARAMS.get(k)
        if not spec:
            continue
        t = spec['type']
        try:
            if t == 'select':
                allowed = [o['v'] for o in spec['options']]
                out[k] = v if v in allowed else spec['def']
            elif t == 'toggle':
                out[k] = bool(v) if not isinstance(v, str) else v.strip().lower() not in ('0', 'false', 'no', 'off', '')
            elif t == 'int':
                out[k] = int(max(spec['min'], min(spec['max'], int(float(v)))))
            else:
                out[k] = float(max(spec['min'], min(spec['max'], float(v))))
        except (TypeError, ValueError):
            out[k] = spec['def']
    return out


def is_default(params: dict, key: str) -> bool:
    spec = _PARAMS.get(key) or {}
    d = spec.get('def')
    v = params.get(key, d)
    if isinstance(d, float):
        return abs(float(v) - d) < 1e-9
    return v == d
