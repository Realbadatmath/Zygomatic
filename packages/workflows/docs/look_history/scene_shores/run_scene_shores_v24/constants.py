# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this module inherits the pre-split file's top import
# block verbatim; its siblings re-import from here, so nothing is unused.

# Re-anchored: the package carries the old module's name, so __package__ IS
# the original __name__. Restores getLogger(__name__), Blueprint(__name__)
# and every moved function's __module__ without editing moved bytes.
__name__ = __package__

import copy
import json
import math
import os
import shutil
import subprocess
import sys

import soundfile as sf

from zyg_workflows import paths
from zyg_workflows.bin import exe

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v20_quay')
SRC_MP4 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v20_quay.mp4')
SLUG = 'second_ledger_intro_teen08_settled_shores_v24_curve'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')
NEW_PLATE = os.path.join(SRC_DIR, 'still_day1_harbor.png')
NEW_HIRES = os.path.join(SRC_DIR, 'still_day1_harbor.hires.png')
SCENE_CFG = os.path.join(CREWS, 'data', 'assets', 'scenes', 'second_ledger_shores')
BIRD_CFG = os.path.join(SCENE_CFG, 'bird_cfg3d_v24.json')
WATER_POLY = os.path.join(SCENE_CFG, 'water_poly.json')
SPRITE_DIR = os.path.join(CREWS, 'data', 'assets', 'bird_sprites', 'canary')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

# ── the tail, all of it v19's except BIRD_DUR ──────────────────────────────
BIRD_IN = 2.0
BIRD_DUR = 11.0
BEAT_S = 0.2
TAIL_FADE_IN_S = 1.1
END_FADE_S = 3.0
MASTER_FADE_S = 2.0
OVERSHOOT_S = 2.0

# Where the moored ship is, in plate fractions. No longer where the flight has
# to END (see the module header) — this is now the CLOSEST APPROACH target:
# the bird has to visibly pass the boat before it banks away.
SHIP_AT = (0.628, 0.470)
SHIP_TOL = 0.075

STILLS_CARRY = (
    'still_cabin_abel.png',
    'still_cabin_abel.png.wlock_c3345deb',
    'still_cabin_abel.hires.png',
    'still_cabin_abel.hires.png.handfix',
)
TAKES = tuple(f'line_{i:02d}_abel{s}' for i in range(4) for s in ('.wav', '.wav.tune', '_raw.wav', '_raw.wav.take')) + (
    'anchor_00_abel.wav',
    'anchor_00_abel.wav.tune',
)
_AUDIO_TAKES = tuple(f'line_{i:02d}_abel.wav' for i in range(4)) + ('anchor_00_abel.wav',)

# FIVE boxes, and the floor is their MEDIAN — see v22's header for why max
# hands the check to whichever box the encoder happened to be noisiest in.
_STATIC_REGIONS = {
    'right gable': (1170, 40, 1330, 200),
    'left roofline': (200, 195, 420, 300),
    'left houses': (60, 330, 260, 470),
    'right brick': (1180, 230, 1330, 420),
    'left gables': (250, 300, 430, 430),
}


def _canary_px(a: np.ndarray) -> int:
    """The bird's colour in the DELIVERED file, after the grade. See v22's
    header — the blue deficit survives the grade, the plate-space g>=r test
    does not."""
    g, b = a[..., 1], a[..., 2]
    return int(((g - b > 90) & (g > 120)).sum())


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _cp(s, d, force=False):
    if os.path.isfile(s) and (force or not os.path.isfile(d)):
        shutil.copyfile(s, d)
        return 1
    return 0


def _carry(names, label):
    n = sum(_cp(os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)) for f in names)
    print(f'[run] carried {n} new / {len(names)} {label}')


def _restamp(spec):
    """Re-write the carried markers in the CURRENT key format, so build_scene
    does not answer a stale marker by re-synthesising a picked take."""
    voices = spec['voices']
    jobs = [(f'line_{i:02d}_abel.wav', dict(spec['dialogue'][i])) for i in range(4)]
    jobs.append(('anchor_00_abel.wav', dict(spec['anchored_lines'][0])))
    n = 0
    for fname, ev in jobs:
        wav = os.path.join(OUT_DIR, fname)
        v = dict(voices[ev['speaker']])
        for k in ('seed', 'exaggeration', 'cfg_weight', 'temperature', 'tempo', 'pace_ref'):
            if k in ev:
                v[k] = ev[k]
        take = sss._take_key(v, ev['text'])
        want = f'{sss._tune_key(v, wav)}|{take}'
        got = None
        if os.path.isfile(wav + '.tune'):
            with open(wav + '.tune') as fh:
                got = fh.read().strip()
        if got == want:
            continue
        with open(wav + '.tune', 'w') as fh:
            fh.write(want)
        raw = wav.replace('.wav', '_raw.wav')
        if os.path.isfile(raw):
            with open(raw + '.take', 'w') as fh:
                fh.write(take)
        n += 1
        print(f'[run] restamped {fname}')
    print(f'[run] {n} marker(s) migrated to the current key format')


def _dur(p):
    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _span(p):
    d = sss._read_mono48k(p)
    a, b = sss._pick_island(d, sss._speech_islands(d), 'span')
    return (b - a) / 48000.0


def _grab(video, t, dst):
    subprocess.run(
        [exe('ffmpeg'), '-loglevel', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', dst], check=True
    )
    return np.asarray(Image.open(dst).convert('RGB'), dtype=np.float32)


def _seq(video, t0, dur, tmp, tag):
    subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-ss',
            str(t0),
            '-t',
            str(dur),
            '-i',
            video,
            '-vf',
            'fps=24',
            os.path.join(tmp, f'{tag}_%03d.png'),
        ],
        check=True,
    )
    fs = sorted(f for f in os.listdir(tmp) if f.startswith(tag + '_'))
    return [np.asarray(Image.open(os.path.join(tmp, f)).convert('L'), dtype=np.float32) for f in fs]
