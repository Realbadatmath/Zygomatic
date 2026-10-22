# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_detectors.py — the detectors, and the curiosity channel.

vfx_metrics reads the picture, vfx_landmarks reads the people; this module turns
those readings into CLAIMS about what happened, and — just as importantly — into
honest non-claims.

Every detector returns a Result carrying the BEST evidence value it saw, even
when it fires nothing. That is what makes a run calibratable: "no kick found,
best ankle velocity 3.1 torso/s against a threshold of 6.0" tells you where to
put the threshold. A bare "not found" tells you nothing, and a detector whose
threshold cannot be checked against a frame a human has looked at is not a
measurement — it is a guess with a number attached.

Preconditions are declared, not assumed. A detector that needs a pose declares
needs=('pose',); if no pose resolved in the window it returns UNMEASURABLE, not
"did not happen". On stylised 2D that is the common case and it must read as a
blind spot in the log.

Thresholds all come from THRESHOLDS below and can be overridden per run from the
GUI, so the calibration loop is: run -> look at the frames -> move the number ->
re-run against the SAME extracted frames.
"""

import math
import os

from zyg_workflows.vfx_detectors import core  # noqa: F401
from zyg_workflows.vfx_detectors.core import (
    _EPS,
    THRESHOLDS,
    _REGISTRY,
    Ctx,
    _mean,
    _std,
    _median,
    _zscores,
    detector,
    registry,
    _result,
    _ev,
    run_all,
)
from zyg_workflows.vfx_detectors import editing_camera  # noqa: F401
from zyg_workflows.vfx_detectors.editing_camera import (
    d_cut,
    d_fade,
    d_flash,
    d_cadence,
    d_held,
    d_impact,
    d_speedlines,
    _cam_move,
    d_pan,
    d_tilt,
    d_zoom,
    d_roll,
    d_shake,
    d_static,
    d_letterbox,
)
from zyg_workflows.vfx_detectors import picture  # noqa: F401
from zyg_workflows.vfx_detectors.picture import (
    _simple_frame,
    d_bloom,
    d_ca,
    d_vignette,
    d_grain,
    d_halation,
    d_banding,
    d_lowkey,
    d_highkey,
    d_silhouette,
    d_flicker,
    _dedupe_runs,
    d_clouds,
    d_water,
    d_boil,
    d_fire,
)
from zyg_workflows.vfx_detectors import people  # noqa: F401
from zyg_workflows.vfx_detectors.people import (
    d_blink,
    d_eyes_closed,
    d_lip,
    d_mouth_open,
    d_head_turn,
    _peaks,
    d_kick,
    d_punch,
    d_slap,
    d_jump,
    d_crouch,
    d_gait,
    d_fall,
    d_hand_mouth,
    d_pinch,
    d_point,
    d_press,
    d_prox,
)
from zyg_workflows.vfx_detectors import curiosity_channel  # noqa: F401
from zyg_workflows.vfx_detectors.curiosity_channel import (
    _iou,
    curiosity,
)
from zyg_workflows.vfx_detectors import taxonomy  # noqa: F401
from zyg_workflows.vfx_detectors.taxonomy import (
    BINDINGS,
    _disc_sign,
    DISCRIMINATORS,
    bind,
)

# The re-export surface, in the import order above: the pre-split vfx_detectors.py
# bound all of these at module level, and the callers reach them through this package.
__all__ = [
    'math',
    'os',
    'core',
    '_EPS',
    'THRESHOLDS',
    '_REGISTRY',
    'Ctx',
    '_mean',
    '_std',
    '_median',
    '_zscores',
    'detector',
    'registry',
    '_result',
    '_ev',
    'run_all',
    'editing_camera',
    'd_cut',
    'd_fade',
    'd_flash',
    'd_cadence',
    'd_held',
    'd_impact',
    'd_speedlines',
    '_cam_move',
    'd_pan',
    'd_tilt',
    'd_zoom',
    'd_roll',
    'd_shake',
    'd_static',
    'd_letterbox',
    'picture',
    '_simple_frame',
    'd_bloom',
    'd_ca',
    'd_vignette',
    'd_grain',
    'd_halation',
    'd_banding',
    'd_lowkey',
    'd_highkey',
    'd_silhouette',
    'd_flicker',
    '_dedupe_runs',
    'd_clouds',
    'd_water',
    'd_boil',
    'd_fire',
    'people',
    'd_blink',
    'd_eyes_closed',
    'd_lip',
    'd_mouth_open',
    'd_head_turn',
    '_peaks',
    'd_kick',
    'd_punch',
    'd_slap',
    'd_jump',
    'd_crouch',
    'd_gait',
    'd_fall',
    'd_hand_mouth',
    'd_pinch',
    'd_point',
    'd_press',
    'd_prox',
    'curiosity_channel',
    '_iou',
    'curiosity',
    'taxonomy',
    'BINDINGS',
    '_disc_sign',
    'DISCRIMINATORS',
    'bind',
]
