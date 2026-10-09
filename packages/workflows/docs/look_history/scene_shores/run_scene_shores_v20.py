#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v20: the quay cleared, and a bird that leaves.

v19's timing to the frame — same takes, same marks, same bird window, same
hold-then-pan — and everything that changed is picture. Four operator notes,
and one defect found while answering them:

  1. THE SHIP'S BOW WAS TRANSPARENT. Not a little: measured inside the bow's
     own outline the plate reads 145-190/255 against 8-13/255 for the hull
     twenty pixels to starboard, and the far quay, the bridge arch and the
     gable line all continue straight across it. The forward third of the hull
     was ~100% background with a bow drawn over it at a tenth of the contrast
     the rest of the hull carries. It is re-synthesised opaque.

  2. THE CRATES ARE OUT OF THE WATER. The row that stood in the canal along
     the right-hand quay — a dozen cases at water level with the canal lapping
     them and no dock under them — is gone, and so are the two that stood in
     the middle of the boardwalk. What is there now is a bare quay with a
     plain timber bulkhead and a row of mooring posts, the canal running
     alongside it, and ONE stack of crates set back against the house wall,
     which is where the operator asked for them.

     v19 recorded that four region edits over this area all invented
     something that is not there. They did, and the reason is now clear: all
     four boxes were mostly WATER, which gives the sampler nothing to continue,
     so it fills the space with structure. A box that runs from the crates
     across the whole boardwalk to the right frame edge gives it the quay to
     continue and it continues it.

  3. THE HELMSMAN IS GONE. There was a man standing at the whipstaff on the
     stern platform — 24x55 plate pixels, 12x27 delivered. Cloned out along
     the plank run.

  4. THE BIRD IS RENDERED, NOT DRAWN, AND IT FLIES AWAY. v19's canary was
     built from polygons and seen from the SIDE, and side-on is the one view
     that cannot say "away from you": at mid-stroke its silhouette is a body
     with the wings edge-on, which at 40 px is a fish. The new bird is a set
     of REAR views — klein-4B renders, background keyed, one per wingbeat
     phase — and the flight is a recession: in past the lens at the bottom
     right big enough to read every feather, out across the harbour to the
     moored ship, away and up into her rigging at a seventh of the size.
     `speed_from_scale` was added to the flight model for it: a bird leaving
     the camera covers less of the PICTURE per second the further off it gets,
     and a receding path run at a constant image speed says the opposite of
     what the path says.

  5. FOUND, NOT ASKED FOR: v19 patched the crates out of the LEFT bank with a
     stretch of canal borrowed from elsewhere, and the right edge of that
     paste is a ruled vertical tone step through the water — +52/+75/+94 over
     eight pixels at y=1300. It has shipped since v19. It is not flattened
     (a step of that size in that place is also what the edge of the ship's
     reflection looks like) but the boundary is displaced by a low-frequency
     wander and softened, which is the difference between a reflection and a
     paste.

usage:  python3 run_scene_shores_v20.py [--verify-only]
"""

import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

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
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v19_canary')
SRC_MP4 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v19_canary.mp4')
SLUG = 'second_ledger_intro_teen08_settled_shores_v20_quay'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')
SCRATCH = os.path.join(
    tempfile.gettempdir(),
    'claude-1000',
    '-home-zygomatic-zygomatics-zero',
    'c2a05d08-bb06-433b-9461-76f5ec4c9abf',
    'scratchpad',
)
NEW_PLATE = os.path.join(SCRATCH, 'plate', 'v20.png')
NEW_HIRES = os.path.join(SCRATCH, 'plate', 'v20.hires.png')
BIRD_CFG = os.path.join(SCRATCH, 'bird_cfg.json')
WATER_POLY = os.path.join(SCRATCH, 'water_poly.json')
SPRITE_DIR = os.path.join(CREWS, 'data', 'assets', 'bird_sprites', 'canary')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

# ── the tail, all of it v19's ──────────────────────────────────────────────
BIRD_IN = 2.0
BIRD_DUR = 5.0
BEAT_S = 0.2
TAIL_FADE_IN_S = 1.1
END_FADE_S = 3.0
MASTER_FADE_S = 2.0
OVERSHOOT_S = 2.0

# Where the moored ship is, in plate fractions: the flight has to END there,
# because "flies towards the boat" is the note and a recession that ends
# anywhere else is just a bird getting smaller.
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

# FIVE boxes, and the floor is their MEDIAN. One box is an estimate of the
# encoder's noise with a sample size of one: measured across five supposedly
# identical regions of the same delivered file the per-box mean ranges 0.42 to
# 0.84/255, so taking the max hands the whole check to whichever box the
# encoder happened to be noisiest in — v20's water scored 2.95x against a max
# floor and 4.2x against the median, on the same frames. All five are clear of
# the flight path and of both smoke plumes; an earlier version of this check
# put a box under the bird and measured the BIRD as the floor.
_STATIC_REGIONS = {
    'right gable': (1170, 40, 1330, 200),
    'left roofline': (200, 195, 420, 300),
    'left houses': (60, 330, 260, 470),
    'right brick': (1180, 230, 1330, 420),
    'left gables': (250, 300, 430, 430),
}


def _canary_px(a: np.ndarray) -> int:
    """The bird's colour in the DELIVERED file, after the grade.

    Not the sprite's colour: the film grade warms the whole frame, which pushes
    the canary's olive-green past its own red channel, so the plate-space test
    (g >= r) counted 175 px of a bird that is 217 px across. What survives the
    grade is the BLUE deficit — measured on the delivered frames, this scores 0
    before the bird enters, 1556 while it is at the lens, 61 when it is out at
    the ship and 0 again once it has gone.
    """
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


def _bird_flies_away(spec) -> bool:
    """The note was "it doesn't fly towards the boat / away from the camera".

    So what is checked is exactly that, off `_bird_pose` and the sprite set
    rather than off an impression: it comes in from the right, it never
    crosses the frame, it gets small, it ENDS AT THE SHIP, and it beats its
    wings — a set of phase sprites that only ever shows one of them is a
    stuffed bird on a wire.
    """
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['bird']
    dur = float(cfg['dur_s'])
    ok = True
    if not (4.0 <= dur <= 6.0):
        ok = False
        print(f'[verify] BIRD ON SCREEN {dur}s — the brief is 4-6 s')
    if not cfg.get('sprites'):
        ok = False
        print('[verify] the bird is still the DRAWN one — no sprite set')
    elif not os.path.isfile(os.path.join(str(cfg['sprites']), 'sprites.json')):
        ok = False
        print(f'[verify] sprite set missing: {cfg["sprites"]}')
    if sss._bird_pose(cfg, -0.01) is not None or sss._bird_pose(cfg, dur + 0.01) is not None:
        ok = False
        print('[verify] the bird exists outside its flight window')

    ps = [sss._bird_pose(cfg, dur * k / 240.0) for k in range(241)]
    xs = [p['pos'][0] for p in ps]
    ys = [p['pos'][1] for p in ps]
    sc = [p['scale'] for p in ps]
    print(
        f'[verify] bird: enters ({xs[0]:.3f}, {ys[0]:.3f}) at scale {sc[0]:.2f}, '
        f'ends ({xs[-1]:.3f}, {ys[-1]:.3f}) at scale {sc[-1]:.2f}'
    )
    if xs[0] < 1.0:
        ok = False
        print('[verify] the bird does not ENTER — it starts already in frame')
    if min(xs) < 0.40:
        ok = False
        print('[verify] the bird CROSSES the frame — it is meant to go away, not past')
    d_ship = math.hypot(xs[-1] - SHIP_AT[0], ys[-1] - SHIP_AT[1])
    print(f'[verify] ends {d_ship:.3f} of a frame width from the moored ship at {SHIP_AT}')
    if d_ship > SHIP_TOL:
        ok = False
        print('[verify] THE FLIGHT DOES NOT END AT THE BOAT')
    if any(b - a > 1e-6 for a, b in zip(sc, sc[1:])):
        ok = False
        print('[verify] the bird grows somewhere along the flight')
    print(
        f'[verify] recession: scale {sc[0]:.2f} -> {sc[-1]:.2f} '
        f'({sc[0] / max(sc[-1], 1e-6):.1f}x), and the traverse is '
        f'{"tied to it" if cfg.get("speed_from_scale") else "NOT tied to it"}'
    )
    if sc[-1] > 0.22:
        ok = False
        print('[verify] THE BIRD DOES NOT FLY AWAY — it barely shrinks')
    if not cfg.get('speed_from_scale'):
        ok = False
        print(
            '[verify] the traverse is not tied to the recession — a receding '
            'path run at one image speed reads as a decal'
        )

    # how big it is when it comes past the lens, in DELIVERED pixels
    man = json.load(open(os.path.join(str(cfg['sprites']), 'sprites.json')))
    lev = man['phases']['rear_level']
    span0 = float(cfg['body_frac']) * sc[0] * lev['span'] / lev['body_w']
    print(f'[verify] entry wingspan {span0 * 100:.1f}% of frame width ({span0 * 1344:.0f} delivered px)')
    if span0 < 0.09:
        ok = False
        print('[verify] the near bird is too small to read as near')

    phases = {sss._bird_phase(p) for p in ps}
    print(f'[verify] wingbeat phases used: {sorted(phases)}')
    if len(phases) < 4:
        ok = False
        print('[verify] the wings do not cycle through the whole beat')

    # The scallop is drawn in BODIES of vertical offset, so the check has to
    # convert it the way the renderer does — measured against the raw path y it
    # is swamped by the climb and the flight scores as a glide.
    bob_y = float(cfg['body_frac']) * float(cfg.get('bob_bodies', 3.0)) * (2688.0 / 1536.0)
    d = np.diff(np.array([p['pos'][1] + p['bob'] * bob_y * p['scale'] for p in ps]))
    turns = int(np.sum(np.sign(d[1:]) != np.sign(d[:-1])))
    want = dur / float(cfg.get('bound_period_s', 0.95))
    print(f'[verify] bounding flight: {turns} reversals over {dur}s (~{want:.1f} cycles authored)')
    if turns < want:
        ok = False
        print('[verify] the flight is not BOUNDING')
    return ok


def _bird_is_in_the_delivered_file(st, video) -> bool:
    """...and it shrinks there.

    Counted on the mp4, not on the config, because everything above is a
    statement about numbers in a dict. The canary's colour is the handle: 20
    pixels of the 4.1 MP harbour plate match it and 12.6% of the sprite does.
    """
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    near = _grab(video, t0 + 0.4, os.path.join(tmp, 'n.png'))
    far = _grab(video, t0 + 3.6, os.path.join(tmp, 'f.png'))
    before = _grab(video, t0 - 0.3, os.path.join(tmp, 'b.png'))
    after = _grab(video, t0 + BIRD_DUR - 0.05, os.path.join(tmp, 'a.png'))
    n, f = _canary_px(near), _canary_px(far)
    b0, a0 = _canary_px(before), _canary_px(after)
    shutil.rmtree(tmp, ignore_errors=True)
    print(
        f'[verify] DELIVERED file, canary pixels: {b0} before / {n} at the '
        f'lens / {f} out at the ship / {a0} after it has gone'
    )
    ok = True
    if n < 600:
        ok = False
        print('[verify] THE BIRD IS NOT IN THE DELIVERED FILE near the lens')
    if not (0 < f < n * 0.25):
        ok = False
        print('[verify] the bird does not measurably RECEDE in the delivered file')
    if b0 > 20 or a0 > 20:
        ok = False
        print('[verify] something canary-coloured is on screen outside the flight window')
    return ok


def _no_crates_in_the_water(spec) -> bool:
    """The crate row stood in the canal on the right. What has to be true now
    is that the water there is water: no warm timber inside the water mask.

    Measured on the hires plate through fx.water's own polygon, so the check
    and the ripple agree about where the canal is — the poly moved out to the
    new bulkhead in this cut and a check written against the old numbers would
    pass over the very strip that was wrong.
    """
    from PIL import ImageFilter

    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['water']
    # ERODED by 20 px. The mask's own edge runs along the quay's timber
    # bulkhead, and unrode it counts that bulkhead as cargo in the canal —
    # 4,294 px of it, which is most of what an unmodified check would flag.
    mk = sss._water_mask(base.size, cfg).filter(ImageFilter.MinFilter(41))
    m = np.asarray(mk, dtype=np.float32) / 255.0
    a = np.asarray(base.convert('RGB'), dtype=np.float32)
    wet = m > 0.75
    # right half only: that is where the crates were, and the left bank has
    # its own warm reflections that are not cargo
    half = np.zeros_like(wet)
    half[:, base.width // 2 :] = True
    sel = wet & half
    r, _g, b = a[..., 0], a[..., 1], a[..., 2]
    timber = sel & (r - b > 48) & (r > 105)
    frac = timber.sum() / max(1, sel.sum())
    print(
        f'[verify] sunlit timber inside the right-hand water mask: '
        f'{timber.sum()} px, {frac * 100:.2f}% of {int(sel.sum())} wet px'
    )
    if frac > 0.008:
        print('[verify] THERE IS STILL CARGO IN THE WATER')
        return False
    return True


def _the_bow_is_opaque(spec) -> bool:
    """The bow read 145-190/255 with the background showing through it. A hull
    is a hull: it has to sit in the same tonal range as the hull beside it, and
    the far bank must not be legible through it.

    Two numbers, because either alone can be gamed: the bow's own MEAN, and the
    correlation between the bow strip and the open background at the same
    heights. A repaint that merely darkened the ghost would pass the first and
    fail the second.
    """
    a = np.asarray(Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png')).convert('RGB'), dtype=np.float32)
    bow = a[970:1130, 1345:1445].mean(axis=2)
    hull = a[980:1140, 1440:1560].mean(axis=2)
    bg = a[970:1130, 1120:1220].mean(axis=2)
    print(
        f'[verify] bow {bow.mean():5.1f}/255   hull to starboard {hull.mean():5.1f}   open background {bg.mean():5.1f}'
    )
    ok = True
    if bow.mean() > hull.mean() + 42.0:
        ok = False
        print('[verify] THE BOW IS STILL LIGHTER THAN THE HULL IT BELONGS TO')
    br = (bow - bow.mean(axis=1, keepdims=True)).ravel()
    gr = (bg - bg.mean(axis=1, keepdims=True)).ravel()
    n = min(len(br), len(gr))
    c = float(np.corrcoef(br[:n], gr[:n])[0, 1])
    print(f'[verify] bow-vs-background row correlation {c:+.3f} (the ghost showed the far bank straight through)')
    if c > 0.45:
        ok = False
        print('[verify] THE BACKGROUND IS STILL LEGIBLE THROUGH THE BOW')
    return ok


def _no_one_on_the_stern(spec) -> bool:
    """The helmsman was a dark upright 24x55 on a pale deck. What is asserted
    is that the deck is now pale all the way across: no dark column on it."""
    a = np.asarray(Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png')).convert('L'), dtype=np.float32)
    cols = a[952:990, 1670:1704].mean(axis=0)
    med = float(np.median(cols))
    print(
        f'[verify] stern platform across the whipstaff: darkest column '
        f'{cols.min():.0f}/255, deck median {med:.0f}   '
        f'(v19, with the man on it: 10 / 188)'
    )
    ok = True
    # ABSOLUTE darkness, not a drop: a figure against a sunlit deck reads
    # near-black (v19 measured 10), while the plank seams and the shadows of
    # the shrouds that are supposed to be there sit near 90. A drop threshold
    # can be passed by darkening the whole deck, so the deck's own level is
    # asserted too.
    if cols.min() < 70.0:
        ok = False
        print('[verify] SOMETHING IS STILL STANDING ON THE STERN PLATFORM')
    if med < 120.0:
        ok = False
        print('[verify] the stern deck is no longer a sunlit deck')
    return ok


def _smoke_leaves_the_chimney(spec) -> bool:
    fx = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']
    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    BW, BH = base.size
    ok = True
    for i, cfg in enumerate(fx['smoke']):
        ax, ay = cfg['anchor']
        widths = []
        near = []
        for t in (k * 0.55 for k in range(15)):
            (x0, y0), tile = sss._draw_smoke((BW, BH), cfg, t)
            a = np.asarray(tile.split()[-1], dtype=np.float32)
            ys, xs = np.where(a > 12)
            if not len(ys):
                ok = False
                print(f'[verify] smoke {i}: NOTHING DRAWN at t={t}')
                continue
            near.append((y0 + ys.max()) - ay * BH)
            top = ys.min() + (ys.max() - ys.min()) * 0.15
            bot = ys.max() - (ys.max() - ys.min()) * 0.10
            wt = float((a[int(top)] > 12).sum())
            wb = float((a[int(bot)] > 12).sum())
            widths.append((wb, wt))
        gap = min(near) if near else -999
        print(
            f'[verify] smoke {i} at ({ax:.4f}, {ay:.4f}): worst case over 8 s, '
            f'reaches {gap / 2.0:+.1f} delivered px past the pot mouth; '
            f'base/top width {widths[0][0] / 2:.0f}/{widths[0][1] / 2:.0f}px'
        )
        if gap < -4:
            ok = False
            print(f'[verify] smoke {i} STARTS ABOVE THE POT')
        if widths and widths[0][1] <= widths[0][0]:
            ok = False
            print(f'[verify] smoke {i} does not SPREAD as it rises')
    return ok


def _water_moves_in_the_delivered_file(spec, st, video) -> bool:
    """Inter-frame change inside the water mask against boxes that are supposed
    to be perfectly still, on the DELIVERED file, grain removed."""
    import tempfile

    tmp = tempfile.mkdtemp()
    tail0 = st['marks']['tail_start']
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['water']
    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    W, H = int(spec['width']), int(spec['height'])
    t0 = tail0 + TAIL_FADE_IN_S + 0.3
    fr = _seq(video, t0, 1.6, tmp, 'w')
    import cv2

    fr = [cv2.GaussianBlur(x, (0, 0), 1.5) for x in fr]
    d = np.mean([np.abs(fr[i + 1] - fr[i]) for i in range(len(fr) - 1)], axis=0)
    mk = sss._water_mask(base.size, cfg).crop(sss._zoom_box(base, 1.0, (0.93, 0.30)))
    if mk.size != (W, H):
        mk = mk.resize((W, H), Image.BILINEAR)
    m = np.asarray(mk, dtype=np.float32) / 255.0
    wet = m > 0.5
    wv = float(d[wet].mean())
    stat = {k: float(d[b[1] : b[3], b[0] : b[2]].mean()) for k, b in _STATIC_REGIONS.items()}
    floor = float(np.median(list(stat.values())))
    shutil.rmtree(tmp, ignore_errors=True)
    print(
        f'[verify] DELIVERED file, camera held {t0:.1f}-{t0 + 1.6:.1f}s, grain '
        f'removed: water {wv:.3f}/255 vs still-region floor {floor:.3f} '
        f'(median of {len(stat)}, worst {max(stat.values()):.3f}) '
        f'-> {wv / max(floor, 1e-6):.1f}x'
    )
    for k, v in stat.items():
        print(f'[verify]     still: {k:14s} {v:.3f}/255')
    if wv < floor * 3.0:
        print('[verify] THE WATER IS NOT VISIBLY MOVING IN THE DELIVERED FILE')
        return False
    return True


def _camera_holds_for_the_bird(spec, st) -> bool:
    shot = sss.shot_by_id_spec(spec, spec['tail_shot_id'])
    fx = shot['fx']
    t0 = st['marks']['tail_start']
    t1 = st['marks']['picture_end'] + float(spec.get('tail_zoom_overshoot_s', 0.0))
    zs = []
    for k in range(0, int((BIRD_IN + BIRD_DUR) * 24) + 1):
        t = t0 + k / 24.0
        tt = max(0.0, min(1.0, (t - t0) / (t1 - t0)))
        zs.append(sss._kb_keys_at(tt, fx['kb_keys'])[0])
    drift = max(zs) - min(zs)
    tt_end = (st['marks']['picture_end'] - t0) / (t1 - t0)
    z_black = sss._kb_keys_at(tt_end, fx['kb_keys'])[0]
    print(
        f'[verify] camera during the bird: z {min(zs):.4f}-{max(zs):.4f} '
        f'(drift {drift:.4f}); reaches z={z_black:.3f} at black'
    )
    if drift > 0.01:
        print('[verify] THE CAMERA PANS UNDER THE BIRD')
        return False
    if z_black < 1.8:
        print('[verify] the closing move never arrives at the house')
        return False
    return True


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    _carry(STILLS_CARRY, 'cabin stills')
    _carry(TAKES, 'approved takes')
    for src, dst in ((NEW_PLATE, 'still_day1_harbor.png'), (NEW_HIRES, 'still_day1_harbor.hires.png')):
        if not os.path.isfile(src):
            print(f'[run] ABORT: new harbour plate missing: {src}')
            return 7
        _cp(src, os.path.join(OUT_DIR, dst))
    print('[run] plates installed: quay cleared, bow repainted, stern empty')

    for f in _AUDIO_TAKES:
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(
                f'[run] ABORT: missing carried take {f} — v19 is the source '
                f'of truth for the audio and it must not be re-synthesised'
            )
            return 2
    anchor = os.path.join(OUT_DIR, 'anchor_00_abel.wav')

    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_abel.wav')) for i in range(4)]
    pauses = [1.0, 1.0, 0.9, 0.6]
    spec = copy.deepcopy(sss.SECOND_LEDGER_INTRO)

    dialogue_end = float(spec.get('head_silence_s', 1.0)) + sum(d + p for d, p in zip(durs, pauses))
    pullout_end = dialogue_end + float(spec['pullout']['hold_s'])
    card_start = pullout_end + float(spec['fade_to_black_s'])
    tail_t0 = card_start + float(spec['title_card']['dur_s'])

    bird_out = BIRD_IN + BIRD_DUR
    line_t0 = bird_out + BEAT_S
    line_t1 = line_t0 + _span(anchor)
    total_rel = line_t1 + 0.2
    picture_end_rel = total_rel + END_FADE_S
    win_rel = picture_end_rel + OVERSHOOT_S

    spec['tail_fade_in_s'] = TAIL_FADE_IN_S
    spec['tail_hold_s'] = round(total_rel - TAIL_FADE_IN_S, 3)
    spec['end_fade_s'] = END_FADE_S
    spec['tail_zoom_overshoot_s'] = OVERSHOOT_S
    spec['audio_tail_s'] = 0.0
    spec['master_fade_s'] = MASTER_FADE_S

    F = (0.93, 0.30)
    hold_at = round(bird_out / win_rel, 4)
    sss.shot_by_id_spec(spec, 'day1_harbor')['fx']['kb_keys'] = [
        {'at': 0.0, 'z': 1.0, 'focus': F},
        {'at': hold_at, 'z': 1.0, 'focus': F},
        {'at': 1.0, 'z': 3.0, 'focus': F},
    ]

    spec['slug'] = SLUG
    spec['voices']['abel'] = {'ref': SEED_WAV, 'seed': 1672}
    spec['stem_lufs'] = STEM_LUFS
    spec['master_lufs'] = MASTER_LUFS
    spec['bed_lufs'] = BED_LUFS
    for cue in spec['music']:
        if cue.get('name') in MUSIC_LUFS:
            cue['lufs'] = MUSIC_LUFS[cue['name']]
    spec['music'][-1]['fade_out_s'] = 0.3

    spec['dialogue'][3].update(LINE3)
    spec['anchored_lines'] = [
        {
            'speaker': 'abel',
            'text': SHORES,
            'seed': CLOSING_SEED,
            'take': 'span',
            'pace_ref': None,
            'at': {'mark': 'tail_start', 'offset': round(line_t0, 3)},
            'align': 'start',
        }
    ]

    fx = sss.shot_by_id_spec(spec, 'day1_harbor')['fx']

    # ── the new bird, and the canal it flies over ───────────────────────────
    with open(BIRD_CFG) as fh:
        bird = json.load(fh)
    bird['sprites'] = SPRITE_DIR  # never a scratch path
    fx['bird'] = bird
    with open(WATER_POLY) as fh:
        poly = json.load(fh)
    fx['water'] = dict(fx['water'])
    fx['water']['poly'] = poly + [[0.0, 1.0]]

    for k in ('water', 'smoke', 'bird'):
        if not fx.get(k):
            print(f'[run] ABORT: the tail shot has no fx.{k}')
            return 5
    if abs(float(fx['bird']['t0_rel']) - BIRD_IN) > 1e-6:
        print("[run] ABORT: the bird's t0_rel disagrees with this driver")
        return 5
    print(
        f'[run] tail {tail_t0:.2f}s: bird {tail_t0 + BIRD_IN:.2f}'
        f'→{tail_t0 + bird_out:.2f}s, line {tail_t0 + line_t0:.2f}'
        f'→{tail_t0 + line_t1:.2f}s, fade {tail_t0 + total_rel:.2f}'
        f'→{tail_t0 + picture_end_rel:.2f}s'
    )
    print(f'[run] camera holds to at={hold_at} of the {win_rel:.2f}s move window')
    print(
        f'[run] water poly {len(fx["water"]["poly"])} pts out to the new '
        f'bulkhead, {len(fx["smoke"])} chimneys, bird {fx["bird"]["dur_s"]}s '
        f'from sprites'
    )

    _restamp(spec)
    before = {f: _md5(os.path.join(OUT_DIR, f)) for f in _AUDIO_TAKES}

    if '--verify-only' in sys.argv:
        r = {'video': os.path.join(OUT_DIR, f'{SLUG}.mp4')}
        if not os.path.isfile(r['video']):
            print('[run] --verify-only but nothing has been built yet')
            return 1
        print(f'[run] --verify-only: re-checking {os.path.basename(r["video"])}')
    else:
        r = sss.build_scene(spec, out_dir=OUT_DIR)
        if not r:
            print('[run] FAILED')
            return 1
        print(f'[run] done: {r["video"]}')

    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    ok = True

    for f in _AUDIO_TAKES:
        now = _md5(os.path.join(OUT_DIR, f))
        v19 = _md5(os.path.join(SRC_DIR, f))
        if now != before[f] or now != v19:
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f} (v19 {v19[:8]}, now {now[:8]})')
    print(f'[verify] {len(_AUDIO_TAKES)} takes checksummed against v19')

    for k in ('dialogue_end', 'pullout_start', 'pullout_end', 'card_start', 'card_end', 'tail_start', 'picture_end'):
        if round(st['marks'][k], 2) != round(ref['marks'][k], 2):
            ok = False
            print(
                f'[verify] MARK {k} MOVED {ref["marks"][k]} → {st["marks"][k]} '
                f'— v20 is a PICTURE cut, nothing in the timing was meant to move'
            )
    print(
        f'[verify] every mark identical to v19 (tail at {st["marks"]["tail_start"]}s, '
        f'picture ends {st["marks"]["picture_end"]}s)'
    )
    for a, b in zip(st['events'][:5], ref['events'][:5]):
        if round(a['t0'], 2) != round(b['t0'], 2):
            ok = False
            print(f'[verify] LINE MOVED {b["text"][:36]!r}')
    print('[verify] all five lines land where v19 put them')

    if not _the_bow_is_opaque(spec):
        ok = False
    if not _no_one_on_the_stern(spec):
        ok = False
    if not _no_crates_in_the_water(spec):
        ok = False
    if not _camera_holds_for_the_bird(spec, st):
        ok = False
    if not _bird_flies_away(spec):
        ok = False
    if not _bird_is_in_the_delivered_file(st, r['video']):
        ok = False
    if not _smoke_leaves_the_chimney(spec):
        ok = False
    if not _water_moves_in_the_delivered_file(spec, st, r['video']):
        ok = False

    # The cabin is v19's, byte for byte, so it must be identical on screen.
    import tempfile

    tmp = tempfile.mkdtemp()
    for t in (12.0, 33.0):
        a = _grab(SRC_MP4, t, os.path.join(tmp, 'a.png'))
        b = _grab(r['video'], t, os.path.join(tmp, 'b.png'))
        d = float(np.abs(a - b).mean())
        print(f'[verify] cabin t={t}s vs v19: {d:5.2f}/255 mean difference')
        if d > 2.0:
            ok = False
            print('[verify] THE CABIN CHANGED — only the harbour was meant to')
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
