# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.run_scene_shores_v24.constants import SHIP_AT, SHIP_TOL, json, np, os, sss

# Re-anchored: the package carries the old module's name, so __package__ IS
# the original __name__. Restores getLogger(__name__), Blueprint(__name__)
# and every moved function's __module__ without editing moved bytes.
__name__ = __package__


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
    # Same checks v22 introduced, same floors. v24 retunes bank_raw_cap_deg
    # 60->70 and bank_max_deg 50->48 for the new screen-space curve (bank_gain
    # stays 3.0, unchanged from v23) — see the module header for why this
    # path's bank now correlates with the apparent turn at +0.699 instead of
    # v23's +0.537, and why that number matters more than it looks: v23's bank
    # held -45 deg for 2 real seconds while the apparent turn measured near
    # zero across that same stretch, which a whole-flight Pearson correlation
    # doesn't surface the way tracing the two series side by side does.
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
