# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Single source of truth for this box's CPU core ceiling.

The operator's rule is a **collective** ceiling: all Claude-driven work together
stays under 20 of the 24 cores. It is enforced at the root by pinning the VS
Code / claude-code process tree (`~/bin/zyg_cpu_cap.sh`, re-asserted every 60 s
by `zyg-cpu-cap.timer`), and CPU affinity is inherited by children, so one pin
covers a whole tree.

Why this module exists
----------------------
`os.sched_setaffinity` sets a process's own mask, and a process is free to set
one WIDER than the one it inherited. Four places did exactly that with a
hardcoded 21 cores:

    crewai_web_gui.py:133   os.sched_setaffinity(0, set(range(21)))
    vram_manager.py:414     os.sched_setaffinity(comfy_pid, set(range(21)))
    stage_runner.py:1583    taskset -c 0-20
    stage_runner.py:1938    taskset -c 0-20

The first runs at import, so **anything that imports the GUI silently widened
itself from the inherited 0-19 back to 0-20** — the cap script would re-pin it
within 60 s only if it were still in the VS Code tree, and the GUI service is
not. That is why measured usage did not stay under 20 cores: the ceiling was
being raised from inside, by one core, in four places, each with its own
comment explaining a slightly different policy.

One number, one place, overridable by the same `ZYG_CPU_CORES` the cap script
reads, so the shell mechanism and the Python one cannot drift apart again.
"""

from __future__ import annotations

import os
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


DEFAULT_SPEC = '0-19'


def spec() -> str:
    """The core range as a taskset-style string, e.g. '0-19'."""
    return (os.environ.get('ZYG_CPU_CORES') or DEFAULT_SPEC).strip()


def cores() -> set:
    """The core range as a set of ints, clamped to cores that exist."""
    out: set = set()
    for part in spec().split(','):
        part = part.strip()
        if not part:
            continue
        try:
            if '-' in part:
                a, b = part.split('-', 1)
                out.update(range(int(a), int(b) + 1))
            else:
                out.add(int(part))
        except ValueError as _exc:
            _zyg_log.warning('cpu cap spec part %r unparseable, ignoring it: %s', part, _exc)
            continue
    try:
        avail = os.sched_getaffinity(0) or set(range(os.cpu_count() or 1))
    except Exception:
        avail = set(range(os.cpu_count() or 1))
    # Never widen past what this process may already use, and never end up
    # empty — an empty mask would raise and leave the process unpinned.
    clamped = {c for c in out if 0 <= c < (os.cpu_count() or 1)}
    return clamped or set(avail)


def apply_to_self() -> bool:
    """Pin this process (and everything it forks after this) to the ceiling."""
    return apply_to_pid(0)


def apply_to_pid(pid: int) -> bool:
    try:
        os.sched_setaffinity(pid, cores())
        return True
    except Exception:
        return False


def taskset_prefix() -> list:
    """['taskset', '-c', '<spec>'] — or [] when taskset is unavailable."""
    import shutil

    if not shutil.which('taskset'):
        return []
    return ['taskset', '-c', spec()]
