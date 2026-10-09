# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.presets — preset load/save/delete and spec()."""

import json
import os
import logging as _zyg_logging

from zyg_workflows.movement_studio.actions_lib import ACTIONS_LIB
from zyg_workflows.movement_studio.options import _PRESET_DIR
from zyg_workflows.movement_studio.params import ACTIONS, RACKS, defaults, sanitize

_zyg_log = _zyg_logging.getLogger(__package__)


# ──────────────────────────────────────────────────────────────────── presets
def presets() -> list:
    try:
        return sorted(f[:-5] for f in os.listdir(_PRESET_DIR) if f.endswith('.json'))
    except OSError:
        return []


def _safe_name(name: str) -> str:
    safe = ''.join(c for c in (name or '') if c.isalnum() or c in ' _-')[:60].strip()
    if not safe:
        raise ValueError('bad preset name')
    return safe


def preset_load(name: str) -> dict:
    with open(os.path.join(_PRESET_DIR, f'{_safe_name(name)}.json'), encoding='utf-8') as fh:
        d = json.load(fh) or {}
    out = sanitize(d.get('params') or d)
    out['_action'] = str(d.get('action') or '')
    return out


def preset_save(name: str, params: dict, action: str = '') -> str:
    safe = _safe_name(name)
    os.makedirs(_PRESET_DIR, exist_ok=True)
    tmp = os.path.join(_PRESET_DIR, f'{safe}.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'action': str(action or ''), 'params': sanitize(params)}, fh, indent=1)
    os.replace(tmp, os.path.join(_PRESET_DIR, f'{safe}.json'))
    return safe


def preset_delete(name: str) -> None:
    try:
        os.remove(os.path.join(_PRESET_DIR, f'{_safe_name(name)}.json'))
    except OSError as _exc:
        _zyg_log.warning('preset %s could not be deleted: %s', name, _exc)


def spec() -> dict:
    """What the GUI builds both bars from."""
    return {'racks': RACKS, 'actions': ACTIONS, 'library': ACTIONS_LIB, 'defaults': defaults()}


# ────────────────────────────────────────────────────────────────── MISSING
# Options a movement studio should have that are NOT offered here, and why —
# recorded so each absence reads as a decision rather than an oversight:
#
#  * Camera moves (dolly/pan/tilt/zoom).  This graph is a LOCKED-CAMERA recipe:
#    generate_vace_static_clip hard-prefixes '固定镜头, static shot, fixed camera,
#    locked-off tripod shot.' onto every beat and pins the set through a VACE
#    embed.  A camera dial here would be an inert lever — the prefix wins.  Move
#    the camera in Video Studio, which drives the I2V graph instead.
#  * (WIRED 2026-09-02, DRIVER WIRED 2026-09-18) Pose/depth control plates and
#    the per-frame control and mask folders — the CONTROL PATH rack.  The driver
#    is live too now: Extract track starts a background job that runs
#    geom.pose_track over the Driver clip and then geom.track_plates over that
#    track, and fills Control frames with the composite plate folder and Mask
#    frames with the tracked masks.  Pointing the two folder fields at frames you
#    already have still works — a typed folder wins over the extraction's.
#  * Set plate / two-VACE-embed split (set_plate_path/set_strength/
#    set_end_percent).  Needs a CLEAN BACKGROUND PLATE of the same shot — a
#    three-zone composite the storyteller pipeline builds from scene metadata.
#    Movement Studio starts from one still and has no plate to offer, and
#    passing the still itself would re-pin exactly what the mask just freed.
#  * (WIRED 2026-09-02) Rigid prop plates — the PROP PLATES rack.  The two
#    halves that were missing are both here now: mesh_control has already
#    written depth/normal/lineart maps for every registered asset view, and the
#    in-frame box is typed or read off SAM 3.  Measured on a synthetic 832x480
#    neutral control with the pufferball front_full depth map at box
#    0.30,0.35,0.28,0.30: 4.54% of the frame left neutral grey, changed region
#    x 0.297-0.583, y 0.346-0.654.  NULL (the same call with an empty plate
#    list) returns None and the control is untouched.
#  * (WIRED 2026-09-02) Per-frame mask sequences — the Mask frames folder on the
#    CONTROL PATH rack, which is also what sets ZYG_VACE_MASK_SEQ for the job.
#  * Per-plate release percent.  Deliberately NOT a dial:
#    prop_control.composite_into_control reads exactly {'plate','meta','quad',
#    'strength'} off a plate dict, and the whole control channel — plates
#    included — is released at vace_end_percent, which is already the Pin end %
#    lever.  A second copy of it here would be an inert lever.
#  * Output fps.  CreateVideo is fixed at 17.0 fps and the only finishing lever
#    is the RIFE pass to 24.  A dial that offered other rates would be lying.
#  * Audio.  This graph is silent by construction; the narration/SFX stack owns
#    levelling, and a second mixer here would produce two loudness paths.
#  * Scheduler choice (unipc/dpm++/euler).  WanVideoSampler takes it, but
#    generate_vace_static_clip hard-codes 'unipc' and does not accept a kwarg.
#    Left out rather than shipped as a dial that changes nothing.
