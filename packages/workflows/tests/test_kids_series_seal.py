#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common — the content credential is applied to what the series ships.

    scripts/run_tests.sh tests/test_kids_series_seal.py

``mux`` writes the episode mp4 and ``write_poster`` writes its thumbnail; both are
deliverables and both must leave the function sealed.  The seal itself is proven in
tests/test_provenance_seal.py — here the recorder replaces it, so what is asserted is
only the wiring: the FINAL path, once, under the 'kids_series' pipeline name.
"""

import os
import subprocess

import pytest

from zyg_workflows import kids_series_common as K
from zyg_workflows import provenance_seal
from zyg_workflows.bin import exe


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


def _lavfi(ffmpeg, args, out):
    subprocess.run([ffmpeg, '-y', '-v', 'error', *args, out], check=True, timeout=120)
    assert os.path.isfile(out), out
    return out


def test_mux_seals_the_episode(tmp_path, seals):
    ffmpeg = _ffmpeg()
    video = _lavfi(
        ffmpeg,
        ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5', '-t', '1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264'],
        str(tmp_path / 'v.mp4'),
    )
    audio = _lavfi(ffmpeg, ['-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1'], str(tmp_path / 'a.wav'))
    out = str(tmp_path / 'episode.mp4')

    assert K.mux(video, audio, out) is True
    assert [path for path, _kw in seals] == [out]
    assert seals[0][1]['pipeline'] == 'kids_series'


def test_write_poster_seals_the_thumbnail(tmp_path, seals):
    ffmpeg = _ffmpeg()
    mp4 = _lavfi(
        ffmpeg,
        ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5', '-t', '2', '-pix_fmt', 'yuv420p', '-c:v', 'libx264'],
        str(tmp_path / 'episode.mp4'),
    )
    jpg = str(tmp_path / 'poster.jpg')

    assert K.write_poster(mp4, jpg) is True
    assert [path for path, _kw in seals] == [jpg]
    assert seals[0][1]['pipeline'] == 'kids_series'


def test_nothing_is_sealed_when_ffmpeg_fails(tmp_path, seals):
    """A deliverable that was never written must not be reported as sealed."""
    assert K.mux(str(tmp_path / 'missing.mp4'), str(tmp_path / 'missing.wav'), str(tmp_path / 'out.mp4')) is False
    assert K.write_poster(str(tmp_path / 'missing.mp4'), str(tmp_path / 'poster.jpg')) is False
    assert seals == []


def test_ffmpeg_is_resolved_through_bin_exe():
    """FFMPEG is the path bin.exe resolves, not a hardcoded /usr/bin guess."""
    assert K.FFMPEG == _ffmpeg()
    assert os.path.isabs(K.FFMPEG)
