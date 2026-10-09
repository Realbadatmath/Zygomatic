# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tile caption writing and the caption axis tokenizer.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 3625-3804).
"""

from __future__ import annotations

import os
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    DEFAULT_CELL_H,
    DEFAULT_CELL_W,
    DEFAULT_COLS,
    DEFAULT_GUTTER,
    DEFAULT_ROWS,
    _zyg_log,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _angle_label,
    build_identity_snippet,
    load_manifest,
    master_sheet_path,
    training_dataset_dir,
    trigger_token_for,
    write_manifest,
)
from zyg_workflows.contact_sheet_pipeline.angle_edit import (
    EXPRESSIONS,
    _CORPUS_CLOSEUP_PHRASES,
    _CORPUS_LIGHTING_PHRASES,
)
from zyg_workflows.contact_sheet_pipeline.sheet_prep import caption_style_description


def _caption_axis_tokens(angle: str) -> tuple[str, list[str]]:
    """Split corpus axis phrases off an angle label → (base_angle, tokens).

    Caption contract (2026-08-09): '{trigger}, {gender}, {angle},
    {expression?}, {lighting?}, {framing?}, {style}' — ONLY tokens that VARY
    per cell; identity attributes stay OUT (trigger-binding rule, see the
    comment in write_tile_captions). Corpus labels append their axis phrases
    comma-separated, so they strip cleanly; legacy labels that embed lighting/
    framing words inline are returned unchanged (the label already IS the
    varying token)."""
    base = (angle or '').strip()
    expr_tok: str | None = None
    light_tok: str | None = None
    framing_tok: str | None = None
    changed = True
    while changed:
        changed = False
        low = base.lower()
        for key in EXPRESSIONS:
            if expr_tok is None and low.endswith(', ' + key):
                base = base[: -(len(key) + 2)].rstrip(', ')
                expr_tok = key
                changed = True
                break
        if changed:
            continue
        for phrase in _CORPUS_LIGHTING_PHRASES:
            if light_tok is None and low.endswith(', ' + phrase):
                base = base[: -(len(phrase) + 2)].rstrip(', ')
                light_tok = phrase
                changed = True
                break
        if changed:
            continue
        for phrase in _CORPUS_CLOSEUP_PHRASES + ('close-up face',):
            if framing_tok is None and low.endswith(', ' + phrase):
                base = base[: -(len(phrase) + 2)].rstrip(', ')
                framing_tok = phrase
                changed = True
                break
    tokens = [t for t in (expr_tok, light_tok, framing_tok) if t]
    return (base or (angle or '').strip()), tokens


def write_tile_captions(
    char_id: str,
    params: dict,
    tiles: list[dict] | None = None,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> int:
    """Write .txt caption beside each tile; copy tiles to char dataset root for SimpleTuner."""
    manifest = load_manifest(char_id) or {}
    tile_list = tiles or manifest.get('tiles') or []
    if not tile_list:
        raise RuntimeError('No tiles to caption — run tile_crop first')

    trigger = trigger_token_for(char_id)
    # Trigger-binding: caption only the TRIGGER + a bare class noun + what VARIES
    # (angle, style) — NOT the full identity descriptor. Restating "fair skin,
    # green eyes, brown hair, oval face…" on every tile made those attributes
    # bind to their own tokens and left the trigger carrying almost no identity
    # (2026-07-12: the trained trigger rendered a brown-eyed stranger). Standard
    # Dreambooth/LoRA practice: the invariant identity must bind to the rare
    # trigger token. ZYG_LORA_CAPTION_IDENTITY=1 restores the old verbose form.
    _verbose_ident = os.environ.get('ZYG_LORA_CAPTION_IDENTITY', '0').strip().lower() in ('1', 'true', 'yes', 'on')
    if _verbose_ident:
        ident = build_identity_snippet(params)
    else:
        _gender = (params or {}).get('gender', 'person').strip() or 'person'
        ident = _gender
    style = caption_style_description((params or {}).get('style', 'photorealistic'))
    dataset_dir = training_dataset_dir(char_id)
    os.makedirs(dataset_dir, exist_ok=True)

    # Operator curation dir: tiles the operator moved out by hand (png+txt in
    # training_excluded_manual/, sibling of the dataset dir) must STAY out —
    # they are QC-passers, so without this every resume re-captioned them
    # straight back into the dataset (would have undone Iris Weber's curation).
    _manual_dir = os.path.join(os.path.dirname(dataset_dir), 'training_excluded_manual')

    count = 0
    skipped_qc = 0
    skipped_manual = 0
    for t in tile_list:
        src = t.get('path') or ''
        if not src or not os.path.isfile(src):
            continue
        if t.get('exclude_from_dataset'):
            skipped_qc += 1
            continue
        idx = int(t.get('index', count))
        # C: a tile flagged angle_neutral is a strong-identity image whose actual
        # pose does not match its angle label (Qwen snapped it back to front). Drop
        # the specific angle so we don't caption a front image as a "90° profile".
        if t.get('angle_neutral'):
            angle = 'front view, character reference'
            axis_tokens: list[str] = []
        else:
            angle = t.get('angle') or _angle_label(idx)
            # Corpus axis split: expression/lighting/framing become their own
            # caption tokens (they vary per cell — trigger binding unharmed).
            angle, axis_tokens = _caption_axis_tokens(angle)
        stem = f'contactsheet_{idx:03d}'
        _legacy_stem = f'contactsheet_{idx:02d}'
        # Operator curation dir may hold pre-migration 02d names — honor both.
        if os.path.isfile(os.path.join(_manual_dir, f'{stem}.png')) or os.path.isfile(
            os.path.join(_manual_dir, f'{_legacy_stem}.png')
        ):
            skipped_manual += 1
            continue
        dest_png = os.path.join(dataset_dir, f'{stem}.png')
        dest_txt = os.path.join(dataset_dir, f'{stem}.txt')
        import shutil

        shutil.copy2(src, dest_png)
        # 03d migration: a stale 02d pair for the same index would double the
        # tile in every prefix listing — remove it.
        if _legacy_stem != stem:
            for _lext in ('.png', '.txt'):
                _lp = os.path.join(dataset_dir, f'{_legacy_stem}{_lext}')
                if os.path.isfile(_lp):
                    try:
                        os.remove(_lp)
                    except OSError as _exc:
                        _zyg_log.warning(
                            'stale 02d dataset file %s not removed, listings may see the tile twice: %s', _lp, _exc
                        )
        caption = ', '.join(
            [trigger, ident, angle] + axis_tokens + [style],
        )
        with open(dest_txt, 'w', encoding='utf-8') as fh:
            fh.write(caption.strip() + '\n')
        t['dataset_path'] = dest_png
        count += 1

    # Preserve ALL non-core extras — this write previously kept only
    # {captioned, dataset_dir}, silently nuking generation_mode, cell_paths,
    # identity_qc and the dual-sheet specs from the manifest.
    cap_extra = {
        k: manifest[k]
        for k in manifest
        if k
        not in (
            'char_id',
            'pipeline',
            'rows',
            'cols',
            'gutter_px',
            'cell_width',
            'cell_height',
            'sheet_path',
            'approved',
            'approved_at',
            'tiles',
            'updated_at',
        )
    }
    cap_extra['captioned'] = count
    cap_extra['dataset_dir'] = dataset_dir
    write_manifest(
        char_id,
        rows=int(manifest.get('rows') or DEFAULT_ROWS),
        cols=int(manifest.get('cols') or DEFAULT_COLS),
        gutter=int(manifest.get('gutter_px') or DEFAULT_GUTTER),
        cell_w=int(manifest.get('cell_width') or DEFAULT_CELL_W),
        cell_h=int(manifest.get('cell_height') or DEFAULT_CELL_H),
        sheet_path=manifest.get('sheet_path') or master_sheet_path(char_id),
        approved=bool(manifest.get('approved')),
        tiles=tile_list,
        extra=cap_extra,
    )
    if log_fn:
        note = f' ({skipped_qc} drifted tiles excluded by identity QC)' if skipped_qc else ''
        if skipped_manual:
            note += f' ({skipped_manual} tiles excluded by operator curation)'
        log_fn(f'Captions written for {count} tiles{note} (dataset: {dataset_dir})')
    return count
