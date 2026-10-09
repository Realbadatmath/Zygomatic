# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.run_scene_shores_v24.constants import (
    BIRD_DUR,
    BIRD_IN,
    Image,
    OUT_DIR,
    TAIL_FADE_IN_S,
    _STATIC_REGIONS,
    _canary_px,
    _grab,
    _seq,
    math,
    np,
    os,
    shutil,
    sss,
)

# Re-anchored: the package carries the old module's name, so __package__ IS
# the original __name__. Restores getLogger(__name__), Blueprint(__name__)
# and every moved function's __module__ without editing moved bytes.
__name__ = __package__


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
