# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The presentation half of `_compute_metrics_dashboard()`.

`dashboard.py` collects the raw numbers (pipeline state, token cost, char-gen
aggregates); everything here turns them into the payload the metrics page reads:
the one-shot reloads that must run before the first collection, the live GPU
snapshot, the four summary dicts (overview / characters / costs / hardware) and
the five display categories. The char-gen aggregate arrives as a 31-tuple, so it
is wrapped once in `CharGenStats` and passed by name from then on.
"""

from dataclasses import dataclass

from zyg_workflows import gui_state

from zyg_dashboard.bp_metrics.aggregate import (
    _backfill_char_gen_states_from_bibles,
    _metrics_fmt_duration,
)
from zyg_dashboard.crewai_web_gui import _METRICS_PIPELINE_LABELS, _char_reload_jobs_from_disk
from zyg_dashboard.gui.telemetry import _read_local_telemetry

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


@dataclass
class CharGenStats:
    """The 31 char-gen aggregates `_aggregate_char_gen()` returns, by name.

    Field order is the tuple's order, so `CharGenStats(*_aggregate_char_gen(...))`
    is the only intended way to build one.
    """

    avg_blender_duration: float | None
    avg_char_duration: float | None
    avg_dataset_size: int
    avg_lora_duration: float | None
    avg_lora_flux: float | None
    avg_lora_sdxl: float | None
    avg_lora_steps: int
    avg_preview_duration: float | None
    blender_durations: list
    char_brief_prose_count: int
    char_brief_token_calls: int
    char_brief_token_cost: float
    char_done: int
    char_durations: list
    char_failed: int
    char_genre_counts: dict
    char_image_count_samples: list
    char_mf_counts: dict
    char_render_mode_counts: dict
    char_running: int
    char_stage_totals: dict
    char_style_counts: dict
    char_success_rate: float
    char_total: int
    lora_attempts: int
    lora_success_rate: float
    lora_successes: int
    most_recent_char_done_id: str | None
    most_recent_char_done_iso: str | None
    preview_render_durations: list
    recent_char_runs: list


@dataclass
class GpuSnapshot:
    """The live GPU numbers read from local telemetry, plus their shared label."""

    vram_used_mb: float
    vram_total_mb: float
    vram_pct: float
    util_pct: float
    temp_c: float | None
    vram_label: str


def _fmt_s(s: float | None) -> str:
    """Render a duration in seconds as the dashboard's short label ('—', '< 1s', '2m 5s', '1h 3m')."""
    if s is None:
        return '—'
    if s < 1:
        return '< 1s'
    if s >= 3600:
        return f'{int(s) // 3600}h {(int(s) % 3600) // 60}m'
    if s >= 60:
        return f'{int(s) // 60}m {int(s) % 60}s'
    return f'{int(s)}s'


def _run_one_shot_reloads() -> None:
    """Reload persisted char-gen jobs and backfill states from bibles, once per process.

    Both guards live on `gui_state`; a failure is printed and swallowed because
    the metrics page must still render without them.
    """
    # One-shot reload of persisted char-gen jobs (Kanban + model_family after restart).
    if not gui_state._CHAR_GEN_RELOAD_DONE:
        try:
            n_rel = _char_reload_jobs_from_disk()
            if n_rel:
                _zyg_log.info(f'[CHAR-STATE] Reloaded {n_rel} character job(s) from disk')
        except Exception as _rel_e:
            _zyg_log.info(f'[CHAR-STATE] Reload warning: {_rel_e}')
        gui_state._CHAR_GEN_RELOAD_DONE = True

    # One-shot backfill so pre-existing character bibles surface in metrics.
    if not gui_state._CHAR_GEN_BACKFILL_DONE:
        try:
            n_bf = _backfill_char_gen_states_from_bibles()
            if n_bf > 0:
                _zyg_log.info(f'[METRICS] Backfilled {n_bf} character generation state files from bibles')
        except Exception as _bf_e:
            _zyg_log.info(f'[METRICS] Char-gen backfill warning: {_bf_e}')
        gui_state._CHAR_GEN_BACKFILL_DONE = True


def _telemetry_snapshot() -> GpuSnapshot:
    """Read local telemetry and return GPU 0's live VRAM / utilisation / temperature."""
    telem = _read_local_telemetry()
    gpu0 = (telem.get('gpus') or [{}])[0]
    vram_used_mb = gpu0.get('memory_used_mb', 0) or 0
    vram_total_mb = gpu0.get('memory_total_mb', 1) or 1
    vram_pct = round(vram_used_mb / vram_total_mb * 100, 1)
    return GpuSnapshot(
        vram_used_mb=vram_used_mb,
        vram_total_mb=vram_total_mb,
        vram_pct=vram_pct,
        util_pct=gpu0.get('utilization_pct', 0),
        temp_c=gpu0.get('temperature_c'),
        vram_label=f'{vram_used_mb / 1024:.1f} / {vram_total_mb / 1024:.1f} GB ({vram_pct}%)',
    )


def _build_overview(
    *,
    total_runs: int,
    completed_runs: int,
    success_rate: float,
    avg_duration_s: float | None,
    avg_jobs_per_day: float,
    total_cost: float,
    flux_s_per_image: float | None,
    chars: CharGenStats,
    gpu: GpuSnapshot,
    env_caveman_level: object,
    cave_tagged_count: int,
) -> dict:
    """The headline tile: story counts, character counts, spend and the live GPU."""
    return {
        'story_runs': total_runs,
        'story_completed': completed_runs,
        'story_success_rate': success_rate,
        'story_avg_duration_s': avg_duration_s,
        'story_avg_duration_label': _metrics_fmt_duration(avg_duration_s),
        'char_total': chars.char_total,
        'char_done': chars.char_done,
        'char_success_rate': chars.char_success_rate,
        'char_running': chars.char_running,
        'total_api_spend_usd': round(total_cost, 4),
        'flux_s_per_image': round(flux_s_per_image, 2) if flux_s_per_image else None,
        'gpu_vram_label': gpu.vram_label,
        'gpu_util_pct': gpu.util_pct,
        'gpu_temp_c': gpu.temp_c,
        'jobs_per_day': avg_jobs_per_day,
        'caveman_env_level': env_caveman_level,
        'caveman_tagged_calls': cave_tagged_count,
    }


def _build_characters_detail(chars: CharGenStats, char_stages_out: list) -> dict:
    """The characters panel: counts, averages, the taxonomy counters and the stage table."""
    return {
        'total': chars.char_total,
        'done': chars.char_done,
        'failed': chars.char_failed,
        'running': chars.char_running,
        'success_rate': chars.char_success_rate,
        'avg_duration_s': chars.avg_char_duration,
        'avg_duration_label': _metrics_fmt_duration(chars.avg_char_duration),
        'lora_success_rate': chars.lora_success_rate,
        'avg_lora_duration_s': chars.avg_lora_duration,
        'avg_lora_flux_s': chars.avg_lora_flux,
        'avg_lora_sdxl_s': chars.avg_lora_sdxl,
        'avg_preview_duration_s': chars.avg_preview_duration,
        'avg_blender_duration_s': chars.avg_blender_duration,
        'avg_dataset_size': chars.avg_dataset_size,
        'model_family_counts': chars.char_mf_counts,
        'style_counts': chars.char_style_counts,
        'genre_counts': chars.char_genre_counts,
        'render_mode_counts': chars.char_render_mode_counts,
        'brief_prose_count': chars.char_brief_prose_count,
        'brief_token_calls': chars.char_brief_token_calls,
        'brief_token_cost_usd': round(chars.char_brief_token_cost, 4),
        'stages': char_stages_out,
    }


def _build_costs_summary(
    *,
    total_cost: float,
    avg_cost_per_run: float,
    calls_by_model: dict,
    tokens_by_model: dict,
    cost_by_model: dict,
    calls_by_pipeline_type: dict,
    cost_by_pipeline_type: dict,
) -> dict:
    """The costs panel: the totals plus per-model and per-pipeline-type breakdowns, busiest first."""
    return {
        'total_usd': round(total_cost, 4),
        'avg_per_run_usd': round(avg_cost_per_run, 4),
        'by_model': [
            {
                'model': m,
                'calls': calls_by_model[m],
                'tokens': tokens_by_model[m],
                'cost_usd': round(cost_by_model[m], 4),
            }
            for m in sorted(calls_by_model, key=lambda x: -calls_by_model[x])
        ],
        'by_pipeline_type': [
            {
                'type': pt,
                'label': _METRICS_PIPELINE_LABELS.get(pt, pt.replace('_', ' ').title()),
                'calls': calls_by_pipeline_type.get(pt, 0),
                'cost_usd': round(cost_by_pipeline_type.get(pt, 0.0), 4),
            }
            for pt in sorted(calls_by_pipeline_type, key=lambda x: -calls_by_pipeline_type[x])
        ],
    }


def _build_hardware(gpu: GpuSnapshot, gpu_mem_value: str, gpu_mem_desc: str, watt_value: str, watt_desc: str) -> dict:
    """The hardware panel: the measured FLUX VRAM and wattage, next to the live GPU readings."""
    return {
        'flux_vram_measured': gpu_mem_value,
        'flux_vram_desc': gpu_mem_desc,
        'wattage_per_run': watt_value,
        'wattage_desc': watt_desc,
        'live_vram': gpu.vram_label,
        'live_gpu_util_pct': gpu.util_pct,
        'live_gpu_temp_c': gpu.temp_c,
    }


def _category_performance(
    *,
    avg_jobs_per_day: float,
    total_runs: int,
    avg_duration_s: float | None,
    completed_runs: int,
    flux_s_per_image: float | None,
    success_rate: float,
) -> dict:
    """The 'Performance' category: throughput, end-to-end time, FLUX speed, success rate."""
    return {
        'name': 'Performance',
        'icon': '⚡',
        'items': [
            {
                'label': 'Processes ~X jobs/day',
                'value': f'~{avg_jobs_per_day}',
                'description': f'Average daily pipeline runs ({total_runs} total runs recorded)',
            },
            {
                'label': 'End-to-end generation time',
                'value': _fmt_s(avg_duration_s),
                'description': f'Average wall-clock time from topic input to finished video ({completed_runs} timed runs)',
            },
            {
                'label': 'FLUX image generation speed',
                'value': f'{flux_s_per_image:.1f}s/img' if flux_s_per_image else '—',
                'description': 'Learned estimate per image on RTX 4090 (exponential-smoothed)',
            },
            {
                'label': 'Pipeline success rate',
                'value': f'{success_rate}%',
                'description': f'{completed_runs} completed of {total_runs} total runs',
            },
        ],
    }


def _category_infrastructure(
    gpu: GpuSnapshot, gpu_mem_value: str, gpu_mem_desc: str, watt_value: str, watt_desc: str
) -> dict:
    """The 'Infrastructure' category: measured VRAM and wattage, concurrency, live GPU."""
    return {
        'name': 'Infrastructure',
        'icon': '🖥️',
        'items': [
            {'label': 'FLUX VRAM usage (measured)', 'value': gpu_mem_value, 'description': gpu_mem_desc},
            {
                'label': 'Supports X concurrent users',
                'value': '2',
                'description': 'Max 2 simultaneous Ollama LLM jobs (GPU semaphore); 1 FLUX image generation at a time; unlimited dashboard viewers',
            },
            {'label': 'Wattage used/run', 'value': watt_value, 'description': watt_desc},
            {
                'label': 'GPU VRAM (live)',
                'value': gpu.vram_label,
                'description': f'GPU utilisation: {gpu.util_pct:.0f}%'
                + (f' | Temp: {gpu.temp_c:.0f}°C' if gpu.temp_c else ''),
            },
        ],
    }


def _category_api_costs(
    *,
    avg_cost_per_run: float,
    total_cost: float,
    pipeline_costs: dict,
    tok_entries: list,
    calls_by_model: dict,
    cost_by_model: dict,
    tokens_by_model: dict,
) -> dict:
    """The 'API Costs' category: per-run and cumulative spend, then one item per model."""
    return {
        'name': 'API Costs',
        'icon': '💰',
        'items': [
            {
                'label': 'API costs/run',
                'value': f'${avg_cost_per_run:.4f}',
                'description': f'Average LLM API spend per pipeline run ({len(pipeline_costs)} runs with API calls)',
            },
            {
                'label': 'Total API spend logged',
                'value': f'${total_cost:.4f}',
                'description': f'Cumulative spend across {len(tok_entries)} logged LLM calls',
            },
        ]
        + [
            {
                'label': f'{m} — {calls_by_model[m]} calls',
                'value': f'${cost_by_model[m]:.4f}',
                'description': f'{tokens_by_model[m]:,} tokens total',
            }
            for m in sorted(calls_by_model, key=lambda x: -calls_by_model[x])
        ],
    }


def _category_workflow(total_runs: int, completed_runs: int, stage_totals: dict) -> dict:
    """The 'Workflow' category: run counts, then one item per stage, slowest first."""
    return {
        'name': 'Workflow',
        'icon': '🔄',
        'items': [
            {
                'label': 'Total pipeline runs',
                'value': str(total_runs),
                'description': 'All pipeline state files recorded',
            },
            {
                'label': 'Completed runs',
                'value': str(completed_runs),
                'description': 'Runs with a recorded start and end timestamp',
            },
            {
                'label': 'Active/incomplete runs',
                'value': str(total_runs - completed_runs),
                'description': 'Runs that started but did not finish (interrupted or in-progress)',
            },
        ]
        + [
            {
                'label': sname,
                'value': _fmt_s(sum(times) / len(times)),
                'description': f'Average stage duration across {len(times)} runs',
            }
            for sname, times in sorted(stage_totals.items(), key=lambda x: -sum(x[1]))
        ],
    }


def _character_items(chars: CharGenStats) -> list:
    """The fixed items of the 'Character Generation' category, before the per-stage rows."""
    return [
        {
            'label': 'Total characters generated',
            'value': str(chars.char_total),
            'description': 'All character generation jobs recorded on disk',
        },
        {
            'label': 'Characters completed',
            'value': str(chars.char_done),
            'description': 'Jobs that finished all 4 stages (1a render → 1b captions → 1c LoRA → 1d preview)',
        },
        {
            'label': 'Characters failed',
            'value': str(chars.char_failed),
            'description': 'Jobs that errored before completion',
        },
        {
            'label': 'Characters in progress',
            'value': str(chars.char_running),
            'description': 'Jobs currently running or interrupted by a restart',
        },
        {
            'label': 'Character success rate',
            'value': f'{chars.char_success_rate}%',
            'description': f'{chars.char_done} done of {chars.char_total} total character generation jobs',
        },
        {
            'label': 'Avg end-to-end character time',
            'value': _fmt_s(chars.avg_char_duration) if chars.avg_char_duration else '—',
            'description': f'Wall-clock average across {len(chars.char_durations)} completed character runs (render + captions + LoRA + preview)',
        },
        {
            'label': 'Avg LoRA training time',
            'value': _fmt_s(chars.avg_lora_duration) if chars.avg_lora_duration else '—',
            'description': (
                f'SimpleTuner FLUX LoRA — avg across {chars.lora_successes} successful runs'
                + (f' (~{chars.avg_lora_steps} steps each)' if chars.avg_lora_steps else '')
            ),
        },
        {
            'label': 'LoRA training success rate',
            'value': f'{chars.lora_success_rate}%' if chars.lora_attempts else '—',
            'description': (
                f'{chars.lora_successes} succeeded of {chars.lora_attempts} attempted LoRA trainings'
                if chars.lora_attempts
                else 'No LoRA trainings recorded yet'
            ),
        },
        {
            'label': 'Avg FLUX preview render time',
            'value': _fmt_s(chars.avg_preview_duration) if chars.avg_preview_duration else '—',
            'description': (
                f'Stage 1d FLUX character preview — avg across {len(chars.preview_render_durations)} renders'
                if chars.preview_render_durations
                else 'No preview renders recorded yet'
            ),
        },
        {
            'label': 'Avg Blender render time',
            'value': _fmt_s(chars.avg_blender_duration) if chars.avg_blender_duration else '—',
            'description': (
                f'Stage 1a Blender headless render — avg across {len(chars.blender_durations)} runs'
                if chars.blender_durations
                else 'No Blender renders recorded yet'
            ),
        },
        {
            'label': 'Avg dataset size',
            'value': f'{chars.avg_dataset_size} imgs' if chars.avg_dataset_size else '—',
            'description': (
                f'Reference images per character across {len(chars.char_image_count_samples)} jobs'
                if chars.char_image_count_samples
                else 'No dataset size data recorded yet'
            ),
        },
        {
            'label': 'Render source breakdown',
            'value': (
                ', '.join(f'{k}: {v}' for k, v in sorted(chars.char_render_mode_counts.items(), key=lambda x: -x[1]))
                if chars.char_render_mode_counts
                else '—'
            ),
            'description': 'How character datasets were sourced (Blender 3D vs uploaded photos)',
        },
        {
            'label': 'Most recent character',
            'value': (chars.most_recent_char_done_id[:12] + '…') if chars.most_recent_char_done_id else '—',
            'description': (
                f'Completed at {chars.most_recent_char_done_iso}'
                if chars.most_recent_char_done_iso
                else 'No completed character generations yet'
            ),
        },
    ]


def _category_characters(chars: CharGenStats) -> dict:
    """The 'Character Generation' category: the fixed items plus one row per char stage."""
    return {
        'name': 'Character Generation',
        'icon': '🎭',
        'items': (
            _character_items(chars)
            + [
                {
                    'label': sname,
                    'value': _fmt_s(sum(times) / len(times)),
                    'description': f'Average stage duration across {len(times)} character runs',
                }
                for sname, times in sorted(chars.char_stage_totals.items(), key=lambda x: -sum(x[1]))
            ]
        ),
    }
