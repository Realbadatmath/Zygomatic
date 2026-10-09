# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b preflight: smart clipping — transcript + motion scoring."""

import threading
from zyg_workflows.stage_runner.stage4b_models import _make_github_models
from zyg_workflows.stage_runner.stage4b_keywords import _make_keyword_tables
from zyg_workflows.stage_runner.stage4b_phases import _assign_moments
from zyg_workflows.stage_runner.stage4b_phases import _build_render_jobs
from zyg_workflows.stage_runner.stage4b_phases import _build_video_lookups
from zyg_workflows.stage_runner.stage4b_phases import _check_disk_space
from zyg_workflows.stage_runner.stage4b_phases import _ensure_asset_dirs
from zyg_workflows.stage_runner.stage4b_phases import _pregenerate_narrator_lines
from zyg_workflows.stage_runner.stage4b_phases import _recover_processed_clips
from zyg_workflows.stage_runner.stage4b_phases import _register_queued_markers
from zyg_workflows.stage_runner.stage4b_phases import _report_quality_gate
from zyg_workflows.stage_runner.stage4b_phases import _score_all_videos
from zyg_workflows.stage_runner.stage4b_post import _make_post_process_clip
from zyg_workflows.stage_runner.stage4b_render import _make_render_clip
from zyg_workflows.stage_runner.stage4b_scoring import _get_natural_clip_duration
from zyg_workflows.stage_runner.stage4b_scoring import _snap_to_sentence_start
from zyg_workflows.stage_runner.agents import _pf_agents_active
from zyg_workflows.stage_runner.agents import _pf_agents_done
from zyg_workflows import paths

_STAGE_4B_AGENTS = [
    'CLIPFARM-Moment-Detection-Agent',
    'CLIPFARM-Commentary-Agent',
    'CLIPFARM-Sound-Effects-Agent',
    'CLIPFARM-Variant-Generator-Agent',
    'CLIPFARM-Hook-Generator-Agent',
    'CLIPFARM-Subtitle-Generator-Agent',
    'CLIPFARM-Thumbnail-Agent',
    'CLIPFARM-Library-Agent',
]


def _pf_stage_4b(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info):
    """The Stage 4b branch of _stage_preflight: score, direct, render, recover.

    Orchestrator only — the work lives in the sibling modules behind the
    ``_make_*`` factories (keyword tables, GPT-4o directors, clip
    post-processing, the renderer) and in ``stage4b_phases``, which holds one
    function per phase of the original branch.  The call order below is the
    statement order of the original function; the renderer is still built
    once ``_narrator_lines`` and ``_queued_markers`` exist.
    """
    # ── Stage 4b: smart clipping — transcript + motion scoring ───────────────
    if 'Stage 4b' in stage_name:
        _pf_agents_active(pipeline_id, stage_name, _STAGE_4B_AGENTS)
        fetched = state.get('fetched_files', {})
        out_dir = state.get('output_dir') or str(paths.tmp_dir('clipfarm'))
        _log_info(f'{len(fetched)} fetched files to process')

        _vid_meta_titles, _vid_channel_map = _build_video_lookups(state)
        _VIRAL_KEYWORDS, _CRINGE_KEYWORDS, _get_contextual_commentary = _make_keyword_tables(_log_warn)
        _ensure_asset_dirs()
        _ask_github_models_bulk = _make_github_models(_log_info, _log_warn, _vid_channel_map)
        _post_process_clip = _make_post_process_clip(_log_err, _log_info, _log_warn, pipeline_id)

        processed = []
        processed_lock = threading.Lock()

        scored_raw = _score_all_videos(fetched, out_dir, _VIRAL_KEYWORDS, _log_err, _log_warn, _log_info)
        scored_videos, _bulk_moments = _assign_moments(scored_raw, _ask_github_models_bulk, _log_warn, _log_info)

        # ── Phase B: Render all clips in PARALLEL (6 concurrent GPU streams) ──
        # GPU does the work, CPU idles at ~10% — telemetry stays responsive
        _log_info('Stage 4b Phase B: parallel GPU rendering begins')
        _check_disk_space(out_dir, len(scored_raw), _log_warn, _log_info)

        _render_jobs = _build_render_jobs(scored_videos)
        _log_info(f'Stage 4b Phase B: {len(_render_jobs)} clips to render (6 parallel GPU streams)')

        _narrator_lines = _pregenerate_narrator_lines(_render_jobs, _get_contextual_commentary, _log_info)
        _queued_markers = _register_queued_markers(_render_jobs, pipeline_id)
        _render_clip = _make_render_clip(
            _get_natural_clip_duration,
            _log_err,
            _log_info,
            _log_warn,
            _narrator_lines,
            _post_process_clip,
            _queued_markers,
            _snap_to_sentence_start,
            _vid_channel_map,
            _vid_meta_titles,
            out_dir,
            pipeline_id,
            processed,
            processed_lock,
        )

        import concurrent.futures as _cf4b_render

        with _cf4b_render.ThreadPoolExecutor(max_workers=3) as _rpool:
            list(_rpool.map(_render_clip, _render_jobs))

        _recover_processed_clips(processed, out_dir, _log_info)

        state['processed_clips'] = processed
        _save(state)
        _log_info(f'processed_clips: {len(processed)}')

        _report_quality_gate(processed, _render_jobs, _bulk_moments, _log_warn, _log_info)
        _pf_agents_done(pipeline_id, stage_name, _STAGE_4B_AGENTS)
