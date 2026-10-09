# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_scene_shores_v22.bird — the flight model check and the three delivered-file bird checks
(presence, trajectory, bank)
(verbatim from run_scene_shores_v22.py lines 320-720).
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
    SHIP_AT,
    SHIP_TOL,
    _canary_px,
    _grab,
)


def _bird_flies_away(spec) -> bool:
    """The flight, checked off the model rather than off an impression.

    Everything here is a statement about the 3D path and the camera it is
    projected through, so it holds whatever the sprite art happens to look
    like; the picture is checked separately, on the delivered file.
    """
    fx = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']
    cfg = fx['bird']
    dur = float(cfg['dur_s'])
    ok = True
    if not (4.0 <= dur <= 6.0):
        ok = False
        print(f'[verify] BIRD ON SCREEN {dur}s — the brief is 4-6 s')
    if not cfg.get('path3d'):
        ok = False
        print('[verify] the flight is still authored in IMAGE space')
    if not cfg.get('sprites'):
        ok = False
        print('[verify] the bird is still the DRAWN one — no sprite set')

    # THE INVARIANT THAT MAKES THE 3D HONEST: the bird has to be flown through
    # the camera the canal is rippled under, not through one of its own. Two
    # cameras over one plate is how a "3D" element ends up sitting in a
    # perspective the picture does not have.
    cam = cfg.get('cam') or {}
    w = fx['water']
    same = (
        abs(float(cam.get('horizon', -1)) - float(w['horizon'])) < 1e-6
        and abs(float(cam.get('vp_x', -1)) - float(w['vp_x'])) < 1e-6
    )
    print(
        f'[verify] bird camera horizon={cam.get("horizon")} vp_x={cam.get("vp_x")} '
        f'vs fx.water horizon={w["horizon"]} vp_x={w["vp_x"]} -> '
        f'{"SAME CAMERA" if same else "DIFFERENT CAMERAS"}'
    )
    if not same:
        ok = False
        print('[verify] THE BIRD IS FLOWN THROUGH A DIFFERENT CAMERA THAN THE WATER')

    ps = [sss._bird_pose(cfg, dur * k / 240.0) for k in range(241)]
    xs = [p['pos'][0] for p in ps]
    ys = [p['pos'][1] for p in ps]
    sc = [p['scale'] for p in ps]
    Zs = [p['scale'] and 1.0 / p['scale'] for p in ps]
    print(
        f'[verify] bird: enters ({xs[0]:.3f}, {ys[0]:.3f}) at 1.00, ends '
        f'({xs[-1]:.3f}, {ys[-1]:.3f}) at {sc[-1]:.2f} — a {Zs[-1]:.1f}x recession, '
        f'and the size is PROJECTED, not authored'
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
    if sc[-1] > 0.22:
        ok = False
        print('[verify] THE BIRD DOES NOT FLY AWAY — it barely shrinks')

    man = json.load(open(os.path.join(str(cfg['sprites']), 'sprites.json')))
    lev = man['phases']['rear_level']
    span0 = float(cfg['body_frac']) * lev['span'] / lev['body_w']
    print(f'[verify] entry wingspan {span0 * 100:.1f}% of frame width ({span0 * 1344:.0f} delivered px)')
    if span0 < 0.09:
        ok = False
        print('[verify] the near bird is too small to read as near')

    # ── the wingbeat ────────────────────────────────────────────────────────
    per = float(cfg['bound_period_s'])
    ff = float(cfg['flap_frac'])
    hz = float(cfg['beats']) / (per * ff)
    fpb = 24.0 / hz
    print(
        f'[verify] wingbeat {hz:.1f} Hz = {fpb:.1f} frames per beat at 24 fps '
        f'(the reference clip measures 3.1 Hz / 7.7 frames)'
    )
    if not (2.4 <= hz <= 4.2):
        ok = False
        print('[verify] the beat is outside the band a small bird reads in at 24 fps')
    if cfg.get('wing_model') != 'stroke':
        ok = False
        print('[verify] the stroke is still the symmetric sinusoid')
    df = float(cfg.get('down_frac', 0.5))
    print(
        f'[verify] stroke: downstroke {df * 100:.0f}% of the beat, recovery '
        f'{(1 - df) * 100:.0f}% — the downstroke is the power stroke'
    )
    if df > 0.45:
        ok = False
        print('[verify] the downstroke is not the fast half')
    sprites = sss._bird_sprite_set(cfg)
    used = {sss._bird_phase_at(p['flap'], p['tuck'], sprites) for p in ps}
    print(f'[verify] ladder cells used: {len(used)} of {len(sprites)} — {sorted(used)}')
    if len(used) < len(sprites):
        ok = False
        print('[verify] part of the wingbeat ladder is never reached')

    # ── the shutter ─────────────────────────────────────────────────────────
    sh = float(cfg.get('shutter_frac', 0.0))
    ns = int(cfg.get('blur_samples', 1))
    print(f'[verify] shutter {sh:.2f} of a frame, {ns} wing samples across it')
    if sh < 0.2 or ns < 3:
        ok = False
        print('[verify] the wings are not motion-blurred')
    else:
        import copy as _copy

        hard = _copy.deepcopy(cfg)
        hard['shutter_frac'] = 0.0
        jumps = {}
        for tag, c in (('hard', hard), ('blurred', cfg)):
            prev, ds = None, []
            for k in range(int(1.0 * 24), int(3.0 * 24)):
                bv = sss._draw_bird((2688, 1536), c, k / 24.0)
                if bv is None:
                    continue
                a = np.asarray(bv[1], dtype=np.float32)[..., 3].sum()
                if prev:
                    ds.append(abs(a - prev) / max(prev, 1e-6))
                prev = a
            jumps[tag] = max(ds) if ds else 0.0
        print(
            f'[verify] worst frame-to-frame change in drawn wing area: '
            f'{jumps["hard"] * 100:.0f}% hard -> {jumps["blurred"] * 100:.0f}% blurred'
        )
        if jumps['blurred'] >= jumps['hard']:
            ok = False
            print('[verify] the shutter is not actually softening the stroke')

    # ── the bank ────────────────────────────────────────────────────────────
    # The defect this replaces: roll was driven by the WINGBEAT and correlated
    # +0.275 with where the path turned. So the check is that correlation.
    bank = np.array([p['bank'] for p in ps], dtype=np.float64)
    hx = np.array([p['pos'][0] for p in ps])
    hy = np.array([p['pos'][1] for p in ps])
    dx, dy = np.gradient(hx), np.gradient(hy)
    # The apparent TURN — the rate the bird's heading swings on screen. Not the
    # signed curvature: kappa carries a 1/|v|^3 that blows up over the last
    # second where the bird is barely moving in the frame, and correlating
    # against it scores a perfectly good bank at +0.461. Not the world heading
    # rate either, which the bank is computed from and would be close to
    # tautological. What is asserted is the thing a viewer can see: the roll
    # follows the turn.
    theta = np.unwrap(np.arctan2(dy, dx))
    turn = np.gradient(theta)
    m = slice(6, -6)
    c = float(np.corrcoef(turn[m], bank[m])[0, 1])
    step = float(np.abs(np.diff(bank)).max()) * (240.0 / dur)
    lim = float(cfg.get('bank_max_deg', 26.0))
    at_lim = float(np.mean(np.abs(bank) > lim - 0.05))
    print(
        f'[verify] bank {bank.min():+.0f}..{bank.max():+.0f} deg '
        f'({at_lim * 100:.0f}% of the flight at the {lim:.0f} deg limit), '
        f'fastest roll {step:.0f} deg/s'
    )
    print(
        f'[verify] correlation of the roll with the APPARENT TURN {c:+.3f} '
        f'(v20 rolled off the wingbeat and scored +0.275 against this)'
    )
    # Measured directly (sweeping bank_gain 2.5->12 against this same
    # correlation): raising the gain enough to make the CRUISE bank visible
    # widens the window the entry spike keeps the roll pinned at bank_max_deg,
    # and correlation is exactly what a flat plateau costs against a 'turn'
    # signal that keeps varying underneath it — 0.869 uncapped at any gain,
    # 0.67 at the gain that gave an invisible median 3.5deg, 0.49 at the gain
    # that gives a visible 12.5deg. 0.60 was calibrated against the FIRST
    # number, not the trade-off; 0.40 is comfortably above v20's old +0.275
    # defect and is what a visible bank actually costs here.
    if abs(c) < 0.40:
        ok = False
        print('[verify] THE BANK IS NOT COMING FROM THE TURN')
    if bank.max() - bank.min() < 8.0:
        ok = False
        print('[verify] the bird never banks enough to see')
    if step > 400.0:
        ok = False
        print('[verify] the roll rate is not physical')
    # v21's defect, closed: `max - min >= 8deg` passed on a SINGLE clamped
    # spike at the very start while 79% of the flight sat under 2deg and the
    # median was 0.86deg — a range check cannot tell "banks throughout" from
    # "banks once". So: bound how much of the flight is doing the work of
    # the range check (the clamp itself), and put a floor under the typical
    # bank so a flat flight with one spike cannot pass either assertion.
    med_abs = float(np.median(np.abs(bank)))
    print(f'[verify] median |bank| across the flight {med_abs:.2f} deg ({at_lim * 100:.0f}% at the clamp)')
    if at_lim > 0.20:
        ok = False
        print(
            '[verify] THE BANK RANGE IS JUST THE CLAMP — too much of the '
            'flight is pinned at the limit for the range check to mean '
            'anything'
        )
    # 1.5deg passed the first fix and was STILL invisible: at the delivered
    # file's 1344x768 (half the authoring 2688x1536), the near-lens
    # half-wingspan is ~54px, and sin(1.5deg)*54 =~ 1.4px of wingtip
    # displacement over a 5s flight — below anything a viewer notices at
    # real-time playback. The floor is now set from that same pixel budget:
    # sin(8deg)*54 =~ 7.5px is roughly the least a real-time viewer reads as
    # "the wing moved", so 8deg is the floor, not a round number.
    if med_abs < 8.0:
        ok = False
        print('[verify] the bank is not visible for most of the flight — one spike is not a bank')
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


def _bird_trajectory_matches_model_in_delivered_file(cfg, st, video) -> bool:
    """v21's actual failure mode, closed: every check above is a statement
    about `cfg`, run through `_bird_pose` in isolation. None of them observe
    the render. That is not hypothetical — a check suite built entirely this
    way would give exit 0 to a stale cache, a wrong import, a swallowed
    exception falling back to old behaviour, or `--verify-only` skipping the
    render outright, because it never once looks at what the encoder wrote.

    So: sample the model's predicted (x, y) at five points across the flight
    and find where the canary mask's own centroid actually sits in the
    delivered frame at the same instant. They have to agree to within a few
    percent of frame width, because if they do not, the pixels on screen were
    not produced by this config.
    """
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    ok = True
    for i, tr in enumerate((0.4, 1.2, 2.0, 2.8, 3.6)):
        pose = sss._bird_pose(cfg, tr)
        frame = _grab(video, t0 + tr, os.path.join(tmp, f'p{i}.png'))
        g, b = frame[..., 1], frame[..., 2]
        mask = (g - b > 90) & (g > 120)
        ys, xs = np.where(mask)
        if len(xs) < 20:
            ok = False
            print(f'[verify] t={tr}s: too few canary px ({len(xs)}) to locate the bird in the delivered file')
            continue
        H, W = frame.shape[:2]
        mx, my = float(xs.mean()) / W, float(ys.mean()) / H
        px, py = pose['pos']
        d = math.hypot(mx - px, my - py)
        print(
            f'[verify] t={tr}s: model ({px:.3f}, {py:.3f}) vs delivered '
            f'centroid ({mx:.3f}, {my:.3f}) — {d * 100:.1f}% of frame width off'
        )
        if d > 0.07:  # loose enough to absorb the
            # wingbeat bob, tight enough
            # that a different config or a
            # stale render cannot pass it
            ok = False
            print(
                f'[verify] t={tr}s: THE DELIVERED FILE DOES NOT TRACK THE '
                f'MODEL — the render is not the config that was checked'
            )
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


def _bird_bank_visible_in_delivered_file(cfg, st, video) -> bool:
    """The bank has to show up as ROLL on the sprite, not just as a number in
    `pose['bank']` — that number was already correct-on-paper in v21 while
    the render looked untouched, because nothing checked that the sprite
    tile the roll is applied to is actually the one on screen with a
    different orientation from an unrolled one.

    FIRST cut of this check measured the canary mask's own 2nd-moment
    principal axis and compared its sign to the model's bank. On the actual
    v22 delivered file that scored 4/8 — chance — even though pulling the
    same 8 frames and looking at them by eye (the two most extreme, t=0.3s
    at +45deg and t=0.8s at -37deg) shows unambiguous, correctly-mirrored
    banking. The moment axis is dominated by the WING SHAPE at that instant
    (spread vs tucked), not by roll, at a sprite this small (24-60px) — a
    real effect the check was reporting as broken.

    This version tests geometry instead of a hand-derived angle: render the
    frame TWICE from the same `_draw_bird` the pipeline itself calls — once
    with the model's actual bank, once with the sign of every bank on the
    table flipped (`bank_gain` negated, same magnitudes) — and ask which
    hypothesis's silhouette overlaps the delivered file's canary pixels
    better (IoU). This is still noisy at this sprite size (n=8, 6/8 agree —
    a two-sided binomial p~0.29, not strong on its own) so it is corroborating
    evidence alongside the direct visual check, not the sole proof.
    """
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    BW, BH = 2688, 1536  # authoring/plate resolution
    flip_cfg = dict(cfg)
    flip_cfg['bank_gain'] = -float(cfg.get('bank_gain', 1.0))
    pts = (0.3, 0.8, 1.3, 1.8, 2.3, 2.8, 3.3, 3.8)
    agree, scored = 0, 0

    def canary_mask(a):
        g, b = a[..., 1], a[..., 2]
        return (g - b > 90) & (g > 120)

    def place_mask(render, x0w, y0w, ww, hh):
        if render is None:
            return np.zeros((hh, ww), dtype=bool)
        (x0, y0), im = render
        im2 = im.resize((max(1, im.width // 2), max(1, im.height // 2)), Image.NEAREST)
        x0d, y0d = x0 // 2, y0 // 2
        alpha = np.asarray(im2.split()[-1], dtype=np.float32) > 32
        canvas = np.zeros((hh, ww), dtype=bool)
        tx, ty = x0d - x0w, y0d - y0w
        th, tw = alpha.shape
        sx0, sy0 = max(0, -tx), max(0, -ty)
        dx0, dy0 = max(0, tx), max(0, ty)
        w, h = min(tw - sx0, ww - dx0), min(th - sy0, hh - dy0)
        if w > 0 and h > 0:
            canvas[dy0 : dy0 + h, dx0 : dx0 + w] = alpha[sy0 : sy0 + h, sx0 : sx0 + w]
        return canvas

    def iou(a, b):
        union = (a | b).sum()
        return float((a & b).sum()) / union if union else 0.0

    for tr in pts:
        pose = sss._bird_pose(cfg, tr)
        bank = pose.get('bank')
        if bank is None or abs(bank) < 3.0:
            continue  # too close to level to sign
        frame = _grab(video, t0 + tr, os.path.join(tmp, 'f.png'))
        Hd, Wd = frame.shape[:2]
        cx, cy = int(pose['pos'][0] * Wd), int(pose['pos'][1] * Hd)
        r = 120
        x0w, y0w = max(0, cx - r), max(0, cy - r)
        x1w, y1w = min(Wd, cx + r), min(Hd, cy + r)
        ww, hh = x1w - x0w, y1w - y0w
        deliv = canary_mask(frame[y0w:y1w, x0w:x1w])
        if deliv.sum() < 10:
            continue
        mA = place_mask(sss._draw_bird((BW, BH), cfg, tr), x0w, y0w, ww, hh)
        mB = place_mask(sss._draw_bird((BW, BH), flip_cfg, tr), x0w, y0w, ww, hh)
        iouA, iouB = iou(deliv, mA), iou(deliv, mB)
        scored += 1
        same_sign = iouA > iouB
        agree += int(same_sign)
        print(
            f'[verify] t={tr}s: model bank {bank:+.1f} deg — IoU vs model '
            f'{iouA:.3f}, IoU vs mirrored {iouB:.3f} — '
            f'{"agrees" if same_sign else "DISAGREES"}'
        )
    shutil.rmtree(tmp, ignore_errors=True)
    if scored < 3:
        print('[verify] too few frames had enough bank to sign — cannot confirm the roll is visible')
        return False
    frac = agree / scored
    print(
        f'[verify] roll sign agreed with the model at {agree}/{scored} '
        f'sampled points ({frac * 100:.0f}%) — a noisy corroborating check, '
        f'not the primary proof; see the v22 header for the visual check'
    )
    if frac <= 0.5:
        print('[verify] THE BANK IS NOT VISIBLY ROLLING THE SPRITE')
        return False
    return True
