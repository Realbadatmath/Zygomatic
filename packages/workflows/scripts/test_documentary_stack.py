#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Functional tests for the 2026-08 documentary work.

Every test exercises the SHIPPED code path against REAL assets — no mocks of
the thing under test. Run from the crews directory:

    python3 scripts/test_documentary_stack.py            # skip slow/GPU tests
    python3 scripts/test_documentary_stack.py --full     # include them

It re-execs itself into the crews venv (agents/.venv) if started from any
other interpreter. That is not a convenience. The stack under test is only
half-installed under /usr/bin/python3 — rapidocr_onnxruntime, the primary
typography judge, lives in the venv only — so running there turns three real
tests into SKIPs and reports a green-ish 120/1/4 for a stack that is fine.
A test harness that scores differently depending on how you invoked it is
measuring the invocation, not the code.

The 2,089 lines of harness this file used to be now live in
scripts/documentary_stack/ — one module per section banner, driven by
documentary_stack.runner.main in the original order. This path stays the
documented entry point: every invocation above still works unchanged.
"""

import os
import sys

# Importing the package is what re-execs into the venv (documentary_stack.core
# runs the same guard this file used to), so put this file's own directory on
# the path before the import rather than relying on sys.path[0].
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from documentary_stack.runner import main  # noqa: E402  the sys.path insert above has to run first

if __name__ == '__main__':
    sys.exit(main())
