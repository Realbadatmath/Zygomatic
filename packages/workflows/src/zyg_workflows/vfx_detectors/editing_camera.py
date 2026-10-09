# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math

from zyg_workflows.vfx_detectors.core import (
    _EPS,
    _ev,
    _mean,
    _median,
    _std,
    _zscores,
    detector,
)

# ═══════════════════════════════════════════════════════════════════════════
# EDITING / TEMPORAL
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'editing_time.hard_cut',
    unit='hist_corr',
    threshold_key='cut_hist_corr',
    needs=('pairs',),
    note='A cut collapses histogram correlation AND moves most '
    'of the frame. Both are required so a whip pan, which '
    'moves everything but keeps its palette, is not a cut.',
)
def d_cut(ctx):
    events, best = [], 1.0
    for sh in ctx.shots:
        c = sh.get('cut_in')
        if not c:
            continue
        best = min(best, c['hist_corr'])
        ev = {k: v for k, v in c.items() if k != 'frame'}
        events.append(_ev('editing_time.hard_cut', c['frame'], ctx, 1.0 - c['hist_corr'], **ev))
    if not events:
        _fr, hs = ctx.pair_series('hist_corr', 1.0)
        best = min(hs) if hs else 1.0
    return events, round(best, 4)


@detector(
    'editing_time.fade_black',
    unit='luma_mean',
    threshold_key='fade_luma',
    note='A run of frames whose mean luminance walks monotonically into or out '
    'of black. Distinguished from a cut to black by taking >1 frame.',
)
def d_fade(ctx):
    lum = ctx.series('luma_mean')
    thr = ctx.T['fade_luma']
    events, best = [], min(lum) if lum else 255.0
    i = 0
    while i < len(lum):
        if lum[i] < thr:
            j = i
            while j + 1 < len(lum) and lum[j + 1] < thr:
                j += 1
            if j > i:  # a HELD dark stretch, not one black frame
                events.append(
                    _ev(
                        'editing_time.fade_black',
                        i,
                        ctx,
                        min(1.0, (thr - min(lum[i : j + 1])) / max(_EPS, thr)),
                        start=i,
                        end=j,
                        frames=j - i + 1,
                        min_luma=round(min(lum[i : j + 1]), 2),
                    )
                )
            i = j + 1
        else:
            i += 1
    return events, round(best, 3)


@detector(
    'editing_time.flash_frame',
    unit='luma z-score',
    threshold_key='flash_luma_z',
    note='One or two frames far brighter than their neighbours. Shared machinery '
    'with the anime impact frame; this is the photographic/edit case.',
)
def d_flash(ctx):
    lum = ctx.series('luma_mean')
    if len(lum) < 5:
        return [], 0.0
    z = _zscores(lum)
    thr = ctx.T['flash_luma_z']
    events, best = [], max(z) if z else 0.0
    for i, zz in enumerate(z):
        if zz < thr:
            continue
        nb = [lum[k] for k in (i - 2, i - 1, i + 1, i + 2) if 0 <= k < len(lum)]
        if nb and lum[i] > _mean(nb) + 25:
            events.append(
                _ev(
                    'editing_time.flash_frame',
                    i,
                    ctx,
                    min(1.0, zz / (thr * 2)),
                    luma=round(lum[i], 2),
                    neighbour_mean=round(_mean(nb), 2),
                    z=round(zz, 3),
                )
            )
    return events, round(best, 3)


@detector(
    'editing_time.animation_cadence',
    unit='mean hold (frames)',
    note='The shooting cadence itself, reported as a finding because every other '
    'temporal reading in the run is conditioned on it.',
)
def d_cadence(ctx):
    cad = ctx.cadence
    ev = [
        _ev(
            'editing_time.animation_cadence',
            ctx.uidx[0] if ctx.uidx else 0,
            ctx,
            1.0,
            cadence=cad['cadence'],
            unique_ratio=cad['unique_ratio'],
            mean_hold=cad['mean_hold'],
            hold_histogram=cad['hold_hist'],
            unique_cels=len(cad['unique_idx']),
            total_frames=ctx.n,
        )
    ]
    return ev, round(float(cad['mean_hold']), 3)


@detector(
    'editing_time.held_cel',
    unit='hold length (frames)',
    threshold_key='held_cel_min',
    note='A drawing held longer than the clip cadence — a deliberate pause, or '
    'limited animation. Reported per run of holds.',
)
def d_held(ctx):
    holds = ctx.cadence.get('holds') or []
    uidx = ctx.cadence.get('unique_idx') or []
    thr = int(ctx.T['held_cel_min'])
    events, best = [], max(holds) if holds else 0
    for u, h in zip(uidx, holds):
        if h >= thr:
            events.append(
                _ev(
                    'editing_time.held_cel',
                    u,
                    ctx,
                    min(1.0, h / (thr * 3.0)),
                    hold_frames=h,
                    seconds=round(h / ctx.fps, 3),
                )
            )
    return events, float(best)


# ═══════════════════════════════════════════════════════════════════════════
# 2D / ANIME
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'anime_2d.impact_frame',
    unit='luma z-score',
    threshold_key='impact_luma_z',
    note='1-3 frames of extreme luminance (white OR black) that the sequence '
    'returns from. Checks the RETURN — a cut to a bright shot also spikes.',
)
def d_impact(ctx):
    lum = ctx.series('luma_mean')
    if len(lum) < 5:
        return [], 0.0
    z = _zscores(lum)
    thr, maxf = ctx.T['impact_luma_z'], int(ctx.T['impact_max_frames'])
    cuts = {sh.get('cut_in', {}).get('frame') for sh in ctx.shots if sh.get('cut_in')}
    events, best = [], max(abs(x) for x in z) if z else 0.0
    i = 1
    while i < len(lum) - 1:
        if abs(z[i]) < thr:
            i += 1
            continue
        j = i
        while j + 1 < len(lum) - 1 and abs(z[j + 1]) >= thr * 0.7:
            j += 1
        span = j - i + 1
        before, after = lum[i - 1], lum[min(len(lum) - 1, j + 1)]
        peak = lum[i : j + 1]
        returned = abs(after - before) < 0.45 * abs(_mean(peak) - before)
        if span <= maxf and returned and not (set(range(i, j + 2)) & cuts):
            events.append(
                _ev(
                    'anime_2d.impact_frame',
                    i,
                    ctx,
                    min(1.0, abs(z[i]) / (thr * 2)),
                    span_frames=span,
                    polarity='white' if z[i] > 0 else 'black',
                    peak_luma=round(_mean(peak), 2),
                    luma_before=round(before, 2),
                    luma_after=round(after, 2),
                    z=round(z[i], 3),
                )
            )
        i = j + 1
    return events, round(best, 3)


@detector(
    'anime_2d.speedlines',
    unit='edge_density',
    threshold_key='speedline_edge_density',
    note='A spike in edge density whose Sobel orientation histogram collapses into '
    'one or two bins (parallel lines). Radial bursts raise density without '
    'collapsing orientation and are NOT caught by this — a known gap.',
)
def d_speedlines(ctx):
    ed = ctx.series('edge_density')
    op = ctx.series('edge_orient_peak')
    if not ed:
        return [], 0.0
    med = _median(ed)
    thr_d, thr_p = ctx.T['speedline_edge_density'], ctx.T['speedline_orient_peak']
    events, best = [], 0.0
    for i, (d, p) in enumerate(zip(ed, op)):
        score = min(1.0, (d / max(_EPS, thr_d)) * (p / max(_EPS, thr_p)) / 2.0)
        best = max(best, d if p >= thr_p else 0.0)
        if d >= thr_d and p >= thr_p and d > med * 1.25:
            events.append(
                _ev(
                    'anime_2d.speedlines',
                    i,
                    ctx,
                    score,
                    edge_density=round(d, 4),
                    orient_peak=round(p, 4),
                    clip_median_density=round(med, 4),
                )
            )
    return events, round(best, 4)


# ═══════════════════════════════════════════════════════════════════════════
# CAMERA
# ═══════════════════════════════════════════════════════════════════════════


def _cam_move(ctx, tid, key, cmp_fn, thr_key, label):
    fr, vals = ctx.pair_series(key)
    if not fr:
        return [], 0.0
    thr = ctx.T[thr_key]
    events, best = [], 0.0
    for f, v in zip(fr, vals):
        best = max(best, abs(v))
        if cmp_fn(v, thr) and ctx.pm[f].get('cam_fit_ok'):
            events.append(
                _ev(
                    tid,
                    f,
                    ctx,
                    min(1.0, abs(v) / (thr * 4)),
                    **{label: round(v, 5), 'cam_inliers': ctx.pm[f].get('cam_inliers', 0)},
                )
            )
    return events, round(best, 5)


@detector(
    'camera.pan',
    unit='frame-widths/pair',
    threshold_key='cam_pan_norm',
    needs=('pairs',),
    note='Horizontal component of the global affine fit. Sign is '
    'the direction the IMAGE moves, so a pan right gives a '
    'negative dx.',
)
def d_pan(ctx):
    return _cam_move(ctx, 'camera.pan', 'cam_pan_norm', lambda v, t: abs(v) >= t, 'cam_pan_norm', 'pan_norm')


@detector(
    'camera.tilt',
    unit='frame-heights/pair',
    threshold_key='cam_pan_norm',
    needs=('pairs',),
    note='Vertical component of the same fit.',
)
def d_tilt(ctx):
    return _cam_move(ctx, 'camera.tilt', 'cam_tilt_norm', lambda v, t: abs(v) >= t, 'cam_pan_norm', 'tilt_norm')


@detector(
    'camera.zoom',
    unit='scale delta/pair',
    threshold_key='cam_zoom_delta',
    needs=('pairs',),
    note='Scale term of the affine fit. Does not distinguish a '
    'lens zoom from a dolly — that needs parallax between '
    'depth layers, which is not measured here.',
)
def d_zoom(ctx):
    fr, vals = ctx.pair_series('cam_zoom', 1.0)
    thr = ctx.T['cam_zoom_delta']
    events, best = [], 0.0
    for f, v in zip(fr, vals):
        d = v - 1.0
        best = max(best, abs(d))
        if abs(d) >= thr and ctx.pm[f].get('cam_fit_ok'):
            events.append(
                _ev(
                    'camera.zoom',
                    f,
                    ctx,
                    min(1.0, abs(d) / (thr * 4)),
                    zoom_delta=round(d, 5),
                    direction='in' if d > 0 else 'out',
                )
            )
    return events, round(best, 5)


@detector(
    'camera.roll',
    unit='degrees/pair',
    threshold_key='cam_roll_deg',
    needs=('pairs',),
    note='Rotation term. A sustained non-zero roll is a dutch angle; an oscillating one is handheld.',
)
def d_roll(ctx):
    return _cam_move(ctx, 'camera.roll', 'cam_roll_deg', lambda v, t: abs(v) >= t, 'cam_roll_deg', 'roll_deg')


@detector(
    'camera.handheld_shake',
    unit='px std',
    threshold_key='shake_std',
    needs=('pairs',),
    note='High-frequency, zero-mean camera translation: the '
    'std of dx/dy is large while their MEAN is near zero. '
    'A steady pan has the opposite signature.',
)
def d_shake(ctx):
    fr, dx = ctx.pair_series('cam_dx')
    _f2, dy = ctx.pair_series('cam_dy')
    if len(dx) < 6:
        return [], 0.0
    sx, sy = _std(dx), _std(dy)
    mx, my = abs(_mean(dx)), abs(_mean(dy))
    shake = math.hypot(sx, sy)
    steady = math.hypot(mx, my)
    best = shake
    thr = ctx.T['shake_std']
    events = []
    if shake >= thr and shake > steady * 1.6:
        events.append(
            _ev(
                'camera.handheld_shake',
                fr[0],
                ctx,
                min(1.0, shake / (thr * 3)),
                dx_std=round(sx, 3),
                dy_std=round(sy, 3),
                dx_mean=round(_mean(dx), 3),
                dy_mean=round(_mean(dy), 3),
                shake_over_drift=round(shake / max(_EPS, steady), 3),
                frames=[fr[0], fr[-1]],
            )
        )
    return events, round(best, 3)


@detector(
    'camera.locked_off',
    unit='residual px',
    threshold_key='static_max_motion',
    needs=('pairs',),
    note='The camera did not move for the whole window. Reported as a positive finding: a static frame is a choice.',
)
def d_static(ctx):
    fr, dx = ctx.pair_series('cam_dx')
    _f2, dy = ctx.pair_series('cam_dy')
    if not dx:
        return [], 0.0
    worst = max(math.hypot(a, b) for a, b in zip(dx, dy))
    thr = ctx.T['static_max_motion']
    events = []
    if worst <= thr:
        events.append(
            _ev('camera.locked_off', fr[0], ctx, 1.0, max_camera_translation_px=round(worst, 4), frames=[fr[0], fr[-1]])
        )
    return events, round(worst, 4)


@detector(
    'camera.letterbox_bars',
    unit='bar px',
    note='Matte bars change the EFFECTIVE aspect, so every framing metric in the '
    'run should be read against active_aspect, not the file aspect.',
)
def d_letterbox(ctx):
    lb = ctx.series('letterboxed')
    pb = ctx.series('pillarboxed')
    events, best = [], 0.0
    for i, (a, b) in enumerate(zip(lb, pb)):
        m = ctx.fm[i]
        bars = (
            float(m.get('bar_top', 0))
            + float(m.get('bar_bottom', 0))
            + float(m.get('bar_left', 0))
            + float(m.get('bar_right', 0))
        )
        best = max(best, bars)
        if a or b:
            events.append(
                _ev(
                    'camera.letterbox_bars',
                    i,
                    ctx,
                    1.0,
                    letterboxed=bool(a),
                    pillarboxed=bool(b),
                    top=m.get('bar_top'),
                    bottom=m.get('bar_bottom'),
                    left=m.get('bar_left'),
                    right=m.get('bar_right'),
                    active_aspect=m.get('active_aspect'),
                    file_aspect=m.get('file_aspect'),
                )
            )
    return events, round(best, 2)
