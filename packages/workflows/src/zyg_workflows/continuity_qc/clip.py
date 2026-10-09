# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.continuity_qc.models import (
    CONTEXT_STRIDE_FRAMES,
    DEFAULT_THRESHOLDS,
    _crops,
    _detect,
    _embed,
    _gate,
    _iou,
    _load_dino,
    _load_gdino,
    _load_sam2,
    _sample_frames,
    _select_box,
    _track_window,
    os,
    pick_device,
    time,
)


# ── main gate: analyze_clip ───────────────────────────────────────────────────
def analyze_clip(
    clip_path,
    objects,
    sample_fps=2,
    device='auto',
    log_fn=None,
    run_id=None,
    thresholds=None,
    stride=None,
    shadow=True,
    background_exclude=('person',),
):
    """Grounded object-permanence + prop-appearance + background continuity.

    objects: [{'name': 'pipe', 'ground_prompt': 'white clay tobacco pipe'}, ...]

    For every context window (frames binned by `stride`, default 57 = the render
    recipe's context 81 minus overlap 24) GroundingDINO grounds every prompt on the
    window's FIRST sampled frame; SAM2.1 then propagates those boxes across the rest
    of the window (detection cost amortized). Per object we emit:

        presence_rate   fraction of sampled frames whose propagated mask survives
        box_iou_prev    grounded box IoU against the previous window's box
        area_drift_pct  mean mask area change across each window seam, percent
        anchor_cos_first  DINOv2 crop cosine to the frame-0 anchor (VBench
                        subject-consistency protocol) — slow cumulative drift
        seam_cos        DINOv2 crop cosine across each context-window boundary,
                        last sampled frame BEFORE vs first AFTER (~0.5 s apart at
                        sample_fps=2) — the primary morph detector
        cos_prev_window window-anchor vs previous-window-anchor cosine (reported)
        bg_cos_first    inverse-mask whole-frame cosine — the tracked objects AND
                        everything in `background_exclude` (the actors, by default)
                        are blacked out, so what is left is the SET. Catches the room
                        being quietly re-derived between windows without mistaking a
                        character raising an arm for set drift.

    Verdicts per object: 'present' | 'vanished' | 'resized' | 'appearance-drift'
    (severity order, worst wins; every tripped flag is kept in rec['flags']).
    Shadow mode (default) reports and ledgers but sets block=False.

    Returns {'ok', 'shadow', 'block', 'device', 'objects': {...}, 'background': {...},
             'windows': [...], 'checks': [...]}; on internal error
    {'ok': True, 'error': ...} — a broken QC layer must never block generation."""
    log = log_fn or (lambda _m: None)
    thr = dict(DEFAULT_THRESHOLDS)
    thr.update(thresholds or {})
    stride = int(stride or CONTEXT_STRIDE_FRAMES)
    out = {
        'tag': f'continuity:{os.path.basename(clip_path)}',
        'kind': 'continuity',
        'path': clip_path,
        'ok': True,
        'shadow': bool(shadow),
        'block': False,
        'device': None,
        'thresholds': thr,
        'objects': {},
        'background': {},
        'windows': [],
        'checks': [],
    }
    t_start = time.time()
    try:
        import numpy as np

        dev = pick_device(device, log_fn=log)
        out['device'] = dev
        names = [o['name'] for o in objects]
        prompts = [o.get('ground_prompt') or o['name'] for o in objects]
        # extra grounded prompts tracked ONLY to be subtracted from the background
        bg_ex = [str(p) for p in (background_exclude or ())]
        bg_exclude_topk = int(thr.get('bg_exclude_topk', 3))
        ex_slots = [f'_ex{i}_{j}' for i in range(len(bg_ex)) for j in range(bg_exclude_topk)]
        all_names = names + ex_slots
        all_prompts = prompts + bg_ex

        idxs, times, frames, fps, total = _sample_frames(clip_path, sample_fps)
        if len(frames) < 2:
            out['error'] = f'only {len(frames)} frames decoded'
            return out
        H, W = frames[0].shape[:2]
        area_px = float(H * W)
        out['clip'] = {'fps': round(fps, 3), 'frames': total, 'sampled': len(frames), 'w': W, 'h': H, 'stride': stride}

        # bin sampled frames into context windows
        bins = {}
        for k, fi in enumerate(idxs):
            bins.setdefault(fi // stride, []).append(k)
        win_ids = sorted(bins)
        log(
            f'[continuity_qc] {os.path.basename(clip_path)}: {len(frames)} sampled '
            f'frames / {total} @ {fps:.1f}fps → {len(win_ids)} context windows '
            f'(stride {stride}) on {dev}'
        )

        gdino = _load_gdino(dev, log_fn=log)
        sam2 = _load_sam2(dev, log_fn=log)
        dino = _load_dino(dev, log_fn=log)

        # per-sampled-frame state
        masks_all = {n: [None] * len(frames) for n in all_names}
        win_rec = []

        prev_box = {n: None for n in all_names}
        for w in win_ids:
            ks = bins[w]
            k0 = ks[0]
            t0 = time.time()
            det = _detect(gdino, frames[k0], all_prompts, dev, thr['det_score_min'], log_fn=log)
            boxes_px, wboxes = {}, {}
            for n, d in zip(names, det[: len(names)]):
                pick, how = _select_box(d, prev_box[n], thr['det_score_min'])
                sel_score = pick['score'] if pick else 0.0
                sel_box = pick['box'] if pick else None
                found = bool(pick) and sel_score >= thr['det_score_min']
                wboxes[n] = {
                    'found': found,
                    'score': sel_score,
                    'box': sel_box,
                    'assoc': how,
                    'top_score': d['score'],
                    'top_box': d['box'],
                    'n_candidates': len(d.get('candidates') or []),
                }
                if found and sel_box:
                    b = sel_box
                    boxes_px[n] = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
                    prev_box[n] = sel_box
            # background-exclusion prompts: EVERY confident instance (a two-hander
            # needs both actors masked out, and 'person' returns one box per body).
            # No temporal association — these masks are only ever unioned away.
            for i, d in enumerate(det[len(names) :]):
                hits = [c for c in (d.get('candidates') or []) if c['score'] >= thr['det_score_min']][:bg_exclude_topk]
                for j, c in enumerate(hits):
                    slot = f'_ex{i}_{j}'
                    b = c['box']
                    boxes_px[slot] = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
                    wboxes[slot] = {
                        'found': True,
                        'score': c['score'],
                        'box': b,
                        'assoc': 'exclude',
                        'top_score': d['score'],
                        'top_box': d['box'],
                        'n_candidates': len(hits),
                    }
            wr = {
                'window': int(w),
                'frame': idxs[k0],
                't': round(times[k0], 2),
                'n_frames': len(ks),
                'detections': wboxes,
            }
            if boxes_px:
                mk = _track_window(sam2, [frames[k] for k in ks], boxes_px, dev)
                for n, mlist in mk.items():
                    for j, k in enumerate(ks):
                        masks_all[n][k] = mlist[j]
            wr['secs'] = round(time.time() - t0, 1)
            win_rec.append(wr)
            log(
                f'[continuity_qc]   window {w} @ {wr["t"]}s: '
                + ', '.join(f'{n}={wboxes[n]["score"]:.2f}[{wboxes[n]["assoc"]}]' for n in all_names if n in wboxes)
                + f' ({wr["secs"]}s)'
            )

        # ── per-object appearance embeddings over the whole clip ──────────────
        for n in names:
            crops, masked, kk = [], [], []
            for k in range(len(frames)):
                m = masks_all[n][k]
                if m is None or m.sum() < thr['min_mask_frac'] * area_px:
                    continue
                c, cm = _crops(frames[k], m)
                if c is None:
                    continue
                crops.append(c)
                masked.append(cm)
                kk.append(k)
            embs = _embed(dino, crops, dev) if crops else np.zeros((0, 384), 'float32')
            embs_m = _embed(dino, masked, dev) if masked else embs
            rec = {
                'name': n,
                'ground_prompt': prompts[names.index(n)],
                'n_present': len(kk),
                'n_sampled': len(frames),
                'series': [],
            }
            for j, k in enumerate(kk):
                m = masks_all[n][k]
                cos_first = float(embs[j] @ embs[0]) if len(embs) else 0.0
                cos_prev = float(embs[j] @ embs[j - 1]) if j > 0 else 1.0
                rec['series'].append(
                    {
                        't': round(times[k], 2),
                        'frame': idxs[k],
                        'window': idxs[k] // stride,
                        'area_frac': round(float(m.sum()) / area_px, 5),
                        'cos_first': round(cos_first, 4),
                        'cos_prev': round(cos_prev, 4),
                        'cos_first_masked': round(float(embs_m[j] @ embs_m[0]), 4) if len(embs_m) else 0.0,
                    }
                )
            rec['anchor'] = _anchor_cosines(embs, embs_m, kk, idxs, stride)
            out['objects'][n] = rec

        # ── background: inverse of the union of all object masks ─────────────
        import cv2

        kern = np.ones((9, 9), np.uint8)
        bg_imgs, bg_ks = [], []
        for k in range(len(frames)):
            union = np.zeros((H, W), dtype=bool)
            for n in all_names:
                m = masks_all[n][k]
                if m is not None:
                    union |= m
            union = cv2.dilate(union.astype(np.uint8), kern) > 0
            img = frames[k].copy()
            img[union] = 0
            bg_imgs.append(img)
            bg_ks.append(k)
        bg_emb = _embed(dino, bg_imgs, dev)
        bg_series = []
        for j, k in enumerate(bg_ks):
            bg_series.append(
                {
                    't': round(times[k], 2),
                    'frame': idxs[k],
                    'window': idxs[k] // stride,
                    'cos_first': round(float(bg_emb[j] @ bg_emb[0]), 4),
                    'cos_prev': round(float(bg_emb[j] @ bg_emb[j - 1]), 4) if j > 0 else 1.0,
                }
            )
        bg_anchor = _anchor_cosines(bg_emb, bg_emb, bg_ks, idxs, stride)
        out['background'] = _verdict_background(bg_series, bg_anchor, thr)

        # ── per-window aggregation + verdicts ─────────────────────────────────
        for n in names:
            out['objects'][n] = _verdict_object(out['objects'][n], win_rec, thr, n)

        out['windows'] = win_rec
        checks = []
        for n in names:
            o = out['objects'][n]
            checks.append(
                {
                    'check': f'continuity:{n}',
                    'verdict': o['verdict'],
                    'ok': o['ok'],
                    'presence_rate': o['presence_rate'],
                    'min_cos_first': o['min_cos_first'],
                    'worst_seam_cos': o['worst_seam_cos'],
                    'worst_seam_t': o['worst_seam_t'],
                    'worst_area_drift_pct': o['worst_area_drift_pct'],
                    'min_box_iou': o['min_box_iou'],
                    'note': o['note'],
                }
            )
            _gate(run_id, f'continuity:{n}', o['ok'], score=o['min_cos_first'], tag=o['verdict'])
        b = out['background']
        checks.append(
            {
                'check': 'continuity:background',
                'ok': b['ok'],
                'verdict': b['verdict'],
                'min_cos_first': b['min_cos_first'],
                'worst_seam_cos': b['worst_seam_cos'],
                'worst_seam_t': b['worst_seam_t'],
                'note': b['note'],
            }
        )
        _gate(run_id, 'continuity:background', b['ok'], score=b['min_cos_first'], tag=b['verdict'])
        out['checks'] = checks
        out['ok'] = all(c['ok'] for c in checks)
        out['block'] = (not out['ok']) and not shadow
        out['secs'] = round(time.time() - t_start, 1)
        log(
            f'[continuity_qc] {os.path.basename(clip_path)} → '
            f'{"PASS" if out["ok"] else "FAIL"} in {out["secs"]}s '
            f'({"shadow" if shadow else "blocking"})'
        )
    except Exception as e:
        out['error'] = str(e)[:300]
        out['ok'] = True  # fail-safe: broken QC never blocks generation
        out['block'] = False
        log(f'[continuity_qc] ERROR (fail-safe pass): {e}')
    return out


def _wget(d, w):
    """Window-keyed lookup that survives a JSON round-trip (int keys become str),
    so a stored report can be re-scored against new thresholds without re-running
    the models."""
    if not d:
        return {}
    return d.get(w) or d.get(str(w)) or {}


def _anchor_cosines(embs, embs_masked, kk, idxs, stride):
    """Per-window appearance anchors.

    seam_cos is the cosine between the LAST sampled frame before a context-window
    boundary and the FIRST one after it — those two frames are ~0.5 s apart at
    sample_fps=2, so anything they disagree about is the chain re-imagining the
    object, not the scene legitimately evolving. (Comparing window *anchors*
    instead would straddle several seconds of honest motion and drown the signal.)
    cos_first is the VBench subject-consistency metric: cosine to the frame-0 crop,
    which tracks slow cumulative drift rather than the seam step."""
    first_j, last_j = {}, {}
    for j, k in enumerate(kk):
        w = idxs[k] // stride
        first_j.setdefault(w, j)
        last_j[w] = j
    anchor, wl = {}, sorted(first_j)
    for i, w in enumerate(wl):
        j = first_j[w]
        a = {'cos_first': round(float(embs[j] @ embs[0]), 4) if len(embs) else 0.0}
        if i > 0:
            pj_last = last_j[wl[i - 1]]
            pj_first = first_j[wl[i - 1]]
            a['seam_cos'] = round(float(embs[j] @ embs[pj_last]), 4)
            a['seam_cos_masked'] = round(float(embs_masked[j] @ embs_masked[pj_last]), 4) if len(embs_masked) else 0.0
            a['cos_prev_window'] = round(float(embs[j] @ embs[pj_first]), 4)
            a['seam_gap_frames'] = int(idxs[kk[j]] - idxs[kk[pj_last]])
        anchor[w] = a
    return anchor


def _verdict_object(rec, win_rec, thr, name):
    """Fold the per-frame series + per-window detections into one verdict."""
    import numpy as np

    ser = rec['series']
    n_sampled = max(1, rec['n_sampled'])
    rec['presence_rate'] = round(rec['n_present'] / n_sampled, 3)

    # per-window aggregates
    by_win = {}
    for s in ser:
        by_win.setdefault(s['window'], []).append(s)
    wins = sorted(by_win)
    rec['per_window'] = []
    anchor = rec.get('anchor') or {}
    seam_cos, seam_area, seam_iou = [], [], []
    prev = None
    for w in wins:
        rows = by_win[w]
        a0 = rows[0]
        det = next((r['detections'].get(name) for r in win_rec if r['window'] == w), None)
        agg = {
            'window': w,
            't': a0['t'],
            'det_score': (det or {}).get('score', 0.0),
            'box': (det or {}).get('box'),
            'assoc': (det or {}).get('assoc'),
            'mean_area_frac': round(float(np.mean([r['area_frac'] for r in rows])), 5),
            'anchor_cos_first': _wget(anchor, w).get('cos_first', a0['cos_first']),
            'n_frames': len(rows),
        }
        if prev is not None:
            d_area = agg['mean_area_frac'] - prev['mean_area_frac']
            agg['area_drift_pct'] = round(100.0 * d_area / max(1e-9, prev['mean_area_frac']), 1)
            agg['box_iou_prev'] = round(_iou(agg['box'], prev['box']), 3)
            # across-the-boundary DINOv2 cosine (last-before → first-after)
            a = _wget(anchor, w)
            agg['seam_cos'] = a.get('seam_cos', min(agg['anchor_cos_first'], prev['anchor_cos_first']))
            agg['seam_cos_masked'] = a.get('seam_cos_masked')
            agg['seam_gap_frames'] = a.get('seam_gap_frames')
            agg['cos_prev_window'] = a.get('cos_prev_window')
            seam_cos.append((agg['seam_cos'], agg['t']))
            seam_area.append((abs(agg['area_drift_pct']), agg['t']))
            seam_iou.append((agg['box_iou_prev'], agg['t']))
        rec['per_window'].append(agg)
        prev = agg

    rec['min_cos_first'] = round(min([s['cos_first'] for s in ser], default=1.0), 4)
    rec['mean_cos_first'] = round(float(np.mean([s['cos_first'] for s in ser])) if ser else 1.0, 4)
    rec['mean_cos_prev'] = round(float(np.mean([s['cos_prev'] for s in ser])) if ser else 1.0, 4)
    worst = min(seam_cos, default=(1.0, None))
    rec['worst_seam_cos'] = round(worst[0], 4)
    rec['worst_seam_t'] = worst[1]
    wa = max(seam_area, default=(0.0, None))
    rec['worst_area_drift_pct'] = round(wa[0], 1)
    rec['worst_area_drift_t'] = wa[1]
    wi = min(seam_iou, default=(1.0, None))
    rec['min_box_iou'] = wi[0]
    rec['min_box_iou_t'] = wi[1]

    # flags first, then a fixed severity order — an object that BOTH vanishes and
    # drifts must be reported as vanished (the worse failure), never masked by the
    # last matching branch.
    notes, flags = [], []
    if rec['presence_rate'] < thr['presence_rate_min']:
        flags.append('vanished')
        notes.append(f'present in only {rec["presence_rate"]:.0%} of sampled frames (< {thr["presence_rate_min"]:.0%})')
    if rec['worst_seam_cos'] < thr['dino_seam_cos_min'] or rec['min_cos_first'] < thr['dino_anchor_min']:
        flags.append('appearance-drift')
        notes.append(
            f'DINOv2 seam cosine {rec["worst_seam_cos"]:.3f} @ '
            f'{rec["worst_seam_t"]}s (min {thr["dino_seam_cos_min"]}), '
            f'frame-0 anchor cosine {rec["min_cos_first"]:.3f} '
            f'(min {thr["dino_anchor_min"]})'
        )
    if rec['worst_area_drift_pct'] > thr['area_drift_pct_max'] or rec['min_box_iou'] < thr['box_iou_min']:
        flags.append('resized')
        notes.append(
            f'mask-area drift {rec["worst_area_drift_pct"]:.0f}% @ '
            f'{rec["worst_area_drift_t"]}s (max {thr["area_drift_pct_max"]}%), '
            f'box IoU {rec["min_box_iou"]:.2f} @ {rec["min_box_iou_t"]}s '
            f'(min {thr["box_iou_min"]})'
        )
    rec['flags'] = flags
    rec['verdict'] = next((v for v in ('vanished', 'appearance-drift', 'resized') if v in flags), 'present')
    rec['ok'] = not flags
    rec['note'] = '; '.join(notes)
    return rec


def _verdict_background(series, anchor, thr):
    """Inverse-mask (props blacked out) whole-frame DINOv2 consistency. Gates on the
    DIRECT window-anchor→window-anchor cosine — a set that is quietly re-derived
    between context windows shows a step there, whereas slow global grade creep only
    depresses the frame-0 cosine (reported, gated far more loosely)."""
    import numpy as np

    rec = {'series': series, 'n': len(series)}
    rec['min_cos_first'] = round(min([s['cos_first'] for s in series], default=1.0), 4)
    rec['mean_cos_first'] = round(float(np.mean([s['cos_first'] for s in series])) if series else 1.0, 4)
    by_win = {}
    for s in series:
        by_win.setdefault(s['window'], []).append(s)
    per, seam = [], []
    for w in sorted(by_win):
        a = _wget(anchor, w)
        row = {'window': w, 't': by_win[w][0]['t'], 'anchor_cos_first': a.get('cos_first', by_win[w][0]['cos_first'])}
        if 'seam_cos' in a:
            row['seam_cos'] = a['seam_cos']
            row['seam_gap_frames'] = a.get('seam_gap_frames')
            seam.append((a['seam_cos'], row['t']))
        per.append(row)
    worst = min(seam, default=(1.0, None))
    rec['per_window'] = per
    rec['worst_seam_cos'] = round(worst[0], 4)
    rec['worst_seam_t'] = worst[1]
    ok = rec['worst_seam_cos'] >= thr['bg_seam_cos_min'] and rec['min_cos_first'] >= thr['bg_anchor_min']
    rec['verdict'] = 'stable' if ok else 'bg-rederivation'
    rec['ok'] = bool(ok)
    rec['note'] = (
        ''
        if ok
        else (
            f'background seam cosine {rec["worst_seam_cos"]:.3f} @ {rec["worst_seam_t"]}s '
            f'(min {thr["bg_seam_cos_min"]}), frame-0 cosine {rec["min_cos_first"]:.3f} '
            f'(min {thr["bg_anchor_min"]})'
        )
    )
    return rec
