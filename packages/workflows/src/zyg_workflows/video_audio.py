#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio audio leg: ambience bed + timed SFX cues -> mastered wav -> mux.

This is the audio half of a Video Studio still/clip workflow.  It does not
generate anything: it takes files that already exist in the audio libraries
(or absolute paths), places them on a timeline, mixes, masters and muxes.
All heavy lifting is delegated to `audio_mix` (prep_bed / master /
mux_onto_video / measure_lufs / probe_duration) — nothing here duplicates it.

THE SPEC
--------
    spec = {
      'bed': {                      # or None for a cue-only track
        'file':       'foley/xyl_ambience_sand_storm.wav',   # or an abs path
        'gain_db':    -8,
        'fade_in_s':  0.5,
        'fade_out_s': 3.0,
        'loop':       True,         # loop with crossfades to reach duration
      },
      'cues': [
        {'file': 'sfx/uh_ambdsgn_heavy_gusts_of_wind.wav',
         'at_s': 1.0,               # where the cue STARTS in the programme
         'gain_db': 0,
         'trim_start_s': 0,         # offset into the source file
         'dur_s': None,             # None = to the end of the source
         'fade_s': 0.05},
      ],
      'duck': {'voice': '/abs/vo.wav', 'bed_gain_db': -6},   # or None
      'target_lufs': -14.0,
      'true_peak_db': -1.0,
    }

    receipt = build_track(spec, duration_s, out_wav)
    # {'duration_s': ..., 'lufs': ..., 'cues': [{'file','at_s',
    #   'measured_onset_s'}], 'bed': ..., 'warnings': [...]}

`measured_onset_s` is measured back off the finished master, not asserted
from the spec: the first 20 ms window at or after `at_s - 0.5` whose RMS
exceeds the whole file's median window RMS by 12 dB.  That is what makes a
receipt worth anything — it proves the cue actually landed where it was
asked for, after every fade, mix and loudnorm stage.

THE amix TRAP
-------------
Every amix in this module carries `normalize=0`.  ffmpeg's default is
`normalize=1`, which divides every input by the number of inputs: a bed at
-8 dB plus four cues would silently come out ~14 dB down and with the
authored balance destroyed.  `normalize=0` keeps the gains that were
written in the spec.  Do not "simplify" it away.

LICENCE
-------
A library reference ('<cat>/<filename>') is resolved through
`asset_library_service.get_audio_meta`, i.e. the licence sidecar is the
authority, not the filename.  `resolve_library_file` RAISES ValueError when
the sidecar says `commercial_ok` is False or the file is marked deleted —
an unlicensed file cannot enter a published mix.  `no_ai_training` and
`transform` are recorded as information only: an intro is a mix, not model
training input, so they do not block the path.

CLI
---
    python3 video_audio.py --spec spec.json --duration 12 --out out.wav \
        [--video in.mp4 --mux out.mp4]
    python3 video_audio.py --selftest
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from zyg_workflows import audio_mix
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


CREWS_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_LIB_ROOT = os.path.join(CREWS_DIR, 'data', 'asset_libraries')
AUDIO_CATS = ('sfx', 'foley', 'vocal_fx', 'soundtracks')

# Onset detection: 20 ms windows, 12 dB over the file's median window RMS.
_ONSET_WIN_S = 0.020
_ONSET_OVER_DB = 12.0
_ONSET_LOOKBACK_S = 0.5


def _log_noop(msg):
    pass


def _scratch():
    return audio_mix._scratch_dir()


# ── licence-aware reference resolution ────────────────────────────────────


def resolve_library_file(ref, log=None):
    """Resolve `ref` to (abs_path, meta).

    `ref` is either an absolute path (meta is {} — no sidecar to consult) or
    a library reference '<cat>/<filename>' with cat in AUDIO_CATS.

    Raises ValueError when the file does not exist, when the reference is
    malformed, or when the licence sidecar refuses commercial use
    (commercial_ok is False) or marks the file deleted.
    """
    log = log or _log_noop
    if not ref or not isinstance(ref, str):
        raise ValueError(f'video_audio: bad file reference {ref!r}')

    if os.path.isabs(ref):
        if not os.path.exists(ref):
            raise ValueError(f'video_audio: file not found: {ref}')
        return ref, {}

    parts = ref.replace('\\', '/').strip('/').split('/')
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f'video_audio: reference must be "<cat>/<filename>" or an absolute path, got {ref!r}')
    cat, filename = parts
    if cat not in AUDIO_CATS:
        raise ValueError(f'video_audio: unknown audio category {cat!r} (known: {", ".join(AUDIO_CATS)})')
    if os.path.basename(filename) != filename:
        raise ValueError(f'video_audio: bad filename {filename!r}')

    path = os.path.join(AUDIO_LIB_ROOT, cat, filename)
    if not os.path.exists(path):
        raise ValueError(f'video_audio: file not found in library: {ref}')

    from zyg_workflows import asset_library_service

    meta = asset_library_service.get_audio_meta(cat, filename) or {}

    if meta.get('commercial_ok') is False:
        raise ValueError(
            f'video_audio: {ref} is not cleared for commercial use (licence {meta.get("license_id")!r}) — refused'
        )
    if 'deleted' in meta:
        raise ValueError(f'video_audio: {ref} is marked deleted — refused')

    if meta.get('no_ai_training'):
        log(f'video_audio: {ref} is no_ai_training (mix-only use, fine here)')
    if meta.get('transform'):
        log(f'video_audio: {ref} transform={meta.get("transform")!r}')
    if meta.get('attribution_required'):
        log(f'video_audio: {ref} needs attribution: {meta.get("attribution") or meta.get("source") or "?"}')
    return path, meta


# ── ffmpeg / numpy helpers ────────────────────────────────────────────────


def _decode_mono_f32(path, sr=48000):
    """Decode `path` to a mono float32 numpy array at `sr`. None on failure."""
    import numpy as np

    try:
        proc = subprocess.run(
            [exe('ffmpeg'), '-v', 'error', '-i', path, '-map', '0:a', '-f', 'f32le', '-ac', '1', '-ar', str(sr), '-'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype='<f4')


def _window_rms(samples, sr, win_s=_ONSET_WIN_S):
    """Return (rms_per_window, win_len) for non-overlapping windows."""
    import numpy as np

    win = max(1, int(round(sr * win_s)))
    n = len(samples) // win
    if n == 0:
        return np.zeros(0), win
    block = samples[: n * win].reshape(n, win).astype('float64')
    return np.sqrt((block * block).mean(axis=1)), win


def measure_onsets(path, at_list, sr=48000, log=None):
    """For each `at_s` in at_list, the measured onset second in `path`.

    The first 20 ms window starting at or after at_s - 0.5 whose RMS exceeds
    the file's median window RMS by 12 dB.  None when nothing crosses.
    """
    import numpy as np

    log = log or _log_noop
    samples = _decode_mono_f32(path, sr=sr)
    if samples is None or len(samples) == 0:
        log(f'video_audio: could not decode {path} for onset measurement')
        return [None] * len(at_list)
    rms, win = _window_rms(samples, sr)
    if len(rms) == 0:
        return [None] * len(at_list)
    median = float(np.median(rms))
    thresh = median * (10.0 ** (_ONSET_OVER_DB / 20.0))
    win_s = win / float(sr)
    out = []
    for at_s in at_list:
        start_idx = max(0, int((float(at_s) - _ONSET_LOOKBACK_S) / win_s))
        hits = np.nonzero(rms[start_idx:] > thresh)[0]
        out.append(round((start_idx + int(hits[0])) * win_s, 4) if len(hits) else None)
    log(f'video_audio: onset scan median RMS {median:.6f} threshold {thresh:.6f} ({len(rms)} windows)')
    return out


def _cue_filter(cue_len_s, duration_s, fade_s, gain_db, delay_ms):
    """Filter chain placing one already-trimmed cue on the programme clock."""
    bits = ['asetpts=PTS-STARTPTS', 'aformat=channel_layouts=mono:sample_rates=48000']
    fade_s = max(0.0, float(fade_s))
    if fade_s > 0 and cue_len_s > 2 * fade_s:
        bits.append(f'afade=t=in:st=0:d={fade_s:g}')
        bits.append(f'afade=t=out:st={cue_len_s - fade_s:g}:d={fade_s:g}')
    if abs(float(gain_db)) > 1e-9:
        bits.append(f'volume={float(gain_db):g}dB')
    if delay_ms > 0:
        bits.append(f'adelay={delay_ms:d}|{delay_ms:d}')
    bits.append('apad')
    bits.append(f'atrim=0:{duration_s:g}')
    bits.append('asetpts=PTS-STARTPTS')
    return ','.join(bits)


def _render_cue(cue, duration_s, out_path, log=None):
    """Render one cue as a duration_s mono 48 kHz wav. Returns out_path/None."""
    log = log or _log_noop
    path, _meta = resolve_library_file(cue.get('file'), log=log)
    src_dur = audio_mix.probe_duration(path, log_fn=log)
    if not src_dur or src_dur <= 0:
        log(f'video_audio: cue {cue.get("file")} has no usable duration')
        return None

    trim_start = max(0.0, float(cue.get('trim_start_s') or 0.0))
    want = cue.get('dur_s')
    avail = max(0.0, src_dur - trim_start)
    cue_len = avail if want in (None, '') else min(float(want), avail)
    if cue_len <= 0.01:
        log(f'video_audio: cue {cue.get("file")} trims to nothing — skipped')
        return None

    at_s = max(0.0, float(cue.get('at_s') or 0.0))
    delay_ms = int(round(at_s * 1000.0))
    filt = _cue_filter(cue_len, duration_s, cue.get('fade_s', 0.05), cue.get('gain_db', 0.0), delay_ms)
    rc, err = audio_mix._ffmpeg(
        [
            '-ss',
            f'{trim_start:g}',
            '-t',
            f'{cue_len:g}',
            '-i',
            path,
            '-af',
            filt,
            '-ar',
            '48000',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            out_path,
        ],
        log_fn=log,
    )
    if not audio_mix._ok_output(out_path, rc, err, log, 'cue render'):
        return None
    log(f'video_audio: cue {cue.get("file")} @{at_s:g}s ({cue_len:.2f}s, {float(cue.get("gain_db", 0.0)):+.1f} dB)')
    return out_path


def _render_bed(bed, duration_s, td, log=None):
    """Bed -> duration_s mono 48 kHz wav with the spec's fades. path or None."""
    log = log or _log_noop
    path, _meta = resolve_library_file(bed.get('file'), log=log)
    gain_db = float(bed.get('gain_db', -8.0))
    raw = os.path.join(td, 'bed_raw.wav')

    if bed.get('loop', True):
        built = audio_mix.prep_bed([{'path': path, 'gain_db': gain_db}], duration_s, raw, log_fn=log)
        if not built:
            return None
    else:
        rc, err = audio_mix._ffmpeg(
            [
                '-i',
                path,
                '-af',
                (
                    f'aformat=channel_layouts=mono:sample_rates=48000,'
                    f'volume={gain_db:g}dB,apad,atrim=0:{duration_s:g},'
                    f'asetpts=PTS-STARTPTS'
                ),
                '-ar',
                '48000',
                '-ac',
                '1',
                '-c:a',
                'pcm_s16le',
                raw,
            ],
            log_fn=log,
        )
        if not audio_mix._ok_output(raw, rc, err, log, 'bed (no loop)'):
            return None

    fi = max(0.0, float(bed.get('fade_in_s', 0.5) or 0.0))
    fo = max(0.0, float(bed.get('fade_out_s', 3.0) or 0.0))
    if fi <= 0 and fo <= 0:
        return raw
    bits = []
    if fi > 0:
        bits.append(f'afade=t=in:st=0:d={fi:g}')
    if fo > 0:
        bits.append(f'afade=t=out:st={max(0.0, duration_s - fo):g}:d={fo:g}')
    faded = os.path.join(td, 'bed_faded.wav')
    rc, err = audio_mix._ffmpeg(['-i', raw, '-af', ','.join(bits), '-c:a', 'pcm_s16le', faded], log_fn=log)
    if not audio_mix._ok_output(faded, rc, err, log, 'bed fades'):
        return None
    log(f'video_audio: bed {bed.get("file")} {duration_s:g}s {gain_db:+.1f} dB fades {fi:g}/{fo:g}')
    return faded


def _mix_to_duration(parts, duration_s, out_path, log=None):
    """amix `parts` (normalize=0) and pad/trim to exactly duration_s."""
    log = log or _log_noop
    tail = f'apad,atrim=0:{duration_s:g},asetpts=PTS-STARTPTS,aformat=channel_layouts=mono:sample_rates=48000'
    args = []
    for p in parts:
        args += ['-i', p]
    if len(parts) == 1:
        args += ['-af', tail]
    else:
        inputs = ''.join(f'[{k}:a]' for k in range(len(parts)))
        # normalize=0: amix's default divides every input by the input count.
        args += [
            '-filter_complex',
            f'{inputs}amix=inputs={len(parts)}:duration=longest:normalize=0[m];[m]{tail}[out]',
            '-map',
            '[out]',
        ]
    args += ['-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', out_path]
    rc, err = audio_mix._ffmpeg(args, log_fn=log)
    if not audio_mix._ok_output(out_path, rc, err, log, 'mix'):
        return None
    return out_path


# ── the public build ──────────────────────────────────────────────────────


def build_track(spec, duration_s, out_wav, log=None):
    """Build a mastered stereo 48 kHz wav from `spec`. Returns a receipt dict.

    Raises ValueError on a licence refusal or a malformed reference;
    RuntimeError when an ffmpeg stage produces nothing.
    """
    log = log or _log_noop
    if not isinstance(spec, dict):
        raise ValueError('video_audio: spec must be a dict')
    duration_s = float(duration_s)
    if duration_s <= 0:
        raise ValueError(f'video_audio: bad duration {duration_s}')

    target_lufs = float(spec.get('target_lufs', -14.0))
    true_peak_db = float(spec.get('true_peak_db', -1.0))
    cues = [c for c in (spec.get('cues') or []) if isinstance(c, dict)]
    bed = spec.get('bed') if isinstance(spec.get('bed'), dict) else None
    duck = spec.get('duck') if isinstance(spec.get('duck'), dict) else None
    warnings = []

    out_wav = os.path.abspath(out_wav)
    os.makedirs(os.path.dirname(out_wav) or '.', exist_ok=True)

    with tempfile.TemporaryDirectory(dir=_scratch()) as td:
        parts = []

        bed_path = None
        if bed:
            bed_path = _render_bed(bed, duration_s, td, log=log)
            if not bed_path:
                raise RuntimeError('video_audio: bed stage produced nothing')

        if duck and bed_path:
            voice, _m = resolve_library_file(duck.get('voice'), log=log)
            ducked = os.path.join(td, 'ducked.wav')
            got = audio_mix.duck_mix(
                voice, bed_path, ducked, bed_gain_db=float(duck.get('bed_gain_db', -6.0)), log_fn=log
            )
            if got:
                parts.append(got)
                bed_path = None
            else:
                warnings.append('duck_mix failed — bed used undocked')
                log('video_audio: WARNING duck_mix failed, using the raw bed')
        elif duck and not bed_path:
            voice, _m = resolve_library_file(duck.get('voice'), log=log)
            parts.append(voice)

        if bed_path:
            parts.append(bed_path)

        kept_cues = []
        for idx, cue in enumerate(cues):
            cue_out = os.path.join(td, f'cue_{idx}.wav')
            if _render_cue(cue, duration_s, cue_out, log=log):
                parts.append(cue_out)
                kept_cues.append(cue)
            else:
                warnings.append(f'cue {idx} ({cue.get("file")}) dropped')

        if not parts:
            raise RuntimeError('video_audio: nothing to mix (no bed, no cues)')

        mixed = os.path.join(td, 'mix.wav')
        if not _mix_to_duration(parts, duration_s, mixed, log=log):
            raise RuntimeError('video_audio: mix stage produced nothing')

        master_res = {}
        if not audio_mix.master(mixed, out_wav, i=target_lufs, tp=true_peak_db, log_fn=log, result=master_res):
            raise RuntimeError('video_audio: master stage produced nothing')

    if master_res.get('normalization_type') not in (None, 'linear'):
        warnings.append(f'loudnorm ran {master_res.get("normalization_type")}, not linear')

    onsets = measure_onsets(out_wav, [c.get('at_s') or 0.0 for c in kept_cues], log=log)
    receipt = {
        'out': out_wav,
        'duration_s': audio_mix.probe_duration(out_wav, log_fn=log),
        'lufs': audio_mix.measure_lufs(out_wav, log_fn=log),
        'target_lufs': target_lufs,
        'true_peak_db': true_peak_db,
        'normalization_type': master_res.get('normalization_type'),
        'bed': (bed or {}).get('file'),
        'cues': [
            {'file': c.get('file'), 'at_s': float(c.get('at_s') or 0.0), 'measured_onset_s': o}
            for c, o in zip(kept_cues, onsets)
        ],
        'warnings': warnings,
    }
    log(f'video_audio: track ok {receipt["duration_s"]}s {receipt["lufs"]} LUFS -> {out_wav}')
    return receipt


def mux(video_path, wav_path, out_mp4, log=None):
    """Replace `video_path`'s audio with `wav_path`. Returns out_mp4 or None."""
    log = log or _log_noop
    out_mp4 = os.path.abspath(out_mp4)
    os.makedirs(os.path.dirname(out_mp4) or '.', exist_ok=True)
    return audio_mix.mux_onto_video(video_path, wav_path, out_mp4, log_fn=log)


# ── self-test ─────────────────────────────────────────────────────────────


def _stream_duration(path, kind='a'):
    """Duration of the first audio ('a') or video ('v') stream, or None."""
    try:
        proc = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-select_streams',
                f'{kind}:0',
                '-show_entries',
                'stream=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if proc.returncode == 0:
            return float(proc.stdout.decode().strip())
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('ffprobe could not read the %s stream duration, reporting unknown: %s', kind, _exc)
    return None


def _selftest():  # pragma: no cover — exercised via CLI
    """Synthetic end-to-end: bed + two timed cues, onset/loudness/mux checks."""
    import json

    log = print
    dur = 12.0
    out_dir = tempfile.mkdtemp(prefix='video_audio_selftest_', dir=_scratch())
    log(f'video_audio selftest: {out_dir}')

    bed_wav = os.path.join(out_dir, 'bed_src.wav')
    cue_wav = os.path.join(out_dir, 'cue_src.wav')
    vid_mp4 = os.path.join(out_dir, 'video.mp4')

    rc, err = audio_mix._ffmpeg(
        [
            '-f',
            'lavfi',
            '-i',
            'anoisesrc=c=pink:r=48000:a=1',
            '-t',
            f'{dur:g}',
            '-af',
            'volume=-30dB',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            bed_wav,
        ],
        log_fn=log,
    )
    if not audio_mix._ok_output(bed_wav, rc, err, log, 'synth bed'):
        raise RuntimeError('synth bed')

    rc, err = audio_mix._ffmpeg(
        ['-f', 'lavfi', '-i', 'sine=frequency=1000:r=48000', '-t', '0.3', '-ac', '1', '-c:a', 'pcm_s16le', cue_wav],
        log_fn=log,
    )
    if not audio_mix._ok_output(cue_wav, rc, err, log, 'synth cue'):
        raise RuntimeError('synth cue')

    rc, err = audio_mix._ffmpeg(
        [
            '-f',
            'lavfi',
            '-i',
            'testsrc2=size=640x360:rate=24',
            '-t',
            f'{dur:g}',
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-an',
            vid_mp4,
        ],
        log_fn=log,
    )
    if not audio_mix._ok_output(vid_mp4, rc, err, log, 'synth video'):
        raise RuntimeError('synth video')

    spec = {
        'bed': {'file': bed_wav, 'gain_db': -6, 'fade_in_s': 0.5, 'fade_out_s': 3.0, 'loop': True},
        'cues': [
            {'file': cue_wav, 'at_s': 1.0, 'gain_db': 0, 'fade_s': 0.05},
            {'file': cue_wav, 'at_s': 3.0, 'gain_db': 0, 'fade_s': 0.05},
        ],
        'duck': None,
        'target_lufs': -14.0,
        'true_peak_db': -1.0,
    }
    out_wav = os.path.join(out_dir, 'track.wav')
    receipt = build_track(spec, dur, out_wav, log=log)
    _zyg_log.info(json.dumps(receipt, indent=2, sort_keys=True))

    if len(receipt['cues']) != 2:
        raise RuntimeError(f'cues in receipt: {receipt["cues"]}')
    for c in receipt['cues']:
        got = c['measured_onset_s']
        if got is None:
            raise RuntimeError(f'cue @{c["at_s"]} not detected')
        if abs(got - c['at_s']) > 0.05:
            raise RuntimeError(f'cue @{c["at_s"]} measured at {got} (off by {got - c["at_s"]:+.3f}s)')

    lufs = receipt['lufs']
    if lufs is None:
        raise RuntimeError('no LUFS measurement')
    if abs(lufs - (-14.0)) > 1.0:
        raise RuntimeError(f'LUFS {lufs} not within 1.0 of -14.0')

    out_mp4 = os.path.join(out_dir, 'muxed.mp4')
    if not mux(vid_mp4, out_wav, out_mp4, log=log):
        raise RuntimeError('mux failed')
    a_dur = _stream_duration(out_mp4, 'a')
    v_dur = _stream_duration(out_mp4, 'v')
    if a_dur is None:
        raise RuntimeError('muxed file has no audio stream')
    if v_dur is None:
        raise RuntimeError('muxed file has no video stream')
    if abs(a_dur - v_dur) > 0.1:
        raise RuntimeError(f'audio {a_dur}s vs video {v_dur}s (>0.1 s apart)')
    _zyg_log.info(f'mux ok: audio {a_dur}s / video {v_dur}s')

    _zyg_log.info('SELFTEST OK')
    return 0


if __name__ == '__main__':  # the CLI lives in video_audio_cli
    from zyg_workflows.video_audio_cli import main as _cli_main

    raise SystemExit(_cli_main())
