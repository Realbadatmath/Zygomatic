# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``_bird_flies_away`` — the v27 bird flight author/render leg.

Moved verbatim out of ``run_scene_shores_v27.py`` (lines 359-729); the
individual checks now live in ``bird_flight_checks`` and this module is the
orchestrator that runs them in order.
"""

from zyg_workflows.run_scene_shores_v27.bird_flight_checks import (
    check_authoring,
    check_bank,
    check_same_camera,
    check_scripted_flaps,
    check_shutter,
    check_trajectory,
    check_wingbeat,
    check_yaw_blend,
    sample_flight,
)
from zyg_workflows.run_scene_shores_v27.constants import sss


def _bird_flies_away(spec) -> bool:
    """The flight, checked off the model rather than off an impression.

    Everything here is a statement about the 3D path and the camera it is
    projected through, so it holds whatever the sprite art happens to look
    like; the picture is checked separately, on the delivered file.
    """
    fx = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']
    cfg = fx['bird']
    dur = float(cfg['dur_s'])
    ok = check_authoring(cfg, dur)
    if not check_same_camera(cfg, fx):
        ok = False

    samples = sample_flight(cfg, dur)
    if not check_trajectory(samples, dur):
        ok = False
    if not check_wingbeat(cfg, samples):
        ok = False
    if not check_shutter(cfg):
        ok = False

    bank_ok, bank = check_bank(cfg, dur, samples)
    if not bank_ok:
        ok = False
    if not check_scripted_flaps(cfg, dur, bank):
        ok = False
    if not check_yaw_blend(cfg, samples):
        ok = False
    return ok
