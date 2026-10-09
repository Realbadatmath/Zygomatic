# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Everything Stage 3.5 does before the first slot renders: load FLUX, wire the gates.

`stage_11c_flux_image_loop` in `stages_37_54` is one `if _flux_ready or
_sch_comfy_only:` statement that used to run 3,500 lines inline. What is left of
it there is the skeleton — the GPU-lock claim, the two `try:` statements, the
error path and the `ctx` tail. The three functions here are the block that ran
between the second `try:` and the first `generate_one` call, in source order:

* `setup_flux_prelude` — the GPU-exclusivity enforcement, the `torch` import and
  the stills-family label. It sits BETWEEN the stage's two `try:` statements in
  the monolith, so it is its own function: an exception out of it is *not*
  swallowed by `except Exception as _flux_err`, and folding it into
  `setup_flux_pipes` would have turned a failed `import torch` into "FLUX
  generation failed — using Wikimedia images only";
* `setup_flux_pipes` — the ControlNet pre-teardown, the Ollama eviction, the
  FLUX load (or cache hit), the style LoRA, the ControlNet load, the FluxWorker
  ownership transfer, the IPAdapter/ControlNet assignment and the loop-state
  inits. It ends by writing every loop-state field of `FluxLoopState` onto the
  `fs` the skeleton passed in — the in-place form of `FluxLoopState.capture`,
  which cannot be used directly because `fs` already exists (the skeleton's
  error path reads it);
* `setup_gates` — the two post-stage QA closures the stage publishes on `ctx`
  and the `init_gate_state` call behind them.

Three names crossed from the prelude to the rest as plain locals of one frame,
so the prelude returns all three and the skeleton holds them for the one
statement that needs each:

* `_torch_flux` and `_sch_family_label` are `FluxLoopState` fields — the
  skeleton passes them to the constructor, and `setup_flux_pipes` /
  `finish_flux_stage` read them off `fs`;
* `_FluxPipeline` — the conditional `from diffusers import FluxPipeline`. It is
  not a `FluxLoopState` field and must stay *conditionally* bound (the
  Comfy-only path never imports diffusers and never reaches the
  `from_pretrained` call), so it is a parameter of `setup_flux_pipes`. `UNSET`
  stands for "never imported": reaching `.from_pretrained` on it raises, as the
  `NameError` did inline.

`_gc_flux` was `import gc as _gc_flux` inline. `gc` is imported by the
interpreter before any of this runs and holds no per-import state, so it is a
module-level alias here and in `stages_37_54_flux_loop` instead of a statement
in the middle of the block.

See `SPLIT_LOG.md` for the full list of spots where this was not a pure move.
"""

import os

from zyg_workflows import gui_state
from zyg_workflows.scholarly import (
    stages_37_54_flux_setup_load as _load,
    stages_37_54_flux_state as _flux_state,
)
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.vram_manager import (
    _enforce_gpu_exclusivity_before_stage35,
)


def setup_flux_prelude(ctx):
    """Enforce GPU exclusivity, import torch, re-derive the stills-family label.

    Returns `(_torch_flux, _sch_family_label, _FluxPipeline)` — the three names
    these statements bound in the monolith's frame and the setup below needs.
    `_FluxPipeline` is `UNSET` on the Comfy-only path, which never imports
    diffusers and never reaches `from_pretrained`: reaching it anyway raises,
    as the `NameError` did inline.

    It takes no `fs` because it runs BEFORE the stage's second `try:`, i.e.
    before `FluxLoopState` is built — see the module docstring.
    """
    _FluxPipeline = UNSET
    _log = ctx._log
    _sch_comfy_only = ctx._sch_comfy_only
    _sch_qwen_stills = ctx._sch_qwen_stills
    pipeline_id = ctx.pipeline_id
    _enforce_gpu_exclusivity_before_stage35(
        log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        pipeline_id=pipeline_id,
    )
    import torch as _torch_flux

    # Re-derive the label AFTER the backend decision — Qwen may have
    # fallen back to FLUX, or ZYG_FORCE_FLUX_LOCAL may have won.
    _sch_family_label = 'Qwen-Image-2512' if _sch_qwen_stills else 'FLUX.1-schnell'
    if not _sch_comfy_only:
        from diffusers import FluxPipeline as _FluxPipeline

    # Module-level cache: avoid reloading model between pipeline runs
    pass  # (global stmt removed: names moved to gui_state)
    return _torch_flux, _sch_family_label, _FluxPipeline


def setup_flux_pipes(fs, ctx, _FluxPipeline):
    """Load (or re-use) FLUX + ControlNet, claim the worker, build the loop state.

    The orchestrator of the sequence: each load block is one function in
    `stages_37_54_flux_setup_load`, called where the block stood. What stays here
    is the control flow (the skip / cache-hit / fresh-load fork), the `gui_state`
    cache assignments the fork makes, the three plain locals the gates read and
    the `capture` tail — which must stay in this frame, because it reads this
    frame's `locals()`.

    Three locals it rebinds are mirrored onto `fs` (or onto `ctx`, for the one
    that is not a `FluxLoopState` field) by a chained assignment at the rebinding
    site, because the skeleton's `except`/`finally` read them and must see the
    value this function had reached when it raised:

    * `_flux_pipe`  -> `fs._flux_pipe` (the skeleton's `del _flux_pipe`);
    * `_sch_fw_active` -> `fs._sch_fw_active`;
    * `_sch_gpu_lock_held` -> `ctx._sch_gpu_lock_held` (the GPU-lock release in
      the `finally` — releasing a lock the FluxWorker now owns is the one
      staleness here that would be a real bug).
    """
    _log = ctx._log
    _sch_skip_local_flux = ctx._sch_skip_local_flux
    _torch_flux = fs._torch_flux
    # Loop-state fields the skeleton seeded from `ctx`, read back as the plain
    # locals the moved statements use and `capture` reads at the end.
    _flux_generated_paths = fs._flux_generated_paths
    _flux_image_meta = fs._flux_image_meta
    _flux_images_dir = fs._flux_images_dir
    _prev_focal_zone = fs._prev_focal_zone
    _sch_family_label = fs._sch_family_label
    _sch_fw_active = fs._sch_fw_active
    # Tear down any lingering ControlNet pipeline before fresh FLUX load.
    _load.teardown_stale_controlnet(ctx, _torch_flux)
    if _sch_skip_local_flux:
        gui_state._FLUX_PIPELINE_CACHE = None
        gui_state._CN_PIPE_CACHE = None
    elif gui_state._FLUX_PIPELINE_CACHE is None:
        # ── Unload Ollama models to free their VRAM (~5-7GB) ─────────────
        _load.evict_ollama_models(ctx)

        # TTS is local (IndexTTS-2/Chatterbox) — no external
        # TTS server to stop and no Stage-4 VRAM reservation needed.

        _load.load_flux_pipeline(ctx, _torch_flux, _FluxPipeline)

        # ── Load style LoRA (visual_style) or fall back to documentary LoRA ──
        _load.load_style_lora(ctx)
        # ── Stage 10: ControlNet — load AFTER FLUX is on VRAM ──────────────
        # FluxControlNetPipeline.from_pipe() wraps the CUDA-resident FLUX.
        # ControlNet (6.6 GB) stays in CPU RAM — swapped to CUDA per-shot
        # via controlnet_to_cuda/cpu() so it never competes with FLUX for VRAM.
        _load.load_controlnet(ctx)
        # ─────────────────────────────────────────────────────────
    else:
        if not _sch_skip_local_flux:
            _log('INFO', 'Stage 3.5', 'Using cached FLUX model')

    _flux_pipe = fs._flux_pipe = gui_state._FLUX_PIPELINE_CACHE

    _flux_pipe, _sch_fw_active = _load.claim_flux_worker(fs, ctx, _flux_pipe, _sch_fw_active)

    # Its reader is `generate_one`, as `fs._rnd_flux`:
    # `FluxLoopState.capture(locals())` below is what carries it there.
    import random as _rnd_flux  # noqa: F401

    # ── Stage 9: IPAdapter — disabled (no HuggingFace connectivity) ───
    _ipa = None
    _ipa_ready = False

    # ── Stage 10: ControlNet — assign from cache ──────────────────────
    # _CN_PIPE_CACHE is populated in the fresh-load block above (FLUX + ControlNet
    # both live in VRAM). On cache-hit runs it carries over from the previous load.
    # _cns module is imported for get_pose_image().
    _cns, _cn_pipe = _load.resolve_controlnet_pipe(ctx, _sch_fw_active)

    # _flux_image_meta initialized above before the flux_ready block
    _last_prompt = None  # dedup guard
    # ── Seed registry: lock per-subject seeds for character consistency ──
    # First time a subject is seen → assign a seed (from murch_engine or random).
    # Subsequent appearances of the same subject reuse that seed so FLUX
    # generates consistent anatomy/proportions/skin tone across all slots.
    # Environment/abstract tags (nature, charts, etc.) always get a fresh
    # random seed since they don't have persistent identity.
    _IDENTITY_TAGS = {
        'historical archive',
        'documentary scene',
        'protest crowd',
        'university campus',
    }
    _subject_seed_registry: dict = {}  # subject_key → seed int

    # ── Hand QC on the PRODUCTION path ──────────────────────
    # HandFixer/hand_qc_service were previously reachable only
    # under ZYG_SCHOLARLY_COMFY_IMAGES=1, i.e. the ComfyUI
    # character path — which is not what production renders.
    # Production is in-process FLUX.1-schnell, so every crowd,
    # barricade and quill-in-hand shipped with no hand review at
    # all beyond the geometric MediaPipe checks below.
    #
    # Verified on real frames from run 77bbbfd4 before wiring:
    # backend=mediapipe finds 3 hand boxes on the cartographer
    # frame and 2 on the map close-up, and the judge (qwen3.5:9b,
    # which does carry the 'vision' capability on this Ollama and
    # describes both frames correctly) returns real verdicts.
    _HAND_QC_ENABLED = os.environ.get('ZYG_SCHOLARLY_HAND_QC', '1').lower() not in ('0', 'false', 'no')
    _hand_qc_stats = {'checked': 0, 'flagged': 0, 'unavailable': 0}

    # `FluxLoopState.capture(locals())` inline; in-place because `fs` is the
    # object the skeleton already holds. The gate fields are `init_gate_state`'s
    # and must not be reset to their defaults here.
    _captured = _flux_state.FluxLoopState.capture(locals())
    for _name in _flux_state.FluxLoopState.__dataclass_fields__:
        if _name not in _flux_state._GATE_FIELDS:
            setattr(fs, _name, getattr(_captured, _name))


def setup_gates(fs, ctx):
    """Publish the two post-stage QA passes on `ctx`, then set every gate field."""
    # Still imported inside the function, as it was in `stage_11c_flux_image_loop`:
    # `stages_37_54_flux_qa` is only reachable from the two closures below, which
    # run long after this stage returns.
    from zyg_workflows.scholarly import stages_37_54_flux_qa as _flux_qa

    def _sch_typography_pass():
        return _flux_qa.typography_post_pass(fs, ctx)

    ctx._sch_typography_pass = _sch_typography_pass

    def _sch_hand_qc_pass():
        return _flux_qa.hand_qc_post_pass(fs, ctx)

    ctx._sch_hand_qc_pass = _sch_hand_qc_pass
    _flux_state.init_gate_state(fs, ctx)
