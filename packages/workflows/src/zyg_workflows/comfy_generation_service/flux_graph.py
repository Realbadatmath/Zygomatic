# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FLUX graph surgery, dual-prompt splitting, face/hand detailer stack probes (original lines 544-723)."""

from __future__ import annotations

import os
import shutil
from typing import Callable
from zyg_workflows.comfy_generation_service.constants import _COMFY_ROOT, _comfy, _log_default


def _flux_rewire_without_lora(workflow: dict) -> None:
    """When no character LoRA is staged, bypass optional LoraLoader node 13.

    2026-07-24: generic over any graph — every input referencing node 13 is
    rewired to the loader outputs (model → 10, clip → 11) before deletion, so
    graphs whose consumers are not the character_locked node ids (e.g.
    flux_img2img's KSampler 31) don't dangle."""
    if '13' not in workflow:
        return
    _fallback = {0: ['10', 0], 1: ['11', 0]}  # LoraLoader out 0 = model, 1 = clip
    for nid, node in workflow.items():
        if nid == '13':
            continue
        inputs = node.get('inputs', {})
        for key, val in list(inputs.items()):
            if isinstance(val, list) and len(val) == 2 and val[0] == '13':
                inputs[key] = list(_fallback.get(val[1], ['10', 0]))
    del workflow['13']


def _trim_prompt_at_clause(text: str, max_len: int) -> str:
    """Cap a prompt at *max_len* chars, cutting at the last comma boundary so a
    hard cap never truncates mid-word/mid-phrase (the 2026-07-09 audit found
    the contact-sheet anchor positive cut at 'controlled studio key with moder',
    silently dropping its whole quality suffix)."""
    t = (text or '').strip()
    if len(t) <= max_len:
        return t
    cut = t[:max_len]
    return cut.rsplit(',', 1)[0].strip().rstrip(',') or cut


def _split_flux_dual_prompt(prompt: str, *, max_clip_l: int = 320) -> tuple[str, str]:
    """Split prompt for Comfy ``CLIPTextEncodeFlux`` (clip_l + t5xxl), matching diffusers clip/prompt_2."""
    _t5_max = int(os.environ.get('ZYG_FLUX_PROMPT_MAX_CHARS', '2000'))
    t5 = _trim_prompt_at_clause(prompt, _t5_max)
    if len(t5) <= max_clip_l:
        return t5, t5
    clip = t5[:max_clip_l].rsplit(' ', 1)[0]
    return (clip or t5[:max_clip_l]), t5


def _workflow_uses_flux_clip_encode(workflow: dict) -> bool:
    return workflow.get('20', {}).get('class_type') == 'CLIPTextEncodeFlux'


def _patch_flux_sampler(
    workflow: dict,
    overrides: dict,
    *,
    seed: int,
    steps: int,
    cfg: float,
    is_schnell: bool,
    cfg_start_frac: float | None = None,
) -> None:
    if '31' not in workflow:
        return
    if workflow['31'].get('class_type') == 'SamplerCustomAdvanced':
        # FLUX.2 klein splits what KSampler bundles: the seed lives on
        # RandomNoise (32), the step count on Flux2Scheduler (33) and the
        # guidance on CFGGuider (34). Writing {'seed','steps','cfg'} onto node
        # 31 the way the KSampler branch does would be accepted silently by
        # Comfy and change nothing — every render would come back at the
        # graph's baked-in seed and step count. Route to the real owners.
        if '32' in workflow:
            overrides['32'] = {'noise_seed': seed}
        if '33' in workflow:
            _sched = dict(workflow['33'].get('inputs') or {})
            _sched['steps'] = steps
            overrides['33'] = {k: _sched[k] for k in ('steps', 'width', 'height') if k in _sched}
        if '34' in workflow:
            overrides['34'] = {'cfg': float(cfg)}
        return
    if workflow['31'].get('class_type') == 'XlabsSampler':
        # timestep_to_start_cfg gates when true CFG (and therefore the NEGATIVE
        # prompt) switches on. Historically it was set to `steps` (final step),
        # making the negative 100% inert — that let the 2026-07-12 contact-sheet
        # runs style-collapse to anime. Engaging CFG early is A/B-validated ONLY
        # for the contact-sheet anchor, so it is opt-in per call: callers pass
        # cfg_start_frac (contact sheet passes ZYG_FLUX_CFG_START_FRAC, 0.18);
        # every other flux caller (video/story/documentary hero stills) keeps
        # the legacy inert behavior it was tuned under. schnell stays inert
        # always (distilled CFG-1.0 model). True CFG also ~doubles per-step cost
        # after the start point — another reason not to force it app-wide.
        if is_schnell or cfg_start_frac is None:
            _cfg_start = steps
        else:
            _cfg_start = max(1, int(steps * float(cfg_start_frac)))
        overrides['31'] = {
            'noise_seed': seed,
            'steps': steps,
            'timestep_to_start_cfg': _cfg_start,
            'true_gs': 1.0 if is_schnell else float(cfg),
            'image_to_image_strength': 0.0,
            'denoise_strength': 1.0,
        }
    else:
        overrides['31'] = {
            'seed': seed,
            'steps': steps,
            'cfg': 1.0 if is_schnell else cfg,
        }


def has_instantid(model_family: str | None = None) -> bool:
    """True when ComfyUI can run an InstantID-style identity lock workflow."""
    if _comfy is None:
        return False
    if not _comfy.has_node('ApplyInstantID'):
        return False
    if not _comfy.has_node('InstantIDModelLoader'):
        return False
    return _comfy.resolve_instantid_model_file() is not None


def has_face_detailer() -> bool:
    """True if the ComfyUI server has Impact-Pack's FaceDetailer."""
    return _comfy is not None and _comfy.has_node('FaceDetailer')


def _sam_model_path() -> str:
    return os.path.join(_COMFY_ROOT, 'models', 'sams', 'sam_vit_b_01ec64.pth')


def _face_yolo_path() -> str:
    return os.path.join(_COMFY_ROOT, 'models', 'ultralytics', 'bbox', 'face_yolov8m.pt')


def _hand_yolo_path() -> str:
    return os.path.join(_COMFY_ROOT, 'models', 'ultralytics', 'bbox', 'hand_yolov8s.pt')


_HAND_YOLO_URL = 'https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8s.pt'


def ensure_hand_yolo_weights(log_fn: Callable[[str], None] | None = None) -> bool:
    """Download ADetailer hand_yolov8s.pt if missing."""
    log = log_fn or _log_default
    path = _hand_yolo_path()
    if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log(f'ComfyGen: downloading hand detector → {path}')
    try:
        from zyg_workflows.net import safe_urlopen

        # safe_urlopen instead of urlretrieve: urlretrieve accepts file:/ and custom schemes.
        with safe_urlopen(_HAND_YOLO_URL, timeout=300) as rsp, open(path, 'wb') as fh:
            shutil.copyfileobj(rsp, fh)
    except Exception as exc:
        log(f'ComfyGen: hand_yolov8s download failed — {exc}')
        return False
    ok = os.path.isfile(path) and os.path.getsize(path) > 1_000_000
    if ok:
        log('ComfyGen: hand_yolov8s.pt ready')
    return ok


def sam_face_stack_ready() -> bool:
    """Impact-Pack FaceDetailer + SAM + face YOLO on disk + Comfy nodes registered."""
    if not has_face_detailer():
        return False
    if _comfy is None or not _comfy.has_node('SAMLoader'):
        return False
    if _comfy is None or not _comfy.has_node('UltralyticsDetectorProvider'):
        return False
    return (
        os.path.isfile(_sam_model_path())
        and os.path.getsize(_sam_model_path()) > 10_000_000
        and os.path.isfile(_face_yolo_path())
    )


def hand_detailer_stack_ready() -> bool:
    """Hand second pass: hand YOLO + FaceDetailer node (reused for hands)."""
    if not sam_face_stack_ready():
        return False
    return os.path.isfile(_hand_yolo_path()) and os.path.getsize(_hand_yolo_path()) > 1_000_000
