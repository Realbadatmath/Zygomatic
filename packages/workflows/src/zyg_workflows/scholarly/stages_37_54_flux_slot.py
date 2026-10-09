# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One Stage 3.5 slot, end to end: prompt, the retry ladder, repairs, receipt.

`_generate_one(idx)`, the 1,176-line closure of `stage_11c_flux_image_loop` in
`stages_37_54`, is `generate_one(fs, ctx, idx)` here. Its three parts are the
three parts of the original, in order and unchanged — and each is now a module
of its own, so this file is the call sequence and nothing else:

1. **the prompt for this slot** — `stages_37_54_flux_slot_prompt`:
   `_build_image_prompt`, the dedup against the previous slot, the style
   prefix/suffix, the Qwen "photograph" register, the period backstops, the era
   anchor, the per-subject seed lock, the stop check before the CUDA call, the
   anatomy-shot classification that picks steps and guidance, the bible
   identity suffix and the DSL hook;
2. **the retry ladder** — `for _attempt in range(3):`, whose six hundred lines
   of body are `run_attempt` in `stages_37_54_flux_attempt`. The body left the
   ladder with `break`, `continue` and one `return`; it now returns the
   `Attempt` sentinel for that jump and the loop below makes it;
3. **what ships** — `stages_37_54_flux_slot_ship`: the typography and era
   region repairs, the slot-review summary, the canonical `flux_NNN.jpg`
   rename, the IPAdapter and ControlNet registrations, the focal point for the
   next slot, the `_flux_image_meta` entry and the prompt receipt.

Parts 1 and 3 shared a frame of thirty-odd locals (`_tag`, `_shot_type`,
`_model_label`, `_cp_used`, …) that nothing else reads; those thirty-odd names
are the fields of `SlotPlan`, which part 1 builds and part 3 reads, while what
part 2 needs crosses on `SlotState` as before.

The closure rebound `_last_prompt` and `_prev_focal_zone` in its enclosing
scope, which a module-level function cannot do, and the two names are exactly
the state that must survive from one slot to the next. They are `FluxLoopState`
fields, so `compose_prompt` and `publish_slot` name `fs.<field>` directly.
"""

from zyg_workflows.scholarly import stages_37_54_flux_attempt as _flux_attempt
from zyg_workflows.scholarly import stages_37_54_flux_slot_prompt as _slot_prompt
from zyg_workflows.scholarly import stages_37_54_flux_slot_ship as _slot_ship
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.scholarly.stages_37_54_flux_state import Attempt


def generate_one(fs, ctx, idx):
    """Render slot *idx* and return the path that ships, or None."""
    plan = _slot_prompt.compose_prompt(fs, ctx, idx)
    plan.gen_seed = _slot_prompt.resolve_seed(fs, ctx, plan)
    # Final stop check immediately before the CUDA call (can't abort mid-inference)
    if _slot_prompt.abort_before_cuda(ctx, idx):
        return None
    _slot_prompt.choose_quality_tier(ctx, plan)
    _slot_prompt.apply_prompt_hooks(ctx, plan)

    # ── The retry ladder ────────────────────────────────────────────────────
    # Generation with QA + retry (up to 3 attempts for anatomy shots). Each
    # attempt may use a slightly different seed and targeted prompt; the
    # best-scoring result is what ships. The body of this loop is
    # `run_attempt`; the sentinel it returns is the jump the body made when it
    # was inline here.
    slot = _slot_prompt.new_slot_state(fs, plan)
    for _attempt in range(3):
        _outcome = _flux_attempt.run_attempt(fs, ctx, slot, _attempt)
        if _outcome is Attempt.ABORT:
            return None
        if _outcome is Attempt.BREAK:
            break
        if _outcome is Attempt.CONTINUE:
            continue
    # What the ladder leaves behind for the rest of the slot. `_active_pipe`
    # and `_steps_attempt` are re-bound only when an attempt bound them, so
    # the `except NameError` below behaves as it did inline.
    _qa_attempts = slot._qa_attempts
    _best_path = slot._best_path
    _best_qa_score = slot._best_qa_score
    if slot._active_pipe is not UNSET:
        _active_pipe = slot._active_pipe
    if slot._steps_attempt is not UNSET:
        _steps_attempt = slot._steps_attempt

    if _best_path is None:
        return None

    # _active_pipe is bound inside the attempt loop, and the
    # ComfyGen path never binds it at all. Resolve it once,
    # explicitly: with no pipe the repair still runs, it just
    # has only the classical strategy to work with.
    try:
        _repair_pipe = _active_pipe
    except NameError:
        _repair_pipe = None
    _slot_ship.repair_typography(fs, ctx, plan, _best_path, _qa_attempts, _repair_pipe)
    _slot_ship.repair_era_regions(fs, ctx, plan, _best_path, _qa_attempts)
    _slot_ship.summarize_slot_review(fs, ctx, plan, _best_path, _best_qa_score, _qa_attempts)
    _out_p = _slot_ship.canonicalize_winner(fs, ctx, plan, _best_path, _qa_attempts)
    _n_attempts = len(_qa_attempts)
    return _slot_ship.publish_slot(
        fs,
        ctx,
        plan,
        _out_p,
        _best_qa_score,
        _qa_attempts,
        _steps_attempt if _n_attempts > 1 else plan.n_steps,
    )
