# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""_compute_metrics_dashboard() — the orchestrator.

The collection blocks live in dashboard_collect.py and dashboard_char.py; the
presentation blocks (the one-shot reloads, the live GPU snapshot, the four
summary dicts and the five display categories) live in dashboard_build.py. What
is left here is the call order and the payload it is assembled into.
"""

from zyg_dashboard.bp_metrics.dashboard_build import (
    CharGenStats,
    _build_characters_detail,
    _build_costs_summary,
    _build_hardware,
    _build_overview,
    _category_api_costs,
    _category_characters,
    _category_infrastructure,
    _category_performance,
    _category_workflow,
    _fmt_s,
    _run_one_shot_reloads,
    _telemetry_snapshot,
)
from zyg_dashboard.bp_metrics.dashboard_char import (
    _aggregate_caveman,
    _aggregate_char_gen,
    _build_pipelines_out,
)
from zyg_dashboard.bp_metrics.dashboard_collect import (
    _collect_flux_perf,
    _collect_pipeline_state,
    _collect_token_cost,
    _collect_vram,
    _collect_wattage,
)
from zyg_dashboard.gui.runtime_state import _runtime_path
from zyg_dashboard.gui.timeutil import _ams_iso


def _compute_metrics_dashboard() -> dict:
    """Compute all metrics categories from live pipeline data. Returns dict with 'categories' list."""
    import glob as _glob

    _run_one_shot_reloads()

    runtime_dir = _runtime_path('')
    (
        avg_duration_s,
        avg_jobs_per_day,
        completed_runs,
        pipelines_by_dept,
        recent_story_runs,
        stage_totals,
        success_rate,
        total_runs,
    ) = _collect_pipeline_state(runtime_dir)

    flux_s_per_image = _collect_flux_perf()

    (
        avg_cost_per_run,
        calls_by_model,
        calls_by_pipeline_type,
        cost_by_model,
        cost_by_pipeline_type,
        pipeline_costs,
        tok_entries,
        tokens_by_model,
        total_cost,
    ) = _collect_token_cost()

    _watt_value, _watt_desc = _collect_wattage(runtime_dir, avg_duration_s, _fmt_s)

    _gpu_mem_value, _gpu_mem_desc = _collect_vram(runtime_dir)

    chars = CharGenStats(*_aggregate_char_gen(_glob, runtime_dir, calls_by_pipeline_type, cost_by_pipeline_type))

    _cave_tagged, _env_caveman_level, caveman_detail = _aggregate_caveman(tok_entries)

    pipelines_out, char_stages_out = _build_pipelines_out(
        pipelines_by_dept, cost_by_pipeline_type, calls_by_pipeline_type, chars.char_stage_totals
    )

    gpu = _telemetry_snapshot()

    overview = _build_overview(
        total_runs=total_runs,
        completed_runs=completed_runs,
        success_rate=success_rate,
        avg_duration_s=avg_duration_s,
        avg_jobs_per_day=avg_jobs_per_day,
        total_cost=total_cost,
        flux_s_per_image=flux_s_per_image,
        chars=chars,
        gpu=gpu,
        env_caveman_level=_env_caveman_level,
        cave_tagged_count=len(_cave_tagged),
    )

    characters_detail = _build_characters_detail(chars, char_stages_out)

    costs_summary = _build_costs_summary(
        total_cost=total_cost,
        avg_cost_per_run=avg_cost_per_run,
        calls_by_model=calls_by_model,
        tokens_by_model=tokens_by_model,
        cost_by_model=cost_by_model,
        calls_by_pipeline_type=calls_by_pipeline_type,
        cost_by_pipeline_type=cost_by_pipeline_type,
    )

    hardware = _build_hardware(gpu, _gpu_mem_value, _gpu_mem_desc, _watt_value, _watt_desc)

    categories = [
        _category_performance(
            avg_jobs_per_day=avg_jobs_per_day,
            total_runs=total_runs,
            avg_duration_s=avg_duration_s,
            completed_runs=completed_runs,
            flux_s_per_image=flux_s_per_image,
            success_rate=success_rate,
        ),
        _category_infrastructure(gpu, _gpu_mem_value, _gpu_mem_desc, _watt_value, _watt_desc),
        _category_api_costs(
            avg_cost_per_run=avg_cost_per_run,
            total_cost=total_cost,
            pipeline_costs=pipeline_costs,
            tok_entries=tok_entries,
            calls_by_model=calls_by_model,
            cost_by_model=cost_by_model,
            tokens_by_model=tokens_by_model,
        ),
        _category_workflow(total_runs, completed_runs, stage_totals),
        _category_characters(chars),
    ]

    return {
        'categories': categories,
        'generated_at': _ams_iso(),
        'overview': overview,
        'pipelines': pipelines_out,
        'characters': characters_detail,
        'costs': costs_summary,
        'hardware': hardware,
        'recent_story_runs': recent_story_runs,
        'recent_char_runs': chars.recent_char_runs,
        'caveman': caveman_detail,
        'total_runs': total_runs,
        'completed_runs': completed_runs,
        'avg_duration_s': avg_duration_s,
        'avg_jobs_per_day': avg_jobs_per_day,
        'char_total': chars.char_total,
        'char_done': chars.char_done,
        'char_failed': chars.char_failed,
        'char_running': chars.char_running,
        'char_success_rate': chars.char_success_rate,
        'char_avg_duration_s': chars.avg_char_duration,
        'lora_success_rate': chars.lora_success_rate,
        'lora_avg_duration_s': chars.avg_lora_duration,
        'preview_avg_duration_s': chars.avg_preview_duration,
        'blender_avg_duration_s': chars.avg_blender_duration,
        'avg_dataset_size': chars.avg_dataset_size,
        'char_render_mode_counts': chars.char_render_mode_counts,
    }
