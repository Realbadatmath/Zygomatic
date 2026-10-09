# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The verify predicates: the flight off the 3D model, then the delivered-file checks.

Verbatim from the single-file run_scene_shores_v23.py: lines 274-847.
"""

from zyg_workflows.run_scene_shores_v23.scene_setup import (
    BIRD_DUR,
    BIRD_IN,
    Image,
    OUT_DIR,
    SHIP_AT,
    SHIP_TOL,
    TAIL_FADE_IN_S,
    _STATIC_REGIONS,
    _canary_px,
    _grab,
    _seq,
    json,
    math,
    np,
    os,
    shutil,
    sss,
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
    # 9.5s, not 4-6: see the module header — holding the old 5-6s band while
    # adding the swing-away rushed the approach to roughly 2x its old speed.
    if not (8.0 <= dur <= 11.0):
        ok = False
        print(
            f'[verify] BIRD ON SCREEN {dur}s — the v23 brief is 8-11 s '
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
    # Same checks v22 introduced, same floors — retuned (bank_gain 9.0 -> 3.0,
    # bank_raw_cap_deg 16 -> 60, bank_max_deg 45 -> 50) for a path whose real
    # curvature is legitimately sharper. See the module header for the
    # measurement (49% pinned at the old gain, on this new path).
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
    return ok


def _bird_is_in_the_delivered_file(st, video) -> bool:
    """...and it shrinks there. See v22's header — the canary's colour is
    counted as the blue-channel deficit, measured on the delivered frames."""
    import tempfile

    tmp = tempfile.mkdtemp()
    t0 = st['marks']['tail_start'] + BIRD_IN
    near = _grab(video, t0 + 0.4, os.path.join(tmp, 'n.png'))
    far = _grab(video, t0 + BIRD_DUR - 1.5, os.path.join(tmp, 'f.png'))
    before = _grab(video, t0 - 0.3, os.path.join(tmp, 'b.png'))
    after = _grab(video, t0 + BIRD_DUR - 0.05, os.path.join(tmp, 'a.png'))
    n, f = _canary_px(near), _canary_px(far)
    b0, a0 = _canary_px(before), _canary_px(after)
    shutil.rmtree(tmp, ignore_errors=True)
    print(
        f'[verify] DELIVERED file, canary pixels: {b0} before / {n} at the '
        f'lens / {f} at t-1.5s / {a0} after it has gone'
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


def _no_crates_in_the_water(spec) -> bool:
    """The crate row stood in the canal on the right. See v22's header."""
    from PIL import ImageFilter

    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['water']
    mk = sss._water_mask(base.size, cfg).filter(ImageFilter.MinFilter(41))
    m = np.asarray(mk, dtype=np.float32) / 255.0
    a = np.asarray(base.convert('RGB'), dtype=np.float32)
    wet = m > 0.75
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
    """The bow read 145-190/255 with the background showing through it."""
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
    """The helmsman was a dark upright 24x55 on a pale deck."""
    a = np.asarray(Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png')).convert('L'), dtype=np.float32)
    cols = a[952:990, 1670:1704].mean(axis=0)
    med = float(np.median(cols))
    print(
        f'[verify] stern platform across the whipstaff: darkest column '
        f'{cols.min():.0f}/255, deck median {med:.0f}   '
        f'(v19, with the man on it: 10 / 188)'
    )
    ok = True
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
    """Inter-frame change inside the water mask against still boxes."""
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
