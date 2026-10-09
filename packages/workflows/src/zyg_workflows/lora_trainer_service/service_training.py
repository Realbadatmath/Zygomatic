# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The phases of `LoraTrainerService._run_training`, one function per block.

`_run_training` was 389 lines: base-model resolution, config writing, the VRAM
pre-flight, the SimpleTuner launch, the log-streaming progress parser, the
non-zero-exit post-mortem and the success tail, all in one frame. Nothing in it
could be exercised without a GPU, a SimpleTuner checkout and a subprocess, which
is why the tqdm parser and the error-line picker — both pure string work — had
never been tested at all.

The phases below are that body in source order, and `_run_training` is now the
sequence of their calls plus the `return`s between them:

* `prepare_base_model` — the per-family weight check (`sdxl` / `qwen` / `klein`
  / the FLUX directory probe). It returns a `BaseModel` whose `ready` is False
  for every path the monolith answered with a bare `return`, having already set
  `job.failed`/`job.done`, saved the status and set `_VRAM_RELEASED_EVENT`;
* `align_sdxl_comfy_checkpoint` and `styled_render_checkpoint` — the SDXL-only
  render-base alignment nested inside it;
* `write_simpletuner_config` — the config directory and the five writers;
* `preflight_vram` — the eviction wait, with `vram_min_gb` as its pure part;
* `launch_simpletuner` — the entry-point probe (`resolve_simpletuner_entry`),
  the environment (`training_env`) and the `Popen`; False means the monolith's
  `return` with `job.failed` set and *no* status save, as before;
* `stream_training_log` — the log rotation and the read loop, with the two pure
  line readers `parse_progress` and `saved_checkpoint_path`;
* `handle_nonzero_exit` — the tail read, the salvage-the-checkpoint decision and
  the error-message extraction (`pick_real_error`, `clean_error_line`);
* `finalize_success` — the final weight resolve, the alpha stamp, the bible
  update and the checkpoint cleanup.

`logger` and `_zyg_log` are re-created here under the service's own logger name,
not `__name__`, so every line of one training run still arrives on the
`zyg_workflows.lora_trainer_service` channel.
"""

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass

import logging as _zyg_logging

from zyg_workflows.lora_trainer_service.config_support import (
    _cleanup_after_training,
)
from zyg_workflows.lora_trainer_service.helpers import (
    _checkpoint_matches_family,
    _find_latest_checkpoint,
    _save_status,
)
from zyg_workflows.lora_trainer_service.job_state import (
    TrainingJob,
    _VRAM_RELEASED_EVENT,
)
from zyg_workflows.lora_trainer_service.model_paths import (
    _KLEIN_HF_ID,
    _KLEIN_PINNED_REV,
    _QWEN_HF_ID,
    _QWEN_PINNED_REV,
    _SIMPLE_TUNER_DIR,
    _STATUS_SAVE_INTERVAL_S,
    _TRAIN_MODEL_PATH,
    _ensure_klein_diffusers_weights,
    _ensure_qwen_diffusers_weights,
    _ensure_sdxl_diffusers_weights,
)
from zyg_workflows.lora_trainer_service.st_config import (
    _drop_stale_benchmarks,
    _ensure_preview_captions,
    _read_config_value,
    stamp_lora_alpha,
)
from zyg_workflows.lora_trainer_service.st_config_writers import (
    _write_st_config_flux,
    _write_st_config_klein,
    _write_st_config_qwen,
    _write_st_config_sdxl,
    _write_st_multidatabackend,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')

# Match actual training step count from tqdm lines like:
#   "Epoch 3/6, Steps:  49%|████| 981/2000 [55:01<56:40, 3.34s/it]"
# We only accept lines that contain "Steps:" so we don't misread loading/
# caching bars (Loading weights: 100%|, Generating bucket cache: 74%|, etc.)
_TRAIN_STEP_RE = re.compile(r'\|\s*(\d+)/(\d+)\s*\[')
_SAVED_PATH_RE = re.compile(r'(/[^\s]+\.safetensors)')
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


@dataclass
class BaseModel:
    """What `prepare_base_model` resolved: the training path, per family.

    `ready` is False when the run must stop — the caller returns at once,
    because the status and the VRAM event have already been written. At most one
    of the three paths is ever set; the FLUX family trains straight from
    `_TRAIN_MODEL_PATH` and needs none.
    """

    ready: bool = True
    sdxl: str | None = None
    qwen: str | None = None
    klein: str | None = None


def styled_render_checkpoint(char_id: str) -> str:
    """The render checkpoint of this character's isolated STYLE profile, or ''.

    In: a character id. Out: the `render_checkpoint` of the profile named by the
    bible's `style_profile.restyle`, or '' when there is no restyle, no profile
    file or no such key — every failure is '' on purpose, which is the
    public/global path.

    2026-07-26: a restyled LoRA was trained through the profile's REALISTIC base
    (render_checkpoint, e.g. Juggernaut) + a style LoRA, so THAT base must be
    recorded — not the global 3D-toon animated checkpoint.
    """
    try:
        from zyg_workflows import character_bible_service as _cbs_rc

        _restyle = str((((_cbs_rc.load(char_id) or {}).get('style_profile') or {}).get('restyle')) or '').strip()
        if not _restyle:
            return ''
        import json as _json_rc

        _spp_rc = os.path.join(
            os.path.dirname(os.path.abspath(_cbs_rc.__file__)),
            'data',
            'runtime',
            'character_style_profiles.json',
        )
        with open(_spp_rc, encoding='utf-8') as _spf_rc:
            return str(
                (((_json_rc.load(_spf_rc).get('profiles') or {}).get(_restyle)) or {}).get('render_checkpoint') or ''
            ).strip()
    except Exception:
        return ''


def align_sdxl_comfy_checkpoint(job: TrainingJob) -> None:
    """Record the Comfy checkpoint the SDXL LoRA will actually render on.

    In: the job (mutated — `job.sdxl_comfy_checkpoint`). Out: nothing. The
    restyle base wins; otherwise the animated checkpoint, because SDXL IS the
    animated path and the bible must not point at the photoreal base the LoRA
    did not render on. `ZYG_SDXL_ANIMATED=0` goes back to resolving the Comfy
    checkpoint. Any failure is a warning: the alignment is not worth the run.
    """
    try:
        from zyg_workflows import comfy_generation_service as _cgs_ckpt

        _styled_rc = styled_render_checkpoint(job.char_id)
        # 2026-07-25: SDXL is the animated path — record the animated
        # render checkpoint so the bible (via update_lora) points at
        # it, not the photoreal base the LoRA did NOT render on.
        if _styled_rc:
            job.sdxl_comfy_checkpoint = _styled_rc
        elif os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in ('0', 'false', 'no'):
            job.sdxl_comfy_checkpoint = _cgs_ckpt._SDXL_ANIMATED_CKPT
        else:
            job.sdxl_comfy_checkpoint = _cgs_ckpt.ensure_sdxl_comfy_checkpoint(
                log_fn=lambda m: logger.info(f'[LoraTrainer] {job.char_id}: {m}'),
            )
        _save_status(job, 'training')
    except Exception as _ckpt_e:
        logger.warning(
            f'[LoraTrainer] {job.char_id}: aligned SDXL Comfy checkpoint: {_ckpt_e}',
        )


def prepare_base_model(job: TrainingJob) -> BaseModel:
    """Make this family's base weights available, or stop the run.

    In: the job. Out: a `BaseModel` — `ready=False` once the job has been marked
    failed (or, for a missing FLUX tree, done/skipped), its status saved and
    `_VRAM_RELEASED_EVENT` set, which is what the four bare `return`s of the
    monolith did. Only the family's own branch runs.
    """
    if job.model_family == 'sdxl':
        try:
            _sdxl_train_path = _ensure_sdxl_diffusers_weights(
                log_fn=lambda m: logger.info(f'[LoraTrainer] {job.char_id}: {m}'),
            )
            align_sdxl_comfy_checkpoint(job)
        except Exception as _sdxl_dl_e:
            logger.error(
                f'[LoraTrainer] {job.char_id}: SDXL base model unavailable: {_sdxl_dl_e}',
            )
            job.failed = True
            job.error_msg = str(_sdxl_dl_e)[:500]
            _save_status(job, 'failed')
            _VRAM_RELEASED_EVENT.set()
            return BaseModel(ready=False)
        return BaseModel(sdxl=_sdxl_train_path)
    if job.model_family == 'qwen':
        try:
            _qwen_train_path = _ensure_qwen_diffusers_weights(
                log_fn=lambda m: logger.info(f'[LoraTrainer] {job.char_id}: {m}'),
            )
        except Exception as _qwen_dl_e:
            logger.error(
                f'[LoraTrainer] {job.char_id}: Qwen base model check failed: {_qwen_dl_e}',
            )
            _qwen_train_path = None
        if not _qwen_train_path:
            logger.error(
                f'[LoraTrainer] {job.char_id}: Qwen base model unavailable ({_QWEN_HF_ID}@{_QWEN_PINNED_REV[:12]})',
            )
            job.failed = True
            job.error_msg = (
                'Qwen-Image-2512 diffusers weights unavailable '
                '(set ZYG_QWEN_DIFFUSERS_DIR or restore the HF cache snapshot)'
            )[:500]
            _save_status(job, 'failed')
            _VRAM_RELEASED_EVENT.set()
            return BaseModel(ready=False)
        return BaseModel(qwen=_qwen_train_path)
    if job.model_family == 'klein':
        try:
            _klein_train_path = _ensure_klein_diffusers_weights(
                log_fn=lambda m: logger.info(f'[LoraTrainer] {job.char_id}: {m}'),
            )
        except Exception as _klein_dl_e:
            logger.error(
                f'[LoraTrainer] {job.char_id}: klein base model check failed: {_klein_dl_e}',
            )
            _klein_train_path = None
        if not _klein_train_path:
            logger.error(
                f'[LoraTrainer] {job.char_id}: klein base model unavailable ({_KLEIN_HF_ID}@{_KLEIN_PINNED_REV[:12]})',
            )
            job.failed = True
            job.error_msg = (
                'FLUX.2 klein-4B diffusers weights unavailable '
                '(set ZYG_KLEIN_DIFFUSERS_DIR or let the trainer download them)'
            )[:500]
            _save_status(job, 'failed')
            _VRAM_RELEASED_EVENT.set()
            return BaseModel(ready=False)
        return BaseModel(klein=_klein_train_path)
    if not os.path.isdir(_TRAIN_MODEL_PATH):
        logger.warning(
            f'[LoraTrainer] No FLUX model at {_TRAIN_MODEL_PATH} — marking training as skipped (IPAdapter-only mode)',
        )
        job.done = True
        job.lora_path = None
        _save_status(job, 'skipped_no_model')
        _VRAM_RELEASED_EVENT.set()
        return BaseModel(ready=False)
    return BaseModel()


def write_simpletuner_config(job: TrainingJob, base: BaseModel) -> str:
    """Write this family's SimpleTuner config directory and return its path.

    In: the job and the resolved base-model paths. Out: the config directory
    (`st_config_<family>` under the job's output dir), holding the family's
    `config.json` and the multidatabackend file. The previous validation prompt
    is read BEFORE the rewrite, because `_drop_stale_benchmarks` needs to know
    whether the prompt changed under the cached benchmarks.
    """
    config_dir = os.path.join(job.output_dir, f'st_config_{job.model_family}')
    os.makedirs(config_dir, exist_ok=True)
    _prev_val_prompt = _read_config_value(config_dir, '--validation_prompt')
    _ensure_preview_captions(job.dataset_dir, job.trigger_token)
    if job.model_family == 'sdxl':
        _write_st_config_sdxl(job, config_dir, train_path=base.sdxl)
    elif job.model_family == 'qwen':
        _write_st_config_qwen(job, config_dir, train_path=base.qwen)
    elif job.model_family == 'klein':
        _write_st_config_klein(job, config_dir, train_path=base.klein)
    else:
        _write_st_config_flux(job, config_dir)
    _write_st_multidatabackend(job, config_dir, model_family=job.model_family)
    _drop_stale_benchmarks(config_dir, _prev_val_prompt)
    return config_dir


def vram_min_gb(model_family: str) -> float:
    """How much free VRAM this family needs before SimpleTuner is launched.

    In: the normalised family name. Out: GB, from `ZYG_LORA_VRAM_MIN_GB` or the
    per-family default — qwen needs 36 (a 20B transformer at int8-quanto plus a
    Qwen2.5-VL text encoder), klein 24, sdxl 18, FLUX 30.
    """
    _default_vram = {'sdxl': '18', 'qwen': '36', 'klein': '24'}.get(model_family, '30')
    return float(os.environ.get('ZYG_LORA_VRAM_MIN_GB', _default_vram))


def preflight_vram(job: TrainingJob) -> None:
    """Wait for (and try to evict for) the free VRAM this training needs.

    In: the job. Out: nothing — this never stops the run, it only logs what it
    found. The single most common training failure is "CUDA OOM during
    init_precision" caused by ComfyUI (a separate process) still holding 20-30 GB
    of FLUX weights from an earlier Stage 3.5 or video pipeline.
    """
    try:
        from zyg_workflows import _comfy_client as _cc_lt

        _min_free_gb = vram_min_gb(job.model_family)
        ok, free_gb = _cc_lt.wait_for_free_vram_gb(
            min_free_gb=_min_free_gb,
            timeout_s=float(os.environ.get('ZYG_LORA_VRAM_WAIT_S', '180')),
            poll_s=2.0,
            try_evict=True,
            log_fn=lambda m: logger.info(f'[LoraTrainer] {job.char_id}: {m}'),
        )
        if ok:
            logger.info(f'[LoraTrainer] {job.char_id}: VRAM ok — {free_gb:.1f} GB free (needed ≥{_min_free_gb:.0f})')
        else:
            logger.warning(
                f'[LoraTrainer] {job.char_id}: VRAM still low ({free_gb:.1f} GB free, '
                f'needed ≥{_min_free_gb:.0f}) — launching anyway; SimpleTuner may OOM'
            )
    except Exception as _vram_e:
        logger.warning(f'[LoraTrainer] {job.char_id}: VRAM pre-flight skipped: {_vram_e}')


def resolve_simpletuner_entry() -> tuple[str, str | None]:
    """Find the interpreter and the train.py SimpleTuner will be launched with.

    In: nothing (the `_SIMPLE_TUNER_DIR` layout). Out: `(python, train_py)` —
    the checkout's own `.venv/bin/python` when it exists, else the system
    interpreter; and either entry point (`train.py`, then
    `simpletuner/train.py`), or None when neither is there.
    """
    # .venv lives inside _SIMPLE_TUNER_DIR, not in its parent
    venv_python = os.path.join(_SIMPLE_TUNER_DIR, '.venv', 'bin', 'python')
    if not os.path.isfile(venv_python):
        venv_python = '/usr/bin/python3'

    st_script = os.path.join(_SIMPLE_TUNER_DIR, 'train.py')
    if not os.path.isfile(st_script):
        # Try alternative entry point
        st_script = os.path.join(_SIMPLE_TUNER_DIR, 'simpletuner', 'train.py')
    if not os.path.isfile(st_script):
        return venv_python, None
    return venv_python, st_script


def training_env(config_dir: str) -> dict:
    """The environment SimpleTuner is launched with.

    In: the config directory. Out: a copy of this process's environment plus the
    five variables the training needs. SimpleTuner reads its config via the
    CONFIG_PATH env var (a directory containing config.json), NOT via any
    `--config_from_json` CLI flag, so CONFIG_PATH is not optional.
    """
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['TOKENIZERS_PARALLELISM'] = 'false'
    env['CONFIG_PATH'] = config_dir  # tells SimpleTuner where config.json lives
    # Reduce VRAM pressure during training/save (group offload configured in config.json)
    env['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
    env['ST_ENABLE_GRADIENT_OFFLOAD'] = '1'  # if SimpleTuner supports it
    return env


def launch_simpletuner(job: TrainingJob, config_dir: str) -> bool:
    """Start SimpleTuner on this config and attach the process to the job.

    In: the job (mutated — `job.proc`) and the config directory. Out: True when
    the process is running. False means the job was marked failed and the caller
    must return; no status file is written for either failure, exactly as the
    monolith's two bare `return`s did.
    """
    venv_python, st_script = resolve_simpletuner_entry()
    if st_script is None:
        logger.error(f'[LoraTrainer] SimpleTuner train.py not found in {_SIMPLE_TUNER_DIR}')
        job.failed = True
        job.error_msg = 'SimpleTuner train.py not found'
        return False

    cmd = [venv_python, st_script]

    logger.info(f'[LoraTrainer] {job.char_id}: launching: {" ".join(cmd)}  CONFIG_PATH={config_dir}')
    try:
        job.proc = subprocess.Popen(
            cmd,
            cwd=_SIMPLE_TUNER_DIR,
            env=training_env(config_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        logger.error(f'[LoraTrainer] {job.char_id}: failed to start process: {exc}')
        job.failed = True
        job.error_msg = str(exc)
        return False
    return True


def parse_progress(line: str) -> tuple[int, int] | None:
    """The `(step, total)` a SimpleTuner tqdm line reports, or None.

    In: one line of SimpleTuner output. Out: the pair, only for lines that are
    really the training bar — a line must name `Steps:` (or be an `Epoch` line
    with a bar), carry an `| n/N [` group, and report a sane `0 < N` with
    `n <= N`. Loading and bucket-cache bars look identical otherwise, and
    reading one of those as progress is what made a run report step counts that
    jumped backwards.
    """
    if not ('Steps:' in line or ('Epoch' in line and '%|' in line)):
        return None
    m = _TRAIN_STEP_RE.search(line)
    if not m:
        return None
    current_step = int(m.group(1))
    total = int(m.group(2))
    if total > 0 and current_step <= total:
        return current_step, total
    return None


def saved_checkpoint_path(line: str) -> str | None:
    """The safetensors path a "saved" log line names, or None.

    In: one line of SimpleTuner output. Out: the absolute path, when the line
    says something was *saved* and names a `.safetensors` file. The caller still
    checks that the file exists — a path that is only announced is not a
    checkpoint.
    """
    if 'saved' not in line.lower() or '.safetensors' not in line.lower():
        return None
    match = _SAVED_PATH_RE.search(line)
    return match.group(1) if match else None


def rotate_training_log(log_path: str) -> None:
    """Archive the previous phase's log before this one overwrites it.

    In: the family-scoped log path. Out: nothing — `<log>.prev` now holds the
    old run. Family-scoped, phase-preserving (2026-07-18): one shared
    training.log meant the v2 refine overwrote v1's and SDXL overwrote FLUX.
    """
    if os.path.isfile(log_path):
        try:
            os.replace(log_path, f'{log_path}.prev')
        except OSError as _exc:
            _zyg_log.warning('training log rotation failed, step parsing may read the previous run: %s', _exc)


def stream_training_log(job: TrainingJob, log_path: str) -> None:
    """Copy SimpleTuner's output to *log_path*, tracking progress as it goes.

    In: the running job and its log path. Out: nothing, when the process has
    closed its stdout — `job.step` and `job.lora_path` have followed the run.

    2026-08-09: the mid-run `_save_status()` used to happen ONLY in the SDXL
    pre-flight, so a flux/qwen job in progress was recoverable in-process only.
    It is saved here for every family instead, throttled by
    `_STATUS_SAVE_INTERVAL_S` so a tqdm line every fraction of a second does not
    become disk I/O that often.
    """
    rotate_training_log(log_path)
    _last_status_save_ts = 0.0
    with open(log_path, 'w') as log_fh:
        for line in job.proc.stdout:
            log_fh.write(line)
            log_fh.flush()

            # Only parse progress from actual training tqdm lines
            _progress = parse_progress(line)
            if _progress is not None:
                job.step = _progress[0]
                _now = time.time()
                if _now - _last_status_save_ts >= _STATUS_SAVE_INTERVAL_S:
                    _save_status(job, 'training')
                    _last_status_save_ts = _now

            # SimpleTuner logs the checkpoint path when it saves
            _saved = saved_checkpoint_path(line)
            if _saved and os.path.isfile(_saved):
                job.lora_path = _saved


def clean_error_line(line: str) -> str:
    """One log line with its ANSI colour codes and surrounding space removed."""
    return _ANSI_RE.sub('', line).strip()


def pick_real_error(tail_lines: list[str]) -> str:
    """The line of a failed run's log tail that actually says what went wrong.

    In: the last lines of the training log, oldest first. Out: the newest line
    that names an error (`error:`, `traceback`, `exited`), else the newest line
    with any content at all, else ''. Argparse usage lines (`[--flag ...]`) are
    never the answer — a run that died on a bad flag printed thirty of them
    after the one sentence that mattered.
    """
    for _line in reversed(tail_lines):
        _clean = clean_error_line(_line)
        if not _clean or _clean.startswith('[--'):
            continue
        if 'error:' in _clean.lower() or 'traceback' in _clean.lower() or 'exited' in _clean.lower():
            return _clean
    return next(
        (
            clean_error_line(line)
            for line in reversed(tail_lines)
            if clean_error_line(line) and not clean_error_line(line).startswith('[--')
        ),
        '',
    )


def handle_nonzero_exit(job: TrainingJob, ret: int, log_path: str) -> None:
    """Decide what a non-zero SimpleTuner exit means for the job, and record it.

    In: the job, the exit code and the log path. Out: nothing — the job is
    either done (a checkpoint of the right family past half the schedule
    survived, and a usable LoRA beats a failed run) or failed with the real
    error message from the log tail. Either way the status is saved and
    `_VRAM_RELEASED_EVENT` is set, because the card is free now.
    """
    logger.error(f'[LoraTrainer] {job.char_id}: SimpleTuner exited {ret}')
    # Read last 25 lines of training.log for the real error message
    _tail_lines = []
    try:
        with open(log_path) as _lf:
            _tail_lines = _lf.read().splitlines()[-25:]
    except OSError as _exc:
        _zyg_log.debug('training log tail unreadable: %s', _exc)
    job.log_tail = _tail_lines  # stored so caller can surface to live tail
    job.lora_path = _find_latest_checkpoint(job.output_dir, job.model_family)
    min_steps = max(10, int(job.total_steps * 0.5))
    if (
        job.lora_path
        and job.step >= min_steps
        and _checkpoint_matches_family(
            job.lora_path,
            job.output_dir,
            job.model_family,
        )
    ):
        logger.info(
            f'[LoraTrainer] {job.char_id}: found checkpoint despite exit code (step={job.step}) — using it',
        )
        job.done = True
    else:
        job.lora_path = None
        job.failed = True
        job.error_msg = f'SimpleTuner exited {ret}'
        if _tail_lines:
            # Prefer argparse/exit errors; skip usage lines and bare ANSI resets
            _real_err = pick_real_error(_tail_lines)
            if _real_err:
                job.error_msg = _real_err[:300]
    _save_status(job, 'failed' if job.failed else 'done')
    _VRAM_RELEASED_EVENT.set()


def finalize_success(job: TrainingJob) -> None:
    """Record the finished LoRA: final weights, alpha stamp, bible, cleanup.

    In: a job whose SimpleTuner exited 0. Out: nothing — `job.done` is set, the
    status is saved, the VRAM event is set and the character bible points at
    weights that exist on disk.

    The final path is always RE-RESOLVED (2026-07-18): the mid-run log match
    records the last checkpoint save, but the authoritative end-of-run weights
    are the root export — and the only file guaranteed to survive checkpoint
    cleanup. Recording the checkpoint left 5/5 trained characters' bibles
    pointing at a deleted file, and ComfyGen then rendered without the LoRA.
    """
    _final_path = _find_latest_checkpoint(job.output_dir, job.model_family)
    if _final_path and os.path.isfile(_final_path):
        job.lora_path = _final_path

    # Make the export self-describing BEFORE anything records or renders it
    # — without this the file cannot state its own strength and ComfyUI
    # applies it at 2x (see stamp_lora_alpha).
    try:
        stamp_lora_alpha(job.lora_path)
    except Exception as _st_e:
        logger.warning(f'[LoraTrainer] alpha stamp failed: {_st_e}')

    job.step = job.total_steps
    job.done = True
    _save_status(job, 'done')
    _VRAM_RELEASED_EVENT.set()
    logger.info(f'[LoraTrainer] {job.char_id}: training complete → {job.lora_path}')
    try:
        from zyg_workflows import character_bible_service as _cbs_lora

        _cbs_lora.update_lora(job.char_id, job.lora_path, model_family=job.model_family)
    except Exception as _cbs_e:
        logger.warning(f'[LoraTrainer] character bible update failed: {_cbs_e}')
    if not job.cleanup_after:
        logger.info(
            f'[LoraTrainer] {job.char_id}: checkpoint cleanup deferred '
            f'(flywheel refine will resume from the latest checkpoint)',
        )
        return
    try:
        _cleanup_after_training(job)
        # If cleanup removed the recorded file (checkpoint path with a
        # newer root export present), re-resolve and re-persist so status
        # and bible always reference weights that exist on disk.
        if job.lora_path and not os.path.isfile(job.lora_path):
            job.lora_path = _find_latest_checkpoint(job.output_dir, job.model_family)
            _save_status(job, 'done')
            try:
                from zyg_workflows import character_bible_service as _cbs_lora2

                _cbs_lora2.update_lora(
                    job.char_id,
                    job.lora_path,
                    model_family=job.model_family,
                )
            except Exception as _exc:
                _zyg_log.warning(
                    'character bible LoRA registration for %s failed, the bible keeps the old path: %s',
                    job.char_id,
                    _exc,
                )
    except Exception as _cl_e:
        logger.warning(f'[LoraTrainer] post-training cleanup failed: {_cl_e}')
