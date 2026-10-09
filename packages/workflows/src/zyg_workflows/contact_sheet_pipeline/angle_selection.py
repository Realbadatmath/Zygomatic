# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Angle catalog + operator angle selection (2026-09-16).

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 314-426).
"""

from __future__ import annotations

from zyg_workflows.contact_sheet_pipeline.constants import (
    SHEET_ANGLES_BY_PART,
    _CLASSIC_PARTS,
    sheet_parts_for,
)


# ── Angle catalog + operator angle selection (2026-09-16) ──────────────────
# The Character Studio lets an operator choose how many angles a run renders
# and which ones. A selection crosses the wire as stable IDS — '<part><1-6>',
# e.g. 'a1' — not as prose, so a stored plan survives any rewording of a label
# and an unknown id is dropped instead of silently becoming a bogus cell spec.
#
# Index 0 of ANY plan is the identity ANCHOR (cell_00): every other cell is a
# Qwen edit of it, so the front head-and-shoulders view is forced first
# whatever the operator ticked — a plan anchored on, say, a back view would
# hand all the remaining cells a face they cannot see.
ANCHOR_ANGLE_ID = 'a1'

ANGLE_GROUP_TITLES: dict[str, str] = {
    'a': 'Core yaw ring — head & shoulders',
    'b': 'Pitch, smiles & face close-up',
    'c': 'Lighting keys & medium shots',
    'd': 'Medium shots, close-ups & rim light',
    'e': 'Full-body yaw ring — A-pose',
    'f': 'High / low camera ring',
    'g': 'Fine head-yaw ring',
    'h': 'Crown, chin & T-pose turnaround',
}


def angle_catalog(angle_set: str | None = 'extended') -> list[dict]:
    """Every selectable angle as ``{id, part, group, index, label}``, in plan
    order. This is the one source the GUIs render their angle pickers from."""
    out: list[dict] = []
    for part in sheet_parts_for(angle_set):
        for i, label in enumerate(SHEET_ANGLES_BY_PART.get(part, []), start=1):
            out.append(
                {
                    'id': f'{part}{i}',
                    'part': part,
                    'group': ANGLE_GROUP_TITLES.get(part, f'Sheet {part.upper()}'),
                    'index': i,
                    'label': label,
                }
            )
    return out


ANGLE_CATALOG = angle_catalog('extended')
_ANGLE_LABEL_BY_ID: dict[str, str] = {a['id']: a['label'] for a in ANGLE_CATALOG}
_ANGLE_ID_BY_LABEL: dict[str, str] = {a['label']: a['id'] for a in ANGLE_CATALOG}

# Named starting points for the picker. Each is a plain id list, so a preset is
# just a pre-ticked custom selection the operator can then edit.
ANGLE_PRESETS: dict[str, dict] = {
    'extended': {
        'title': 'Extended — all 48',
        'ids': [a['id'] for a in ANGLE_CATALOG],
    },
    'classic': {
        'title': 'Classic — 24 (sheets A–D)',
        'ids': [a['id'] for a in ANGLE_CATALOG if a['part'] in _CLASSIC_PARTS],
    },
    'head': {
        'title': 'Head & shoulders — 12',
        'ids': [a['id'] for a in ANGLE_CATALOG if a['part'] in ('a', 'g')],
    },
    'body': {
        'title': 'Full-body turnaround — 12',
        'ids': [a['id'] for a in ANGLE_CATALOG if a['part'] in ('e', 'h')],
    },
    'minimal': {
        'title': 'Minimal — 6 core yaw',
        'ids': [a['id'] for a in ANGLE_CATALOG if a['part'] == 'a'],
    },
}


def angle_ids_to_labels(ids, *, force_anchor: bool = True) -> list[str]:
    """Resolve an operator selection (angle ids, or exact angle labels) to the
    ordered label list a per-cell run generates. Unknown tokens and duplicates
    are dropped; the front anchor view is prepended unless it is already first.
    Returns [] for an empty/unusable selection — callers must not treat that
    as 'render everything'."""
    labels: list[str] = []
    seen: set[str] = set()
    for raw in ids or []:
        tok = str(raw or '').strip()
        if not tok:
            continue
        label = _ANGLE_LABEL_BY_ID.get(tok.lower())
        if label is None and tok in _ANGLE_ID_BY_LABEL:
            label = tok
        if label is None or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    if not labels:
        return []
    if force_anchor:
        anchor = _ANGLE_LABEL_BY_ID[ANCHOR_ANGLE_ID]
        if labels[0] != anchor:
            if anchor in seen:
                labels.remove(anchor)
            labels.insert(0, anchor)
    return labels


def labels_to_angle_ids(labels) -> list[str]:
    """Inverse of angle_ids_to_labels — for showing a stored plan in a picker."""
    return [_ANGLE_ID_BY_LABEL[l] for l in (labels or []) if l in _ANGLE_ID_BY_LABEL]


def custom_angle_labels_for_job(job: dict | None) -> list[str]:
    """The custom plan carried by a run job (``angle_ids`` preferred,
    ``angle_labels`` accepted), or [] when there is no usable selection."""
    j = job or {}
    return angle_ids_to_labels(j.get('angle_ids') or j.get('angle_labels') or [])
