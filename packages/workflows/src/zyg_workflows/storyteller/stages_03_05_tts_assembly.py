# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stages 3, 4 and 5 of the storyteller pipeline — TTS, Ken Burns, assembly.

``stage_03_tts`` synthesises the narration and its word timings,
``stage_04_ken_burns`` renders a PIL pan/zoom clip per image slot, and
``stage_05_final_assembly`` concatenates the slides and muxes the audio. Stage
3.5 (FLUX image generation) sits between 3 and 4 and is still inline in
``pipeline_storyteller._run_storyteller_pipeline``, so the driver hands
``img_paths`` over on the context. Cut verbatim out of that function (lines
1624-1710, 3097-3216 and 3218-3332 of commit 770c30a); see ``SPLIT_LOG.md``."""

import os

from zyg_workflows.bin import exe
from zyg_workflows.pipeline_common import _align_narration_word_timings
from zyg_workflows.pipeline_scholarly import _render_kb_pil_shared
from zyg_workflows.tts_service import _synthesise_tts


def stage_03_tts(ctx):
    _check_stop = ctx._check_stop
    _effective_tts_voice = ctx._effective_tts_voice
    _log = ctx._log
    _save = ctx._save
    _update_stage = ctx._update_stage
    duration_min = ctx.duration_min
    narration_enabled = ctx.narration_enabled
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    scenes = ctx.scenes
    voice_style = ctx.voice_style
    # ── Stage 3: TTS Narration ────────────────────────────────────────────────
    _update_stage('Stage 3 — TTS Narration', 20)
    _check_stop()

    # Build full narration script from scenes
    full_narration = '\n\n'.join(s.get('narration', '') for s in scenes if s.get('narration', '').strip())

    tts_word_timings: list = []
    if narration_enabled and full_narration.strip():
        _log('INFO', 'Stage 3', f'Synthesising narration ({len(full_narration)} chars)…')
        tts_path, tts_duration, tts_word_timings, tts_engine = _synthesise_tts(
            full_narration,
            out_dir,
            pipeline_id,
            voice_mode=voice_style,
            voice_override=_effective_tts_voice,
            log_fn=_log,
        )
        pipeline_state['tts_engine'] = tts_engine
        if tts_path:
            if tts_word_timings:
                _tts_aligned, _tts_cov = _align_narration_word_timings(
                    full_narration,
                    tts_word_timings,
                    voice_mode=voice_style,
                )
                if _tts_cov >= 0.5:
                    tts_word_timings = _tts_aligned
                    _log('INFO', 'Stage 3', f'Subtitle timings script-aligned ({_tts_cov:.0%} coverage)')
            # 2026-08-06: IndexTTS-2 is the PRIMARY engine — an IndexTTS-2
            # render is the normal path, not a degradation. The
            # 'narration_voice_fallback' flag means "primary engine failed,
            # Chatterbox delivered the narration instead".
            if tts_engine == 'chatterbox-fallback':
                pipeline_state['narration_voice_fallback'] = True
                _log(
                    'WARNING',
                    'Stage 3',
                    f'IndexTTS-2 primary TTS failed — narration rendered by the '
                    f'Chatterbox fallback ({_effective_tts_voice}); check the '
                    f'[TTS] lines above for the failure reason.',
                )
            # 2026-07-24 r3: a TTS backend that silently truncates (torch
            # tensor bug in run 4cd49ffd rendered 101s for an ~11-min
            # script) must not sail through — length-sanity gate against
            # the script size (~14 chars/sec spoken is the platform floor).
            _exp_tts_s = len(full_narration) / 20.0
            if tts_duration and tts_duration < 0.5 * _exp_tts_s:
                pipeline_state['narration_truncated'] = True
                _log(
                    'WARNING',
                    'Stage 3',
                    f'Narration suspiciously short: {tts_duration:.0f}s for '
                    f'{len(full_narration)} chars (expected ≥{_exp_tts_s:.0f}s) — '
                    f'flagging degraded',
                )
            pipeline_state['tts_path'] = tts_path
            pipeline_state['tts_duration'] = tts_duration
            pipeline_state['narration_script'] = full_narration
            _log(
                'INFO',
                'Stage 3',
                f'TTS done: {tts_duration:.1f}s → {tts_path}'
                + (f' ({len(tts_word_timings)} word timings)' if tts_word_timings else ' (no word timings)'),
            )
        else:
            # 2026-07-24: total TTS failure is a FATAL defect for a narrated
            # product — run 6278904c shipped a 600s SILENT slideshow as
            # 'completed DEGRADED' because nothing recorded the audio loss.
            # The video is still assembled for inspection; the wrap-up gate
            # fails the job on this flag.
            pipeline_state['narration_missing'] = True
            _log(
                'ERROR',
                'Stage 3',
                'TTS FAILED on ALL engines — continuing to assemble a video '
                'for inspection, but the job will be marked FAILED (no audio)',
            )
            tts_path = None
            tts_duration = duration_min * 60
    else:
        _log('INFO', 'Stage 3', 'Narration disabled — skipping TTS')
        tts_path = None
        tts_duration = duration_min * 60

    _save()
    _check_stop()

    ctx.full_narration = full_narration
    ctx.tts_duration = tts_duration
    ctx.tts_path = tts_path
    ctx.tts_word_timings = tts_word_timings


def stage_04_ken_burns(ctx):
    _check_stop = ctx._check_stop
    _log = ctx._log
    _save = ctx._save
    _update_stage = ctx._update_stage
    duration_min = ctx.duration_min
    img_paths = ctx.img_paths
    job = ctx.job
    out_dir = ctx.out_dir
    scenes = ctx.scenes
    tts_duration = ctx.tts_duration
    # ── Stage 4: Ken Burns + Assembly ─────────────────────────────────────────
    _update_stage('Stage 4 — Ken Burns Animation', 65)
    _check_stop()

    # Per-scene duration: fit images to TTS audio, compensating for xfade overlap.
    # xfade transitions overlap adjacent clips, shortening total video vs sum of durations.
    # Two-pass: estimate overlap with initial durations, then correct scene_dur accordingly.
    if tts_duration and tts_duration > 0:
        total_img_dur = tts_duration
    else:
        total_img_dur = duration_min * 60

    scene_dur = total_img_dur / max(len(img_paths), 1)
    scene_dur = max(3.0, min(30.0, scene_dur))  # clamp 3–30 s per scene

    # Pass 1: estimate total xfade overlap with current durations
    try:
        from zyg_workflows import murch_engine as _mex_pre

        _pre_emotions = [s.get('emotion', 'calm') for s in scenes[: len(img_paths)]]
        _pre_shot_types = [s.get('shot_type', 'medium') for s in scenes[: len(img_paths)]]
        _, _pre_manifest = _mex_pre.build_xfade_filter_graph(
            [scene_dur] * len(img_paths), _pre_emotions, shot_types=_pre_shot_types
        )
        _total_xfade_overlap = sum(m['duration'] for m in _pre_manifest if m.get('transition', 'cut') != 'cut')
        if _total_xfade_overlap > 0:
            scene_dur = (total_img_dur + _total_xfade_overlap) / max(len(img_paths), 1)
            scene_dur = max(3.0, min(30.0, scene_dur))
            _log(
                'INFO',
                'Stage 4',
                f'xfade compensation: +{_total_xfade_overlap:.1f}s overlap → scene_dur={scene_dur:.2f}s',
            )
    except Exception as _xpre_e:
        _log('WARNING', 'Stage 4', f'xfade pre-pass skipped: {_xpre_e}')

    _img_durations = [scene_dur] * len(img_paths)

    # Shot types + emotions from scene list
    _slot_shot_types = [s.get('shot_type', 'medium') for s in scenes[: len(img_paths)]]
    _slot_emotions = [s.get('emotion', 'calm') for s in scenes[: len(img_paths)]]
    _focal_zones = [s.get('focal_zone', 'center') for s in scenes[: len(img_paths)]]

    _n_imgs = len(img_paths)
    _SLIDE_W_ST, _SLIDE_H_ST = 1280, 720

    # Ken Burns PIL render (shares _render_kb_pil from scholarly pipeline)
    _kb_tmp_st = os.path.join(out_dir, '_kb_tmp')
    os.makedirs(_kb_tmp_st, exist_ok=True)
    _KB_FPS_ST = 24

    _kb_clips_st: list = []

    import concurrent.futures as _kb_cf_st

    _kb_tasks_st = {}
    for _ki in range(_n_imgs):
        _kb_out = os.path.join(_kb_tmp_st, f'kb_{_ki:03d}.mp4')
        _fz = _focal_zones[_ki] if _ki < len(_focal_zones) else 'center'
        _kb_tasks_st[_ki] = (
            img_paths[_ki],
            _kb_out,
            _img_durations[_ki],
            _KB_FPS_ST,
            _ki,
            _slot_shot_types[_ki] if _ki < len(_slot_shot_types) else 'medium',
            _slot_emotions[_ki] if _ki < len(_slot_emotions) else 'calm',
            _fz,
            _SLIDE_W_ST,
            _SLIDE_H_ST,
        )

    _kb_n_workers_st = min(
        os.cpu_count() or 4,
        len(_kb_tasks_st),
        max(1, int(os.environ.get('ZYG_KB_MAX_WORKERS', '8'))),
    )
    _kb_results_st: dict = {}

    if _kb_tasks_st:
        # 2026-07-24 fix: release ComfyUI's resident models before the parallel
        # NVENC encodes. With a healthy Comfy holding ~40GB through Stage 4,
        # 23/25 KB encodes failed session/VRAM allocation (run a6f458bc) —
        # silently, because stderr goes to DEVNULL.
        try:
            from zyg_workflows import _comfy_client as _cc_kb

            _cc_kb.free_vram(unload_models=True, free_memory=True)
            _log('INFO', 'Stage 4', 'ComfyUI models released before Ken Burns NVENC encodes')
        except Exception as _kbf_e:
            _log('WARNING', 'Stage 4', f'Comfy VRAM release before KB skipped: {_kbf_e}')
        _log('INFO', 'Stage 4', f'PIL Ken Burns: rendering {len(_kb_tasks_st)} clips on {_kb_n_workers_st} threads…')

        def _kb_worker_st(args):
            _ki_w, _task = args
            return _ki_w, _render_kb_pil_shared(*_task)

        with _kb_cf_st.ThreadPoolExecutor(max_workers=_kb_n_workers_st) as _kb_pool_st:
            for _ki_r, _ok_r in _kb_pool_st.map(_kb_worker_st, _kb_tasks_st.items()):
                _kb_results_st[_ki_r] = _ok_r

    for _ki in range(_n_imgs):
        _kb_out_ki = _kb_tasks_st[_ki][1]
        if _kb_results_st.get(_ki, False):
            _kb_clips_st.append(('pil', _kb_out_ki, _img_durations[_ki]))
        else:
            _log('WARNING', 'Stage 4', f'KB render failed slot {_ki} — static fallback')
            _kb_clips_st.append(('static', img_paths[_ki], _img_durations[_ki]))

    _log(
        'INFO',
        'Stage 4',
        f'Ken Burns: {sum(1 for c in _kb_clips_st if c[0] == "pil")} animated, '
        f'{sum(1 for c in _kb_clips_st if c[0] == "static")} static',
    )
    job['progress_pct'] = 75
    _save()
    _check_stop()

    ctx._SLIDE_H_ST = _SLIDE_H_ST
    ctx._SLIDE_W_ST = _SLIDE_W_ST
    ctx._img_durations = _img_durations
    ctx._kb_clips_st = _kb_clips_st
    ctx._n_imgs = _n_imgs
    ctx._slot_emotions = _slot_emotions
    ctx._slot_shot_types = _slot_shot_types


def stage_05_final_assembly(ctx):
    _SLIDE_H_ST = ctx._SLIDE_H_ST
    _SLIDE_W_ST = ctx._SLIDE_W_ST
    _check_stop = ctx._check_stop
    _img_durations = ctx._img_durations
    _kb_clips_st = ctx._kb_clips_st
    _log = ctx._log
    _n_imgs = ctx._n_imgs
    _save = ctx._save
    _slot_emotions = ctx._slot_emotions
    _slot_shot_types = ctx._slot_shot_types
    _slug_st = ctx._slug_st
    _sp_st = ctx._sp_st
    _update_stage = ctx._update_stage
    job = ctx.job
    out_dir = ctx.out_dir
    pipeline_state = ctx.pipeline_state
    tts_path = ctx.tts_path
    # ── Stage 5: Final Assembly ───────────────────────────────────────────────
    _update_stage('Stage 5 — Final Assembly', 80)
    _check_stop()

    # 2026-07-24 fix: normalize fps + pixel format per input. Mixed inputs
    # (KB mp4 clips are yuv420p, PNG stills are rgb24) made xfade negotiate
    # gbrp and ffmpeg died ("No accelerated colorspace conversion found from
    # yuv420p to gbrp") → 0-byte slideshow (run a6f458bc).
    _scale_prefix_st = ''.join(
        [
            f'[{i}:v]scale={_SLIDE_W_ST}:{_SLIDE_H_ST}:flags=lanczos,fps=24,format=yuv420p,setsar=1[vs{i}];'
            for i in range(_n_imgs)
        ]
    )

    # Build xfade transitions
    _use_xfade_st = False
    _xfade_debug_st: list = []
    _filter_st = ''
    try:
        from zyg_workflows import murch_engine as _mex_st

        _xfade_str_st, _xfade_manifest_st = _mex_st.build_xfade_filter_graph(
            _img_durations,
            _slot_emotions,
            shot_types=_slot_shot_types,
            debug_log=_xfade_debug_st,
        )
        if _xfade_str_st:
            _patched_st = _xfade_str_st
            for _xi in range(_n_imgs):
                _patched_st = _patched_st.replace(f'[{_xi}:v]', f'[vs{_xi}]')
            _filter_st = _scale_prefix_st + _patched_st
            _use_xfade_st = True
            _log('INFO', 'Stage 5', f'xfade: {len(_xfade_manifest_st)} transitions')
    except Exception as _xfe_st:
        _log('WARNING', 'Stage 5', f'xfade build failed: {_xfe_st} — hard cuts')

    if not _use_xfade_st:
        _filter_st = _scale_prefix_st
        _filter_st += ''.join([f'[vs{i}]' for i in range(_n_imgs)])
        _filter_st += f'concat=n={_n_imgs}:v=1:a=0[vout]'

    _slideshow_path = os.path.join(out_dir, f'{_slug_st}_slideshow.mp4')
    _ffmpeg_inputs_st = []
    for _ktype, _kpath, _kdur in _kb_clips_st:
        if _ktype == 'pil':
            _ffmpeg_inputs_st += ['-t', f'{_kdur:.3f}', '-i', _kpath]
        else:
            _ffmpeg_inputs_st += ['-loop', '1', '-t', str(_kdur), '-i', _kpath]

    if _ffmpeg_inputs_st:
        _slide_cmd_st = (
            [exe('ffmpeg'), '-y']
            + _ffmpeg_inputs_st
            + [
                '-filter_complex',
                _filter_st,
                '-map',
                '[vout]',
                '-c:v',
                'libx264',
                '-preset',
                'fast',
                '-pix_fmt',
                'yuv420p',
                '-r',
                '24',
                _slideshow_path,
            ]
        )
        _log('INFO', 'Stage 5', f'ffmpeg slideshow → {_slideshow_path}')
        try:
            _proc_st = _sp_st.run(_slide_cmd_st, capture_output=True, stdin=_sp_st.DEVNULL, timeout=600)
            if _proc_st.returncode != 0:
                _log('ERROR', 'Stage 5', f'ffmpeg slideshow failed: {_proc_st.stderr[-1000:]}')
        except Exception as _ffe:
            _log('ERROR', 'Stage 5', f'ffmpeg slideshow exception: {_ffe}')

    # Merge audio + video
    final_path = os.path.join(out_dir, f'{_slug_st}_final.mp4')
    if tts_path and os.path.isfile(tts_path) and os.path.isfile(_slideshow_path):
        _merge_cmd_st = [
            exe('ffmpeg'),
            '-y',
            '-i',
            _slideshow_path,
            '-i',
            tts_path,
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-shortest',
            final_path,
        ]
        _log('INFO', 'Stage 5', 'Merging audio + video…')
        try:
            _p_merge = _sp_st.run(_merge_cmd_st, capture_output=True, stdin=_sp_st.DEVNULL, timeout=300)
            if _p_merge.returncode != 0:
                _log('ERROR', 'Stage 5', f'Audio merge failed: {_p_merge.stderr[-500:]}')
                final_path = _slideshow_path  # use video-only as fallback
        except Exception as _me:
            _log('ERROR', 'Stage 5', f'Merge exception: {_me}')
            final_path = _slideshow_path
    elif os.path.isfile(_slideshow_path):
        final_path = _slideshow_path
    else:
        raise RuntimeError('No slideshow produced')

    pipeline_state['video_path'] = final_path
    job['progress_pct'] = 95
    _save()

    ctx.final_path = final_path
