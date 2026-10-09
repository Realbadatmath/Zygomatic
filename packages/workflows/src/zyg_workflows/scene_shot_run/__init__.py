# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_shot_run.py — one shot.json in, one final.mp4 out.

This is the assembler for the Blender scene bridge: the operator's six questions
(where is the city, where is the camera, where are the VFX, where is the actor,
what does the video engine do with all that, and what does it look like cut
together) are answered by seven stages that already exist as separate tools.
This module is the only place that knows the ORDER, the caching rule and the
composite.

    "…/agents/.venv/bin/python" scene_shot_run.py         data/architecture/shots/<id>/shot.json         [--engine vace|animate] [--skip-video] [--draft-only] [--force STAGE,…]

STAGES — each idempotent, each skipped when its outputs are newer than its
inputs, each writing a line into ``<shot_dir>/receipt.json``:

  1 validate   scene_shot.load + validate + resolve_positions -> shot.resolved.json
  2 build      blender_scripts/scene_build.py                 -> scene.blend
  3 draft      blender_scripts/scene_render.py --mode draft   -> draft/draft.mp4
  4 plates     scene_plates_export.py then scene_plates.build -> plates_raw/, plates/
  5 video      VACE (movement_studio scene_plateset path) or Wan-Animate
               (wan_animate_service.animate_from_plateset)    -> video/<engine>_take<N>/
  6 vfx        scene_render.py --mode full --effects-only 1   -> full/effects_alpha.mov
  7 composite  ffmpeg: engine clip + the alpha element        -> final.mp4, final_strip.png

WHY THE VFX ARE A SEPARATE LAYER. The video engine resamples the actor region of
a Blender beauty plate; it has never seen the volumes, and asking it to keep them
would be asking it to re-invent a Cycles render. So the volumes are rendered ONCE
in Cycles with the geometry as a holdout, come out as ProRes 4444 with a real
alpha, and are laid over the engine's output. The honest cost of that choice is
recorded in the docs: the VFX are not lit by, and do not light, the engine's
picture.

Locks. Every headless Blender launch holds the flock on
``/tmp/claude-1000/arch_ext_blender.lock`` (two at once SIGBUS the Bonsai
add-on). The two stages that put a model or a path tracer on the GPU — 5 and 6 —
additionally hold ``geom.pose_track.gpu_lock``.
"""

# ruff: noqa: F401  this __init__ is a pure re-export surface: it must bind every
# name the pre-split module defined, used here or not.

# The submodules, imported in the original section order so module-level side
# effects (the sys.path bootstrap, the makedirs, the catalog literals) run in
# exactly the pre-split sequence.
from zyg_workflows.scene_shot_run import (  # noqa: E402
    constants,
    planner,
    stages,
    runner,
)

from zyg_workflows.scene_shot_run.constants import (
    annotations,
    argparse,
    glob,
    json,
    os,
    re,
    shutil,
    subprocess,
    sys,
    tempfile,
    time,
    traceback,
    paths,
    exe,
    _zyg_logging,
    _zyg_log,
    HERE,
    BLENDER,
    BLENDER_LOCK,
    SCRIPTS,
    SCHEMA,
    STAGE_ORDER,
    _log,
    CHARS_ROOT,
    LORA_ROOT,
    _CHAR_ID_RE,
    _IMG_EXT,
    _images_in,
    resolve_character,
)
from zyg_workflows.scene_shot_run.planner import (
    stage_io,
    _absent,
    engine_clip,
    plan_stages,
    composite_cmd,
    _decode,
    contact_strip,
    _last_json,
    blender_run,
    ffprobe,
)
from zyg_workflows.scene_shot_run.stages import (
    run_build,
    run_draft,
    run_plates,
    run_vfx,
    _forced_4n1,
    _clip_fps,
    _hold_frame2_over_1,
    _chunk_plates,
    _explode,
    _keyframe_plates,
    run_video_vace,
    run_video_animate,
    _next_take,
    run_composite,
)
from zyg_workflows.scene_shot_run.runner import (
    identity_facts,
    licence_facts,
    _read_json,
    _sizes,
    run,
    main,
)
