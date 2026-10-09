# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The run: ``build_sheet`` — anchors, per-cell edits, QC, regen, the sheet."""

from __future__ import annotations

from typing import Callable

from . import build_anchors as _anchors
from . import build_cells as _cells


def build_sheet(
    dataset_dir: str,
    brief: dict,
    *,
    source: str = 'reference',
    reference_paths: list[str] | None = None,
    preset: str = 'standard',
    log_fn: Callable[[str], None] | None = None,
    halt_check: Callable[[], None] | None = None,
    progress_fn: Callable[[str], None] | None = None,
) -> dict:
    """Build the sheet. Returns the report dict (also written to sheet.json)."""
    log = log_fn or (lambda _m: None)
    prog = progress_fn or (lambda _m: None)

    def _halt():
        if callable(halt_check):
            halt_check()

    run, refs_in = _anchors.new_run(
        dataset_dir,
        brief,
        source=source,
        reference_paths=reference_paths,
        preset=preset,
        log=log,
        prog=prog,
        halt=_halt,
    )

    # ── 1. references ────────────────────────────────────────────────────
    _anchors.collect_references(run, refs_in)

    # ── 2. anchors ───────────────────────────────────────────────────────
    _halt()
    prog('Anchor')
    _anchors.load_checklists(run)
    resumed_anchor = _anchors.resume_anchors(run)
    if resumed_anchor:
        pass
    elif run.locks.get('full_body') and run.source == 'scratch':
        pass  # the operator's lock IS the anchor (applied below) — no txt2img candidates
    elif run.source == 'reference':
        _anchors.anchors_from_reference(run)
    else:
        _anchors.anchors_from_scratch(run)
    if not resumed_anchor:
        _anchors.settle_anchors(run)
    log(_anchors.anchors_ready_line(run))

    # ── 3. cells ─────────────────────────────────────────────────────────
    prog('Multi-Angle Sheet')
    _cells.plan_cells(run)
    cells = _cells.render_all_cells(run)

    # ── 4. semantic judge (one GPU window for the batch) ─────────────────
    _halt()
    _cells.judge_cells(run, [c for c in cells if c.get('path')])

    # ── 5. regen ladder ──────────────────────────────────────────────────
    _cells.regen_ladder(run, cells)

    # ── 6. sheet + report ────────────────────────────────────────────────
    return _cells.finalise(run, cells)
