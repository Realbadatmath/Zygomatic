# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tts_service.py — text helpers: roman numerals, cleaning, sentence splitting, chunking, edge-silence trim (lines 113-289 of the pre-split file, verbatim)."""

import logging as _zyg_logging
from .constants import (
    re,
    _TTS_MAX_CHARS,
    _ROMAN_VALUES,
    _ROMAN_CANON,
    _ROMAN_CARDINAL_BEFORE,
    _ROMAN_MAX,
    _ORD_UNITS,
    _CARD_UNITS,
    _CARD_TENS,
    _ORD_TENS,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.tts_service')


def _roman_to_int(s: str) -> int:
    _v = [_ROMAN_VALUES[c] for c in s]
    return sum(-x if i + 1 < len(_v) and x < _v[i + 1] else x for i, x in enumerate(_v))


def _int_to_cardinal(n: int) -> str:
    if n < 20:
        return _CARD_UNITS[n]
    _t, _u = (n // 10) * 10, n % 10
    return _CARD_TENS[_t] if not _u else f'{_CARD_TENS[_t]}-{_CARD_UNITS[_u]}'


def _int_to_ordinal(n: int) -> str:
    if n < 20:
        return _ORD_UNITS[n]
    _t, _u = (n // 10) * 10, n % 10
    return _ORD_TENS[_t] if not _u else f'{_CARD_TENS[_t]}-{_ORD_UNITS[_u]}'


def _expand_roman_numerals(text_: str) -> tuple:
    """Speak roman numerals as numbers. Returns (text, [(token, spoken), ...])."""
    _changed: list = []

    def _sub(_m):
        _prev, _gap, _tok, _dot = _m.group(1), _m.group(2), _m.group(3), _m.group(4)
        if not _ROMAN_CANON.match(_tok):
            return _m.group(0)
        # A SINGLE letter followed by a period is a middle initial, not a
        # numeral. Measured: "Diego L. González", "Arthur C.D. Pain", "Irene M.
        # Muñoz", "Elena V. Korotkikh", "Washington D.C." all reach here past
        # the capitalised-word gate, and every one is an initial. Real regnal
        # numerals in the corpus sit mid-sentence with no period ("Pope Clement
        # V formally dissolved", "Charles V set out"). Multi-letter numerals
        # (II, IV, XIV) are never initials, so they keep their trailing period.
        if len(_tok) == 1 and _dot:
            return _m.group(0)
        _n = _roman_to_int(_tok)
        if not (1 <= _n <= _ROMAN_MAX):
            return _m.group(0)
        _spoken = _int_to_cardinal(_n) if _prev.lower() in _ROMAN_CARDINAL_BEFORE else f'the {_int_to_ordinal(_n)}'
        _changed.append((_tok, _spoken))
        return f'{_prev}{_gap}{_spoken}{_dot}'

    # prev word must be a spelled-out capitalised word (3+ letters) — that is
    # what separates "Sixtus IV" from the "D. L" and "CC BY" noise.
    _out = re.sub(r'\b([A-Z][a-z]{2,})(\s+)([MDCLXVI]{1,7})\b(\.?)', _sub, text_)
    return _out, _changed


def _tts_clean_text(text_: str) -> str:
    _t = text_.strip()
    # Markdown horizontal rules are layout, and the cloner reads them out as a
    # syllable per dash ("Jian, Jian, Jian"). Blank lines are kept so
    # _tts_split_sentences still sees a paragraph boundary and its 800 ms pause.
    # pipeline_scholarly strips these from the script too — this is the backstop
    # for every other caller that feeds LLM-formatted text straight to a voice.
    _t = re.sub(r'(?m)^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$', '', _t)
    _t = re.sub(r'\*?(?:\(|\[)[^\)\]]{1,80}(?:\)|\])\*?', ' ', _t)
    _t, _roman = _expand_roman_numerals(_t)
    if _roman:
        try:
            _zyg_log.info(
                f'[TTS] Roman numerals spoken as numbers: '
                f'{", ".join(f"{a}→{b}" for a, b in _roman[:8])}'
                f'{" …" if len(_roman) > 8 else ""}'
            )
        except Exception as _exc:
            _zyg_log.debug('roman numeral notice not printed: %s', _exc)
    return re.sub(r' {2,}', ' ', _t).strip()


def _tts_split_sentences(text_: str) -> 'list[tuple[str, int]]':
    """Split narration text into (sentence, pause_ms) pairs.

    pause_ms is silence inserted AFTER the sentence in the final audio:
      - paragraph boundary  → 800 ms
      - question / exclaim  → 520 ms
      - normal period       → 420 ms
      - clause sub-split    → 150 ms (long sentence split at comma/semicolon)

    Paragraph boundaries (double newline) are detected before splitting so
    the inter-paragraph breath is preserved even though _tts_clean_text
    collapses spaces but leaves newlines intact. Pauses are DATA, not model
    behaviour — this is what keeps narration timing deterministic.
    """
    _t = re.sub(r'\n{3,}', '\n\n', text_.strip())
    _paragraphs = re.split(r'\n\n+', _t)
    _non_empty = [p.strip() for p in _paragraphs if p.strip()]
    _result: list = []

    for _pi, _para in enumerate(_non_empty):
        _sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', _para) if s.strip()]
        for _si, _sent in enumerate(_sents):
            _is_para_end = (_si == len(_sents) - 1) and (_pi < len(_non_empty) - 1)
            if _is_para_end:
                _pause = 800
            elif _sent[-1] in '?!' if _sent else False:
                _pause = 520
            else:
                _pause = 420

            # Long sentence: sub-split at clause boundaries (comma / semicolon).
            # Also keeps every segment inside the AR models' reliable span —
            # long single generations are where they repeat or drop words.
            if len(_sent) > _TTS_MAX_CHARS:
                _parts = [p.strip() for p in re.split(r'(?<=[,;])\s+', _sent) if p.strip()]
                if len(_parts) > 1:
                    for _pj, _part in enumerate(_parts):
                        _result.append((_part, _pause if _pj == len(_parts) - 1 else 150))
                    continue

            _result.append((_sent, _pause))

    return _result or [(text_.strip(), 420)]


def _tts_chunk_text(text_: str, max_chars: int = _TTS_MAX_CHARS) -> list:
    """Plain text → chunks of at most max_chars, split on sentence boundaries."""
    _clean = _tts_clean_text(text_)
    if not _clean:
        return []
    if len(_clean) <= max_chars:
        return [_clean]
    _sentences = re.split(r'(?<=[.!?])\s+', _clean)
    _chunks, _cur, _cnt = [], [], 0
    for _s in _sentences:
        if not _s.strip():
            continue
        _slen = len(_s)
        if _cnt + _slen + 1 > max_chars and _cur:
            _chunks.append(' '.join(_cur))
            _cur, _cnt = [], 0
        _cur.append(_s)
        _cnt += _slen + 1
    if _cur:
        _chunks.append(' '.join(_cur))
    _out = []
    for _c in _chunks:
        if len(_c) <= max_chars:
            _out.append(_c)
        else:
            for _i in range(0, len(_c), max_chars):
                _out.append(_c[_i : _i + max_chars])
    return _out


def _tts_trim_edge_silence(audio, np_mod, keep_ms: int = 100, sample_rate: int = 22050):
    """Trim leading/trailing silence from one synthesized sentence.

    Engines pad each sentence with dead air; stacked on the designed 420-800 ms
    inter-sentence pauses this put ~34% of run dd36662e's narration in silence
    (measured 244.7 s of 720 s). Keeps keep_ms of natural breath on each side.
    """
    try:
        # Some engines yield TORCH tensors; numpy ufuncs on them return tensors
        # and np.nonzero(bool_tensor) is 2-D (N,1) — indexing [0] then yields the
        # first ROW, which truncated every sentence to ~0.2s in run 4cd49ffd
        # (101s narration for a 7958-char script). Convert to numpy first.
        if hasattr(audio, 'detach'):
            audio = audio.detach().cpu().numpy()
        audio = np_mod.asarray(audio, dtype=np_mod.float32)
        _amp = np_mod.abs(audio)
        _peak = float(_amp.max()) if _amp.size else 0.0
        if _peak <= 0.0:
            return audio
        # 1% of peak (review: 2% risked clipping soft sentence onsets/sibilants)
        _thr = max(0.002, 0.01 * _peak)
        _nz = np_mod.nonzero(_amp > _thr)[0]
        if _nz.size == 0:
            return audio
        _keep = int(sample_rate * keep_ms / 1000)
        _s = max(0, int(_nz[0]) - _keep)
        _e = min(len(audio), int(_nz[-1]) + _keep)
        return audio[_s:_e]
    except Exception:
        return audio
