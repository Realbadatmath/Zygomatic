# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encoder helpers behind `stage_04_clip_mux.mux_clips`.

`mux_clips` was one 420-line loop: probe the narration, trim or smart-loop the
WAN clip, fall back to a Ken Burns move over the still, then mux the narration
and the foley. Each of those is a step with a name, so each is a function here
and the loop keeps only the order.

The ffmpeg command builders (`trim_args`, `crossfade_args`, `stream_loop_args`,
`pingpong_args`, `manga_panel_args`, `kenburns_args`, `mux_audio_args`) and the
two filter/strategy functions (`kenburns_filter`, `wants_crossfade_loop`) are
pure: they take values and return a list or a string, touch no disk and run no
subprocess, which is what makes them unit-testable
(`tests/test_stage_04_clip_mux_helpers.py`).
"""

import os

from zyg_workflows.bin import exe

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')

#: The deliverable frame every clip is letterboxed into.
SCALE_PAD_1080 = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black'

#: Forward plus a reversed copy, concatenated: a palindrome loop with no hard cut.
PINGPONG_FILTER = '[0:v]reverse[r];[0:v][r]concat=n=2:v=1:a=0[pp]'

#: The intermediate codec every per-scene clip is written with — lossless, so the
#: final assembly pass is the only generation loss in the whole pipeline.
_X264_LOSSLESS = ('-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-pix_fmt', 'yuv420p', '-an')

#: scene_type → the emotion whose pan speed the Ken Burns move borrows.
KENBURNS_EMOTION = {
    'character': 'calm',
    'action': 'tension',
    'environment': 'awe',
    'atmosphere': 'mystery',
    'crowd': 'triumph',
}

#: emotion → pan/zoom speed multiplier.
KENBURNS_SPEED = {'calm': 0.70, 'mystery': 0.80, 'awe': 1.0, 'triumph': 1.1, 'tension': 1.4}

#: A clip smaller than this is ffmpeg's idea of a file, not a video.
MIN_CLIP_BYTES = 1000


def _usable(path):
    """True when *path* exists and is bigger than a stub — ffmpeg's success test."""
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > MIN_CLIP_BYTES


# ── durations ────────────────────────────────────────────────────────────────


def measure_tts_duration(sp, json_mod, tts, default):
    """Probe the narration file for its real length in seconds.

    Returns *default* when there is no narration file or the probe fails: the
    probe is advisory, the planned scene duration is the contract.
    """
    if not (tts and os.path.exists(tts)):
        return default
    try:
        pb = sp.run(
            [exe('ffprobe'), '-v', 'quiet', '-show_format', '-of', 'json', tts],
            capture_output=True,
            timeout=10,
        )
        return float(json_mod.loads(pb.stdout).get('format', {}).get('duration', default))
    except Exception as _exc:
        _zyg_log.warning('TTS duration probe failed, using the planned scene duration: %s', _exc)
        return default


def measure_clip_duration(sp, clip):
    """Probe a rendered WAN clip for its length in seconds; 0.0 when unreadable."""
    try:
        wpb = sp.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                clip,
            ],
            capture_output=True,
            timeout=10,
        )
        return float(wpb.stdout.decode().strip() or '0')
    except Exception as _exc:
        _zyg_log.warning('WAN clip duration probe failed, treating the clip as 0 s: %s', _exc)
        return 0.0


# ── pure ffmpeg command builders ─────────────────────────────────────────────


def trim_args(src, duration, out):
    """ffmpeg args that cut *src* down to *duration* — the narration fits inside it."""
    return [exe('ffmpeg'), '-y', '-i', src, '-t', str(duration), '-vf', SCALE_PAD_1080, *_X264_LOSSLESS, out]


def crossfade_args(src, clip_dur, xf_dur, out):
    """ffmpeg args that blend *src*'s tail back over its head, hiding the loop seam."""
    return [
        exe('ffmpeg'),
        '-y',
        '-i',
        src,
        '-vf',
        crossfade_filter(clip_dur, xf_dur),
        '-map',
        '[outv]',
        *_X264_LOSSLESS,
        out,
    ]


def crossfade_filter(clip_dur, xf_dur):
    """The xfade graph that cross-dissolves the last *xf_dur* seconds into the start."""
    return (
        f'[0:v]split[v1][v2];'
        f'[v2]trim=start={max(0.0, clip_dur - xf_dur)},setpts=PTS-STARTPTS[tail];'
        f'[v1][tail]xfade=transition=fade:duration={xf_dur}:offset={clip_dur - xf_dur}[outv]'
    )


def stream_loop_args(src, duration, out):
    """ffmpeg args that repeat *src* until *duration* is filled, then letterbox it."""
    return [
        exe('ffmpeg'),
        '-y',
        '-stream_loop',
        '-1',
        '-i',
        src,
        '-t',
        str(duration),
        '-vf',
        SCALE_PAD_1080,
        *_X264_LOSSLESS,
        out,
    ]


def pingpong_args(src, out):
    """ffmpeg args for the palindrome (forward + reverse) variant of *src*."""
    return [
        exe('ffmpeg'),
        '-y',
        '-i',
        src,
        '-filter_complex',
        PINGPONG_FILTER,
        '-map',
        '[pp]',
        *_X264_LOSSLESS,
        out,
    ]


def manga_panel_args(img, duration, out):
    """ffmpeg args for a held manga panel: one frame a second, no camera move."""
    return [
        exe('ffmpeg'),
        '-y',
        '-loop',
        '1',
        '-i',
        img,
        '-t',
        str(duration),
        '-vf',
        SCALE_PAD_1080,
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-crf',
        '0',
        '-r',
        '1',
        '-pix_fmt',
        'yuv420p',
        '-an',
        out,
    ]


def kenburns_args(img, duration, vf, out):
    """ffmpeg args for a Ken Burns move over *img*; *vf* comes from `kenburns_filter`.

    The input is held half a second longer than the output so the zoompan pass
    never runs out of source on the last frame.
    """
    return [
        exe('ffmpeg'),
        '-y',
        '-loop',
        '1',
        '-t',
        str(duration + 0.5),
        '-i',
        img,
        '-vf',
        vf,
        '-t',
        str(duration),
        *_X264_LOSSLESS,
        out,
    ]


def mux_audio_args(video_src, audio, out):
    """ffmpeg args that put *audio* on *video_src* without re-encoding the video."""
    return [
        exe('ffmpeg'),
        '-y',
        '-i',
        video_src,
        '-i',
        audio,
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-c:v',
        'copy',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-shortest',
        out,
    ]


# ── pure strategy / filter choices ───────────────────────────────────────────


def wants_crossfade_loop(scene_meta):
    """True when the scene is a close read of a face, so a hard loop cut would show.

    Close-ups, extreme shots, portraits and character scenes get the cross-fade
    loop; everything wider gets the ping-pong.
    """
    stype = str(scene_meta.get('scene_type', '')).lower()
    shot = str(scene_meta.get('shot_type', '')).lower()
    return 'close-up' in shot or 'extreme' in shot or stype == 'character' or 'portrait' in shot


def kenburns_filter(scene_index, scene_meta, duration):
    """The zoompan filter chain for a static scene image.

    Close shots push in on the upper third, wide shots pan sideways (alternating
    direction by *scene_index* so two neighbouring wides do not drift the same
    way), everything else pushes in on centre. *duration* sets the frame count.
    """
    shot = str(scene_meta.get('shot_type', '')).lower()
    stype = str(scene_meta.get('scene_type', '')).lower()
    # Map scene_type to emotion for speed multiplier
    emotion = KENBURNS_EMOTION.get(stype, 'calm')
    speed = KENBURNS_SPEED.get(emotion, 1.0)
    delta = 0.0003 * speed
    frames = max(1, int(duration * 30))
    if 'close' in shot or 'extreme' in shot or 'portrait' in shot:
        zoom = f'min(1.0+(on+1)*{delta:.6f},1.3)'
        pan_x = 'iw/2-iw/zoom/2'
        pan_y = 'ih/5-ih/zoom/5'
    elif 'wide' in shot or 'establish' in shot or 'aerial' in shot:
        rate = delta * 0.4
        zoom = '1.08'
        pan_x = (
            f'min(iw*{rate:.6f}*on,iw*(1-1/zoom))' if scene_index % 2 == 0 else f'max(iw*(1-1/zoom)-iw*{rate:.6f}*on,0)'
        )
        pan_y = 'ih/2-ih/zoom/2'
    else:
        zoom = f'min(1.0+(on+1)*{delta:.6f},1.25)'
        pan_x = 'iw/2-iw/zoom/2'
        pan_y = 'ih/2-ih/zoom/2'
    return (
        f'scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,'
        f'setsar=1,'
        f"zoompan=z='{zoom}':x='{pan_x}':y='{pan_y}':d={frames}:s=1920x1080:fps=30,"
        f'scale=1920:1080,format=yuv420p,setpts=PTS-STARTPTS'
    )


# ── the video source for one scene ───────────────────────────────────────────


def _loop_source(sp, wan_clip, looped, clip_dur, scene_meta):
    """Pre-process *wan_clip* into a seamlessly loopable intermediate.

    Returns (source_path, scratch_path, label): the source to stream-loop from
    (the intermediate when it encoded, else *wan_clip*), the scratch file to
    delete afterwards, and the strategy's name for the cleanup log line.
    """
    if wants_crossfade_loop(scene_meta):
        # Crossfade loop: blend end→start to hide seam, then stream-loop
        xf_dur = max(0.5, clip_dur * 0.08)  # 8% of clip, min 0.5 s
        scratch = looped + '_xftmp.mp4'
        label = 'crossfade loop'
        res = sp.run(crossfade_args(wan_clip, clip_dur, xf_dur, scratch), capture_output=True, timeout=120)
    else:
        # Ping-pong (palindrome) loop: forward + reverse → seamless reversal
        # Great for wide/action/atmospheric scenes — no hard cut
        scratch = looped + '_pp.mp4'
        label = 'ping-pong loop'
        res = sp.run(pingpong_args(wan_clip, scratch), capture_output=True, timeout=180)
    return (scratch if (res.returncode == 0 and _usable(scratch)) else wan_clip), scratch, label


def build_looped_clip(sp, clips_dir, scene_index, wan_clip, tts_dur, scene_meta):
    """Fit the rendered WAN clip to the narration; returns the clip path or None.

    Narration shorter than the clip is a plain trim. Narration longer means a
    loop, and which loop depends on the shot: `wants_crossfade_loop` decides.
    """
    looped = os.path.join(clips_dir, f'clip_{scene_index:04d}_looped.mp4')
    wan_dur = measure_clip_duration(sp, wan_clip)
    if tts_dur <= wan_dur:
        # TTS fits inside the WAN clip — simple trim, no looping needed
        res = sp.run(trim_args(wan_clip, tts_dur, looped), capture_output=True, timeout=180)
    else:
        # TTS overruns clip — choose loop strategy based on scene metadata
        src, scratch, label = _loop_source(sp, wan_clip, looped, wan_dur, scene_meta)
        res = sp.run(stream_loop_args(src, tts_dur, looped), capture_output=True, timeout=180)
        try:
            if os.path.exists(scratch):
                os.remove(scratch)
        except OSError as _exc:
            _zyg_log.debug('%s scratch file cleanup skipped: %s', label, _exc)
    return looped if (res.returncode == 0 and _usable(looped)) else None


def build_static_clip(sp, clips_dir, scene_index, img, tts_dur, scene_meta, job, manga_mode):
    """Fall back to the scene still; returns the clip path or None.

    A manga page at one frame a second is held flat — a camera move over a comic
    panel reads as a mistake. Everything else gets a Ken Burns move.
    """
    static = os.path.join(clips_dir, f'clip_{scene_index:04d}_static.mp4')
    panel_fps = int((job.get('pipeline_options') or {}).get('manga_panel_fps') or 30)
    if manga_mode and panel_fps <= 1:
        args = manga_panel_args(img, tts_dur, static)
    else:
        args = kenburns_args(img, tts_dur, kenburns_filter(scene_index, scene_meta, tts_dur), static)
    res = sp.run(args, capture_output=True, timeout=90)
    return static if (res.returncode == 0 and _usable(static)) else None


# ── narration and foley ──────────────────────────────────────────────────────


def foley_over_narration(audio_svc, scene_desc, tts, tts_dur, tts_dir, scene_index, log):
    """Mix ambient SFX into the narration track; returns the audio path to mux.

    Falls back to the plain narration whenever there is no audio service, no
    scene description, no matching foley, or the mix fails.
    """
    if not (audio_svc and scene_desc):
        return tts
    foley_list = audio_svc.get_foley_for_scene(
        scene_desc,
        max_foley=2,
        log_fn=lambda m: log('INFO', 'Stage 4', m),
    )
    if not foley_list:
        return tts
    foley_out = os.path.join(tts_dir, f'tts_{scene_index:04d}_foley.mp3')
    if audio_svc.mix_foley_into_audio(
        tts,
        foley_list,
        foley_out,
        tts_dur,
        log_fn=lambda m: log('INFO', 'Stage 4', m),
    ):
        foley_names = [os.path.basename(p) for p, _ in foley_list]
        log('INFO', 'Stage 4', f'Scene {scene_index} foley: {foley_names}')
        return foley_out
    log('WARNING', 'Stage 4', f'Scene {scene_index} foley mix failed — using plain TTS')
    return tts


def mux_narrated_clip(sp, clips_dir, scene_index, video_src, audio, log):
    """Mux *audio* onto *video_src*; returns the clip to deliver.

    On an ffmpeg failure the video-only clip ships rather than nothing — a scene
    with no sound is a defect, a missing scene is a hole.
    """
    muxed = os.path.join(clips_dir, f'clip_{scene_index:04d}.mp4')
    res = sp.run(mux_audio_args(video_src, audio, muxed), capture_output=True, timeout=90)
    if res.returncode == 0 and _usable(muxed):
        return muxed
    log('WARNING', 'Stage 4', f'Audio mux failed scene {scene_index} — using video-only clip')
    return video_src


def foley_only_clip(audio_svc, clips_dir, scene_index, video_src, scene_desc, tts_dur, log):
    """No narration: lay the foley straight into the video's audio track.

    Returns the foley-mixed clip, or None when there is nothing to mix in — the
    caller then ships *video_src* untouched.
    """
    if not (audio_svc and scene_desc and video_src and os.path.exists(video_src)):
        return None
    foley_list = audio_svc.get_foley_for_scene(
        scene_desc,
        max_foley=2,
        log_fn=lambda m: log('INFO', 'Stage 4', m),
    )
    if not foley_list:
        return None
    foley_muxed = os.path.join(clips_dir, f'clip_{scene_index:04d}_foley.mp4')
    if not audio_svc.mix_foley_into_video(
        video_src,
        foley_list,
        foley_muxed,
        tts_dur,
        log_fn=lambda m: log('INFO', 'Stage 4', m),
    ):
        return None
    foley_names = [os.path.basename(p) for p, _ in foley_list]
    log('INFO', 'Stage 4', f'Scene {scene_index} foley (no-TTS): {foley_names}')
    return foley_muxed
