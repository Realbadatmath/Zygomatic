# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Transcode command ladders and progressive streaming."""

import subprocess

from .constants import FFMPEG, FFPROBE
from .probing import _run

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_cinema')


# ══ Playback ══════════════════════════════════════════════════════════════════
NVENC_MAX_HEIGHT = 1080  # transcoded output is capped here; 4K→1080 runs 6x realtime


def _audio_order(item: dict, audio_id) -> int:
    """Map a requested audio selection to its ffmpeg ``0:a:<n>`` index."""
    tracks = item.get('audio') or []
    if not tracks:
        return 0
    try:
        n = int(audio_id)
    except (TypeError, ValueError):
        n = -1
    if 0 <= n < len(tracks):
        return n
    for i, t in enumerate(tracks):
        if t.get('default'):
            return i
    return 0


def transcode_commands(item: dict, start: float = 0.0, audio_id=None, burn_sub: str = '') -> list[list[str]]:
    """ffmpeg command ladder for ``item``: try each in order until one produces output.

    Ordered cheapest-first. Measured 2026-08-30 on this box (RTX 4090):
      remux (-c:v copy)                    ~60x realtime
      full-GPU NVDEC→scale_cuda→NVENC      ~17x realtime (1080p) / ~6x (4K)
      CPU decode → NVENC                   ~6.5x realtime (4K)
    """
    path = item['path']
    a_ord = _audio_order(item, audio_id)
    a_copy = bool(item.get('audio_copy'))
    height = int(item.get('height') or 0)
    needs_scale = height > NVENC_MAX_HEIGHT

    burn = next(
        (
            s
            for s in item.get('subs') or []
            if s.get('id') == burn_sub and s.get('kind') == 'embedded' and not s.get('text')
        ),
        None,
    )

    def _pre() -> list[str]:
        c = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin']
        if start > 0.1:
            c += ['-ss', f'{start:.3f}']
        return c

    def _audio() -> list[str]:
        if a_copy:
            return ['-c:a', 'copy']
        return ['-c:a', 'aac', '-b:a', '192k', '-ac', '2']

    def _tail() -> list[str]:
        # -map_chapters -1: an MKV's chapter list is otherwise muxed into the MP4
        # as a 'text' track (measured on Gods of Egypt — ffprobe reported a third
        # bin_data stream). -dn/-sn do NOT remove it; only dropping chapters does.
        return [
            '-map_chapters',
            '-1',
            '-dn',
            '-sn',
            '-movflags',
            'frag_keyframe+empty_moov+default_base_moof',
            '-f',
            'mp4',
            'pipe:1',
        ]

    cmds: list[list[str]] = []

    # 1 ── Remux: video already browser-safe, only the container/audio is wrong.
    if item.get('video_copy') and not burn:
        cmds.append(_pre() + ['-i', path, '-map', '0:v:0', '-map', f'0:a:{a_ord}', '-c:v', 'copy'] + _audio() + _tail())

    nvenc = ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', '25', '-b:v', '0', '-profile:v', 'high']

    if burn:
        # PGS/VOBSUB are bitmaps — the only way to show them is to paint them on.
        # Overlay BEFORE scaling: the subtitle bitmaps carry the source geometry,
        # so scaling first puts them in the wrong place.
        chain = f'[0:v][0:s:{burn.get("stream", 0)}]overlay[o];[o]'
        chain += f'scale=-2:{NVENC_MAX_HEIGHT},' if needs_scale else ''
        chain += 'format=yuv420p[vo]'
        cmds.append(
            _pre()
            + ['-i', path, '-filter_complex', chain, '-map', '[vo]', '-map', f'0:a:{a_ord}']
            + nvenc
            + _audio()
            + _tail()
        )
        cmds.append(
            _pre()
            + [
                '-i',
                path,
                '-filter_complex',
                chain,
                '-map',
                '[vo]',
                '-map',
                f'0:a:{a_ord}',
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '23',
                '-threads',
                '8',
            ]
            + _audio()
            + _tail()
        )
        return cmds

    # 2 ── Full-GPU: NVDEC decode → scale_cuda → NVENC. Never leaves the card.
    gpu_vf = f'scale_cuda=-2:{NVENC_MAX_HEIGHT}:format=yuv420p' if needs_scale else 'scale_cuda=format=yuv420p'
    cmds.append(
        _pre()[:1]
        + ['-hide_banner', '-loglevel', 'error', '-nostdin', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda']
        + (['-ss', f'{start:.3f}'] if start > 0.1 else [])
        + ['-i', path, '-map', '0:v:0', '-map', f'0:a:{a_ord}', '-vf', gpu_vf]
        + nvenc
        + _audio()
        + _tail()
    )

    # 3 ── CPU decode → NVENC. `format=yuv420p` is REQUIRED, not cosmetic:
    #      h264_nvenc refuses 10-bit input ("10 bit encode not supported"), and
    #      the software scaler preserves yuv420p10le, so without it every
    #      10-bit HEVC title dies with zero frames written.
    cpu_vf = (f'scale=-2:{NVENC_MAX_HEIGHT},' if needs_scale else '') + 'format=yuv420p'
    cmds.append(
        _pre() + ['-i', path, '-map', '0:v:0', '-map', f'0:a:{a_ord}', '-vf', cpu_vf] + nvenc + _audio() + _tail()
    )

    # 4 ── No GPU at all.
    cmds.append(
        _pre()
        + [
            '-i',
            path,
            '-map',
            '0:v:0',
            '-map',
            f'0:a:{a_ord}',
            '-vf',
            cpu_vf,
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '23',
            '-threads',
            '8',
        ]
        + _audio()
        + _tail()
    )
    return cmds


def keyframe_before(path: str, t: float, window: float = 12.0) -> float:
    """Timestamp of the last video keyframe at or before ``t``.

    Only meaningful for the ``-c:v copy`` path. ffmpeg cannot start a copied
    stream anywhere but a keyframe, so asking for t=600 on a title whose
    keyframes sit at 596.262 and 606.272 silently yields content that begins
    3.7 s early — measured on "Gods of Egypt". Every subtitle would then be
    3.7 s out. The client is told the REAL start instead of the requested one.
    """
    if t <= 0.1:
        return 0.0
    lo = max(0.0, t - window)
    rc, out, _e = _run(
        [
            FFPROBE,
            '-v',
            'error',
            '-read_intervals',
            f'{lo:.3f}%{t + 0.5:.3f}',
            '-select_streams',
            'v:0',
            '-skip_frame',
            'nokey',
            '-show_entries',
            'frame=pts_time',
            '-of',
            'csv=p=0',
            path,
        ],
        timeout=45,
    )
    if rc != 0:
        return t
    best = None
    for line in out.splitlines():
        line = line.strip().rstrip(',')
        if not line:
            continue
        try:
            v = float(line)
        except ValueError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        if v <= t + 0.001 and (best is None or v > best):
            best = v
    if best is not None:
        return best
    # Nothing in the window — widen once before giving up on the request value.
    if window < 60:
        return keyframe_before(path, t, window * 4)
    return t


def exact_start(item: dict, t: float, burn_sub: str = '') -> float:
    """The timestamp playback will ACTUALLY begin at for a transcode request."""
    if t <= 0.1:
        return 0.0
    burn = next(
        (
            s
            for s in item.get('subs') or []
            if s.get('id') == burn_sub and s.get('kind') == 'embedded' and not s.get('text')
        ),
        None,
    )
    # Re-encoding paths decode from the keyframe and drop frames before the seek
    # point, so -ss is frame-accurate there and t is already exact.
    if item.get('video_copy') and not burn:
        return keyframe_before(item['path'], t)
    return t


def stream_transcode(item: dict, start: float = 0.0, audio_id=None, burn_sub: str = ''):
    """Yield fragmented-MP4 bytes, falling forward through the command ladder.

    A command that dies before emitting a single byte was rejected by ffmpeg
    (missing NVDEC support, a pixel format the encoder won't take); that is
    recoverable, so the next command in the ladder is tried. Once bytes are
    flowing the client is committed and a later failure just ends the stream.
    """
    cmds = transcode_commands(item, start, audio_id, burn_sub)
    for i, cmd in enumerate(cmds):
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            first = proc.stdout.read(65536)
            if not first:
                err = b''
                try:
                    proc.kill()
                    err = (proc.stderr.read() or b'')[:300]
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                _zyg_log.info(
                    f'[Cinema] transcode step {i + 1}/{len(cmds)} produced nothing: '
                    f'{err.decode("utf-8", "replace").strip()}'
                )
                continue
            yield first
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
            return
        except GeneratorExit:
            # Client seeked or closed the tab — stop encoding immediately.
            if proc:
                try:
                    proc.kill()
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            return
        except Exception as exc:  # noqa: BLE001
            _zyg_log.info(f'[Cinema] transcode error: {exc}')
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    _zyg_log.info('[Cinema] every transcode path failed')
