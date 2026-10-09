# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LoRA weight discovery, checkpoint scanning and status helpers."""

import os
import json
import logging
from typing import Optional
import logging as _zyg_logging
from zyg_workflows.lora_trainer_service.job_state import (  # noqa: F401
    TrainingJob,
    _family_lora_weights_dir,
    _legacy_lora_weights_dir,
    _normalize_train_family,
    _read_disk_train_family,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.lora_trainer_service')
logger = logging.getLogger('zyg_workflows.lora_trainer_service')

# ── Helpers ──────────────────────────────────────────────────────────────────────
# SimpleTuner's export filenames, most-canonical first. Used only to break ties
# deterministically — never to reject a file.
_EXPORT_NAME_ORDER = (
    'pytorch_lora_weights.safetensors',
    'adapter_model.safetensors',
    'lora.safetensors',
)


def _export_name_rank(name: str) -> int:
    try:
        return _EXPORT_NAME_ORDER.index(name)
    except ValueError:
        return len(_EXPORT_NAME_ORDER)


def _scan_lora_weights_dir(lora_weights_dir: str) -> list[tuple[int, str]]:
    """Collect (step, path) for all .safetensors under a weights directory.

    2026-07-31: every scan is ordered, never os.scandir order. Two directories
    that contain the same files used to resolve to different adapters run to
    run: several root *.safetensors all got the SAME rank (_max_ckpt_step + 1),
    and _find_latest_checkpoint's sort is stable, so the winner was whichever
    the filesystem happened to yield first. The `candidates` list was also
    mutated inside the root loop, so the FIRST root file decided which branch
    the rest took. Now the root files are ranked (canonical export name, then
    newest mtime, then name), only the winner can outrank a checkpoint, and the
    runners-up sit below everything so they stay as last-resort fallbacks.
    """
    if not os.path.isdir(lora_weights_dir):
        return []
    candidates: list[tuple[int, str]] = []
    _max_ckpt_step = 0
    _max_ckpt_mtime = 0.0
    try:
        _entries = sorted(os.scandir(lora_weights_dir), key=lambda e: e.name)
    except OSError:
        return []
    _ckpt_dirs: list[tuple[int, str, str]] = []  # (step, name, path)
    _root_files: list[tuple[int, float, str, str]] = []  # (name rank, -mtime, name, path)
    for entry in _entries:
        if entry.is_dir() and entry.name.startswith('checkpoint-'):
            try:
                step = int(entry.name.split('-')[1])
            except (ValueError, IndexError):
                step = 0
            _ckpt_dirs.append((step, entry.name, entry.path))
        elif entry.is_file() and entry.name.endswith('.safetensors'):
            try:
                _mtime = entry.stat().st_mtime
            except OSError:
                _mtime = 0.0
            _root_files.append((_export_name_rank(entry.name), -_mtime, entry.name, entry.path))

    _ckpt_dirs.sort(key=lambda c: (-c[0], c[1]))
    for step, _ck_name, ck_path in _ckpt_dirs:
        try:
            _ck_files = sorted(os.scandir(ck_path), key=lambda f: (_export_name_rank(f.name), f.name))
        except OSError as _exc:
            _zyg_log.debug('checkpoint dir %s unreadable, skipped: %s', ck_path, _exc)
            continue
        for f in _ck_files:
            if f.name.endswith('.safetensors'):
                candidates.append((step, f.path))
                _max_ckpt_step = max(_max_ckpt_step, step)
                try:
                    _max_ckpt_mtime = max(_max_ckpt_mtime, f.stat().st_mtime)
                except OSError as _exc:
                    _zyg_log.debug('checkpoint %s mtime unavailable: %s', f.name, _exc)

    # Root-level export = SimpleTuner's END-OF-TRAINING weights at the FULL step
    # target. With checkpoint_step_interval that doesn't divide the target, the
    # last checkpoint always lags (e.g. 1500 of 1600), so the old "only if no
    # candidates" rule shipped a lagging checkpoint and discarded the real final
    # weights (2026-07-12 audit). Rank the root export ABOVE the last checkpoint
    # when it is the newest file (i.e. actually the end-of-run export, not a
    # stale leftover from an interrupted earlier run).
    _had_ckpt = bool(candidates)
    _root_files.sort()
    for _rank, (_n_rank, _neg_mtime, _r_name, _r_path) in enumerate(_root_files):
        _root_mtime = -_neg_mtime
        if _had_ckpt and _root_mtime >= _max_ckpt_mtime:
            candidates.append(
                (_max_ckpt_step + 1 if _rank == 0 else -1 - _rank, _r_path),
            )
        elif not _had_ckpt:
            candidates.append((0 if _rank == 0 else -1 - _rank, _r_path))
    return candidates


def _find_latest_checkpoint(
    output_dir: str,
    model_family: str | None = None,
) -> Optional[str]:
    """Highest-step safetensors for a model family (family dir, then legacy)."""
    mf = _normalize_train_family(model_family) if model_family else None
    dirs_to_scan: list[str] = []
    if mf:
        dirs_to_scan.append(_family_lora_weights_dir(output_dir, mf))
        legacy = _legacy_lora_weights_dir(output_dir)
        # qwen and klein postdate the pre-split era entirely: the un-suffixed
        # legacy dir can only ever hold flux/sdxl weights, so neither claims it.
        if mf not in ('qwen', 'klein') and _read_disk_train_family(output_dir) == mf and legacy not in dirs_to_scan:
            if not os.path.isdir(_family_lora_weights_dir(output_dir, mf)):
                dirs_to_scan.append(legacy)
        elif legacy not in dirs_to_scan and _legacy_dir_is_unclaimed_flux(output_dir, mf):
            # 2026-07-31: _read_disk_train_family returns None when no
            # training_status*.json survives, so a legacy-layout character with
            # weights in lora-weights/ resolved to None in BOTH get_lora_path and
            # the fallback scan — while char_lora_families_for_dir still reported
            # it ready, so the render silently proceeded LoRA-less. The legacy dir
            # predates the split and is FLUX by convention (same rule as
            # character_lora_family.infer_lora_family_from_path), so scan it for
            # flux only, and only when no family dir claims the character.
            dirs_to_scan.append(legacy)
    else:
        for fam in ('flux', 'sdxl', 'qwen', 'klein'):
            fam_dir = _family_lora_weights_dir(output_dir, fam)
            if fam_dir not in dirs_to_scan:
                dirs_to_scan.append(fam_dir)
        legacy = _legacy_lora_weights_dir(output_dir)
        if legacy not in dirs_to_scan:
            dirs_to_scan.append(legacy)

    candidates: list[tuple[int, str]] = []
    for weights_dir in dirs_to_scan:
        candidates.extend(_scan_lora_weights_dir(weights_dir))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _legacy_dir_is_unclaimed_flux(output_dir: str, model_family: str | None) -> bool:
    """True when lora-weights/ may be read as this family's FLUX weights.

    2026-07-31: the pre-split legacy dir is FLUX by convention. Treat it as such
    when NOTHING claims it — no training_status*.json records a family and no
    lora-weights-flux/ dir exists. Never for sdxl, whose weights always live in
    the family-named dir. ZYG_LORA_LEGACY_DIR_FALLBACK=0 disables.
    """
    if _normalize_train_family(model_family) != 'flux' or not model_family:
        return False
    if os.environ.get('ZYG_LORA_LEGACY_DIR_FALLBACK', '1').strip().lower() in (
        '0',
        'false',
        'no',
        'off',
    ):
        return False
    if _read_disk_train_family(output_dir) is not None:
        return False
    return not os.path.isdir(_family_lora_weights_dir(output_dir, 'flux')) and os.path.isdir(
        _legacy_lora_weights_dir(output_dir)
    )


def _checkpoint_matches_family(path: str, output_dir: str, model_family: str) -> bool:
    if not path:
        return False
    fam_dir = _family_lora_weights_dir(output_dir, model_family)
    if path.startswith(fam_dir + os.sep):
        return True
    legacy = _legacy_lora_weights_dir(output_dir)
    if not path.startswith(legacy + os.sep):
        return False
    if _normalize_train_family(model_family) in ('qwen', 'klein'):
        # The legacy un-suffixed dir predates qwen and klein — never a match.
        return False
    return (
        _read_disk_train_family(output_dir) == _normalize_train_family(model_family) and not os.path.isdir(fam_dir)
    ) or _legacy_dir_is_unclaimed_flux(output_dir, model_family)


def _status_path_for(output_dir: str, model_family: str | None) -> str:
    """Family-scoped status file. Both FLUX and SDXL trainers share one output_dir
    per char_id, so a single training_status.json let the flux v2 refine clobber
    the sdxl trainer's status right before the sdxl lookup read it — the sdxl
    companion LoRA then silently resolved to None (2026-07-12 audit). Scope by
    family so the two never collide; the legacy shared name is still written for
    backward-compat readers."""
    mf = _normalize_train_family(model_family) if model_family else 'flux'
    return os.path.join(output_dir, f'training_status_{mf}.json')


def _save_status(job: TrainingJob, status: str):
    """Persist job status to disk for crash recovery (family-scoped + legacy)."""
    payload = {'status': status, **job.to_dict()}
    for status_path in (
        _status_path_for(job.output_dir, job.model_family),
        os.path.join(job.output_dir, 'training_status.json'),  # legacy shared
    ):
        try:
            with open(status_path, 'w') as f:
                json.dump(payload, f, indent=2)
        except Exception as _exc:
            _zyg_log.warning(
                'training status write to %s failed, the dashboard will show stale progress: %s', status_path, _exc
            )
