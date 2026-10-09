# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Section 15 of the harness: staleness + receipts, and the interpreter check.

Moved verbatim out of scripts/test_documentary_stack.py lines 1211-1289."""

# E402: the __file__ re-anchor has to run before the moved section.
# ruff: noqa: E402

import os as _zyg_os

# test_production_interpreter reads its own module source to prove the venv
# re-exec guard has not been deleted. In the single-file harness that guard sat
# in this very file; the split moved it to documentary_stack/core.py, so point
# the dunder at the module that now holds it instead of editing the moved
# assertion.
__file__ = _zyg_os.path.join(_zyg_os.path.dirname(_zyg_os.path.abspath(__file__)), 'core.py')
del _zyg_os

import os
import subprocess
import sys

from .core import CREWS, _zyg_log, check, skip


# ── 15. staleness + receipts ───────────────────────────────────────────────
def test_staleness_and_receipts():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('module records its import time', '_MODULE_IMPORTED_AT = time.time()' in src)
    check('a run whose code changed after import says so', 'STALE CODE' in src)
    # the CALL, not the def — the def contains the same substring
    _call = src.find('            _gate_receipts_audit()')
    check('gate audit is called from a finally block', _call > 0 and 0 < src.rfind('finally:', 0, _call))
    check('audit names gates that never executed', 'filed NO receipt' in src)
    check('receipts land in run state', "pipeline_state['gate_receipts']" in src)


def test_production_interpreter():
    """The suite must score the interpreter production actually uses.

    Found by running the suite the way its own docstring said to. Under
    /usr/bin/python3 it reported PASS 120 / FAIL 1 / SKIP 4; under the venv,
    the full set. Nothing in the pipeline had changed — only how I started
    the test. Three OCR-dependent tests had quietly become SKIPs.
    """
    venv_py = os.path.join(os.path.dirname(CREWS), '.venv', 'bin', 'python')
    check('the production venv exists', os.path.exists(venv_py), venv_py)

    # We are IN it — either started there, or re-exec'd into it.
    venv_dir = os.path.join(os.path.dirname(CREWS), '.venv')
    check(
        'the suite is running under the production interpreter',
        os.path.abspath(sys.prefix) == os.path.abspath(venv_dir),
        sys.prefix,
    )

    # The guard must actually FIRE from the system interpreter. Assert on the
    # behaviour, not on the source: the first version compared realpaths, read
    # correctly, and was inert because the venv python is a symlink.
    probe = (
        'import os,sys;'
        'CREWS=%r;'
        'V=os.path.join(os.path.dirname(CREWS),".venv");'
        'print(os.path.abspath(sys.prefix)!=os.path.abspath(V))' % CREWS
    )
    fired = ''
    try:
        fired = subprocess.run(
            ['/usr/bin/python3', '-c', probe], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except Exception as exc:
        fired = repr(exc)
    check('the guard fires when started from /usr/bin/python3', fired == 'True', fired)

    # The re-exec is present in source (so removing it fails here, not silently).
    body = open(os.path.abspath(__file__), encoding='utf-8').read()
    check('the re-exec guard is in the source', 'os.execv(_VENV_PY' in body)
    check(
        'the guard compares sys.prefix, not a symlink-collapsing realpath',
        'os.path.abspath(sys.prefix) != os.path.abspath(_VENV_DIR)' in body,
    )

    # The GUI really does run from this interpreter — the reason we chose it.
    ps = ''
    try:
        ps = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True, timeout=20).stdout
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    gui = [l for l in ps.splitlines() if 'crewai_web_gui.py' in l and 'grep' not in l]
    if not gui:
        skip('the GUI runs from the same interpreter', 'GUI not running')
    else:
        # Substring, not realpath: the venv python is a symlink to the system
        # one, and the install path contains a space so .split()[0] truncates
        # it at the first space, losing everything after "Zygomatic".
        check('the GUI runs from the same interpreter', any(venv_dir in l for l in gui), gui[0][: len(venv_py) + 20])

    # And the thing that was actually missing is importable here.
    try:
        from zyg_workflows import typography_ocr as _t

        check('the OCR judge is importable under it', _t.available())
    except Exception as exc:
        check('the OCR judge is importable under it', False, repr(exc))
