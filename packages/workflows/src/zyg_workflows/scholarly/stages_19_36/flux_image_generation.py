# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.5 — FLUX/Qwen still generation (`stage_10_flux_image_generation`)."""

from ._common import (
    _ensure_comfy_offload_env,
    _update_marker,
    os,
    paths,
)

from .flux_image_generation_setup import (
    ARC_STYLE_MAP_HISTORICAL,
    ARC_STYLE_MAP_MODERN,
    DEFAULT_FLUX_PROMPT,
    EMOTION_RELIEF_SLOTS,
    FLUX_PROMPT_TEMPLATES,
    SHOT_ROTATION,
    STYLE_SUFFIXES,
    build_fallback_subject,
    build_flux_negative,
    log_generation_estimate,
    prepare_character_bible,
    resolve_era_lock,
    resolve_image_count,
    resolve_still_family_label,
    split_narration_sentences,
)
from .prompt_builder import _make_build_image_prompt
from .prompt_helpers import (
    _make_extract_named_entities,
    _make_get_claude_scene_description,
    _make_is_hook_slot,
    _make_sentence_event_tag,
    _make_shot_size_of,
    _make_slot_word_bounds,
)


def stage_10_flux_image_generation(ctx):
    _debug = ctx._debug
    _log = ctx._log
    _pipeline_marker = ctx._pipeline_marker
    _sch_char_id = ctx._sch_char_id
    _sch_duration_targets = ctx._sch_duration_targets
    _sch_intensity = ctx._sch_intensity
    _tag_sentence = ctx._tag_sentence
    job = ctx.job
    narration_script = ctx.narration_script
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    # ── Stage 3.5: FLUX Image Generation ──────────────────────────────
    job['current_stage'] = 'Stage 3.5: AI Image Generation'
    _update_marker(_pipeline_marker, label=f'🔄 Scholarly {pipeline_id[:8]} — Generating Images')
    _sch_family_early, _sch_family_label = resolve_still_family_label()
    _log('INFO', 'Stage 3.5', f'Generating documentary images with {_sch_family_label}')
    _ensure_comfy_offload_env()

    prepare_character_bible(pipeline_state, _sch_char_id, _log)

    _flux_model_path = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
    _flux_images_dir = os.path.join(out_dir, 'flux_images')
    os.makedirs(_flux_images_dir, exist_ok=True)

    _count_plan = resolve_image_count(pipeline_state, _sch_duration_targets, _log)
    _word_count_est = _count_plan.word_count_est
    _n_flux_images = _count_plan.n_flux_images
    log_generation_estimate(pipeline_state, _count_plan, _sch_family_early, _sch_family_label, _log)

    _FLUX_PROMPT_TEMPLATES = FLUX_PROMPT_TEMPLATES
    _DEFAULT_FLUX_PROMPT = DEFAULT_FLUX_PROMPT
    _FLUX_NEGATIVE = build_flux_negative(_sch_intensity)

    # ── EPISODE ERA LOCK ─────────────────────────────────────────────────
    _era_lock, _is_modern_topic, _era_variants = resolve_era_lock(ctx, _log, _debug)

    _STYLE_SUFFIXES = STYLE_SUFFIXES
    _ARC_STYLE_MAP = ARC_STYLE_MAP_MODERN if _is_modern_topic else ARC_STYLE_MAP_HISTORICAL

    # A slot is the HOOK when it is image 0 and the dial is up. Everything
    # downstream (shot grammar, style row, counterpoint, prompt directive)
    # keys off this one predicate so the definition never drifts.
    _is_hook_slot = _make_is_hook_slot(_sch_intensity)

    import re as _re_flux_sub

    _extract_named_entities = _make_extract_named_entities(_re_flux_sub)

    _sentence_event_tag = _make_sentence_event_tag()

    _get_claude_scene_description = _make_get_claude_scene_description(_is_modern_topic, pipeline_id, topic)

    # Entity dedup: list of recently used entity strings (last 3 suppressed)
    _used_entities: list = []
    # Scene diversity: rolling list of last 5 Claude scene descriptions (shown to Claude to prevent repeats)
    _recent_scene_descs: list = []
    # Shot diversity enforcer: track recent shot types, prevent >2 consecutive identical shots
    _recent_shot_types: list = []
    _recent_shot_sizes: list = []

    _shot_size_of = _make_shot_size_of()

    # Emotion diversity enforcer: inject a calm/mystery beat every 6 slots to prevent monotony
    _recent_emotions: list = []

    # ── Audio-time slot windows ─────────────────────────────────────────
    # Narration plays at near-constant rate but sentence LENGTH varies, so
    # slicing the script by sentence index drifts minutes off the audio by
    # mid-video (toothbrush run: DuPont-lab image during the Dōgen beat).
    # Slot i's text must be the words actually spoken during its display
    # window [i*T/n, (i+1)*T/n) — from whisper word timings when available,
    # else by equal word count (constant speech rate approximation).
    _slot_word_bounds = _make_slot_word_bounds(narration_script, pipeline_state)

    _build_image_prompt = _make_build_image_prompt(
        _ARC_STYLE_MAP,
        EMOTION_RELIEF_SLOTS,
        SHOT_ROTATION,
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
    )

    _essay_title_for_prompt = pipeline_state.get('essay_title', topic)
    _fallback_subject = build_fallback_subject(_essay_title_for_prompt, topic)

    # Sentence list used for time-locking image slots
    _narration_sentences = split_narration_sentences(narration_script)

    ctx._DEFAULT_FLUX_PROMPT = _DEFAULT_FLUX_PROMPT
    ctx._FLUX_NEGATIVE = _FLUX_NEGATIVE
    ctx._FLUX_PROMPT_TEMPLATES = _FLUX_PROMPT_TEMPLATES
    ctx._STYLE_SUFFIXES = _STYLE_SUFFIXES
    ctx._build_image_prompt = _build_image_prompt
    ctx._era_lock = _era_lock
    ctx._essay_title_for_prompt = _essay_title_for_prompt
    ctx._fallback_subject = _fallback_subject
    ctx._flux_images_dir = _flux_images_dir
    ctx._flux_model_path = _flux_model_path
    ctx._is_modern_topic = _is_modern_topic
    ctx._n_flux_images = _n_flux_images
    ctx._narration_sentences = _narration_sentences
    ctx._sch_family_early = _sch_family_early
    ctx._sch_family_label = _sch_family_label
    ctx._slot_word_bounds = _slot_word_bounds
    ctx._word_count_est = _word_count_est
