# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# This module keeps the original top import block for its siblings and the package.
import json
import os
import subprocess
import sys
import time
import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows.bin import exe

# Re-exported for the siblings, which read it back out of this module
# (ownership.py: ``from zyg_workflows.continuity_qc.models import … json, os, paths …``).
__all__ = ['json']


# Hugging Face revision for every from_pretrained/download in this module. 'main' is the
# floating default these call sites used implicitly; $ZYG_HF_REVISION pins a commit instead.
_HF_REVISION = os.environ.get('ZYG_HF_REVISION', '').strip() or 'main'

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.continuity_qc')


# ── on-disk assets (env-overridable) ──────────────────────────────────────────
GDINO_WEIGHTS = os.environ.get('ZYG_GDINO_WEIGHTS') or str(
    paths.ZYG_MODELS_ROOT / 'groundingdino' / 'groundingdino_swint_ogc.pth'
)
GDINO_CONFIG = os.environ.get('ZYG_GDINO_CONFIG') or ''  # '' → package default
SAM2_WEIGHTS = os.environ.get('ZYG_SAM2_WEIGHTS') or str(
    paths.ZYG_COMFY_ROOT / 'models' / 'sam2' / 'sam2.1_hiera_base_plus.safetensors'
)
SAM2_NODE_DIR = paths.ZYG_SAM2_NODE_DIR
DINOV2_MODEL_ID = os.environ.get('ZYG_DINOV2_MODEL') or 'facebook/dinov2-small'

# The render recipe's chaining geometry: context 81 frames, overlap 24 → stride 57.
CONTEXT_STRIDE_FRAMES = int(os.environ.get('ZYG_CONTEXT_STRIDE') or 57)

# ── calibrated thresholds (see CALIBRATION note at end of file) ───────────────
DEFAULT_THRESHOLDS = {
    'det_score_min': 0.25,  # GroundingDINO phrase score to call an object seen
    'min_mask_frac': 2.0e-4,  # mask smaller than this = not present in that frame
    'presence_rate_min': 0.60,  # < this fraction of sampled frames → 'vanished'
    'box_iou_min': 0.45,  # grounded box IoU across a window seam
    'area_drift_pct_max': 45.0,  # |mask-area change| across a window seam, percent
    'dino_seam_cos_min': 0.80,  # across-the-boundary crop cosine — PRIMARY gate
    'dino_anchor_min': 0.60,  # min cosine to the frame-0 crop anchor (slow drift)
    'bg_seam_cos_min': 0.78,  # background across-the-boundary cosine
    'bg_anchor_min': 0.55,  # background cosine to frame 0 (grade creep)
    'own_overlap_min': 0.12,  # prop-box fraction inside the owner's actor box
    'own_margin_min': 0.05,  # owner must beat runner-up by this much
    'bg_exclude_topk': 3,  # instances per background_exclude prompt to mask
}

_GPU_FLOOR_BYTES = int(os.environ.get('ZYG_QC_VRAM_FLOOR_MB') or 8192) * 1024 * 1024

_CACHE = {}  # (kind, device) -> model
_SAM2_PKG = '_zyg_sam2node'


# ── device selection ──────────────────────────────────────────────────────────
def _free_vram_bytes():
    """Free VRAM via nvidia-smi. Deliberately NOT torch.cuda.mem_get_info —
    that would create a CUDA context (and take VRAM) just to ask a question."""
    try:
        out = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            return 0
        return int(out.stdout.strip().splitlines()[0].strip()) * 1024 * 1024
    except Exception:
        return 0


def pick_device(pref='auto', log_fn=None):
    """'auto' → cuda only when >= 8 GB VRAM is free, else cpu (the GPU floor rule).
    Explicit 'cpu'/'cuda' pass straight through. ZYG_CONTINUITY_DEVICE overrides."""
    log = log_fn or (lambda _m: None)
    env = os.environ.get('ZYG_CONTINUITY_DEVICE')
    if env:
        return env
    if pref and pref not in ('auto', 'auto-with-8GB-floor-else-cpu'):
        return pref
    if os.environ.get('CUDA_VISIBLE_DEVICES', None) == '':
        return 'cpu'
    free = _free_vram_bytes()
    if free >= _GPU_FLOOR_BYTES:
        log(f'[continuity_qc] device=cuda ({free / 1024**3:.1f} GB free)')
        return 'cuda'
    log(
        f'[continuity_qc] device=cpu (only {free / 1024**3:.1f} GB VRAM free, '
        f'floor {_GPU_FLOOR_BYTES / 1024**3:.0f} GB) — ~10x slower, still correct'
    )
    return 'cpu'


# ── ledger (defensive) ────────────────────────────────────────────────────────
def _gate(run_id, gate, outcome, score=None, tag=''):
    try:
        from zyg_workflows import run_ledger

        run_ledger.record_gate(run_id, gate, outcome, score=score, tag=tag)
    except Exception as _exc:
        _zyg_log.warning('run ledger gate record failed, gate unrecorded: %s', _exc)


# ── model loaders (lazy, cached) ──────────────────────────────────────────────
def _load_gdino(device, log_fn=None):
    key = ('gdino', device)
    if key in _CACHE:
        return _CACHE[key]
    log = log_fn or (lambda _m: None)
    import torch
    import groundingdino
    from groundingdino.util.slconfig import SLConfig
    from groundingdino.models import build_model

    cfg = GDINO_CONFIG or os.path.join(os.path.dirname(groundingdino.__file__), 'config', 'GroundingDINO_SwinT_OGC.py')
    args = SLConfig.fromfile(cfg)
    args.device = device
    t0 = time.time()
    model = build_model(args)
    # B614 justified: the GroundingDINO checkpoint is a locally installed file and carries
    # non-tensor config objects, so weights_only=True cannot load it.
    sd = torch.load(GDINO_WEIGHTS, map_location='cpu', weights_only=False)  # nosec B614
    sd = sd.get('model', sd)
    model.load_state_dict({k.replace('module.', ''): v for k, v in sd.items()}, strict=False)
    model.eval().to(device)
    log(f'[continuity_qc] GroundingDINO ready on {device} ({time.time() - t0:.1f}s)')
    _CACHE[key] = model
    return model


def _sam2_cfg_for(weights_path):
    base = os.path.basename(weights_path).lower()
    for needle, yml in (
        ('base_plus', 'sam2.1_hiera_b+.yaml'),
        ('b+', 'sam2.1_hiera_b+.yaml'),
        ('large', 'sam2.1_hiera_l.yaml'),
        ('small', 'sam2.1_hiera_s.yaml'),
        ('tiny', 'sam2.1_hiera_t.yaml'),
    ):
        if needle in base:
            name = yml if '2.1' in base else yml.replace('sam2.1', 'sam2')
            p = os.path.join(SAM2_NODE_DIR, 'sam2_configs', name)
            if os.path.exists(p):
                return p
    return os.path.join(SAM2_NODE_DIR, 'sam2_configs', 'sam2.1_hiera_b+.yaml')


def _load_sam2(device, log_fn=None):
    """The kijai node ships a vendored, hydra-free SAM2 (Apache-2.0). Its loader is
    self-contained except for one `from comfy.utils import load_torch_file`, so we
    import it as a synthetic package with a tiny comfy shim — no ComfyUI process,
    no second venv, no vendored copy to keep in sync."""
    key = ('sam2', device)
    if key in _CACHE:
        return _CACHE[key]
    log = log_fn or (lambda _m: None)
    import importlib
    import types
    import torch

    if 'comfy' not in sys.modules:
        from safetensors.torch import load_file as _sload

        comfy = types.ModuleType('comfy')
        comfy.__path__ = []
        cu = types.ModuleType('comfy.utils')

        def load_torch_file(path, safe_load=True, device=None):
            if str(path).endswith('.safetensors'):
                return _sload(path, device='cpu')
            # B614 justified: this shim stands in for comfy.utils.load_torch_file and must keep
            # its semantics for the locally installed SAM2 checkpoints.
            return torch.load(path, map_location='cpu', weights_only=False)  # nosec B614

        cu.load_torch_file = load_torch_file
        comfy.utils = cu
        sys.modules['comfy'] = comfy
        sys.modules['comfy.utils'] = cu
    if _SAM2_PKG not in sys.modules:
        pkg = types.ModuleType(_SAM2_PKG)
        pkg.__path__ = [SAM2_NODE_DIR]
        sys.modules[_SAM2_PKG] = pkg
    lm = importlib.import_module(_SAM2_PKG + '.load_model')
    t0 = time.time()
    model = lm.load_model(SAM2_WEIGHTS, _sam2_cfg_for(SAM2_WEIGHTS), 'video', torch.float32, device)
    log(f'[continuity_qc] SAM2.1 ready on {device} ({time.time() - t0:.1f}s)')
    _CACHE[key] = model
    return model


def _load_dino(device, log_fn=None):
    key = ('dinov2', device)
    if key in _CACHE:
        return _CACHE[key]
    log = log_fn or (lambda _m: None)
    from transformers import AutoImageProcessor, AutoModel

    t0 = time.time()
    proc = AutoImageProcessor.from_pretrained(DINOV2_MODEL_ID, use_fast=True, revision=_HF_REVISION)
    model = AutoModel.from_pretrained(DINOV2_MODEL_ID, revision=_HF_REVISION).eval().to(device)
    log(f'[continuity_qc] DINOv2 ({DINOV2_MODEL_ID}) ready on {device} ({time.time() - t0:.1f}s)')
    _CACHE[key] = (proc, model)
    return _CACHE[key]


def available(log_fn=None):
    """Cheap import/exists probe — no weights loaded. Use to decide whether the
    grounded suite can run at all before scheduling it."""
    import importlib.util as iu

    out = {}
    for mod in ('torch', 'cv2', 'groundingdino', 'transformers', 'safetensors'):
        try:
            out[mod] = bool(iu.find_spec(mod))
        except Exception:
            out[mod] = False
    out['gdino_weights'] = os.path.exists(GDINO_WEIGHTS)
    out['sam2_weights'] = os.path.exists(SAM2_WEIGHTS)
    out['sam2_node'] = os.path.isdir(os.path.join(SAM2_NODE_DIR, 'sam2'))
    out['ok'] = all(
        out.get(k)
        for k in ('torch', 'cv2', 'groundingdino', 'transformers', 'gdino_weights', 'sam2_weights', 'sam2_node')
    )
    (log_fn or (lambda _m: None))(f'[continuity_qc] available: {out}')
    return out


# ── frame sampling ────────────────────────────────────────────────────────────
def _sample_frames(clip_path, sample_fps):
    """Decode every Nth frame as RGB. Returns (indices, times, frames, fps, total)."""
    import cv2

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise IOError(f'cannot open {clip_path}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(fps / max(0.05, float(sample_fps)))))
    idxs, times, frames = [], [], []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % step == 0:
            frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            idxs.append(i)
            times.append(i / fps)
        i += 1
    cap.release()
    return idxs, times, frames, fps, (total or i)


def _frames_at_times(clip_path, times):
    """Decode specific timestamps (seconds) → [(t, frame_idx, rgb), ...]."""
    import cv2

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise IOError(f'cannot open {clip_path}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    got = []
    for t in times:
        fi = int(round(float(t) * fps))
        if total:
            fi = max(0, min(fi, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, fr = cap.read()
        if not ok:
            continue
        got.append((float(t), fi, cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)))
    cap.release()
    return got, fps


# ── GroundingDINO ─────────────────────────────────────────────────────────────
def _caption_and_spans(tokenizer, prompts):
    """Build the dot-separated caption and, per prompt, the token indices its
    phrase occupies. Scoring off the token span (instead of string-matching the
    decoded phrase) is what keeps 'lit candle in a holder' from being reported as
    the truncated 'lit candle'."""
    clean = [' '.join(str(p).lower().strip().rstrip('.').split()) for p in prompts]
    caption = ' . '.join(clean) + ' .'
    enc = tokenizer(caption, return_offsets_mapping=True)
    offs = enc['offset_mapping']
    spans, cursor = [], 0
    for phrase in clean:
        s = caption.find(phrase, cursor)
        if s < 0:
            s = caption.find(phrase)
        e = s + len(phrase)
        cursor = max(cursor, e)
        spans.append([i for i, (a, b) in enumerate(offs) if b > a and a >= s and b <= e])
    return caption, spans


def _nms(cands, iou_thr=0.6, keep=8):
    out = []
    for c in cands:
        if all(_iou(c['box'], k['box']) < iou_thr for k in out):
            out.append(c)
        if len(out) >= keep:
            break
    return out


def _detect(model, frame_rgb, prompts, device, score_min, topk=8, log_fn=None):
    """One GroundingDINO forward for ALL prompts. Returns per prompt:
    {'found', 'score', 'box': [x0,y0,x1,y1] normalized, 'candidates': [...]}.
    Detection is amortized — the caption is scored once and split by token span,
    and the top-k NMS'd candidates are kept so the caller can associate the box
    temporally (a phrase like 'open book on the table' legitimately matches both
    the page and the whole spread; without association we would be measuring the
    detector's ambiguity instead of the scene's continuity)."""
    import torch
    from PIL import Image
    import groundingdino.datasets.transforms as T

    tf = T.Compose(
        [T.RandomResize([800], max_size=1333), T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])]
    )
    img, _ = tf(Image.fromarray(frame_rgb), None)
    caption, spans = _caption_and_spans(model.tokenizer, prompts)
    with torch.no_grad():
        out = model(img[None].to(device), captions=[caption])
    logits = out['pred_logits'].sigmoid()[0].float().cpu()  # (nq, 256)
    boxes = out['pred_boxes'][0].float().cpu()  # (nq, 4) cxcywh
    res = []
    for idxs in spans:
        if not idxs:
            res.append({'found': False, 'score': 0.0, 'box': None, 'candidates': []})
            continue
        per_q = logits[:, idxs].max(dim=1).values
        order = torch.argsort(per_q, descending=True)[: max(topk * 4, 16)]
        cands = []
        for q in order.tolist():
            sc = float(per_q[q])
            if sc < 0.10:
                break
            cx, cy, w, h = [float(v) for v in boxes[q]]
            cands.append(
                {
                    'score': round(sc, 4),
                    'box': [
                        round(max(0.0, cx - w / 2), 4),
                        round(max(0.0, cy - h / 2), 4),
                        round(min(1.0, cx + w / 2), 4),
                        round(min(1.0, cy + h / 2), 4),
                    ],
                }
            )
        cands = _nms(cands, keep=topk)
        top = cands[0] if cands else {'score': 0.0, 'box': None}
        res.append({'found': top['score'] >= score_min, 'score': top['score'], 'box': top['box'], 'candidates': cands})
    return res


def _select_box(det, prev_box, score_min, assoc_iou_min=0.30):
    """Pick which grounded candidate to hand SAM2 for this window.

    Window 0 (or after a total loss of the object) takes the highest-scoring box.
    Later windows prefer the candidate that best overlaps the PREVIOUS window's box,
    provided it still clears a score floor — i.e. track-by-detect association, so a
    nested-phrase flip (page vs spread) does not masquerade as a continuity break.
    Association only chooses the SEED box; every drift metric downstream is measured
    from the propagated SAM2 mask, so a prop that genuinely shrinks still fails."""
    cands = det.get('candidates') or []
    if not cands:
        return None, 'none'
    if prev_box is None:
        return cands[0], 'top-score'
    # Association re-ranks only among CONFIDENT detections — never promote a weak
    # box just because it overlaps (that would let a shrinking prop keep its old
    # footprint and hide the very defect this gate exists to catch).
    pool = [c for c in cands if c['score'] >= float(score_min)]
    if not pool:
        return cands[0], 'top-score'
    best = max(pool, key=lambda c: (_iou(c['box'], prev_box), c['score']))
    if _iou(best['box'], prev_box) >= assoc_iou_min:
        return best, ('associated' if best is not cands[0] else 'top-score')
    return cands[0], 'reacquired'


def _iou(a, b):
    if not a or not b:
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ub = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    den = ua + ub - inter
    return float(inter / den) if den > 0 else 0.0


def _containment(inner, outer):
    """Fraction of `inner`'s area that falls inside `outer` (asymmetric on purpose:
    a small prop box inside a big actor box should score ~1.0, not a low IoU)."""
    if not inner or not outer:
        return 0.0
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    ia = max(1e-9, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return float(inter / ia)


# ── SAM2 ──────────────────────────────────────────────────────────────────────
def _sam2_batch(frames_rgb, image_size, device):
    """Resize + ImageNet-normalize to the tensor layout the vendored predictor's
    init_state() expects (it does NO normalization of its own)."""
    import cv2
    import numpy as np
    import torch

    mean = torch.tensor([0.485, 0.456, 0.406])[:, None, None]
    std = torch.tensor([0.229, 0.224, 0.225])[:, None, None]
    out = []
    for f in frames_rgb:
        r = cv2.resize(f, (image_size, image_size), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        t = torch.from_numpy(r).permute(2, 0, 1)
        out.append((t - mean) / std)
    return torch.stack(out).to(device)


def _track_window(sam2, frames_rgb, boxes_px, device):
    """Propagate one box per object across a window's sampled frames.
    boxes_px: {obj_key: [x0,y0,x1,y1] pixels}. Returns {obj_key: [mask,...]}."""
    import numpy as np
    import torch

    H, W = frames_rgb[0].shape[:2]
    imgs = _sam2_batch(frames_rgb, sam2.image_size, device)
    state = sam2.init_state(imgs, H, W, device=device)
    keys = list(boxes_px.keys())
    for oid, k in enumerate(keys):
        sam2.add_new_points_or_box(
            inference_state=state, frame_idx=0, obj_id=oid, box=np.asarray(boxes_px[k], dtype=np.float32)
        )
    masks = {k: [None] * len(frames_rgb) for k in keys}
    with torch.inference_mode():
        for fi, out_ids, logits in sam2.propagate_in_video(state):
            for j, oid in enumerate(out_ids):
                if 0 <= fi < len(frames_rgb) and 0 <= oid < len(keys):
                    masks[keys[oid]][fi] = (logits[j, 0] > 0).cpu().numpy()
    try:
        sam2.reset_state(state)
    except Exception as _exc:
        _zyg_log.debug('sam2 state reset skipped: %s', _exc)
    return masks


# ── DINOv2 ────────────────────────────────────────────────────────────────────
def _embed(dino, images, device, batch=8):
    """L2-normalized DINOv2 pooled embeddings for a list of HxWx3 uint8 arrays."""
    import numpy as np
    import torch

    proc, model = dino
    vecs = []
    for i in range(0, len(images), batch):
        chunk = images[i : i + batch]
        with torch.no_grad():
            inp = proc(images=chunk, return_tensors='pt').to(device)
            out = model(**inp)
        v = out.pooler_output.float().cpu().numpy()
        v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
        vecs.append(v)
    return np.concatenate(vecs, axis=0) if vecs else np.zeros((0, 384), dtype='float32')


def _mask_bbox(mask, pad=0.15):
    import numpy as np

    ys, xs = np.where(mask)
    if ys.size == 0:
        return None
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    h, w = y1 - y0 + 1, x1 - x0 + 1
    py, px = int(h * pad), int(w * pad)
    H, W = mask.shape
    return [max(0, x0 - px), max(0, y0 - py), min(W, x1 + 1 + px), min(H, y1 + 1 + py)]


def _crops(frame_rgb, mask):
    """(plain bbox crop, masked crop with the background neutralised to grey).
    The plain crop is the appearance signal; the masked crop isolates the object
    silhouette+skin and is reported alongside as corroboration."""
    import numpy as np

    bb = _mask_bbox(mask)
    if bb is None:
        return None, None
    x0, y0, x1, y1 = bb
    if (x1 - x0) < 8 or (y1 - y0) < 8:
        return None, None
    crop = frame_rgb[y0:y1, x0:x1]
    m = mask[y0:y1, x0:x1]
    masked = crop.copy()
    masked[~m] = 128
    return np.ascontiguousarray(crop), np.ascontiguousarray(masked)
