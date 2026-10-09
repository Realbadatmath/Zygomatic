# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages and line builders `scan._worker` was split into.

`_worker` was 340 lines of nested phases around ~20 shared locals, so none of the
arithmetic below — the frame-count tolerance, the cadence warning, the landmark coverage,
the ledger block, the max_frames cap — had ever been exercised without ffmpeg, a video
file and a GPU. These tests take each one on plain inputs.
"""

import os

import pytest
from zyg_workflows.vfx_analyzer import scan as S
from zyg_workflows.vfx_analyzer import scan_stages as ST


def _run(tmp_path, **over):
    """A ScanRun over a tmp run dir, with a recording log and a never-cancel gate."""
    cfg = {
        'start_s': 1.0,
        'duration_s': 0.5,
        'do_landmarks': True,
        'do_vlm': False,
        'do_curiosity': True,
        'max_frames': 0,
        'do_probes': True,
        'thresholds': {},
    }
    cfg.update(over.pop('cfg', {}))
    meta = over.pop('meta', {'name': 'clip.mp4', 'bytes': 1_000_000, 'probe': {'fps': 24.0}})
    lines = []
    run = ST._new_run(
        'jid1',
        str(tmp_path),
        'media1',
        '/videos/clip.mp4',
        meta,
        cfg,
        str(tmp_path),
        lines.append,
        lambda: False,
    )
    for k, v in over.items():
        setattr(run, k, v)
    return run, lines


# ── the initial report and the stage ledger ──────────────────────────────────


def test_the_initial_report_opens_running_with_no_stages_and_the_window_echoed():
    cfg = {'start_s': 2.5, 'duration_s': 0.75, 'max_frames': 0}
    rep = ST._initial_report('rid9', 'm1', {'name': 'c.mp4', 'probe': {'fps': 25}}, cfg)
    assert rep['state'] == 'running'
    assert rep['stages'] == []
    assert rep['error'] == ''
    assert rep['window'] == {'start_s': 2.5, 'duration_s': 0.75}
    assert rep['config'] is cfg
    assert rep['probe'] == {'fps': 25}


def test_a_media_without_a_name_or_probe_still_yields_a_report():
    rep = ST._initial_report('rid9', 'm1', {}, {'start_s': 0, 'duration_s': 1})
    assert rep['media_name'] == ''
    assert rep['probe'] == {}


def test_each_recorded_stage_rounds_its_seconds_and_coerces_its_verdict():
    rep = {'stages': []}
    ST._record_stage(rep, 'extract', 1, 0.12345, '8 frames')
    ST._record_stage(rep, 'cadence', None, 2.0)
    assert rep['stages'] == [
        {'name': 'extract', 'ok': True, 'seconds': 0.12, 'note': '8 frames'},
        {'name': 'cadence', 'ok': False, 'seconds': 2.0, 'note': ''},
    ]


# ── the capability line ──────────────────────────────────────────────────────


def test_the_capability_line_reports_only_the_dict_shaped_landmark_tiers():
    cap = {
        'landmarks': {'pose': {'ok': True}, 'face': {'ok': False}, 'note': 'a string, not a tier'},
        'vlm': {'ok': True},
        'detectors': {'count': 42},
        'taxonomy': {'count': 7},
    }
    line = ST._capability_line(cap)
    assert line.startswith('capability: landmarks={')
    assert "'pose': True" in line and "'face': False" in line
    assert 'note' not in line
    assert line.endswith('vlm=True detectors=42 taxonomy=7')


def test_the_capability_line_survives_a_box_with_no_tiers_at_all():
    assert ST._capability_line({'landmarks': None, 'vlm': {}}) == (
        'capability: landmarks={} vlm=None detectors=0 taxonomy=0'
    )


# ── the frame-count tolerance ────────────────────────────────────────────────


def test_an_exact_frame_count_says_nothing():
    assert ST._frame_count_note(24, 1.0, 24.0) == ''


def test_two_frames_off_is_inside_the_floor_even_on_a_tiny_window():
    assert ST._frame_count_note(4, 0.25, 24.0) == ''  # expected 6, off by 2
    note = ST._frame_count_note(3, 0.25, 24.0)  # off by 3
    assert note.startswith('NOTE: extracted 3 frames, expected ~6 at 24.000 fps')
    assert 'clipped by the file end, or the source is VFR' in note


def test_a_long_window_tolerates_five_percent_then_complains():
    assert ST._frame_count_note(1140, 50.0, 24.0) == ''  # expected 1200, 5 % off
    assert ST._frame_count_note(1139, 50.0, 24.0).startswith('NOTE: extracted 1139 frames, expected ~1200')


# ── the cadence lines ────────────────────────────────────────────────────────


def _cad(cadence, uniq, ratio):
    return {'cadence': cadence, 'unique_idx': uniq, 'unique_ratio': ratio, 'mean_hold': 2.0, 'hold_hist': {'2': 4}}


def test_ones_reports_the_map_and_nothing_else():
    lines = ST._cadence_lines(_cad('ones', list(range(8)), 1.0), 8)
    assert len(lines) == 1
    assert lines[0] == "cadence: ones  unique cels 8/8 (ratio 1.000, mean hold 2.00) holds={'2': 4}"


def test_twos_warns_that_a_per_frame_reading_would_be_structural_zeros():
    lines = ST._cadence_lines(_cad('twos', [0, 2, 4, 6], 0.5), 8)
    assert len(lines) == 2
    assert lines[0].startswith('cadence: twos  unique cels 4/8 (ratio 0.500')
    assert '50% structural zeros' in lines[1]
    assert 'between UNIQUE cels only' in lines[1]


def test_threes_warns_as_well():
    assert len(ST._cadence_lines(_cad('threes', [0, 3], 0.25), 8)) == 2


# ── the landmark coverage ────────────────────────────────────────────────────


def test_coverage_counts_found_frames_per_tier_and_ignores_the_rest():
    seq = [
        {'pose': {'state': 'found'}, 'face': {'state': 'missing'}},
        {'pose': {'state': 'found'}, 'face': {'state': 'found'}, 'hand': {'state': 'found'}},
        {},
        {'pose': None},
    ]
    assert ST._landmark_coverage(seq, 4) == {
        'pose_frames': 2,
        'face_frames': 1,
        'hand_frames': 1,
        'total_frames': 4,
    }


def test_a_run_where_nothing_resolved_reports_zeros_against_the_frame_total():
    assert ST._landmark_coverage([{}, {}], 9) == {
        'pose_frames': 0,
        'face_frames': 0,
        'hand_frames': 0,
        'total_frames': 9,
    }


# ── the ledger block ─────────────────────────────────────────────────────────


def test_the_ledger_block_names_all_four_states_and_the_unknowns():
    ledger = {
        'found': [1, 2, 3],
        'not_found': [1] * 12,
        'unmeasurable': [],
        'not_detectable': [1] * 140,
    }
    lines = ST._ledger_lines(ledger, [1, 2], 31.5)
    assert lines[:2] == ['', '=== LEDGER ===']
    assert lines[2] == '  FOUND             3   detector fired'
    assert lines[3] == '  NOT FOUND        12   detector ran, evidence below threshold'
    assert lines[4] == '  UNMEASURABLE      0   detector could not run on this input'
    assert lines[5] == '  NOT DETECTABLE  140   no detector exists yet (known blind spot)'
    assert lines[6] == '  UNKNOWNS          2   moving things nothing in the taxonomy claimed'
    assert lines[7] == 'run finished in 31.5s'


# ── the failure stamp ────────────────────────────────────────────────────────


def test_the_failed_report_keeps_the_error_type_and_the_last_25_traceback_lines():
    rep = {'state': 'running', 'error': ''}
    tb = '\n'.join(f'line {i}' for i in range(40))
    out = ST._failed_report(rep, ValueError('bad window'), tb, 0.0)
    assert out is rep
    assert rep['state'] == 'error'
    assert rep['error'] == 'ValueError: bad window'
    assert rep['traceback'] == [f'line {i}' for i in range(15, 40)]
    assert rep['seconds'] > 0
    assert rep['finished']


def test_a_short_traceback_is_kept_whole():
    rep = {}
    ST._failed_report(rep, RuntimeError('cancelled'), 'one\ntwo', 0.0)
    assert rep['traceback'] == ['one', 'two']


# ── the run context ──────────────────────────────────────────────────────────


def test_a_new_run_puts_the_frame_dir_under_the_run_dir_and_opens_a_report(tmp_path):
    run, lines = _run(tmp_path)
    assert run.fdir == os.path.join(str(tmp_path), 'frames')
    assert run.report['state'] == 'running'
    assert run.t_start > 0
    assert (run.names, run.n, run.fps) == ([], 0, 0.0)
    assert lines == []


# ── stage 1, on a stubbed extractor ──────────────────────────────────────────


def test_extract_frames_records_the_count_the_fps_and_the_stage(tmp_path, monkeypatch):
    names = [f'f{i:06d}.jpg' for i in range(1, 13)]
    monkeypatch.setattr(S, '_extract', lambda *a: (list(names), ''))
    run, lines = _run(tmp_path, cfg={'duration_s': 0.5})
    ST.extract_frames(run)
    assert run.names == names
    assert (run.n, run.fps) == (12, 24.0)
    assert run.report['frames_scanned'] == 12
    assert run.report['stages'][-1]['name'] == 'extract'
    assert run.report['stages'][-1]['note'] == '12 frames @ 24.000 fps'
    assert lines == []  # 12 frames is exactly the expectation, so no NOTE


def test_extract_frames_falls_back_to_24_fps_when_the_probe_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(S, '_extract', lambda *a: (['f000001.jpg'], ''))
    run, _ = _run(tmp_path, meta={'name': 'c.mp4', 'probe': {}}, cfg={'duration_s': 1 / 24})
    ST.extract_frames(run)
    assert run.fps == 24.0


def test_extract_frames_raises_what_ffmpeg_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(S, '_extract', lambda *a: ([], 'ffmpeg rc=1: moov atom not found'))
    run, _ = _run(tmp_path)
    with pytest.raises(RuntimeError, match='moov atom not found'):
        ST.extract_frames(run)
    assert run.report['stages'] == []


def test_extract_frames_refuses_an_empty_window(tmp_path, monkeypatch):
    monkeypatch.setattr(S, '_extract', lambda *a: ([], ''))
    run, _ = _run(tmp_path)
    with pytest.raises(RuntimeError, match='produced no frames for that window'):
        ST.extract_frames(run)


def test_the_max_frames_cap_deletes_the_surplus_jpgs_from_the_frame_dir(tmp_path, monkeypatch):
    names = [f'f{i:06d}.jpg' for i in range(1, 9)]
    fdir = tmp_path / 'frames'
    fdir.mkdir()
    for fn in names:
        (fdir / fn).write_bytes(b'jpg')
    monkeypatch.setattr(S, '_extract', lambda *a: (list(names), ''))
    run, lines = _run(tmp_path, cfg={'max_frames': 3, 'duration_s': 3 / 24})
    ST.extract_frames(run)
    assert run.names == names[:3]
    assert run.n == 3
    assert sorted(os.listdir(fdir)) == names[:3]
    assert 'capped to max_frames=3' in lines


def test_a_cap_above_the_extracted_count_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(S, '_extract', lambda *a: (['f000001.jpg'], ''))
    run, lines = _run(tmp_path, cfg={'max_frames': 99, 'duration_s': 1 / 24})
    ST.extract_frames(run)
    assert run.names == ['f000001.jpg']
    assert not any('capped' in ln for ln in lines)


def test_a_clipped_window_notes_the_mismatch_without_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(S, '_extract', lambda *a: (['f000001.jpg'], ''))
    run, lines = _run(tmp_path, cfg={'duration_s': 1.0})
    ST.extract_frames(run)
    assert run.n == 1
    assert lines[0].startswith('NOTE: extracted 1 frames, expected ~24')
    assert run.report['stages'][-1]['ok'] is True
