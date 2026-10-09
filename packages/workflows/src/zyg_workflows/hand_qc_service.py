# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Hand detection + quality scoring (2026-07-24 HandFixer rebuild).

Why this module exists
----------------------
The previous hand QA was structurally dead code: it used the mediapipe LEGACY
``mp.solutions`` API, which mediapipe 0.10.35 removed — every call raised
AttributeError and a blanket ``except`` returned a PERFECT 1.0 score for every
frame of every run (run 6278904c shipped 12 defective frames at 'hand=1.00').
Landmark-geometry scoring was also evaluated for the rebuild and rejected:
MediaPipe fits its fixed 21-landmark/5-finger topology onto ANY hand, so
malformed hands measure geometrically 'plausible' (verified on the 6278904c
frames: every known-bad hand scored clean).

2026-07-30 backend switch: ``detect_hand_boxes`` now runs on MediaPipe
hand_landmarker (Apache-2.0, via anatomy_qc) instead of ADetailer
hand_yolov8s, whose ultralytics runtime is AGPL-3.0 and cannot ship. The
fail-closed contract is unchanged — see ``_select_backend`` and
``ZYG_HANDS_BACKEND``. The landmark-geometry finding above still stands and is
NOT what anatomy_qc scores: it measures fit residuals (degenerate fingertip
clusters, reversed joint chains, ratios outside the landmarker's own envelope),
never a finger count.

This module provides:
  * ``detect_hand_boxes(path)`` — hand boxes from the selected backend; the
    shared detection gate for the HandFixer. FAIL-CLOSED: raises on error;
    callers must skip repair when detection is unavailable, never inpaint blind.
  * ``hand_quality(path)`` — (score, issues): YOLO hand crops judged by the
    local Ollama vision model (same tier the contact-sheet VLM judge uses,
    proven to run alongside ComfyUI on this box). Returns (None, [reason])
    when scoring is UNAVAILABLE — callers must treat None as "unknown",
    never as "perfect".
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_LOCK = threading.Lock()
_YOLO_MODEL = None
_WARNED = False
_BACKEND = None  # 'mediapipe' | 'yolo' | 'mediapipe-unavailable'

# VLM circuit breaker: after _CB_MAX consecutive transport failures the judge
# reports unavailable instantly for _CB_COOLDOWN_S (a wedged Ollama must not
# stall a 25-scene run at full timeout per crop).
_CB_FAILS = 0
_CB_MAX = int(os.environ.get('ZYG_HAND_VLM_CB_FAILS', '2'))
_CB_COOLDOWN_S = float(os.environ.get('ZYG_HAND_VLM_CB_COOLDOWN_S', '600'))
_CB_OPEN_UNTIL = 0.0

# Memoized frame scores keyed by (abspath, mtime, size) — the Stage 3.5 loop
# legitimately asks for the same unchanged file's score several times.
_SCORE_CACHE: dict = {}
_SCORE_CACHE_MAX = 128

_COMFY_ROOT = str(paths.ZYG_COMFY_ROOT)
_HAND_YOLO = os.path.join(_COMFY_ROOT, 'models', 'ultralytics', 'bbox', 'hand_yolov8s.pt')

# ── Style-drift OOD gate (2026-08-31) ───────────────────────────────────────
# The VLM judge is calibrated on photoreal hands and has been caught confidently
# WRONG off that domain: on arcane-restyled stills it scored a fused-mitten hand
# defective=false at confidence="high" (see project_hand_repair_arcane memory),
# and the only fix shipped was a one-off SKIP_CLEAN override for that one art
# style. That doesn't generalise to the next stylised domain. Softmax-style
# self-reported confidence cannot detect its own miscalibration (same reason a
# linear probe cannot abstain — see vfx_probes.py) so this is an EXTERNAL
# check: embed the crop with the same frozen DINOv2 backbone vfx_probes uses,
# and compare it to a reference set of known photoreal hand crops. A crop far
# from that reference means the judge is being asked to extrapolate outside
# its calibration domain, regardless of how confident it claims to be.
_OOD_REF_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'data', 'runtime', 'hand_qc', 'ood_reference.npz'
)
_OOD_K = int(os.environ.get('ZYG_HAND_OOD_K', '5'))
_OOD_STATE: dict = {'ref': None, 'threshold': None, 'loaded': False}
_OOD_SCORE_CAP = float(os.environ.get('ZYG_HAND_OOD_SCORE_CAP', '0.85'))

_OLLAMA_HOST = os.environ.get('ZYG_OLLAMA_HOST', paths.ZYG_OLLAMA_URL).rstrip('/')
_VLM_MODEL = os.environ.get('ZYG_HAND_VLM_MODEL', os.environ.get('ZYG_CELL_VLM_LOCAL_MODEL', 'qwen3.5:9b')).strip()
_VLM_TIMEOUT = float(os.environ.get('ZYG_HAND_VLM_TIMEOUT_S', '90'))

_VLM_PROMPT = (
    'You are inspecting a CROPPED region of an AI-generated photo that should '
    'contain a human hand. Judge ONLY hand anatomy. Reply with STRICT JSON, '
    'no other text: {"hand_visible": true/false, "defective": true/false, '
    '"problem": "<short reason or empty>", "confidence": "high"|"medium"|"low"}. '
    'defective=true means a clear anatomical problem: wrong number of fingers '
    '(more than five or fewer than four visible on an open hand), fused or '
    'merged fingers, fingers bending backwards, extra or missing thumb, '
    'fingernails on the palm side, a smeared or melted blob instead of a hand, '
    'or a hand whose skin tone is completely different from a natural human '
    'hand. Partially visible, curled, or holding hands are NORMAL unless '
    'clearly malformed. Be conservative: only defective=true when you are '
    'confident.'
)


_CONCRETE_DEFECT = re.compile(
    r'extra|missing|fused|merged|backward|blob|melt|smear|six|seven|nail|'
    r'wrong number|deformed|malformed|claw|too many|stub',
    re.IGNORECASE,
)


def _get_yolo():
    global _YOLO_MODEL
    with _LOCK:
        if _YOLO_MODEL is None:
            from ultralytics import YOLO

            if not os.path.isfile(_HAND_YOLO):
                raise FileNotFoundError(f'hand YOLO weights missing: {_HAND_YOLO}')
            _YOLO_MODEL = YOLO(_HAND_YOLO)
        return _YOLO_MODEL


def _select_backend() -> str:
    """Which detector backs detect_hand_boxes. Decided ONCE, on availability.

    2026-07-30: MediaPipe hand_landmarker (Apache-2.0) replaces the ADetailer
    hand_yolov8s path, which runs on ultralytics (AGPL-3.0) — a licence we
    cannot ship commercially. ZYG_HANDS_BACKEND:
        'auto' (default) — mediapipe when anatomy_qc + the .task bundle are
                           importable, otherwise the legacy YOLO path, and the
                           downgrade is recorded as a fallback, not hidden;
        'mediapipe'      — mediapipe only; if it cannot load, detect_hand_boxes
                           RAISES and the fixer stays closed;
        'yolo'           — legacy path (AGPL: development only).

    Selection happens at AVAILABILITY time, never per call: a per-call
    except-and-switch is exactly the kind of silent degrade that let run
    6278904c inpaint blind. Once chosen, a detection error propagates.
    """
    global _BACKEND
    with _LOCK:
        if _BACKEND is not None:
            return _BACKEND
        want = (os.environ.get('ZYG_HANDS_BACKEND') or 'auto').strip().lower()
        if want == 'yolo':
            _BACKEND = 'yolo'
            return _BACKEND
        ok, why = False, 'anatomy_qc unavailable'
        try:
            from zyg_workflows import anatomy_qc as _aq

            ok, why = _aq.hands_available()
        except Exception as exc:
            why = f'{type(exc).__name__}: {exc}'
        if ok:
            _BACKEND = 'mediapipe'
        elif want == 'mediapipe':
            _BACKEND = 'mediapipe-unavailable'  # fail CLOSED, never to YOLO
            _zyg_log.info(
                f'[HAND-QC] ZYG_HANDS_BACKEND=mediapipe but it will not load '
                f'({why}) — hand detection is DOWN, the fixer stays closed'
            )
        else:
            _BACKEND = 'yolo'
            _zyg_log.info(
                f'[HAND-QC] mediapipe unavailable ({why}) — falling back to the AGPL ultralytics hand detector'
            )
            try:
                from zyg_workflows import run_ledger

                run_ledger.record_fallback('hand_detect_backend', 'mediapipe', 'yolo', detail=why)
            except Exception as _exc:
                _zyg_log.warning('fallback ledger record failed, the backend downgrade is unrecorded: %s', _exc)
        return _BACKEND


def detect_hand_boxes(image_path: str, conf: float | None = None) -> list[dict]:
    """Hand boxes: [{'box': (x1,y1,x2,y2), 'conf': float}, ...].

    RAISES on any detection failure — the HandFixer must fail closed
    (the old gate returned (True, -1) on exceptions and 29/29 renders of run
    6278904c ran a blind inpaint logged as 'applied (-1 YOLO hand box(es))').
    That contract is unchanged by the backend switch: whichever detector is
    selected, an error here reaches the caller and the repair is skipped.
    """
    backend = _select_backend()
    if backend == 'mediapipe':
        from zyg_workflows import anatomy_qc as _aq

        return _aq.detect_hand_boxes_strict(image_path, conf)
    if backend != 'yolo':
        raise RuntimeError(
            'hand detection unavailable: ZYG_HANDS_BACKEND=mediapipe but the '
            'mediapipe landmarker will not load (gate stays CLOSED)'
        )
    if conf is None:
        conf = float(os.environ.get('ZYG_HAND_FIXER_YOLO_CONF', '0.35'))
    model = _get_yolo()
    # predict under the lock: Ultralytics Model objects share a stateful
    # predictor and are not thread-safe (contact-sheet + storyteller threads
    # can both reach this in the one Flask process). CPU inference ~0.3s.
    with _LOCK:
        res = model.predict(image_path, conf=conf, verbose=False, device='cpu')[0]
    out: list[dict] = []
    if res.boxes is not None:
        for b in res.boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
            out.append({'box': (x1, y1, x2, y2), 'conf': float(b.conf[0])})
    return out


def _crop_pil(image_path: str, box, margin: float = 0.30, min_side: int = 448):
    """The same hand crop the VLM judge sees, as a PIL image (caller must close)."""
    from PIL import Image

    with Image.open(image_path) as im:
        im = im.convert('RGB')
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        mx, my = w * margin, h * margin
        cx1 = max(0, int(x1 - mx))
        cy1 = max(0, int(y1 - my))
        cx2 = min(im.width, int(x2 + mx))
        cy2 = min(im.height, int(y2 + my))
        crop = im.crop((cx1, cy1, cx2, cy2))
        if min(crop.size) < min_side:
            scale = min_side / max(1, min(crop.size))
            crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))))
        return crop


def _crop_b64(image_path: str, box, margin: float = 0.30, min_side: int = 448) -> str:
    crop = _crop_pil(image_path, box, margin, min_side)
    buf = io.BytesIO()
    crop.save(buf, format='JPEG', quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def _load_ood_reference():
    """Lazy-load the cached reference embeddings. Returns None when unavailable
    (no cached file yet, or the embedding backbone isn't ready) — callers must
    treat that as 'cannot check', never as 'in distribution'."""
    if _OOD_STATE['loaded']:
        return _OOD_STATE['ref']
    _OOD_STATE['loaded'] = True
    if not os.path.isfile(_OOD_REF_PATH):
        return None
    try:
        import numpy as np

        data = np.load(_OOD_REF_PATH)
        ref = data['ref'].astype(np.float32)
        # Self-consistency threshold: how far each reference crop sits from its
        # OWN k nearest neighbours (leave-one-out). Not a hand-picked constant —
        # it is measured from the reference set's own internal spread, the same
        # way a probe's OOD threshold in vfx_probes.py is measured rather than
        # guessed. Built 2026-08-31 from run 59e8d33f (35 photoreal crops);
        # scripts/build_hand_ood_reference.py sanity-checked it against the
        # known-bad-but-still-photoreal run 6278904c and got 0/37 false-flagged
        # — the gate reacts to STYLE, not to anatomical defect, on that sample.
        # It has NOT yet been checked against a real stylised (e.g. arcane)
        # frame, since none shipped with this checkout — tighten
        # ZYG_HAND_OOD_DIST_THRESHOLD once one confirms the separation there.
        n = np.linalg.norm(ref, axis=1, keepdims=True)
        unit = ref / np.maximum(n, 1e-8)
        sim = unit @ unit.T
        np.fill_diagonal(sim, -1.0)
        k = min(_OOD_K, sim.shape[1])
        self_dist = 1.0 - np.sort(sim, axis=1)[:, -k:].mean(axis=1)
        auto_threshold = float(self_dist.mean() + 4 * self_dist.std())
        threshold = float(os.environ.get('ZYG_HAND_OOD_DIST_THRESHOLD', '') or auto_threshold)
        _OOD_STATE['ref'] = unit
        _OOD_STATE['threshold'] = threshold
        _zyg_log.info(
            f'[HAND-QC] OOD reference loaded: {len(ref)} crops, '
            f'auto threshold {auto_threshold:.3f} (using {threshold:.3f})'
        )
        return _OOD_STATE['ref']
    except Exception as exc:
        _zyg_log.info(f'[HAND-QC] OOD reference failed to load: {type(exc).__name__}: {exc}')
        _OOD_STATE['ref'] = None
        return None


def _ood_distance(crop) -> float | None:
    """k-NN cosine distance from one PIL hand crop to the reference set, or
    None when the gate is unavailable (missing reference, missing embedder)."""
    ref = _load_ood_reference()
    if ref is None:
        return None
    try:
        import numpy as np
        from zyg_workflows import vfx_embed as VE

        if not VE.available().get('ok'):
            return None
        feat = VE.embed_images([crop])
        n = np.linalg.norm(feat, axis=1, keepdims=True)
        unit = feat / np.maximum(n, 1e-8)
        sim = unit @ ref.T
        k = min(_OOD_K, sim.shape[1])
        return float(1.0 - np.sort(sim, axis=1)[:, -k:].mean(axis=1)[0])
    except Exception as exc:
        _zyg_log.info(f'[HAND-QC] OOD distance check failed: {type(exc).__name__}: {exc}')
        return None


def _parse_vlm_json(text: str) -> dict | None:
    m = re.search(r'\{.*\}', text or '', re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _judge_crop(crop_b64: str) -> dict:
    """One VLM verdict for one hand crop. Raises on transport failure or when
    the circuit breaker is open."""
    global _CB_FAILS, _CB_OPEN_UNTIL
    import time as _t_cb

    if _t_cb.monotonic() < _CB_OPEN_UNTIL:
        raise RuntimeError('hand-VLM circuit breaker open')

    try:
        _hand_payload_extra = {'think': False} if _VLM_MODEL.startswith('qwen3') else {}
        from zyg_workflows import llm_audit as _la_hq

        _resp_hq = _la_hq.ollama_post(
            f'{_OLLAMA_HOST}/api/generate',
            {
                **_hand_payload_extra,
                'model': _VLM_MODEL,
                'prompt': _VLM_PROMPT,
                'images': [crop_b64],
                'stream': False,
                'keep_alive': os.environ.get('ZYG_HAND_VLM_KEEP_ALIVE', '5m'),
                'options': {'num_ctx': 4096, 'num_predict': 150, 'temperature': 0.0},
            },
            timeout=_VLM_TIMEOUT,
            stage='hand_qc',
        )
    except Exception:
        _CB_FAILS += 1
        if _CB_FAILS >= _CB_MAX:
            _CB_OPEN_UNTIL = _t_cb.monotonic() + _CB_COOLDOWN_S
            _zyg_log.info(
                f'[HAND-QC] VLM breaker OPEN for {_CB_COOLDOWN_S:.0f}s ({_CB_FAILS} consecutive transport failures)'
            )
        raise
    _CB_FAILS = 0
    parsed = _parse_vlm_json(_resp_hq.get('response') or '')
    if not isinstance(parsed, dict):
        raise ValueError('VLM returned unparseable output')
    return parsed


def judge_image_file(path: str) -> dict:
    """One VLM hand verdict for an image file (used by the HandFixer to
    accept/reject each repainted crop). Raises on transport failure."""
    with open(path, 'rb') as fh:
        b64 = base64.b64encode(fh.read()).decode()
    return _judge_crop(b64)


def hand_quality(image_path: str) -> tuple:
    """(score, issues). score is None when scoring is UNAVAILABLE.

    Callers MUST treat None as unknown — the old code's 1.0-on-error is what
    let 12 defective frames ship in run 6278904c with 'hand=1.00' logs.

    Scoring: 1.0 when no hands or all hands judged fine; each hand the VLM
    flags as defective (medium+ confidence) costs 0.45. Results are memoized
    per (path, mtime, size) — the Stage 3.5 loop scores the same unchanged
    file several times per attempt.
    """
    try:
        _st = os.stat(image_path)
        _ck = (os.path.abspath(image_path), _st.st_mtime_ns, _st.st_size)
    except OSError:
        _ck = None
    if _ck is not None and _ck in _SCORE_CACHE:
        return _SCORE_CACHE[_ck]
    _res = _hand_quality_uncached(image_path)
    if _ck is not None and _res[0] is not None:  # never cache 'unavailable'
        if len(_SCORE_CACHE) >= _SCORE_CACHE_MAX:
            _SCORE_CACHE.pop(next(iter(_SCORE_CACHE)))
        _SCORE_CACHE[_ck] = _res
    return _res


def _hand_quality_uncached(image_path: str) -> tuple:
    global _WARNED
    try:
        boxes = detect_hand_boxes(image_path)
    except Exception as exc:
        return None, [f'hand QC unavailable (detector [{_BACKEND}]: {type(exc).__name__}: {exc})']

    if not boxes:
        return 1.0, []

    # Judge the largest boxes first; cap crops per frame to bound latency.
    _max_crops = int(os.environ.get('ZYG_HAND_VLM_MAX_CROPS', '3'))
    boxes = sorted(
        boxes,
        key=lambda b: (b['box'][2] - b['box'][0]) * (b['box'][3] - b['box'][1]),
        reverse=True,
    )[:_max_crops]

    issues: list[str] = []
    penalty = 0.0
    ood_unverified = False
    for bi, b in enumerate(boxes):
        crop = _crop_pil(image_path, b['box'])
        try:
            buf = io.BytesIO()
            crop.save(buf, format='JPEG', quality=92)
            verdict = _judge_crop(base64.b64encode(buf.getvalue()).decode())
        except Exception as exc:
            if not _WARNED:
                _WARNED = True
                _zyg_log.info(f'[HAND-QC] VLM judge unavailable: {type(exc).__name__}: {exc}')
            return None, [f'hand QC unavailable (VLM: {type(exc).__name__})']
        if not verdict.get('hand_visible', True):
            continue
        conf = str(verdict.get('confidence') or '').lower()
        problem = str(verdict.get('problem') or 'anatomical defect')[:120]
        flagged = False
        if verdict.get('defective') and conf in ('high', 'medium'):
            # Medium-confidence flags must name a CONCRETE defect — the local
            # model sometimes flags ordinary curled/holding hands at medium
            # with vague 'not fully visible' reasoning (calibrated on the
            # 6278904c known-bad + 59e8d33f known-good frames).
            if conf == 'medium' and not _CONCRETE_DEFECT.search(problem):
                pass
            else:
                issues.append(f'hand {bi + 1}: {problem} ({conf})')
                penalty += 0.45
                flagged = True
        if not flagged:
            # The judge says this hand is fine. Its own confidence field can't
            # tell us whether that's trustworthy — it was "high" confidence on
            # the documented arcane fused-mitten failure too. Check externally:
            # is this crop even inside the domain the judge was calibrated on?
            dist = _ood_distance(crop)
            if dist is not None and dist > (_OOD_STATE['threshold'] or float('inf')):
                issues.append(
                    f'hand {bi + 1}: judge says clean ({conf}) but the crop is '
                    f'style-OOD (dist {dist:.3f} > {_OOD_STATE["threshold"]:.3f}) '
                    f'— treating as unverified, not confirmed clean'
                )
                ood_unverified = True

    score = max(0.0, 1.0 - penalty)
    if ood_unverified and penalty == 0.0:
        score = min(score, _OOD_SCORE_CAP)
    return score, issues
