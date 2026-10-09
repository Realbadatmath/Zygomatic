#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
medusa_body_mask.py — build the BODY-TEMPLATE training dataset (2026-08-08).

WHAT THIS IS FOR. A Medusa training character has one of two modes:

  identity — the trained character IS the person in the photographs. The face is
             kept and binds to the trigger token. Nothing here runs.
  body     — only the BUILD, proportions and posture should be learned, so a
             DIFFERENT identity can be locked on later. That is what this module
             prepares.

HOW THE FACE IS SUPPRESSED — AND WHY NOT BY EDITING PIXELS.
The obvious approach is to blur / pixelate / fill the face in the training
images. It was prototyped and REJECTED on evidence: every style leaves a
consistent artifact in the same place across all ~60 photographs of a character,
and a LoRA trained on that learns "this body has a smudged head" and reproduces
the smudge at inference. Pixelation was worst, but blur and flat-fill both leave
a learnable signature.

Instead this uses SimpleTuner's MASKED LOSS. The training pixels are never
altered — they are HARDLINKED from the identity dataset, byte-identical. What we
ship alongside is a parallel greyscale mask image per photo, and SimpleTuner
multiplies the per-pixel loss by it:

    simpletuner/helpers/models/common.py  ->  loss = loss * mask_image
    DREAMBOOTH.md                         ->  "The dark portions of the mask will
                                               cause the loss calculations to
                                               ignore these parts."

BLACK (0) = ignore, WHITE (255) = learn. The face is therefore never learned AND
never corrupted: the VAE still sees a real head, so head/shoulder proportion,
neck, hairline and skin-tone context all stay intact, while the gradient
contribution of the face region is zero.

FAIL-CLOSED, EVERYWHERE. A face that is present but not masked is silently
trained in — the exact failure this module exists to prevent, and one that only
surfaces hours later as a LoRA that fights the identity lock. So anything we
cannot prove is safe is QUARANTINED (excluded from the body dataset) rather than
admitted:
  * a mask whose ellipse does not sit on the head -> quarantine
  * a photo with no detectable face that is NOT a verified back view -> quarantine
  * a face still detectable after masking, by an INDEPENDENT detector -> quarantine
  * a mask covering more than 15% of the frame -> excluded (it is a portrait, not
    a body reference, and heavy masking also dilutes the gradient)

Verification deliberately uses a DIFFERENT detector family from the one that
placed the mask: asking MediaPipe whether it can still see the face it just told
us to cover is circular. identity_qc_service shells out to the ComfyUI venv
(SCRFD / antelopev2) for that second opinion.

COST. The independent verifier is a subprocess that loads the antelopev2 pack,
so it is called ONCE PER CHARACTER (batched), never per photograph. Measured
2026-08-09 over 20 photographs: 2.76 s/image one-at-a-time versus 1.27 s/image
batched — 221 minutes against 101 for an 80x60 library, in startup alone. The
work is therefore structured in PHASES rather than as a single per-image loop.

The verifier runs on GPU by default (0.06 s/image vs 1.31 on CPU, measured
2026-08-09), which only pays off because of the batching above. It yields to CPU
whenever ComfyUI is mid-sample or free VRAM is short (see gpu_ok_now) — taking
VRAM from an uninterruptible render costs far more than it saves. CPU is always
a correct fallback, just slower. ZYG_MEDUSA_MASK_GPU=0 forces it. The MediaPipe passes
stay on CPU regardless: those models are 3.6 MB and 9.0 MB, so transfer and
launch overhead would eat the gain.

If the ComfyUI venv is unavailable, body prepare REFUSES for that character
(retryable) rather than degrading to a single detector.

ISOLATION: same contract as bp_medusa_training.py. Never import
contact_sheet_pipeline, char_state_service, character_bible_service or
character_lora_family.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
from typing import Callable

from zyg_workflows import medusa_sheet_service as _sheet
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Mask geometry. Padding is generous because the face-mesh hull stops at the
# skin: it excludes the hairline, the ear at three-quarter yaw, and the jaw
# shadow, all of which carry identity.
_PAD_X = float(os.environ.get('ZYG_MEDUSA_MASK_PAD_X', '0.28'))
_PAD_UP = float(os.environ.get('ZYG_MEDUSA_MASK_PAD_UP', '0.40'))
_PAD_DOWN = float(os.environ.get('ZYG_MEDUSA_MASK_PAD_DOWN', '0.18'))

# SimpleTuner area-downsamples the mask to latent resolution (8px cells at
# 1024), so feather finer than ~3 cells is invisible to the loss. 8px is enough
# to avoid a hard edge without wasting effort on geometry that gets averaged away.
_FEATHER_PX = int(os.environ.get('ZYG_MEDUSA_MASK_FEATHER_PX', '8'))

_MAX_FACES = int(os.environ.get('ZYG_MEDUSA_MASK_MAX_FACES', '5'))
_DETECT_CONF = float(os.environ.get('ZYG_MEDUSA_MASK_CONF', '0.5'))

# Above this masked fraction the photo is a portrait, not a body reference.
_MAX_MASKED_FRACTION = float(os.environ.get('ZYG_MEDUSA_MASK_MAX_FRACTION', '0.15'))
# SCRFD detection score at or above which we treat a face as "still visible".
_VERIFY_DET_SCORE = float(os.environ.get('ZYG_MEDUSA_MASK_VERIFY_SCORE', '0.40'))
_VERIFY_ROUNDS = int(os.environ.get('ZYG_MEDUSA_MASK_VERIFY_ROUNDS', '3'))

BODY_DIRNAME = 'training_body'
MASK_DIRNAME = 'training_body_mask'

_IMAGE_RE = re.compile(r'^img_[0-9a-f]{8}\.png$')
_tls = threading.local()


# ══════════════════════════════════════════════════════════════════════════
# Detection — a SECOND landmarker, kept away from the angle classifier
# ══════════════════════════════════════════════════════════════════════════
def _mask_detector():
    """Multi-face landmarker used ONLY for mask geometry.

    Deliberately separate from medusa_sheet_service._get_detectors(): that one
    is num_faces=1 at confidence 0.25 and its output drives yaw/pitch/framing
    and therefore captions and coverage. Nothing measured here is ever written
    back into those — a mask-geometry change must not be able to move an angle.
    """
    got = getattr(_tls, 'mask_det', None)
    if got is not None:
        return got
    os.environ.setdefault('GLOG_minloglevel', '3')
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision

    det = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_sheet._FACE_TASK),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=_MAX_FACES,
            min_face_detection_confidence=_DETECT_CONF,
            min_face_presence_confidence=_DETECT_CONF,
            output_facial_transformation_matrixes=True,
        )
    )
    _tls.mask_det = det
    return det


def _detect_faces(pil_img) -> list[dict]:
    """Pixel-space hull bbox + roll for every face found."""
    import mediapipe as mp
    import numpy as np

    w, h = pil_img.size
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(pil_img, dtype='uint8'))
    res = _mask_detector().detect(mp_img)
    out: list[dict] = []
    mats = list(res.facial_transformation_matrixes or [])
    for i, lm in enumerate(res.face_landmarks or []):
        xs = [p.x * w for p in lm]
        ys = [p.y * h for p in lm]
        roll = 0.0
        if i < len(mats):
            try:
                _y, _p, roll = _sheet._euler_from_matrix(mats[i])
            except Exception:
                roll = 0.0
        out.append({'x0': min(xs), 'y0': min(ys), 'x1': max(xs), 'y1': max(ys), 'roll': float(roll)})
    return out


# ══════════════════════════════════════════════════════════════════════════
# Mask construction
# ══════════════════════════════════════════════════════════════════════════
def _padded_box(face: dict, w: int, h: int) -> tuple[float, float, float, float]:
    fw = face['x1'] - face['x0']
    fh = face['y1'] - face['y0']
    return (
        max(0.0, face['x0'] - _PAD_X * fw),
        max(0.0, face['y0'] - _PAD_UP * fh),
        min(float(w), face['x1'] + _PAD_X * fw),
        min(float(h), face['y1'] + _PAD_DOWN * fh),
    )


def build_mask(pil_img, faces: list[dict]):
    """White canvas with a black, roll-rotated ellipse over each face."""
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np

    w, h = pil_img.size
    mask = Image.new('L', (w, h), 255)
    for f in faces:
        bx0, by0, bx1, by1 = _padded_box(f, w, h)
        bw, bh = max(1.0, bx1 - bx0), max(1.0, by1 - by0)
        # Draw the ellipse upright on its own layer, rotate by roll, paste back.
        layer = Image.new('L', (int(bw) + 4, int(bh) + 4), 255)
        ImageDraw.Draw(layer).ellipse([2, 2, int(bw) + 2, int(bh) + 2], fill=0)
        if abs(f.get('roll') or 0.0) > 1.0:
            layer = layer.rotate(-f['roll'], resample=Image.BICUBIC, expand=True, fillcolor=255)
        px, py = int(bx0 + bw / 2 - layer.width / 2), int(by0 + bh / 2 - layer.height / 2)
        region = Image.new('L', (w, h), 255)
        region.paste(layer, (px, py))
        mask = Image.fromarray(np.minimum(np.asarray(mask), np.asarray(region)))
    if _FEATHER_PX > 0 and faces:
        blurred = mask.filter(ImageFilter.GaussianBlur(_FEATHER_PX))
        # min() keeps the ellipse core a hard 0 — feather only softens outward.
        mask = Image.fromarray(np.minimum(np.asarray(blurred), np.asarray(mask)))
    return mask


def masked_fraction(mask) -> float:
    import numpy as np

    a = np.asarray(mask)
    return float((a < 128).sum()) / float(a.size or 1)


def _ellipse_centres(faces: list[dict], w: int, h: int) -> list[tuple[float, float]]:
    out = []
    for f in faces:
        bx0, by0, bx1, by1 = _padded_box(f, w, h)
        out.append(((bx0 + bx1) / 2.0, (by0 + by1) / 2.0))
    return out


def placement_ok(centres, meas: dict, w: int, h: int) -> tuple[bool, str]:
    """Does every ellipse actually sit on a head?

    Guards against the mask landing on a hand, a background object, or a second
    person's shoulder — cases where the photo would train with the real face
    fully visible and an irrelevant patch ignored.
    """
    head = meas.get('head_points') or []
    if not head:
        return False, 'no_pose_for_placement_check'
    span = meas.get('shoulder_span')
    # Fall back to a frame-relative tolerance when shoulders are degenerate.
    tol_px = (float(span) * w * 0.6) if span else (0.25 * max(w, h))
    tol_px = max(tol_px, 0.08 * max(w, h))
    for cx, cy in centres:
        near = any(math.hypot(cx - px, cy - py) <= tol_px for px, py in head)
        if not near:
            return False, 'mask_off_head'
    return True, ''


# ══════════════════════════════════════════════════════════════════════════
# Independent verification (different detector family — see module docstring)
# ══════════════════════════════════════════════════════════════════════════
def verifier_available() -> tuple[bool, str]:
    try:
        from zyg_workflows import identity_qc_service as _idqc

        return _idqc.available()
    except Exception as exc:
        return False, f'identity_qc_service unimportable ({exc.__class__.__name__})'


def gpu_ok_now() -> bool:
    """Is it safe to ask for the GPU right now?

    ON by default because the win is large and the fallback is safe: measured
    2026-08-09, SCRFD verification runs at 0.06 s/image on GPU against 1.31 on
    CPU — 20.5x, or 5 minutes instead of 105 for an 80x60 library, with 40/40
    agreement on face detection.

    It still yields whenever ComfyUI is mid-sample or free VRAM is short:
    squeezing VRAM out from under an uninterruptible render costs far more than
    this saves. Any uncertainty returns False and the run proceeds on CPU —
    slower, never wrong. Set ZYG_MEDUSA_MASK_GPU=0 to force CPU.
    """
    if os.environ.get('ZYG_MEDUSA_MASK_GPU', '1') != '1':
        return False
    try:
        from zyg_workflows import comfy_offload

        if comfy_offload.comfy_is_sampling():
            return False
        free = comfy_offload.gpu_free_gb()
        need = float(os.environ.get('ZYG_MEDUSA_MASK_GPU_MIN_FREE_GB', '4'))
        if free is not None and free < need:
            return False
    except Exception:
        # Cannot establish that the GPU is free -> do not take it.
        return False
    return True


def _verify_batch(paths: list[str], log_fn=None, use_gpu: bool | None = None) -> dict:
    """One subprocess for MANY images.

    This is called per CHARACTER, never per photograph. Each call spawns a
    Python subprocess that loads the antelopev2 pack, so calling it per image
    costs 2.76 s/image against 1.27 s/image batched (measured 2026-08-09 over 20
    photographs) — 221 minutes versus 101 for an 80x60 library, purely in
    startup. Batching is also what makes the GPU path worth taking: you do not
    want to load the model onto the card thousands of times either.
    """
    from zyg_workflows import identity_qc_service as _idqc

    if use_gpu is None:
        use_gpu = gpu_ok_now()
    return _idqc.embed_images(paths, log_fn=log_fn, use_gpu=use_gpu)


def _still_visible(entry: dict) -> bool:
    if not entry:
        return False
    return bool(entry.get('face_detected')) and float(entry.get('det_score') or 0.0) >= _VERIFY_DET_SCORE


# ══════════════════════════════════════════════════════════════════════════
# Captions
# ══════════════════════════════════════════════════════════════════════════
def body_caption(meas: dict, trigger: str, promptables: str, suffix: str = '') -> str:
    """Body-mode caption.

    Caption policy is INVERTED relative to identity mode. The house rule is
    "what you caption stays promptable; what you omit welds itself to the
    trigger" — so for a reusable body the operator's hair/skin/wardrobe
    description MUST be captioned, otherwise this person's haircut ships with
    every body generated from the template.
    """
    return _sheet.caption_for(meas, trigger, suffix=suffix, mode='body', promptables=promptables)


def _write_caption(path: str, text: str, log_fn=None) -> None:
    """Write a caption, refusing to follow a hardlink.

    training_body/*.png are hardlinks of training/*.png. If a .txt were ever
    hardlinked too, writing the body caption would truncate and rewrite the very
    same inode as the identity caption — silently corrupting the identity
    dataset from the body path, and vice versa on the next sheet rebuild.
    """
    if os.path.exists(path):
        try:
            if os.stat(path).st_nlink > 1:
                if log_fn:
                    log_fn(
                        f'[bodymask] WARNING: {path} was hardlinked — replacing '
                        f'with a fresh file so the identity caption is not clobbered'
                    )
                os.remove(path)
        except OSError as _exc:
            _zyg_log.warning('hardlink check on %s failed, the caption may be written through the link: %s', path, _exc)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


# ══════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════
def prepare_body_dataset(
    char_id: str,
    char_dir: str,
    *,
    trigger: str,
    body_promptables: str,
    suffix: str = '',
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Rebuild training_body/ + training_body_mask/ from the identity dataset.

    Structured in PHASES so the expensive independent verifier is invoked once
    per character rather than once per photograph — see _verify_batch for the
    measured cost of getting that wrong.
    """

    def log(msg):
        if log_fn:
            try:
                log_fn(msg)
            except Exception as _exc:
                _zyg_log.debug('log callback raised, message dropped: %s', _exc)

    t0 = time.time()
    train_dir = os.path.join(char_dir, 'training')
    body_dir = os.path.join(char_dir, BODY_DIRNAME)
    mask_dir = os.path.join(char_dir, MASK_DIRNAME)

    if not os.path.isdir(train_dir):
        return {'ok': False, 'error': 'character has no training folder'}

    sheet = _sheet.load_sheet(char_dir)
    if not sheet:
        return {'ok': False, 'error': 'build the contact sheet first — body preparation needs its angle measurements'}
    if not (body_promptables or '').strip():
        return {
            'ok': False,
            'error': 'body templates need a hair / skin / wardrobe description so those stay promptable',
        }

    ok, why = verifier_available()
    if not ok:
        return {'ok': False, 'retryable': True, 'error': f'independent face verifier unavailable ({why})'}

    by_file = {m.get('file'): m for m in (sheet.get('images') or [])}

    for d in (body_dir, mask_dir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    from PIL import Image

    names = sorted(n for n in os.listdir(train_dir) if _IMAGE_RE.match(n))
    quarantined: list[dict] = []
    off_head = 0
    use_gpu = gpu_ok_now()
    log(f'[bodymask] {char_id}: verifying on {"GPU" if use_gpu else "CPU"}')

    def qtn(name, reason):
        quarantined.append({'file': name, 'reason': reason})

    tmpdir = tempfile.mkdtemp(prefix=f'medusa_bodyverify_{char_id}_')
    try:
        # ── Phase 1 — pure CPU analysis. No subprocesses at all. ──────────
        state: dict[str, dict] = {}
        need_orig: list[str] = []  # no MediaPipe face -> ask the stronger detector
        pending: list[str] = []  # has a candidate mask -> needs verification
        ready: list[str] = []  # provably faceless -> admit with an all-white mask

        for name in names:
            src = os.path.join(train_dir, name)
            meas = by_file.get(name) or {}
            try:
                img = Image.open(src).convert('RGB')
            except Exception as exc:
                qtn(name, f'decode failed: {exc}')
                continue
            if (meas.get('framing_slot') or '') == 'close_up':
                qtn(name, 'close_up_excluded')
                continue

            st = {
                'img': img,
                'meas': meas,
                'w': img.size[0],
                'h': img.size[1],
                'faces': _detect_faces(img),
                'mask': None,
                'frac': 0.0,
            }
            state[name] = st

            if not st['faces']:
                need_orig.append(name)
                continue
            if not _apply_mask(st, name, qtn):
                if st.get('off_head'):
                    off_head += 1
                del state[name]
                continue
            pending.append(name)

        # ── Phase 2 — ONE batched call over every photo MediaPipe missed. ──
        # MediaPipe is weakest exactly where body templates are strongest: a
        # small face in a full-body frame. Ask the stronger detector before
        # concluding there is no face, otherwise most legitimate full-body
        # photographs are thrown away as "unverified_faceless".
        if need_orig:
            probes = {}
            for name in need_orig:
                pth = os.path.join(tmpdir, f'orig_{name}')
                state[name]['img'].save(pth, 'PNG')
                probes[pth] = name
            try:
                res = _verify_batch(list(probes), log_fn=None, use_gpu=use_gpu)
            except Exception as exc:
                for name in need_orig:
                    qtn(name, f'verify failed: {exc}')
                    state.pop(name, None)
                res = {}
                probes = {}
            for pth, name in probes.items():
                st = state.get(name)
                if st is None:
                    continue
                entry = res.get(pth) or {}
                if _still_visible(entry):
                    bbox = entry.get('bbox') or []
                    if len(bbox) != 4:
                        qtn(name, 'unverified_faceless')
                        state.pop(name, None)
                        continue
                    st['faces'] = [
                        {
                            'x0': float(bbox[0]),
                            'y0': float(bbox[1]),
                            'x1': float(bbox[2]),
                            'y1': float(bbox[3]),
                            'roll': 0.0,
                        }
                    ]
                    if not _apply_mask(st, name, qtn):
                        if st.get('off_head'):
                            off_head += 1
                        state.pop(name, None)
                        continue
                    pending.append(name)
                elif (st['meas'].get('yaw_slot') or '') in ('back', 'back_three_quarter'):
                    # Neither detector sees a face AND the angle classifier
                    # independently says we are behind the head — that is proof.
                    st['mask'] = Image.new('L', (st['w'], st['h']), 255)
                    st['frac'] = 0.0
                    ready.append(name)
                else:
                    # Not provably a back view. A face we cannot locate is a
                    # face we cannot mask.
                    qtn(name, 'unverified_faceless')
                    state.pop(name, None)

        # ── Phase 3 — batched verification rounds. One call per ROUND, not ──
        # per photo. The set shrinks each round, so this is at most
        # _VERIFY_ROUNDS subprocesses for the whole character.
        for round_i in range(_VERIFY_ROUNDS):
            if not pending:
                break
            probes = {}
            for name in pending:
                st = state[name]
                pth = os.path.join(tmpdir, f'chk{round_i}_{name}')
                _flatten(st['img'], st['mask']).save(pth, 'PNG')
                probes[pth] = name
            try:
                res = _verify_batch(list(probes), log_fn=None, use_gpu=use_gpu)
            except Exception as exc:
                for name in pending:
                    qtn(name, f'verify failed: {exc}')
                    state.pop(name, None)
                pending = []
                break

            still: list[str] = []
            for pth, name in probes.items():
                st = state[name]
                entry = res.get(pth) or {}
                if not _still_visible(entry):
                    ready.append(name)
                    continue
                bbox = entry.get('bbox') or []
                if len(bbox) != 4:
                    qtn(name, 'face_still_detectable')
                    state.pop(name, None)
                    continue
                st['faces'].append(
                    {
                        'x0': float(bbox[0]),
                        'y0': float(bbox[1]),
                        'x1': float(bbox[2]),
                        'y1': float(bbox[3]),
                        'roll': 0.0,
                    }
                )
                if not _apply_mask(st, name, qtn):
                    if st.get('off_head'):
                        off_head += 1
                    state.pop(name, None)
                    continue
                still.append(name)
            pending = still

        # Anything the verifier could still see after every round is unsafe.
        for name in pending:
            qtn(name, 'face_still_detectable')
            state.pop(name, None)

        # ── Phase 4 — admit: hardlink PIXELS, write FRESH captions. ────────
        admitted: list[str] = []
        fractions: list[float] = []
        for name in sorted(ready):
            st = state.get(name)
            if st is None:
                continue
            src = os.path.join(train_dir, name)
            dst = os.path.join(body_dir, name)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
            st['mask'].convert('RGB').save(os.path.join(mask_dir, name), 'PNG')
            _write_caption(
                os.path.join(body_dir, name[:-4] + '.txt'),
                body_caption(st['meas'], trigger, body_promptables, suffix),
                log_fn=log_fn,
            )
            admitted.append(name)
            fractions.append(st['frac'])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    pages: list[str] = []
    try:
        pages = build_mask_montage(char_dir, admitted, log_fn=log_fn)
    except Exception as exc:
        log(f'[bodymask] mask check sheet failed ({exc.__class__.__name__}: {exc})')

    report = {
        'pages': pages,
        'prepared_at': time.time(),
        'duration_s': round(time.time() - t0, 1),
        'total': len(names),
        'admitted': len(admitted),
        'quarantined': quarantined,
        'quarantined_count': len(quarantined),
        'masks_placed_off_head': off_head,
        'mean_masked_fraction': round(sum(fractions) / len(fractions), 4) if fractions else 0.0,
        'max_masked_fraction': round(max(fractions), 4) if fractions else 0.0,
        'body_promptables': body_promptables,
        'trigger': trigger,
        'verified_on': 'gpu' if use_gpu else 'cpu',
    }

    try:
        full = _sheet.load_sheet(char_dir) or {}
        full['body_mode'] = report
        pth = _sheet.sheet_json_path(char_dir)
        tmp = f'{pth}.tmp.{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(full, fh, indent=2)
        os.replace(tmp, pth)
        summ = _sheet.load_summary(char_dir) or {}
        summ['body_mode'] = report
        pth2 = _sheet.summary_path(char_dir)
        tmp2 = f'{pth2}.tmp.{os.getpid()}'
        with open(tmp2, 'w', encoding='utf-8') as fh:
            json.dump(summ, fh, indent=2)
        os.replace(tmp2, pth2)
    except OSError as exc:
        log(f'[bodymask] could not persist report: {exc}')

    log(
        f'[bodymask] {char_id}: {len(admitted)}/{len(names)} admitted, '
        f'{len(quarantined)} quarantined, mean mask '
        f'{report["mean_masked_fraction"]:.3f}, {report["duration_s"]}s'
    )
    return {'ok': True, 'report': report}


def _apply_mask(st: dict, name: str, qtn) -> bool:
    """Placement check + mask build + area gate. False means quarantined."""
    centres = _ellipse_centres(st['faces'], st['w'], st['h'])
    ok_place, why = placement_ok(centres, st['meas'], st['w'], st['h'])
    if not ok_place:
        st['off_head'] = why == 'mask_off_head'
        qtn(name, why)
        return False
    mask = build_mask(st['img'], st['faces'])
    frac = masked_fraction(mask)
    if frac > _MAX_MASKED_FRACTION:
        qtn(name, f'mask_too_large ({frac:.2f} of frame)')
        return False
    st['mask'] = mask
    st['frac'] = frac
    return True


MASK_PAGE_PREFIX = 'medusa_bodymask_'
_MASK_PAGE_RE = re.compile(r'^medusa_bodymask_[0-9]{2,4}\.png$')


def build_mask_montage(
    char_dir: str, admitted: list[str], cols: int = 6, rows: int = 4, cell_px: int = 256, log_fn=None
) -> list[str]:
    """Render what will actually be ignored, as flat-grey-filled preview cells."""
    from PIL import Image, ImageDraw, ImageFont

    out_dir = _sheet.sheet_dir(char_dir)
    os.makedirs(out_dir, exist_ok=True)

    # Clear this run's previous pages (own prefix only — never the angle sheet).
    try:
        for old in os.listdir(out_dir):
            if _MASK_PAGE_RE.match(old):
                try:
                    os.remove(os.path.join(out_dir, old))
                except OSError as _exc:
                    _zyg_log.debug('stale mask page %s removal skipped: %s', old, _exc)
    except OSError as _exc:
        _zyg_log.debug('mask page sweep of %s skipped: %s', out_dir, _exc)

    if not admitted:
        return []
    body_dir = os.path.join(char_dir, BODY_DIRNAME)
    mask_dir = os.path.join(char_dir, MASK_DIRNAME)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    except Exception:
        font = ImageFont.load_default()

    per_page = max(1, cols * rows)
    pages: list[str] = []
    label_px = 22
    for start in range(0, len(admitted), per_page):
        chunk = admitted[start : start + per_page]
        n_rows = (len(chunk) + cols - 1) // cols
        cell_h = cell_px + label_px
        canvas = Image.new('RGB', (cols * cell_px, n_rows * cell_h), (18, 18, 20))
        draw = ImageDraw.Draw(canvas)
        for i, name in enumerate(chunk):
            cx = (i % cols) * cell_px
            cy = (i // cols) * cell_h
            try:
                img = Image.open(os.path.join(body_dir, name)).convert('RGB')
                msk = Image.open(os.path.join(mask_dir, name)).convert('L')
                prev = _flatten(img, msk)
                frac = masked_fraction(msk)
                prev.thumbnail((cell_px, cell_px), Image.LANCZOS)
                canvas.paste(prev, (cx + (cell_px - prev.width) // 2, cy + (cell_px - prev.height) // 2))
                colour = (
                    (150, 220, 150)
                    if frac <= 0.10
                    else ((220, 200, 130) if frac <= _MAX_MASKED_FRACTION else (230, 130, 130))
                )
                draw.text((cx + 4, cy + cell_px + 3), f'{frac * 100:.1f}% ignored', fill=colour, font=font)
            except Exception:
                draw.rectangle([cx, cy, cx + cell_px - 2, cy + cell_px - 2], outline=(90, 40, 40))
        p = os.path.join(out_dir, f'{MASK_PAGE_PREFIX}{len(pages) + 1:02d}.png')
        canvas.save(p, 'PNG')
        pages.append(os.path.basename(p))
    if log_fn:
        log_fn(f'[bodymask] mask check sheet: {len(pages)} page(s)')
    return pages


def _flatten(img, mask):
    """The photo with masked regions filled flat grey — the verification frame.

    This is NEVER written into the training set; it exists only so the
    independent detector is asked "can you still find a face where we said there
    is none?" without being handed the original pixels.
    """
    from PIL import Image

    grey = Image.new('RGB', img.size, (128, 128, 128))
    return Image.composite(img, grey, mask)


def body_dataset_dir(char_dir: str) -> str:
    return os.path.join(char_dir, BODY_DIRNAME)


def body_mask_dir(char_dir: str) -> str:
    return os.path.join(char_dir, MASK_DIRNAME)


def is_stale(char_dir: str) -> bool:
    """Have the source photographs changed since the body dataset was built?"""
    sheet = _sheet.load_summary(char_dir) or {}
    prepared = ((sheet.get('body_mode') or {}).get('prepared_at')) or 0
    if not prepared:
        return True
    train_dir = os.path.join(char_dir, 'training')
    try:
        for n in os.listdir(train_dir):
            if os.path.getmtime(os.path.join(train_dir, n)) > prepared:
                return True
    except OSError:
        return True
    return False
