#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v17: the canal in the closing shot is WATER.

A COPY of the delivered v16 cut with exactly one change, and it is a PICTURE
change: the harbour the scene ends on is a painted mirror, and every ripple in
it is frozen paint.  It is the last image of the episode, held for five seconds
while the score resolves, so a dead canal is precisely the thing the eye settles
on.  The audio master is v16's — same takes, same marks, same levels, same cues,
the mix bit-for-bit — so the only difference between the two files is the thing
that was asked for.  The candle from v16 is untouched and re-verified here.

WHAT MOVES, AND WHY IT IS NOT AN OVERLAY.  `fx.water` (see `_water_apply`)
warps the plate itself, exactly as `fx.flame` warps the candle and for the same
reason: paint does not move, so a brightness cycle over a painted reflection is
a lamp on a dimmer.  The reflections that rise, stretch and slide here are the
PAINTED ones, remapped by a travelling surface, so the motion arrives in the
illustration's own style and there is no drawn water to mismatch it.

The thing that makes it read as water rather than as a corrugated sheet is the
perspective.  Depth under a flat plane goes as 1/(v − horizon), and the waves
are authored in WORLD wavelength, so one train projects to crests 144 px apart
at the bottom of frame, 52 px at three-quarter height and 16 px near the far
bank, all travelling toward the viewer at one world speed.  Each train is then
switched off wherever it has compressed past `min_px`, because by the far bank
the projection genuinely puts a crest every 5 px — the long swell therefore
runs further up the canal than the chop does, which is what a canal does.

Measured on the delivered frames with the CAMERA FROZEN — the tail is a zoom,
and with the move running every pixel changes, so the water cannot be told from
the camera (a first cut of this check measured the two as identical and duly
reported no water at all).  Temporal std over 2 s:

    water, bottom quarter of frame      18.6 /255
    water, rows 620-690                 12.9 /255
    water, rows 560-620                  6.0 /255
    water, near the far bank             1.0 /255
    EVERYTHING OUTSIDE THE MASK          0.00008/255
    near/far motion ratio                3.1 x
    high-frequency detail kept in the water   100 %

i.e. the canal moves, in perspective, the ship and both quays do not move with
it, and the motion is not paid for in detail.

WHY THIS IS A NEW DIRECTORY.  v16 is the delivered cut and it is also the
reference this driver verifies its own copy against — the marks, the cue levels
and the take checksums all come out of v16's own files.  Re-rendering over it
would destroy the only thing this driver can check itself against.

The rendered TAKES are not re-synthesised: the TTS cache is per-output-dir, so
the approved wavs + their `.tune`/`.take` markers are carried across first and
build_scene reuses them.  That also makes the timeline reproduce exactly, since
every mark is derived from the audio's own length.  The music is cached globally
(data/asset_libraries/soundtracks/*.mp3), so nothing is re-generated and no GPU
is touched by this run.

usage:  python3 run_scene_shores_water.py [--verify-only]
"""

import logging as _zyg_logging
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
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v16_flame')
SRC_MP4 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v16_flame.mp4')
SLUG = 'second_ledger_intro_teen08_settled_shores_v17_water'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

# ── v14/v16's levels, measured off the delivered files ──────────────────────
STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

FADE_LEAD_S = 0.0
END_FADE_S = 3.0
MASTER_FADE_S = 2.0

STILLS = (
    'still_cabin_abel.png',
    'still_cabin_abel.png.wlock_c3345deb',
    'still_cabin_abel.hires.png',
    'still_cabin_abel.hires.png.handfix',
    'still_day1_harbor.png',
    'still_day1_harbor.hires.png',
)
TAKES = tuple(f'line_{i:02d}_abel{s}' for i in range(4) for s in ('.wav', '.wav.tune', '_raw.wav', '_raw.wav.take')) + (
    'anchor_00_abel.wav',
    'anchor_00_abel.wav.tune',
)

_AUDIO_TAKES = tuple(f'line_{i:02d}_abel.wav' for i in range(4)) + ('anchor_00_abel.wav',)

# Delivered-pixel regions of the TAIL that must not move, checked at z ≈ 1.
# They are the three things a warp that leaked would spoil first: the sky the
# masts are drawn against, the canal houses on the left bank, and the loaded
# quay in the bottom-right corner.
_DRY_REGIONS = {
    'sky + masts': (560, 60, 940, 380),
    'left houses': (60, 240, 420, 440),
    'right quay': (1000, 600, 1320, 750),
}
# The cabin, at a moment the flame is mid-gutter: this cut must reproduce v16
# there exactly, because nothing about the cabin changed.
_CABIN_REGION = (150, 120, 1060, 620)


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _cp(s, d):
    if os.path.isfile(s) and not os.path.isfile(d):
        shutil.copyfile(s, d)
        return 1
    return 0


def _carry(names, label):
    n = sum(_cp(os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)) for f in names)
    _zyg_log.info(f'[run] carried {n} new / {len(names)} {label}')


def _restamp(spec):
    """Re-write the carried `.tune`/`.take` markers in the CURRENT key format.

    A no-op while v16's markers are current — which is the point of running it:
    a marker that has gone stale is answered by build_scene the only way it can
    be, by re-synthesising the line, and these takes were picked off benches
    rather than rendered from the spec. Silence there means shipping different
    audio under a picture-only change.
    """
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
        _zyg_log.info(f'[run] restamped {fname}')
    _zyg_log.info(f'[run] {n} marker(s) migrated to the current key format')


def _dur(p):
    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _span(p):
    d = sss._read_mono48k(p)
    a, b = sss._pick_island(d, sss._speech_islands(d), 'span')
    return (b - a) / 48000.0


def _lufs(path):
    r = subprocess.run(
        [exe('ffmpeg'), '-nostdin', '-i', path, '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True
    )
    hit = [ln for ln in r.stderr.splitlines() if ln.strip().startswith('I:')]
    return float(hit[-1].split()[1]) if hit else float('nan')


def _grab(video, t, dst):
    subprocess.run(
        [exe('ffmpeg'), '-loglevel', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', dst], check=True
    )
    return np.asarray(Image.open(dst).convert('RGB'), dtype=np.float32)


def _tail_cam(spec, st, t):
    """(z, focus) of the tail move at t — the service's own camera, read the
    same way `_shot_frame` reads it, so a verification region derived from it
    cannot drift away from the picture."""
    shot = sss.shot_by_id_spec(spec, spec['tail_shot_id'])
    fx = shot.get('fx', {})
    t0 = st['marks']['tail_start']
    t1 = st['marks']['picture_end'] + float(spec.get('tail_zoom_overshoot_s', 0.0))
    tt = max(0.0, min(1.0, (t - t0) / max(1e-6, t1 - t0)))
    z = sss._kb_zoom_at(tt, fx.get('kenburns', 'push_in'), float(fx.get('kb_amount', 0.06)), fx.get('kb_zoom'))
    return z, tuple(fx['focus_xy'])


def _water_is_local(spec):
    """Prove, on the RENDERED frame and before any codec touches it, that the
    canal moves and that nothing else in the picture does.

    The camera is FROZEN for this. The tail is a pull-in, and with the move
    running every pixel in the frame changes between two instants — the water
    is then indistinguishable from the zoom, and a first cut of this check duly
    reported a perfectly good effect as no effect at all. Holding the camera
    still leaves exactly one thing that can differ between two frames.

    What is asserted is the SPLIT: temporal variance inside the water mask, and
    temporal variance outside it, which for a warp that stays where it belongs
    has to be zero rather than merely small.
    """
    shot = sss.shot_by_id_spec(spec, spec['tail_shot_id'])
    cfg = shot.get('fx', {}).get('water')
    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png')).convert('RGB')
    W, H = int(spec['width']), int(spec['height'])
    t0 = 37.5
    z, focus = 1.0, tuple(shot['fx']['focus_xy'])
    box = sss._zoom_box(base, z, focus)

    def render(t, with_water):
        img = sss._zoom_frame(base, W, H, z, focus)
        if with_water:
            img = sss._water_apply(img, cfg, box, base.size, z, t)
        return np.asarray(img, dtype=np.float32).mean(axis=2)

    ts = [t0 + k / 24.0 for k in range(49)]  # 2 s
    sd = np.stack([render(t, True) for t in ts]).std(axis=0)
    mk = sss._water_mask(base.size, cfg).crop(box)
    if mk.size != (W, H):
        mk = mk.resize((W, H), Image.BILINEAR)
    m = np.asarray(mk, dtype=np.float32) / 255.0
    wet, dry = m > 0.5, m <= 0.0
    ok = True
    _zyg_log.info(
        f'[verify] pre-encode, camera frozen, 2 s: water std '
        f'{sd[wet].mean():.3f}/255 over {wet.sum()} px, '
        f'outside the mask {sd[dry].max():.5f}/255 over {dry.sum()} px'
    )
    for y0, y1, label in (
        (690, 768, 'bottom quarter'),
        (620, 690, 'rows 620-690'),
        (560, 620, 'rows 560-620'),
        (480, 560, 'far bank'),
    ):
        band = np.zeros_like(m, dtype=bool)
        band[y0:y1] = True
        sel = band & wet
        if sel.sum():
            _zyg_log.info(f'[verify]   {label:15s} std {sd[sel].mean():6.3f}/255')
    if sd[wet].mean() < 4.0:
        ok = False
        _zyg_log.info('[verify] THE WATER DID NOT LAND — the canal is barely moving')
    if sd[dry].max() > 0.01:
        ok = False
        _zyg_log.info('[verify] THE WARP LEAKED OUTSIDE ITS MASK')
    # the perspective is the effect: near water has to move more than far water
    near = np.zeros_like(m, dtype=bool)
    near[690:768] = True
    far = np.zeros_like(m, dtype=bool)
    far[560:620] = True
    n, f = sd[near & wet].mean(), sd[far & wet].mean()
    _zyg_log.info(f'[verify] perspective: near/far motion ratio {n / max(f, 1e-6):.2f}x')
    if n < f * 1.8:
        ok = False
        _zyg_log.info(
            '[verify] NO PERSPECTIVE — the far canal moves as much as the near '
            'canal, which is a corrugated sheet, not water'
        )
    # and it must not be paid for in detail
    import cv2

    plate = render(t0, False)
    warped = render(t0, True)

    def hf(a):
        return float(np.abs(a - cv2.GaussianBlur(a, (0, 0), 1.2))[wet].mean())

    keep = hf(warped) / max(hf(plate), 1e-6)
    _zyg_log.info(f'[verify] high-frequency detail kept in the water: {keep * 100:.1f}%')
    if keep < 0.90:
        ok = False
        _zyg_log.info('[verify] THE WARP IS SOFTENING THE PLATE — motion bought with detail')
    return ok


def _flame_is_local(spec):
    """v16's check, kept verbatim in spirit: the candle still moves, and only
    the candle. It is re-run here because this cut no longer compares its mp4
    against v14 — nothing else in this driver would notice if the flame had
    silently stopped."""
    from PIL import ImageEnhance, ImageFilter
    from zyg_workflows.pipeline_effects import _draw_particles

    shot = sss.shot_by_id_spec(spec, 'cabin_abel')
    fx = shot['fx']
    flame = fx['flame']
    W, H = int(spec['width']), int(spec['height'])
    base = Image.open(os.path.join(OUT_DIR, 'still_cabin_abel.hires.png')).convert('RGB')
    t_abs, z, focus = 33.0, 1.0, tuple(fx['focus_xy'])

    def render(with_flame):
        rng = np.random.RandomState(99)
        img = sss._zoom_frame(base, W, H, z, focus)
        img = ImageEnhance.Brightness(img).enhance(sss._flicker_factor(t_abs, float(fx.get('flicker', 0.0))))
        if with_flame:
            b = sss._zoom_box(base, z, focus)
            bw, bh = base.size
            sx = (flame['anchor'][0] * bw - b[0]) / (b[2] - b[0]) * W
            sy = (flame['anchor'][1] * bh - b[1]) / (b[3] - b[1]) * H
            img = sss._flame_apply(img, flame, sx, sy, z, t_abs)
        ov = _draw_particles(W, H, fx['particles'], (t_abs * 0.10) % 1.0, seed=42).filter(ImageFilter.GaussianBlur(0.8))
        ai = np.asarray(img, dtype=np.float32)
        ao = np.asarray(ov, dtype=np.float32) * float(fx.get('particle_gain', 0.5))
        img = Image.fromarray(np.clip(255 - (255 - ai) * (255 - ao) / 255, 0, 255).astype(np.uint8))
        return np.asarray(
            sss._grade(
                img,
                warm=float(fx.get('warm', 0.6)),
                vignette=float(fx.get('vignette', 0.28)),
                grain=float(fx.get('grain', 5.0)),
                rng=rng,
            ),
            dtype=np.float32,
        )

    d = np.abs(render(False) - render(True)).mean(axis=2)
    nz = np.where(d > 0.5)
    if not len(nz[0]):
        _zyg_log.info('[verify] THE FLAME DID NOT LAND — it changes no pixel at all')
        return False
    bx0, bx1, by0, by1 = nz[1].min(), nz[1].max(), nz[0].min(), nz[0].max()
    sx, halo_r, pad = 250.0, float(flame['halo_r_frac']) * W * z, 3.0
    up = float(flame['h_frac']) * H * z * float(flame.get('warp_span', 2.2))
    lim = (
        math.floor(sx - halo_r - pad),
        math.ceil(sx + halo_r + pad),
        math.floor(508 - max(halo_r, up) - pad),
        math.ceil(508 + halo_r + pad),
    )
    _zyg_log.info(
        f'[verify] pre-encode: flame changes x {bx0}-{bx1}, y {by0}-{by1} '
        f'(tile allows x {lim[0]:.0f}-{lim[1]:.0f}, y {lim[2]:.0f}-{lim[3]:.0f})'
    )
    ok = True
    if bx0 < lim[0] or bx1 > lim[1] or by0 < lim[2] or by1 > lim[3]:
        ok = False
        _zyg_log.info('[verify] THE FLAME LEAKED OUTSIDE ITS TILE')
    if float(d[400:600, 150:350].mean()) < 0.5:
        ok = False
        _zyg_log.info('[verify] THE FLAME DID NOT LAND — the candle barely moved')
    for k, (x0, y0, x1, y1) in (('abel face', (880, 150, 1060, 320)), ('far bulkhead', (600, 120, 800, 320))):
        m = float(d[y0:y1, x0:x1].mean())
        if m != 0.0:
            ok = False
            _zyg_log.info(f'[verify] {k} MOVED — the flame is not staying local ({m:.4f})')
    return ok


def _picture_delta(spec, st, new_video):
    """Confirm on the DELIVERED file that the water reached the mp4, that it
    reached only the canal, and that the rest of the cut is still v16.

    Absolute thresholds are meaningless against an mp4: at CRF 18 changing any
    pixel re-allocates bits across the whole frame, so two files differ by a
    couple of levels EVERYWHERE. What is measured is each region against that
    frame's own encode floor.
    """
    if not os.path.isfile(SRC_MP4):
        _zyg_log.info('[verify] SKIP delivered-file delta — v16 mp4 missing')
        return True
    import tempfile

    tmp = tempfile.mkdtemp()
    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['water']
    W, H = int(spec['width']), int(spec['height'])
    ok = True

    # ── the tail: the canal has to be the busiest thing in the frame ────────
    for t in (37.9, 38.5, 39.2):
        a = _grab(SRC_MP4, t, os.path.join(tmp, 'a.png'))
        b = _grab(new_video, t, os.path.join(tmp, 'b.png'))
        if a.shape != b.shape:
            _zyg_log.info(f'[verify] FRAME SIZE CHANGED {a.shape} → {b.shape}')
            return False
        d = np.abs(a - b).mean(axis=2)
        floor = float(d.mean())
        z, focus = _tail_cam(spec, st, t)
        box = sss._zoom_box(base, z, focus)
        mk = sss._water_mask(base.size, cfg).crop(box)
        if mk.size != (W, H):
            mk = mk.resize((W, H), Image.BILINEAR)
        m = np.asarray(mk, dtype=np.float32) / 255.0
        wet = m > 0.5
        wv = float(d[wet].mean()) if wet.sum() else 0.0
        _zyg_log.info(
            f'[verify] t={t}s (z={z:.3f}) encode floor {floor:.2f}/255 — '
            f'canal {wv:.2f} ({wv / max(floor, 1e-6):.2f}x floor, {wet.sum()} px)'
        )
        if wv < floor * 1.6:
            ok = False
            _zyg_log.info('[verify] THE WATER DID NOT REACH THE MP4 — the canal is no busier than the encode floor')
        for k, (x0, y0, x1, y1) in _DRY_REGIONS.items():
            v = float(d[y0:y1, x0:x1].mean())
            flag = ''
            if v > floor * 1.6:
                ok = False
                flag = '   ← STANDS ABOVE THE FLOOR, check for a leak'
            _zyg_log.info(f'[verify]     {k:12s} {v:5.2f}/255 ({v / max(floor, 1e-6):.2f}x floor){flag}')

    # ── the cabin: this cut changed nothing there, and must prove it ────────
    for t in (12.0, 33.0):
        a = _grab(SRC_MP4, t, os.path.join(tmp, 'a.png'))
        b = _grab(new_video, t, os.path.join(tmp, 'b.png'))
        d = np.abs(a - b).mean(axis=2)
        x0, y0, x1, y1 = _CABIN_REGION
        v = float(d[y0:y1, x0:x1].mean())
        _zyg_log.info(f'[verify] cabin at t={t}s: mean |Δ| vs v16 {v:.3f}/255 (frame-wide {d.mean():.3f})')
        if v > 0.5:
            ok = False
            _zyg_log.info('[verify] THE CABIN CHANGED — this was meant to be a tail-only edit')
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == '__main__':  # the CLI lives in run_scene_shores_water_cli
    from zyg_workflows.run_scene_shores_water_cli import main as _cli_main

    raise SystemExit(_cli_main())
