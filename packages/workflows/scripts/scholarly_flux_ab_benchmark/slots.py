# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One benchmark slot on each backend: diffusers stack, Comfy call, teardown, summary."""

from __future__ import annotations

from .bench_assets import (
    Any,
    Path,
    _CFG,
    _FLUX_PATH,
    _H,
    _PARITY,
    _PARITY_SUBJ_KEY,
    _STEPS,
    _W,
    _gpu_exclusivity_sweep,
    _load_bench_bible,
    _log,
    _qa_score,
    os,
    time,
)
from . import bench_assets as _bench_assets

# Bound by ASSIGNMENT, not `from ... import`: an import-originated global compiles
# `_zyg_log.debug(...)` to a different (non method-form) call sequence.
_zyg_log = _bench_assets._zyg_log


def _build_diffusers_prompt(scene: str, pkg: dict | None, anat_suffix: str) -> str:
    from zyg_workflows import character_bible_service as cbs

    prompt = scene
    if pkg:
        ident = cbs.identity_prompt_prefix(pkg)
        if ident:
            prompt = f'{ident}, {prompt}'
    if anat_suffix.lower() not in prompt.lower():
        prompt = f'{prompt}, {anat_suffix}'
    return prompt


def _load_diffusers_stack(pose_ref: str | None, char_id: str = ''):
    import types
    import torch
    from diffusers import FluxPipeline

    _gpu_exclusivity_sweep()
    _log('Loading FLUX diffusers pipeline…')
    t0 = time.time()
    pipe = FluxPipeline.from_pretrained(
        _FLUX_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.transformer.to('cuda')
    pipe.text_encoder.to('cuda')
    pipe.vae.to('cuda')

    def _t5_cpu_fwd(self, prompt=None, num_images_per_prompt=1, max_sequence_length=512, device=None, dtype=None):
        device = device or self._execution_device
        prompt = [prompt] if isinstance(prompt, str) else prompt
        batch_size = len(prompt)
        text_inputs = self.tokenizer_2(
            prompt,
            padding='max_length',
            max_length=max_sequence_length,
            truncation=True,
            return_length=False,
            return_overflowing_tokens=False,
            return_tensors='pt',
        )
        t5_dev = next(self.text_encoder_2.parameters()).device
        emb = self.text_encoder_2(
            text_inputs.input_ids.to(t5_dev),
            output_hidden_states=False,
        )[0].to(dtype=self.text_encoder_2.dtype, device=device)
        _, seq_len, _ = emb.shape
        emb = emb.repeat(1, num_images_per_prompt, 1)
        return emb.view(batch_size * num_images_per_prompt, seq_len, -1)

    try:
        pipe.vae.enable_tiling()
    except Exception:
        pipe.enable_vae_tiling()

    cn_pipe = None
    cns = None
    cns_mod = None
    try:
        from zyg_workflows import controlnet_service as cns_mod

        cn_pipe = cns_mod.setup(pipe, log_fn=_log)
        cns = cns_mod if cn_pipe else None
    except Exception as exc:
        _log(f'ControlNet setup: {exc}')

    if cn_pipe and cns_mod is not None:
        cns_mod.prepare_flux_for_controlnet(pipe, cn_pipe, log_fn=_log)
    else:
        pipe._get_t5_prompt_embeds = types.MethodType(_t5_cpu_fwd, pipe)

    from zyg_workflows import character_bible_service as cbs

    pkg, _ = _load_bench_bible(char_id) if _PARITY else (None, '')
    neg = cbs.scholarly_flux_negative_prompt(pkg)
    cn_scale = cbs.scholarly_controlnet_scale(pkg)
    anat_suffix = cbs.scholarly_anatomy_prompt_suffix(pkg)

    _log(f'Diffusers ready in {time.time() - t0:.1f}s (CN={"yes" if cn_pipe else "no"}, parity={_PARITY})')
    return pipe, cn_pipe, cns, neg, cn_scale, anat_suffix, pose_ref, pkg


def _load_pose_pil(pose_skeleton: str | None, pose_ref: str | None, subj_key: str, cns) -> Any:
    if pose_skeleton and os.path.isfile(pose_skeleton):
        from PIL import Image

        return Image.open(pose_skeleton).convert('RGB')
    if cns and pose_ref:
        return cns.get_pose_image(subj_key, None, fallback_reference_paths=[pose_ref])
    return None


def _run_diffusers_slot(
    pipe,
    cn_pipe,
    cns,
    neg,
    cn_scale,
    anat_suffix,
    pose_ref,
    pkg,
    slot_id: str,
    scene: str,
    seed: int,
    out_path: str,
    pose_skeleton: str | None = None,
) -> dict[str, Any]:
    import torch

    prompt = _build_diffusers_prompt(scene, pkg, anat_suffix)
    clip = prompt[:320].rsplit(' ', 1)[0] if len(prompt) > 320 else prompt
    active = pipe
    cn_active = False
    pose_img = None
    subj_key = _PARITY_SUBJ_KEY if _PARITY else slot_id
    if cn_pipe and cns and (pose_skeleton or pose_ref):
        pose_img = _load_pose_pil(pose_skeleton, pose_ref, subj_key, cns)
        if pose_img is not None:
            active = cn_pipe
            cn_active = True
            cns.controlnet_to_cuda(cn_pipe)

    t0 = time.time()
    try:
        kwargs = dict(
            prompt=clip,
            prompt_2=prompt,
            negative_prompt=neg,
            width=_W,
            height=_H,
            num_inference_steps=_STEPS,
            guidance_scale=_CFG,
            generator=torch.Generator('cuda').manual_seed(seed),
        )
        if cn_active and pose_img is not None:
            kwargs['control_image'] = pose_img
            kwargs['controlnet_conditioning_scale'] = cn_scale
            kwargs['control_mode'] = 4
        with torch.autocast('cuda', dtype=torch.bfloat16):
            img = active(**kwargs).images[0]
        img.save(out_path, 'JPEG', quality=95)
        ok = True
        err = ''
    except Exception as exc:
        ok = False
        err = str(exc)[:400]
    finally:
        if cn_active and cns:
            cns.controlnet_to_cpu(cn_pipe)

    elapsed = time.time() - t0
    qa, issues = _qa_score(out_path) if ok and os.path.isfile(out_path) else (0.0, ['no_output'])
    return {
        'ok': ok,
        'elapsed_s': round(elapsed, 2),
        'qa_score': round(qa, 3),
        'qa_pass_first': qa >= 0.65,
        'qa_issues': issues,
        'cn_active': cn_active,
        'bible': bool(pkg),
        'error': err,
    }


def _run_comfy_slot(
    scene: str,
    seed: int,
    out_path: str,
    pose_ref: str | None,
    pose_skeleton: str | None,
    pkg: dict | None,
    char_id: str,
    run_dir: Path,
) -> dict[str, Any]:
    from zyg_workflows import character_bible_service as cbs
    from zyg_workflows import comfy_generation_service as cgs

    if not cgs.is_available():
        return {'ok': False, 'elapsed_s': 0, 'error': 'comfy_unavailable', 'qa_score': 0}

    if _PARITY and pkg:
        prompt = cgs.build_locked_prompt(
            f'{scene}, {cbs.scholarly_anatomy_prompt_suffix(pkg)}',
            pkg,
        )
        neg_extra = cbs.scholarly_flux_negative_prompt(pkg)
    else:
        prompt = f'{scene}, {cbs.scholarly_anatomy_prompt_suffix()}'
        neg_extra = cbs.scholarly_flux_negative_prompt()

    force_wf = None
    wf_lbl = 'txt2img'
    if _PARITY:
        force_wf, wf_lbl = cgs.pick_scholarly_anatomy_workflow(pose_ref, pose_skeleton)
    elif pose_skeleton and cgs.pose_locked_stack_ready():
        force_wf, wf_lbl = 'flux_pose_ipa_cell', 'pose_ipa_cn'

    t0 = time.time()
    ok, backend = cgs.generate_still(
        out_path,
        prompt,
        width=_W,
        height=_H,
        steps=_STEPS,
        cfg=_CFG,
        seed=seed,
        character_package=pkg,
        char_id=char_id,
        reference_image=pose_ref,
        model_family='flux',
        force_unet='flux1-schnell.safetensors',
        force_workflow=force_wf,
        pose_image=pose_skeleton,
        extra_negative=neg_extra,
        prompt_finalized=bool(_PARITY and pkg),
        clear_vram_after=True,
        skip_qa=not bool(char_id),
        log_fn=_log,
    )
    elapsed = time.time() - t0
    qa, issues = _qa_score(out_path) if ok else (0.0, ['no_output'])
    return {
        'ok': ok,
        'elapsed_s': round(elapsed, 2),
        'qa_score': round(qa, 3),
        'qa_pass_first': qa >= 0.65,
        'qa_issues': issues,
        'backend': backend,
        'workflow': force_wf or wf_lbl,
        'bible': bool(pkg),
        'pose_cn': bool(pose_skeleton),
        'error': '' if ok else backend,
    }


def _teardown_diffusers(pipe, cn_pipe, cns) -> None:
    from zyg_workflows import scholarly_stills_backend as ssb

    ssb.aggressive_release_flux_pipeline_vram(
        pipe,
        cn_pipe=cn_pipe,
        cn_service=cns,
        log_fn=_log,
    )


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [r for r in rows if r.get('ok')]
    times = [r['elapsed_s'] for r in ok_rows]
    cn_on = sum(1 for r in ok_rows if r.get('cn_active') or r.get('pose_cn'))
    return {
        'rows': rows,
        'mean_s': round(sum(times) / len(times), 2) if times else None,
        'total_s': round(sum(times), 2) if times else None,
        'qa_first_pass_rate': round(
            sum(1 for r in rows if r.get('qa_pass_first')) / max(len(rows), 1),
            3,
        ),
        'cn_active_rate': round(cn_on / max(len(ok_rows), 1), 3) if ok_rows else 0.0,
        'failures': [r['slot'] for r in rows if not r.get('ok')],
    }


def _vram_free_gb() -> float:
    """Return GPU 0 free VRAM in GB, or -1.0 if unavailable."""
    try:
        import torch

        if torch.cuda.is_available():
            return round(torch.cuda.mem_get_info(0)[0] / 1024**3, 2)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return -1.0
