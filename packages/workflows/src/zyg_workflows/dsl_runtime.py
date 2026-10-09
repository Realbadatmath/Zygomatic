# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Load persisted SCENE DSL YAML and merge into FLUX generation kwargs."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    from zyg_workflows.dsl_schema import Scene, scene_from_yaml_file
    from zyg_workflows.dsl_transformers import dsl_to_flux_config

    _DSL_OK = True
except ImportError:
    _DSL_OK = False
    Scene = None  # type: ignore


def load_scene_yaml(path: str | None) -> Any | None:
    if not path or not _DSL_OK or not os.path.isfile(path):
        return None
    try:
        return scene_from_yaml_file(path)
    except Exception as exc:
        logger.debug('dsl_runtime: failed to load %s: %s', path, exc)
        return None


def _minimal_dsl_prompt(scene) -> str:
    """Lighting + composition only — avoid duplicating subject/setting into FLUX."""
    try:
        from zyg_workflows.dsl_transformers import _expand_lighting_to_prompt
    except ImportError:
        _expand_lighting_to_prompt = lambda _x: ''  # type: ignore
    parts: list[str] = []
    if scene.visual.lighting_style:
        lit = _expand_lighting_to_prompt(scene.visual.lighting_style)
        if lit:
            parts.append(lit)
    if scene.visual.composition:
        parts.append(f'composition: {scene.visual.composition}')
    return ', '.join(filter(None, parts))


def merge_flux_generation_params(
    prompt: str,
    *,
    seed: int,
    steps: int,
    cfg: float,
    dsl_yaml_path: str | None = None,
    is_schnell: bool = False,
    portrait_mode: bool = False,
) -> tuple[str, int, int, float]:
    """Apply DSL-derived FLUX overrides when a scene YAML exists."""
    scene = load_scene_yaml(dsl_yaml_path)
    if scene is None:
        return prompt, seed, steps, cfg
    try:
        fx = dsl_to_flux_config(scene)
    except Exception as exc:
        logger.warning('dsl_runtime: dsl_to_flux_config failed: %s', exc)
        return prompt, seed, steps, cfg

    if portrait_mode:
        dsl_prompt = _minimal_dsl_prompt(scene).strip()
    else:
        dsl_prompt = (fx.get('prompt') or '').strip()
    if dsl_prompt:
        prompt = f'{prompt}, {dsl_prompt}' if prompt else dsl_prompt

    seed = int(fx.get('seed', seed))
    steps = int(fx.get('num_inference_steps', steps))
    cfg = float(fx.get('guidance_scale', cfg))

    if is_schnell:
        steps = min(steps, 8)
        cfg = 0.0
    else:
        steps = max(4, min(steps, 50))
        cfg = max(0.0, min(cfg, 15.0))

    return prompt, seed, steps, cfg


def scene_yaml_path(dsl_dir: str, scene_index: int) -> str:
    return os.path.join(dsl_dir, f'scene_{scene_index:02d}.yaml')
