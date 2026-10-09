# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The board must admit to every pipeline that is running (2026-10-02).

Documentary and Children's Music share one ``_workflow_jobs`` registry and can
run at the same time — the scholarly start route has no busy gate at all, so a
documentary will happily start on top of a song.  The board, though, picked ONE
job, rendered that job's department template, and listed peers only from the
SAME department:

    and (j.get('department') or 'scholarly').lower() == dept

So two live pipelines rendered as a one-job machine with no sign the other
existed, and there was no request parameter to steer it.  Measured live after
the fix, with a song and a documentary running together::

    focused run      b78d4a40 ( scholarly  — Stage 3: Script Preparation )
    live_runs        2
    concurrent_runs  0 (same department)
    other_runs       1 -> kidsmusic | 24e1406d308a | Measure Produced Track

and pinned the other way (``?pipeline_id=24e1406d308a``)::

    template         kidsmusic
    focused run      24e1406d308a ( kidsmusic — Measure Produced Track )
    other_runs       [('scholarly', 'b78d4a40', 'Stage 3: Script Preparation')]

bp_pipeline_api cannot be imported standalone (it pulls the whole Flask GUI in
through a circular import), so these read the source.  CPU-only.
"""

import os
import re

import pytest

import zyg_dashboard

PKG = os.path.dirname(os.path.abspath(zyg_dashboard.__file__))


def _src(*parts):
    with open(os.path.join(PKG, *parts), encoding='utf-8') as fh:
        return fh.read()


# Both GUI modules became packages in the 2026-10 modularization; the tests below slice on
# anchors, so each reads the ONE module that holds them: the kanban status route lives in
# bp_pipeline_api/kanban.py, the job restore in crewai_web_gui/pages.py.
@pytest.fixture(scope='module')
def api():
    return _src('bp_pipeline_api', 'kanban.py')


@pytest.fixture(scope='module')
def gui():
    return _src('crewai_web_gui', 'pages.py')


@pytest.fixture(scope='module')
def js():
    return _src(os.path.join('kanban_assets', 'kanban_main.js'))


# ── the payload tells the truth about what is live ───────────────────────────


def test_payload_carries_other_runs_and_a_live_count(api):
    for key in ("'other_runs':", "'live_runs':", "'focused_run':"):
        assert key in api, key


def test_idle_board_carries_the_same_keys(api):
    """A client reading other_runs must not have to special-case the idle board."""
    # Anchored on the guard and on the CORS call that closes the branch: the payload dict
    # is one key per line since `ruff format`, and the headers are set by apply_cors() now.
    idle = api[api.index('if not active_job:') :]
    idle = idle[: idle.index('apply_cors')]
    assert "'pipeline': None" in idle
    for key in ("'concurrent_runs': []", "'other_runs': []", "'live_runs': 0"):
        assert key in idle, key


def test_other_runs_is_cross_department_and_live_only(api):
    block = api[api.index('_other_runs = []') : api.index('# ── Collect debug events')]
    # the inverse of the same-department filter that hid them
    assert "(_ojob.get('department') or 'scholarly').lower() == dept" in block
    assert 'continue' in block
    # only runs that are actually alive
    assert "_workflow_job_gpu_active(_ojob) or _ojob.get('status') == 'running'" in block
    # never the focused job twice
    assert '_ojob is active_job' in block


def test_other_runs_carry_no_card_map(api):
    """A song has no "Stage 3.5" to paint. Naming the run is honest; giving it
    this board's card states would be a fabrication."""
    block = api[api.index('_other_runs = []') : api.index('# ── Collect debug events')]
    assert "'cards'" not in block
    for key in ("'pipeline_id'", "'department'", "'current_stage'", "'status'"):
        assert key in block, key


def test_same_department_peers_still_filtered_to_the_department(api):
    """concurrent_runs is painted as cells under THIS board's cards, so it has
    to stay same-department. The fix adds a channel, it does not widen this one."""
    block = api[api.index('concurrent_runs = []') : api.index('_other_runs = []')]
    assert "(j.get('department') or 'scholarly').lower() == dept" in block


# ── the board can be steered ─────────────────────────────────────────────────


def test_status_accepts_a_pipeline_id_to_focus(api):
    assert "_focus_pid = (request.args.get('pipeline_id') or '').strip()" in api
    assert '_focus_pid and _focus_pid in _workflow_jobs' in api


def test_auto_pick_is_skipped_when_a_run_is_pinned(api):
    """Without this the board snaps back to the most recent run on every poll."""
    # `ruff format` wrapped the generator onto its own line, so the opening paren of the
    # `for job in (...)` header is no longer adjacent to the guard.
    assert '() if active_job else' in api


def test_js_sends_the_pin_and_renders_the_chips(js):
    assert '_pinnedRunId' in js
    assert "'?pipeline_id=' + encodeURIComponent(_pinnedRunId)" in js
    assert 'function _renderOtherRuns(data)' in js
    assert '_renderOtherRuns(data);' in js


def test_js_chips_do_not_interpolate_ids_into_inline_handlers(js):
    block = js[js.index('function _renderOtherRuns(data)') :]
    block = block[: block.index('\n}\n')]
    assert 'onclick=' not in block  # delegated listener, not inline JS
    assert 'data-pid=' in block
    assert '_escHtml(' in block


def test_js_drops_a_pin_whose_run_has_ended(js):
    block = js[js.index('function _renderOtherRuns(data)') :]
    block = block[: block.index('\n}\n')]
    assert '_pinnedRunId = null' in block


def test_board_markup_has_the_strip_and_a_bumped_cache_key(gui):
    html = _src('kanban.html')
    assert 'id="kb-other-runs"' in html
    assert '.kb-other-runs' in html and '.kb-or-chip' in html
    m = re.search(r'kanban_main\.js\?v=(\d+)', html)
    assert m and int(m.group(1)) >= 46, 'cache key must be bumped or browsers keep the old JS'


# ── an unfinished run must not fall off the restore window ───────────────────


def test_restore_window_keeps_running_jobs(gui):
    """Six songs ran after the documentary on 2026-10-02; at a flat 5-file window
    the documentary was 7th by mtime and vanished from the registry entirely —
    not shown as stopped, absent."""
    start = gui.index('def _restore_jobs_from_disk():')
    block = gui[start : gui.index('\n_restore_jobs_from_disk()', start)]
    assert '[:30]' in block, 'the scan window must be wider than the keep window'
    assert '_scanned[:5]' in block, 'the 5 most recent are still kept unconditionally'
    assert "_resolve_pipeline_public_status(json.load(_fh)) == 'running'" in block
