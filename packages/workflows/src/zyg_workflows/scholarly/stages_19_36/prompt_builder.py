# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Stage 3.5 prompt builder, lifted out of `stage_10_flux_image_generation`.

The `_make_*` wrapper re-creates the closure the nested `def` used to get from
its stage function, binding the twenty-three stage locals into one
`PromptSlotContext`; the slot assembly itself is the helpers of
`prompt_builder_parts`, called here in the order the single file ran them.
"""

from . import prompt_builder_parts as parts


def _make_build_image_prompt(
    _ARC_STYLE_MAP,
    _EMOTION_RELIEF_SLOTS,
    _SHOT_ROTATION,
    _STYLE_SUFFIXES,
    _debug,
    _era_variants,
    _extract_named_entities,
    _is_hook_slot,
    _is_modern_topic,
    _log,
    _recent_emotions,
    _recent_shot_sizes,
    _recent_shot_types,
    _sch_intensity,
    _sentence_event_tag,
    _shot_size_of,
    _slot_word_bounds,
    _tag_sentence,
    _used_entities,
    ctx,
    narration_script,
    pipeline_id,
    pipeline_state,
):
    """Build `_build_image_prompt` over the twenty-three stage locals it closed over."""
    pb = parts.PromptSlotContext(
        arc_style_map=_ARC_STYLE_MAP,
        emotion_relief_slots=_EMOTION_RELIEF_SLOTS,
        shot_rotation=_SHOT_ROTATION,
        style_suffixes=_STYLE_SUFFIXES,
        debug=_debug,
        era_variants=_era_variants,
        extract_named_entities=_extract_named_entities,
        is_hook_slot=_is_hook_slot,
        is_modern_topic=_is_modern_topic,
        log=_log,
        recent_emotions=_recent_emotions,
        recent_shot_sizes=_recent_shot_sizes,
        recent_shot_types=_recent_shot_types,
        sch_intensity=_sch_intensity,
        sentence_event_tag=_sentence_event_tag,
        shot_size_of=_shot_size_of,
        slot_word_bounds=_slot_word_bounds,
        tag_sentence=_tag_sentence,
        used_entities=_used_entities,
        ctx=ctx,
        narration_script=narration_script,
        pipeline_id=pipeline_id,
        pipeline_state=pipeline_state,
    )

    def _build_image_prompt(
        idx: int,
        n_total: int,
        sentences: list,
        fallback_subject: str,
        prev_prompt: str = '',
        emotion_curve: list = None,
        # murch_engine extras
        turning_points: list = None,
        prev_focal_zone: str = None,
        scene_weights: dict = None,
        murch_debug: list = None,
    ) -> tuple:
        """
        Build a FLUX prompt for image slot `idx` using the full Murch engine:
          Layer 2a: Scene type weights per arc zone
          Layer 2b: Shot grammar with arc awareness
          Layer 2c: Counterpoint mode at turning points
          Layer 2d: Named entity seed anchoring
          Layer 3b: Composition constraints from previous focal zone

        Returns (prompt_str, subject_str, tag_str, narration_segment_str,
                 shot_type_str, emotion_str, seed_override, counterpoint_used,
                 subject_is_entity).
        subject_is_entity (9th element, 2026-08-25) is True only when the
        subject came from a real named entity in the slot text — False when
        it fell back to the essay title — so the seed registry never locks
        a seed on the topic (P-09).
        """
        if murch_debug is None:
            murch_debug = []
        if turning_points is None:
            turning_points = []
        if scene_weights is None:
            scene_weights = dict(parts.DEFAULT_SCENE_WEIGHTS)

        seg = parts.slot_segment(pb.slot_word_bounds, pb.narration_script, idx, n_total, sentences)
        n_sents = len(sentences)
        emotion, intensity = parts.slot_emotion(emotion_curve, seg, n_sents)
        arc_zone = parts.slot_arc_zone(seg, turning_points, n_sents)
        emotion, intensity = parts.enforce_emotion_diversity(
            pb.recent_emotions, pb.emotion_relief_slots, emotion, intensity, arc_zone
        )
        subject, subject_is_entity = parts.slot_subject(
            pb.extract_named_entities, pb.used_entities, seg.text, fallback_subject
        )
        seed_override = parts.entity_seed(subject, pb.pipeline_id) if subject_is_entity else None
        event_tag = parts.slot_event_tag(pb.sentence_event_tag, pb.tag_sentence, seg.sentences)
        # Positive-phrased anatomy descriptor for this tag, appended only when the
        # event tag explicitly signals human subjects (tag lookup built in Stage
        # 3b; empty for non-person tags). No keyword-based fallback — re-classifying
        # scene text put anatomy boilerplate on pure landscape/object shots.
        anatomy_hint = pb.pipeline_state.get('anatomy_hints_by_tag', {}).get(event_tag, '')
        weights = parts.scene_weight_profile(seg.text, scene_weights, murch_debug)

        # Image 0 is the cold open: its own style row and its own shot grammar.
        # The style row keys off the hook zone rather than the arc zone so the arc
        # itself (emotion, counterpoint, composition) stays honest.
        hook_slot = pb.is_hook_slot(idx)
        style_zone = 'hook' if hook_slot else arc_zone
        if hook_slot:
            intensity = max(intensity, 0.95)

        shot_type = parts.slot_shot_type(
            idx,
            emotion,
            intensity,
            arc_zone,
            weights,
            subject,
            prev_prompt,
            murch_debug,
            hook_slot=hook_slot,
            exposition_alternate=pb.sch_intensity['enabled'],
        )
        shot_type = parts.enforce_shot_diversity(
            pb.recent_shot_sizes,
            pb.recent_shot_types,
            pb.shot_rotation,
            pb.shot_size_of,
            shot_type,
            arc_zone,
            flat_half=pb.sch_intensity['enabled'],
        )
        composition = parts.composition_constraint(prev_focal_zone, emotion, arc_zone, murch_debug)
        kuleshov = parts.kuleshov_modifier(prev_prompt, intensity)
        # Elements 4-7 of the 9-tuple, the same whichever path writes the prompt.
        tail = (seg.text[:200], shot_type, emotion, seed_override)

        cp_prompt = parts.counterpoint_prompt(
            pb,
            idx,
            seg,
            emotion=emotion,
            intensity=intensity,
            arc_zone=arc_zone,
            style_zone=style_zone,
            subject=subject,
            shot_type=shot_type,
            turning_points=turning_points,
            murch_debug=murch_debug,
            composition=composition,
            anatomy_hint=anatomy_hint,
            hook_slot=hook_slot,
        )
        if cp_prompt is not None:
            return (cp_prompt, subject, event_tag, *tail, True, subject_is_entity)

        suffix = parts.intensity_suffix(pb.sch_intensity, hook_slot=hook_slot)
        era_suffix = ', ' + pb.era_variants[idx % len(pb.era_variants)]
        # ERA ANCHOR ON THE LIVE PATH (2026-08-25). The rotating per-episode
        # anchor line was appended only on the fallback (no-Claude) path; the
        # prebuilt path — which is what production renders — never carried it.
        # (The short CLIP-front anchor is added in _generate_one, where the
        # render prompt is final.)
        pre = parts.prebuilt_prompt(
            pb.ctx._prebuilt_prompts,
            idx,
            quality_footer=parts.QUALITY_FOOTER_QWEN if pb.ctx._sch_qwen_stills else parts.QUALITY_FOOTER,
            suffix=suffix,
            era_suffix='' if pb.is_modern_topic else era_suffix,
            anatomy_hint=anatomy_hint,
        )
        if pre is not None:
            return (pre, subject, event_tag, *tail, False, subject_is_entity)

        prompt = parts.assemble_fallback_prompt(
            parts.fallback_scene_desc(pb.pipeline_state, seg.start, subject),
            shot_type,
            mood=parts.emotion_mood(emotion, intensity, intense=pb.sch_intensity['enabled'], hook_slot=hook_slot),
            style=parts.style_suffix(pb.arc_style_map, pb.style_suffixes, style_zone, idx),
            kuleshov=kuleshov,
            era_suffix=era_suffix,
            suffix=suffix,
            composition=composition,
            anatomy_hint=anatomy_hint,
        )
        return (prompt, subject, event_tag, *tail, False, subject_is_entity)

    return _build_image_prompt
