# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.briefing_video.tts — TTS, the ASR read-back gate, speak_batch.

Moved verbatim out of briefing_video.py (lines 1020-1349); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.briefing_video.base import _CREWS, _zyg_log, os, re, shutil


# ── TTS ─────────────────────────────────────────────────────────────────────


def speak(text: str, wav_path: str, seed_wav: str = '', voice_id: str = '', log=None) -> bool:
    """One narration segment → wav. IndexTTS-2 primary, Chatterbox fallback."""
    try:
        from zyg_workflows import tts_service as _tts
    except Exception as e:
        if log:
            log('ERROR', f'tts_service unavailable: {e!r}')
        return False

    def _lf(level, stage, msg):
        if log:
            log(level if level in ('INFO', 'WARNING', 'ERROR') else 'INFO', msg)

    try:
        ok, _ = _tts._tts_shared(text, wav_path, 'Narrate', log_fn=_lf, voice_id=voice_id, seed_wav=seed_wav)
    except TypeError:
        # tts_service predates the seed_wav kwarg — fall back to voice-id routing
        ok, _ = _tts._tts_shared(text, wav_path, 'Narrate', log_fn=_lf, voice_id=voice_id)
    except Exception as e:
        if log:
            log('WARNING', f'TTS raised: {e!r}')
        return False
    return bool(ok) and os.path.isfile(wav_path) and os.path.getsize(wav_path) > 1000


def seed_path(seed_name: str) -> str:
    p = os.path.join(_CREWS, 'data', 'assets', 'voice_seeds', 'pool', f'{seed_name}.wav')
    return p if os.path.isfile(p) else ''


def _indextts_call(tts_mod, segs, out_dir, ref, lf):
    """IndexTTS-2 with the briefing channels' CALM delivery.

    The first TokiToki episode ran the storyteller defaults — emotion-from-text
    ON at alpha 0.6 — and exclamatory betting copy drove the presenter audibly
    over-excited (operator complaint 2026-08-07). Briefing episodes read with
    emotion-from-text OFF and a lower alpha; the reference voice still carries
    the channel's character. ZYG_BRIEF_CALM_TTS=0 restores the old behaviour.
    """
    kw = {}
    if os.environ.get('ZYG_BRIEF_CALM_TTS', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
        kw = {
            'emo_alpha': float(os.environ.get('ZYG_BRIEF_EMO_ALPHA', '0.45') or 0.45),
            'emo_text': os.environ.get('ZYG_BRIEF_EMO_TEXT', '0').strip().lower() in ('1', 'true', 'yes', 'on'),
        }
    try:
        return tts_mod._indextts_segments(segs, out_dir, ref, lf, **kw)
    except TypeError:  # tts_service predates the emotion kwargs
        return tts_mod._indextts_segments(segs, out_dir, ref, lf)


# ── ASR read-back gate ──────────────────────────────────────────────────────
# An autoregressive cloner can hallucinate words: the 2026-08-08 episode spoke
# "NEC Nijmegen" as a club that does not exist on its first mention. The gate
# transcribes every rendered sentence back with faster-whisper, compares the
# words actually spoken with the script, and re-rolls any sentence that does not
# match before the episode is assembled. ZYG_BRIEF_TTS_ASR_QC=0 disables.

_ASR_NUM_WORDS = frozenset(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen '
    'fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty '
    'fifty sixty seventy eighty ninety hundred thousand million point percent oh '
    'a an and'.split()
)


def _asr_tokens(text: str) -> list:
    """Comparable spoken-word tokens: unaccented, lowercase, digits and number
    words dropped (the script writes '7.5', the ASR hears 'seven point five' —
    numbers are already covered by the invented-number guard upstream)."""
    import unicodedata

    t = unicodedata.normalize('NFKD', str(text or ''))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return [w for w in re.findall(r'[a-z]+', t.lower()) if w not in _ASR_NUM_WORDS]


def _asr_similarity(intended: str, heard: str) -> float:
    import difflib

    a, b = _asr_tokens(intended), _asr_tokens(heard)
    if not a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _asr_read_back_gate(tts_mod, segs, expected, batch_dir, ref, lf, log):
    """Verify each rendered sentence says its script; re-roll the ones that don't.

    Fail-open by design: if whisper is unavailable the batch ships unverified
    (as it always did) with a WARNING, never a dead episode."""
    if os.environ.get('ZYG_BRIEF_TTS_ASR_QC', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return
    try:
        import zyg_whisper
    except Exception as e:
        if log:
            log('WARNING', f'ASR gate: zyg_whisper unavailable ({e!r}) — narration ships unverified')
        return
    model_size = os.environ.get('ZYG_BRIEF_ASR_MODEL', 'small')
    thr = float(os.environ.get('ZYG_BRIEF_ASR_MIN', '0.66') or 0.66)

    def _hear(wav):
        rows, _info = zyg_whisper.transcribe_segments(wav, language='en', vad=False, beam_size=1, model_size=model_size)
        return ' '.join(r['text'] for r in rows)

    sims, bad = {}, []
    try:
        for i, (sent, _pause) in enumerate(segs):
            p = expected[i]
            if not (os.path.isfile(p) and os.path.getsize(p) > 512):
                continue  # dropped-line tier already logged it
            sim = _asr_similarity(sent, _hear(p))
            sims[i] = sim
            if sim < thr:
                bad.append(i)
        if not bad:
            if log:
                log('INFO', f'ASR gate: {len(sims)}/{len(sims)} segment(s) read back matching their script')
            return
        for i in bad:
            if log:
                log(
                    'WARNING',
                    f'ASR gate: segment {i} does not say its script '
                    f'(match {sims[i]:.2f} < {thr}) — re-rolling: '
                    f'{segs[i][0][:100]!r}',
                )
        retry_dir = os.path.join(batch_dir, 'asr_retry')
        sub = [segs[i] for i in bad]
        _indextts_call(tts_mod, sub, retry_dir, ref, lf)
        _sbp, sub_expected = tts_mod._tts_batch_file(sub, retry_dir)
        for k, i in enumerate(bad):
            src = sub_expected[k]
            if not (os.path.isfile(src) and os.path.getsize(src) > 512):
                if log:
                    log('WARNING', f'ASR gate: segment {i} re-roll produced no audio — keeping the original read')
                continue
            sim2 = _asr_similarity(segs[i][0], _hear(src))
            if sim2 > sims[i]:
                shutil.copy2(src, expected[i])
            if log:
                log(
                    'INFO' if max(sim2, sims[i]) >= thr else 'WARNING',
                    f'ASR gate: segment {i} match {sims[i]:.2f} → {sim2:.2f} '
                    f'({"re-rolled" if sim2 > sims[i] else "original kept"})',
                )
    except Exception as e:
        if log:
            log('WARNING', f'ASR gate raised ({e!r}) — narration continues unverified')
    finally:
        try:  # never leave whisper resident in the GUI process
            zyg_whisper.unload_models()
        except Exception as _exc:
            _zyg_log.debug('whisper unload skipped: %s', _exc)


def speak_batch(items: list, work_dir: str, seed_wav: str = '', voice_id: str = '', log=None) -> dict:
    """[(key, text)] → {key: wav}. ONE engine invocation for the whole episode.

    Measured 2026-08-06: IndexTTS-2 spends ~16 s loading its weights per worker
    call, and `speak()` is one call per panel. A betting episode has 23 panels, so
    per-panel synthesis burns ~6 minutes of GPU on nothing but model loading —
    every day, on every sub-channel. Batching every panel's sentences into a
    single worker run pays that cost once.

    Alignment is positional and deterministic: `_tts_batch_file` names outputs
    seg_0000.wav … in list order, so recomputing it gives the same paths the
    worker just wrote and each panel takes its own slice. A panel whose slice is
    not fully present is NOT delivered from the batch — it is returned unset so
    the caller re-runs it through `speak()`. Set ZYG_BRIEF_TTS_BATCH=0 to disable
    and go back to one call per panel.
    """
    out: dict = {}
    if os.environ.get('ZYG_BRIEF_TTS_BATCH', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return out
    try:
        from zyg_workflows import tts_service as _tts
    except Exception as e:
        if log:
            log('WARNING', f'tts_service unavailable for batching: {e!r}')
        return out

    # tts_service's ENGINE helpers (_indextts_segments / _chatterbox_segments /
    # _tts_assemble) take a two-argument log(level, msg). Only _tts_shared's
    # `log_fn` is the three-argument (level, stage, msg) form that `speak()` above
    # passes. Getting this wrong throws inside the batch and silently demotes the
    # whole episode to per-panel synthesis.
    def _lf(level, msg):
        if log:
            log(level if level in ('INFO', 'WARNING', 'ERROR') else 'INFO', msg)

    spans, segs = {}, []
    for key, text in items:
        clean = _tts._tts_clean_text(text or '')
        s = _tts._tts_split_sentences(clean) if clean else []
        if not s:
            continue
        spans[key] = (len(segs), len(segs) + len(s))
        segs.extend(s)
    if not segs:
        return out

    try:
        _seed_name, ref = _tts._voice_seed_for(voice_id, seed_wav=seed_wav)
    except TypeError:  # tts_service predates the kwarg
        _seed_name, ref = _tts._voice_seed_for(voice_id)
    if not ref:
        if log:
            log('WARNING', 'no reference voice for the batch — per-panel fallback')
        return out

    batch_dir = os.path.join(work_dir, 'tts_batch')
    dropped: list = []  # segment indices IndexTTS-2 could not render
    if log:
        log(
            'INFO',
            f'TTS batch: {len(items)} panel(s), {len(segs)} segment(s), '
            f'{sum(len(s.split()) for s, _ in segs)} words, voice {_seed_name} '
            f'— one model load',
        )
    try:
        paths = _indextts_call(_tts, segs, batch_dir, ref, _lf)
        engine = 'indextts2'
        _bp, expected = _tts._tts_batch_file(segs, batch_dir)

        def _missing():
            return [i for i, p in enumerate(expected) if not (os.path.isfile(p) and os.path.getsize(p) > 512)]

        if not paths:
            # `_indextts_segments` is all-or-nothing: it discards a whole run when
            # ANY segment fails its duration-sanity check. At batch scale that is
            # the wrong trade — a 65-segment episode losing its primary voice
            # because 2 segments came out wrong. Re-run only the failures first.
            # The worker seeds per item index, so a smaller batch really is a
            # different roll rather than a repeat of the same one.
            gap = _missing()
            if gap and len(gap) <= max(3, len(segs) // 8):
                if log:
                    log(
                        'INFO',
                        f'IndexTTS-2 left {len(gap)}/{len(segs)} segment(s) '
                        f'short — retrying just those before any fallback',
                    )
                sub_dir = os.path.join(batch_dir, 'retry')
                sub = [segs[i] for i in gap]
                _indextts_call(_tts, sub, sub_dir, ref, _lf)
                _sbp, sub_expected = _tts._tts_batch_file(sub, sub_dir)
                for k, idx in enumerate(gap):
                    src = sub_expected[k]
                    if os.path.isfile(src) and os.path.getsize(src) > 512:
                        shutil.copy2(src, expected[idx])
                if not _missing():
                    paths = list(expected)
                    if log:
                        log('INFO', 'IndexTTS-2 recovered on retry — primary voice kept')

        if not paths:
            # LAST TIER BEFORE THE FALLBACK. An episode is ~70 sentences, and
            # IndexTTS-2 rejects the occasional one on its own duration-sanity
            # check no matter how many seeds it tries. Downgrading all 70 to the
            # weaker engine because 1 of them is stubborn means the channel loses
            # its voice on most episodes — a much bigger loss than the sentence.
            # So: drop the irrecoverable sentences, keep the primary voice, and
            # say exactly which lines were dropped. Never silently.
            gap = _missing()
            if gap and len(gap) <= max(2, len(segs) // 20):
                dropped[:] = gap
                paths = [p for p in expected if os.path.isfile(p) and os.path.getsize(p) > 512]
                if log:
                    for i in gap:
                        log(
                            'WARNING',
                            'IndexTTS-2 could not render this line after '
                            f'retries — DROPPED from the episode: '
                            f'{segs[i][0][:110]!r}',
                        )
                    log(
                        'WARNING',
                        f'{len(gap)}/{len(segs)} line(s) dropped to keep '
                        f'the primary voice for the other '
                        f'{len(segs) - len(gap)}',
                    )
        if not paths:
            # Still short: fall back for the WHOLE episode so one engine speaks
            # throughout. _chatterbox_segments wipes the stale primary files
            # first, so a partial fallback can never blend the two voices.
            paths = _tts._chatterbox_segments(segs, batch_dir, ref, _lf)
            engine = 'chatterbox-fallback'
        if not paths:
            return out
        if engine == 'indextts2':
            # every sentence must actually SAY its script before assembly
            _asr_read_back_gate(_tts, segs, expected, batch_dir, ref, _lf, log)
    except Exception as e:
        if log:
            log('WARNING', f'TTS batch raised ({e!r}) — per-panel fallback')
        return out

    ok_n, drop_set = 0, set(dropped)
    for key, (a, b) in spans.items():
        # Keep only the segments that actually exist. When `dropped` is empty this
        # is the strict all-or-nothing check as before; when a line was dropped
        # above, the panel is assembled from the rest instead of being handed
        # back for a per-panel re-run that would use a different engine.
        idxs = [i for i in range(a, b) if os.path.isfile(expected[i]) and os.path.getsize(expected[i]) > 512]
        if len(idxs) < (b - a) and not drop_set:
            continue  # caller re-runs this panel alone
        if not idxs:
            continue
        sub_p = [expected[i] for i in idxs]
        sub_s = [segs[i] for i in idxs]
        wav = os.path.join(work_dir, f'seg_{_slugkey(key)}.wav')
        try:
            if _tts._tts_assemble(sub_p, sub_s, wav, _lf) and os.path.isfile(wav) and os.path.getsize(wav) > 1000:
                out[key] = wav
                ok_n += 1
        except Exception as _exc:
            _zyg_log.warning('panel TTS assembly failed, panel left without audio: %s', _exc)
            continue
    if log:
        log('INFO', f'TTS batch ({engine}): {ok_n}/{len(spans)} panel(s) assembled')
    return out


def _slugkey(key) -> str:
    return re.sub(r'[^A-Za-z0-9_-]', '_', str(key))[:40]
