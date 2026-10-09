# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3: Haiku pre-analysis, the LLM chain and the structured narration fallback."""

from .constants import (
    _build_framework_block,
    _classify_subject_type,
    _dsl,
    _mask_bad_words,
    _update_marker,
    _zyg_log,
    topic,
)
from .stage3_script_fallback import _build_structured_narration
from .stage3_script_llm import (
    _build_enriched_source,
    _build_script_prompt,
    _register_narration_template,
    _run_haiku_prefill,
    _try_claude_script,
    _try_gpt_script,
    _try_ollama_script,
)


def _persist_dsl_scene(_log, out_dir, pipeline_id, pipeline_state, selected) -> None:
    """Persist a DSL Scene snapshot for the finished script (env-gated).

    In: the stage logger, the output dir, the pipeline id, the pipeline state
    (for ``word_count``) and the case dict. Out: nothing — writes the scene YAML
    next to the episode and logs where it went; a failure is non-fatal.
    """
    # ── DSL: persist a Scene snapshot for this script (env-gated, no extra LLM call) ──
    if _dsl is None or not _dsl.is_enabled('documentary'):
        return
    try:
        _doc_scene = _dsl.build_scene_from_metadata(
            {
                'duration': max(60.0, pipeline_state['word_count'] / 2.5),  # ~150 wpm
                'subject': selected.get('name', '') or topic,
                'setting': f'{selected.get("crime_category", "")} case, {selected.get("year", "")}'.strip(', '),
                'lighting_style': 'dramatic',
                'aspect_ratio': '16:9',
                'tags': ['documentary', 'crime', topic],
            },
            pipeline='documentary',
            scene_id=f'crime_{pipeline_id[:8]}',
        )
        _doc_yaml = _dsl.persist_scene(_doc_scene, out_dir)
        if _doc_yaml:
            _log('INFO', 'Stage 3', f'DSL: persisted scene → {_doc_yaml}')
        else:
            _log('INFO', 'Stage 3', f'DSL: {_dsl.status_summary("documentary")}')
    except Exception as _dsl_e:
        _log('WARNING', 'Stage 3', f'DSL hook failed (non-fatal): {_dsl_e}')


def _crime_stage_3_script(
    _done, _log, _pipeline_marker, _save, court_text, job, out_dir, pipeline_id, pipeline_state, selected
):
    # ── Stage 3: Script Generation ──────────────────────────────────────
    job['current_stage'] = 'Stage 3: Script Generation'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — Script Writing')
    _log('INFO', 'Stage 3', 'Generating narration script')

    # ── Option 2: Haiku pre-analysis — enrich thin case facts ────────────
    _subject_type = _classify_subject_type(
        selected.get('name', '') + ' ' + selected.get('description', ''), selected.get('crime_category', '')
    )
    _framework_block = _build_framework_block(_subject_type, selected.get('name', ''))
    _haiku_prefill = _run_haiku_prefill(selected, court_text, pipeline_id, _log)
    _enriched_source = _build_enriched_source(_haiku_prefill, court_text)
    _script_prompt = _build_script_prompt(_framework_block, _enriched_source, selected)
    _register_narration_template(pipeline_id)

    narration_script = _try_claude_script(_script_prompt, pipeline_id, _log)
    if not narration_script:
        narration_script = _try_gpt_script(_script_prompt, pipeline_id, _log)

    _stage3_llm_model = None  # remember which model succeeded so Stage 3b reuses it
    _stage3_llm_inst = None  # keep the live Ollama instance for Stage 3b reuse
    if not narration_script:
        _stage3_llm_inst, _stage3_llm_model, narration_script = _try_ollama_script(_script_prompt, _log)

    # Structured fallback — produces ~1350 words (~9.3 min at 145 wpm) without any LLM
    if not narration_script or len(narration_script.split()) < 100:
        _log('WARNING', 'Stage 3', 'No LLM available — building full structured narration from case data')
        narration_script = _build_structured_narration(selected)

    # Clean bad words from script
    try:
        narration_script = _mask_bad_words(narration_script)
    except Exception as _exc:
        _zyg_log.warning('bad-word masking failed, the script keeps its original wording: %s', _exc)

    pipeline_state['script'] = narration_script
    pipeline_state['word_count'] = len(narration_script.split())
    _save()
    _log('INFO', 'Stage 3', f'Script ready: {pipeline_state["word_count"]} words')
    _done('Stage 3: Script Generation', {'word_count': pipeline_state['word_count']})

    _persist_dsl_scene(_log, out_dir, pipeline_id, pipeline_state, selected)

    return (_stage3_llm_inst, _stage3_llm_model, narration_script)
