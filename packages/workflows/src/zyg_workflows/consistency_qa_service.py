# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
consistency_qa_service.py
=========================
Embedding-based identity drift detection for long-form generation.

Uses OpenCLIP (if installed) else falls back to lightweight histogram similarity.
Reference embeddings are cached per character in the bible directory.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

import numpy as np
from PIL import Image
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_CACHE_DIR = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
_DEFAULT_THRESHOLD = float(os.environ.get('ZYG_DRIFT_THRESHOLD', '0.72'))

# 2026-07-31: "no reference embedding" is now an explicit UNKNOWN state instead
# of a hardcoded 1.0 (perfect similarity). The old value was a guaranteed PASS
# for exactly the characters that have no verified reference — the failure was
# silent-positive and indistinguishable in the log from a genuine pass, so a
# wrong-character render scored 'drift score=1.000 (OK)' on every frame.
DRIFT_UNKNOWN: float = -1.0


def is_unknown(score) -> bool:
    """True when *score* is the UNVERIFIED sentinel (never a pass)."""
    try:
        return score is None or float(score) < 0.0
    except Exception:
        return True


class DriftResult(tuple):
    """(passed, score) with an explicit verification status.

    Unpacks as the legacy 2-tuple so existing callers keep working; new callers
    should consult ``.status``:
      'ok'      — verified against a real reference embedding, above threshold
      'drift'   — verified, below threshold
      'unknown' — NO reference embedding exists; nothing was verified. This is
                  never a pass, and ``score`` is ``DRIFT_UNKNOWN`` (-1.0), which
                  formats as -1.000 rather than pretending to be a similarity.
    """

    # (no __slots__ — a variable-length tuple subtype cannot declare one)

    def __new__(cls, passed, score, status: str = 'ok', reason: str = ''):
        obj = super().__new__(cls, (passed, score))
        obj.status = status
        obj.reason = reason
        return obj

    @property
    def verified(self) -> bool:
        return self.status != 'unknown'


def _cache_path(char_id: str) -> str:
    return os.path.join(_CACHE_DIR, char_id, '.consistency_ref_embedding.json')


def has_reference(char_id: str) -> bool:
    """2026-07-31: True when a verified reference embedding is cached for
    *char_id*. Callers that want to HARD-REJECT on drift must check this first —
    without a reference there is nothing to reject against."""
    return _load_reference(char_id) is not None


def _load_clip():
    try:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            'ViT-B-32',
            pretrained='openai',
        )
        model.eval()
        if torch.cuda.is_available():
            model = model.to('cuda')
        device = next(model.parameters()).device

        def embed(path: str) -> np.ndarray:
            img = preprocess(Image.open(path).convert('RGB')).unsqueeze(0).to(device)
            with torch.no_grad():
                feat = model.encode_image(img)
                feat = feat / feat.norm(dim=-1, keepdim=True)
            return feat.cpu().numpy().flatten()

        return embed, 'openclip'
    except Exception as _exc:
        _zyg_log.warning('openclip embedder unavailable, falling back to the histogram embedder: %s', _exc)

    def _hist_embed(path: str) -> np.ndarray:
        img = np.array(Image.open(path).convert('RGB').resize((128, 128)))
        hist, _ = np.histogramdd(
            img.reshape(-1, 3),
            bins=(8, 8, 8),
            range=((0, 256), (0, 256), (0, 256)),
        )
        v = hist.flatten().astype(np.float64)
        v /= np.linalg.norm(v) + 1e-8
        return v

    return _hist_embed, 'histogram'


_embed_fn, _embed_backend = _load_clip()
_secondary_embed_fn = None
_secondary_backend = None


def _try_load_secondary_backend() -> tuple[Optional[Callable[[str], np.ndarray]], Optional[str]]:
    """Load a secondary embedding backend if the primary is the lightweight
    histogram fallback. Returns (embed_fn, backend_name) or (None, None) on failure.

    Used by ``check_drift`` to escalate from histogram → CLIP on apparent drift,
    avoiding expensive FLUX regenerations triggered by histogram false-positives.
    """
    global _secondary_embed_fn, _secondary_backend
    if _secondary_embed_fn is not None or _secondary_backend == 'unavailable':
        return _secondary_embed_fn, _secondary_backend
    if _embed_backend == 'openclip':
        # Primary is already the strong backend; nothing better to escalate to
        _secondary_backend = 'unavailable'
        return None, None
    try:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            'ViT-B-32',
            pretrained='openai',
        )
        model.eval()
        if torch.cuda.is_available():
            model = model.to('cuda')
        device = next(model.parameters()).device

        def embed(path: str) -> np.ndarray:
            img = preprocess(Image.open(path).convert('RGB')).unsqueeze(0).to(device)
            with torch.no_grad():
                feat = model.encode_image(img)
                feat = feat / feat.norm(dim=-1, keepdim=True)
            return feat.cpu().numpy().flatten()

        _secondary_embed_fn = embed
        _secondary_backend = 'openclip'
        return embed, 'openclip'
    except Exception:
        _secondary_backend = 'unavailable'
        return None, None


def register_reference(char_id: str, image_path: str, log_fn: Callable[[str], None] | None = None) -> bool:
    if not char_id or not os.path.isfile(image_path):
        return False
    try:
        vec = _embed_fn(image_path).tolist()
        os.makedirs(os.path.join(_CACHE_DIR, char_id), exist_ok=True)
        with open(_cache_path(char_id), 'w', encoding='utf-8') as f:
            json.dump(
                {
                    'char_id': char_id,
                    'reference_image': image_path,
                    'backend': _embed_backend,
                    'embedding': vec,
                },
                f,
            )
        if log_fn:
            log_fn(f'Consistency QA: registered reference ({_embed_backend}) → {os.path.basename(image_path)}')
        return True
    except Exception as exc:
        if log_fn:
            log_fn(f'Consistency QA: reference registration failed — {exc}')
        return False


def _load_reference(char_id: str) -> Optional[np.ndarray]:
    path = _cache_path(char_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return np.array(data['embedding'], dtype=np.float64)
    except Exception:
        return None


def similarity_to_reference(image_path: str, char_id: str) -> Optional[float]:
    """Cosine similarity in [0, 1] (higher = more consistent with reference).

    2026-07-31: returns **None** (UNKNOWN — nothing was verified) when no
    reference embedding is cached, the image is missing, or embedding fails.
    It used to return 1.0 in all three cases, i.e. a perfect score for an
    unverifiable frame."""
    ref = _load_reference(char_id)
    if ref is None or not os.path.isfile(image_path):
        return None
    try:
        cur = _embed_fn(image_path)
        ref = ref / (np.linalg.norm(ref) + 1e-8)
        cur = cur / (np.linalg.norm(cur) + 1e-8)
        sim = float(np.dot(ref, cur))
        return max(0.0, min(1.0, (sim + 1.0) / 2.0 if _embed_backend == 'histogram' else sim))
    except Exception:
        return None


def check_drift(
    image_path: str,
    char_id: str,
    threshold: float | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[bool, float]:
    """
    Returns (passed, score).  passed=False means identity drift detected.

    2026-07-31: the return value is a :class:`DriftResult` — it still unpacks as
    ``(passed, score)``, but carries ``.status`` ('ok' | 'drift' | 'unknown').
    'unknown' means NO reference embedding exists, so nothing was verified; it
    is reported as NOT PASSED with score ``DRIFT_UNKNOWN`` (-1.0) instead of the
    old hardcoded 1.0 pass. Set ZYG_CQA_UNKNOWN_NOT_PASS=0 to restore the legacy
    (silently-passing) behaviour.

    When the primary backend is the histogram fallback and reports drift, a
    secondary CLIP check is attempted on-the-fly (loaded once). This avoids
    expensive scene regenerations triggered by histogram false-positives on
    dark / low-contrast frames.
    """
    # Histogram is noisier than embeddings; use a lower default threshold for it
    if threshold is None:
        if _embed_backend == 'histogram':
            thr = float(os.environ.get('ZYG_DRIFT_THRESHOLD_HIST', '0.60'))
        else:
            thr = _DEFAULT_THRESHOLD
    else:
        thr = threshold
    score = similarity_to_reference(image_path, char_id)
    if score is None:
        _strict = str(os.environ.get('ZYG_CQA_UNKNOWN_NOT_PASS', '1')).strip().lower() not in (
            '0',
            'false',
            'no',
            'off',
        )
        _reason = (
            'no reference embedding cached'
            if _load_reference(char_id) is None
            else 'embedding failed / image unreadable'
        )
        if log_fn:
            log_fn(
                f'Consistency QA: drift UNVERIFIED ({_reason}) — '
                f'identity was NOT checked for {os.path.basename(image_path or "?")}'
                + ('' if _strict else ' [ZYG_CQA_UNKNOWN_NOT_PASS=0 → reported as pass]')
            )
        if _strict:
            return DriftResult(False, DRIFT_UNKNOWN, 'unknown', _reason)
        return DriftResult(True, 1.0, 'unknown', _reason)
    passed = score >= thr
    if log_fn:
        log_fn(
            f'Consistency QA: drift score={score:.3f} '
            f'({"OK" if passed else "DRIFT"}) threshold={thr:.2f} backend={_embed_backend}'
        )
    if passed or _embed_backend != 'histogram':
        return DriftResult(passed, score, 'ok' if passed else 'drift')

    # Histogram says drift — try escalating to CLIP before believing it.
    sec_fn, sec_backend = _try_load_secondary_backend()
    if sec_fn is None:
        return DriftResult(passed, score, 'drift')
    ref_master = None
    try:
        from zyg_workflows import character_bible_service as cbs

        pkg = cbs.load(char_id)
        ref_master = cbs.get_master_reference(pkg)
    except Exception:
        ref_master = None
    if not ref_master or not os.path.isfile(ref_master):
        return DriftResult(passed, score, 'drift')
    try:
        ref_vec = sec_fn(ref_master)
        cur_vec = sec_fn(image_path)
        ref_n = ref_vec / (np.linalg.norm(ref_vec) + 1e-8)
        cur_n = cur_vec / (np.linalg.norm(cur_vec) + 1e-8)
        sec_score = float(np.dot(ref_n, cur_n))
        sec_score = max(0.0, min(1.0, sec_score))
        sec_thr = _DEFAULT_THRESHOLD
        sec_passed = sec_score >= sec_thr
        if log_fn:
            log_fn(
                f'Consistency QA: histogram drift escalated → CLIP score={sec_score:.3f} '
                f'({"OK" if sec_passed else "DRIFT"}) threshold={sec_thr:.2f} backend={sec_backend}'
            )
        return DriftResult(sec_passed, sec_score, 'ok' if sec_passed else 'drift')
    except Exception as exc:
        if log_fn:
            log_fn(f'Consistency QA: CLIP escalation failed ({exc}) — trusting histogram')
        return DriftResult(passed, score, 'drift')


def ensure_reference_from_bible(char_id: str, log_fn: Callable[[str], None] | None = None) -> bool:
    if _load_reference(char_id) is not None:
        return True
    try:
        from zyg_workflows import character_bible_service as cbs

        pkg = cbs.load(char_id)
        ref = cbs.get_master_reference(pkg)
        if ref:
            return register_reference(char_id, ref, log_fn=log_fn)
    except Exception as _exc:
        _zyg_log.warning('bible reference lookup failed, falling back to the contact-sheet anchor: %s', _exc)
    # 2026-07-31: contact-sheet characters routinely have neither
    # conditioning.master_reference_image nor ipadapter_reference_images, so
    # they never got a drift reference and every frame scored a fake 1.000.
    # The contact-sheet identity anchor IS a verified still of the character —
    # seed from it. ZYG_CQA_ANCHOR_SEED=0 disables. Guarded import: a missing
    # contact_sheet_pipeline just leaves the state UNKNOWN, never a pass.
    if str(os.environ.get('ZYG_CQA_ANCHOR_SEED', '1')).strip().lower() not in ('0', 'false', 'no', 'off'):
        try:
            from zyg_workflows import contact_sheet_pipeline as _csp_ref

            for _fn in ('identity_anchor_face_path', 'identity_profile_anchor_face_path'):
                _getter = getattr(_csp_ref, _fn, None)
                if not callable(_getter):
                    continue
                _anchor = _getter(char_id)
                if _anchor and os.path.isfile(_anchor):
                    if log_fn:
                        log_fn(
                            f'Consistency QA: seeding drift reference from the verified '
                            f'contact-sheet anchor ({os.path.basename(_anchor)})'
                        )
                    return register_reference(char_id, _anchor, log_fn=log_fn)
        except Exception as exc:
            if log_fn:
                log_fn(f'Consistency QA: contact-sheet anchor seeding skipped ({exc!r})')
    return False


_text_clip_model = None
_text_clip_tokenizer = None
_text_clip_preprocess = None
_text_clip_device = None


def score_text_match(image_path: str, prompt_text: str) -> float:
    """CLIP text–image similarity in [0, 1]. Returns 0.5 when CLIP is unavailable."""
    global _text_clip_model, _text_clip_tokenizer, _text_clip_preprocess, _text_clip_device
    if not image_path or not os.path.isfile(image_path) or not (prompt_text or '').strip():
        return 0.5
    try:
        import open_clip
        import torch

        if _text_clip_model is None:
            _text_clip_model, _, _text_clip_preprocess = open_clip.create_model_and_transforms(
                'ViT-B-32',
                pretrained='openai',
            )
            _text_clip_tokenizer = open_clip.get_tokenizer('ViT-B-32')
            _text_clip_model.eval()
            _text_clip_device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            _text_clip_model = _text_clip_model.to(_text_clip_device)
        img = _text_clip_preprocess(Image.open(image_path).convert('RGB')).unsqueeze(0).to(_text_clip_device)
        tokens = _text_clip_tokenizer([prompt_text.strip()]).to(_text_clip_device)
        with torch.no_grad():
            img_feat = _text_clip_model.encode_image(img)
            txt_feat = _text_clip_model.encode_text(tokens)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            txt_feat = txt_feat / txt_feat.norm(dim=-1, keepdim=True)
            sim = float((img_feat * txt_feat).sum().cpu().item())
        return max(0.0, min(1.0, sim))
    except Exception:
        return 0.5
