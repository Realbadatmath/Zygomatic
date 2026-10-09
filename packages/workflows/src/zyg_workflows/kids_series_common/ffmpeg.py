# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common.py — ffmpeg helpers (lines 169-508 of the pre-split file, verbatim)."""

from __future__ import annotations

import logging as _zyg_logging
from .constants import json, os, shutil, subprocess, tempfile, _seal, W, H, FPS, FFMPEG, FFPROBE, SR

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.kids_series_common')


# ── ffmpeg helpers ───────────────────────────────────────────────────────────


def _run(cmd, timeout=900):
    """Run a command, swallow its chatter, return True on exit 0."""
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def probe(path):
    """{'duration', 'has_audio', 'w', 'h'} — zeros/False when unreadable."""
    out = {'duration': 0.0, 'has_audio': False, 'w': 0, 'h': 0}
    if not os.path.isfile(path):
        return out
    try:
        r = subprocess.run(
            [FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        info = json.loads(r.stdout.decode() or '{}')
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    try:
        out['duration'] = float((info.get('format') or {}).get('duration') or 0.0)
    except (TypeError, ValueError):
        out['duration'] = 0.0
    for st in info.get('streams') or []:
        if st.get('codec_type') == 'audio':
            out['has_audio'] = True
        elif st.get('codec_type') == 'video' and not out['w']:
            out['w'] = int(st.get('width') or 0)
            out['h'] = int(st.get('height') or 0)
            if not out['duration']:
                try:
                    out['duration'] = float(st.get('duration') or 0.0)
                except (TypeError, ValueError) as _exc:
                    _zyg_log.debug('ffprobe duration not numeric, left at 0.0: %s', _exc)
    return out


_NORM_VF = f'scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:-1:-1,fps={FPS},format=yuv420p,setsar=1'


def frames_to_clip(pattern, out_mp4, fps=FPS):
    """A printf-style frame sequence -> one 1280x720 h264 clip, no audio."""
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    return _run(
        [
            FFMPEG,
            '-y',
            '-framerate',
            str(int(fps)),
            '-i',
            pattern,
            '-vf',
            _NORM_VF,
            '-r',
            str(FPS),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-an',
            out_mp4,
        ]
    )


def zoompan_clip(png, out_mp4, seconds, *, direction='in', fps=FPS):
    """A still -> a slow Ken Burns move.  'in' pushes to 1.25, 'out' pulls back.

    The source is upscaled to 8000 px wide first: zoompan samples the INPUT, so
    zooming a 1280-wide still directly is a crop of a small picture and it
    shimmers.  That scale is why this is one filter chain and not two.
    """
    seconds = max(0.2, float(seconds))
    fps = int(fps)
    d = max(1, int(round(seconds * fps)))
    step = 0.25 / d
    if str(direction).lower() == 'out':
        z = f"'max(1.25-{step:.8f}*on,1.0)'"
    else:
        z = f"'min(1.0+{step:.8f}*on,1.25)'"
    vf = f"scale=8000:-1,zoompan=z={z}:d={d}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps}"
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    return _run(
        [
            FFMPEG,
            '-y',
            '-loop',
            '1',
            '-i',
            png,
            '-vf',
            vf,
            '-t',
            f'{seconds:.3f}',
            '-r',
            str(FPS),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-an',
            out_mp4,
        ]
    )


def _normalise_clip(src, dst):
    return _run(
        [
            FFMPEG,
            '-y',
            '-i',
            src,
            '-vf',
            _NORM_VF,
            '-r',
            str(FPS),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-an',
            dst,
        ]
    )


def concat_clips(clips, out_mp4, *, xfade=0.5):
    """Join clips into one 1280x720@24 video.

    Every input is normalised first — a chain that mixes sizes or frame rates
    is where xfade silently produces a black half-second — and only then does
    the crossfade chain run.  ``xfade <= 0`` is a hard cut through the concat
    demuxer; one clip is just the normalised copy.
    """
    clips = [c for c in (clips or []) if c and os.path.isfile(c)]
    if not clips:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    work = tempfile.mkdtemp(prefix='kseries_cat_')
    try:
        norm, lens = [], []
        for i, c in enumerate(clips):
            n = os.path.join(work, f'n{i:03d}.mp4')
            if not _normalise_clip(c, n):
                return False
            d = probe(n)['duration']
            if d <= 0:
                return False
            norm.append(n)
            lens.append(d)
        if len(norm) == 1:
            shutil.copy(norm[0], out_mp4)
            return os.path.isfile(out_mp4)

        if float(xfade) <= 0:
            lst = os.path.join(work, 'list.txt')
            with open(lst, 'w') as fh:
                for n in norm:
                    fh.write("file '%s'\n" % n.replace("'", r"'\''"))
            return _run(
                [
                    FFMPEG,
                    '-y',
                    '-f',
                    'concat',
                    '-safe',
                    '0',
                    '-i',
                    lst,
                    '-c:v',
                    'libx264',
                    '-preset',
                    'veryfast',
                    '-crf',
                    '20',
                    '-pix_fmt',
                    'yuv420p',
                    '-an',
                    out_mp4,
                ]
            )

        # xfade OVERLAPS its inputs, so the offset of transition j is the sum of
        # the clips before it minus every transition already spent.  Getting
        # that arithmetic wrong does not error — it just drops the tail.
        n = len(norm)
        t = min(float(xfade), 0.45 * min(lens))
        t = max(0.05, t)
        parts, cur, off = [], '[0:v]', 0.0
        for j in range(n - 1):
            off = off + lens[j] - t
            lbl = '[vout]' if j == n - 2 else f'[x{j:03d}]'
            parts.append(f'{cur}[{j + 1}:v]xfade=transition=fade:duration={t:.3f}:offset={max(0.0, off):.3f}{lbl}')
            cur = lbl
        cmd = [FFMPEG, '-y']
        for p in norm:
            cmd += ['-i', p]
        cmd += [
            '-filter_complex',
            ';'.join(parts),
            '-map',
            '[vout]',
            '-r',
            str(FPS),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-an',
            out_mp4,
        ]
        return _run(cmd)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def mix_audio(tracks, out_wav, total_s):
    """[(wav, start_s, gain_db)] -> one 48 kHz bed, limited then normalised.

    THE LIMITER RUNS BEFORE loudnorm, not after.  Normalising first and then
    limiting undoes the measurement the normaliser just made; this order is the
    house lesson from the music workflow and it is not a matter of taste.
    """
    usable = [(p, float(s), float(g)) for (p, s, g) in (tracks or []) if p and os.path.isfile(p)]
    total_s = max(0.1, float(total_s))
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)) or '.', exist_ok=True)
    if not usable:
        return _run(
            [
                FFMPEG,
                '-y',
                '-f',
                'lavfi',
                '-i',
                f'anullsrc=r={SR}:cl=mono',
                '-t',
                f'{total_s:.3f}',
                '-c:a',
                'pcm_s16le',
                out_wav,
            ]
        )
    cmd = [FFMPEG, '-y']
    for p, _s, _g in usable:
        cmd += ['-i', p]
    legs = []
    for i, (_p, s, g) in enumerate(usable):
        legs.append(
            f'[{i}:a]aformat=sample_rates={SR}:channel_layouts=stereo,'
            f'volume={g:.2f}dB,adelay={int(max(0.0, s) * 1000)}:all=1'
            f'[a{i}]'
        )
    chain = ''.join(f'[a{i}]' for i in range(len(usable)))
    graph = (
        ';'.join(legs) + ';' + chain + f'amix=inputs={len(usable)}:normalize=0:duration=longest,'
        f'alimiter=limit=0.94,loudnorm=I=-16:TP=-1:LRA=11,'
        f'atrim=0:{total_s:.3f},apad=whole_dur={total_s:.3f},'
        f'aformat=sample_rates={SR}[aout]'
    )
    cmd += ['-filter_complex', graph, '-map', '[aout]', '-c:a', 'pcm_s16le', out_wav]
    return _run(cmd)


def mux(video_mp4, audio_wav, out_mp4):
    """Video + bed -> the deliverable: h264 yuv420p + aac, faststart."""
    if not (os.path.isfile(video_mp4) and os.path.isfile(audio_wav)):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    ok = _run(
        [
            FFMPEG,
            '-y',
            '-i',
            video_mp4,
            '-i',
            audio_wav,
            '-map',
            '0:v:0',
            '-map',
            '1:a:0',
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-c:a',
            'aac',
            '-b:a',
            '160k',
            '-shortest',
            '-movflags',
            '+faststart',
            out_mp4,
        ]
    )
    if ok:
        _seal.seal(out_mp4, pipeline='kids_series', run_id='', log_fn=_zyg_log.info)
    return ok


def write_poster(mp4, jpg):
    """One frame at 1 s.  The thumbnail the board and the store both show."""
    if not os.path.isfile(mp4):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(jpg)) or '.', exist_ok=True)
    at = '1.0' if probe(mp4)['duration'] > 1.2 else '0.0'
    ok = _run([FFMPEG, '-y', '-ss', at, '-i', mp4, '-frames:v', '1', '-q:v', '3', jpg]) and os.path.isfile(jpg)
    if ok:
        _seal.seal(jpg, pipeline='kids_series', run_id='', log_fn=_zyg_log.info)
    return ok
