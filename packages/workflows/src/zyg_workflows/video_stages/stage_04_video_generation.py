# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4 of the video pipeline: a video clip per scene.

Driver lines 193-1416 of `pipeline_video._run_video_pipeline` at d443b3b. The
three big blocks it held are now three functions in three sibling modules and
this one is the skeleton that calls them in the order the monolith ran them:

| driver lines | function | module |
| --- | --- | --- |
| 193-209 | the `clips_dir` setup and the manga branch | here, verbatim |
| 213-379 | `prepare_vram_and_services` | `stage_04_vram_prep` |
| 381-1000 | `generate_wan_clips` | `stage_04_wan_generate` |
| 1002-1412 | `mux_clips` | `stage_04_clip_mux` |
| 1414-1416 | the stage card and `good_clips` | here, verbatim |

In manga mode neither of the first two run, so `wan_by_idx`, `_audio_svc` and
`_json_v` keep the values the setup lines gave them — `{}`, whatever the manga
branch's `audio_service` import left, and `json`. `clip_paths` is built here
and handed to `mux_clips`, which appends to it in place.

The three products Stage 5 reads are published on the context at the end, which
is where the driver published them while this block was still inline.
"""

import os

from zyg_workflows.video_stages.stage_04_clip_mux import mux_clips
from zyg_workflows.video_stages.stage_04_vram_prep import prepare_vram_and_services
from zyg_workflows.video_stages.stage_04_wan_generate import generate_wan_clips


def stage_04_video_generation(ctx):
    _complete_stage = ctx._complete_stage
    _log = ctx._log
    _manga_mode = ctx._manga_mode
    _set_stage = ctx._set_stage
    n_scenes = ctx.n_scenes
    out_dir = ctx.out_dir
    clips_dir = os.path.join(out_dir, 'clips')
    os.makedirs(clips_dir, exist_ok=True)
    clip_paths = []
    wan_by_idx = {}
    _audio_svc = None
    import json as _json_v

    if _manga_mode:
        _set_stage('Panel Animation')
        _log('INFO', 'Stage 4', f'Manga: Ken Burns / hold for {n_scenes} panels (WAN skipped)')
        try:
            from zyg_workflows import audio_service as _audio_svc

            _log('INFO', 'Stage 4', 'Audio service loaded (foley SFX + BGM enabled)')
        except ImportError as _asvc_e:
            _log('WARNING', 'Stage 4', f'audio_service unavailable: {_asvc_e}')
        _complete_stage('Panel Animation')
    if not _manga_mode:
        # ── Stage 4: WAN Video Generation + Subtitle Burn ────────────────────
        (
            _wan_svc,
            _audio_svc,
            _json_v,
            _wan_n_chained,
            _wan_test_frames,
            _wan_test_steps,
        ) = prepare_vram_and_services(ctx)
        wan_by_idx = generate_wan_clips(ctx, _wan_svc, _wan_n_chained, _wan_test_frames, _wan_test_steps)

    mux_clips(ctx, clips_dir, clip_paths, wan_by_idx, _audio_svc, _json_v)

    _complete_stage('Video Generation')
    good_clips = [c for c in clip_paths if c and os.path.exists(c)]
    _log('INFO', 'Stage 4', f'{len(good_clips)}/{n_scenes} clips ready')

    # The three Stage 4 products Stage 5 reads.
    ctx.clip_paths = clip_paths
    ctx.good_clips = good_clips
    ctx._audio_svc = _audio_svc
