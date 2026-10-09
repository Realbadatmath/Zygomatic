#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
The Remix departments stamp a content credential on what they ship.

Built 2026-10-06, with the C2PA seal. ``pipeline_remix._loudnorm_master`` is the single
funnel every remix deliverable leaves through — vertical clips and long-form compilations
alike — and it has three exits: the normalised mux, and two ``shutil.copy2`` fallbacks that
ship un-normalised audio when ffmpeg's loudnorm pass fails. A seal wired into only the happy
exit is the failure that looks like a success, so both of the fallbacks are exercised here
too: the test with an audio-less input takes the first one.

``pipeline_remixai._run_pipeline`` cannot be called from a test (it sweeps YouTube, runs a
diffusion model and TTS on the GPU, and needs a live job on the board), so its hook is proved
by ``scripts/check_seal_hooks.py``, which this suite runs on it as its last test.

    .venv/bin/python -m pytest tests/test_remix_seal.py -q
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import bin as zbin  # noqa: E402
from zyg_workflows import pipeline_remix  # noqa: E402
from zyg_workflows import provenance_seal  # noqa: E402

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def ffmpeg():
    try:
        return zbin.exe('ffmpeg')
    except zbin.MissingExecutable as exc:
        pytest.skip(f'cannot build test media: {exc}')


@pytest.fixture
def recorder(monkeypatch):
    """``provenance_seal.seal`` replaced by a list of the calls it was asked to make.

    The pipelines hold the module (``from zyg_workflows import provenance_seal as _seal``),
    not the function, so patching the attribute is what the call site sees.
    """
    calls = []

    def fake_seal(path, **kwargs):
        calls.append({'path': str(path), **kwargs})
        return {'ok': None, 'skipped': 'test'}

    monkeypatch.setattr(provenance_seal, 'seal', fake_seal)
    return calls


def _media(ffmpeg, out, *, audio=True):
    """A one-second H.264 clip in *out*, with or without a sound track."""
    cmd = [ffmpeg, '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440', '-c:a', 'aac']
    cmd += ['-t', '1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f'ffmpeg failed: {proc.stderr[-2000:]}'
    return str(out)


def test_loudnorm_master_seals_the_master(tmp_path, ffmpeg, recorder):
    """The normal exit: loudnorm succeeds, the mux writes final_path, the seal follows."""
    mix = _media(ffmpeg, tmp_path / 'mix.mp4')
    final = str(tmp_path / 'FINAL_clip.mp4')

    ntype = pipeline_remix._loudnorm_master('pidtest00', mix, final, 'Master & Deliver')

    assert ntype in ('linear', 'dynamic'), ntype
    assert os.path.isfile(final)
    assert [c['path'] for c in recorder] == [final]
    assert recorder[0]['pipeline'] == 'remix'
    assert recorder[0]['run_id'] == 'pidtest00'


def test_loudnorm_master_seals_the_copy_fallback(tmp_path, ffmpeg, recorder):
    """An input with no audio makes the loudnorm pass fail: the copy2 exit seals too."""
    mix = _media(ffmpeg, tmp_path / 'silent.mp4', audio=False)
    final = str(tmp_path / 'FINAL_compilation.mp4')

    ntype = pipeline_remix._loudnorm_master('pidtest01', mix, final, 'Master & Deliver')

    assert ntype == 'skipped'
    assert os.path.isfile(final)
    assert [c['path'] for c in recorder] == [final]
    assert recorder[0]['pipeline'] == 'remix'


def test_remixai_run_pipeline_hook_is_in_place():
    """The remixai deliverable cannot be rendered in a test; the checker is the proof."""
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(PACKAGE_ROOT, 'scripts', 'check_seal_hooks.py'),
            os.path.join(PACKAGE_ROOT, 'src', 'zyg_workflows', 'pipeline_remixai.py'),
            '_run_pipeline',
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'OK pipeline_remixai.py:_run_pipeline' in proc.stdout


def test_remix_hook_survives_a_refactor():
    """The same guard on the remix funnel, so a refactor that drops the seal fails here."""
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(PACKAGE_ROOT, 'scripts', 'check_seal_hooks.py'),
            os.path.join(PACKAGE_ROOT, 'src', 'zyg_workflows', 'pipeline_remix.py'),
            '_loudnorm_master',
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'OK pipeline_remix.py:_loudnorm_master' in proc.stdout
