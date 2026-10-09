# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""remixai_divergence.py — proof that a regenerated script is not the source's (2026-08-29).

pipeline_remixai guarantees STRUCTURALLY that source wording cannot reach the
script writer (`regenerate_script()` takes an abstract brief and has no parameter
that could carry a sentence). That guarantee is strong but invisible. This module
makes it MEASURED: every episode carries a number, not a promise.

THREE METRICS, because each catches what the others miss
--------------------------------------------------------
1. `containment_5gram` — fraction of our 5-word runs that also occur in the
   source. Catches literal reuse exactly. Deterministic, no model, and the one
   that cannot be argued with.
2. `longest_shared_run` — the single longest contiguous shared run of words.
   Aggregate containment can look clean while one lifted twelve-word clause
   sits in the middle of the script; this finds it.
3. `max_sentence_cosine` — per-sentence nearest-neighbour similarity. This is
   the paraphrase detector, and it is deliberately PER-SENTENCE:

   Document-level cosine is meaningless for this job. Two scripts genuinely
   about the same subject score 0.6-0.8 against each other no matter how
   differently they are written — that similarity IS the topic, and gating on it
   would fail every honest run. What marks a paraphrase is one of OUR sentences
   sitting very close to one of THEIRS, so the score is the maximum over
   per-sentence nearest neighbours, plus the fraction of our sentences that have
   such a neighbour.

VERDICTS ARE THREE-VALUED ON PURPOSE
------------------------------------
'pass' / 'fail' / 'degraded'. A gate whose "clean" and "broken" answers are the
same value cannot monitor itself, so an unavailable embedding model NEVER returns
a quiet pass — it returns 'degraded', which is visible in the log, the manifest
and the upload sheet, and which the operator can configure to block.

THRESHOLD CALIBRATION — RE-DERIVED FROM A REAL JOB (2026-08-29)
--------------------------------------------------------------
The cosine threshold has now been wrong twice, both times because it was set
against material that was not representative. Recording both, because the shape
of the mistake matters more than the number:

  0.85  guessed from where MiniLM "should" put paraphrase. Too high.
  0.70  midpoint of a sweep over CONSTRUCTED pairs on BROAD topics
        (independent prose topped out at 0.52 there). Far too low.

The first real job — an AI-filmmaking tutorial, a NARROW technical subject —
failed the gate three times running with 5-gram containment of 0.0000 and a
longest shared run of 4 words. There was no reuse. Two scripts about keeping a
character consistent across shots in one named tool must both say so, and in a
15-word window that shared domain vocabulary IS most of the window. Measured on
that job's real transcript:

    independent scripts vs their own source   max cosine 0.809 - 0.898
    script + a 30-word verbatim lift                     0.976
    the entire source pasted back                        1.000

so the honest cosine threshold is 0.95, and it can only ever be a NEAR-VERBATIM
BACKSTOP. It is not a paraphrase detector on a narrow topic and must not be sold
as one: a constructed light paraphrase measured 0.945, which sits inside the
range real independent writing reaches.

A null-model correction was tried and REJECTED on measurement. The idea was to
gate on how far the top match stands above the pair's own topical baseline
(max - p90, or a z-score), so topic-driven similarity would cancel out. It
separates in the wrong direction: a total lift scores the LOWEST margin (0.029)
because when every window matches, the top one is not an outlier at all, while a
legitimate script scored 0.189. The gap came out NEGATIVE (-0.161). Do not
revive this without new evidence.

WHAT ACTUALLY CARRIES THE GATE
------------------------------
The LEXICAL checks, which are topic-independent and were clean on every real
script (containment <= 0.004, longest run 3-5 words) while catching a planted
12-word lift (containment 0.0282, run 12w). Containment and run length are the
load-bearing metrics. Cosine is a backstop for the near-verbatim case, and
frac_sentences_near does not block at all.

WHAT THIS GATE DOES NOT CATCH (measured 2026-08-29, do not oversell it)
----------------------------------------------------------------------
It catches verbatim reuse, near-verbatim, and LIGHT paraphrase (word-level
swaps: 'everyone'→'everybody', 'short'→'brief'), which measured 0.98 cosine.
It does NOT catch HEAVY paraphrase — the same idea and sentence shape with every
content word replaced. A constructed example ('treating the generator like a
stock library instead of a camera' → 'handling the model as a shot archive
rather than a lens') measured 0.47, sitting exactly where INDEPENDENTLY WRITTEN
prose on the same topic sits (0.46). That is not a threshold that can be tuned
down: at 0.47 the two populations overlap completely, so lowering the bar buys
false positives and no real detection.

This is a limit of the measurement, not a hole in the pipeline. The PRIMARY
guarantee is structural and lives in remixai_analyze: the writer never receives
the source's words, so it has nothing to paraphrase heavily FROM. This gate is
defence in depth — it verifies that guarantee held rather than being the thing
that enforces it. Read a 'pass' as 'no measurable reuse', never as 'proven
original'.

The embedding model runs on CPU by design: it is a 6-layer MiniLM over short
chunks, so CPU costs a second or two and keeps the gate entirely out of the
way of renders — no GPU gate, no contention, no reason to ever skip it.
"""

from __future__ import annotations

import os
import re
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_MODEL_NAME = os.environ.get('ZYG_REMIXAI_EMBED_MODEL', 'all-MiniLM-L6-v2')
_MODEL_CACHE = {}

# ── thresholds (env-overridable; see the calibration note above) ─────────────
DEFAULTS = {
    'containment_5gram': 0.020,  # >2% of our 5-grams seen in the source
    'longest_shared_run': 8,  # words; a shared run this long is a lift
    'max_sentence_cosine': 0.95,  # near-verbatim backstop (see calibration)
    'frac_sentences_near': 0.15,  # REPORTED ONLY — never blocks (see calibration)
}


# Hard cap on how much of an offending phrase may be quoted back as a ban.
# See the note in retry_instruction(): the ban must never become a route by
# which source-matching text reaches the writer's prompt.
_BAN_PHRASE_WORDS = 10


def _thresholds(overrides: dict = None) -> dict:
    t = dict(DEFAULTS)
    for k in t:
        env = os.environ.get(f'ZYG_REMIXAI_MAX_{k.upper()}')
        if env:
            try:
                t[k] = type(t[k])(float(env))
            except ValueError as _exc:
                _zyg_log.warning('env override for %s is not a number, keeping the default: %s', k, _exc)
    t.update({k: v for k, v in (overrides or {}).items() if k in t})
    return t


# ── text prep ───────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-z0-9']+")
_SENT_RE = re.compile(r'(?<=[.!?])\s+')


def _words(text: str) -> list:
    return _WORD_RE.findall((text or '').lower())


# MiniLM truncates at 256 word-pieces. Any chunk handed to it must sit well
# inside that, or the tail of the chunk is silently not embedded at all.
# 15/5 chosen by MEASUREMENT, not taste (2026-08-29). A window mixes the text
# that matches with its neighbours, which dilutes the peak cosine — at 28/14 a
# verbatim lift scored only 0.84-0.90 and sat almost on top of the paraphrase
# band. Narrowing to 15/5 lifted verbatim to 0.95 and widened the gap between
# independent prose and reuse from +0.27 to +0.36. Smaller still costs compute
# for no further separation.
_CHUNK_WORDS = int(os.environ.get('ZYG_REMIXAI_CHUNK_WORDS', '15') or 15)
_CHUNK_STRIDE = max(1, int(os.environ.get('ZYG_REMIXAI_CHUNK_STRIDE', '0') or 0) or max(1, _CHUNK_WORDS // 3))


def _sentences(text: str) -> list:
    out = []
    for chunk in _SENT_RE.split((text or '').strip()):
        c = re.sub(r'\s+', ' ', chunk).strip()
        if len(c.split()) >= 4:  # fragments are noise in a cosine test
            out.append(c)
    return out


def _windows(text: str, size: int = None, stride: int = None) -> list:
    """Overlapping fixed-width word windows. Punctuation-independent."""
    size = size or _CHUNK_WORDS
    stride = stride or _CHUNK_STRIDE
    w = re.sub(r'\s+', ' ', (text or '')).strip().split()
    if not w:
        return []
    if len(w) <= size:
        return [' '.join(w)]
    return [' '.join(w[i : i + size]) for i in range(0, len(w) - size + stride, stride) if w[i : i + size]]


def chunks(text: str, *, prefer_sentences: bool) -> tuple:
    """Split text for embedding. Returns (chunks, how).

    THE BUG THIS EXISTS TO FIX (measured 2026-08-29): YouTube auto-captions carry
    NO PUNCTUATION — pipeline_remix's own transcript path logs 'captions-only'
    for exactly this reason. Splitting such a transcript on [.!?] yields ONE
    chunk of the entire video, MiniLM truncates it at 256 word-pieces, and every
    word past roughly the first 200 is never embedded. The paraphrase check then
    silently scores against a fragment of the source: a verbatim lift late in a
    caption transcript measured 0.15 cosine, and a paraphrase of one measured
    0.21 and PASSED.

    So the SOURCE side is always windowed — never trusted to be punctuated. Our
    own side prefers sentences (they make the report readable: 'this line of
    yours is too close to that line of theirs') but falls back to windows if the
    writer returned unpunctuated prose."""
    if prefer_sentences:
        sents = _sentences(text)
        # demand real sentence structure, not one run-on blob
        if len(sents) >= 2 and max((len(x.split()) for x in sents), default=0) <= 60:
            return sents, 'sentences'
    return _windows(text), 'windows'


# ── 1. n-gram containment ───────────────────────────────────────────────────


def shingles(words: list, n: int = 5) -> set:
    return {' '.join(words[i : i + n]) for i in range(len(words) - n + 1)} if len(words) >= n else set()


def containment(ours: list, theirs: list, n: int = 5) -> tuple:
    """Fraction of OUR n-grams that also appear in THEIRS.

    Containment, not Jaccard: the source transcript is typically far longer than
    our script, and Jaccard would be dominated by their unmatched mass and read
    near-zero even for a wholesale lift."""
    a, b = shingles(ours, n), shingles(theirs, n)
    if not a:
        return 0.0, []
    shared = a & b
    return len(shared) / len(a), sorted(shared)[:12]


# ── 2. longest shared contiguous run ────────────────────────────────────────


def longest_shared_run(ours: list, theirs: list) -> tuple:
    """Longest run of consecutive words appearing in both, via classic DP over a
    rolling row (the full table would be len(ours)*len(theirs) ints — a 20k-word
    transcript against a 400-word script is 8M cells for a single number)."""
    if not ours or not theirs:
        return 0, ''
    prev = [0] * (len(theirs) + 1)
    best, best_end = 0, 0
    for i in range(1, len(ours) + 1):
        cur = [0] * (len(theirs) + 1)
        oi = ours[i - 1]
        for j in range(1, len(theirs) + 1):
            if oi == theirs[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best, best_end = cur[j], i
        prev = cur
    return best, ' '.join(ours[best_end - best : best_end]) if best else ''


# ── 3. per-sentence semantic nearest neighbour ──────────────────────────────


def _load_model():
    """Lazy CPU load, cached for the process. Returns None when unavailable —
    the caller turns that into a 'degraded' verdict, never a quiet pass."""
    if _MODEL_CACHE.get('m') is not None:
        return _MODEL_CACHE['m']
    # A previous FAILURE is not cached: a transient load error (cold HF cache, a
    # momentary OOM) would otherwise mark the gate degraded for the rest of the
    # process, silently disabling the paraphrase check on every later job.
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE['m'] = SentenceTransformer(_MODEL_NAME, device='cpu')
    except Exception:
        _MODEL_CACHE['m'] = None
    return _MODEL_CACHE['m']


def sentence_similarity(ours_text: str, theirs_text: str, near_threshold: float = None) -> dict:
    """Per-sentence nearest-neighbour cosine of ours against theirs.

    Returns {'available': False} when the model cannot load, so the caller can
    report 'degraded' rather than inventing a passing number."""
    model = _load_model()
    if model is None:
        return {'available': False}
    so, how_o = chunks(ours_text, prefer_sentences=True)
    st, how_s = chunks(theirs_text, prefer_sentences=False)
    if not so or not st:
        return {
            'available': True,
            'max': 0.0,
            'frac_near': 0.0,
            'percentiles': {},
            'worst': '',
            'worst_match': '',
            'n_ours': len(so),
            'n_theirs': len(st),
            'chunking': f'{how_o}/{how_s}',
        }
    try:
        import numpy as np

        eo = model.encode(so, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        et = model.encode(st, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        sim = np.asarray(eo) @ np.asarray(et).T  # normalised → cosine
        nearest = sim.max(axis=1)  # best match per OUR sentence
        idx = int(nearest.argmax())
        thr = near_threshold if near_threshold is not None else _thresholds()['max_sentence_cosine']
        pct = {f'p{p}': round(float(np.percentile(nearest, p)), 4) for p in (50, 75, 90, 100)}
        return {
            'available': True,
            'max': round(float(nearest.max()), 4),
            'frac_near': round(float((nearest >= thr).mean()), 4),
            'percentiles': pct,
            'worst': so[idx][:220],
            'worst_match': st[int(sim[idx].argmax())][:220],
            'n_ours': len(so),
            'n_theirs': len(st),
            'chunking': f'{how_o}/{how_s}',
        }
    except Exception:
        return {'available': False}


# ── the gate ────────────────────────────────────────────────────────────────


def check(script_text: str, source_text: str, *, thresholds: dict = None, log=None) -> dict:
    """Score a regenerated script against the source transcript.

    Returns a report whose 'verdict' is 'pass', 'fail' or 'degraded'. 'failed'
    names every metric that breached, so a regeneration attempt can be told
    precisely what went wrong instead of being asked to try harder in general."""
    t = _thresholds(thresholds)
    ow, tw = _words(script_text), _words(source_text)

    cont, shared_grams = containment(ow, tw, 5)
    run_len, run_text = longest_shared_run(ow, tw)
    sem = sentence_similarity(script_text, source_text, near_threshold=t['max_sentence_cosine'])

    failed = []
    if cont > t['containment_5gram']:
        failed.append('containment_5gram')
    if run_len > t['longest_shared_run']:
        failed.append('longest_shared_run')
    if sem.get('available') and sem['max'] > t['max_sentence_cosine']:
        failed.append('max_sentence_cosine')
    # frac_sentences_near is COMPUTED AND REPORTED BUT NEVER BLOCKS. On the first
    # real job it fired on all three drafts at 0.105-0.167 with ZERO literal
    # overlap: on a narrow technical topic most windows are dominated by shared
    # domain vocabulary, so this measures how specialised the subject is, not how
    # much was reused. It stays in the report because the distribution is worth
    # watching; it is not evidence of anything on its own.

    if failed:
        verdict = 'fail'
    elif not sem.get('available'):
        verdict = 'degraded'
    else:
        verdict = 'pass'

    report = {
        'verdict': verdict,
        'failed': failed,
        'thresholds': t,
        'semantic': 'ok' if sem.get('available') else 'unavailable',
        'metrics': {
            'containment_5gram': round(cont, 5),
            'longest_shared_run': run_len,
            'max_sentence_cosine': sem.get('max'),
            'frac_sentences_near': sem.get('frac_near'),
            'percentiles': sem.get('percentiles') or {},
            'our_words': len(ow),
            'source_words': len(tw),
            'our_chunks': sem.get('n_ours'),
            'source_chunks': sem.get('n_theirs'),
            'chunking': sem.get('chunking'),
        },
        'evidence': {
            'longest_shared_run_text': run_text,
            'shared_5grams': shared_grams,
            'closest_pair': ([sem.get('worst'), sem.get('worst_match')] if sem.get('available') else []),
        },
    }
    if log:
        log(_summary(report))
    return report


def _summary(r: dict) -> str:
    m = r['metrics']
    cos = m.get('max_sentence_cosine')
    return (
        f'divergence {r["verdict"].upper()}: '
        f'5-gram containment {m["containment_5gram"]:.4f} '
        f'(max {r["thresholds"]["containment_5gram"]}), '
        f'longest shared run {m["longest_shared_run"]}w '
        f'(max {r["thresholds"]["longest_shared_run"]}), '
        f'sentence cosine {"n/a" if cos is None else f"{cos:.3f}"} '
        f'(max {r["thresholds"]["max_sentence_cosine"]})'
        + (f' — BREACHED: {", ".join(r["failed"])}' if r['failed'] else '')
        + ('  [semantic check UNAVAILABLE]' if r['semantic'] != 'ok' else '')
    )


def retry_instruction(report: dict) -> str:
    """Turn a failure into a specific instruction for the next attempt. Naming the
    breached metric beats 'be more different' — the writer is told what to avoid,
    and with the actual offending phrase where there is one."""
    if not report.get('failed'):
        return ''
    bits = []
    ev = report.get('evidence') or {}
    if 'containment_5gram' in report['failed'] or 'longest_shared_run' in report['failed']:
        run = (ev.get('longest_shared_run_text') or '').strip()
        bits.append(
            'Your previous draft reused wording from the material this brief '
            'was abstracted from. Write every line from scratch in your own '
            'phrasing.'
        )
        if run:
            # A ban is a CONSTRAINT, not a channel. On a wholesale lift the shared
            # run can be the entire draft (measured: 113 words on a verbatim copy),
            # and quoting that back would push the very text the writer must not
            # see INTO its next prompt. Capped hard: enough to name the phrase,
            # never enough to carry content.
            words = run.split()
            shown = ' '.join(words[:_BAN_PHRASE_WORDS])
            if len(words) > _BAN_PHRASE_WORDS:
                shown += '…'
            bits.append(f'In particular, do not open with or reuse "{shown}".')
    if 'max_sentence_cosine' in report['failed'] or 'frac_sentences_near' in report['failed']:
        bits.append(
            'Several lines were close restatements of existing sentences. '
            'Change the sentence structure and the vocabulary, not just a '
            'few words — make each point in a different order and from a '
            'different starting image than the obvious one.'
        )
    return ' '.join(bits)
