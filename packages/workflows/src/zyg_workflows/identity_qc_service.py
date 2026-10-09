# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Identity QC — ArcFace face-embedding drift gate for the contact sheet pipeline.

Scores every tile against the identity anchor with antelopev2 (ArcFace) via a
subprocess in the ComfyUI venv, which already ships insightface + models.

Two layers of judgment (the Rhea Kim forensics showed why both are needed):
1. Identity: cosine similarity vs the anchor, with angle-aware thresholds —
   frontal strict, profile lenient, back views exempt (embeddings carry no
   back-of-head information; the LoRA flywheel covers those).
2. Content truth: a tile whose *content* is corrupt can still score above
   threshold (two half-people from a misaligned grid slice scored 0.44 and
   entered a training set). So tiles are also rejected for: more than one
   detected face (multi_face), a face centered on the tile edge (face_cut —
   slicing artifact), or content contradicting the label (mislabeled_angle:
   a frontal face on a "back of head" or profile label, caught via head yaw).

Verdicts: pass | fail | multi_face | face_cut | mislabeled_angle
        | no_face (expected face, none found) | no_face_expected.
FAIL_CLASS lists the verdicts that trigger regeneration / dataset exclusion.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import uuid
from typing import Any, Callable
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_identity_embed_worker.py')

_DEFAULT_WORKER_PYTHON = str(paths.ZYG_COMFY_ROOT / '.venv' / 'bin' / 'python')
_DEFAULT_INSIGHTFACE_ROOT = str(paths.ZYG_COMFY_ROOT / 'models' / 'insightface')
_DEFAULT_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

# Same-person ArcFace cosine: frontal-vs-frontal typically >0.5, frontal-vs-profile
# drops to 0.2-0.35 — a single global threshold would flag every clean profile.
# 2026-08-09 pack-aware thresholds. AuraFace cosines sit on a different scale
# than glintr100; the auraface defaults below were CALIBRATED by quantile-
# matching 630 same-person / 6.9K cross-person pairs from 11 library characters
# at each production operating point (data/runtime/auraface_calibration.json;
# method + caveats in the 2026-08-09 build-log artifact). Measured at matched
# sensitivity: frontal FAR on par with glintr100, oblique slightly worse,
# PROFILE markedly worse (0.61 vs 0.34).
#
# 2026-08-26 — AURAFACE IS NOW THE DEFAULT, on licence grounds, not on scores.
# The insightface pretrained packs state in their own distribution metadata that
# they are "available for non-commercial research purposes only", and this
# channel is monetised. A QC instrument is still a commercial USE of the tool
# even though no antelopev2 pixel reaches an episode — which is exactly how this
# case differs from SAM 3, whose licence GRANTS commercial use.
#
# The profile cost above is accepted, not solved. Read it precisely before
# trusting it: frontal is a slight IMPROVEMENT (FAR 0.329 vs 0.354), oblique is
# mildly worse, and the real loss is confined to profile — measured on the
# smallest sample in the set (82 same-person pairs), at an operating point where
# glintr100's own FAR was 0.338 and therefore never a strong gate either.
# The route to closing it is MediaPipe pose assist; geom/ already derives
# face_yaw from FaceLandmarker transformation matrices at production scale.
#
# NOT A CLEAN CHAIN YET: fal ships AuraFace as a drop-in antelopev2 replacement,
# so only glintr100.onnx (the recogniser) is actually theirs. The other four
# files in the pack are BYTE-IDENTICAL insightface weights — verified by md5.
# Of those, this worker loads scrfd_10g_bnkps (detection) and 1k3d68
# (landmark_3d_68 → yaw/roll), so ~160 MB of non-commercial weight remains in
# the chain until detection and pose move to MediaPipe.
_PACK = os.environ.get('ZYG_IDQC_PACK', 'auraface').strip() or 'auraface'
_CAL = {
    'auraface': {'frontal': '0.465', 'oblique': '0.317', 'profile': '0.206'},
}.get(_PACK, {'frontal': '0.42', 'oblique': '0.30', 'profile': '0.25'})
THRESH_FRONTAL = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_THRESH_FRONTAL', _CAL['frontal']))
THRESH_OBLIQUE = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_THRESH_OBLIQUE', _CAL['oblique']))
THRESH_PROFILE = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_THRESH_PROFILE', _CAL['profile']))
# Full-body cells: the face is small and distant, so cosine carries little
# signal — clean full-body cells measured 0.21-0.39 on the 2026-07-16 runs
# while the frontal threshold flagged them. Scored, but at a floor that only
# catches gross drift.
THRESH_FULLBODY = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_THRESH_FULLBODY', '0.18'))
MIN_DET_SCORE = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_MIN_DET', '0.40'))

# Content-truth knobs.
MAX_FACES = int(os.environ.get('ZYG_CONTACT_SHEET_IDQC_MAX_FACES', '1'))
EDGE_CENTER_PCT = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_EDGE_PCT', '0.08'))
YAW_CHECK = os.environ.get('ZYG_CONTACT_SHEET_IDQC_YAW', '1').strip().lower() not in (
    '0',
    'false',
    'no',
    'off',
)
# A face on a "back of head" label with |yaw| below this is frontal content.
BACK_LABEL_MIN_YAW = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_BACK_MIN_YAW', '45'))
# A face on a profile label with |yaw| below this is frontal content.
PROFILE_LABEL_MIN_YAW = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_PROFILE_MIN_YAW', '12'))
# A face on an oblique (3/4) label with |yaw| below this is frontal content —
# catches under-rotated chained regens delivered on 35° labels (2026-07-16).
OBLIQUE_LABEL_MIN_YAW = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_OBLIQUE_MIN_YAW', '12'))
# Head roll beyond this = sideways/inverted frame (2026-07-16 audit: an
# upside-down and a 90-degree-rotated portrait trained as-is — no studio
# angle in the sheet legitimately tilts the head anywhere near this far).
MAX_ROLL = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_MAX_ROLL', '55'))
# Full-body/dynamic-pose cells tilt the head as part of the pose (T-pose lunge
# cells measured roll 59-60 on usable images) and roll estimation is noisy on
# small profile faces — allow more before calling it a broken frame.
FULLBODY_MAX_ROLL = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_FULLBODY_MAX_ROLL', '70'))
# A frontal-labeled tile whose head yaw exceeds this is profile content on a
# frontal label (HarmoView-style pose verification, loosened for fuzzy text
# labels: clean frontal cells measure up to ~41° yaw on natural head turns,
# true profiles ~75-90°).
FRONTAL_MAX_YAW = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_FRONTAL_MAX_YAW', '60'))

FAIL_CLASS = ('fail', 'multi_face', 'face_cut', 'mislabeled_angle', 'bad_orientation')


def enabled() -> bool:
    return os.environ.get('ZYG_CONTACT_SHEET_IDQC', '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def _worker_python() -> str:
    return os.environ.get('ZYG_IDQC_PYTHON', _DEFAULT_WORKER_PYTHON).strip()


def _insightface_root() -> str:
    return os.environ.get('ZYG_IDQC_INSIGHTFACE_ROOT', _DEFAULT_INSIGHTFACE_ROOT).strip()


def available() -> tuple[bool, str]:
    py = _worker_python()
    if not os.path.isfile(py):
        return False, f'worker python not found: {py}'
    root = _insightface_root()
    # Check the pack we will actually RUN, not a hardcoded one. This asserted
    # antelopev2 even when ZYG_IDQC_PACK selected another pack, so after the
    # 2026-08-26 removal of the non-commercial antelopev2 weights it would have
    # reported identity QC unavailable while auraface sat right beside it.
    if not os.path.isdir(os.path.join(root, 'models', _PACK)):
        return False, f'{_PACK} model pack not found under {root}'
    if not os.path.isfile(_WORKER):
        return False, f'embed worker missing: {_WORKER}'
    return True, 'ok'


def embed_images(
    image_paths: list[str],
    *,
    log_fn: Callable[[str], None] | None = None,
    timeout_s: int = 900,
    use_gpu: bool = False,
) -> dict[str, dict]:
    """Batch-embed faces. Returns {path: {face_detected, faces_count, det_score,
    bbox, embedding|None, yaw|None, img_w, img_h}}."""
    ok, reason = available()
    if not ok:
        raise RuntimeError(f'identity QC unavailable: {reason}')
    paths = [p for p in image_paths if p and os.path.isfile(p)]
    if not paths:
        return {}
    tmpdir = tempfile.gettempdir()
    tag = uuid.uuid4().hex[:10]
    in_path = os.path.join(tmpdir, f'idqc_in_{tag}.json')
    out_path = os.path.join(tmpdir, f'idqc_out_{tag}.json')
    with open(in_path, 'w', encoding='utf-8') as fh:
        json.dump(paths, fh)
    cmd = [
        _worker_python(),
        _WORKER,
        '--images',
        in_path,
        '--root',
        _insightface_root(),
        '--out',
        out_path,
        # Resolved once at import (_PACK) so the worker, the thresholds in _CAL
        # and the available() preflight can never disagree about which pack is
        # in play — they read the same value. Default flipped to the Apache-2.0
        # fal/AuraFace-v1 embedder 2026-08-26; see the _PACK comment for the
        # licence reason and the measured cost.
        '--pack',
        _PACK,
    ]
    # use_gpu defaults False so every existing caller (contact_sheet_pipeline's
    # identity QC, which runs mid-render) keeps competing with nothing for VRAM.
    # Only bulk callers that have checked the GPU is idle should pass True.
    env = None
    if use_gpu:
        cmd.append('--gpu')
        # The ComfyUI venv's onnxruntime 1.22 is built against CUDA 12, but that
        # venv ships CUDA 13 (nvidia/cu13). Without this the CUDA provider fails
        # to load libcublasLt.so.12 and onnxruntime SILENTLY falls back to CPU —
        # measured 2026-08-09: identical timings to CPU, and the only way to see
        # it is the worker's stderr, which this function discards on success.
        # The CUDA-12 set lives in the crews venv; injecting it here affects only
        # this short-lived subprocess, never the ComfyUI server process.
        import glob as _glob

        cu12 = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.venv',
            'lib',
            'python3.12',
            'site-packages',
            'nvidia',
        )
        libs = sorted(_glob.glob(os.path.join(cu12, '*', 'lib')))
        if libs:
            env = dict(os.environ)
            env['LD_LIBRARY_PATH'] = ':'.join(libs + [env.get('LD_LIBRARY_PATH', '')]).rstrip(':')
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        if use_gpu and log_fn and 'CUDAExecutionProvider' not in (proc.stderr or ''):
            log_fn(
                'Identity QC: GPU requested but CUDA provider did not engage '
                '— results are still correct, just CPU-speed'
            )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or '')[-400:]
            raise RuntimeError(f'embed worker rc={proc.returncode}: {tail}')
        with open(out_path, encoding='utf-8') as fh:
            results = json.load(fh)
        if log_fn:
            n_face = sum(1 for v in results.values() if v.get('face_detected'))
            log_fn(f'Identity QC: embedded {len(results)} images ({n_face} faces detected)')
        return results
    finally:
        for p in (in_path, out_path):
            try:
                os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('embed worker temp cleanup skipped: %s', _exc)


def dedup_report(
    face_image: str,
    exclude_char_id: str = '',
    *,
    dataset_root: str = _DEFAULT_DATASET_ROOT,
    max_anchors: int = 20,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Warn-only cross-character similarity report (2026-07-18).

    Compares *face_image* against the newest existing character anchors.
    Used by flows without the contact-sheet dedup gate (Blender / photo
    generate-character). Returns {'max_sim': float|None, 'vs': char_id, 'compared': n}.
    """
    out: dict = {'max_sim': None, 'vs': '', 'compared': 0}
    ok, _why = available()
    if not ok or not os.path.isfile(face_image):
        return out
    others: list[tuple[str, str, float]] = []
    try:
        # _archived characters stay comparable — they hold FLUX's modal face.
        for root in (dataset_root, os.path.join(dataset_root, '_archived')):
            if not os.path.isdir(root):
                continue
            for cid in os.listdir(root):
                if cid == exclude_char_id or cid.startswith('_'):
                    continue
                p = os.path.join(root, cid, 'contact_sheet', 'contact_sheet_anchor_face.png')
                if os.path.isfile(p):
                    others.append((cid, p, os.path.getmtime(p)))
    except OSError:
        return out
    pairs = [t[:2] for t in sorted(others, key=lambda t: t[2], reverse=True)[:max_anchors]]
    if not pairs:
        return out
    emb = embed_images([face_image] + [p for _, p in pairs], log_fn=log_fn)
    probe = emb.get(face_image) or {}
    out['probe'] = {
        'face_detected': bool(probe.get('face_detected')),
        'bbox': probe.get('bbox'),
        'det_score': probe.get('det_score'),
    }
    me = probe.get('embedding')
    if not me:
        return out
    for cid, p in pairs:
        e = (emb.get(p) or {}).get('embedding')
        if not e:
            continue
        s = cosine(me, e)
        out['compared'] += 1
        if out['max_sim'] is None or s > out['max_sim']:
            out['max_sim'] = round(s, 3)
            out['vs'] = cid
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def intra_set_outliers(
    pairs: list[tuple[str, list[float]]],
    *,
    k: float = 2.5,
    abs_floor: float = None,  # None → pack default (glintr100 0.55 / auraface 0.524 calibrated)
    min_set: int = 6,
) -> dict:
    """Flag tiles whose ArcFace embedding sits far from the SET's OWN centroid
    (2026-07-20). Anchor-vs-tile scoring passes a tile that matches the anchor
    yet drifts from its siblings — the Ivy Rossi audit found tile 16 (neutral
    pose, but a narrower face, thinner upper lip and cat-eye look) that no
    anchor comparison could catch. We build the centroid of the comparable
    face-forward tiles and flag the ones the set itself disagrees with, using a
    robust median/MAD threshold so a tight, healthy set flags nothing.

    A tile is an outlier only if it is BOTH statistically low (below
    median - k·1.4826·MAD) AND absolutely low (cosine-to-centroid < abs_floor),
    so a uniformly consistent set never false-flags. Returns
    {'checked', 'outliers': [{path, sim, thr}], 'centroid_n', 'median'}.
    """
    if abs_floor is None:
        abs_floor = 0.524 if _PACK == 'auraface' else 0.55

    if len(pairs) < min_set:
        return {'checked': False, 'outliers': [], 'reason': f'set too small ({len(pairs)})'}

    def _l2(v: list[float]) -> list[float]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    normed = [(p, _l2(e)) for p, e in pairs if e]
    if len(normed) < min_set:
        return {'checked': False, 'outliers': [], 'reason': 'insufficient embeddings'}
    dim = len(normed[0][1])
    centroid = [0.0] * dim
    for _, e in normed:
        for i in range(dim):
            centroid[i] += e[i]
    centroid = _l2(centroid)
    sims = [(p, sum(a * b for a, b in zip(e, centroid))) for p, e in normed]
    vals = sorted(s for _, s in sims)
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    devs = sorted(abs(s - median) for s in vals)
    mad = devs[n // 2] if n % 2 else (devs[n // 2 - 1] + devs[n // 2]) / 2.0
    thr = median - k * 1.4826 * mad
    outliers = [{'path': p, 'sim': round(s, 4), 'thr': round(thr, 4)} for p, s in sims if s < thr and s < abs_floor]
    return {
        'checked': True,
        'outliers': outliers,
        'centroid_n': len(normed),
        'median': round(median, 4),
        'thr': round(thr, 4),
    }


_BACK_KEYWORDS = (
    'back of head',
    'from behind',
    'directly behind',
    'straight behind',
    'back view',
    'back three-quarter',
    'directly overhead',
    'top-down',
    'crown',
    'hair whorl',
    'hairline',
    'back of the head',
    'rear view',
)
_PROFILE_KEYWORDS = (
    'profile',
    '90 degrees',
    '120 degrees',
    '60 degrees',
)
_OBLIQUE_KEYWORDS = (
    '30 degrees',
    '35 degrees',
    '45 degrees',
)
# Pitch-only variation: the face IS visible (from above/below), so identity is
# scoreable at the lenient threshold — but head YAW stays near zero, so these
# labels must be exempt from the yaw-vs-label check (which would otherwise
# deterministically flag every correct under-chin/worm-eye cell as mislabeled).
_PITCH_KEYWORDS = (
    'under-chin',
    'below chin',
    'chin level',
    'worm eye',
    'jawline',
)


_FULLBODY_KEYWORDS = ('full body', 'full-body', 't-pose', 'a-pose')


def expected_visibility(angle_label: str) -> str:
    """'frontal' | 'oblique' | 'profile' | 'pitch' | 'back' | 'full_body' from the label.

    full_body (2026-07-16): distant/small faces where cosine and head-yaw carry
    little signal — scored at the lenient THRESH_FULLBODY, exempt from the
    yaw-vs-label checks (the BODY is angled, the head often faces the camera),
    and given the looser FULLBODY_MAX_ROLL. Back-labeled full-body cells stay
    'back' (checked first).
    """
    a = (angle_label or '').strip().lower()
    if any(k in a for k in _BACK_KEYWORDS):
        return 'back'
    if any(k in a for k in _FULLBODY_KEYWORDS):
        return 'full_body'
    if any(k in a for k in _PITCH_KEYWORDS):
        return 'pitch'
    if any(k in a for k in _PROFILE_KEYWORDS):
        return 'profile'
    if any(k in a for k in _OBLIQUE_KEYWORDS):
        return 'oblique'
    return 'frontal'


def threshold_for(visibility: str) -> float:
    if visibility == 'frontal':
        return THRESH_FRONTAL
    if visibility == 'oblique':
        return THRESH_OBLIQUE
    if visibility == 'full_body':
        return THRESH_FULLBODY
    return THRESH_PROFILE


def _face_edge_cut(entry: dict) -> bool:
    """Face center hugging a vertical tile edge = half a person from a bad slice."""
    bbox = entry.get('bbox')
    w = entry.get('img_w')
    if not bbox or not w:
        return False
    cx = (bbox[0] + bbox[2]) / 2.0
    margin = EDGE_CENTER_PCT * float(w)
    return cx <= margin or cx >= float(w) - margin


def assess_tile(visibility: str, entry: dict, score: float | None) -> str:
    """Full verdict: content-truth checks first, then identity thresholds.

    Content checks only act on CONFIDENT detections (det >= MIN_DET_SCORE) —
    spurious weak detections at the low worker det-thresh must not brand a
    clean back view as multi_face.
    """
    face = bool(entry.get('face_detected'))
    det = float(entry.get('det_score') or 0.0)
    yaw = entry.get('yaw')
    confident = face and det >= MIN_DET_SCORE

    if confident and MAX_FACES > 0:
        scores = entry.get('faces_scores')
        strong = (
            sum(1 for s in scores if float(s) >= MIN_DET_SCORE)
            if isinstance(scores, list) and scores
            else int(entry.get('faces_count') or 0)
        )
        if strong > MAX_FACES:
            return 'multi_face'
    if confident and _face_edge_cut(entry):
        return 'face_cut'
    roll = entry.get('roll')
    # Back/crown labels are exempt: in-plane face orientation is arbitrary when
    # the camera is behind/above, so roll carries no orientation signal there.
    # Full-body cells use the looser ceiling (dynamic poses tilt the head).
    _roll_max = FULLBODY_MAX_ROLL if visibility == 'full_body' else MAX_ROLL
    if confident and visibility != 'back' and roll is not None and abs(float(roll)) > _roll_max:
        return 'bad_orientation'
    if YAW_CHECK and confident and yaw is not None:
        # 'pitch' labels (under-chin, worm eye) keep near-zero yaw by design —
        # exempt from the yaw-vs-label check.
        if visibility == 'back' and abs(yaw) < BACK_LABEL_MIN_YAW:
            return 'mislabeled_angle'
        if visibility == 'profile' and abs(yaw) < PROFILE_LABEL_MIN_YAW:
            return 'mislabeled_angle'
        if visibility == 'oblique' and abs(yaw) < OBLIQUE_LABEL_MIN_YAW:
            return 'mislabeled_angle'
        if visibility == 'frontal' and abs(yaw) > FRONTAL_MAX_YAW:
            return 'mislabeled_angle'

    if visibility == 'back':
        return 'no_face_expected'
    if not face or det < MIN_DET_SCORE:
        return 'no_face'
    if score is None:
        return 'no_face'
    return 'pass' if score >= threshold_for(visibility) else 'fail'


def extract_anchor_face(
    src_path: str,
    dest_path: str,
    *,
    margin: float = 0.35,
    log_fn: Callable[[str], None] | None = None,
) -> str | None:
    """Crop the largest DETECTED face from src as the identity anchor.

    Replaces geometric cell-[0,0] cropping, which produced an anchor straddling
    two panels (1.5 faces) on the Rhea Kim run and degraded both IP-Adapter
    conditioning and every similarity score downstream.
    """
    ok, reason = available()
    if not ok:
        if log_fn:
            log_fn(f'Anchor extraction unavailable ({reason})')
        return None
    try:
        entry = (embed_images([src_path]) or {}).get(src_path) or {}
        bbox = entry.get('bbox')
        if not entry.get('face_detected') or not bbox:
            if log_fn:
                log_fn('Anchor extraction: no face detected in source')
            return None
        from PIL import Image

        img = Image.open(src_path).convert('RGB')
        w, h = img.size
        x0, y0, x1, y1 = bbox
        pad = margin * max(x1 - x0, y1 - y0)
        crop = img.crop(
            (
                max(0, int(x0 - pad)),
                max(0, int(y0 - pad * 1.4)),  # extra headroom for hair
                min(w, int(x1 + pad)),
                min(h, int(y1 + pad)),
            )
        )
        os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
        crop.save(dest_path, format='PNG')
        if log_fn:
            log_fn(
                f'Identity anchor — detected face crop {crop.size[0]}×{crop.size[1]} '
                f'(det {entry.get("det_score"):.2f}, yaw {entry.get("yaw")}) '
                f'→ {os.path.basename(dest_path)}',
            )
        return dest_path
    except Exception as exc:
        if log_fn:
            log_fn(f'Anchor extraction failed ({exc})')
        return None


def score_images_against_anchor(
    anchor_path: str,
    items: list[dict],
    *,
    profile_anchor_path: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Score items [{path, angle}] against the anchor face.

    ``profile_anchor_path`` (2026-07-18): a verified side-profile anchor.
    ArcFace scores profile tiles ~0.25 against a frontal crop — the lenient
    floors that requires made profiles the sloppiest third of the sheet. When
    a profile anchor is available, profile/oblique/back tiles score as the MAX
    of (vs frontal, vs profile), so genuine same-person profiles rank high and
    the floors actually discriminate.

    Returns {ok, anchor_path, results: {path: {score, verdict, visibility,
    face_detected, faces_count, yaw, det_score}}, summary}; ok=False + reason
    when the anchor itself has no detectable face (mock sheets, corrupt anchor).
    """
    _pa = profile_anchor_path if (profile_anchor_path and os.path.isfile(profile_anchor_path)) else None
    all_paths = [anchor_path] + ([_pa] if _pa else []) + [it['path'] for it in items]
    embeds = embed_images(all_paths, log_fn=log_fn)
    anchor = embeds.get(anchor_path) or {}
    if not anchor.get('face_detected') or not anchor.get('embedding'):
        return {
            'ok': False,
            'reason': 'anchor face not detected',
            'anchor_path': anchor_path,
            'results': {},
            'summary': {},
        }
    if int(anchor.get('faces_count') or 0) > 1 and log_fn:
        log_fn(
            f'Identity QC WARNING: anchor contains {anchor["faces_count"]} faces — '
            f'scoring against the largest; consider re-extracting the anchor',
        )
    a_emb = anchor['embedding']
    p_emb = None
    if _pa:
        _pa_e = embeds.get(_pa) or {}
        if _pa_e.get('face_detected') and _pa_e.get('embedding'):
            p_emb = _pa_e['embedding']
        elif log_fn:
            log_fn('Identity QC: profile anchor has no detectable face — frontal-only scoring')

    results: dict[str, dict] = {}
    scored: list[float] = []
    counts: dict[str, int] = {}
    for it in items:
        path = it['path']
        vis = expected_visibility(it.get('angle') or '')
        e = embeds.get(path) or {}
        score: float | None = None
        if e.get('face_detected') and e.get('embedding'):
            score = round(cosine(a_emb, e['embedding']), 4)
            if p_emb is not None and vis in ('profile', 'oblique', 'back'):
                score = round(max(score, cosine(p_emb, e['embedding'])), 4)
        v = assess_tile(vis, e, score)
        if score is not None and v in ('pass', 'fail'):
            scored.append(score)
        counts[v] = counts.get(v, 0) + 1
        results[path] = {
            'score': score,
            'verdict': v,
            'visibility': vis,
            'face_detected': bool(e.get('face_detected')),
            'faces_count': int(e.get('faces_count') or 0),
            'yaw': e.get('yaw'),
            'roll': e.get('roll'),
            'det_score': round(float(e.get('det_score') or 0.0), 3),
            'bbox': e.get('bbox'),
        }

    # Cross-tile (intra-set) outlier scan — FRONTAL passing tiles only (2026-07-20).
    # The centroid + MAD model assumes a single pose cluster: pooling oblique
    # (30-45 deg yaw) tiles with frontal ones pushes obliques systematically far
    # from a frontal-dominated centroid (false flags) and inflates the spread
    # enough to mask a real frontal drift outlier. Frontal is the tightest,
    # most-populous cluster (~8 of 48), well above min_set; if too few, the
    # detector safely returns checked=False.
    _os_pairs = [
        (it['path'], (embeds.get(it['path']) or {}).get('embedding'))
        for it in items
        if (results.get(it['path']) or {}).get('verdict') == 'pass'
        and (results.get(it['path']) or {}).get('visibility') == 'frontal'
        and (embeds.get(it['path']) or {}).get('embedding')
    ]
    try:
        _outlier_info = intra_set_outliers(_os_pairs)
    except Exception:
        _outlier_info = {'checked': False, 'outliers': []}

    summary = {
        'total': len(items),
        **counts,
        'mean_score': round(sum(scored) / len(scored), 4) if scored else None,
        'min_score': round(min(scored), 4) if scored else None,
        'threshold_frontal': THRESH_FRONTAL,
        'threshold_oblique': THRESH_OBLIQUE,
        'threshold_profile': THRESH_PROFILE,
        'intra_set_outliers': _outlier_info,
        'content_checks': {
            'max_faces': MAX_FACES,
            'edge_center_pct': EDGE_CENTER_PCT,
            'yaw_check': YAW_CHECK,
        },
        'backend': 'arcface_antelopev2',
    }
    if log_fn:
        fail_total = sum(counts.get(v, 0) for v in FAIL_CLASS)
        log_fn(
            f'Identity QC: {counts.get("pass", 0)} pass / {fail_total} fail-class '
            f'({", ".join(f"{k}:{v}" for k, v in counts.items() if k != "pass")}) '
            f'(mean {summary["mean_score"]}, min {summary["min_score"]})',
        )
    return {
        'ok': True,
        'anchor_path': anchor_path,
        'results': results,
        'summary': summary,
    }
