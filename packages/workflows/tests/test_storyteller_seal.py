#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Storyteller — the content credential is applied to what it ships.

    scripts/run_tests.sh tests/test_storyteller_seal.py

Two deliverables, two hooks. ``storyteller_scene_service_steps._step_encode`` writes the
scene mp4 and is callable here, so the recorder proves the wiring directly: the FINAL
path, once, under the 'storyteller_scene' pipeline name — after the subtitle mux has
replaced the file for the last time, which is the only point at which a seal survives.

The episode pipeline's own hook cannot be called from a test (it wants a registered job, a
GPU, TTS engines and ComfyUI, and the module only imports with crewai present), so its
proof is scripts/check_seal_hooks.py, run below as a subprocess: an AST check that the
function still calls the seal. That is also what guards the hook against a refactor
quietly dropping it. Since the 2026-10-08 split of ``_run_storyteller_pipeline`` the hook
lives in ``storyteller.stage_05b_subtitles.stage_05b_burn_subtitles`` — Stage 5b owns the
subtitle mux, which is the last thing that rewrites the delivered file, so it is the only
place the seal survives. ``test_pipeline_storyteller_imports`` below still pins the
driver's own ``_seal`` binding.

The seal itself — that it signs, verifies, and never breaks a render — is proven in
tests/test_provenance_seal.py. Here the recorder replaces it and only the wiring is
asserted.
"""

import os
import subprocess
import sys
import time

import pytest

from zyg_workflows import provenance_seal
from zyg_workflows import storyteller_scene_service_steps as S
from zyg_workflows.bin import exe

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(PKG, 'scripts', 'check_seal_hooks.py')
SRC = os.path.join(PKG, 'src', 'zyg_workflows')


@pytest.fixture
def seals(monkeypatch):
    """Record every seal call instead of signing; returns the list of (path, kwargs)."""
    calls = []

    def _record(path, **kwargs):
        calls.append((str(path), kwargs))
        return {'ok': None, 'skipped': 'test'}

    monkeypatch.setattr(provenance_seal, 'seal', _record)
    return calls


def _ffmpeg():
    path = exe('ffmpeg', required=False)
    if not path:
        pytest.skip('ffmpeg is not installed on this machine')
    return path


def _scene_inputs(tmp_path):
    """The two things _step_encode reads: a directory of frames and a master audio track."""
    ffmpeg = _ffmpeg()
    framedir = tmp_path / 'frames'
    framedir.mkdir()
    frames = ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5', '-t', '1', str(framedir / 'f_%05d.jpg')]
    subprocess.run([ffmpeg, '-y', '-v', 'error', *frames], check=True, timeout=120)
    master = tmp_path / 'master.wav'
    subprocess.run(
        [ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', str(master)],
        check=True,
        timeout=120,
    )
    assert os.path.isfile(master)
    return str(framedir), str(master)


def _encode(tmp_path, monkeypatch, slug='scene_01'):
    """Run _step_encode over lavfi frames, with scene_state.json's contents stubbed.

    _scene_state only summarises the build for the sidecar; standing a full timeline up to
    satisfy it would prove nothing about the seal, so it is replaced by the two keys the
    caller logs. Everything the hook depends on — the encode, the subtitle mux, the order
    of the two — is the real code path.
    """
    framedir, master = _scene_inputs(tmp_path)
    monkeypatch.setattr(S, '_scene_state', lambda *a, **kw: {'total_s': 1.0, 'elapsed_s': 0.1})
    lines: list[str] = []
    out = S._step_encode(
        {'subtitles': False},
        str(tmp_path),
        slug,
        64,
        64,
        lines.append,
        {},
        {'events': [], 'picture_end': 1.0},
        {'framedir': framedir},
        {'master': master},
        time.time(),
        S._GateReceipts(lines.append),
    )
    return out, lines


def test_step_encode_seals_the_scene_mp4(tmp_path, monkeypatch, seals):
    out, _lines = _encode(tmp_path, monkeypatch)
    assert out is not None, 'the encode failed, so the hook was never reached'
    video = str(tmp_path / 'scene_01.mp4')
    assert out['video'] == video
    assert [path for path, _kw in seals] == [video]
    assert seals[0][1]['pipeline'] == 'storyteller_scene'
    assert seals[0][1]['run_id'] == 'scene_01'


def test_the_scene_is_sealed_before_its_state_file_is_written(tmp_path, monkeypatch):
    """scene_state.json describes the file that ships, so the seal must precede it."""
    state_p = tmp_path / 'scene_state.json'
    seen: list[bool] = []

    def _record(_path, **_kwargs):
        seen.append(state_p.exists())
        return {'ok': None, 'skipped': 'test'}

    monkeypatch.setattr(provenance_seal, 'seal', _record)
    out, _lines = _encode(tmp_path, monkeypatch)
    assert out is not None
    assert seen == [False]
    assert state_p.is_file()


def test_nothing_is_sealed_when_the_encode_fails(tmp_path, monkeypatch, seals):
    """A deliverable ffmpeg never wrote must not be reported as sealed."""
    monkeypatch.setattr(S, '_scene_state', lambda *a, **kw: {'total_s': 0.0, 'elapsed_s': 0.0})
    empty = tmp_path / 'empty'
    empty.mkdir()
    out = S._step_encode(
        {'subtitles': False},
        str(tmp_path),
        'scene_01',
        64,
        64,
        lambda _m: None,
        {},
        {'events': [], 'picture_end': 1.0},
        {'framedir': str(empty)},
        {'master': str(tmp_path / 'missing.wav')},
        time.time(),
        S._GateReceipts(lambda _m: None),
    )
    assert out is None
    assert seals == []


@pytest.mark.parametrize(
    ('module', 'func'),
    [
        ('storyteller/stage_05b_subtitles.py', 'stage_05b_burn_subtitles'),
        ('storyteller_scene_service_steps.py', '_step_encode'),
    ],
)
def test_the_hook_checker_finds_both_hooks(module, func):
    """The AST guard against a refactor dropping either seal call."""
    proc = subprocess.run(
        [sys.executable, CHECKER, os.path.join(SRC, module), func],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f'{proc.stdout}{proc.stderr}'
    # The checker reports `path.name`, so a hook inside a package prints the bare
    # module file name and not the `storyteller/…` path it was given.
    assert proc.stdout.strip() == f'OK {os.path.basename(module)}:{func}'


def test_pipeline_storyteller_imports():
    """The hooked module still imports — a bad import would break the pipeline at load."""
    pytest.importorskip('crewai', reason='pipeline_storyteller imports crewai at module scope')
    import zyg_workflows.pipeline_storyteller as P

    assert P._seal is provenance_seal
