# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GATE 2 — t5_pose_stiffness.

Moved verbatim out of the old single-file pose_limits.py (lines 1855-2367). The gate's
stages moved to stiffness_measures.py on 2026-10-09 (the no-function-over-300-lines
rule); what stays here is the entry point, which is the order those stages run in.
"""

from zyg_workflows.geom.pose_limits import stiffness_measures as SM


# the two helpers pose_limits/__init__.py re-exports from this module moved whole into
# stiffness_measures; re-export them by ASSIGNMENT rather than by `from … import`, so no
# unused-import suppression is needed and a later tidy-up cannot prune them
_trunk_tilts = SM._trunk_tilts
_p175_error = SM._p175_error


# ---------------------------------------------------------------------------------
# GATE 2 — t5_pose_stiffness (a DIVERSITY statistic over a SET, not an anatomy gate)
# ---------------------------------------------------------------------------------
def t5_pose_stiffness(skeletons, world_up=None):
    """Pose-set diversity. AFS p.175's three named errors, p.19's ERECT share, p.16's tilt.

    This is a statistic about a CAST, in the same family as the existing t3_cast_diversity.

    AFS p.16'S SENTENCE HAS TWO CONJUNCTS AND BOTH ARE NOW ENFORCED (R1, 2026-08-06). The
    page asks for a transverse-tilt standard deviation above 2 degrees WITH SHOULDER AND HIP
    TILTS OF OPPOSITE SIGN. Until this fix the gate scored only the standard deviation; the
    sign opposition was computed, stored in `observed`, and never read, so the row was a
    clean PASS on a set that violated the second half of the very sentence quoted as its
    source — abel 22 of 44 fitted poses same-sign, cornelis 23 of 43. Both conjuncts are
    CANON, both can block, and enforcing the second one is what turns those two rows from
    pass to fail. That is the correct outcome, not a regression.

    AFS p.175'S THREE NAMED ERRORS ARE SCORED TOO, at HOUSE provenance and capped at WARN.
    They cannot block. Each is decided at the narrowest of its three declared windows and
    all three widths ship — see _p175_error. Before this fix these three fractions were
    registered as `quantities` on the gate, computed on every run, and read by nothing.

    THE FIVE-CONFIGURATION TAXONOMY IS NOT REPRODUCED. AFS p.19 sorts poses into five
    configurations; the definitions of those five categories are not in our possession, and
    inventing them so a number could be printed would be exactly the failure this stack
    exists to avoid. What is computed instead is the one split that needs no taxonomy — how
    many poses are ERECT — and the trunk-inclination distribution behind it, which is
    parameter-free. The ERECT share is REPORTED and is not scored: p.19 gives no target for
    it, and scoring it would mean inventing one.
    """
    skeletons = list(skeletons)
    refusal = SM.frame_guard(skeletons)
    if refusal is not None:
        return refusal
    meas = SM.measure_pose_set(skeletons, world_up)
    wins = SM.window_fractions(meas)
    tilt = SM.tilt_statistics(meas.tilts)
    # the drift guard runs on EVERY call, before a verdict exists, and refuses rather than
    # reporting a band that is not the band that was enforced
    drifted = SM.drift_refusal(len(skeletons), tilt)
    if drifted is not None:
        return drifted
    scored = SM.scored_rows(tilt, wins, meas)
    status, explain = SM.verdict(scored, tilt)
    return SM.build_result(len(skeletons), tilt, wins, meas, scored, status, explain)
