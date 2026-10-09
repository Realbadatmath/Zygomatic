# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finishing steps of `stage_05_assembly`: card, trim, master, thumbnail.

The second half of the 604-line stage, dedent-only out of
`pipeline_video._run_video_pipeline`'s assembly tail: the ending title card,
the duration trim against WAN's natural length, the 4K master encode, the
thumbnail pick and the prop-persistence advisory. The first half — the two
colour passes, the ffmpeg concat and the background-music mix — is in
`stage_05_assembly_steps`.

Same contract as that module: one-way imports (`bin` only), no caller globals,
every value a parameter, and parameters named with a leading underscore are the
monolith's own local names, kept so the moved bodies stay verbatim. The
`_seal.seal` hook is deliberately NOT here — it stays in `stage_05_assembly`,
where `scripts/check_seal_hooks.py` asserts it by file and function name.
"""

import os

from zyg_workflows.bin import exe

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')


# ── Ending title card ───────────────────────────────────────────────────────


def _title_card_vf(_ending_text):
    """The drawtext + fade filtergraph for the studio card.

    *_ending_text* is escaped for ffmpeg's filter syntax: backslashes become
    slashes, apostrophes and colons are backslash-escaped.
    """
    _safe_et = _ending_text.replace('\\', '/').replace("'", "\\'").replace(':', '\\:')
    return (
        f"drawtext=text='{_safe_et}':fontcolor=white:fontsize=48"
        ':x=(w-text_w)/2:y=(h-text_h)/2,'
        'fade=type=in:start_time=0:duration=0.5,'
        'fade=type=out:start_time=2.5:duration=0.5'
    )


def _render_title_card(_sp_video, _card_path, _vf_title):
    """Render the 3-second black card with silent stereo audio to *_card_path*.

    Returns the completed ffmpeg process, so the caller can read both its
    return code and its stderr tail.
    """
    return _sp_video.run(
        [
            exe('ffmpeg'),
            '-y',
            '-f',
            'lavfi',
            '-i',
            'color=c=black:s=1920x1080:r=30:d=3',
            '-f',
            'lavfi',
            '-i',
            'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-t',
            '3',
            '-vf',
            _vf_title,
            '-c:v',
            'libx264',
            '-preset',
            'ultrafast',
            '-crf',
            '0',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-pix_fmt',
            'yuv420p',
            _card_path,
        ],
        capture_output=True,
        timeout=60,
    )


def _main_video_has_audio(_sp_video, final_path):
    """True when *final_path* carries at least one audio stream."""
    _has_aud_r = _sp_video.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'a',
            '-show_entries',
            'stream=codec_type',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            final_path,
        ],
        capture_output=True,
        timeout=10,
    )
    return bool((_has_aud_r.stdout or b'').strip())


def _concat_title_card(_sp_video, out_dir, final_path, _card_path, _titled_path, _main_has_audio):
    """Append *_card_path* to *final_path*, writing *_titled_path*.

    With audio on the main video the two go through `filter_complex` so the
    audio tracks concatenate too; without it, through a demuxer list file
    (`concat_title.txt`), which is the only form that works when one input has
    no audio stream at all. Returns the completed ffmpeg process.
    """
    if _main_has_audio:
        return _sp_video.run(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                final_path,
                '-i',
                _card_path,
                '-filter_complex',
                '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]',
                '-map',
                '[outv]',
                '-map',
                '[outa]',
                '-c:v',
                'libx264',
                '-preset',
                'ultrafast',
                '-crf',
                '0',
                '-pix_fmt',
                'yuv420p',
                '-c:a',
                'aac',
                '-b:a',
                '192k',
                '-movflags',
                '+faststart',
                _titled_path,
            ],
            capture_output=True,
            timeout=300,
        )
    _concat_et_txt = os.path.join(out_dir, 'concat_title.txt')
    with open(_concat_et_txt, 'w') as _cf_et:
        _cf_et.write(f"file '{final_path}'\nfile '{_card_path}'\n")
    return _sp_video.run(
        [
            exe('ffmpeg'),
            '-y',
            '-f',
            'concat',
            '-safe',
            '0',
            '-i',
            _concat_et_txt,
            '-c:v',
            'libx264',
            '-preset',
            'ultrafast',
            '-crf',
            '0',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            _titled_path,
        ],
        capture_output=True,
        timeout=300,
    )


def append_ending_card(_ending_text, final_path, out_dir, pipeline_id, _sp_video, _log, _set_stage, _complete_stage):
    """Append the studio ending card to *final_path*, in place.

    Renders the card, concatenates it onto the video and moves the result over
    *final_path*, then removes the card scratch file. A failed render or concat
    logs a warning and leaves the video untouched; either way the stage is
    completed, unless the step raised — then only the warning is logged, which
    is what the monolith did.
    """
    _set_stage('Ending Title Card')
    _log('INFO', 'Ending Title Card', f'Appending studio card: "{_ending_text}"')
    try:
        _card_path = os.path.join(out_dir, f'title_card_{pipeline_id[:8]}.mp4')
        _tc_r = _render_title_card(_sp_video, _card_path, _title_card_vf(_ending_text))
        if _tc_r.returncode == 0 and os.path.exists(_card_path) and os.path.getsize(_card_path) > 1000:
            _titled_path = final_path.replace('.mp4', '_titled.mp4')
            _has_audio = _main_video_has_audio(_sp_video, final_path)
            _cat_r = _concat_title_card(_sp_video, out_dir, final_path, _card_path, _titled_path, _has_audio)
            if _cat_r.returncode == 0 and os.path.exists(_titled_path) and os.path.getsize(_titled_path) > 10000:
                import shutil as _shu_title

                _shu_title.move(_titled_path, final_path)
                _log('INFO', 'Ending Title Card', f'Studio card appended: "{_ending_text}"')
                try:
                    os.remove(_card_path)
                except OSError as _exc:
                    _zyg_log.debug('title card scratch file cleanup skipped: %s', _exc)
            else:
                _err_tc = (_cat_r.stderr or b'').decode('utf-8', errors='replace')[-300:]
                _log('WARNING', 'Ending Title Card', f'Concat failed — video unchanged: {_err_tc}')
        else:
            _err_tc = (_tc_r.stderr or b'').decode('utf-8', errors='replace')[-200:]
            _log('WARNING', 'Ending Title Card', f'Render failed — video unchanged: {_err_tc}')
        _complete_stage('Ending Title Card')
    except Exception as _tc_e:
        _log('WARNING', 'Ending Title Card', f'Title card error: {_tc_e}')


# ── Duration trim and the 4K master ─────────────────────────────────────────


def _probe_duration(_sp_video, final_path):
    """The container duration of *final_path* in seconds; 0.0 when ffprobe says nothing."""
    _probe = _sp_video.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            final_path,
        ],
        capture_output=True,
        timeout=15,
    )
    return float((_probe.stdout or b'0').decode().strip() or '0')


def trim_to_target(_target_total_sec, scene_duration, n_scenes, final_path, _sp_video, _log):
    """Trim *final_path* down to WAN's natural length when it overshoots.

    `wan_video_service.final_trim_target_sec` decides the target; a video
    already at or below it (within 0.25 s) is left alone, so a 3.8 s assembly is
    never cut back to a requested 3.5 s. The trimmed file replaces *final_path*
    in place; any error logs one warning and changes nothing.
    """
    try:
        from zyg_workflows import wan_video_service as _wan_trim

        _trim_to = _wan_trim.final_trim_target_sec(
            _target_total_sec,
            scene_duration,
            n_scenes,
        )
        if _trim_to > 0 and os.path.exists(final_path):
            _cur_dur = _probe_duration(_sp_video, final_path)
            if _cur_dur > _trim_to + 0.25:
                _trimmed = final_path.replace('.mp4', '_trim.mp4')
                _tr = _sp_video.run(
                    [
                        exe('ffmpeg'),
                        '-y',
                        '-i',
                        final_path,
                        '-t',
                        str(_trim_to),
                        '-c:v',
                        'libx264',
                        '-preset',
                        'ultrafast',
                        '-crf',
                        '0',
                        '-pix_fmt',
                        'yuv420p',
                        '-c:a',
                        'copy',
                        '-movflags',
                        '+faststart',
                        _trimmed,
                    ],
                    capture_output=True,
                    timeout=300,
                )
                if _tr.returncode == 0 and os.path.getsize(_trimmed) > 10000:
                    import shutil as _shu_trim

                    _shu_trim.move(_trimmed, final_path)
                    _log(
                        'INFO',
                        'Stage 5',
                        f'Trimmed final video to {_trim_to:.2f}s (was {_cur_dur:.2f}s; '
                        f'requested {_target_total_sec:.1f}s)',
                    )
    except Exception as _trim_e:
        _log('WARNING', 'Stage 5', f'Duration trim skipped: {_trim_e}')


def encode_master(final_path, tts_duration, _sp_video, _log):
    """The one lossy pass: 4K lanczos upscale, x264 slow/CRF15, AAC 192k.

    Replaces *final_path* with the master when the encode produced a file over
    10 kB; otherwise logs a warning, deletes the partial master and keeps the
    lossless concat source, so a failed encode never costs the render.
    """
    _log('INFO', 'Stage 6', 'Final encode: 4K upscale + slow/CRF15 for YouTube…')
    _master_path = final_path.replace('.mp4', '_master.mp4')
    _master_r = _sp_video.run(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            final_path,
            '-vf',
            'scale=3840:2160:flags=lanczos',
            '-c:v',
            'libx264',
            '-preset',
            'slow',
            '-crf',
            '15',
            '-pix_fmt',
            'yuv420p',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-movflags',
            '+faststart',
            _master_path,
        ],
        capture_output=True,
        timeout=int(tts_duration * 8 + 600),
    )
    if _master_r.returncode == 0 and os.path.exists(_master_path) and os.path.getsize(_master_path) > 10000:
        import shutil as _shu_master

        _shu_master.move(_master_path, final_path)
        _log(
            'INFO',
            'Stage 6',
            f'Master ready: 3840×2160 slow/CRF15 — {os.path.getsize(final_path) // 1024 // 1024} MB',
        )
    else:
        _err_m = (_master_r.stderr or b'').decode(errors='replace')[-300:]
        _log('WARNING', 'Stage 6', f'4K encode failed — keeping lossless source: {_err_m}')
        try:
            if os.path.exists(_master_path):
                os.remove(_master_path)
        except OSError as _exc:
            _zyg_log.debug('failed 4K master cleanup skipped: %s', _exc)


# ── Thumbnail and the prop-persistence advisory ─────────────────────────────


def save_thumbnail(out_dir, scene_images, _log):
    """Write `_thumbnail.jpg` under *out_dir* from the richest scene still.

    The richest still is the largest file over 50 kB, falling back to the
    largest that exists at all; it is fitted into 1280×720 and letterboxed on
    black. An existing thumbnail, an empty *scene_images* or any error leaves
    the directory alone.
    """
    try:
        _thumb_dst = os.path.join(out_dir, '_thumbnail.jpg')
        if not os.path.exists(_thumb_dst) and scene_images:
            from PIL import Image as _PILImg

            _valid = [p for p in scene_images if os.path.exists(p) and os.path.getsize(p) > 50_000]
            if not _valid:
                _valid = [p for p in scene_images if os.path.exists(p)]
            if _valid:
                _best = max(_valid, key=os.path.getsize)
                with _PILImg.open(_best) as _im:
                    _im = _im.convert('RGB')
                    _im.thumbnail((1280, 720), _PILImg.LANCZOS)
                    _canvas = _PILImg.new('RGB', (1280, 720), (0, 0, 0))
                    _canvas.paste(_im, ((1280 - _im.width) // 2, (720 - _im.height) // 2))
                    _canvas.save(_thumb_dst, 'JPEG', quality=92)
                _log('INFO', 'Thumbnail', f'Saved _thumbnail.jpg from {os.path.basename(_best)}')
    except Exception as _th_e:
        _log('WARNING', 'Thumbnail', f'Thumbnail generation skipped: {_th_e}')


def report_prop_persistence(job, _log):
    """Append the advisory for planned props that were not visible across their clip.

    Reads `job['_prop_persistence']`, lists the non-persistent props per scene in
    scene-key order and appends one note to `job['warnings']` plus one WARNING
    log line. Non-fatal by design: nothing here can fail the render.
    """
    try:
        _pp_all = job.get('_prop_persistence') or {}
        _pp_bad_bits = []
        for _si in sorted(_pp_all):
            _pe = _pp_all.get(_si) or {}
            _pp_bad = [_ph for _ph, _pd in (_pe.get('verdicts') or {}).items() if not _pd.get('persistent')]
            if _pp_bad:
                _pp_bad_bits.append(f'scene {int(_si) + 1}: {", ".join(_pp_bad)}')
        if _pp_bad_bits:
            _pp_note = (
                '⚠️ ADVISORY: prop persistence below threshold — '
                + '; '.join(_pp_bad_bits)
                + ' — planned prop(s) not visible across the clip (non-fatal, video kept).'
            )
            job.setdefault('warnings', []).append(_pp_note)
            _log('WARNING', 'Stage 6', _pp_note)
    except Exception as _pp_rep_e:
        _log('WARNING', 'Stage 6', f'Prop-persistence report aggregation failed: {_pp_rep_e}')
