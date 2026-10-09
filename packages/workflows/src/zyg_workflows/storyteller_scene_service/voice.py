# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.voice — the voice section — TTS synthesis, pitch/pace conditioning and take caching (lines 97-601).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    _POOL_DIR,
    _SR,
    _log_noop,
    exe,
    os,
    shutil,
    subprocess,
    zlib,
)

# ── voice ────────────────────────────────────────────────────────────────────


def _training_ok(path: str, log_fn=None) -> bool:
    """False when `path` is a library file whose licence forbids model input.

    A clone reference IS model input: the wav conditions the TTS network. The
    344 Audio EULA permits its sounds in a commercial mix but forbids using them
    "to train AI, machine learning, or neural networks", so a vocal_fx file
    handed in as a voice ref would breach the licence without ever failing the
    publish gate. Fails CLOSED — if the gate itself cannot run, the ref is
    refused rather than used. See ambience_ingest.training_gate.
    """
    try:
        from zyg_workflows import ambience_ingest
    except Exception as e:
        (log_fn or _log_noop)(f'[scene] training gate unavailable ({e}) — refusing voice ref {os.path.basename(path)}')
        return False
    return bool(ambience_ingest.training_gate([path], log_fn=log_fn)['ok'])


def _resolve_voice_ref(voice: dict) -> str | None:
    """voice: {'ref': 'abel_seed' | '<pool id>' | '/abs/path.wav'}

    A resolved ref is licence-checked before it is returned: see _training_ok.
    """
    ref = (voice or {}).get('ref', '')
    if ref == 'abel_seed':
        from zyg_workflows import abel_voice

        return abel_voice.ABEL_SEED_WAV if os.path.isfile(abel_voice.ABEL_SEED_WAV) else None
    if os.path.isabs(ref) and os.path.isfile(ref):
        return ref if _training_ok(ref) else None
    cand = os.path.join(_POOL_DIR, ref if ref.endswith('.wav') else ref + '.wav')
    if not os.path.isfile(cand):
        return None
    return cand if _training_ok(cand) else None


def _probe_sr(path: str, default: int = 24000) -> int:
    r = subprocess.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'stream=sample_rate',
            '-of',
            'csv=p=0',
            path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return int(r.stdout.strip())
    except (TypeError, ValueError):
        return default


def _pitch_shift(src: str, dst: str, semitones: float, formant: str = 'shifted', log_fn=None) -> str | None:
    """Re-pitch a rendered line WITHOUT changing its duration.

    formant='shifted' drags the formants along with the pitch, which lengthens
    the apparent VOCAL TRACT. That size cue — not F0 on its own — is what makes
    a voice read masculine: voice_qc measures it as vtl_cm, and its calibration
    puts adult female at 14.44 cm, so a render sitting near that number reads
    female no matter how the pitch is nudged.
    formant='preserved' moves pitch only and keeps the apparent body size (the
    narration_service pitch_lift behaviour) — use it for expression, not sex.

    THE TWO PATHS ARE DIFFERENT ALGORITHMS, and that is the point (2026-08-11,
    operator: "sounds robotic"). Shifting pitch and formants TOGETHER is exactly
    what replaying the waveform at a different rate does, so it needs no vocoder
    at all: `asetrate` retunes the whole spectrum by an exact resample — every
    phase relationship between the harmonics survives untouched — and `atempo`
    puts the duration back with a WSOLA splice that, on speech at these small
    factors, is very nearly transparent. This is the same whole-spectrum scale
    the original abel_voice child_transform used for its `k` axis.
    Running it through librubberband instead measurably damaged the voice —
    measured on this scene's cached line_02 clone (source 14.74 dB HNR,
    7.30 % shimmer):

        shift        engine                    HNR      shimmer
        -3.5 st      rubberband (shipped)    12.74 dB   12.20 %
        -1.5 st      rubberband              10.96 dB   12.85 %
        -1.5 st      asetrate+atempo         14.58 dB    7.79 %

    Rubberband nearly DOUBLES shimmer — cycle-to-cycle amplitude jitter added
    between analysis windows, which is precisely the buzzy/warbly artefact that
    reads as "robotic" — while the resample path holds the source's own figures.
    Note ffmpeg's `pitchq` default is `speed`, not `quality`; switching it to
    quality was tested and did NOT recover the loss (HNR 10.3-11.5 dB across
    -1.0…-3.5 st), so the fix is to leave the phase vocoder out of this axis
    entirely, not to tune it.

    formant='preserved' genuinely needs a vocoder — pitch has to move while the
    formants stay put, which a resample cannot express — so it keeps rubberband,
    now on the high-quality pitch engine with speech-friendly smoothing.
    """
    log = log_fn or _log_noop
    factor = 2.0 ** (float(semitones) / 12.0)
    if formant == 'preserved':
        af = (
            f'rubberband=pitch={factor:.8f}:formant=preserved:transients=smooth'
            f':detector=soft:window=long:smoothing=on:pitchq=quality'
        )
    else:
        sr_in = _probe_sr(src)
        # asetrate takes an integer rate; at 24 kHz the rounding is <0.002 % of
        # the factor, i.e. ~0.0003 semitones. soxr keeps the resample clean.
        af = (
            f'asetrate={int(round(sr_in * factor))},'
            f'aresample={_SR}:resampler=soxr:precision=28,'
            f'atempo={1.0 / factor:.8f}'
        )
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-i',
            src,
            '-af',
            af,
            '-ar',
            str(_SR),
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            dst,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) <= 44:
        log(f'[scene] pitch shift failed ({r.stderr[:200]}) — using unshifted line')
        return None
    return dst


def _probe_dur(path: str) -> float | None:
    r = subprocess.run(
        [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip())
    except (TypeError, ValueError):
        return None


# A pace match outside this band is a re-render, not a stretch: it means the take
# is not the same performance as the reference (a one-word prompt that restated
# itself, a line whose text changed). Clamped and logged rather than shipped —
# atempo below 0.5 is not even expressible in one filter instance.
_PACE_CLAMP = (0.60, 1.50)


def _pace_target(voice: dict, out_wav: str) -> float | None:
    """The duration this line is being paced to, in seconds, or None.

    `pace_ref` points at an ALREADY-RENDERED scene directory: the line with the
    same basename in it is the reference. This exists because delivery speed is
    not a knob the engine really has — measured on this scene, swinging Chatterbox's
    cfg_weight from 0.40 down to 0.20 moved a 7.4 s line by 0.2 s, while the
    approved Abel take of the same line runs 8.56 s. So a re-voiced scene has to
    be paced after the fact or it rushes.

    Matching PER LINE rather than with one global tempo is the point: every music
    cue and shot window in a spec is anchored to a line's start or end, so
    identical line durations mean the new voice inherits the approved cut's
    timeline exactly — the two versions differ in timbre and in nothing else.
    """
    d = (voice or {}).get('pace_ref')
    if not d:
        return None
    cand = os.path.join(d, os.path.basename(out_wav))
    return _probe_dur(cand) if os.path.isfile(cand) else None


def _time_stretch(src: str, dst: str, tempo: float, log_fn=None) -> str | None:
    """Change delivery SPEED without moving pitch. atempo is WSOLA — the same
    splice the pitch path already relies on to put duration back after a
    resample, and on speech it is very nearly transparent. Measured on this
    scene's teen08 line_02 (7.38 s → 8.54 s, tempo 0.862), it did not degrade
    the voice at all: HNR 11.06 → 12.92 dB, shimmer 9.90 → 9.21 %, jitter
    3.05 → 2.45 % — slowing gives the analysis more periods per window, so the
    stretch reads cleaner than the take it came from.

    THE FILTER ORDER IS LICENCE TO SHIP, NOT STYLE. `atempo` BEFORE
    `aresample=…:resampler=soxr:precision=28` HANGS ffmpeg 6.1.1 on a short
    input: the 0.70 s anchored "Home." take wrote its complete output and then
    never exited, wedging the render for 22 minutes until it was killed (the
    4 dialogue lines, 5-7 s each, passed through the same chain unharmed, so
    this only bites the short ones). Resampling FIRST — the order the shipping
    _pitch_shift chain already uses, which is why it never hit this — completes
    in milliseconds, and running the WSOLA splice at 48 kHz rather than 24 is
    the better-quality half anyway. The timeout below is the belt to that
    braces: an ffmpeg that will not exit must not be able to hang a build."""
    log = log_fn or _log_noop
    try:
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-loglevel',
                'error',
                '-y',
                '-i',
                src,
                '-af',
                f'aresample={_SR}:resampler=soxr:precision=28,atempo={float(tempo):.8f}',
                '-ar',
                str(_SR),
                '-ac',
                '1',
                '-c:a',
                'pcm_s16le',
                dst,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        log('[scene] time stretch TIMED OUT — using unstretched line')
        return None
    if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) <= 44:
        log(f'[scene] time stretch failed ({r.stderr[:200]}) — using unstretched line')
        return None
    return dst


def _gain_limit(src: str, dst: str, gain_db: float, tp_db: float = -1.5, log_fn=None) -> str:
    """Raise by gain_db and catch the resulting overs with a true-peak limiter.

    This exists to keep loudnorm LINEAR. Narration renders at roughly -22 LUFS
    with peaks already near -2 dBFS, so reaching a -14 LUFS master needs ~8 dB
    that the peak ceiling has no room for — and ffmpeg's answer to that is to
    silently switch to DYNAMIC normalisation, whose slow AGC lifts the quiet
    passages and drags the ambience bed up with them. Limiting ~1 % of samples
    on plosives is inaudible; pumping the bed back up is not.

    Returns dst, or src unchanged if ffmpeg fails (never breaks the render).
    """
    log = log_fn or _log_noop
    lim = 10.0 ** (float(tp_db) / 20.0)
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-i',
            src,
            '-af',
            f'volume={float(gain_db):.3f}dB,alimiter=limit={lim:.5f}:attack=5:release=60:level=disabled',
            '-ar',
            str(_SR),
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            dst,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.isfile(dst):
        log(f'[scene] pre-limiter failed ({r.stderr[:200]}) — passing audio through')
        return src
    return dst


def _level_to(path: str, target_lufs: float, work: str, audio_mix, tp_db=-1.5, log_fn=None) -> None:
    """Bring `path` to target_lufs in place, limiter-first so the final loudnorm
    only has to make a small, LINEAR correction."""
    log = log_fn or _log_noop
    # Converge on the target by gain-then-limit. Iterated because limiting
    # REMOVES energy: one pass at the measured deficit always lands short, and
    # the leftover is what tips the final loudnorm into dynamic AGC.
    # alimiter also caps SAMPLE peaks while loudnorm gates on TRUE peak, which
    # runs ~1 dB higher on inter-sample maxima — hence the extra 1.2 dB.
    #
    # 8 PASSES, NOT 4 (2026-08-21). Each pass recovers only part of its deficit,
    # and HOW MUCH depends on the crest factor of the material — so the number of
    # passes needed is a property of the VOICE, not a constant. Swapping Cornelis
    # from the broken donor seed (HNR ~3.4 dB) to Elder Gravel (HNR 9.1) was
    # enough to cross the old cap: the cleaner voice is peakier, the limiter takes
    # a bigger bite per pass, and the master landed 0.8 dB short at -14.8. Three
    # further passes converged it to -14.1 with the peak UNMOVED at -2.4 dBFS, so
    # the ceiling was never the binding constraint — the loop simply ran out.
    # A pass is one ffmpeg on an already-short file; converging is cheaper than
    # shipping quiet.
    for _ in range(8):
        cur = audio_mix.measure_lufs(path, log_fn=log)  # float LUFS or None
        if cur is None:
            break
        deficit = float(target_lufs) - float(cur)
        if abs(deficit) < 0.15:
            break
        _gain_limit(path, work, deficit, tp_db=tp_db - 1.2, log_fn=log)
        if not os.path.isfile(work):
            break
        shutil.copyfile(work, path)
    else:
        # Out of passes with the target still unmet. Say so: the next stage
        # silently keeps whatever this produced, and a master drifting quiet is
        # exactly the kind of defect that ships unnoticed because nothing fails.
        # Re-measure before shouting. The loop tests at the TOP, so the LAST
        # pass's result is never checked inside it — a run that converged on its
        # final correction would otherwise warn about a file that is already on
        # target (observed: warned at -14.1 against a 0.15 tolerance).
        cur = audio_mix.measure_lufs(path, log_fn=log)
        if cur is not None and abs(float(target_lufs) - float(cur)) >= 0.15:
            log(
                f'[scene] WARN {os.path.basename(path)}: did NOT converge to '
                f'{target_lufs:g} LUFS in 8 passes — sitting at {cur:g}. The '
                f'limiter is eating each pass; check the crest factor of the '
                f'source before raising the cap again.'
            )
    # Final polish pass — but ONLY if loudnorm can do it linearly. Its pass-1
    # gating disagrees with ebur128 by up to ~1 dB, so on an already-converged
    # file it can ask for a gain the peak ceiling refuses and drop into dynamic
    # AGC for a correction smaller than the measurement disagreement itself.
    # The converged file is already at target by the ebur128 measure the QC
    # gates use, so discarding a dynamic result costs nothing and protects the
    # bed from being pumped back up.
    n = audio_mix.loudnorm_two_pass(path, work, i=float(target_lufs), tp=tp_db, log_fn=log)
    if n and n.get('normalization_type') == 'linear':
        shutil.copyfile(n['out'], path)
    elif n:
        log(
            f'[scene] {os.path.basename(path)}: loudnorm wanted DYNAMIC for the '
            f'last {abs(float(target_lufs) - (audio_mix.measure_lufs(path) or 0)):.2f} dB '
            f'— keeping the limiter-levelled file instead (no AGC on the bed)'
        )


# Bumped whenever _pitch_shift's ALGORITHM changes, so a cached line whose
# semitones/formant are unchanged is still re-shifted through the new chain.
# v2 = resample+atempo for formant='shifted' (was librubberband).
_SHIFTER_REV = 'v2'

# The same contract as _SHIFTER_REV, for the pace stretch: bumped whenever
# _time_stretch's CHAIN changes, so a cached line whose target duration is
# unchanged is still re-paced through the new one. v2 = aresample before atempo
# (v1 hung ffmpeg on short inputs).
_PACER_REV = 'v2'


def _tune_key(voice: dict, out_wav: str = '') -> str:
    """The post-render settings a cached line was rendered with. build_scene
    compares this against the `.tune` marker beside a cached wav, because the raw
    clone and the finished line are two different cache layers: changing
    pitch_semitones must re-run the ffmpeg shift while still REUSING the TTS
    render. Without the marker a re-tune silently ships the old pitch — the
    cached line_NN_x.wav exists, so the caller skips _synth_line entirely.

    The pace stretch rides the same marker for the same reason, and it records
    the RESOLVED target duration rather than the pace_ref path: re-rendering the
    reference scene's line at a different length has to re-pace this one, and a
    path alone would compare equal and ship the old timing."""
    v = voice or {}
    key = f'{float(v.get("pitch_semitones", 0.0)):+.3f}/{v.get("formant", "shifted")}/{_SHIFTER_REV}'
    tgt = _pace_target(v, out_wav) if out_wav else None
    if tgt is not None:
        key += f'/pace{tgt:.3f}/{_PACER_REV}'
    elif abs(float(v.get('tempo', 1.0)) - 1.0) > 1e-6:
        key += f'/tempo{float(v["tempo"]):.4f}/{_PACER_REV}'
    return key


def _take_key(voice: dict, text: str) -> str:
    """The TTS settings a cached CLONE was rendered with — the `.take` marker
    beside <line>_raw.wav, and the exact counterpart of `.tune` one layer down.

    `.tune` was added because changing pitch_semitones silently did nothing: the
    final wav existed, so the caller skipped the re-shift. The raw clone had the
    identical hole one level deeper — changing the sampling seed (or the
    exaggeration/cfg/temperature) left <line>_raw.wav in place, so the build
    kept shipping the old take and the parameter change was unobservable.
    Re-rolling a bad take is the normal way to use a sampler; it has to work.

    THE SAME HOLE EXISTED ONE LAYER FURTHER OUT, and it was the worst of the
    three: the key did not include `ref`, so changing WHO IS SPEAKING left every
    cached raw clone in place and the build shipped the old voice. Recasting a
    character is not an edge case — it is the single most consequential thing a
    spec can change — and it was the one change the cache could not see. The ref
    is keyed by path AND size AND mtime, because a frozen seed can be re-baked
    at the same path with different knobs and would otherwise look unchanged.
    """
    ref = _resolve_voice_ref(voice) or str((voice or {}).get('ref', ''))
    try:
        st = os.stat(ref)
        ref_key = f'{os.path.basename(ref)}:{st.st_size}:{int(st.st_mtime)}'
    except OSError:
        ref_key = ref
    return '/'.join(
        (
            ref_key,
            str(int((voice or {}).get('seed', 1672))),
            f'{float((voice or {}).get("exaggeration", 0.3)):.3f}',
            f'{float((voice or {}).get("cfg_weight", 0.4)):.3f}',
            f'{float((voice or {}).get("temperature", 0.7)):.3f}',
            # crc32, not hash() — str hashing is salted per interpreter run, so a
            # hash()-based marker would mismatch itself on the next build and
            # re-render every line forever.
            format(zlib.crc32(text.encode('utf-8')), '08x'),
        )
    )


def _synth_line(text: str, out_wav: str, voice: dict, log_fn=None) -> str | None:
    """One spoken line via the isolated Chatterbox venv. Returns out_wav or None.

    When the voice carries `pitch_semitones`, the CLONE is cached unshifted as
    <out_wav>_raw.wav and the shift is applied on top: re-tuning the voice then
    costs one ffmpeg pass instead of a fresh TTS render per line.
    """
    from zyg_workflows import abel_voice

    log = log_fn or _log_noop
    ref = _resolve_voice_ref(voice)
    if not ref:
        log(f'[scene] voice ref unresolved: {voice!r}')
        return None
    semis = float(voice.get('pitch_semitones', 0.0))
    tgt = _pace_target(voice, out_wav)
    tempo = float(voice.get('tempo', 1.0))
    stretch = tgt is not None or abs(tempo - 1.0) > 1e-6
    # An unpitched, unpaced voice renders straight to out_wav (no second copy) —
    # EXCEPT when a _raw from a previously processed build is sitting there, in
    # which case out_wav still holds the old treatment and the raw is the one to
    # restore. A paced line always keeps its raw: stretching in place would
    # compound every re-pace on top of the last one.
    raw = out_wav[:-4] + '_raw.wav'
    if not semis and not stretch and not os.path.isfile(raw):
        raw = out_wav
    want_take = _take_key(voice, text)
    got_take = None
    if os.path.isfile(raw + '.take'):
        with open(raw + '.take') as fh:
            got_take = fh.read().strip()
    if os.path.isfile(raw) and got_take is not None and got_take != want_take:
        log(f'[scene] {os.path.basename(raw)} re-render: TTS settings changed ({got_take} → {want_take})')
        os.remove(raw)
    if not os.path.isfile(raw):
        if not abel_voice.chatterbox_synth_segment(
            text,
            raw,
            ref=ref,
            exaggeration=float(voice.get('exaggeration', 0.3)),
            cfg_weight=float(voice.get('cfg_weight', 0.4)),
            temperature=float(voice.get('temperature', 0.7)),
            seed=int(voice.get('seed', 1672)),
            device=voice.get('device', 'cpu'),
            log_fn=log,
        ):
            return None
    with open(raw + '.take', 'w') as fh:
        fh.write(want_take)
    # raw ─(pitch)→ ─(pace)→ out_wav. Both stages are optional and each reads
    # whatever the previous one produced, so the raw clone is never touched.
    src = raw
    if semis:
        shifted = out_wav[:-4] + '_shift.wav'
        if _pitch_shift(raw, shifted, semis, voice.get('formant', 'shifted'), log_fn=log):
            src = shifted
            log(
                f'[scene] pitched {os.path.basename(out_wav)} by {semis:+.2f} st '
                f'(formants {voice.get("formant", "shifted")})'
            )
    if stretch:
        if tgt is not None:
            d = _probe_dur(src)
            # atempo=T divides the duration by T, so hitting `tgt` needs d/tgt.
            tempo = (d / float(tgt)) if (d and tgt) else 1.0
        lo, hi = _PACE_CLAMP
        if not lo <= tempo <= hi:
            log(
                f'[scene] WARN {os.path.basename(out_wav)}: pace match wants '
                f'atempo {tempo:.3f} (target {tgt}s) — clamped to '
                f'{min(max(tempo, lo), hi):.3f}. A stretch this far means the take '
                f'is not the same performance as the reference; re-roll it instead.'
            )
            tempo = min(max(tempo, lo), hi)
        if abs(tempo - 1.0) > 1e-6 and _time_stretch(src, out_wav, tempo, log_fn=log):
            log(
                f'[scene] paced {os.path.basename(out_wav)}: atempo {tempo:.3f}'
                + (f' → {tgt:.2f}s (reference)' if tgt else '')
            )
            src = out_wav
    if src != out_wav:
        shutil.copyfile(src, out_wav)
    with open(out_wav + '.tune', 'w') as fh:
        fh.write(f'{_tune_key(voice, out_wav)}|{want_take}')
    return out_wav
