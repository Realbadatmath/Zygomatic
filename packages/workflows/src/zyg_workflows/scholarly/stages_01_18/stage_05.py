# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3b of the scholarly pipeline: visual intent tagging."""

import re

from ._common import (
    _bench_replay_get,
    _llm_key,
)
from .stage_05_keywords import (
    _ANATOMY_HINTS_BY_TAG,
    _tag_sentence,
)
from .stage_05_scenes import (
    SceneDescJob,
    _fill_scene_descs,
    _generic_fallback_stats,
    _ollama_model_loaded,
    _prefill_inline_scenes,
)


def stage_05_visual_intent_tagging(ctx):
    # Re-bound as plain locals: the lambda published on the context below
    # closes over them, and a closure cannot capture ctx.<name>.
    _debug = ctx._debug
    pipeline_id = ctx.pipeline_id
    topic = ctx.topic

    # ── Stage 3b: Visual Intent Tagging ───────────────────────────────────
    # Phase 1: instant keyword pass → assigns category tags used for anatomy hints
    # Phase 2: LLM pass (Claude Sonnet → Mistral fallback) → generates a specific
    #           visual scene description per sentence stored as visual_tags[i]['scene_desc']
    # scene_desc is used downstream in _batch_generate_flux_prompts (extra context for Claude)
    # and in the _generate_one_flux_prompt fallback path when the batch call fails.
    ctx.job['current_stage'] = 'Stage 3b: Visual Tagging'
    ctx._log('INFO', 'Stage 3b', 'Tagging sentences with visual intents (keyword rules + LLM scene descriptions)')

    # Both are published for later stages: stages_06_07 probes Ollama through
    # ctx._ollama_model_loaded, stages_19_36.prompt_builder re-tags its own
    # segment sentences through the one-argument ctx._tag_sentence.
    ctx._ollama_model_loaded = _ollama_model_loaded
    ctx._tag_sentence = lambda _s: _tag_sentence(_s, topic)

    _sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', ctx.narration_script) if len(s.strip()) > 20]
    ctx.visual_tags = [{'sentence': s, 'tag': ctx._tag_sentence(s)} for s in _sentences]

    for _vt in ctx.visual_tags:
        _vt['anatomy_hint'] = _ANATOMY_HINTS_BY_TAG.get(_vt['tag'], '')

    ctx.pipeline_state['anatomy_hints_by_tag'] = _ANATOMY_HINTS_BY_TAG
    ctx._save()

    # ── Phase 2: LLM scene description pass ───────────────────────────────
    # Generates a specific, concrete visual scene description for every sentence
    # (e.g. "Roman gladiator in iron helmet practising sword strikes in sand arena"
    # instead of "general related imagery").
    # Stored as visual_tags[i]['scene_desc'].  The keyword tag is preserved for
    # anatomy hint lookups.  Runs Claude Sonnet (one batch per 20 sentences) with
    # Mistral/Ollama as fallback.  If both fail, scene_desc falls back to the
    # keyword tag so nothing downstream breaks.
    _3b_ak = _llm_key()
    _scene_job = SceneDescJob(
        topic=topic,
        pipeline_id=pipeline_id,
        api_key=_3b_ak,
        replay_descs=_bench_replay_get('stage_3b_scene_descs'),  # list or None
        debug=_debug,
    )
    _scene_desc_count = 0

    # Pre-populate from inline scene descriptions returned by Stage 3 script call.
    # When present these are already aligned to _sentences by sentence index, so we
    # can fill them in directly and skip the LLM batch for any fully-covered chunk.
    _inline_scenes = ctx.pipeline_state.get('_stage3_scene_list', [])
    if _inline_scenes:
        _scene_desc_count += _prefill_inline_scenes(ctx.visual_tags, _inline_scenes)
        ctx._log(
            'INFO',
            'Stage 3b',
            f'Pre-populated {_scene_desc_count} scene descs from Stage 3 inline scenes — '
            f'skipping LLM batches for covered sentences',
        )

    _scene_desc_count += _fill_scene_descs(ctx.visual_tags, _sentences, _scene_job)

    _scene_desc_src = 'Claude Haiku' if _3b_ak else 'Mistral/Ollama'
    _scene_desc_fallback = len(ctx.visual_tags) - _scene_desc_count
    ctx._log(
        'INFO',
        'Stage 3b',
        f'Scene descriptions: {_scene_desc_count}/{len(ctx.visual_tags)} via {_scene_desc_src}'
        + (f' ({_scene_desc_fallback} used keyword fallback)' if _scene_desc_fallback else ''),
    )

    ctx.pipeline_state['visual_tags'] = ctx.visual_tags
    ctx._save()

    # ── Quality gate ───────────────────────────────────────────────────────
    _generic_count, _generic_pct = _generic_fallback_stats(ctx.visual_tags, topic)
    if _generic_pct > 30:
        ctx._log(
            'WARNING',
            'Stage 3b',
            f'{_generic_count}/{len(ctx.visual_tags)} sentences ({_generic_pct:.0f}%) '
            f'still using keyword fallback after LLM pass — '
            f'LLM scene description may have failed or returned empty strings.',
        )
    ctx._log(
        'INFO',
        'Stage 3b',
        f'Tagged {len(ctx.visual_tags)} sentences '
        f'({_scene_desc_count} with LLM scene descriptions, '
        f'{len(ctx.visual_tags) - _scene_desc_count} keyword-only fallback)',
    )
    ctx._done(
        'Stage 3b: Visual Tagging',
        {
            'tagged': len(ctx.visual_tags),
            'scene_desc_llm': _scene_desc_count,
            'scene_desc_fallback': len(ctx.visual_tags) - _scene_desc_count,
        },
    )
