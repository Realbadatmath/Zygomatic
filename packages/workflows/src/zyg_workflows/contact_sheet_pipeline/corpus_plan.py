# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Corpus plan builder — the 70-240 cell LoRA training corpus.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 472-726).
"""

from __future__ import annotations

from typing import Any, Callable

from zyg_workflows.contact_sheet_pipeline.constants import (
    CORPUS_CELLS_DEFAULT,
    CORPUS_CELLS_MAX,
    CORPUS_CELLS_MIN,
    CORPUS_DERIVED_MAX_FRAC,
    contact_sheet_angle_labels,
)
from zyg_workflows.contact_sheet_pipeline.layout import _ams_iso
from zyg_workflows.contact_sheet_pipeline.angle_edit import (
    EXPRESSIONS,
    _CORPUS_CLOSEUP_PHRASES,
    _CORPUS_LIGHTING_PHRASES,
    _angle_rotation_deg,
    _cell_size_for_angle,
    _framing_clause,
    _is_closeup_zoom_angle,
    _is_full_body_angle,
    _is_relight_angle,
    _is_steep_or_back_angle,
    _qwen_angle_instruction,
)


def _is_expression_base_angle(angle: str) -> bool:
    """Face-visible frontal/three-quarter angles that can carry an expression
    variant — decided with the EXISTING angle-class helpers so every emitted
    label keeps routing to the qwen_edit generate path, never the fallback."""
    a = (angle or '').lower()
    if _is_full_body_angle(a) or _is_steep_or_back_angle(a) or _is_closeup_zoom_angle(a) or _is_relight_angle(a):
        return False
    # Existing expression/lighting wording would fight the added phrase.
    # NOTE: match 'lighting'/'key light', NOT bare 'light' — 'slightly above'
    # contains 'light' as a substring and silently shrank the pool.
    if (
        'profile' in a
        or 'smile' in a
        or 'neutral expression' in a
        or 'lighting' in a
        or 'key light' in a
        or 'rim light' in a
    ):
        return False
    rot = _angle_rotation_deg(a)
    return rot is not None and abs(rot) <= 60


def _plan_hash(labels: list[str]) -> str:
    import hashlib

    return hashlib.sha1('\n'.join(labels).encode('utf-8'), usedforsecurity=False).hexdigest()[:16]


def _corpus_target_cells(target_cells: int | None) -> int:
    try:
        t = int(target_cells) if target_cells else CORPUS_CELLS_DEFAULT
    except (TypeError, ValueError):
        t = CORPUS_CELLS_DEFAULT
    return max(CORPUS_CELLS_MIN, min(CORPUS_CELLS_MAX, t))


def _corpus_label_maps(label: str) -> tuple[bool, str]:
    """Plan-time verification that *label* is understood by every classifier a
    cell spec flows through. Returns (ok, why). An unmapped label would
    silently route to the frontal PuLID/IPA fallback — the exact failure mode
    corpus mode must design away."""
    try:
        w, h = _cell_size_for_angle(label)
        if not (w > 0 and h > 0):
            return False, 'cell size unresolvable'
        _framing_clause(label)  # must not raise
        if _is_closeup_zoom_angle(label) or _is_relight_angle(label):
            # Derived cells crop/grade an existing render; the qwen instruction
            # is only their emergency fallback but must still exist.
            if _qwen_angle_instruction(label, {}) is None:
                return False, 'derived label has no qwen fallback instruction'
            return True, 'derived'
        if _qwen_angle_instruction(label, {}) is None:
            return False, 'no qwen_edit instruction (would hit PuLID/IPA fallback)'
        return True, 'generated'
    except Exception as exc:
        return False, f'classifier error: {exc}'


def build_corpus_plan_detail(
    target_cells: int | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Corpus grid plan: base 48 extended angles + expression axis (generated)
    + lighting/distance axes (derived crops of generated sources).

    Every emitted label is verified against the live classifiers at plan time;
    unmappable candidates are dropped and logged, never emitted. Generated
    cells get budget priority; derived cells fill the remainder capped at
    CORPUS_DERIVED_MAX_FRAC of the plan and each records its source label.
    Returns {'angle_set','target','hash','labels','cells','derived_count',...}.
    """
    total = _corpus_target_cells(target_cells)
    base = contact_sheet_angle_labels('extended')

    cells: list[dict] = []
    seen: set[str] = set()
    dropped: list[str] = []

    def _push(label: str, kind: str, axis: str, *, source: str | None = None, expression: str | None = None) -> bool:
        if label in seen:
            return False
        ok, why = _corpus_label_maps(label)
        if not ok:
            dropped.append(f'{label} ({why})')
            if log_fn:
                log_fn(f'Corpus plan: dropped unmappable label "{label[:60]}" — {why}')
            return False
        # A generated cell must never be classified derived (and vice versa) or
        # the generation loop would route it down the wrong path.
        is_derived = _is_closeup_zoom_angle(label) or _is_relight_angle(label)
        if (kind == 'derived') != is_derived:
            dropped.append(f'{label} (kind mismatch: planned {kind})')
            if log_fn:
                log_fn(f'Corpus plan: dropped "{label[:60]}" — planned {kind} but classifies otherwise')
            return False
        seen.add(label)
        entry: dict[str, Any] = {'label': label, 'kind': kind, 'axis': axis}
        if source:
            entry['source_label'] = source
        if expression:
            entry['expression'] = expression
        cells.append(entry)
        return True

    # 1) Base 48 — the anchor MUST stay index 0, and keeping base order makes
    #    the corpus a strict prefix-superset of an extended run (resume-safe).
    for i, lbl in enumerate(base):
        if i == 0:
            # The anchor is txt2img (never instruction-routed) — admit as-is.
            seen.add(lbl)
            cells.append({'label': lbl, 'kind': 'generated', 'axis': 'base'})
            continue
        kind = 'derived' if (_is_closeup_zoom_angle(lbl) or _is_relight_angle(lbl)) else 'generated'
        _push(lbl, kind, 'base', source=(base[0] if kind == 'derived' else None))

    # 2) Expression axis — face-visible frontal/three-quarter angles only.
    expr_angles = [a for a in base if _is_expression_base_angle(a)]
    expr_pool: list[tuple[str, str, str]] = []  # (label, base_label, expr_key)
    if expr_angles:
        n_pairs = len(EXPRESSIONS) * len(expr_angles)
        expr_keys = list(EXPRESSIONS)
        for k in range(n_pairs):
            # len(EXPRESSIONS)=12 and typical len(expr_angles)=13 are coprime,
            # so the (k mod E, k mod A) walk covers every pair exactly once
            # while keeping BOTH axes diverse in any truncated prefix.
            ek = expr_keys[k % len(expr_keys)]
            ba = expr_angles[k % len(expr_angles)]
            lbl = f'{ba}, {ek}'
            if (lbl, ba, ek) not in expr_pool:
                expr_pool.append((lbl, ba, ek))
        # coprimality fallback: fill any pairs the walk missed
        if len({p[0] for p in expr_pool}) < n_pairs:
            for ek in expr_keys:
                for ba in expr_angles:
                    tup = (f'{ba}, {ek}', ba, ek)
                    if tup not in expr_pool:
                        expr_pool.append(tup)

    # 3) Derived pools — lighting (relight crop+grade) and distance (close-up
    #    crop). Head-and-shoulders source views only: the crop output IS a
    #    head framing, so the label must describe one.
    frontal_view = 'camera straight on, front view head and shoulders'
    hs_views: list[tuple[str, str]] = [(frontal_view, base[0])]
    for a in expr_angles:
        al = a.lower()
        if 'head and shoulders' in al and 'medium' not in al and 'upper body' not in al:
            hs_views.append((a, a))
    relight_pool: list[tuple[str, str]] = []  # (label, source_label)
    for phrase in _CORPUS_LIGHTING_PHRASES:
        for view, src in hs_views:
            if view == frontal_view:
                continue  # frontal warm/cool/rim already exist in the base 48
            relight_pool.append((f'{view}, {phrase}', src))
    closeup_pool: list[tuple[str, str]] = []
    for phrase in _CORPUS_CLOSEUP_PHRASES:
        for view, src in hs_views:
            if view == frontal_view and 'fill frame' in phrase:
                continue  # base 48 already has the frontal fill-frame close-up
            closeup_pool.append((f'{view}, {phrase}', src))
    combo_pool: list[tuple[str, str]] = []
    for phrase in _CORPUS_LIGHTING_PHRASES:
        for view, src in hs_views[:3]:
            combo_pool.append((f'{view}, close-up face, {phrase}', src))
    derived_pool: list[tuple[str, str, str]] = []
    _rl = [(lbl, src, 'lighting') for lbl, src in relight_pool]
    _cu = [(lbl, src, 'distance') for lbl, src in closeup_pool]
    for i in range(max(len(_rl), len(_cu))):
        if i < len(_rl):
            derived_pool.append(_rl[i])
        if i < len(_cu):
            derived_pool.append(_cu[i])
    derived_pool.extend((lbl, src, 'distance') for lbl, src in combo_pool)

    # 4) Budget: generated (base + expression) has priority; derived fills the
    #    remainder, capped at CORPUS_DERIVED_MAX_FRAC of the plan.
    remaining = total - len(cells)
    derived_in_base = sum(1 for c in cells if c['kind'] == 'derived')
    derived_cap_total = int(CORPUS_DERIVED_MAX_FRAC * total)
    # Aim ~22% derived overall so the lighting/distance axes stay represented
    # at every corpus size without ever approaching the 35% hard cap.
    derived_target_total = min(derived_cap_total, max(derived_in_base, round(0.22 * total)))
    n_derived_extra = max(
        0,
        min(
            derived_target_total - derived_in_base,
            len(derived_pool),
            remaining,
        ),
    )
    n_expr = max(0, remaining - n_derived_extra)
    if n_expr > len(expr_pool):
        # Expression pool exhausted — top up with derived, still under the cap.
        overflow = n_expr - len(expr_pool)
        n_expr = len(expr_pool)
        n_derived_extra = min(
            n_derived_extra + overflow,
            len(derived_pool),
            max(0, derived_cap_total - derived_in_base),
        )
    for lbl, _ba, ek in expr_pool:
        if n_expr <= 0:
            break
        if _push(lbl, 'generated', 'expression', expression=ek):
            n_expr -= 1
    for lbl, src, axis in derived_pool:
        if n_derived_extra <= 0:
            break
        if _push(lbl, 'derived', axis, source=src):
            n_derived_extra -= 1
    # Verification drops can leave the plan short — backfill from whichever
    # pool still has verified labels (generated first).
    if len(cells) < total:
        for lbl, _ba, ek in expr_pool:
            if len(cells) >= total:
                break
            _push(lbl, 'generated', 'expression', expression=ek)
    if len(cells) < total:
        for lbl, src, axis in derived_pool:
            if len(cells) >= total:
                break
            if sum(1 for c in cells if c['kind'] == 'derived') >= derived_cap_total:
                break
            _push(lbl, 'derived', axis, source=src)

    labels = [c['label'] for c in cells]
    n_derived = sum(1 for c in cells if c['kind'] == 'derived')
    detail = {
        'angle_set': 'corpus',
        'target': total,
        'hash': _plan_hash(labels),
        'labels': labels,
        'cells': cells,
        'derived_count': n_derived,
        'derived_frac': round(n_derived / max(1, len(cells)), 4),
        'dropped': dropped,
        'built_at': _ams_iso(),
    }
    if log_fn:
        log_fn(
            f'Corpus plan: {len(cells)}/{total} cells '
            f'({len(cells) - n_derived} generated, {n_derived} derived '
            f'[{detail["derived_frac"] * 100:.0f}%], {len(dropped)} dropped) '
            f'hash {detail["hash"]}',
        )
    return detail


def build_corpus_plan(target_cells: int) -> list[str]:
    """Public corpus plan API — the ordered cell label list (see the detail
    builder for axes metadata and the plan hash)."""
    return list(build_corpus_plan_detail(target_cells)['labels'])
