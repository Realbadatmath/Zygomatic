# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The egress gate: nothing reaches the Windows Desktop without a content credential.

``stage_runner._scp_output_to_windows`` is the last code that touches a deliverable before
it leaves this machine, so it is where the seal has to be unavoidable. Three properties are
proved here, all of them with the sftp subprocess replaced by a recorder:

  * every .mp4 in the output folder is sealed exactly once, with ``pipeline='egress'`` and
    the run id, and the .srt sidecars are not (the library cannot carry a manifest in them);
  * an already-sealed clip is not re-sealed — a second signature would supersede the
    pipeline's own claim with the transport's;
  * under ``ZYG_C2PA=strict`` a clip that could not be sealed is dropped from the sftp
    batch, while the default warn mode ships it unsigned rather than losing the render.

The seal itself is monkeypatched: this is a test of the wiring, not of c2pa (that is
tests/test_provenance_seal.py). The pipeline id deliberately does NOT look like a smoke run
and ZYG_NO_DELIVERY is cleared, because those guards are what the seal step sits behind.

    .venv/bin/python -m pytest tests/test_scp_seal_gate.py -q
"""

import json
import logging
import os
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# stage_runner imports crewai at module scope for the agent runs this test never reaches —
# the only function under test shells out to sftp. crewai is not in the test venv; a stub
# satisfies the import graph and would fail loudly if any code path actually used it.
if 'crewai' not in sys.modules:
    try:
        import crewai  # noqa: F401
    except ImportError:
        _stub = types.ModuleType('crewai')
        _stub.Crew = _stub.Process = _stub.Task = _stub.Agent = _stub.LLM = None
        sys.modules['crewai'] = _stub

from zyg_workflows import bin as zbin  # noqa: E402
from zyg_workflows import provenance_seal as seal_mod  # noqa: E402
from zyg_workflows import stage_runner  # noqa: E402

#: Not one of stage_runner._TEST_ID_PREFIXES_FALLBACK, or delivery is skipped entirely.
PIPELINE_ID = 'clipfarm-20261006-120000'


class _Recorder:
    """Stands in for provenance_seal.seal: records the call, signs nothing."""

    def __init__(self, ok=None):
        self.calls = []
        self._ok = ok

    def __call__(self, path, *, pipeline, run_id='', log_fn=None, **kw):
        self.calls.append({'path': str(path), 'pipeline': pipeline, 'run_id': run_id})
        return {'ok': self._ok, 'path': str(path), 'state': None, 'skipped': 'test'}

    @property
    def paths(self):
        return [c['path'] for c in self.calls]


class _FakeSftp:
    """Stands in for subprocess.Popen: keeps the batch file the function built."""

    def __init__(self):
        self.batches = []

    def __call__(self, cmd, **kw):
        batch = cmd[cmd.index('-b') + 1]
        with open(batch, encoding='utf-8') as fh:
            self.batches.append(fh.read())
        proc = types.SimpleNamespace(pid=424242, returncode=0)
        proc.communicate = lambda timeout=None: (b'', b'')
        return proc

    @property
    def put(self):
        """The basenames the one sftp batch was told to put."""
        assert len(self.batches) == 1, f'expected exactly one sftp run, got {len(self.batches)}'
        return sorted(
            os.path.basename(line.split('"')[1]) for line in self.batches[0].splitlines() if line.startswith('put ')
        )


def _media(path):
    """One second of 64x64 colour bars with a tone — the smallest real mp4 ffmpeg makes."""
    ffmpeg = zbin.exe('ffmpeg', required=False)
    if not ffmpeg:
        pytest.skip('ffmpeg is not installed; cannot build a test deliverable')
    proc = subprocess.run(
        [
            *(ffmpeg, '-loglevel', 'error', '-y'),
            *('-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5'),
            *('-f', 'lavfi', '-i', 'sine=frequency=440'),
            *('-t', '1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-c:a', 'aac'),
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f'ffmpeg failed: {proc.stderr[-2000:]}'


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    """An output folder with two clips and a sidecar, and a live sftp config beside it.

    Returns (out_dir, fake_sftp): everything _scp_output_to_windows needs is wired, the
    smoke guards are open, and the sftp subprocess is the recorder.
    """
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    for name in ('alpha.mp4', 'beta.mp4'):
        _media(out_dir / name)
    (out_dir / 'alpha.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')

    cfg = tmp_path / 'output_scp_config.json'
    cfg.write_text(
        json.dumps(
            {
                'enabled': True,
                'host': 'desktop.invalid',
                'user': 'operator',
                'remote_path': 'Desktop/Zygomatic',
                'ssh_key': str(tmp_path / 'id_ed25519'),
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(stage_runner, '_runtime_path', lambda name: str(tmp_path / name))
    monkeypatch.setattr(stage_runner, '_agent_log', lambda *a, **k: None)
    monkeypatch.setattr(stage_runner, '_register_subproc', lambda *a, **k: None)
    monkeypatch.setattr(stage_runner, '_finish_subproc', lambda *a, **k: None)
    monkeypatch.delenv('ZYG_NO_DELIVERY', raising=False)
    monkeypatch.setenv('ZYG_C2PA', 'warn')
    monkeypatch.setattr(seal_mod, 'is_sealed', lambda path: False)

    sftp = _FakeSftp()
    monkeypatch.setattr(subprocess, 'Popen', sftp)
    return out_dir, sftp


def test_every_delivered_clip_is_sealed_as_egress(delivery, monkeypatch):
    out_dir, sftp = delivery
    recorder = _Recorder(ok=True)
    monkeypatch.setattr(seal_mod, 'seal', recorder)

    stage_runner._scp_output_to_windows(str(out_dir), PIPELINE_ID)

    assert recorder.paths == [str(out_dir / 'alpha.mp4'), str(out_dir / 'beta.mp4')]
    assert {c['pipeline'] for c in recorder.calls} == {'egress'}
    assert {c['run_id'] for c in recorder.calls} == {PIPELINE_ID}
    # The sidecar has nowhere to carry a manifest, and both clips still ship.
    assert sftp.put == ['alpha.mp4', 'alpha.srt', 'beta.mp4']


def test_an_already_sealed_clip_is_not_sealed_again(delivery, monkeypatch):
    out_dir, sftp = delivery
    recorder = _Recorder(ok=True)
    monkeypatch.setattr(seal_mod, 'seal', recorder)
    monkeypatch.setattr(seal_mod, 'is_sealed', lambda path: os.path.basename(str(path)) == 'alpha.mp4')

    stage_runner._scp_output_to_windows(str(out_dir), PIPELINE_ID)

    assert recorder.paths == [str(out_dir / 'beta.mp4')]
    assert sftp.put == ['alpha.mp4', 'alpha.srt', 'beta.mp4']


def test_strict_mode_refuses_to_ship_a_clip_it_could_not_seal(delivery, monkeypatch, caplog):
    out_dir, sftp = delivery
    recorder = _Recorder(ok=False)
    monkeypatch.setattr(seal_mod, 'seal', recorder)
    monkeypatch.setenv('ZYG_C2PA', 'strict')

    with caplog.at_level(logging.INFO, logger='zyg_workflows.stage_runner'):
        stage_runner._scp_output_to_windows(str(out_dir), PIPELINE_ID)

    assert recorder.paths == [str(out_dir / 'alpha.mp4'), str(out_dir / 'beta.mp4')]
    assert sftp.put == ['alpha.srt'], 'an unsealable clip must not leave the machine in strict mode'
    out = caplog.text
    assert '[seal] refused to ship unsealed alpha.mp4' in out
    assert '[seal] refused to ship unsealed beta.mp4' in out


def test_warn_mode_still_ships_a_clip_it_could_not_seal(delivery, monkeypatch):
    """The seal may never cost a render: warn mode logs the failure and delivers anyway."""
    out_dir, sftp = delivery
    recorder = _Recorder(ok=False)
    monkeypatch.setattr(seal_mod, 'seal', recorder)

    stage_runner._scp_output_to_windows(str(out_dir), PIPELINE_ID)

    assert len(recorder.calls) == 2
    assert sftp.put == ['alpha.mp4', 'alpha.srt', 'beta.mp4']
