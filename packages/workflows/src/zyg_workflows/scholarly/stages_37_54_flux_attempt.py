# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One attempt of the Stage 3.5 FLUX retry ladder, hoisted out of the loop.

`_generate_one` in `stages_37_54` renders a slot up to three times:
`for _attempt in range(3):` and six hundred lines of body — the ladder rung
choice, the ComfyUI branch, the in-process FLUX/Qwen call with its ControlNet
and IPAdapter conditioning, and the QA/VLM verdict that decides whether to
retry. That body is `run_attempt` here: the call sequence and nothing else,
because the four blocks it is made of now live in two sibling modules —
`stages_37_54_flux_attempt_ladder` (what this attempt renders) and
`stages_37_54_flux_attempt_render` (how it is rendered and judged).

Two things a loop body can do that a function cannot, and what replaces them:

* **`break` / `continue` / `return`** — the body leaves the ladder in eight
  places. Each is now `return Attempt.<BREAK|CONTINUE|ABORT>`, and
  `generate_one` does the jump the sentinel names. Falling off the end returns
  `None`, which means the same thing the end of a loop body meant: next
  attempt.
* **locals that survive the iteration** — a loop body shares one frame with
  its neighbours, so `_scale_attempt` (set on four of the eight rungs and read
  on all of them), `_ipa_subj_key` and the `locals().get("_bk_cg")` log all
  read what an *earlier* attempt bound. Those names are the fields of
  `SlotState` (`slot`), the one object the three attempts of a slot share, and
  every helper below writes the field in place. That is what the loop's shared
  frame was; the glue block and the `finally` that copied the fields into
  locals and back out again were only needed while the body still spoke in
  locals. A field no attempt has written is still `UNSET`, which is what keeps
  `try: _repair_pipe = _active_pipe / except NameError:` in `generate_one`
  deciding what it decided inline.

The two other carriers are the ones the rest of the package uses: `fs`
(`FluxLoopState`, the per-run FLUX state) and `ctx` (`RunContext`, the run
inputs and prologue closures). `AttemptEnv.build` reads them — and binds the
four sibling gates as `functools.partial(<fn>, fs, ctx)` — once per attempt, so
every call site in the two step modules is the line the monolith ran.
"""

from zyg_workflows.scholarly import stages_37_54_flux_attempt_ladder as _ladder
from zyg_workflows.scholarly import stages_37_54_flux_attempt_render as _render
from zyg_workflows.scholarly.stages_37_54_flux_state import Attempt


def run_attempt(fs, ctx, slot, _attempt):
    """Render and judge attempt *_attempt* of slot `slot.idx`.

    Returns the `Attempt` sentinel for the jump the inline loop body made, or
    `None` where it ran off the end.
    """
    env = _ladder.AttemptEnv.build(fs, ctx)
    if _ladder.ladder_exhausted(slot, _attempt):
        return Attempt.BREAK

    # ── Which rung, at which seed, written where ────────────────────────────
    _prompt_attempt, _anat_neg_attempt = _ladder.choose_rung(env, slot, _attempt)
    _seed_attempt = _ladder.attempt_seed(slot, _attempt)
    env._ladder_stats['attempts'] += 1
    if _attempt == 0:
        env._ladder_stats['slots'] += 1
    _attempt_p = _ladder.attempt_path(env._flux_images_dir, slot.idx, _attempt)

    # ── ComfyUI first; it judges its own still and never falls through ──────
    if _render.comfy_still(env, slot, _attempt, _prompt_attempt, _anat_neg_attempt, _attempt_p, _seed_attempt):
        _qa_s, _qa_iss, _vlm_ok = _render.score_and_gate(env, slot, _attempt, _attempt_p, _prompt_attempt)
        return _render.comfy_verdict(env, slot, _attempt, _attempt_p, _qa_s, _qa_iss, _vlm_ok)
    if env._flux_pipe is None:
        return _render.no_pipe_outcome(env, slot, _attempt)

    # ── The in-process FLUX/Qwen call ───────────────────────────────────────
    _pose_img, _cn_active = _render.resolve_active_pipe(env, slot, _attempt)
    _ipa_active = _render.condition_ipadapter(env, slot)
    _render_jump = _render.render_still(
        env,
        slot,
        _attempt,
        _prompt_attempt,
        _attempt_p,
        _seed_attempt,
        _pose_img,
        _cn_active,
        _ipa_active,
    )
    if _render_jump is not None:
        return _render_jump

    # ── MediaPipe QA and the VLM gate on the saved image ────────────────────
    _qa_s, _qa_iss, _vlm_ok = _render.score_and_gate(env, slot, _attempt, _attempt_p, _prompt_attempt)
    return _render.flux_verdict(env, slot, _attempt, _attempt_p, _qa_s, _qa_iss, _vlm_ok)
