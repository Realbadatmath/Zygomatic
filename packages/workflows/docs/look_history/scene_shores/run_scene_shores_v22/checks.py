# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_scene_shores_v22.checks — the remaining delivered-file checks: crates, bow, stern, smoke,
water, camera hold
(verbatim from run_scene_shores_v22.py lines 721-919).
"""

# ruff: noqa: F401
# The original top import block is repeated here for the moved code; the
# side-effecting part of it (sys.path insert + chdir) lives in constants.py
# alone and still runs exactly once, first.
import copy
import json
import math
import os
import shutil
import subprocess
import sys

import soundfile as sf

import numpy as np
from PIL import Image
from zyg_workflows import paths
from zyg_workflows import storyteller_scene_service as sss
from zyg_workflows.bin import exe
from zyg_workflows.run_scene_shores_v22.constants import (
    BIRD_DUR,
    BIRD_IN,
    OUT_DIR,
    TAIL_FADE_IN_S,
    _STATIC_REGIONS,
    _seq,
)


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
