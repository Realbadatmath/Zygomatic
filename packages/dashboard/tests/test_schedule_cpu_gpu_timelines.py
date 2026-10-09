# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The dual CPU/GPU timeline orchestrator answers its read API (2026-10-06).

This file used to live at ``src/zyg_dashboard/Schedule/test_cpu_gpu_timelines.py``
as a hand-run demo script: it imported ``timeline_orchestrator_dual`` by its old
flat name, which no longer resolves since the monorepo move, so any pytest run
pointed at ``src/`` collected it and errored on the import.

Two things changed in the move:

* the import is the package path
  (``zyg_dashboard.Schedule.timeline_orchestrator_dual``), and
* nothing a run does may write into the package tree. The demo rendered
  ``cpu_24_hour_timeline.png`` / ``gpu_24_hour_timeline.png`` into the process
  cwd and aimed its entry additions at the **tracked**
  ``schedule_data_CPU.json`` / ``schedule_data_GPU.json``, so it was parked
  behind ``ZYG_TIMELINE_WRITE_TEST=1`` and never ran. There is no test data root
  here (see ``apitests/README.md`` §4), so the writing half now runs
  unconditionally against throwaway copies in ``tmp_path`` (2026-10-09): the
  orchestrator takes ``cpu_schedule_file=`` / ``gpu_schedule_file=`` and the
  renderers take ``output_file=``, which is all the redirection it needs. The
  flag is gone; the assertion that the tracked pair stays byte-identical is the
  regression guard that replaces it.

The read side is what regressed when the module was renamed: the orchestrator
must import and each of its three getters must answer the ``{'entries': [...]}``
shape the Schedule pages consume. The counts are not asserted — the fixture date
has no scheduled work on a clean checkout, and a smoke test that demanded data
would fail for the wrong reason.
"""

import json
from pathlib import Path

import pytest

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.Schedule.timeline_orchestrator_dual import DualTimelineOrchestrator

TEST_DATE = '2025-07-15'

TRACKED_CPU = Path(_dash_paths.SCHEDULE_DIR) / 'schedule_data_CPU.json'
TRACKED_GPU = Path(_dash_paths.SCHEDULE_DIR) / 'schedule_data_GPU.json'

CPU_ENTRY = {
    'ai_model': '1010',
    'agent': 'CEO-Agent',
    'start_time': '08:00',
    'end_time': '09:00',
    'cpu_percent': '0.95',
    'memory_fraction': '0.15',
    'cpu_device': 'CPU 1',
    'priority': 'High',
    'bar_id': 'CEO-Agent__Claude 3',
}
GPU_ENTRY = {
    'ai_model': '1001',
    'agent': '2D-Character-Designer-Agent',
    'start_time': '08:00',
    'end_time': '09:00',
    'gpu_percent': '0.95',
    'memory_fraction': '0.15',
    'gpu_device': 'GTX 970',
    'priority': 'High',
    'bar_id': '2D-Character-Designer-Agent__Stable Diffusion 1.5 Xl',
}


@pytest.fixture(scope='module')
def orchestrator():
    return DualTimelineOrchestrator()


@pytest.fixture
def throwaway_orchestrator(tmp_path):
    """An orchestrator reading and writing copies of the tracked schedule files."""
    cpu = tmp_path / 'schedule_data_CPU.json'
    gpu = tmp_path / 'schedule_data_GPU.json'
    cpu.write_bytes(TRACKED_CPU.read_bytes())
    gpu.write_bytes(TRACKED_GPU.read_bytes())
    return DualTimelineOrchestrator(cpu_schedule_file=str(cpu), gpu_schedule_file=str(gpu))


@pytest.mark.parametrize('getter', ['get_cpu_timeline_data', 'get_gpu_timeline_data', 'get_combined_timeline_data'])
def test_timeline_getter_answers_the_entries_shape(orchestrator, getter):
    data = getattr(orchestrator, getter)('24h', date=TEST_DATE)
    assert isinstance(data, dict), f'{getter} returned {type(data).__name__}, expected a dict'
    assert isinstance(data.get('entries', []), list), f'{getter} returned a non-list "entries"'


def test_reading_a_timeline_does_not_rewrite_the_tracked_schedule_files(orchestrator):
    """The read API normalises in memory: a getter leaves the files byte-identical."""
    before = (TRACKED_CPU.read_bytes(), TRACKED_GPU.read_bytes())
    for getter in ('get_cpu_timeline_data', 'get_gpu_timeline_data', 'get_combined_timeline_data'):
        getattr(orchestrator, getter)('24h', date=TEST_DATE)
    assert (TRACKED_CPU.read_bytes(), TRACKED_GPU.read_bytes()) == before, (
        'a timeline getter rewrote Schedule/schedule_data_CPU.json or schedule_data_GPU.json'
    )


def test_entry_addition_writes_to_the_files_it_was_given(throwaway_orchestrator, tmp_path):
    """``cpu_schedule_file=``/``gpu_schedule_file=`` redirect every write off the tracked pair."""
    tracked_before = (TRACKED_CPU.read_bytes(), TRACKED_GPU.read_bytes())
    copies_before = (
        (tmp_path / 'schedule_data_CPU.json').read_bytes(),
        (tmp_path / 'schedule_data_GPU.json').read_bytes(),
    )

    cpu_result = throwaway_orchestrator.add_cpu_schedule_entry(dict(CPU_ENTRY), TEST_DATE)
    gpu_result = throwaway_orchestrator.add_gpu_schedule_entry(dict(GPU_ENTRY), TEST_DATE)

    for scope, result in (('CPU', cpu_result), ('GPU', gpu_result)):
        assert isinstance(result, dict), f'add_{scope.lower()}_schedule_entry returned {type(result).__name__}'
        assert 'success' in result, f'add_{scope.lower()}_schedule_entry answered without a "success" key'

    assert (TRACKED_CPU.read_bytes(), TRACKED_GPU.read_bytes()) == tracked_before, (
        'adding an entry rewrote the tracked Schedule/schedule_data_*.json pair'
    )

    for scope, result, name, before in (
        ('CPU', cpu_result, 'schedule_data_CPU.json', copies_before[0]),
        ('GPU', gpu_result, 'schedule_data_GPU.json', copies_before[1]),
    ):
        copy = tmp_path / name
        if result['success']:
            added = json.loads(copy.read_text(encoding='utf-8')).get(TEST_DATE) or []
            assert any(e.get('agent') == (CPU_ENTRY if scope == 'CPU' else GPU_ENTRY)['agent'] for e in added), (
                f'{scope} add reported success but the copy holds no entry for {TEST_DATE}'
            )
        else:
            assert copy.read_bytes() == before, f'{scope} add was rejected yet the copy changed'


def test_visualisation_renders_into_the_output_file_it_is_given(throwaway_orchestrator, tmp_path):
    """The PNG lands where the caller asked, not in the Schedule package folder."""
    cpu_png = tmp_path / 'cpu_24_hour_timeline.png'
    gpu_png = tmp_path / 'gpu_24_hour_timeline.png'
    assert throwaway_orchestrator.generate_cpu_visualization('24h', date=TEST_DATE, output_file=str(cpu_png))
    assert throwaway_orchestrator.generate_gpu_visualization('24h', date=TEST_DATE, output_file=str(gpu_png))
    for png in (cpu_png, gpu_png):
        assert png.is_file(), f'{png.name} was not written'
        assert png.stat().st_size > 0, f'{png.name} is empty'
    assert not list(Path(_dash_paths.SCHEDULE_DIR).glob('*_24_hour_timeline.png')), (
        'a timeline render dropped a PNG into the Schedule package folder'
    )
