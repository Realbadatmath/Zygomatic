# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Perceptual-hash dataset de-duplication and dataset manifest sync.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 4421-4601).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    DEFAULT_CELL_H,
    DEFAULT_CELL_W,
    DEFAULT_COLS,
    DEFAULT_GUTTER,
    DEFAULT_ROWS,
    _DATASET_ROOT,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _ams_iso,
    append_run_log,
    load_manifest,
    master_sheet_path,
    trigger_token_for,
    write_manifest,
)
from zyg_workflows.contact_sheet_pipeline.angle_edit import (
    _angle_rotation_deg,
    _is_closeup_zoom_angle,
    _is_relight_angle,
    _lighting_grade_kind,
)
from zyg_workflows.contact_sheet_pipeline.identity_qc import (
    _dedup_clusters,
    _dhash64,
)


def dedup_dataset_tiles(
    char_id: str,
    tiles: list[dict],
    *,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Intra-set near-duplicate exclusion before dataset export (2026-08-09).

    Runs AFTER identity-QC exclusions, BEFORE captions/sync: perceptual dHash
    per kept tile; Hamming ≤ ZYG_SHEET_DEDUP_HAMMING (default 4) forms a
    duplicate cluster; the member with the highest identity score trains, the
    rest are excluded with reason 'near_duplicate' — they STAY in the sheet,
    exactly like the waxy band. Additionally caps derived cells at 2 per crop
    source ('derived_cap'), dropping the lowest-identity extras. Writes a
    summary into the manifest + run log; never raises.
    """
    try:
        _ham_max = int(os.environ.get('ZYG_SHEET_DEDUP_HAMMING', '4'))
    except ValueError:
        _ham_max = 4
    summary: dict[str, Any] = {
        'hamming_max': _ham_max,
        'checked': 0,
        'clusters': 0,
        'near_duplicate_excluded': 0,
        'derived_cap_excluded': 0,
        'checked_at': _ams_iso(),
    }
    try:
        manifest = load_manifest(char_id) or {}
        plan_cells = (manifest.get('cell_plan') or {}).get('cells') or []
        plan_by_idx = {i: c for i, c in enumerate(plan_cells) if isinstance(c, dict)}
        # In-memory tiles may predate QC flag writeback (resume path) — merge
        # stored per-index flags/scores so exclusions and rankings hold.
        stored_by_idx = {int(t.get('index', -1)): t for t in (manifest.get('tiles') or []) if isinstance(t, dict)}

        def _ident(t: dict) -> float:
            s = t.get('identity_score')
            if not isinstance(s, (int, float)):
                s = (stored_by_idx.get(int(t.get('index', -1)), {}) or {}).get('identity_score')
            return float(s) if isinstance(s, (int, float)) else -1.0

        def _already_excluded(t: dict) -> bool:
            if t.get('exclude_from_dataset'):
                return True
            st = stored_by_idx.get(int(t.get('index', -1))) or {}
            return bool(st.get('exclude_from_dataset'))

        kept = [t for t in tiles if t.get('path') and os.path.isfile(t['path']) and not _already_excluded(t)]
        summary['checked'] = len(kept)
        hashes = [_dhash64(t['path']) for t in kept]
        clusters = _dedup_clusters(hashes, _ham_max)
        summary['clusters'] = len(clusters)
        for group in clusters:
            members = [kept[i] for i in group]
            # Highest identity trains; the anchor (index 0) wins ties by the
            # lower-index tiebreak. Everything else is exhibition-only.
            members.sort(key=lambda t: (-_ident(t), int(t.get('index', 0))))
            for loser in members[1:]:
                loser['exclude_from_dataset'] = True
                loser['exclude_reason'] = 'near_duplicate'
                loser['near_duplicate_of'] = int(members[0].get('index', 0))
                summary['near_duplicate_excluded'] += 1
                if log_fn:
                    log_fn(
                        f'Dedup: tile {loser.get("index")} ≈ tile '
                        f'{members[0].get("index")} (dHash ≤ {_ham_max}) — '
                        f'excluded from dataset as near_duplicate (kept in sheet)',
                    )

        # Derived-per-source cap: ≤2 exported derived (relight/close-up) cells
        # per crop source; the corpus plan records each source label, legacy
        # sheets group by (rotation, grade-kind).
        groups: dict[str, list[dict]] = {}
        for t in kept:
            if t.get('exclude_from_dataset'):
                continue
            idx = int(t.get('index', -1))
            angle = t.get('angle') or ''
            plan_c = plan_by_idx.get(idx) or {}
            is_derived = plan_c.get('kind') == 'derived' or _is_relight_angle(angle) or _is_closeup_zoom_angle(angle)
            if not is_derived:
                continue
            src = plan_c.get('source_label')
            if not src:
                kind = _lighting_grade_kind(angle) or ('closeup' if _is_closeup_zoom_angle(angle) else 'derived')
                src = f'{_angle_rotation_deg(angle)}:{kind}'
            groups.setdefault(src, []).append(t)
        _derived_cap = 2
        for src, members in groups.items():
            if len(members) <= _derived_cap:
                continue
            members.sort(key=lambda t: (-_ident(t), int(t.get('index', 0))))
            for loser in members[_derived_cap:]:
                loser['exclude_from_dataset'] = True
                loser['exclude_reason'] = 'derived_cap'
                summary['derived_cap_excluded'] += 1
                if log_fn:
                    log_fn(
                        f'Dedup: tile {loser.get("index")} dropped from dataset '
                        f'— derived cap ({_derived_cap} per source) for source '
                        f"'{str(src)[:50]}'",
                    )

        # Persist: summary + updated tile flags survive the captions-stage
        # manifest rewrite (write_tile_captions preserves non-core extras).
        extra = {
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
        extra['dataset_dedup'] = summary
        write_manifest(
            char_id,
            rows=int(manifest.get('rows') or DEFAULT_ROWS),
            cols=int(manifest.get('cols') or DEFAULT_COLS),
            gutter=int(manifest.get('gutter_px') or DEFAULT_GUTTER),
            cell_w=int(manifest.get('cell_width') or DEFAULT_CELL_W),
            cell_h=int(manifest.get('cell_height') or DEFAULT_CELL_H),
            sheet_path=manifest.get('sheet_path') or master_sheet_path(char_id),
            approved=bool(manifest.get('approved')),
            tiles=tiles,
            extra=extra,
        )
        append_run_log(
            char_id,
            f'Dataset dedup: {summary["checked"]} tiles checked, '
            f'{summary["clusters"]} duplicate cluster(s), '
            f'{summary["near_duplicate_excluded"]} near-duplicate + '
            f'{summary["derived_cap_excluded"]} derived-cap exclusions '
            f'(hamming ≤ {_ham_max})',
        )
        if log_fn:
            log_fn(
                f'Dataset dedup: {summary["near_duplicate_excluded"]} near-duplicate, '
                f'{summary["derived_cap_excluded"]} derived-cap exclusion(s) '
                f'across {summary["checked"]} kept tiles',
            )
    except Exception as exc:
        summary['error'] = str(exc)[:200]
        if log_fn:
            log_fn(f'Dataset dedup skipped ({str(exc)[:120]})')
    return summary


def sync_dataset_manifest(char_id: str, params: dict, image_paths: list[str]) -> str:
    """Update storyteller_chars manifest.json for LoRA trainer discovery."""
    dataset_dir = os.path.join(_DATASET_ROOT, char_id)
    manifest_file = os.path.join(dataset_dir, 'manifest.json')
    payload = {
        'name': (params or {}).get('name') or char_id[:8],
        'style': (params or {}).get('style') or 'photorealistic',
        'gender': (params or {}).get('gender') or '',
        'hair_color': (params or {}).get('hair_color') or '',
        'eye_color': (params or {}).get('eye_color') or '',
        'skin_tone': (params or {}).get('skin_tone') or '',
        'source': 'contact_sheet',
        'render_mode': 'contact_sheet',
        'images': image_paths,
        'total': len(image_paths),
        'trigger_token': trigger_token_for(char_id),
    }
    with open(manifest_file, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=2)
    return manifest_file
