# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 6d: the tag-driven timeline, the concat/merge, the text-card fallback and loudnorm."""

from .constants import (
    os,
)
from .stage6_assembly_steps import (
    _append_outro_card,
    _apply_loudnorm,
    _build_segment_timeline,
    _concat_and_merge,
    _remove_quietly,
    _render_text_card,
    _segment_ctx,
)


def _crime_stage_6d_assembly(
    _case_name,
    _doc_cards,
    _img_to_clip,
    _log,
    _person_infobox_clip,
    _person_time_triggers,
    _shown_persons,
    _sp_crime,
    _word_timings,
    final_video_path,
    named_persons,
    out_dir,
    pipeline_id,
    pipeline_state,
    stock_clips,
    stock_images,
    tts_duration,
    tts_path,
    video_assembled,
):
    # ── 6d: Build tag-driven segment timeline ───────────────────────────
    # Uses visual_tags from Stage 3b to pick the right asset for each moment.
    # Fallback to phase-based rotation for sentences without a specific tag.
    _seg_files = []
    _seg_total_dur = 0.0

    try:
        _ctx = _segment_ctx(
            _doc_cards,
            _img_to_clip,
            _log,
            _person_infobox_clip,
            _person_time_triggers,
            _shown_persons,
            _sp_crime,
            _word_timings,
            named_persons,
            pipeline_state,
            stock_clips,
            stock_images,
        )
        _seg_total_dur = _build_segment_timeline(_ctx, _seg_files, tts_duration)

        _log('INFO', 'Stage 6', f'Built {len(_seg_files)} segments, {_seg_total_dur:.0f}s total')

        # ── Outro card: 5s black screen with "Subscribe to Crime Chronicles" ──
        _seg_total_dur += _append_outro_card(_img_to_clip, _log, _seg_files, out_dir)

    except Exception as _seg_e:
        _log('WARNING', 'Stage 6', f'Segment building failed: {_seg_e}')

    if _seg_files:
        video_assembled = (
            _concat_and_merge(
                (len(_doc_cards), len(stock_images), len(stock_clips)),
                _log,
                _seg_files,
                _sp_crime,
                final_video_path,
                out_dir,
                pipeline_id,
                tts_duration,
                tts_path,
            )
            or video_assembled
        )

    _remove_quietly(_doc_cards, 'doc card')

    # ── Fallback: text-card with subtitles burned in ──────────────────────
    if not video_assembled:
        _log('INFO', 'Stage 6', 'Creating text-card fallback video')
        video_assembled = _render_text_card(
            _case_name, _log, _sp_crime, final_video_path, pipeline_id, tts_duration, tts_path
        )

    if not video_assembled or not os.path.exists(final_video_path):
        raise RuntimeError('Stage 6: Video assembly failed — no output file produced')

    # Loudness normalisation (EBU R128 -14 LUFS)
    _apply_loudnorm(_log, _sp_crime, final_video_path, pipeline_id, tts_duration)
