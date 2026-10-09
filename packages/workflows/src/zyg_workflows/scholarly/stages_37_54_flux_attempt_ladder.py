# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which rung of the Stage 3.5 retry ladder one attempt climbs, and at what seed.

`run_attempt` in `stages_37_54_flux_attempt` opened with the two blocks that
decide what the attempt is going to render and nothing else: the early exit for
an environment shot that nothing flagged, and the eight-way `if`/`elif` ladder
that picks the prompt, the step count and the guidance scale for attempt 0, 1
or 2. Each rung is a function here, named for the defect it answers;
`choose_rung` is that chain of conditions, in its original order, and
`attempt_seed` / `attempt_path` are the two derivations that followed it.

A rung reads a dozen names the loop body had for free and writes four of them,
so the two carriers are its arguments:

* `env` — `AttemptEnv`, the `fs` and `ctx` names and the four sibling gates the
  body called as plain locals, read once per attempt;
* `slot` — `SlotState`, the frame the three attempts of one slot share. A rung
  writes `_steps_attempt`, `_scale_attempt`, `_clause_used` and
  `_era_rung_used` on it in place, which is what the loop body's locals did.
"""

import functools as _ft
import os
from dataclasses import dataclass
from typing import Any

from zyg_workflows.pipeline_scholarly import (
    _smoke_cap,
    _strip_written_subject,
)
from zyg_workflows.scholarly import stages_37_54_flux_qa as _flux_qa
from zyg_workflows.scholarly import stages_37_54_flux_render_gate as _flux_render_gate
from zyg_workflows.scholarly import stages_37_54_flux_vlm_gates as _flux_vlm_gates


@dataclass
class AttemptEnv:
    """The `fs`, `ctx` and gate names one attempt of the ladder reads.

    The monolith's loop body reached all of these as enclosing-scope locals.
    `build` is the glue block that opened `run_attempt`, statement for
    statement, so every call site below is the name the inline body used.
    """

    # ── From `ctx` (`RunContext`): the run inputs and prologue closures ──────
    _FLUX_NEGATIVE: Any
    _debug: Any
    _era_lock: Any
    _flux_lever_guard: Any
    _log: Any
    _sch_qwen_stills: Any
    _sch_use_comfy_images: Any
    job: Any
    out_dir: Any
    pipeline_id: Any
    pipeline_state: Any
    visual_style: Any
    # ── From `fs` (`FluxLoopState`): the per-run FLUX state ─────────────────
    _cn_pipe: Any
    _cns: Any
    _flux_images_dir: Any
    _flux_pipe: Any
    _ipa: Any
    _ipa_ready: Any
    _ladder_stats: Any
    _torch_flux: Any
    # ── The four sibling gates, bound as the body's own local names ─────────
    _era_ladder_qualifier: Any
    _mediapipe_qa_score: Any
    _record_slot_review: Any
    _vlm_render_gate: Any

    @classmethod
    def build(cls, fs, ctx):
        """Read every name one attempt needs out of *fs* and *ctx*.

        The four gates come back as `functools.partial(<fn>, fs, ctx)` so that
        `env._vlm_render_gate(path, prompt=…)` is the line the monolith ran.
        """
        return cls(
            _FLUX_NEGATIVE=ctx._FLUX_NEGATIVE,
            _debug=ctx._debug,
            _era_lock=ctx._era_lock,
            _flux_lever_guard=ctx._flux_lever_guard,
            _log=ctx._log,
            _sch_qwen_stills=ctx._sch_qwen_stills,
            _sch_use_comfy_images=ctx._sch_use_comfy_images,
            job=ctx.job,
            out_dir=ctx.out_dir,
            pipeline_id=ctx.pipeline_id,
            pipeline_state=ctx.pipeline_state,
            visual_style=ctx.visual_style,
            _cn_pipe=fs._cn_pipe,
            _cns=fs._cns,
            _flux_images_dir=fs._flux_images_dir,
            _flux_pipe=fs._flux_pipe,
            _ipa=fs._ipa,
            _ipa_ready=fs._ipa_ready,
            _ladder_stats=fs._ladder_stats,
            _torch_flux=fs._torch_flux,
            _era_ladder_qualifier=_ft.partial(_flux_render_gate.era_ladder_qualifier, fs, ctx),
            _mediapipe_qa_score=_ft.partial(_flux_qa.mediapipe_qa_score, fs, ctx),
            _record_slot_review=_ft.partial(_flux_vlm_gates.record_slot_review, fs, ctx),
            _vlm_render_gate=_ft.partial(_flux_render_gate.vlm_render_gate, fs, ctx),
        )


def ladder_exhausted(slot, attempt):
    """True when *attempt* must not render at all — the loop body's first `break`.

    Anatomy shots get retried; environment shots only retry when the VLM gate
    flagged the last attempt (or when always-reroll is on, for attempt 2 only).
    """
    if attempt > 0 and not slot._is_anatomy_shot and not slot._vlm_fail_prev:
        return not (slot._always_reroll and attempt == 1)
    return False


def choose_rung(env, slot, attempt):
    """Pick the prompt, step count and guidance scale for *attempt*.

    Returns `(prompt, anatomy_negative)`: the prompt this attempt renders, and
    whether the anatomy defect terms belong in the live negative instead of the
    positive (the Qwen anatomy rung). `slot._steps_attempt`,
    `slot._scale_attempt`, `slot._clause_used` and `slot._era_rung_used` are
    written in place.

    The three attempts:

    1. the prompt as written
    2. the SAME prompt at a new seed — a pure re-roll, which answers "was that
       defect this seed, or is it the prompt?" and costs one render to find out
    3. only now change the guidance: negatives switched on (schnell ignores
       them at guidance 0.0, so the scale is raised to make them bite) plus the
       defect-specific rewrite below

    Whatever wins on score ships, and if the winner is still flagged the slot
    is reported rather than quietly shipped.
    """
    if attempt == 0:
        return rung_as_written(slot), False
    if attempt == 1 and slot._vlm_text_fail_prev:
        return rung_text_clause(env, slot), False
    if slot._vlm_era_fail_prev and slot._era_rung_used == 0:
        return rung_era_qualifier(env, slot), False
    if attempt == 1:
        return rung_reroll(env, slot), False
    if slot._vlm_text_fail_prev:
        return rung_text_strip(env, slot), False
    if slot._vlm_era_fail_prev:
        return rung_era_escalation(env, slot), False
    return rung_anatomy_escalation(env, slot), True


def rung_as_written(slot):
    """Attempt 1 of 3: the prompt as composed, at the slot's own steps and scale."""
    slot._steps_attempt = slot._n_steps
    slot._scale_attempt = slot._g_scale
    return slot._prompt


def rung_text_clause(env, slot):
    """Typography, first rung: a new seed plus the lettering suppression clause.

    TEXT failures do not get a pure re-roll.

    The clause below is the one mechanism with production evidence behind it:
    on the run that cleared all ten slots, every slot cleared at attempt 2 with
    this appended and nothing else. The restructure that introduced the pure
    re-roll dropped it, which left the ladder going from no remedy straight to
    rewriting the scene — trading a measured 64% fix for an unmeasured one.

    A seed re-roll is also the weakest possible move here: run 7033208f showed
    that when the SCENE is a written thing every seed paints lettering. So
    attempt 2 keeps the new seed AND asks nicely; only attempt 3 rewrites the
    scene.
    """
    prompt = (
        slot._prompt + ', no readable lettering anywhere in frame, '
        'any document sign or map turned away from '
        'camera or thrown far out of focus so its '
        'writing reads as texture only'
    )
    slot._steps_attempt = slot._n_steps
    slot._scale_attempt = slot._g_scale
    env._ladder_stats['text_clause'] += 1
    slot._clause_used = True
    env._debug('Stage 3.5', f'Slot {slot.idx}: new seed + lettering suppression clause')
    return prompt


def rung_era_qualifier(env, slot):
    """Anachronism, first rung: the era gate's own fix phrase, seed kept.

    ANACHRONISM, first rung (2026-08-25): the era gate says WHICH object failed
    and carries the period 'fix' phrase for it. Append that qualifier and KEEP
    THE SEED — exactly how the typography ladder works: the composition was
    fine, one object was rendered with its modern default. A seed re-roll would
    throw the composition away to fix a hat.
    """
    _era_qual = env._era_ladder_qualifier(slot.idx)
    prompt = slot._prompt + (
        _era_qual or (f', strictly period-accurate {env._era_lock["period_label"]}, historical reconstruction')
    )
    slot._steps_attempt = slot._n_steps
    slot._scale_attempt = slot._g_scale
    slot._era_rung_used += 1
    env._ladder_stats['era_edit'] += 1
    env._debug(
        'Stage 3.5',
        f'Slot {slot.idx}: era edit, seed kept — {(_era_qual or "generic period restatement")[:120]}',
    )
    return prompt


def rung_reroll(env, slot):
    """Attempt 2 of 3: the identical prompt at a different seed.

    Pure re-roll: identical prompt, different seed (`attempt_seed` adds
    `attempt` to `_gen_seed`). Answers "was that defect this seed, or the
    prompt?" for anatomy, where the seed lottery genuinely does decide.
    """
    slot._steps_attempt = slot._n_steps
    slot._scale_attempt = slot._g_scale
    env._ladder_stats['reroll'] += 1
    env._debug('Stage 3.5', f'Slot {slot.idx}: re-roll at a new seed, prompt unchanged')
    return slot._prompt


def rung_text_strip(env, slot):
    """Typography, second rung: drop the written object and re-aim the camera.

    Re-rolling the seed alone cannot fix this. When the SCENE is a pamphlet or
    a map, every seed paints lettering, so the retry has to change what the
    camera is looking at.

    ESCALATED after measuring run 7033208f: appending a suppression clause
    cleared only 9 of 14 flagged slots (64%). The five that never cleared were
    the ones whose SCENE is a written thing — slot 1 read 'RUSSIA' off a map on
    both retries — because "a map, but with no lettering" is a contradiction
    FLUX resolves in favour of the map.

    So attempt 2 asks nicely; attempt 3 removes the written object from the
    sentence altogether and re-points the camera at the people.
    """
    prompt = (
        _strip_written_subject(slot._prompt) + ', no readable lettering anywhere in frame, '
        'any document sign or map turned away from '
        'camera, cropped by the frame edge or thrown '
        'far out of focus so its writing reads as '
        'texture only, no signage, no banners, '
        'no printed words'
    )
    # Steps only. Raising guidance here used to be
    # described as "switching the negatives on"; it is
    # not, and never was.
    #
    # MEASURED on this box (diffusers 0.37.1,
    # flux1-schnell, one seed, sha256 of the PNG):
    #   guidance 0.0, no negative   7ca25f6349e03e6b
    #   guidance 3.5, no negative   7ca25f6349e03e6b
    #   guidance 3.5 + negative     7ca25f6349e03e6b
    #   true_cfg 3.5 + negative     a4a979a3597a1ec7
    # Bit-identical for the first three. schnell's
    # transformer config carries guidance_embeds=False,
    # so diffusers sets `guidance = None` and discards
    # guidance_scale outright; and a negative prompt is
    # applied only when `true_cfg_scale > 1`, which
    # defaults to 1.0 and was never passed. Both levers
    # were inert on every run that claimed them.
    #
    # true_cfg DOES bite (fourth hash) — at 2x compute,
    # and it visibly wrecks a 4-step distilled model:
    # washed-out green cast, smeared faces. So it stays
    # off, and this rung leans on the lever that does
    # work — rewriting the prompt, positively phrased,
    # which is what this module's own negative-prompt
    # note has said all along.
    slot._steps_attempt = 4 if _smoke_cap() else 20
    env._ladder_stats['text_strip'] += 1
    # Say which rung it actually survived. A slot whose
    # first defect was anatomy takes the pure re-roll at
    # attempt 2 and only turns up as a text failure at
    # attempt 3 — so "survived the suppression clause"
    # was, on the measured run, describing a clause that
    # had never run for that slot.
    _prev_rung = 'the suppression clause' if slot._clause_used else 'the re-roll'
    env._log(
        'INFO',
        'Stage 3.5',
        f'Slot {slot.idx}: lettering survived {_prev_rung} — '
        f'dropping the written object and re-aiming '
        f'the camera ({slot._steps_attempt} steps)',
    )
    return prompt


def rung_era_escalation(env, slot):
    """Anachronism, second rung: keep the qualifier, restate the period, raise the steps.

    Anachronism, second rung — the object qualifier did not take. Keep it, add
    the generic period restatement, and raise the steps (the one FLUX lever
    that works; on Qwen the ladder tier).

    This used to raise guidance to 3.5 "so that `_FLUX_NEGATIVE` finally
    bites". Measured: it never bit, at any guidance (see the hashes on the
    typography rung above). On schnell the positive restatement is the whole of
    this rung; on Qwen the negatives are live and were on from attempt 1.
    """
    env._ladder_stats['era_escalation'] += 1
    slot._era_rung_used += 1
    prompt = (
        slot._prompt
        + (env._era_ladder_qualifier(slot.idx) or '')
        + f', strictly period-accurate {env._era_lock["period_label"]}, '
        'historical reconstruction, everything in frame '
        'handmade from wood stone cloth leather and iron, '
        'lit only by daylight fire candle or oil lamp'
    )
    # Third attempt on Qwen (P-11): a REAL guidance step —
    # cfg 3.5 / 28 steps. The ladder used to say it
    # climbed and never moved cfg off 2.5.
    if env._sch_qwen_stills:
        slot._steps_attempt = slot._n_steps if _smoke_cap() else 28
        slot._scale_attempt = 3.5
    else:
        slot._steps_attempt = 4 if _smoke_cap() else 20
    return prompt


def rung_anatomy_escalation(env, slot):
    """Anatomy, last rung: positive anatomy terms at the retry's step budget.

    Positively phrased only. The negated tail ("no deformities, no extra
    limbs") is the phrasing this module's own notes forbid; on Qwen those terms
    go into the live negative instead (`comfy_extra_negative`).
    """
    env._ladder_stats['anatomy_escalation'] += 1
    prompt = slot._prompt + ', perfectly formed hands, correct number of fingers, natural human anatomy'
    if env._sch_qwen_stills:
        slot._steps_attempt = slot._n_steps if _smoke_cap() else 28
        slot._scale_attempt = 3.5
    else:
        # Steps are the real lever; guidance is discarded on
        # schnell (guidance_embeds=False — measured above).
        slot._steps_attempt = 28 if not _smoke_cap() else 4  # max quality on retry (smoke: keep fast)
    return prompt


def attempt_seed(slot, attempt):
    """The seed *attempt* renders at, wrapped into the 31-bit range.

    Vary the seed slightly on each retry to explore a different sample — EXCEPT
    on an era prompt-edit rung, which keeps the seed so the composition
    survives and only the object changes.
    """
    _keep_seed = slot._vlm_era_fail_prev and attempt > 0 and not slot._vlm_text_fail_prev
    return (slot._gen_seed if _keep_seed else slot._gen_seed + attempt) % (2**31)


def attempt_path(images_dir, idx, attempt):
    """The JPEG this attempt writes: `flux_NNN.jpg`, `_r1`/`_r2` on a retry."""
    _attempt_suffix = '' if attempt == 0 else f'_r{attempt}'
    return os.path.join(
        images_dir,
        f'flux_{idx:03d}{_attempt_suffix}.jpg',
    )
