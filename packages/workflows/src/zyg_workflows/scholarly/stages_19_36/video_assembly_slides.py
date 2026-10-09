# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slideshow planning and encoding, lifted out of `stage_15_video_assembly`.

Which pictures the slideshow is made of, how long each is held, which of them
a motion clip replaces, the ffmpeg filter graph that joins them and the final
encode. Each helper takes plain values plus the stage's `log`/`debug`
callables, so the timing grid, the mood mapping, the manifest reading and the
filter graph are unit-testable without ffmpeg, a GPU or a network.
"""

from dataclasses import dataclass

from ._common import (
    _cq_for_crf,
    _ffmpeg_run_nvenc_first,
    _nvenc_vcodec_args,
    _scholarly_motion,
    _urlsplit,
    _x264_vcodec_args,
    _zyg_log,
    exe,
    os,
    requests,
)
from .image_durations import _make_build_image_durations
from .video_assembly_kenburns import _SLIDE_H, _SLIDE_W


@dataclass(frozen=True)
class SlidePlan:
    """The per-slot timing and mood the Ken Burns render and the xfade graph share."""

    durations: list
    emotions: list
    shot_types: list


def essay_image_paths(essay_imgs, log):
    """The essay image paths still on disk, warning about however many are not."""
    _img_paths = [img['path'] for img in essay_imgs if os.path.exists(img.get('path', ''))]
    _missing_img_count = len(essay_imgs) - len(_img_paths)
    if _missing_img_count:
        log('WARNING', 'Stage 6', f'{_missing_img_count} of {len(essay_imgs)} essay image paths missing from disk')
    return _img_paths


def rescue_flux_images(out_dir, family_label, log):
    """FLUX stills found on disk for this run — upscaled ones first, then raw.

    Before falling back to Wikimedia, scan for FLUX images on disk for this
    run. This rescues the first-pass images when a second FLUX pass OOM'd and
    `pipeline_state['essay_images']` was never populated. Empty when the run
    left nothing behind, which sends the caller on to the Wikimedia fallback.
    """
    import glob as _g6_rescue

    _flux_dir_rescue = os.path.join(out_dir, 'flux_images')
    # Upscaled stills are _2x on the qwen family and _4x on flux.
    _rescued_paths = sorted(_g6_rescue.glob(os.path.join(_flux_dir_rescue, 'flux_*_[24]x.jpg')))
    if not _rescued_paths:
        _rescued_paths = sorted(_g6_rescue.glob(os.path.join(_flux_dir_rescue, 'flux_*.jpg')))
    if _rescued_paths:
        log(
            'INFO',
            'Stage 6',
            f'Rescued {len(_rescued_paths)} {family_label} images from disk ({_flux_dir_rescue}) '
            f'— skipping Wikimedia fallback',
        )
    return _rescued_paths


def download_generic_backgrounds(pipeline_state, out_dir, log):
    """Fetch up to two generic Wikimedia clips as the background of last resort.

    Returns the paths that landed over 10 kB; a clip that failed is logged and
    skipped, never raised.
    """
    log(
        'WARNING',
        'Stage 6',
        'No valid essay images — downloading generic Wikimedia clips as background fallback',
    )
    downloaded_clips = []
    for _gc in [c for c in pipeline_state.get('stock_clips', []) if c.get('source') == 'generic'][:2]:
        _gc_dest = os.path.join(out_dir, f'generic_bg_{len(downloaded_clips)}.webm')
        try:
            _gc_url = _gc.get('url', '')
            if _urlsplit(_gc_url).scheme not in ('http', 'https'):
                raise ValueError(f'refusing to download clip from {_gc_url!r}')
            _gc_resp = requests.get(
                _gc_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
                    'Referer': 'https://commons.wikimedia.org/',
                },
                timeout=60,
            )
            with open(_gc_dest, 'wb') as _gc_fh:
                _gc_fh.write(_gc_resp.content)
            if os.path.exists(_gc_dest) and os.path.getsize(_gc_dest) > 10000:
                downloaded_clips.append(_gc_dest)
                log('INFO', 'Stage 6', f'Generic fallback clip ready: {_gc.get("query", "")}')
        except Exception as _gce:
            log('WARNING', 'Stage 6', f'Generic clip download failed ({_gc.get("query", "")}): {_gce}')
    return downloaded_clips


def locked_grid_durations(pipeline_state, img_paths, essay_imgs, tts_dur, log):
    """Durations off the time-locked display grid, or None when the slots are unusable.

    FLUX prompts are content-anchored to uniform audio windows
    [i*T/n, (i+1)*T/n] (Stage 3.5a/3.5). Each image must be shown in exactly
    its own window — the legacy sentence-bucket + emotion warp stretched single
    images across 30-40s and squeezed others toward 2.5s, drifting the picture
    track minutes off the narration. Missing slots fold into the previous
    image's window.
    """
    _lock_entries = [img for img in essay_imgs if os.path.exists(img.get('path', ''))]
    _lock_idxs = [img.get('index') for img in _lock_entries]
    _lock_grid_n = pipeline_state.get('n_flux_images') or len(img_paths)
    _lock_ok = (
        bool(_lock_idxs)
        and all(isinstance(_ix, int) for _ix in _lock_idxs)
        and _lock_idxs == sorted(set(_lock_idxs))
        and _lock_idxs[-1] < max(_lock_grid_n, 1)
    )
    if not _lock_ok:
        return None
    _slot_w6 = tts_dur / max(_lock_grid_n, 1)
    _starts6 = [_ix * _slot_w6 for _ix in _lock_idxs]
    _starts6[0] = 0.0
    _ends6 = _starts6[1:] + [tts_dur]
    _img_durations = [round(max(1.0, _e6 - _s6), 2) for _s6, _e6 in zip(_starts6, _ends6)]
    log(
        'INFO',
        'Stage 6',
        f'Time-locked slideshow: {len(_img_durations)} images on uniform '
        f'{_slot_w6:.1f}s grid (emotion duration warp disabled to keep '
        f'each image on its narrated beat)',
    )
    return _img_durations


def slot_moods(pipeline_state, n_imgs):
    """(emotions, shot types) for *n_imgs* slots, read off the emotion curve.

    Layer 3c of the xfade transitions: the emotion curve is resampled onto the
    slot count, and each slot's shot type comes from its essay-image metadata.
    """
    _slot_emotions = []
    _slot_shot_types = []
    _ec = pipeline_state.get('emotion_curve', [])
    _essay_imgs_meta = pipeline_state.get('essay_images', [])
    for _bi in range(n_imgs):
        _ec_idx = min(int(_bi * len(_ec) / max(n_imgs, 1)), len(_ec) - 1) if _ec else 0
        _slot_emotions.append(_ec[_ec_idx]['emotion'] if _ec else 'calm')
        _meta_entry = _essay_imgs_meta[_bi] if _bi < len(_essay_imgs_meta) else {}
        _slot_shot_types.append(_meta_entry.get('shot_type', ''))
    return _slot_emotions, _slot_shot_types


def inflate_for_xfade(img_durations, slot_emotions, slot_shot_types, tts_dur, debug):
    """Scale the durations up by the overlap a preliminary xfade manifest reports.

    xfade transitions eat their full duration from the rendered timeline:
    rendered_duration = sum(durations) - sum(transition_durations). Without
    compensation the slideshow ends up ~67s short of TTS and loops. Solution:
    measure overhead from a preliminary manifest, then scale up.
    """
    try:
        from zyg_workflows import murch_engine as _mex_pre

        _, _prelim_manifest = _mex_pre.build_xfade_filter_graph(
            img_durations, slot_emotions, shot_types=slot_shot_types
        )
        _xfade_overhead = sum(m['duration'] for m in _prelim_manifest if m['transition'] != 'cut')
        if _xfade_overhead > 1.0:
            _inflate_scale = (tts_dur + _xfade_overhead) / tts_dur
            img_durations = [round(d * _inflate_scale, 3) for d in img_durations]
            debug(
                'Stage 6',
                f'Duration inflation: ×{_inflate_scale:.3f} '
                f'(+{_xfade_overhead:.1f}s xfade overhead absorbed — '
                f'target rendered ≈ {tts_dur:.0f}s)',
            )
    except Exception as _pre_xe:
        debug('Stage 6', f'xfade pre-pass failed: {_pre_xe}', level='WARNING')
    return img_durations


def plan_slideshow(pipeline_state, img_paths, essay_imgs, visual_tags, tts_dur, log, debug):
    """The `SlidePlan` for this run: a duration, an emotion and a shot type per slot.

    The time-locked grid is preferred; a run whose slot indices are unusable
    falls back to the legacy emotion-timed durations. Either way the durations
    come out inflated by the xfade overlap so the rendered timeline still
    matches the narration.
    """
    _wtr = pipeline_state.get('final_word_timings') or pipeline_state.get('word_timings_raw', [])
    _img_durations = locked_grid_durations(pipeline_state, img_paths, essay_imgs, tts_dur, log)
    if _img_durations is None:
        _build_image_durations = _make_build_image_durations(pipeline_state)
        _img_durations = _build_image_durations(img_paths, visual_tags, _wtr, tts_dur)
        log('INFO', 'Stage 6', 'Slot indices unavailable — legacy emotion-timed durations in use')
    log(
        'INFO',
        'Stage 6',
        f'Image slideshow: {len(img_paths)} images, timed durations: {[f"{d:.0f}s" for d in _img_durations]}',
    )
    debug(
        'Stage 6',
        f'Using {"Whisper" if pipeline_state.get("whisper_timings") else "TTS"} word timings ({len(_wtr)} words)',
    )

    _slot_emotions, _slot_shot_types = slot_moods(pipeline_state, len(img_paths))
    _img_durations = inflate_for_xfade(_img_durations, _slot_emotions, _slot_shot_types, tts_dur, debug)
    return SlidePlan(durations=_img_durations, emotions=_slot_emotions, shot_types=_slot_shot_types)


def load_motion_clip_map(out_dir, pipeline_state, log):
    """{source image path: motion clip path} from the LTX-2.5 and WAN manifests.

    Two sources, LTX-2.5 first: Stage 5 animates every picture on the :8189
    instance and writes ltx_manifest.json, and the older WAN manifest still
    substitutes if one is ever produced. A picture with no clip falls through
    to its PIL Ken Burns move, and the count of those is reported, never
    hidden.
    """
    _wan_img_to_clip: dict = {}
    _ltx_manifest_path = os.path.join(out_dir, _scholarly_motion.MANIFEST_REL)
    if os.path.exists(_ltx_manifest_path):
        try:
            import json as _json6l

            with open(_ltx_manifest_path) as _lm6:
                for _lc in _json6l.load(_lm6):
                    _lclip = _lc.get('path', '')
                    _lsrc = _lc.get('source_image', '')
                    if _lsrc and _lclip and os.path.exists(_lclip):
                        _wan_img_to_clip[_lsrc] = _lclip
            if _wan_img_to_clip:
                log(
                    'INFO',
                    'Stage 6',
                    f'LTX-2.5 clips: substituting {len(_wan_img_to_clip)} moving picture(s) for Ken Burns',
                )
        except Exception as _lme:
            log('WARNING', 'Stage 6', f'LTX manifest read failed: {_lme}')
    _wan_manifest_path = os.path.join(out_dir, 'wan_clips', 'wan_manifest.json')
    if pipeline_state.get('wan_enabled', True) and os.path.exists(_wan_manifest_path):
        try:
            import json as _json6s

            with open(_wan_manifest_path) as _wm6:
                for _wc in _json6s.load(_wm6):
                    _wclip = _wc.get('path', '')
                    _wsrc = _wc.get('source_image', '')
                    if _wsrc and os.path.exists(_wclip):
                        _wan_img_to_clip[_wsrc] = _wclip
            if _wan_img_to_clip:
                log(
                    'INFO',
                    'Stage 6',
                    f'WAN clips: substituting {len(_wan_img_to_clip)} video clip(s) into slideshow',
                )
        except Exception as _wme:
            log('WARNING', 'Stage 6', f'WAN manifest read failed: {_wme}')
    elif not pipeline_state.get('wan_enabled', True):
        log('INFO', 'Stage 6', 'WAN substitution disabled for this run')
    return _wan_img_to_clip


def build_slideshow_filter(n_imgs, plan, log, debug):
    """(filter_complex string, True when xfade is in it) for the whole slideshow.

    A failing murch_engine build is not fatal: the graph falls back to hard
    cuts through `concat`, which is what the stage did before xfade existed.
    """
    # Trivial scale prefix: PIL clips are already at _SLIDE_W×_SLIDE_H;
    # the scale pass just provides [vs{i}] labels that the xfade graph expects.
    _scale_prefix = ''.join(
        [f'[{i}:v]scale={_SLIDE_W}:{_SLIDE_H}:flags=lanczos,setsar=1[vs{i}];' for i in range(n_imgs)]
    )
    _xfade_debug: list = []
    try:
        from zyg_workflows import murch_engine as _mex

        _xfade_str, _xfade_manifest = _mex.build_xfade_filter_graph(
            plan.durations, plan.emotions, shot_types=plan.shot_types, debug_log=_xfade_debug
        )
        for _mde in _xfade_debug:
            debug(f'6/xfade/{_mde["fn"]}', _mde['msg'], level=_mde.get('level', 'DEBUG'))
        if _xfade_str:
            _patched_xfade = _xfade_str
            for _xi in range(n_imgs):
                _patched_xfade = _patched_xfade.replace(f'[{_xi}:v]', f'[vs{_xi}]')
            debug('Stage 6', f'xfade: {len(_xfade_manifest)} transitions (PIL KB)')
            return _scale_prefix + _patched_xfade, True
    except Exception as _xfe:
        log('WARNING', 'Stage 6', f'xfade build failed: {_xfe} — using hard cuts')
        debug('Stage 6', f'xfade exception: {_xfe}', level='ERROR')

    _filter = _scale_prefix
    _filter += ''.join([f'[vs{i}]' for i in range(n_imgs)])
    _filter += f'concat=n={n_imgs}:v=1:a=0[vout]'
    return _filter, False


def ffmpeg_input_args(kb_clips):
    """The `-i` run for every slot clip: loop a motion clip, trim a PIL render, hold a still."""
    _ffmpeg_inputs = []
    for _ktype, _kpath, _kdur in kb_clips:
        if _ktype == 'wan':
            # WAN video clip — stream-loop to cover full slot duration
            _ffmpeg_inputs += ['-stream_loop', '-1', '-t', str(_kdur), '-i', _kpath]
        elif _ktype == 'pil':
            # PIL pre-rendered clip — exact duration baked in; trim for safety
            _ffmpeg_inputs += ['-t', f'{_kdur:.3f}', '-i', _kpath]
        else:
            # Static image fallback
            _ffmpeg_inputs += ['-loop', '1', '-t', str(_kdur), '-i', _kpath]
    return _ffmpeg_inputs


def encode_slideshow(kb_clips, filter_graph, use_xfade, slide_out, tts_dur, kb_tmp_dir, log, debug):
    """Encode the slot clips into *slide_out*; that path on success, None otherwise.

    NVENC first, x264 as the fallback. The Ken Burns temp directory is removed
    either way — but, exactly as the stage did, only when there was something
    to encode at all.
    """
    _ffmpeg_inputs = ffmpeg_input_args(kb_clips)
    if not _ffmpeg_inputs:
        return None
    _slide_base = (
        [exe('ffmpeg'), '-y']
        + _ffmpeg_inputs
        + [
            '-filter_complex',
            filter_graph,
            '-map',
            '[vout]',
        ]
    )
    _slide_nvenc = _slide_base + _nvenc_vcodec_args(_cq_for_crf(20), 'p4') + [slide_out]
    _slide_x264 = _slide_base + _x264_vcodec_args(20, 'fast') + [slide_out]
    _made = None
    try:
        # Timeout scales with video length — a 1424s video can take
        # several minutes to encode; 300s was far too low.
        _slide_timeout = max(900, int(tts_dur * 1.2))
        _slide_r = _ffmpeg_run_nvenc_first(
            _slide_nvenc,
            _slide_x264,
            _slide_timeout,
            label='Stage 6 slideshow',
        )
        if _slide_r.returncode == 0 and os.path.exists(slide_out) and os.path.getsize(slide_out) > 10000:
            _made = slide_out
            log('INFO', 'Stage 6', f'Image slideshow created: {slide_out} (xfade={use_xfade})')
    except Exception as _slide_err:
        _slide_stderr = ''
        if hasattr(_slide_err, 'stderr') and _slide_err.stderr:
            _slide_stderr = _slide_err.stderr.decode('utf-8', errors='replace')[-1000:]
        log('WARNING', 'Stage 6', f'Slideshow creation failed: {_slide_err}')
        debug('Stage 6', f'FFmpeg stderr: {_slide_stderr}', level='ERROR')
    finally:
        # Clean up PIL KB temp clips
        try:
            import shutil as _shu6

            if os.path.isdir(kb_tmp_dir):
                _shu6.rmtree(kb_tmp_dir, ignore_errors=True)
        except OSError as _exc:
            _zyg_log.warning('Ken Burns temp clips left in %s: %s', kb_tmp_dir, _exc)
    return _made
