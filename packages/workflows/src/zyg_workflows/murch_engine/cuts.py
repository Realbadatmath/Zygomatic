# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Layer 3 — saliency focal points, composition constraints, xfade transitions, RMS rhythm.

Moved verbatim from murch_engine.py lines 1842-2356.
"""

from __future__ import annotations
import os
import time


from zyg_workflows.murch_engine.base import _dbg

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3a — OpenCV Saliency Focal Point Extraction
# ─────────────────────────────────────────────────────────────────────────────


def extract_focal_point(image_path: str, debug_log: list | None = None) -> dict:
    """
    Layer 3a: Compute the visual focal point of an image using OpenCV saliency.
    Returns {'x': float, 'y': float, 'zone': str, 'saliency_peak': float}
    x, y are 0–1 normalized coordinates (0,0 = top-left, 1,1 = bottom-right)
    zone is one of: top-left, top-center, top-right, center-left, center,
                    center-right, bottom-left, bottom-center, bottom-right
    """
    if debug_log is None:
        debug_log = []

    try:
        import cv2
        import numpy as np

        img = cv2.imread(image_path)
        if img is None:
            _dbg(debug_log, 'focal_point', f'Could not load image: {image_path}', 'WARN')
            return {'x': 0.5, 'y': 0.5, 'zone': 'center', 'saliency_peak': 0.0}

        saliency = cv2.saliency.StaticSaliencyFineGrained_create()
        ok, saliency_map = saliency.computeSaliency(img)
        if not ok:
            return {'x': 0.5, 'y': 0.5, 'zone': 'center', 'saliency_peak': 0.0}

        sal = (saliency_map * 255).astype('uint8')
        h, w = sal.shape

        # Find centroid of top-5% saliency pixels
        threshold = np.percentile(sal, 95)
        hot = sal >= threshold
        ys, xs = np.where(hot)
        if len(xs) == 0:
            cx, cy = 0.5, 0.5
        else:
            cx = float(np.mean(xs)) / w
            cy = float(np.mean(ys)) / h

        # Map to 3x3 zone grid
        col = 'left' if cx < 0.33 else ('center' if cx < 0.67 else 'right')
        row = 'top' if cy < 0.33 else ('center' if cy < 0.67 else 'bottom')
        zone = f'{row}-{col}' if row != 'center' else col

        peak = float(saliency_map.max())
        result = {'x': round(cx, 3), 'y': round(cy, 3), 'zone': zone, 'saliency_peak': round(peak, 3)}
        _dbg(debug_log, 'focal_point', f'{os.path.basename(image_path)} → focal={zone} ({cx:.2f},{cy:.2f})', 'DEBUG')
        return result

    except Exception as e:
        _dbg(debug_log, 'focal_point', f'Saliency failed for {image_path}: {e}', 'WARN')
        return {'x': 0.5, 'y': 0.5, 'zone': 'center', 'saliency_peak': 0.0}


def extract_focal_points_batch(image_paths: list[str], debug_log: list | None = None) -> list[dict]:
    """Process all images and return focal point list in order."""
    if debug_log is None:
        debug_log = []
    _dbg(debug_log, 'focal_points_batch', f'Extracting focal points for {len(image_paths)} images', 'INFO')
    results = []
    for p in image_paths:
        results.append(extract_focal_point(p, debug_log))
    _dbg(debug_log, 'focal_points_batch', f'Done. Zones: {[r["zone"] for r in results]}', 'INFO')
    return results


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3b — Composition Constraints for FLUX Prompts
# ─────────────────────────────────────────────────────────────────────────────

# Zone proximity table: how "far" is each zone from each other zone?
_ZONE_COORDS = {
    'top-left': (0.17, 0.17),
    'top-center': (0.50, 0.17),
    'top-right': (0.83, 0.17),
    'center-left': (0.17, 0.50),
    'center': (0.50, 0.50),
    'center-right': (0.83, 0.50),
    'bottom-left': (0.17, 0.83),
    'bottom-center': (0.50, 0.83),
    'bottom-right': (0.83, 0.83),
    'left': (0.17, 0.50),
    'right': (0.83, 0.50),
}

# Composition constraint phrases for FLUX (keyed by desired focal zone)
_COMPOSITION_CONSTRAINTS = {
    'top-left': 'subject positioned upper-left, negative space lower-right',
    'top-center': 'subject positioned top-center, rule of thirds top band',
    'top-right': 'subject positioned upper-right, leading space to the left',
    'center-left': 'subject positioned center-left, balanced composition',
    'center': 'subject centered, symmetrical composition, direct gaze',
    'center-right': 'subject positioned center-right, facing left',
    'bottom-left': 'subject grounded lower-left, sky dominant upper portion',
    'bottom-center': 'subject anchored bottom-center, dramatic sky above',
    'bottom-right': 'subject lower-right, environment fills upper-left',
    'left': 'subject on left third, open space right',
    'right': 'subject on right third, open space left',
}


def get_composition_constraint(
    prev_focal_zone: str | None,
    emotion: str,
    arc_zone: str,
    debug_log: list | None = None,
) -> str:
    """
    Layer 3b: Given previous image focal zone, return a composition constraint
    that keeps eye movement minimal (matching zones) or intentionally jarring (counterpoint).
    """
    if debug_log is None:
        debug_log = []

    if not prev_focal_zone:
        # No previous image — use center as default
        return _COMPOSITION_CONSTRAINTS.get('center', '')

    prev_coords = _ZONE_COORDS.get(prev_focal_zone, (0.5, 0.5))

    if arc_zone == 'climax' and emotion in ('shock', 'tension', 'grief'):
        # Intentional break — place subject far from previous focal zone (jarring)
        px, py = prev_coords
        # Move to opposite quadrant
        target_x = 1.0 - px
        target_y = 1.0 - py
        # Find closest zone
        best_zone = min(
            _ZONE_COORDS,
            key=lambda z: ((_ZONE_COORDS[z][0] - target_x) ** 2 + (_ZONE_COORDS[z][1] - target_y) ** 2) ** 0.5,
        )
        constraint = _COMPOSITION_CONSTRAINTS.get(best_zone, '')
        _dbg(debug_log, 'composition', f'Climax break: {prev_focal_zone}→{best_zone} (jarring cut)', 'DEBUG')
        return constraint
    else:
        # Smooth eye movement — find a zone close to the previous one
        px, py = prev_coords
        # Find zone within ~0.3 distance (adjacent zone)
        candidates = [(z, ((c[0] - px) ** 2 + (c[1] - py) ** 2) ** 0.5) for z, c in _ZONE_COORDS.items()]
        candidates.sort(key=lambda x: x[1])
        # Pick the second-closest (not same zone, but close)
        target_zone = candidates[1][0] if len(candidates) > 1 else 'center'
        constraint = _COMPOSITION_CONSTRAINTS.get(target_zone, '')
        _dbg(debug_log, 'composition', f'Smooth eye trace: {prev_focal_zone}→{target_zone}', 'DEBUG')
        return constraint


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3c — Emotion-Driven FFmpeg xfade Transition Builder
# ─────────────────────────────────────────────────────────────────────────────

# Transition types: (xfade_name, duration_s)
_TRANSITION_TABLE = {
    # (prev_emotion, next_emotion): (transition_type, duration)
    # ('calm', 'calm') is defined once, further down, as the sustained-calm override.
    ('calm', 'unease'): ('dissolve', 1.0),
    ('calm', 'mystery'): ('fadeblack', 1.0),
    ('calm', 'tension'): ('dissolve', 0.6),
    ('calm', 'shock'): ('cut', 0.0),  # hard smash cut
    ('calm', 'grief'): ('fadeblack', 0.8),
    ('calm', 'triumph'): ('dissolve', 0.8),
    ('calm', 'awe'): ('fadeslow', 1.4),
    ('tension', 'shock'): ('cut', 0.0),
    ('tension', 'calm'): ('dissolve', 0.8),
    ('tension', 'tension'): ('cut', 0.0),
    ('tension', 'grief'): ('fadeblack', 0.8),
    ('tension', 'triumph'): ('dissolve', 0.6),
    ('shock', 'grief'): ('fadeblack', 1.0),
    ('shock', 'calm'): ('fadeblack', 0.8),
    ('shock', 'shock'): ('cut', 0.0),
    ('grief', 'calm'): ('fadegrays', 1.4),
    ('grief', 'grief'): ('fadegrays', 1.5),
    ('grief', 'triumph'): ('dissolve', 0.8),
    ('triumph', 'calm'): ('dissolve', 1.0),
    ('triumph', 'triumph'): ('dissolve', 0.5),
    ('triumph', 'awe'): ('zoomin', 1.0),
    ('awe', 'calm'): ('fadeslow', 1.8),
    ('awe', 'awe'): ('fadeslow', 1.6),
    ('awe', 'mystery'): ('fadewhite', 1.0),
    ('mystery', 'revelation'): ('fadeblack', 0.6),
    ('mystery', 'shock'): ('cut', 0.0),
    ('mystery', 'awe'): ('circleopen', 1.2),
    ('mystery', 'calm'): ('hblur', 1.0),
    ('calm', 'calm'): ('fadeslow', 1.5),  # override: sustained calm = slow fade
}
_DEFAULT_TRANSITION = ('dissolve', 0.6)

# Shot-type transition overrides — applied on top of emotion table.
# Key: (prev_shot_tightness, next_shot_tightness)
# Tightness buckets: 'wide' | 'medium' | 'close' | 'extreme'
_SHOT_TRANSITION_OVERRIDES = {
    # Moving IN (wide → close): physically push forward
    ('wide', 'close'): ('coverleft', 0.7),
    ('wide', 'extreme'): ('zoomin', 0.8),
    ('medium', 'close'): ('coverleft', 0.6),
    ('medium', 'extreme'): ('zoomin', 0.7),
    # Moving OUT (close → wide): reveal / expand to context
    ('close', 'wide'): ('revealright', 0.7),
    ('extreme', 'wide'): ('revealright', 0.8),
    ('close', 'medium'): ('revealright', 0.6),
    ('extreme', 'medium'): ('smoothright', 0.6),
    # Lateral moves (same tightness): fluid slide
    ('wide', 'wide'): ('smoothleft', 1.0),
    ('medium', 'medium'): ('dissolve', 0.8),  # keep dissolve for medium same-tightness
    ('close', 'close'): ('smoothleft', 0.7),
    ('extreme', 'extreme'): ('fadefast', 0.4),
    # Overhead ↔ any: descend/ascend
    ('overhead', 'medium'): ('smoothdown', 0.8),
    ('overhead', 'close'): ('smoothdown', 0.7),
    ('medium', 'overhead'): ('smoothup', 0.8),
    ('wide', 'overhead'): ('smoothup', 1.0),
}

# Hard-cut emotions — kept for reference; get_transition now only hard-blocks on table 'cut'
_HARD_CUT_EMOTIONS = {'shock', 'tension'}


def _shot_tightness(shot_type: str) -> str:
    """Map a shot_type string to a tightness bucket for transition selection."""
    sl = (shot_type or '').lower()
    if 'extreme' in sl or 'tight crop' in sl:
        return 'extreme'
    if 'close' in sl:
        return 'close'
    if 'overhead' in sl or 'drone' in sl or 'bird' in sl:
        return 'overhead'
    if 'wide' in sl or 'establishing' in sl:
        return 'wide'
    return 'medium'  # default: medium/Dutch/shoulder etc.


def get_transition(
    prev_emotion: str,
    next_emotion: str,
    prev_shot: str = '',
    next_shot: str = '',
    debug_log: list | None = None,
) -> tuple[str, float]:
    """Return (xfade_type, duration_seconds) for this emotion + shot-type pair.

    Shot-type axis (Method B):
    1. Look up base transition from emotion table.
    2. If the emotion result is NOT a hard cut, check shot-tightness override table.
    3. Shot override wins when present — it describes the physical camera move feel.
    """
    if debug_log is None:
        debug_log = []

    # Step 1: emotion-based base transition
    key = (prev_emotion, next_emotion)
    trans_type, trans_dur = _TRANSITION_TABLE.get(key, _DEFAULT_TRANSITION)

    # Step 2: table hard cuts are absolute — never soften them via shot-type rules.
    # Shock/tension with a soft table result (dissolve, fadeblack, …) still allows
    # shot-type overrides so physical camera moves are honoured.
    if trans_type == 'cut':
        _dbg(
            debug_log,
            'transition',
            f'{prev_emotion}→{next_emotion} [table hard cut — shot override skipped]: cut 0s',
            'DEBUG',
        )
        return trans_type, trans_dur

    # Step 3: shot-type override
    if prev_shot or next_shot:
        prev_t = _shot_tightness(prev_shot)
        next_t = _shot_tightness(next_shot)
        shot_key = (prev_t, next_t)
        if shot_key in _SHOT_TRANSITION_OVERRIDES:
            ov_type, ov_dur = _SHOT_TRANSITION_OVERRIDES[shot_key]
            _dbg(
                debug_log,
                'transition',
                f'{prev_emotion}→{next_emotion} | {prev_t}→{next_t}: '
                f'shot override {ov_type} {ov_dur}s (was {trans_type} {trans_dur}s)',
                'DEBUG',
            )
            return ov_type, ov_dur

    _dbg(debug_log, 'transition', f'{prev_emotion}→{next_emotion}: {trans_type} {trans_dur}s', 'DEBUG')
    return trans_type, trans_dur


def build_xfade_filter_graph(
    image_durations: list[float],
    emotions: list[str],
    shot_types: list[str] | None = None,
    debug_log: list | None = None,
) -> tuple[str, list[dict]]:
    """
    Layer 3c: Build an FFmpeg xfade filter graph for N images with emotion-driven transitions.
    Returns (filter_complex_str, transition_manifest).
    transition_manifest: list of {idx, prev_emotion, next_emotion, transition, duration, offset}

    The filter_complex is designed to be inserted into the FFmpeg command that assembles the slideshow.
    Each input image is treated as a video segment of its assigned duration.

    Architecture: segment-based concat.
    FFmpeg's xfade filter silently terminates early when 3+ consecutive micro-cut xfades are
    chained — consecutive cuts where offset ≈ A_stream_end cause the filter to stop rather than
    continue into the next image.  The fix: treat every hard-cut transition as a segment boundary
    and join segments with FFmpeg's concat filter (which correctly sequences them).  Smooth
    transitions (dissolve, fadeblack) remain as xfade chains within each segment.
    """
    if debug_log is None:
        debug_log = []
    if shot_types is None:
        shot_types = []

    n = len(image_durations)
    if n == 0:
        return '', []
    if n == 1:
        return '[0:v]copy[vout]', []

    # ── Step 1: build the full transition manifest ────────────────────────────
    manifest = []
    for i in range(n - 1):
        dur_i = image_durations[i]
        emo_i = emotions[i] if i < len(emotions) else 'calm'
        emo_j = emotions[i + 1] if i + 1 < len(emotions) else 'calm'

        shot_i = shot_types[i] if shot_types and i < len(shot_types) else ''
        shot_j = shot_types[i + 1] if shot_types and i + 1 < len(shot_types) else ''
        trans_type, trans_dur = get_transition(emo_i, emo_j, prev_shot=shot_i, next_shot=shot_j, debug_log=debug_log)

        # Clamp transition to at most 80 % of slot duration so xfade offset stays positive.
        if trans_type != 'cut' and trans_dur > 0:
            trans_dur = min(trans_dur, dur_i * 0.8)

        manifest.append(
            {
                'idx': i,
                'prev_emotion': emo_i,
                'next_emotion': emo_j,
                'transition': trans_type,
                'duration': trans_dur,
                'offset': 0.0,  # filled in per-segment below
            }
        )

    # ── Step 2: split at every hard cut → list of segments ───────────────────
    # Each segment is a run of consecutive images connected ONLY by smooth transitions.
    # Hard cuts become concat boundaries (no xfade overlap, zero wasted duration).
    segments: list[list[int]] = []
    seg_start = 0
    for i in range(n - 1):
        if manifest[i]['transition'] == 'cut':
            segments.append(list(range(seg_start, i + 1)))
            seg_start = i + 1
    segments.append(list(range(seg_start, n)))

    # ── Step 3: build per-segment xfade chains ────────────────────────────────
    filters: list[str] = []
    seg_labels: list[str] = []  # one output label per segment (for the concat)

    for seg_k, seg_imgs in enumerate(segments):
        seg_n = len(seg_imgs)

        if seg_n == 1:
            # Single image — feed directly into the concat without an extra filter.
            # After the [i:v] → [vsi] patch in crewai_web_gui.py this becomes [vs{i}].
            seg_labels.append(f'[{seg_imgs[0]}:v]')
            continue

        # Multi-image segment: build an xfade chain (smooth transitions only).
        cumulative_offset = 0.0
        current_label = f'[{seg_imgs[0]}:v]'

        for k in range(seg_n - 1):
            img_i = seg_imgs[k]
            img_j = seg_imgs[k + 1]
            dur_i = image_durations[img_i]
            m = manifest[img_i]  # transition between img_i and img_j
            trans_type = m['transition']
            trans_dur = m['duration']

            xfade_offset = max(0.0, cumulative_offset + dur_i - trans_dur)
            cumulative_offset += dur_i - trans_dur
            m['offset'] = round(xfade_offset, 3)

            next_label = f'[{img_j}:v]'
            is_last = k == seg_n - 2
            out_label = f'[s{seg_k:03d}_{k + 1:02d}]' if not is_last else f'[s{seg_k:03d}_out]'

            filters.append(
                f'{current_label}{next_label}xfade=transition={trans_type}:'
                f'duration={trans_dur}:offset={xfade_offset:.3f}{out_label}'
            )
            current_label = out_label

        seg_labels.append(f'[s{seg_k:03d}_out]')

    # ── Step 4: assemble final filter string ──────────────────────────────────
    filter_str = ';'.join(filters)

    if len(seg_labels) == 1:
        # Single segment — rename its output label to [vout].
        label = seg_labels[0]
        if filter_str:
            filter_str = filter_str.replace(label, '[vout]')
        else:
            # Edge case: single segment, single image (n≥2 but all were split — shouldn't happen)
            filter_str = f'{label[:-1]}copy[vout]'
    else:
        # Multiple segments — concat them in sequence.
        concat_inputs = ''.join(seg_labels)
        concat_filter = f'{concat_inputs}concat=n={len(seg_labels)}:v=1:a=0[vout]'
        filter_str = (filter_str + ';' + concat_filter) if filter_str else concat_filter

    n_smooth = sum(1 for m in manifest if m['transition'] != 'cut')
    n_cuts = sum(1 for m in manifest if m['transition'] == 'cut')
    n_fadeblk = sum(1 for m in manifest if m['transition'] == 'fadeblack')
    _dbg(
        debug_log,
        'xfade_graph',
        f'Built xfade filter for {n} images: {n_smooth - n_fadeblk} dissolves, '
        f'{n_cuts} hard cuts ({len(segments)} concat-segments), '
        f'{n_fadeblk} fade-to-blacks',
        'INFO',
        {'manifest': manifest, 'segments': [[s[0], s[-1]] for s in segments]},
    )
    return filter_str, manifest


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3d — librosa RMS Energy Rhythm Alignment
# ─────────────────────────────────────────────────────────────────────────────


def extract_audio_rhythm(
    audio_path: str,
    n_cuts: int,
    debug_log: list | None = None,
) -> list[float]:
    """
    Layer 3d: Use librosa to find natural cut points aligned to audio rhythm.
    Returns list of n_cuts suggested cut times (in seconds) based on:
      1. RMS energy peaks (emphasis beats)
      2. Natural pauses (RMS troughs)
    Falls back to empty list if librosa fails.
    """
    if debug_log is None:
        debug_log = []

    if not os.path.exists(audio_path):
        _dbg(debug_log, 'audio_rhythm', f'Audio not found: {audio_path}', 'WARN')
        return []

    try:
        import librosa
        import numpy as np

        t0 = time.monotonic()
        y, sr = librosa.load(audio_path, sr=16000, mono=True)  # downsample for speed
        duration = float(len(y)) / sr

        # RMS energy (frame-level)
        hop_length = 512
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

        # Find natural pauses (local minima in RMS)
        from scipy.signal import find_peaks

        # Troughs = peaks in negative RMS
        troughs, _ = find_peaks(-rms, prominence=0.005, distance=int(sr / hop_length * 0.5))

        # Filter troughs that are actual pauses (RMS below 40th percentile)
        rms_threshold = float(np.percentile(rms, 40))
        pause_times = [float(times[t]) for t in troughs if rms[t] < rms_threshold]

        # Also find emphasis peaks (high RMS = stressed syllable)
        peaks, _ = find_peaks(rms, prominence=0.008, distance=int(sr / hop_length * 0.3))
        emphasis_times = [float(times[p]) for p in peaks]

        _dbg(
            debug_log,
            'audio_rhythm',
            f'librosa: duration={duration:.1f}s | {len(pause_times)} pauses | '
            f'{len(emphasis_times)} emphasis peaks | elapsed={time.monotonic() - t0:.1f}s',
            'INFO',
        )

        # Select n_cuts best cut points
        # Prefer pauses (natural breath), fill with emphasis if not enough pauses
        all_candidates = sorted(
            [(t, 'pause') for t in pause_times] + [(t, 'emphasis') for t in emphasis_times], key=lambda x: x[0]
        )

        if not all_candidates:
            _dbg(debug_log, 'audio_rhythm', 'No rhythm candidates found', 'WARN')
            return []

        # Space them roughly evenly while preferring pause points
        step = duration / (n_cuts + 1)
        selected = []
        for i in range(1, n_cuts + 1):
            target = i * step
            nearest = min(all_candidates, key=lambda x: abs(x[0] - target))
            selected.append(round(nearest[0], 3))

        _dbg(debug_log, 'audio_rhythm', f'Selected {len(selected)} rhythm cut points: {selected}', 'INFO')
        return selected

    except Exception as e:
        _dbg(debug_log, 'audio_rhythm', f'librosa rhythm extraction failed: {e}', 'WARN')
        return []
