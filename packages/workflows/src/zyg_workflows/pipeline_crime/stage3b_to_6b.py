# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stages 3b-6b: visual intent tagging, TTS narration, the SRT file and the court doc cards.

`_crime_stages_3b_to_6b` keeps the stage banners, the job label updates, the Stage 5
no-op and the pipeline_state writes; the work of each stage lives in
:mod:`.stage3b_to_6b_steps` and is called from here in the original order.
"""

from .constants import (
    _update_marker,
    os,
)
from .stage3b_to_6b_steps import (
    pick_tag_llm,
    register_tagging_prompt,
    stage_4_tts,
    stage_6a_srt,
    stage_6b_doc_cards,
    tag_sentence_batches,
)


def _crime_stages_3b_to_6b(
    _done,
    _log,
    _pipeline_marker,
    _re_crime,
    _save,
    _sp_crime,
    _stage3_llm_inst,
    _stage3_llm_model,
    job,
    narration_script,
    out_dir,
    pipeline_id,
    pipeline_state,
    selected,
):
    # ── Stage 3b: Visual Intent Tagging ────────────────────────────────
    # Reuse the same model instance from Stage 3 — it's already loaded in VRAM,
    # so no eviction/reload cost. Use gpt-oss:20b if Stage 3 used the structured fallback.
    job['current_stage'] = 'Stage 3b: Visual Tagging'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — Visual Tagging')
    _log('INFO', 'Stage 3b', 'Tagging sentences with visual intents')

    _tag_gpt = bool(os.environ.get('OPENAI_API_KEY', ''))
    register_tagging_prompt(pipeline_id)
    _tag_llm = pick_tag_llm(_log, _tag_gpt, _stage3_llm_model, _stage3_llm_inst)
    visual_tags = tag_sentence_batches(_log, narration_script, pipeline_id, _tag_gpt, _tag_llm)
    pipeline_state['visual_tags'] = visual_tags
    _save()

    # ── Stage 4: TTS Narration ──────────────────────────────────────────
    job['current_stage'] = 'Stage 4: TTS Narration'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — TTS Narration')
    _log('INFO', 'Stage 4', 'Generating TTS audio')

    tts_path, tts_duration, _word_timings = stage_4_tts(
        _done, _log, _save, _sp_crime, narration_script, out_dir, pipeline_id, pipeline_state
    )

    # ── Stage 5: Stock Footage — DISABLED ──────────────────────────────────
    job['current_stage'] = 'Stage 5: Stock Footage'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — Stock Footage')

    # Stock footage and stock image fetching is disabled.
    # External APIs (Pexels, Pixabay, Wikimedia, Unsplash, Internet Archive) are not used.
    stock_clips = []
    stock_images = []
    location_images = {}
    pipeline_state['location_images'] = location_images
    pipeline_state['stock_clips'] = stock_clips
    pipeline_state['stock_images'] = stock_images
    _save()
    _log('INFO', 'Stage 5', 'Stock footage disabled — skipped')
    _done('Stage 5: Stock Footage', {'clips_found': 0, 'images_found': 0})

    # ── Stage 6: Video Assembly ─────────────────────────────────────────
    job['current_stage'] = 'Stage 6: Video Assembly'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — Video Assembly')
    _log('INFO', 'Stage 6', f'Assembling video ({tts_duration:.0f}s, {len(stock_clips)} clips)')

    _case_name = selected.get('name', 'Unknown')
    _title_safe = _re_crime.sub(r'[<>:"/\\|?*\x00-\x1f]', '', f'Crime_Chronicles_{_case_name}').strip()
    _title_safe = _re_crime.sub(r'\s+', '_', _title_safe)[:80]
    final_video_path = os.path.join(out_dir, f'{_title_safe}.mp4')

    video_assembled = False
    stock_images = pipeline_state.get('stock_images', [])

    # ── 6a: Generate SRT subtitle file ──────────────────────────────────
    _word_timings = pipeline_state.get('word_timings', [])
    stage_6a_srt(_log, narration_script, out_dir, pipeline_state, _title_safe, tts_duration, _word_timings)

    # ── 6b: Generate court document cards using Pillow ──────────────────
    _doc_cards = stage_6b_doc_cards(_log, _case_name, narration_script, out_dir, selected, tts_duration)

    return (
        _case_name,
        _doc_cards,
        _word_timings,
        final_video_path,
        stock_clips,
        stock_images,
        tts_duration,
        tts_path,
        video_assembled,
    )
