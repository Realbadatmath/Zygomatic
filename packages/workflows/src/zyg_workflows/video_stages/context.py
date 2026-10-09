# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one object every video-pipeline stage function shares.

`_run_video_pipeline` in `zyg_workflows.pipeline_video` was a single
2,963-line function whose stages talked to each other through plain locals.
The split moves each stage block into a `stage_<nn>_<slug>(ctx)` function in
`zyg_workflows.video_stages.stage_*`; every local that crosses a stage
boundary becomes a field of `VideoContext`, and nothing else about the code
changes.

A field here is one of four things:

* **run input** — one of the eight parameters, or a value the prologue derives
  from them before the first stage (`job`, `out_dir`, `_manga_mode`,
  `_dir_prefix`, the function-local `subprocess` alias `_sp_video`);
* **prologue closure** — `_log`, `_set_stage`, `_complete_stage` and
  `_fail_stage` stay nested `def`s of the driver, because they close over
  `job`, `pipeline_id` and `_manga_mode`; the stages reach them through the
  context and so call the very same objects the monolith called;
* **GPU-lock flag** — `_flux_gpu_acq_v` and `_wan_gpu_acq_v` are fields and
  not locals because the driver's `except`/`finally` release
  `_GPU_PIPELINE_LOCK` off them. `stage_02_image_prep` writes the FLUX one,
  `generate_wan_clips` writes the WAN one, and both have to be visible to
  the handlers the moment they flip — a write-back at the end of a stage would
  leak the lock on the paths that raise;
* **stage product** — written by one stage and read by a later one. These
  default to `None`, which is also what the monolith's locals effectively were
  before their first assignment.

Every field defaults, so a later task can append the fields its stages need
without touching the construction site. The fields are grouped by the stage
that first writes them, in run order.

`StageExit` and `UNSET` are the scholarly split's, re-exported here so both
packages share one mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zyg_workflows.scholarly.context import UNSET, StageExit

__all__ = ['UNSET', 'StageExit', 'VideoContext']


@dataclass
class VideoContext:
    """Everything that crosses a stage boundary of the video pipeline."""

    # ── Run inputs: the eight parameters of `_run_video_pipeline` ────────────
    pipeline_id: str = ''
    directive: str = ''
    image_paths: list[Any] = field(default_factory=list)
    video_duration_minutes: float = 0.5
    narration_enabled: bool = False
    visual_style: str = 'cinematic'
    scene_mode: str = 'independent'
    ending_text: str = ''

    # ── Run inputs the prologue derives ──────────────────────────────────────
    job: dict[str, Any] | None = None
    out_dir: str = ''
    _manga_mode: bool = False
    _dir_prefix: str = ''
    _sp_video: Any = None  # the driver's `import subprocess as _sp_video`

    # ── Prologue closures the stages call ────────────────────────────────────
    _log: Any = None
    _set_stage: Any = None
    _complete_stage: Any = None
    _fail_stage: Any = None

    # ── GPU-lock flags the driver's except/finally read ──────────────────────
    _flux_gpu_acq_v: bool = False
    _wan_gpu_acq_v: bool = False

    # ── Stage 1: Scene planning ──────────────────────────────────────────────
    scenes: Any = None
    topic: Any = None
    n_scenes: Any = None
    scene_duration: Any = None
    _target_total_sec: Any = None
    _vscfg: Any = None
    _claude_music_mood: Any = None

    # ── Stage 2: Image Prep ──────────────────────────────────────────────────
    images_dir: Any = None
    scene_images: Any = None

    # ── Stage 3: TTS Narration ───────────────────────────────────────────────
    tts_dir: Any = None
    tts_files: Any = None

    # ── Stage 4: Video Generation ────────────────────────────────────────────
    # `stage_04_video_generation` stores these three at its end; they are the
    # only Stage 4 products Stage 5 reads.
    clip_paths: Any = None
    good_clips: Any = None
    _audio_svc: Any = None

    # ── Module global of `pipeline_video`, read by the 4K master encode ──────
    # `pipeline_video.tts_duration` is `None` at module scope and nothing in
    # this pipeline assigns it; the driver copies whatever it holds onto the
    # context so the moved `int(tts_duration * 8 + 600)` reads the same object.
    tts_duration: Any = None
