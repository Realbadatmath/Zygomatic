# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  the original top import block — the siblings re-import from here

"""pose_track.py — a per-shot POSE TRACK for the VACE control channel (2026-09-02).

Section 1: the original import block, the module constants (``_CREWS``,
``OUT_ROOT``, ``MHR70_TO_POSE``, the four ledger states) and the RAM/GPU
serialisation guards (``_mem_available_gb``, ``_wait_for_ram``, ``gpu_lock``).
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import subprocess
import sys
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.pose_track')


_CREWS = str(paths.PKG_DIR)

OUT_ROOT = os.path.join(_CREWS, 'output', 'pose_tracks')

# MHR70 (sam_3d_body/metadata/mhr70.py) -> the BlazePose names geom.char_vace._BONES
# is written in. Only the 19 joints those bones need; the other 51 MHR keypoints are
# fingers, toes and clinical landmarks the OpenPose convention has no edge for.
MHR70_TO_POSE = {
    'nose': 0,
    'left_eye': 1,
    'right_eye': 2,
    'left_ear': 3,
    'right_ear': 4,
    'left_shoulder': 5,
    'right_shoulder': 6,
    'left_elbow': 7,
    'right_elbow': 8,
    'left_hip': 9,
    'right_hip': 10,
    'left_knee': 11,
    'right_knee': 12,
    'left_ankle': 13,
    'right_ankle': 14,
    'left_foot_index': 15,
    'right_foot_index': 18,
    'left_wrist': 63,
    'right_wrist': 41,
}

FOUND, NOT_FOUND, NOT_DETECTABLE, UNMEASURABLE = ('found', 'not_found', 'not_detectable', 'unmeasurable')

# The box on this machine serialises GPU work at the JOB level through one lock file
# (README rule 5 of the 2026-09-02 plan). A track runs TWO models — SAM 3 for the
# subject and SAM 3D Body for the fit — and holding the lock across both is what stops
# a second track, or a ComfyUI render, landing between them. `fcntl` rather than
# `flock -c` because a nested `flock` on the same file from inside a held lock
# deadlocks; the inner sam3d_body_service is told to skip its own lock instead.
_GPU_LOCK = paths.ZYG_GPU_LOCK


def _mem_available_gb() -> float:
    """Host RAM the kernel says is really available, in GB (0.0 if unreadable)."""
    try:
        with open('/proc/meminfo', encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / 1048576.0
    except Exception as _exc:  # pragma: no cover
        _zyg_log.warning('MemAvailable unreadable, reporting 0 GB: %s', _exc)
    return 0.0


def _wait_for_ram(need_gb: float, *, timeout_s: float = 900, poll_s: float = 10.0, log=print) -> float:
    """Block until MemAvailable >= need_gb; raise RuntimeError with the shortfall.

    The GPU lock never guarded host RAM, and on 2026-09-03 that cost a render: a
    flash-attn build (nvcc, 3-5 GB per job) drove MemAvailable down far enough that
    the OOM killer took ComfyUI out mid-frame while the GPU sat at 1%. A stage that
    starts several GB short does not degrade, it kills a neighbour — so it waits
    here, and if the RAM never arrives it refuses rather than starts.
    """
    t0 = time.time()
    ram = _mem_available_gb()
    if ram >= need_gb:
        return ram
    while time.time() - t0 < timeout_s:
        time.sleep(min(poll_s, max(0.0, timeout_s - (time.time() - t0))))
        ram = _mem_available_gb()
        if ram >= need_gb:
            log('  waited %.0fs for host RAM (%.1f GB available, floor %.1f GB)' % (time.time() - t0, ram, need_gb))
            return ram
    raise RuntimeError(
        'host RAM short by %.1f GB after %.0fs: %.1f GB available, %.1f GB needed'
        % (need_gb - ram, time.time() - t0, ram, need_gb)
    )


@contextlib.contextmanager
def gpu_lock(timeout_s: float = 7200, log=print, *, stage: str = '', ram_gb: float = 8.0, ram_wait_s: float = 900):
    """Hold the box's one GPU lock for the whole track.

    BLOCKING, not polling, and that is the whole point. Every other job on this box
    waits with `flock -w 7200 <file> -c ...`, which blocks in the kernel and is woken
    the instant the lock frees. A python loop that tries LOCK_NB every two seconds
    loses that race essentially every time: measured 2026-09-03, a track sat through
    the full 7200 s timeout while `flock -c` waiters queued behind it took the lock
    repeatedly. So this blocks in the same syscall they do, and uses SIGALRM for the
    deadline instead of a poll interval.

    Falls back to polling only off the main thread, where signals cannot be armed.

    `stage` names what the lock is being held FOR, so a long hold in the log is
    attributable instead of guessed, and `ram_gb` is a host-RAM floor applied after
    the lock is taken (see _wait_for_ram), waited for up to `ram_wait_s`. Yields a
    dict with the wait it cost.
    """
    import fcntl
    import signal

    fh = open(_GPU_LOCK, 'a+')
    t0 = time.time()
    got = False
    try:
        try:

            def _timeout(_sig, _frm):
                raise TimeoutError('GPU lock held for >%ds: %s' % (timeout_s, _GPU_LOCK))

            old = signal.signal(signal.SIGALRM, _timeout)
            signal.setitimer(signal.ITIMER_REAL, float(timeout_s))
            blocking = True
        except ValueError:  # not the main thread
            blocking = False

        if blocking:
            log('  waiting for the GPU lock (%s)' % _GPU_LOCK)
            try:
                fcntl.flock(fh, fcntl.LOCK_EX)
                got = True
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        else:
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    got = True
                    break
                except OSError as exc:
                    if time.time() - t0 > timeout_s:
                        raise TimeoutError('GPU lock held for >%ds: %s' % (timeout_s, _GPU_LOCK)) from exc
                    time.sleep(2.0)
        wait_s = time.time() - t0
        ram = _wait_for_ram(ram_gb, timeout_s=ram_wait_s, log=log)
        log('  GPU lock acquired for %s after %.0fs (ram avail %.1f GB)' % (stage or 'the track', wait_s, ram))
        prev = os.environ.get('ZYG_SAM3DB_NO_LOCK')
        os.environ['ZYG_SAM3DB_NO_LOCK'] = '1'
        try:
            yield {'stage': stage, 'wait_s': round(wait_s, 1), 'ram_avail_gb': round(ram, 1)}
        finally:
            if prev is None:
                os.environ.pop('ZYG_SAM3DB_NO_LOCK', None)
            else:
                os.environ['ZYG_SAM3DB_NO_LOCK'] = prev
    finally:
        if got:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
