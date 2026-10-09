# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fades, the silence floor, levelling, mastering and the video mux.

Moved verbatim out of the old single-file audio_mix.py (lines 512-780).
"""

from __future__ import annotations

import os

from zyg_workflows.audio_mix.chain import (
    _ffmpeg,
    _log_noop,
    _ok_output,
    _probe_audio_props,
    _scratch_dir,
    loudnorm_two_pass,
    measure_lufs,
    probe_duration,
)


# ── fades / mastering / mux ───────────────────────────────────────────────


def fade_out(in_path, out_path, fade_start_s, fade_dur_s, curve='squ', log_fn=None):
    """Apply a fade-out (default squ curve: fast early drop, gentle tail —
    reads as an intentional scene end rather than a linear volume slide).
    Returns out_path or None."""
    log_fn = log_fn or _log_noop
    filt = f'afade=t=out:st={float(fade_start_s):g}:d={float(fade_dur_s):g}:curve={curve}'
    rc, err = _ffmpeg(['-i', in_path, '-af', filt, '-c:a', 'pcm_s16le', out_path], log_fn=log_fn)
    if not _ok_output(out_path, rc, err, log_fn, 'fade_out'):
        return None
    log_fn(f'audio_mix: fade_out ok st={fade_start_s} d={fade_dur_s} -> {out_path}')
    return out_path


def master(in_path, out_path, i=-14.0, tp=-1.0, log_fn=None, result=None):
    """Publish master: two-pass loudnorm to i/tp, then mono->stereo at 48 kHz.

    -14 LUFS / -1 dBTP because YouTube normalizes DOWN to ~-14 but never
    boosts quiet uploads.  A mono program is loudnorm'd with dual_mono=true:
    the L=R=c0 upmix raises BS.1770 integrated loudness by ~3 LU, so
    normalizing plain mono to -14 would publish at ~-11.
    Returns out_path or None.

    `result` (optional dict) receives the loudnorm outcome — the same pattern
    level_to already uses — specifically including 'normalization_type'. This
    function used to RECEIVE that field from loudnorm_two_pass and drop it on the
    floor, so a master that ffmpeg had silently produced with dynamic AGC instead
    of a linear gain was indistinguishable from a clean one. Verified at byte
    level: rebuilding a shipped master through the real path reproduces its md5
    exactly and its pass-2 JSON reads normalization_type 'dynamic'. Callers
    should treat anything other than 'linear' as a warning worth recording.
    """
    import tempfile

    log_fn = log_fn or _log_noop
    res_out = result if isinstance(result, dict) else {}
    res_out.update({'normalization_type': None, 'measured': None, 'lra_eff': None, 'target_i': i, 'target_tp': tp})
    props = _probe_audio_props(in_path, log_fn=log_fn)
    is_mono = bool(props and props.get('channels') == 1)
    with tempfile.TemporaryDirectory(dir=_scratch_dir()) as td:
        normed = os.path.join(td, 'normed.wav')
        res = loudnorm_two_pass(in_path, normed, i=i, tp=tp, lra=11.0, ar=48000, dual_mono=is_mono, log_fn=log_fn)
        if not res:
            log_fn('audio_mix: master loudnorm stage failed')
            return None
        res_out.update({k: res.get(k) for k in ('normalization_type', 'measured', 'lra_eff') if k in res})
        if res.get('normalization_type') not in (None, 'linear'):
            log_fn(
                f'audio_mix: WARNING master loudnorm ran '
                f"{res['normalization_type']}, not linear — the programme's "
                f'dynamics were re-shaped, not just re-levelled'
            )
        if is_mono:
            pan = 'pan=stereo|c0=c0|c1=c0'
        else:
            pan = 'aformat=channel_layouts=stereo'
        rc, err = _ffmpeg(['-i', normed, '-af', pan, '-ar', '48000', '-c:a', 'pcm_s16le', out_path], log_fn=log_fn)
        if not _ok_output(out_path, rc, err, log_fn, 'master upmix'):
            return None
    log_fn(f'audio_mix: master ok ({"dual-mono" if is_mono else "stereo"} -> stereo, I={i:g} TP={tp:g}) -> {out_path}')
    return out_path


# ebur128 reports digital silence as exactly -70.0 LUFS integrated; anything at
# or under this is zeros (or as good as) and has nothing to level.
_SILENT_LUFS = -69.0


def is_silent(path, floor_lufs=-60.0, log_fn=None):
    """True when `path` measures at or below floor_lufs integrated, or cannot
    be measured at all.

    ebur128 reports digital silence as -70.0 LUFS, so the default -60 floor
    catches a muted narration, a silent placeholder track and an all-but-empty
    render, while a -34 LUFS music bed or a -22 LUFS raw cloner output is NOT
    silent. Unmeasurable (missing/undecodable file) counts as silent: there is
    nothing to level or mix in that case either.
    """
    v = measure_lufs(path, log_fn=log_fn)
    return v is None or float(v) <= float(floor_lufs)


def level_to(path, target_lufs=-14.0, tp_db=-1.5, log_fn=None, result=None):
    """Bring `path` to target_lufs IN PLACE, limiter-first.

    Returns True ONLY when the file measurably landed within 0.5 LU of the
    target. False when the source is silent/unmeasurable (<= -69 LUFS
    integrated), when a step failed, or when the loop ran out of passes short
    of the target. `result` (optional dict) receives
    {'input_lufs', 'final_lufs', 'converged', 'silent'} so a caller can log
    the numbers instead of the boolean.

    2026-08-25 (P-04): the previous version applied +56 dB four times to a
    track of zeros, never compared its final measurement with the target, and
    returned True — Stage 4 then printed "Narration levelled to -14 LUFS" over
    a silent placeholder and the master lifted the music bed to voice level.
    The pass cap is 8 (was 4) for the reason storyteller_scene_service raised
    its own copy: how much of a pass survives the limiter is a property of the
    voice's crest factor, and a clean, peaky voice ran out of passes at -14.8.
    The default TP ceiling is -1.0 dBTP to match master(); every caller in the
    tree passes tp_db explicitly.

    Use this instead of a bare two-pass loudnorm whenever the source is quiet
    narration. The reason is the failure this module already documents in
    loudnorm_two_pass: ffmpeg silently reverts to a DYNAMIC AGC when the linear
    gain would push true peak past TP. Narration renders around -22 LUFS with
    peaks already near -2 dBFS, so an 8 dB lift to -14 has nowhere to go and
    dynamic is exactly what you get — a slow AGC that lifts the quiet passages,
    and (once there is a music bed) drags it back up under the voice.

    Gain-then-limit converges instead: limiting ~1% of samples on plosives is
    inaudible, pumping is not. Iterated because limiting REMOVES energy, so a
    single pass at the measured deficit always lands short and the leftover is
    what tips the polish pass into dynamic. alimiter caps SAMPLE peaks while
    loudnorm gates on TRUE peak (~1 dB higher on inter-sample maxima), hence
    the extra headroom on the limiter ceiling.

    The final loudnorm polish is KEPT ONLY IF IT RAN LINEAR. On an already
    converged file loudnorm's own gating can disagree with ebur128 by ~1 dB and
    drop to dynamic for a correction smaller than the disagreement itself, so
    discarding that result costs nothing.

    Lifted from the tuned implementation in storyteller_scene_service
    (_gain_limit/_level_to) so every caller gets it; that module keeps its own
    copy and is deliberately untouched.
    """
    import shutil
    import tempfile

    log_fn = log_fn or _log_noop
    res = result if isinstance(result, dict) else {}
    res.update({'input_lufs': None, 'final_lufs': None, 'converged': False, 'silent': False})
    if not os.path.isfile(path):
        log_fn(f'audio_mix: level_to — no such file {path}')
        return False
    ext = os.path.splitext(path)[1].lower() or '.wav'
    enc = (
        ['-c:a', 'libmp3lame', '-q:a', '2']
        if ext == '.mp3'
        else ['-c:a', 'aac', '-b:a', '192k']
        if ext in ('.m4a', '.aac')
        else ['-c:a', 'pcm_s16le']
    )
    lim_ceiling = float(tp_db) - 1.2
    passes = 0
    with tempfile.TemporaryDirectory(dir=_scratch_dir()) as td:
        work = os.path.join(td, 'work.wav')
        cur_wav = os.path.join(td, 'cur.wav')
        # Decode once to wav so the iteration never re-encodes lossily.
        rc, err = _ffmpeg(['-i', path, '-ar', '48000', '-c:a', 'pcm_s16le', cur_wav], log_fn=log_fn)
        if not _ok_output(cur_wav, rc, err, log_fn, 'level_to decode'):
            return False
        # Measure BEFORE touching anything. Zeros come back as -70.0 LUFS
        # (ebur128's floor) or as None when the scan cannot find a summary;
        # either way there is no programme to lift, and lifting it +56 dB per
        # pass only manufactures a file that LOOKS levelled to the next stage.
        cur = measure_lufs(cur_wav, log_fn=log_fn)
        res['input_lufs'] = cur
        if cur is None or float(cur) <= _SILENT_LUFS:
            res['silent'] = True
            res['final_lufs'] = cur
            log_fn(
                f'audio_mix: level_to: source is silent/unmeasurable '
                f'(I={cur if cur is not None else "unmeasurable"}) — '
                f'nothing to level'
            )
            return False
        for _ in range(8):
            if passes:
                cur = measure_lufs(cur_wav, log_fn=log_fn)
                if cur is None:
                    break
            deficit = float(target_lufs) - float(cur)
            if abs(deficit) < 0.15:
                break
            lim = 10.0 ** (lim_ceiling / 20.0)
            rc, err = _ffmpeg(
                [
                    '-i',
                    cur_wav,
                    '-af',
                    f'volume={deficit:.3f}dB,alimiter=limit={lim:.5f}:attack=5:release=60:level=disabled',
                    '-ar',
                    '48000',
                    '-c:a',
                    'pcm_s16le',
                    work,
                ],
                log_fn=log_fn,
            )
            if not _ok_output(work, rc, err, log_fn, 'level_to gain+limit'):
                break
            shutil.copyfile(work, cur_wav)
            passes += 1
        polished = os.path.join(td, 'polished.wav')
        n = loudnorm_two_pass(cur_wav, polished, i=float(target_lufs), tp=float(tp_db), log_fn=log_fn)
        if n and n.get('normalization_type') == 'linear':
            shutil.copyfile(n['out'], cur_wav)
        elif n:
            log_fn(
                'audio_mix: level_to — loudnorm wanted DYNAMIC for the last '
                'correction; keeping the limiter-levelled file (no AGC)'
            )
        # The verdict is a MEASUREMENT of the file we are about to ship, not
        # the fact that the loop ran. 0.5 LU is the tolerance the stack test
        # already asserts (test_documentary_stack: |after + 14| < 0.5).
        final_lufs = measure_lufs(cur_wav, log_fn=log_fn)
        hit = final_lufs is not None and abs(float(final_lufs) - float(target_lufs)) < 0.5
        res['final_lufs'] = final_lufs
        res['converged'] = hit
        rc, err = _ffmpeg(['-i', cur_wav] + enc + [path + '.lvl_tmp' + ext], log_fn=log_fn)
        if not _ok_output(path + '.lvl_tmp' + ext, rc, err, log_fn, 'level_to encode'):
            res['converged'] = False
            return False
        shutil.move(path + '.lvl_tmp' + ext, path)
    if hit:
        log_fn(f'audio_mix: level_to -> {final_lufs:g} LUFS (target {target_lufs:g}, limiter-first, {passes} pass(es))')
    else:
        # The levelled file is still written in place — it is closer to the
        # target than the source — but the caller is told the truth.
        log_fn(
            f'audio_mix: WARNING level_to: did NOT converge — sitting at '
            f'{final_lufs if final_lufs is not None else "unmeasured"} LUFS '
            f'(target {target_lufs:g}) after {passes} pass(es); the limiter is '
            f'eating each pass — check the crest factor of the source'
        )
    return hit


def mux_onto_video(video_path, audio_path, out_path, audio_fade_last_s=None, log_fn=None):
    """Replace a video's audio track with audio_path (video stream copied).

    If audio_fade_last_s is set, the audio fades out over the last N seconds
    of the VIDEO's duration (so the tail is silent even if the audio runs
    long; -shortest then trims).  Audio encoded AAC 192k.  Returns out_path
    or None.
    """
    log_fn = log_fn or _log_noop
    args = [
        '-i',
        video_path,
        '-i',
        audio_path,
        '-map',
        '0:v',
        '-c:v',
        'copy',
        '-map',
        '1:a',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
    ]
    if audio_fade_last_s:
        vid_dur = probe_duration(video_path, log_fn=log_fn)
        if vid_dur is None:
            log_fn('audio_mix: mux_onto_video could not probe video duration')
            return None
        st = max(0.0, vid_dur - float(audio_fade_last_s))
        args += ['-af', f'afade=t=out:st={st:g}:d={float(audio_fade_last_s):g}']
    args += ['-shortest', out_path]
    rc, err = _ffmpeg(args, log_fn=log_fn)
    if not _ok_output(out_path, rc, err, log_fn, 'mux_onto_video'):
        return None
    log_fn(f'audio_mix: mux ok -> {out_path}')
    return out_path
