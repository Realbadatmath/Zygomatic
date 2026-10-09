# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.ink_fx.tunables import INK_SAM2_ENABLED
from zyg_workflows.ink_fx.write_on import _log_noop
import json
import os

import numpy as np
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)


# ── v3: SAM2.1 occlusion matte (2026-07-31) ────────────────────────────────────


def _box_iou(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    ua = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return float(inter / ua)


def _box_overlap_area(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)


def _seed_boxes_gdino(frame_rgb, quad_px, device, log, score_min=0.22, max_objs=4):
    """Auto-seed SAM2 with GroundingDINO boxes for whatever sits IN FRONT of the page.

    Separate prompts per object class on purpose: one box around 'hand holding a quill
    pen' segments the fist and drops the thin quill shaft entirely, so the quill gets
    its own prompt (and, being thin, a much lower page-overlap requirement).
    Returns [(label, [x0,y0,x1,y1] px), ...] or [] — never raises."""
    try:
        from zyg_workflows import continuity_qc as cq
    except Exception as e:  # pragma: no cover
        log(f'[ink] !! GroundingDINO seed unavailable (import: {e})')
        return []
    pb = [
        float(quad_px[:, 0].min()),
        float(quad_px[:, 1].min()),
        float(quad_px[:, 0].max()),
        float(quad_px[:, 1].max()),
    ]
    pb_area = max(1.0, (pb[2] - pb[0]) * (pb[3] - pb[1]))
    H, W = frame_rgb.shape[:2]
    #            prompt                      min page-overlap fraction
    spec = [('hand holding a quill pen', 0.03), ('quill pen', 0.004), ('hand', 0.03), ('shirt cuff', 0.03)]
    try:
        model = cq._load_gdino(device, log_fn=log)
        res = cq._detect(model, frame_rgb, [p for p, _ in spec], device, score_min, topk=6, log_fn=log)
    except Exception as e:
        log(f'[ink] !! GroundingDINO seed failed ({e}) — no occlusion seeds')
        return []
    kept = []
    for (prompt, min_ov), r in zip(spec, res):
        for c in r.get('candidates') or []:
            if len(kept) >= max_objs:
                break
            if float(c.get('score', 0)) < score_min or not c.get('box'):
                continue
            b = [c['box'][0] * W, c['box'][1] * H, c['box'][2] * W, c['box'][3] * H]
            area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
            if area > 8.0 * pb_area:  # frame-wide box: useless prompt
                continue
            if _box_overlap_area(b, pb) < min_ov * pb_area:
                continue  # not actually over the page
            if any(_box_iou(b, k[1]) >= 0.55 for k in kept):
                continue
            kept.append((prompt, [round(v, 1) for v in b]))
    log(f'[ink] occluder seeds: {kept}')
    return kept


def _paper_points(quad_px, boxes_px, W, H, k=2):
    """Negative SAM2 points on BARE paper — the k page-interior points farthest from
    every seed box. Without them a hand box that happens to include a lot of page
    lets SAM2 swallow the page itself, and the matte erases all the ink."""
    import cv2

    poly = np.zeros((H, W), dtype=np.uint8)
    cv2.fillConvexPoly(poly, np.round(quad_px).astype(np.int32), 1)
    free = poly.copy()
    for b in boxes_px:
        x0, y0 = max(0, int(round(b[0]))), max(0, int(round(b[1])))
        x1, y1 = min(W, int(round(b[2])) + 1), min(H, int(round(b[3])) + 1)
        free[y0:y1, x0:x1] = 0
    pts = []
    if int(free.sum()) == 0:
        return pts
    d = cv2.distanceTransform(free, cv2.DIST_L2, 3)
    for _ in range(k):
        idx = int(np.argmax(d))
        y, x = divmod(idx, W)
        if d[y, x] <= 0.5:
            break
        pts.append((float(x), float(y)))
        cv2.circle(d, (x, y), max(6, int(d[y, x])), 0, -1)
    return pts


def _sam2_images_cpu(frames_rgb, image_size):
    """ImageNet-normalised SAM2 input batch kept on the CPU in fp16.

    The vendored predictor does `images[i].to(device).float()` per frame, so holding
    341 frames of 1024x1024 on the GPU (4.3 GB fp32) buys nothing — fp16 on CPU is
    2.1 GB of host RAM and zero VRAM."""
    import cv2
    import torch

    mean = torch.tensor([0.485, 0.456, 0.406])[:, None, None]
    std = torch.tensor([0.229, 0.224, 0.225])[:, None, None]
    out = torch.empty((len(frames_rgb), 3, image_size, image_size), dtype=torch.float16)
    for i, f in enumerate(frames_rgb):
        r = cv2.resize(f, (image_size, image_size), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        t = torch.from_numpy(r).permute(2, 0, 1)
        out[i] = ((t - mean) / std).half()
    return out


def _matte_device(log):
    """cuda only when the GPU is genuinely idle AND has headroom. We never queue a
    ComfyUI job, never /free, never kill — if ComfyUI is sampling we take the slow
    CPU path rather than compete for VRAM with a render."""
    try:
        from zyg_workflows import comfy_offload

        if comfy_offload.comfy_is_sampling():
            log('[ink] SAM2 on CPU — ComfyUI is sampling (never compete for VRAM)')
            return 'cpu'
    except Exception as _exc:
        _zyg_log.debug('comfy sampling probe failed, falling back to the device pick: %s', _exc)
    try:
        from zyg_workflows import continuity_qc as cq

        return cq.pick_device('auto', log_fn=log)
    except Exception:
        return 'cpu'


def _matte_signature(clip_path, quad_px, n, W, H, seeds, extra=()):
    try:
        stt = os.stat(clip_path)
        sig = f'{os.path.basename(clip_path)}:{stt.st_size}:{int(stt.st_mtime)}'
    except Exception:
        sig = os.path.basename(clip_path)
    return json.dumps(
        {
            'clip': sig,
            'n': int(n),
            'W': int(W),
            'H': int(H),
            'quad': np.round(quad_px, 2).tolist(),
            'seeds': [[s[0], s[1]] for s in seeds],
            'extra': [float(v) for v in extra],
            'v': 4,
        },
        sort_keys=True,
    )


def occlusion_matte(
    clip_path,
    frames_rgb,
    quad_px,
    cache_path=None,
    log_fn=None,
    dilate_px=3.0,
    blur_sigma=1.5,
    max_objs=4,
    seed_boxes=None,
    return_hard=False,
):
    """SAM2.1 video matte of everything occluding the page. Returns (n,H,W) float32
    in [0,1] — or (soft, hard_bool) when return_hard — or None if SAM2 is unavailable
    (logged LOUDLY — never raises).

    obj 1..k come from `seed_boxes` or GroundingDINO; every object also receives the
    same 1-2 NEGATIVE points on bare paper. The union is dilated by `dilate_px` and
    softened with a `blur_sigma` gaussian so stroke ends tuck under the fingers
    instead of stopping on a hard cut.

    WHY dilate_px defaults to 2*blur_sigma and not the plan's blur-only matte: a bare
    gaussian puts its 0.5 level ON the occluder boundary, so the outermost ~2px of the
    true occluder keep up to half their ink — measured 0.038 violation against a
    <=0.005 gate. Dilating first pushes the ramp entirely outside the occluder, which
    is also the physically right answer (a hand casts a contact shadow, it does not
    end on a razor edge)."""
    log = log_fn or _log_noop
    if not INK_SAM2_ENABLED:
        log('[ink] !! occlusion matte DISABLED by ZYG_INK_SAM2=0 — ink will paint over the writing hand')
        return None
    n = len(frames_rgb)
    H, W = frames_rgb[0].shape[:2]
    try:
        import cv2
        import torch
        from zyg_workflows import continuity_qc as cq
    except Exception as e:
        log(
            f'[ink] !! SAM2 occlusion matte UNAVAILABLE ({e}) — compositing WITHOUT '
            f'occlusion; ~31% of strokes will land on the hand'
        )
        return None
    dev = _matte_device(log)
    seeds = list(seed_boxes or [])
    if not seeds:
        seeds = _seed_boxes_gdino(frames_rgb[0], quad_px, dev, log, max_objs=max_objs)
    if not seeds:
        log('[ink] !! no occluder seeds found — compositing WITHOUT occlusion')
        return None
    cache_path = cache_path or None
    sig = _matte_signature(clip_path, quad_px, n, W, H, seeds, extra=(dilate_px, blur_sigma))
    if cache_path and os.path.exists(cache_path):
        try:
            z = np.load(cache_path, allow_pickle=False)
            if str(z['sig']) == sig and z['matte'].shape == (n, H, W):
                log(f'[ink] occlusion matte loaded from cache {cache_path}')
                soft = z['matte'].astype(np.float32) / 255.0
                if not return_hard:
                    return soft
                hard = np.unpackbits(z['hard']).astype(bool)[: n * H * W]
                return soft, hard.reshape(n, H, W)
            log('[ink] occlusion matte cache stale — recomputing')
        except Exception as e:
            log(f'[ink] occlusion matte cache unreadable ({e}) — recomputing')
    try:
        import time
        from contextlib import nullcontext

        t0 = time.time()
        sam2 = cq._load_sam2(dev, log_fn=log)
        imgs = _sam2_images_cpu(frames_rgb, sam2.image_size)
        neg = _paper_points(quad_px, [b for _, b in seeds], W, H, k=2)
        pts = np.asarray(neg, dtype=np.float32) if neg else None
        lbl = np.zeros((len(neg),), dtype=np.int32) if neg else None
        matte = np.zeros((n, H, W), dtype=bool)
        # WHY autocast: the vendored SAM2 picks its SDPA backend at import time and on
        # Ampere+ that is FLASH_ATTENTION ONLY (math/mem-efficient are compiled out).
        # Flash refuses fp32 q/k/v, so the fp32 loader raises "No available kernel"
        # unless the call runs under bf16 autocast — which is exactly what the kijai
        # ComfyUI node does. CPU keeps the math kernel and needs no autocast.
        amp = torch.autocast('cuda', dtype=torch.bfloat16) if dev == 'cuda' else nullcontext()
        with amp:
            state = sam2.init_state(imgs, H, W, device=dev)
            for oid, (_label, box) in enumerate(seeds, start=1):
                sam2.add_new_points_or_box(
                    inference_state=state,
                    frame_idx=0,
                    obj_id=oid,
                    box=np.asarray(box, dtype=np.float32),
                    points=pts,
                    labels=lbl,
                )
            with torch.inference_mode():
                for fi, out_ids, logits in sam2.propagate_in_video(state):
                    if not (0 <= fi < n):
                        continue
                    for j in range(len(out_ids)):
                        matte[fi] |= (logits[j, 0] > 0).float().cpu().numpy() > 0
        try:
            sam2.reset_state(state)
        except Exception as _exc:
            _zyg_log.debug('sam2 state reset skipped: %s', _exc)
        del imgs, state
        if dev == 'cuda':
            try:
                torch.cuda.empty_cache()
            except Exception as _exc:
                _zyg_log.debug('cuda cache release skipped: %s', _exc)
        cov = float(matte.mean())
        log(
            f'[ink] SAM2 matte: {len(seeds)} objects, {n} frames, {time.time() - t0:.0f}s '
            f'on {dev}, mean frame coverage {cov * 100:.1f}%'
        )
        out = np.empty((n, H, W), dtype=np.float32)
        k = int(max(1, round(dilate_px))) * 2 + 1
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        for i in range(n):
            m = matte[i].astype(np.uint8)
            if dilate_px > 0:
                m = cv2.dilate(m, ker)
            f = m.astype(np.float32)
            out[i] = cv2.GaussianBlur(f, (0, 0), float(blur_sigma)) if blur_sigma > 0 else f
        np.clip(out, 0.0, 1.0, out=out)
        if cache_path:
            try:
                os.makedirs(os.path.dirname(cache_path) or '.', exist_ok=True)
                np.savez_compressed(
                    cache_path, sig=sig, matte=(out * 255.0 + 0.5).astype(np.uint8), hard=np.packbits(matte)
                )
                log(f'[ink] occlusion matte cached -> {cache_path}')
            except Exception as e:
                log(f'[ink] occlusion matte cache write failed ({e}) — continuing')
        return (out, matte) if return_hard else out
    except Exception as e:
        log(
            f'[ink] !! SAM2 occlusion matte FAILED ({type(e).__name__}: {e}) — '
            f'compositing WITHOUT occlusion; ~31% of strokes will land on the hand'
        )
        return None
