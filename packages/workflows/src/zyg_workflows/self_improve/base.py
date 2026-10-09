# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Preamble constants, JSON helpers, geometry + normalisation.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os
import sys
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)


SCHEMA = 'zyg.signature/1'

# ── calibration geometry of the pipeline_debug gates (do not drift) ──────────
CAL_W = 832.0
CAL_FPS = 17.0
CAL_SAMPLE_EVERY = 4

# containment fraction at which a keep box is said to COVER a region
_COVER_FRAC = 0.30
# grid used by the region-free motion-loss map
_GRID_COLS, _GRID_ROWS = 16, 10
# a tile counts as "motion lost" when raw >= gate and delivered < gate and the
# relative drop is at least this much (guards against measurement jitter)
_TILE_DROP_FRAC = 0.35


def _log_noop(_m):
    pass


def _mklog(log_fn):
    return log_fn if callable(log_fn) else _log_noop


def _jsonable(o):
    """Numpy scalars/arrays and tuples → plain JSON types (report writers choke otherwise)."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (str, bool, int, float)) or o is None:
        return o
    for attr in ('item', 'tolist'):
        if hasattr(o, attr):
            try:
                return _jsonable(getattr(o, attr)())
            except Exception as _exc:
                _zyg_log.debug('%s() is not json-able, falling back to str(): %s', attr, _exc)
    return str(o)


def _write_json(path, obj, log_fn=None):
    log = _mklog(log_fn)
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_jsonable(obj), f, indent=1)
        os.replace(tmp, path)
        return path
    except Exception as e:
        log(f'[self_improve] write failed {path}: {e}')
        return None


def _read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _write_text(path, text, log_fn=None):
    log = _mklog(log_fn)
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path
    except Exception as e:
        log(f'[self_improve] write failed {path}: {e}')
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1.  GEOMETRY + NORMALISATION
# ══════════════════════════════════════════════════════════════════════════════


def clip_geometry(clip_path):
    """(W, H, fps, n_frames) via cv2, or (None, None, None, None).

    cv2 is already a hard dependency of pipeline_debug, so no new install."""
    try:
        import cv2

        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            return (None, None, None, None)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        return (W or None, H or None, fps or None, n or None)
    except Exception:
        return (None, None, None, None)


def norm_factor(W, fps, sample_every=CAL_SAMPLE_EVERY):
    """Multiplier that maps a measured px/sample flow onto the calibration geometry.

    flow_measured = v_framewidths_per_s * W * (sample_every / fps)
    flow_cal      = v_framewidths_per_s * 832 * (4 / 17)
    ⇒ flow_cal = flow_measured * (832/W) * (fps/17) * (4/sample_every)"""
    try:
        if not W or not fps or not sample_every:
            return 1.0
        return (CAL_W / float(W)) * (float(fps) / CAL_FPS) * (float(CAL_SAMPLE_EVERY) / float(sample_every))
    except Exception:
        return 1.0
