# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers lifted out of `_compute_metrics_dashboard()`.

Each helper is pure: numbers in, a slice of the metrics payload out. No
filesystem sweep, no GPU, no services — `_telemetry_snapshot()` is the only one
that reads anything, and its reader is monkeypatched.
"""

from __future__ import annotations

import os
import threading


class _LazyDashboardBuild:
    """`bp_metrics.dashboard_build`, imported on first use rather than at collection.

    The blueprint contract binds the GUI package first, and importing that package
    starts watcher threads and builds the Flask app; done at collection time it would
    run before the API harness sets the secret key and suppresses the threads, so the
    import waits for the first test and applies the same two guards itself.
    """

    _mod = None

    @classmethod
    def _module(cls):
        if cls._mod is None:
            os.environ.setdefault('FLASK_SECRET_KEY', 'a' * 64)
            real_start = threading.Thread.start
            threading.Thread.start = lambda t: real_start(t) if t.name.startswith('Otel') else None
            try:
                import zyg_dashboard.crewai_web_gui  # noqa: F401  blueprint contract: the main module binds first
                from zyg_dashboard.bp_metrics import dashboard_build
            finally:
                threading.Thread.start = real_start
            cls._mod = dashboard_build
        return cls._mod

    def __getattr__(self, name):
        if name.startswith('__'):  # pytest probes collected objects for dunders; that must not import anything
            raise AttributeError(name)
        return getattr(self._module(), name)

    def __setattr__(self, name, value):  # monkeypatch.setattr(DB, ...) must reach the real module
        setattr(self._module(), name, value)

    def __delattr__(self, name):
        delattr(self._module(), name)


DB = _LazyDashboardBuild()


def _chars(**kw) -> DB.CharGenStats:
    """A CharGenStats with every field at a benign default, overridable by keyword."""
    base = {
        'avg_blender_duration': None,
        'avg_char_duration': None,
        'avg_dataset_size': 0,
        'avg_lora_duration': None,
        'avg_lora_flux': None,
        'avg_lora_sdxl': None,
        'avg_lora_steps': 0,
        'avg_preview_duration': None,
        'blender_durations': [],
        'char_brief_prose_count': 0,
        'char_brief_token_calls': 0,
        'char_brief_token_cost': 0.0,
        'char_done': 0,
        'char_durations': [],
        'char_failed': 0,
        'char_genre_counts': {},
        'char_image_count_samples': [],
        'char_mf_counts': {},
        'char_render_mode_counts': {},
        'char_running': 0,
        'char_stage_totals': {},
        'char_style_counts': {},
        'char_success_rate': 0.0,
        'char_total': 0,
        'lora_attempts': 0,
        'lora_success_rate': 0.0,
        'lora_successes': 0,
        'most_recent_char_done_id': None,
        'most_recent_char_done_iso': None,
        'preview_render_durations': [],
        'recent_char_runs': [],
    }
    base.update(kw)
    return DB.CharGenStats(**base)


def _gpu(**kw) -> DB.GpuSnapshot:
    """A GpuSnapshot with plausible live readings, overridable by keyword."""
    base = {
        'vram_used_mb': 2048,
        'vram_total_mb': 24576,
        'vram_pct': 8.3,
        'util_pct': 12,
        'temp_c': 41.0,
        'vram_label': '2.0 / 24.0 GB (8.3%)',
    }
    base.update(kw)
    return DB.GpuSnapshot(**base)


# ---------------------------------------------------------------------------
# _fmt_s — the duration label every category uses
# ---------------------------------------------------------------------------


def test_fmt_s_renders_each_magnitude_band():
    """None is an em dash, sub-second is '< 1s', then seconds, minutes and hours."""
    assert DB._fmt_s(None) == '—'
    assert DB._fmt_s(0.4) == '< 1s'
    assert DB._fmt_s(42) == '42s'
    assert DB._fmt_s(125) == '2m 5s'
    assert DB._fmt_s(3800) == '1h 3m'


def test_fmt_s_truncates_rather_than_rounds():
    """59.9s is still 59s: the label floors, as the original nested helper did."""
    assert DB._fmt_s(59.9) == '59s'
    assert DB._fmt_s(3599.9) == '59m 59s'


# ---------------------------------------------------------------------------
# _telemetry_snapshot — the live GPU block
# ---------------------------------------------------------------------------


def test_telemetry_snapshot_reads_gpu_zero_and_builds_the_shared_label(monkeypatch):
    """The VRAM label is computed once and is what both the overview and hardware show."""
    monkeypatch.setattr(
        DB,
        '_read_local_telemetry',
        lambda: {
            'gpus': [{'memory_used_mb': 12288, 'memory_total_mb': 24576, 'utilization_pct': 73, 'temperature_c': 65}]
        },
    )
    gpu = DB._telemetry_snapshot()
    assert gpu.vram_pct == 50.0
    assert gpu.util_pct == 73
    assert gpu.temp_c == 65
    assert gpu.vram_label == '12.0 / 24.0 GB (50.0%)'


def test_telemetry_snapshot_survives_a_machine_with_no_gpu(monkeypatch):
    """No gpus key at all must not divide by zero: total defaults to 1 MB, used to 0."""
    monkeypatch.setattr(DB, '_read_local_telemetry', lambda: {})
    gpu = DB._telemetry_snapshot()
    assert gpu.vram_used_mb == 0
    assert gpu.vram_total_mb == 1
    assert gpu.vram_pct == 0.0
    assert gpu.temp_c is None


# ---------------------------------------------------------------------------
# _build_costs_summary — the costs panel
# ---------------------------------------------------------------------------


def test_build_costs_summary_orders_models_by_call_count_and_rounds_to_cents_of_a_cent():
    """Busiest model first, every money figure rounded to 4 decimals."""
    out = DB._build_costs_summary(
        total_cost=1.234567,
        avg_cost_per_run=0.0411522,
        calls_by_model={'haiku': 3, 'opus': 11},
        tokens_by_model={'haiku': 1500, 'opus': 90000},
        cost_by_model={'haiku': 0.004321, 'opus': 1.230246},
        calls_by_pipeline_type={'story': 9, 'char_gen': 5},
        cost_by_pipeline_type={'story': 1.0, 'char_gen': 0.234567},
    )
    assert out['total_usd'] == 1.2346
    assert out['avg_per_run_usd'] == 0.0412
    assert [row['model'] for row in out['by_model']] == ['opus', 'haiku']
    assert out['by_model'][0]['cost_usd'] == 1.2302
    assert [row['type'] for row in out['by_pipeline_type']] == ['story', 'char_gen']


def test_build_costs_summary_titles_an_unlabelled_pipeline_type():
    """A type with no entry in _METRICS_PIPELINE_LABELS falls back to Title Case."""
    out = DB._build_costs_summary(
        total_cost=0.0,
        avg_cost_per_run=0.0,
        calls_by_model={},
        tokens_by_model={},
        cost_by_model={},
        calls_by_pipeline_type={'brand_new_thing': 1},
        cost_by_pipeline_type={},
    )
    assert out['by_pipeline_type'] == [
        {'type': 'brand_new_thing', 'label': 'Brand New Thing', 'calls': 1, 'cost_usd': 0.0}
    ]


# ---------------------------------------------------------------------------
# _category_workflow — run counts plus the per-stage rows
# ---------------------------------------------------------------------------


def test_category_workflow_derives_incomplete_runs_and_sorts_stages_by_total_time():
    """Active runs are total minus completed; stage rows are slowest-in-total first."""
    cat = DB._category_workflow(10, 7, {'fast': [1.0, 1.0], 'slow': [100.0]})
    assert cat['name'] == 'Workflow'
    assert [it['value'] for it in cat['items'][:3]] == ['10', '7', '3']
    stage_rows = cat['items'][3:]
    assert [row['label'] for row in stage_rows] == ['slow', 'fast']
    assert stage_rows[0]['value'] == '1m 40s'
    assert stage_rows[1]['description'] == 'Average stage duration across 2 runs'


def test_category_workflow_with_no_stages_has_only_the_three_counts():
    """An empty stage table adds no rows at all."""
    cat = DB._category_workflow(0, 0, {})
    assert len(cat['items']) == 3


# ---------------------------------------------------------------------------
# _build_overview / _build_hardware / _category_characters
# ---------------------------------------------------------------------------


def test_build_overview_copies_the_char_counts_and_the_live_gpu_label():
    """The headline tile reads its character numbers off CharGenStats, not its own sweep."""
    out = DB._build_overview(
        total_runs=4,
        completed_runs=3,
        success_rate=75.0,
        avg_duration_s=90,
        avg_jobs_per_day=1.5,
        total_cost=0.123456,
        flux_s_per_image=3.456,
        chars=_chars(char_total=6, char_done=5, char_running=1, char_success_rate=83.3),
        gpu=_gpu(),
        env_caveman_level='off',
        cave_tagged_count=2,
    )
    assert out['char_total'] == 6
    assert out['char_done'] == 5
    assert out['char_running'] == 1
    assert out['char_success_rate'] == 83.3
    assert out['total_api_spend_usd'] == 0.1235
    assert out['flux_s_per_image'] == 3.46
    assert out['gpu_vram_label'] == '2.0 / 24.0 GB (8.3%)'
    assert out['caveman_tagged_calls'] == 2


def test_build_overview_reports_no_flux_speed_rather_than_zero():
    """A zero/None learned estimate must stay None, not round to 0.0."""
    out = DB._build_overview(
        total_runs=0,
        completed_runs=0,
        success_rate=0.0,
        avg_duration_s=None,
        avg_jobs_per_day=0,
        total_cost=0.0,
        flux_s_per_image=None,
        chars=_chars(),
        gpu=_gpu(),
        env_caveman_level=None,
        cave_tagged_count=0,
    )
    assert out['flux_s_per_image'] is None


def test_build_hardware_shows_the_same_live_vram_string_as_the_overview():
    """hardware['live_vram'] used to be read back out of the overview dict; it must still match."""
    gpu = _gpu()
    hw = DB._build_hardware(gpu, '18.2 GB', 'measured on 12 runs', '310 W', 'over 1m 30s')
    overview = DB._build_overview(
        total_runs=0,
        completed_runs=0,
        success_rate=0.0,
        avg_duration_s=None,
        avg_jobs_per_day=0,
        total_cost=0.0,
        flux_s_per_image=None,
        chars=_chars(),
        gpu=gpu,
        env_caveman_level=None,
        cave_tagged_count=0,
    )
    assert hw['live_vram'] == overview['gpu_vram_label']
    assert hw['flux_vram_measured'] == '18.2 GB'
    assert hw['wattage_desc'] == 'over 1m 30s'


def test_category_characters_elides_the_long_job_id_and_appends_stage_rows():
    """The 'Most recent character' value is the first 12 characters plus an ellipsis."""
    cat = DB._category_characters(
        _chars(
            char_total=2,
            char_done=1,
            most_recent_char_done_id='abcdefghijklmnopqrstuvwxyz',
            most_recent_char_done_iso='2026-10-09T12:00:00+02:00',
            char_stage_totals={'1a_render': [30.0, 50.0]},
        )
    )
    labels = {it['label']: it for it in cat['items']}
    assert labels['Most recent character']['value'] == 'abcdefghijkl…'
    assert labels['Most recent character']['description'] == 'Completed at 2026-10-09T12:00:00+02:00'
    assert labels['1a_render']['value'] == '40s'
    assert labels['1a_render']['description'] == 'Average stage duration across 2 character runs'


def test_category_characters_with_nothing_recorded_says_so_instead_of_showing_zeros():
    """Every averaged row falls back to an em dash and an explanatory description."""
    cat = DB._category_characters(_chars())
    labels = {it['label']: it for it in cat['items']}
    assert labels['Avg LoRA training time']['value'] == '—'
    assert labels['LoRA training success rate']['description'] == 'No LoRA trainings recorded yet'
    assert labels['Avg dataset size']['description'] == 'No dataset size data recorded yet'
    assert labels['Render source breakdown']['value'] == '—'


def test_build_characters_detail_carries_the_stage_table_through_untouched():
    """characters['stages'] is exactly what _build_pipelines_out() handed over."""
    stages = [{'name': '1c_lora', 'avg_s': 900}]
    out = DB._build_characters_detail(_chars(char_brief_token_cost=0.123456, char_total=3), stages)
    assert out['stages'] is stages
    assert out['brief_token_cost_usd'] == 0.1235
    assert out['total'] == 3
