# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.render — LoRA chain, pin regions, scene plate sets and
render_kwargs()."""

import json
import os

from zyg_workflows.movement_studio.params import sanitize
from zyg_workflows.movement_studio.plates import prop_plates


# ─────────────────────────────────────────────────────── render wiring
def lora_chain(p: dict, auto_name: str = '') -> list:
    """[(comfy-relative name, strength), ...] for generate_vace_static_clip's
    `loras`. 'auto' resolves to whatever LoRA bp_movement found for the subject;
    an empty resolution yields an empty chain rather than a None entry, which
    would raise inside the loader loop."""
    p = sanitize(p)
    chain = []
    first = p.get('lora')
    if first == 'auto':
        first = auto_name or ''
    if first:
        chain.append((first, float(p.get('lora_strength', 0.5))))
    if p.get('lora2'):
        chain.append((p['lora2'], float(p.get('lora2_strength', 0.4))))
    return chain


def _pin_regions(p: dict):
    """None (the pin is OFF and no diffdiff node is emitted) unless BOTH the
    toggle is on and a parseable box is given. A toggle with no box is the
    documented no-op — the graph is byte-identical to never having asked —
    so it must not turn into an empty list that reads as 'pin everything'."""
    if not p.get('graded_pin'):
        return None
    raw = str(p.get('pin_box') or '').replace(' ', '')
    if not raw:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw.split(',')[:4])
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    return [{'box': (x0, y0, x1, y1), 'level': float(p.get('pin_level', 0.65))}]


# ───────────────────────────────────────── scene plate sets (2026-09-15, S11)
# One dropdown renders the subject INTO a Blender shot. Everything it sets was
# already reachable by hand — control_dir, mask_path, ZYG_VACE_MASK_SEQ, the raw
# control blend, the frame count, the resolution and the still — and getting all
# seven right by hand is how a scene render quietly becomes a still render.
# plateset.json is scene_plates.SCHEMA ('zyg.plateset/1'): frames/width/height/
# still/ctrl/mask.
def plateset_dir(p: dict) -> str:
    """The chosen plates directory, or '' when the dropdown is off / the
    directory has lost its plateset.json. Never raises: a scene that has been
    deleted since the options were built must leave the render exactly as it
    would have been without the rack, not fail at kwargs time."""
    d = str((p or {}).get('scene_plateset') or 'none').strip()
    if not d or d == 'none':
        return ''
    return d if os.path.isfile(os.path.join(d, 'plateset.json')) else ''


def plateset_meta(p: dict) -> dict:
    """The parsed plateset.json for the chosen scene, or {}."""
    d = plateset_dir(p)
    if not d:
        return {}
    try:
        with open(os.path.join(d, 'plateset.json'), encoding='utf-8') as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def still_for(p: dict, still_path: str = '') -> str:
    """The still the render should actually start from.

    A scene shot's own beauty frame 0 is the only still whose framing, lens and
    lighting match the control plates; the subject's canon portrait does not, and
    starting a plate-driven render from it fights the control channel for the
    whole denoise. Falls back to the subject's still whenever the scene has no
    still.png, so the override can never blank the argument."""
    d = plateset_dir(p)
    if d:
        cand = os.path.join(d, str(plateset_meta(p).get('still') or 'still.png'))
        if os.path.isfile(cand):
            return cand
    return still_path


def render_kwargs(p: dict, num_frames_override=None, still_path: str = '', log_fn=None) -> dict:
    """The spec-derived half of generate_vace_static_clip's call. The caller adds
    prompt, out_dir, loras, ref_images_paths and log_fn — those come from the
    SUBJECT, not from the dials.

    still_path is passed in only so the PROP PLATES rack can ask SAM 3 where the
    object is in THIS still; it is not a render argument here (the caller still
    passes the still positionally) and an empty value simply disables the auto
    box, leaving the typed one."""
    p = sanitize(p)
    try:
        W, H = (int(v) for v in str(p['resolution']).split('x'))
    except (TypeError, ValueError):
        W, H = 832, 480
    nf = int(num_frames_override or p['num_frames'])
    # SCENE PLATE SET. The shot's own geometry wins over the Engine rack's: a
    # control folder of 49 frames at 832x480 rendered at the dial's 65 frames and
    # a different aspect is a shot that no longer lines up with its own plates.
    # An explicit num_frames_override (the probe button) still wins, because
    # probing the head of a long shot is a deliberate act, and the padding rule
    # in wan_vace_service (L1723-1732) makes a short count safe.
    ps = plateset_meta(p)
    if ps:
        W = int(ps.get('width') or W)
        H = int(ps.get('height') or H)
        if not num_frames_override and ps.get('frames'):
            nf = int(ps['frames'])
        still_path = still_for(p, still_path)
    # 4n+1 or the encoder truncates. Snap rather than refuse: the caller may be a
    # probe button passing a raw frame count, not a value off the select.
    nf = max(17, ((nf - 1) // 4) * 4 + 1)
    return {
        'num_frames': nf,
        'steps': int(p['steps']),
        'cfg': float(p['cfg']),
        'shift': float(p['shift']),
        'seed': int(p['seed']),
        'width': W,
        'height': H,
        'n_regions': int(p['n_regions']),
        'vace_strength': float(p['vace_strength']),
        'vace_start_percent': float(p['vace_start_percent']),
        'vace_end_percent': float(p['vace_end_percent']),
        'neutral_control': bool(p['neutral_control']),
        'interpolate': bool(p['interpolate']),
        'extra_negative': str(p['negative_prompt'] or ''),
        'context_windows': bool(p['context_windows']),
        'context_frames': int(p['context_frames']),
        'context_overlap': int(p['context_overlap']),
        'context_stride': int(p['context_stride']),
        'fuse_method': str(p['fuse_method']),
        'pin_regions': _pin_regions(p),
        # PROP PLATES. None when the rack is off, and building the plate is the
        # only file I/O this function does — it happens once per render, is
        # cached on the source map's mtime, and returns None on every failure so
        # the control frame is exactly what it was before the rack existed.
        'prop_plates': prop_plates(p, still_path=still_path, log_fn=log_fn),
    }
