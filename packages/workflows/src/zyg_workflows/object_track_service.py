# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4.1 — Object tracking compositing.

After WAN generates video clips, this service runs YOLOv8 object tracking on
each clip to detect identity drift and weapon/object disappearance, then
composites the missing objects back from the reference FLUX source image.

Detected object classes that matter for documentary combat/character scenes:
  - person (class 0)
  - knife / sword (class 43)
  - scissors / bladed tool (class 76)
  - sports equipment (many classes used as proxy for weapons in stylised content)

The compositor:
  1. Runs YOLOv8 ``track()`` on every frame of the clip
  2. Identifies the reference bounding box for each object ID from the frame
     where it appears most confidently
  3. For any consecutive-frame window where the object is missing (dropped below
     ``MIN_CONFIDENCE`` for ``MISS_THRESHOLD`` frames), replaces the missing
     region with a crop from the FLUX source image blended onto the current frame
  4. Writes the repaired clip to ``<clip_stem>_tracked.mp4``

Usage
-----
    from zyg_workflows import object_track_service as ots
    updated_clips = ots.process_clips(
        wan_clips,        # list[dict] from Stage 4/WAN
        flux_image_meta,  # list[dict] from Stage 3.5 (source images)
        out_dir,          # pipeline run output directory
        log_fn=lambda m: print(m),
    )
    # updated_clips[i]['path'] may point to tracked/repaired clip
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable

import cv2
import numpy as np
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────
_YOLO_MODEL = 'yolov8n.pt'  # nano — fast; auto-downloaded on first use
_MIN_CONFIDENCE = 0.40  # below this confidence → object "missing"
_MISS_THRESHOLD = 10  # frames missing before compositing kicks in

# Person (class 0) intentionally excluded: natural animation causes false
# "disappearances" (hand deformations, partial occlusion, motion blur) that
# the compositor cannot safely repair — it pastes the static source image
# crop over the animated frame, producing a visible hard-edged stamp.
# Only track rigid objects that genuinely disappear due to WAN hallucination.
_TRACKED_CLASSES = {
    43: 'knife',
    76: 'scissors',
    32: 'sports ball',  # proxy for round projectiles
    39: 'bottle',  # proxy for glass weapons
}

_yolo_model_cache = None


# ── Public API ────────────────────────────────────────────────────────────────


def process_clips(
    wan_clips: list[dict],
    flux_image_meta: list[dict],
    out_dir: str,
    log_fn: Callable[[str], None] | None = None,
) -> list[dict]:
    """Run tracking + compositing on all WAN clips.

    Parameters
    ----------
    wan_clips : list[dict]
        Each entry: ``{path, source_image, index, slot_seconds, subject, prompt}``
    flux_image_meta : list[dict]
        Stage 3.5 output — used to retrieve reference images by ``index``.
    out_dir : str
        Pipeline run output directory.  Repaired clips go into ``wan_clips/``.
    log_fn : callable | None

    Returns
    -------
    list[dict]  Updated clips list.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not wan_clips:
        _log('Stage 4.1: no WAN clips — tracking skipped')
        return wan_clips

    _log(f'Stage 4.1: object tracking on {len(wan_clips)} clip(s)')

    flux_by_index: dict[int, dict] = {m['index']: m for m in flux_image_meta}
    results: list[dict] = []

    for clip_meta in wan_clips:
        clip_path = clip_meta.get('path', '')
        if not clip_path or not os.path.exists(clip_path):
            results.append(clip_meta)
            continue

        src_img_path = clip_meta.get('source_image', '') or ''
        slot_idx = clip_meta.get('index', 0)
        if not src_img_path or not os.path.exists(src_img_path):
            flux_entry = flux_by_index.get(slot_idx, {})
            src_img_path = flux_entry.get('path', '')

        repaired_path = _track_and_composite(clip_path, src_img_path, slot_idx, _log)

        updated = dict(clip_meta)
        if repaired_path and os.path.exists(repaired_path):
            updated['path'] = repaired_path
            updated['tracked'] = True
            _log(f'Stage 4.1: clip {slot_idx} → {os.path.basename(repaired_path)}')
        else:
            updated['tracked'] = False
        results.append(updated)

    _log('Stage 4.1: tracking pass complete')
    return results


# ── Core tracking ─────────────────────────────────────────────────────────────


def _track_and_composite(
    clip_path: str,
    src_img_path: str,
    slot_idx: int,
    log_fn: Callable[[str], None],
) -> str | None:
    """Track objects in *clip_path*.  Returns repaired clip path or None."""
    try:
        model = _get_yolo_model(log_fn)
        if model is None:
            return None

        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            log_fn(f'Stage 4.1: could not open clip {os.path.basename(clip_path)}')
            return None

        fps = cap.get(cv2.CAP_PROP_FPS) or 17.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Read all frames into memory (WAN clips are short: ~81 frames / 4.8s)
        frames_bgr: list[np.ndarray] = []
        while True:
            ret, frm = cap.read()
            if not ret:
                break
            frames_bgr.append(frm)
        cap.release()

        if not frames_bgr:
            return None

        # ── Track objects across all frames ──────────────────────────────────
        tracking_results = model.track(
            frames_bgr,
            persist=True,
            conf=_MIN_CONFIDENCE,
            classes=list(_TRACKED_CLASSES.keys()),
            verbose=False,
        )

        # Build per-object-ID best-seen bounding box + the frame it came from
        best_bbox: dict[int, tuple] = {}  # obj_id → (x1, y1, x2, y2, frame_idx)
        per_frame_ids: list[set] = [set() for _ in frames_bgr]

        for fi, result in enumerate(tracking_results):
            if result.boxes is None:
                continue
            for box in result.boxes:
                if box.id is None:
                    continue
                oid = int(box.id.item())
                conf = float(box.conf.item())
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                per_frame_ids[fi].add(oid)
                if oid not in best_bbox or conf > best_bbox[oid][4]:
                    best_bbox[oid] = (x1, y1, x2, y2, fi, conf)

        # ── Identify disappearance windows ────────────────────────────────────
        # For each tracked object: find runs of consecutive frames where it's absent
        disappearances: list[tuple] = []  # (obj_id, start_frame, end_frame)
        for oid in best_bbox:
            absent_start = None
            consecutive = 0
            for fi in range(len(frames_bgr)):
                if oid not in per_frame_ids[fi]:
                    consecutive += 1
                    if consecutive == _MISS_THRESHOLD and absent_start is None:
                        absent_start = fi - consecutive + 1
                else:
                    if absent_start is not None and consecutive >= _MISS_THRESHOLD:
                        disappearances.append((oid, absent_start, fi - 1))
                    absent_start = None
                    consecutive = 0
            if absent_start is not None and consecutive >= _MISS_THRESHOLD:
                disappearances.append((oid, absent_start, len(frames_bgr) - 1))

        if not disappearances:
            log_fn(f'Stage 4.1: clip {slot_idx} — no object disappearances detected, skipping composite')
            return None

        log_fn(
            f'Stage 4.1: clip {slot_idx} — {len(disappearances)} disappearance window(s) detected; '
            f'compositing from source image'
        )

        # ── Load source FLUX image for compositing ────────────────────────────
        src_img_orig: np.ndarray | None = None
        if src_img_path and os.path.exists(src_img_path):
            src_img_orig = cv2.imread(src_img_path)
            # Do NOT resize to WAN dimensions here — we scale bbox coordinates
            # into source-image space below, avoiding the aspect-ratio distortion
            # that occurs when squeezing a 1024×1024 FLUX image to 832×480.

        # ── Apply compositing ─────────────────────────────────────────────────
        patched_frames = [f.copy() for f in frames_bgr]

        for oid, start_fi, end_fi in disappearances:
            x1, y1, x2, y2, ref_fi, _ = best_bbox[oid]

            # Crop the object region from the reference WAN frame (always available)
            obj_crop = frames_bgr[ref_fi][y1:y2, x1:x2].copy()
            if obj_crop.size == 0:
                continue

            # Prefer source FLUX image crop when available.
            # Map bbox from WAN-clip pixel space → source-image pixel space so
            # the crop aligns correctly regardless of resolution difference.
            if src_img_orig is not None:
                src_h, src_w = src_img_orig.shape[:2]
                scale_x = src_w / width
                scale_y = src_h / height
                sx1 = max(0, int(x1 * scale_x))
                sx2 = min(src_w, int(x2 * scale_x))
                sy1 = max(0, int(y1 * scale_y))
                sy2 = min(src_h, int(y2 * scale_y))
                src_crop_raw = src_img_orig[sy1:sy2, sx1:sx2]
                if src_crop_raw.size > 0:
                    # Resize cropped patch back to WAN-clip bbox size
                    obj_crop = cv2.resize(src_crop_raw, (x2 - x1, y2 - y1))

            for fi in range(start_fi, end_fi + 1):
                dst = patched_frames[fi]
                h_dst, w_dst = dst.shape[:2]
                # Skip if bbox overflows this frame
                if y2 > h_dst or x2 > w_dst or x1 < 0 or y1 < 0:
                    continue

                crop_h = y2 - y1
                crop_w = x2 - x1
                patch = cv2.resize(obj_crop, (crop_w, crop_h))

                cx = x1 + crop_w // 2
                cy = y1 + crop_h // 2

                # Use seamlessClone for invisible compositing.
                # Requires the patch centre to be at least patch_size/2 away from
                # every border; fall back to weighted alpha blend if not.
                margin_x = crop_w // 2 + 2
                margin_y = crop_h // 2 + 2
                can_clone = (
                    cx - margin_x >= 0 and cx + margin_x < w_dst and cy - margin_y >= 0 and cy + margin_y < h_dst
                )
                if can_clone:
                    try:
                        mask = np.full((crop_h, crop_w), 255, dtype=np.uint8)
                        patched_frames[fi] = cv2.seamlessClone(patch, dst, mask, (cx, cy), cv2.NORMAL_CLONE)
                        continue
                    except cv2.error as _exc:
                        _zyg_log.debug('seamless clone failed, using the alpha-blend fallback: %s', _exc)

                # Alpha blend fallback (near-border regions or clone failure)
                roi = dst[y1:y2, x1:x2].astype(np.float32)
                cmp = patch.astype(np.float32)
                alpha = 0.75  # slightly lower to reduce visibility of fallback
                blended = (cmp * alpha + roi * (1.0 - alpha)).astype(np.uint8)
                patched_frames[fi][y1:y2, x1:x2] = blended

        # ── Write repaired clip ───────────────────────────────────────────────
        base, ext = os.path.splitext(clip_path)
        out_path = f'{base}_tracked.mp4'

        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w') as flist:
            frame_dir = tempfile.mkdtemp()
            for fi, frm in enumerate(patched_frames):
                fpath = os.path.join(frame_dir, f'f_{fi:05d}.jpg')
                cv2.imwrite(fpath, frm, [cv2.IMWRITE_JPEG_QUALITY, 95])
            flist.write(
                '\n'.join(f"file '{os.path.join(frame_dir, f'f_{fi:05d}.jpg')}'" for fi in range(len(patched_frames)))
            )
            flist_path = flist.name

        try:
            subprocess.run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-r',
                    str(fps),
                    '-f',
                    'concat',
                    '-safe',
                    '0',
                    '-i',
                    flist_path,
                    '-c:v',
                    'libx264',
                    '-preset',
                    'fast',
                    '-crf',
                    '18',
                    out_path,
                ],
                capture_output=True,
                check=True,
            )
        finally:
            try:
                os.unlink(flist_path)
                import shutil

                shutil.rmtree(frame_dir, ignore_errors=True)
            except Exception as _exc:
                _zyg_log.debug('frame scratch cleanup skipped: %s', _exc)

        return out_path

    except Exception as e:
        log_fn(f'Stage 4.1: tracking failed for clip {slot_idx}: {e}')
        return None


# ── YOLO model loader ─────────────────────────────────────────────────────────


def _get_yolo_model(log_fn: Callable[[str], None]):
    global _yolo_model_cache
    if _yolo_model_cache is not None:
        return _yolo_model_cache
    try:
        from ultralytics import YOLO

        log_fn(f'Stage 4.1: loading YOLO model ({_YOLO_MODEL}) …')
        _yolo_model_cache = YOLO(_YOLO_MODEL)
        log_fn('Stage 4.1: YOLO model ready')
        return _yolo_model_cache
    except Exception as e:
        log_fn(f'Stage 4.1: YOLO load failed — {e}')
        return None
