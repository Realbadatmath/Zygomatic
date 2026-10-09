# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The assembly steps of `stage_05_assembly`: colour, concat, background music.

`stage_05_assembly` was 604 lines — the whole assembly tail of
`pipeline_video._run_video_pipeline` in one def, with two nested closures. The
first half moved here, dedent-only: the colour-consistency normalisation, the
cinematic grade, the ffmpeg concat and the background-music mix. The finishing
half (ending card, duration trim, 4K master, thumbnail, prop advisory) is in
`stage_05_assembly_finish`. Both closures (`_clip_mean_rgb`, `_bgm_emotion`)
are module-level functions now and take what they used to read from the
enclosing scope as parameters.

The orchestrator in `stage_05_assembly` keeps the ORDER, the stage bookkeeping
(`_set_stage` / `_complete_stage` / `_fail_stage`), the `_seal.seal` hook that
`scripts/check_seal_hooks.py` and `tests/test_egress_seal.py` assert by file and
function name, and the job's `completed` record.

Nothing here reads a caller global: every value arrives as a parameter, so each
step is callable on plain inputs — which is what
`tests/test_stage_05_assembly_helpers.py` does with a stub runner and no
ffmpeg, no GPU and no services.

The import direction is one-way: this module imports `bin` and `color_grade`
only, and `stage_05_assembly` imports this module. Parameters named with a
leading underscore are the monolith's own local names, kept so the moved bodies
stay verbatim.
"""

import os

from zyg_workflows.bin import exe
from zyg_workflows.color_grade import _apply_color_grade

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')


# ── Colour: consistency normalisation, then the cinematic grade ──────────────


def _clip_mean_rgb(cp, _sp_cc, _io_cc, _np_cc, _PIL_cc):
    """Mean RGB of clip *cp*, averaged over frames at 10 %, 50 % and 90 %.

    *_sp_cc*, *_io_cc*, *_np_cc* and *_PIL_cc* are the `subprocess`, `io`,
    `numpy` and `PIL.Image` modules the caller imported lazily — passed in so
    this stays a plain function with no hidden imports. Returns a length-3
    array; a clip whose three sample frames are all undecodable reads as
    mid-grey (128, 128, 128).
    """
    probe = _sp_cc.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=nb_frames',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            cp,
        ],
        capture_output=True,
        timeout=10,
    )
    n = int((probe.stdout.decode().strip() or '30').split()[0])
    # Sample 3 frames (10%, 50%, 90%) and average for a
    # representative color estimate across the full clip
    samples = []
    for frac in (0.10, 0.50, 0.90):
        fi = max(0, min(n - 1, int(n * frac)))
        ff = _sp_cc.run(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                cp,
                '-vf',
                f'select=eq(n\\,{fi})',
                '-vframes',
                '1',
                '-f',
                'image2pipe',
                '-vcodec',
                'png',
                '-',
            ],
            capture_output=True,
            timeout=30,
        )
        if ff.stdout:
            try:
                img = _PIL_cc.open(_io_cc.BytesIO(ff.stdout)).convert('RGB')
                samples.append(_np_cc.array(img, dtype=float).mean(axis=(0, 1)))
            except Exception as _exc:
                _zyg_log.debug('colour sample frame undecodable, skipped: %s', _exc)
    if not samples:
        return _np_cc.array([128.0, 128.0, 128.0])
    return _np_cc.array(samples).mean(axis=0)


def _channel_gains(_ref_rgb, _cm):
    """Per-channel multipliers that pull mean RGB *_cm* onto reference *_ref_rgb*.

    Clamped to [0.70, 1.30]; a channel whose clip mean is 2.0 or darker stays at
    1.0 rather than being amplified out of the noise floor.
    """
    return [max(0.70, min(1.30, _ref_rgb[c] / _cm[c])) if _cm[c] > 2.0 else 1.0 for c in range(3)]


def _normalize_clip_colors(good_clips, _log):
    """Colour-normalise every clip after the first onto clip 0's mean RGB.

    Returns the list to concat: clip 0, then per later clip either the
    `colorchannelmixer` copy (when the correction was worth making and the
    encode produced a file over 1 kB) or the clip itself. Any failure logs one
    warning and returns *good_clips* unchanged.
    """
    try:
        import io as _io_cc
        import numpy as _np_cc
        from PIL import Image as _PIL_cc
        import subprocess as _sp_cc

        _ref_rgb = _clip_mean_rgb(good_clips[0], _sp_cc, _io_cc, _np_cc, _PIL_cc)
        _cc_clips = [good_clips[0]]
        for _cc_i, _cc_p in enumerate(good_clips[1:], 1):
            _cm = _clip_mean_rgb(_cc_p, _sp_cc, _io_cc, _np_cc, _PIL_cc)
            _adj = _channel_gains(_ref_rgb, _cm)
            # Skip if deviation is negligible (< 3%)
            if max(abs(a - 1.0) for a in _adj) < 0.03:
                _cc_clips.append(_cc_p)
                continue
            _cc_out = _cc_p.replace('.mp4', '_cc.mp4')
            _cc_vf = f'colorchannelmixer=rr={_adj[0]:.3f}:gg={_adj[1]:.3f}:bb={_adj[2]:.3f}'
            _sp_cc.run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-i',
                    _cc_p,
                    '-vf',
                    _cc_vf,
                    '-c:v',
                    'libx264',
                    '-preset',
                    'ultrafast',
                    '-crf',
                    '0',
                    '-c:a',
                    'copy',
                    _cc_out,
                ],
                capture_output=True,
                timeout=300,
            )
            if os.path.exists(_cc_out) and os.path.getsize(_cc_out) > 1000:
                _cc_clips.append(_cc_out)
                _log(
                    'INFO',
                    'Stage 5',
                    f'Color normalized clip {_cc_i}: R×{_adj[0]:.2f} G×{_adj[1]:.2f} B×{_adj[2]:.2f}',
                )
            else:
                _cc_clips.append(_cc_p)
        return _cc_clips
    except Exception as _cc_e:
        _log('WARNING', 'Stage 5', f'Color consistency pass skipped: {_cc_e}')
        return good_clips


def _cinematic_grade(good_clips, visual_style, pipeline_id, _log):
    """Apply the *visual_style* LUT plus unsharp to every clip.

    Returns the graded paths — `_apply_color_grade` returns its input unchanged
    when it had nothing to do, so the count of actually graded clips is the
    number of entries that differ. Any failure logs one warning and returns
    *good_clips* unchanged.
    """
    try:
        _graded_clips = []
        for _gc_path in good_clips:
            _gout = _apply_color_grade(
                _gc_path,
                visual_style,
                pipeline_id,
                log_fn=lambda m: _log('INFO', 'Stage 5', m),
            )
            _graded_clips.append(_gout)
        _n_graded = sum(1 for a, b in zip(good_clips, _graded_clips) if a != b)
        if _n_graded:
            _log(
                'INFO',
                'Stage 5',
                f'Cinematic grade applied ({visual_style} LUT + unsharp) to {_n_graded}/{len(good_clips)} clips',
            )
        return _graded_clips
    except Exception as _cg_e:
        _log('WARNING', 'Stage 5', f'Color grade pass skipped: {_cg_e}')
        return good_clips


def color_passes(good_clips, visual_style, pipeline_id, _log):
    """Both colour passes in order: consistency normalisation, then the grade.

    Returns the clip list the concat should use. A single clip skips the
    normalisation entirely, exactly as the monolith did.
    """
    if len(good_clips) > 1:
        good_clips = _normalize_clip_colors(good_clips, _log)
    return _cinematic_grade(good_clips, visual_style, pipeline_id, _log)


# ── Concat assembly ─────────────────────────────────────────────────────────


def concat_clips(_sp_video, out_dir, pipeline_id, good_clips):
    """Stream-copy concat of *good_clips* into `video_<id>.mp4` under *out_dir*.

    Writes the demuxer list as `concat.txt` beside it. Returns
    `(final_path, None)` on success, or `(final_path, stderr_tail)` when ffmpeg
    failed or the output is missing or under 10 kB — the caller turns that tail
    into the failed stage, so the message stays the monolith's.
    """
    concat_list = os.path.join(out_dir, 'concat.txt')
    with open(concat_list, 'w') as _cl:
        for _cp in good_clips:
            _cl.write(f"file '{_cp}'\n")

    final_path = os.path.join(out_dir, f'video_{pipeline_id[:12]}.mp4')
    _r = _sp_video.run(
        [
            exe('ffmpeg'),
            '-y',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            concat_list,
            '-c:v',
            'copy',
            '-c:a',
            'copy',
            '-movflags',
            '+faststart',
            final_path,
        ],
        capture_output=True,
        timeout=600,
    )
    if _r.returncode != 0 or not os.path.exists(final_path) or os.path.getsize(final_path) < 10000:
        return final_path, (_r.stderr or b'').decode('utf-8', errors='replace')[-800:]
    return final_path, None


# ── Stage 5b: background music ──────────────────────────────────────────────


def _bgm_emotion(desc: str) -> str:
    """The dominant emotion of the joined scene descriptions, for the music mood.

    First keyword family that matches wins, in this order: anger, triumph, awe,
    grief, tension; nothing matching is `'neutral'`.
    """
    d = desc.lower()
    if any(k in d for k in ['fight', 'battle', 'combat', 'clash', 'charge', 'attack', 'blood', 'brutal']):
        return 'anger'
    if any(k in d for k in ['victori', 'triumph', 'raised', 'conquer', 'standing atop', 'standing victorious']):
        return 'triumph'
    if any(k in d for k in ['sunset', 'vast', 'sweeping', 'panoram', 'landscape', 'vista', 'mountain', 'coast']):
        return 'awe'
    if any(k in d for k in ['death', 'fallen', 'dead', 'grief', 'mour', 'despair', 'tragic']):
        return 'grief'
    if any(k in d for k in ['tense', 'siege', 'surround', 'standoff', 'face off']):
        return 'tension'
    return 'neutral'


def mix_background_music(
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
):
    """Pick a music track for the run's dominant emotion and mix it into *final_path*.

    The mixed file replaces *final_path* in place when the mix succeeded; a
    missing track or any error logs a warning and leaves the video alone.
    Completes the stage and then unloads ACE-Step, in that order — the unload is
    belt-and-braces, the ComfyUI submit path already evicts the checkpoint.
    """
    _log('INFO', 'Stage 5b', 'Selecting background music track…')
    try:
        # Derive dominant emotion across all scenes for music mood
        _all_descs = ' '.join(sc.get('description', '') for sc in scenes)
        _dominant_emotion = _bgm_emotion(_all_descs)
        _video_duration_s = int(n_scenes * scene_duration)
        _music_path = _audio_svc.get_music_for_topic(
            topic,
            _dominant_emotion,
            out_dir=os.path.join(out_dir, 'music'),
            duration_s=_video_duration_s,
            music_mood=_claude_music_mood,
            log_fn=lambda m: _log('INFO', 'Stage 5b', m),
        )
        if _music_path:
            _final_with_music = os.path.join(out_dir, f'video_{pipeline_id[:12]}_bgm.mp4')
            _bgm_ok = _audio_svc.mix_bgm_into_video(
                final_path,
                _music_path,
                _final_with_music,
                music_vol=0.12,
                log_fn=lambda m: _log('INFO', 'Stage 5b', m),
            )
            if _bgm_ok:
                # Replace final_path with the BGM version
                import shutil as _shutil_bgm

                _shutil_bgm.move(_final_with_music, final_path)
                _log(
                    'INFO',
                    'Stage 5b',
                    f'BGM mixed in — mood: {_claude_music_mood or _audio_svc._pick_mood(topic, _dominant_emotion)}, '
                    f'track: {os.path.basename(_music_path)}',
                )
            else:
                _log('WARNING', 'Stage 5b', 'BGM mix failed — video without background music')
        else:
            _log('WARNING', 'Stage 5b', 'No music track available (all tiers failed) — skipping BGM')
    except Exception as _bgm_e:
        _log('WARNING', 'Stage 5b', f'BGM step error: {_bgm_e} — skipping')
    _complete_stage('Background Music')
    # Explicit ACE-Step VRAM release — the ComfyUI submit path already
    # evicts the checkpoint after each job, but this is a belt-and-
    # suspenders guarantee that VRAM is fully clear before exit.
    try:
        from zyg_workflows import ace_step_service as _ace_end

        _ace_end.unload()
        _log('INFO', 'Stage 5b', 'ACE-Step unloaded — VRAM freed for next run')
    except Exception as _exc:
        _zyg_log.debug('ACE-Step unload skipped: %s', _exc)
