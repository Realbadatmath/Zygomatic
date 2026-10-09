# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3 of the scholarly pipeline: the script-preparation (editing) pass."""

from ._common import (
    _build_framework_block,
    _classify_subject_type,
    _llm_key,
    _update_marker,
)
from .stage_03_cleaners import _script_cleaners
from .stage_03_llm import _run_claude_script_pass
from .stage_03_prep import (
    _apply_bench_replay,
    _apply_prose_gate,
    _duration_targets,
    _enforce_word_gate,
    _essay_metadata_to_state,
    _fetch_wiki_source_block,
    _finalise_script_state,
    _persist_dsl_scene,
    _register_narration_prompt,
    _reject_disallowed_topic,
    _tidy_narration,
)


def stage_03_script_preparation(ctx):
    # ── Stage 3: Script Preparation (Editing Pass) ─────────────────────────────
    ctx._stage_start('Stage 3: Script Preparation')
    ctx.job['current_stage'] = 'Stage 3: Script Preparation'
    _update_marker(ctx._pipeline_marker, label=f'🔄 Scholarly {ctx.pipeline_id[:8]} — Editing Pass')
    ctx._log('INFO', 'Stage 3', 'Preparing essay text for narration (editing pass)')

    # Get research result metadata, publish it for Stage 5, choose the display title
    _essay_metadata_to_state(ctx)

    # Stage 3: Clean essay text for narration
    # GPT-4o (if GITHUB_TOKEN set) → regex fallback (Ollama bypassed — context too small for long essays)
    _strip_citation_header, _regex_clean, _strip_llm_preamble = _script_cleaners()

    ctx.narration_script = ''
    ctx._stage3_llm_model = None
    _targets = _duration_targets(ctx)

    # ── Hard reject: anatomy/medical topics are not supported ─────────────
    _reject_disallowed_topic(ctx)

    # ── Option 1+3: Subject classifier + 10-section framework block ──────
    ctx._sch_subject_type = _classify_subject_type(ctx.directive or ctx.topic or '', '')
    _sch_framework = _build_framework_block(ctx._sch_subject_type, ctx.directive or ctx.topic or '')

    # ── Wikipedia RAG: fetch verified source material before scripting ────
    _fetch_wiki_source_block(ctx)

    # Register the scholarly narration template (instructions without essay source material)
    _register_narration_prompt(ctx, _targets)

    # ── Benchmark replay: inject cached script instead of calling Claude ──
    _rep_s3 = _apply_bench_replay(ctx)

    # Claude Sonnet (first priority — best quality, handles large essays fine, no VRAM cost)
    ctx._anthropic_key = _llm_key()
    _yt_meta = {}
    if not _rep_s3 and ctx._anthropic_key:
        _yt_meta = _run_claude_script_pass(ctx, _targets, _sch_framework, _strip_llm_preamble)

    if not ctx.narration_script:
        ctx._log('ERROR', 'Stage 3', 'Claude Sonnet failed to produce a narration script — aborting run')
        raise RuntimeError('Stage 3: narration model failed — essay skipped')

    # ── DSL: persist a Scene snapshot for the scholarly script (env-gated) ──
    _persist_dsl_scene(ctx)

    # ── Post-cleaning narrative word count gate ─────────────────────────────
    _enforce_word_gate(ctx, _targets)

    # Short-doc word ceiling, markdown horizontal rules, title-echo sentences
    _tidy_narration(ctx, _targets)

    # ── Publishable-prose gate ──────────────────────────────────────────
    _apply_prose_gate(ctx)

    _finalise_script_state(ctx, _yt_meta)
