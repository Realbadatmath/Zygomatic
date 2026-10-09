# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tts_service.py — the ASR read-back gate shared by every _tts_shared caller (lines 812-1061 of the pre-split file, verbatim)."""

import logging as _zyg_logging
from .constants import os, re, shutil
from .engines import _indextts_segments, _chatterbox_segments

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.tts_service')


# ── ASR read-back gate (shared by every _tts_shared caller) ─────────────────
# Both cloners are autoregressive and can drop a clause or invent a name — the
# briefing channels caught one speaking a football club that does not exist.
# This transcribes each rendered segment back with faster-whisper, compares the
# words actually spoken against the script, and re-rolls the ones that do not
# match. Living in tts_service means documentary, storyteller and narration all
# get it from one implementation, instead of the briefing pipeline being the
# only place it exists.
#
# Fail-open throughout: no whisper, a raised exception, a re-roll that produces
# nothing — the narration ships as it always did, with a WARNING. A QC gate must
# never be able to kill an episode.
_ASR_NUM_WORDS = frozenset(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen '
    'fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty '
    'fifty sixty seventy eighty ninety hundred thousand million billion point '
    'percent oh a an and the'.split()
)


def _asr_tokens(text: str) -> list:
    """Comparable spoken-word tokens: unaccented, lowercase, numbers dropped.

    Numbers are dropped on both sides because the script writes "1801" and the
    ASR hears "eighteen oh one" — a mismatch there is a spelling difference, not
    a misread, and would swamp the signal we actually want.
    """
    import unicodedata

    _t = unicodedata.normalize('NFKD', str(text or ''))
    _t = ''.join(c for c in _t if not unicodedata.combining(c))
    return [w for w in re.findall(r'[a-z]+', _t.lower()) if w not in _ASR_NUM_WORDS]


def _asr_similarity(intended: str, heard: str) -> float:
    import difflib

    _a, _b = _asr_tokens(intended), _asr_tokens(heard)
    if not _a:
        return 1.0
    return difflib.SequenceMatcher(None, _a, _b).ratio()


def _asr_inserted_run(intended: str, heard: str) -> str:
    """A run of words the voice said that the script does not contain.

    The ratio and the name check both measure what went MISSING, so neither can
    see a hallucination. The Byzantine run spoke "Jian, Jian, Jian" aloud at six
    section separators and every check passed it: three inserted tokens in a
    fifteen-token segment barely move the ratio, and nothing is absent. An
    insertion is the failure the briefing channels originally built their gate
    for — a club that does not exist — so it has to be its own signal.

    Returns the longest inserted run of 2+ words, or ''. Two is the floor
    because a single inserted filler ("the", "a") is normal ASR noise; a
    repeated syllable or an invented clause is not.
    """
    import difflib

    _a = _asr_tokens(intended)
    _b = _asr_tokens(heard)
    if not _a or not _b:
        return ''
    _worst = []
    for _tag, _i1, _i2, _j1, _j2 in difflib.SequenceMatcher(None, _a, _b).get_opcodes():
        if _tag not in ('insert', 'replace'):
            continue
        _run = _b[_j1:_j2]
        # 'replace' is only an insertion when the voice added materially more
        # than it swapped — a like-for-like mis-hearing is not a hallucination.
        if _tag == 'replace' and len(_run) <= (_i2 - _i1) + 1:
            continue
        if len(_run) >= 2 and len(_run) > len(_worst):
            _worst = _run
    return ' '.join(_worst)


def _asr_missing_names(intended: str, heard: str) -> list:
    """Proper nouns in the script that the ASR did not hear at all.

    A whole-sentence similarity ratio is dominated by the words that DID match,
    so exactly the failure this gate exists to catch hides inside it: dropping
    "Mohkam Chand" from a 10-word sentence still scores 0.88, and swapping
    "Amritsar" for "Amsterdam" scores 0.67 — both above the ratio threshold the
    briefing channels use for their much shorter copy. Names are the load-bearing
    words in a documentary, so they get checked individually.

    Matching is fuzzy because ASR legitimately re-spells unfamiliar proper
    nouns, and a strict compare would re-roll perfectly good audio. Two ways to
    count as heard, measured on real documentary names:

      * ratio >= 0.80          — "Theodosius"/"Theodosious" (0.95)
      * ratio >= 0.55 AND the first three letters agree
                               — "Nicene"/"Nicaean" (0.62), "Ranjit"/"Ranjeet"

    The prefix clause is what separates a re-spelling from a substitution: a
    mis-heard name keeps its opening ("nic…"/"nic…"), a substituted one does not
    ("Amritsar" heard as "Amsterdam" shares only "am" and scores 0.44). Without
    it the fuzzy threshold has to sit so low that real substitutions slip past.

    Sentence-initial words are skipped: they are capitalised by position, not
    because they are names.
    """
    import difflib

    _words = re.findall(r"[A-Za-z][A-Za-z'’-]+", intended or '')
    if len(_words) < 2:
        return []
    _heard = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'’-]+", heard or '')}
    _missing = []
    for _w in _words[1:]:  # skip the sentence-initial word
        if not _w[0].isupper() or len(_w) < 4:
            continue
        _lw = _w.lower()
        if _lw in _heard:
            continue
        _hit = False
        for _h in _heard:
            _r = difflib.SequenceMatcher(None, _lw, _h).ratio()
            if _r >= 0.80 or (_r >= 0.55 and _lw[:3] == _h[:3]):
                _hit = True
                break
        if not _hit:
            _missing.append(_w)
    return _missing


def _tts_asr_read_back(
    segments: list, paths: list, work_dir: str, ref_wav: str, engine: str, log, emo_alpha=None, emo_text=None
) -> dict:
    """Verify each rendered segment says its script; re-roll the ones that don't.

    Returns a stats dict for the caller to record. Mutates `paths` in place when
    a re-roll reads better than the original.
    """
    _stats = {'checked': 0, 'flagged': 0, 'rerolled': 0, 'kept': 0, 'skipped': 0}
    if os.environ.get('ZYG_TTS_ASR_QC', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return _stats
    try:
        import zyg_whisper
    except Exception as _e:
        log('WARNING', f'ASR read-back: zyg_whisper unavailable ({_e!r}) — narration ships unverified')
        _stats['skipped'] = len(paths)
        return _stats

    _model = os.environ.get('ZYG_TTS_ASR_MODEL', 'small')
    # Deliberately LOWER than the briefing channels' 0.66. There the ratio is
    # the whole gate; here _asr_missing_names does the precision work, so the
    # ratio is only the gross-truncation backstop. Measured on documentary
    # sentences: a legitimate ASR re-spelling of unfamiliar proper nouns
    # ("Ranjit Singh … Maharaja" heard as "Ranjeet Sing … Maharajah") scores
    # 0.62 and must NOT re-roll; a genuinely truncated read scores 0.44 and must.
    _thr = float(os.environ.get('ZYG_TTS_ASR_MIN', '0.55') or 0.55)

    def _hear(_wav):
        _rows, _ = zyg_whisper.transcribe_segments(_wav, language='en', vad=False, beam_size=1, model_size=_model)
        return ' '.join(r['text'] for r in _rows)

    try:
        _sims, _bad, _reasons, _misses = {}, [], {}, {}
        for _i, _p in enumerate(paths):
            if _i >= len(segments):
                break
            if not (os.path.isfile(_p) and os.path.getsize(_p) > 512):
                _stats['skipped'] += 1
                continue
            _heard = _hear(_p)
            _s = _asr_similarity(segments[_i][0], _heard)
            _miss = _asr_missing_names(segments[_i][0], _heard)
            _ins = _asr_inserted_run(segments[_i][0], _heard)
            _sims[_i] = _s
            _misses[_i] = _miss
            _stats['checked'] += 1
            if _s < _thr or _miss or _ins:
                _reasons[_i] = (
                    f'match {_s:.2f} < {_thr}'
                    if _s < _thr
                    else f'name(s) not spoken: {", ".join(_miss[:4])}'
                    if _miss
                    else f'said words not in the script: {_ins[:60]!r}'
                )
                # The heard text is the only way to tell a real misread from a
                # gate bug after the fact — the segment wavs are deleted at the
                # end of _tts_shared, so without it a flag is undiagnosable.
                _reasons[_i] += f' | heard: {_heard.strip()[:140]!r}'
                _bad.append(_i)

        if not _bad:
            log('INFO', f'ASR read-back: {_stats["checked"]}/{_stats["checked"]} segment(s) match their script')
            return _stats

        _stats['flagged'] = len(_bad)
        for _i in _bad:
            log(
                'WARNING',
                f'ASR read-back: segment {_i} does not say its script '
                f'({_reasons.get(_i, "mismatch")}) — re-rolling: '
                f'{segments[_i][0][:100]!r}',
            )

        # Re-roll with a DIFFERENT seed. The worker uses --seed verbatim on its
        # first attempt, so re-running the same text on the same seed returns
        # the same audio and the retry would be theatre.
        _base = int(os.environ.get('ZYG_INDEXTTS_SEED', '1672') or 1672)
        _retry_dir = os.path.join(work_dir, 'asr_retry')
        _sub = [segments[_i] for _i in _bad]
        if engine == 'indextts2':
            _new = _indextts_segments(
                _sub, _retry_dir, ref_wav, log, emo_alpha=emo_alpha, emo_text=emo_text, seed=_base + 7919
            )
        else:
            _new = _chatterbox_segments(_sub, _retry_dir, ref_wav, log)

        for _k, _i in enumerate(_bad):
            _src = _new[_k] if _k < len(_new) else None
            if not (_src and os.path.isfile(_src) and os.path.getsize(_src) > 512):
                log('WARNING', f'ASR read-back: segment {_i} re-roll produced no audio — keeping the original read')
                _stats['kept'] += 1
                continue
            _heard2 = _hear(_src)
            _s2 = _asr_similarity(segments[_i][0], _heard2)
            _miss2 = _asr_missing_names(segments[_i][0], _heard2)
            # Judge the re-roll on the SAME two signals that flagged it. Judging
            # only on the ratio threw away good takes: segment 50 of the
            # Byzantine run was flagged for not saying "Civilis", re-rolled, and
            # discarded because the ratio happened to tie at 0.94 — the one
            # question that mattered (does it say the name now?) was never asked.
            _n1, _n2 = len(_misses.get(_i) or ()), len(_miss2)
            _better = (_n2 < _n1) or (_n2 == _n1 and _s2 > _sims[_i])
            if _better:
                shutil.copy2(_src, paths[_i])
                _stats['rerolled'] += 1
            else:
                _stats['kept'] += 1
            _fixed = _n2 == 0 and _n1 > 0
            log(
                'INFO' if (_fixed or max(_s2, _sims[_i]) >= _thr) else 'WARNING',
                f'ASR read-back: segment {_i} match {_sims[_i]:.2f} → {_s2:.2f}, '
                f'missing names {_n1} → {_n2} '
                f'({"re-rolled" if _better else "original kept"})',
            )
        return _stats
    except Exception as _e:
        log('WARNING', f'ASR read-back raised ({_e!r}) — narration continues unverified')
        return _stats
    finally:
        try:  # never leave whisper resident in the GUI process
            zyg_whisper.unload_models()
        except Exception as _exc:
            _zyg_log.debug('whisper unload skipped: %s', _exc)
