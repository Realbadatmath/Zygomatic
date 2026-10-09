# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Export to the deliverable formats, and the content types."""

from zyg_workflows.bin import exe
import hashlib
import os
from zyg_workflows.sfx_merger.constants import _SR, _WORK, _zyg_log
from zyg_workflows.sfx_merger.render import _dirs, _lock, _run, render_mix

# ── export ────────────────────────────────────────────────────────────────────
_EXPORT_FORMATS = {
    'wav16': ('wav', ['-c:a', 'pcm_s16le']),
    'wav24': ('wav', ['-c:a', 'pcm_s24le']),
    'wav32': ('wav', ['-c:a', 'pcm_f32le']),
    'flac': ('flac', ['-c:a', 'flac', '-compression_level', '8']),
    'mp3': ('mp3', ['-c:a', 'libmp3lame', '-b:a', '320k']),
    'ogg': ('ogg', ['-c:a', 'libvorbis', '-q:a', '7']),
    'opus': ('opus', ['-c:a', 'libopus', '-b:a', '192k']),
    'aiff': ('aiff', ['-c:a', 'pcm_s16be']),
}
_DITHERS_OK = (
    'rectangular',
    'triangular',
    'triangular_hp',
    'lipshitz',
    'shibata',
    'low_shibata',
    'high_shibata',
    'f_weighted',
    'modified_e_weighted',
    'improved_e_weighted',
)


def export_mix(items, fmt='wav24', rate=48000, dither='triangular_hp'):
    """Render the merge and encode it for delivery. Separate from save_mix on
    purpose: save_mix puts a licensed asset in the library, export hands you a
    file. Neither is the other."""
    if fmt not in _EXPORT_FORMATS:
        raise ValueError(f'unknown export format {fmt}')
    ext, enc = _EXPORT_FORMATS[fmt]
    try:
        rate = int(rate)
    except (TypeError, ValueError):
        rate = _SR
    if rate not in (8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 192000):
        raise ValueError(f'unsupported sample rate {rate}')
    if dither not in _DITHERS_OK:
        dither = 'triangular_hp'
    d = render_mix(items)
    if not d.get('mix'):
        raise ValueError('nothing to export')
    src = os.path.join(_WORK, d['mix'])
    _dirs()
    key = hashlib.sha1(f'{d["mix"]}|{fmt}|{rate}|{dither}|v1'.encode(), usedforsecurity=False).hexdigest()[:24]
    rel = f'exports/{key}.{ext}'
    out = os.path.join(_WORK, rel)
    with _lock(rel):
        if not (os.path.isfile(out) and os.path.getsize(out) > 128):
            tmp = os.path.join(os.path.dirname(out), f'.tmp-{os.getpid()}-{os.path.basename(out)}')
            code, err = _run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-loglevel',
                    'error',
                    '-i',
                    src,
                    '-af',
                    f'aresample={rate}:dither_method={dither}',
                    '-ar',
                    str(rate),
                ]
                + enc
                + [tmp]
            )
            if code != 0:
                try:
                    os.remove(tmp)
                except OSError as _exc:
                    _zyg_log.debug('temp file %s cleanup skipped: %s', tmp, _exc)
                raise ValueError(f'export failed: {err.strip()[-200:] or code}')
            os.replace(tmp, out)
    return {
        'ok': True,
        'export': rel,
        'ext': ext,
        'format': fmt,
        'rate': rate,
        'dither': dither,
        'bytes': os.path.getsize(out),
        'duration': d.get('dur', 0.0),
    }


_CTYPES = {
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.mp3': 'audio/mpeg',
    '.ogg': 'audio/ogg',
    '.opus': 'audio/ogg',
    '.aiff': 'audio/aiff',
    '.png': 'image/png',
}


def content_type(rel):
    return _CTYPES.get(os.path.splitext(str(rel or ''))[1].lower(), 'application/octet-stream')
