# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Layer 4 — post-render LLM self-evaluation and the full Murch pass.

Moved verbatim from murch_engine.py lines 2357-2535.
"""

from __future__ import annotations
import os
import json
import time

from zyg_workflows.net import safe_urlopen
from zyg_workflows import paths

from zyg_workflows.murch_engine.base import (
    MURCH_LLM_MODEL,
    _dbg,
    _log_ollama_prompt,
    _ollama_response_text,
)
from zyg_workflows.murch_engine.alignment import extract_word_timestamps_whisper
from zyg_workflows.murch_engine.arc import detect_arc_turning_points, smooth_emotion_curve
from zyg_workflows.murch_engine.cuts import extract_audio_rhythm
from zyg_workflows.murch_engine.emotion import _ollama_llm_available, extract_emotion_curve
from zyg_workflows.murch_engine.images import reset_counterpoint_state, reset_entity_seeds

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4 — Post-Render LLM Self-Evaluation
# ─────────────────────────────────────────────────────────────────────────────


def self_evaluate_sequence(
    image_sequence: list[dict],
    ollama_url: str = paths.ZYG_OLLAMA_URL,
    debug_log: list | None = None,
    pipeline_id: str = '',
) -> dict:
    """
    Layer 4: Ask Ollama to evaluate the image sequence against Murch's six criteria.
    image_sequence: list of {idx, prompt, shot_type, emotion, intensity, duration, transition, counterpoint}
    Returns {score_1_to_10, weakest_cuts: [...], suggestions: [...], overall_notes: str}
    """
    if debug_log is None:
        debug_log = []

    if not image_sequence:
        return {'score': 0, 'weakest_cuts': [], 'suggestions': [], 'overall_notes': 'No sequence to evaluate'}

    # Build compact sequence description for the LLM
    seq_lines = []
    for item in image_sequence:
        seq_lines.append(
            f'[{item["idx"]}] {item.get("shot_type", "?")} | {item.get("emotion", "?")}({item.get("intensity", 0):.2f}) | '
            f'{item.get("duration", 0):.1f}s | {"COUNTERPOINT" if item.get("counterpoint") else "direct"} | '
            f'→{item.get("transition", "cut")} | prompt: {str(item.get("prompt", ""))[:60]}'
        )
    sequence_text = '\n'.join(seq_lines)

    prompt = (
        "You are a film editor evaluating a documentary image sequence based on Walter Murch's six criteria:\n"
        '1. Emotion (most important)\n2. Story\n3. Rhythm\n4. Eye trace\n5. 2D continuity\n6. 3D continuity\n\n'
        f'Here is the sequence ({len(image_sequence)} images):\n{sequence_text}\n\n'
        'Evaluate this sequence and return ONLY valid JSON with these keys:\n'
        '  "score": integer 1-10 (how well it follows Murch principles)\n'
        '  "weakest_cuts": array of image indices where the cut is worst (max 3)\n'
        '  "suggestions": array of short strings describing improvements for each weak cut\n'
        '  "overall_notes": one sentence summary of main issue\n\nJSON:'
    )

    try:
        # Skip if the murch LLM isn't installed in Ollama (fail fast, no hang)
        if not _ollama_llm_available(ollama_url, debug_log):
            _dbg(debug_log, 'self_eval', f'{MURCH_LLM_MODEL} not installed — skipping self-eval', 'WARN')
            return {
                'score': 0,
                'weakest_cuts': [],
                'suggestions': [],
                'overall_notes': 'Eval skipped — LLM not available',
            }
        payload = json.dumps(
            {
                'model': MURCH_LLM_MODEL,
                'prompt': prompt,
                'stream': False,
                'think': False,
                'format': 'json',
                'options': {'temperature': 0.2, 'num_predict': 400},
            }
        ).encode()
        _log_ollama_prompt(
            'ollama_self_eval',
            'Murch/self_eval',
            pipeline_id,
            prompt,
            direction='sent',
            llm=MURCH_LLM_MODEL,
            from_who='system',
            to_who=MURCH_LLM_MODEL,
            meta={'n_images': len(image_sequence)},
        )
        with safe_urlopen(f'{ollama_url}/api/generate', data=payload, timeout=120) as resp:
            raw = _ollama_response_text(resp.read())
        _log_ollama_prompt(
            'ollama_self_eval',
            'Murch/self_eval',
            pipeline_id,
            raw,
            direction='received',
            role='assistant',
            llm=MURCH_LLM_MODEL,
            from_who=MURCH_LLM_MODEL,
            to_who='system',
            meta={'n_images': len(image_sequence)},
        )
        result = json.loads(raw)
        result.setdefault('score', 0)
        result.setdefault('weakest_cuts', [])
        result.setdefault('suggestions', [])
        result.setdefault('overall_notes', '')
        _dbg(
            debug_log,
            'self_eval',
            f'Self-eval score: {result["score"]}/10 | weakest: {result["weakest_cuts"]} | '
            f'notes: {result["overall_notes"][:80]}',
            'INFO',
            {'result': result},
        )
        return result
    except Exception as e:
        _dbg(debug_log, 'self_eval', f'Self-evaluation failed: {e}', 'WARN')
        return {'score': 0, 'weakest_cuts': [], 'suggestions': [], 'overall_notes': f'Eval failed: {e}'}


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: Full Murch pass — call this once per pipeline run
# ─────────────────────────────────────────────────────────────────────────────


def run_full_murch_pass(
    narration_script: str,
    tts_audio_path: str | None = None,
    ollama_url: str = paths.ZYG_OLLAMA_URL,
    use_embeddings: bool = True,
    debug_log: list | None = None,
) -> dict:
    """
    Convenience wrapper: runs Layer 1 (emotion + arc + Whisper) in one call.
    Returns {
      'emotion_curve':     [...],   # smoothed, cascaded
      'raw_emotion_curve': [...],   # pre-smoothing
      'turning_points':    [...],
      'word_timings':      [...],   # from Whisper (empty if no audio)
      'rhythm_cut_times':  [...],   # from librosa
      'debug_log':         [...],
    }
    """
    if debug_log is None:
        debug_log = []

    _dbg(debug_log, 'full_murch_pass', 'Starting full Murch Layer-1 pass', 'INFO')
    t0 = time.monotonic()

    # 1. Cascading emotion curve
    raw_curve = extract_emotion_curve(
        narration_script, ollama_url=ollama_url, use_embeddings=use_embeddings, debug_log=debug_log
    )

    # 2. Smooth the curve
    smooth_curve = smooth_emotion_curve(raw_curve, sigma=2.5, debug_log=debug_log)

    # 3. Arc turning points
    turning_points = detect_arc_turning_points(
        narration_script, smooth_curve, ollama_url=ollama_url, debug_log=debug_log
    )

    # 4. Whisper word timestamps
    word_timings: list[tuple[str, float]] = []
    rhythm_cuts: list[float] = []
    if tts_audio_path and os.path.exists(tts_audio_path):
        word_timings = extract_word_timestamps_whisper(tts_audio_path, narration_script, debug_log)
        # Rhythm cut suggestion based on RMS
        rhythm_cuts = extract_audio_rhythm(tts_audio_path, n_cuts=max(1, len(smooth_curve) // 3), debug_log=debug_log)

    elapsed = time.monotonic() - t0
    _dbg(
        debug_log,
        'full_murch_pass',
        f'Layer-1 complete in {elapsed:.1f}s | curve={len(smooth_curve)} pts | '
        f'turning_pts={len(turning_points)} | word_timings={len(word_timings)} | '
        f'rhythm_cuts={len(rhythm_cuts)}',
        'INFO',
    )

    # Reset per-run stateful counters
    reset_counterpoint_state()
    reset_entity_seeds()

    return {
        'emotion_curve': smooth_curve,
        'raw_emotion_curve': raw_curve,
        'turning_points': turning_points,
        'word_timings': word_timings,
        'rhythm_cut_times': rhythm_cuts,
        'debug_log': debug_log,
    }
