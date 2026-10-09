# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rollback switches, and the provenance and status vocabulary.

Moved verbatim out of the old single-file pose_limits.py (lines 263-357).
"""

# ruff: noqa: F401  the original module's top import block, re-exported to the submodules
import fractions
import glob
import json
import os
import sys

import numpy as np

# One os.path.dirname() deeper than the single file needed: pose_limits.py sat in geom/,
# base.py sits in geom/pose_limits/. The value is unchanged.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from zyg_workflows import paths as _paths  # noqa: E402  the sys.path/env setup above must run first
from zyg_workflows.geom import mesh_skeletons as MS  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


SCHEMA = 'geom.pose_limits/1'

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# $ZYG_ANSUR_IMPORT_DIR overrides it; the default lives under the package scratch root
# (paths.ZYG_TMP_DIR, 0o700) rather than a world-readable fixed /tmp path.
SCRATCH = _paths.ZYG_ANSUR_IMPORT_DIR


# ---------------------------------------------------------------------------------
# rollback switches. Nothing in this file changes behaviour that already ships — it is a
# new module — but every consumer that starts calling it needs a way to turn it off
# without a code edit, and the two-band wrist rule needs a way to choose which band bites.
# ---------------------------------------------------------------------------------
def _flag(name, default='1'):
    return os.environ.get(name, default).strip().lower() not in ('0', 'false', 'no', 'off', '')


def enabled():
    """ZYG_POSE_LIMITS — default 1 (on). Set 0 and run_all() returns a single skipped
    record and touches no mesh. This is the whole-module rollback."""
    return _flag('ZYG_POSE_LIMITS', '1')


def strict_wrist():
    """ZYG_POSE_LIMITS_STRICT_WRIST — default 0 (off).

    AFS p.181-182 prints TWO bands per wrist direction, not one: extension is natural to
    45 degrees and forced from 45 to 90, flexion natural to 50 and forced from 50 to 90.
    Default behaviour honours that structure — past the FORCED limit is a failure, between
    natural and forced is a warning. Set this flag to 1 and the NATURAL limit becomes the
    failing one, which is what a gate on relaxed standing poses wants.
    """
    return _flag('ZYG_POSE_LIMITS_STRICT_WRIST', '0')


def _threads():
    return max(1, int(os.environ.get('ZYG_POSE_LIMITS_THREADS', '4')))


def _set_threads():
    """Hold this process inside the operator's CPU budget. torch defaults to one thread
    per core, and several of these agents run at once."""
    try:
        import torch

        torch.set_num_threads(_threads())
    except Exception as _exc:  # pragma: no cover
        _zyg_log.debug('torch thread cap skipped: %s', _exc)


# ---------------------------------------------------------------------------------
# provenance and status vocabulary — deliberately the same words geom.anthro.gates uses,
# plus the two this file needs that it does not have.
# ---------------------------------------------------------------------------------
MEASURED = 'MEASURED'  # survey microdata
CANON = 'CANON'  # printed in an anatomy-for-artists reference. Below MEASURED.
HOUSE = 'HOUSE'  # ours, and said so
PROVENANCE_RANK = {MEASURED: 0, CANON: 1, HOUSE: 2}

PASS = 'pass'  # noqa: S105  gate status constant, not a secret
WARN = 'warn'
FAIL = 'fail'
REPORT = 'report'
UNMEASURABLE = 'unmeasurable'  # the anchor exists; this DATA cannot answer
UNRESOLVED = 'unresolved'  # the anchor does not exist on this rig at all
SKIP = 'skip'
ERROR = 'error'
STATUSES = (PASS, WARN, FAIL, REPORT, UNMEASURABLE, UNRESOLVED, SKIP, ERROR)

# How these map onto geom.anthro.gates' vocabulary when a verdict is exported into an
# anthro report. Stated here so the mapping is a fact in the code rather than a habit.
GATES_STATUS_MAP = {
    PASS: 'pass',
    WARN: 'warn',
    FAIL: 'fail',
    REPORT: 'report',
    UNMEASURABLE: 'unmeasurable',
    UNRESOLVED: 'not_implementable',
    SKIP: 'skip',
    ERROR: 'error',
}

# THE ROLL-UP ORDER, when one gate has more than one subject (see pose_layer()). Higher
# rank wins. Stated as data so it can be read, quoted and argued with, and so nothing can
# quietly re-order it inside a branch.
#   PASS < REPORT/SKIP < WARN < UNMEASURABLE/UNRESOLVED < FAIL < ERROR
# A measured FAIL outranks a non-verdict, because a breach that was measured is a fact.
# A non-verdict outranks a WARN, because a WARN is a verdict about a subject that WAS
# evaluated, whereas UNRESOLVED means a declared subject was not evaluated at all — and a
# gate that could not evaluate its declared subject has not earned a verdict on it. That is
# rule 4 of the operating brief ("a gate that cannot compute must say so, never a pass"),
# in arithmetic. An unknown status ranks as ERROR: it must never fall through to PASS.
ROLLUP_RANK = {PASS: 0, REPORT: 1, SKIP: 1, WARN: 2, UNMEASURABLE: 3, UNRESOLVED: 3, FAIL: 4, ERROR: 5}


def rollup(statuses):
    """The worst status in `statuses` under ROLLUP_RANK. Empty -> UNRESOLVED, never PASS."""
    st = [s for s in statuses if s]
    if not st:
        return UNRESOLVED
    return max(st, key=lambda s: ROLLUP_RANK.get(s, ROLLUP_RANK[ERROR]))
