# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Base-model path resolution and training constants."""

import os
import logging
import subprocess
from typing import Optional
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')

# ── Paths ────────────────────────────────────────────────────────────────────────
_SIMPLE_TUNER_DIR = paths.ZYG_SIMPLETUNER_DIR
_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
_OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')
_CREATURE_OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'creatures')
_FLUX_DEV_PATH = str(paths.ZYG_FLUX_ROOT / 'flux1-dev')
_FLUX_SCHNELL_PATH = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')

# Prefer flux1-dev for training; schnell is distilled and doesn't produce good LoRAs
_TRAIN_MODEL_PATH = _FLUX_DEV_PATH if os.path.isdir(_FLUX_DEV_PATH) else _FLUX_SCHNELL_PATH

# ComfyUI merged checkpoint (inference only — SimpleTuner needs diffusers layout).
_SDXL_COMFY_CKPT = str(
    paths.ZYG_COMFY_ROOT / 'models' / 'checkpoints' / 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
)
_SDXL_DIFFUSERS_HF_ID = 'stabilityai/stable-diffusion-xl-base-1.0'
#: Hub revision the base weights are fetched at; set ZYG_SDXL_HF_REVISION to a commit sha to pin it.
_SDXL_DIFFUSERS_HF_REVISION = os.environ.get('ZYG_SDXL_HF_REVISION', '') or 'main'
_SDXL_HF_CACHE_ROOT = str(
    paths.ZYG_HOME
    / '.cache'
    / 'huggingface'
    / 'hub'
    / 'models--stabilityai--stable-diffusion-xl-base-1.0'
    / 'snapshots'
)
_SDXL_LOCAL_DIFFUSERS = os.environ.get(
    'ZYG_SDXL_DIFFUSERS_DIR',
    str(paths.ZYG_MODELS_ROOT / 'SDXL' / 'stable-diffusion-xl-base-1.0'),
).strip()

_SDXL_WEIGHT_FILENAMES = (
    'model.safetensors',
    'pytorch_model.bin',
    'diffusion_pytorch_model.safetensors',
)

# Qwen-Image-2512 (Apache-2.0). Crews-side family string is 'qwen' everywhere;
# only the SimpleTuner config.json translates it to '--model_family': 'qwen_image'.
_QWEN_HF_ID = 'Qwen/Qwen-Image-2512'
# Pinned snapshot revision — the full 54 GB tree verified on disk 2026-08-09.
_QWEN_PINNED_REV = '25468b98e3276ca6700de15c6628e51b7de54a26'
_QWEN_HF_SNAPSHOT = os.path.join(
    os.path.expanduser('~/.cache/huggingface/hub'),
    'models--Qwen--Qwen-Image-2512',
    'snapshots',
    _QWEN_PINNED_REV,
)
_QWEN_LOCAL_DIFFUSERS = os.environ.get('ZYG_QWEN_DIFFUSERS_DIR', '').strip()

# FLUX.2 [klein] 4B BASE (Apache-2.0), 2026-08-25. Crews-side family string is
# 'klein'; only _write_st_config_klein translates it to SimpleTuner's
# '--model_family': 'flux2', '--model_flavour': 'klein-4b'. The BASE (undistilled)
# repo is the training base — the distilled 'FLUX.2-klein-4B' is the 4-step
# throughput model and, like schnell, is the wrong thing to train on. Pinned to
# the revision the licence registry was verified against. Only the 4B is
# Apache-2.0: FLUX.2-klein-base-9B is flux-non-commercial and must never be
# substituted here.
_KLEIN_HF_ID = 'black-forest-labs/FLUX.2-klein-base-4B'
_KLEIN_PINNED_REV = 'a3b4f4849157f664bdbc776fd7453c2783562f4d'
_KLEIN_LOCAL_DIFFUSERS = os.environ.get(
    'ZYG_KLEIN_DIFFUSERS_DIR',
    str(paths.ZYG_MODELS_ROOT / 'FLUX2' / 'flux2-klein-base-4b'),
).strip()


def _sdxl_submodel_has_weights(subdir: str) -> bool:
    """True when a diffusers subfolder contains loadable weight files."""
    if not os.path.isdir(subdir):
        return False
    for fn in _SDXL_WEIGHT_FILENAMES:
        if os.path.isfile(os.path.join(subdir, fn)):
            return True
    if os.path.isfile(os.path.join(subdir, 'model.safetensors.index.json')):
        return True
    if os.path.isfile(os.path.join(subdir, 'diffusion_pytorch_model.safetensors.index.json')):
        return True
    return False


def _sdxl_diffusers_complete(path: str) -> bool:
    """True when *path* is a full SDXL diffusers tree (not config-only stubs)."""
    if not path or not os.path.isdir(path):
        return False
    if not os.path.isfile(os.path.join(path, 'model_index.json')):
        return False
    for sub in ('text_encoder', 'text_encoder_2', 'unet', 'vae'):
        if not _sdxl_submodel_has_weights(os.path.join(path, sub)):
            return False
    return True


def _iter_sdxl_diffusers_candidates() -> list[str]:
    """Ordered list of local paths that might hold a complete SDXL diffusers base."""
    out: list[str] = []
    override = os.environ.get('ZYG_SDXL_TRAIN_CHECKPOINT', '').strip()
    # 2026-07-25: the .env pins ZYG_SDXL_TRAIN_CHECKPOINT to the animated
    # (DynaVision) base so SDXL LoRAs train on-model. When SDXL=animated is
    # rolled back (ZYG_SDXL_ANIMATED=0), ignore that override so training
    # reverts to the photoreal SDXL base and doesn't train/render-mismatch.
    _animated_on = os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in ('0', 'false', 'no')
    if override and _animated_on and os.path.isdir(override) and not override.endswith('.safetensors'):
        out.append(override)
    if _SDXL_LOCAL_DIFFUSERS:
        out.append(_SDXL_LOCAL_DIFFUSERS)
    if os.path.isdir(_SDXL_HF_CACHE_ROOT):
        snaps = []
        for name in os.listdir(_SDXL_HF_CACHE_ROOT):
            snap = os.path.join(_SDXL_HF_CACHE_ROOT, name)
            if os.path.isfile(os.path.join(snap, 'model_index.json')):
                snaps.append(snap)
        snaps.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        out.extend(snaps)
    # De-dupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _resolve_sdxl_train_path() -> str:
    """Return a SimpleTuner-compatible SDXL base path (complete diffusers dir).

    Merged ``.safetensors`` Comfy checkpoints cannot be used here.  Incomplete
    HuggingFace cache stubs (config-only) are skipped.
    """
    override = os.environ.get('ZYG_SDXL_TRAIN_CHECKPOINT', '').strip()
    if override.endswith('.safetensors') and os.path.isfile(override):
        logger.warning(
            '[LoraTrainer] ZYG_SDXL_TRAIN_CHECKPOINT is a merged .safetensors file '
            f'({override}) — need diffusers SDXL base for training',
        )
    for cand in _iter_sdxl_diffusers_candidates():
        if _sdxl_diffusers_complete(cand):
            return cand
    return _SDXL_LOCAL_DIFFUSERS or _SDXL_DIFFUSERS_HF_ID


def _ensure_sdxl_diffusers_weights(log_fn=None) -> str:
    """Ensure a complete SDXL diffusers tree exists; download once if needed."""
    _log = log_fn or (lambda m: logger.info(m))
    ready = _resolve_sdxl_train_path()
    if _sdxl_diffusers_complete(ready):
        _log(f'[LoraTrainer] SDXL diffusers base ready → {ready}')
        return ready

    dest = _SDXL_LOCAL_DIFFUSERS
    os.makedirs(os.path.dirname(dest) or dest, exist_ok=True)
    _log(
        f'[LoraTrainer] Downloading {_SDXL_DIFFUSERS_HF_ID} → {dest} '
        f'(~6 GB one-time; required for SDXL LoRA training)…',
    )
    try:
        from huggingface_hub import snapshot_download

        # revision pins what is fetched. 'main' is the branch this download has always
        # taken; no commit sha for the SDXL base card is recorded in this tree, so the
        # branch name is made explicit here rather than left implicit.
        snapshot_download(
            repo_id=_SDXL_DIFFUSERS_HF_ID,
            revision=_SDXL_DIFFUSERS_HF_REVISION,
            local_dir=dest,
            local_dir_use_symlinks=False,
        )
    except Exception as exc:
        raise RuntimeError(f'Failed to download SDXL diffusers weights to {dest}: {exc}') from exc

    if not _sdxl_diffusers_complete(dest):
        raise RuntimeError(
            f'SDXL download finished but weights still missing under {dest} '
            f'(check disk space and HF_TOKEN if the repo is gated)',
        )
    _log(f'[LoraTrainer] SDXL diffusers download complete → {dest}')
    return dest


def _sdxl_train_model_ready(train_path: str) -> bool:
    if not train_path:
        return False
    if os.path.isdir(train_path):
        return _sdxl_diffusers_complete(train_path)
    return '/' not in train_path and not train_path.endswith('.safetensors')


def _qwen_submodel_has_weights(subdir: str) -> bool:
    """Mirror of _sdxl_submodel_has_weights that also accepts sharded trees
    (Qwen's transformer/text_encoder ship as *-0000N-of-0000M.safetensors)."""
    if _sdxl_submodel_has_weights(subdir):
        return True
    if not os.path.isdir(subdir):
        return False
    try:
        return any(fn.endswith('.safetensors') for fn in os.listdir(subdir))
    except OSError:
        return False


def _qwen_diffusers_complete(path: str) -> bool:
    """True when *path* is a full Qwen-Image diffusers tree (not config-only stubs)."""
    if not path or not os.path.isdir(path):
        return False
    if not os.path.isfile(os.path.join(path, 'model_index.json')):
        return False
    for sub in ('transformer', 'text_encoder', 'vae'):
        if not _qwen_submodel_has_weights(os.path.join(path, sub)):
            return False
    return True


def _resolve_qwen_train_path() -> str:
    """First complete local Qwen diffusers tree (env override wins), else the
    pinned HF cache snapshot path."""
    for cand in (_QWEN_LOCAL_DIFFUSERS, _QWEN_HF_SNAPSHOT):
        if cand and _qwen_diffusers_complete(cand):
            return cand
    return _QWEN_LOCAL_DIFFUSERS or _QWEN_HF_SNAPSHOT


def _ensure_qwen_diffusers_weights(log_fn=None) -> Optional[str]:
    """Ensure a complete Qwen-Image-2512 diffusers tree; return its dir or None.

    The pinned snapshot is normally already on disk (54 GB, verified
    2026-08-09) — the download branch is a safety net only.
    """
    _log = log_fn or (lambda m: logger.info(m))
    ready = _resolve_qwen_train_path()
    if _qwen_diffusers_complete(ready):
        _log(f'[LoraTrainer] Qwen diffusers base ready → {ready}')
        return ready

    _log(
        f'[LoraTrainer] Qwen diffusers base incomplete — downloading '
        f'{_QWEN_HF_ID}@{_QWEN_PINNED_REV[:12]} (~54 GB; safety net)…',
    )
    try:
        subprocess.run(
            ['hf', 'download', _QWEN_HF_ID, '--revision', _QWEN_PINNED_REV],
            check=True,
            capture_output=True,
            text=True,
            timeout=float(os.environ.get('ZYG_QWEN_DL_TIMEOUT_S', str(6 * 3600))),
        )
    except Exception as exc:
        _log(f'[LoraTrainer] Qwen weights download failed: {exc}')

    ready = _resolve_qwen_train_path()
    if _qwen_diffusers_complete(ready):
        _log(f'[LoraTrainer] Qwen diffusers download complete → {ready}')
        return ready
    return None


def _klein_diffusers_complete(path: str) -> bool:
    """True when *path* is a full klein-4B diffusers tree.

    Checks WEIGHTS, not just directories: the first download of this tree left
    transformer/ holding only config.json (hf download's include-glob quietly
    skipped the 7.75 GB file) — a directory-only test would have called that
    complete and SimpleTuner would have failed 60 s into the run.
    """
    if not path or not os.path.isdir(path):
        return False
    need = (
        ('transformer', 'diffusion_pytorch_model.safetensors', 7_000_000_000),
        ('text_encoder', 'model-00001-of-00002.safetensors', 4_000_000_000),
        ('text_encoder', 'model-00002-of-00002.safetensors', 2_500_000_000),
        ('vae', 'diffusion_pytorch_model.safetensors', 100_000_000),
        ('tokenizer', 'tokenizer.json', 1_000_000),
    )
    for sub, fn, min_bytes in need:
        p = os.path.join(path, sub, fn)
        try:
            if os.path.getsize(p) < min_bytes:
                return False
        except OSError:
            return False
    return os.path.isfile(os.path.join(path, 'model_index.json'))


def _resolve_klein_train_path() -> str:
    """The local klein-4B diffusers tree (env override wins)."""
    return _KLEIN_LOCAL_DIFFUSERS


def _ensure_klein_diffusers_weights(log_fn=None) -> Optional[str]:
    """Ensure a complete klein-4B diffusers tree; return its dir or None.

    Downloads only the subfolders SimpleTuner reads. The repo also carries a
    7.75 GB top-level single-file copy of the transformer (for ComfyUI users);
    it is excluded — the ComfyUI copy lives under models/diffusion_models.
    """
    _log = log_fn or (lambda m: logger.info(m))
    ready = _resolve_klein_train_path()
    if _klein_diffusers_complete(ready):
        _log(f'[LoraTrainer] klein diffusers base ready → {ready}')
        return ready
    _log(
        f'[LoraTrainer] klein diffusers base incomplete — downloading '
        f'{_KLEIN_HF_ID}@{_KLEIN_PINNED_REV[:12]} (~16 GB)…',
    )
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            _KLEIN_HF_ID,
            revision=_KLEIN_PINNED_REV,
            local_dir=ready,
            allow_patterns=[
                'transformer/*',
                'text_encoder/*',
                'tokenizer/*',
                'vae/*',
                'scheduler/*',
                '*.json',
                'LICENSE.md',
            ],
        )
    except Exception as exc:
        _log(f'[LoraTrainer] klein weights download failed: {exc}')
    if _klein_diffusers_complete(ready):
        _log(f'[LoraTrainer] klein diffusers download complete → {ready}')
        return ready
    return None


# Deprecated SimpleTuner CLI flags (removed upstream — must not appear in config.json)
_DEPRECATED_ST_CONFIG_KEYS = (
    '--enable_model_cpu_offload',
    '--enable_sequential_cpu_offload',
)

# Offload flags that we now strip from any stale config.json on disk because
# they're incompatible with --gradient_checkpointing (cuda/cpu mismatch in
# backward pass). Kept stripped unless ZYG_ST_GROUP_OFFLOAD is opted-in.
_GROUP_OFFLOAD_KEYS = (
    '--enable_group_offload',
    '--group_offload_type',
    '--group_offload_blocks_per_group',
    '--group_offload_use_stream',
)

# Number of training steps — character LoRAs (override via ZYG_LORA_TRAIN_STEPS in .env)
# 1200 base steps (was 200): at batch 1 with ~50 images × 20 repeats, 200 steps
# covered <20% of one epoch — the 2026-07-09 audit found the step-400 validation
# render nearly identical to the base model (trigger token learned nothing).
_QUICK_STEPS = int(os.environ.get('ZYG_LORA_TRAIN_STEPS', '1200'))

# Floor and ceiling on the epoch-scaled schedule below. The ceiling is a
# runaway guard against a week-long run, NOT a quality opinion — and it bites
# early: at ZYG_LORA_EPOCHS=26 it caps any dataset above ~69 images, so a
# 340-photo folder was getting ~5 passes per image instead of 26.
#
# Set ZYG_LORA_MAX_STEPS=0 to remove it globally, or pass max_steps= per call.
# Callers that legitimately hold hundreds of photographs (the Medusa Training
# tab imports whole galleries) pass max_steps=0 so every image gets the full
# epoch count; the storyteller/crime/documentary paths keep the default
# ceiling, so their schedules are unchanged by this parameter existing.
_EPOCH_STEP_FLOOR = int(os.environ.get('ZYG_LORA_MIN_STEPS', '900'))
_EPOCH_STEP_CEIL = int(os.environ.get('ZYG_LORA_MAX_STEPS', '1800'))

# 2026-08-09: throttle for mid-run _save_status() calls from the stdout-parsing
# loop (see _run_training) — writes a live status FILE for flux/qwen while
# training (previously only the SDXL pre-flight branch ever wrote one), capped
# so tqdm's per-line updates don't turn into per-line disk writes.
_STATUS_SAVE_INTERVAL_S = float(os.environ.get('ZYG_LORA_STATUS_SAVE_INTERVAL_S', '15'))
