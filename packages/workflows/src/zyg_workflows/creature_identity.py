# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_identity.py
====================
Identity-drift metric for NON-HUMAN subjects (2026-08-25).

Every identity gate in this repo is ArcFace — a human-face embedding. A creature
returns ``face_detected: false`` on every cell and the whole QC ladder goes
blind. This module is the creature-side replacement: a DINOv2 CLS-token cosine
similarity between a candidate cell and the anchor it was edited from.

Why DINOv2 and not CLIP/SigLIP: DINO features are structure-sensitive (shape,
markings, proportions) where CLIP/SigLIP are semantic (a "cute furry creature"
scores 0.65 against a dragon on SigLIP2 — measured 2026-08-25 on the
pufferball reference). Calibration on the same day, dinov2-base CLS cosine:

    same image vs its mirror ........ 0.981
    same image vs a 56% crop ........ 0.997
    same creature, different angle .. 0.784   (FLUX dragon ref_00 vs ref_05)
    different creature .............. 0.113   (pufferball vs dragon)

So a rotation of the SAME creature lands well above 0.5 and a different subject
well below 0.2. The floors in ``BANDS`` sit in the gap, lower for views that
legitimately hide most of the identity (back, top-down, extreme detail).

Weights: facebook/dinov2-base (Apache-2.0), ~330 MB, loaded lazily on CPU so a
creature run never competes with ComfyUI or the VLM judge for VRAM. Falls back
to dinov2-small if base is not in the HF cache. Both load offline.
"""

from __future__ import annotations

import os
import threading
from typing import Any


# Hugging Face revision for every from_pretrained/download in this module. 'main' is the
# floating default these call sites used implicitly; $ZYG_HF_REVISION pins a commit instead.
_HF_REVISION = os.environ.get('ZYG_HF_REVISION', '').strip() or 'main'

_MODEL_IDS = ('facebook/dinov2-base', 'facebook/dinov2-small')
_lock = threading.Lock()
_state: dict[str, Any] = {'model': None, 'proc': None, 'id': None, 'err': None}

# Per-view-band soft floors (log + best-of-N ranking) and one hard floor
# (a different subject entirely → the cell is excluded even if the VLM is
# unavailable). Bands are keyed by the angle's `band` field.
BANDS: dict[str, float] = {
    'front': 0.45,
    'quarter': 0.42,
    'side': 0.38,
    'back': 0.28,
    'top': 0.28,
    'close': 0.40,
    'wide': 0.35,
    'detail': 0.25,
}
HARD_FLOOR = float(os.environ.get('ZYG_CREATURE_DINO_HARD_FLOOR', '0.15'))


def enabled() -> bool:
    return os.environ.get('ZYG_CREATURE_DINO', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def soft_floor(band: str) -> float:
    return float(
        os.environ.get(
            f'ZYG_CREATURE_DINO_FLOOR_{(band or "front").upper()}', BANDS.get(band or 'front', BANDS['front'])
        )
    )


def _load() -> bool:
    """Load once. Returns True when a model is ready."""
    if _state['model'] is not None:
        return True
    if _state['err'] is not None:
        return False
    with _lock:
        if _state['model'] is not None:
            return True
        if _state['err'] is not None:
            return False
        # local_files_only, NOT a process-wide HF_HUB_OFFLINE: this runs inside
        # the GUI process, and the judge worker is spawned with a copy of this
        # environment — an offline flag here would silently block the FP8
        # kernel fetch in the judge (2026-08-25).
        last = None
        for mid in _MODEL_IDS:
            try:
                import torch  # noqa: F401
                from transformers import AutoImageProcessor, AutoModel

                proc = AutoImageProcessor.from_pretrained(mid, local_files_only=True, revision=_HF_REVISION)
                model = AutoModel.from_pretrained(mid, local_files_only=True, revision=_HF_REVISION).eval()
                _state.update({'model': model, 'proc': proc, 'id': mid})
                return True
            except Exception as exc:  # cache miss, import error
                last = exc
                continue
        _state['err'] = f'dinov2 unavailable: {last}'
        return False


def model_id() -> str | None:
    return _state['id'] if _load() else None


def unavailable_reason() -> str | None:
    _load()
    return _state['err']


def embed_image(im):
    """L2-normalised CLS embedding of an already-open PIL image, or None."""
    if im is None or not _load():
        return None
    try:
        import torch

        inputs = _state['proc'](images=im.convert('RGB'), return_tensors='pt')
        with torch.no_grad():
            out = _state['model'](**inputs)
        v = out.last_hidden_state[:, 0]
        v = v / v.norm(dim=-1, keepdim=True)
        return v[0]
    except Exception:
        return None


def embed(path: str):
    """L2-normalised CLS embedding (torch tensor on CPU) or None."""
    if not path or not os.path.isfile(path) or not _load():
        return None
    try:
        from PIL import Image

        with Image.open(path) as im:
            return embed_image(im)
    except Exception:
        return None


def similarity(a_path: str, b_path: str) -> float | None:
    a = embed(a_path)
    b = embed(b_path)
    if a is None or b is None:
        return None
    return round(float((a @ b).item()), 4)


def similarity_emb(a, b) -> float | None:
    if a is None or b is None:
        return None
    return round(float((a @ b).item()), 4)


def verdict(score: float | None, band: str) -> dict:
    """{'score', 'soft_ok', 'hard_ok', 'floor'} — None score = metric unavailable
    (both flags True: the metric can never fail a cell it could not measure)."""
    fl = soft_floor(band)
    if score is None:
        return {'score': None, 'soft_ok': True, 'hard_ok': True, 'floor': fl, 'measured': False}
    return {'score': score, 'soft_ok': score >= fl, 'hard_ok': score >= HARD_FLOOR, 'floor': fl, 'measured': True}


def release() -> None:
    """Drop the model (a run is over)."""
    with _lock:
        _state.update({'model': None, 'proc': None, 'id': None})


# ── clips (2026-09-02, S03) ──────────────────────────────────────────────────
# Creatures had a stills path and no clip path at all: a finished creature video
# was scored by nothing. This is the same per-frame contract the human instrument
# uses (identity_bank.check_clip), with DINOv2 CLS in place of a face bank.
CLIP_STRIDE = int(os.environ.get('ZYG_CREATURE_CLIP_STRIDE', '8'))
CLIP_MAX_FRAMES = int(os.environ.get('ZYG_CREATURE_CLIP_MAX_FRAMES', '200'))
# Fraction of FOUND frames that must clear the band's soft floor.
CLIP_PASS_FRAC = float(os.environ.get('ZYG_CREATURE_CLIP_PASS_FRAC', '0.70'))
LEDGER_STATES = ('found', 'not_found', 'not_detectable', 'unmeasurable')


def _explode_frames(clip: str, wd: str, stride: int, max_frames: int):
    import glob
    import subprocess

    os.makedirs(wd, exist_ok=True)
    cmd = [
        'ffmpeg',
        '-v',
        'error',
        '-y',
        '-i',
        str(clip),
        '-vf',
        "select='not(mod(n\\,%d))'" % int(stride),
        '-vsync',
        '0',
    ]
    if max_frames:
        cmd += ['-frames:v', str(int(max_frames))]
    cmd += [os.path.join(wd, 'f_%06d.png')]
    subprocess.run(cmd, check=True, timeout=1800)
    return sorted(glob.glob(os.path.join(wd, 'f_*.png')))


def clip_similarity(
    clip: str,
    anchor: str,
    band: str = 'front',
    stride: int = None,
    max_frames: int = None,
    roi=None,
    pass_frac: float = None,
) -> dict:
    """DINOv2 CLS per sampled frame of `clip` against `anchor`, bands as in BANDS.

    roi: optional (fx0, fy0, fx1, fy1) fractional crop — one creature's part of a
    frame, the same job the human instrument's ROI does.

    FOUR-STATE LEDGER, with the honest limit written down: there is no creature
    DETECTOR, so every extractable frame is `found` and `not_found` /
    `not_detectable` are 0 by construction. A frame the creature has walked out of
    scores low and is indistinguishable from a frame with the WRONG creature in it.
    Until a creature detector exists this metric answers "does this frame look like
    the anchor", not "is the right creature present".

    `ok` is None (UNKNOWN) when nothing was measurable; UNKNOWN is never a pass.
    """
    import shutil
    import tempfile

    stride = int(stride or CLIP_STRIDE)
    max_frames = int(CLIP_MAX_FRAMES if max_frames is None else max_frames)
    fl = soft_floor(band)
    out = {
        'ok': None,
        'clip': str(clip),
        'anchor': str(anchor),
        'band': band,
        'floor': fl,
        'hard_floor': HARD_FLOOR,
        'stride': stride,
        'roi': ([round(float(v), 4) for v in roi] if roi else None),
        'model': model_id(),
        'series': [],
        'ledger': {k: 0 for k in LEDGER_STATES},
        'detector': None,
        'note': 'no creature detector: not_found/not_detectable are 0 by construction (see clip_similarity docstring)',
    }
    if not enabled():
        out['reason'] = 'disabled (ZYG_CREATURE_DINO=0)'
        return out
    if not clip or not os.path.isfile(clip):
        out['reason'] = 'clip_missing'
        return out
    a = embed(anchor)
    if a is None:
        out['reason'] = 'anchor_not_embeddable: ' + (unavailable_reason() or 'unknown')
        return out
    wd = tempfile.mkdtemp(prefix='creatureclip_')
    try:
        from PIL import Image

        try:
            frames = _explode_frames(clip, wd, stride, max_frames)
        except Exception as exc:
            out['ledger']['unmeasurable'] += 1
            out['reason'] = f'extract: {type(exc).__name__}: {exc}'
            return out
        vals = []
        for i, fp in enumerate(frames):
            rec = {'i': i * stride}
            try:
                with Image.open(fp) as im:
                    im = im.convert('RGB')
                    if roi:
                        W, H = im.size
                        fx0, fy0, fx1, fy1 = roi
                        box = (max(0, int(W * fx0)), max(0, int(H * fy0)), min(W, int(W * fx1)), min(H, int(H * fy1)))
                        if box[2] - box[0] > 8 and box[3] - box[1] > 8:
                            im = im.crop(box)
                    v = embed_image(im)
            except Exception:
                v = None
            if v is None:
                out['ledger']['unmeasurable'] += 1
                rec.update({'state': 'unmeasurable', 'score': None})
                out['series'].append(rec)
                continue
            s = round(float((a @ v).item()), 4)
            vals.append(s)
            out['ledger']['found'] += 1
            rec.update({'state': 'found', 'score': s, 'soft_ok': bool(s >= fl), 'hard_ok': bool(s >= HARD_FLOOR)})
            out['series'].append(rec)
        out['sampled'] = len(frames)
        if not vals:
            out['reason'] = 'no_measurable_frame'
            return out
        vs = sorted(vals)
        pf = float(CLIP_PASS_FRAC if pass_frac is None else pass_frac)
        n_soft = sum(1 for s in vals if s >= fl)
        frac = n_soft / len(vals)
        out.update(
            {
                'found': len(vals),
                'measured': True,
                'score': round(sum(vals) / len(vals), 4),
                'score_min': vs[0],
                'score_max': vs[-1],
                'score_p10': vs[max(0, int(0.10 * (len(vs) - 1)))],
                'score_median': vs[len(vs) // 2],
                'spread': round(vs[-1] - vs[0], 4),
                'n_soft_ok': n_soft,
                'pass_frac': round(frac, 4),
                'pass_frac_floor': pf,
                'hard_ok': bool(vs[0] >= HARD_FLOOR),
                'ok': bool(frac >= pf),
                'reason': 'pass' if frac >= pf else 'below_pass_frac',
            }
        )
        return out
    finally:
        shutil.rmtree(wd, ignore_errors=True)
