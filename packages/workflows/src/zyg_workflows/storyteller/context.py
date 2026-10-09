# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one object every storyteller stage function shares.

`_run_storyteller_pipeline` in `zyg_workflows.pipeline_storyteller` is a single
3.8k-line function whose nine stages talk to each other through plain locals.
The split moves each `# ── Stage N …` block into a `stage_<nn>_<slug>(ctx)`
function in `zyg_workflows.storyteller.stage*`; every local that crosses a stage
boundary becomes a field of `StorytellerContext`, and nothing else about the
code changes. This mirrors `zyg_workflows.scholarly.context.RunContext` — read
`scholarly/README.md` and `scholarly/SPLIT_LOG.md` before moving another range.

A field here is one of three things:

* **run input** — bound by the driver's prologue before the first stage and
  never reassigned (`job`, `pipeline_id`, `out_dir`, `era_str`, the
  `_animated_render` / `_restyle_render` markers);
* **prologue closure** — one of the four nested helpers the prologue defines
  over the job and the state file (`_save`, `_log`, `_check_stop`,
  `_update_stage`). They stay nested functions in the driver, because they close
  over `pipeline_state` and `state_file`; the stages reach them through the
  context. Carrying callables on the context is what makes the move pure — a
  stage calls the very same object the monolith called;
* **stage product** — written by one stage and read by a later one. These
  default to `None`, which is also what the monolith's locals effectively were
  before their first assignment.

Every field defaults, so a later task can append the fields its stages need
without touching the construction site. The fields are grouped by the stage that
first writes them, in stage order.

`StageExit` and `UNSET` are imported from `scholarly.context` rather than
copied: a stage function cannot `return` for its caller, and that mechanism
should have exactly one implementation in the tree. No storyteller stage needs
either one yet — none of the nine ranges holds a top-level `return`, `break` or
`continue` — but the next task in the chain uses these and not its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zyg_workflows.scholarly.context import UNSET, StageExit

__all__ = ['UNSET', 'ImageGenState', 'StageExit', 'StorytellerContext']


@dataclass
class StorytellerContext:
    """Everything that crosses a stage boundary of the storyteller pipeline."""

    # ── Run inputs, bound by the driver's prologue ───────────────────────────
    pipeline_id: str = ''
    job: dict[str, Any] | None = None
    pipeline_state: dict[str, Any] | None = None
    out_dir: str = ''
    char_id: str = ''
    character_params: Any = None  # reconciled against the bible by stage 1
    voice_style: str = 'narration'
    narrator_voice: str = ''
    character_voice: str = ''
    duration_min: float = 10.0
    camera_mode: str = 'automatic'
    story_prompt: str = ''
    visual_style: str = 'cinematic'
    narration_enabled: bool = True
    model_family: str = 'flux'
    era_str: str = 'modern day'
    _slug_st: str = ''
    _pipeline_marker: Any = None
    _sp_st: Any = None  # the `subprocess` module, imported once by the prologue
    # SDXL render markers: an ANIMATED twin and an (Arcane) RESTYLE episode
    # relax different photoreal QC gates — see the prologue for which and why.
    _animated_render: bool = False
    _restyle_render: bool = False
    _restyle_caption_prefix: str = ''

    # ── Prologue closures the stages call ────────────────────────────────────
    _save: Any = None
    _log: Any = None
    _check_stop: Any = None
    _update_stage: Any = None

    # ── Stage 1: Character Prep ──────────────────────────────────────────────
    lora_path: Any = None
    trigger_token: str = ''
    _effective_tts_voice: Any = None

    # ── Stage 2: Story Script (scene count and word budget) ──────────────────
    n_scenes: Any = None  # re-derived by stage 2b after the scene list settles
    target_words: Any = None
    char_desc: Any = None
    style_str: Any = None
    angle_instruction: Any = None
    _WPM: Any = None
    _scene_word_budgets: Any = None

    # ── Stage 2a: Sonnet — story arc, narration, visual concept ──────────────
    scenes: Any = None
    story_title: Any = None
    _claude_client_st: Any = None
    _re_json_st: Any = None

    # ── Stage 3: TTS Narration ───────────────────────────────────────────────
    tts_path: Any = None
    tts_duration: Any = None
    tts_word_timings: Any = None
    full_narration: Any = None

    # ── Stage 3.5: FLUX Image Generation ─────────────────────────────────────
    # `stage_035_image_generation` publishes its one product here before the
    # Stage 4 call; everything else Stage 3.5 juggles lives on `ImageGenState`.
    img_paths: Any = None

    # ── Stage 4: Ken Burns + Assembly ────────────────────────────────────────
    _kb_clips_st: Any = None
    _img_durations: Any = None
    _n_imgs: Any = None
    _slot_emotions: Any = None
    _slot_shot_types: Any = None
    _SLIDE_W_ST: Any = None
    _SLIDE_H_ST: Any = None

    # ── Stage 5: Final Assembly ──────────────────────────────────────────────
    final_path: Any = None


@dataclass
class ImageGenState:
    """The former `nonlocal` state of the Stage 3.5 image loop.

    Stage 3.5 was the one range the first split task left in place. It is not a
    flat statement sequence that can be lifted as it stands: five nested `def`s
    inside it — `_st_load_flux_diffusers`, `_st_generate_one` and the three QA
    helpers — rebound seven of the block's locals through `nonlocal`
    (`_flux_i2i_pipe`, `_use_dev_st`, `_st_lora_loaded`, `_st_lora_active`,
    `_ipa_ready_st`, `_ipa_svc_st`, `_flux_model_path_st`), and a `nonlocal`
    cannot reach a field of a context object.

    Hoisting those helpers to module level therefore meant replacing the
    `nonlocal` rebinding with writes to fields on a small mutable object that is
    passed in — this one. Every field below is a local of the old
    `with _GPU_PIPELINE_LOCK:` block that at least two of the hoisted functions
    share; a name only ONE of them used stayed a plain local of that function,
    and a name that never changes after the prologue is read off
    `StorytellerContext` instead.

    Why a second dataclass rather than more `StorytellerContext` fields: none of
    these names crosses a *stage* boundary. They are the private, rapidly
    rebound state of one loop, and putting them on the context would hand every
    other stage a writable pipe handle and a LoRA-loaded flag that is only
    meaningful inside Stage 3.5. `scholarly` draws the same line between
    `RunContext` and `RunGlue`.

    The three list fields (`img_paths`, `_st_image_meta`,
    `_hand_qc_style_skip`) are only ever appended to, never rebound — exactly
    as in the monolith, where the nested helpers could mutate them without a
    `nonlocal` declaration.
    """

    # ── Stage 3.5 prologue, before the GPU lock ──────────────────────────────
    # `_ssh_st` is the `scene_still_helpers` module. It is carried rather than
    # imported at the top of each stage module so the import still happens
    # where the monolith ran it — inside the stage, after `_update_stage`.
    _ssh_st: Any = None
    img_paths: list = field(default_factory=list)
    # Stage 1's LoRA path, which Stage 3.5 may REPLACE (a mismatched family is
    # re-resolved) or CLEAR; `ctx.lora_path` must not see either, so the stage
    # works on its own copy — the monolith's plain local.
    lora_path: Any = None
    _st_lora_active: bool = False
    _st_comfy_available: bool = False
    _st_comfy_primary: bool = False
    _st_use_flux_diffusers: bool = True
    # `functools.partial(mediapipe_hand_qa, ctx, st)`, built once so that the
    # `hand_qa_fn=` argument is the same object on every call, as the closure was.
    _hand_qa_fn: Any = None

    # ── Inside `with _GPU_PIPELINE_LOCK:` — the seven old `nonlocal`s ────────
    _flux_i2i_pipe: Any = None
    _use_dev_st: bool = True
    _ipa_ready_st: bool = False
    _ipa_svc_st: Any = None
    _ipa_ref_path: Any = None
    _st_lora_loaded: bool = False
    _char_ref_img: Any = None

    # ── torch / diffusers handles and the FLUX model paths ───────────────────
    _torch_st: Any = None
    _FluxPipeline: Any = None
    _flux_dev_path_st: str = ''
    _flux_schnell_path: str = ''
    _flux_model_path_st: str = ''

    # ── Products of `select_backend` the loop and the QA helpers read ────────
    _style_prefix_st: str = ''
    _qc_style_st: str = ''
    _hand_qc_style_skip: list = field(default_factory=list)  # lazy one-shot [bool]

    # ── Pre-loop gates ──────────────────────────────────────────────────────
    _st_blender_ds: bool = False
    _st_drift_ref_ok: bool = False

    # ── The loop's product, which Stage 3.6 repairs in place ────────────────
    _st_image_meta: list = field(default_factory=list)
