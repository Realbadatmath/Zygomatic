# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Measurement, facts, and QC spec resolution.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os

from zyg_workflows.self_improve.base import (
    CAL_SAMPLE_EVERY,
    _GRID_COLS,
    _GRID_ROWS,
    _TILE_DROP_FRAC,
    _jsonable,
    _mklog,
    _read_json,
    _write_json,
    clip_geometry,
    norm_factor,
)


# ══════════════════════════════════════════════════════════════════════════════
# 4.  MEASUREMENT
# ══════════════════════════════════════════════════════════════════════════════


def _cache_path(run_dir):
    return os.path.join(run_dir, '.self_improve_cache.json')


def _cache_key(clip_path, kind, spec):
    try:
        st = os.stat(clip_path)
        stamp = f'{int(st.st_mtime)}:{st.st_size}'
    except Exception:
        stamp = '0:0'
    return f'{kind}|{os.path.basename(clip_path)}|{stamp}|' + json.dumps(_jsonable(spec), sort_keys=True)


def measure_clip(
    clip_path,
    regions,
    min_flow=None,
    max_churn=None,
    prop_boxes=None,
    prop_pairs=None,
    ncc_min=None,
    sample_every=CAL_SAMPLE_EVERY,
    cache_dir=None,
    log_fn=None,
):
    """Run the pixel gates on ONE clip and normalise them to calibration geometry.

    Returns {'ok','clip','geometry','norm_factor','regions':{name:{...,'flow_norm',
    'gate_min_flow','flow_ok','churn_ok','ok'}}, 'props':{name:{'pairs','ncc_min',
    'ncc_max','ok'}}}.  Every value here is MEASURED from the file — nothing is
    inherited from a report.  Fail-safe: errors land in ['error'] with ok=False."""
    log = _mklog(log_fn)
    W, H, fps, nfr = clip_geometry(clip_path)
    nf = norm_factor(W, fps, sample_every)
    out = {
        'ok': False,
        'clip': clip_path,
        'file': os.path.basename(clip_path),
        'geometry': {
            'w': W,
            'h': H,
            'fps': round(fps, 3) if fps else None,
            'frames': nfr,
            'sample_every': sample_every,
        },
        'norm_factor': round(nf, 4),
        'regions': {},
        'props': {},
    }
    cache, cpath = {}, None
    if cache_dir:
        cpath = _cache_path(cache_dir)
        cache = _read_json(cpath, {}) or {}
    try:
        from zyg_workflows import pipeline_debug as DBG
    except Exception as e:
        out['error'] = f'pipeline_debug unavailable: {e}'
        log(f'[self_improve] {out["error"]}')
        return out
    # An UNDECODABLE clip must never read as "measured and fine". pipeline_debug's
    # gates are deliberately fail-safe (a broken QC returns ok=True so it can never
    # block a render) — that is right for a gate and wrong for evidence, so the
    # decode is checked here before anything is believed.
    if not (W and H):
        out['error'] = f'clip has no decodable video stream: {clip_path}'
        log(f'[self_improve] {out["error"]}')
        return out
    try:
        if regions:
            key = _cache_key(clip_path, 'flow', [regions, min_flow, max_churn, sample_every])
            r = cache.get(key)
            if r is None:
                r = DBG.qc_region_flow(
                    clip_path, regions, min_flow=min_flow, max_churn=max_churn, sample_every=sample_every, log_fn=None
                )
                cache[key] = _jsonable(r)
            if r.get('error'):
                # qc_region_flow swallows its own errors into ok=True; surface it
                out['error'] = f'region flow failed: {r["error"]}'
                log(f'[self_improve] {out["error"]}')
                return out
            for name, v in (r.get('regions') or {}).items():
                mn = DBG._gate_thr(min_flow, name, DBG._REGION_FLOW_MIN)
                mx = DBG._gate_thr(max_churn, name, DBG._REGION_CHURN_MAX)
                fn_ = round(float(v['flow_mean']) * nf, 4)
                out['regions'][name] = {
                    'flow_mean': v['flow_mean'],
                    'flow_p95': v['flow_p95'],
                    'flow_norm': fn_,
                    'churn_mean': v['churn_mean'],
                    'churn_p95': v['churn_p95'],
                    'gate_min_flow': mn,
                    'gate_max_churn': mx,
                    'flow_ok': bool(fn_ >= mn),
                    'churn_ok': bool(v['churn_p95'] <= mx),
                    'ok': bool(fn_ >= mn and v['churn_p95'] <= mx),
                    'box': list(regions[name]),
                }
        for pname, pbox in (prop_boxes or {}).items():
            key = _cache_key(clip_path, 'prop', [pbox, prop_pairs, ncc_min])
            p = cache.get(key)
            if p is None:
                p = DBG.qc_prop_consistency(clip_path, tuple(pbox), pairs=prop_pairs, ncc_min=ncc_min, log_fn=None)
                cache[key] = _jsonable(p)
            nccs = [x['ncc'] for x in (p.get('pairs') or [])]
            out['props'][pname] = {
                'box': list(pbox),
                'pairs': p.get('pairs') or [],
                'ncc_min': round(min(nccs), 3) if nccs else None,
                'ncc_max': round(max(nccs), 3) if nccs else None,
                'gate_ncc_min': DBG._PROP_NCC_MIN if ncc_min is None else float(ncc_min),
                'ok': bool(p.get('ok', True)),
            }
        out['ok'] = True
    except Exception as e:
        out['error'] = str(e)[:250]
        log(f'[self_improve] measure_clip({os.path.basename(clip_path)}) failed: {e}')
    if cpath:
        _write_json(cpath, cache)
    if out['ok']:
        log(
            '[self_improve] measured '
            + os.path.basename(clip_path)
            + ': '
            + (
                ', '.join(f'{k}={v["flow_norm"]:.3f}{"" if v["ok"] else " FAIL"}' for k, v in out['regions'].items())
                or f'(no named regions; {W}x{H}@{fps}, {nfr} frames)'
            )
        )
    return out


def motion_loss_map(raw_clip, delivered_clip, cols=_GRID_COLS, rows=_GRID_ROWS, gate=None, sample_every=8, log_fn=None):
    """REGION-FREE DISCOVERY: where did motion disappear between two clips?

    Nobody has to have named a region.  The frame is tiled cols x rows; dense
    Farneback flow is averaged per tile on both clips (each normalised to the
    calibration geometry, so a 1664x960@24 delivered file is comparable with an
    832x480@17 raw one).  A tile is flagged when the raw tile is ALIVE
    (>= gate) while the delivered tile is FROZEN (< gate) and the relative drop
    is >= 35 %.  Flagged tiles are merged into rectangles by 4-connected
    labelling and returned as fractional boxes.

    This is what finds "something that used to move at 0.58-0.83 x 0.60-0.90
    stopped moving" without knowing the word 'hand'.

    Returns {'ok','gate','tiles_flagged','tiles_total','boxes':[{'box','raw',
    'delivered','drop_frac','tiles'}]}."""
    log = _mklog(log_fn)
    out = {'ok': False, 'boxes': [], 'tiles_flagged': 0, 'tiles_total': int(cols) * int(rows)}
    try:
        import cv2
        import numpy as np
        from zyg_workflows import pipeline_debug as DBG

        if gate is None:
            gate = DBG._REGION_FLOW_MIN
        out['gate'] = gate

        def _grid_flow(path):
            arrs, _ = DBG._sampled_gray_frames(path, sample_every)
            if len(arrs) < 3:
                return None, None
            W, H, fps, _n = clip_geometry(path)
            nf = norm_factor(W, fps, sample_every)
            acc = np.zeros((rows, cols), dtype='float64')
            for i in range(len(arrs) - 1):
                fl = cv2.calcOpticalFlowFarneback(arrs[i], arrs[i + 1], None, 0.5, 3, 15, 3, 5, 1.2, 0)
                mag = np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2)
                # INTER_AREA downsample == exact per-tile mean, ~200x faster than
                # a Python loop over 160 tiles per frame pair
                acc += cv2.resize(mag, (cols, rows), interpolation=cv2.INTER_AREA)
            return (acc / max(1, len(arrs) - 1)) * nf, nf

        graw, _ = _grid_flow(raw_clip)
        gdel, _ = _grid_flow(delivered_clip)
        if graw is None or gdel is None:
            out['error'] = 'clip too short to grid'
            return out
        flagged = (graw >= gate) & (gdel < gate) & ((graw - gdel) >= _TILE_DROP_FRAC * np.maximum(graw, 1e-6))
        out['tiles_flagged'] = int(flagged.sum())
        n, lab = cv2.connectedComponents(flagged.astype('uint8'), 4)
        for i in range(1, n):
            ys, xs = np.where(lab == i)
            if len(ys) < 1:
                continue
            box = [
                round(float(xs.min()) / cols, 3),
                round(float(ys.min()) / rows, 3),
                round(float(xs.max() + 1) / cols, 3),
                round(float(ys.max() + 1) / rows, 3),
            ]
            rv = float(graw[lab == i].mean())
            dv = float(gdel[lab == i].mean())
            out['boxes'].append(
                {
                    'box': box,
                    'raw': round(rv, 4),
                    'delivered': round(dv, 4),
                    'drop_frac': round((rv - dv) / rv, 3) if rv > 0 else 0.0,
                    'tiles': int(len(ys)),
                }
            )
        out['boxes'].sort(key=lambda b: b['tiles'] * b['drop_frac'], reverse=True)
        out['ok'] = True
        log(
            f'[self_improve] motion-loss map: {out["tiles_flagged"]}/{out["tiles_total"]} '
            f'tiles, {len(out["boxes"])} cluster(s)'
        )
    except Exception as e:
        out['error'] = str(e)[:250]
        log(f'[self_improve] motion_loss_map failed: {e}')
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 5.  FACTS — the atoms the remedy KB matches on
# ══════════════════════════════════════════════════════════════════════════════


def _num_or_none(v):
    try:
        return float(v)
    except Exception:
        return None


def _fact(ns, args, evidence, note=''):
    tag = ns + (':' + '~'.join(str(args[k]) for k in sorted(args)) if args else '')
    return {'fact': tag, 'ns': ns, 'args': dict(args), 'evidence': _jsonable(evidence), 'note': note}


# ══════════════════════════════════════════════════════════════════════════════
# 6.  QC SPEC RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════


def load_qc_spec(run_dir, log_fn=None):
    """What SHOULD move, and by how much.  Resolution order (first hit wins):
      1. <run_dir>/qc_spec.json          — the driver publishing its own gates
      2. <run_dir>/regions.json          — bare {name: box} plus optional gates
      3. shot_metadata.json['qc'] / ['regions']
      4. {} — no named regions.  The motion-loss grid still works; the loop
         degrades to region-free discovery instead of failing.
    Shape: {'regions': {name: [x0,y0,x1,y1]}, 'min_flow': ..., 'max_churn': ...,
            'prop_boxes': {...}, 'ncc_min': ..., 'source': ...}"""
    log = _mklog(log_fn)
    for fn in ('qc_spec.json', 'regions.json'):
        d = _read_json(os.path.join(run_dir, fn))
        if isinstance(d, dict) and d.get('regions'):
            d = dict(d)
            d.setdefault('source', fn)
            log(f'[self_improve] qc spec from {fn}: {sorted(d["regions"])}')
            return d
    meta = _read_json(os.path.join(run_dir, 'shot_metadata.json'), {}) or {}
    for k in ('qc', 'qc_spec'):
        if isinstance(meta.get(k), dict) and meta[k].get('regions'):
            d = dict(meta[k])
            d['source'] = f'shot_metadata[{k}]'
            return d
    if isinstance(meta.get('regions'), dict):
        return {'regions': meta['regions'], 'source': 'shot_metadata[regions]'}
    log('[self_improve] no named QC regions — falling back to region-free discovery')
    return {'regions': {}, 'source': 'none'}


def _find_clip(
    run_dir, chain, prefer=('deliver', 'interp', 'smoke_overlay', 'ink_overlay', 'paste_back_static', 'render')
):
    for step in prefer:
        for c in chain:
            if c['step'] == step and c['variant_of'] is None:
                return c['path']
    return chain[-1]['path'] if chain else None


def _find_raw(chain):
    for c in chain:
        if c['step'] == 'render':
            return c['path']
    return None
