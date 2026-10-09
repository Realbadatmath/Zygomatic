# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.options — paths, the on-disk option scans and RESOLUTIONS."""

import os
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__package__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_ROOT = os.path.realpath(os.path.join(HERE, 'output', 'movement'))
_PRESET_DIR = os.path.join(_OUT_ROOT, '_presets')
_LORA_ROOT = str(paths.ZYG_COMFY_LORA_DIR)


# ────────────────────────────────────────────────────────── dynamic options
def _lora_options() -> list:
    """Every Wan LoRA actually on disk, as {v: comfy-relative path, l: label}.

    Same scan video_studio._lora_options runs, and for the same reason: an
    SDXL/FLUX LoRA loaded into a Wan graph is a guaranteed ComfyUI error, not a
    creative option, so the non-Wan ones never reach the picker. 'auto' is the
    default and means "whichever wan_chars/wan_props LoRA bp_movement resolved
    for this subject" — picking a file here overrides that resolution."""
    opts = [{'v': 'auto', 'l': "auto — the subject's own LoRA"}, {'v': '', 'l': 'none — base model only'}]
    try:
        for sub in sorted(os.listdir(_LORA_ROOT)):
            full = os.path.join(_LORA_ROOT, sub)
            if os.path.isdir(full):
                for f in sorted(os.listdir(full)):
                    if f.endswith('.safetensors') and 'wan' in (sub + f).lower():
                        opts.append({'v': f'{sub}/{f}', 'l': f'{sub}/{f[:-12]}'})
            elif sub.endswith('.safetensors') and 'wan' in sub.lower():
                opts.append({'v': sub, 'l': sub[:-12]})
    except OSError as _exc:
        _zyg_log.debug('wan LoRA scan of %s skipped: %s', _LORA_ROOT, _exc)
    return opts


def _lora2_options() -> list:
    """Second slot: no 'auto', because there is no such thing as a subject's
    second LoRA — this seat is for a style/motion LoRA chained after it."""
    return [{'v': '', 'l': 'none'}] + [o for o in _lora_options()[2:]]


def _object_options() -> list:
    """Every asset actually in prop_mesh_library, as picker options.

    Same rule as _lora_options: what is on disk, never a placeholder catalogue.
    'none' is the default and is what keeps prop_plates OFF — an empty plate
    list must reach generate_vace_static_clip as None so the control frame is
    byte-identical to never having asked (wan_vace_service.py:1579)."""
    opts = [{'v': 'none', 'l': 'none — no rigid plate'}]
    try:
        from zyg_workflows import prop_mesh_library as PML

        for rec in PML.list_assets():
            aid = rec.get('id')
            if aid:
                opts.append({'v': aid, 'l': f'{rec.get("name") or aid} ({rec.get("kind") or "prop"})'})
    except Exception as _exc:  # noqa: BLE001 — no registry is not an error here
        _zyg_log.debug('prop asset registry unavailable, no prop options offered: %s', _exc)
    return opts


def _plate_view_options() -> list:
    """The union of every registered asset's view ids, plus 'auto'.

    A view id is only meaningful for its own asset, but RACKS is a static spec
    and the GUI filters the list against the chosen object. 'auto' picks the
    first view the asset's control manifest actually wrote, which is the only
    value that is correct for every asset without the client knowing anything."""
    opts = [{'v': 'auto', 'l': "auto — the asset's first built view"}]
    seen = set()
    try:
        from zyg_workflows import prop_mesh_library as PML

        for rec in PML.list_assets():
            for vid in PML.view_ids(rec.get('id')) or []:
                if vid not in seen:
                    seen.add(vid)
                    opts.append({'v': vid, 'l': vid})
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('prop asset registry unavailable, no plate view options offered: %s', _exc)
    return opts


_SHOTS_ROOT = os.path.join(HERE, 'data', 'architecture', 'shots')


def _plateset_options() -> list:
    """Every Blender shot that scene_plates.py has already exported, as picker
    options whose VALUE is the absolute plates directory.

    The value is the directory rather than the shot id because that directory is
    literally what control_dir= and mask_path= receive — there is no second
    resolution step that could disagree with the label. 'none' is the default and
    is what keeps this whole path off."""
    opts = [{'v': 'none', 'l': 'none — render from the still'}]
    try:
        for shot in sorted(os.listdir(_SHOTS_ROOT)):
            plates = os.path.join(_SHOTS_ROOT, shot, 'plates')
            if os.path.isfile(os.path.join(plates, 'plateset.json')):
                opts.append({'v': plates, 'l': shot})
    except OSError as _exc:
        _zyg_log.debug('shot plate scan of %s skipped: %s', _SHOTS_ROOT, _exc)
    return opts


# 4n+1 is not decoration: WanVideoVACEEncode builds ((n-1)//4)+1 latent frames,
# and a count that is not 4n+1 silently truncates. Every offered length is legal.
RESOLUTIONS = ['832x480', '480x832', '640x640', '704x704', '960x544', '544x960', '1280x720', '720x1280']
