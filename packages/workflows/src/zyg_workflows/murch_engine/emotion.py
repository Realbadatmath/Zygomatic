# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Layer 1a — cascading emotion scorer (keyword / embedding / LLM tiers).

Moved verbatim from murch_engine.py lines 127-597.
"""

from __future__ import annotations
import re
import json

from zyg_workflows.net import safe_urlopen
from zyg_workflows import paths

from zyg_workflows.murch_engine.base import (
    MURCH_LLM_MODEL,
    _dbg,
    _log_ollama_prompt,
    _ollama_response_text,
)

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1a — Cascading Emotion Scorer
# ─────────────────────────────────────────────────────────────────────────────

_EMOTION_KEYWORDS = {
    'triumph': (
        [
            'victory',
            'triumph',
            'conquered',
            'achieved',
            'won',
            'defeated',
            'glory',
            'celebrated',
            'success',
            'liberation',
            'independent',
        ],
        0.85,
    ),
    'tension': (
        [
            'threatened',
            'conflict',
            'war',
            'battle',
            'crisis',
            'danger',
            'siege',
            'invasion',
            'clash',
            'struggle',
            'skirmish',
            'standoff',
        ],
        0.80,
    ),
    'shock': (
        [
            'assassinated',
            'executed',
            'collapsed',
            'destroyed',
            'sudden',
            'catastroph',
            'massacre',
            'betrayed',
            'murdered',
            'obliterated',
        ],
        0.95,
    ),
    'grief': (
        [
            'death',
            'died',
            'mourned',
            'tragedy',
            'lost',
            'fallen',
            'perished',
            'sacrifice',
            'suffering',
            'mourning',
            'widowed',
            'buried',
        ],
        0.75,
    ),
    'awe': (
        [
            'magnificent',
            'vast',
            'enormous',
            'breathtaking',
            'wonder',
            'monumental',
            'grand',
            'legendary',
            'epic',
            'towering',
            'awe',
        ],
        0.70,
    ),
    'mystery': (
        [
            'unknown',
            'mysterious',
            'ancient',
            'lost',
            'buried',
            'forgotten',
            'hidden',
            'secret',
            'enigma',
            'disappear',
            'vanished',
            'coded',
        ],
        0.60,
    ),
    'unease': (
        [
            'however',
            'despite',
            'warned',
            'threatened',
            'tension',
            'rivalry',
            'competition',
            'conflict',
            'uneasy',
            'fragile',
            'volatile',
        ],
        0.50,
    ),
    'calm': (
        [
            'peace',
            'established',
            'founded',
            'built',
            'created',
            'developed',
            'grew',
            'expanded',
            'flourished',
            'prospered',
            'settled',
            'era',
        ],
        0.30,
    ),
}

# Words that invert emotion (irony/negation detectors)
_NEGATION_WORDS = {'not', 'never', 'no', 'neither', 'nor', 'without', 'despite', 'although', 'though', 'yet', 'but'}

_ST_MODEL = None  # lazy-loaded sentence transformer


def _load_st_model(debug_log: list):
    global _ST_MODEL
    if _ST_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer

            _dbg(debug_log, 'emotion_cascade', 'Loading all-MiniLM-L6-v2 sentence transformer …', 'INFO')
            _ST_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
            _dbg(debug_log, 'emotion_cascade', 'Sentence transformer loaded OK', 'INFO')
        except Exception as e:
            _dbg(debug_log, 'emotion_cascade', f'Failed to load sentence transformer: {e}', 'WARN')
    return _ST_MODEL


# Pre-computed anchor embeddings for each emotion (computed lazily)
_EMOTION_ANCHORS: dict | None = None
_EMOTION_ANCHOR_TEXTS = {
    'triumph': 'They won a great victory. The crowd celebrated their triumph.',
    'tension': 'The situation was tense. War was about to break out.',
    'shock': 'He was suddenly assassinated. The city collapsed without warning.',
    'grief': 'She died. They mourned the tragedy. The loss was unbearable.',
    'awe': 'The sight was breathtaking. The scale was monumental and vast.',
    'mystery': 'No one knew the truth. The ancient secret remained hidden.',
    'unease': 'Despite the peace, tension lingered. The stability was fragile.',
    'calm': 'The empire flourished. Peace was established. The city grew.',
}


def _get_emotion_anchors(model, debug_log: list) -> dict:
    global _EMOTION_ANCHORS
    if _EMOTION_ANCHORS is None and model is not None:
        try:
            texts = list(_EMOTION_ANCHOR_TEXTS.values())
            labels = list(_EMOTION_ANCHOR_TEXTS.keys())
            vecs = model.encode(texts, convert_to_numpy=True)
            _EMOTION_ANCHORS = {labels[i]: vecs[i] for i in range(len(labels))}
            _dbg(
                debug_log,
                'emotion_cascade',
                f'Emotion anchors computed for {len(_EMOTION_ANCHORS)} categories',
                'DEBUG',
            )
        except Exception as e:
            _dbg(debug_log, 'emotion_cascade', f'Anchor computation failed: {e}', 'WARN')
    return _EMOTION_ANCHORS or {}


def _keyword_score(sentence: str) -> dict[str, float]:
    """Fast keyword-based scorer. Returns {emotion: intensity}."""
    words = set(sentence.lower().split())
    negated = bool(words & _NEGATION_WORDS)
    scores: dict[str, float] = {}
    for emo, (kws, base) in _EMOTION_KEYWORDS.items():
        matches = sum(1 for kw in kws if kw in sentence.lower())
        if matches:
            intensity = min(1.0, base + (matches - 1) * 0.05)
            if negated:
                # Negation flips the emotion toward grief or unease
                if emo in ('triumph', 'awe'):
                    scores['grief'] = max(scores.get('grief', 0), intensity * 0.7)
                    scores['unease'] = max(scores.get('unease', 0), intensity * 0.5)
                else:
                    scores[emo] = intensity * 0.6
            else:
                scores[emo] = intensity
    return scores


def _embedding_score(sentence: str, model, anchors: dict, debug_log: list) -> dict[str, float]:
    """Semantic similarity scorer using sentence embeddings."""
    try:
        import numpy as np

        vec = model.encode([sentence], convert_to_numpy=True)[0]
        scores: dict[str, float] = {}
        for emo, anchor_vec in anchors.items():
            sim = float(np.dot(vec, anchor_vec) / (np.linalg.norm(vec) * np.linalg.norm(anchor_vec) + 1e-9))
            scores[emo] = max(0.0, sim)
        # Normalize to match intensity scale
        top = max(scores.values()) if scores else 0.0
        if top < 1e-9:
            return {}
        return {k: round(v / top * _EMOTION_KEYWORDS[k][1], 3) for k, v in scores.items()}
    except Exception as e:
        _dbg(debug_log, 'embedding_score', f'Embedding scoring failed: {e}', 'WARN')
        return {}


def _llm_score(sentence: str, ollama_url: str, debug_log: list, pipeline_id: str = '') -> dict[str, float]:
    """LLM-based emotion scoring via Ollama for ambiguous sentences."""
    if not ollama_url:
        return {}
    prompt = (
        'Analyze the emotional content of this sentence from a historical documentary.\n'
        'Return ONLY valid JSON with these exact keys: shock, grief, triumph, tension, awe, mystery, unease, calm\n'
        'Each value must be a float between 0.0 and 1.0.\n'
        'Account for irony, negation, and implied meaning — not just literal words.\n\n'
        f'Sentence: "{sentence}"\n\nJSON:'
    )
    try:
        payload = json.dumps(
            {
                'model': MURCH_LLM_MODEL,
                'prompt': prompt,
                'stream': False,
                'think': False,
                'format': 'json',
                'options': {'temperature': 0.1, 'num_predict': 120},
            }
        ).encode()
        _log_ollama_prompt(
            'ollama_emotion_score',
            'Murch/emotion',
            pipeline_id,
            prompt,
            direction='sent',
            llm=MURCH_LLM_MODEL,
            from_who='system',
            to_who=MURCH_LLM_MODEL,
            meta={'sentence': sentence[:120]},
        )
        with safe_urlopen(f'{ollama_url}/api/generate', data=payload, timeout=70) as resp:
            raw = _ollama_response_text(resp.read())
        _log_ollama_prompt(
            'ollama_emotion_score',
            'Murch/emotion',
            pipeline_id,
            raw,
            direction='received',
            role='assistant',
            llm=MURCH_LLM_MODEL,
            from_who=MURCH_LLM_MODEL,
            to_who='system',
            meta={'sentence': sentence[:120]},
        )
        scores = json.loads(raw)
        valid = {k: float(v) for k, v in scores.items() if k in _EMOTION_KEYWORDS and isinstance(v, (int, float))}
        _dbg(debug_log, 'llm_score', f'LLM scored: {valid}', 'DEBUG', {'sentence': sentence[:80]})
        return valid
    except Exception as e:
        _dbg(debug_log, 'llm_score', f'LLM emotion call failed: {e}', 'WARN')
        return {}


def _cascade_score_sentence(
    sentence: str,
    model,
    anchors: dict,
    ollama_url: str,
    debug_log: list,
) -> tuple[str, float, str]:
    """
    Three-tier cascade:
      Tier 1: Keyword   — if dominant emotion margin >= 0.4, trust it
      Tier 2: Embedding — if ST agrees with keyword, high confidence; if disagrees, go to Tier 3
      Tier 3: LLM       — used only when Tier 1+2 are ambiguous
    Returns (emotion, intensity, tier_used)
    """
    kw = _keyword_score(sentence)
    if not kw:
        # No keywords at all — use embedding directly
        if model and anchors:
            emb = _embedding_score(sentence, model, anchors, debug_log)
            if emb:
                top_emo = max(emb, key=emb.get)
                top_val = emb[top_emo]
                second_vals = sorted(emb.values(), reverse=True)
                margin = top_val - (second_vals[1] if len(second_vals) > 1 else 0)
                if margin >= 0.15:
                    return top_emo, round(top_val, 3), 'embedding'
        # True neutral — no keywords, no clear embedding signal
        return 'calm', 0.25, 'default'

    top_kw_emo = max(kw, key=kw.get)
    top_kw_val = kw[top_kw_emo]
    second_kw_vals = sorted(kw.values(), reverse=True)
    kw_margin = top_kw_val - (second_kw_vals[1] if len(second_kw_vals) > 1 else 0)

    if kw_margin >= 0.35:
        # Keyword is confident — use it (Tier 1)
        _dbg(debug_log, 'cascade', f'Tier1 keyword: {top_kw_emo}={top_kw_val:.2f} margin={kw_margin:.2f}', 'DEBUG')
        return top_kw_emo, round(top_kw_val, 3), 'keyword'

    # Keyword ambiguous — run embedding (Tier 2)
    if model and anchors:
        emb = _embedding_score(sentence, model, anchors, debug_log)
        if emb:
            top_emb_emo = max(emb, key=emb.get)
            top_emb_val = emb[top_emb_emo]
            if top_kw_emo == top_emb_emo:
                # Agreement between keyword and embedding — high confidence
                blended = top_kw_val * 0.6 + top_emb_val * 0.4
                _dbg(debug_log, 'cascade', f'Tier2 agree: {top_kw_emo}={blended:.2f}', 'DEBUG')
                return top_kw_emo, round(blended, 3), 'kw+embedding'
            else:
                # Disagreement — call LLM (Tier 3)
                _dbg(debug_log, 'cascade', f'Tier3 LLM needed: kw={top_kw_emo} emb={top_emb_emo}', 'DEBUG')
                llm = _llm_score(sentence, ollama_url, debug_log)
                if llm:
                    top_llm_emo = max(llm, key=llm.get)
                    # LLM is tie-breaker; blend with whichever it agrees with
                    agreed = top_kw_val if top_llm_emo == top_kw_emo else top_emb_val
                    blended = llm[top_llm_emo] * 0.5 + agreed * 0.5
                    return top_llm_emo, round(blended, 3), 'kw+emb+llm'

    # Fallback to keyword
    return top_kw_emo, round(top_kw_val, 3), 'keyword_fallback'


def _ollama_llm_available(ollama_url: str, debug_log: list) -> bool:
    """
    Quick pre-flight: check that Ollama is reachable AND MURCH_LLM_MODEL is
    installed (/api/tags). Ollama loads the model on first call; every murch
    LLM pass runs before FLUX claims the GPU, so an on-demand load is fine.
    The old check demanded the model be already RESIDENT (/api/ps) — with a
    47 GB qwen2.5:72b that was never true during a run, so the LLM tier
    silently degraded to keywords and the self-eval never executed.
    3-second timeout so a cold/absent Ollama doesn't block scoring.
    """
    try:
        with safe_urlopen(f'{ollama_url}/api/tags', timeout=3) as resp:
            data = json.loads(resp.read())
        names = [m.get('name', '') for m in data.get('models', [])]
        installed = any(n == MURCH_LLM_MODEL or n.split(':')[0] == MURCH_LLM_MODEL for n in names)
        _dbg(
            debug_log,
            'ollama_preflight',
            f'Ollama /tags: {len(names)} models; {MURCH_LLM_MODEL} '
            f'{"installed — LLM tier active" if installed else "NOT installed — LLM tier disabled"}',
            'DEBUG' if installed else 'WARN',
        )
        return installed
    except Exception as e:
        _dbg(debug_log, 'ollama_preflight', f'Ollama not reachable ({e}) — LLM tier disabled', 'DEBUG')
        return False


def extract_emotion_curve(
    narration_script: str,
    ollama_url: str = paths.ZYG_OLLAMA_URL,
    use_embeddings: bool = True,
    debug_log: list | None = None,
    haiku_emotion_scores: dict | None = None,
) -> list[dict]:
    """
    Layer 1a: Full cascading emotion scoring for every sentence.
    Returns list of {sentence_idx, sentence, emotion, intensity, tier}.

    haiku_emotion_scores: optional dict[int, (emotion, intensity)] pre-computed by a
    batched Claude Haiku call. When provided, Ollama is disabled and any sentence that
    falls through to keyword_fallback or default tier is upgraded to the Haiku score.
    """
    if debug_log is None:
        debug_log = []

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration_script) if len(s.strip()) > 15]
    _dbg(debug_log, 'extract_emotion_curve', f'Scoring {len(sentences)} sentences', 'INFO')

    model = _load_st_model(debug_log) if use_embeddings else None
    anchors = _get_emotion_anchors(model, debug_log) if model else {}

    # When Haiku pre-scores are provided, skip Ollama entirely — Haiku handles ambiguous cases.
    if haiku_emotion_scores:
        _effective_ollama_url = ''
        _dbg(
            debug_log,
            'extract_emotion_curve',
            f'Haiku emotion scores provided ({len(haiku_emotion_scores)} sentences) — Ollama tier disabled',
            'INFO',
        )
    else:
        # Pre-flight: only attempt LLM tier if Ollama has the murch LLM installed.
        # Avoids 15s × N timeout stalls when the model isn't loaded.
        _llm_available = _ollama_llm_available(ollama_url, debug_log)
        _effective_ollama_url = ollama_url if _llm_available else ''

    tier_counts = {
        'keyword': 0,
        'keyword_fallback': 0,
        'embedding': 0,
        'kw+embedding': 0,
        'kw+emb+llm': 0,
        'default': 0,
        'haiku': 0,
    }
    curve = []
    for i, sent in enumerate(sentences):
        # After 3 consecutive LLM timeouts, disable the LLM tier for the remainder of the run
        # to avoid burning 4s × (N-3) calls on a model that isn't responding.
        if _effective_ollama_url:
            _recent_llm_fails = sum(1 for _e in debug_log[-6:] if 'LLM emotion call failed' in _e.get('msg', ''))
            if _recent_llm_fails >= 3:
                _effective_ollama_url = ''
                _dbg(
                    debug_log,
                    'extract_emotion_curve',
                    'LLM tier disabled after 3 consecutive timeouts — using keyword/embedding only',
                    'WARN',
                )
        try:
            emo, intensity, tier = _cascade_score_sentence(sent, model, anchors, _effective_ollama_url, debug_log)
            # When keyword/embedding couldn't resolve this sentence and Haiku scored it, use Haiku.
            if tier in ('keyword_fallback', 'default') and haiku_emotion_scores and i in haiku_emotion_scores:
                h_emo, h_intensity = haiku_emotion_scores[i]
                _dbg(
                    debug_log,
                    'extract_emotion_curve',
                    f'Haiku override sentence {i}: {tier} → haiku ({h_emo} {h_intensity:.2f})',
                    'DEBUG',
                )
                emo, intensity, tier = h_emo, h_intensity, 'haiku'
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            curve.append({'sentence_idx': i, 'sentence': sent, 'emotion': emo, 'intensity': intensity, 'tier': tier})
        except Exception as e:
            _dbg(debug_log, 'extract_emotion_curve', f'Sentence {i} scoring failed: {e}', 'WARN')
            curve.append({'sentence_idx': i, 'sentence': sent, 'emotion': 'calm', 'intensity': 0.25, 'tier': 'error'})

    _dbg(
        debug_log,
        'extract_emotion_curve',
        f'Emotion curve complete: {len(curve)} points | tier usage: {tier_counts}',
        'INFO',
        {'tier_counts': tier_counts, 'peak': max(curve, key=lambda x: x['intensity']) if curve else None},
    )
    return curve
