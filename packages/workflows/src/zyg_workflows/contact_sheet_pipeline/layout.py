# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""On-disk layout: run directories, anchors, run log, manifest I/O.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 727-1018, 3347-3390).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    CONTACT_SHEET_ANGLE_LABELS,
    SHEET_ANGLES_BY_PART,
    SHEET_A_ANGLES,
    _AMS,
    _DATASET_ROOT,
    _EXTENDED_PARTS,
    _zyg_log,
)


def _stem_index(name: str) -> int:
    """Numeric index parsed from a cell_/tile_/contactsheet_/regen_/expansion_
    filename. Lexical sorts break at the 02d→03d boundary ('tile_100' sorts
    before 'tile_48'); every listing over these stems must sort by THIS."""
    import re as _re_si

    m = _re_si.search(r'_(\d+)', os.path.basename(name or ''))
    return int(m.group(1)) if m else -1


def _find_indexed_file(dirpath: str, stem: str, idx: int, ext: str = '.png') -> str:
    """Read-side 03d/02d compatibility: prefer the {idx:03d} name, fall back to
    a pre-migration {idx:02d} file, else return the (new) 03d path."""
    p3 = os.path.join(dirpath, f'{stem}_{idx:03d}{ext}')
    if os.path.isfile(p3):
        return p3
    p2 = os.path.join(dirpath, f'{stem}_{idx:02d}{ext}')
    if os.path.isfile(p2):
        return p2
    return p3


def _anchor_cell_path(char_id: str) -> str:
    """The head anchor cell on disk — cell_000.png (03d era) or the legacy
    cell_00.png. Returns the 03d path when neither exists yet."""
    return _find_indexed_file(os.path.join(contact_sheet_dir(char_id), 'cells'), 'cell', 0)


def _body_anchor_path_for(char_id: str) -> str:
    """Body anchor lookup with 03d/02d read compatibility."""
    cdir = os.path.join(contact_sheet_dir(char_id), 'cells')
    for name in ('cell_000_body.png', 'cell_00_body.png'):
        p = os.path.join(cdir, name)
        if os.path.isfile(p):
            return p
    return os.path.join(cdir, 'cell_000_body.png')


def _resolve_anchor_family(job: dict | None) -> str:
    """Anchor render family for the FLUX exit (2026-08-09): job['anchor_family']
    or ZYG_SHEET_ANCHOR_FAMILY; 'auto' = qwen while FLUX renders are
    licence-paused, flux otherwise."""
    fam = (
        str(
            (job or {}).get('anchor_family') or os.environ.get('ZYG_SHEET_ANCHOR_FAMILY', 'auto'),
        )
        .strip()
        .lower()
    )
    if fam not in ('flux', 'qwen', 'klein', 'auto'):
        fam = 'auto'
    if fam == 'auto':
        try:
            from zyg_workflows import licence_provenance as _lp

            fam = 'qwen' if _lp.flux_paused() else 'flux'
        except Exception:
            fam = 'flux'
    return fam


def _ams_iso() -> str:
    return datetime.now(_AMS).isoformat(timespec='milliseconds')


def contact_sheet_dir(char_id: str) -> str:
    return os.path.join(_DATASET_ROOT, char_id, 'contact_sheet')


def tiles_dir(char_id: str) -> str:
    return os.path.join(contact_sheet_dir(char_id), 'tiles')


def training_sheet_path(char_id: str) -> str:
    """Composite of ONLY the training-set tiles — see stitch_training_sheet."""
    return os.path.join(contact_sheet_dir(char_id), 'contact_sheet_training.png')


def stitch_training_sheet(char_id: str, log_fn: Callable[[str], None] | None = None) -> str | None:
    """Stitch a composite of ONLY the tiles that actually train (2026-07-20).

    The master sheet keeps excluded tiles for exhibition ("kept in sheet,
    excluded from dataset"), so the review card could not show what an Allow
    actually approves. This sheet is the curated dataset, nothing else —
    contactsheet_* plus any expansion_* tiles, in index order, 6 per row.
    """
    try:
        from PIL import Image

        tdir = training_dataset_dir(char_id)
        if not os.path.isdir(tdir):
            return None
        # Numeric index sort — a lexical sort breaks at the 02d→03d stem
        # boundary once corpus runs write contactsheet_100+ (2026-08-09).
        names = sorted(
            (f for f in os.listdir(tdir) if f.startswith('contactsheet_') and f.endswith('.png')),
            key=_stem_index,
        ) + sorted(
            (f for f in os.listdir(tdir) if f.startswith('expansion_') and f.endswith('.png')),
            key=_stem_index,
        )
        if not names:
            return None
        cols, cell_w, cell_h, gutter = 6, 640, 640, 8
        rows = (len(names) + cols - 1) // cols
        W = cols * cell_w + (cols + 1) * gutter
        H = rows * cell_h + (rows + 1) * gutter
        canvas = Image.new('RGB', (W, H), (18, 18, 22))
        placed = 0
        for i, nm in enumerate(names):
            try:
                im = Image.open(os.path.join(tdir, nm)).convert('RGB')
            except OSError as _exc:
                _zyg_log.debug('contact sheet tile %s unreadable, skipped: %s', nm, _exc)
                continue
            im.thumbnail((cell_w, cell_h), Image.LANCZOS)
            r, c = divmod(i, cols)
            x = gutter + c * (cell_w + gutter) + (cell_w - im.width) // 2
            y = gutter + r * (cell_h + gutter) + (cell_h - im.height) // 2
            canvas.paste(im, (x, y))
            placed += 1
        out = training_sheet_path(char_id)
        canvas.save(out, format='PNG')
        if log_fn:
            log_fn(f'Training-set sheet ({placed} tiles, {W}×{H}) → {out}')
        return out
    except Exception as exc:
        if log_fn:
            log_fn(f'Training-set sheet failed ({exc})')
        return None


def training_dataset_dir(char_id: str) -> str:
    """Trainer-facing dataset dir — png+txt pairs ONLY.

    SimpleTuner discovers images with an unconditional rglob, so pointing it at
    the char root made it trip over the caption-less working files under
    contact_sheet/ (native sheets, masters, tiles). Training reads this subdir.
    """
    return os.path.join(_DATASET_ROOT, char_id, 'training')


def run_log_path(char_id: str) -> str:
    """Full, untrimmed generation log for a run.

    The job-state debug_events buffer is capped at the last 50 entries, so a
    completed run's main-phase detail (per-cell lock choice, QC scores, regen
    attempts) was previously unrecoverable. This file keeps everything.
    """
    return os.path.join(contact_sheet_dir(char_id), 'generation.log')


def append_run_log(char_id: str, msg: str, level: str = 'INFO') -> None:
    """Append one timestamped line to the persistent run log (never raises)."""
    try:
        os.makedirs(contact_sheet_dir(char_id), exist_ok=True)
        with open(run_log_path(char_id), 'a', encoding='utf-8') as fh:
            fh.write(f'[{_ams_iso()}] [{level}] {msg}\n')
    except Exception as _exc:
        _zyg_log.warning('run log append failed, this line stays only in the app log: %s', _exc)


def manifest_path(char_id: str) -> str:
    return os.path.join(contact_sheet_dir(char_id), 'manifest.json')


def master_sheet_path(char_id: str) -> str:
    return os.path.join(contact_sheet_dir(char_id), 'contact_sheet_master.png')


def trigger_token_for(char_id: str) -> str:
    return f'ZYG_CHAR_{char_id[:6].upper()}'


def _angle_label(index: int) -> str:
    if index < len(CONTACT_SHEET_ANGLE_LABELS):
        return CONTACT_SHEET_ANGLE_LABELS[index]
    return f'angle view {index + 1}, character reference'


def _angles_for_sheet_part(part: str) -> list[str]:
    p = (part or 'a').strip().lower()
    return list(SHEET_ANGLES_BY_PART.get(p, SHEET_A_ANGLES))


def build_identity_snippet(params: dict) -> str:
    """Identity phrase for tile captions — covers all key attributes so the
    LoRA training captions condition the trigger on the full character spec."""
    p = params or {}
    parts: list[str] = []
    gender = (p.get('gender') or 'person').strip()
    if gender:
        parts.append(gender)
    skin = (p.get('skin_tone') or '').strip()
    if skin:
        parts.append(f'{skin} skin')
    face_shape = (p.get('face_shape') or '').strip()
    if face_shape:
        parts.append(f'{face_shape} face')
    nose = (p.get('nose_shape') or '').strip()
    if nose and nose.lower() != 'balanced':
        parts.append(f'{nose} nose')
    lips = (p.get('lip_shape') or '').strip()
    if lips:
        parts.append(f'{lips} lips')
    eye_color = (p.get('eye_color') or '').strip()
    eye_shape = (p.get('eye_shape') or '').strip()
    if eye_shape and eye_color:
        parts.append(f'{eye_shape} {eye_color} eyes')
    elif eye_color:
        parts.append(f'{eye_color} eyes')
    hair_color = (p.get('hair_color') or '').strip()
    hair_style = (p.get('hair_style') or '').strip()
    if hair_color and hair_style:
        parts.append(f'{hair_style} {hair_color} hair')
    elif hair_color:
        parts.append(f'{hair_color} hair')
    marks = (p.get('distinctive_marks') or '').strip()
    if marks and marks.lower() not in ('', 'none', 'n/a'):
        parts.append(marks)
    return ', '.join(parts).strip() or 'character'


def _resolve_sheet_mode(mode: str | None) -> str:
    """Normalize sheet mode. ``auto`` → per-cell generation (grid modes proved
    unreliable: FLUX ignores grid geometry and per-panel angle instructions,
    so sliced tiles held half-people with fictional angle labels)."""
    m = (mode or os.environ.get('ZYG_CONTACT_SHEET_MODE', 'auto')).strip().lower()
    if m in ('per_cell', 'per_cell_ipa', 'cell_grid'):
        return 'per_cell'
    if m in ('pose_locked', 'perfect_consistency'):
        return 'pose_locked_cells'
    if m in (
        'mock',
        'cells',
        'single_canvas',
        'dual_canvas',
        'dual',
        'pose_locked_cells',
    ):
        return m
    if m == 'comfy':
        dual = os.environ.get('ZYG_CONTACT_SHEET_DUAL', '1').lower() not in ('0', 'false', 'no')
        return 'dual_canvas' if dual else 'single_canvas'
    return 'per_cell'


def native_sheet_path(char_id: str, sheet_part: str | None = None) -> str:
    if sheet_part in _EXTENDED_PARTS:
        return os.path.join(
            contact_sheet_dir(char_id),
            f'contact_sheet_native_{sheet_part}_1920.png',
        )
    return os.path.join(contact_sheet_dir(char_id), 'contact_sheet_native_1920.png')


def master_sheet_path_part(char_id: str, sheet_part: str) -> str:
    return os.path.join(contact_sheet_dir(char_id), f'contact_sheet_master_{sheet_part}.png')


def identity_anchor_face_path(char_id: str) -> str:
    return os.path.join(contact_sheet_dir(char_id), 'contact_sheet_anchor_face.png')


def identity_profile_anchor_face_path(char_id: str) -> str:
    """Verified side-profile anchor (2026-07-18) — see the profile-anchor gate."""
    return os.path.join(contact_sheet_dir(char_id), 'contact_sheet_profile_anchor_face.png')


def _save_dedup_conflict_image(char_id: str, new_face: str, other_face: str) -> str | None:
    """Side-by-side (new | existing) crop saved when the dedup gate parks
    (2026-07-19) — 0.45-0.55 ArcFace is a gray zone between 'sisters' and
    'same person', so the operator adjudicates visually in seconds instead of
    guessing from a similarity number."""
    try:
        from PIL import Image

        a = Image.open(new_face).convert('RGB')
        b = Image.open(other_face).convert('RGB')
        h = 512
        a = a.resize((max(1, int(a.width * h / a.height)), h))
        b = b.resize((max(1, int(b.width * h / b.height)), h))
        canvas = Image.new('RGB', (a.width + b.width + 12, h), (24, 24, 28))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (a.width + 12, 0))
        out = os.path.join(contact_sheet_dir(char_id), 'dedup_conflict.png')
        canvas.save(out, format='PNG')
        return out
    except Exception:
        return None


def write_manifest(
    char_id: str,
    *,
    rows: int,
    cols: int,
    gutter: int,
    cell_w: int,
    cell_h: int,
    sheet_path: str,
    approved: bool = False,
    tiles: list[dict] | None = None,
    extra: dict | None = None,
) -> dict:
    manifest = {
        'char_id': char_id,
        'pipeline': 'multi_angle_contact_sheet',
        'rows': rows,
        'cols': cols,
        'gutter_px': gutter,
        'cell_width': cell_w,
        'cell_height': cell_h,
        'sheet_path': sheet_path,
        'approved': approved,
        'approved_at': _ams_iso() if approved else None,
        'tiles': tiles or [],
        'updated_at': _ams_iso(),
    }
    if extra:
        manifest.update(extra)
    os.makedirs(contact_sheet_dir(char_id), exist_ok=True)
    with open(manifest_path(char_id), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def load_manifest(char_id: str) -> dict | None:
    path = manifest_path(char_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None
