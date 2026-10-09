# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stages 4.6, 4.7 and 5 — colour grade, book intro and the subtitle burn-in."""

from ._common import (
    _ams_iso,
    _apply_color_grade,
    _bm_record_pipeline,
    _burn_subtitles,
    _cleanup_pipeline_output,
    _cq_for_crf,
    _ffmpeg_run_nvenc_first,
    _make_book_intro,
    _nvenc_vcodec_args,
    _parse_iso_to_ams,
    _scp_output_to_windows,
    _seal,
    _update_marker,
    _x264_vcodec_args,
    _zyg_log,
    exe,
    os,
)


def stage_17_colour_grade(ctx):
    _done = ctx._done
    _log = ctx._log
    _stage_start = ctx._stage_start
    final_video_path = ctx.final_video_path
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    visual_style = ctx.visual_style
    # ── Stage 6a: Cinematic color grade ──────────────────────────────────
    _stage_start('Color Grade')
    try:
        # Film grain rides on the grade pass, not the per-clip render: this
        # is the last video encode (the subtitle step delivers a sidecar SRT
        # and copies the video), so grain added here actually reaches the
        # viewer instead of being crushed by the nvenc chain.
        _cg_grain = ''
        try:
            from zyg_workflows import documentary_film_look as _dfl_cg

            # essay_images carries one emotion per rendered slot; the
            # emotion_curve is per-SENTENCE dicts, which is a different
            # shape and a different length.
            _cg_grain = _dfl_cg.final_grain_filter(
                [_im.get('emotion') for _im in (pipeline_state.get('essay_images') or [])]
            )
            if _cg_grain:
                _log('INFO', 'Color Grade', f'Film grain on final encode: {_cg_grain}')
        except Exception as _cge:
            _log('WARNING', 'Color Grade', f'grain filter unavailable: {_cge}')
        _cg_out = _apply_color_grade(
            final_video_path,
            visual_style,
            pipeline_id,
            log_fn=lambda m: _log('INFO', 'Color Grade', m),
            crf=18,
            extra_vf=_cg_grain,
        )
        if _cg_out != final_video_path:
            os.replace(_cg_out, final_video_path)
            _log('INFO', 'Color Grade', f'Cinematic grade applied ({visual_style} LUT + unsharp)')
        else:
            _log('INFO', 'Color Grade', 'Color grade pass-through (LUT not found or skipped)')
    except Exception as _cg2_e:
        _log('WARNING', 'Color Grade', f'Color grade skipped: {_cg2_e}')
    _done('Color Grade', {'style': visual_style})


def stage_18_book_intro(ctx):
    _book_intro_prepended = ctx._book_intro_prepended
    _img_paths = ctx._img_paths
    _log = ctx._log
    _slug = ctx._slug
    final_video_path = ctx.final_video_path
    out_dir = ctx.out_dir
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    # ── Stage 6b: Book intro — disabled ────────────────────────────────
    if False:  # book intro disabled for all topics
        _log('INFO', 'Stage 6', 'Rendering book intro…')
        _essay_title = pipeline_state.get('essay_title', topic.title())
        _essay_authors = pipeline_state.get('essay_authors', '')
        _desc = f'A scholarly exploration\nof {topic}.'
        if _essay_authors:
            _desc = f'Presented from the work of\n{_essay_authors[:60]}'
        _cover_img = _img_paths[0] if _img_paths else None
        _book_clip = _make_book_intro(out_dir, _essay_title, _desc, essay_img=_cover_img, duration=9.0)
        if _book_clip:
            # Prepend book intro to main video using filter_complex concat.
            # Scale the intro to match the slideshow (1920×1080 yuv420p) and add
            # silent audio — both streams must be identical before concat.
            _book_with_audio = os.path.join(out_dir, 'book_intro_audio.mp4')
            _book_aud_base = [
                exe('ffmpeg'),
                '-y',
                '-i',
                _book_clip,
                '-f',
                'lavfi',
                '-i',
                'anullsrc=r=44100:cl=stereo',
                '-filter_complex',
                'scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,'
                'format=yuv420p[vout]',
                '-map',
                '[vout]',
                '-map',
                '1:a:0',
                '-c:a',
                'aac',
                '-b:a',
                '192k',
                '-t',
                '9',
            ]
            _ffmpeg_run_nvenc_first(
                _book_aud_base + _nvenc_vcodec_args(_cq_for_crf(22), 'p4') + [_book_with_audio],
                _book_aud_base + _x264_vcodec_args(22, 'fast') + [_book_with_audio],
                30,
                label='book intro audio',
            )

            _with_intro = os.path.join(out_dir, f'{_slug}_with_intro.mp4')
            _intro_src = (
                _book_with_audio
                if (os.path.exists(_book_with_audio) and os.path.getsize(_book_with_audio) > 10000)
                else _book_clip
            )
            _intro_base = [
                exe('ffmpeg'),
                '-y',
                '-i',
                _intro_src,
                '-i',
                final_video_path,
                '-filter_complex',
                '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[vout][aout]',
                '-map',
                '[vout]',
                '-map',
                '[aout]',
                '-c:a',
                'aac',
                '-b:a',
                '192k',
                '-movflags',
                '+faststart',
            ]
            _r_intro = _ffmpeg_run_nvenc_first(
                _intro_base + _nvenc_vcodec_args(_cq_for_crf(22), 'p4') + [_with_intro],
                _intro_base + _x264_vcodec_args(22, 'fast') + [_with_intro],
                300,
                label='book intro concat',
            )
            if _r_intro.returncode != 0:
                _log(
                    'WARNING',
                    'Stage 6',
                    f'Book intro concat error: {_r_intro.stderr[-200:].decode(errors="replace")}',
                )

            if os.path.exists(_with_intro) and os.path.getsize(_with_intro) > 100000:
                os.replace(_with_intro, final_video_path)
                _book_intro_prepended = True
                _log('INFO', 'Stage 6', 'Book intro prepended')
            else:
                _log('WARNING', 'Stage 6', 'Book intro concat failed — skipping intro')
        else:
            _log('WARNING', 'Stage 6', 'Book intro render failed — skipping')

    ctx._book_intro_prepended = _book_intro_prepended


def stage_19_burn_subtitles(ctx):
    _book_intro_prepended = ctx._book_intro_prepended
    _done = ctx._done
    _log = ctx._log
    _pipeline_marker = ctx._pipeline_marker
    _save = ctx._save
    _sch_family_label = ctx._sch_family_label
    _slug = ctx._slug
    _stage_start = ctx._stage_start
    final_video_path = ctx.final_video_path
    job = ctx.job
    narration_enabled = ctx.narration_enabled
    narration_script = ctx.narration_script
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    tts_duration = ctx.tts_duration
    tts_path = ctx.tts_path
    # ── Stage 6c: Burn subtitles ──────────────────────────────────────
    # Documentary with narration always gets burned subtitles (voice on → subs on).
    _burn_subs_sch = bool(narration_enabled)
    _stage_start('Subtitle Burn')
    if _burn_subs_sch:
        # Prefer Whisper word timestamps (accurate, from actual audio) over
        # the TTS-estimated timings which are a linear approximation.
        _wtr_sub = pipeline_state.get('final_word_timings') or pipeline_state.get('word_timings_raw', [])
        _narr_for_subs = pipeline_state.get('script') or narration_script or ''
        _intro_offset = 9.0 if _book_intro_prepended else 0.0
        if pipeline_state.get('word_timings_raw'):
            _sub_method = 'Azure SDK+script'
        elif pipeline_state.get('whisper_timings'):
            _sub_method = 'Whisper+script'
        elif _wtr_sub:
            _sub_method = 'TTS-estimated'
        else:
            _sub_method = 'fallback'
        _log('INFO', 'Subtitle Burn', f'Burning subtitles ({_sub_method}, offset={_intro_offset:.0f}s)…')
        _subbed = os.path.join(out_dir, f'{_slug}_subtitled.mp4')
        _sub_ok = _burn_subtitles(
            final_video_path,
            tts_path,
            _subbed,
            pipeline_id=pipeline_id,
            word_timings_raw=_wtr_sub,
            intro_offset=_intro_offset,
            narration_script=_narr_for_subs,
            # Standing rule: numbers in subtitles are DIGITS. Converted in
            # the caption only — `narration_script` above is what the word
            # timings align against and what the voice already spoke.
            digits_in_subs=True,
        )
        if _sub_ok:
            # pipeline_video._burn_subtitles is sidecar-only ("YouTube mode
            # — no burn"): it writes <final>.srt and copies the video
            # unchanged, so _subbed is a byte-identical copy. Keep the
            # sidecar, drop the copy, and say what actually happened.
            _srt_side = os.path.splitext(final_video_path)[0] + '.srt'
            _srt_alt = os.path.splitext(_subbed)[0] + '.srt'
            if not os.path.isfile(_srt_side) and os.path.isfile(_srt_alt):
                try:
                    os.replace(_srt_alt, _srt_side)
                except OSError as _exc:
                    _zyg_log.warning(
                        'subtitle sidecar not moved to %s, the episode ships without one: %s', _srt_side, _exc
                    )
            if os.path.isfile(_srt_side):
                try:
                    os.remove(_subbed)
                except OSError as _exc:
                    _zyg_log.debug('byte-identical subtitle copy %s not removed: %s', _subbed, _exc)
                _log(
                    'INFO',
                    'Subtitle Burn',
                    f'Subtitle sidecar .srt written ({_sub_method}) — YouTube caption mode, video not burned',
                )
            else:
                os.replace(_subbed, final_video_path)
                _log('INFO', 'Subtitle Burn', f'Subtitles burned in ({_sub_method})')
        else:
            _log('WARNING', 'Subtitle Burn', 'Subtitle burn failed — delivering without subtitles')
        _done('Subtitle Burn', {'method': _sub_method, 'ok': _sub_ok})
    else:
        _log(
            'INFO',
            'Subtitle Burn',
            'Subtitles skipped — narration disabled (narration_enabled=False), no .srt written',
        )
        _done('Subtitle Burn', {'skipped': True, 'reason': 'narration_disabled'})

    # ── Content credential: the episode, after its last mutation ────────
    # The book intro and the subtitle burn both os.replace() over
    # final_video_path, so this is the first point at which the bytes that
    # ship are final. Fail-safe: without a key it logs and leaves the file
    # untouched, and _vid_size below is then the size of what is delivered.
    _seal.seal(
        final_video_path,
        pipeline='documentary',
        run_id=pipeline_id,
        title=pipeline_state.get('essay_title') or f'Scholarly Voices: {topic.title()}',
        extra={'topic': topic, 'subtitles': _sub_method if _burn_subs_sch else 'none'},
        log_fn=lambda m: _log('INFO', 'Content Credential', m),
    )

    _vid_size = os.path.getsize(final_video_path)
    pipeline_state['video_path'] = final_video_path
    pipeline_state['processed_clips'] = [
        {
            'video_id': f'scholarly_{topic}_{pipeline_id[:8]}',
            'clip_index': 1,
            'path': final_video_path,
            'source_ts': 0,
            'topic': topic,
            'department': 'scholarly',
            'title': pipeline_state.get('essay_title') or f'Scholarly Voices: {topic.title()}',
            'description': (
                f"Documentary on '{pipeline_state.get('essay_title', topic)}'. "
                f'{pipeline_state.get("word_count", 0)} words narrated. '
                f'Duration: {round(tts_duration / 60, 1)} min. '
                f'Topic: {topic}. '
                f'Images: {len(pipeline_state.get("essay_images", []))} '
                f'({sum(1 for i in pipeline_state.get("essay_images", []) if i.get("source") == "flux")} {_sch_family_label}-generated). '
                f'Pipeline: {pipeline_id}.'
            ),
            'word_count': pipeline_state.get('word_count', 0),
            'tts_duration': round(tts_duration, 1),
            'essay_title': pipeline_state.get('essay_title', ''),
            'essay_authors': pipeline_state.get('essay_authors', ''),
            'flux_images': len([i for i in pipeline_state.get('essay_images', []) if i.get('source') == 'flux']),
            'pipeline_id': pipeline_id,
        }
    ]
    _save()
    _done(
        'Stage 6: Video Assembly',
        {
            'path': final_video_path,
            'size_mb': round(_vid_size / 1024 / 1024, 1),
        },
    )

    # Self-evaluation was moved to Stage 3.5 (pre-FLUX) to avoid OOM
    # when the emotion/self-eval model tries to load after FLUX + TTS have
    # filled VRAM.

    job['status'] = 'completed'
    job['ended'] = _ams_iso()
    # Persist total elapsed to state file
    if job.get('started'):
        try:
            _end_dt = _parse_iso_to_ams(job['ended'])
            _start_dt = _parse_iso_to_ams(job['started'])
            if _end_dt and _start_dt:
                pipeline_state['total_elapsed_s'] = round((_end_dt - _start_dt).total_seconds(), 1)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('run keeps no total_elapsed_s, its timestamps did not parse: %s', _exc)
    pipeline_state['stage_timeline'] = job.get('stage_timeline', [])
    pipeline_state['debug_events'] = job.get('debug_events', [])
    pipeline_state['ended'] = job['ended']
    pipeline_state['status'] = job['status']
    # Copy flux stats onto job so _bm_record_pipeline can read them
    job['flux_images'] = len([i for i in pipeline_state.get('essay_images', []) if i.get('source') == 'flux'])
    job['tts_duration'] = pipeline_state.get('tts_duration') or tts_duration
    job['flux_gen_elapsed_s'] = pipeline_state.get('flux_gen_elapsed_s')
    _bm_record_pipeline(job, pipeline_id=pipeline_id)  # no-op for test ids
    _save()

    job['result'] = (
        f'Scholarly — {topic.title()} complete. '
        f'Script: {pipeline_state["word_count"]} words. '
        f'Duration: {tts_duration / 60:.1f} min. '
        f'Output: {final_video_path}'
    )
    job['final_output_file'] = final_video_path  # used by zero_public to show only final
    _update_marker(_pipeline_marker, status='done', label=f'✅ Scholarly {pipeline_id[:8]} — {topic.title()} complete')
    _log('INFO', 'COMPLETE', job['result'])

    # ── Thumbnail: the HOOK still, before Cleanup deletes flux_images/ ──
    # pipeline_video.py has written _thumbnail.jpg since 2277; this pipeline
    # never did, Cleanup deletes the stills, and bp_assets_media then falls
    # back to the ffmpeg frame at 10% runtime — verified pixel-identical on
    # a prior episode. The hook is built to be the most arresting frame in
    # the film and it never reached the YouTube thumbnail. Now it does.
    try:
        _thumb_dst = os.path.join(out_dir, '_thumbnail.jpg')
        _hook_src = ''
        for _ei in pipeline_state.get('essay_images', []) or []:
            if int(_ei.get('index', -1)) == 0 and _ei.get('source') == 'flux':
                _hook_src = str(_ei.get('path') or '')
                break
        if not _hook_src or not os.path.isfile(_hook_src):
            for _cand in ('flux_000_2x.jpg', 'flux_000_4x.jpg', 'flux_000.jpg'):
                _cp = os.path.join(out_dir, 'flux_images', _cand)
                if os.path.isfile(_cp):
                    _hook_src = _cp
                    break
        if _hook_src and os.path.isfile(_hook_src):
            from PIL import Image as _PILThumb

            with _PILThumb.open(_hook_src) as _im_t:
                _im_t = _im_t.convert('RGB')
                # Fit-scale (contain) to 1280×720, UPSCALING when the source
                # is smaller: PIL .thumbnail never upsizes, so a 512×288 smoke
                # still shipped as a postage stamp on a black canvas (S-01).
                _fit_t = min(1280 / max(_im_t.width, 1), 720 / max(_im_t.height, 1))
                _tw_t = max(1, min(1280, int(round(_im_t.width * _fit_t))))
                _th_t = max(1, min(720, int(round(_im_t.height * _fit_t))))
                _im_t = _im_t.resize((_tw_t, _th_t), _PILThumb.LANCZOS)
                if (_tw_t, _th_t) == (1280, 720):
                    _im_t.save(_thumb_dst, 'JPEG', quality=92)
                else:
                    _canvas_t = _PILThumb.new('RGB', (1280, 720), (0, 0, 0))
                    _canvas_t.paste(_im_t, ((1280 - _tw_t) // 2, (720 - _th_t) // 2))
                    _canvas_t.save(_thumb_dst, 'JPEG', quality=92)
            pipeline_state['thumbnail_path'] = _thumb_dst
            _seal.seal(
                _thumb_dst,
                pipeline='documentary',
                run_id=pipeline_id,
                title=os.path.basename(_thumb_dst),
                extra={'topic': topic, 'derived_from': os.path.basename(_hook_src)},
                log_fn=lambda m: _log('INFO', 'Content Credential', m),
            )
            _log('INFO', 'Thumbnail', f'Saved _thumbnail.jpg from the hook still ({os.path.basename(_hook_src)})')
        else:
            _log('WARNING', 'Thumbnail', 'No hook still found — YouTube thumbnail will fall back to a video frame')
    except Exception as _th_e:
        _log('WARNING', 'Thumbnail', f'Thumbnail from hook still skipped: {_th_e!r}')

    # ── Intermediate file cleanup ────────────────────────────────────────
    job['current_stage'] = 'Cleanup'
    _cleanup_pipeline_output(
        out_dir,
        final_video_path,
        log_fn=lambda m: _log('INFO', 'Cleanup', m),
        # Smoke runs keep their stills so the harness can assert on them.
        keep_stills=bool(pipeline_state.get('smoke')),
    )

    # ── SFTP Delivery to Windows Desktop ────────────────────────────────
    job['current_stage'] = 'Delivering to Desktop'
    _update_marker(_pipeline_marker, label=f'🔄 Scholarly {pipeline_id[:8]} — SFTP Delivery')
    _scp_output_to_windows(out_dir, pipeline_id)
    job['current_stage'] = None
