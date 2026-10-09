# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared helpers: the lazy run_ledger / qc_contract bridges, VRAM sampling and
the CLIP identity / hand-count probes every gate and DebugRun method reaches for."""

import json
import time
import logging as _zyg_logging
from zyg_workflows import paths


_zyg_log = _zyg_logging.getLogger(__name__)


_THUMB_W = 360


def _now():
    return time.strftime('%H:%M:%S')


# ── run_ledger bridge (lazy, fail-safe) ──────────────────────────────────────
_LEDGER = {'mod': None, 'tried': False}


def _ledger():
    """Lazy run_ledger import; None if unavailable (debug must survive without it)."""
    if not _LEDGER['tried']:
        _LEDGER['tried'] = True
        try:
            from zyg_workflows import run_ledger

            _LEDGER['mod'] = run_ledger
        except Exception:
            _LEDGER['mod'] = None
    return _LEDGER['mod']


# ── qc_contract bridge (lazy, fail-safe) ─────────────────────────────────────
# The authority layer: PASS/FAIL/UNKNOWN, the shadow→warn→block ladder, and the
# coverage matrix. If it cannot be imported, finish() falls back to the old
# two-verdict behaviour rather than breaking a render.
_CONTRACT = {'mod': None, 'tried': False}


def _contract():
    if not _CONTRACT['tried']:
        _CONTRACT['tried'] = True
        try:
            from zyg_workflows import qc_contract

            _CONTRACT['mod'] = qc_contract
        except Exception:
            _CONTRACT['mod'] = None
    return _CONTRACT['mod']


def _vram_mb():
    """Current VRAM usage in MB via NVML (read-only, allocates nothing), or None."""
    try:
        led = _ledger()
        return led.vram_used_mb() if led is not None else None
    except Exception:
        return None


# score fields worth trending per gate, most-specific first.
# 'reversals_per_s' leads: it is the only key here carried by the 2026-07-31 jitter gate,
# and if flow_mean won that match the cross-run trend for a JITTER gate would plot the very
# quantity that gate exists to overrule (magnitude ranks the two reference clips backwards).
# 'flow_median' added 2026-08-01 for qc_character_balance, whose GATED quantity is the
# median (the whole-clip mean is burst-dominated and ranks the two reference clips
# backwards — see the calibration block above qc_character_balance). It sits after
# reversals_per_s so the jitter gate's trend is untouched, and no check dict that
# existed before 2026-08-01 carries this key, so no existing trend changes either.
_SCORE_KEYS = (
    'reversals_per_s',
    'flow_median',
    'flow_mean',
    'mean_delta',
    'clip_sim',
    'ncc',
    'clipped_pct',
    'white_frac',
    'churn_p95',
    'path_px_median',
    'bg_structure',
    'ratio',
    'delta',
    'value',
)


def _check_score(c):
    """Pick the one numeric worth trending from a QC check dict (None if none)."""
    for k in _SCORE_KEYS:
        v = c.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    for k, v in c.items():
        if k == 'ok' or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        return float(v)
    return None


_CLIP = {'model': None, 'pre': None}


def _clip_embed(pil_img):
    """Lazy open_clip ViT-B-32 image embedding (openai weights, already cached locally)."""
    import torch
    import open_clip

    if _CLIP['model'] is None:
        m, _, pre = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
        m.eval()
        _CLIP['model'] = m
        _CLIP['pre'] = pre
    with torch.no_grad():
        t = _CLIP['pre'](pil_img).unsqueeze(0)
        e = _CLIP['model'].encode_image(t)
        e = e / e.norm(dim=-1, keepdim=True)
    return e[0]


def identity_similarity(image_path, canon_crop_path, region=None):
    """Cosine similarity between a region of an image and a canonical face crop.
    region: (fx0, fy0, fx1, fy1) fractions; None = whole image. CLIP-space — coarse but
    stylization-tolerant (ArcFace is documented-unreliable on painterly faces + NC-licensed)."""
    try:
        from PIL import Image

        im = Image.open(image_path).convert('RGB')
        if region:
            W, H = im.size
            fx0, fy0, fx1, fy1 = region
            im = im.crop((int(W * fx0), int(H * fy0), int(W * fx1), int(H * fy1)))
        a = _clip_embed(im)
        b = _clip_embed(Image.open(canon_crop_path).convert('RGB'))
        return float((a * b).sum())
    except Exception:
        return None


def _detect_hands(image_path):
    """Best-effort hand count via the comfy-side hand_yolov8s detector (None = unavailable).
    LICENSE NOTE (2026-07-29 research): ultralytics runtime is AGPL-3.0 and the Bingsu
    hand_yolov8s weights carry AGPL too — fine for internal QC signals, but the planned
    replacement is MediaPipe Hands (Apache-2.0) before any redistribution scenario."""
    try:
        from ultralytics import YOLO  # only if installed in this venv

        model = YOLO(str(paths.ZYG_COMFY_ROOT / 'models' / 'ultralytics' / 'bbox' / 'hand_yolov8s.pt'))
        r = model(image_path, verbose=False)
        return sum(len(x.boxes) for x in r)
    except Exception:
        return None


def _jsonable(obj):
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return {k: str(v)[:200] for k, v in (obj or {}).items()} if isinstance(obj, dict) else str(obj)[:300]
