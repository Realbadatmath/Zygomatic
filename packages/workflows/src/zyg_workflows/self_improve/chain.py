# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Chain detection by artifact, and keep/pin box recovery.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import os
import re
import logging as _zyg_logging

from zyg_workflows.self_improve.base import _mklog

_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')


# ══════════════════════════════════════════════════════════════════════════════
# 2.  CHAIN DETECTION — which post-process steps actually ran, by artifact
# ══════════════════════════════════════════════════════════════════════════════
#
# Each entry: (step_id, regex over the run-dir basename, human role, param key it
# is controlled by, the value that DISABLES it, consumes_keep_mask).  Order is the
# pipeline order — consecutive detected artifacts are the pairs we diff.
#
# `consumes_keep_mask` is STRUCTURAL knowledge about the pipeline, not about any
# scene: only a step that reads a keep mask can possibly be the step a keep-box
# fact indicts.  Without it, an unrelated destructive link (the upscale/re-encode
# measurably costs motion too) would inherit the pin evidence and the loop would
# recommend deleting the wrong stage.
_CHAIN_SPEC = [
    ('render', r'^vace_static(_[a-z0-9]+)?\.mp4$', 'VACE render (source of truth)', None, None, False),
    ('paste_back_static', r'^pasted\d*\.mp4$', 'static keep-mask paste-back', 'post.paste_back', 'none', True),
    ('paste_back_dynamic', r'^pasted\d*_dyn\.mp4$', 'occluder-aware paste-back', 'post.paste_back', 'none', True),
    ('ink_overlay', r'^inked\d*(_[a-z])?\.mp4$', 'ink/quill overlay', 'post.ink', False, False),
    ('smoke_overlay', r'^smoked\d*(_[a-z])?\.mp4$', 'smoke overlay', 'post.smoke', False, False),
    ('upscale', r'^[a-z0-9]+_\d+fps\.mp4$', 'upscale + re-encode (up_out → *_Nfps)', 'post.upscale', False, False),
    ('deliver', r'^FINAL_.*(?<!_narrated)\.mp4$', 'delivered master (+ frame interp)', None, None, False),
    ('narrate', r'^FINAL_.*_narrated\.mp4$', 'narration mux', 'post.narrate', False, False),
]

# a "variant" is a second artifact for the same step_id family — an alternative
# that was ALREADY TRIED in this run dir.  Measuring it is free evidence.
_STEP_FAMILY = {
    'paste_back_static': 'paste_back',
    'paste_back_dynamic': 'paste_back',
}

# our step ids → the stage vocabulary published in
# config/remedy_kb.json['_signature_contract']['chain'].  Kept as an explicit
# table (not a string transform) so a rename on either side fails loudly here
# rather than silently stopping every chain-conditioned rule from firing.
_CONTRACT_STEP = {
    'render': 'render',
    'paste_back_static': 'pasteback_static',
    'paste_back_dynamic': 'pasteback_dynamic',
    'ink_overlay': 'ink',
    'smoke_overlay': 'smoke',
    'upscale': 'upscale',
    'deliver': 'deliver',
    'narrate': 'narrate',
}


def detect_chain(run_dir, log_fn=None):
    """Which pipeline steps ran, inferred from which intermediate files exist.

    Returns [{'step','family','file','path','role','param_key','disable_value',
              'keep_mask','mtime','order','variant_of'}] in pipeline order, then mtime.
    Variants are grouped by FAMILY, not by step id: pasted17.mp4 (static) and
    pasted17_dyn.mp4 (occluder-aware) are two attempts at the same pipeline slot,
    so the second is marked `variant_of` the first rather than being diffed as if
    it were the next link in the chain.  That is what lets the KB see 'this
    alternative was already tried in this very run and still failed'."""
    log = _mklog(log_fn)
    out = []
    try:
        names = sorted(os.listdir(run_dir))
    except Exception as e:
        log(f'[self_improve] cannot list {run_dir}: {e}')
        return out
    for order, (step, pat, role, pkey, disable, keepmask) in enumerate(_CHAIN_SPEC):
        hits = []
        for n in names:
            if not re.match(pat, n):
                continue
            # a later, more specific spec wins (pasted17_dyn must not also be static)
            better = None
            for s2, p2, *_ in _CHAIN_SPEC:
                if s2 != step and re.match(p2, n) and len(p2) > len(pat):
                    better = s2
            if better:
                continue
            p = os.path.join(run_dir, n)
            if os.path.isfile(p) and os.path.getsize(p) > 1024:
                hits.append((os.path.getmtime(p), n, p))
        hits.sort()
        for mt, n, p in hits:
            out.append(
                {
                    'step': step,
                    'family': _STEP_FAMILY.get(step, step),
                    'file': n,
                    'path': p,
                    'role': role,
                    'param_key': pkey,
                    'disable_value': disable,
                    'keep_mask': bool(keepmask),
                    'mtime': round(mt, 1),
                    'order': order,
                    'variant_of': None,
                }
            )
    out.sort(key=lambda r: (r['order'], r['mtime']))
    first_of_family = {}
    for r in out:
        fam = r['family']
        if fam in first_of_family:
            r['variant_of'] = first_of_family[fam]
        else:
            first_of_family[fam] = r['file']
    main = ' → '.join(f'{r["step"]}({r["file"]})' for r in out if r['variant_of'] is None)
    alts = ', '.join(f'{r["file"]}~{r["step"]}' for r in out if r['variant_of'])
    log('[self_improve] chain: ' + (main or '(empty)') + (f'   [alternatives already tried: {alts}]' if alts else ''))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 3.  KEEP / PIN BOXES — named from metadata, measured from the mask PNG
# ══════════════════════════════════════════════════════════════════════════════


def keep_boxes_from_mask(mask_path, black_thr=8, erode_px=3, min_area_frac=0.002, log_fn=None):
    """Recover the PINNED boxes from a VACE mask PNG.

    METHOD (documented because the numbers depend on it):
      1. The mask is a feathered greyscale: WHITE = generate, BLACK = keep the
         anchor's pixels.  The feather ramp means a naive `< 128` threshold
         floods the whole right half into one blob (measured: 1 component at
         0.44-1.00 x 0.00-1.00, fill 0.35 — useless).
      2. So we threshold hard at `black_thr` (default 8 — the solid core of the
         keep region, before any feather) and erode by `erode_px` to snap the
         thin feather bridges that still join separate pins.
      3. cv2.connectedComponentsWithStats(8-connectivity); components smaller
         than `min_area_frac` of the frame are dropped as feather speckle.
      4. Each surviving component is reported as its FRACTIONAL bounding box
         plus `fill` (area / bbox area) — fill well under 1.0 means the
         component is not a rectangle and its bbox over-claims, which matters
         when we ask "does this pin cover a moving region?".

    On mask_v8.png this yields 2 pins: (0.523,0.000,1.000,0.075) — the top strip
    — and (0.448,0.556,0.829,0.929), the candle+book table pin that turned out
    to swallow Abel's writing hand.

    Returns {'ok', 'boxes': {name: {'box','area_frac','fill','source'}}}."""
    log = _mklog(log_fn)
    out = {
        'ok': False,
        'boxes': {},
        'method': f'threshold<{black_thr} → erode {erode_px}px → 8-conn components ≥ {min_area_frac} frame area',
    }
    try:
        import cv2
        import numpy as np
        from PIL import Image

        a = np.asarray(Image.open(mask_path).convert('L'))
        H, W = a.shape
        keep = (a < black_thr).astype('uint8')
        if erode_px and erode_px > 1:
            keep = cv2.erode(keep, np.ones((int(erode_px), int(erode_px)), np.uint8))
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(keep, 8)
        idx = 0
        for i in range(1, n):
            x, y, w, h, area = [int(v) for v in stats[i]]
            if area < min_area_frac * H * W:
                continue
            idx += 1
            out['boxes'][f'mask_pin{idx}'] = {
                'box': [round(x / W, 3), round(y / H, 3), round((x + w) / W, 3), round((y + h) / H, 3)],
                'area_frac': round(area / float(H * W), 4),
                'fill': round(area / float(max(1, w * h)), 3),
                'source': f'mask:{os.path.basename(mask_path)}',
            }
        out['ok'] = True
        log(f'[self_improve] mask pins: {len(out["boxes"])} from {os.path.basename(mask_path)}')
    except Exception as e:
        out['error'] = str(e)[:200]
        log(f'[self_improve] keep_boxes_from_mask failed: {e}')
    return out


def keep_boxes_from_metadata(meta, log_fn=None):
    """Named pinned boxes from shot_metadata.json: every `*_box` key holding four
    fractional numbers (candle_box, book_box, page_box ...).  `*_pin` 2-tuples are
    points, not boxes — carried as zero-size boxes for provenance only."""
    boxes = {}
    for k, v in (meta or {}).items():
        try:
            if k.endswith('_box') and isinstance(v, (list, tuple)) and len(v) == 4:
                b = [float(x) for x in v]
                if all(0.0 <= x <= 1.0 for x in b) and b[2] > b[0] and b[3] > b[1]:
                    boxes[k] = {
                        'box': [round(x, 3) for x in b],
                        'area_frac': round((b[2] - b[0]) * (b[3] - b[1]), 4),
                        'fill': 1.0,
                        'source': 'shot_metadata',
                    }
        except Exception as _exc:
            _zyg_log.debug('metadata key %s is not a usable box: %s', k, _exc)
            continue
    _mklog(log_fn)(f'[self_improve] metadata pins: {sorted(boxes)}')
    return boxes


def _box_iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    ub = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = ua + ub - inter
    return (inter / union if union > 0 else 0.0), (inter / ua if ua > 0 else 0.0)


def _box_subtract_note(keep, region):
    """The keep box with the moving region carved out, expressed as the largest
    axis-aligned remainder strips.  Used by the shrink-the-pin remedy so a driver
    gets concrete numbers rather than 'make it smaller'."""
    kx0, ky0, kx1, ky1 = keep
    rx0, ry0, rx1, ry1 = region
    strips = []
    if ry0 > ky0:
        strips.append([kx0, ky0, kx1, round(min(ry0, ky1), 3)])  # above
    if ry1 < ky1:
        strips.append([kx0, round(max(ry1, ky0), 3), kx1, ky1])  # below
    if rx0 > kx0:
        strips.append([kx0, ky0, round(min(rx0, kx1), 3), ky1])  # left
    if rx1 < kx1:
        strips.append([round(max(rx1, kx0), 3), ky0, kx1, ky1])  # right
    strips = [s for s in strips if s[2] - s[0] > 0.02 and s[3] - s[1] > 0.02]
    strips.sort(key=lambda s: (s[2] - s[0]) * (s[3] - s[1]), reverse=True)
    return strips[:2]
