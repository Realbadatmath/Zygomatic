# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A transient VRAM shortage must not destroy an episode (2026-10-02).

What happened: a children's song was in its Illustrate leg while a documentary
reached Stage 4.  IndexTTS-2's worker exits 3 when free VRAM is under
``ZYG_INDEXTTS_MIN_VRAM_MB`` (21000); 18508 MiB was free.  The caller read exit 3
as "engine unavailable" and fell through to Chatterbox — whose **.venv had been
deleted that same morning** by the 02:36 disk sweep, leaving chatterbox_worker.py
(untouched since 2026-07-30) with no interpreter to run it — and the pipeline
failed::

    Stage 4: IndexTTS-2 VRAM gate: 18508 MiB free < 21000 MiB - falling back to Chatterbox
    Stage 4: Chatterbox worker/venv missing - no fallback available
    Stage 4: ALL TTS engines failed - no narration audio produced

Research, script, visual tagging and emotion analysis were already done and were
thrown away, because another job held 2.5 GB too much for a moment.

The gate now WAITS and retries — re-running the worker is cheap when the gate
trips, it checks VRAM and exits before loading anything — and the log says
honestly whether a fallback exists at all.

tts_service cannot be imported standalone (circular import through
subproc_registry → crewai_web_gui), so these read the source.  CPU-only.
"""

import os

import pytest

from zyg_workflows import paths

from tests import _tree

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope='module')
def src():
    with open(_tree.pkg('tts_service', 'engines.py'), encoding='utf-8') as fh:  # a package since 2026-10
        return fh.read()


@pytest.fixture(scope='module')
def gate(src):
    """The exit-3 handling inside _indextts_segments."""
    start = src.index('# ── VRAM gate: WAIT, do not give up')
    return src[start : src.index('_good = [_p for _p in _outs', start)]


def test_gate_retries_instead_of_giving_up_at_once(gate):
    assert 'for _attempt in range(_waits)' in gate
    assert 'time.sleep(_wait_s)' in gate
    assert '_rc, _res = _tts_run_worker(' in gate


def test_retry_budget_is_tunable_and_defaults_to_ten_minutes(gate):
    assert "os.environ.get('ZYG_TTS_VRAM_WAITS', '30')" in gate
    assert "os.environ.get('ZYG_TTS_VRAM_WAIT_S', '20')" in gate
    assert 30 * 20 == 600  # ten minutes of waiting before giving up


def test_waiting_stops_as_soon_as_the_gate_clears(gate):
    assert 'if _rc != 3:' in gate
    assert 'break' in gate


def test_zero_waits_restores_the_old_fail_fast(gate):
    """ZYG_TTS_VRAM_WAITS=0 must give exactly the pre-change behaviour."""
    assert "max(0, int(os.environ.get('ZYG_TTS_VRAM_WAITS', '30') or 0))" in gate
    # range(0) runs no attempts, and the failure branch below is re-tested
    assert 'if _rc == 3:' in gate


def test_failure_message_does_not_claim_a_fallback_that_cannot_run(gate):
    assert '_chatterbox_installed()' in gate
    assert 'cannot run' in gate


def test_chatterbox_installed_helper_exists(src):
    assert 'def _chatterbox_installed() -> bool:' in src
    assert 'os.path.isfile(_CHATTERBOX_PY) and os.path.isfile(_CHATTERBOX_WORKER)' in src


def test_missing_fallback_log_names_the_path_it_looked_in(src):
    block = src[src.index('def _chatterbox_segments(') :]
    block = block[: block.index('_bp, _outs =')]
    assert '_chatterbox_installed()' in block
    assert '{_CHATTERBOX_DIR}' in block


# ── the box this runs on ─────────────────────────────────────────────────────


def test_the_fallback_really_cannot_run_here():
    """Not a style check — the premise of the fix, and the thing that turned a
    transient VRAM shortage into a lost episode. The worker script is present;
    it is the INTERPRETER that is gone. If someone reinstalls the venv this
    flips, and the honest-message branch stops being the one that fires."""
    # The same flag and default tts_service.py reads; it cannot be imported here.
    d = os.environ.get('ZYG_CHATTERBOX_DIR', str(paths.ZYG_HOME / 'Zygomatic Full' / 'models' / 'tts_chatterbox'))
    if not os.path.isdir(d):
        pytest.skip('Chatterbox was never installed on this box')
    assert os.path.isfile(os.path.join(d, 'chatterbox_worker.py')), (
        'the worker script itself was never the missing piece'
    )
    assert not os.path.isfile(os.path.join(d, '.venv', 'bin', 'python')), (
        'Chatterbox can run again — update the comments saying the documentary has only one working TTS engine'
    )


def test_primary_engine_is_installed():
    d = os.environ.get('ZYG_INDEXTTS_DIR', str(paths.ZYG_MODELS_DIR / 'tts_indextts2'))
    if not os.path.isdir(d):
        pytest.skip('IndexTTS-2 is not installed on this box')
    assert os.path.isfile(os.path.join(d, 'indextts2_worker.py'))
    assert os.path.isfile(os.path.join(d, '.venv', 'bin', 'python'))
