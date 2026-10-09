# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
pipeline_dsl_adapter.py
=======================
Universal hook layer that wires the SCENE DSL + caveman style into the
production pipelines (documentary, intro, video, storyteller, character).

Design goals
------------
* Opt-in: pipelines call thin helpers; if env flags are unset, the helpers
  short-circuit and return inputs unchanged.
* Non-invasive: no pipeline control flow changes — only prompt wrapping
  and side-effect-free DSL persistence.
* Pipeline-scoped: each pipeline can be enabled or disabled independently
  through PIPELINE_DSL_PIPELINES (comma-separated allowlist).

Environment flags
-----------------
PIPELINE_DSL_ENABLED            — master switch ("true"/"1"/"yes" to enable)
PIPELINE_DSL_PIPELINES          — comma-separated allowlist
                                  (e.g. "documentary,video,storyteller,character")
                                  Default: all pipelines when master is on.
PIPELINE_DSL_PERSIST            — "true" to write Scene YAML files to disk
CAVEMAN_STYLE_LEVEL             — off/base/extended/aggressive
CAVEMAN_STYLE_ENABLED           — legacy boolean (maps to BASE)

Public API
----------
is_enabled(pipeline)            — DSL active for this pipeline?
caveman_level()                 — current CavemanStyle
wrap_system(prompt, pipeline)   — append caveman instruction to system prompt
wrap_user(prompt, pipeline)     — append caveman instruction to user prompt
build_scene_from_text(...)      — generate Scene from raw text (returns None if disabled)
persist_scene(scene, out_dir)   — write Scene YAML alongside pipeline output
scene_to_flux_overrides(scene)  — flux config dict (caller merges into its own params)
scene_to_ffmpeg_overrides(scene)— ffmpeg config dict
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# ── Soft imports — adapter must load even if DSL modules / yaml are missing ──
try:
    from zyg_workflows.caveman_style import (
        CavemanStyle,
        get_caveman_instruction,
        get_caveman_style,
        inject_caveman_into_system_prompt,
    )

    _CAVEMAN_AVAILABLE = True
except ImportError:
    _CAVEMAN_AVAILABLE = False
    CavemanStyle = None  # type: ignore

try:
    from zyg_workflows.dsl_schema import Scene, scene_to_yaml_file
    from zyg_workflows.dsl_llm_generator import DSLLLMGenerator
    from zyg_workflows.dsl_transformers import dsl_to_flux_config, dsl_to_ffmpeg_config

    _DSL_AVAILABLE = True
except ImportError as _imp_exc:
    _DSL_AVAILABLE = False
    Scene = None  # type: ignore
    DSLLLMGenerator = None  # type: ignore
    logger.debug('DSL modules not loadable: %s', _imp_exc)


# ─────────────────────────────────────────────────────────────────────────────
# Env helpers
# ─────────────────────────────────────────────────────────────────────────────


def _truthy(val: str) -> bool:
    return (val or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _master_dsl_on() -> bool:
    return _truthy(os.environ.get('PIPELINE_DSL_ENABLED', ''))


def _persist_on() -> bool:
    return _truthy(os.environ.get('PIPELINE_DSL_PERSIST', ''))


def _allowed_pipelines() -> set:
    raw = os.environ.get('PIPELINE_DSL_PIPELINES', '').strip()
    if not raw:
        # Empty allowlist → all pipelines allowed (when master switch is on)
        return set()
    return {p.strip().lower() for p in raw.split(',') if p.strip()}


# ─────────────────────────────────────────────────────────────────────────────
# Public predicates
# ─────────────────────────────────────────────────────────────────────────────


def is_enabled(pipeline: str = 'default') -> bool:
    """Is the DSL active for this pipeline?"""
    if not _DSL_AVAILABLE:
        return False
    if not _master_dsl_on():
        return False
    allow = _allowed_pipelines()
    if not allow:
        return True
    return pipeline.lower() in allow


def caveman_level():
    """Return the current CavemanStyle, or None if module missing."""
    if not _CAVEMAN_AVAILABLE:
        return None
    return get_caveman_style()


def caveman_active() -> bool:
    """Is caveman style enabled in the env?"""
    lvl = caveman_level()
    if lvl is None:
        return False
    return lvl != CavemanStyle.OFF


# ─────────────────────────────────────────────────────────────────────────────
# Prompt wrapping
# ─────────────────────────────────────────────────────────────────────────────


def wrap_system(prompt: str, pipeline: str = 'default') -> str:
    """
    Append the caveman instruction to a system prompt.

    Safe to call unconditionally — returns prompt unchanged if caveman_style
    is unavailable or the level is OFF.
    """
    if not prompt:
        return prompt
    if not _CAVEMAN_AVAILABLE:
        return prompt
    try:
        from zyg_workflows.caveman_style import should_apply_caveman

        if not should_apply_caveman('default'):
            return prompt
        return inject_caveman_into_system_prompt(prompt)
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] wrap_system failed (%s): %s', pipeline, exc)
        return prompt


def wrap_system_planner(prompt: str, pipeline: str = 'default') -> str:
    """Caveman on system for JSON planners — BASE brevity prepended, schema body intact."""
    if not prompt:
        return prompt
    if not _CAVEMAN_AVAILABLE:
        return prompt
    try:
        from zyg_workflows.caveman_style import CavemanStyle, get_caveman_instruction, should_apply_caveman

        if not should_apply_caveman('default'):
            return prompt
        instruction = get_caveman_instruction(CavemanStyle.BASE)
        if not instruction:
            return prompt
        return f'{instruction}\n\nKeep internal reasoning terse. Follow output format rules exactly.\n\n{prompt}'
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] wrap_system_planner failed (%s): %s', pipeline, exc)
        return prompt


def wrap_user(prompt: str, pipeline: str = 'default') -> str:
    """
    Append the caveman instruction to a user prompt.

    Use this for LLM calls that send everything in a single user message
    (no separate system field). Idempotent under repeated calls only if
    the level itself does not change between calls.

    Prefer wrap_user_planner() for JSON / structured single-message calls.
    """
    if not prompt:
        return prompt
    if not _CAVEMAN_AVAILABLE:
        return prompt
    try:
        from zyg_workflows.caveman_style import should_apply_caveman

        if not should_apply_caveman('default'):
            return prompt
        instruction = get_caveman_instruction()
        if not instruction:
            return prompt
        return f'{prompt}\n\n[STYLE: {instruction}]'
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] wrap_user failed (%s): %s', pipeline, exc)
        return prompt


def wrap_user_planner(prompt: str, pipeline: str = 'default') -> str:
    """BASE brevity on user-only JSON / structured planner prompts."""
    if not prompt:
        return prompt
    if not _CAVEMAN_AVAILABLE:
        return prompt
    try:
        from zyg_workflows.caveman_style import CavemanStyle, get_caveman_instruction, should_apply_caveman

        if not should_apply_caveman('default'):
            return prompt
        instruction = get_caveman_instruction(CavemanStyle.BASE)
        if not instruction:
            return prompt
        return f'{instruction}\n\nKeep internal reasoning terse. Follow output format rules exactly.\n\n{prompt}'
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] wrap_user_planner failed (%s): %s', pipeline, exc)
        return prompt


def caveman_record_meta(mode: str = '') -> dict:
    """Kwargs for _record_token_usage when caveman was applied at this call site."""
    if not mode or not caveman_active():
        return {'caveman_level': 'off', 'caveman_mode': ''}
    lvl = caveman_level()
    return {
        'caveman_level': lvl.value if lvl is not None else 'extended',
        'caveman_mode': mode,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DSL helpers
# ─────────────────────────────────────────────────────────────────────────────


def build_scene_from_text(
    text: str,
    *,
    pipeline: str = 'default',
    scene_id: str = 'scene',
    kind: str = 'description',
    sequence: int = 0,
    llm_callable: Optional[Callable[[str, str], str]] = None,
) -> Optional['Scene']:
    """
    Generate a Scene DSL object from raw text via the LLM.

    Returns None if:
      - DSL is disabled for this pipeline
      - llm_callable is missing
      - The LLM response cannot be parsed/validated

    `kind`: 'research' | 'script_beat' | 'description'
    """
    if not is_enabled(pipeline):
        return None
    if not text or llm_callable is None:
        return None
    try:
        generator = DSLLLMGenerator(use_caveman=caveman_active())
        if kind == 'research':
            return generator.generate_from_research(text, topic_id=scene_id, llm_callable=llm_callable)
        if kind == 'script_beat':
            return generator.generate_from_script_beat(text, sequence=sequence, llm_callable=llm_callable)
        return generator.generate_from_description(text, scene_id=scene_id, llm_callable=llm_callable)
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] build_scene_from_text failed (%s): %s', pipeline, exc)
        return None


def build_scene_from_metadata(
    metadata: Dict[str, Any],
    *,
    pipeline: str = 'default',
    scene_id: str = 'scene',
    sequence: int = 0,
) -> Optional['Scene']:
    """
    Build a Scene DSL object directly from a metadata dict, without invoking the LLM.

    Useful for character creation and other pipelines that already have
    structured semantic info (gender, lighting, style, etc.) and just need
    deterministic seeds + tool overrides.
    """
    if not is_enabled(pipeline) or not _DSL_AVAILABLE:
        return None
    try:
        from zyg_workflows.dsl_schema import (
            Scene,
            SceneAudio,
            SceneExecution,
            SceneMetadata,
            SceneQA,
            SceneSemantic,
            SceneTechnical,
            SceneVisual,
        )

        return Scene(
            metadata=SceneMetadata(
                id=scene_id,
                duration=float(metadata.get('duration', 0.0) or 0.0),
                sequence=sequence,
                tags=list(metadata.get('tags', []) or []),
            ),
            semantic=SceneSemantic(
                subject=str(metadata.get('subject', '') or ''),
                setting=str(metadata.get('setting', '') or ''),
            ),
            visual=SceneVisual(
                lighting_style=str(metadata.get('lighting_style', '') or ''),
                color_palette=str(metadata.get('color_palette', '') or ''),
                focus_point=str(metadata.get('focus_point', '') or ''),
                aspect_ratio=str(metadata.get('aspect_ratio', '') or '16:9'),
                composition=str(metadata.get('composition', '') or ''),
            ),
            audio=SceneAudio(),
            technical=SceneTechnical(),
            execution=SceneExecution(),
            qa=SceneQA(),
        )
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] build_scene_from_metadata failed (%s): %s', pipeline, exc)
        return None


def persist_scene(scene: Optional['Scene'], out_dir: str, filename: Optional[str] = None) -> Optional[str]:
    """
    Write a Scene to YAML alongside pipeline output. No-op if persistence is
    disabled or scene is None.

    Returns the written path (or None if skipped).
    """
    if scene is None or not _DSL_AVAILABLE:
        return None
    if not _persist_on():
        return None
    try:
        os.makedirs(out_dir, exist_ok=True)
        fname = filename or f'scene_{getattr(scene.metadata, "id", "unknown")}.yaml'
        path = os.path.join(out_dir, fname)
        scene_to_yaml_file(scene, path)
        return path
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] persist_scene failed: %s', exc)
        return None


def scene_to_flux_overrides(scene: Optional['Scene']) -> Dict[str, Any]:
    """
    Return a FLUX-config dict derived from the Scene DSL.
    Returns {} if scene is None or DSL is unavailable.

    Callers should treat this as an OVERRIDE: merge selectively into existing
    pipeline params, do NOT replace.
    """
    if scene is None or not _DSL_AVAILABLE:
        return {}
    try:
        return dict(dsl_to_flux_config(scene))
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] scene_to_flux_overrides failed: %s', exc)
        return {}


def scene_to_ffmpeg_overrides(scene: Optional['Scene']) -> Dict[str, Any]:
    """Return an ffmpeg-config dict derived from the Scene DSL (or {})."""
    if scene is None or not _DSL_AVAILABLE:
        return {}
    try:
        return dict(dsl_to_ffmpeg_config(scene))
    except Exception as exc:
        logger.warning('[pipeline_dsl_adapter] scene_to_ffmpeg_overrides failed: %s', exc)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Status report (for logging at pipeline start)
# ─────────────────────────────────────────────────────────────────────────────


def status_summary(pipeline: str = 'default') -> str:
    """One-line status string for the pipeline log."""
    parts = []
    parts.append(f'dsl={"on" if is_enabled(pipeline) else "off"}')
    lvl = caveman_level()
    parts.append(f'caveman={lvl.value if lvl is not None else "unavailable"}')
    parts.append(f'persist={"on" if _persist_on() else "off"}')
    return ' '.join(parts)


__all__ = [
    'is_enabled',
    'caveman_level',
    'caveman_active',
    'wrap_system',
    'wrap_system_planner',
    'wrap_user',
    'wrap_user_planner',
    'caveman_record_meta',
    'build_scene_from_text',
    'build_scene_from_metadata',
    'persist_scene',
    'scene_to_flux_overrides',
    'scene_to_ffmpeg_overrides',
    'status_summary',
]


if __name__ == '__main__':
    print('pipeline_dsl_adapter — status')
    print(f'  CAVEMAN module loaded:   {_CAVEMAN_AVAILABLE}')
    print(f'  DSL modules loaded:      {_DSL_AVAILABLE}')
    print(f'  Master switch:           {_master_dsl_on()}')
    print(f'  Allowed pipelines:       {_allowed_pipelines() or "all"}')
    for p in ('documentary', 'video', 'storyteller', 'character'):
        print(f'  {p:<14} → {status_summary(p)}')
