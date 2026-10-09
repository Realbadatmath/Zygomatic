# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.scoring — the local LLM span pass and the fused score curve.

Lines 438-645 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import math
import os

from zyg_workflows import remix_ingest as RI
from zyg_workflows.net import safe_urlopen

from .constants import _OLLAMA, _env_i

from .jobs import _log

from .media import _gpu_clear

# Bound by assignment (never `from . import`), to __package__ — which IS the
# old module's own __name__, whichever route it is imported by. The logger a
# moved line writes to must not be renamed by the move.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── local LLM (Ollama, pattern B: safe_urlopen + format=json + preflight) ────


def _llm_model() -> str:
    # qwen3.5:9b, not gpt-oss:20b: format:'json' returns an EMPTY response on
    # gpt-oss (harmony channels vs the format grammar, verified ollama 0.17.7);
    # murch_engine picked the same model for the same strict-JSON task shape.
    return os.environ.get('ZYG_REMIX_LLM_MODEL', 'qwen3.5:9b')


def _ollama_json(prompt, timeout=240, num_predict=900):
    if not _gpu_clear(9.0):
        return None
    try:  # server-up preflight (3 s) — never stall a tick on a dead daemon
        with safe_urlopen(f'{_OLLAMA}/api/version', timeout=3):
            pass
    except Exception:
        return None
    _m = _llm_model()
    payload = json.dumps(
        {
            'model': _m,
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            # qwen3.x are thinking models: think tokens eat num_predict and 'response'
            # comes back empty; non-thinking models 500 on the think key, so add it
            # conditionally (animated_sdxl_dataset.py:167 / cell_vlm_judge.py:56 pattern)
            **({'think': False} if _m.startswith('qwen3') else {}),
            'keep_alive': '2m',
            'options': {'temperature': 0.2, 'num_predict': num_predict, 'num_ctx': 8192},
        }
    ).encode()
    try:
        from zyg_workflows import llm_audit as _la_rx

        _data = _la_rx.ollama_post(f'{_OLLAMA}/api/generate', json.loads(payload), timeout=timeout, stage='remix')
        # thinking models can route output into 'thinking' even with
        # think:false (murch_engine._ollama_response_text pattern)
        raw = (_data.get('response') or '').strip() or (_data.get('thinking') or '')
        raw = raw.strip().strip('`')
        return json.loads(raw[raw.find('{') : raw.rfind('}') + 1])
    except Exception:
        return None


def _ollama_release():
    try:
        payload = json.dumps({'model': _llm_model(), 'prompt': '', 'keep_alive': 0}).encode()
        with safe_urlopen(f'{_OLLAMA}/api/generate', data=payload, timeout=15):
            pass
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('ollama model release skipped: %s', _exc)


def _llm_spans(pid, segments, dur):
    """Ask the local LLM for interesting spans. Absence just renormalizes fusion."""
    max_s = _env_i('ZYG_REMIX_SRC_MAX_MIN', 90) * 60
    lines, t_cap = [], min(dur, max_s)
    for s in segments:
        if s['start'] > t_cap:
            break
        lines.append(f'[{int(s["start"])}] {s["text"]}')
    if dur > max_s:
        _log(
            pid,
            'WARNING',
            'Select Moments',
            f'transcript truncated to first {max_s // 60} min of {dur / 60:.0f} min source',
        )
    prompt = (
        'You are a short-form video editor. Below is a timestamped transcript '
        '("[seconds] text"). Identify up to 8 self-contained, high-energy moments '
        '(a joke landing, a heated exchange, a revelation, a strong story beat). '
        'Only use moments explicitly present in the transcript — never invent context. '
        'Answer STRICT JSON: {"spans":[{"start":<sec>,"end":<sec>,"score":<0..1>,'
        '"reason":"<8 words>"}]}\n\nTRANSCRIPT:\n' + '\n'.join(lines)[:24000]
    )
    resp = _ollama_json(prompt)
    spans = []
    for sp in (resp or {}).get('spans') or []:
        try:
            a, b = float(sp['start']), float(sp['end'])
            if 0 <= a < b <= dur + 1:
                spans.append(
                    {
                        'start': a,
                        'end': min(b, dur),
                        'score': max(0.0, min(1.0, float(sp.get('score', 0.5)))),
                        'reason': str(sp.get('reason') or '')[:60],
                    }
                )
        except (KeyError, TypeError, ValueError) as _exc:
            _zyg_log.debug('unparseable LLM span dropped: %s', _exc)
            continue
    return spans


# ── score-curve fusion (weights + measurements: project memory 2026-08-05) ───


def _smooth(xs, w):
    n = len(xs)
    return [sum(xs[max(0, i - w) : min(n, i + w + 1)]) / len(xs[max(0, i - w) : min(n, i + w + 1)]) for i in range(n)]


def _norm01(xs):
    lo, hi = min(xs), max(xs)
    return [(x - lo) / max(hi - lo, 1e-9) for x in xs]


def _fused_curve(dur, heatmap, comments, llm_spans, rms):
    n = int(math.ceil(dur))
    S1, w1 = [0.0] * n, 0.0
    if heatmap:
        vals = [float(b.get('value') or 0) for b in heatmap]
        det = RI.detrend_heatmap(vals, w=12)
        bw = dur / len(det)
        S1 = _smooth([det[min(int(t / bw), len(det) - 1)] for t in range(n)], 5)
        w1 = 0.35
    S2, w2 = [0.0] * n, 0.0
    if comments:
        sigma = max(20.0, 2 * dur / 100.0)
        for t, likes in comments:
            wgt = 1.0 + math.log1p(likes)
            for i in range(max(0, int(t - 4 * sigma)), min(n, int(t + 4 * sigma))):
                S2[i] += wgt * math.exp(-0.5 * ((i - t) / sigma) ** 2)
        if max(S2) > 0:
            S2, w2 = _norm01(S2), 0.25
    S3, w3 = [0.0] * n, 0.0
    if llm_spans:
        for sp in llm_spans:
            for i in range(int(sp['start']), min(n, int(sp['end']) + 1)):
                S3[i] = max(S3[i], sp['score'])
        w3 = 0.25
    S4, w4 = [0.0] * n, 0.0
    if rms and max(rms) > 0:
        S4 = _norm01(_smooth((rms + [0.0] * n)[:n], 3))
        w4 = 0.15
    Z = (w1 + w2 + w3 + w4) or 1.0
    S = [(w1 * S1[i] + w2 * S2[i] + w3 * S3[i] + w4 * S4[i]) / Z for i in range(n)]
    for i in range(n):  # intro tax survives detrending; outro cards
        if i < 0.02 * dur:
            S[i] *= 0.5
        if i > 0.97 * dur:
            S[i] *= 0.7
    return S, {'heatmap': w1 > 0, 'comments': w2 > 0, 'llm': w3 > 0, 'rms': w4 > 0}


def _pick_windows(S, n_clips, min_len, max_len, min_gap=30):
    """Best windows by MEAN score (sum biases toward max_len), greedy non-overlap."""
    S = list(S)
    prefix = [0.0]
    for v in S:
        prefix.append(prefix[-1] + v)
    picks = []
    for _ in range(n_clips):
        best, best_mean = None, -1.0
        for a in range(0, len(S) - min_len):
            if S[a] <= 0:
                continue
            for L in range(min_len, min(max_len, len(S) - a) + 1, 5):
                mean = (prefix[a + L] - prefix[a]) / L
                if mean > best_mean:
                    best, best_mean = (a, L), mean
        if best is None or best_mean <= 0:
            break
        a, L = best
        picks.append({'start': float(a), 'end': float(a + L), 'mean_score': round(best_mean, 4)})
        for i in range(max(0, a - min_gap), min(len(S), a + L + min_gap)):
            S[i] = 0.0
        prefix = [0.0]
        for v in S:
            prefix.append(prefix[-1] + v)
    return picks


def _snap_window(t_in, t_out, segments, silences, dur, min_len, max_len):
    """Sentence-boundary + silence-midpoint snapping; asymmetric pad 0.6 in / 0.8 out
    (a clip ending 0.3 s early feels broken; 0.5 s late feels intentional)."""

    def _seg_at(t):
        for s in segments or []:
            if s['start'] <= t <= s['end']:
                return s
        return None

    mids = [(a + b) / 2.0 for a, b in silences or []]
    s_seg = _seg_at(t_in)
    s = s_seg['start'] if s_seg else t_in
    cand = [m for m in mids if s - 3.0 <= m <= s + 0.5]
    t_in2 = (max(cand) if cand else s) - 0.6
    e_seg = _seg_at(t_out)
    e = e_seg['end'] if e_seg else t_out
    cand = [m for m in mids if e - 0.5 <= m <= e + 3.0]
    t_out2 = (min(cand) if cand else e) + 0.8
    t_in2 = max(0.0, t_in2)
    t_out2 = min(dur, t_out2)
    if t_out2 - t_in2 > max_len:
        t_out2 = t_in2 + max_len
        cand = [m for m in mids if t_out2 - 4.0 <= m <= t_out2]
        if cand:
            t_out2 = max(cand)
    if t_out2 - t_in2 < min_len:
        t_out2 = min(dur, t_in2 + min_len)
    return round(t_in2, 2), round(t_out2, 2)
