# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.medusa_sheet_service.constants import (
    COVERAGE_FRAMINGS,
    COVERAGE_GROUPS,
    COVERAGE_PITCHES,
    COVERAGE_SIDED_PAIRS,
    _CELL_PX,
    _DUPE_HAMMING_MAX,
    _LABEL_PX,
    _PAGE_NAME_RE,
    _SHEET_COLS,
    _SHEET_ROWS,
    os,
)

import logging as _zyg_logging

# Bound by ASSIGNMENT (not `from .constants import _zyg_log`) so the moved
# `_zyg_log.debug(...)` calls keep compiling to the same method form; the
# channel is kept from the pre-split module.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.medusa_sheet_service')


# ══════════════════════════════════════════════════════════════════════════
# Coverage report
# ══════════════════════════════════════════════════════════════════════════
def coverage_report(measures: list[dict]) -> dict:
    usable = [m for m in measures if not m.get('error') and 'no_person_detected' not in (m.get('flags') or [])]
    by_yaw: dict[str, int] = {}
    by_framing: dict[str, int] = {}
    by_pitch: dict[str, int] = {}
    for m in usable:
        y = m.get('yaw_slot') or 'unknown'
        by_yaw[y] = by_yaw.get(y, 0) + 1
        f = m.get('framing_slot') or 'unknown'
        by_framing[f] = by_framing.get(f, 0) + 1
        p = m.get('pitch_slot') or 'unknown'
        by_pitch[p] = by_pitch.get(p, 0) + 1

    group_counts = {g: sum(by_yaw.get(s, 0) for s in slots) for g, slots in COVERAGE_GROUPS.items()}
    covered = [g for g, n in group_counts.items() if n]
    missing = [g for g, n in group_counts.items() if not n]

    # A group can be "covered" yet lopsided — six left profiles and no right.
    sided_gaps = []
    for group, left, right in COVERAGE_SIDED_PAIRS:
        nl, nr = by_yaw.get(left, 0), by_yaw.get(right, 0)
        if (nl or nr) and not (nl and nr):
            sided_gaps.append({'group': group, 'have': left if nl else right, 'missing': right if nl else left})

    return {
        'usable': len(usable),
        'total': len(measures),
        'by_yaw': by_yaw,
        'by_framing': by_framing,
        'by_pitch': by_pitch,
        'group_counts': group_counts,
        'yaw_covered': covered,
        'yaw_missing': missing,
        'sided_gaps': sided_gaps,
        'unknown_angle': by_yaw.get('unknown', 0),
        'framing_missing': [f for f in COVERAGE_FRAMINGS if not by_framing.get(f)],
        'pitch_missing': [p for p in COVERAGE_PITCHES if not by_pitch.get(p)],
        'yaw_coverage_pct': round(100.0 * len(covered) / max(1, len(COVERAGE_GROUPS)), 1),
    }


def _duplicate_groups(measures: list[dict]) -> list[list[str]]:
    """Near-duplicate clusters by dhash Hamming distance."""
    items = [(m['file'], m.get('dhash')) for m in measures if m.get('dhash') is not None]
    seen: set[int] = set()
    groups: list[list[str]] = []
    for i in range(len(items)):
        if i in seen:
            continue
        fi, hi = items[i]
        grp = [fi]
        for j in range(i + 1, len(items)):
            if j in seen:
                continue
            fj, hj = items[j]
            if bin(hi ^ hj).count('1') <= _DUPE_HAMMING_MAX:
                grp.append(fj)
                seen.add(j)
        if len(grp) > 1:
            groups.append(grp)
        seen.add(i)
    return groups


# ══════════════════════════════════════════════════════════════════════════
# Montage
# ══════════════════════════════════════════════════════════════════════════
# Montage order: sweep the yaw ring left-to-right so a gap in coverage is
# visible as a gap in the sheet.
_SLOT_ORDER = {
    name: i
    for i, name in enumerate(
        [
            'profile_left',
            'strong_three_quarter_left',
            'three_quarter_left',
            'near_frontal_left',
            'front',
            'near_frontal_right',
            'three_quarter_right',
            'strong_three_quarter_right',
            'profile_right',
            'profile_unsided',
            'back_three_quarter',
            'back',
            'unknown',
        ]
    )
}

_SHORT = {
    'front': 'front',
    'near_frontal_left': 'nf-L',
    'near_frontal_right': 'nf-R',
    'three_quarter_left': '3q-L',
    'three_quarter_right': '3q-R',
    'strong_three_quarter_left': '3q+L',
    'strong_three_quarter_right': '3q+R',
    'profile_left': 'prof-L',
    'profile_right': 'prof-R',
    'profile_unsided': 'prof-?',
    'back_three_quarter': 'b3q',
    'back': 'back',
    'unknown': '?',
}


def build_montage(
    measures: list[dict],
    image_dir: str,
    out_dir: str,
    cols: int = _SHEET_COLS,
    rows: int = _SHEET_ROWS,
    cell_px: int = _CELL_PX,
) -> list[str]:
    """Assemble labelled contact-sheet pages, ordered by canonical slot."""
    from PIL import Image, ImageDraw, ImageFont

    ordered = sorted(
        [m for m in measures if not m.get('error')],
        key=lambda m: (
            _SLOT_ORDER.get(m.get('yaw_slot') or 'unknown', 99),
            m.get('framing_slot') or '',
            m.get('file') or '',
        ),
    )
    if not ordered:
        return []

    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    except Exception:
        font = ImageFont.load_default()

    per_page = max(1, cols * rows)
    pages: list[str] = []
    os.makedirs(out_dir, exist_ok=True)

    # Clear pages from a previous build first. A rebuild after removing photos
    # produces fewer pages, and the leftovers would stay on disk unlisted in
    # sheet.json yet still servable.
    try:
        for old in os.listdir(out_dir):
            if _PAGE_NAME_RE.match(old):
                try:
                    os.remove(os.path.join(out_dir, old))
                except OSError as _exc:
                    _zyg_log.debug('stale montage page %s removal skipped: %s', old, _exc)
    except OSError as _exc:
        _zyg_log.debug('montage page sweep of %s skipped: %s', out_dir, _exc)

    for page_idx in range(0, len(ordered), per_page):
        chunk = ordered[page_idx : page_idx + per_page]
        n_rows = (len(chunk) + cols - 1) // cols
        cell_h = cell_px + _LABEL_PX
        canvas = Image.new('RGB', (cols * cell_px, n_rows * cell_h), (18, 18, 20))
        draw = ImageDraw.Draw(canvas)

        for i, m in enumerate(chunk):
            cx = (i % cols) * cell_px
            cy = (i // cols) * cell_h
            src = os.path.join(image_dir, m['file'])
            try:
                im = Image.open(src).convert('RGB')
                im.thumbnail((cell_px, cell_px), Image.LANCZOS)
                canvas.paste(im, (cx + (cell_px - im.width) // 2, cy + (cell_px - im.height) // 2))
            except Exception:
                draw.rectangle([cx, cy, cx + cell_px - 2, cy + cell_px - 2], outline=(90, 40, 40))

            slot = m.get('yaw_slot') or 'unknown'
            label = _SHORT.get(slot, slot)
            fr = (m.get('framing_slot') or '')[:2]
            conf = m.get('angle_confidence') or 'none'
            colour = {'high': (150, 220, 150), 'medium': (220, 200, 130), 'low': (220, 160, 110)}.get(
                conf, (220, 110, 110)
            )
            if m.get('flags'):
                colour = (230, 130, 130)
            draw.text((cx + 4, cy + cell_px + 3), f'{label} · {fr}', fill=colour, font=font)

        p = os.path.join(out_dir, f'medusa_sheet_{len(pages) + 1:02d}.png')
        canvas.save(p, 'PNG')
        pages.append(p)
    return pages
