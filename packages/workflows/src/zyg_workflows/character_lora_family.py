# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Detect and validate character LoRA checkpoints per model family (FLUX / SDXL / Qwen)."""

from __future__ import annotations

import json
import os
import re
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_LORA_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')
_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

# 2026-07-31: data/runtime derived the same way every other module in this tree
# derives it (zpub_routes_storyteller._CHAR_RUNTIME_DIR, animal_library_service,
# bp_medusa, …) — never hardcoded, so a relocated checkout still resolves.
_CREWS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.join(_CREWS_DIR, 'data', 'runtime')

# End-of-run root exports SimpleTuner writes beside the checkpoint-* dirs.
_ROOT_EXPORT_NAMES = (
    'pytorch_lora_weights.safetensors',
    'adapter_model.safetensors',
    'lora.safetensors',
)

# Distilled contact-sheet verdicts, keyed by (path, mtime_ns, size). The library
# page asks about ~56 characters per request; the state files are ~20 KB each.
_USABLE_CACHE: dict = {}


def _env_on(name: str, default: str = '1') -> bool:
    return os.environ.get(name, default).strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def infer_lora_family_from_path(lora_path: str | None) -> str | None:
    """Return 'flux', 'sdxl', 'qwen', 'klein', or None if path does not imply a family."""
    if not lora_path:
        return None
    norm = lora_path.replace('\\', '/').lower()
    if 'lora-weights-klein' in norm:
        return 'klein'
    if 'lora-weights-qwen' in norm:
        return 'qwen'
    if 'lora-weights-sdxl' in norm:
        return 'sdxl'
    if 'lora-weights-flux' in norm:
        return 'flux'
    if '/lora-weights/' in norm and 'sdxl' not in norm:
        return 'flux'
    return None


def lora_path_matches_family(lora_path: str | None, model_family: str) -> bool:
    """False when path clearly belongs to the other family."""
    want = (model_family or 'flux').strip().lower()
    if want not in ('flux', 'sdxl', 'qwen', 'klein'):
        want = 'flux'
    inferred = infer_lora_family_from_path(lora_path)
    if inferred is None:
        return True
    return inferred == want


def char_lora_families_for_dir(lora_dir: str) -> list[str]:
    """Families with at least one checkpoint under *lora_dir*."""
    fams: list[str] = []
    if not lora_dir or not os.path.isdir(lora_dir):
        return fams
    for sub, mf in (
        ('lora-weights-flux', 'flux'),
        ('lora-weights-sdxl', 'sdxl'),
        ('lora-weights-qwen', 'qwen'),
        ('lora-weights-klein', 'klein'),
        ('lora-weights', 'flux'),
    ):
        base = os.path.join(lora_dir, sub)
        if not os.path.isdir(base):
            continue
        if _dir_has_lora_checkpoint(base) and mf not in fams:
            fams.append(mf)
    return fams


def char_lora_ready_for_family(lora_dir: str, model_family: str) -> bool:
    mf = (model_family or 'flux').strip().lower()
    if mf in ('sdxl', 'qwen', 'klein'):
        # No legacy-dir fallback: the un-suffixed lora-weights/ is flux-only.
        return mf in char_lora_families_for_dir(lora_dir)
    return 'flux' in char_lora_families_for_dir(lora_dir) or (
        'flux' not in char_lora_families_for_dir(lora_dir)
        and _dir_has_lora_checkpoint(os.path.join(lora_dir, 'lora-weights'))
    )


def char_lora_usable(
    char_id: str,
    model_family: str = '',
    runtime_dir: str | None = None,
) -> tuple[bool, str]:
    """(usable, reason) for *char_id* — adapters on disk AND a run that stood.

    2026-07-31: every readiness helper in this tree answers "is this character
    LoRA-ready?" by listing *.safetensors, but contact_sheet_pipeline trains the
    LoRA BEFORE the QC safety valve and before the operator's Allow/Decline — so
    a declined, QC-failed run still leaves complete adapters on disk and the
    public wizard advertised "LoRA trained — full character consistency" for
    c3345deb5bde, whose identity QC measured 0.194 against a 0.42 floor and whose
    run a human declined.

    Usable requires BOTH:
      (a) an adapter file exists for *model_family* (empty = any family), and
      (b) data/runtime/contact_sheet_<char_id>.json, when it exists, is neither
          ``review_declined``/``status == 'declined'`` nor
          ``qc_safety_valve.verdict == 'fail'`` — OR a manifest approves the run.

    *reason* is a short human string for the library card / API payload. Cheap
    and exception-safe: this runs on web request paths, and ANY unexpected error
    resolves to the permissive legacy answer (adapter-exists) rather than
    raising or hiding every character. ZYG_CHAR_LORA_QC_GATE=0 restores the
    pre-2026-07-31 adapter-exists-only answer.
    """
    mf = (model_family or '').strip().lower()
    if mf not in ('flux', 'sdxl', 'qwen', 'klein'):
        mf = ''

    # (a) Adapter presence — the legacy answer, via this module's own helpers.
    try:
        has_adapter = _char_has_adapter(char_id, mf)
    except Exception:
        return True, 'LoRA adapter check failed — treated as usable'
    if not has_adapter:
        return False, (f'no {mf.upper()} LoRA adapter on disk' if mf else 'no LoRA adapter on disk')

    if not _env_on('ZYG_CHAR_LORA_QC_GATE'):
        return True, 'LoRA trained (QC gate disabled)'

    # (b) Contact-sheet verdict.
    try:
        declined, valve_reason, approved = _char_run_verdict(char_id, runtime_dir)
    except Exception:
        return True, 'LoRA trained (contact-sheet state unreadable)'
    if not declined and not valve_reason:
        return True, 'LoRA trained'
    if approved or _char_manifest_approved(char_id):
        return True, 'LoRA trained (run approved despite QC flags)'
    parts = []
    if declined:
        parts.append('the contact-sheet run was declined')
    if valve_reason:
        parts.append(f'identity QC failed ({valve_reason})')
    return False, 'LoRA trained but ' + ' and '.join(parts)


def _char_has_adapter(char_id: str, model_family: str = '') -> bool:
    """True when a *model_family* adapter (any family when empty) is on disk."""
    if not char_id:
        return False
    for root in (_LORA_ROOT, _DATASET_ROOT):
        lora_dir = os.path.join(root, char_id)
        if model_family:
            if char_lora_ready_for_family(lora_dir, model_family):
                return True
        elif char_lora_families_for_dir(lora_dir):
            return True
    return False


def _char_run_verdict(
    char_id: str,
    runtime_dir: str | None = None,
) -> tuple[bool, str, bool]:
    """(declined, qc_fail_reason, approved) from the contact-sheet state file.

    Absent state file → (False, '', False): a character with no recorded run is
    not penalised (legacy/imported characters predate the state file).
    """
    path = os.path.join(runtime_dir or _RUNTIME_DIR, f'contact_sheet_{char_id}.json')
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return False, '', False
    cached = _USABLE_CACHE.get(key)
    if cached is not None:
        return cached
    with open(path, encoding='utf-8') as fh:
        state = json.load(fh) or {}
    declined = state.get('review_declined') is True or str(state.get('status') or '').strip().lower() == 'declined'
    valve = state.get('qc_safety_valve') or {}
    valve_reason = ''
    if str(valve.get('verdict') or '').strip().lower() == 'fail':
        valve_reason = str(valve.get('reason') or 'safety valve verdict=fail')[:160]
    out = (declined, valve_reason, state.get('approved') is True)
    if len(_USABLE_CACHE) > 512:
        _USABLE_CACHE.clear()
    _USABLE_CACHE[key] = out
    return out


def _char_manifest_approved(char_id: str) -> bool:
    """True when any dataset/output manifest records an explicit approval."""
    for mpath in (
        os.path.join(_DATASET_ROOT, char_id, 'contact_sheet', 'manifest.json'),
        os.path.join(_DATASET_ROOT, char_id, 'manifest.json'),
        os.path.join(_LORA_ROOT, char_id, 'manifest.json'),
    ):
        try:
            with open(mpath, encoding='utf-8') as fh:
                if (json.load(fh) or {}).get('approved') is True:
                    return True
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('approval manifest %s unreadable: %s', mpath, _exc)
            continue
    return False


def _dir_has_lora_checkpoint(base: str) -> bool:
    if not os.path.isdir(base):
        return False
    try:
        for entry in os.listdir(base):
            path = os.path.join(base, entry)
            if os.path.isfile(path) and entry.endswith('.safetensors'):
                return True
            if os.path.isdir(path) and entry.startswith('checkpoint-'):
                if any(f.endswith('.safetensors') for f in os.listdir(path)):
                    return True
    except OSError as _exc:
        _zyg_log.debug('lora checkpoint scan skipped: %s', _exc)
    return False


def resolve_char_lora_path(
    char_id: str,
    model_family: str,
    *,
    preferred_path: str | None = None,
) -> str | None:
    """Best LoRA path for *model_family*, or None."""
    mf = (model_family or 'flux').strip().lower()
    if (
        preferred_path
        and os.path.isfile(preferred_path)
        and lora_path_matches_family(
            preferred_path,
            mf,
        )
    ):
        return preferred_path
    if preferred_path and not lora_path_matches_family(preferred_path, mf):
        preferred_path = None
    try:
        from zyg_workflows import lora_trainer_service as _lts

        p = _lts.get_trainer().get_lora_path(char_id, model_family=mf)
        if p and os.path.isfile(p):
            return p
    except Exception as _exc:
        _zyg_log.warning('trainer lora path lookup failed, falling back to the filesystem scan: %s', _exc)
    roots = [
        os.path.join(_LORA_ROOT, char_id),
        os.path.join(_DATASET_ROOT, char_id),
    ]
    sub = {'sdxl': 'lora-weights-sdxl', 'qwen': 'lora-weights-qwen', 'klein': 'lora-weights-klein'}.get(
        mf, 'lora-weights-flux'
    )
    fallback_sub = 'lora-weights' if mf == 'flux' else None
    for root in roots:
        for s in (sub, fallback_sub):
            if not s:
                continue
            base = os.path.join(root, s)
            if not os.path.isdir(base):
                continue
            best = _latest_checkpoint_file(base)
            if best:
                return best
    return None


def _latest_checkpoint_file(base: str) -> str | None:
    """Best adapter under *base* — checkpoint dirs AND root end-of-run exports.

    2026-07-31: this scanner used to ``continue`` on every entry that did not
    start with 'checkpoint-', so it could never return a root
    pytorch_lora_weights.safetensors — yet lora_trainer_service's
    _cleanup_after_training deletes the checkpoint dirs by default and keeps
    precisely that root export. A swept legacy-layout character therefore
    resolved to None here while _dir_has_lora_checkpoint (which does accept root
    exports) still reported it LoRA-ready, and the render silently proceeded
    LoRA-less. Mirrors lora_trainer_service._scan_lora_weights_dir: the root
    export outranks the last (lagging) checkpoint when it is the newest file.
    ZYG_CHAR_LORA_ROOT_EXPORT_SCAN=0 restores the checkpoint-only scan.
    """
    root_scan = _env_on('ZYG_CHAR_LORA_ROOT_EXPORT_SCAN')
    if root_scan:
        # Prefer the trainer's own ranking so there is one source of truth.
        try:
            from zyg_workflows import lora_trainer_service as _lts_scan

            cands = _lts_scan._scan_lora_weights_dir(base)
            if cands:
                cands.sort(key=lambda c: (-c[0], c[1]))
                return cands[0][1]
        except Exception as _exc:
            _zyg_log.warning('trainer weights scan failed, falling back to the local scan: %s', _exc)

    best_step = -1
    best_path: str | None = None
    root_files: list[tuple[float, str, str]] = []  # (mtime, name, path)
    max_ck_mtime = 0.0
    try:
        for entry in os.listdir(base):
            path = os.path.join(base, entry)
            if entry.startswith('checkpoint-') and os.path.isdir(path):
                m = re.search(r'checkpoint-(\d+)', entry)
                step = int(m.group(1)) if m else 0
                for name in _ROOT_EXPORT_NAMES:
                    p = os.path.join(path, name)
                    if os.path.isfile(p) and step >= best_step:
                        best_step = step
                        best_path = p
                        try:
                            max_ck_mtime = max(max_ck_mtime, os.path.getmtime(p))
                        except OSError as _exc:
                            _zyg_log.debug('checkpoint mtime unavailable: %s', _exc)
            elif root_scan and entry.endswith('.safetensors') and os.path.isfile(path):
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    mtime = 0.0
                root_files.append((mtime, entry, path))
    except OSError as _exc:
        _zyg_log.debug('lora weights dir listing skipped: %s', _exc)
    if root_files:
        # Deterministic winner: canonical export name first, then newest, then
        # name — never os.listdir order.
        root_files.sort(
            key=lambda r: (
                _ROOT_EXPORT_NAMES.index(r[1]) if r[1] in _ROOT_EXPORT_NAMES else len(_ROOT_EXPORT_NAMES),
                -r[0],
                r[1],
            ),
        )
        winner = root_files[0]
        if best_path is None or winner[0] >= max_ck_mtime:
            return winner[2]
    return best_path
