# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bake the Medusa splash assets: one base picture + one alpha mask per snake.

    ~/TRELLIS.2/venv/bin/python3 bake_medusa_masks.py
        (any interpreter with numpy + opencv + pillow will do)

Writes medusa_base.jpg, snake_NN.png and snakes.js next to this file — the
files kanban_main.js's Medusa splash reads. Re-run only if the drawing changes.
The manifest is a .js assignment rather than JSON because kanban_server.py's
static allowlist deliberately refuses .json (source-leak guard), so the page
loads it with a <script> tag instead of fetching it.

Every line that reads the drawing or writes an asset lives in ``main()``:
importing this module must not touch the disk. It used to bake at import, and a
mere ``import`` rewrote the tracked snakes.js — which is how that file lost its
SPDX header on 2026-10-09.

How the snakes are found, and why this is not guesswork: the drawing is
greyscale line art in three bands — background 24-70, snake bodies and skin
above 95, outlines and scale texture below. So `L > 95` alone separates the
subject from the background cleanly, and inside the subject each snake body is
fenced off from its neighbours by its OWN dark outline, which means a plain
connected-component pass over that bright mask IS the snake-by-snake partition.
The face is never a region: skin is flood-filled from seed points first and cut
out before labelling.  Verified against dbg_regions.png, which this script
writes for exactly that purpose.
"""

import json
import math
import os

import cv2
import numpy as np
from PIL import Image

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

SRC = os.environ.get(
    'MDZ_SRC',
    os.path.expanduser('~/Documents/craiyon_142159_Black_and_white_drawing_of_Medusa_with_celtic_knot_snake_hair.png'),
)
OUT = os.environ.get('MDZ_OUT', os.path.dirname(os.path.abspath(__file__)))

# snakes.js is a tracked source file, so the bake has to re-emit its REUSE
# header; a baked file without one fails `reuse lint` and therefore scan.sh.
SNAKES_JS_HEADER = '// SPDX-FileCopyrightText: 2026 Zygomatic\n//\n// SPDX-License-Identifier: AGPL-3.0-or-later\n\n'

# ── skin: face, neck, shoulders, chest — the part that must never change colour ──
# Seeds are points in this picture, in pixels; a tight tolerance keeps the fill
# from walking out of the skin and into a snake.
SEEDS = [
    (440, 470),
    (380, 560),
    (500, 560),
    (440, 650),
    (440, 700),
    (440, 760),
    (300, 880),
    (150, 950),
    (700, 950),
    (440, 930),
]

MIN_AREA = 260  # px² below which a bright component is texture, not a snake

# ── tongues (2026-09-23, second pass) ────────────────────────────────────────
# The snakes curl on the board; their tongues flick. A tongue cannot be found
# the way a snake is: it is ink, not a bright region, it is the same stroke
# weight as every outline in the drawing, and at a fixed threshold it merges
# with the dark background into one component covering the whole picture
# (measured). So each tongue is SEEDED by hand — one point on the stroke, the
# same way the skin fill above is seeded — and grown from there:
#
#   * ink is local contrast, `blur(L) - L > 20`, not an absolute threshold, so
#     it works over the bright skin and the dark background alike (the thinnest
#     tongue in the drawing, the top-right one, is a ONE pixel diagonal chain
#     with a contrast of 35-55 — well clear of 20, but nowhere near solid);
#   * growth is capped at TONGUE_RAD px from the seed, which stops a tongue
#     from crawling off down a coil;
#   * everything within PROTECT px of a snake's bright core is dropped, which
#     is what keeps the jaw and the head outline out of the mask.
#
# PROTECT was 4 px in the first cut and that was the bug behind every tongue
# defect on the board. The bold outline around a head is 5-7 px thick, so at
# 4 px its OUTER fringe survived, the fringe is connected to the root of the
# tongue, and the component that comes back is therefore the tongue PLUS an arc
# of the head's own jaw. Consequences, all measured on the shipped assets:
#   * the anchor (nearest point of the mask to the body) landed on that arc
#     instead of the mouth — 33 px behind the lip on tongue 8 (the head over
#     her right shoulder), 25 px on tongue 4, 14 px on tongue 5 — so the tongue
#     slid out of the middle of the face and, retracting, slid back ACROSS it;
#   * `ang` is measured anchor→far end, so a wrong anchor tilted the axis too;
#   * the jaw arc was inpainted out of the plate as if it were tongue ink, and
#     the sprite that carries it is only drawn while the tongue is out, so for
#     most of every cycle those heads were missing a piece of their outline.
# At 7.5 px the arc is gone from all eight (checked one by one against the
# drawing) and what is left is the fork alone.
TONGUE_SEEDS = [  # (x, y) on the stroke, growth radius
    (420, 438, 44),
    (762, 786, 44),
    (54, 775, 44),
    (174, 830, 44),
    (786, 160, 44),
    (556, 634, 22),
    (596, 922, 44),
    (400, 886, 44),
]
PROTECT = 7.5  # px of head outline held back from the mask
ANCHOR_IN = 5.0  # px the anchor sits INSIDE the lip, so the clip line the
# page slides the sprite against is hidden under the drawn
# outline instead of cutting the tongue off in mid-air


if __name__ == '__main__':  # the bake is a script: importing this module runs nothing and writes nothing
    # Bake every Medusa splash asset into OUT (one straight-line pass; the steps are the banners below).
    os.makedirs(OUT, exist_ok=True)

    rgb = Image.open(SRC).convert('RGB')
    im = np.asarray(rgb.convert('L'))
    H, W = im.shape

    ff = np.zeros((H + 2, W + 2), np.uint8)
    for x, y in SEEDS:
        cv2.floodFill(im.copy(), ff, (x, y), 0, loDiff=6, upDiff=6, flags=8 | cv2.FLOODFILL_MASK_ONLY | (255 << 8))
    skin = (ff[1:-1, 1:-1] > 0).astype(np.uint8)
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    # Eyes, brows, lips and nostrils are darker than that tolerance, so they survive
    # as holes INSIDE the skin — and a hole left out of the skin becomes a region,
    # which is how the first bake gave Medusa purple lips. The skin fill also
    # reaches the dark gaps between the coils, so "enclosed by skin" cannot be the
    # whole test: a facial feature is ringed by BRIGHT skin (160-250), a snake that
    # happens to be enclosed is ringed by those gaps (40-70).
    hn, hl, hs, _ = cv2.connectedComponentsWithStats((1 - skin).astype(np.uint8), 4)
    for h in range(1, hn):
        if hs[h, 4] > 12000:
            continue
        hole = hl == h
        ring = (cv2.dilate(hole.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0) & ~hole
        if ring.any() and skin[ring].mean() > 0.9 and im[ring].mean() > 120:
            skin[hole] = 1

    # ── silhouette: the bright mask with its interior holes filled ───────────────
    bright = (im > 95).astype(np.uint8)
    inv = (1 - bright).astype(np.uint8)
    tmp, m2 = inv.copy(), np.zeros((H + 2, W + 2), np.uint8)
    for seed in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        cv2.floodFill(tmp, m2, seed, 2)
    sil = ((bright == 1) | ((inv == 1) & (tmp != 2))).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sil, 8)
    sil = np.zeros_like(sil)
    for i in range(1, n):
        if st[i, 4] >= 400:
            sil[lab == i] = 1

    # ── one component per snake ─────────────────────────────────────────────────
    # The skin is cut out BEFORE labelling: a snake lying across the chest shares no
    # outline with it, so without the cut the two fuse into a single component and
    # the snake would have to be dropped to keep the skin grey.
    skin_cut = cv2.dilate(skin, np.ones((3, 3), np.uint8))
    body = cv2.morphologyEx(
        (bright & sil & (1 - skin_cut)).astype(np.uint8),
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    body = cv2.morphologyEx(body, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(body, 8)

    keep = [i for i in range(1, n) if st[i, 4] >= MIN_AREA and float(skin[lab == i].mean()) <= 0.5]

    sel = np.zeros((H, W), np.int32)
    for new_id, i in enumerate(keep, start=1):
        sel[lab == i] = new_id

    # Grow each region 1 px at a time, inside the silhouette and never into skin, so
    # a snake takes its own outline with it instead of leaving a grey rim.
    paintable = (sil == 1) & (skin == 0)
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    for _ in range(7):
        free = (sel == 0) & paintable
        if not free.any():
            break
        d = cv2.dilate(sel.astype(np.float32), k3, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        sel = np.where(free & (d > 0), d.astype(np.int32), sel)

    # ── tongues: one sprite per hand-placed seed (TONGUE_SEEDS/PROTECT above) ────
    _loc = cv2.blur(im.astype(np.float32), (21, 21))
    # What must be protected is the SNAKE regions, not every bright pixel: half
    # these tongues are drawn across her forehead and shoulders, and guarding all
    # bright pixels guards her skin too, which erased three of them outright.
    _core = (sel > 0).astype(np.uint8)
    _d_core = cv2.distanceTransform((1 - _core).astype(np.uint8), cv2.DIST_L2, 3)
    _ink_full = ((_loc - im.astype(np.float32)) > 20).astype(np.uint8)
    _ink_all = np.zeros((H, W), np.uint8)
    _tongues = []
    _dbg = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    for sx, sy, rad in TONGUE_SEEDS:
        near = np.zeros((H, W), np.uint8)
        cv2.circle(near, (sx, sy), rad, 1, -1)
        ink = _ink_full & near
        ink[_d_core <= PROTECT] = 0
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        tn, tlab, tst, tcen = cv2.connectedComponentsWithStats(ink, 8)
        pick, pd = 0, 1e9
        for i in range(1, tn):
            if tst[i, 4] < 20:
                continue
            dd = (tcen[i][0] - sx) ** 2 + (tcen[i][1] - sy) ** 2
            if dd < pd:
                pd, pick = dd, i
        if not pick:
            _zyg_log.info(f'  tongue seed ({sx},{sy}): nothing found')
            continue
        m = (tlab == pick).astype(np.uint8)
        ys, xs = np.nonzero(m)

        # Which head this tongue belongs to: the region nearest the SEED, not the
        # nearest region to each pixel of the mask. Half of these tongues hang in
        # front of a coil that is closer to their free end than their own head is,
        # and the root has to be measured from the head that owns the mouth.
        ring = np.zeros((H, W), np.uint8)
        cv2.circle(ring, (sx, sy), 40, 1, -1)
        ids, cnt = np.unique(sel[(ring > 0) & (sel > 0)], return_counts=True)
        owner = 0
        if len(ids):
            best = 1e9
            for rid in ids:
                dmin = cv2.distanceTransform((sel != rid).astype(np.uint8), cv2.DIST_L2, 3)[sy, sx]
                if dmin < best:
                    best, owner = dmin, int(rid)
        d_own = _d_core if not owner else cv2.distanceTransform((sel != owner).astype(np.uint8), cv2.DIST_L2, 3)

        # The mouth end of the stroke is its point nearest the owning head; the axis
        # is the direction the stroke LEAVES the mouth on, averaged over the first
        # 22 px of it. Taking anchor→far end instead (the first cut) reads the
        # curl at the tip of a curved tongue as its direction of travel, so the
        # tongue slid out sideways through the jaw.
        dd = d_own[ys, xs]
        rx_, ry_ = int(xs[dd.argmin()]), int(ys[dd.argmin()])
        r2 = (xs - rx_) ** 2 + (ys - ry_) ** 2
        nearroot = (r2 >= 9) & (r2 <= 22 * 22)
        if nearroot.sum() < 6:
            nearroot = r2 >= 0
        vx = float((xs[nearroot] - rx_).mean())
        vy = float((ys[nearroot] - ry_).mean())
        vn = math.hypot(vx, vy) or 1.0
        vx, vy = vx / vn, vy / vn
        ax, ay = int(round(rx_ - vx * ANCHOR_IN)), int(round(ry_ - vy * ANCHOR_IN))
        x0, y0 = max(0, int(xs.min()) - 4), max(0, int(ys.min()) - 4)
        x1, y1 = min(W, int(xs.max()) + 5), min(H, int(ys.max()) + 5)
        _ink_all |= m
        _tongues.append(
            {
                'm': m,
                'rect': (x0, y0, x1, y1),
                'anchor': (ax, ay),
                'owner': owner,
                'root': (rx_, ry_),
                'ang': round(math.degrees(math.atan2(vy, vx)), 2),
            }
        )
        _dbg[m > 0] = (0, 0, 255)
        cv2.circle(_dbg, (ax, ay), 3, (0, 255, 0), -1)
        cv2.line(_dbg, (ax, ay), (int(ax + vx * 40), int(ay + vy * 40)), (255, 200, 0), 1)

    # A region has to carry its own INK, or it leaves its outline behind when it
    # moves and the board looks like it is melting: measured on the first cut, only
    # 37 % of the mane's outline and scale ink was inside a cut-out, so two thirds
    # of the linework stayed in the plate while the bodies swayed. Seven rounds
    # inside `sil` cannot reach it — the rim around the outside of the mane lies a
    # few px OUTSIDE the silhouette, and a gap wider than 14 px is never closed from
    # both sides. So: grow again, further, and a little way past the silhouette.
    # Tongues are held back from it, because they are animated separately and must
    # not be absorbed into the body that carries them.
    # Only INK and body, never flat ground: a region that is allowed to grow into
    # the empty dark inside a coil drags that patch of background around with it,
    # and the plate blurs it as if it were part of the mane. Ink is local contrast,
    # the same measure the tongues use.
    _lo = cv2.blur(im.astype(np.float32), (21, 21))
    _is_ink = (_lo - im.astype(np.float32)) > 20
    paintable2 = (
        (cv2.dilate(sil, np.ones((9, 9), np.uint8)) == 1)
        & (skin == 0)
        & (_is_ink | (bright == 1))
        & (cv2.dilate(_ink_all, np.ones((5, 5), np.uint8)) == 0)
    )
    for _ in range(13):
        free = (sel == 0) & paintable2
        if not free.any():
            break
        d = cv2.dilate(sel.astype(np.float32), k3, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        sel = np.where(free & (d > 0), d.astype(np.int32), sel)

    # ── emit: one cropped alpha mask per snake + a manifest in 0..1 coordinates ──
    manifest = []
    rid2idx = {}  # region id -> index into `manifest`, for the tongues below
    for rid in range(1, len(keep) + 1):
        reg = sel == rid
        ys, xs = np.nonzero(reg)
        if len(xs) == 0:
            continue
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        a = cv2.GaussianBlur((reg[y0:y1, x0:x1] * 255).astype(np.uint8), (3, 3), 0)
        rgba = np.zeros((a.shape[0], a.shape[1], 4), np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = a
        name = f'snake_{rid:02d}.png'
        Image.fromarray(rgba).save(os.path.join(OUT, name), optimize=True)
        rid2idx[rid] = len(manifest)
        manifest.append(
            {
                'f': name,
                'x': round(x0 / W, 5),
                'y': round(y0 / H, 5),
                'w': round((x1 - x0) / W, 5),
                'h': round((y1 - y0) / H, 5),
                'a': int(reg.sum()),
            }
        )

    # One inpaint for all of them: Telea over a 2 px dilation of the ink.
    _clean = cv2.inpaint(
        cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR),
        cv2.dilate(_ink_all, np.ones((3, 3), np.uint8)),
        4,
        cv2.INPAINT_TELEA,
    )
    tongue_manifest = []
    for ti, t in enumerate(_tongues, 1):
        x0, y0, x1, y1 = t['rect']
        m = t['m'][y0:y1, x0:x1]
        alpha = np.clip((_loc - im.astype(np.float32))[y0:y1, x0:x1] / 34.0, 0, 1) * m
        spr = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
        spr[..., :3] = np.asarray(rgb)[y0:y1, x0:x1]
        spr[..., 3] = (alpha * 255).astype(np.uint8)
        fs, fp = f'tongue_{ti:02d}.png', f'tpatch_{ti:02d}.png'
        Image.fromarray(spr).save(os.path.join(OUT, fs), optimize=True)
        Image.fromarray(cv2.cvtColor(_clean[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)).save(
            os.path.join(OUT, fp), optimize=True
        )
        (ax, ay) = t['anchor']
        tongue_manifest.append(
            {
                'f': fs,
                'p': fp,
                'x': round(x0 / W, 5),
                'y': round(y0 / H, 5),
                'w': round((x1 - x0) / W, 5),
                'h': round((y1 - y0) / H, 5),
                'ax': round(ax / W, 5),
                'ay': round(ay / H, 5),
                'ang': t['ang'],
                # The head this tongue belongs to, baked rather than
                # guessed at draw time: the page used to take the
                # snake whose BOX was nearest the anchor, and in a
                # mane this dense that is routinely a coil passing
                # in front of the head, so a tongue rode the wrong
                # body's sway.
                'o': rid2idx.get(t['owner'], -1),
            }
        )
    cv2.imwrite(os.path.join(OUT, 'dbg_tongues.png'), _dbg)

    rgb.save(os.path.join(OUT, 'medusa_base.jpg'), quality=90, optimize=True, progressive=True)
    with open(os.path.join(OUT, 'snakes.js'), 'w', encoding='utf-8') as fh:
        fh.write(SNAKES_JS_HEADER)
        fh.write('/* Baked by bake_medusa_masks.py — do not edit by hand. */\nwindow.MDZ_SNAKES = ')
        json.dump({'w': W, 'h': H, 'snakes': manifest, 'tongues': tongue_manifest}, fh, indent=0)
        fh.write(';\n')

    # ── loop_alpha.png: which pixels the rendered loop is allowed to paint ───────
    # The board's mane can also be a VIDEO (Wan2.2 I2V; see README_loop.md), and a
    # video model re-draws whatever it is given — including her face. So the loop is
    # composited back over this drawing through this alpha, and everything the alpha
    # zeroes is the drawing itself, unchanged, for ever. Three regions are zero:
    #
    #   * her FACE CORE, an ellipse over brows/eyes/nose/lips/chin, which nothing may
    #     ever paint over — not even a snake that wanders across it;
    #   * her body: the skin fill, eroded to drop the thin slivers it leaks into
    #     between the coils, and then punched through wherever a snake cut-out lies
    #     ON her skin PLUS 24 px of room, because those heads have to be free to move
    #     or the composite clips them at the outline they had at rest;
    #   * everything more than ~45 px outside the silhouette — the flat dark paper,
    #     where nothing should ever happen and model drift would be plainly visible.
    #
    # The mane itself, the gaps between the coils and the tongues are all 1: a snake
    # must be able to move INTO the gap beside it, and masking to the cut-outs at
    # rest would clip every motion and leave the still drawing of the same snake
    # showing behind it.
    _body = cv2.erode(skin, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    _n, _lab, _st, _ = cv2.connectedComponentsWithStats(_body, 8)
    _keep = np.zeros_like(_body)
    for _i in range(1, _n):
        if _st[_i, 4] >= 18000:  # her body; the slivers are small
            _keep[_lab == _i] = 1
    _lock = cv2.morphologyEx(
        cv2.dilate(_keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))) & skin,
        cv2.MORPH_CLOSE,
        np.ones((15, 15), np.uint8),
    )
    _lock[cv2.dilate((sel > 0).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49))) > 0] = 0
    _lock = cv2.erode(_lock, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    _core = np.zeros((H, W), np.uint8)  # measured off the drawing:
    cv2.ellipse(_core, (442, 565), (129, 142), 0, 0, 360, 1, -1)  # brows 431 .. chin 737
    _area = cv2.dilate(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (91, 91)))
    _raw = ((_area > 0) & (_lock == 0) & (_core == 0)).astype(np.float32)
    _alpha = np.clip(
        cv2.GaussianBlur(_raw, (0, 0), 5.0) * (1.0 - cv2.GaussianBlur(_core.astype(np.float32), (0, 0), 4.0)), 0, 1
    )
    Image.fromarray((_alpha * 255).astype(np.uint8)).save(os.path.join(OUT, 'loop_alpha.png'), optimize=True)

    rng = np.random.default_rng(11)
    cols = np.vstack([[0, 0, 0], rng.integers(50, 255, size=(len(manifest), 3))]).astype(np.uint8)
    vis = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    vis = np.where((sel > 0)[..., None], (0.45 * vis + 0.55 * cols[sel]).astype(np.uint8), vis)
    cv2.imwrite(os.path.join(OUT, 'dbg_regions.png'), vis)

    _zyg_log.info(f"loop_alpha: {100 * (_alpha > 0.5).mean():.1f} % of the frame is the video's")
    _zyg_log.info(f'{len(tongue_manifest)} tongues')
    _zyg_log.info(
        f'{len(manifest)} snakes · masks '
        f'{round(sum(os.path.getsize(os.path.join(OUT, m["f"])) for m in manifest) / 1024)} KB · '
        f'base {round(os.path.getsize(os.path.join(OUT, "medusa_base.jpg")) / 1024)} KB'
    )
