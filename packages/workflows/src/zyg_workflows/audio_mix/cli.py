# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The lavfi CLI self-test and the argparse entry point.

Moved verbatim out of the old single-file audio_mix.py (lines 800-1003).
"""

from __future__ import annotations

import os

from zyg_workflows.audio_mix.chain import (
    _ffmpeg,
    duck_mix,
    loudnorm_two_pass,
    measure_lufs,
    prep_bed,
    probe_duration,
)
from zyg_workflows.audio_mix.mastering import (
    fade_out,
    master,
    mux_onto_video,
)


# ── CLI self-test ─────────────────────────────────────────────────────────


def _selftest(out_dir):  # pragma: no cover — exercised via CLI
    """lavfi-generate voice + 2 bed layers, run the full chain, report
    durations and final integrated LUFS.  Returns 0/1 exit code."""
    os.makedirs(out_dir, exist_ok=True)
    log = print
    failures = []

    def stage(name, path, want_dur=None, tol=0.15):
        dur = probe_duration(path, log_fn=log) if path else None
        ok = path is not None and dur is not None
        if ok and want_dur is not None and abs(dur - want_dur) > tol:
            ok = False
        log(
            f'[selftest] {name:<14} dur={dur if dur is not None else "FAIL"}'
            f'{"" if want_dur is None else f" (want {want_dur})"}'
            f'  {"OK" if ok else "** FAIL **"}'
        )
        if not ok:
            failures.append(name)
        return ok

    # 1. 'voice': 6 s amplitude-modulated 220 Hz tone with silent gaps
    #    (bursts of ~1.3 s per 2 s cycle — enough silence to prove the
    #    two-pass loudnorm does not pump through pauses).
    voice6 = os.path.join(out_dir, 'voice_6s.wav')
    rc, err = _ffmpeg(
        [
            '-f',
            'lavfi',
            '-i',
            ('aevalsrc=0.55*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*3*t))*gt(mod(t\\,2)\\,0.7):d=6:s=48000'),
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            voice6,
        ],
        log_fn=log,
    )
    stage('voice_6s', voice6 if rc == 0 else None, 6.0)

    # Production narration tracks span the whole program; emulate that by
    # placing the 6 s utterance at t=4 s on a 20 s timeline (duck_mix uses
    # duration=first, so the VO input defines program length).
    voice20 = os.path.join(out_dir, 'voice_20s.wav')
    rc, err = _ffmpeg(
        [
            '-i',
            voice6,
            '-af',
            'adelay=4000,apad=whole_dur=20',
            '-ar',
            '48000',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            voice20,
        ],
        log_fn=log,
    )
    stage('voice_20s', voice20 if rc == 0 else None, 20.0)

    # 2. VO loudnorm to -16 (exercises the pass-1 JSON parse path).
    vo_norm = os.path.join(out_dir, 'vo_norm.wav')
    res = loudnorm_two_pass(voice20, vo_norm, i=-16.0, tp=-1.5, lra=11.0, log_fn=log)
    stage('vo_norm', vo_norm if res else None, 20.0)

    # 3. Bed layers, both 8 s (shorter than 20 s -> forces the loop path).
    waves = os.path.join(out_dir, 'waves_8s.wav')
    rc, err = _ffmpeg(
        [
            '-f',
            'lavfi',
            '-i',
            'anoisesrc=color=pink:r=48000:amplitude=0.5:duration=8',
            '-af',
            'lowpass=f=300',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            waves,
        ],
        log_fn=log,
    )
    stage('waves_8s', waves if rc == 0 else None, 8.0)

    gulls = os.path.join(out_dir, 'gulls_8s.wav')
    rc, err = _ffmpeg(
        [
            '-f',
            'lavfi',
            '-i',
            ('aevalsrc=0.35*sin(2*PI*(1500+700*sin(2*PI*4*t))*t)*lt(mod(t\\,2.7)\\,0.22):d=8:s=48000'),
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            gulls,
        ],
        log_fn=log,
    )
    stage('gulls_8s', gulls if rc == 0 else None, 8.0)

    # 4. Bed: 20 s from two 8 s layers — MUST come out exactly 20 s
    #    (the classic looping bug is a 21 s or 14.5 s bed).
    bed = prep_bed(
        [{'path': waves, 'gain_db': -4.0}, {'path': gulls, 'gain_db': -10.0}],
        duration_s=20,
        out_path=os.path.join(out_dir, 'bed_20s.wav'),
        crossfade_s=1.5,
        log_fn=log,
    )
    stage('bed_20s', bed, 20.0, tol=0.05)

    # 5. Duck bed under VO.
    ducked = duck_mix(vo_norm, bed, os.path.join(out_dir, 'ducked.wav'), bed_gain_db=0.0, log_fn=log)
    stage('ducked', ducked, 20.0)

    # 6. Fade out 17..19.5 s.
    faded = (
        fade_out(ducked, os.path.join(out_dir, 'faded.wav'), fade_start_s=17, fade_dur_s=2.5, log_fn=log)
        if ducked
        else None
    )
    stage('faded', faded, 20.0)

    # 7. Master to -14/-1, mono -> stereo.
    mastered = master(faded, os.path.join(out_dir, 'master.wav'), i=-14.0, tp=-1.0, log_fn=log) if faded else None
    stage('master', mastered, 20.0)

    # 7b. The master stage must achieve LINEAR normalization (the lra_eff
    #     raise makes the high-LRA program linear-eligible; before 2026-07-30
    #     it silently reverted to dynamic AGC).  Re-run the same loudnorm the
    #     master stage performs and assert the verified normalization_type.
    if faded:
        ln = loudnorm_two_pass(
            faded, os.path.join(out_dir, 'norm_check.wav'), i=-14.0, tp=-1.0, lra=11.0, dual_mono=True, log_fn=log
        )
        ln_ok = bool(ln) and ln.get('normalization_type') == 'linear'
        log(
            f'[selftest] normalization_type: '
            f'{ln.get("normalization_type") if ln else "FAIL"} '
            f'(want linear)  {"OK" if ln_ok else "** FAIL **"}'
        )
        if not ln_ok:
            failures.append('normalization_type')
    else:
        failures.append('normalization_type')

    # Tolerance note: loudnorm's internal meter and the reference ebur128
    # filter diverge by ~1.3 LU on this synthetic 50%-duty sine-burst signal
    # (gating-block alignment), so linear normalization lands ~-12.7 here by
    # ebur128.  On real program material the meters track (verified on the
    # scene20 mix: linear master reads -13.9).  The old +/-1 window only
    # passed because dynamic AGC re-centered the synthetic signal — the very
    # defect the linear verification exists to catch.
    lufs = measure_lufs(mastered, log_fn=log) if mastered else None
    lufs_ok = lufs is not None and abs(lufs - (-14.0)) <= 2.0
    log(
        f'[selftest] final integrated: {lufs} LUFS (target -14 +/- 2, '
        f'synthetic-signal meter divergence — see comment)  '
        f'{"OK" if lufs_ok else "** FAIL **"}'
    )
    if not lufs_ok:
        failures.append('final_lufs')

    # 8. Mux onto a tiny synthetic video (native mpeg4 encoder, CPU-only).
    vid = os.path.join(out_dir, 'testvid.mp4')
    rc, err = _ffmpeg(
        ['-f', 'lavfi', '-i', 'testsrc2=duration=20:size=64x64:rate=5', '-c:v', 'mpeg4', '-q:v', '5', vid], log_fn=log
    )
    if rc == 0 and mastered:
        muxed = mux_onto_video(vid, mastered, os.path.join(out_dir, 'muxed.mp4'), audio_fade_last_s=2.0, log_fn=log)
        stage('muxed', muxed, 20.0, tol=0.3)
    else:
        log('[selftest] mux stage skipped (video gen or master failed)')
        failures.append('muxed')

    if failures:
        log(f'[selftest] FAILURES: {failures}')
        return 1
    log('[selftest] ALL STAGES OK')
    return 0


def main(argv=None):  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description='Zygomatic audio mix chain')
    ap.add_argument('--selftest', metavar='OUT_DIR', help='run the lavfi self-test into OUT_DIR')
    ns = ap.parse_args(argv)
    if ns.selftest:
        return _selftest(ns.selftest)
    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
