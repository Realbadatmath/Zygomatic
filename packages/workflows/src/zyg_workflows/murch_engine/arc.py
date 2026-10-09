# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Layer 1b — Gaussian arc smoothing and turning-point detection.

Moved verbatim from murch_engine.py lines 598-869.
"""

from __future__ import annotations
import logging as _zyg_logging
import json

from zyg_workflows.net import safe_urlopen
from zyg_workflows import paths

from zyg_workflows.murch_engine.base import (
    MURCH_LLM_MODEL,
    _dbg,
    _log_ollama_prompt,
    _ollama_response_text,
)
from zyg_workflows.murch_engine.emotion import _ollama_llm_available

_zyg_log = _zyg_logging.getLogger('zyg_workflows.murch_engine')

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1b — Gaussian Arc Smoothing + Turning Point Detection
# ─────────────────────────────────────────────────────────────────────────────


def smooth_emotion_curve(
    curve: list[dict],
    sigma: float = 2.5,
    debug_log: list | None = None,
) -> list[dict]:
    """
    Apply Gaussian smoothing to emotion intensity values.
    High-variance sections get less smoothing; flat sections get more.
    Returns a new curve with smoothed intensities (originals preserved in 'raw_intensity').
    """
    if debug_log is None:
        debug_log = []
    if not curve:
        return curve

    try:
        import numpy as np
        from scipy.ndimage import gaussian_filter1d

        intensities = np.array([e['intensity'] for e in curve], dtype=float)
        # Adaptive sigma: compute local variance in windows of 5, reduce sigma where variance is high
        local_var = np.array(
            [np.var(intensities[max(0, i - 2) : min(len(intensities), i + 3)]) for i in range(len(intensities))]
        )
        # Where variance > 0.04 (genuine drama), use sigma/2; elsewhere use full sigma
        # (per-element sigma is not supported by scipy, so two passes are blended below)
        low_sigma_mask = local_var > 0.04
        smoothed_full = gaussian_filter1d(intensities, sigma=sigma)
        smoothed_half = gaussian_filter1d(intensities, sigma=sigma / 2)
        smoothed = np.where(low_sigma_mask, smoothed_half, smoothed_full)
        smoothed = np.clip(smoothed, 0.0, 1.0)

        result = []
        for i, entry in enumerate(curve):
            new_entry = dict(entry)
            new_entry['raw_intensity'] = entry['intensity']
            new_entry['intensity'] = round(float(smoothed[i]), 3)
            result.append(new_entry)

        _dbg(
            debug_log,
            'smooth_emotion_curve',
            f'Smoothed {len(curve)} points | max_raw={float(intensities.max()):.2f} '
            f'max_smooth={float(smoothed.max()):.2f} | low-sigma sentences: {int(low_sigma_mask.sum())}',
            'INFO',
            {'sigma': sigma},
        )
        return result
    except Exception as e:
        _dbg(debug_log, 'smooth_emotion_curve', f'Smoothing failed: {e} — returning unsmoothed', 'WARN')
        return curve


def detect_arc_turning_points(
    narration_script: str,
    curve: list[dict],
    ollama_url: str = paths.ZYG_OLLAMA_URL,
    debug_log: list | None = None,
    pipeline_id: str = '',
    haiku_turning_points: list | None = None,
) -> list[dict]:
    """
    Detect narrative turning points (arc boundaries) via LLM + statistical peaks.
    Returns list of {sentence_idx, type, label} where type is:
      'rising' | 'climax' | 'falling' | 'resolution' | 'chapter_break'
    Falls back to Freytag zones if LLM unavailable.

    If haiku_turning_points is provided (pre-computed by Claude Haiku), the Ollama
    LLM tier is skipped entirely — Haiku points are merged with statistical peaks.
    """
    if debug_log is None:
        debug_log = []

    n = len(curve)
    if n == 0:
        return []

    # ── Statistical turning points (peaks in smoothed curve) ──────────────
    try:
        import numpy as np
        from scipy.signal import find_peaks

        intensities = np.array([e['intensity'] for e in curve])
        peaks, props = find_peaks(intensities, prominence=0.15, distance=max(3, n // 10))
        valleys, _ = find_peaks(-intensities, prominence=0.10, distance=max(3, n // 10))
        stat_points = []
        for p in peaks:
            stat_points.append(
                {
                    'sentence_idx': int(p),
                    'type': 'climax',
                    'label': f'peak_{int(p)}',
                    'source': 'statistical',
                    'intensity': round(float(intensities[p]), 3),
                }
            )
        for v in valleys:
            stat_points.append(
                {
                    'sentence_idx': int(v),
                    'type': 'resolution',
                    'label': f'valley_{int(v)}',
                    'source': 'statistical',
                    'intensity': round(float(intensities[v]), 3),
                }
            )
        _dbg(debug_log, 'detect_turning_points', f'Statistical: {len(peaks)} peaks, {len(valleys)} valleys', 'INFO')
    except Exception as e:
        _dbg(debug_log, 'detect_turning_points', f'Statistical detection failed: {e}', 'WARN')
        stat_points = []

    # ── LLM turning point detection ────────────────────────────────────────
    # If Haiku pre-computed points are provided, skip Ollama entirely.
    llm_points = []
    if haiku_turning_points:
        llm_points = [
            p
            for p in haiku_turning_points
            if isinstance(p.get('sentence_idx'), int)
            and p.get('type') in ('rising', 'climax', 'falling', 'resolution', 'chapter_break')
        ]
        for p in llm_points:
            p.setdefault('source', 'haiku')
        _dbg(
            debug_log,
            'detect_turning_points',
            f'Haiku pre-computed: {len(llm_points)} turning points (Ollama skipped)',
            'INFO',
            {'points': llm_points},
        )
    else:
        # Skip entirely if Ollama/the murch LLM was not reachable (avoids 30s stall).
        _llm_ok = _ollama_llm_available(ollama_url, debug_log)
        sentences_list = [e['sentence'] for e in curve]
        numbered = '\n'.join(f'{i}: {s[:80]}' for i, s in enumerate(sentences_list[:30]))
        prompt = (
            'You are analyzing a historical documentary narration.\n'
            'Identify the 3–6 major narrative turning points in this text.\n'
            'A turning point is where the story shifts: rising action begins, climax hits, '
            'falling action starts, a chapter ends, or a new subject is introduced.\n\n'
            f'Sentences (index: text):\n{numbered}\n\n'
            'Return ONLY a JSON array of objects with keys "sentence_idx" (integer) and '
            '"type" (one of: rising, climax, falling, resolution, chapter_break) and "label" (short phrase).\n'
            'Example: [{"sentence_idx": 4, "type": "rising", "label": "conflict begins"}, ...]\n\nJSON:'
        )
        if not _llm_ok:
            _dbg(debug_log, 'detect_turning_points', 'LLM tier skipped (Ollama not available)', 'DEBUG')
        else:
            try:
                payload = json.dumps(
                    {
                        'model': MURCH_LLM_MODEL,
                        'prompt': prompt,
                        'stream': False,
                        'think': False,
                        'format': 'json',
                        'options': {'temperature': 0.1, 'num_predict': 600},
                    }
                ).encode()
                _log_ollama_prompt(
                    'ollama_turning_points',
                    'Murch/arc',
                    pipeline_id,
                    prompt,
                    direction='sent',
                    llm=MURCH_LLM_MODEL,
                    from_who='system',
                    to_who=MURCH_LLM_MODEL,
                )
                with safe_urlopen(f'{ollama_url}/api/generate', data=payload, timeout=70) as resp:
                    raw = _ollama_response_text(resp.read())
                _log_ollama_prompt(
                    'ollama_turning_points',
                    'Murch/arc',
                    pipeline_id,
                    raw,
                    direction='received',
                    role='assistant',
                    llm=MURCH_LLM_MODEL,
                    from_who=MURCH_LLM_MODEL,
                    to_who='system',
                )

                def _repair_json_array(s: str) -> list:
                    s = s.strip()
                    try:
                        return json.loads(s)
                    except ValueError as _exc:
                        _zyg_log.debug('LLM array did not parse, attempting a repair: %s', _exc)
                    last_brace = s.rfind('}')
                    if last_brace != -1:
                        candidate = s[: last_brace + 1]
                        if '[' not in candidate:
                            candidate = '[' + candidate
                        candidate = candidate + ']'
                        try:
                            return json.loads(candidate)
                        except ValueError as _exc:
                            _zyg_log.warning('LLM array could not be repaired, continuing with no points: %s', _exc)
                    return []

                parsed = _repair_json_array(raw)
                if isinstance(parsed, list):
                    llm_points = [
                        p
                        for p in parsed
                        if isinstance(p.get('sentence_idx'), int)
                        and p.get('type') in ('rising', 'climax', 'falling', 'resolution', 'chapter_break')
                    ]
                    for p in llm_points:
                        p['source'] = 'llm'
                _dbg(
                    debug_log,
                    'detect_turning_points',
                    f'LLM found {len(llm_points)} turning points',
                    'INFO',
                    {'points': llm_points},
                )
            except Exception as e:
                _dbg(debug_log, 'detect_turning_points', f'LLM turning point call failed: {e}', 'WARN')

    # ── Merge: LLM takes priority; statistical fills gaps ─────────────────
    merged = list(llm_points)
    llm_indices = {p['sentence_idx'] for p in llm_points}
    for sp in stat_points:
        if not any(abs(sp['sentence_idx'] - li) <= 2 for li in llm_indices):
            merged.append(sp)

    # If nothing found at all, use Freytag zones
    if not merged:
        _dbg(debug_log, 'detect_turning_points', 'No turning points found — using Freytag zones', 'WARN')
        merged = [
            {'sentence_idx': int(n * 0.15), 'type': 'rising', 'label': 'rising action', 'source': 'freytag'},
            {'sentence_idx': int(n * 0.45), 'type': 'climax', 'label': 'climax', 'source': 'freytag'},
            {'sentence_idx': int(n * 0.65), 'type': 'falling', 'label': 'falling action', 'source': 'freytag'},
            {'sentence_idx': int(n * 0.85), 'type': 'resolution', 'label': 'resolution', 'source': 'freytag'},
        ]

    merged.sort(key=lambda x: x['sentence_idx'])
    _dbg(debug_log, 'detect_turning_points', f'Final: {len(merged)} turning points', 'INFO', {'points': merged})
    return merged


def get_arc_zone(sentence_idx: int, turning_points: list[dict], n_sentences: int) -> str:
    """Return the arc zone ('exposition','rising','climax','falling','resolution') for a sentence index."""
    if not turning_points:
        # Freytag fallback
        frac = sentence_idx / max(n_sentences, 1)
        if frac < 0.15:
            return 'exposition'
        if frac < 0.45:
            return 'rising'
        if frac < 0.65:
            return 'climax'
        if frac < 0.85:
            return 'falling'
        return 'resolution'

    zone = 'exposition'
    for tp in turning_points:
        if sentence_idx >= tp['sentence_idx']:
            zone = tp['type']
        else:
            break
    return zone
