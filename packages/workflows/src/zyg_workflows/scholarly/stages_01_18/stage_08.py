# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.4 of the scholarly pipeline: the TTS pre-image pass.

`stage_08_tts_pre_image_pass` was one 404-line straight-line block.  It is now
the orchestrator of the eight steps it always had — settings, narration, the
P-04 guard, levelling, word timings, the ASR read-back gate, rhythm cues and
the state write — each a module-level function with explicit parameters.  The
statements, their order and their side effects are unchanged; the helpers stay
in this module so every name they read resolves exactly where it did before.
"""

import os
from dataclasses import dataclass

from ._common import (
    _PKG_DIR,
    _SCHOLARLY_SEC_PER_WORD,
    _align_narration_word_timings,
    _scholarly_n_images,
    _tts_shared,
    _update_marker,
    _zyg_log,
    exe,
)


@dataclass(frozen=True)
class TtsSettings:
    """How this run narrates.

    `voice_id` is the edge-TTS voice name that goes into the logs and the job
    state, `seed_wav` the fixed reference voice handed to tts_service,
    `emo_alpha`/`emo_text` the IndexTTS-2 delivery dials, and `skip_record` is
    True on a pre-emptive RECORD run, which banks Claude work only and
    estimates the narration length instead of synthesising it.
    """

    voice_id: str
    seed_wav: str
    emo_alpha: float
    emo_text: bool
    skip_record: bool


def _tts_settings(ctx):
    """Resolve the narrator settings for this run.

    In: the run context (its subject type and pre-empt mode).  Out: a
    `TtsSettings`.  Logs the single `[preempt]` line when synthesis is skipped.
    """
    _tts_voice_map = {
        'person': 'en-GB-ThomasNeural',
        'war': 'en-GB-RyanNeural',
        'gold': 'en-US-GuyNeural',
    }
    _sch_tts_voice = _tts_voice_map.get(ctx._sch_subject_type, 'en-GB-RyanNeural')

    # 2026-08-12 (operator, on the Sikh Empire run): the narrator read "way
    # too excited". Two independent fixes, because timbre and delivery are
    # separate axes and only one of them is the voice.
    #
    # 1. TIMBRE — the narrator is now the FIXED reference voice
    #    m03_elder_gravel (the elder seed in the wholly-synthetic Maya1 pool),
    #    handed to tts_service as `seed_wav` instead of being reached through
    #    the voice-id md5 pick. That is the contract the briefing channels
    #    already use for their per-channel voices: hash-routing a WANTED seed
    #    means inventing a voice id whose md5 happens to land on it, and it
    #    re-breaks the day the pool gains a wav. The voice-id map above still
    #    names the id that goes into the logs and job state; it no longer
    #    decides how the narrator sounds. Every scholarly episode before this
    #    resolved to m08_wry_mid.
    # 2. DELIVERY — IndexTTS-2 infers an emotion per sentence from the text
    #    itself (`use_emo_text`) and applies it at ZYG_INDEXTTS_EMO_ALPHA=0.6.
    #    On a documentary script written to grip ("Imagine standing at the
    #    gates of Lahore…") that inference is exactly what produces an
    #    excited read, and no change of reference voice suppresses it. The
    #    briefing channels met the same complaint ("gets too excited at
    #    times") and answered it with alpha 0.45 + inference off, so the
    #    narrator takes its emotion from the reference voice's own steady
    #    read. Same defaults here.
    _sch_seed_wav = os.environ.get('ZYG_SCHOLARLY_SEED_WAV', '').strip() or os.path.join(
        _PKG_DIR, 'data', 'assets', 'voice_seeds', 'pool', 'm03_elder_gravel.wav'
    )
    _sch_emo_alpha = float(os.environ.get('ZYG_SCHOLARLY_EMO_ALPHA', '0.45') or 0.45)
    _sch_emo_text = os.environ.get('ZYG_SCHOLARLY_EMO_TEXT', '0').strip().lower() in ('1', 'true', 'yes', 'on')

    # 2026-09-23 (operator ruling): a pre-emptive RECORD run banks CLAUDE work only.
    # TTS is local, it is re-synthesised at render anyway, and it was the single biggest
    # cost in a recording — 22-25 min of the ~27, more than every Claude turn combined.
    # The turns after this stage embed an image-slot count derived from the narration
    # length, so the length still has to exist: the word-count estimate is used instead
    # (measured 2026-09-20: 2 082 words -> 1 041 s estimated vs 1 036 s synthesised,
    # 0.4 % out) and the slot count it produces is banked, so the replay — which does
    # synthesise for real — asks the identical question and hits by hash.
    _tts_skip_record = bool(ctx._preempt_mode == 'record')
    if _tts_skip_record:
        ctx._log(
            'INFO', 'Stage 4', '[preempt] record run — TTS skipped, narration length estimated from the word count'
        )
    return TtsSettings(
        voice_id=_sch_tts_voice,
        seed_wav=_sch_seed_wav,
        emo_alpha=_sch_emo_alpha,
        emo_text=_sch_emo_text,
        skip_record=_tts_skip_record,
    )


def _silent_placeholder(ctx, tts_path):
    """Write a silent mp3 as long as the script is estimated to read.

    In: the context and the narration path.  Out: True when the placeholder
    exists and is non-empty.  Used when the narrator is off and on a RECORD
    run, where the length still has to exist for the slot count below.
    """
    tts_ok = False
    _est_dur_s = max(300.0, len(ctx.narration_script.split()) * _SCHOLARLY_SEC_PER_WORD)
    try:
        import subprocess as _sp_sil

        _sp_sil.run(
            [
                exe('ffmpeg'),
                '-f',
                'lavfi',
                '-i',
                'anullsrc=channel_layout=stereo:sample_rate=44100',
                '-t',
                str(int(_est_dur_s)),
                '-q:a',
                '9',
                '-acodec',
                'libmp3lame',
                '-y',
                tts_path,
            ],
            check=True,
            capture_output=True,
        )
        tts_ok = os.path.exists(tts_path) and os.path.getsize(tts_path) > 0
    except Exception as _sil_e:
        ctx._log('WARNING', 'Stage 4', f'Silent audio generation failed: {_sil_e}')
    ctx._log('INFO', 'Stage 4', f'🔇 Narrator disabled — silent placeholder: {int(_est_dur_s)}s')
    return tts_ok


def _narrate(ctx, tts_path, st):
    """Produce the narration audio and measure it.

    In: the context, the mp3 path and the `TtsSettings`.  Out:
    `(tts_ok, voice_label, engine_meta, word_timings_raw)`; sets
    `ctx.tts_duration`.  Raises RuntimeError when the narrator was asked for
    and produced nothing — the film must not be built without it.
    """
    tts_ok = False
    _sch_voice = 'indextts2'
    _word_timings_raw = []

    if (not ctx.narration_enabled) or st.skip_record:
        _sch_voice = 'silent'
        _word_timings_raw = []
        tts_ok = _silent_placeholder(ctx, tts_path)

    _eng: dict = {}  # engine metadata (segments, partial flag) read by the guard below
    if ctx.narration_enabled and not tts_ok and not st.skip_record:
        # 2026-08-06 engine swap: IndexTTS-2 primary, Chatterbox fallback —
        # tts_service resolves the voice id to a gender-matched seed-pool
        # reference wav and falls back internally.
        if not os.path.isfile(st.seed_wav):
            # Fail loud rather than silently falling back to the md5 pick:
            # a missing seed wav would put the old m08_wry_mid narrator back
            # on the episode and nothing downstream would notice.
            ctx._log(
                'WARNING',
                'Stage 4',
                f'Narrator seed missing: {st.seed_wav} — falling back to the voice-id pick for {st.voice_id}',
            )
        _sch_ok, _ = _tts_shared(
            ctx.narration_script,
            tts_path,
            'Stage 4',
            ctx._log,
            voice_id=st.voice_id,
            engine_out=_eng,
            seed_wav=st.seed_wav,
            emo_alpha=st.emo_alpha,
            emo_text=st.emo_text,
        )
        if _sch_ok:
            tts_ok = True
            _sch_voice = f'{_eng.get("engine", "indextts2")} (seed {_eng.get("seed", "?")})'
            ctx._log('INFO', 'Stage 4', f'🎙️ TTS engine: {_sch_voice} ✓')

    if not tts_ok and not st.skip_record:
        raise RuntimeError('Stage 4: TTS audio generation failed')

    ctx._log('INFO', 'Stage 4', f'🎙️ TTS engine used: {_sch_voice}')

    try:
        import mutagen.mp3 as _mut_sch

        ctx.tts_duration = _mut_sch.MP3(tts_path).info.length
    except Exception:
        ctx.tts_duration = len(ctx.narration_script.split()) * _SCHOLARLY_SEC_PER_WORD

    ctx._log('INFO', 'Stage 4', f'TTS duration: {ctx.tts_duration:.0f}s ({ctx.tts_duration / 60:.1f} min)')
    return tts_ok, _sch_voice, _eng, _word_timings_raw


def _guard_narration(ctx, tts_path, st, eng):
    """The silent / partial narration guard (P-04).

    In: the context, the mp3 path, the `TtsSettings` and the engine metadata.
    Out: nothing; records `tts_partial`/`tts_segments` in the pipeline state.
    Raises RuntimeError on a silent track, or on a read that delivered under
    80 % of the segments it was asked for.
    """
    # A TTS file that is valid but silent, or a cloner that rendered only
    # part of the script, used to pass every gate: a file-size check,
    # "levelled to -14" regardless, and a 100% read-back by construction.
    # With the narrator ON these are fatal — the film must not be built.
    if not (ctx.narration_enabled and not st.skip_record):
        return
    try:
        from zyg_workflows import audio_mix as _am_guard

        _voice_silent = bool(_am_guard.is_silent(tts_path, log_fn=lambda m: ctx._debug('Stage 4', str(m))))
        if _voice_silent:
            # "Unmeasurable" counts as silent by design; one retry
            # separates a transient ffmpeg hiccup from real silence
            # before this becomes fatal.
            _voice_silent = bool(_am_guard.is_silent(tts_path, log_fn=lambda m: ctx._debug('Stage 4', str(m))))
    except Exception as _sil_g_e:
        _voice_silent = False
        ctx._log('WARNING', 'Stage 4', f'Silence check skipped: {_sil_g_e}')
    if _voice_silent:
        ctx._log('ERROR', 'Stage 4', 'Narration track is silent/unmeasurable — refusing to build the film')
        raise RuntimeError('Stage 4: narration track is silent — refusing to build the film')
    _seg_req = int(eng.get('segments_requested') or 0)
    _seg_ok = int(eng.get('segments_rendered') or 0)
    _tts_partial = bool(eng.get('partial')) or (_seg_req > 0 and _seg_ok < _seg_req)
    ctx.pipeline_state['tts_partial'] = _tts_partial
    ctx.pipeline_state['tts_segments'] = {
        'requested': _seg_req,
        'rendered': _seg_ok,
        'contiguous': eng.get('contiguous'),
    }
    if _tts_partial:
        _ratio_seg = (_seg_ok / _seg_req) if _seg_req else 0.0
        ctx._log(
            'WARNING',
            'Stage 4',
            f'TTS delivered a PARTIAL read: {_seg_ok}/{_seg_req} segments '
            f'({_ratio_seg:.0%}, contiguous={eng.get("contiguous")})',
        )
        if _seg_req and _ratio_seg < 0.8:
            raise RuntimeError(
                f'Stage 4: TTS rendered only {_seg_ok}/{_seg_req} segments — '
                f'refusing to build the film on a partial narration'
            )


def _level_narration(ctx, tts_path, tts_ok, voice_label):
    """Level the narration to -14 LUFS in place.

    In: the context, the mp3 path, whether it exists at all and the voice
    label.  Out: nothing; records `narration_lufs` in the pipeline state.
    """
    # Was a hand-rolled two-pass loudnorm that asked for linear=true and
    # never checked whether it got it. ffmpeg silently falls back to a
    # DYNAMIC AGC when the linear gain would breach TP — which is the
    # normal case here, because narration lands near -22 LUFS with peaks
    # already close to the ceiling, so an ~8 dB lift to -14 has nowhere to
    # go. The AGC lifts quiet passages and breathes on the pauses this
    # pipeline deliberately authors.
    #
    # audio_mix.level_to converges limiter-first and keeps the loudnorm
    # polish ONLY if it actually ran linear. Same target (-14 LUFS), same
    # in-place mp3 result; it just verifies what the old block assumed.
    if not (tts_ok and os.path.exists(tts_path)):
        return
    if voice_label == 'silent':
        ctx._log('INFO', 'Stage 4', 'Silent placeholder — levelling skipped')
        return
    try:
        from zyg_workflows import audio_mix as _am_ln

        _lv: dict = {}
        _lv_ok = _am_ln.level_to(
            tts_path, target_lufs=-14.0, tp_db=-1.0, log_fn=lambda m: ctx._debug('Stage 4', str(m)), result=_lv
        )
        _lv_final = _lv.get('final_lufs')
        _lv_txt = f'{_lv_final:.1f}' if isinstance(_lv_final, (int, float)) else 'unmeasured'
        if _lv_ok:
            ctx._log('INFO', 'Stage 4', f'Narration levelled to {_lv_txt} LUFS (target -14, limiter-first)')
        else:
            ctx._log(
                'WARNING',
                'Stage 4',
                f'Narration levelling did NOT reach -14 LUFS — measured {_lv_txt} LUFS '
                f'(input {_lv.get("input_lufs")}, silent={_lv.get("silent")})',
            )
        ctx.pipeline_state['narration_lufs'] = _lv_final
    except Exception as _ln_e:
        ctx._log('WARNING', 'Stage 4', f'Narration levelling exception: {_ln_e}')


def _collect_word_timings(ctx, tts_path, tts_ok, voice_label, word_timings_raw):
    """Word timings for the narration, and the pick that lands on ctx.

    In: the context, the mp3 path, whether it exists, the voice label and any
    timings the engine itself returned.  Out: `(whisper_timings, stats,
    align_coverage)`; sets `ctx._final_word_timings`.  A silent placeholder
    gets SYNTHETIC linear timings instead of a Whisper pass, because Whisper
    on silence hallucinates.
    """
    _whisper_timings = []
    _murch_whisper_debug: list = []
    _ws: dict = {}
    _script_word_count = len(ctx.narration_script.split())
    if voice_label == 'silent':
        # Narrator OFF: Whisper on a silent file hallucinates a handful of
        # words and the forced aligner interpolates the rest, so subtitles
        # and slot windows ended up keyed to noise. Synthetic linear
        # timings are honest about what they are.
        _n_syn = max(_script_word_count, 1)
        _whisper_timings = [
            (w, round(i * float(ctx.tts_duration) / _n_syn, 3)) for i, w in enumerate(ctx.narration_script.split())
        ]
        ctx._log(
            'INFO',
            'Stage 4',
            f'Narrator disabled — {len(_whisper_timings)} SYNTHETIC linear word timings '
            f'across {ctx.tts_duration:.0f}s (no Whisper, no ASR read-back)',
        )
    elif tts_ok and os.path.exists(tts_path) and not word_timings_raw:
        try:
            from zyg_workflows import murch_engine as _mew

            ctx._log('INFO', 'Stage 4', 'Running Whisper word-timestamp pass…')
            _whisper_timings = _mew.extract_word_timestamps_whisper(
                tts_path,
                ctx.narration_script,
                debug_log=_murch_whisper_debug,
                stats=_ws,
            )
            ctx._log('INFO', 'Stage 4', f'Whisper: {len(_whisper_timings)} word timestamps')
            for _mde in _murch_whisper_debug:
                ctx._debug(f'4/whisper/{_mde["fn"]}', _mde['msg'], level=_mde.get('level', 'DEBUG'))
        except Exception as _we:
            ctx._log('WARNING', 'Stage 4', f'Whisper pass failed: {_we}')

    _whisper_coverage = len(_whisper_timings) / max(_script_word_count, 1)
    _align_coverage = None
    if word_timings_raw:
        ctx._final_word_timings, _align_coverage = _align_narration_word_timings(ctx.narration_script, word_timings_raw)
    elif _whisper_coverage >= 0.10:
        ctx._final_word_timings = _whisper_timings
    else:
        ctx._final_word_timings = word_timings_raw
    return _whisper_timings, _ws, _align_coverage


def _asr_read_back(ctx, voice_label, stats, align_coverage):
    """The script/speech agreement gate.

    In: the context, the voice label, the Whisper aligner's own stats and the
    coverage the timings pick produced.  Out: nothing; records the read-back
    numbers in the pipeline state and warns when agreement is under the floor.
    Raises RuntimeError when Whisper ran and heard nothing, or under 30 % of
    the script — that narration is unusable.
    """
    # _whisper_coverage above is only a word-COUNT ratio: it cannot tell a
    # correct read from a cloner that dropped a clause, because both give
    # the same count. This compares the actual words.
    #
    # Computed from _final_word_timings rather than from a branch return
    # value, because there are three ways to get here and only one of them
    # goes through _align_narration_word_timings. On the Byzantine run
    # word_timings_raw was empty, so the alignment happened inside
    # extract_word_timestamps_whisper instead and a branch-local capture
    # recorded nothing at all (asr_alignment_coverage: None).
    #
    # P-02: the aligner's output contains EVERY script word (deleted ones
    # get interpolated timestamps), so a set intersection of script vs
    # aligned words is 1.0 by construction — it read 100% on a file of
    # digital silence. The honest number is matched/N from the aligner's
    # own op counts (stats); the set intersection survives only as the
    # legacy fallback for word timings that carry no provenance.
    _align_coverage = align_coverage
    if voice_label == 'silent':
        _align_coverage = None
    elif stats.get('asr_error'):
        # Whisper itself failed (import, model load, OOM…): the stats are
        # pre-filled with match_ratio=0.0, which must NOT read as "heard
        # nothing". The gate is skipped, loudly, and the film is built on
        # uniform timings exactly as before.
        _align_coverage = None
        ctx.pipeline_state['asr_error'] = str(stats.get('asr_error'))
        ctx._log('WARNING', 'Stage 4', f'Whisper failed ({stats.get("asr_error")}) — ASR read-back gate skipped')
    elif stats.get('n_script'):
        _align_coverage = float(stats.get('match_ratio') or 0.0)
        _n_raw_w = int(stats.get('n_whisper_raw') or 0)
        _n_match_w = int(stats.get('n_match') or 0)
        ctx.pipeline_state['whisper_raw_words'] = _n_raw_w
        ctx.pipeline_state['whisper_matched'] = _n_match_w
        ctx.pipeline_state['whisper_match_ratio'] = round(_align_coverage, 4)
        ctx.pipeline_state['asr_empty'] = bool(stats.get('asr_empty'))
        ctx._log(
            'INFO',
            'Stage 4',
            f'ASR read-back: {_n_match_w}/{int(stats.get("n_script") or 0)} script words '
            f'matched ({_align_coverage:.1%}); raw Whisper words {_n_raw_w}, '
            f'interpolated {int(stats.get("n_delete") or 0)}',
        )
        # Fatal only when Whisper actually RAN: an empty transcript, or a
        # transcript that agrees with less than 30% of the script.
        if ctx.narration_enabled and (stats.get('asr_empty') or (_n_raw_w > 0 and _align_coverage < 0.3)):
            _heard = 'nothing' if stats.get('asr_empty') else f'only {_align_coverage:.0%} of the script'
            ctx._log(
                'ERROR',
                'Stage 4',
                f'ASR read-back: Whisper heard {_heard} — refusing to build the film on this narration',
            )
            raise RuntimeError(
                f'Stage 4: ASR read-back {_align_coverage:.0%} (raw Whisper words {_n_raw_w}) — narration unusable'
            )
        # Truncation check: where does the last MATCHED word sit?
        try:
            _m_idx = stats.get('matched_idx') or []
            if _m_idx and ctx._final_word_timings and ctx.tts_duration:
                _last_m = max(int(i) for i in _m_idx)
                _last_t = float(ctx._final_word_timings[min(_last_m, len(ctx._final_word_timings) - 1)][1])
                if _last_t < 0.8 * float(ctx.tts_duration):
                    ctx._log(
                        'WARNING',
                        'Stage 4',
                        f'ASR read-back: last matched word at {_last_t:.0f}s of '
                        f'{ctx.tts_duration:.0f}s — the narration may be truncated or '
                        f'its tail unspoken; listen before publishing',
                    )
        except (TypeError, ValueError, IndexError) as _exc:
            _zyg_log.warning('ASR read-back not checked, a truncated narration would go unflagged: %s', _exc)
    elif _align_coverage is None and ctx._final_word_timings:
        try:
            from zyg_workflows import murch_engine as _me_cov

            _align_coverage = _me_cov.alignment_coverage(ctx.narration_script.split(), ctx._final_word_timings)
        except Exception:
            _align_coverage = None
    if _align_coverage is not None:
        ctx.pipeline_state['asr_alignment_coverage'] = round(float(_align_coverage), 4)
        _asr_floor = float(os.environ.get('ZYG_SCHOLARLY_ASR_FLOOR', '0.60') or 0.60)
        if _align_coverage < _asr_floor:
            ctx._log(
                'WARNING',
                'Stage 4',
                f'ASR read-back: only {_align_coverage:.1%} of the script is '
                f'accounted for in the spoken audio (floor {_asr_floor:.0%}) — '
                f'the narration may have dropped or invented words; '
                f'listen before publishing',
            )
        else:
            ctx._log('INFO', 'Stage 4', f'ASR read-back: {_align_coverage:.1%} script/speech agreement')


def _extract_rhythm_cuts(ctx, tts_path, tts_ok):
    """Rhythm cut cues for the image slots.

    In: the context, the mp3 path and whether it exists.  Out: the list of cut
    cues — one fewer than the image count estimated from `ctx.tts_duration`,
    which is refreshed after stage 3.5.  A librosa failure is a warning, not a
    stop: the film is cut on uniform timings instead.
    """
    _rhythm_cuts = []
    _murch_rhythm_debug: list = []
    _pre_n_images = _scholarly_n_images(ctx.tts_duration)
    if tts_ok and os.path.exists(tts_path):
        try:
            from zyg_workflows import murch_engine as _mer

            _rhythm_cuts = _mer.extract_audio_rhythm(
                tts_path,
                n_cuts=max(_pre_n_images - 1, 0),
                debug_log=_murch_rhythm_debug,
            )
            ctx._log('INFO', 'Stage 4', f'Rhythm alignment: {len(_rhythm_cuts)} cut cues')
        except Exception as _re:
            ctx._log('WARNING', 'Stage 4', f'Librosa rhythm pass failed: {_re}')
    return _rhythm_cuts


def _publish_tts_state(ctx, tts_path, tts_ok, voice_label, word_timings_raw, whisper_timings, rhythm_cuts):
    """Write the stage's results into the pipeline state and close the stage.

    In: the context plus everything the steps above produced.  Out: nothing;
    saves the state and reports the stage done with its duration, voice,
    Whisper word count and cut count.
    """
    ctx.pipeline_state['tts_path'] = tts_path
    ctx.pipeline_state['tts_duration'] = round(ctx.tts_duration, 1)
    ctx.pipeline_state['tts_voice'] = voice_label
    ctx.pipeline_state['word_timings_raw'] = word_timings_raw
    ctx.pipeline_state['whisper_timings'] = whisper_timings
    ctx.pipeline_state['final_word_timings'] = ctx._final_word_timings
    ctx.pipeline_state['rhythm_cuts'] = rhythm_cuts
    ctx.pipeline_state['wan_enabled'] = False
    ctx.pipeline_state['wan_clips'] = []
    ctx._save()
    ctx._done(
        'Stage 4: TTS Narration',
        {
            'duration_s': round(ctx.tts_duration, 1),
            'voice': voice_label if tts_ok else 'indextts2',
            'whisper_words': len(whisper_timings),
            'rhythm_cuts': len(rhythm_cuts),
        },
    )


def stage_08_tts_pre_image_pass(ctx):
    # ── Stage 4 (pre-image pass): TTS + word timings ──────────────────────
    # TTS runs before image generation so Whisper word timings are available
    # to lock every FLUX image to the exact narration moment it will accompany.
    ctx._stage_start('Stage 4: TTS Narration')
    ctx._assert_not_stopped('Stage 4')
    ctx.job['current_stage'] = 'Stage 4: TTS Narration'
    _update_marker(ctx._pipeline_marker, label=f'🔄 Scholarly {ctx.pipeline_id[:8]} — TTS Narration')
    ctx._log('INFO', 'Stage 4', 'Generating TTS audio (pre-image pass for time-locked alignment)')

    tts_path = os.path.join(ctx.out_dir, f'{ctx._slug}_narration.mp3')
    _st = _tts_settings(ctx)
    tts_ok, _sch_voice, _eng, _word_timings_raw = _narrate(ctx, tts_path, _st)

    # ── Silent / partial narration guard (P-04) ─────────────────────────
    _guard_narration(ctx, tts_path, _st, _eng)
    # ── Narration levelling ──────────────────────────────────────────
    _level_narration(ctx, tts_path, tts_ok, _sch_voice)

    _whisper_timings, _ws, _align_coverage = _collect_word_timings(ctx, tts_path, tts_ok, _sch_voice, _word_timings_raw)
    # ── Script/speech agreement ─────────────────────────────────────────
    _asr_read_back(ctx, _sch_voice, _ws, _align_coverage)

    # Rhythm cuts — use estimated image count from tts_duration (will be refreshed post-3.5)
    _rhythm_cuts = _extract_rhythm_cuts(ctx, tts_path, tts_ok)
    _publish_tts_state(ctx, tts_path, tts_ok, _sch_voice, _word_timings_raw, _whisper_timings, _rhythm_cuts)
