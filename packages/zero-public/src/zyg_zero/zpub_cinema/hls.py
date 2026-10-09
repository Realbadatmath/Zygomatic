# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""HLS session manager."""

import hashlib
import os
import re
import shutil
import signal
import subprocess
import threading
import time

from .constants import CACHE_DIR, FFPROBE
from .probing import _run
from .playback import transcode_commands

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_cinema')


# ══ HLS sessions ═════════════════════════════════════════════════════════════
# Why HLS exists alongside stream_transcode(): a plain <video src> progressive
# stream is throttled by the BROWSER, not by us. Measured 2026-09-04 with Chrome
# reading from loopback off NVMe with the encoder running 19x realtime — it held
# a flat 2.3-2.4 s of buffer ahead of the playhead and would not fetch more, on
# the direct path and the transcode path alike. Nothing server-side can widen
# that window while the element owns the buffer.
#
# Under Media Source Extensions the PLAYER owns it, so hls.js is told to keep
# ~90 s. That only works if the media arrives as independently addressable
# segments, which is what this layer produces.
#
# Shape: one ffmpeg per session writing fMP4 segments + a growing EVENT playlist
# into its own directory. The client seeks within that playlist for free; a seek
# outside it starts a new session, exactly as the single-stream path did.
HLS_DIR = os.path.join(CACHE_DIR, 'hls')
os.makedirs(HLS_DIR, exist_ok=True)

HLS_SEG_SECONDS = 6  # segment length; measured GOP-length-neutral for bitrate
HLS_LEAD_SECONDS = 180  # how far ahead of the client ffmpeg is allowed to get
HLS_IDLE_TIMEOUT = 90  # kill a session nobody has fetched from for this long
HLS_START_TIMEOUT = 25  # give up on a ladder step that produces no segment
HLS_MIN_FREE_BYTES = 10 * 1024**3  # below this, refuse HLS and fall back

_HLS: dict[str, dict] = {}
_HLS_LOCK = threading.Lock()
_FPS_CACHE: dict[str, float] = {}


def _video_fps(path: str) -> float:
    """Frames per second of the first video stream. Cached; 0.0 when unknown.

    Needed because the segment length is enforced with ``-g`` (a FRAME count):
    h264_nvenc on this build ignores ``-force_key_frames`` — measured, it emitted
    its default 250-frame GOP and the segments came out 10.4 s regardless.
    """
    cached = _FPS_CACHE.get(path)
    if cached is not None:
        return cached
    rc, out, _e = _run(
        [
            FFPROBE,
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=avg_frame_rate,r_frame_rate',
            '-of',
            'csv=p=0',
            path,
        ],
        timeout=30,
    )
    fps = 0.0
    if rc == 0:
        for field in (out.strip().replace('\n', ',')).split(','):
            try:
                num, _, den = field.partition('/')
                v = float(num) / float(den or 1)
            except (TypeError, ValueError, ZeroDivisionError) as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if 1.0 < v < 1000.0:
                fps = v
                break
    _FPS_CACHE[path] = fps
    return fps


def _hls_tail(out_dir: str, gop: int) -> list[str]:
    """Output options that turn any of the ladder's encoders into an HLS writer.

    ``-hls_playlist_type event`` keeps every segment listed, so hls.js can seek
    backwards anywhere inside the session for free. The playlist is rewritten
    after each segment, which is also why a session is torn down with SIGKILL:
    ffmpeg answers SIGTERM by rewriting the playlist EMPTY on its way out
    (measured), and a client still holding it would see the stream vanish.
    """
    return [
        '-g',
        str(gop),
        '-keyint_min',
        str(gop),
        '-map_chapters',
        '-1',
        '-dn',
        '-sn',
        '-f',
        'hls',
        '-hls_time',
        str(HLS_SEG_SECONDS),
        '-hls_playlist_type',
        'event',
        '-hls_list_size',
        '0',
        '-hls_segment_type',
        'fmp4',
        '-hls_fmp4_init_filename',
        'init.mp4',
        '-hls_flags',
        'independent_segments',
        '-hls_segment_filename',
        os.path.join(out_dir, 'seg%05d.m4s'),
        os.path.join(out_dir, 'index.m3u8'),
    ]


def hls_commands(item: dict, start: float, audio_id, burn_sub: str, out_dir: str) -> list[list[str]]:
    """The transcode ladder, rewired to write segments instead of a pipe.

    Same order and same fallbacks as transcode_commands(); only the tail differs,
    so a build without NVDEC still walks down to libx264 the way it always did.
    """
    fps = _video_fps(item['path']) or 24.0
    gop = max(24, int(round(fps * HLS_SEG_SECONDS)))
    tail = _hls_tail(out_dir, gop)
    cmds = []
    for cmd in transcode_commands(item, start, audio_id, burn_sub):
        # Everything from -map_chapters onwards is the pipe tail; replace it.
        cut = cmd.index('-map_chapters')
        cmds.append(cmd[:cut] + tail)
    return cmds


def _hls_read_playlist(out_dir: str) -> tuple[str, int, float]:
    """(playlist text, segment count, seconds of content produced)."""
    try:
        with open(os.path.join(out_dir, 'index.m3u8'), encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return '', 0, 0.0
    durs = [float(x) for x in re.findall(r'#EXTINF:([\d.]+)', text)]
    return text, len(durs), sum(durs)


def _hls_governor(sess: dict) -> None:
    """Hold ffmpeg ~HLS_LEAD_SECONDS ahead of the client, and reap idle sessions.

    Without this the encoder runs at 19x realtime and writes the whole film to
    disk in minutes — ~4.5 GB for a two-hour title, on the same volume the
    library itself lives on. SIGSTOP/SIGCONT is the throttle because it costs
    nothing and leaves the segments already written perfectly valid.
    """
    proc = sess['proc']
    stopped = False
    while True:
        time.sleep(1.0)
        if proc.poll() is not None:
            break
        if time.time() - sess['touched'] > HLS_IDLE_TIMEOUT:
            _zyg_log.info(f'[Cinema] HLS session {sess["id"]} idle — closing')
            break
        _text, n, produced = _hls_read_playlist(sess['dir'])
        sess['segments'] = n
        sess['produced'] = produced
        lead = produced - sess['consumed']
        want_stop = lead > HLS_LEAD_SECONDS
        if want_stop != stopped:
            try:
                proc.send_signal(signal.SIGSTOP if want_stop else signal.SIGCONT)
                stopped = want_stop
            except Exception:  # noqa: BLE001
                break
    close_hls(sess['id'])


def start_hls(item: dict, start: float = 0.0, audio_id=None, burn_sub: str = '') -> dict:
    """Start a session and return once its first segment is playable.

    Returns ``{'id', 'offset', 'duration'}``, or ``{'error': ...}`` when every
    ladder step failed or the disk is too full to hold segments.
    """
    try:
        free = shutil.disk_usage(HLS_DIR).free
    except OSError:
        free = 0
    if free < HLS_MIN_FREE_BYTES:
        return {'error': 'low_disk'}

    sess_id = hashlib.sha1(
        f'{item["id"]}|{start:.3f}|{audio_id}|{burn_sub}|{time.time()}'.encode('utf-8'), usedforsecurity=False
    ).hexdigest()[:16]
    out_dir = os.path.join(HLS_DIR, sess_id)
    os.makedirs(out_dir, exist_ok=True)

    for i, cmd in enumerate(hls_commands(item, start, audio_id, burn_sub, out_dir)):
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + HLS_START_TIMEOUT
        ready = False
        while time.time() < deadline:
            if _hls_read_playlist(out_dir)[1] > 0:
                ready = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.15)
        if ready:
            sess = {
                'id': sess_id,
                'dir': out_dir,
                'proc': proc,
                'item': item['id'],
                'offset': start,
                'touched': time.time(),
                'consumed': 0.0,
                'segments': 0,
                'produced': 0.0,
            }
            with _HLS_LOCK:
                _HLS[sess_id] = sess
            threading.Thread(target=_hls_governor, args=(sess,), daemon=True, name=f'cinema-hls-{sess_id}').start()
            return {'id': sess_id, 'offset': start, 'duration': float(item.get('duration') or 0)}
        err = b''
        try:
            proc.kill()
            err = (proc.stderr.read() or b'')[:300]
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        _zyg_log.info(f'[Cinema] HLS step {i + 1} produced no segment: {err.decode("utf-8", "replace").strip()}')
        for name in os.listdir(out_dir):
            try:
                os.remove(os.path.join(out_dir, name))
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

    shutil.rmtree(out_dir, ignore_errors=True)
    return {'error': 'transcode_failed'}


def get_hls(sess_id: str) -> dict | None:
    with _HLS_LOCK:
        sess = _HLS.get(sess_id)
    if sess:
        sess['touched'] = time.time()
    return sess


def note_hls_segment(sess: dict, index: int) -> None:
    """Record how far the client has actually pulled, for the lead governor."""
    sess['consumed'] = max(sess['consumed'], (index + 1) * float(HLS_SEG_SECONDS))


def close_hls(sess_id: str) -> None:
    with _HLS_LOCK:
        sess = _HLS.pop(sess_id, None)
    if not sess:
        return
    proc = sess['proc']
    try:
        if proc.poll() is None:
            # SIGCONT first: a SIGSTOPped process never reaches its own kill.
            try:
                proc.send_signal(signal.SIGCONT)
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            proc.kill()  # SIGKILL, see _hls_tail
            proc.wait(timeout=5)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    shutil.rmtree(sess['dir'], ignore_errors=True)


def sweep_hls() -> int:
    """Delete session directories no live session owns. Called at import."""
    n = 0
    with _HLS_LOCK:
        live = set(_HLS)
    try:
        for name in os.listdir(HLS_DIR):
            if name in live:
                continue
            shutil.rmtree(os.path.join(HLS_DIR, name), ignore_errors=True)
            n += 1
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return n


sweep_hls()


def _norm_title(t: str | None) -> str:
    """Case/punctuation-insensitive title key ('Godzilla Vs. Kong' == 'Godzilla vs Kong')."""
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()


def version_suffixes(items: list[dict]) -> dict[str, str]:
    """Map item id -> 'V1'/'V2'/... where several FILES are the same MOVIE.

    Keyed on normalised title AND year together, which is what keeps sequels and
    remakes out of it: 'Deadpool' (2016) and 'Deadpool 2' (2018) differ in the
    title, 'The Thing' (1982) and (2011) differ in the year, so neither pair can
    ever be labelled versions of one another. Only a genuine second copy of the
    same release year and name — e.g. the .mkv/DTS and .mp4/AAC rips of Gods of
    Egypt (2016) — collides.

    Ordered best-copy-first (widest, then largest) so V1 is the one to watch, and
    deterministically, so the labels never shuffle between page loads.
    """
    groups: dict[tuple, list[dict]] = {}
    for it in items:
        if it.get('kind') == 'episode':
            continue
        title = _norm_title(it.get('title'))
        if not title:
            continue
        groups.setdefault((title, it.get('year')), []).append(it)
    out: dict[str, str] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda i: (-(i.get('width') or 0), -(i.get('size') or 0), i.get('filename', ''), i.get('id', ''))
        )
        for n, it in enumerate(group, 1):
            out[it['id']] = f'V{n}'
    return out
