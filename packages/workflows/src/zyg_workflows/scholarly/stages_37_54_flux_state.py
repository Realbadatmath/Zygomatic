# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Everything the Stage 3.5 FLUX loop carries across its hoisted QA and gate functions.

`stage_11c_flux_image_loop` in `stages_37_54` used to define the fourteen QA and
gate helpers as nested `def`s, so they read the loop's forty-odd locals for
free. Hoisting them to module level takes that away, and `RunContext` is the
wrong home for it: these names live and die inside one `if _flux_ready` block,
and three of them are rebound by the loop itself. They become fields of this
object instead, which the stage builds once and passes to every hoisted
function as `fs`. A field is one of three things:

* **loop state** — bound by the stage before the first gate runs (the FLUX and
  ControlNet pipes, the seed registry, the output directory). `capture` reads
  these straight out of the stage's `locals()`, so the construction site stays
  one line and a field added here needs no edit there;
* **gate state** — the enable flags, judge model names and statistics
  containers that `init_gate_state` sets. That function holds the four
  statement blocks that used to sit between the closures, in their original
  order, so every `os.environ.get`, every log line and the one `extract_checks`
  API call happen exactly where they did;
* **ladder scratch** — the mutable dicts and lists the gates count into
  (`_vlm_gate_stats`, `_slot_review`, `_era_last_flags`, `_tx_api_dead`). The
  stage re-binds the same objects as plain locals, so a gate mutating one is
  visible to the loop with no write-back step.

The discipline: **`fs` is the source of truth.** The plain locals the stage
still reads are re-bound from `fs` immediately after `capture`, and the state
object is never read back into it. Three fields (`_cn_pipe`,
`_flux_generated_paths`, `_flux_image_meta`) are rebound by the loop *after*
`capture` and so go stale on `fs`; no function hoisted so far reads them, and
the task that hoists `_generate_one` converts those sites to `fs.<name>`.

Every field defaults, like `RunContext`, so a later task can append the fields
its functions need without touching the construction site.
"""

import enum
import logging as _zyg_logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from zyg_workflows.pipeline_scholarly import (
    _ERA_GATE_DEFAULT,
    _SCHOLARLY_SEC_PER_WORD,
)
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.runtime import (
    _record_token_usage,
)
from zyg_workflows.subscription_llm import (
    MODEL_SMALL as _LLM_SMALL,
    api_key_or_login as _llm_key,
)

# The monolith's logger name, not `__name__`, so every debug line of one run
# stays under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')

# Fields `init_gate_state` owns. `capture` leaves them at their defaults, and
# the one loop at the end of that function is what sets them — so a block moved
# in here that forgets a name raises KeyError on the spot instead of shipping a
# gate that silently never fires.
_GATE_FIELDS = (
    '_VLM_QC_ENABLED',
    '_VLM_QC_MODEL',
    '_vlm_gate_stats',
    '_anatomy_esc_budget',
    '_era_gate_stats',
    '_vlm_text_boxes',
    '_shipped_flagged',
    '_ladder_stats',
    '_slot_review',
    '_era_last_flags',
    '_VLM_TEXT_ENABLED',
    '_OCR_TEXT_ENABLED',
    '_TYPO_REPAIR_ENABLED',
    '_tx_api_dead',
    '_VLM_TEXT_MODEL',
    '_VLM_ERA_ENABLED',
    '_era_slot_checks',
    '_slot_clock_total',
    '_slot_clock_src',
    '_VLM_TEXT_PROMPT',
    '_last_gate_outcome',
)


@dataclass
class FluxLoopState:
    """The per-run state of the Stage 3.5 FLUX image loop."""

    # ── Loop state, captured from the stage's locals ─────────────────────────
    _torch_flux: Any = None
    _rnd_flux: Any = None
    _flux_pipe: Any = None
    _cn_pipe: Any = None
    _cns: Any = None
    _ipa: Any = None
    _ipa_ready: bool = False
    _flux_images_dir: Any = None
    _flux_generated_paths: Any = None
    _flux_image_meta: Any = None
    _sch_family_label: str = ''
    _sch_fw_active: bool = False
    _last_prompt: Any = None
    _prev_focal_zone: Any = None
    _IDENTITY_TAGS: Any = None
    _subject_seed_registry: Any = None
    _HAND_QC_ENABLED: bool = False
    _hand_qc_stats: Any = None

    # ── Gate state, set by `init_gate_state` ─────────────────────────────────
    _VLM_QC_ENABLED: bool = False
    _VLM_QC_MODEL: str = ''
    _vlm_gate_stats: Any = None
    _anatomy_esc_budget: int = 0
    _era_gate_stats: Any = None
    _vlm_text_boxes: Any = None
    _shipped_flagged: Any = None
    _ladder_stats: Any = None
    _slot_review: Any = None
    _era_last_flags: Any = None
    _VLM_TEXT_ENABLED: bool = False
    _OCR_TEXT_ENABLED: bool = False
    _TYPO_REPAIR_ENABLED: bool = False
    _tx_api_dead: Any = None
    _VLM_TEXT_MODEL: str = ''
    _VLM_ERA_ENABLED: bool = False
    _era_slot_checks: Any = None
    _slot_clock_total: float = 0.0
    _slot_clock_src: str = ''
    _VLM_TEXT_PROMPT: str = ''
    _last_gate_outcome: Any = None

    @classmethod
    def capture(cls, scope):
        """The loop-state fields, read out of the stage's `locals()`.

        A 39-keyword constructor call in `stage_11c_flux_image_loop` would be a
        new top-level block to keep in step with this class forever; reading the
        scope keeps the construction site one line. A loop-state field the stage
        has not bound yet is left at its default and named in the debug log,
        which is how a crossing the hoist dropped shows up without running a GPU
        job.
        """
        missing = [n for n in cls.__dataclass_fields__ if n not in scope and n not in _GATE_FIELDS]
        if missing:
            _zyg_log.debug('FluxLoopState.capture: left at default: %s', ', '.join(missing))
        return cls(**{n: v for n, v in scope.items() if n in cls.__dataclass_fields__})


def init_gate_state(fs, ctx):
    """Set every gate-state field of *fs*, running the stage's own four blocks.

    The statements below are the four blocks that sat between the
    closures of `stage_11c_flux_image_loop`, concatenated in source
    order. Nothing between them was anything but a `def`, so their
    side effects — the environment reads, the slot-clock `_debug`
    line and the one `era_gate.extract_checks` call with its two log
    lines — stay in the order and the position the monolith ran them
    in.
    """
    _debug = ctx._debug
    _era_lock = ctx._era_lock
    _log = ctx._log
    _n_flux_images = ctx._n_flux_images
    _prebuilt_prompts = ctx._prebuilt_prompts
    _word_count_est = ctx._word_count_est
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    # ── VLM render gate ─────────────────────────────────────────
    # Catches macro render defects mediapipe cannot see (grotesque
    # distorted faces, melted anatomy, fused objects) — the class
    # of defect that shipped in the toothbrush run because no QC
    # ever looked at the rendered frames. Fail-open by design:
    # every skip is logged, and the gate can never stall the run.
    _VLM_QC_ENABLED = os.environ.get('ZYG_SCHOLARLY_VLM_QC', '1').lower() not in ('0', 'false', 'no')
    # moondream (1.7 GB). PROMPTS MUST BE IMPERATIVE, NOT QUESTIONS.
    # Measured on ollama 0.17.7: any interrogative prompt ('Does this
    # image…?', 'Is there…?', even 'What color is the sky?') comes back
    # with eval_count=1 and an EMPTY response — the model emits a stop
    # token and nothing else. 'Describe this image.' works fine, so it
    # sees the pixels; it just cannot be asked. The gate previously
    # asked questions, so it returned '' for every render and — because
    # silence was read as a pass — shipped 135 images across 4 runs
    # while reporting 'checked: N, defect: 0, skipped: 0'.
    # 'Say yes if X, otherwise say no.' returns ' No' / ' Yes'.
    # (qwen2.5vl still fails to load on this build — HTTP 500.)
    _VLM_QC_MODEL = os.environ.get('ZYG_SCHOLARLY_VLM_QC_MODEL', 'moondream')
    _vlm_gate_stats = {
        'checked': 0,
        'defect': 0,
        'skipped': 0,
        'anachronism': 0,
        'unreadable': 0,
        'typography': 0,
        'text_checked': 0,
        'text_unreadable': 0,
        'text_skipped': 0,
        'text_judge': '',
        'text_second_vote': 0,
        'text_second_flag': 0,
        'anatomy_escalated': 0,
        'anatomy_reask': 0,
        'anatomy_reask_verdict': 0,
        'anatomy_escalation_calls': 0,
    }
    # Per-run escalation budget (P-08): every slot that can carry
    # a human escalates an empty moondream verdict — not just the
    # hook — with a re-ask first, then the second judge, until
    # this many second-judge calls have been spent.
    try:
        _anatomy_esc_budget = int(os.environ.get('ZYG_SCHOLARLY_ANATOMY_ESCALATIONS', '8') or 8)
    except (TypeError, ValueError):
        _anatomy_esc_budget = 8
    _era_gate_stats = {
        'checked': 0,
        'flagged': 0,
        'gore': 0,
        'subject_missing': 0,
        'unavailable': 0,
        'judge': '',
        'seconds': 0.0,
        'by_id': {},
    }
    # Bboxes from the local judge, keyed by image filename. Nothing
    # consumes these yet; they are the input a region-repair pass
    # would need to inpaint lettering out instead of re-rolling.
    _vlm_text_boxes: dict = {}
    # Slots whose winning attempt was STILL flagged. The episode
    # ships them (a flagged frame beats a missing one), but they
    # are named in the log and in the state file so the run can be
    # judged without replaying it.
    _shipped_flagged: list = []
    # How far the ladder actually climbed. Without this the only
    # way to answer "did the escalation ever fire?" was to read
    # every attempt line by hand — which is how a run reported
    # 100% convergence while its top two rungs had never once
    # executed. Counted here, the receipt says so outright.
    _ladder_stats = {
        'slots': 0,
        'attempts': 0,
        'reroll': 0,
        'text_clause': 0,
        'text_strip': 0,
        'era_edit': 0,
        'era_escalation': 0,
        'anatomy_escalation': 0,
        'cleared_at_1': 0,
        'cleared_at_2': 0,
        'cleared_at_3': 0,
        'repair_tried': 0,
        'repair_ok': 0,
        'era_repair_tried': 0,
        'era_repair_ok': 0,
    }
    # Per-slot review outcomes (see _generate_one) and the era
    # gate's per-slot flags, which the ladder reads for its fix.
    _slot_review: dict = {}
    _era_last_flags: dict = {}
    # ── Typography gate ─────────────────────────────────────
    # The prompt rule ("a document may appear, but never be the
    # SUBJECT") can only police words; this is the check that
    # looks at what was actually painted. It exists because the
    # Revolutions-of-1848 film shipped a newspaper reading
    # 'The Resulateires' and a shopfront reading 'PAILAT'.
    #
    # It does NOT run on moondream. Measured on ollama 0.17.7
    # against 8 hand-labelled frames: every text-related yes/no
    # phrasing either returns an empty response (eval_count=1 —
    # 'contains text', 'contains writing', 'contains readable
    # written words', and the question forms) or answers wrong.
    # The one phrasing that does answer — the anatomy prompt with
    # a text clause grafted on — said "No" on all four frames
    # whose text is the subject of the shot. moondream can be
    # asked about anatomy and about the sky; it cannot be asked
    # about lettering. qwen2.5vl on ollama still segfaults the
    # runner (exit 2).
    #
    # The judge that DOES do this well is the Qwen3-VL install at
    # <ZYG_MODELS_DIR>/vlm_judge (venv + worker + all four
    # checkpoints, present since 30 Jul — NOT crews/models/, which
    # is a different and empty path), driven through
    # vlm_inspector.py; see _vlm_text_gate_qwen. The Anthropic
    # vision path is the fallback for when that judge cannot run.
    # Neither available -> skipped and logged, never a silent pass.
    _VLM_TEXT_ENABLED = os.environ.get('ZYG_SCHOLARLY_VLM_TEXT', '1').lower() not in (
        '0',
        'false',
        'no',
    )
    # OCR is the PRIMARY typography judge — see typography_ocr.
    # It is the only one of the three that can actually answer
    # during Stage 3.5: it runs on the CPU, so FLUX holding the
    # card is irrelevant, and it costs nothing per call, so a
    # billing failure cannot blind the gate.
    _OCR_TEXT_ENABLED = os.environ.get('ZYG_SCHOLARLY_OCR_TEXT', '1').lower() not in (
        '0',
        'false',
        'no',
    )
    # Region repair: repaint flagged lettering instead of
    # re-rolling the slot. Verified clean AND plausible before it
    # is allowed to replace the frame; otherwise the original
    # stands and the slot is still reported flagged.
    _TYPO_REPAIR_ENABLED = os.environ.get('ZYG_SCHOLARLY_TYPO_REPAIR', '1').lower() not in (
        '0',
        'false',
        'no',
    )
    # Permanent API failures (billing, auth) are not per-frame
    # facts; once seen, stop paying the timeout on every frame.
    _tx_api_dead = ['']
    _VLM_TEXT_MODEL = os.environ.get('ZYG_SCHOLARLY_VLM_TEXT_MODEL', _LLM_SMALL)
    # Anachronism check runs only on historical episodes, and only
    # where it can be decided from pixels: vehicles, electric light
    # and modern dress are unambiguous, "wrong century of masonry"
    # is not.
    # DEFAULT OFF, on measurement. With the prompt fixed so the
    # model actually answers, this gate flagged 25 of 39 frames
    # from the Sikh Empire render (64%). Some are real — a bazaar
    # frame where a man holds a black slab that reads as a phone —
    # but slot 39, a clean silhouette of Khalsa banners at dusk
    # with no modern object in frame, was also flagged. At that
    # rate it would force a retry on most slots and could fail to
    # converge. Calibrate against labelled frames before enabling
    # with ZYG_SCHOLARLY_VLM_ERA=1.
    # 2026-08-25: the gate is now era_gate.py (per-slot, prompt-
    # derived, 3x2 tiles, Qwen3-VL / Anthropic vision) and is ON
    # by default for historical episodes; its default was set from
    # scripts/bench_era_gate.py on the 40 Black Death frames — see
    # the bench numbers in the session notes / memory before
    # changing either the questions or this default.
    _VLM_ERA_ENABLED = _era_lock['is_historical'] and os.environ.get(
        'ZYG_SCHOLARLY_VLM_ERA', _ERA_GATE_DEFAULT
    ).lower() not in ('0', 'false', 'no', '')
    # Per-slot checkable objects, one Haiku call per 20 prompts,
    # offline derivation as the fallback. Done ONCE here so the
    # in-loop gate never waits on the API.
    _era_slot_checks: list = []
    if _VLM_ERA_ENABLED:
        try:
            from zyg_workflows import era_gate as _eg_pre

            _s_prompts = []
            for _pi in range(_n_flux_images):
                _pb = _prebuilt_prompts[_pi] if _prebuilt_prompts and _pi < len(_prebuilt_prompts) else ''
                _s_prompts.append(_pb.get('standard', '') if isinstance(_pb, dict) else str(_pb or ''))
            _t_ec = time.time()
            _era_slot_checks = _eg_pre.extract_checks(
                _s_prompts,
                _era_lock,
                api_key=_llm_key(),
                log=lambda m: _debug('Stage 3.5', m),
                record_usage=lambda mdl, i, o: _record_token_usage(
                    model=mdl,
                    prompt_tokens=i,
                    completion_tokens=o,
                    pipeline_id=pipeline_id,
                    stage='Stage 3.5',
                    pipeline_type='scholarly',
                ),
            )
            _n_llm = sum(1 for c in _era_slot_checks if c.get('source') == 'llm')
            _log(
                'INFO',
                'Stage 3.5',
                f'Era gate: checks extracted for {len(_era_slot_checks)} slots '
                f'({_n_llm} from Haiku, {len(_era_slot_checks) - _n_llm} offline) '
                f'in {time.time() - _t_ec:.1f}s',
            )
        except Exception as _ec_e:
            _log(
                'WARNING',
                'Stage 3.5',
                f'Era gate: check extraction failed ({_ec_e!r}) — offline derivation per slot',
            )
            _era_slot_checks = []
    # ── Slot clock ──────────────────────────────────────────
    # Stage 3.5 runs AFTER Stage 4 TTS, so the real audio length
    # is already known — use it. The old estimate divided the word
    # count by a hardcoded 2.5 words/sec; the Sikh Empire run
    # narrated at 1.82 w/s, so its stored slot_seconds ran on a
    # 14.74s grid against a real 20.24s one, 37% fast by the end.
    # Harmless while WAN is off (nothing reads it), but
    # wan_video_service consumes slot_seconds, so re-enabling WAN
    # would have quietly reintroduced the desync Stage 6 fixed.
    _slot_clock_total = float(
        pipeline_state.get('tts_duration')
        or (pipeline_state.get('final_word_timings') or [['', 0.0]])[-1][1]
        or (_word_count_est * _SCHOLARLY_SEC_PER_WORD)
    )
    _slot_clock_src = (
        'tts_duration'
        if pipeline_state.get('tts_duration')
        else 'word_timings'
        if pipeline_state.get('final_word_timings')
        else 'wpm_estimate'
    )
    _debug(
        'Stage 3.5',
        f'Slot clock: {_slot_clock_total:.1f}s / {_n_flux_images} slots = '
        f'{_slot_clock_total / max(_n_flux_images, 1):.2f}s per slot '
        f'(source: {_slot_clock_src})',
    )
    # Prompt kept as a module-level-ish constant so it can be
    # reviewed and diffed without reading the call site.
    _VLM_TEXT_PROMPT = (
        'You are a render-QC judge for a historical documentary. '
        'Diffusion models cannot render real writing: they produce '
        'lettering that LOOKS readable but is gibberish. A viewer '
        'who notices it reads the shot as fake.\n\n'
        'Look at this frame and report lettering that a viewer '
        'would try to read — writing on signs, documents, '
        'newspapers, banners, posters, book spines, shopfronts, '
        'maps or engraved plaques. Ignore lettering too small, too '
        'blurred, too oblique or too dark to attract the eye.\n\n'
        'Reply with ONLY a JSON object:\n'
        '{"text_visible": true|false, "prominent": true|false, '
        '"largest_text": "<what it appears to say, or empty>", '
        '"where": "<short location, e.g. centre foreground>"}\n\n'
        '"prominent" is true only when the lettering is large or '
        'central enough that a viewer would attempt to read it — '
        'i.e. the written thing is a SUBJECT of the shot, not '
        'incidental background texture.'
    )
    # What the LAST _vlm_render_gate call actually established, per
    # judge. _generate_one copies it into _slot_review right after
    # the call, so the completion line can list unreviewed slots by
    # number instead of saying "every slot cleared its gates".
    _last_gate_outcome: dict = {}

    _scope = locals()
    for _name in _GATE_FIELDS:
        setattr(fs, _name, _scope[_name])


class Attempt(enum.Enum):
    """What one rung of the retry ladder asked the ladder to do next.

    `run_attempt` in `stages_37_54_flux_attempt` is the body of
    `for _attempt in range(3):`, so it still contains the five `break`s, the two
    `continue`s and the one `return None` that body had — and a function cannot
    break out of its caller's loop. Each is now `return Attempt.<member>`, and
    `generate_one` does the jump. Running off the end of the body returns `None`,
    which is what the end of a loop body meant: take the next attempt.
    """

    BREAK = 'break'
    CONTINUE = 'continue'
    ABORT = 'abort'


# The locals `for _attempt in range(3):` shared with its own next iteration, in
# the order `SlotState` declares them. `run_attempt` re-binds each as a plain
# local on entry and its `finally` writes back every one that is bound — so a
# name an attempt never bound stays `UNSET` and the next attempt's glue leaves
# its local unbound, exactly as the single frame did.
SLOT_FIELDS = (
    'idx',
    '_prompt',
    '_subj',
    '_n_steps',
    '_g_scale',
    '_gen_seed',
    '_is_anatomy_shot',
    '_qa_attempts',
    '_best_path',
    '_best_qa_score',
    '_clause_used',
    '_era_rung_used',
    '_vlm_fail_prev',
    '_vlm_era_fail_prev',
    '_vlm_text_fail_prev',
    '_always_reroll',
    '_active_pipe',
    '_bk_cg',
    '_ipa_subj_key',
    '_scale_attempt',
    '_steps_attempt',
)


@dataclass
class SlotState:
    """The frame one slot's three attempts shared when they were a loop body.

    Two groups, split by whether the inline loop could reach the name unbound:

    * the first sixteen are bound by `generate_one`'s prompt section before the
      ladder starts, so they are passed to the constructor and read back with a
      plain assignment. Seven of them (`_best_path`, `_best_qa_score`,
      `_clause_used`, `_era_rung_used` and the three `_vlm_*_fail_prev` flags)
      are what one attempt tells the next, and what the slot's summary reads
      afterwards. `_qa_attempts` is the list itself, appended to in place;
    * the last five are written by *some* attempts only — `_scale_attempt` on
      four of the eight ladder rungs, `_bk_cg` on the ComfyUI branch,
      `_active_pipe` and `_steps_attempt` never on the ComfyGen path. They
      default to `UNSET`, and both glue blocks re-bind them only when they were
      written, which is what keeps `try: _repair_pipe = _active_pipe / except
      NameError:` in `generate_one` deciding what it decided inline.
    """

    idx: int = -1
    _prompt: Any = UNSET
    _subj: Any = UNSET
    _n_steps: Any = UNSET
    _g_scale: Any = UNSET
    _gen_seed: Any = UNSET
    _is_anatomy_shot: Any = UNSET
    _qa_attempts: list = field(default_factory=list)
    _best_path: Any = None
    _best_qa_score: Any = -1.0
    _clause_used: bool = False
    _era_rung_used: int = 0
    _vlm_fail_prev: bool = False
    _vlm_era_fail_prev: bool = False
    _vlm_text_fail_prev: bool = False
    _always_reroll: bool = False
    # ── Bound by some attempts only — see the class docstring ────────────────
    _active_pipe: Any = UNSET
    _bk_cg: Any = UNSET
    _ipa_subj_key: Any = UNSET
    _scale_attempt: Any = UNSET
    _steps_attempt: Any = UNSET
