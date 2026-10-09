#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_music_service — the content credential is applied to what the song ships.

    scripts/run_tests.sh tests/test_kids_music_seal.py

``master_audio`` writes the delivery master and ``remux_video`` rewrites the video
container around a new master; both leave a deliverable behind and both must seal it.
The seal itself is proven in tests/test_provenance_seal.py — here the recorder replaces
it, so what is asserted is only the wiring: the FINAL path, once, under the 'kids_music'
pipeline name.
"""

import os
import subprocess

import pytest

from zyg_workflows import kids_music_service as M
from zyg_workflows import provenance_seal
from zyg_workflows.bin import exe

#: The least a plan can hold and still get through gate_audio with want_clap=False.
PLAN = {'seconds': 6.0, 'bpm': 120.0, 'key': {'tonic_pc': 0, 'mode': 'major', 'tonic': 'C'}}


@pytest.fixture
def seals(monkeypatch):
    """Record every seal call instead of signing; returns the list of (path, kwargs)."""
    calls = []

    def _record(path, *args, **kwargs):
        calls.append((str(path), kwargs))
        return {'ok': None, 'skipped': 'test'}

    monkeypatch.setattr(provenance_seal, 'seal', _record)
    monkeypatch.setattr(provenance_seal, 'seal_derived', _record)
    return calls


def _ffmpeg():
    path = exe('ffmpeg', required=False)
    if not path:
        pytest.skip('ffmpeg is not installed on this machine')
    return path


def _lavfi(ffmpeg, args, out):
    subprocess.run([ffmpeg, '-y', '-v', 'error', *args, out], check=True, timeout=120)
    assert os.path.isfile(out), out
    return out


def test_master_audio_seals_the_master(tmp_path, seals):
    ffmpeg = _ffmpeg()
    src = _lavfi(ffmpeg, ['-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '6'], str(tmp_path / 'take.wav'))

    master, gate, _trimmed = M.master_audio(src, str(tmp_path), PLAN)

    assert master == str(tmp_path / 'master.mp3')
    assert gate['ok'] is True
    assert [path for path, _kw in seals] == [master]
    assert seals[0][1]['pipeline'] == 'kids_music'


def test_nothing_is_sealed_when_the_master_was_never_written(tmp_path, seals):
    """A master the chain failed to produce must not be reported as sealed."""
    master, _gate, _trimmed = M.master_audio(str(tmp_path / 'missing.wav'), str(tmp_path), PLAN)

    assert master is None
    assert seals == []


def test_remux_video_seals_the_new_container(tmp_path, seals):
    ffmpeg = _ffmpeg()
    _lavfi(
        ffmpeg,
        ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5', '-t', '1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264'],
        str(tmp_path / 'video.mp4'),
    )
    audio = _lavfi(ffmpeg, ['-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1'], str(tmp_path / 'master.mp3'))

    assert M.remux_video(str(tmp_path), audio) is True
    assert [path for path, _kw in seals] == [str(tmp_path / 'video.mp4')]
    assert seals[0][1]['pipeline'] == 'kids_music'


def test_remux_video_seals_nothing_when_there_is_no_video(tmp_path, seals):
    assert M.remux_video(str(tmp_path), str(tmp_path / 'master.mp3')) is False
    assert seals == []
