# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How one Stage 3.5 attempt is rendered and judged, once its rung is chosen.

`stages_37_54_flux_attempt_ladder` decides *what* the attempt renders; this
module is everything `run_attempt` did afterwards, in the same order:

1. **the ComfyUI branch** — `comfy_still`, with the character package, the
   style LoRA, the pose/anatomy workflow pick and the Qwen live negative as
   four helpers of their own;
2. **the in-process FLUX branch** — `no_pipe_outcome` for the case where no
   pipe was ever loaded, then `resolve_active_pipe` (ControlNet over base
   FLUX), `condition_ipadapter` and `render_still`, which keeps the monolith's
   `try/except/finally` around the CUDA call so the ControlNet and IPAdapter
   teardown still runs on the error path;
3. **the verdict** — `score_and_gate` is the sixteen lines both branches ran
   identically (MediaPipe score, VLM render gate, the three carried flags, the
   defect penalty), and `comfy_verdict` / `flux_verdict` are the two tails that
   differ, each returning the `Attempt` sentinel for the jump the loop body
   made.

Both carriers are the ladder module's: `env` (`AttemptEnv`) for the `fs`/`ctx`
names, and `slot` (`SlotState`) for the frame the three attempts share — a
helper that used to write a loop local writes the field in place.
"""

import logging as _zyg_logging
import os

from zyg_workflows.pipeline_config import (
    _STYLE_LORA_CONFIG,
)
from zyg_workflows.pipeline_scholarly import (
    _ERA_NEGATIVE,
    _smoke_cap,
)
from zyg_workflows.runtime import (
    workflow_jobs as _workflow_jobs,
)
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.scholarly.stages_37_54_flux_state import Attempt

# The monolith's logger name, not `__name__`, so every debug line of one run
# stays under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')


def comfy_character_package(pipeline_state):
    """The run's character bible, deep-copied and given the scholarly defaults.

    Returned unchanged when the run has none, because every call site below
    branches on its truthiness exactly as the inline body did.
    """
    _sch_pkg = pipeline_state.get('character_bible')
    if not _sch_pkg:
        return _sch_pkg
    import copy as _copy_sch

    from zyg_workflows import character_bible_service as _cbs_cg

    _sch_pkg = _copy_sch.deepcopy(_sch_pkg)
    _cbs_cg.apply_scholarly_conditioning_defaults(_sch_pkg)
    return _sch_pkg


def comfy_style_lora(visual_style):
    """The style LoRA config for *visual_style* and its safetensors file, if present.

    Returns `(config, path_or_None)`; an unknown style falls back to
    `cinematic`, and the path is None unless the directory really holds
    `pytorch_lora_weights.safetensors`.
    """
    _vs_comfy = _STYLE_LORA_CONFIG.get(
        visual_style,
        _STYLE_LORA_CONFIG['cinematic'],
    )
    _lora_dir_c = _vs_comfy.get('lora_dir')
    if _lora_dir_c:
        _cand = os.path.join(
            _lora_dir_c,
            'pytorch_lora_weights.safetensors',
        )
        if os.path.isfile(_cand):
            return _vs_comfy, _cand
    return _vs_comfy, None


def comfy_pose_workflow(env, slot, cgs, char_ref):
    """The cached pose PNG and the forced workflow for an anatomy shot on Comfy.

    Returns `(pose_path, force_workflow)`, both None off the anatomy path. The
    pose/IP anatomy graphs are FLUX graphs; the qwen family renders plain
    qwen_txt2img, so this does nothing when Qwen stills are on.
    """
    _comfy_pose_path = None
    _comfy_force_wf = None
    if slot._is_anatomy_shot and not env._sch_qwen_stills and char_ref and os.path.isfile(char_ref):
        try:
            from zyg_workflows import controlnet_service as _cns_cg

            _pose_pil_cg = _cns_cg.extract_pose_image(char_ref)
            if _pose_pil_cg is not None:
                _comfy_pose_path = os.path.join(
                    env.out_dir,
                    'scholarly_pose_cache.png',
                )
                _pose_pil_cg.save(_comfy_pose_path)
        except Exception as _pose_cg_e:
            env._debug('Stage 3.5', f'Comfy pose extract: {_pose_cg_e}', level='WARN')
        _comfy_force_wf, _comfy_wf_lbl = cgs.pick_scholarly_anatomy_workflow(
            char_ref,
            _comfy_pose_path,
        )
        env._debug('Stage 3.5', f'Comfy scholarly workflow: {_comfy_wf_lbl}')
    return _comfy_pose_path, _comfy_force_wf


def comfy_extra_negative(env, anat_neg_attempt):
    """The live negative prompt for the Comfy call — Qwen only, '' on FLUX.

    Qwen: negatives are LIVE (real CFG), so the anachronism and figure
    negatives finally do something. FLUX-on-Comfy keeps its old call, hence the
    empty string.
    """
    if not env._sch_qwen_stills:
        return ''
    _extra_neg_cg = env._FLUX_NEGATIVE
    if env._era_lock['is_historical']:
        _extra_neg_cg += ', ' + _ERA_NEGATIVE
    if anat_neg_attempt:
        # Anatomy rung (P-11): the defect terms
        # belong in the live negative, not as
        # negated phrases in the positive.
        _extra_neg_cg += ', deformed hands, wrong number of fingers, extra limbs, missing limbs, deformities'
    return _extra_neg_cg


def comfy_still(env, slot, attempt, prompt_attempt, anat_neg_attempt, attempt_p, seed):
    """Try to render this attempt on ComfyUI; True when it produced the still.

    Writes `slot._bk_cg` (the backend label the service reports) when the call
    returns at all, which is what the "no output" logs below read. Fail-open:
    any failure is logged and False sends the attempt down the diffusers path.
    """
    _used_comfy = False
    _sch_char_id = env.pipeline_state.get('char_id', '') or ''
    try:
        from zyg_workflows import comfy_generation_service as _cgs_sch

        if env._sch_use_comfy_images and _cgs_sch.is_available():
            _smoke_res_c = _smoke_cap() > 0
            _sch_pkg = comfy_character_package(env.pipeline_state)
            _prompt_comfy = _cgs_sch.build_locked_prompt(prompt_attempt, _sch_pkg) if _sch_pkg else prompt_attempt
            _vs_comfy, _style_lora_sf = comfy_style_lora(env.visual_style)
            _char_ref_cg = env.pipeline_state.get('char_reference_image')
            _comfy_pose_path, _comfy_force_wf = comfy_pose_workflow(env, slot, _cgs_sch, _char_ref_cg)
            _extra_neg_cg = comfy_extra_negative(env, anat_neg_attempt)
            _ok_cg, slot._bk_cg = _cgs_sch.generate_still(
                attempt_p,
                _prompt_comfy,
                # Smoke renders at 1280×720 (S-01): a 512×288
                # still cost ~3 s and bought nothing but a
                # 3.75× bicubic upsample in Stage 6 and a
                # postage-stamp thumbnail. Production on Qwen
                # uses its published 16:9 bucket 1664×928
                # (P-05); FLUX keeps its 1280×720 budget.
                width=(1280 if _smoke_res_c else (1664 if env._sch_qwen_stills else 1280)),
                height=(720 if _smoke_res_c else (928 if env._sch_qwen_stills else 720)),
                steps=slot._steps_attempt,
                cfg=slot._scale_attempt,
                seed=seed,
                character_package=_sch_pkg,
                # Package-less documentary stills must not carry
                # the character-bible "solo subject" ban (P-06):
                # on Qwen at real CFG it pulled against every
                # crowd / plague-street prompt.
                solo_subject=bool(_sch_pkg),
                char_id=_sch_char_id,
                reference_image=(
                    None
                    if env._sch_qwen_stills
                    else _char_ref_cg
                    if slot._is_anatomy_shot
                    else (_char_ref_cg if _sch_char_id else None)
                ),
                model_family=('qwen' if env._sch_qwen_stills else env.job.get('model_family', 'flux')),
                force_unet=(None if env._sch_qwen_stills else 'flux1-schnell.safetensors'),
                force_workflow=_comfy_force_wf,
                pose_image=_comfy_pose_path,
                style_lora_path=(None if env._sch_qwen_stills else _style_lora_sf),
                style_lora_scale=_vs_comfy.get('lora_dir_scale', 0.75),
                # Qwen stays resident between slots (a ~28 GB
                # reload per image is the whole 6.5x penalty
                # of the old curation path). The QC judges
                # fit beside it or fall through to the API.
                clear_vram_after=(not env._sch_qwen_stills)
                or (os.environ.get('ZYG_SCHOLARLY_QWEN_CLEAR_VRAM', '0').lower() in ('1', 'true', 'yes')),
                extra_negative=_extra_neg_cg,
                prompt_finalized=env._sch_qwen_stills and not _sch_pkg,
                log_fn=lambda m: env._log('INFO', 'Stage 3.5', m),
            )
            if _ok_cg:
                _used_comfy = True
                env._log('INFO', 'Stage 3.5', f'Slot {slot.idx}: ComfyGen ({slot._bk_cg}) seed={seed}')
    except Exception as _cgs_sch_e:
        env._log(
            'WARNING',
            'Stage 3.5',
            f'ComfyGen slot {slot.idx} failed — diffusers fallback: {_cgs_sch_e}',
        )
    return _used_comfy


def no_pipe_outcome(env, slot, attempt):
    """What the ladder does when ComfyGen produced nothing and no FLUX pipe is loaded.

    Qwen path: one more try at a new seed before giving the slot up — a ComfyUI
    timeout or a transient queue error is not a property of the prompt, and a
    missing slot shifts every later image off its narration window in Stage 6.
    """
    _bk_cg = slot._bk_cg if slot._bk_cg is not UNSET else 'no output'
    if env._sch_qwen_stills and attempt == 0:
        env._log(
            'WARNING',
            'Stage 3.5',
            f'Slot {slot.idx}: Qwen render failed ({_bk_cg}) — retrying once at a new seed',
        )
        slot._vlm_fail_prev = True  # let the loop reach attempt 2
        return Attempt.CONTINUE
    if attempt == 0:
        env._log(
            'WARNING',
            'Stage 3.5',
            f'Slot {slot.idx}: ComfyGen failed ({_bk_cg}) — in-process FLUX not loaded (ComfyUI primary)',
        )
    return Attempt.BREAK


def resolve_active_pipe(env, slot, attempt):
    """Pick the pipe this attempt renders on: ControlNet over base FLUX.

    Returns `(pose_image, controlnet_active)` and writes `slot._active_pipe`,
    which `generate_one` reads afterwards to choose the repair pipe. ControlNet
    is only used on anatomy shots (the reference pose may not exist yet on
    attempt 0, but the service returns None gracefully).
    """
    slot._active_pipe = env._flux_pipe
    _pose_img = None
    _cn_active = False
    if slot._is_anatomy_shot and env._cn_pipe is not None and env._cns is not None:
        _cn_subj_key = slot._subj.lower().strip()[:40]
        _cn_fallback_refs: list = []
        _char_ref_cn = env.pipeline_state.get('char_reference_image')
        if _char_ref_cn and os.path.isfile(_char_ref_cn):
            _cn_fallback_refs.append(_char_ref_cn)
        _pose_ref = slot._best_path or _char_ref_cn
        _pose_img = env._cns.get_pose_image(
            _cn_subj_key,
            _pose_ref,
            fallback_reference_paths=_cn_fallback_refs,
        )
        if _pose_img is not None:
            slot._active_pipe = env._cn_pipe
            _cn_active = True
            env._debug(
                'Stage 3.5',
                f'Slot {slot.idx} attempt {attempt + 1}: ControlNet pose conditioning active',
            )
    return _pose_img, _cn_active


def condition_ipadapter(env, slot):
    """Apply IPAdapter reference conditioning; True when the pipe took it.

    Only applies after the subject has been seen at least once (first slot →
    registers the result; subsequent → conditions on it). Writes
    `slot._ipa_subj_key`, which `build_gen_kwargs` reads back.
    """
    _ipa_active = False
    if slot._is_anatomy_shot and env._ipa_ready and env._ipa is not None:
        slot._ipa_subj_key = slot._subj.lower().strip()[:40]
        _ipa_active = env._ipa.condition_pipe(
            env._flux_pipe,
            slot._ipa_subj_key,
            scale=0.6,
            log_fn=lambda m: env._debug('Stage 3.5', m),
        )
    return _ipa_active


def clip_prompt(prompt_attempt):
    """The prompt as CLIP-L will see it, truncated on a word boundary.

    CLIP-L has a hard 77-token limit (~320 chars) — truncate to avoid silent
    loss of the cinematic suffix that describes lighting and style. T5-XXL
    (`prompt_2`) has a 512-token budget and sees the full prompt.
    """
    return prompt_attempt[:320].rsplit(' ', 1)[0] if len(prompt_attempt) > 320 else prompt_attempt


def negative_prompt(env, slot):
    """The negative prompt for this attempt: the bible's anatomy one, or the default."""
    _neg_prompt = env._FLUX_NEGATIVE
    if slot._is_anatomy_shot and slot._scale_attempt > 0.01:
        try:
            from zyg_workflows import character_bible_service as _cbs_neg

            _neg_prompt = _cbs_neg.scholarly_flux_negative_prompt(
                env.pipeline_state.get('character_bible'),
            )
        except (ImportError, AttributeError, KeyError, TypeError, ValueError) as _exc:
            _zyg_log.debug(
                'anatomy negative prompt unavailable for slot %s — the default negative prompt is kept: %s',
                slot.idx,
                _exc,
            )
    return _neg_prompt


def controlnet_scale(env, cn_active):
    """The ControlNet conditioning scale: the bible's, the service default, or 0.78."""
    _cn_scale = 0.78
    if cn_active:
        try:
            from zyg_workflows import character_bible_service as _cbs_cns

            _cn_scale = _cbs_cns.scholarly_controlnet_scale(
                env.pipeline_state.get('character_bible'),
            )
        except Exception:
            from zyg_workflows import controlnet_service as _cns_def

            _cn_scale = _cns_def.SCHOLARLY_CN_CONDITIONING_SCALE
    return _cn_scale


def build_gen_kwargs(env, slot, prompt_attempt, neg_prompt, seed, pose_img, cn_active, ipa_active, cn_scale):
    """Every keyword the diffusers call takes for this attempt."""
    _gen_kwargs = dict(
        prompt=clip_prompt(prompt_attempt),
        prompt_2=prompt_attempt,
        negative_prompt=neg_prompt,
        # S-01: smoke renders at 1280×720 on this path too —
        # a 512×288 source fed Stage 6 a 3.75× upsample.
        width=1280,
        height=720,
        num_inference_steps=slot._steps_attempt,
        guidance_scale=slot._scale_attempt,
        # Use CPU generator: diffusers randn_tensor anchors latent
        # device to the pipeline's execution device (CPU when T5 is
        # on CPU), so a cuda generator causes "cannot generate a cpu
        # tensor from a generator of type cuda". CPU generators are
        # also the diffusers convention and produce the same output.
        generator=env._torch_flux.Generator('cpu').manual_seed(seed),
    )
    if cn_active and pose_img is not None:
        _gen_kwargs['control_image'] = pose_img
        _gen_kwargs['controlnet_conditioning_scale'] = cn_scale
        _gen_kwargs['control_mode'] = 4  # Union mode 4 = pose
    if ipa_active and env._ipa is not None:
        _ipa_ref = env._ipa.get_reference_image(slot._ipa_subj_key)
        if _ipa_ref is not None:
            _gen_kwargs['ip_adapter_image'] = _ipa_ref
    return _gen_kwargs


def render_still(env, slot, attempt, prompt_attempt, attempt_p, seed, pose_img, cn_active, ipa_active):
    """Run the in-process FLUX/Qwen call and save the JPEG.

    Returns None when the still was written, or the `Attempt` sentinel the loop
    body returned on a render failure: ABORT on the first attempt (the slot is
    given up) and BREAK on a retry (whatever already scored still ships).
    """
    try:
        # `_smoke_res = _smoke_cap() > 0` here, dead since S-01 hardcoded
        # 1280×720 on this path. The call is kept because it is inside the
        # `except Exception` below and reads the cap through `pipeline_config`.
        _smoke_cap()
        _neg_prompt = negative_prompt(env, slot)
        _cn_scale = controlnet_scale(env, cn_active)
        _gen_kwargs = build_gen_kwargs(
            env,
            slot,
            prompt_attempt,
            _neg_prompt,
            seed,
            pose_img,
            cn_active,
            ipa_active,
            _cn_scale,
        )
        if cn_active and env._cns is not None:
            env._cns.controlnet_to_cuda(env._cn_pipe)
        env._flux_lever_guard(slot._active_pipe, _neg_prompt, slot._scale_attempt, _gen_kwargs)
        with env._torch_flux.autocast('cuda', dtype=env._torch_flux.bfloat16):
            _img = slot._active_pipe(**_gen_kwargs).images[0]
        _img.save(attempt_p, 'JPEG', quality=95)
    except Exception as _ge_a:
        import traceback as _tb_flux35

        env._log(
            'WARNING',
            'Stage 3.5',
            f'Image {slot.idx} attempt {attempt + 1} failed: {_ge_a}\n{_tb_flux35.format_exc()[:600]}',
        )
        if attempt == 0:
            return Attempt.ABORT  # first attempt failed — abort this slot
        return Attempt.BREAK
    finally:
        if cn_active and env._cns is not None:
            env._cns.controlnet_to_cpu(env._cn_pipe)
        # Always reset IPAdapter scale after each call
        if ipa_active and env._ipa is not None:
            env._ipa.reset_conditioning(env._flux_pipe)
    return None


def score_and_gate(env, slot, attempt, attempt_p, prompt_attempt):
    """Score the saved still and run the VLM render gate over it.

    Returns `(score, issues, gate_passed)` and writes the three carried
    `_vlm_*_fail_prev` flags that tell the next attempt which rung to climb. A
    gate defect caps the score at 0.45 so a flagged still can never outscore a
    clean one.
    """
    _qa_s, _qa_iss = env._mediapipe_qa_score(attempt_p)
    _vlm_ok, _vlm_why = env._vlm_render_gate(
        attempt_p, prompt=prompt_attempt, slot=slot.idx, anatomy_shot=slot._is_anatomy_shot
    )
    env._record_slot_review(slot.idx, attempt)
    slot._vlm_fail_prev = not _vlm_ok
    slot._vlm_era_fail_prev = _vlm_why.startswith('anachronism')
    slot._vlm_text_fail_prev = _vlm_why.startswith('typography')
    if not _vlm_ok:
        _qa_s = min(_qa_s, 0.45)
        _qa_iss = list(_qa_iss) + [f'vlm_defect: {_vlm_why}']
        env._log(
            'INFO',
            'Stage 3.5',
            f'Slot {slot.idx} attempt {attempt + 1}: VLM gate DEFECT — {_vlm_why}',
        )
    return _qa_s, _qa_iss, _vlm_ok


def record_attempt(slot, attempt, attempt_p, qa_s, qa_iss):
    """Append this attempt's QA row — score, path and issues — to the slot's log.

    Promotion to the slot's winner is `promote_best`, which both verdicts call
    separately, because the monolith logged the row before it compared scores.
    """
    slot._qa_attempts.append(
        {
            'attempt': attempt,
            'score': qa_s,
            'path': attempt_p,
            'issues': qa_iss,
        }
    )


def promote_best(slot, attempt_p, qa_s):
    """Make *attempt_p* the slot's winner when *qa_s* beats the best score so far."""
    if qa_s > slot._best_qa_score:
        slot._best_qa_score = qa_s
        slot._best_path = attempt_p


def accepted(slot, qa_s, vlm_ok):
    """True when this still is good enough to ship and stop retrying.

    An environment shot only has to clear the gate; an anatomy shot also has to
    score 0.72 or better.
    """
    return (qa_s >= 0.72 or not slot._is_anatomy_shot) and vlm_ok


def comfy_verdict(env, slot, attempt, attempt_p, qa_s, qa_iss, vlm_ok):
    """Record and judge a still ComfyGen produced; always a jump, never None."""
    record_attempt(slot, attempt, attempt_p, qa_s, qa_iss)
    promote_best(slot, attempt_p, qa_s)
    if accepted(slot, qa_s, vlm_ok):
        return Attempt.BREAK
    if attempt < 2:
        env._log(
            'INFO',
            'Stage 3.5',
            f'Slot {slot.idx}: QA {qa_s:.2f} < 0.72 — retrying (attempt {attempt + 2}/3)',
        )
    return Attempt.CONTINUE


def flux_verdict(env, slot, attempt, attempt_p, qa_s, qa_iss, vlm_ok):
    """Record and judge a still the in-process pipe produced.

    Returns BREAK when it ships, or None — the end of the loop body, which
    means take the next attempt.
    """
    record_attempt(slot, attempt, attempt_p, qa_s, qa_iss)
    if qa_iss:
        env._debug(
            'Stage 3.5',
            f'QA slot {slot.idx} attempt {attempt + 1}: score={qa_s:.2f} issues={qa_iss}',
            level='WARN',
        )
    else:
        env._debug('Stage 3.5', f'QA slot {slot.idx} attempt {attempt + 1}: score={qa_s:.2f} — OK')
    promote_best(slot, attempt_p, qa_s)
    if accepted(slot, qa_s, vlm_ok):
        env._ladder_stats[f'cleared_at_{attempt + 1}'] += 1
        return Attempt.BREAK  # acceptable quality — stop retrying
    if attempt < 2:
        env._log(
            'INFO',
            'Stage 3.5',
            f'Slot {slot.idx}: QA {qa_s:.2f} < 0.72 — retrying (attempt {attempt + 2}/3)',
        )
        bump_retry_counter(env)
    return None


def bump_retry_counter(env):
    """Track an anatomy retry in job state for the dashboard."""
    try:
        _jobs_ref = _workflow_jobs
        _cur_job = _jobs_ref.get(env.pipeline_id)
        if _cur_job is not None:
            _cur_job['retried_count'] = _cur_job.get('retried_count', 0) + 1
    except (AttributeError, KeyError, TypeError) as _exc:
        _zyg_log.debug(
            'retry counter of %s not bumped — the dashboard count only: %s',
            env.pipeline_id,
            _exc,
        )
