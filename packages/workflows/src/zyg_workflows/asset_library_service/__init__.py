# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""asset_library_service.py — GENERIC shared asset libraries (props/objects/scenery/audio).

One engine powering the Asset-Manager category tabs:
    visual : items, food, weapons, agriculture, water, clouds, geology
    audio  : sfx, vocal_fx, soundtracks

`sfx` is the AMBIENCE/environment library — the handful of beds a scene lays under
dialogue (waves, creak, gulls). `vocal_fx` is kept separate deliberately: it holds the
344 Audio Human Mouth Noises library (315 files), and merging 315 mouth noises into a
7-file bed picker would make choosing a bed impossible. They are different jobs — a bed
loops under a whole scene, a vocal fx is a one-shot placed on a beat.

Built from the prop-library research (2026-07-29): props/objects are STORED ASSETS applied
deterministically — never free prompt tokens inside multi-subject prompts (that caused the
quill-bleed / missing-pipe defects). Each visual record carries an `anchor` that decides HOW
"Apply to character" edits the render via Qwen-Image-Edit (same Apache-2.0 engine as wardrobe):
    held-in-hand : placed in the character's hand, fingers-wrapped grip instruction
    on-table     : placed on the surface in front of the character
    scene        : the render's BACKGROUND/setting is changed to the asset (water/clouds/etc.)
A presence-QC gate (image-delta) flags silent no-op edits ("prop went missing" regressions).

Audio categories are file-backed: drop .wav/.mp3/.ogg/.flac files into
data/asset_libraries/<cat>/ and they appear as cards (the file itself is the preview).

Public API:
    categories() / category_info(cat)
    load_assets(cat) / get_asset(cat, id) / add_asset(cat, rec) / remove_asset(cat, id)
    get_audio_meta(cat, file_id) / set_audio_meta(cat, file_id, meta)   # license sidecar
    preview_path(cat, id) / has_preview(cat, id) / generate_preview / ensure_previews
    apply_asset(cat, asset_id, char_id, out_path, base_image=None) -> (path|None, qc_dict)

2026-07-30: audio records carry a license-metadata SIDECAR (data/runtime/
asset_library_<cat>_meta.json, keyed by filename). WHY: published episodes are commercial —
every library sound must prove its provenance (source_url, license_id, commercial_ok,
attribution) or the ambience_ingest.license_gate blocks it at publish time. The sidecar is
separate from the file-backed records so dropping a raw file in still works (it just audits
as un-cleared until metadata is set).
"""

# ruff: noqa: F401,E402  this __init__ IS the re-export surface of the old asset_library_service.py.

# The submodules are imported in the original section order, so any module-level
# side effect still runs exactly when it did in the single-file asset_library_service.py.
from zyg_workflows.asset_library_service.catalog import (
    os,
    json,
    copy,
    math,
    threading,
    _zyg_logging,
    paths,
    _zyg_log,
    _HERE,
    _CHARS_ROOT,
    _AUDIO_ROOT,
    _AUDIO_EXTS,
    _CATEGORIES,
    _DEFAULTS,
    _log_noop,
    categories,
    category_info,
    _lib_path,
    _audio_dir,
)
from zyg_workflows.asset_library_service.audio_meta import (
    _audio_meta_path,
    _AUDIO_META_LOCK,
    _load_audio_meta_strict,
    _load_audio_meta,
    get_audio_meta,
    set_audio_meta,
    set_audio_meta_many,
)
from zyg_workflows.asset_library_service.assets import (
    load_assets,
    save_assets,
    get_asset,
    add_asset,
    remove_asset,
    _preview_dir,
    preview_path,
    has_preview,
    generate_preview,
    ensure_previews,
)
from zyg_workflows.asset_library_service.apply import (
    _char_base_image,
    _apply_instruction,
    _presence_qc,
    apply_asset,
)
