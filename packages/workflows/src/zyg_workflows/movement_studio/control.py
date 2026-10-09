# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.control — per-frame control/mask folders and the ZYG_*
environment overrides."""

import os

from zyg_workflows.movement_studio.params import sanitize
from zyg_workflows.movement_studio.plates import _plate_log
from zyg_workflows.movement_studio.render import _pin_regions, plateset_dir


# ────────────────────────────────────────── per-frame control and mask folders
def _is_frame_dir(path: str) -> bool:
    if not (path and os.path.isdir(path)):
        return False
    try:
        return any(f.lower().endswith(('.png', '.jpg', '.jpeg')) for f in os.listdir(path))
    except OSError:
        return False


def control_kwargs(p: dict, generate_fn=None, log_fn=None) -> dict:
    """{'control_dir': ...} / {'mask_path': ...} for the folders the operator gave.

    control_dir is S01's argument. While the INSTALLED signature has no such
    parameter this raises, because the alternative — dropping it — renders a
    clip from the still that looks like a driven clip and is not."""
    log = _plate_log(log_fn)
    p = sanitize(p)
    out = {}
    scene = plateset_dir(p)
    cdir = str(p.get('control_dir') or '').strip()
    if scene and not cdir:
        # The scene's own ctrl_*.png. Routed through the same variable as the
        # typed folder so it meets the SAME two refusals below — an empty export
        # and a build with no control_dir= must fail for a scene exactly as they
        # fail for a hand-typed path.
        cdir = scene
        log(f'[ctrl] scene plate set <- {scene}')
    if cdir:
        if not _is_frame_dir(cdir):
            raise ValueError(f'control frames folder has no images: {cdir}')
        if generate_fn is not None:
            import inspect

            if 'control_dir' not in inspect.signature(generate_fn).parameters:
                raise ValueError(
                    'this build of wan_vace_service.generate_vace_static_clip has no '
                    'control_dir= parameter, so a control-frames folder cannot be '
                    'honoured. That argument is S01 (video control path) work; clear '
                    'the Control frames folder field to render from the still instead.'
                )
        out['control_dir'] = cdir
        log(f'[ctrl] control frames <- {cdir}')
    mdir = str(p.get('mask_dir') or '').strip() or scene
    if mdir:
        if not _is_frame_dir(mdir):
            raise ValueError(f'mask frames folder has no images: {mdir}')
        out['mask_path'] = mdir
        log(f'[ctrl] per-frame masks <- {mdir} (ZYG_VACE_MASK_SEQ=1)')
    return out


# The five switches wan_vace_service reads off the environment at graph-build
# time. They are applied around one render and restored afterwards (bp_movement
# holds the one-job lock, so no second render can observe the window), because
# the alternative is threading five more keyword arguments through a function
# whose signature already has thirty.
_ENV_KEYS = (
    'ZYG_WAN_ATTENTION',
    'ZYG_WAN_TIMEOUT_S',
    'ZYG_MASK_GATE',
    'ZYG_BEAT_MAP_GATE',
    'ZYG_LORA_ATTEST',
    'ZYG_WAN_BEAT_CHARS',
    'ZYG_CHAR_GEOM_CTRL',
    'ZYG_VACE_DIFFDIFF',
    'ZYG_VACE_MASK_SEQ',
    'ZYG_VACE_CTRL_BLEND',
)


def env_overrides(p: dict) -> dict:
    p = sanitize(p)
    return {
        'ZYG_WAN_ATTENTION': str(p['attention']),
        'ZYG_WAN_TIMEOUT_S': str(int(p['timeout_s'])),
        'ZYG_MASK_GATE': '1' if p['mask_gate'] else '0',
        'ZYG_BEAT_MAP_GATE': '1' if p['beat_gate'] else '0',
        'ZYG_LORA_ATTEST': 'strict' if p['attest'] == 'strict' else '',
        'ZYG_WAN_BEAT_CHARS': str(int(p['beat_chars'])),
        'ZYG_CHAR_GEOM_CTRL': '1' if p['char_geom'] else '0',
        # the diffdiff flag alone does nothing without regions — see _pin_regions
        'ZYG_VACE_DIFFDIFF': '1' if _pin_regions(p) else '0',
        # scoped per job for the same reason the other seven are: mask_path is
        # a DIRECTORY only while this is set, and wan_vace_service refuses to
        # guess (wan_vace_service.py:1490). Empty means 'unset', not '0'.
        'ZYG_VACE_MASK_SEQ': '1' if (str(p.get('mask_dir') or '').strip() or plateset_dir(p)) else '',
        # A scene plate is a rendered frame of the actual shot, so it goes into
        # the control channel VERBATIM ('raw'); the default 'mask' composite
        # would keep only the part inside the generate region and hand the
        # sampler a shot with the set cut out of it. Empty means 'unset', which
        # is wan_vace_service's own 'mask' default (L1846).
        'ZYG_VACE_CTRL_BLEND': 'raw' if plateset_dir(p) else '',
    }
