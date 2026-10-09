# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401,E402  - a re-export facade: the package API is what the old module bound.
"""Default test — Conditioning / ControlNet (controlnet). 2026-09-30.

Question the sheet asks: does conditioning actually constrain the render? The sheet already
carries one measured answer and it is a NO: controls extracted from the old pictures produced
bad renders, and the fix was to REBUILD THE SOURCE PICTURES rather than to tune the control
(project_ledger_permanent_route). That finding is a probe here, `cn_garbage_in`, not a footnote.

Shape of the test
-----------------
Seventeen domain columns: fifteen probes, one lookup, one derive. Everything is measured against
ONE control set, the mannequin plates, and that choice is what makes the numbers mean something:

  * The plates come from geom/conditioning.py, which turns a RENDER PASS SET into conditioning
    maps. Depth, normal, lineart and segmentation are read out of the Z, normal and IndexOB
    passes — the renderer already knows the geometry exactly, so there is no estimator and no
    estimator error. `cn_extract_quality` therefore has a real ground truth to measure against,
    which a photograph-derived control never does.
  * The pose plate comes from geom/char_control.py: the 33-point skeleton drawn in the OpenPose
    COLOUR CONVENTION the ControlNet was trained against, from the house cascade — not from an
    NC OpenPose model. That distinction is the whole of `extractor_clean`.
  * `cn_constrains` scores the render by RE-EXTRACTING the same channel from it and comparing to
    the map that was fed in. No VLM is asked whether the pose looks right: the 2026-09-27 defect
    bench measured the best local model at 34/40 on a global question and 2/8 on the hard cases,
    so a blind operator sits beside every mechanical number and never replaces it.

Which conditions
----------------
The eight `*_ok` columns are one probe each, and a row that has no such head is `na` with the
reason on the cell — a single-condition depth checkpoint is not "bad at pose", it has no pose
mode. Where the house is not certain a mode exists (the union rows), the probe RUNS: a control
mode the workflow cannot build is a transport failure and the runner writes untested with the
error, which is honest. Inventing a licence fact or an absent feature to fill a cell is not.

What is blocked and why
-----------------------
Every plate is declared with the command that makes it and `verified: False`; none of them exist
on disk yet and this task creates no binaries. The mannequin ground-truth file blocks
`extract_quality` and `constrains`: a control we have not checked ourselves cannot be the ruler.
"""

from __future__ import annotations

from capability_tests.controlnet.constants import (
    CHECK_KINDS,
    FX,
    BEAUTY,
    TRUTH,
    MAPS,
    GARBAGE,
    MASK,
    BROKEN,
    NEG,
    PROMPT,
    PROMPT_STYLE,
    COND,
    _cond,
    RULE,
    RULE_STRICT,
    DEPTH_MIN,
    EDGE_MIN,
    NORMAL_MAX,
    SEG_MIN,
    POSE_MAX,
    OP_POSE,
    OP_LOUD,
    _p,
    AGREE,
)

from capability_tests.controlnet.probes import (
    PROBES,
)

from capability_tests.controlnet.spec import (
    SINGLE_DEPTH,
    SINGLE_POSE,
    NOT_CN_HEAD,
    INPAINT_ONLY,
    REF_DEPTH_ONLY,
    NO_COMBINE,
    TEST,
)
