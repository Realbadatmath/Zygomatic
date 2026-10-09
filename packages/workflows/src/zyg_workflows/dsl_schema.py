#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Documentary Pipeline — Intermediate Semantic DSL (Domain-Specific Language)

This module defines the SCENE DSL schema for the documentary production pipeline.
The DSL bridges the semantic world (LLM planning, research, scripting) and the
deterministic world (tool execution: FLUX, MediaPipe, ffmpeg, YOLO8, RIFE, etc).

Architecture:
  Research/Script (prose or planning)
    → [LLM + caveman prompting]
    → SCENE DSL (structured YAML)
    → [Validators]
    → Valid SCENE DSL
    → [Transformers]
    → Tool configs (FLUX, MediaPipe, ffmpeg, etc.)
    → Execute tools
"""

from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import yaml
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_iso() -> str:
    """Tz-aware ISO timestamp in Europe/Amsterdam (UTC fallback)."""
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ).isoformat(timespec='milliseconds')
        except Exception as _exc:
            _zyg_log.debug('amsterdam timestamp failed, using utc: %s', _exc)
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


# ─────────────────────────────────────────────────────────────────────────────
# Enums for strict typing
# ─────────────────────────────────────────────────────────────────────────────


class CameraMovement(str, Enum):
    """Camera movement types."""

    STATIC = 'static'
    PUSH_IN = 'push_in'
    PULL_OUT = 'pull_out'
    PAN_LEFT = 'pan_left'
    PAN_RIGHT = 'pan_right'
    TILT_UP = 'tilt_up'
    TILT_DOWN = 'tilt_down'
    ZOOM_IN = 'zoom_in'
    ZOOM_OUT = 'zoom_out'
    ORBIT = 'orbit'
    FOLLOW = 'follow'
    DOLLY = 'dolly'
    HANDHELD = 'handheld'


class MotionLevel(str, Enum):
    """Intensity of motion in the scene."""

    MINIMAL = 'minimal'
    SLOW = 'slow'
    NORMAL = 'normal'
    DYNAMIC = 'dynamic'
    FRENETIC = 'frenetic'


class Complexity(str, Enum):
    """Scene complexity level (affects render settings)."""

    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    EXTREME = 'extreme'


class Emotion(str, Enum):
    """Emotional states (for narrative and audio design)."""

    FEAR = 'fear'
    WONDER = 'wonder'
    CURIOSITY = 'curiosity'
    DREAD = 'dread'
    CALM = 'calm'
    TENSION = 'tension'
    JOY = 'joy'
    MELANCHOLY = 'melancholy'
    AWE = 'awe'
    CONFUSION = 'confusion'
    CLARITY = 'clarity'
    MYSTERY = 'mystery'


class NarrativeFunction(str, Enum):
    """Narrative role of the scene."""

    EXPOSITION = 'exposition'
    RISING_ACTION = 'rising_action'
    CLIMAX = 'climax'
    FALLING_ACTION = 'falling_action'
    RESOLUTION = 'resolution'
    HOOK = 'hook'
    REVEAL = 'reveal'
    TRANSITION = 'transition'
    MONTAGE = 'montage'


class TempoTiming(str, Enum):
    """Tempo/pacing for music and narration."""

    VERY_SLOW = 'very_slow'
    SLOW = 'slow'
    MODERATE = 'moderate'
    FAST = 'fast'
    VERY_FAST = 'very_fast'


class RepairMethod(str, Enum):
    """Repair method for QA failures."""

    FLUX_INPAINT = 'flux_inpaint'
    RIFE_INTERPOLATION = 'rife_interpolation'
    OPENCV_TELEA = 'opencv_telea'
    MANUAL = 'manual'
    SKIP = 'skip'


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes (DSL Schema)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SceneMetadata:
    """Metadata and tracking information."""

    id: str  # Unique scene identifier (deterministic seed)
    version: int = 1  # Schema version
    duration: float = 0.0  # Duration in seconds
    sequence: int = 0  # Position in sequence
    timestamp: str = field(default_factory=_ams_iso)
    tags: List[str] = field(default_factory=list)  # Searchable tags
    continuity_refs: List[str] = field(default_factory=list)  # Links to other scenes


@dataclass
class SceneSemantic:
    """Semantic/narrative information (for LLM planning)."""

    emotional_arc: List[str] = field(default_factory=list)  # [start_emotion, end_emotion]
    narrative_function: Optional[NarrativeFunction] = None
    subject: str = ''  # Main subject/focus
    setting: str = ''  # Location/environment
    conflict: str = ''  # Central tension (if any)
    discovery: str = ''  # Key revelation (if any)


@dataclass
class SceneVisual:
    """Visual directives (for FLUX, YOLO8, MediaPipe, color grading)."""

    camera_movement: Optional[CameraMovement] = None
    camera_speed: float = 1.0  # Multiplier: 0.5 = half speed, 2.0 = double

    lighting_style: str = ''  # e.g., "cool_blue + warm_accent"
    color_palette: List[str] = field(default_factory=list)  # e.g., ["deep_ocean", "gold"]

    focus_point: str = ''  # e.g., "eyes", "artifact", "landscape"
    depth_of_field: Optional[str] = None  # shallow, medium, deep

    motion_level: Optional[MotionLevel] = None
    subject_scale: float = 1.0  # Size relative to frame (0.1 to 5.0)

    composition: str = ''  # e.g., "rule_of_thirds", "centered", "leading_lines"
    aspect_ratio: str = '16:9'


@dataclass
class SceneAudio:
    """Audio directives (for TTS, music, sound design)."""

    narration_style: str = ''  # e.g., "whisper", "authoritative", "intimate"
    narration_emotion: Optional[Emotion] = None
    narration_pace: Optional[TempoTiming] = None

    music_mood: str = ''  # e.g., "tense", "peaceful", "triumphant"
    music_tempo: Optional[TempoTiming] = None
    music_intensity: float = 1.0  # 0.0 (silent) to 1.0 (maximum)

    sfx_list: List[str] = field(default_factory=list)  # Sound effects to include
    ambient_sound: str = ''  # Ambient background sound


@dataclass
class SceneTechnical:
    """Technical requirements and constraints."""

    requires_qa_check: bool = True
    requires_repair_check: bool = False
    render_priority: int = 50  # 0-100, higher = more important
    estimated_complexity: Optional[Complexity] = None

    gpu_memory_required_gb: float = 8.0
    estimated_render_time_minutes: float = 5.0

    # Warnings/blockers for executor
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class SceneExecution:
    """Tool-specific overrides and execution parameters."""

    flux_overrides: Dict[str, Any] = field(default_factory=dict)
    mediapipe_overrides: Dict[str, Any] = field(default_factory=dict)
    ffmpeg_overrides: Dict[str, Any] = field(default_factory=dict)
    yolo_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QAIssue:
    """QA failure record."""

    issue_type: str  # e.g., "face_drift", "lighting_flicker", "temporal_jitter"
    severity: str  # low, medium, high, critical
    frame_indices: List[int] = field(default_factory=list)
    suggested_repair: Optional[RepairMethod] = None
    details: str = ''


@dataclass
class SceneQA:
    """QA and repair information."""

    qa_score: Optional[float] = None  # 0.0-1.0, None if not yet QA'd
    qa_timestamp: Optional[str] = None
    qa_passed: bool = False
    qa_issues: List[QAIssue] = field(default_factory=list)

    repair_applied: bool = False
    repair_method: Optional[RepairMethod] = None
    repair_timestamp: Optional[str] = None


@dataclass
class Scene:
    """
    Complete SCENE DSL object.

    This is the semantic representation of a single scene in the documentary.
    It bridges the gap between:
      - Input: LLM planning, research, script beats
      - Output: Tool-specific configurations (FLUX, MediaPipe, ffmpeg, etc.)
    """

    metadata: SceneMetadata
    semantic: SceneSemantic = field(default_factory=SceneSemantic)
    visual: SceneVisual = field(default_factory=SceneVisual)
    audio: SceneAudio = field(default_factory=SceneAudio)
    technical: SceneTechnical = field(default_factory=SceneTechnical)
    execution: SceneExecution = field(default_factory=SceneExecution)
    qa: SceneQA = field(default_factory=SceneQA)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for YAML serialization)."""
        return asdict(self)

    def to_yaml(self) -> str:
        """Convert to YAML string."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Scene':
        """Create Scene from dictionary."""
        # Reconstruct with proper type handling
        return cls(
            metadata=SceneMetadata(**data.get('metadata', {})),
            semantic=SceneSemantic(**data.get('semantic', {})),
            visual=SceneVisual(**data.get('visual', {})),
            audio=SceneAudio(**data.get('audio', {})),
            technical=SceneTechnical(**data.get('technical', {})),
            execution=SceneExecution(**data.get('execution', {})),
            qa=SceneQA(**data.get('qa', {})),
        )

    @classmethod
    def from_yaml(cls, yaml_content: str) -> 'Scene':
        """Create Scene from YAML string."""
        data = yaml.safe_load(yaml_content)
        return cls.from_dict(data)


# ─────────────────────────────────────────────────────────────────────────────
# Example Scene (documentation)
# ─────────────────────────────────────────────────────────────────────────────

EXAMPLE_SCENE = Scene(
    metadata=SceneMetadata(
        id='ocean_01_creature_reveal',
        duration=8.0,
        sequence=5,
        tags=['discovery', 'creature', 'ocean', 'dread_to_wonder'],
        continuity_refs=['ocean_00_descent', 'ocean_02_behavior'],
    ),
    semantic=SceneSemantic(
        emotional_arc=['dread', 'wonder'],
        narrative_function=NarrativeFunction.REVEAL,
        subject='unknown deep-sea creature',
        setting='abyssal zone, 3000m depth',
        conflict='unknown threat vs scientific curiosity',
        discovery='creature is harmless and beautiful',
    ),
    visual=SceneVisual(
        camera_movement=CameraMovement.PUSH_IN,
        camera_speed=0.3,  # Very slow push
        lighting_style='cool_blue + warm_golden_accent',
        color_palette=['deep_ocean_blue', 'bioluminescent_cyan', 'warm_gold'],
        focus_point='creature_eyes',
        depth_of_field='deep',
        motion_level=MotionLevel.MINIMAL,
        composition='rule_of_thirds',
        aspect_ratio='16:9',
    ),
    audio=SceneAudio(
        narration_style='whisper',
        narration_emotion=Emotion.AWE,
        narration_pace=TempoTiming.SLOW,
        music_mood='mysterious_and_sublime',
        music_tempo=TempoTiming.SLOW,
        music_intensity=0.7,
        sfx_list=['water_pressure_ambient', 'bioluminescence_pulse'],
    ),
    technical=SceneTechnical(
        requires_qa_check=True,
        requires_repair_check=False,
        render_priority=85,
        estimated_complexity=Complexity.HIGH,
        gpu_memory_required_gb=16.0,
        estimated_render_time_minutes=8.0,
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Utility: Serialize/deserialize
# ─────────────────────────────────────────────────────────────────────────────


def scene_to_yaml_file(scene: Scene, filepath: str) -> None:
    """Write scene to YAML file."""
    with open(filepath, 'w') as f:
        f.write(scene.to_yaml())


def scene_from_yaml_file(filepath: str) -> Scene:
    """Load scene from YAML file."""
    with open(filepath, 'r') as f:
        return Scene.from_yaml(f.read())


if __name__ == '__main__':
    # Demo: print example scene
    print('=' * 70)
    print('EXAMPLE SCENE DSL')
    print('=' * 70)
    print(EXAMPLE_SCENE.to_yaml())
