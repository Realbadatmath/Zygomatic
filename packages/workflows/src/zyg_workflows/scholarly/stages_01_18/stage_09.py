# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.5a of the scholarly pipeline: time-locked scene descriptions."""

from ._common import (
    _LLM_LARGE,
    _bench_replay_get,
    _llm_client,
    _llm_key,
    _record_token_usage,
    _scholarly_n_images,
)


def stage_09_time_locked_scene_descriptions(ctx):
    # ── Stage 3.5a: Time-Locked Scene Descriptions ────────────────────────
    # Word timings now exist. Generate one scene description per image slot
    # locked to the exact words spoken in that time window — so the image
    # on screen always reflects what the narrator is saying at that moment.
    ctx._stage_start('Stage 3.5a: Time-Locked Scenes')
    # One picture = one LTX-2.5 clip since 2026-10-02, so the count is no longer
    # a hardcoded 1-per-20s with a 10-picture floor — it is however many
    # clip-length slots the narration actually needs. scholarly_motion owns the
    # rule so this site and Stage 3.5's cannot drift apart.
    _tls_n = _scholarly_n_images(ctx.tts_duration)
    # The slot count is what every later prompt is phrased around ("a 51-image
    # slideshow"). A record run derives it from the ESTIMATED narration length and banks
    # it; a replay derives a real one from real audio, so without this the replayed
    # prompt would differ from the recorded one by a slot and miss its hash. The slots
    # are still spread over the replay's real duration — only how many there are is fixed.
    if ctx._preempt_mode == 'replay':
        _banked_slots = 0
        try:
            _banked_slots = int((ctx._preempt_state or {}).get('preempt_n_slots') or 0)
        except (TypeError, ValueError):
            _banked_slots = 0
        if _banked_slots >= 10:
            ctx._log(
                'INFO',
                'Stage 3.5a',
                f'[preempt] slot count {_banked_slots} taken from the bank '
                f"(this run's audio would have given {_tls_n})",
            )
            _tls_n = _banked_slots
    elif ctx._preempt_mode == 'record':
        ctx.pipeline_state['preempt_n_slots'] = _tls_n
    _tls_ok = False
    try:
        _anthropic_key_tls = _llm_key()
        _rep_tls = _bench_replay_get('stage_3_5a_scene_list')
        if _rep_tls:
            _tls_pool = _rep_tls or []
            ctx.pipeline_state['_stage3_scene_list'] = (
                [_tls_pool[i % len(_tls_pool)] for i in range(_tls_n)]
                if _tls_pool
                else ctx.pipeline_state.get('_stage3_scene_list', [])
            )
            _tls_ok = True
            ctx._log('INFO', 'Stage 3.5a', f'[bench_replay] {_tls_n} time-locked scenes from cache')
        elif ctx._final_word_timings and _anthropic_key_tls:
            import re as _re_tls

            _tls_client = _llm_client(_anthropic_key_tls)
            _tls_slot_dur = ctx.tts_duration / _tls_n

            # Build word-index → sentence-emotion lookup from already-computed curve
            _tls_emo_curve = ctx.pipeline_state.get('emotion_curve', [])
            _tls_turn_pts = ctx.pipeline_state.get('turning_points', [])
            _tls_total_words = len(ctx._final_word_timings)
            _tls_n_sents = len(_tls_emo_curve)
            # Map each word index to its sentence's emotion/intensity
            _tls_word_emo = []
            if _tls_emo_curve and _tls_total_words:
                for _wi in range(_tls_total_words):
                    _si = min(int(_wi * _tls_n_sents / _tls_total_words), _tls_n_sents - 1)
                    _ep = _tls_emo_curve[_si]
                    _tls_word_emo.append((_ep.get('emotion', 'calm'), _ep.get('intensity', 0.5)))
            # Build turning-point sentence-index set
            _tls_tp_sent_idxs = {tp['sentence_idx'] for tp in _tls_turn_pts}

            _tls_items = []
            for _tls_i in range(_tls_n):
                _t0 = _tls_i * _tls_slot_dur
                _t1 = _t0 + _tls_slot_dur
                _slot_words = [w for w, t in ctx._final_word_timings if _t0 <= t < _t1]
                _slot_text = ' '.join(_slot_words) if _slot_words else f'documentary section {_tls_i + 1}'

                # Dominant emotion for this slot
                _slot_word_idxs = [wi for wi, (_, wt) in enumerate(ctx._final_word_timings) if _t0 <= wt < _t1]
                if _slot_word_idxs and _tls_word_emo:
                    _slot_emos = [_tls_word_emo[wi][0] for wi in _slot_word_idxs if wi < len(_tls_word_emo)]
                    _slot_intens = [_tls_word_emo[wi][1] for wi in _slot_word_idxs if wi < len(_tls_word_emo)]
                    _dom_emo = max(set(_slot_emos), key=_slot_emos.count) if _slot_emos else 'calm'
                    _avg_inten = round(sum(_slot_intens) / len(_slot_intens), 2) if _slot_intens else 0.5
                    # Check if any turning-point sentence falls in this slot's word range
                    _slot_sent_idxs = {
                        min(int(wi * _tls_n_sents / _tls_total_words), _tls_n_sents - 1)
                        for wi in _slot_word_idxs
                        if _tls_total_words
                    }
                    _is_tp = bool(_slot_sent_idxs & _tls_tp_sent_idxs)
                    _tone_tag = f'[TONE:{_dom_emo}·{_avg_inten}{"·TURNING_POINT" if _is_tp else ""}]'
                else:
                    _tone_tag = ''

                _tls_items.append(f'{_tls_i + 1}. [{_t0:.0f}s–{_t1:.0f}s] {_tone_tag} "{_slot_text[:150]}"')

            # INTENSITY DIAL: scene descriptions are the seed the batch
            # prompt writer enriches, so a scene born calm stays calm no
            # matter how hard Stage 3.5 pushes afterwards. Make them born
            # arresting instead, and give slot 1 its own hook instruction.
            _tls_intensity_rules = ''
            if ctx._sch_intensity['enabled']:
                _tls_intensity_rules = (
                    '- INTENSITY: this documentary is cut for maximum impact. For each '
                    'segment choose the most ARRESTING moment its words support — get '
                    'close to a face, a hand, a body under strain; find the moment of '
                    'danger, exhaustion, defiance or awe; use scale, fire, smoke, '
                    'darkness, weather and ruin. Never the safe scholarly object (a '
                    'scroll, a coin, an empty room) when a human moment is available in '
                    'those words\n'
                    '- Intensity here means dramatic force, NOT shock value. Do not reach '
                    'for gratuitous gore. Reach for the image a viewer cannot look away '
                    'from. Hardship, injury and death belong in a scene only when the '
                    'words themselves are about them\n'
                    '- Do not soften a violent or tragic beat into its aftermath or its '
                    'symbol. Describe the moment itself\n'
                )
                if ctx._sch_intensity['hook_rank'] >= 2:
                    _tls_intensity_rules += (
                        '- SLOT 1 IS THE HOOK — it is the first frame a viewer ever sees and '
                        'it decides whether they watch. It must be the single most arresting '
                        'image this episode can justify: close, direct and impossible to '
                        'scroll past — a face filling the frame, a body mid-action, a moment '
                        'of danger or ruin. Nothing establishing or scene-setting about it. '
                        'Write it that way even if the narration at that moment is calm — '
                        'pull the imagery forward from whatever the episode is truly about\n'
                    )

            _tls_prompt = (
                f'You are the visual director for a documentary about: "{ctx.topic}".\n\n'
                f'Below are {_tls_n} narration segments with their timestamps.\n'
                f'For each segment write ONE specific 15–20 word visual scene description '
                f'of exactly what should appear on screen while those words are spoken.\n\n'
                f'Rules:\n'
                f"- Match the visual to the CONTENT of that specific segment's words\n"
                f'- Name the specific person, object, or event being described in those words\n'
                f'- Cinematic present tense (e.g. "Achilles charges across the battlefield")\n'
                f'- No generic atmosphere unless the words themselves are purely atmospheric\n'
                f'- Use the TONE tag to set visual mood through framing, lighting, and camera distance —\n'
                + (
                    "  grief→tight close-up on the mourner's face; shock→the impact itself in "
                    'close, not the reveal; triumph→low upward angle, hard bright light; '
                    'unease→claustrophobic frame; awe→crushing scale against a single figure; '
                    'calm→charged stillness with something at stake in frame; '
                    'TURNING_POINT→bold, abrupt visual shift\n'
                    if ctx._sch_intensity['enabled']
                    else '  grief→tight close-ups, low light; shock→wide sudden reveal; triumph→upward angle, bright;\n'
                    '  unease→claustrophobic frame; awe→vast scale; calm→wide neutral; TURNING_POINT→bold visual shift\n'
                )
                + _tls_intensity_rules
                + '- Output a numbered list only — one line per slot, no explanations\n\n'
                + '\n'.join(_tls_items)
            )
            _tls_resp = _tls_client.messages.create(
                model=_LLM_LARGE,
                max_tokens=_tls_n * 50,
                temperature=0.5,
                messages=[{'role': 'user', 'content': _tls_prompt}],
            )
            _tls_raw = _tls_resp.content[0].text.strip()
            _tls_parsed = _re_tls.findall(r'^\d+\.\s+(.+)$', _tls_raw, _re_tls.MULTILINE)
            if len(_tls_parsed) >= max(5, _tls_n // 2):
                ctx.pipeline_state['_stage3_scene_list'] = [s.strip() for s in _tls_parsed[:_tls_n]]
                _tls_ok = True
                ctx._log(
                    'INFO',
                    'Stage 3.5a',
                    f'Time-locked: {len(_tls_parsed)} scene descriptions anchored to word timings',
                )
                _record_token_usage(
                    model=_LLM_LARGE,
                    prompt_tokens=_tls_resp.usage.input_tokens,
                    completion_tokens=_tls_resp.usage.output_tokens,
                    pipeline_id=ctx.pipeline_id,
                    stage='Stage 3.5a',
                    pipeline_type='scholarly',
                )
            else:
                ctx._log(
                    'WARNING',
                    'Stage 3.5a',
                    f'Only {len(_tls_parsed)}/{_tls_n} descriptions returned — keeping Stage 3 scenes',
                )
        elif not ctx._final_word_timings:
            ctx._log('WARNING', 'Stage 3.5a', 'No word timings available — keeping Stage 3 scenes')
    except Exception as _tls_e:
        ctx._log('WARNING', 'Stage 3.5a', f'Time-locked scene generation failed (non-fatal): {_tls_e}')

    ctx.pipeline_state['_tls_n_images'] = _tls_n
    ctx._save()
    ctx._done(
        'Stage 3.5a: Time-Locked Scenes',
        {
            'n': _tls_n,
            'locked': _tls_ok,
            'source': 'word_timing' if _tls_ok else 'stage3_fallback',
        },
    )

    ctx._stage_start('Stage 3.5: AI Image Generation')
