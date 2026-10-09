# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 1 of the storyteller pipeline — character prep.

Verifies the character dataset, resolves the LoRA and its trigger token,
reconciles the client-supplied ``character_params`` against the server-side
character bible, and picks the TTS voice. Cut verbatim out of
``pipeline_storyteller._run_storyteller_pipeline`` (lines 534-914 of commit
770c30a); see ``SPLIT_LOG.md``.

2026-10-09: the 391-line stage was itself over the 300-line function cap, so its
seven blocks became the step functions of
:mod:`stage_01_character_prep_steps`; what is left here is the order they run
in and the context fields they produce."""

from zyg_workflows.storyteller.stage_01_character_prep_steps import (
    load_character_bible,
    pick_reference_image,
    reconcile_character_params,
    record_clean_extra_prompt,
    resolve_dataset_provenance,
    resolve_lora,
    select_voices,
)


def stage_01_character_prep(ctx):
    """Stage 1 — character prep: LoRA, bible, identity reference and voices.

    Writes ``lora_path``, ``trigger_token``, ``character_bible``,
    ``_st_extra_prompt_clean``, ``storyteller_blender_dataset``,
    ``char_reference_image`` and the two voices into ``pipeline_state``, and
    hands the next stages ``ctx.lora_path``, ``ctx.trigger_token``, the
    reconciled ``ctx.character_params`` and ``ctx._effective_tts_voice``."""
    # ── Stage 1: Character Prep ───────────────────────────────────────────────
    ctx._update_stage('Stage 1 — Character Prep', 2)
    ctx._check_stop()

    # Resolve LoRA and trigger token
    lora_path, trigger_token = resolve_lora(ctx)
    # Character bible — continuity package for Comfy + drift QA
    lora_path = load_character_bible(ctx, lora_path)
    character_params = reconcile_character_params(ctx, ctx.character_params)
    record_clean_extra_prompt(ctx, character_params)
    _st_char_info = resolve_dataset_provenance(ctx, character_params)
    pick_reference_image(ctx, _st_char_info, character_params)
    ctx._log(
        'INFO',
        'Stage 1',
        f'Character prep complete — LoRA: {"✓" if lora_path else "⚠ fallback"} trigger: {trigger_token or "(none)"}',
    )

    # ── Voice selection ───────────────────────────────────────────────────
    narrator_voice, character_voice, _effective_tts_voice = select_voices(ctx, character_params)
    ctx.pipeline_state['narrator_voice'] = narrator_voice
    ctx.pipeline_state['character_voice'] = character_voice

    ctx._save()
    ctx._check_stop()

    ctx._effective_tts_voice = _effective_tts_voice
    ctx.character_params = character_params
    ctx.lora_path = lora_path
    ctx.trigger_token = trigger_token
