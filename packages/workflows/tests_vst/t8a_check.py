#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T8A — Video Studio spec + post-chain proof (CPU only, no GPU, no ComfyUI).

Two halves:

1. THE SPEC.  video_studio compiles, every new AUDIO / OVERLAY / SHOTS /
   upscale key is in defaults(), interp_mode offers 'rife', the eight NOT
   BUILT cells that were built are gone while the five character-control ones
   are untouched, and RACKS still serialises to JSON (the /video/api/spec
   route hands it to the browser verbatim).

2. THE POST CHAIN.  _post_process is run for real over a synthetic 3 s clip
   with an overlay record and an audio cue, and the RESULT is measured: the
   red disc is actually red at (0.25W, 0.5H) at t=2.0, the file has an audio
   stream, and the last frame is dark because the fade-out ran.  None of that
   touches the GPU — the upscale and RIFE legs are the two that do, and they
   are exercised by their own module's selftest, not here.

Run from $ZYG_CREWS_ROOT with the crews venv:
    "$ZYG_SERVER_PYTHON" tests_vst/t8a_check.py
"""

import json
import os
import py_compile
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)

FFMPEG = 'ffmpeg'


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, timeout=300)
    assert p.returncode == 0, f'{cmd[0]} failed: {p.stderr.decode(errors="replace")[-900:]}'
    return p


# ── 1. the spec ───────────────────────────────────────────────────────────
py_compile.compile(os.path.join(CREWS, 'video_studio.py'), doraise=True)
print('py_compile video_studio.py: ok')

from zyg_workflows import video_studio as vs  # noqa: E402

d = vs.defaults()
NEW = [
    'upscale',
    'audio_bed',
    'audio_bed_path',
    'audio_bed_gain',
    'audio_bed_fade_in',
    'audio_cues',
    'audio_target_lufs',
    'audio_fade_out',
    'overlay_record',
    'overlay_draft',
    'shot_list',
    'shot_xfade',
    'link_prompts',
]
missing = [k for k in NEW if k not in d]
assert not missing, f'defaults() is missing {missing}'
print(f'defaults(): {len(d)} params, all {len(NEW)} new keys present')

modes = [o['v'] for o in vs._PARAMS['interp_mode']['options']]
assert 'rife' in modes, f'interp_mode has no rife option: {modes}'
print(f'interp_mode options: {modes}')

RETIRED = [
    'nb_audio_bed',
    'nb_audio_sfx',
    'nb_audio_duck',
    'nb_loudness',
    'nb_upscale',
    'nb_ai_interp',
    'nb_matte',
    'nb_timeline',
]
KEPT = ['nb_vace', 'nb_pose', 'nb_depth', 'nb_face_restore', 'nb_prompt_extend']
still = [k for k in RETIRED if k in d]
assert not still, f'NOT BUILT cells that should be gone: {still}'
lost = [k for k in KEPT if k not in d]
assert not lost, f'NOT BUILT cells that must stay were removed: {lost}'
print(f'NOT BUILT: {len(RETIRED)} retired, {len(KEPT)} kept')

spec_json = json.dumps(vs.RACKS)
assert json.dumps(vs.ACTIONS)
rack_ids = [r['id'] for r in vs.RACKS]
for rid in ('audio', 'overlay', 'shots'):
    assert rid in rack_ids, f'rack {rid} missing'
assert (
    rack_ids.index('post')
    < rack_ids.index('audio')
    < rack_ids.index('overlay')
    < rack_ids.index('shots')
    < rack_ids.index('output')
), f'rack order is wrong: {rack_ids}'
assert 'assemble' in [a['id'] for a in vs.ACTIONS], 'no assemble action'
assert callable(vs.start_assemble), 'start_assemble is not callable'
print(f'RACKS serialises ({len(spec_json)} bytes), order {rack_ids}')
print(f'bed options: {len(vs._PARAMS["audio_bed"]["options"])} (off + library beds)')

# ── 2. the post chain, for real ───────────────────────────────────────────
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

tmp = tempfile.mkdtemp(prefix='t8a_')

clip = os.path.join(tmp, 'clip.mp4')
run(
    [
        FFMPEG,
        '-hide_banner',
        '-v',
        'error',
        '-y',
        '-f',
        'lavfi',
        '-i',
        'testsrc2=s=640x360:r=24:d=3',
        '-c:v',
        'libx264',
        '-crf',
        '12',
        '-pix_fmt',
        'yuv420p',
        clip,
    ]
)

# RGBA red disc, as in video_overlay's own selftest
edir = os.path.join(tmp, 'disc')
os.makedirs(edir)
yy, xx = np.mgrid[0:200, 0:200]
rgba = np.zeros((200, 200, 4), dtype=np.uint8)
rgba[..., 0] = 255
rgba[..., 3] = np.where(((xx - 100) ** 2 + (yy - 100) ** 2) <= 90**2, 255, 0)
for n in range(1, 13):
    Image.fromarray(rgba, 'RGBA').save(os.path.join(edir, 'f_%04d.png' % n))

sine = os.path.join(tmp, 'sine.wav')
run(
    [
        FFMPEG,
        '-hide_banner',
        '-v',
        'error',
        '-y',
        '-f',
        'lavfi',
        '-i',
        'sine=frequency=440:duration=0.3',
        '-ac',
        '1',
        '-ar',
        '48000',
        sine,
    ]
)

p = vs.sanitize(
    {
        'overlay_record': json.dumps(
            {'layers': [{'element': edir, 'x': 0.25, 'y': 0.6, 'height': 0.2, 'start_s': 1.0, 'end_s': 2.5, 'fps': 24}]}
        ),
        'audio_cues': json.dumps([{'file': sine, 'at_s': 1.0}]),
        'fade_out': 0.5,
    }
)
assert json.loads(p['overlay_record'])['layers'], 'sanitize dropped the record'
assert json.loads(p['audio_cues']), 'sanitize dropped the cues'

print('--- _post_process ---')
vs._post_process(clip, p, print)
print('--- /_post_process ---')

# audio stream present?
pr = run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,duration', '-of', 'json', clip])
streams = json.loads(pr.stdout.decode())['streams']
kinds = [s['codec_type'] for s in streams]
assert 'audio' in kinds, f'no audio stream after the audio leg: {streams}'
print(f'streams: {[(s["codec_type"], s["codec_name"]) for s in streams]}')


def _png(png, seek):
    run([FFMPEG, '-hide_banner', '-v', 'error', '-y'] + seek + ['-i', clip, '-frames:v', '1', png])
    return np.asarray(Image.open(png).convert('RGB'))


def frame_at(t):
    return _png(os.path.join(tmp, f'f_{t:.2f}.png'), ['-ss', f'{t:.3f}'])


fr = frame_at(2.0)
H, W = fr.shape[:2]
px, py = int(0.25 * W), int(0.5 * H)  # bottom-center anchor: y-h/2 = 0.5H
r, g, b = (int(v) for v in fr[py, px])
assert r > 180 and g < 90 and b < 90, f'overlay disc not red at ({px},{py}) t=2.0 — got ({r},{g},{b})'
print(f'overlay: pixel({px},{py}) @ t=2.0 = ({r},{g},{b}) — red')

# -sseof, not a wall-clock seek: the muxed file's video stream is a frame or
# two short of the nominal 3.0 s and an absolute -ss past the end decodes
# nothing at all.
last = _png(os.path.join(tmp, 'f_last.png'), ['-sseof', '-0.05'])
mean = float(last.mean())
assert mean < 24.0, f'last frame is not dark (mean {mean:.1f}) — fade-out missing'
print(f'fade out: last frame mean luma {mean:.1f} (< 24)')

print('T8A OK')
