#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline Rubber Band R3 pitch shift through the installed librubberband (3.3.0).

WHY THIS EXISTS. ffmpeg's `rubberband` filter (libavfilter/af_rubberband.c)
hard-codes RubberBandOptionProcessRealTime and never sets OptionEngineFiner, so
every shift the pipeline made so far ran the older R2 engine. The R3 ("finer")
engine is in the same shared library that is already on the box
(/usr/lib/x86_64-linux-gnu/librubberband.so.2, 3.3.0 — it exports
rubberband_get_engine_version and rubberband_set_formant_scale, both 3.x API).
The `rubberband-cli` package is not installed and needs root, so this file
talks to the library directly with ctypes. No build, no sudo.

Licence: Rubber Band is GPL-2+ (dual). It is used here as a TOOL; the audio it
emits contains none of its code, so the GPL does not reach the output
(GNU GPL FAQ, "GPLOutput"). Do not link it into anything that is distributed.

Usage:
  python tools/rubberband_r3.py IN OUT --semitones -4                 # formants preserved (R3)
  python tools/rubberband_r3.py IN OUT --semitones -4 --formant-follow # formants move with pitch
  python tools/rubberband_r3.py IN OUT --semitones 0 --formant-semitones -1.5   # timbre only
  python tools/rubberband_r3.py IN OUT --semitones -4 --engine faster  # R2 for A/B

IN may be anything ffmpeg decodes; OUT is .wav or .mp3 (256k). Prints one JSON line.
"""

import ctypes
import os
import subprocess
import tempfile

import numpy as np
from zyg_workflows.bin import exe

_LIB = '/usr/lib/x86_64-linux-gnu/librubberband.so.2'

# RubberBandOptions (rubberband-c.h, 3.x)
OPT_PROCESS_OFFLINE = 0x00000000
OPT_PROCESS_REALTIME = 0x00000001
OPT_TRANSIENTS_CRISP = 0x00000000
OPT_TRANSIENTS_MIXED = 0x00000100
OPT_TRANSIENTS_SMOOTH = 0x00000200
OPT_PHASE_LAMINAR = 0x00000000
OPT_WINDOW_STANDARD = 0x00000000
OPT_FORMANT_SHIFTED = 0x00000000
OPT_FORMANT_PRESERVED = 0x01000000
OPT_PITCH_HIGH_SPEED = 0x00000000
OPT_PITCH_HIGH_QUALITY = 0x02000000
OPT_PITCH_HIGH_CONSISTENCY = 0x04000000
OPT_CHANNELS_APART = 0x00000000
OPT_CHANNELS_TOGETHER = 0x10000000
OPT_ENGINE_FASTER = 0x00000000
OPT_ENGINE_FINER = 0x20000000


def _lib():
    lib = ctypes.CDLL(_LIB)
    P = ctypes.c_void_p
    lib.rubberband_new.restype = P
    lib.rubberband_new.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_double, ctypes.c_double]
    lib.rubberband_delete.argtypes = [P]
    lib.rubberband_get_engine_version.restype = ctypes.c_int
    lib.rubberband_get_engine_version.argtypes = [P]
    lib.rubberband_set_pitch_scale.argtypes = [P, ctypes.c_double]
    lib.rubberband_set_formant_scale.argtypes = [P, ctypes.c_double]
    lib.rubberband_set_expected_input_duration.argtypes = [P, ctypes.c_uint]
    lib.rubberband_set_max_process_size.argtypes = [P, ctypes.c_uint]
    lib.rubberband_get_samples_required.restype = ctypes.c_uint
    lib.rubberband_get_samples_required.argtypes = [P]
    FPP = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    lib.rubberband_study.argtypes = [P, FPP, ctypes.c_uint, ctypes.c_int]
    lib.rubberband_process.argtypes = [P, FPP, ctypes.c_uint, ctypes.c_int]
    lib.rubberband_available.restype = ctypes.c_int
    lib.rubberband_available.argtypes = [P]
    lib.rubberband_retrieve.restype = ctypes.c_uint
    lib.rubberband_retrieve.argtypes = [P, FPP, ctypes.c_uint]
    return lib, FPP


def _ptrs(block, FPP):
    """block: float32 array (channels, n), C-contiguous rows → float** for the C API."""
    rows = [np.ascontiguousarray(block[c]) for c in range(block.shape[0])]
    arr = (ctypes.POINTER(ctypes.c_float) * len(rows))(
        *[r.ctypes.data_as(ctypes.POINTER(ctypes.c_float)) for r in rows]
    )
    return ctypes.cast(arr, FPP), rows  # keep `rows` alive


def shift(audio, sr, *, semitones=0.0, formant='preserved', formant_semitones=None, engine='finer', block=8192):
    """audio: float32 (channels, n). Returns float32 (channels, m), m ≈ n.

    formant: 'preserved' (timbre kept, the vocal-tract envelope stays put) or
             'follow' (envelope moves with the pitch → a larger/smaller person).
    formant_semitones: explicit envelope shift in semitones, independent of the
             pitch (0 = envelope untouched). When given it overrides `formant`.
    """
    lib, FPP = _lib()
    ch, n = audio.shape
    opts = OPT_PROCESS_OFFLINE | OPT_PITCH_HIGH_QUALITY | OPT_CHANNELS_TOGETHER
    opts |= OPT_ENGINE_FINER if engine == 'finer' else OPT_ENGINE_FASTER
    if formant_semitones is None:
        opts |= OPT_FORMANT_PRESERVED if formant == 'preserved' else OPT_FORMANT_SHIFTED
    else:
        # Explicit envelope scale needs the preserved mode as the base, then a
        # ratio on top of it (set_formant_scale is absolute: 1.0 = unchanged).
        opts |= OPT_FORMANT_PRESERVED
    scale = float(2.0 ** (semitones / 12.0))
    st = lib.rubberband_new(int(sr), int(ch), int(opts), 1.0, scale)
    if not st:
        raise RuntimeError('rubberband_new failed')
    try:
        engine_ver = lib.rubberband_get_engine_version(st)
        if formant_semitones is not None:
            lib.rubberband_set_formant_scale(st, float(2.0 ** (formant_semitones / 12.0)))
        lib.rubberband_set_expected_input_duration(st, int(n))
        lib.rubberband_set_max_process_size(st, int(block))
        a = np.ascontiguousarray(audio.astype(np.float32))
        # Offline mode: one study pass over everything, then process.
        for i in range(0, n, block):
            b = a[:, i : i + block]
            p, keep = _ptrs(b, FPP)
            lib.rubberband_study(st, p, b.shape[1], 1 if i + block >= n else 0)
        out = []
        buf = np.zeros((ch, block * 4), dtype=np.float32)
        for i in range(0, n, block):
            b = a[:, i : i + block]
            p, keep = _ptrs(b, FPP)
            lib.rubberband_process(st, p, b.shape[1], 1 if i + block >= n else 0)
            while True:
                avail = lib.rubberband_available(st)
                if avail <= 0:
                    break
                take = min(avail, buf.shape[1])
                q, keep2 = _ptrs(buf, FPP)
                got = lib.rubberband_retrieve(st, q, take)
                if got <= 0:
                    break
                out.append(np.stack([r[:got].copy() for r in keep2]))
        y = np.concatenate(out, axis=1) if out else np.zeros((ch, 0), np.float32)
        return y, engine_ver
    finally:
        lib.rubberband_delete(st)


def _decode(path, sr=48000):
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
        w = t.name
    subprocess.run(
        [exe('ffmpeg'), '-y', '-v', 'error', '-i', path, '-ar', str(sr), '-ac', '2', '-c:a', 'pcm_f32le', w], check=True
    )
    import soundfile as sf

    x, got_sr = sf.read(w, dtype='float32', always_2d=True)
    os.unlink(w)
    return np.ascontiguousarray(x.T), got_sr


def _encode(y, sr, out):
    import soundfile as sf

    if out.lower().endswith('.wav'):
        sf.write(out, y.T, sr, subtype='FLOAT')
        return
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
        w = t.name
    sf.write(w, y.T, sr, subtype='FLOAT')
    subprocess.run([exe('ffmpeg'), '-y', '-v', 'error', '-i', w, '-c:a', 'libmp3lame', '-b:a', '256k', out], check=True)
    os.unlink(w)


if __name__ == '__main__':  # the CLI lives in rubberband_r3_cli
    from zyg_workflows.tools.rubberband_r3_cli import main as _cli_main

    raise SystemExit(_cli_main())
