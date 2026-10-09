# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_bank.py — longitudinal face/subject identity bank (2026-07-30).

Why this exists
---------------
Two verified failure modes had no detector:

  1. Character identity drifts ACROSS context windows inside a single render while the
     whole-image CLIP gate (0.80) happily passes — CLIP scores "a bearded man in a
     brown coat at a table", not "THIS man".
  2. Slow cross-episode ratchet drift after a retrain / restyle. The per-render gate is
     memoryless, so a character can walk away from its canon a few percent per episode
     and never trip anything.

This module gives every character a PERSISTENT embedding bank keyed by
(char_id, style_profile, backend), so a new render is scored against the character's own
historical distribution — cosine vs the bank centroid AND a z-score vs the bank spread.

License posture (STRICT commercial bar)
---------------------------------------
  * facenet-pytorch — MIT (code + converted weights). Installed with --no-deps so it
    cannot downgrade the venv torch (its metadata pins torch<2.3).
  * DINOv2 ViT-S/14 (`facebook/dinov2-small`) — Apache-2.0 (DINOv2 was relicensed from
    CC-BY-NC in 2024). Do NOT swap in any *-NC checkpoint.
  * This module exists to retire the NON-COMMERCIAL insightface dependency in the
    identity QC path. Nothing here imports insightface.
  * CAVEAT, flagged not hidden: the facenet `vggface2` weights were trained on the
    VGGFace2 dataset, whose *dataset* terms are research-oriented even though the
    facenet-pytorch code+weights ship MIT. If legal wants zero dataset-provenance risk,
    set ZYG_IDENTITY_BACKEND=dinov2 — the DINOv2 path is fully Apache-2.0 (LVD-142M) and
    is measurably discriminative on our stylized cast (see MEASURED, below).

MEASURED on the real Second Ledger cast (2026-07-30, CPU, scene20_v7/pasted17.mp4)
---------------------------------------------------------------------------------
Cast: Cornelis 0015c8a3f2e3 (box 0.10,0.02,0.45,0.50) and Abel c3345deb5bde
(box 0.60,0.02,0.96,0.56), windows sampled at 2/6/9/13/16 s.

  MTCNN detection rate on arcane-stylized faces: 14/14 = 100% (both canon portraits,
  both canon face crops, all ten per-window head crops), det_prob 0.87-1.00.
  => Face-ID nets do NOT fail on this style. `facenet` is the PRIMARY backend.

  facenet (bank = canon portrait + canon face crop):
      genuine  cos 0.468 - 0.586  (mean 0.534)
      impostor cos -0.029 - 0.250 (mean 0.087)     margin  +0.218
      canon-Cornelis vs canon-Abel = 0.292
  dinov2 region (same banks, whole head box):
      genuine  cos 0.414 - 0.591  (mean 0.488)
      impostor cos  0.273 - 0.367 (mean 0.325)     margin  +0.048
      canon-Cornelis vs canon-Abel = 0.567  <-- same style + same framing dominates

  => DINOv2-on-a-head-box is largely a STYLE/COMPOSITION descriptor, not an identity
     descriptor: two different people in the same arcane style score 0.57. Keep it as
     the no-face FALLBACK and treat a dinov2 fail as "flag for review", never as a hard
     identity verdict. Floors: facenet 0.35 (0.12 under the worst genuine, 0.10 over the
     best impostor); dinov2 0.50 (calibrated against a render-domain bank).

BENCH CLIP — the per-frame clip instrument (2026-09-02, scripts/identity_clip_bench.py)
--------------------------------------------------------------------------------------
The old check_clip sampled five fixed times through a STATIC box, had its spread
alarm calibrated on ONE render, and had zero callers. It was replaced by a
per-frame instrument and BENCHED BEFORE BEING TRUSTED. 12 arms, 419 scored frames,
facenet backend, banks of 3 (canon portrait + canon face crop + anchor crop):

  arm                                          n   cos_min  p10    mean   spread
  ceiling/Abel      (canon still x341 @24fps) 15   0.9327  0.933  0.9355  0.012
  ceiling/Cornelis                            15   0.9465  0.947  0.9471  0.003
  true/Abel         shores_v27_leanfix        34   0.7287  0.745  0.7666  0.092
  true/Cornelis     cornelis_day1             26   0.4980  0.500  0.5240  0.074
  true/Cornelis-left   20s_pipe_smoke (L col) 55   0.4775  0.523  0.5879  0.190
  true/Abel-right      20s_pipe_smoke (R col) 50   0.3943  0.503  0.5667  0.299
  shuffle/Abel      same frames, random order 34   0.7387  0.743  0.7656  0.073
  shuffle/Cornelis                            25   0.5072  0.512  0.5319  0.079
  impostor/Abel-bank on Cornelis clip         26   0.0276  0.030  0.0740  0.163
  impostor/Cornelis-bank on Abel clip         34   0.2917  0.315  0.3404  0.085
  impostor/Cornelis-bank on Abel column       50  -0.0581  0.019  0.1458  0.350
  impostor/Abel-bank on Cornelis column       55   0.1065  0.128  0.1747  0.173

  * IMPOSTORS ARE SEPARATED. Worst case is Cornelis' bank on Abel's clip: arm mean
    0.340 against a worst genuine arm mean of 0.524 — a gap of 0.184 at the arm
    level, 0.185 at p10. The two SAME-CLIP impostor arms (the other character's
    column of the very same two-hander: identical style, grade, framing and render)
    score 0.146 and 0.175, i.e. the hardest impostor available is not the closest
    one. The metric is reading the face, not the render.
  * BUT THE PER-FRAME GAP IS RAZOR THIN: worst genuine frame 0.3943, best impostor
    frame 0.3763 — an overlap-free window only 0.018 wide. So no single frame may
    decide a clip; the verdict is `pass_frac` over found frames (CLIP_PASS_FRAC).
  * THE TWO CHARACTERS ARE NOT EQUALLY SAFE. Abel's true clip sits at 0.73-0.82,
    Cornelis' at 0.50-0.57 — both pass, but Cornelis has ~0.08 of headroom over
    the 0.42 floor and Abel has ~0.31. Whatever trips first will be Cornelis, and
    it will not necessarily mean his identity moved: it may mean his bank of three
    canon images is a worse centroid than Abel's. Enrol more before tightening.
  * SHUFFLE says the summary statistics carry NO temporal information: the shuffled
    frame SET scores 0.7656 vs 0.7666 (Abel) and 0.5319 vs 0.5240 (Cornelis). This
    is the expected result for an order-blind metric and it is the reason `spread`
    is informational only — it is dispersion, never continuity.
  * CEILING is IN-BANK (the canon portrait is one of the three enrolled images), so
    0.93-0.95 is the top of the achievable scale plus the cost of an h264 round
    trip, not an independent genuine sample.
  * LEDGER: true/Abel found 34, not_found 20, not_detectable 5 over a 59 s scene.
    The 20 not_found frames are harbour shots with nobody in them — the old
    instrument had no state for those and its five fixed times only ever landed in
    the one shot where Abel is on screen.
  * LEGACY comparison on the same clip (5 times, static box (0.45,0,1,0.6)):
    mean 0.7736 over 5 windows, verdict "ok". Not wrong — blind. It sampled 5
    moments of a 1411-frame clip and all 5 fell inside a single shot.

Usage
-----
    from zyg_workflows import identity_bank as ib
    ib.enroll('0015c8a3f2e3', 'arcane', [canon_portrait, canon_face_crop, anchor_crop])
    r = ib.check('0015c8a3f2e3', 'arcane', frame_png, box_frac=(0.10, 0.02, 0.45, 0.50))
    # -> {'ok': True, 'cosine': 0.71, 'z': 0.3, 'n_bank': 3, 'backend': 'facenet', ...}
    ib.drift_report('0015c8a3f2e3')     # time-series for the nightly dashboard

Every public call is fail-safe: on any internal error it returns
{'ok': None, 'error': '...'} (ok=None means UNKNOWN, never a silent pass and never an
exception into the generation path).
"""

import os
import time

from zyg_workflows import paths, pgdb
import logging as _zyg_logging
from zyg_workflows.bin import exe

# ruff: noqa: F401  (the original module-level import block, re-imported by the sibling modules)

# Hugging Face revision for every from_pretrained/download in this module. 'main' is the
# floating default these call sites used implicitly; $ZYG_HF_REVISION pins a commit instead.
_HF_REVISION = os.environ.get('ZYG_HF_REVISION', '').strip() or 'main'

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.identity_bank')


# ── paths / config ───────────────────────────────────────────────────────────
_HERE = str(paths.PKG_DIR)
_RUNTIME = str(paths.DATA_DIR / 'runtime')

# Backend chosen when the caller does not pin one and the bank is empty.
DEFAULT_BACKEND = os.environ.get('ZYG_IDENTITY_BACKEND', 'facenet')
DEVICE = os.environ.get('ZYG_IDENTITY_DEVICE', 'cpu')  # CPU by default: never fight the renderer for VRAM

# Calibrated cosine floors (see MEASURED above and the calibration report).
# facenet : InceptionResnetV1(vggface2) 512-d, L2-normalised, MTCNN-aligned 160px.
# dinov2  : facebook/dinov2-small CLS token 384-d, L2-normalised, 224px box resize.
_FLOORS = {
    'facenet': float(os.environ.get('ZYG_IDENTITY_FLOOR_FACENET', '0.35')),
    'dinov2': float(os.environ.get('ZYG_IDENTITY_FLOOR_DINOV2', '0.50')),
}
Z_FLOOR = float(os.environ.get('ZYG_IDENTITY_Z_FLOOR', '-2.5'))
# The z-gate needs a real distribution. Measured: a 3-image bank (two 1024px canon
# stills + one 480p anchor crop) has loo_std 0.11-0.13 and pushes GENUINE windows to
# z=-3.1 — a false alarm caused by bank heterogeneity, not by drift. So z is always
# REPORTED but only ENFORCED once the bank is big enough / tight enough to mean anything.
Z_MIN_BANK = int(os.environ.get('ZYG_IDENTITY_Z_MIN_BANK', '5'))
Z_MIN_STD = float(os.environ.get('ZYG_IDENTITY_Z_MIN_STD', '0.02'))
# Cross-context-window identity wander inside ONE render (advisory).
SPREAD_ALARM = float(os.environ.get('ZYG_IDENTITY_SPREAD_ALARM', '0.20'))
# Cross-RENDER ratchet: per-render mean falling this far between the oldest and newest
# quartile of renders. Needs at least this many distinct renders to mean anything.
RATCHET_DELTA = float(os.environ.get('ZYG_IDENTITY_RATCHET_DELTA', '-0.03'))
RATCHET_MIN_RENDERS = int(os.environ.get('ZYG_IDENTITY_RATCHET_MIN_RENDERS', '4'))

_FACENET_DIM = 512
_DINOV2_DIM = 384
_IMNET_MEAN = (0.485, 0.456, 0.406)
_IMNET_STD = (0.229, 0.224, 0.225)

# lazy model singletons
_MTCNN = None
_RESNET = None
_DINO = None


def _log(log_fn, msg):
    try:
        if log_fn:
            log_fn(msg)
    except Exception as _exc:
        _zyg_log.debug('log callback failed: %s', _exc)


def _run_id():
    return os.environ.get('ZYG_RUN_ID') or 'adhoc'


def _ledger_gate(run_id, gate, outcome, score=None, tag=''):
    """Best-effort hand-off to the cross-run gate ledger (built by the ledger agent)."""
    try:
        from zyg_workflows import run_ledger

        run_ledger.record_gate(run_id or _run_id(), gate, outcome, score=score, tag=tag)
    except Exception as _exc:
        _zyg_log.warning('gate ledger record failed, the gate is unrecorded: %s', _exc)


def _ledger_fallback(component, expected, actual, detail='', run_id=None):
    try:
        from zyg_workflows import run_ledger

        run_ledger.record_fallback(component, expected, actual, detail=detail, run_id=run_id or _run_id())
    except Exception as _exc:
        _zyg_log.warning('fallback ledger record failed, the downgrade is unrecorded: %s', _exc)


# ── embedding helpers ────────────────────────────────────────────────────────
def _np():
    import numpy as np

    return np


def _l2(vec):
    np = _np()
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-8 else v


def _blob(vec):
    return _l2(vec).astype(_np().float32).tobytes()


def _unblob(buf, dim):
    np = _np()
    buf = bytes(buf)  # psycopg may hand back a memoryview
    v = np.frombuffer(buf, dtype=np.float32)
    return v if v.size == dim else v[:dim]


def _open_crop(image_path, box_frac=None):
    """PIL RGB image, optionally cropped to a fractional box (fx0, fy0, fx1, fy1)."""
    from PIL import Image

    im = Image.open(image_path).convert('RGB')
    if box_frac:
        W, H = im.size
        fx0, fy0, fx1, fy1 = box_frac
        box = (max(0, int(W * fx0)), max(0, int(H * fy0)), min(W, int(W * fx1)), min(H, int(H * fy1)))
        if box[2] > box[0] and box[3] > box[1]:
            im = im.crop(box)
    return im


def _get_facenet(device=None):
    global _MTCNN, _RESNET
    if _MTCNN is None or _RESNET is None:
        from facenet_pytorch import MTCNN, InceptionResnetV1

        dev = device or DEVICE
        _MTCNN = MTCNN(image_size=160, margin=20, keep_all=True, select_largest=True, post_process=True, device=dev)
        _RESNET = InceptionResnetV1(pretrained='vggface2').eval().to(dev)
    return _MTCNN, _RESNET


def _get_dino(device=None):
    global _DINO
    if _DINO is None:
        from transformers import AutoModel

        dev = device or DEVICE
        _DINO = AutoModel.from_pretrained('facebook/dinov2-small', revision=_HF_REVISION).eval().to(dev)
    return _DINO


def embed_face(image_path, backend='facenet', box_frac=None, device=None, log_fn=None):
    """MTCNN-detect + InceptionResnetV1(vggface2) 512-d L2-normalised face embedding.

    Returns {'ok': True, 'embedding': [...], 'dim', 'backend', 'det_prob', 'box'}
    or      {'ok': False, 'error': 'no_face'|...}   (fail-safe, never raises).
    """
    if backend != 'facenet':
        return embed_region(image_path, box_frac=box_frac, backend=backend, device=device, log_fn=log_fn)
    try:
        import torch

        mt, net = _get_facenet(device)
        im = _open_crop(image_path, box_frac)
        boxes, probs = mt.detect(im)
        if boxes is None or len(boxes) == 0:
            return {'ok': False, 'error': 'no_face', 'backend': 'facenet'}
        # highest-confidence face
        idx = 0
        try:
            idx = int(max(range(len(probs)), key=lambda i: probs[i] if probs[i] else 0.0))
        except (TypeError, ValueError, IndexError) as _exc:
            _zyg_log.debug('face confidence ranking failed, using the first face: %s', _exc)
        faces = mt.extract(im, boxes, save_path=None)
        if faces is None:
            return {'ok': False, 'error': 'extract_failed', 'backend': 'facenet'}
        if faces.dim() == 3:
            faces = faces.unsqueeze(0)
        chip = faces[idx : idx + 1].to(device or DEVICE)
        with torch.no_grad():
            emb = net(chip).cpu().numpy()[0]
        return {
            'ok': True,
            'embedding': _l2(emb).tolist(),
            'dim': _FACENET_DIM,
            'backend': 'facenet',
            'det_prob': float(probs[idx]) if probs is not None and probs[idx] else None,
            'box': [float(x) for x in boxes[idx]],
        }
    except Exception as e:
        _log(log_fn, f'[identity_bank] embed_face failed: {type(e).__name__}: {e}')
        return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'backend': 'facenet'}


def embed_region(image_path, box_frac=None, backend='dinov2', device=None, log_fn=None):
    """DINOv2 ViT-S/14 CLS embedding of a whole region — the stylized-crop fallback for
    when MTCNN finds no face (heavy stylization, extreme pose, occluded/back of head).

    box_frac: (fx0, fy0, fx1, fy1) fractional crop, or None for the whole image.
    Returns {'ok': True, 'embedding', 'dim', 'backend'} or {'ok': False, 'error'}.
    """
    if backend == 'facenet':
        return embed_face(image_path, backend='facenet', box_frac=box_frac, device=device, log_fn=log_fn)
    try:
        import numpy as np
        import torch

        model = _get_dino(device)
        im = _open_crop(image_path, box_frac).resize((224, 224))
        arr = np.asarray(im, dtype=np.float32) / 255.0
        arr = (arr - np.asarray(_IMNET_MEAN, dtype=np.float32)) / np.asarray(_IMNET_STD, dtype=np.float32)
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device or DEVICE)
        with torch.no_grad():
            out = model(pixel_values=t)
        cls = out.last_hidden_state[:, 0].cpu().numpy()[0]
        return {'ok': True, 'embedding': _l2(cls).tolist(), 'dim': _DINOV2_DIM, 'backend': 'dinov2'}
    except Exception as e:
        _log(log_fn, f'[identity_bank] embed_region failed: {type(e).__name__}: {e}')
        return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'backend': 'dinov2'}


def embed_auto(image_path, box_frac=None, prefer=None, device=None, log_fn=None, run_id=None):
    """Preferred backend with a RECORDED fallback (never a silent degrade)."""
    prefer = prefer or DEFAULT_BACKEND
    r = (
        embed_face(image_path, backend=prefer, box_frac=box_frac, device=device, log_fn=log_fn)
        if prefer == 'facenet'
        else embed_region(image_path, box_frac=box_frac, backend=prefer, device=device, log_fn=log_fn)
    )
    if r.get('ok'):
        return r
    if prefer == 'facenet':
        _log(log_fn, f'[identity_bank] facenet miss ({r.get("error")}) -> dinov2 region')
        _ledger_fallback(
            'identity_bank.embed',
            'facenet',
            'dinov2',
            detail=f'{os.path.basename(str(image_path))}: {r.get("error")}',
            run_id=run_id,
        )
        alt = embed_region(image_path, box_frac=box_frac, backend='dinov2', device=device, log_fn=log_fn)
        alt['fallback_from'] = 'facenet'
        alt['fallback_reason'] = r.get('error')
        return alt
    return r
