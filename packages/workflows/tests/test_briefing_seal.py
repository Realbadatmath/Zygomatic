#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
The briefing episode renderer seals what it delivers.

Built 2026-10-06 with the content-credential hooks. `render_episode` writes exactly one
deliverable video, and the claim about who made it is only worth something if it is still
attached after a refactor: these tests render a whole tiny episode (TTS stubbed out, every
other stage real ffmpeg) and assert the seal was asked for, once, on the FINAL path — and
that it was asked for BEFORE the QC gate, so a quarantined episode is signed too.

The real seal is never called here; `provenance_seal.seal` is replaced by a recorder, so
the operator's signing key is neither read nor needed.

    .venv/bin/python -m pytest tests/test_briefing_seal.py -q
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import briefing_video as bv  # noqa: E402
from zyg_workflows import provenance_seal as seal_mod  # noqa: E402
from zyg_workflows.bin import exe  # noqa: E402

FFMPEG = exe('ffmpeg', required=False)
if not FFMPEG:
    pytest.skip('the briefing render needs ffmpeg', allow_module_level=True)


def _have_ffmpeg() -> bool:
    try:
        subprocess.run([FFMPEG, '-version'], capture_output=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


needs_ffmpeg = pytest.mark.skipif(not _have_ffmpeg(), reason='ffmpeg is not on this machine')


def _png(path, colour='red'):
    subprocess.run(
        [FFMPEG, '-y', '-f', 'lavfi', '-i', f'color={colour}:size=320x180', '-frames:v', '1', str(path)],
        capture_output=True,
        timeout=60,
        check=True,
    )
    return str(path)


def _wav(path, seconds=1.0):
    subprocess.run(
        [FFMPEG, '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:r=48000', '-t', f'{seconds}', str(path)],
        capture_output=True,
        timeout=60,
        check=True,
    )
    return str(path)


@pytest.fixture
def recorder(monkeypatch):
    """Replace the real seal with a recorder, and make the render cheap and GPU-free."""
    calls = []

    def _record(path, **kw):
        calls.append({'path': str(path), **kw})
        return {'ok': None, 'skipped': 'test'}

    monkeypatch.setattr(seal_mod, 'seal', _record)
    monkeypatch.setattr(seal_mod, 'seal_derived', _record)
    # 320x180 instead of 1920x1080: the same code path, two orders of magnitude less encoding.
    monkeypatch.setattr(bv, 'W', 320)
    monkeypatch.setattr(bv, 'H', 180)
    monkeypatch.setattr(bv, '_nvenc_available', lambda: False)
    return calls


def _episode(tmp_path, theme='stocks', **extra):
    """A two-item spec whose narration is stubbed: no TTS engine, no model load."""
    work = tmp_path / 'work'
    out = tmp_path / 'out'
    work.mkdir()
    out.mkdir()
    spec = {
        'channel': 'test',
        'theme': theme,
        'slug': 'seal-episode',
        'title': 'Seal episode',
        'voice_seed': '',
        'board_png': _png(tmp_path / 'board.png', 'blue'),
        'outro_png': _png(tmp_path / 'outro.png', 'green'),
        'board_seconds': 1,
        'welcome_text': 'Welcome to the test.',
        'items': [{'chapter': 'First item', 'panels': [{'image': _png(tmp_path / 'item.png'), 'text': 'An item.'}]}],
        'outro_text': 'Goodbye.',
        'description_intro': 'A test episode.',
    }
    spec.update(extra)
    return spec, str(work), str(out)


@needs_ffmpeg
def test_render_episode_seals_the_final_video_once(tmp_path, monkeypatch, recorder):
    spec, work, out = _episode(tmp_path)
    monkeypatch.setattr(bv, 'speak_batch', lambda items, wd, **kw: {i: _wav(tmp_path / f'n{i}.wav') for i, _ in items})
    monkeypatch.setattr(bv, 'speak', lambda text, wav, **kw: False)

    res = bv.render_episode(spec, work, out)

    assert len(recorder) == 1, f'expected exactly one seal call, got {recorder} (render said {res})'
    call = recorder[0]
    assert call['path'] == os.path.join(out, 'seal-episode.mp4')
    assert call['pipeline'] == 'market'
    # The deliverable the renderer reports is the file that was sealed — unless the QC
    # gate quarantined it, in which case the seal travelled with the rename.
    assert res.get('video') == call['path'] or res.get('quarantined')


@needs_ffmpeg
@pytest.mark.parametrize(
    ('theme', 'pipeline'),
    [('arena', 'sports'), ('tokitoki', 'sports'), ('crypto', 'market'), ('kids', 'briefing'), ('', 'briefing')],
)
def test_pipeline_name_follows_the_channel(tmp_path, monkeypatch, recorder, theme, pipeline):
    spec, work, out = _episode(tmp_path, theme=theme, run_id='run-7')
    monkeypatch.setattr(bv, 'speak_batch', lambda items, wd, **kw: {i: _wav(tmp_path / f'n{i}.wav') for i, _ in items})
    monkeypatch.setattr(bv, 'speak', lambda text, wav, **kw: False)

    bv.render_episode(spec, work, out)

    assert [c['pipeline'] for c in recorder] == [pipeline]
    assert recorder[0]['run_id'] == 'run-7'


@needs_ffmpeg
def test_the_seal_is_asked_for_before_the_qc_gate(tmp_path, monkeypatch, recorder):
    """A failing gate must still have sealed: it renames the deliverable, it does not rewrite it."""
    spec, work, out = _episode(tmp_path)
    monkeypatch.setattr(bv, 'speak_batch', lambda items, wd, **kw: {i: _wav(tmp_path / f'n{i}.wav') for i, _ in items})
    monkeypatch.setattr(bv, 'speak', lambda text, wav, **kw: False)
    monkeypatch.setattr(bv, 'qc', lambda *a, **kw: {'passed': False, 'checks': [], 'failed': ['forced']})

    res = bv.render_episode(spec, work, out)

    assert res.get('quarantined'), res
    assert [c['path'] for c in recorder] == [os.path.join(out, 'seal-episode.mp4')]


def test_the_renderer_never_shells_out_to_a_bare_ffmpeg():
    """Every ffmpeg invocation goes through bin.exe, so ZYG_FFMPEG/a sandbox path is honoured."""
    # briefing_video is a package since 76fbfe5: scan every module in it (a single file
    # before that -- bv.__file__ then names the module itself).
    pkg_dir = os.path.dirname(bv.__file__)
    if os.path.basename(bv.__file__) == '__init__.py':
        srcs = sorted(os.path.join(pkg_dir, n) for n in os.listdir(pkg_dir) if n.endswith('.py'))
    else:
        srcs = [bv.__file__]
    bare = []
    for src in srcs:
        with open(src, encoding='utf-8') as fh:
            lines = fh.read().splitlines()
        bare += [
            f'{os.path.basename(src)}:{i + 1}: {ln.strip()}'
            for i, ln in enumerate(lines)
            if ln.strip() in ("'ffmpeg',", "'ffmpeg'")
        ]
    assert bare == [], f'bare ffmpeg argv entries left: {bare}'
