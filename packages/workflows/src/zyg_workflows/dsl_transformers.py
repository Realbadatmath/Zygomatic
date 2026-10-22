#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
DSL Transformers — Convert SCENE DSL to tool-specific configurations.

This module transforms semantic DSL into deterministic, executable tool configs:
  - dsl_to_flux_config() → FLUX image generation parameters
  - dsl_to_mediapipe_config() → MediaPipe skeleton tracking parameters
  - dsl_to_ffmpeg_config() → ffmpeg video encoding parameters
  - dsl_to_yolo_config() → YOLO8 object detection parameters
  - dsl_to_rife_config() → RIFE interpolation parameters

Key principle: Transform semantic descriptions into exact numerical parameters
for deterministic tool execution.
"""

from typing import Dict, Any
from zyg_workflows.dsl_schema import Scene, MotionLevel, Complexity
import hashlib


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for deterministic mapping
# ─────────────────────────────────────────────────────────────────────────────


def _seed_from_scene_id(scene_id: str) -> int:
    """
    Generate deterministic seed from scene ID.

    Same scene ID always produces same seed → same outputs.
    Enables caching and reproducibility.
    """
    hash_obj = hashlib.md5(scene_id.encode(), usedforsecurity=False)
    return int(hash_obj.hexdigest(), 16) % (2**31)


def _expand_lighting_to_prompt(lighting_style: str) -> str:
    """
    Expand semantic lighting description to FLUX prompt text.

    Input:  "cool_blue + warm_accent"
    Output: "cool blue tones with warm golden highlights"
    """
    if not lighting_style:
        return ''

    # Simple mapping (can be expanded)
    mappings = {
        'cool_blue': 'cool blue tones',
        'warm_accent': 'warm golden accents',
        'cool_blue + warm_accent': 'cool blue tones with warm golden highlights',
        'dark': 'dark, shadowy lighting',
        'bright': 'bright, overexposed lighting',
        'warm_low': 'warm, low-angle lighting',
        'key_light': 'strong key light from above',
        'backlit': 'backlit, rim lighting',
        'dramatic': 'dramatic, chiaroscuro lighting',
    }

    return mappings.get(lighting_style, lighting_style)


def _emotion_to_guidance_scale(emotional_intensity: float) -> float:
    """
    Map emotional intensity to FLUX guidance scale.

    Higher emotion = higher guidance (more adherence to prompt).
    Range: 3.0 (minimal) to 15.0 (maximum)
    """
    return 3.0 + (emotional_intensity * 12.0)


def _motion_to_num_steps(motion_level: MotionLevel, complexity: Complexity) -> int:
    """
    Map motion level and complexity to FLUX inference steps.

    More motion / higher complexity = more steps (better quality).
    Range: 20 (fast) to 100 (quality)
    """
    base = {
        MotionLevel.MINIMAL: 40,
        MotionLevel.SLOW: 50,
        MotionLevel.NORMAL: 60,
        MotionLevel.DYNAMIC: 80,
        MotionLevel.FRENETIC: 100,
    }.get(motion_level, 60)

    # Complexity multiplier
    complexity_mult = {
        Complexity.LOW: 0.8,
        Complexity.MEDIUM: 1.0,
        Complexity.HIGH: 1.3,
        Complexity.EXTREME: 1.5,
    }.get(complexity, 1.0)

    return int(base * complexity_mult)


# ─────────────────────────────────────────────────────────────────────────────
# FLUX Transformer
# ─────────────────────────────────────────────────────────────────────────────


def dsl_to_flux_config(scene: Scene) -> Dict[str, Any]:
    """
    Transform SCENE DSL → FLUX image generation config.

    FLUX parameters:
      - prompt: what to generate
      - guidance_scale: how much to follow prompt (3-15)
      - num_inference_steps: quality vs speed (20-100)
      - seed: reproducibility
      - height, width: dimensions
      - scheduler: sampling method
    """

    # Build prompt from semantic + visual
    prompt_parts = []

    if scene.semantic.subject:
        prompt_parts.append(f'{scene.semantic.subject}')

    if scene.visual.lighting_style:
        prompt_parts.append(_expand_lighting_to_prompt(scene.visual.lighting_style))

    # scene_type labels (character, pure_action, …) must not become "in character" locations.
    _setting = (scene.semantic.setting or '').strip().lower()
    _taxonomy = frozenset(
        {
            'character',
            'pure_action',
            'landscape',
            'establishing',
            'action',
        }
    )
    if _setting and _setting not in _taxonomy:
        prompt_parts.append(f'in {_setting}')

    if scene.visual.motion_level == MotionLevel.MINIMAL:
        prompt_parts.append('static, still composition')
    elif scene.visual.motion_level == MotionLevel.DYNAMIC:
        prompt_parts.append('dynamic motion, flowing movement')

    if scene.visual.composition:
        prompt_parts.append(f'composition: {scene.visual.composition}')

    prompt = ', '.join(filter(None, prompt_parts))

    # Emotional intensity (average of emotional arc)
    emotional_intensity = 0.5  # default
    if scene.semantic.emotional_arc:
        # Map emotions to 0-1 scale (simple: just count distinct emotions)
        emotional_intensity = min(1.0, len(scene.semantic.emotional_arc) / 3.0)

    # Apply overrides if present
    config = {
        'prompt': prompt,
        'guidance_scale': _emotion_to_guidance_scale(emotional_intensity),
        'num_inference_steps': _motion_to_num_steps(
            scene.visual.motion_level or MotionLevel.NORMAL,
            scene.technical.estimated_complexity or Complexity.MEDIUM,
        ),
        'seed': _seed_from_scene_id(scene.metadata.id),
        'height': 768,  # default
        'width': 1344,  # 16:9 aspect
        'scheduler': 'DDIM',
        'negative_prompt': 'blurry, distorted, low quality, artifacts',
    }

    # Handle aspect ratio overrides
    aspect_to_dims = {
        '16:9': (768, 1344),
        '9:16': (1344, 768),
        '1:1': (768, 768),
        '4:3': (768, 1024),
    }
    if scene.visual.aspect_ratio in aspect_to_dims:
        h, w = aspect_to_dims[scene.visual.aspect_ratio]
        config['height'] = h
        config['width'] = w

    # Apply execution overrides
    if scene.execution.flux_overrides:
        config.update(scene.execution.flux_overrides)

    return config


# ─────────────────────────────────────────────────────────────────────────────
# MediaPipe Transformer
# ─────────────────────────────────────────────────────────────────────────────


def dsl_to_mediapipe_config(scene: Scene) -> Dict[str, Any]:
    """
    Transform SCENE DSL → MediaPipe skeleton tracking config.

    MediaPipe parameters:
      - static_image_mode: True for single frames
      - model_complexity: 0 (lite), 1 (full)
      - smooth_landmarks: temporal smoothing
      - min_detection_confidence: threshold
      - focus_point: which body part to track
    """

    # Motion level affects smoothing
    smooth = {
        MotionLevel.MINIMAL: True,
        MotionLevel.SLOW: True,
        MotionLevel.NORMAL: True,
        MotionLevel.DYNAMIC: False,  # Don't smooth fast motion
        MotionLevel.FRENETIC: False,
    }.get(scene.visual.motion_level, True)

    # Complexity determines model
    model_complexity = {
        Complexity.LOW: 0,
        Complexity.MEDIUM: 0,
        Complexity.HIGH: 1,
        Complexity.EXTREME: 1,
    }.get(scene.technical.estimated_complexity, 0)

    config = {
        'static_image_mode': False,
        'model_complexity': model_complexity,
        'smooth_landmarks': smooth,
        'min_detection_confidence': 0.7,
        'min_tracking_confidence': 0.5,
        'focus_point': scene.visual.focus_point or 'pose',  # Default: full body
    }

    # Focus point special handling
    if scene.visual.focus_point:
        if 'eye' in scene.visual.focus_point.lower():
            config['focus_point'] = 'face'
            config['min_detection_confidence'] = 0.8
        elif 'hand' in scene.visual.focus_point.lower():
            config['focus_point'] = 'hands'
        elif 'pose' in scene.visual.focus_point.lower():
            config['focus_point'] = 'pose'

    # Apply execution overrides
    if scene.execution.mediapipe_overrides:
        config.update(scene.execution.mediapipe_overrides)

    return config


# ─────────────────────────────────────────────────────────────────────────────
# ffmpeg Transformer
# ─────────────────────────────────────────────────────────────────────────────


def dsl_to_ffmpeg_config(scene: Scene) -> Dict[str, Any]:
    """
    Transform SCENE DSL → ffmpeg encoding config.

    ffmpeg parameters:
      - codec: vp9, h264, hevc
      - bitrate: quality (kbps)
      - fps: frame rate
      - color_grade: LUT or color profile
      - crf: quality factor
    """

    # Bitrate based on complexity
    bitrate_mbps = {
        Complexity.LOW: 2,
        Complexity.MEDIUM: 4,
        Complexity.HIGH: 8,
        Complexity.EXTREME: 16,
    }.get(scene.technical.estimated_complexity, 4)

    # Color grading based on lighting
    color_lut = None
    if scene.visual.lighting_style:
        if 'cool_blue' in scene.visual.lighting_style:
            color_lut = 'lut_cool_blue.3dl'
        elif 'warm' in scene.visual.lighting_style:
            color_lut = 'lut_warm_gold.3dl'
        elif 'dark' in scene.visual.lighting_style:
            color_lut = 'lut_cinematic_dark.3dl'

    config = {
        'codec': 'libvpx-vp9',  # VP9 for good quality/compression
        'bitrate': f'{bitrate_mbps}M',
        'fps': 24,  # Standard documentary fps
        'crf': 32 if scene.technical.estimated_complexity == Complexity.LOW else 28,
        'pixel_format': 'yuv420p',
        'color_lut': color_lut,
        'height': 1080,
        'width': 1920,
    }

    # Handle aspect ratio
    aspect_to_dims = {
        '16:9': (1080, 1920),
        '9:16': (1920, 1080),
        '1:1': (1080, 1080),
        '4:3': (1080, 1440),
    }
    if scene.visual.aspect_ratio in aspect_to_dims:
        h, w = aspect_to_dims[scene.visual.aspect_ratio]
        config['height'] = h
        config['width'] = w

    # Apply execution overrides
    if scene.execution.ffmpeg_overrides:
        config.update(scene.execution.ffmpeg_overrides)

    return config


# ─────────────────────────────────────────────────────────────────────────────
# YOLO8 Transformer
# ─────────────────────────────────────────────────────────────────────────────


def dsl_to_yolo_config(scene: Scene) -> Dict[str, Any]:
    """
    Transform SCENE DSL → YOLO8 object detection config.

    YOLO parameters:
      - conf: confidence threshold
      - iou: NMS IoU threshold
      - model_size: n, s, m, l, x
    """

    # Model size based on complexity
    model_size = {
        Complexity.LOW: 'n',  # nano - fast
        Complexity.MEDIUM: 's',  # small
        Complexity.HIGH: 'm',  # medium
        Complexity.EXTREME: 'l',  # large
    }.get(scene.technical.estimated_complexity, 'm')

    # Confidence based on focus point (eyes are harder to detect)
    conf_threshold = 0.5
    if scene.visual.focus_point and 'eye' in scene.visual.focus_point.lower():
        conf_threshold = 0.7

    config = {
        'model': f'yolov8{model_size}.pt',
        'conf': conf_threshold,
        'iou': 0.45,  # NMS threshold
        'device': 0,  # GPU device
    }

    # Apply execution overrides
    if scene.execution.yolo_overrides:
        config.update(scene.execution.yolo_overrides)

    return config


# ─────────────────────────────────────────────────────────────────────────────
# RIFE Transformer (Interpolation)
# ─────────────────────────────────────────────────────────────────────────────


def dsl_to_rife_config(scene: Scene) -> Dict[str, Any]:
    """
    Transform SCENE DSL → RIFE interpolation config.

    RIFE parameters:
      - model: model_name (rife46, etc.)
      - multiplier: 2x, 4x, 8x interpolation
      - device: GPU device
    """

    # Interpolation factor based on motion
    multiplier = {
        MotionLevel.MINIMAL: 2,
        MotionLevel.SLOW: 2,
        MotionLevel.NORMAL: 2,
        MotionLevel.DYNAMIC: 4,
        MotionLevel.FRENETIC: 8,
    }.get(scene.visual.motion_level, 2)

    config = {
        'model': 'rife46',
        'multiplier': multiplier,
        'device': 0,
        'ensemble': True,  # Better quality with ensemble
    }

    return config


# ─────────────────────────────────────────────────────────────────────────────
# Batch transformer
# ─────────────────────────────────────────────────────────────────────────────


def dsl_to_all_configs(scene: Scene) -> Dict[str, Dict[str, Any]]:
    """
    Generate all tool configs from a single SCENE DSL.

    Returns dict with keys: flux, mediapipe, ffmpeg, yolo, rife
    """
    return {
        'flux': dsl_to_flux_config(scene),
        'mediapipe': dsl_to_mediapipe_config(scene),
        'ffmpeg': dsl_to_ffmpeg_config(scene),
        'yolo': dsl_to_yolo_config(scene),
        'rife': dsl_to_rife_config(scene),
    }


if __name__ == '__main__':  # the CLI lives in dsl_transformers_cli
    from zyg_workflows.dsl_transformers_cli import main as _cli_main

    raise SystemExit(_cli_main())
