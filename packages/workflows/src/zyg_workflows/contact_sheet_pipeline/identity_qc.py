# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ArcFace identity QC over the exported tiles.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 4084-4420).
"""

from __future__ import annotations

import os
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.layout import (
    _angle_label,
    identity_anchor_face_path,
    identity_profile_anchor_face_path,
    load_manifest,
)


_VIS_ORDER = {'frontal': 0, 'pitch': 0, 'full_body': 1, 'oblique': 1, 'profile': 2, 'back': 3}


def _nearest_passing_reference(tiles: list[dict], tile: dict) -> str | None:
    """Runway-style chaining (2026-07-16): the PASSING cell nearest in view
    class to this tile, never farther from frontal than the target. A smaller
    pose delta gives the edit model less to hallucinate on retry. Full-body
    cells never serve as the reference — their faces are too small to carry
    identity through a qwen edit."""
    tv = _VIS_ORDER.get(tile.get('identity_visibility') or 'frontal', 0)
    cands: list[tuple[int, float, str]] = []
    for o in tiles:
        if o is tile or not o.get('path') or not os.path.isfile(o.get('path') or ''):
            continue
        if o.get('identity_visibility') == 'full_body':
            continue
        if o.get('vlm_flag') or o.get('identity_verdict') not in ('pass', 'no_face_expected'):
            continue
        ov = _VIS_ORDER.get(o.get('identity_visibility') or 'frontal', 0)
        if ov > tv:
            continue
        sc = o.get('identity_score')
        sc = float(sc) if isinstance(sc, (int, float)) else 0.0
        cands.append((tv - ov, -sc, o['path']))
    return min(cands)[2] if cands else None


def _anchor_skin_luma(path: str) -> float | None:
    """Mean green-channel over the central SKIN band of an anchor face crop
    (2026-07-21). The luminance gate must measure SKIN brightness, not the whole
    crop: extract_anchor_face pads ~1.4x extra headroom on top for hair, so a
    fair face with dark hair averages down to ~130 over the full crop and
    false-trips the fair floor. Sample a central rectangle (cheeks/nose/mouth
    band) that is skin-dominant for a centred crop, avoiding the top hair band,
    the neck/collar, and the side background. Returns None if unmeasurable.
    """
    try:
        from PIL import Image as _PILImg
        import numpy as _np

        img = _PILImg.open(path).convert('RGB')
        w, h = img.size
        if w < 40 or h < 40:
            return None
        # Horizontal 30-70% (central face), vertical 45-72% (below the hair
        # headroom, above the neck): the cheek/nose band of a face-with-headroom
        # crop, reliably skin for a centred anchor.
        x0, x1 = int(0.30 * w), int(0.70 * w)
        y0, y1 = int(0.45 * h), int(0.72 * h)
        patch = _np.asarray(img.crop((x0, y0, x1, y1)), dtype=_np.float64)
        if patch.size == 0:
            return None
        return float(patch[:, :, 1].mean())
    except Exception:
        return None


def _tile_texture_score(path: str, bbox: list | None) -> float | None:
    """Cheek-band Laplacian variance — a micro-texture proxy for the texture
    QC gate. Scores two cheek patches (rows 52-72% of the face bbox, left and
    right thirds) rather than the whole bbox: eyes/brows/lips dominate
    full-bbox variance and invert the metric on small faces. Requires a face
    bbox at least 120px wide — below that pores are sub-pixel and whole-image
    variance measures background/clothing edges, not skin. Calibrated on run
    e58b9137bdc5: waxy cheeks 20-33, textured cells 60-200, anchor cheek ~122,
    mannequin-grade ~4. Returns None when unmeasurable.
    """
    if not bbox or len(bbox) != 4:
        return None
    try:
        import numpy as _np
        from PIL import Image as _PILImg

        x0, y0, x1, y1 = (int(v) for v in bbox)
        bw = x1 - x0
        bh = y1 - y0
        if bw < 120 or bh < 120:
            return None
        img = _PILImg.open(path).convert('L')
        w, h = img.size

        def _patch_var(cx0: float, cx1: float, cy0: float = 0.52, cy1: float = 0.72) -> float | None:
            px0 = max(0, int(x0 + cx0 * bw))
            px1 = min(w, int(x0 + cx1 * bw))
            py0 = max(0, int(y0 + cy0 * bh))
            py1 = min(h, int(y0 + cy1 * bh))
            if (px1 - px0) < 16 or (py1 - py0) < 16:
                return None
            a = _np.asarray(img.crop((px0, py0, px1, py1)), dtype=_np.float64)
            lap = -4.0 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
            return float(lap.var())

        # 3-region sampling (2026-07-18, was cheeks only): forehead and chin
        # bands catch waxy renders whose cheeks happen to carry hair strands or
        # shadow edges (false texture).
        cheeks = [v for v in (_patch_var(0.10, 0.34), _patch_var(0.66, 0.90)) if v is not None]
        if not cheeks:
            return None
        cheek_score = sum(cheeks) / len(cheeks)
        aux = [
            v
            for v in (
                _patch_var(0.30, 0.70, 0.06, 0.20),  # forehead band
                _patch_var(0.35, 0.65, 0.82, 0.96),  # chin band
            )
            if v is not None
        ]
        if not aux:
            return cheek_score
        _mode = os.environ.get('ZYG_TEXTURE_QC_REGION_MODE', 'min').strip().lower()
        if _mode == 'blend':
            return 0.7 * cheek_score + 0.3 * min(aux)
        # 'min' default since 2026-07-19: the 0.7/0.3 blend let a smeared
        # forehead at variance 10 pass behind crisp cheeks at 160 (≈115
        # blended) on run 0cc9541b. The worst region IS the defect — score it.
        # Revert with ZYG_TEXTURE_QC_REGION_MODE=blend if bangs/shadow rolls
        # over-exclude in practice.
        return min(cheek_score, min(aux))
    except Exception:
        return None


def run_identity_qc(
    char_id: str,
    params: dict,
    tiles: list[dict],
    *,
    model_family: str = 'flux',
    log_fn: Callable[[str], None] | None = None,
    progress_job: dict | None = None,
    halt_check: Callable[[], None] | None = None,
    allow_regen: bool = True,
) -> tuple[list[dict], dict]:
    """
    ArcFace drift gate: score every tile against the identity anchor, regenerate
    drifted cells (fail, or frontal with no detectable face), and flag hard
    failures for dataset exclusion. Non-fatal by design — any missing dependency
    degrades to a logged skip. Returns (tiles, summary_dict).
    """
    if os.environ.get('ZYG_CONTACT_SHEET_IDQC', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return tiles, {'skipped': 'disabled via ZYG_CONTACT_SHEET_IDQC=0'}
    try:
        from zyg_workflows import identity_qc_service as _idqc
    except ImportError as exc:
        return tiles, {'skipped': f'identity_qc_service unavailable ({exc})'}
    ok, reason = _idqc.available()
    if not ok:
        if log_fn:
            log_fn(f'Identity QC skipped — {reason}')
        return tiles, {'skipped': reason}

    from zyg_workflows import contact_sheet_pipeline_steps as _steps

    manifest = load_manifest(char_id) or {}
    anchor = manifest.get('identity_anchor_face') or identity_anchor_face_path(char_id)
    if not anchor or not os.path.isfile(anchor):
        front = next((t for t in tiles if t.get('path') and os.path.isfile(t['path'])), None)
        if not front:
            return tiles, {'skipped': 'no anchor face and no tiles'}
        anchor = front['path']
        if log_fn:
            log_fn('Identity QC: anchor face missing — using first tile as anchor')

    items = [
        {'path': t['path'], 'angle': t.get('angle') or _angle_label(int(t.get('index', 0)))}
        for t in tiles
        if t.get('path') and os.path.isfile(t['path'])
    ]
    if not items:
        return tiles, {'skipped': 'no tile images on disk'}

    report = _idqc.score_images_against_anchor(
        anchor,
        items,
        profile_anchor_path=identity_profile_anchor_face_path(char_id),
        log_fn=log_fn,
    )
    if not report.get('ok'):
        # Mock sheets / corrupt anchors land here — pipeline continues untouched.
        if log_fn:
            log_fn(f'Identity QC skipped — {report.get("reason")}')
        return tiles, {'skipped': report.get('reason')}

    for t in tiles:
        r = report['results'].get(t.get('path') or '')
        if not r:
            continue
        t['identity_score'] = r['score']
        t['identity_verdict'] = r['verdict']
        t['identity_visibility'] = r['visibility']
        t['face_detected'] = r['face_detected']
        t['faces_count'] = r.get('faces_count')
        t['face_yaw'] = r.get('yaw')

    fail_class = tuple(getattr(_idqc, 'FAIL_CLASS', ('fail',)))

    # QC budget scaling (2026-08-09): corpus sheets run 70-240 cells, so every
    # absolute per-run QC budget keeps its calibrated value at 48 cells and
    # grows proportionally with cell_count/48. An env var that is explicitly
    # SET stays an absolute override, exactly as before. (The pass-rate valve
    # thresholds are fractions and need no scaling.)
    _qc_scale = max(1.0, len(tiles) / 48.0)

    _idqc_retries = max(1, _steps.scaled_budget('ZYG_CONTACT_SHEET_IDQC_MAX_RETRIES', 2, _qc_scale))
    if _qc_scale > 1.0 and log_fn:
        log_fn(
            f'QC budgets scaled ×{_qc_scale:.2f} for {len(tiles)} cells — '
            f'regen retries {_idqc_retries}, '
            f'drift cap {_steps.scaled_budget("ZYG_IDQC_DRIFT_MAX", 10, _qc_scale)}, '
            f'attr samples {_steps.scaled_budget("ZYG_IDQC_ATTR_SAMPLES", 2, _qc_scale)}',
        )

    to_fix = [t for t in tiles if _steps.needs_regen(t, fail_class)]

    _steps.step_regen_circuit_breaker(char_id, tiles, allow_regen, log_fn)

    _vlm, _vlm_anchor_cell, _vlm_refixed = _steps.step_vlm_judge(
        char_id,
        tiles,
        fail_class=fail_class,
        qc_scale=_qc_scale,
        progress_job=progress_job,
        halt_check=halt_check,
        log_fn=log_fn,
    )
    if _vlm_refixed is not None:
        to_fix = _vlm_refixed

    regen_ok = _steps.step_regen_drifted(
        char_id,
        params,
        to_fix,
        anchor=anchor,
        report=report,
        fail_class=fail_class,
        model_family=model_family,
        idqc_retries=_idqc_retries,
        idqc=_idqc,
        vlm=_vlm,
        vlm_anchor_cell=_vlm_anchor_cell,
        tiles=tiles,
        allow_regen=allow_regen,
        progress_job=progress_job,
        halt_check=halt_check,
        log_fn=log_fn,
    )

    _steps.step_texture_qc(tiles, report, log_fn)

    train_floor = float(os.environ.get('ZYG_CONTACT_SHEET_TRAIN_MIN_SCORE', '0.32'))
    excluded, weak_train, _mislabel_kept = _steps.step_dataset_exclusions(
        tiles,
        fail_class=fail_class,
        train_floor=train_floor,
        log_fn=log_fn,
    )

    _drift_dropped = _steps.step_drift_gate(
        tiles,
        report=report,
        vlm=_vlm,
        vlm_anchor_cell=_vlm_anchor_cell,
        allow_regen=allow_regen,
        train_floor=train_floor,
        qc_scale=_qc_scale,
        halt_check=halt_check,
        log_fn=log_fn,
    )

    summary = _steps.step_qc_summary(
        char_id,
        tiles,
        anchor=anchor,
        report=report,
        fail_class=fail_class,
        regen_ok=regen_ok,
        excluded=excluded,
        weak_train=weak_train,
        drift_dropped=_drift_dropped,
        progress_job=progress_job,
        log_fn=log_fn,
    )
    return tiles, summary


def _dhash64(image) -> int | None:
    """Pure-PIL perceptual dHash (2026-08-09): grayscale 9×8 downscale,
    horizontal gradient bits → 64-bit int. *image* is a path or a PIL image.
    No new dependencies by design."""
    try:
        from PIL import Image as _PILImg

        img = image if hasattr(image, 'convert') else _PILImg.open(image)
        img = img.convert('L').resize((9, 8), _PILImg.LANCZOS)
        px = list(img.getdata())
        bits = 0
        for r in range(8):
            row = r * 9
            for c in range(8):
                bits = (bits << 1) | (1 if px[row + c] > px[row + c + 1] else 0)
        return bits
    except Exception:
        return None


def _hamming64(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count('1')


def _dedup_clusters(hashes: list[int | None], max_hamming: int) -> list[list[int]]:
    """Union-find clustering over dHash values; None hashes stay singleton.
    Returns clusters (index lists) with 2+ members."""
    n = len(hashes)
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        if hashes[i] is None:
            continue
        for j in range(i + 1, n):
            if hashes[j] is None:
                continue
            if _hamming64(hashes[i], hashes[j]) <= max_hamming:
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[rj] = ri
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]
