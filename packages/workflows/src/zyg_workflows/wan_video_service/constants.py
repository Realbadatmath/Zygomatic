# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  # this module carries the original top import block verbatim,
# re-exported by __init__.py so wan/blockout-style attribute access still resolves.

"""wan_video_service.py — Wan2.1-I2V-14B-480P image-to-video clip generation.

Generates short (~3.8 s) video clips by animating the FLUX-generated still
images produced by Stage 2.  Uses the I2V (image-to-video) variant so each
clip visually matches its source FLUX frame — correct lighting, composition,
and characters — rather than re-imagining the scene from text alone.

    Wan2.1-I2V-14B-480P      ~28 GB VRAM  (bfloat16)
    ─────────────────────────────────────
    Combined                  ~39 GB  →  fits in 48 GB (RTX 4090 / A6000)

Clips are written to:
    {out_dir}/wan_clips/wan_{idx:03d}.mp4

A manifest is saved to:
    {out_dir}/wan_clips/wan_manifest.json

The manifest maps each clip back to its source FLUX image path so Stage 6 can
substitute the live video in place of the static image in the slideshow.
"""

import gc
import json
import os
import shutil
import subprocess
import threading
import time
from zyg_workflows.bin import exe

try:
    from zyg_workflows import _comfy_client as _comfy
except ImportError:
    _comfy = None
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.wan_video_service')


# ── Constants ────────────────────────────────────────────────────────────────
_MODEL_ID = 'Wan-AI/Wan2.1-I2V-14B-480P-Diffusers'
_DEFAULT_N_CLIPS = 4  # generate one clip per scene (each anchored to a unique FLUX image)
_CLIP_FRAMES = 65  # 65 frames @ ~17 fps ≈ 3.8 s per sub-clip
_CLIP_FPS = 17  # WAN native generation framerate
_OUTPUT_FPS = 24  # final output framerate after interpolation
_N_CHAINED = 4  # sub-clips chained per scene: 4 × 3.8 s ≈ 15.3 s — covers scene_duration without looping
SEC_PER_SUBCLIP = _CLIP_FRAMES / _CLIP_FPS  # ≈3.82 s per WAN sub-clip
_SEC_PER_SUBCLIP = SEC_PER_SUBCLIP

# UI labels (3.5 / 7 / 11 / 15) map to 1–4 WAN sub-clips at SEC_PER_SUBCLIP each.
VIDEO_SHORT_PRESETS = (3.5, 7.0, 11.0, 15.0)


def n_chained_for_scene_duration(scene_duration: float) -> int:
    """WAN sub-clips needed to cover one scene (1–4). Short clips use fewer subs."""
    try:
        dur = float(scene_duration)
    except (TypeError, ValueError):
        dur = 15.0
    return max(1, min(_N_CHAINED, int(__import__('math').ceil(dur / _SEC_PER_SUBCLIP))))


def effective_wan_scene_duration_sec(scene_duration: float) -> float:
    """Natural stitched WAN length for one scene (n_subclips × SEC_PER_SUBCLIP)."""
    return n_chained_for_scene_duration(scene_duration) * SEC_PER_SUBCLIP


def final_trim_target_sec(
    requested_total_sec: float,
    scene_duration: float,
    n_scenes: int = 1,
) -> float:
    """Do not trim below WAN stitch length (e.g. keep ~3.8s when user picked 3.5)."""
    wan_total = effective_wan_scene_duration_sec(scene_duration) * max(1, int(n_scenes))
    return max(float(requested_total_sec), wan_total)


# ComfyUI I2V resolution + model — env-overridable so we can switch to the 720P checkpoint for a
# sharper render without touching the workflow json. Defaults preserve the original 480P behavior.
_WIDTH = int(os.environ.get('ZYG_WAN_WIDTH', '832'))
_HEIGHT = int(os.environ.get('ZYG_WAN_HEIGHT', '480'))
_WAN_COMFY_MODEL = os.environ.get('ZYG_WAN_MODEL', 'Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors')
# Attention backend for WanVideoModelLoader: 'sdpa' (safe default) or 'sageattn'
# (INT8 triton kernels — ~35-40%% faster end-to-end; needs sageattention in the
# ComfyUI venv, installed 2026-08-09). Instant rollback: unset ZYG_WAN_ATTENTION.
_WAN_ATTENTION = os.environ.get('ZYG_WAN_ATTENTION', 'sdpa').strip() or 'sdpa'
# ── Wan2.2 A14B dual-expert path (2026-08-09 upgrade, env-gated) ─────────────
# ZYG_WAN22=1 switches to the wan22_i2v graph (HIGH+LOW noise experts, MoE).
# ZYG_WAN_LIGHTNING=1 additionally injects the 4-step Lightning LoRA pair
# (steps→4, cfg→1.0, shift→5.0). Known failure mode: extreme motion — keep the
# flag off for hero shots. 2.1 char LoRAs only fit the LOW expert; full-quality
# identity needs a 2.2 retrain (musubi i2v-A14B recipe).
_WAN22 = os.environ.get('ZYG_WAN22', '').strip().lower() in ('1', 'true', 'yes', 'on')
_WAN_LIGHTNING = os.environ.get('ZYG_WAN_LIGHTNING', '').strip().lower() in ('1', 'true', 'yes', 'on')
_WAN22_BOUNDARY_FRACTION = 0.5  # HIGH expert handles the first half of the steps
_LIGHTNING_HIGH_LORA = 'wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors'
_LIGHTNING_LOW_LORA = 'wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors'
_INFER_STEPS = 20  # 20 steps: ~33% faster than 30, negligible quality loss for I2V
_GUIDANCE = 5.0

# Motion quality / anti-static constants
_MOTION_FREEZE_THRESH = 0.40  # > 40% frozen → near-static → trigger regeneration retry
_T2V_MODEL_ID = 'Wan-AI/Wan2.1-T2V-14B-Diffusers'

# Human-subject keywords used to build anatomy-aware negative prompts (Problem 3D)
_HUMAN_SUBJECT_KW = frozenset(
    [
        'warrior',
        'gladiator',
        'soldier',
        'man',
        'woman',
        'person',
        'figure',
        'face',
        'portrait',
        'fighter',
        'knight',
        'archer',
        'general',
        'emperor',
        'king',
        'queen',
        'hero',
        'character',
        'human',
        'people',
        'crowd',
        'centurion',
        'legionnaire',
        'viking',
        'spartan',
        'samurai',
        'barbarian',
        'guard',
        'warrior',
        'chieftain',
        'athlete',
        'dancer',
        'child',
    ]
)

# Emotion → visual motion cue injected into the Wan prompt
_MOTION_BY_EMOTION = {
    'shock': 'sudden dramatic camera push-in, frozen moment, stark contrast',
    'triumph': 'slow cinematic rise, triumphant upward tilt, golden light',
    'grief': 'slow dolly pullback, heavy atmosphere, muted tones',
    'anger': 'urgent handheld motion, tense close-up, harsh shadows',
    'awe': 'slow dramatic pan revealing vast scale, epic depth',
    'tension': 'slow creeping zoom, atmospheric haze, unsettled mood',
    'unease': 'subtle handheld sway, liminal space, cool palette',
    'mystery': 'slow fog drift, ambient motion, muted colours',
    'calm': 'gentle ambient camera drift, serene atmosphere',
    'neutral': 'steady gentle camera movement, documentary style',
}

# Scene-type keyword groups → additional motion language injected on top of emotion cue.
# Addresses WAN's tendency to produce near-static frames for scenes with no inherent action.
_SCENE_MOTION_HINTS: list[tuple[list[str], str]] = [
    # Landscapes / environments — inject atmospheric movement
    (
        [
            'landscape',
            'vista',
            'sweeping',
            'panorama',
            'horizon',
            'valley',
            'mountain',
            'coastline',
            'cliff',
            'shore',
            'plains',
            'desert',
            'forest',
            'field',
            'ruins',
        ],
        'clouds drifting slowly across sky, camera panning across the scene, wind moving through grass and foliage',
    ),
    # Sunset / sky / atmospheric
    (
        ['sunset', 'sunrise', 'sky', 'dawn', 'dusk', 'golden hour', 'dramatic light', 'storm'],
        'clouds rolling in, light rays shifting, atmospheric haze drifting',
    ),
    # Water / ocean / sea
    (
        ['ocean', 'sea', 'river', 'waves', 'water', 'lake', 'coast', 'beach'],
        'waves rolling and crashing, water surface glittering and rippling',
    ),
    # Static standing / posed characters — inject subtle life
    (
        [
            'standing',
            'victorious',
            'atop',
            'lone ',
            'solitary',
            'single',
            'overlooking',
            'gazing',
            'watching',
            'surveying',
            'posed',
        ],
        'character cloak and hair billowing in wind, subtle breathing movement, slow camera orbit',
    ),
    # Battle / combat — inject kinetic energy
    (
        [
            'battle',
            'fight',
            'combat',
            'clash',
            'charge',
            'charging',
            'attack',
            'war',
            'sword',
            'spear',
            'shield',
            'bleed',
            'blood',
        ],
        'camera tracking fast movement, dust and debris flying, figures in dynamic motion',
    ),
    # Crowd / army
    (
        ['army', 'soldiers', 'warriors', 'horde', 'legion', 'troops', 'crowd', 'masses'],
        'figures moving in formation, banners and standards rippling in the wind',
    ),
]

_EMOTION_PRIORITY = {
    'shock': 9,
    'triumph': 8,
    'grief': 8,
    'anger': 7,
    'awe': 7,
    'tension': 6,
    'unease': 5,
    'mystery': 5,
    'calm': 2,
    'neutral': 1,
}

# Shot-type → cinematic camera direction override (used when visual_style='cinematic').
# These replace the emotion-derived heuristic with intentional film grammar.
_CAMERA_BY_SHOT: dict[str, str] = {
    'wide shot': 'slow drone pullback revealing vast scale, anamorphic lens flare',
    'establishing shot': 'slow drone pullback revealing vast scale, anamorphic lens flare',
    'medium shot': 'gentle dolly push-in, shallow depth-of-field, teal-orange grade',
    'close-up': 'slow creeping zoom, rack-focus shift, shallow depth-of-field',
    'extreme close-up': 'rack focus drift across fine detail, shallow bokeh, film grain',
    'over-the-shoulder': 'subtle handheld sway, face bokeh background, cinematic warmth',
    'two-shot': 'slow lateral dolly, natural framing, cinematic colour grade',
    'aerial': 'slow aerial drift, mist and atmosphere, epic depth',
    'low angle': 'slow rise upward, heroic framing, anamorphic distortion',
}

# Suffix appended to every WAN prompt when visual_style='cinematic'
# Curated negative for LOCKED-CAMERA / static shots (2026-07-29 morph research).
# The template default negative contains 'static, frozen, no motion' — Wan's official
# anti-static tokens that FORCE motion; on a locked shot they are what makes the set
# churn, the camera push in, and props morph. This replacement keeps the official
# Chinese quality negatives (untranslated — translation weakens them), drops the
# anti-static and anti-artwork tokens (we WANT a painterly still scene), and adds
# camera-motion + scene-change + identity negatives.
_STATIC_SHOT_NEG = (
    '色调艳丽, 过曝, 整体发灰, 最差质量, 低质量, JPEG压缩残留, 丑陋的, 残缺的, 畸形的, '
    '形态畸形的肢体, 多余的手指, 手指融合, 三条腿, 杂乱的背景, '
    '镜头移动, 镜头晃动, 推镜, 拉镜, 变焦, camera movement, camera pan, camera zoom, '
    'dolly, push in, tracking shot, handheld camera, morphing background, warping, '
    'objects changing, flickering, changing face, changing hairstyle, different person, '
    'photorealistic, photograph, deformed anatomy, extra limbs'
)

_CINEMATIC_WAN_SUFFIX = (
    'anamorphic lens, cinematic colour grade teal-orange, '
    'shallow depth-of-field, film grain, professional cinematography, '
    'smooth motion, 4K quality'
)
