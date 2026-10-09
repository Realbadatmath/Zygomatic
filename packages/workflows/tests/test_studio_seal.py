#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
The three studio delivery functions seal what they write.

Built 2026-10-06 with the C2PA seal. The property under test is not that a manifest
verifies — test_provenance_seal.py owns that — but that the hook is *reached*: every
file one of these functions leaves on disk is handed to the seal exactly once, under the
right pipeline name, and it is the FINAL path, after the last os.replace.

The seal itself is monkeypatched out with a recorder, so these tests need no key and no
c2pa wheel; they only need ffmpeg to make a one-second clip to work on.

    .venv/bin/python -m pytest tests/test_studio_seal.py -q
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import bin as zbin  # noqa: E402
from zyg_workflows import provenance_seal as seal_mod  # noqa: E402

FFMPEG = zbin.exe('ffmpeg', required=False)

# video_assembly resolves ffmpeg at import, so the skip has to come before the import.
pytestmark = pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed in this environment')


class Recorder:
    """Stands in for provenance_seal.seal / seal_derived and remembers the calls."""

    def __init__(self):
        self.calls: list = []

    def seal(self, path, **kw):
        self.calls.append({'path': str(path), 'master': None, **kw})
        return {'ok': None, 'skipped': 'test'}

    def seal_derived(self, path, master_path, **kw):
        self.calls.append({'path': str(path), 'master': str(master_path), **kw})
        return {'ok': None, 'skipped': 'test'}

    def paths(self) -> list:
        return [c['path'] for c in self.calls]

    def one(self, path) -> dict:
        """The single call for *path* — asserts it was sealed exactly once."""
        hits = [c for c in self.calls if c['path'] == str(path)]
        assert len(hits) == 1, f'{path} sealed {len(hits)} time(s), expected once: {self.paths()}'
        return hits[0]


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(seal_mod, 'seal', rec.seal)
    monkeypatch.setattr(seal_mod, 'seal_derived', rec.seal_derived)
    return rec


def _log_lines() -> tuple:
    lines: list = []
    return lines, lines.append


def _clip(path, seconds=1.0):
    """A tiny silent-picture mp4 — 64x64, 5 fps, the cheapest thing ffmpeg will make."""
    subprocess.run(
        [
            FFMPEG,
            '-y',
            '-v',
            'error',
            '-f',
            'lavfi',
            '-i',
            f'testsrc=size=64x64:rate=5:duration={seconds}',
            '-pix_fmt',
            'yuv420p',
            '-c:v',
            'libx264',
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def _wav(path, seconds=1.0):
    subprocess.run(
        [
            FFMPEG,
            '-y',
            '-v',
            'error',
            '-f',
            'lavfi',
            '-i',
            f'sine=frequency=440:duration={seconds}',
            '-ar',
            '48000',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


# ── video_studio._post_process ────────────────────────────────────────────


def test_post_process_seals_master_and_every_side_export(tmp_path, recorder):
    from zyg_workflows import video_studio

    clip = _clip(tmp_path / 'clip.mp4')
    p = video_studio.sanitize(
        {'gif_export': True, 'webp_export': True, 'poster_frame': True, 'contact_sheet': True, 'probe_report': True}
    )
    lines, log = _log_lines()

    video_studio._post_process(clip, p, log, run_id='job-7')

    base = os.path.splitext(clip)[0]
    master = recorder.one(clip)
    assert master['master'] is None, 'the mp4 master is an original, not a transcode'
    assert master['pipeline'] == 'video_studio'
    assert master['run_id'] == 'job-7'

    for side in (base + '.gif', base + '.webp', base + '.poster.png', base + '.sheet.png'):
        assert os.path.isfile(side), f'{side} was not written — {lines}'
        call = recorder.one(side)
        assert call['master'] == clip, 'a side export is a transcode of the master'
        assert call['pipeline'] == 'video_studio'
        assert call['run_id'] == 'job-7'

    # The probe report is a JSON sidecar: written, but nowhere to carry a manifest.
    assert os.path.isfile(base + '.probe.json')
    assert base + '.probe.json' not in recorder.paths()


def test_post_process_seals_the_alternate_codec_delivery(tmp_path, recorder):
    from zyg_workflows import video_studio

    clip = _clip(tmp_path / 'clip.mp4')
    p = video_studio.sanitize({'codec': 'h265'})
    lines, log = _log_lines()

    video_studio._post_process(clip, p, log, run_id='job-8')

    delivery = os.path.splitext(clip)[0] + '.h265.mp4'
    assert os.path.isfile(delivery), f'the h265 delivery was not written — {lines}'
    assert recorder.one(clip)['master'] is None
    call = recorder.one(delivery)
    assert call['master'] == clip
    assert call['pipeline'] == 'video_studio'
    assert call['run_id'] == 'job-8'


def test_side_exports_returns_only_what_it_wrote(tmp_path, recorder):
    from zyg_workflows import video_studio

    clip = _clip(tmp_path / 'clip.mp4')
    _, log = _log_lines()
    assert video_studio._side_exports(clip, video_studio.sanitize({}), log) == []
    wrote = video_studio._side_exports(clip, video_studio.sanitize({'poster_frame': True}), log)
    assert wrote == [os.path.splitext(clip)[0] + '.poster.png']


# ── video_assembly.assemble ───────────────────────────────────────────────


def test_assemble_seals_the_programme(tmp_path, recorder):
    from zyg_workflows import video_assembly

    shot = _clip(tmp_path / 'shot.mp4')
    out = str(tmp_path / 'programme.mp4')
    _, log = _log_lines()

    receipt = video_assembly.assemble({'fps': 5, 'size': [64, 64], 'shots': [{'path': shot}]}, out, log, draft=True)

    assert receipt['out'] == out
    call = recorder.one(out)
    assert call['pipeline'] == 'video_assembly'
    assert call['master'] is None


def test_assembly_resolves_ffmpeg_by_absolute_path():
    from zyg_workflows import video_assembly

    assert os.path.isabs(video_assembly.FFMPEG)
    assert video_assembly.FFMPEG == zbin.exe('ffmpeg')


# ── voice_studio._finish_take ─────────────────────────────────────────────


def test_finish_take_seals_the_preview(tmp_path, recorder):
    from zyg_workflows import voice_studio

    raw = _wav(tmp_path / 'raw.wav')
    work = tmp_path / 'take'
    work.mkdir()
    _, log = _log_lines()

    final = voice_studio._finish_take(raw, voice_studio.sanitize({}), str(work), log)

    assert final == str(work / 'preview.wav')
    assert os.path.isfile(final)
    call = recorder.one(final)
    assert call['pipeline'] == 'voice_studio'
    assert call['run_id'] == 'take'


def test_finish_take_seals_the_unnormalised_fallback(tmp_path, recorder, monkeypatch):
    """The loudnorm path and the copyfile fallback both ship a take, so both seal it."""
    from zyg_workflows import audio_mix, voice_studio

    monkeypatch.setattr(audio_mix, 'loudnorm_two_pass', lambda *a, **kw: None)
    raw = _wav(tmp_path / 'raw.wav')
    work = tmp_path / 'take'
    work.mkdir()
    lines, log = _log_lines()

    final = voice_studio._finish_take(raw, voice_studio.sanitize({}), str(work), log)

    assert os.path.isfile(final)
    assert recorder.one(final)['pipeline'] == 'voice_studio'
