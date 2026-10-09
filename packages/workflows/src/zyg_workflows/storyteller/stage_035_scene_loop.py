# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.5, part 4 — one pass of the per-scene loop.

The body of ``for _si, scene in enumerate(scenes):`` — compose the prompt,
condition IPAdapter, render with up to three QC-driven retries, rescue or fail
the scene, lock scene 0 as the master, append to ``img_paths`` and to the
image-meta list Stage 3.6 repairs. The loop header itself stays in
``stage_035_image_gen``; only its body moved, as
:func:`generate_scene(ctx, st, _si, scene)`.

Why its own module rather than the two the brief named: the body is ~390 lines
and ``generate_one`` is ~290, so holding both would put
``stage_035_generate.py`` near 720 — inside the 800-line ceiling but well past
the 300-600 the split aims for. Split at the loop boundary instead, which is
also the natural seam: ``generate_one`` renders a frame, this renders a
*scene* (retries, QC verdicts, fallbacks and the state writes that record
them).

No ``break``/``continue``/``return`` crossed the new boundary — the only
``break`` belongs to the inner ``for _attempt in range(3)``, which moved whole
— so the function needs no `StageExit` sentinel. See ``SPLIT_LOG.md``.

2026-10-09: the 399-line body was itself over the 300-line function cap, so its
seven banner seams became the step functions of
:mod:`stage_035_scene_loop_steps`; what is left here is the order they run in."""

from __future__ import annotations

from zyg_workflows.storyteller.stage_035_scene_loop_steps import (
    compose_scene_prompt,
    condition_ipadapter,
    finalize_scene_file,
    lock_ipadapter_master,
    record_failed_scene,
    record_scene_meta,
    render_with_retries,
    rescue_scene,
    reset_ipadapter,
)


def generate_scene(ctx, st, _si: int, scene) -> None:
    """Render, QC, rescue and record scene ``_si``."""
    ctx._check_stop()
    sp = compose_scene_prompt(ctx, st, _si, scene)

    # ── IPAdapter: condition on master reference for scenes 1+ (FLUX only) ───
    _ipa_was_set = condition_ipadapter(ctx, st, _si)

    # ── Generate with auto-regenerate on quality failure ──────────
    outcome = render_with_retries(ctx, st, _si, sp)
    if not outcome.generated:
        rescue_scene(ctx, st, _si, sp, outcome)
    if not outcome.generated:
        record_failed_scene(ctx, _si)
    finalize_scene_file(ctx, st, _si, sp, outcome)

    # ── Reset IPAdapter after generation ────────────────────────
    reset_ipadapter(ctx, st, _ipa_was_set)

    # ── Scene 0: quality gate before locking as IPAdapter reference ──
    lock_ipadapter_master(ctx, st, _si, sp)

    record_scene_meta(ctx, st, _si, scene, sp)
