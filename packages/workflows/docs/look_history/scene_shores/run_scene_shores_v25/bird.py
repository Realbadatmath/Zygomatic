# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_scene_shores_v25.bird — the flight model check and the three delivered-file bird checks
(presence, trajectory, bank)
(verbatim from run_scene_shores_v25.py lines 265-727).
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
from zyg_workflows.run_scene_shores_v25.constants import (
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
    # 11.0s: see the module header — the screen-space curve needs more room
    # to bend gradually than v23's world-space one did.
    if not (9.0 <= dur <= 13.0):
        ok = False
        print(
            f'[verify] BIRD ON SCREEN {dur}s — the v24 brief is 9-13 s '
            f"(longer than v19-v22's 4-6s so the approach is not rushed "
            f'to make room for the swing-away)'
        )
    if not cfg.get('path3d'):
        ok = False
        print('[verify] the flight is still authored in IMAGE space')
    if not cfg.get('sprites'):
        ok = False
        print('[verify] the bird is still the DRAWN one — no sprite set')

    # THE INVARIANT THAT MAKES THE 3D HONEST: the bird has to be flown through
    # the camera the canal is rippled under, not through one of its own.
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
    xs = np.array([p['pos'][0] for p in ps])
    ys = np.array([p['pos'][1] for p in ps])
    sc = np.array([p['scale'] for p in ps])
    Zs = [p['scale'] and 1.0 / p['scale'] for p in ps]
    print(
        f'[verify] bird: enters ({xs[0]:.3f}, {ys[0]:.3f}) at 1.00, ends '
        f'({xs[-1]:.3f}, {ys[-1]:.3f}) at {sc[-1]:.2f} — a {Zs[-1]:.1f}x recession, '
        f'and the size is PROJECTED, not authored'
    )
    if xs[0] < 1.0:
        ok = False
        print('[verify] the bird does not ENTER — it starts already in frame')

    # ── the ship pass ────────────────────────────────────────────────────────
    # v20-v22: the flight had to END within SHIP_TOL of SHIP_AT. v23: the boat
    # is a waypoint, not a destination, so what is asserted is the CLOSEST
    # APPROACH over the whole trajectory, not the last sample.
    d_ship = np.hypot(xs - SHIP_AT[0], ys - SHIP_AT[1])
    k_ship = int(np.argmin(d_ship))
    t_ship = dur * k_ship / 240.0
    print(
        f'[verify] closest approach to the moored ship at {SHIP_AT}: '
        f'{d_ship[k_ship]:.3f} of a frame width, at t={t_ship:.2f}s '
        f'(x={xs[k_ship]:.3f}, y={ys[k_ship]:.3f})'
    )
    if d_ship[k_ship] > SHIP_TOL:
        ok = False
        print('[verify] THE FLIGHT NEVER ACTUALLY PASSES THE BOAT')
    if not (1.0 <= t_ship <= dur - 1.0):
        ok = False
        print(
            '[verify] the ship pass sits at the very start or end of the '
            'flight — there is no room either to arrive or to bank away'
        )

    if np.any(np.diff(sc) > 1e-6):
        ok = False
        print('[verify] the bird grows somewhere along the flight')
    if sc[-1] > 0.22:
        ok = False
        print('[verify] THE BIRD DOES NOT FLY AWAY — it barely shrinks')

    # Crossing back past x=0.40 ("going away, not past" in v22) is only a
    # defect while the bird still reads as near-size. Past the ship it is
    # SUPPOSED to cross the frame, tiny, on its way off the left edge —
    # measured on this path, that crossing happens at scale 0.14, well under
    # the 0.22 "barely shrinks" floor above.
    below = np.where(xs < 0.40)[0]
    if len(below):
        k0 = int(below[0])
        print(f'[verify] first crosses x=0.40 at t={dur * k0 / 240:.2f}s, scale={sc[k0]:.3f}')
        if sc[k0] > 0.30:
            ok = False
            print(
                '[verify] THE BIRD CROSSES THE FRAME WHILE STILL NEAR-SIZE '
                '— that is a foreground sweep, not a recession'
            )

    # New: it actually has to LEAVE. x < -0.02 is a real margin past the left
    # edge, not a graze, and it has to hold for the last second of screen
    # time — not just tag the edge on the final sample.
    off = np.where(xs < -0.02)[0]
    if not len(off):
        ok = False
        print('[verify] THE BIRD NEVER EXITS OFF-SCREEN — it ends inside the frame')
    else:
        t_off = dur * off[0] / 240.0
        trailing = dur - t_off
        print(
            f'[verify] exits off-screen-left at t={t_off:.2f}s, stays off '
            f'for the remaining {trailing:.2f}s (x ends at {xs[-1]:.3f})'
        )
        if off[-1] != 240:
            ok = False
            print('[verify] THE BIRD COMES BACK ON-SCREEN AFTER EXITING')
        if trailing < 1.0:
            ok = False
            print('[verify] it only grazes the edge — under 1s off-screen at the end')

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
    # Same checks v22 introduced, same floors. v25 does not retune the path
    # or the turn's own bank — only the ENTRY, which used to sit pinned flat
    # at the +48 deg clamp for ~0.6s regardless of the (much smaller, and
    # decreasing) real curvature there (`bank_entry_settle_frac: 0.06`, see
    # the module header). `bank_gain` 3.0->3.1 restores the median-|bank|
    # floor the taper alone narrowly missed (7.93 vs the 8.0 deg floor v22
    # set) — swept and re-measured, not guessed; correlation, range, clamp
    # fraction and roll rate all move by a fraction of a degree at this gain.
    bank = np.array([p['bank'] for p in ps], dtype=np.float64)
    hx = np.array([p['pos'][0] for p in ps])
    hy = np.array([p['pos'][1] for p in ps])
    dx, dy = np.gradient(hx), np.gradient(hy)
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
    if abs(c) < 0.40:
        ok = False
        print('[verify] THE BANK IS NOT COMING FROM THE TURN')
    if bank.max() - bank.min() < 8.0:
        ok = False
        print('[verify] the bird never banks enough to see')
    if step > 400.0:
        ok = False
        print('[verify] the roll rate is not physical')
    med_abs = float(np.median(np.abs(bank)))
    print(f'[verify] median |bank| across the flight {med_abs:.2f} deg ({at_lim * 100:.0f}% at the clamp)')
    if at_lim > 0.20:
        ok = False
        print(
            '[verify] THE BANK RANGE IS JUST THE CLAMP — too much of the '
            'flight is pinned at the limit for the range check to mean '
            'anything'
        )
    if med_abs < 8.0:
        ok = False
        print('[verify] the bank is not visible for most of the flight — one spike is not a bank')

    # ── the yaw / side-view blend ───────────────────────────────────────────
    # THE v25 FIX ITSELF: below here is a statement about whether the SIDE
    # ladder actually engages, not just whether it exists. A missing/typo'd
    # `sprites_side` path, or `_bird_pose` silently failing to carry `yaw`,
    # would leave the render bit-identical to v24's rear-only picture while
    # every check above still passes — this is the check that would catch
    # that class of regression the same way v22's trajectory check caught a
    # stale-config render.
    yaw = np.array([p['yaw'] for p in ps], dtype=np.float64)
    lo = float(cfg.get('yaw_side_lo_deg', 25.0))
    hi = float(cfg.get('yaw_side_hi_deg', 65.0))
    frac_side = float(np.mean(np.abs(yaw) >= hi))
    frac_rear = float(np.mean(np.abs(yaw) <= lo))
    print(
        f'[verify] yaw {yaw.min():+.0f}..{yaw.max():+.0f} deg vs camera '
        f'boresight — {frac_rear * 100:.0f}% of the flight pure-rear '
        f'(|yaw|<={lo:.0f}), {frac_side * 100:.0f}% pure-side '
        f'(|yaw|>={hi:.0f})'
    )
    if not cfg.get('sprites_side'):
        ok = False
        print("[verify] NO sprites_side CONFIGURED — the bird can only roll, not turn (this is v24's defect, unfixed)")
    elif not os.path.isdir(str(cfg['sprites_side'])):
        ok = False
        print(f'[verify] sprites_side DOES NOT EXIST: {cfg["sprites_side"]}')
    if frac_side < 0.10:
        ok = False
        print(
            '[verify] THE SIDE VIEW NEVER FULLY ENGAGES — most of the '
            'flight is well past the entry/exit yaw this shot measured '
            '(58-80 deg); something is capping yaw or the blend window'
        )
    if frac_rear < 0.05:
        ok = False
        print(
            '[verify] the rear view never gets a clean window either — '
            'the cruise (measured ~5-9 deg yaw) should sit there'
        )
    return ok


def _bird_is_in_the_delivered_file(st, video) -> bool:
    """...and it shrinks there. See v22's header — the canary's colour is
    counted as the blue-channel deficit, measured on the delivered frames.

    The "far" sample used to be `BIRD_DUR - 1.5` (9.5s on an 11.0s flight) —
    the SAME "duration-relative offset lands past where the bird is still
    reliably detectable" bug v23's header already found once for
    `_bird_trajectory_matches_model_in_delivered_file`, just not closed here
    too: this shot's own verified model exit is at 9.40s, so that checkpoint
    was sampling AFTER the bird was already gone, 0.1s of margin that a
    render-to-render pixel-count wobble can (and, measured, did) erase. v24
    happened to still show 4 residual canary px there — noise-level, not a
    real margin. Fixed the same way v23 fixed the other check: a FIXED
    early-flight second (4.0s, the same instant the trajectory check's own
    last sample uses) that is robustly still on-screen and shrinking, not a
    duration-relative offset that silently assumes the flight stays
    detectable near its end — it does not, once "exits and stays off" is the
    intended ending (see `_bird_flies_away`).
    """
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    near = _grab(video, t0 + 0.4, os.path.join(tmp, 'n.png'))
    far = _grab(video, t0 + 4.0, os.path.join(tmp, 'f.png'))
    before = _grab(video, t0 - 0.3, os.path.join(tmp, 'b.png'))
    after = _grab(video, t0 + BIRD_DUR - 0.05, os.path.join(tmp, 'a.png'))
    n, f = _canary_px(near), _canary_px(far)
    b0, a0 = _canary_px(before), _canary_px(after)
    shutil.rmtree(tmp, ignore_errors=True)
    print(
        f'[verify] DELIVERED file, canary pixels: {b0} before / {n} at the '
        f'lens / {f} at t+4.0s (past the ship) / {a0} after it has gone'
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
    """v21's actual failure mode, closed in v22: every check above is a
    statement about `cfg`, run through `_bird_pose` in isolation. This one
    samples the model's predicted (x, y) across the flight and finds where
    the canary mask's own centroid actually sits in the delivered frame at
    the same instant."""
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    ok = True
    # Fixed early-flight times, not fractions of BIRD_DUR: past ~t=5s the
    # canary mask on the delivered file drops under the 20px detection floor
    # this check itself requires (measured: 42px at 4.0s, 16px at 5.6s, 0px
    # by 8.5s — the bird is SUPPOSED to shrink and exit, which is exactly why
    # a centroid-tracking check stops being meaningful there). That part of
    # the flight is covered instead by `_bird_is_in_the_delivered_file` (the
    # recede/vanish canary-pixel-count check) and the model-only exit check
    # in `_bird_flies_away`.
    checkpoints = (0.3, 0.8, 1.6, 2.4, 3.2, 4.0)
    for i, tr in enumerate(checkpoints):
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
        if d > 0.07:
            ok = False
            print(
                f'[verify] t={tr}s: THE DELIVERED FILE DOES NOT TRACK THE '
                f'MODEL — the render is not the config that was checked'
            )
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


def _bird_bank_visible_in_delivered_file(cfg, st, video) -> bool:
    """The bank has to show up as ROLL on the sprite. See v22's header for
    why this is a corroborating geometry test (IoU vs a sign-flipped
    hypothesis), not the primary proof."""
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    BW, BH = 2688, 1536
    flip_cfg = dict(cfg)
    flip_cfg['bank_gain'] = -float(cfg.get('bank_gain', 1.0))
    pts = tuple(round(BIRD_DUR * f, 2) for f in (0.03, 0.09, 0.15, 0.22, 0.30, 0.40, 0.55, 0.70, 0.85))
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
            continue
        frame = _grab(video, t0 + tr, os.path.join(tmp, 'f.png'))
        Hd, Wd = frame.shape[:2]
        cx, cy = int(pose['pos'][0] * Wd), int(pose['pos'][1] * Hd)
        r = 120
        x0w, y0w = max(0, cx - r), max(0, cy - r)
        x1w, y1w = min(Wd, cx + r), min(Hd, cy + r)
        ww, hh = x1w - x0w, y1w - y0w
        if ww <= 0 or hh <= 0:
            continue
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
        f'sampled points ({frac * 100:.0f}%) — a noisy corroborating check'
    )
    if frac <= 0.5:
        print('[verify] THE BANK IS NOT VISIBLY ROLLING THE SPRITE')
        return False
    return True
