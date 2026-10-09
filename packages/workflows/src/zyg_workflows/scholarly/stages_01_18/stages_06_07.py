# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.1 of the scholarly pipeline: turning points, emotions and the emotion curve."""

import re
import traceback

from ._common import (
    _LLM_SMALL,
    _MURCH_MODEL,
    _OLLAMA_BASE_URL,
    _llm_client,
    _log_prompt,
    _zyg_log,
    gui_state,
    safe_urlopen,
)


def stage_06_turning_points_and_emotions(ctx):
    # ── Stage 3.1 pre-step: combined Haiku call (turning points + emotions) ─
    # Single Haiku call returns both turning_points and emotions arrays,
    # replacing the two separate calls that were here before (saves 1 API call
    # per run; total latency is nearly identical since the extra tokens are small).
    ctx._haiku_turning_points = []
    ctx._haiku_emotion_scores = None
    try:
        if ctx._anthropic_key and ctx.narration_script:
            import re as _re_31
            import json as _json_31

            _sentences_31 = [
                s.strip() for s in _re_31.split(r'(?<=[.!?])\s+', ctx.narration_script) if len(s.strip()) > 15
            ]
            _numbered_31 = '\n'.join(f'{i}: {s[:120]}' for i, s in enumerate(_sentences_31))
            _combined_prompt = (
                'You are analyzing a documentary narration script. Perform two tasks simultaneously.\n\n'
                '=== TASK 1: Turning points ===\n'
                'Identify 3–6 major narrative turning points distributed across the full script.\n'
                'A turning point is where the story shifts: rising action begins, climax hits,\n'
                'falling action starts, a chapter ends, or a new subject is introduced.\n\n'
                '=== TASK 2: Emotion scoring ===\n'
                'For EVERY sentence, pick the dominant emotion and an intensity 0.0–1.0.\n'
                'Valid emotions: shock, grief, triumph, tension, awe, mystery, unease, calm\n'
                '  - calm = neutral/informational (0.1–0.3)\n'
                '  - Account for irony, negation, and implied meaning\n'
                '  - Use full range: climactic = 0.8–1.0, quiet = 0.1–0.3\n\n'
                f'Sentences:\n{_numbered_31}\n\n'
                'Return ONLY a single valid JSON object with exactly these two keys:\n'
                '  "turning_points": array — each object: '
                '{"sentence_idx": int, "type": "rising|climax|falling|resolution|chapter_break", "label": "max 5 words"}\n'
                '  "emotions": array — each object: {"i": int, "e": emotion_string, "v": float}\n'
                'Example:\n'
                '{"turning_points":[{"sentence_idx":4,"type":"rising","label":"conflict begins"}],'
                '"emotions":[{"i":0,"e":"tension","v":0.72},{"i":1,"e":"calm","v":0.18}]}\n\nJSON:'
            )
            _log_prompt(
                'haiku_combined_31',
                'Stage 3.1',
                ctx.pipeline_id,
                _combined_prompt,
                meta={'pipeline_type': 'scholarly', 'topic': ctx.topic, 'sentence_count': len(_sentences_31)},
                direction='sent',
                role='user',
                llm=_LLM_SMALL,
                from_who='system',
                to_who=_LLM_SMALL,
            )
            _hk31_resp = _llm_client(ctx._anthropic_key).messages.create(
                model=_LLM_SMALL,
                max_tokens=8000,
                temperature=0.1,
                messages=[{'role': 'user', 'content': _combined_prompt}],
            )
            _hk31_raw = _hk31_resp.content[0].text.strip()
            _log_prompt(
                'haiku_combined_31',
                'Stage 3.1',
                ctx.pipeline_id,
                _hk31_raw,
                meta={'pipeline_type': 'scholarly', 'topic': ctx.topic, 'sentence_count': len(_sentences_31)},
                direction='received',
                role='assistant',
                llm=_LLM_SMALL,
                from_who=_LLM_SMALL,
                to_who='system',
            )
            _hk31_clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', _hk31_raw, flags=re.DOTALL).strip()
            _hk31_parsed = _json_31.loads(_hk31_clean)
            # Turning points
            _tp_list = _hk31_parsed.get('turning_points', [])
            if isinstance(_tp_list, list):
                ctx._haiku_turning_points = _tp_list
            # Emotion scores
            _emo_list = _hk31_parsed.get('emotions', [])
            _valid_emotions = {'shock', 'grief', 'triumph', 'tension', 'awe', 'mystery', 'unease', 'calm'}
            ctx._haiku_emotion_scores = {
                int(item['i']): (str(item['e']), float(item['v']))
                for item in _emo_list
                if isinstance(item, dict)
                and str(item.get('e', '')) in _valid_emotions
                and isinstance(item.get('v'), (int, float))
            }
            ctx._log(
                'INFO',
                'Stage 3.1',
                f'Haiku combined call: {len(ctx._haiku_turning_points)} turning points, '
                f'{len(ctx._haiku_emotion_scores)}/{len(_sentences_31)} emotions scored',
            )
    except Exception as _hk31_e:
        ctx._log('WARNING', 'Stage 3.1', f'Haiku combined call failed (non-fatal, Ollama fallback): {_hk31_e}')


def stage_07_emotion_curve(ctx):
    # ── Stage 3.1: Emotion Curve Extraction (Murch hierarchy) ─────────
    # Cascading scorer (keyword → embedding → LLM), Gaussian smoothing,
    # arc turning point detection — all via murch_engine.
    #
    # Pre-load the emotion LLM in Ollama only when Haiku pre-scoring is
    # unavailable. When Haiku scored all sentences the Ollama tier is skipped
    # entirely, so there is no point loading anything.
    #
    # This used to warm 'qwen2.5:72b' while murch_engine's LLM tier called
    # MURCH_LLM_MODEL (qwen3.5:9b) — so on the one path where it mattered it
    # pulled 47 GB into VRAM and then scored with a different model that had
    # to load anyway. Warm what the engine will actually call.
    _qwen_model = _MURCH_MODEL
    if not ctx._haiku_emotion_scores:
        try:
            import json as _json_qwen

            if not ctx._ollama_model_loaded(_qwen_model):
                ctx._log('INFO', 'Stage 3.1', f'Loading {_qwen_model} in Ollama for emotion LLM tier…')
                _qwen_req_body = _json_qwen.dumps(
                    {
                        'model': _qwen_model,
                        'prompt': 'ready',
                        'stream': False,
                        'keep_alive': '10m',
                    }
                ).encode()
                # Run load in daemon thread so stop-flag can interrupt the 3-min wait
                import threading as _thr_qwen

                _qwen_load_done = _thr_qwen.Event()
                _qwen_load_err = [None]

                def _do_qwen_load():
                    try:
                        safe_urlopen(_OLLAMA_BASE_URL + '/api/generate', data=_qwen_req_body, timeout=180)
                    except Exception as _e:
                        _qwen_load_err[0] = _e
                    finally:
                        _qwen_load_done.set()

                _thr_qwen.Thread(target=_do_qwen_load, daemon=True).start()
                # Poll every second so stop_flag is checked promptly
                while not _qwen_load_done.wait(timeout=1.0):
                    if gui_state._pipeline_stop_flag or (
                        ctx._stop_event_scholarly and ctx._stop_event_scholarly.is_set()
                    ):
                        ctx._log(
                            'INFO', 'Stage 3.1', f'Stop requested during {_qwen_model} load — evicting and aborting'
                        )
                        # Evict qwen synchronously — it may have partially loaded into VRAM
                        try:
                            import json as _json_ev_q

                            _evq = _json_ev_q.dumps(
                                {'model': _qwen_model, 'prompt': ' ', 'keep_alive': 0, 'stream': False}
                            ).encode()
                            safe_urlopen(_OLLAMA_BASE_URL + '/api/generate', data=_evq, timeout=30)
                        except Exception as _exc:  # noqa: BLE001 — urllib, socket and Ollama's own errors
                            _zyg_log.warning(
                                'qwen not evicted on stop, it holds its VRAM until the daemon times it out: %s', _exc
                            )
                        raise StopIteration('user_stop')
                if _qwen_load_err[0]:
                    raise _qwen_load_err[0]
                ctx._log('INFO', 'Stage 3.1', f'{_qwen_model} loaded — LLM emotion tier active')
            else:
                ctx._log('INFO', 'Stage 3.1', f'{_qwen_model} already resident in Ollama')
        except StopIteration:
            raise
        except Exception as _qwen_load_e:
            ctx._log('WARNING', 'Stage 3.1', f'{_qwen_model} load failed (emotion tier will degrade): {_qwen_load_e}')
    else:
        ctx._log('INFO', 'Stage 3.1', f'Haiku emotion scores available — skipping {_qwen_model} load')

    ctx.job['current_stage'] = 'Stage 3.1: Emotion Analysis'
    ctx._stage_start('Stage 3.1: Emotion Analysis')
    ctx._log('INFO', 'Stage 3.1', 'Extracting emotional arc — cascading scorer + arc analysis')
    ctx._debug(
        'Stage 3.1', f'Narration length: {len(ctx.narration_script)} chars, {len(ctx.narration_script.split())} words'
    )

    _emotion_curve = []
    _murch_turning_points = []
    _murch_debug_log = []

    try:
        from zyg_workflows import murch_engine as _me

        _ollama_url = _OLLAMA_BASE_URL

        # ── Layer 1a: Cascading emotion score ─────────────────────────
        _raw_curve = _me.extract_emotion_curve(
            ctx.narration_script,
            ollama_url=_ollama_url,
            use_embeddings=True,
            debug_log=_murch_debug_log,
            haiku_emotion_scores=ctx._haiku_emotion_scores,
        )
        ctx._debug('Stage 3.1', f'Raw curve: {len(_raw_curve)} pts | tier usage: {set(e["tier"] for e in _raw_curve)}')

        # ── Layer 1b: Gaussian smoothing + arc turning points ──────────
        _emotion_curve = _me.smooth_emotion_curve(_raw_curve, sigma=2.5, debug_log=_murch_debug_log)
        _murch_turning_points = _me.detect_arc_turning_points(
            ctx.narration_script,
            _emotion_curve,
            ollama_url=_ollama_url,
            debug_log=_murch_debug_log,
            pipeline_id=ctx.pipeline_id,
            haiku_turning_points=ctx._haiku_turning_points if ctx._haiku_turning_points else None,
        )

        _peak = max(_emotion_curve, key=lambda x: x['intensity']) if _emotion_curve else {}
        _calm_count = sum(1 for e in _emotion_curve if e['intensity'] < 0.45)
        _tense_count = sum(1 for e in _emotion_curve if e['intensity'] >= 0.65)
        ctx._log(
            'INFO',
            'Stage 3.1',
            f'Emotion curve: {len(_emotion_curve)} pts | '
            f'peak={_peak.get("emotion", "?")}({_peak.get("intensity", 0):.2f}) | '
            f'turning_pts={len(_murch_turning_points)}',
        )
        ctx._debug(
            'Stage 3.1',
            f'Distribution — calm: {_calm_count}, medium: {len(_emotion_curve) - _calm_count - _tense_count}, intense: {_tense_count}',
        )
        ctx._debug('Stage 3.1', f'Turning points: {_murch_turning_points}')
        # Forward all murch engine debug events to the pipeline debug log
        for _mde in _murch_debug_log:
            ctx._debug(f'3.1/murch/{_mde["fn"]}', _mde['msg'], level=_mde.get('level', 'DEBUG'))

    except Exception as _ece:
        ctx._log('WARNING', 'Stage 3.1', f'Murch emotion engine failed: {_ece} — using flat curve')
        ctx._debug('Stage 3.1', f'Exception: {traceback.format_exc()}', level='ERROR')

    ctx.pipeline_state['emotion_curve'] = _emotion_curve
    ctx.pipeline_state['turning_points'] = _murch_turning_points
    ctx.pipeline_state['murch_debug_events'] = _murch_debug_log

    # ── Scholarly emotion dampening ────────────────────────────────────────
    # Academic language about crises/contamination/collapse scores high on
    # 'shock', which forces hard smash cuts (calm→shock = cut in the table).
    # For non-crime/war departments, remap low-intensity shock to 'unease' so
    # transitions stay smooth (calm→unease = dissolve 1.0s).
    # INTENSITY DIAL: at high/extreme this pass is skipped outright. It runs
    # BEFORE the prompt writer ever sees the curve, so leaving it on quietly
    # de-fanged the whole episode — every 'shock' beat under 0.75 became
    # 'unease' and the batch writer was handed a curve with no peaks in it.
    # The transition table it was protecting (calm→shock = hard cut) is the
    # behaviour we now want, not the one to avoid.
    _sch_dept = ctx.pipeline_state.get('department', 'general').lower()
    if ctx._sch_intensity['enabled']:
        ctx._debug(
            'Stage 3.1',
            f'Emotion dampening SKIPPED — image_intensity={ctx._sch_intensity["level"]} (shock beats kept intact)',
        )
    elif _sch_dept not in ('crime', 'war', 'disaster'):
        _remapped_shock = 0
        for _ec_pt in _emotion_curve:
            if _ec_pt.get('emotion') == 'shock' and _ec_pt.get('intensity', 0.0) <= 0.75:
                _ec_pt['emotion'] = 'unease'
                _remapped_shock += 1
        if _remapped_shock:
            ctx._debug(
                'Stage 3.1',
                f'Scholarly emotion dampening: {_remapped_shock} low-intensity shock→unease (dept={_sch_dept})',
            )

    # ── Backfill arc zone into visual_tags now that emotion_curve exists ──
    # visual_tags were built in Stage 3b before emotion_curve was available;
    # add arc zone per tag slot so FLUX prompt builder and xfade engine have
    # richer data even if _batch_generate_flux_prompts fails.
    _vt_list = ctx.pipeline_state.get('visual_tags', [])
    _n_vt = len(_vt_list)
    if _vt_list and _emotion_curve:
        try:
            from zyg_workflows import murch_engine as _me_arc

            _tp_for_arc = _murch_turning_points
            for _vti, _vt in enumerate(_vt_list):
                _frac = _vti / max(_n_vt - 1, 1)
                try:
                    _az = _me_arc.get_arc_zone(_vti, _tp_for_arc, _n_vt) if _tp_for_arc else None
                except Exception:
                    _az = None
                if not _az:
                    _az = (
                        'exposition'
                        if _frac < 0.15
                        else 'rising'
                        if _frac < 0.45
                        else 'climax'
                        if _frac < 0.65
                        else 'falling'
                        if _frac < 0.85
                        else 'resolution'
                    )
                _ec_idx = min(int(_vti * len(_emotion_curve) / max(_n_vt, 1)), len(_emotion_curve) - 1)
                _vt['arc'] = _az
                _vt['emotion'] = _emotion_curve[_ec_idx].get('emotion', 'calm')
                _vt['intensity'] = round(_emotion_curve[_ec_idx].get('intensity', 0.2), 2)
            ctx.pipeline_state['visual_tags'] = _vt_list
            ctx._debug('Stage 3.1', f'Arc backfill: {_n_vt} visual_tags enriched with arc/emotion/intensity')
        except Exception as _arc_err:
            ctx._debug('Stage 3.1', f'Arc backfill failed: {_arc_err}', level='WARNING')

    ctx._save()
    ctx._done(
        'Stage 3.1: Emotion Analysis',
        {
            'points': len(_emotion_curve),
            'turning_points': len(_murch_turning_points),
            'tiers_used': list(set(e.get('tier', '?') for e in _emotion_curve)),
        },
    )
