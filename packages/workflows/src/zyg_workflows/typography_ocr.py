# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Local OCR typography judge — "is there readable lettering in this frame?"

Why OCR and not a vision model
------------------------------
FLUX cannot render real writing; it paints shapes that read as lettering but
spell gibberish ('RECTAAIS', "IVET'Y"). The gate's job is to notice that, and
its precision rule has always been *flag only when the judge can QUOTE what it
sees* — which is exactly what an OCR engine does natively.

The two judges this replaces could not answer in production:

  * the local Qwen3-VL judge needs 14 GB and Stage 3.5 runs with FLUX resident
    (measured 5.9 GB free), so it correctly declines rather than downshift to
    its CPU tier (~126 s/frame — that is what stalled the Catherine run);
  * the Anthropic fallback then returned HTTP 400 "credit balance is too low"
    on every frame.

So the gate returned `0 checked, 0 flagged, 3 unreadable`, nothing was ever
flagged, the retry ladder was never asked to fix anything, and the run reported
a tidy 100% convergence. This module removes both failure modes: it runs on the
CPU, needs no VRAM, costs nothing per call, and cannot be billed out.

Agreement with the judge it replaces
------------------------------------
Calibrated against Qwen3-VL ('documentary_typography', resident tier) over 48
real frames from scholarly run 85f0659c — 12 with lettering, 36 clean:

    conf >= 0.50, box area >= 0.1% of frame, k >= 1
    TP 12   FP 0   FN 0   TN 36   precision 1.00   recall 1.00

Perfect agreement, and stable: every threshold in conf 0.30-0.60 x area
0.00-0.10% scored 1.00/1.00, so the operating point is not perched on a cliff.
Cost 0.58 s/frame on CPU vs ~2.7 s/frame on the GPU judge.

Licence: rapidocr-onnxruntime is Apache-2.0, its bundled PP-OCR models are
Apache-2.0, Shapely BSD-3, pyclipper Boost. Nothing here reaches an output
asset in any case — this is a QC tool.

Contract
--------
``judge(path)`` returns ``(ok, reason, boxes)`` or **None** when the engine is
unavailable. None means UNKNOWN and callers must treat it as unreviewed, never
as a pass — the same fail-closed rule the other judges follow.
"""

from __future__ import annotations

import os
import threading
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_ENGINE = None
_ENGINE_TRIED = False
_LOCK = threading.Lock()

MIN_CONF = float(os.environ.get('ZYG_SCHOLARLY_OCR_MIN_CONF', '0.50'))
MIN_AREA_FRAC = float(os.environ.get('ZYG_SCHOLARLY_OCR_MIN_AREA_FRAC', '0.001'))
MIN_REGIONS = int(os.environ.get('ZYG_SCHOLARLY_OCR_MIN_REGIONS', '1'))


def _engine():
    """Lazily build the OCR engine once (~0.2 s)."""
    global _ENGINE, _ENGINE_TRIED
    with _LOCK:
        if _ENGINE is None and not _ENGINE_TRIED:
            _ENGINE_TRIED = True
            try:
                from rapidocr_onnxruntime import RapidOCR

                _ENGINE = RapidOCR()
            except Exception:
                _ENGINE = None
        return _ENGINE


def available() -> bool:
    return _engine() is not None


def read_lettering(image_path: str, min_conf: float | None = None, min_area_frac: float | None = None) -> list | None:
    """Every text region above threshold. None = engine unavailable.

    Each region: {'text', 'conf', 'area_frac', 'bbox'} where bbox is
    (x0, y0, x1, y1) in 0-1000 normalised coordinates — the same convention
    vlm_inspector uses, so a future inpainting pass can consume either source.
    """
    eng = _engine()
    if eng is None:
        return None
    mc = MIN_CONF if min_conf is None else min_conf
    ma = MIN_AREA_FRAC if min_area_frac is None else min_area_frac
    try:
        from PIL import Image

        with Image.open(image_path) as im:
            W, H = im.size
    except Exception:
        return None
    if not W or not H:
        return None
    area = float(W * H)
    try:
        res, _ = eng(image_path)
    except Exception:
        return None
    out = []
    for box, txt, conf in res or []:
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            af = ((max(xs) - min(xs)) * (max(ys) - min(ys))) / area
            if float(conf) < mc or af < ma:
                continue
            out.append(
                {
                    'text': str(txt),
                    'conf': round(float(conf), 3),
                    'area_frac': round(af, 5),
                    'bbox': (
                        int(1000 * min(xs) / W),
                        int(1000 * min(ys) / H),
                        int(1000 * max(xs) / W),
                        int(1000 * max(ys) / H),
                    ),
                }
            )
        except Exception as _exc:
            _zyg_log.debug('OCR box ignored, its geometry did not parse: %s', _exc)
            continue
    out.sort(key=lambda r: -r['area_frac'])
    return out


def judge(image_path: str) -> tuple | None:
    """(ok, reason, boxes) — or None when the engine cannot run.

    ok=False means readable lettering is present. The reason quotes the largest
    thing read, because a flag nobody can check is a flag nobody acts on.
    """
    regs = read_lettering(image_path)
    if regs is None:
        return None
    if len(regs) < MIN_REGIONS:
        return True, '', []
    top = regs[0]
    quoted = ', '.join(repr(r['text'])[:24] for r in regs[:3])
    return (
        False,
        f'typography: reads {quoted} ({len(regs)} region(s), largest {top["area_frac"] * 100:.2f}% of frame)',
        [r['bbox'] for r in regs[:8]],
    )
