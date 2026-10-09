# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""agent_activity — the numbers the Live Tail's agent panel reports.

The defect this file exists for (2026-08-30): the panel showed CPU on psutil's
raw per-process scale, where 100% means ONE core.  A session using three cores
read `300%` and a busy one on this 24-core box read `2240%`, sitting beside a
whole-machine CPU ring that also reads in the thousands — so it was reported as
"the CPU reading is wrong, it reads the system total".

The measurement was never wrong.  A controlled three-core burn reported 300.0%
against 299.9% of /proc ground truth while the machine sat at 1500-2300%.  The
UNIT was wrong, and a unit regression is invisible in a screenshot review, so
it is pinned here instead.
"""

import os
import re
import sys

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

aa = pytest.importorskip('agent_activity')


# ── the unit ────────────────────────────────────────────────────────────────
def test_cores_formatter_never_speaks_in_percent():
    assert aa._fmt_cores(0) == 'idle'
    assert aa._fmt_cores(4) == 'idle'  # 0.04 core is noise
    assert aa._fmt_cores(30) == '0.30 cores'
    assert aa._fmt_cores(100) == '1.0 core'  # singular at exactly one
    assert aa._fmt_cores(300) == '3.0 cores'
    assert aa._fmt_cores(2240) == '22.4 cores'  # the reading that was misread
    for pct in (0, 4, 30, 100, 300, 2240):
        assert '%' not in aa._fmt_cores(pct), pct


def test_snapshot_publishes_cores_and_machine_width():
    snap = aa.snapshot()
    # The degraded payload (no psutil, as in the test venv) must carry the same
    # SHAPE as a healthy one — a page rendering it should hit real zeroes, not
    # undefined fields. Only `ok` may differ.
    for key in (
        'ok',
        'sessions',
        'events',
        'count',
        'active',
        'orphans',
        'seq',
        'as_of',
        'cpu_count',
        'gpu',
        'thresholds',
    ):
        assert key in snap, key
    # Without cpu_count a client cannot turn cores into a share of the box.
    assert snap['cpu_count'] == (os.cpu_count() or 1)
    assert 'cpu_cores' in snap['thresholds']
    if not snap['ok']:
        pytest.skip('psutil unavailable here — shape checked, sampling cannot be')
    for s in snap['sessions']:
        # cpu_pct stays as the raw psutil reading; cpu_cores is what is shown.
        assert s['cpu_cores'] == pytest.approx(s['cpu_pct'] / 100.0, abs=0.011)
        assert s['cpu_share_pct'] == pytest.approx(s['cpu_pct'] / (100.0 * snap['cpu_count']) * 100.0, abs=0.11)
        # RAM is summed RSS and must say so — pages shared between forks are
        # counted once per process (~11% high on a worker pool), so a caller
        # must not be able to mistake it for an exact footprint.
        assert s['ram_metric'] == 'rss'
        for p in s['procs']:
            assert p['cpu_cores'] == pytest.approx(p['cpu_pct'] / 100.0, abs=0.011)


def test_every_surface_shows_cores():
    """The three places a number reaches the operator, and none of them may
    print the raw per-core percent."""
    js = open(os.path.join(_CREWS, 'kanban_assets', 'kanban_livetail.js'), encoding='utf-8').read()
    assert 'function _ltCores(' in js
    # the rail row, the pane header and the per-process row all go through it
    assert js.count('_ltCores(') >= 4
    assert "'% cpu'" not in js and '"% cpu"' not in js
    assert re.search(r'cpu_pct\s*\|\|\s*0\s*\)\.toFixed\(0\)\s*\}%', js) is None, (
        'the pane header is printing raw cpu_pct as a percentage again'
    )


# ── attribution + hygiene ───────────────────────────────────────────────────
def test_bash_tool_wrapper_is_unwrapped_and_secrets_are_stripped():
    wrapped = (
        '/bin/bash -c source /home/x/.claude/shell-snapshots/snapshot-bash-1.sh '
        '2>/dev/null || true && shopt -u extglob 2>/dev/null || true && '
        "eval 'python3 render.py --token=hunter2' && pwd -P >| /tmp/claude-1-cwd"
    )
    out = aa._clean_cmd([wrapped])
    assert out.startswith('python3 render.py')
    assert 'shell-snapshots' not in out
    assert 'hunter2' not in out and '***' in out


def test_the_claude_binary_is_never_counted_as_agent_work():
    for cmd in (
        '/home/z/.vscode-server/extensions/anthropic.claude-code-2.1.245-linux-x64'
        '/resources/native-binary/claude --output-format stream-json',
        '/x/native-binary/claude --claude-in-chrome-mcp',
    ):
        assert aa._SELF_RE.search(cmd), cmd
    assert not aa._SELF_RE.search('/usr/bin/python3 pipeline_kidsmusic.py')


def test_existence_is_not_activity():
    """A detached service an agent started long ago must not read as busy."""
    idle = {'cpu_pct': 0.4, 'vram_mb': 12.0, 'rss_mb': 210.0}
    assert not aa._proc_is_busy(idle)
    assert aa._proc_is_busy({'cpu_pct': 300.0, 'vram_mb': 0.0, 'rss_mb': 40.0})
    assert aa._proc_is_busy({'cpu_pct': 0.0, 'vram_mb': 8000.0, 'rss_mb': 40.0})


def test_proc_start_identity_guards_against_pid_reuse():
    """A live pid must match /proc's own start-tick, or a recycled pid could be
    renamed into an agent session by a stale registry file."""
    mine = aa._proc_start_ticks(os.getpid())
    assert mine is not None and mine.isdigit()
    assert aa._proc_start_ticks(2**30) is None
