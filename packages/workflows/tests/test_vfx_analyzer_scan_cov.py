# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for `zyg_workflows.vfx_analyzer.scan`.

`test_scan_helpers.py` covers the pure line builders hoisted into `scan_stages`;
nothing covered `scan.py` itself — the job board, `start_run`'s option parsing and
dispatch, the ffmpeg call in `_extract`, the stage order `_worker` promises, and the
two pure builders `_segment_shots` and `_build_ledger`. All offline: ffmpeg is a fake
`subprocess` namespace, the worker's thread is a `threading.Thread` that never starts
one, the run dir is `tmp_path`, the taxonomy is a dict.

`_StubFinder` is the price of `--cov=zyg_workflows.vfx_analyzer.scan`: coverage
resolves that dotted name with `importlib.util.find_spec` inside its
`sys_modules_saved()`, whose `restore()` deletes every `numpy.*` entry the import
added while numpy's C extension stays initialised — so the next `import numpy` dies
with `cannot load module more than once per process`. It is armed only once that has
happened (a plain suite run never sees it), and the three modules importing numpy here
touch it only inside `np.save`/`np.load`, which these tests never reach.
"""

import importlib
import importlib.abc
import importlib.util
import os
import subprocess
import sys
import types

import pytest


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Fabricates empty `numpy`/`numpy.*` modules for a poisoned interpreter."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'numpy' or fullname.startswith('numpy.'):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        mod = types.ModuleType(spec.name)
        mod.__path__ = []
        mod.__getattr__ = lambda attr: types.SimpleNamespace()
        return mod

    def exec_module(self, module):
        return None


def _arm_numpy_stub():
    try:
        importlib.import_module('numpy')
    except ImportError:
        sys.meta_path.insert(0, _StubFinder())


_arm_numpy_stub()

S = importlib.import_module('zyg_workflows.vfx_analyzer.scan')
ST = importlib.import_module('zyg_workflows.vfx_analyzer.scan_stages')


@pytest.fixture(autouse=True)
def _empty_board():
    """The job table is process-wide state; no test may leak a job into the next."""
    S._JOBS.clear()
    yield
    S._JOBS.clear()


def _put(jid, **kw):
    j = {'id': jid, 'state': 'queued', 'log': [], 'started_ts': 0.0}
    j.update(kw)
    S._JOBS[jid] = j
    return j


def _fake_threads(monkeypatch):
    """Replace `scan.threading` with a Thread that records its args instead of running."""
    seen = []

    class _T:
        def __init__(self, target=None, args=(), daemon=None):
            self.target, self.args, self.daemon = target, args, daemon

        def start(self):
            seen.append(self)

    monkeypatch.setattr(S, 'threading', types.SimpleNamespace(Thread=_T))
    return seen


# ── the job table ────────────────────────────────────────────────────────────


def test_job_set_updates_only_the_keys_it_is_given():
    _put('a', pct=0.0, stage='queued')
    S._job_set('a', pct=0.5, stage='measure')
    assert S._JOBS['a']['pct'] == 0.5
    assert S._JOBS['a']['stage'] == 'measure'
    assert S._JOBS['a']['state'] == 'queued'


def test_job_set_on_an_unknown_id_is_a_silent_no_op():
    S._job_set('ghost', pct=1.0)
    assert S._JOBS == {}


def test_job_stringifies_its_id_and_hands_back_a_copy_or_none():
    _put('7', state='running')
    assert S.job(7)['state'] == 'running'
    assert S.job('nope') is None
    S.job('7')['state'] = 'tampered'
    assert S._JOBS['7']['state'] == 'running'


def test_jobs_lists_copies_of_every_job_newest_first():
    assert S.jobs() == []
    for jid, ts in (('old', 10.0), ('new', 30.0), ('mid', 20.0)):
        _put(jid, started_ts=ts)
    assert [j['id'] for j in S.jobs()] == ['new', 'mid', 'old']
    S.jobs()[0]['state'] = 'tampered'
    assert S._JOBS['new']['state'] == 'queued'


@pytest.mark.parametrize(
    ('state', 'expected'),
    [('queued', True), ('running', True), ('done', False), ('error', False), ('cancelled', False)],
)
def test_cancel_only_flags_a_job_that_is_still_alive(state, expected):
    _put('a', state=state)
    assert S.cancel('a') is expected
    assert S._JOBS['a'].get('cancel', False) is expected


def test_cancelling_an_unknown_job_is_false_and_requests_nothing():
    assert S.cancel('ghost') is False
    assert S._cancel_requested('ghost') is False


def test_cancel_requested_reads_the_flag_the_board_set():
    _put('a', state='running')
    assert S._cancel_requested('a') is False
    S.cancel('a')
    assert S._cancel_requested('a') is True


# ── the job log ──────────────────────────────────────────────────────────────


def test_a_log_line_is_timestamped_appended_and_mirrored_to_the_run_log(tmp_path):
    path = tmp_path / 'run.log'
    _put('a', log_path=str(path))
    S._job_log('a', 'extract: 12 frames')
    (line,) = S._JOBS['a']['log']
    assert line.endswith('] extract: 12 frames')
    assert line[0] == '[' and line[9] == ']'
    assert path.read_text(encoding='utf-8') == line + '\n'


def test_a_job_with_no_log_path_keeps_only_the_last_four_hundred_lines_in_memory():
    _put('a')
    for i in range(405):
        S._job_log('a', f'line {i}')
    log = S._JOBS['a']['log']
    assert len(log) == 400
    assert log[0].endswith('line 5')
    assert log[-1].endswith('line 404')


def test_an_unwritable_log_path_warns_and_keeps_the_line_in_memory(tmp_path, caplog):
    _put('a', log_path=str(tmp_path))  # a directory: open(..., 'a') raises IsADirectoryError
    with caplog.at_level('WARNING', logger=S._zyg_log.name):
        S._job_log('a', 'still recorded')
    assert S._JOBS['a']['log'][0].endswith('still recorded')
    assert 'survives only on stdout' in caplog.text


def test_logging_against_an_unknown_job_trips_an_unbound_local(tmp_path):
    """Documented, not endorsed: `path` is only bound inside `if j`, so a line logged
    against a job the board has already pruned raises instead of being dropped. The
    module is out of scope for this task; the defect is named in the report."""
    with pytest.raises(UnboundLocalError, match='path'):
        S._job_log('ghost', 'into the void')
    assert S._JOBS == {}


# ── pruning ──────────────────────────────────────────────────────────────────


def test_pruning_drops_the_oldest_finished_jobs_past_the_keep_limit(monkeypatch):
    monkeypatch.setattr(S, '_JOB_KEEP', 2)
    for i in range(5):
        _put(f'done{i}', state='done', started_ts=float(i))
    S._prune_jobs()
    assert sorted(S._JOBS) == ['done3', 'done4']
    S._prune_jobs()  # a board already under the limit is left alone
    assert sorted(S._JOBS) == ['done3', 'done4']


def test_pruning_never_evicts_a_live_job_however_old(monkeypatch):
    monkeypatch.setattr(S, '_JOB_KEEP', 1)
    _put('ancient', state='running', started_ts=0.0)
    _put('queued', state='queued', started_ts=1.0)
    for i in range(3):
        _put(f'done{i}', state='done', started_ts=10.0 + i)
    S._prune_jobs()
    assert sorted(S._JOBS) == ['ancient', 'done2', 'queued']


# ── start_run ────────────────────────────────────────────────────────────────


@pytest.fixture
def board(tmp_path, monkeypatch):
    """`start_run` with its media library, its runs dir and its thread all faked."""
    monkeypatch.setattr(S, '_ensure_dirs', lambda: None)
    monkeypatch.setattr(S, 'RUNS_DIR', str(tmp_path / 'runs'))
    monkeypatch.setattr(S, 'get_media', lambda mid: {'name': 'clip.mp4', 'bytes': 12})
    monkeypatch.setattr(S, 'media_path', lambda mid: str(tmp_path / 'clip.mp4'))
    return _fake_threads(monkeypatch)


def test_start_run_refuses_an_unknown_media_id(board, monkeypatch):
    monkeypatch.setattr(S, 'get_media', lambda mid: None)
    assert S.start_run('deadbeef0001') == {'error': 'unknown media'}
    assert S._JOBS == {} and board == []


def test_start_run_refuses_a_registration_whose_file_is_gone(board, monkeypatch):
    monkeypatch.setattr(S, 'media_path', lambda mid: None)
    assert S.start_run('deadbeef0001') == {'error': 'source file missing'}
    assert board == []


def test_start_run_queues_a_job_makes_its_dirs_and_dispatches_the_worker(board):
    out = S.start_run('deadbeef0001')
    assert out['ok'] is True
    assert out['job'] == out['run_id'] and out['run_id'].startswith('deadbeef0001_')
    (j,) = S._JOBS.values()
    assert (j['state'], j['stage'], j['pct'], j['cancel'], j['error']) == ('queued', 'queued', 0.0, False, '')
    assert (j['media_id'], j['media_name'], j['frame'], j['frames_total']) == ('deadbeef0001', 'clip.mp4', 0, 0)
    assert j['log'] == [] and j['started_ts'] > 0 and j['started']
    rdir = os.path.join(S.RUNS_DIR, out['run_id'])
    assert j['log_path'] == os.path.join(rdir, 'run.log')
    assert os.path.isdir(os.path.join(rdir, 'frames'))
    assert os.path.isdir(os.path.join(rdir, 'crops'))
    (t,) = board
    assert t.daemon is True and t.target is S._worker
    assert t.args[:4] == (out['job'], out['run_id'], 'deadbeef0001', S.media_path('x'))


_FLAGS = ('do_landmarks', 'do_vlm', 'do_curiosity', 'do_probes')
_OPTS = {'start_s': 3.5, 'duration_s': 2.0, 'max_frames': '7', 'thresholds': {'pan': 0.2}}
_OPTS.update(do_landmarks=False, do_vlm=True, do_curiosity=False, do_probes=False)


def test_start_run_defaults_every_option_when_none_are_given(board):
    S.start_run('deadbeef0001')
    cfg = board[0].args[5]
    assert (cfg['start_s'], cfg['duration_s']) == (0.0, S.DEFAULT_WINDOW_S)
    assert tuple(cfg[k] for k in _FLAGS) == (True, False, True, True)
    assert (cfg['max_frames'], cfg['thresholds']) == (0, {})
    assert sorted(cfg) == sorted(('start_s', 'duration_s', 'max_frames', 'thresholds') + _FLAGS)


def test_start_run_passes_the_options_it_was_handed_through(board):
    S.start_run('deadbeef0001', _OPTS)
    cfg = board[0].args[5]
    assert (cfg['start_s'], cfg['duration_s']) == (3.5, 2.0)
    assert tuple(cfg[k] for k in _FLAGS) == (False, True, False, False)
    assert cfg['max_frames'] == 7 and cfg['thresholds'] == {'pan': 0.2}
    assert cfg['thresholds'] is not _OPTS['thresholds']


@pytest.mark.parametrize(
    ('opts', 'start_s', 'duration_s'),
    [
        ({'start_s': -5}, 0.0, None),
        ({'start_s': 'nope'}, 0.0, None),
        ({'start_s': None}, 0.0, None),
        ({'start_s': '2.5'}, 2.5, None),
        ({'duration_s': 'nope'}, 0.0, None),
        ({'duration_s': 0.0}, 0.0, 0.1),
        ({'duration_s': 10_000}, 0.0, 120.0),
        ({'max_frames': None}, 0.0, None),
    ],
)
def test_start_run_coerces_and_clamps_a_hostile_option_block(board, opts, start_s, duration_s):
    S.start_run('deadbeef0001', opts)
    cfg = board[0].args[5]
    assert cfg['start_s'] == start_s
    assert cfg['duration_s'] == (S.DEFAULT_WINDOW_S if duration_s is None else duration_s)
    assert 0.1 <= cfg['duration_s'] <= S.MAX_WINDOW_S
    assert cfg['max_frames'] == 0 if 'max_frames' in opts else True


def test_start_run_prunes_the_board_as_it_queues(board, monkeypatch):
    monkeypatch.setattr(S, '_JOB_KEEP', 1)
    _put('old0', state='done', started_ts=1.0)
    _put('old1', state='done', started_ts=2.0)
    out = S.start_run('deadbeef0001')
    assert sorted(S._JOBS) == sorted(['old1', out['job']])


# ── _extract ─────────────────────────────────────────────────────────────────


def _fake_subprocess(returncode=0, stderr='', raises=None):
    seen = {}

    def run(cmd, **kw):
        seen['cmd'] = cmd
        seen['kw'] = kw
        if raises is not None:
            raise raises
        return types.SimpleNamespace(returncode=returncode, stderr=stderr, stdout='')

    return types.SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError), seen


def test_extract_builds_a_passthrough_ffmpeg_call_and_returns_the_jpgs(tmp_path, monkeypatch):
    for fn in ('f000002.jpg', 'f000001.jpg', 'notes.txt'):
        (tmp_path / fn).write_bytes(b'x')
    fake, seen = _fake_subprocess()
    monkeypatch.setattr(S, 'subprocess', fake)
    lines = []
    got, err = S._extract('/videos/clip.mp4', str(tmp_path), 1.5, 0.25, lines.append)
    assert (got, err) == (['f000001.jpg', 'f000002.jpg'], '')
    cmd = seen['cmd']
    assert cmd[0] == S.FFMPEG
    assert cmd[cmd.index('-fps_mode') + 1] == 'passthrough'
    assert cmd[cmd.index('-ss') + 1] == '1.500'
    assert cmd[cmd.index('-t') + 1] == '0.250'
    assert cmd[cmd.index('-i') + 1] == '/videos/clip.mp4'
    assert cmd[-1] == os.path.join(str(tmp_path), 'f%06d.jpg')
    assert seen['kw']['timeout'] == 1800 and seen['kw']['capture_output'] is True
    assert lines[0].startswith('extract: 2 frames in ')
    assert 'window 1.50s +0.25s, fps_mode=passthrough' in lines[0]


def test_extract_reports_a_non_zero_ffmpeg_return_code_with_its_stderr(tmp_path, monkeypatch):
    fake, _ = _fake_subprocess(returncode=1, stderr='moov atom not found' + 'x' * 500)
    monkeypatch.setattr(S, 'subprocess', fake)
    got, err = S._extract('/videos/clip.mp4', str(tmp_path), 0.0, 1.0, lambda m: None)
    assert got == []
    assert err.startswith('ffmpeg rc=1: moov atom not found')
    assert len(err) == len('ffmpeg rc=1: ') + 400


def test_extract_reports_a_non_zero_code_even_with_no_stderr_at_all(tmp_path, monkeypatch):
    fake, _ = _fake_subprocess(returncode=69, stderr=None)
    monkeypatch.setattr(S, 'subprocess', fake)
    assert S._extract('/v.mp4', str(tmp_path), 0.0, 1.0, lambda m: None) == ([], 'ffmpeg rc=69: ')


def test_extract_turns_a_timeout_into_a_message_rather_than_an_exception(tmp_path, monkeypatch):
    fake, _ = _fake_subprocess(raises=subprocess.TimeoutExpired(cmd='ffmpeg', timeout=1800))
    monkeypatch.setattr(S, 'subprocess', fake)
    got, err = S._extract('/v.mp4', str(tmp_path), 0.0, 1.0, lambda m: None)
    assert got == []
    assert err.startswith('ffmpeg failed: TimeoutExpired: ')


# ── _worker ──────────────────────────────────────────────────────────────────


_STAGES = ('open_run', 'extract_frames', 'measure_frames', 'temporal_structure', 'track_landmarks')
_STAGES += ('embed_frames', 'run_detectors', 'write_outputs')


def _trace_stages(monkeypatch, fails_at=None, exc=None):
    """Replace every `scan_stages` entry point with a recorder; `_new_run` yields a sentinel."""
    calls = []
    run = types.SimpleNamespace(tag='the-run')
    monkeypatch.setattr(ST, '_new_run', lambda *a: (calls.append(('_new_run',) + a), run)[1])
    for name in _STAGES:

        def stage(r, _name=name):
            calls.append(_name)
            if _name == fails_at:
                raise exc

        monkeypatch.setattr(ST, name, stage)
    monkeypatch.setattr(ST, '_record_failure', lambda r, e: calls.append(('_record_failure', r, e)))
    return calls, run


def test_the_worker_runs_every_stage_once_in_the_documented_order(monkeypatch):
    calls, run = _trace_stages(monkeypatch)
    S._worker('jid1', 'rid1', 'm1', '/videos/clip.mp4', {'name': 'clip.mp4'}, {'do_vlm': False})
    assert calls[0][0] == '_new_run'
    assert tuple(calls[1:]) == _STAGES


def test_the_worker_hands_the_stages_the_run_dir_and_the_two_board_callables(monkeypatch, tmp_path):
    monkeypatch.setattr(S, 'RUNS_DIR', str(tmp_path))
    calls, _ = _trace_stages(monkeypatch)
    _put('jid1', state='running', cancel=True)
    cfg = {'do_vlm': False}
    meta = {'name': 'clip.mp4'}
    S._worker('jid1', 'rid1', 'm1', '/videos/clip.mp4', meta, cfg)
    _, jid, rid, mid, src, got_meta, got_cfg, rdir, log, cancelled = calls[0]
    assert (jid, rid, mid, src) == ('jid1', 'rid1', 'm1', '/videos/clip.mp4')
    assert got_meta is meta and got_cfg is cfg
    assert rdir == os.path.join(str(tmp_path), 'rid1')
    assert cancelled() is True
    log('a line from a stage')
    assert S._JOBS['jid1']['log'][0].endswith('a line from a stage')


def test_a_stage_that_raises_is_recorded_and_stops_the_run_without_escaping(monkeypatch):
    boom = RuntimeError('mediapipe tier unavailable')
    calls, run = _trace_stages(monkeypatch, fails_at='track_landmarks', exc=boom)
    S._worker('jid1', 'rid1', 'm1', '/v.mp4', {}, {})
    assert tuple(calls[1:-1]) == _STAGES[:5]
    assert calls[-1] == ('_record_failure', run, boom)


# ── _thin_landmarks ──────────────────────────────────────────────────────────


def test_thin_landmarks_drops_the_mesh_and_the_blendshapes_but_keeps_the_scalars():
    item = {'score': 0.9, 'pts': [[0, 0]] * 468, 'blendshapes': {'smile': 1.0}, 'bbox': [1, 2]}
    out = S._thin_landmarks({'pose': {'state': 'found', 'n_strict': 1, 'n_weak': 0, 'items': [item]}})
    assert out['pose']['items'] == [{'score': 0.9, 'bbox': [1, 2]}]
    assert (out['pose']['state'], out['pose']['n_strict'], out['pose']['n_weak']) == ('found', 1, 0)
    assert 'reason' not in out['pose']


def test_thin_landmarks_defaults_every_absent_tier_to_unmeasurable():
    out = S._thin_landmarks({'face': None})
    assert sorted(out) == ['face', 'hand', 'pose']
    for tier in out.values():
        assert tier == {'state': 'unmeasurable', 'n_strict': 0, 'n_weak': 0, 'items': []}


def test_thin_landmarks_carries_a_stated_reason_over():
    out = S._thin_landmarks({'hand': {'state': 'unmeasurable', 'reason': 'stylised input', 'items': None}})
    assert out['hand']['reason'] == 'stylised input'
    assert out['hand']['items'] == []


@pytest.mark.parametrize('bad', [None, [], 'frame', 7])
def test_thin_landmarks_refuses_anything_that_is_not_a_frame_record(bad):
    assert S._thin_landmarks(bad) == {}


# ── _segment_shots ───────────────────────────────────────────────────────────


def _pf(n, luma_std=40.0):
    return [{'luma_std': luma_std} for _ in range(n)]


def _pair(frm, hist, moved, cam=1.0):
    return {'from_frame': frm, 'hist_corr': hist, 'diff_frac_moved': moved, 'cam_fit_ok': cam}


def test_a_window_with_no_cut_is_one_shot_spanning_every_frame():
    shots = S._segment_shots(_pf(10), {1: _pair(0, 0.99, 0.01)}, [0, 2, 4], 24.0)
    assert shots == [{'index': 0, 'start': 0, 'end': 9, 'frames': 10, 'seconds': round(10 / 24.0, 3), 'unique_cels': 3}]


def test_a_collapsed_histogram_over_a_moved_picture_cuts_the_window_in_two():
    shots = S._segment_shots(_pf(10), {5: _pair(4, 0.50, 0.60, cam=0.2)}, list(range(10)), 25.0)
    assert [(s['start'], s['end'], s['frames']) for s in shots] == [(0, 4, 5), (5, 9, 5)]
    assert 'cut_in' not in shots[0]
    score = round((1.0 - 0.50) * 0.6 + 0.60 * 0.4, 4)
    assert shots[1]['cut_in'] == {
        'frame': 5, 'score': score, 'hist_corr': 0.5, 'frac_moved': 0.6, 'cam_fit_ok': 0.2,
    }  # fmt: skip
    assert shots[1]['seconds'] == 0.2


def test_a_histogram_below_the_hard_floor_cuts_whatever_moved():
    (_, second) = S._segment_shots(_pf(6), {3: _pair(2, 0.30, 0.0)}, [], 24.0)
    assert second['start'] == 3 and second['unique_cels'] == 0


@pytest.mark.parametrize('pm', [_pair(2, 0.60, 0.90), _pair(2, 0.40, 0.40), _pair(2, 0.99, 0.99)])
def test_a_whip_pan_or_a_surviving_histogram_is_not_a_cut(pm):
    assert len(S._segment_shots(_pf(6), {3: pm}, [], 24.0)) == 1


@pytest.mark.parametrize('flat_at', [2, 3])
def test_a_flash_or_fade_edge_is_never_read_as_a_cut(flat_at):
    per_frame = _pf(6)
    per_frame[flat_at] = {'luma_std': 1.0}
    assert len(S._segment_shots(per_frame, {3: _pair(2, 0.10, 0.90)}, [], 24.0)) == 1


def test_a_missing_luma_std_reads_as_bright_but_an_explicit_none_reads_as_flat():
    per_frame = [{}, {'luma_std': None}, {}, {}]
    assert len(S._segment_shots(per_frame, {3: _pair(2, 0.10, 0.90)}, [], 24.0)) == 2  # 2 and 3 both default
    assert len(S._segment_shots(per_frame, {2: _pair(1, 0.10, 0.90)}, [], 24.0)) == 1  # frame 1 is None → flat


def test_a_cut_on_the_first_frame_yields_no_empty_leading_shot():
    shots = S._segment_shots(_pf(4), {0: _pair(-1, 0.10, 0.90)}, [0, 1], 24.0)
    assert [(s['index'], s['start'], s['end']) for s in shots] == [(0, 0, 3)]


def test_a_pair_with_no_from_frame_falls_back_to_the_frame_before_it():
    per_frame = _pf(6)
    per_frame[2] = {'luma_std': 0.0}
    assert len(S._segment_shots(per_frame, {3: {'hist_corr': 0.1, 'diff_frac_moved': 0.9}}, [], 24.0)) == 1


# ── _build_ledger ────────────────────────────────────────────────────────────


_TAXONOMY = {
    'by_id': {
        'anim.pop': {'label': 'Pop', 'group': 'animation', 'applies_to': '2d', 'detector_tier': 'A'},
        'anim.smear': {'label': 'Smear', 'group': 'animation', 'detector_tier': 'B'},
        'cam.shake': {'label': 'Shake', 'group': 'camera', 'detector_tier': 'A'},
        'cam.zoom': {'group': 'camera'},
    }
}


@pytest.fixture
def tax(monkeypatch):
    monkeypatch.setattr(S, 'taxonomy', lambda: {'by_id': dict(_TAXONOMY['by_id'])})


def test_the_ledger_sorts_every_taxonomy_entry_into_its_state(tax):
    results = [
        {'id': 'anim.pop', 'events': [{'frame': 3}, {'frame': 1}, {'frame': 1}, {'no_frame': 1}], 'best': 0.8},
        {'id': 'anim.smear', 'events': [], 'best': 0.1, 'threshold': 0.4, 'unit': 'px', 'note': 'calibrate me'},
        {'id': 'cam.shake', 'state': 'unmeasurable', 'reason': 'no subject found'},
    ]
    led = S._build_ledger(results, lambda m: None)
    assert [e['id'] for e in led['found']] == ['anim.pop']
    assert [e['id'] for e in led['not_found']] == ['anim.smear']
    assert [e['id'] for e in led['unmeasurable']] == ['cam.shake']
    assert [e['id'] for e in led['not_detectable']] == ['cam.zoom']
    assert led['found'][0]['n_events'] == 4
    assert led['found'][0]['frames'] == [1, 3]
    assert led['not_found'][0]['note'] == 'calibrate me'
    assert led['not_found'][0]['threshold'] == 0.4 and led['not_found'][0]['unit'] == 'px'


def test_every_entry_carries_its_label_group_domain_and_declared_tier(tax):
    led = S._build_ledger([], lambda m: None)
    by_id = {e['id']: e for e in led['not_detectable']}
    assert by_id['anim.pop']['label'] == 'Pop'
    assert (by_id['anim.pop']['group'], by_id['anim.pop']['domain']) == ('animation', 'anim')
    assert by_id['anim.pop']['applies_to'] == '2d'
    assert by_id['anim.smear']['applies_to'] == 'both'
    assert by_id['cam.zoom']['label'] == 'cam.zoom' and by_id['cam.zoom']['declared_tier'] == ''
    assert "taxonomy declares tier 'A'" in by_id['anim.pop']['reason']
    assert "taxonomy declares tier '?'" in by_id['cam.zoom']['reason']


def test_an_unmeasurable_result_with_no_reason_gets_the_default_one(tax):
    led = S._build_ledger([{'id': 'cam.shake', 'state': 'unmeasurable'}], lambda m: None)
    assert led['unmeasurable'][0]['reason'] == 'precondition failed'


def test_a_detector_keyed_outside_the_taxonomy_is_surfaced_as_a_loud_orphan(tax):
    lines = []
    fired = {'id': 'bogus.fired', 'events': [{'frame': 2}], 'best': 1.0, 'unit': 'px'}
    quiet_in = {'id': 'bogus.quiet', 'events': [], 'threshold': 0.5, 'note': 'wired to nothing'}
    led = S._build_ledger([fired, quiet_in], lines.append)
    assert lines[0].startswith('WARNING: 2 detector(s) keyed to ids absent from the taxonomy')
    assert 'bogus.fired, bogus.quiet' in lines[0]
    assert not lines[0].endswith('…')
    (orphan,) = [e for e in led['found'] if e['id'] == 'bogus.fired']
    assert orphan['orphan'] is True
    assert (orphan['domain'], orphan['applies_to'], orphan['label']) == ('bogus', 'both', 'bogus.fired')
    assert orphan['n_events'] == 1 and orphan['frames'] == [2]
    quiet = [e for e in led['not_found'] if e['id'] == 'bogus.quiet'][0]
    assert quiet['n_events'] == 0 and quiet['frames'] == []


def test_more_than_ten_orphans_are_summarised_with_an_ellipsis(tax):
    lines = []
    S._build_ledger([{'id': f'bogus.{i:02d}', 'events': []} for i in range(12)], lines.append)
    assert lines[0].startswith('WARNING: 12 detector(s)')
    assert lines[0].endswith('…')
    assert 'bogus.09' in lines[0] and 'bogus.11' not in lines[0]


def test_an_empty_taxonomy_and_no_results_is_four_empty_buckets(monkeypatch):
    monkeypatch.setattr(S, 'taxonomy', dict)
    led = S._build_ledger([], lambda m: None)
    assert led == dict.fromkeys(('found', 'not_found', 'unmeasurable', 'not_detectable'), [])


def test_the_last_result_for_a_repeated_id_is_the_one_the_ledger_keeps(tax):
    twice = [{'id': 'anim.pop', 'events': [{'frame': 1}]}, {'id': 'anim.pop', 'events': []}]
    led = S._build_ledger(twice, lambda m: None)
    assert led['found'] == []
    assert [e['id'] for e in led['not_found']] == ['anim.pop']
