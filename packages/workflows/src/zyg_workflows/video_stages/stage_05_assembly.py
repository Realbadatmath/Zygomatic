# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 5/6 of the video pipeline: assembly, music, ending card, master.

Lines 2403-2992 of `pipeline_video._run_video_pipeline` at 770c30a, verbatim:
the Foley timeline entry, the colour-consistency normalisation, the ffmpeg
concat, the background-music mix, the ending-text card, the duration trim, the
4K master encode, the C2PA seal, the thumbnail, the prop-persistence report and
the job's `completed` record.

The `provenance_seal` call lives here now, so `tests/test_egress_seal.py` names
this module and `stage_05_assembly` in its DELIVERY table.

2026-10-09: the 604-line stage moved into two sibling modules, one function per
phase — `stage_05_assembly_steps` (the colour passes, the concat, the music
mix) and `stage_05_assembly_finish` (the ending card, the trim, the master
encode, the thumbnail, the prop advisory). What is left here is the order, the
stage bookkeeping, the seal hook and the job record; nothing it does changed.
"""

import os

from zyg_workflows import provenance_seal as _seal
from zyg_workflows.pipeline_common import _cleanup_pipeline_output
from zyg_workflows.runtime import _ams_iso, _bm_record_pipeline
from zyg_workflows.stage_runner import _scp_output_to_windows

from zyg_workflows.video_stages import stage_05_assembly_finish as _finish
from zyg_workflows.video_stages import stage_05_assembly_steps as _steps
from zyg_workflows.video_stages.context import StageExit


def stage_05_assembly(ctx):
    """Assemble the graded clips into the delivered 4K master and close the job.

    Runs the tail of the video pipeline in order: the Foley timeline entry, the
    two colour passes, the ffmpeg concat, the background-music mix, the ending
    title card, the duration trim, the 4K master encode, the content
    credential, the thumbnail and the prop-persistence advisory; then marks the
    job `completed`, cleans the output directory and ships it. Returns a
    `StageExit` when there was nothing to assemble or the concat failed, else
    None. Every step is a function in `stage_05_assembly_steps`.
    """
    _audio_svc = ctx._audio_svc
    _claude_music_mood = ctx._claude_music_mood
    _complete_stage = ctx._complete_stage
    _fail_stage = ctx._fail_stage
    _log = ctx._log
    _set_stage = ctx._set_stage
    _sp_video = ctx._sp_video
    _target_total_sec = ctx._target_total_sec
    clip_paths = ctx.clip_paths
    ending_text = ctx.ending_text
    good_clips = ctx.good_clips
    job = ctx.job
    n_scenes = ctx.n_scenes
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    scene_duration = ctx.scene_duration
    scene_images = ctx.scene_images
    scenes = ctx.scenes
    topic = ctx.topic
    tts_duration = ctx.tts_duration
    visual_style = ctx.visual_style
    # ── Foley SFX — register in timeline (ran per-clip inside Stage 4) ────
    _set_stage('Foley SFX')
    _foley_total = sum(1 for c in clip_paths if c and 'foley' in c)
    _log('INFO', 'Foley SFX', f'Foley SFX applied to {_foley_total}/{n_scenes} clips')
    _complete_stage('Foley SFX')

    # ── Stage 5: Concat assembly ─────────────────────────────────────────
    _set_stage('Video Assembly')
    _log('INFO', 'Stage 5', 'Assembling final video…')

    if not good_clips:
        _fail_stage('Video Assembly', 'No clips were produced — cannot assemble video')
        job['status'] = 'failed'
        return StageExit()

    # Colour consistency against clip 0, then the cinematic LUT + sharpening
    good_clips = _steps.color_passes(good_clips, visual_style, pipeline_id, _log)

    final_path, _concat_err = _steps.concat_clips(_sp_video, out_dir, pipeline_id, good_clips)
    if _concat_err is not None:
        _fail_stage('Video Assembly', f'ffmpeg concat failed: {_concat_err}')
        job['status'] = 'failed'
        return StageExit()

    _complete_stage('Video Assembly')
    dur_min = len(good_clips) * scene_duration // 60
    _log('INFO', 'Stage 5', f'Final video assembled: {final_path} (~{dur_min} min)')

    # ── Stage 5b: Background Music mixing ────────────────────────────────
    _enable_bgm = bool((job.get('pipeline_options') or {}).get('enable_bgm', True))
    if _audio_svc and _enable_bgm:
        _set_stage('Background Music')
        _steps.mix_background_music(
            _audio_svc,
            topic,
            scenes,
            n_scenes,
            scene_duration,
            out_dir,
            pipeline_id,
            final_path,
            _claude_music_mood,
            _log,
            _complete_stage,
        )
    elif not _enable_bgm:
        _log('INFO', 'Stage 5b', 'Background music disabled (pipeline_options) — skipping')

    # ── Ending title card (intro mode) ─────────────────────────────────────
    _ending_text = (ending_text or job.get('ending_text', '')).strip()
    if _ending_text:
        _finish.append_ending_card(
            _ending_text, final_path, out_dir, pipeline_id, _sp_video, _log, _set_stage, _complete_stage
        )

    # Trim only when assembled runtime exceeds WAN-natural length (never 3.8→3.5)
    _finish.trim_to_target(_target_total_sec, scene_duration, n_scenes, final_path, _sp_video, _log)

    # ── Final quality encode: 4K upscale + slow/CRF15 (single lossy pass) ─
    _finish.encode_master(final_path, tts_duration, _sp_video, _log)

    # ── Content credential: the master, after the last encode ────────────
    # The 4K pass above is the last thing that rewrites final_path, so the
    # bytes are final here and the C2PA manifest signs what ships. Fail-safe:
    # no key means a logged line and an untouched file, never a failed render.
    _seal.seal(
        final_path,
        pipeline='video',
        run_id=pipeline_id,
        title=os.path.basename(final_path),
        log_fn=lambda m: _log('INFO', 'Content Credential', m),
    )

    # ── Thumbnail: pick richest scene image → 1280×720 JPEG ──────────────
    _finish.save_thumbnail(out_dir, scene_images, _log)

    # ── ADVISORY: prop-persistence run report (non-fatal, never blocks) ──
    _finish.report_prop_persistence(job, _log)

    job['status'] = 'completed'
    job['result'] = final_path
    job['output_files'] = [final_path]
    job['final_output_file'] = final_path
    job['completed_at'] = _ams_iso()
    _bm_record_pipeline(job)
    _cleanup_pipeline_output(
        out_dir,
        final_path,
        log_fn=lambda m: _log('INFO', 'Cleanup', m),
    )
    _scp_output_to_windows(out_dir, pipeline_id)
