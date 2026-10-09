# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SimpleTuner config writers per model family."""

import os
import json
import logging
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service.model_paths import (  # noqa: F401
    _DEPRECATED_ST_CONFIG_KEYS,
    _GROUP_OFFLOAD_KEYS,
    _TRAIN_MODEL_PATH,
    _resolve_klein_train_path,
    _resolve_qwen_train_path,
    _resolve_sdxl_train_path,
)
from zyg_workflows.lora_trainer_service.job_state import (  # noqa: F401
    TrainingJob,
    _family_lora_weights_dir,
    _normalize_train_family,
)
from zyg_workflows.lora_trainer_service.st_config import (  # noqa: F401
    _validation_interval,
    _validation_prompt,
)
from zyg_workflows.lora_trainer_service.helpers import (  # noqa: F401
    _find_latest_checkpoint,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')


def _write_st_config_flux(job: TrainingJob, config_dir: str):
    """Write the SimpleTuner config.json for a FLUX character LoRA."""
    steps = max(1, job.total_steps)
    warmup_steps = min(50, max(10, steps // 10))
    val_interval = _validation_interval(steps)
    ckpt_interval = min(250, max(50, steps // 4))
    weights_dir = _family_lora_weights_dir(job.output_dir, 'flux')
    os.makedirs(weights_dir, exist_ok=True)

    # Rank 64/alpha 32 (2026-07-18, was 128/64): 128 produced 418 MB LoRAs and
    # whole-image memorisation risk on ~48-image datasets; character identity
    # does not need it. 64 halves size/load time at equal identity strength;
    # A/B lower via ZYG_LORA_RANK=32 ZYG_LORA_ALPHA=16.
    _rank = int(os.environ.get('ZYG_LORA_RANK', '64'))
    _alpha = int(os.environ.get('ZYG_LORA_ALPHA', str(max(1, _rank // 2))))

    config = {
        '--data_backend_config': os.path.join(config_dir, 'multidatabackend.json'),
        '--aspect_bucket_rounding': 2,
        '--seed': 42,
        '--minimum_image_size': 256,
        '--output_dir': weights_dir,
        '--model_type': 'lora',
        '--lora_type': 'standard',
        '--lora_rank': _rank,
        '--lora_alpha': _alpha,
        '--pretrained_model_name_or_path': _TRAIN_MODEL_PATH,
        '--model_family': 'flux',
        '--base_model_precision': 'int8-quanto',
        '--text_encoder_1_precision': 'no_change',
        '--text_encoder_2_precision': 'no_change',
        # Attention + compile accelerators. diffusers (the default) uses xformers
        # if available, else torch's SDPA. FA2 requires flash-attn in SimpleTuner's
        # venv (needs nvcc, not on this box yet). torch.compile gives ~15-30% on
        # training steps once compiled.
        '--attention_mechanism': os.environ.get('ZYG_ST_ATTENTION', 'diffusers'),
        '--validation_torch_compile': os.environ.get('ZYG_ST_COMPILE', 'false'),
        '--max_train_steps': job.total_steps,
        '--num_train_epochs': 0,
        '--train_batch_size': 1,
        '--gradient_checkpointing': 'true',
        '--gradient_accumulation_steps': 1,  # reduced from 2 to save VRAM
        '--mixed_precision': 'bf16',
        '--optimizer': 'adamw_bf16',
        '--learning_rate': '1e-4',
        '--lr_scheduler': 'cosine',
        '--lr_warmup_steps': warmup_steps,
        # 0.10 (2026-07-18, was 0.05): with trigger-first captions a little more
        # dropout improves robustness to prompts that omit the trigger phrasing.
        '--caption_dropout_probability': float(
            os.environ.get('ZYG_LORA_CAPTION_DROPOUT', '0.10'),
        ),
        # 1024 pixel-area (was 768): the trainer downsampled every 1024×1152
        # tile to ~0.59MP before VAE caching, so the LoRA never saw the pore
        # detail the pipeline pays to generate (2026-07-09 audit).
        '--resolution_type': 'pixel_area',
        '--resolution': int(os.environ.get('ZYG_LORA_TRAIN_RES', '1024')),
        '--checkpoint_step_interval': ckpt_interval,
        '--checkpoints_total_limit': 3,
        '--validation_seed': 42,
        '--validation_step_interval': val_interval,
        '--validation_resolution': '1024x1024',
        # Guidance 2.8: validation must render in the same photoreal regime the
        # pipeline uses; 3.5+ is FLUX's plastic-skin zone. And no 'character
        # reference sheet' phrasing — it is a 3D-render/illustration attractor
        # that made validation images look like cartoons regardless of the LoRA.
        '--validation_guidance': 2.8,
        '--validation_guidance_rescale': '0.0',
        '--validation_num_inference_steps': '20',
        # Subject-aware: see _validation_prompt(). A caller that knows the
        # subject is not a person (creature, animal) overrides it outright.
        '--validation_prompt': _validation_prompt(job, 'flux'),
        '--report_to': 'tensorboard',
        '--tracker_project_name': f'storyteller-char-{job.char_id[:8]}',
        '--tracker_run_name': f'char-lora-rank{_rank}-v{job.lora_version}',
    }
    if _find_latest_checkpoint(job.output_dir, 'flux'):
        config['--resume_from_checkpoint'] = 'latest'
    # SimpleTuner FLUX VRAM offload — opt-in via ZYG_ST_GROUP_OFFLOAD=true.
    # Group offload is incompatible with --gradient_checkpointing (causes
    # cuda/cpu device mismatch in backward pass — see SimpleTuner trainer.py).
    # FLUX dev at int8-quanto + LoRA rank 128 fits in ~30 GB, so we keep
    # everything on-GPU by default on 48 GB+ cards.
    if os.environ.get('ZYG_ST_GROUP_OFFLOAD', 'false').lower() in ('1', 'true', 'yes'):
        # If user forces offload, disable gradient checkpointing per upstream guidance
        config['--gradient_checkpointing'] = 'false'
        config.update(
            {
                '--enable_group_offload': 'true',
                '--group_offload_type': 'block_level',
                '--group_offload_blocks_per_group': 1,
                # Streams are auto-disabled by SimpleTuner when gradient checkpointing
                # is on; we keep them on here only because we explicitly disabled it.
                '--group_offload_use_stream': 'true',
            }
        )
    for _bad in _DEPRECATED_ST_CONFIG_KEYS:
        config.pop(_bad, None)
    # Only keep group-offload flags if explicitly opted in just above
    if '--enable_group_offload' not in config:
        for _k in _GROUP_OFFLOAD_KEYS:
            config.pop(_k, None)
    with open(os.path.join(config_dir, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)


def _write_st_config_sdxl(
    job: TrainingJob,
    config_dir: str,
    train_path: str | None = None,
):
    """Write the SimpleTuner config.json for an SDXL character LoRA."""
    steps = max(1, job.total_steps)
    warmup_steps = min(50, max(10, steps // 10))
    val_interval = _validation_interval(steps)
    ckpt_interval = min(250, max(50, steps // 4))

    weights_dir = _family_lora_weights_dir(job.output_dir, 'sdxl')
    os.makedirs(weights_dir, exist_ok=True)

    config = {
        '--data_backend_config': os.path.join(config_dir, 'multidatabackend.json'),
        '--aspect_bucket_rounding': 2,
        '--seed': 42,
        '--minimum_image_size': 256,
        '--output_dir': weights_dir,
        '--model_type': 'lora',
        '--lora_type': 'standard',
        '--lora_rank': 64,
        '--lora_alpha': 32,
        '--pretrained_model_name_or_path': train_path or _resolve_sdxl_train_path(),
        '--model_family': 'sdxl',
        '--max_train_steps': job.total_steps,
        '--num_train_epochs': 0,
        '--train_batch_size': 1,
        '--gradient_checkpointing': 'true',
        '--gradient_accumulation_steps': 1,
        '--mixed_precision': 'bf16',
        '--optimizer': 'adamw_bf16',
        '--learning_rate': '1e-4',
        '--lr_scheduler': 'cosine',
        '--lr_warmup_steps': warmup_steps,
        # 0.10 (2026-07-18, was 0.05): with trigger-first captions a little more
        # dropout improves robustness to prompts that omit the trigger phrasing.
        '--caption_dropout_probability': float(
            os.environ.get('ZYG_LORA_CAPTION_DROPOUT', '0.10'),
        ),
        '--resolution_type': 'pixel_area',
        '--resolution': 1024,
        '--checkpoint_step_interval': ckpt_interval,
        '--checkpoints_total_limit': 3,
        '--validation_seed': 42,
        '--validation_step_interval': val_interval,
        '--validation_resolution': '1024x1024',
        '--validation_guidance': 6.0,
        '--validation_guidance_rescale': '0.0',
        '--validation_num_inference_steps': '28',
        '--validation_prompt': _validation_prompt(job, 'sdxl'),
        '--report_to': 'tensorboard',
        '--tracker_project_name': f'storyteller-char-sdxl-{job.char_id[:8]}',
        '--tracker_run_name': 'char-sdxl-lora-rank64',
    }
    if _find_latest_checkpoint(job.output_dir, 'sdxl'):
        config['--resume_from_checkpoint'] = 'latest'
    with open(os.path.join(config_dir, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)


def _write_st_config_qwen(
    job: TrainingJob,
    config_dir: str,
    train_path: str | None = None,
):
    """Write the SimpleTuner config.json for a Qwen-Image-2512 character LoRA.

    Mirrors the FLUX writer's schedule (rank/steps/lr/optimizer) with the
    Qwen-specific keys from SimpleTuner's QWEN_IMAGE quickstart: bf16 is
    mandatory, gradient checkpointing is required, base model + the single
    Qwen2.5-VL text encoder run int8-quanto (quantized on CPU to avoid OOM),
    flow_schedule_shift 1.73, validation guidance in the 3.0-4.0 band at ~30
    steps. Qwen has ONE text encoder — no text_encoder_2/t5/FLUX guidance keys.
    """
    steps = max(1, job.total_steps)
    warmup_steps = min(50, max(10, steps // 10))
    val_interval = _validation_interval(steps)
    ckpt_interval = min(250, max(50, steps // 4))
    weights_dir = _family_lora_weights_dir(job.output_dir, 'qwen')
    os.makedirs(weights_dir, exist_ok=True)

    _rank = int(os.environ.get('ZYG_LORA_RANK', '64'))
    _alpha = int(os.environ.get('ZYG_LORA_ALPHA', str(max(1, _rank // 2))))

    config = {
        '--data_backend_config': os.path.join(config_dir, 'multidatabackend.json'),
        # 32px-aligned latents: rounding 2 with pixel_area 1024 (as used today)
        # keeps every bucket edge a multiple of 64 — compatible with Qwen's
        # 32px alignment requirement.
        '--aspect_bucket_rounding': 2,
        '--seed': 42,
        '--minimum_image_size': 256,
        '--output_dir': weights_dir,
        '--model_type': 'lora',
        '--lora_type': 'standard',
        '--lora_rank': _rank,
        '--lora_alpha': _alpha,
        # The ONE place the crews-side 'qwen' family string becomes SimpleTuner's.
        '--pretrained_model_name_or_path': train_path or _resolve_qwen_train_path(),
        '--model_family': 'qwen_image',
        '--model_flavour': 'v2.0',
        '--base_model_precision': 'int8-quanto',
        '--text_encoder_1_precision': 'int8-quanto',
        '--quantize_via': 'cpu',
        '--quantize_activations': False,
        '--flow_schedule_shift': 1.73,
        '--attention_mechanism': os.environ.get('ZYG_ST_ATTENTION', 'diffusers'),
        '--validation_torch_compile': os.environ.get('ZYG_ST_COMPILE', 'false'),
        '--max_train_steps': job.total_steps,
        '--num_train_epochs': 0,
        '--train_batch_size': 1,
        '--gradient_checkpointing': 'true',
        '--gradient_accumulation_steps': 1,
        '--mixed_precision': 'bf16',
        '--optimizer': 'adamw_bf16',
        '--learning_rate': '1e-4',
        '--lr_scheduler': 'cosine',
        '--lr_warmup_steps': warmup_steps,
        '--caption_dropout_probability': float(
            os.environ.get('ZYG_LORA_CAPTION_DROPOUT', '0.10'),
        ),
        '--resolution_type': 'pixel_area',
        '--resolution': int(os.environ.get('ZYG_LORA_TRAIN_RES', '1024')),
        '--checkpoint_step_interval': ckpt_interval,
        '--checkpoints_total_limit': 3,
        '--validation_seed': 42,
        '--validation_step_interval': val_interval,
        '--validation_resolution': '1024x1024',
        '--validation_guidance': 3.5,
        '--validation_guidance_rescale': '0.0',
        '--validation_num_inference_steps': '30',
        '--validation_prompt': _validation_prompt(job, 'qwen'),
        '--report_to': 'tensorboard',
        '--tracker_project_name': f'storyteller-char-qwen-{job.char_id[:8]}',
        '--tracker_run_name': f'char-qwen-lora-rank{_rank}-v{job.lora_version}',
    }
    if _find_latest_checkpoint(job.output_dir, 'qwen'):
        config['--resume_from_checkpoint'] = 'latest'
    for _bad in _DEPRECATED_ST_CONFIG_KEYS:
        config.pop(_bad, None)
    with open(os.path.join(config_dir, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)


def _write_st_config_klein(
    job: TrainingJob,
    config_dir: str,
    train_path: str | None = None,
):
    """Write the SimpleTuner config.json for a FLUX.2 [klein] 4B character LoRA.

    Same schedule as the FLUX and Qwen writers (rank/alpha/steps/lr/optimizer/
    caption dropout/resolution) ON PURPOSE: the first klein run is a controlled
    comparison against the character's existing FLUX.1-dev LoRA, and a schedule
    that differs in three places answers no question. What differs is only what
    the architecture forces:

      * model_family 'flux2', flavour 'klein-4b' — the undistilled BASE.
      * bf16 everywhere, no quantisation. A 4B transformer plus the bundled
        Qwen3-4B text encoder is ~20 GB; the int8-quanto the 20B Qwen needs to
        fit at all is not needed here, and training against an unquantised
        base is one of the reasons this family exists.
      * NO pretrained_text_encoder_model_name_or_path: SimpleTuner loads the
        Qwen3 encoder from the model repo's own text_encoder/ subfolder when
        the key is absent; setting it overrides that and can pull a different
        encoder (FLUX2.md, "Important").
      * NO flux_guidance_* keys: klein has no guidance embeddings; the keys
        are ignored, and carrying them implies a lever that is not there.
      * flow_schedule_auto_shift rather than a static shift: FLUX.2 samples
        with resolution-dependent shifting (base 0.5 / max 1.15 by sequence
        length) and the dataset spans 1024x1152 buckets.
      * validation_guidance is the TRUE-CFG value — SimpleTuner moves it to
        validation_guidance_real for undistilled klein — and the model uses a
        negative prompt, so one is supplied.
    """
    steps = max(1, job.total_steps)
    warmup_steps = min(50, max(10, steps // 10))
    val_interval = _validation_interval(steps)
    ckpt_interval = min(250, max(50, steps // 4))
    weights_dir = _family_lora_weights_dir(job.output_dir, 'klein')
    os.makedirs(weights_dir, exist_ok=True)

    _rank = int(os.environ.get('ZYG_LORA_RANK', '64'))
    _alpha = int(os.environ.get('ZYG_LORA_ALPHA', str(max(1, _rank // 2))))

    config = {
        '--data_backend_config': os.path.join(config_dir, 'multidatabackend.json'),
        # 16 px latent grid (8x VAE + 2x pixel shuffle): rounding 2 at pixel_area
        # 1024 keeps every bucket edge a multiple of 64, which is a multiple of 16.
        '--aspect_bucket_rounding': 2,
        '--seed': 42,
        '--minimum_image_size': 256,
        '--output_dir': weights_dir,
        '--model_type': 'lora',
        '--lora_type': 'standard',
        '--lora_rank': _rank,
        '--lora_alpha': _alpha,
        # The ONE place the crews-side 'klein' family string becomes SimpleTuner's.
        '--pretrained_model_name_or_path': train_path or _resolve_klein_train_path(),
        '--model_family': 'flux2',
        '--model_flavour': 'klein-4b',
        '--base_model_precision': 'no_change',
        '--text_encoder_1_precision': 'no_change',
        '--flow_schedule_auto_shift': True,
        '--attention_mechanism': os.environ.get('ZYG_ST_ATTENTION', 'diffusers'),
        '--validation_torch_compile': os.environ.get('ZYG_ST_COMPILE', 'false'),
        '--max_train_steps': job.total_steps,
        '--num_train_epochs': 0,
        '--train_batch_size': 1,
        '--gradient_checkpointing': 'true',
        '--gradient_accumulation_steps': 1,
        '--mixed_precision': 'bf16',
        '--optimizer': 'adamw_bf16',
        '--learning_rate': '1e-4',
        '--lr_scheduler': 'cosine',
        '--lr_warmup_steps': warmup_steps,
        '--caption_dropout_probability': float(
            os.environ.get('ZYG_LORA_CAPTION_DROPOUT', '0.10'),
        ),
        '--resolution_type': 'pixel_area',
        '--resolution': int(os.environ.get('ZYG_LORA_TRAIN_RES', '1024')),
        '--checkpoint_step_interval': ckpt_interval,
        '--checkpoints_total_limit': 3,
        '--validation_seed': 42,
        '--validation_step_interval': val_interval,
        '--validation_resolution': '1024x1024',
        '--validation_guidance': 4.0,
        '--validation_guidance_rescale': '0.0',
        '--validation_num_inference_steps': '20',
        '--validation_negative_prompt': (
            'blurry, low quality, deformed face, bad anatomy, extra fingers, watermark, text'
        ),
        '--validation_prompt': _validation_prompt(job, 'klein'),
        '--report_to': 'tensorboard',
        '--tracker_project_name': f'storyteller-char-klein-{job.char_id[:8]}',
        '--tracker_run_name': f'char-klein-lora-rank{_rank}-v{job.lora_version}',
    }
    if _find_latest_checkpoint(job.output_dir, 'klein'):
        config['--resume_from_checkpoint'] = 'latest'
    for _bad in _DEPRECATED_ST_CONFIG_KEYS:
        config.pop(_bad, None)
    with open(os.path.join(config_dir, 'config.json'), 'w') as f:
        json.dump(config, f, indent=2)


def _write_st_multidatabackend(job: TrainingJob, config_dir: str, model_family: str = 'flux'):
    """Write the SimpleTuner multidatabackend.json for a character dataset."""
    mf = _normalize_train_family(model_family)
    # FLUX now trains at 1024 pixel-area like SDXL (was 768 — see audit note in
    # _write_st_config_flux). The FLUX VAE cache dir is res-suffixed so latents
    # cached at the old 768 resolution can never silently mix in; SDXL's
    # resolution never changed, so it keeps its existing vae_cache_sdxl.
    res = 1024 if mf == 'sdxl' else int(os.environ.get('ZYG_LORA_TRAIN_RES', '1024'))
    _res_suffix = '' if mf == 'sdxl' else f'_{res}'
    vae_cache_dir = os.path.join(job.dataset_dir, f'vae_cache_{mf}{_res_suffix}')
    os.makedirs(vae_cache_dir, exist_ok=True)
    text_cache_dir = os.path.join(job.dataset_dir, f'text_cache_{mf}')
    os.makedirs(text_cache_dir, exist_ok=True)
    # Body-template training (Medusa) pairs each image with a greyscale mask
    # whose black pixels are dropped from the loss, so a face can be present in
    # the pixels yet contribute no gradient. None for every other workflow, in
    # which case the emitted JSON below is byte-identical to what it always was.
    mask_dir = getattr(job, 'loss_mask_dir', None)
    mask_id = f'char-{job.char_id[:8]}-mask'

    backend = [
        {
            'id': f'char-{job.char_id[:8]}-images',
            'type': 'local',
            'instance_data_dir': job.dataset_dir,
            'caption_strategy': 'textfile',
            'cache_dir_vae': vae_cache_dir,
            'resolution': res,
            'resolution_type': 'pixel_area',
            'minimum_image_size': 256,
            'maximum_image_size': res,
            'target_downsample_size': res,
            'crop': False,
            'repeats': 20,  # high repeats for small dataset
            'metadata_backend': 'discovery',
            'probability': 1.0,
        },
        {
            'id': 'text-embeds',
            'type': 'local',
            'dataset_type': 'text_embeds',
            'default': True,
            'cache_dir': text_cache_dir,
        },
    ]

    if mask_dir and os.path.isdir(mask_dir):
        # Link the images backend to its mask backend, then append the mask
        # dataset. SimpleTuner multiplies the per-pixel loss by this mask
        # (helpers/models/common.py: `loss = loss * mask_image`); black = ignore.
        backend[0]['conditioning_data'] = mask_id
        backend.append(
            {
                'id': mask_id,
                'type': 'local',
                'dataset_type': 'conditioning',
                'conditioning_type': 'mask',
                'source_dataset_id': f'char-{job.char_id[:8]}-images',
                'instance_data_dir': mask_dir,
                'resolution': res,
                'resolution_type': 'pixel_area',
                'minimum_image_size': 256,
                'maximum_image_size': res,
                'target_downsample_size': res,
                'crop': False,
                'metadata_backend': 'discovery',
            }
        )

    with open(os.path.join(config_dir, 'multidatabackend.json'), 'w') as f:
        json.dump(backend, f, indent=2)
