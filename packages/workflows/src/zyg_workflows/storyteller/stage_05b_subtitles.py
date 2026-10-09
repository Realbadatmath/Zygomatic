# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 5b of the storyteller pipeline — burnt-in subtitles and the seal.

Builds the SRT from the TTS word timings, burns it into the assembled video,
records the degraded-render reasons, and applies the content credential to the
delivered file. The ``_seal.seal(...)`` hook lives here now;
``scripts/check_seal_hooks.py`` is pointed at this module by
``tests/test_storyteller_seal.py``. Cut verbatim out of
``pipeline_storyteller._run_storyteller_pipeline`` (lines 3334-3777 of commit
770c30a); see ``SPLIT_LOG.md``.

2026-10-09: the 458-line stage was itself over the 300-line function cap, so the
caption building and the four delivery gates became the step functions of
:mod:`stage_05b_subtitles_captions`; what is left here is the order they run in,
the completion of the job record and the seal."""

import os

from zyg_workflows import provenance_seal as _seal
from zyg_workflows.storyteller.stage_05b_subtitles_captions import (
    degradation_report,
    delivered_scene_count,
    fail_degraded,
    gate_final_video,
    gate_narration_audio,
    scan_near_duplicates,
    write_subtitles,
)
from zyg_workflows.subproc_registry import _update_marker


def stage_05b_burn_subtitles(ctx):
    """Stage 5b — subtitles, the delivery gates, the seal and the final job record.

    Writes the SRT beside the delivered video, points ``pipeline_state`` and the
    job at ``final_path``, and completes the job: a missing/empty video, lost
    narration audio or more than 30% bad frames fail it instead, each with the
    reason in ``job['error']``. A completed run is sealed with its content
    credential before the job points at the file."""
    _log = ctx._log
    _save = ctx._save
    final_path = ctx.final_path
    job = ctx.job
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    # ── Stage 5b: Burn subtitles ──────────────────────────────────────────────
    _burn_subs_st = bool((job.get('pipeline_options') or {}).get('burn_subtitles', True))
    ctx._update_stage('Stage 5b — Subtitle Burn', 95)
    ctx._check_stop()
    if not _burn_subs_st:
        _log('INFO', 'Stage 5b — Subtitle Burn', 'Subtitles disabled (pipeline_options) — skipping')
    if _burn_subs_st:
        write_subtitles(ctx)

    pipeline_state['video_path'] = final_path
    job['progress_pct'] = 98
    _save()

    # ── Wrap-up ───────────────────────────────────────────────────────────────
    # Mark final stage_timeline entry as completed
    for _tl_e in job.get('stage_timeline', []):
        if _tl_e.get('status') == 'running':
            _tl_e['status'] = 'completed'
    if gate_final_video(ctx):
        return
    if gate_narration_audio(ctx):
        return

    _dupe_scenes = scan_near_duplicates(pipeline_state, _log, float(os.environ.get('ZYG_ST_DUPE_CORR', '0.90')))
    _n_scenes = delivered_scene_count(pipeline_state)
    _bad_scenes, _degraded_bits = degradation_report(pipeline_state, _n_scenes, _dupe_scenes)
    _fb_frac = len(_bad_scenes) / float(_n_scenes)
    if _fb_frac > 0.30:
        fail_degraded(ctx, _bad_scenes, _n_scenes, _degraded_bits)
        return
    job['status'] = 'completed'
    if _degraded_bits:
        job['degraded'] = True
        job['degraded_reasons'] = _degraded_bits
        _log('WARNING', 'PIPELINE', f'Storyteller completed DEGRADED: {"; ".join(_degraded_bits)}')
    # Content credential on the delivered video, after the last thing that rewrites it
    # (merge, slideshow fallback, subtitle pass) and before the job points at it.
    # Fail-safe: a missing key or an unsignable file logs and leaves the render intact.
    _seal.seal(
        final_path,
        pipeline='storyteller',
        run_id=pipeline_id,
        extra={'scenes': _n_scenes, 'degraded': bool(_degraded_bits)},
        log_fn=lambda m: _log('INFO', 'PIPELINE', m),
    )
    job['result'] = final_path
    job['final_output_file'] = final_path
    job['current_stage'] = 'Complete ✓'
    _update_marker(ctx._pipeline_marker, status='done', label=f'Storyteller complete → {os.path.basename(final_path)}')
    _log('INFO', 'PIPELINE', f'✅ Storyteller complete → {final_path}')
    _save()
