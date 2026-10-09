# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.remixai_analyze.music — verbatim from remixai_analyze.py lines 859-1021.

section 4 — the soundtrack: music-bed extraction, CLAP ranking and the
genre/mood mapping that becomes a music request
"""

from __future__ import annotations

from zyg_workflows.bin import exe
import os
from zyg_workflows.remixai_analyze import llm as _zyg_llm

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file remixai_analyze.py.
_run = _zyg_llm._run


# ── 4. soundtrack ───────────────────────────────────────────────────────────

_GENRES = [
    'cinematic orchestral',
    'lo-fi hip hop',
    'ambient electronic',
    'synthwave',
    'corporate uplifting',
    'epic trailer',
    'acoustic folk',
    'tense underscore',
    'upbeat pop',
    'dark techno',
]
_MOODS = ['happy', 'sad', 'tense', 'triumphant', 'calm', 'eerie', 'energetic', 'melancholic']


def extract_music_bed(video_path: str, out_wav: str, log=None) -> str | None:
    """Pull the audio bed for CLAP. Speech is not removed — a music/speech
    separator is a whole model, and CLAP reads the dominant bed well enough for
    a genre label through narration."""
    rc, _o, err = _run(
        [exe('ffmpeg'), '-y', '-i', video_path, '-vn', '-ac', '1', '-ar', '48000', '-t', '120', out_wav], timeout=300
    )
    if rc != 0 or not os.path.isfile(out_wav):
        if log:
            log(f'audio extract failed: {err[:160]}')
        return None
    return out_wav


def _clap_rank(wav_path, labels, log=None) -> list:
    """Rank `labels` against one audio file with a SINGLE CLAP call.

    TWO BUGS LIVED HERE (both found on the first real job, 2026-08-29, which
    reported margins of exactly 0.000 for every label):

    1. `qc_clap` returns 'positive_prob' — there is no 'score' key. Reading
       .get('score') yielded None for every label, so every genre tied at 0.0 and
       the reading was reported AMBIGUOUS every time. A metric that returns the
       same constant for all inputs looks exactly like a genuine tie, which is
       why this survived the smoke tests.
    2. qc_clap softmaxes over the WHOLE prompt list. Calling it once per label
       with a single positive and no negatives makes that softmax a one-element
       distribution — identically 1.0 — so even with the right key the per-label
       calls could not rank anything.

    Both are fixed by the same change: pass every label in ONE call and read the
    per-prompt breakdown in `scores`, which is a real softmax across the labels.
    Note that breakdown is for a single window (qc_clap keeps the worst window's
    detail), so this is a 30 s read of a bed rather than a whole-file average —
    acceptable for a genre label on a track that does not change genre, and the
    caller still treats a thin margin as AMBIGUOUS."""
    try:
        from zyg_workflows import audio_qc
    except Exception:
        return []
    prompts = [f'{lab} music' for lab in labels]
    try:
        res = audio_qc.qc_clap(wav_path, prompts, [], threshold=0.0, log_fn=(lambda m: log(m)) if log else None)
    except Exception as e:
        if log:
            log(f'CLAP call failed: {e}')
        return []
    scores = (res or {}).get('scores') or {}
    if not scores:
        if log:
            log(f'CLAP unavailable: {(res or {}).get("reason", "no scores returned")}')
        return []
    ranked = [(lab, float(scores.get(f'{lab} music', 0.0))) for lab in labels]
    ranked.sort(key=lambda kv: -kv[1])
    return ranked


def analyze_music(wav_path: str, log=None) -> dict:
    """CLAP text-audio similarity over a genre list and a mood list. Returns the
    best of each with its margin — a thin margin means the bed is ambiguous, and
    the caller should widen the replacement search rather than trust the label.

    Margins are now compared against a CHANCE baseline rather than zero: with N
    labels softmaxed, an uninformative read puts every label at 1/N, so the
    meaningful question is how far the winner sits above that."""
    if not wav_path or not os.path.isfile(wav_path):
        return {}
    g = _clap_rank(wav_path, _GENRES, log=log)
    m = _clap_rank(wav_path, _MOODS, log=log)
    if not g or not m:
        return {}
    g_chance, m_chance = 1.0 / len(_GENRES), 1.0 / len(_MOODS)
    out = {
        'genre': g[0][0],
        'genre_score': round(g[0][1], 4),
        'genre_margin': round(g[0][1] - (g[1][1] if len(g) > 1 else 0), 4),
        'genre_over_chance': round(g[0][1] - g_chance, 4),
        'mood': m[0][0],
        'mood_score': round(m[0][1], 4),
        'mood_margin': round(m[0][1] - (m[1][1] if len(m) > 1 else 0), 4),
        'mood_over_chance': round(m[0][1] - m_chance, 4),
        'genre_ranked': [{'label': k, 'score': round(v, 4)} for k, v in g[:5]],
        'mood_ranked': [{'label': k, 'score': round(v, 4)} for k, v in m[:5]],
    }
    # Confident = the winner beats the runner-up AND clears chance by a real
    # margin. Either alone is weak: a two-way tie at the top can still sit far
    # above chance, and a label can beat chance while being indistinguishable
    # from the next one down.
    out['confident'] = bool(
        out['genre_margin'] >= 0.05 and out['genre_over_chance'] >= 0.05 and out['mood_margin'] >= 0.05
    )
    if log:
        log(
            f'soundtrack: {out["genre"]} ({out["genre_score"]:.3f}) / '
            f'{out["mood"]} ({out["mood_score"]:.3f}) '
            f'[margins {out["genre_margin"]:.3f}/{out["mood_margin"]:.3f}, '
            f'chance {g_chance:.2f}]'
            f'{"" if out["confident"] else " — AMBIGUOUS"}'
        )
    return out


# CLAP genre → the mood vocabulary audio_service.get_music_for_topic understands.
_GENRE_TO_MOOD = {
    'cinematic orchestral': 'epic',
    'epic trailer': 'epic',
    'lo-fi hip hop': 'calm',
    'ambient electronic': 'calm',
    'acoustic folk': 'calm',
    'synthwave': 'upbeat',
    'upbeat pop': 'upbeat',
    'corporate uplifting': 'upbeat',
    'tense underscore': 'tense',
    'dark techno': 'tense',
}
_MOOD_TO_MOOD = {
    'happy': 'upbeat',
    'energetic': 'upbeat',
    'triumphant': 'epic',
    'sad': 'somber',
    'melancholic': 'somber',
    'calm': 'calm',
    'tense': 'tense',
    'eerie': 'tense',
}


def music_request(analysis: dict) -> dict:
    """Turn the CLAP reading into a replacement request for audio_service.

    Same genre, DIFFERENT track — that is the whole job of step 6. When CLAP was
    ambiguous the genre label is dropped and mood alone drives the pick, because
    a confidently-wrong genre is worse than none."""
    if not analysis:
        return {'mood': 'calm', 'genre': '', 'confident': False}
    genre = analysis.get('genre') or ''
    mood = _GENRE_TO_MOOD.get(genre) or _MOOD_TO_MOOD.get(analysis.get('mood') or '') or 'calm'
    if not analysis.get('confident'):
        mood = _MOOD_TO_MOOD.get(analysis.get('mood') or '') or mood
        genre = ''
    return {
        'mood': mood,
        'genre': genre,
        'confident': bool(analysis.get('confident')),
        'source_mood': analysis.get('mood', ''),
    }
