"""The one object every scholarly stage function shares.

`_run_scholarly_pipeline` in `zyg_workflows.pipeline_scholarly` used to be a
single 11k-line function whose stages talked to each other through ~300 plain
locals. The split moves each `# ── Stage N …` block into a
`stage_<nn>_<slug>(ctx)` function in `zyg_workflows.scholarly.stages_*`; every
local that crosses a stage boundary becomes a field of `RunContext`, and
nothing else about the code changes.

A field here is one of three things:

* **run input** — bound by the monolith's prologue before the first stage and
  never reassigned (`job`, `pipeline_id`, `out_dir`, the `_sch_*` option
  blocks);
* **prologue closure** — one of the nested helpers the prologue defines over
  that prologue (`_log`, `_save`, `_done`, `_stage_start`, `_debug`,
  `_assert_not_stopped`). They stay nested functions in the monolith, because
  they close over the job and the state file; the stages reach them through
  the context. Carrying callables on the context is what makes the move pure:
  the stages call the very same objects they called before;
* **stage product** — written by one stage and read by a later one. These
  default to `None`, which is also what the monolith's locals effectively were
  before their first assignment.

Every field defaults, so a later task in the split chain can append the fields
its stages need without touching the construction site. The fields are grouped
by the stage that first writes them, in stage order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class StageExit:
    """A `return` that used to leave `_run_scholarly_pipeline` from inside a stage.

    A stage function cannot return from its caller, so a moved `return value`
    becomes `return StageExit(value)` and the call site does::

        _exit = stage_nn_slug(ctx)
        if isinstance(_exit, StageExit):
            return _exit.value

    No stage extracted so far needs it (stages 1-9 contain no top-level
    `return`, `break` or `continue`), but the mechanism belongs with the
    context so the next task in the chain uses this one and not its own.
    """

    __slots__ = ('value',)

    def __init__(self, value=None):
        self.value = value

    def __repr__(self):
        return f'StageExit({self.value!r})'


class _Unset:
    """The default of a field whose local may legitimately be *unbound*.

    Almost every crossing can default to `None`, because that is what reading
    the monolith's local before its first assignment effectively meant. Two
    cannot: Stage 3.7 calls `_sch_typography_pass()` and `_sch_hand_qc_pass()`
    inside `except NameError:` to detect "the FLUX stage never ran and there is
    no closure to call". A `None` default turns that `NameError` into a
    `TypeError` and the gate receipt changes, so those fields default to
    `UNSET` and the stage binds its local only when the field was written::

        if ctx._sch_hand_qc_pass is not UNSET:
            _sch_hand_qc_pass = ctx._sch_hand_qc_pass
    """

    __slots__ = ()

    def __repr__(self):
        return 'UNSET'


UNSET = _Unset()


@dataclass
class RunContext:
    """Everything that crosses a stage boundary of the scholarly pipeline."""

    # ── Run inputs, bound by the monolith's prologue ─────────────────────────
    pipeline_id: str = ''
    topic: str = ''
    directive: str | None = None
    narration_enabled: bool = True
    visual_style: str = 'cinematic'
    job: dict[str, Any] | None = None
    pipeline_state: dict[str, Any] | None = None
    out_dir: str = ''
    _slug: str = ''
    _pipeline_marker: Any = None
    _sch_char_id: str = ''
    _sch_duration_targets: Any = None
    _sch_intensity: Any = None
    _stop_event_scholarly: Any = None
    _ilu_sch: Any = None  # importlib.util, imported once by the prologue
    # Pre-emptive bank (record/replay of the text LLM calls)
    _pbank: Any = None
    _preempt_mode: str = ''
    _preempt_entry: str = ''
    _preempt_dry: bool = False

    # ── Prologue closures the stages call ────────────────────────────────────
    _log: Any = None
    _save: Any = None
    _debug: Any = None
    _done: Any = None
    _stage_start: Any = None
    _assert_not_stopped: Any = None
    _should_stop: Any = None
    _gate_receipt: Any = None
    _flux_lever_guard: Any = None

    # ── Stage 2: Academic Research ───────────────────────────────────────────
    _research_result: Any = None
    _selected_essay_id: Any = None  # read back through `locals()` by Stage 3
    _preempt_state: Any = None
    essay_text: str | None = None

    # ── Stage 3: Script Preparation ──────────────────────────────────────────
    narration_script: str | None = None
    _anthropic_key: Any = None
    _stage3_llm_model: Any = None
    _wiki_source_block: Any = None
    _sch_subject_type: Any = None

    # ── Stage 3b: Visual Intent Tagging ──────────────────────────────────────
    visual_tags: Any = None
    _ollama_model_loaded: Any = None  # nested helper, published for Stage 3.1
    _tag_sentence: Any = None  # nested helper, published for Stage 3.1

    # ── Stage 3.1 pre-step: combined Haiku call ──────────────────────────────
    _haiku_turning_points: Any = None
    _haiku_emotion_scores: Any = None

    # ── Stage 4 (pre-image pass): TTS + word timings ─────────────────────────
    tts_duration: Any = None
    _final_word_timings: Any = None

    # ── Stage 3.5: FLUX Image Generation (marker 10) ─────────────────────────
    # The prompt vocabulary, the era lock and the slot arithmetic. Every one of
    # the seventeen is read by the Pre-generation block, which is still inline
    # in the monolith, so the call site unpacks them straight back into locals.
    _DEFAULT_FLUX_PROMPT: Any = None
    _FLUX_NEGATIVE: Any = None
    _FLUX_PROMPT_TEMPLATES: Any = None
    _STYLE_SUFFIXES: Any = None
    _build_image_prompt: Any = None
    _era_lock: Any = None
    _essay_title_for_prompt: Any = None
    _fallback_subject: Any = None
    _flux_images_dir: Any = None
    _flux_model_path: Any = None
    _is_modern_topic: Any = None
    _n_flux_images: Any = None
    _narration_sentences: Any = None
    _sch_family_early: Any = None
    _sch_family_label: Any = None
    _slot_word_bounds: Any = None
    _word_count_est: Any = None

    # ── Stage 3.5 Pre-generation (marker 11 — stages 11, 11b, 11c) ───────────
    # `_prebuilt_prompts` and `_sch_qwen_stills` are read by
    # `_build_image_prompt`, a nested `def` that lives in `stage_10` but is only
    # *called* from `stage_11c`, after both have their final value — hence the
    # mirror that still sits at each of their assignment sites.
    _prebuilt_prompts: Any = None
    _sch_qwen_stills: Any = None
    _flux_generated_paths: Any = None
    _flux_image_meta: Any = None
    _murch_image_debug: Any = None
    _murch_turning_points: Any = None
    _prev_focal_zone: Any = None  # closed over by a nested `def` of stage_11c
    _flux_ready: Any = None
    _sch_backend: Any = None  # the scholarly_stills_backend module itself
    _sch_skip_local_flux: Any = None
    _sch_comfy_only: Any = None
    _sch_use_comfy_images: Any = None
    _sch_gpu_lock_held: Any = None
    _sch_fw: Any = None
    _sch_fw_active: Any = None
    _fw_claimed_start: Any = None
    _sch_typography_pass: Any = UNSET  # may stay unbound — see _Unset
    _sch_hand_qc_pass: Any = UNSET  # may stay unbound — see _Unset

    # ── Stage 4b: Rhythm refresh (marker 13) ─────────────────────────────────
    _sch_voice: Any = None
    tts_path: Any = None

    # ── Stage 6: Video Assembly (marker 15) ──────────────────────────────────
    _img_paths: Any = None
    downloaded_clips: Any = None

    # ── Stage 6a: music bed (marker 16) ──────────────────────────────────────
    final_video_path: Any = None
    _book_intro_prepended: Any = None
