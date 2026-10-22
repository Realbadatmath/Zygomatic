#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
DSL Validator — Validate and type-check SCENE DSL objects.

This module provides:
  - Schema validation (type checking, required fields)
  - Reference validation (continuity_refs point to real scenes)
  - Consistency checks (emotional_arc has 2 emotions, duration > 0, etc.)
  - Early error detection (catch LLM hallucinations before execution)
"""

from typing import Tuple, List, Optional
from zyg_workflows.dsl_schema import Scene, SceneMetadata, SceneSemantic, Emotion
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class DSLValidationError(Exception):
    """Raised when DSL validation fails."""

    pass


class DSLValidator:
    """Validates SCENE DSL objects."""

    def __init__(self, scene_database_dir: Optional[str] = None):
        """
        Initialize validator.

        Args:
            scene_database_dir: Directory where scene YAML files are stored.
                                Used for reference validation.
        """
        self.scene_database_dir = scene_database_dir
        self._cached_scene_ids = set()

        if scene_database_dir and os.path.isdir(scene_database_dir):
            self._index_scene_ids()

    def _index_scene_ids(self) -> None:
        """Index all scene IDs in the database directory."""
        for filename in os.listdir(self.scene_database_dir):
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                scene_id = filename.rsplit('.', 1)[0]
                self._cached_scene_ids.add(scene_id)

    def validate(self, scene: Scene) -> Tuple[bool, List[str]]:
        """
        Validate a SCENE object.

        Returns:
            (is_valid: bool, errors: list[str])

        If is_valid=True, scene is safe to execute.
        If is_valid=False, errors list contains validation failures.
        """
        errors = []

        # Metadata validation
        errors.extend(self._validate_metadata(scene.metadata))

        # Semantic validation
        errors.extend(self._validate_semantic(scene.semantic))

        # Visual validation
        errors.extend(self._validate_visual(scene.visual))

        # Audio validation
        errors.extend(self._validate_audio(scene.audio))

        # Technical validation
        errors.extend(self._validate_technical(scene.technical))

        # Cross-field validation
        errors.extend(self._validate_consistency(scene))

        # Reference validation (if database dir provided)
        if self.scene_database_dir:
            errors.extend(self._validate_references(scene))

        return len(errors) == 0, errors

    def validate_strict(self, scene: Scene) -> None:
        """
        Validate with strict mode.
        Raises DSLValidationError if any validation fails.
        """
        is_valid, errors = self.validate(scene)
        if not is_valid:
            raise DSLValidationError(
                f"DSL validation failed for scene '{scene.metadata.id}':\n" + '\n'.join(f'  - {e}' for e in errors)
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Individual validators
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_metadata(self, metadata: SceneMetadata) -> List[str]:
        """Validate metadata section."""
        errors = []

        if not metadata.id or not isinstance(metadata.id, str):
            errors.append('metadata.id: must be non-empty string')

        if metadata.duration <= 0:
            errors.append(f'metadata.duration: must be > 0, got {metadata.duration}')

        if metadata.duration > 3600:  # 1 hour max per scene
            errors.append(f'metadata.duration: exceeds 1 hour, got {metadata.duration}s')

        if metadata.sequence < 0:
            errors.append(f'metadata.sequence: must be >= 0, got {metadata.sequence}')

        if metadata.version < 1:
            errors.append(f'metadata.version: must be >= 1, got {metadata.version}')

        return errors

    def _validate_semantic(self, semantic: SceneSemantic) -> List[str]:
        """Validate semantic section."""
        errors = []

        # Check emotional_arc
        if semantic.emotional_arc:
            if len(semantic.emotional_arc) < 2:
                errors.append(
                    f'semantic.emotional_arc: must have start and end emotion, got {len(semantic.emotional_arc)}'
                )
            else:
                # Validate emotions are valid
                try:
                    for emotion in semantic.emotional_arc:
                        if emotion not in [e.value for e in Emotion]:
                            errors.append(
                                f"semantic.emotional_arc: '{emotion}' is not a valid emotion. "
                                f'Valid: {[e.value for e in Emotion]}'
                            )
                except Exception as e:
                    errors.append(f'semantic.emotional_arc: {e}')

        # Check narrative_function
        if semantic.narrative_function:
            from zyg_workflows.dsl_schema import NarrativeFunction

            valid_funcs = [f.value for f in NarrativeFunction]
            if semantic.narrative_function not in valid_funcs:
                errors.append(f"semantic.narrative_function: '{semantic.narrative_function}' not in {valid_funcs}")

        return errors

    def _validate_visual(self, visual) -> List[str]:
        """Validate visual section."""
        errors = []

        if visual.camera_speed <= 0:
            errors.append(f'visual.camera_speed: must be > 0, got {visual.camera_speed}')

        if visual.camera_speed > 10:
            errors.append(f'visual.camera_speed: unrealistic speed {visual.camera_speed}')

        if visual.subject_scale < 0.1 or visual.subject_scale > 5.0:
            errors.append(f'visual.subject_scale: must be in [0.1, 5.0], got {visual.subject_scale}')

        if visual.aspect_ratio and visual.aspect_ratio not in ['16:9', '9:16', '1:1', '4:3']:
            errors.append(f"visual.aspect_ratio: '{visual.aspect_ratio}' not standard")

        return errors

    def _validate_audio(self, audio) -> List[str]:
        """Validate audio section."""
        errors = []

        if audio.music_intensity < 0.0 or audio.music_intensity > 1.0:
            errors.append(f'audio.music_intensity: must be in [0.0, 1.0], got {audio.music_intensity}')

        return errors

    def _validate_technical(self, technical) -> List[str]:
        """Validate technical section."""
        errors = []

        if technical.gpu_memory_required_gb < 1:
            errors.append(f'technical.gpu_memory_required_gb: must be >= 1, got {technical.gpu_memory_required_gb}')

        if technical.gpu_memory_required_gb > 80:
            errors.append(f'technical.gpu_memory_required_gb: unrealistic, got {technical.gpu_memory_required_gb}')

        if technical.render_priority < 0 or technical.render_priority > 100:
            errors.append(f'technical.render_priority: must be in [0, 100], got {technical.render_priority}')

        return errors

    def _validate_consistency(self, scene: Scene) -> List[str]:
        """Validate cross-field consistency."""
        errors = []

        # If estimated_complexity is HIGH/EXTREME, GPU should be high
        if scene.technical.estimated_complexity:
            from zyg_workflows.dsl_schema import Complexity

            if scene.technical.estimated_complexity in [Complexity.HIGH, Complexity.EXTREME]:
                if scene.technical.gpu_memory_required_gb < 12:
                    errors.append(
                        f'Complexity is {scene.technical.estimated_complexity} '
                        f'but GPU memory is only {scene.technical.gpu_memory_required_gb}GB. '
                        f'Recommend >= 16GB.'
                    )

        return errors

    def _validate_references(self, scene: Scene) -> List[str]:
        """Validate continuity references point to real scenes."""
        errors = []

        for ref in scene.metadata.continuity_refs:
            if ref not in self._cached_scene_ids:
                errors.append(
                    f"metadata.continuity_refs: reference '{ref}' not found in database. "
                    f'Available: {sorted(list(self._cached_scene_ids))[:5]}...'
                )

        return errors


def validate_scene(scene: Scene, strict: bool = False) -> bool:
    """
    Quick validation function.

    Args:
        scene: SCENE object to validate
        strict: If True, raise exception on validation failure

    Returns:
        True if valid, False otherwise (unless strict=True, then raises)
    """
    validator = DSLValidator()
    is_valid, errors = validator.validate(scene)

    if not is_valid:
        _zyg_log.info(f"Validation failed for scene '{scene.metadata.id}':")
        for error in errors:
            _zyg_log.info(f'  ✗ {error}')

    if strict and not is_valid:
        raise DSLValidationError(f"Scene '{scene.metadata.id}' failed validation")

    return is_valid


if __name__ == '__main__':  # the CLI lives in dsl_validator_cli
    from zyg_workflows.dsl_validator_cli import main as _cli_main

    raise SystemExit(_cli_main())
