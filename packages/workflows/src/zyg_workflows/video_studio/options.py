# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, dynamic options — the choice lists that are scanned off disk.

Moved verbatim (lines 67-178 of the old single-file module) when video_studio.py
became this package. LoRAs, LUTs, VFX elements and ambience beds are enumerated
at import: the GUI re-reads /video/api/spec on every tab enter, so a restart
picks up new trainer output. PATHWAYS and RESOLUTIONS are the two static lists
the spec needs before it can declare its selects.
"""

import os

from zyg_workflows import wan_video_service as _wan

from . import _LORA_ROOT, _LUT_DIR, _zyg_log


# ────────────────────────────────────────────────────────── dynamic options
def _lora_options() -> list:
    """Every Wan LoRA actually on disk, as {v: comfy-relative path, l: label}.

    Scanned at import (the GUI re-reads /video/api/spec on every tab enter, so
    a restart picks up new trainer output). Non-Wan LoRAs are filtered out —
    an SDXL/FLUX LoRA in a Wan graph is a guaranteed ComfyUI error, not a
    creative option."""
    opts = [{'v': '', 'l': 'none'}]
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
        _zyg_log.warning('LoRA directory unreadable, offering no LoRAs: %s', _exc)
    return opts


def _lut_options() -> list:
    """Every .cube LUT dropped into output/video_studio/_luts.

    Scanned at import like the LoRA list. The folder is created on first use so
    the answer to "where do I put one" is visible on disk rather than only in a
    hint; an empty list here means the folder is empty, which is a true
    statement about this box and not a broken option."""
    opts = [{'v': '', 'l': 'none'}]
    try:
        os.makedirs(_LUT_DIR, exist_ok=True)
        for f in sorted(os.listdir(_LUT_DIR)):
            if f.lower().endswith('.cube'):
                opts.append({'v': f, 'l': f[:-5]})
    except OSError as _exc:
        _zyg_log.warning('LUT directory unavailable, offering no LUTs: %s', _exc)
    return opts


def _vfx_element_options() -> list:
    """Every placeable VFX library element, as {v: '<cat>/<file>', l: label}.

    Built at import from the VFX sidecar like the LoRA and LUT lists above. An
    unreadable sidecar (or a box with no VFX library at all) leaves the single
    'none' option, which is the default — the rack is then inert rather than
    broken."""
    try:
        from zyg_workflows import vfx_place as _vfxp

        return _vfxp.element_options()
    except Exception:  # noqa: BLE001
        return [{'v': 'none', 'l': 'none'}]


# Filename fragments that mark a library sound as usable as a BED rather than
# a hit: a bed has to be long, flat and loopable, and in these two libraries
# that is exactly what these words name.
_BED_WORDS = ('wind', 'storm', 'amb', 'ambience', 'rain', 'sea', 'wave', 'forest', 'city', 'night', 'room')
_BED_CATS = ('sfx', 'foley')
_BED_MAX = 80


def _ambience_options() -> list:
    """Library beds as {v: '<cat>/<filename>', l: label}, built once at import.

    The licence sidecar is the authority, not the filename: only entries whose
    meta says ``commercial_ok`` is True are offered, so an unlicensed file
    cannot be picked in the first place (video_audio.resolve_library_file
    refuses it a second time downstream).

    Each sidecar is loaded ONCE with ``_load_audio_meta(cat)`` — the per-file
    ``get_audio_meta`` would re-read and re-parse a 1000-entry JSON document
    for every candidate."""
    opts = [{'v': 'off', 'l': 'off'}]
    try:
        from zyg_workflows import asset_library_service as _als
    except Exception:  # noqa: BLE001 — optional at import
        return opts
    found = []
    for cat in _BED_CATS:
        try:
            meta = _als._load_audio_meta(cat)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('ambience category %s skipped, its audio metadata did not load: %s', cat, _exc)
            continue
        for fn, md in (meta or {}).items():
            if not isinstance(md, dict) or md.get('commercial_ok') is not True:
                continue
            if md.get('banned') or md.get('deleted'):
                continue
            low = str(fn).lower()
            if any(wrd in low for wrd in _BED_WORDS):
                found.append((cat, str(fn)))
    for cat, fn in sorted(found)[:_BED_MAX]:
        opts.append({'v': f'{cat}/{fn}', 'l': f'{cat} · {os.path.splitext(fn)[0][:52]}'})
    return opts


# pathway → (workflow name, node-1 model override or None when the graph
# already names its own models, as wan22's dual-expert graph does)
PATHWAYS = {
    'wan21_480p': ('wan_i2v', 'Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors'),
    'wan21_720p': ('wan_i2v', 'Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors'),
    'wan22': ('wan22_i2v', None),
}
_DEF_PATHWAY = 'wan22' if _wan._WAN22 else 'wan21_480p'

RESOLUTIONS = ['832x480', '480x832', '640x640', '960x544', '544x960', '1280x720', '720x1280']
