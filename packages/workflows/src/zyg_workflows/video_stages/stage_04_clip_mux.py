# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4, step 3: one deliverable clip per scene, muxed to its narration.

Driver lines 1002-1412 of `pipeline_video._run_video_pipeline` at d443b3b,
verbatim: the whole `for _ci in range(n_scenes):` loop — the ffprobe TTS
duration measurement, the WAN clip trim / smart loop (with the cross-fade and
ping-pong variants), the Ken Burns static fallback, the audio mux and the foley
mix, both with and without narration.

`clip_paths` is a parameter and is only ever appended to, so the caller's list
is the one that grows; the loop's `continue` statements stay inside the loop
they belong to, which moved whole.

2026-10-09: the 420-line loop body moved into `stage_04_clip_mux_build`, one
function per step (probe, trim/loop, Ken Burns fallback, foley, mux). This
module keeps the loop and the order; nothing it does changed.
"""

import os

from zyg_workflows.video_stages import stage_04_clip_mux_build as _build


def mux_clips(ctx, clips_dir, clip_paths, wan_by_idx, _audio_svc, _json_v):
    """One deliverable clip per scene, in scene order, appended to *clip_paths*.

    Each scene appends exactly one entry: the muxed clip, the video-only clip
    when the mux failed, or None when the scene had neither a WAN clip nor a
    usable still. Every step is a function in `stage_04_clip_mux_build`; the
    only thing left here is the order they run in.
    """
    _log = ctx._log
    _manga_mode = ctx._manga_mode
    _sp_video = ctx._sp_video
    job = ctx.job
    n_scenes = ctx.n_scenes
    scene_duration = ctx.scene_duration
    scene_images = ctx.scene_images
    scenes = ctx.scenes
    tts_dir = ctx.tts_dir
    tts_files = ctx.tts_files
    for _ci in range(n_scenes):
        _tts = tts_files[_ci] if _ci < len(tts_files) else None
        _scene_meta = scenes[_ci] if _ci < len(scenes) else {}

        # Measure actual TTS duration
        _tts_dur = _build.measure_tts_duration(_sp_video, _json_v, _tts, float(scene_duration))

        # WAN clip → trim or smart-loop to fill TTS duration; fallback to static image
        wan_clip = wan_by_idx.get(_ci)
        video_src = None
        if wan_clip and os.path.exists(wan_clip):
            video_src = _build.build_looped_clip(_sp_video, clips_dir, _ci, wan_clip, _tts_dur, _scene_meta)

        if not video_src:
            _img = scene_images[_ci] if _ci < len(scene_images) else None
            if _img and os.path.exists(_img):
                video_src = _build.build_static_clip(
                    _sp_video, clips_dir, _ci, _img, _tts_dur, _scene_meta, job, _manga_mode
                )

        if not video_src:
            _log('WARNING', 'Stage 4', f'No video source for scene {_ci} — skipping')
            clip_paths.append(None)
            continue

        # Subtitles are generated at final assembly stage (_burn_subtitles), not per scene clip

        # Mux with TTS audio + foley SFX (audio drives duration via -shortest)
        _scene_desc = scenes[_ci].get('description', '') if _ci < len(scenes) else ''
        if _tts and os.path.exists(_tts):
            _audio = _build.foley_over_narration(_audio_svc, _scene_desc, _tts, _tts_dur, tts_dir, _ci, _log)
            clip_paths.append(_build.mux_narrated_clip(_sp_video, clips_dir, _ci, video_src, _audio, _log))
        else:
            # No TTS narration — apply foley directly into video audio track
            _foley = _build.foley_only_clip(_audio_svc, clips_dir, _ci, video_src, _scene_desc, _tts_dur, _log)
            clip_paths.append(_foley if _foley else video_src)
        _log('INFO', 'Stage 4', f'Clip {_ci + 1}/{n_scenes} ready')
