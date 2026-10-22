# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for `zyg_workflows.pipeline_char2d`: brief parsing, the
job-registry plumbing, the subprocess wrappers, the fourteen-stage order and
the entry point, driven with fake stage modules and fake subprocesses. No
Blender, no ffmpeg, no MediaPipe, no thread left running, nothing written
outside tmp_path."""

import json
import os
import subprocess
import threading
import types

import pytest
from PIL import Image

import zyg_workflows
from zyg_workflows import pipeline_char2d as C


# ── brief parsing ────────────────────────────────────────────────────────────


def test_parse_directive_reads_name_numbers_cut_and_four_colours():
    """The Run button's one-line form, exactly as the board sends it."""
    assert C.parse_directive('Mika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a') == {
        'name': 'Mika',
        'gender': 0.2,
        'age': 19.0,
        'height_m': 1.68,
        'hair_cut': 'bob',
        'skin': '#f5cfb5',
        'hair': '#2a1a12',
        'top': '#3b5fa3',
        'bottom': '#2b2f3a',
    }


def test_parse_directive_takes_the_colours_it_finds_whatever_the_separator():
    """Colours are pattern-matched first, so their separators and count are free."""
    brief = C.parse_directive('Abel, 1, 40, 1.8, LONG, #abc, #def')
    assert (brief['hair_cut'], brief['skin'], brief['hair']) == ('long', '#abc', '#def')
    assert 'top' not in brief
    bare = C.parse_directive('Noor, 0.5, 30, 1.7, short')
    assert set(bare) == {'name', 'gender', 'age', 'height_m', 'hair_cut'}


@pytest.mark.parametrize(
    ('text', 'message'),
    [
        ('', 'a character brief is required'),
        (None, 'a character brief is required'),
        ('   ', 'a character brief is required'),
        ('Mika, 0.2, 19, 1.68', 'got 4 field'),
        ('Mika, x, 19, 1.68, bob', "gender must be a number, got 'x'"),
        ('Mika, 0.2, old, 1.68, bob', "age must be a number, got 'old'"),
        ('Mika, 0.2, 19, tall, bob', "height_m must be a number, got 'tall'"),
        ('Mika, 2.0, 19, 1.68, bob', 'gender must be 0..1'),
        ('Mika, -0.1, 19, 1.68, bob', 'gender must be 0..1'),
        ('Mika, 0.2, 19, 168, bob', 'height_m must be in metres'),
        ('Mika, 0.2, 19, 0.2, bob', 'height_m must be in metres'),
        ('Mika, 0.2, 19, 1.68, mohawk', 'hair_cut must be one of bob|short|long'),
    ],
)
def test_parse_directive_refuses_a_malformed_brief(text, message):
    """Every rejection says which field was wrong and what it got."""
    with pytest.raises(ValueError) as exc:
        C.parse_directive(text)
    assert message in str(exc.value)


def test_normalise_brief_copies_a_dict_and_normalises_the_cut():
    """A structured brief is copied, not aliased, and its cut is lowercased."""
    src = {'name': 'Mika'}
    assert C.normalise_brief(brief=src) == {'name': 'Mika', 'hair_cut': 'bob'}
    assert C.normalise_brief(brief=src) is not src
    assert C.normalise_brief(brief={'name': 'Mika', 'hair_cut': ' Short '})['hair_cut'] == 'short'


@pytest.mark.parametrize(
    ('brief', 'message'),
    [({'name': '  '}, 'brief has no "name"'), ({'name': 'Mika', 'hair_cut': 'mohawk'}, 'hair_cut must be one of')],
)
def test_normalise_brief_refuses_a_broken_dict(brief, message):
    with pytest.raises(ValueError, match=message):
        C.normalise_brief(brief=brief)


@pytest.mark.parametrize('empty', [None, {}, [], 'not a dict'])
def test_normalise_brief_falls_through_to_the_directive(empty):
    """Anything that is not a non-empty dict means the one-line form is used."""
    assert C.normalise_brief(brief=empty, directive='Mika, 0.2, 19, 1.68, bob')['name'] == 'Mika'


def test_describe_renders_the_one_line_directive_a_card_shows():
    brief = C.parse_directive('Mika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a')
    assert C.describe(brief) == 'Mika, 0.2, 19.0, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a'
    assert C.describe({'name': 'Noor'}) == 'Noor, None, None, None, None, '


# ── job registry plumbing ────────────────────────────────────────────────────


@pytest.fixture
def jobs():
    """The shared registry, with every job a test added removed afterwards."""
    before = set(C._jobs())
    yield C._jobs()
    for pid in set(C._jobs()) - before:
        C._jobs().pop(pid, None)


def test_mk_job_registers_a_running_char2d_card(jobs):
    """The registry contract pipeline_kidsmusic established, field for field."""
    pid = C._mk_job(' make Mika ', {'wav': '/w.wav'}, {'name': 'Mika'})
    job = jobs[pid]
    assert job['job_id'] == pid == job['pipeline_id']
    assert (job['status'], job['department']) == ('running', 'char2d')
    assert job['current_stage'] == C.STAGES[0]
    assert job['directive'] == 'make Mika'
    assert job['pipeline_options'] == {'wav': '/w.wav'}
    assert job['brief'] == {'name': 'Mika'}
    assert isinstance(job['stop_event'], threading.Event)
    assert job['result'] is None and job['error'] is None
    assert job['started'] == job['started'].strip() and C._now_iso()
    bare = jobs[C._mk_job(None, None, {'name': 'Mika'})]
    assert (bare['directive'], bare['pipeline_options']) == ('', {})


def test_finish_closes_a_job_green_or_red_and_ends_its_open_timeline_rows(jobs):
    pid = C._mk_job('d', {}, {'name': 'Mika'})
    C._set_stage(pid, 'Demo Reel')
    C._finish(pid, True, result={'demo': 'demo.mp4'})
    job = jobs[pid]
    assert (job['status'], job['current_stage'], job['error']) == ('completed', 'Demo Reel', None)
    assert job['result'] == {'demo': 'demo.mp4'}
    assert job['ended']
    assert job['stage_timeline'][-1]['status'] == 'completed'
    assert job['stage_timeline'][-1]['ended_at'] is not None

    red = C._mk_job('d', {}, {'name': 'Mika'})
    C._set_stage(red, 'Six-View Render')
    C._finish(red, False, error='boom')
    assert (jobs[red]['status'], jobs[red]['current_stage'], jobs[red]['error']) == ('failed', 'Error', 'boom')
    assert jobs[red]['stage_timeline'][-1]['status'] == 'failed'


def test_finish_reads_the_stop_event_first_and_keeps_the_stop_reason(jobs):
    """A halted run is 'stopped', not 'failed', and keeps the reason it recorded."""
    pid = C._mk_job('d', {}, {'name': 'Mika'})
    C._set_stage(pid, 'Mouth Sprites')
    jobs[pid]['stop_event'].set()
    jobs[pid]['error'] = 'stopped at mouth sprites'
    C._finish(pid, True, error='ignored')
    assert jobs[pid]['status'] == 'stopped'
    assert jobs[pid]['current_stage'] == 'Stopped'
    assert jobs[pid]['error'] == 'stopped at mouth sprites'
    assert jobs[pid]['stage_timeline'][-1]['status'] == 'stopped'
    mute = C._mk_job('d', {}, {'name': 'Mika'})
    jobs[mute]['stop_event'].set()
    C._finish(mute, False)
    assert jobs[mute]['error'] == 'halted by operator'


def test_a_job_removed_mid_run_is_a_no_op_everywhere():
    """A card the operator deleted must not raise inside the worker thread."""
    C._finish('no-such-job', True)
    C._set_stage('no-such-job', 'Demo Reel')
    C._log_for('no-such-job')('hello')


def test_log_for_appends_dict_events_the_kanban_poll_can_read(jobs):
    """Live-Tail entries must be {level, ts, stage, msg} dicts, never bare strings,
    truncated to 200 characters and stamped with the stage the card is showing."""
    pid = C._mk_job('d', {}, {'name': 'Mika'})
    C._log_for(pid)('turnaround: front -> back')
    ev = jobs[pid]['debug_events'][-1]
    assert set(ev) == {'level', 'ts', 'stage', 'msg'}
    assert (ev['level'], ev['stage']) == ('INFO', C.STAGES[0])
    assert ev['msg'] == 'turnaround: front -> back'
    jobs[pid]['current_stage'] = ''
    C._log_for(pid)('x' * 500)
    assert jobs[pid]['debug_events'][-1]['msg'] == 'x' * 200
    assert jobs[pid]['debug_events'][-1]['stage'] == C.STAGES[0]


@pytest.mark.parametrize(
    'msg',
    [
        'blender failed', 'rhubarb unavailable', 'ffmpeg error', 'could not open png', 'missing anchors',
        'halted by operator', '1 frame flagged', 'sprites ship degraded', 'view skipped', 'seal not verified',
        'refused to overwrite', 'no hands detected', 'hand gate: clean',
    ],
)  # fmt: skip
def test_log_for_raises_the_level_to_warn_on_every_trouble_word(jobs, msg):
    pid = C._mk_job('d', {}, {'name': 'Mika'})
    C._log_for(pid)(msg)
    assert jobs[pid]['debug_events'][-1]['level'] == 'WARN'


def test_set_stage_advances_the_card_and_ends_the_previous_row(jobs):
    pid = C._mk_job('d', {}, {'name': 'Mika'})
    C._set_stage(pid, 'MPFB Body Build')
    C._set_stage(pid, 'Six-View Render')
    tl = jobs[pid]['stage_timeline']
    assert [e['name'] for e in tl] == ['MPFB Body Build', 'Six-View Render']
    assert tl[0]['status'] == 'completed' and tl[0]['ended_at'] is not None
    assert tl[1]['status'] == 'running' and tl[1]['ended_at'] is None
    assert jobs[pid]['current_stage'] == 'Six-View Render'


# ── subprocess wrappers ──────────────────────────────────────────────────────


class _FakeStdout:
    def __init__(self, lines, close_raises=False):
        self._lines = list(lines)
        self._close_raises = close_raises
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        if self._close_raises:
            raise OSError('already gone')
        self.closed = True


class _FakeProc:
    """A Popen stand-in: canned stdout lines, a recording stdin, an exit code."""

    def __init__(self, lines=(), rc=0, close_raises=False):
        self.stdout = _FakeStdout(lines, close_raises)
        self.written = []
        self.stdin_closed = False
        self.stdin = types.SimpleNamespace(write=self.written.append, close=self._close_stdin)
        self._rc = rc
        self.terminated = False

    def _close_stdin(self):
        self.stdin_closed = True

    def terminate(self):
        self.terminated = True

    def wait(self):
        return self._rc


def _fake_popen(monkeypatch, proc, seen):
    def _popen(cmd, **kw):
        seen.append(list(cmd))
        return proc

    monkeypatch.setattr(C.subprocess, 'Popen', _popen)
    return proc


def test_blender_runs_under_the_shared_lock_and_streams_every_line(monkeypatch):
    """The flock path and the binary are fixed; progress lines reach `on_line`."""
    proc = _FakeProc(['CLASSIFY done\n', '\n', 'CAMERA front\n'], rc=0)
    seen = []
    _fake_popen(monkeypatch, proc, seen)
    lines, logged = [], []
    assert C._blender(['-b', '/abs/char2d_build.py', '--', 'x'], logged.append, on_line=lines.append) == 0
    assert seen[0][:3] == ['flock', C.BLENDER_LOCK, C.BLENDER]
    assert lines == ['CLASSIFY done', 'CAMERA front']
    assert logged == ['blender: blender -b char2d_build.py -- x']
    assert proc.stdout.closed


def test_blender_terminates_the_process_and_raises_halted_on_abort(monkeypatch):
    """The stop button must kill Blender, not wait five minutes for it."""
    proc = _FakeProc(['one\n', 'two\n'], rc=0)
    _fake_popen(monkeypatch, proc, [])
    seen = []
    with pytest.raises(C.Halted, match='halted during blender'):
        C._blender(['-b'], lambda m: None, on_line=seen.append, should_abort=lambda: True)
    assert proc.terminated and seen == ['one']


def test_blender_survives_a_stdout_that_cannot_be_closed(monkeypatch):
    """Closing a dead pipe must not mask the exit code Blender gave."""
    _fake_popen(monkeypatch, _FakeProc(['x\n'], rc=3, close_raises=True), [])
    assert C._blender(['-b'], lambda m: None) == 3


def test_ffmpeg_returns_the_completed_process_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr(
        C.subprocess,
        'run',
        lambda cmd, **kw: calls.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, '', ''),
    )
    assert C._ffmpeg(['-i', 'a.mp4', 'out.mp4'], lambda m: None).returncode == 0
    assert calls[0][1:4] == ['-y', '-loglevel', 'error']
    assert calls[0][-1] == 'out.mp4'


@pytest.mark.parametrize(('rc', 'err', 'tail'), [(1, 'y' * 400, 300), (2, None, 0)])
def test_ffmpeg_logs_the_tail_of_stderr_and_raises(monkeypatch, rc, err, tail):
    monkeypatch.setattr(C.subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(cmd, rc, '', err))
    logged = []
    with pytest.raises(RuntimeError, match='ffmpeg exit %d' % rc):
        C._ffmpeg(['-i', 'a.mp4'], logged.append)
    assert logged[0] == 'ffmpeg failed: ' + (err or '')[-300:]
    assert len(logged[0]) == len('ffmpeg failed: ') + tail


def test_pipe_frames_writes_every_buffer_and_asks_for_a_silent_track(monkeypatch):
    """A silent AAC track is what lets the demo reel be one concat filter."""
    proc = _FakeProc(rc=0)
    seen = []
    _fake_popen(monkeypatch, proc, seen)
    assert C._pipe_frames([b'a', b'b'], (768, 1152), '/run/clip.mp4') == '/run/clip.mp4'
    assert proc.written == [b'a', b'b'] and proc.stdin_closed
    cmd = seen[0]
    assert cmd[cmd.index('-s') + 1] == '768x1152'
    assert cmd[cmd.index('-r') + 1] == str(C.FPS)
    assert 'anullsrc=channel_layout=stereo:sample_rate=44100' in cmd
    assert cmd[cmd.index('-c:a') + 1] == 'aac' and '-shortest' in cmd
    assert cmd[-1] == '/run/clip.mp4'


def test_pipe_frames_can_leave_the_audio_track_out(monkeypatch):
    seen = []
    _fake_popen(monkeypatch, _FakeProc(rc=0), seen)
    C._pipe_frames([], (10, 20), '/run/mute.mp4', silent_audio=False)
    assert '-c:a' not in seen[0] and 'lavfi' not in seen[0]


def test_pipe_frames_raises_on_a_nonzero_encoder(monkeypatch):
    _fake_popen(monkeypatch, _FakeProc(rc=4), [])
    with pytest.raises(RuntimeError, match=r'ffmpeg exit 4 writing /run/clip.mp4'):
        C._pipe_frames([b'a'], (10, 20), '/run/clip.mp4')


def test_on_white_composites_transparency_over_white_and_resizes_to_the_cell(tmp_path):
    """A cel still with an alpha hole must read as white paper, not black."""
    hole = tmp_path / 'hole.png'
    Image.new('RGBA', (4, 6), (0, 0, 0, 0)).save(hole)
    img = C._on_white(hole)
    assert (img.mode, img.size, img.getpixel((0, 0))) == ('RGB', (4, 6), (255, 255, 255))
    view = tmp_path / 'view.png'
    Image.new('RGBA', (8, 12), (10, 20, 30, 255)).save(view)
    assert C._on_white(view, size=(4, 6)).size == (4, 6)
    assert C._on_white(view, size=(8, 12)).getpixel((0, 0)) == (10, 20, 30)


def test_probe_duration_reads_the_container_duration_or_falls_back_to_zero(monkeypatch):
    """A probe is not the run: a missing ffprobe must not fail a delivered reel."""
    monkeypatch.setattr(C.subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, ' 12.5\n', ''))
    assert C._probe_duration('/run/demo.mp4') == 12.5

    def _boom(cmd, **kw):
        raise OSError('no ffprobe')

    monkeypatch.setattr(C.subprocess, 'run', _boom)
    assert C._probe_duration('/run/demo.mp4') == 0.0


# ── the fourteen stages ──────────────────────────────────────────────────────

_RES = (8, 12)


def _fake_stage_modules(monkeypatch, out_dir):
    """Stand-ins for `pipeline_char2d_stages` and `char2d_mouth`: `run_char2d`
    imports both with `from zyg_workflows import …` inside its own body, so the
    package attribute is what the import machinery reads."""
    os.makedirs(os.path.join(out_dir, 'views'), exist_ok=True)
    views = {}
    for i, name in enumerate(('front', 'back')):
        rel = os.path.join('views', '%s.png' % name)
        Image.new('RGBA', _RES, (i * 10, 20, 30, 255)).save(os.path.join(out_dir, rel))
        views[name] = {'file': rel, 'yaw': float(i * 45)}
    blend = os.path.join(out_dir, 'character.blend')
    views_json = os.path.join(out_dir, 'views.json')
    gestures_dir = os.path.join(out_dir, 'gestures')
    os.makedirs(gestures_dir, exist_ok=True)
    gate = {'n_frames': 2, 'flagged': [], 'hard': [], 'unknown': 0}
    rendered = [{'spec': {'name': 'wave'}, 'render': {'res': list(_RES)}}]

    def _build_views(o, brief_path, log, stage, should_abort):
        stage('Cel Shader + Ink Lines')
        stage('Six-View Render')
        return views_json, blend, {'height_m': 1.68}, views, _RES

    def _draw_all_views(vj, mouth_dir):
        os.makedirs(mouth_dir, exist_ok=True)
        return [{'view': 'front', 'files': {'closed': os.path.join(mouth_dir, 'front_closed.png')}}]

    def _render_keys(b, o, log, should_abort, guard):
        guard()
        return gestures_dir, rendered

    st = types.SimpleNamespace(
        build_views=_build_views,
        collect_anchors=lambda v: {k: {'kind': k} for k in v},
        anchors_line=lambda a: 'anchors: %d' % len(a),
        resolve_wav=lambda opts: opts.get('wav') or '/elsewhere/line.wav',
        timing_line=lambda t: 'timing: %s' % t['duration_s'],
        render_gesture_keyframes=_render_keys,
        run_hand_gate=lambda r, g, o: gate,
        gate_verdict=lambda g: ({'hand_gate': 'clean'}, ['hand gate: clean']),
        encode_gesture_clips=lambda r, g, o, log, guard: ({'wave': {'front': 'gestures/wave/front.mp4'}}, _RES),
        build_manifest=lambda **kw: {
            'views': kw['views'],
            'gestures': {'wave': {}},
            'mouth': kw['mouth_files'],
            'hand_gate': {'verdict': kw['hand_gate']},
        },
        demo_reel_args=lambda reel, res, demo: ['-i', *reel, str(demo)],
    )
    mouth = types.SimpleNamespace(
        SHAPES=('closed', 'mid', 'open'),
        draw_all_views=_draw_all_views,
        build_timing=lambda wav, fps=24: {'duration_s': 6.25, 'wav': wav, 'fps': fps},
        render_talking_clip=lambda png, md, wav, out, fps=24, timing=None: {'frames': 150},
    )
    monkeypatch.setattr(zyg_workflows, 'pipeline_char2d_stages', st, raising=False)
    monkeypatch.setattr(zyg_workflows, 'char2d_mouth', mouth, raising=False)
    sealed, ffmpeg = [], []
    monkeypatch.setattr(C, '_seal', types.SimpleNamespace(seal=lambda p, **kw: sealed.append(p)))
    monkeypatch.setattr(C, '_ffmpeg', lambda args, log: ffmpeg.append(list(args)))
    monkeypatch.setattr(C, '_probe_duration', lambda p: 9.5)
    return {'sealed': sealed, 'ffmpeg': ffmpeg}


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def test_run_char2d_delivers_every_artefact_in_order(tmp_path, monkeypatch):
    """The whole workflow on fake stages: the order, the files and the seals."""
    out_dir = str(tmp_path / 'deep' / 'run')
    calls = _fake_stage_modules(monkeypatch, out_dir)
    logged, stages = [], []
    result = C.run_char2d({'name': 'Mika', 'hair_cut': 'bob'}, out_dir, logged.append, stages.append, {}, lambda: False)

    assert stages[:3] == ['Character Brief', 'MPFB Body Build', 'Cel Shader + Ink Lines']
    assert stages[-1] == 'Demo Reel'
    for name in ('Turnaround Sheet', 'Mouth Anchors', 'Hand Anatomy Gate', 'Sprite Manifest'):
        assert name in stages

    assert _read(os.path.join(out_dir, 'brief.json'))['name'] == 'Mika'
    assert Image.open(os.path.join(out_dir, 'turnaround.png')).size == (_RES[0] // 2 * 2, _RES[1] // 2)
    assert set(_read(os.path.join(out_dir, 'anchors.json'))) == {'front', 'back'}
    assert _read(os.path.join(out_dir, 'timing.json'))['duration_s'] == 6.25
    assert _read(os.path.join(out_dir, 'gestures', 'anatomy.json'))['n_frames'] == 2
    manifest = _read(os.path.join(out_dir, 'sprites.json'))
    assert manifest['demo'] == {'file': 'demo.mp4', 'clips': 2, 'duration_s': 9.5}
    assert manifest['hand_gate'] == {'verdict': 'clean'}

    assert result['hand_gate'] == 'clean'
    assert result['out_dir'] == out_dir and result['clips'] == 1
    assert result['demo'] == os.path.join(out_dir, 'demo.mp4')
    assert result['talk'] == os.path.join(out_dir, 'talk', 'talk_front.mp4')
    assert [os.path.basename(p) for p in calls['sealed']] == ['turnaround.png', 'demo.mp4']
    assert calls['ffmpeg'][0][-1] == os.path.join(out_dir, 'demo.mp4')
    assert 'turnaround: front → back' in ' '.join(logged)
    assert 'mouth sprites: 1 views x 3 shapes' in logged
    assert 'talking clip: 150 frames at 24 fps -> talk/talk_front.mp4' in logged
    assert 'sprites.json: 2 views, 1 gestures, 1 mouth sets' in logged
    assert 'demo reel: 2 clips, 9.5 s -> demo.mp4' in logged


def test_run_char2d_stops_at_the_first_guard_when_the_operator_pressed_stop(tmp_path, monkeypatch):
    """Halted is raised before any Blender work, with the brief already on disk."""
    out_dir = str(tmp_path / 'run')
    _fake_stage_modules(monkeypatch, out_dir)
    stages = []
    with pytest.raises(C.Halted, match='halted by operator'):
        C.run_char2d({'name': 'Mika'}, out_dir, lambda m: None, stages.append, {}, lambda: True)
    assert stages == ['Character Brief']
    assert os.path.isfile(os.path.join(out_dir, 'brief.json'))
    assert not os.path.exists(os.path.join(out_dir, 'turnaround.png'))


# ── entry point ──────────────────────────────────────────────────────────────


class _SyncThread:
    """Runs the worker on the calling thread, so no thread leaks into the suite."""

    def __init__(self, target=None, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture
def sync_start(monkeypatch, tmp_path):
    """start_char2d with its output root in tmp_path and no real thread."""
    monkeypatch.setattr(C, '_OUT_ROOT', str(tmp_path / 'char2d'))
    monkeypatch.setattr(C, 'threading', types.SimpleNamespace(Event=threading.Event, Thread=_SyncThread))
    return tmp_path


def test_start_char2d_registers_the_run_and_completes_on_a_clean_gate(sync_start, jobs, monkeypatch):
    """A malformed request is refused without a card; a good one runs to green."""
    before = set(jobs)
    refused = C.start_char2d(directive='nonsense')
    assert list(refused) == ['error']
    assert refused['error'].endswith('got 1 field(s) before the colours')
    assert set(jobs) == before
    seen = {}

    def _run(brief, out_dir, log, stage, options, should_abort):
        seen['args'] = (brief, options)
        log('working')
        stage('Talking Clip')
        return {
            'hand_gate': 'clean',
            'sprites': out_dir + '/sprites.json',
            'demo': out_dir + '/demo.mp4',
            'turnaround': out_dir + '/turnaround.png',
            'talk': out_dir + '/talk/talk_front.mp4',
            'clips': 10,
            'hand_gate_frames': [],
        }

    monkeypatch.setattr(C, 'run_char2d', _run)
    out = C.start_char2d(directive='Mika, 0.2, 19, 1.68, bob', pipeline_options={'wav': '/w.wav'}, extra=1)
    pid = out['job_id']
    assert (out['status'], out['department']) == ('running', 'char2d')
    assert out['brief']['name'] == 'Mika'
    assert out['out_dir'] == os.path.join(C._OUT_ROOT, pid)
    assert os.path.isdir(out['out_dir'])
    job = jobs[pid]
    assert (job['status'], job['error'], job['current_stage']) == ('completed', None, 'Demo Reel')
    assert job['char2d'] == {'name': 'Mika', 'hand_gate': 'clean', 'out_dir': out['out_dir']}
    assert job['result']['clips'] == 10
    assert job['result']['demo'].endswith('demo.mp4')
    assert [e['msg'] for e in job['debug_events']] == ['working']
    assert seen['args'][0]['name'] == 'Mika'
    assert seen['args'][1] == {'wav': '/w.wav'}


def test_start_char2d_takes_a_structured_brief_and_fails_a_broken_hand_gate(sync_start, jobs, monkeypatch):
    """A run that delivered its files with broken hands is red, and says why."""
    monkeypatch.setattr(
        C, 'run_char2d', lambda *a, **k: {'hand_gate': 'failed', 'hand_gate_error': 'fused-fingers on wave k1'}
    )
    pid = C.start_char2d(brief={'name': 'Noor', 'hair_cut': 'short'})['job_id']
    assert jobs[pid]['directive'] == 'Noor, None, None, None, short,'
    assert jobs[pid]['status'] == 'failed'
    assert jobs[pid]['error'] == 'fused-fingers on wave k1'
    assert jobs[pid]['current_stage'] == 'Error'


@pytest.mark.parametrize(('stop', 'status', 'stage'), [(False, 'failed', 'Error'), (True, 'stopped', 'Stopped')])
def test_start_char2d_records_a_halt_as_failed_or_stopped(sync_start, jobs, monkeypatch, stop, status, stage):
    """The stop event decides: a card the operator stopped is not a failure."""

    def _halt(brief, out_dir, log, stage_fn, options, should_abort):
        if stop:
            for job in jobs.values():
                if job.get('department') == 'char2d' and job['status'] == 'running':
                    job['stop_event'].set()
        raise C.Halted('halted by operator')

    monkeypatch.setattr(C, 'run_char2d', _halt)
    pid = C.start_char2d(directive='Mika, 0.2, 19, 1.68, bob')['job_id']
    assert (jobs[pid]['status'], jobs[pid]['current_stage']) == (status, stage)
    assert jobs[pid]['error'] == 'halted by operator'
    assert [e['msg'] for e in jobs[pid]['debug_events']] == ['halted: halted by operator']


def test_start_char2d_survives_an_unexpected_exception_with_a_traceback(sync_start, jobs, monkeypatch):
    """A failed character must not take the GUI down; the card carries the trace."""

    def _boom(*a, **k):
        raise RuntimeError('blender exit 1')

    monkeypatch.setattr(C, 'run_char2d', _boom)
    pid = C.start_char2d(directive='Mika, 0.2, 19, 1.68, bob')['job_id']
    assert jobs[pid]['status'] == 'failed'
    assert jobs[pid]['error'].startswith('blender exit 1\n')
    assert 'RuntimeError' in jobs[pid]['error']
    assert len(jobs[pid]['error']) <= len('blender exit 1\n') + 900
    assert [e['msg'] for e in jobs[pid]['debug_events']] == ['failed: blender exit 1']


def test_start_char2d_tolerates_a_job_removed_from_the_registry_mid_run(sync_start, jobs, monkeypatch):
    """The worker reads the job back after the run; a vanished card is not a crash."""

    def _run(brief, out_dir, log, stage, options, should_abort):
        for pid in [k for k, v in jobs.items() if v.get('department') == 'char2d']:
            jobs.pop(pid)
        return {'hand_gate': 'clean'}

    monkeypatch.setattr(C, 'run_char2d', _run)
    assert C.start_char2d(directive='Mika, 0.2, 19, 1.68, bob')['status'] == 'running'
