#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
The two serialisation guards, tested without touching the GPU.

WHY THESE EXIST. On 2026-09-03 the pose track held the shared ~/.zyg_gpu.lock for
1h50m at 1% GPU utilisation with eight jobs queued behind it, and a flash-attn build
(nvcc, no GPU at all) OOM-killed a ComfyUI render because nothing on this box
serialises host RAM. scripts/gpu_run.sh is the wrapper that guards both, and
geom.pose_track.gpu_lock is the in-process version the track uses per stage.

What is actually asserted here is the REFUSAL path in both: a guard that only ever
passes is not a guard. Nothing here loads a model.

    scripts/run_tests.sh tests/test_gpu_run.py
"""

import os
import subprocess
import sys
import tempfile
import time

import pytest

from zyg_workflows import paths

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)

GPU_RUN = os.path.join(_HERE, 'scripts', 'gpu_run.sh')
#: The shared lock every GPU job on the box takes — the same default gpu_run.sh uses.
REAL_LOCK = str(paths.ZYG_HOME / '.zyg_gpu.lock')

# Point everything this module imports or spawns at a private lock file. pose_track
# reads ZYG_GPU_LOCK at import, so this has to happen before the import below.
_TMP = tempfile.mkdtemp(prefix='zyg_gpu_run_test_')
TMP_LOCK = os.path.join(_TMP, 'test.lock')
os.environ['ZYG_GPU_LOCK'] = TMP_LOCK
os.environ['ZYG_GPU_LOG'] = TMP_LOCK + '.log'

cv2 = pytest.importorskip('cv2', reason='geom.pose_track imports cv2 at module scope')
import zyg_workflows.geom.pose_track as P  # noqa: E402


def _run(args, env=None, timeout=30):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([GPU_RUN] + args, capture_output=True, text=True, timeout=timeout, env=e)


def test_script_is_executable_and_parses():
    assert os.access(GPU_RUN, os.X_OK), f'{GPU_RUN} is not executable'
    r = subprocess.run(['bash', '-n', GPU_RUN], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- (a) it runs


def test_ram_floor_met_runs_the_command():
    r = _run(['--ram-gb', '1', '--', 'true'])
    assert r.returncode == 0, r.stderr


# ------------------------------------------------- (b) short RAM does NOT run


def test_ram_floor_unreachable_refuses_and_does_not_run():
    """The whole point: it must exit 75 WITHOUT running the command."""
    marker = os.path.join(_TMP, 'marker_b')
    if os.path.exists(marker):
        os.remove(marker)
    r = _run(['--ram-gb', '100000', '--ram-wait', '1', '--', 'touch', marker])
    assert r.returncode == 75, (r.returncode, r.stdout, r.stderr)
    assert not os.path.exists(marker), 'the command ran despite the RAM shortfall'
    assert 'short' in r.stderr, r.stderr


def test_no_lock_still_applies_the_ram_floor():
    """--no-lock is for CPU builds (pip/nvcc) — it drops the GPU lock, not the guard."""
    marker = os.path.join(_TMP, 'marker_nolock')
    if os.path.exists(marker):
        os.remove(marker)
    r = _run(['--no-lock', '--ram-gb', '100000', '--ram-wait', '1', '--', 'touch', marker])
    assert r.returncode == 75, (r.returncode, r.stderr)
    assert not os.path.exists(marker)
    assert _run(['--no-lock', '--ram-gb', '1', '--', 'true']).returncode == 0


# ------------------------------------------------ (c) a held lock is respected


def test_held_lock_times_out_fast():
    """Against the REAL lock file, and only when it is free — this is the contract
    every other GPU job on the box relies on, so a temp file would not prove it."""
    if subprocess.run(['flock', '-n', REAL_LOCK, 'true']).returncode != 0:
        pytest.skip('the real GPU lock is held by a running job')
    holder = subprocess.Popen(['flock', REAL_LOCK, 'sleep', '5'])
    try:
        time.sleep(0.5)
        t0 = time.time()
        r = _run(
            ['--lock-wait', '1', '--', 'true'],
            env={'ZYG_GPU_LOCK': REAL_LOCK, 'ZYG_GPU_LOG': TMP_LOCK + '.log'},
            timeout=10,
        )
        dt = time.time() - t0
        assert r.returncode != 0, 'it took a lock another job was holding'
        assert dt < 3.0, f'gave up after {dt:.1f}s, not within the 1s wait'
    finally:
        holder.wait()


# ------------------------------------- (d) the in-process lock really excludes


def test_gpu_lock_holds_and_releases(monkeypatch):
    import fcntl

    monkeypatch.setattr(P, '_GPU_LOCK', TMP_LOCK)

    def taken() -> bool:
        """True when a second open-file-description cannot get the lock."""
        with open(TMP_LOCK, 'a+') as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False

    assert not taken(), 'the temp lock was already held before the test'
    with P.gpu_lock(stage='a', ram_gb=0.1) as info:
        assert taken(), 'gpu_lock did not exclude a second holder'
        assert info['stage'] == 'a'
        assert info['ram_avail_gb'] > 0
        assert os.environ.get('ZYG_SAM3DB_NO_LOCK') == '1'
    assert not taken(), 'gpu_lock did not release'


def test_ram_guard_refuses_inside_gpu_lock(monkeypatch):
    """The python-side floor must refuse, not warn — and must free the lock doing it."""
    import fcntl

    monkeypatch.setattr(P, '_GPU_LOCK', TMP_LOCK)
    with pytest.raises(RuntimeError, match='host RAM short'):
        with P.gpu_lock(stage='b', ram_gb=1e9, ram_wait_s=1):
            pytest.fail('the body ran with the host 1e9 GB short of RAM')
    with open(TMP_LOCK, 'a+') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if still held
        fcntl.flock(fh, fcntl.LOCK_UN)
