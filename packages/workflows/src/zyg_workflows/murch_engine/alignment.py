# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script-first caption alignment and Layer 1c Whisper word timestamps.

Moved verbatim from murch_engine.py lines 870-1409.
"""

from __future__ import annotations
import logging as _zyg_logging
import os
import re
import time
import difflib
import traceback


from zyg_workflows.murch_engine.base import _dbg

_zyg_log = _zyg_logging.getLogger('zyg_workflows.murch_engine')

# ─────────────────────────────────────────────────────────────────────────────
# Script-first caption alignment (TTS timings + narration script text)
# ─────────────────────────────────────────────────────────────────────────────


def script_words_from_narration(narration: str, voice_mode: str = 'narration') -> list[str]:
    """Split narration into words for alignment; strip unspoken stage directions."""
    t = (narration or '').strip()
    if not t:
        return []
    if voice_mode == 'character':
        t = re.sub(
            r'\*?(?:\(|\[)\s*long\s*pause\s*(?:\)|\])\*?',
            ' ',
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r'\*?(?:\(|\[)\s*pause[sd]?\s*(?:\)|\])\*?',
            ' ',
            t,
            flags=re.IGNORECASE,
        )
    t = re.sub(r'\*?(?:\(|\[)[^\)\]]{1,50}(?:\)|\])\*?', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t.split() if t else []


def alignment_coverage(script_words: list[str], aligned: list[tuple[str, float]], matched_idx=None) -> float:
    """Fraction of script tokens that received a REAL (matched, non-interpolated) anchor.

    `matched_idx` (2026-08-25, P-02): the script indices the forced aligner matched
    to an actual Whisper word — `stats['matched_idx']` from _forced_align_words /
    extract_word_timestamps_whisper. When given, coverage is
    len(matched_idx) / len(script_words), the only number that can see a truncated
    or silent read. Without it the legacy SET-intersection runs, which is 1.0 by
    construction whenever `aligned` came out of the forced aligner (it emits every
    script word, interpolated ones included) — the gate then compares the script
    with itself, which is how 16 documentary runs (one of digital silence) all
    reported "100% script/speech agreement". Keep passing matched_idx.
    """
    if not script_words:
        return 0.0
    if matched_idx is not None:
        n = len(script_words)
        try:
            k = len({int(i) for i in matched_idx if 0 <= int(i) < n})
        except (TypeError, ValueError):
            k = len(matched_idx)
        return min(1.0, k / n)

    def _norm_set(words: list[str]) -> set[str]:
        out: set[str] = set()
        for w in words:
            n = re.sub(r'[^a-z0-9\']', '', w.lower())
            if n:
                out.add(n)
        return out

    expected = _norm_set(script_words)
    if not expected:
        return 0.0
    got = _norm_set([w for w, _ in aligned])
    return len(expected & got) / len(expected)


def align_script_to_word_timings(
    word_timings: list[tuple[str, float]],
    narration: str | None = None,
    *,
    script_words: list[str] | None = None,
    voice_mode: str = 'narration',
    min_coverage: float = 0.5,
    debug_log: list | None = None,
) -> tuple[list[tuple[str, float]], float]:
    """
    Map narration script tokens onto TTS/Whisper word onset times.

    Returns (aligned_timings, coverage). On low coverage or failure, returns
    the original word_timings unchanged.
    """
    if not word_timings:
        return [], 0.0
    sw = (
        script_words
        if script_words is not None
        else script_words_from_narration(
            narration or '',
            voice_mode=voice_mode,
        )
    )
    if not sw:
        return list(word_timings), 0.0
    _dl = debug_log if debug_log is not None else []
    # Thread the aligner's own op counts through so `cov` is matched/N — the
    # 2-arg alignment_coverage is a set intersection of script vs aligned
    # words, which is 1.0 by construction and kept min_coverage dead.
    _st: dict = {}
    aligned = _forced_align_words(sw, word_timings, _dl, stats=_st)
    if not aligned:
        return list(word_timings), 0.0
    cov = alignment_coverage(sw, aligned, matched_idx=_st.get('matched_idx'))
    if cov < min_coverage:
        _dbg(_dl, 'script_align', f'Coverage {cov:.1%} below {min_coverage:.0%} — keeping raw TTS tokens', 'WARN')
        return list(word_timings), cov
    _dbg(_dl, 'script_align', f'Script-aligned {len(aligned)} words ({cov:.1%} coverage)', 'INFO')
    return aligned, cov


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1c — Post-TTS Whisper Real Word Timestamps
# ─────────────────────────────────────────────────────────────────────────────


def _forced_align_words(
    script_words: list[str],
    whisper_timings: list[tuple[str, float]],
    debug_log: list | None = None,
    stats: dict | None = None,
) -> list[tuple[str, float]]:
    """
    Forced alignment: map original script words to Whisper timestamps via DP sequence alignment.

    Timing timestamps are accurate (correct *when* words are spoken) but TTS/ASR tokens
    often omit punctuation. This function keeps the script words verbatim while borrowing
    the timing stream's onset times.

    Algorithm:
      - Build NxM DP cost matrix (N=script words, M=whisper words). cost = 0.0 on an
        exact normalised match, 0.2 on a FUZZY match (difflib.SequenceMatcher ratio
        >= 0.7 — "Florence"/"Florance", "Boccaccio"/"Bocaccio"), else SUBST = 1.1.
      - SUBST > 2*GAP (2026-08-25, P-02). It used to be 1.0 == GAP+GAP, so a plain
        substitution TIED with delete+insert and the `best == m` tie-break turned every
        Whisper hallucination into a "match": on a file of digital silence the aligner
        reported "27 matched" against 1,740 hallucinated words and pinned unspoken
        script words to the hallucinated times. 'M' now wins only on a REAL (exact or
        fuzzy) match — a substitution is always the dearer path, and the tie-break is
        gated on the match being real as well, so a fake 'M' cannot be emitted.
      - Backtrace to find the optimal alignment path.
      - MATCH: use script word + whisper timestamp.
      - INSERT (Whisper has extra word not in script): skip whisper word (drop timestamp).
      - DELETE (script word absent from Whisper): interpolate timestamp linearly between
        surrounding matched/inserted anchors.

    `stats` (optional dict) receives the op counts the return value cannot carry:
    n_script, n_whisper_raw, n_match, n_fuzzy, n_delete, n_insert,
    match_ratio (= n_match / max(n_script, 1)), matched_idx (sorted script indices
    that got a REAL Whisper anchor) and asr_empty (raw Whisper produced 0 words).
    The return shape is unchanged for existing callers.

    Returns list of (script_word, start_seconds).
    """
    if debug_log is None:
        debug_log = []
    _st = stats if isinstance(stats, dict) else {}

    def _norm(w: str) -> str:
        return re.sub(r"[^a-z0-9']", '', w.lower())

    sw = script_words
    ww = [w for w, _ in whisper_timings]
    wt = [t for _, t in whisper_timings]

    N, M = len(sw), len(ww)
    _st.update(
        {
            'n_script': N,
            'n_whisper_raw': M,
            'n_match': 0,
            'n_fuzzy': 0,
            'n_delete': N,
            'n_insert': M,
            'match_ratio': 0.0,
            'matched_idx': [],
            'asr_empty': (M == 0),
        }
    )
    if N == 0:
        return []
    if M == 0:
        # No Whisper output — cannot align; return empty (caller falls back to TTS timing)
        _dbg(debug_log, 'forced_align', 'Whisper produced 0 words — alignment skipped', 'WARN')
        return []

    # ── DP alignment (Needleman–Wunsch style, minimise cost) ──────────────
    GAP = 0.5  # penalty for inserting/deleting a word
    MATCH = 0.0
    FUZZY = 0.2  # near-miss ASR spelling of the same word
    SUBST = 1.1  # MUST stay > 2*GAP — see docstring (P-02)
    FUZZY_MIN = 0.7

    # Normalise ONCE and intern every distinct token to an int. The old loop ran
    # two regex substitutions per DP cell (6 M regex calls on a 1,740-word
    # script); that budget now pays for the fuzzy tier instead. The fuzzy
    # verdict is cached per (script token, whisper token) pair in a V*V byte
    # table — a few hundred KB — so SequenceMatcher runs once per distinct pair,
    # not once per cell.
    _vocab: dict[str, int] = {}
    sw_id = [_vocab.setdefault(_norm(w), len(_vocab)) for w in sw]
    ww_id = [_vocab.setdefault(_norm(w), len(_vocab)) for w in ww]
    _vwords = list(_vocab.keys())
    _empty_id = _vocab.get('', -1)  # punctuation-only tokens never anchor
    V = len(_vwords)
    _fzc = bytearray(V * V)  # 0 = unknown, 1 = no, 2 = fuzzy match

    def _fuzzy(ia: int, ib: int) -> bool:
        k = ia * V + ib
        c = _fzc[k]
        if c:
            return c == 2
        a, b = _vwords[ia], _vwords[ib]
        la, lb = len(a), len(b)
        # Function-word collisions (he/the 0.80, an/and 0.80, of/off 0.80,
        # the/then 0.857) pass FUZZY_MIN and would pin a script word to a
        # neighbouring mis-heard token: no fuzzy match under 4 chars, and a
        # stricter 0.8 floor at 4 chars.
        _min_ratio = FUZZY_MIN if min(la, lb) >= 5 else 0.8
        if not la or not lb or min(la, lb) < 4 or 2.0 * min(la, lb) / (la + lb) < _min_ratio:
            r = False  # the length bound == SequenceMatcher.real_quick_ratio()
        else:
            sm = difflib.SequenceMatcher(None, a, b)
            r = sm.quick_ratio() >= _min_ratio and sm.ratio() >= _min_ratio
        _fzc[k] = 2 if r else 1
        return r

    # dp[i][j] = min cost aligning sw[:i] to ww[:j]
    INF = float('inf')
    dp = [[INF] * (M + 1) for _ in range(N + 1)]
    back = [[None] * (M + 1) for _ in range(N + 1)]  # 'M'atch,'I'nsert,'D'elete

    dp[0][0] = 0.0
    for i in range(1, N + 1):
        dp[i][0] = i * GAP  # script word deleted (no whisper match)
        back[i][0] = 'D'
    for j in range(1, M + 1):
        dp[0][j] = j * GAP  # whisper word inserted (extra word)
        back[0][j] = 'I'

    for i in range(1, N + 1):
        ia = sw_id[i - 1]
        dpi, dpp, bki = dp[i], dp[i - 1], back[i]
        for j in range(1, M + 1):
            ib = ww_id[j - 1]
            if ia == ib and ia != _empty_id:
                cost_m, real = MATCH, True
            elif _fuzzy(ia, ib):
                cost_m, real = FUZZY, True
            else:
                cost_m, real = SUBST, False
            m = dpp[j - 1] + cost_m  # match / substitute
            d = dpp[j] + GAP  # delete script word
            ins = dpi[j - 1] + GAP  # insert whisper word
            # 'M' only on a real match AND only when it is the cheapest path
            # (ties still favour M, as before). A substitution can never be
            # cheapest while SUBST > 2*GAP; the `real` gate makes that explicit
            # so a future constant change cannot silently reopen P-02.
            if real and m <= d and m <= ins:
                dpi[j] = m
                bki[j] = 'M'
            elif d <= ins:
                dpi[j] = d
                bki[j] = 'D'
            else:
                dpi[j] = ins
                bki[j] = 'I'

    # ── Backtrace ─────────────────────────────────────────────────────────
    ops: list[tuple[str, int, int]] = []  # (op, script_idx, whisper_idx)
    i, j = N, M
    while i > 0 or j > 0:
        op = back[i][j]
        if op == 'M':
            ops.append(('M', i - 1, j - 1))
            i -= 1
            j -= 1
        elif op == 'D':
            ops.append(('D', i - 1, -1))
            i -= 1
        else:  # 'I'
            ops.append(('I', -1, j - 1))
            j -= 1
    ops.reverse()

    # ── Build result: (script_word, timestamp) ────────────────────────────
    # First pass: assign timestamps for M and I ops; mark D ops for interpolation
    result: list[tuple[str, float] | None] = []
    # Script index behind each result slot. result[] gets exactly one entry per
    # M or D op ('I' appends nothing), so this stays index-aligned with result
    # and is the ONLY reliable way back to the word a slot stands for.
    res_si: list[int] = []
    for op, si, wi in ops:
        if op == 'M':
            result.append((sw[si], wt[wi]))
            res_si.append(si)
        elif op == 'D':
            result.append(None)  # placeholder for interpolation
            res_si.append(si)
        # op == 'I': Whisper hallucination — drop entirely (no append)

    # Second pass: fill interpolated timestamps for deleted script words
    n_res = len(result)
    for k in range(n_res):
        if result[k] is not None:
            continue
        # Find previous and next anchor timestamps
        prev_t = 0.0
        for p in range(k - 1, -1, -1):
            if result[p] is not None:
                prev_t = result[p][1]
                break
        next_t = None
        for q in range(k + 1, n_res):
            if result[q] is not None:
                next_t = result[q][1]
                break
        # Count consecutive Nones in this run for linear spacing
        run_start = k
        while run_start > 0 and result[run_start - 1] is None:
            run_start -= 1
        run_end = k
        while run_end < n_res - 1 and result[run_end + 1] is None:
            run_end += 1
        run_len = run_end - run_start + 1
        run_pos = k - run_start + 1
        if next_t is None:
            interp_t = prev_t + run_pos * 0.15  # 150ms spacing after last anchor
        else:
            step = (next_t - prev_t) / (run_len + 1)
            interp_t = prev_t + step * run_pos
        # The word for this slot comes straight from res_si. The previous code
        # counted "how many Nones precede k" to index into the D-ops list — but
        # this loop fills slots in order, so every earlier None had already been
        # replaced and the count was ALWAYS 0. Every unmatched word therefore
        # came out as the FIRST unmatched word. On the Sikh Empire run that was
        # an em-dash, so the script's "Sarkar Khalsaji — … — the Khalsa" reached
        # the slot-narration builder as "Sarkar — — … — —": the proper nouns and
        # dates, which are exactly the words the image prompts hang on, were the
        # ones being erased.
        result[k] = (sw[res_si[k]], interp_t)

    aligned = [(w, t) for w, t in result]

    n_match = sum(1 for op, _, _ in ops if op == 'M')
    n_delete = sum(1 for op, _, _ in ops if op == 'D')
    n_insert = sum(1 for op, _, _ in ops if op == 'I')
    n_fuzzy = sum(1 for op, si, wi in ops if op == 'M' and sw_id[si] != ww_id[wi])
    matched_idx = sorted(si for op, si, _ in ops if op == 'M')
    _st.update(
        {
            'n_match': n_match,
            'n_fuzzy': n_fuzzy,
            'n_delete': n_delete,
            'n_insert': n_insert,
            'match_ratio': n_match / max(N, 1),
            'matched_idx': matched_idx,
            'asr_empty': False,
        }
    )
    _dbg(
        debug_log,
        'forced_align',
        f'Alignment: {n_match} matched ({n_fuzzy} fuzzy), {n_delete} interpolated, '
        f'{n_insert} Whisper-only dropped → {len(aligned)} subtitle words '
        f'(script had {N}, Whisper {M}; match ratio {n_match / max(N, 1):.1%})',
        'INFO',
        {'first_5': aligned[:5], 'last_5': aligned[-5:]},
    )

    return aligned


def extract_word_timestamps_whisper(
    audio_path: str,
    expected_text: str | None = None,
    debug_log: list | None = None,
    device: str | None = None,
    stats: dict | None = None,
    *,
    narration: str | None = None,
) -> list[tuple[str, float]]:
    """
    Layer 1c: Run Whisper tiny on TTS audio to extract real word-level timestamps.
    Returns list of (word, start_seconds) tuples using the ORIGINAL script words with
    Whisper-derived timestamps (forced alignment via DP sequence alignment).
    Falls back to uniform spacing if Whisper fails.

    `stats` (2026-08-25, P-02): pass a dict to receive n_script, n_whisper_raw (raw
    Whisper word count BEFORE alignment), n_match, n_fuzzy, n_delete, n_insert,
    match_ratio (= n_match / max(n_script, 1)), matched_idx, asr_empty (raw Whisper
    produced 0 words — a silent or unintelligible file) and asr_error (str when
    Whisper itself failed, else None). These are the numbers that tell a truncated
    or silent narration from a good one; the returned list cannot, because the
    aligner emits every script word. Pass `stats` BY KEYWORD — the positional slot
    after debug_log is `device` (a dict landing there is tolerated and taken as
    stats). `narration` is a keyword alias for `expected_text`.
    """
    if debug_log is None:
        debug_log = []
    if narration is not None and expected_text is None:
        expected_text = narration
    if isinstance(device, dict) and stats is None:
        stats, device = device, None
    _st = stats if isinstance(stats, dict) else {}
    _n_script = len(expected_text.split()) if expected_text else 0
    _st.update(
        {
            'n_script': _n_script,
            'n_whisper_raw': 0,
            'n_match': 0,
            'n_fuzzy': 0,
            'n_delete': _n_script,
            'n_insert': 0,
            'match_ratio': 0.0,
            'matched_idx': [],
            'asr_empty': False,
            'asr_error': None,
        }
    )

    t0 = time.monotonic()
    _dbg(debug_log, 'whisper_timestamps', f'Running Whisper tiny on: {audio_path}', 'INFO')

    try:
        import whisper as _whisper
        import torch

        if not os.path.exists(audio_path):
            _dbg(debug_log, 'whisper_timestamps', f'Audio file not found: {audio_path}', 'ERROR')
            _st['asr_error'] = 'audio file not found'
            return []

        # 2026-07-24: headroom-checked device pick — no local TTS engine emits
        # word timings, so this Whisper pass is the routine word-timing source
        # and often runs while ComfyUI holds the GPU (run 6278904c had 28 MiB
        # free at TTS time). CUDA only with real headroom.
        if not device:
            device = 'cpu'
            try:
                if torch.cuda.is_available():
                    _free_w, _ = torch.cuda.mem_get_info()
                    _min_w = int(os.environ.get('ZYG_WHISPER_MIN_VRAM_MB', '1536')) * 1024 * 1024
                    if _free_w >= _min_w:
                        device = 'cuda'
                    else:
                        _dbg(debug_log, 'whisper_timestamps', f'{_free_w >> 20} MiB VRAM free — Whisper on CPU', 'INFO')
            except Exception as _exc:
                _zyg_log.debug('VRAM probe for Whisper failed, staying on %s: %s', device, _exc)
        try:
            model = _whisper.load_model('tiny', device=device)
        except Exception as _wl_e:
            if device == 'cuda':
                _dbg(debug_log, 'whisper_timestamps', f'cuda load failed ({_wl_e}) — retrying on CPU', 'WARNING')
                device = 'cpu'
                model = _whisper.load_model('tiny', device=device)
            else:
                raise
        result = model.transcribe(
            audio_path,
            word_timestamps=True,
            language='en',
            fp16=(device == 'cuda'),
            verbose=False,
        )

        whisper_timings: list[tuple[str, float]] = []
        for segment in result.get('segments', []):
            for word_info in segment.get('words', []):
                w = word_info.get('word', '').strip()
                t = float(word_info.get('start', 0))
                if w:
                    whisper_timings.append((w, t))

        elapsed = time.monotonic() - t0
        _dbg(
            debug_log,
            'whisper_timestamps',
            f'Whisper extracted {len(whisper_timings)} raw word timestamps in {elapsed:.1f}s (device={device})',
            'INFO',
            {'first_5': whisper_timings[:5], 'last_5': whisper_timings[-5:]},
        )
        _st['n_whisper_raw'] = len(whisper_timings)
        _st['asr_empty'] = not whisper_timings
        if not whisper_timings:
            _dbg(
                debug_log,
                'whisper_timestamps',
                'Whisper produced 0 words — the audio is silent or unintelligible '
                '(asr_empty); no subtitle timings and nothing for the read-back gate '
                'to agree with',
                'WARN',
            )

        # Free VRAM after use — model stays in RAM but GPU freed
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # ── Forced alignment: replace Whisper words with original script words ──
        script_words: list[str] = []
        if expected_text and whisper_timings:
            script_words = expected_text.split()
            word_timings = _forced_align_words(script_words, whisper_timings, debug_log, stats=_st)
            if not word_timings:
                # Alignment produced nothing (edge case) — fall back to raw Whisper
                word_timings = whisper_timings
        else:
            word_timings = whisper_timings

        # Quality check (P-02): coverage = script words anchored to a REAL Whisper
        # word / N, from the aligner's matched indices. The old check intersected
        # two word SETS: it read 76% on digital silence and 77% on a correct read
        # (a punctuation artefact) and could never see truncation, because the
        # aligner emits every script word, interpolated ones included.
        if expected_text and whisper_timings:
            coverage = alignment_coverage(script_words, word_timings, matched_idx=_st.get('matched_idx') or [])
            _dbg(
                debug_log,
                'whisper_timestamps',
                f'Post-alignment script coverage: {coverage:.1%} '
                f'({_st.get("n_match", 0)}/{len(script_words)} script words anchored to a '
                f'real Whisper word, {_st.get("n_fuzzy", 0)} fuzzy; '
                f'{_st.get("n_insert", 0)} Whisper-only dropped)',
                'INFO',
            )
            if coverage < 0.4:
                _dbg(
                    debug_log,
                    'whisper_timestamps',
                    'Low coverage — TTS may have truncated or Whisper struggled',
                    'WARN',
                )

        return word_timings

    except Exception as e:
        _dbg(debug_log, 'whisper_timestamps', f'Whisper failed: {e}\n{traceback.format_exc()}', 'ERROR')
        _st['asr_error'] = str(e) or type(e).__name__
        return []
