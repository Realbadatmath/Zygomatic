# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Speech-to-text for the voice bridge (2026-09-15).

One job: turn the browser's microphone blob (webm/opus, occasionally ogg/wav/mp4)
into text, fast enough that a spoken command feels immediate.

Pipeline: bytes -> NamedTemporaryFile -> ffmpeg -ac 1 -ar 16000 wav ->
zyg_whisper.transcribe_segments(vad=True, beam_size=1). Beam 1 because the
utterances are short commands, not media: beam 5 buys accuracy we do not need
and costs latency we do.

Model policy is zyg_whisper's, not ours: it gates on free VRAM (>= 5000 MB for
CUDA) and falls back to CPU `base`. We only report which of the two we got so
the bridge can tell the operator why it feels slow.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import wave

import zyg_whisper

# Below this the blob is a click, a pop, or a mic that never opened.
MIN_SECONDS = 0.25

_MIME_SUFFIX = {
    'audio/webm': '.webm',
    'video/webm': '.webm',
    'audio/ogg': '.ogg',
    'application/ogg': '.ogg',
    'audio/opus': '.ogg',
    'audio/wav': '.wav',
    'audio/wave': '.wav',
    'audio/x-wav': '.wav',
    'audio/mp4': '.mp4',
    'video/mp4': '.mp4',
    'audio/m4a': '.mp4',
    'audio/x-m4a': '.mp4',
    'audio/mpeg': '.mp3',
}


class SttError(RuntimeError):
    """Audio could not be decoded (bad container, truncated blob, no ffmpeg)."""


def _suffix_for(mime: str) -> str:
    base = (mime or '').split(';')[0].strip().lower()
    return _MIME_SUFFIX.get(base, '.webm')


def _model_name(device: str) -> str:
    """The size zyg_whisper.transcribe_segments will pick for this device."""
    if device == 'cpu':
        return os.environ.get('ZYG_WHISPER_CPU_MODEL', 'base')
    return zyg_whisper.DEFAULT_MODEL


def _to_wav16k(src: str, dst: str) -> None:
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SttError('ffmpeg not found on PATH')
    proc = subprocess.run(
        [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', src, '-ac', '1', '-ar', '16000', '-f', 'wav', dst],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
        tail = ' | '.join(err.splitlines()[-3:])[:400] or 'no stderr'
        raise SttError(f'ffmpeg could not decode the audio (rc={proc.returncode}): {tail}')


def _wav_seconds(path: str) -> float:
    with wave.open(path, 'rb') as w:
        rate = w.getframerate() or 16000
        return w.getnframes() / float(rate)


def transcribe_utterance(audio_bytes: bytes, mime: str = 'audio/webm', language: str = 'en') -> dict:
    """Transcribe one microphone utterance.

    Returns {'text', 'seconds', 'ms', 'device', 'model'} and, when the audio was
    rejected without decoding, 'reason'. Raises SttError when ffmpeg cannot read
    the bytes at all.
    """
    t0 = time.time()
    device, _compute = zyg_whisper._pick_device_compute()
    model = _model_name(device)

    if not audio_bytes:
        return {
            'text': '',
            'seconds': 0.0,
            'ms': int((time.time() - t0) * 1000),
            'device': device,
            'model': model,
            'reason': 'too_short',
        }

    tmpdir = tempfile.mkdtemp(prefix='vb_stt_')
    src = os.path.join(tmpdir, 'in' + _suffix_for(mime))
    wav = os.path.join(tmpdir, 'in16k.wav')
    try:
        with open(src, 'wb') as fh:
            fh.write(audio_bytes)
        _to_wav16k(src, wav)
        seconds = _wav_seconds(wav)
        if seconds < MIN_SECONDS:
            return {
                'text': '',
                'seconds': round(seconds, 3),
                'ms': int((time.time() - t0) * 1000),
                'device': device,
                'model': model,
                'reason': 'too_short',
            }
        segments, _info = zyg_whisper.transcribe_segments(
            wav, language=language, vad=True, want_words=False, beam_size=1
        )
        text = ' '.join((s.get('text') or '').strip() for s in segments)
        text = re.sub(r'\s+', ' ', text).strip()
        return {
            'text': text,
            'seconds': round(seconds, 3),
            'ms': int((time.time() - t0) * 1000),
            'device': device,
            'model': model,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def warm() -> dict:
    """Load the model so the first real utterance is not a 10-20 s stall.

    zyg_whisper caches per (size, device, compute), so this is what every later
    transcribe_utterance() will reuse. Call it from voice_bridge's hello.
    """
    t0 = time.time()
    device, _compute = zyg_whisper._pick_device_compute()
    model = _model_name(device)
    zyg_whisper.get_model(model)
    return {'device': device, 'model': model, 'ms': int((time.time() - t0) * 1000)}
