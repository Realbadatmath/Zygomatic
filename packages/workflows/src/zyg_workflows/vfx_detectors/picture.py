# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math

from zyg_workflows.vfx_detectors.core import (
    _EPS,
    _ev,
    _mean,
    _std,
    detector,
)

# ═══════════════════════════════════════════════════════════════════════════
# POST-PROCESS SIGNATURES  (the honestly-invertible tier)
# ═══════════════════════════════════════════════════════════════════════════


def _simple_frame(ctx, tid, key, thr_key, extra_keys=(), direction='ge'):
    xs = ctx.series(key)
    thr = ctx.T[thr_key]
    events, best = [], (max(xs) if xs else 0.0) if direction == 'ge' else (min(xs) if xs else 0.0)
    for i, v in enumerate(xs):
        hit = v >= thr if direction == 'ge' else v <= thr
        if hit:
            ev = {key: round(v, 5)}
            for k in extra_keys:
                ev[k] = ctx.fm[i].get(k)
            events.append(_ev(tid, i, ctx, min(1.0, abs(v) / max(_EPS, thr * 2)), **ev))
    return events, round(best, 5)


@detector(
    'post_fx.bloom',
    unit='luma lift 0-1',
    threshold_key='bloom_lift',
    note='Measured as the luminance lift in the ring AROUND blown highlights. '
    'bloom_radius_px comes back with it — these two numbers are directly '
    'reusable as render parameters.',
)
def d_bloom(ctx):
    return _simple_frame(ctx, 'post_fx.bloom', 'bloom_lift', 'bloom_lift', ('bloom_radius_px', 'highlight_frac'))


@detector(
    'post_fx.chromatic_aberration',
    unit='px',
    threshold_key='ca_px',
    note='Best-fit radial scale of R and B against G. Real CA scales consistently '
    'with radius; a coloured edge that does not is not CA.',
)
def d_ca(ctx):
    return _simple_frame(ctx, 'post_fx.chromatic_aberration', 'ca_px', 'ca_px', ('ca_scale_r', 'ca_scale_b'))


@detector(
    'post_fx.vignette',
    unit='0-1 falloff',
    threshold_key='vignette',
    note='Corner-vs-centre luminance ratio. A genuinely dark-cornered SHOT reads '
    'the same as an applied vignette — this cannot separate them.',
)
def d_vignette(ctx):
    return _simple_frame(ctx, 'post_fx.vignette', 'vignette_strength', 'vignette')


@detector(
    'post_fx.film_grain',
    unit='sigma (8-bit levels)',
    threshold_key='grain_sigma',
    note='Immerkaer noise estimate. Cannot tell added grain from sensor noise or '
    'from codec noise on a low-bitrate source.',
)
def d_grain(ctx):
    return _simple_frame(ctx, 'post_fx.film_grain', 'noise_sigma', 'grain_sigma', ('spectrum_slope',))


@detector(
    'post_fx.halation',
    unit='red lift 0-1',
    threshold_key='halation',
    note='Red channel spilling further than green around highlights — the film signature, distinct from neutral bloom.',
)
def d_halation(ctx):
    return _simple_frame(ctx, 'post_fx.halation', 'halation_red_lift', 'halation', ('bloom_lift',))


@detector(
    'post_fx.banding',
    unit='top-16-level mass',
    threshold_key='banding_score',
    note='Fraction of a blurred frame sitting on only 16 luminance levels. Flags '
    'posterised gradients and 8-bit compression on skies.',
)
def d_banding(ctx):
    xs = ctx.series('banding_score')
    thr = ctx.T['banding_score']
    events, best = [], max(xs) if xs else 0.0
    for i, v in enumerate(xs):
        if v >= thr:
            events.append(
                _ev(
                    'post_fx.banding',
                    i,
                    ctx,
                    min(1.0, v),
                    banding_score=round(v, 4),
                    spectrum_slope=ctx.fm[i].get('spectrum_slope'),
                )
            )
    return events, round(best, 4)


# ═══════════════════════════════════════════════════════════════════════════
# LIGHTING
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'lighting.low_key',
    unit='luma p50',
    threshold_key='lowkey_p50',
    note='Median luminance low while the frame still has highlights — dark but '
    'not underexposed. A fade-to-black also reads low and is excluded by '
    'requiring a live highlight.',
)
def d_lowkey(ctx):
    events, best = [], 255.0
    for i, m in enumerate(ctx.fm):
        p50 = float(m.get('luma_p50', 128) or 0)
        p99 = float(m.get('luma_p99', 128) or 0)
        best = min(best, p50)
        if p50 <= ctx.T['lowkey_p50'] and p99 > 140:
            events.append(
                _ev(
                    'lighting.low_key',
                    i,
                    ctx,
                    min(1.0, (ctx.T['lowkey_p50'] - p50) / max(_EPS, ctx.T['lowkey_p50'])),
                    luma_p50=round(p50, 2),
                    luma_p99=round(p99, 2),
                    black_clip=m.get('black_clip_frac'),
                )
            )
    return events, round(best, 2)


@detector(
    'lighting.high_key', unit='luma p50', threshold_key='highkey_p50', note='Median luminance high with shadows lifted.'
)
def d_highkey(ctx):
    events, best = [], 0.0
    for i, m in enumerate(ctx.fm):
        p50 = float(m.get('luma_p50', 128) or 0)
        p5 = float(m.get('luma_p5', 0) or 0)
        best = max(best, p50)
        if p50 >= ctx.T['highkey_p50'] and p5 > 60:
            events.append(
                _ev('lighting.high_key', i, ctx, min(1.0, p50 / 255.0), luma_p50=round(p50, 2), luma_p5=round(p5, 2))
            )
    return events, round(best, 2)


@detector(
    'lighting.silhouette',
    unit='bimodality 0-1',
    threshold_key='silhouette_bimodal',
    note='A strongly bimodal histogram with mass at both ends and little between: '
    'a dark subject against a bright field. Weak on a busy background.',
)
def d_silhouette(ctx):
    events, best = [], 0.0
    for i, m in enumerate(ctx.fm):
        dark = float(m.get('black_clip_frac', 0) or 0)
        p5, p95 = float(m.get('luma_p5', 0) or 0), float(m.get('luma_p95', 0) or 0)
        mid = float(m.get('luma_p50', 0) or 0)
        spread = (p95 - p5) / 255.0
        bimodal = spread * (1.0 - abs(mid - 0.5 * (p5 + p95)) / max(_EPS, 0.5 * (p95 - p5) + _EPS))
        bimodal = max(0.0, min(1.0, bimodal))
        best = max(best, bimodal)
        if bimodal >= ctx.T['silhouette_bimodal'] and dark > 0.08 and p95 > 180:
            events.append(
                _ev(
                    'lighting.silhouette',
                    i,
                    ctx,
                    bimodal,
                    bimodality=round(bimodal, 4),
                    dark_frac=round(dark, 4),
                    luma_p5=round(p5, 1),
                    luma_p95=round(p95, 1),
                )
            )
    return events, round(best, 4)


@detector(
    'lighting.flicker',
    unit='luma std over window',
    threshold_key='flicker_std',
    note='Frame-to-frame luminance oscillation with no camera motion and no cut — '
    'firelight, a candle, a failing lamp, a screen. Measured on a 7-frame '
    'rolling window so a fade does not read as flicker.',
)
def d_flicker(ctx):
    lum = ctx.series('luma_mean')
    if len(lum) < 9:
        return [], 0.0
    cuts = {sh.get('cut_in', {}).get('frame') for sh in ctx.shots if sh.get('cut_in')}
    thr = ctx.T['flicker_std']
    events, best = [], 0.0
    w = 7
    for i in range(len(lum) - w):
        win = lum[i : i + w]
        if set(range(i, i + w)) & cuts:
            continue
        s = _std(win)
        # a monotone ramp (a fade) has high std too — require sign changes
        signs = [1 if win[k + 1] > win[k] else -1 for k in range(len(win) - 1)]
        flips = sum(1 for k in range(len(signs) - 1) if signs[k] != signs[k + 1])
        best = max(best, s if flips >= 2 else 0.0)
        if s >= thr and flips >= 2:
            events.append(
                _ev(
                    'lighting.flicker',
                    i,
                    ctx,
                    min(1.0, s / (thr * 3)),
                    luma_std=round(s, 3),
                    direction_flips=flips,
                    window=[i, i + w - 1],
                )
            )
    return _dedupe_runs(events), round(best, 3)


def _dedupe_runs(events, gap=4):
    """Collapse consecutive per-frame hits into one event per run. A rolling
    window fires on every offset; the log wants the EVENT, not the window."""
    if not events:
        return events
    out = [events[0]]
    for e in events[1:]:
        if e['frame'] - out[-1]['frame'] > gap:
            out.append(e)
        else:
            out[-1].setdefault('evidence', {})['run_end_frame'] = e['frame']
    return out


# ═══════════════════════════════════════════════════════════════════════════
# NATURAL PHENOMENA  (weak heuristics — flagged as such)
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'weather_atmos.clouds_moving',
    unit='coherence 0-1',
    threshold_key='cloud_coherence',
    needs=('pairs',),
    note='WEAK HEURISTIC, needs calibration. Upper-third residual flow that is '
    'slow, coherent in direction, over low-edge-density (sky-like) content. '
    'A slow pan over any textured top band will imitate this.',
)
def d_clouds(ctx):
    events, best = [], 0.0
    for f, pm in sorted(ctx.pm.items()):
        blobs = pm.get('motion_blobs') or []
        top = [b for b in blobs if b['cy'] < 0.4]
        if not top:
            continue
        mags = [b['mag_mean'] for b in top]
        m = _mean(mags)
        if not (ctx.T['cloud_flow_min'] <= m <= ctx.T['cloud_flow_max']):
            continue
        dxs = [b['dx'] for b in top]
        dys = [b['dy'] for b in top]
        vec = math.hypot(_mean(dxs), _mean(dys))
        coh = vec / max(_EPS, _mean([math.hypot(a, b) for a, b in zip(dxs, dys)]))
        ed = float(ctx.fm[f].get('edge_density', 1.0) or 1.0)
        best = max(best, coh)
        if coh >= ctx.T['cloud_coherence'] and ed < 0.12:
            events.append(
                _ev(
                    'weather_atmos.clouds_moving',
                    f,
                    ctx,
                    coh,
                    coherence=round(coh, 4),
                    mean_mag=round(m, 4),
                    edge_density=round(ed, 4),
                    n_regions=len(top),
                    caveat='weak heuristic — verify visually',
                )
            )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'fluids_fire.water_moving',
    unit='incoherence 0-1',
    threshold_key='water_incoherence',
    needs=('pairs',),
    note='WEAK HEURISTIC, needs calibration. Residual motion that is INCOHERENT '
    '(neighbouring regions disagree on direction) and persistent, with a '
    'high specular-sparkle count. Foliage in wind reads very similarly.',
)
def d_water(ctx):
    events, best = [], 0.0
    for f, pm in sorted(ctx.pm.items()):
        blobs = pm.get('motion_blobs') or []
        if len(blobs) < 3:
            continue
        dxs = [b['dx'] for b in blobs]
        dys = [b['dy'] for b in blobs]
        vec = math.hypot(_mean(dxs), _mean(dys))
        avg = _mean([math.hypot(a, b) for a, b in zip(dxs, dys)])
        incoh = 1.0 - (vec / max(_EPS, avg))
        curl = abs(float(pm.get('flow_curl', 0.0) or 0.0))
        best = max(best, incoh)
        if incoh >= ctx.T['water_incoherence'] and avg > 0.4:
            events.append(
                _ev(
                    'fluids_fire.water_moving',
                    f,
                    ctx,
                    incoh,
                    incoherence=round(incoh, 4),
                    mean_mag=round(avg, 4),
                    curl=round(curl, 5),
                    n_regions=len(blobs),
                    caveat='weak heuristic — foliage and crowds imitate this',
                )
            )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'fluids_fire.water_boiling',
    unit='churn 0-1',
    threshold_key='boil_churn',
    needs=('pairs',),
    note='WEAK HEURISTIC, needs calibration. A localised region with high churn '
    '(large per-frame change) but near-zero NET displacement across the '
    'window — the surface roils without going anywhere — plus rising '
    'high-frequency texture. Steam above it is not measured.',
)
def d_boil(ctx):
    events, best = [], 0.0
    frames = sorted(ctx.pm)
    for f in frames:
        pm = ctx.pm[f]
        blobs = pm.get('motion_blobs') or []
        for b in blobs:
            if b['area_frac'] < 0.004:
                continue
            net = math.hypot(b['dx'], b['dy'])
            churn = b['mag_mean']
            if churn < 0.35:
                continue
            ratio = net / max(_EPS, churn)
            score = max(0.0, 1.0 - ratio)
            hf = float(ctx.fm[f].get('hf_energy_frac', 0.0) or 0.0)
            best = max(best, score)
            if score >= ctx.T['boil_churn'] and ratio <= ctx.T['boil_net_ratio']:
                events.append(
                    _ev(
                        'fluids_fire.water_boiling',
                        f,
                        ctx,
                        score,
                        churn=round(churn, 4),
                        net_displacement=round(net, 4),
                        net_over_churn=round(ratio, 4),
                        hf_energy=round(hf, 4),
                        bbox=[b['x'], b['y'], b['w'], b['h']],
                        caveat='weak heuristic — any in-place texture churn '
                        '(rain on a surface, static, foliage) matches',
                    )
                )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'fluids_fire.fire_flicker',
    unit='hue frac x luma std',
    threshold_key='fire_hue_frac',
    note='WEAK HEURISTIC. A warm-hue mass (orange/yellow band of the hue histogram) '
    'whose luminance oscillates. A warm-graded shot with a flickering lamp '
    'will match; the hue test alone is not fire.',
)
def d_fire(ctx):
    lum = ctx.series('luma_mean')
    events, best = [], 0.0
    for i, m in enumerate(ctx.fm):
        hh = m.get('hue_hist12') or []
        if len(hh) < 12:
            continue
        # OpenCV hue 0-179 in 12 bins: bins 0-2 cover red->orange->yellow
        warm = float(hh[0] + hh[1] + hh[2])
        lo, hi = max(0, i - 3), min(len(lum), i + 4)
        s = _std(lum[lo:hi])
        score = warm * min(1.0, s / max(_EPS, ctx.T['fire_flicker_std']))
        best = max(best, score)
        if warm >= ctx.T['fire_hue_frac'] and s >= ctx.T['fire_flicker_std']:
            events.append(
                _ev(
                    'fluids_fire.fire_flicker',
                    i,
                    ctx,
                    min(1.0, score * 4),
                    warm_hue_frac=round(warm, 4),
                    local_luma_std=round(s, 3),
                    sat_mean=m.get('sat_mean'),
                    caveat='weak heuristic — warm grade + any flicker matches',
                )
            )
    return _dedupe_runs(events), round(best, 4)
