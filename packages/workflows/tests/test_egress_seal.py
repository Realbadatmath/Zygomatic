#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The egress family seals what it hands to the SFTP delivery.

    scripts/run_tests.sh tests/test_egress_seal.py

Three pipelines end in ``stage_runner._scp_output_to_windows``: the scholarly documentary
(stage 19 — the episode mp4 and the hook thumbnail), ``video_stages.stage_05_assembly``
(the 4K master; it is the assembly tail of ``pipeline_video._run_video_pipeline``, split
out of the driver in 2026-10) and ``pipeline_crime._run_crime_pipeline`` (the
loudness-normalised episode). Whatever leaves the machine must carry a content credential.

Stage 19 can be driven here with a stub context, so its wiring is asserted directly: the
recorder replaces :func:`zyg_workflows.provenance_seal.seal` and what is checked is the
FINAL path, once per deliverable, under the ``documentary`` pipeline name. The other two
are single thousand-line functions that need a job, the GPU, Ollama and the TTS service —
they cannot be called in a test, so ``scripts/check_seal_hooks.py`` is their proof, run
here as a subprocess over all three delivery functions. That script is what catches a
refactor dropping a hook, which is the failure mode that matters.
"""

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

# All three modules reach crewai through stage_runner, for the agent runs this test never
# gets near: the stage under test is the encode/deliver tail. crewai is not in the test
# venv; a stub satisfies the import graph and would fail loudly if a path actually used it.
if 'crewai' not in sys.modules:
    try:
        import crewai  # noqa: F401
    except ImportError:
        _stub = types.ModuleType('crewai')
        _stub.Crew = _stub.Process = _stub.Task = _stub.Agent = _stub.LLM = None
        sys.modules['crewai'] = _stub

from zyg_workflows import pipeline_crime, pipeline_video, provenance_seal  # noqa: E402
from zyg_workflows.bin import exe  # noqa: E402
from zyg_workflows.scholarly import stages_19_36  # noqa: E402

#: packages/workflows — where scripts/ and src/ live.
PKG = Path(__file__).resolve().parents[1]

#: The delivery functions and the file each lives in, as the checker wants them.
DELIVERY = [
    ('src/zyg_workflows/scholarly/stages_19_36.py', 'stage_19_burn_subtitles'),
    ('src/zyg_workflows/video_stages/stage_05_assembly.py', 'stage_05_assembly'),
    ('src/zyg_workflows/pipeline_crime.py', '_run_crime_pipeline'),
]


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


def _lavfi(args, out):
    subprocess.run([_ffmpeg(), '-y', '-v', 'error', *args, out], check=True, timeout=120)
    assert os.path.isfile(out), out
    return out


def _stage_19_ctx(tmp_path, monkeypatch):
    """A context stage 19 can run on: a real mp4, a hook still, no narration.

    ``narration_enabled=False`` skips the subtitle burn (which would need the TTS wav and
    word timings) and leaves the mp4 final where the seal is. The SFTP delivery at the end
    of the stage is stubbed: this test must not reach the network.
    """
    out_dir = tmp_path / 'out'
    (out_dir / 'flux_images').mkdir(parents=True)
    final = _lavfi(
        ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5', '-t', '1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264'],
        str(out_dir / 'episode.mp4'),
    )
    _lavfi(
        ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5', '-frames:v', '1'],
        str(out_dir / 'flux_images' / 'flux_000.jpg'),
    )
    delivered = []
    monkeypatch.setattr(stages_19_36, '_scp_output_to_windows', lambda *a, **kw: delivered.append(a))
    ctx = types.SimpleNamespace(
        _book_intro_prepended=False,
        _done=lambda *a, **kw: None,
        _log=lambda *a, **kw: None,
        _pipeline_marker=0,
        _save=lambda *a, **kw: None,
        _sch_family_label='FLUX',
        _slug='test_episode',
        _stage_start=lambda *a, **kw: None,
        final_video_path=final,
        job={},
        narration_enabled=False,
        narration_script='',
        out_dir=str(out_dir),
        pipeline_id='test_egress_seal',
        pipeline_state={'word_count': 120, 'essay_title': 'Test Essay'},
        topic='provenance',
        tts_duration=60.0,
        tts_path=str(out_dir / 'narration.mp3'),
    )
    return ctx, final, str(out_dir / '_thumbnail.jpg'), delivered


def test_stage_19_seals_the_episode_and_the_thumbnail(tmp_path, monkeypatch, seals):
    ctx, final, thumbnail, delivered = _stage_19_ctx(tmp_path, monkeypatch)

    stages_19_36.stage_19_burn_subtitles(ctx)

    assert delivered, 'the stage never reached the SFTP delivery'
    assert ctx.pipeline_state['thumbnail_path'] == thumbnail
    assert [path for path, _kw in seals] == [final, thumbnail]
    assert [kw['pipeline'] for _path, kw in seals] == ['documentary', 'documentary']
    assert [kw['run_id'] for _path, kw in seals] == ['test_egress_seal', 'test_egress_seal']


def test_the_episode_is_sealed_before_it_is_measured_and_delivered(tmp_path, monkeypatch, seals):
    """The seal rewrites the file, so it has to happen before the size is reported."""
    ctx, final, _thumbnail, _delivered = _stage_19_ctx(tmp_path, monkeypatch)
    order = []
    monkeypatch.setattr(stages_19_36, '_scp_output_to_windows', lambda *a, **kw: order.append('deliver'))
    monkeypatch.setattr(provenance_seal, 'seal', lambda path, **kw: order.append(f'seal:{os.path.basename(path)}'))

    stages_19_36.stage_19_burn_subtitles(ctx)

    assert order == ['seal:episode.mp4', 'seal:_thumbnail.jpg', 'deliver']
    assert ctx.job['final_output_file'] == final


@pytest.mark.parametrize(('rel', 'func'), DELIVERY)
def test_the_delivery_function_still_seals(rel, func):
    """``check_seal_hooks.py`` is the standing guard against a dropped hook."""
    proc = subprocess.run(
        [sys.executable, str(PKG / 'scripts' / 'check_seal_hooks.py'), rel, func],
        cwd=PKG,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == f'OK {Path(rel).name}:{func}'


def test_the_three_egress_modules_import():
    """The hooks are at module top; an import error would break every render."""
    for module in (stages_19_36, pipeline_video, pipeline_crime):
        assert module._seal is provenance_seal
