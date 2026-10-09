# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character style/LoRA resolution: families, trained-at, adapter discovery.

Moved verbatim out of the old single-file char_state_service.py (lines 779-1282).
"""

import json
import os
from datetime import datetime
from zyg_workflows.pipeline_config import (
    _ANIMATED_USE_FLUX,
    _CHAR_DEFAULT_MODEL_FAMILY,
    _CHAR_DUAL_LORA_PHOTOREAL,
    _CHAR_PHOTOREAL_HYBRID_PREVIEW,
)
from zyg_workflows.runtime import (
    _parse_iso_to_ams,
)
from zyg_workflows.char_state_service._common import (
    _CHARS_DATASETS,
    _CHARS_OUTPUTS,
    _preview_env_on,
    _zyg_log,
)
from zyg_workflows.char_state_service.char_state import (
    _char_state_path,
)


def _char_render_style(params: dict | None, info: dict | None = None) -> str:
    params = params or {}
    info = info or {}
    pkg = info.get('package') or {}
    return (
        (
            params.get('render_style')
            or params.get('style')
            or (pkg.get('style_profile') or {}).get('render_style')
            or ''
        )
        .strip()
        .lower()
    )


def _char_is_photoreal_style(params: dict | None = None, info: dict | None = None) -> bool:
    rs = _char_render_style(params, info)
    return rs in ('photorealistic', 'cinematic', 'realistic', 'photo', '')


def _char_restyle_profile(params: dict | None = None, info: dict | None = None) -> dict | None:
    """State-side arcane/restyle gate: resolve the char's style_profile.restyle to a
    profile dict, else None. Mirrors comfy_generation_service._restyle_profile_from_package.
    Public/global characters never carry style_profile.restyle → None → zero blast radius.
    """
    name = (((info or {}).get('package') or {}).get('style_profile') or {}).get('restyle')
    if not name:
        return None
    try:
        from zyg_workflows import arcane_restyle as _ar_cs

        prof = _ar_cs.load_profile(str(name))
        return prof if (prof and prof.get('restyle')) else None
    except Exception:
        return None


def _char_lora_train_families(
    model_family: str | None,
    params: dict | None = None,
    info: dict | None = None,
) -> list[str]:
    """Photoreal characters train both FLUX (story) and SDXL (previews) LoRAs."""
    mf = (model_family or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl', 'qwen', 'klein'):
        mf = 'flux'
    if not _CHAR_DUAL_LORA_PHOTOREAL or not _char_is_photoreal_style(params, info):
        return [mf]
    if mf in ('qwen', 'klein'):
        # The dual-LoRA pairing is flux↔sdxl; qwen/klein have no companion
        # twin — and pairing klein with FLUX would mint a flux1-dev derivative
        # on a run that chose klein precisely to avoid that licence.
        return [mf]
    other = 'sdxl' if mf == 'flux' else 'flux'
    return [mf, other]


def _char_has_sdxl_lora(
    cond: dict | None,
    char_id: str,
    dataset_dir: str,
) -> bool:
    cond = cond or {}
    for p in (cond.get('sdxl_lora_path'), _discover_char_sdxl_lora(char_id, dataset_dir)):
        if p and os.path.isfile(p):
            return True
    return False


def _char_effective_hybrid_preview(
    params: dict | None = None,
    info: dict | None = None,
    char_id: str = '',
    dataset_dir: str = '',
) -> bool:
    """Hybrid SDXL body + FLUX face only when an SDXL LoRA actually exists."""
    if not _char_photoreal_hybrid_preview(params, info):
        return False
    pkg = (info or {}).get('package') or {}
    cond = (pkg.get('conditioning') or {}) if isinstance(pkg, dict) else {}
    ds = dataset_dir or (info or {}).get('dataset_dir') or ''
    if not char_id:
        char_id = (info or {}).get('char_id') or ''
    return _char_has_sdxl_lora(cond, char_id, ds)


def _char_photoreal_hybrid_preview(params: dict | None = None, info: dict | None = None) -> bool:
    """Photoreal: FLUX face (pores) + SDXL front (composition + HandDetailer)."""
    if not _CHAR_PHOTOREAL_HYBRID_PREVIEW:
        return False
    rs = _char_render_style(params, info)
    return rs in ('photorealistic', 'cinematic', 'realistic', 'photo', '')


def _char_lora_output_ready(lora_dir: str) -> bool:
    """True when any LoRA safetensors exist under the char's lora-outputs folder."""
    if not lora_dir or not os.path.isdir(lora_dir):
        return False
    for sub in ('', 'lora-weights', 'lora-weights-flux', 'lora-weights-sdxl'):
        base = lora_dir if not sub else os.path.join(lora_dir, sub)
        if not os.path.isdir(base):
            continue
        try:
            for entry in os.listdir(base):
                path = os.path.join(base, entry)
                if os.path.isfile(path) and entry.endswith('.safetensors'):
                    return True
                if os.path.isdir(path) and entry.startswith('checkpoint-'):
                    if any(f.endswith('.safetensors') for f in os.listdir(path)):
                        return True
        except OSError as _exc:
            _zyg_log.debug('lora weight scan skipped, directory unreadable: %s', _exc)
    return False


def _char_trained_at_from_status(lora_dir: str) -> list[str]:
    """completed_at stamps from training_status[_<family>].json (newest wins).

    2026-07-31: lora_trainer_service._save_status does not write completed_at yet
    (cross-file request filed) — this stays empty until it does, which is why the
    adapter mtime below is the real ground truth today.
    """
    out: list[str] = []
    if not lora_dir or not os.path.isdir(lora_dir):
        return out
    for fn in ('training_status_flux.json', 'training_status_sdxl.json', 'training_status.json'):
        p = os.path.join(lora_dir, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding='utf-8') as _tf:
                _ts = json.load(_tf)
            if isinstance(_ts, dict) and _ts.get('completed_at'):
                out.append(str(_ts['completed_at']))
        except Exception as _exc:
            _zyg_log.debug('training_status.json unreadable, no trained_at from it: %s', _exc)
    return out


def _char_trained_at_from_adapters(lora_dir: str) -> list[str]:
    """mtime of every real LoRA adapter on disk — 'which weights are actually there'."""
    out: list[str] = []
    if not lora_dir or not os.path.isdir(lora_dir):
        return out
    for sub in ('', 'lora-weights', 'lora-weights-flux', 'lora-weights-sdxl'):
        base = lora_dir if not sub else os.path.join(lora_dir, sub)
        if not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except OSError as _exc:
            _zyg_log.debug('adapter scan skipped, directory unreadable: %s', _exc)
            continue
        for entry in entries:
            # Never date a character from a hidden/backup/broken adapter copy.
            if entry.startswith('.') or '.broken' in entry or 'backup' in entry.lower():
                continue
            path = os.path.join(base, entry)
            try:
                if os.path.isfile(path) and entry.endswith('.safetensors'):
                    out.append(
                        datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec='seconds')
                    )
                elif os.path.isdir(path) and entry.startswith('checkpoint-'):
                    for f in os.listdir(path):
                        if f.endswith('.safetensors'):
                            out.append(
                                datetime.fromtimestamp(os.path.getmtime(os.path.join(path, f)))
                                .astimezone()
                                .isoformat(timespec='seconds')
                            )
            except Exception as _exc:
                _zyg_log.debug('adapter timestamp skipped, stat failed: %s', _exc)
    return out


def _char_trained_at_from_timeline(char_id: str) -> list[str]:
    """ended_at of completed LoRA-training stages in the char_gen stage_timeline."""
    out: list[str] = []
    try:
        _st_path = _char_state_path(char_id)
        if not os.path.isfile(_st_path):
            return out
        with open(_st_path, encoding='utf-8') as _sf:
            _st = json.load(_sf)
        tl = _st.get('stage_timeline') or []
        _train = [
            e
            for e in tl
            if isinstance(e, dict) and e.get('ended_at') and str(e.get('status') or '').lower() == 'completed'
        ]
        _lora = [
            e
            for e in _train
            if 'lora' in str(e.get('name') or '').lower() and 'train' in str(e.get('name') or '').lower()
        ]
        for e in _lora or _train:
            out.append(str(e.get('ended_at')))
    except Exception as _exc:
        _zyg_log.debug('trained_at from the stage timeline unavailable: %s', _exc)
    return out


def _char_newest_iso(stamps: list[str]) -> str:
    """Newest of a list of ISO-8601 stamps (tz-aware compare, string fallback)."""
    best = ''
    best_dt = None
    for s in stamps:
        if not s:
            continue
        _dt = None
        try:
            _dt = _parse_iso_to_ams(s)
        except Exception:
            _dt = None
        if _dt is not None and best_dt is not None:
            if _dt > best_dt:
                best, best_dt = s, _dt
        elif _dt is not None and best_dt is None:
            best, best_dt = s, _dt
        elif best_dt is None and s > best:
            best = s
    return best


def _char_library_trained_at(char_id: str, meta: dict, lora_dir: str) -> str:
    """Best-effort timestamp for library sorting (newest first).

    2026-07-31: this used to return the char_gen job's `ended` — a bp_metrics
    backfill of the bible's updated_at that predated every adapter on disk by 20+
    hours (c3345deb5bde: state ended 07-26T00:22, FLUX adapter 07-26T20:59, SDXL
    adapter 07-27T03:57).  Since the library sorts newest-first on this field,
    retrained characters sank below never-retrained ones.  Prefer real training
    evidence: training_status*.json completed_at, completed LoRA-training stage
    timeline rows, and the adapter files themselves — newest of the three.
    """
    meta = meta or {}
    if _preview_env_on('ZYG_CHAR_TRAINED_AT_TRUE'):
        _cands: list[str] = []
        try:
            _cands.extend(_char_trained_at_from_status(lora_dir))
        except Exception as _exc:
            _zyg_log.debug('trained_at from training_status unavailable: %s', _exc)
        try:
            _cands.extend(_char_trained_at_from_timeline(char_id))
        except Exception as _exc:
            _zyg_log.debug('trained_at from the stage timeline unavailable: %s', _exc)
        try:
            _cands.extend(_char_trained_at_from_adapters(lora_dir))
        except Exception as _exc:
            _zyg_log.debug('trained_at from the adapters unavailable: %s', _exc)
        _best = _char_newest_iso(_cands)
        if _best:
            return _best
    if meta.get('trained_at'):
        return str(meta['trained_at'])
    try:
        _st_path = _char_state_path(char_id)
        if os.path.isfile(_st_path):
            with open(_st_path, encoding='utf-8') as _sf:
                _st = json.load(_sf)
            return str(_st.get('ended') or _st.get('started') or '')
    except Exception as _exc:
        _zyg_log.debug('char state unreadable, trying training_status: %s', _exc)
    _ts_path = os.path.join(lora_dir, 'training_status.json')
    if os.path.isfile(_ts_path):
        try:
            with open(_ts_path, encoding='utf-8') as _tf:
                _ts = json.load(_tf)
            if _ts.get('completed_at'):
                return str(_ts['completed_at'])
        except Exception as _exc:
            _zyg_log.debug('training_status.json unreadable: %s', _exc)
    return ''


def _discover_char_sdxl_lora(char_id: str, dataset_dir: str | None = None) -> str | None:
    """SDXL LoRA path for preview slots."""
    roots: list[str] = []
    if dataset_dir:
        roots.append(dataset_dir)
    if char_id:
        roots.append(str(_CHARS_DATASETS / char_id))
        roots.append(str(_CHARS_OUTPUTS / char_id))
    seen: set[str] = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        for sub in ('lora-weights-sdxl', 'lora-weights'):
            cand = os.path.join(
                root,
                sub,
                'checkpoint-200',
                'pytorch_lora_weights.safetensors',
            )
            if os.path.isfile(cand):
                return cand
    return None


def _char_lora_family_roots(char_id: str, dataset_dir: str | None = None) -> list[str]:
    roots: list[str] = []
    for r in (
        dataset_dir,
        str(_CHARS_DATASETS / char_id) if char_id else '',
        str(_CHARS_OUTPUTS / char_id) if char_id else '',
    ):
        if r and r not in roots:
            roots.append(r)
    return roots


def _char_family_lora_dirs(char_id: str, dataset_dir: str | None, family: str) -> list[str]:
    """Existing lora-weights-<family> dirs for this char (backups/hidden excluded)."""
    _f = (family or '').lower()
    fam = _f if _f in ('sdxl', 'qwen') else 'flux'
    out: list[str] = []
    for root in _char_lora_family_roots(char_id, dataset_dir):
        d = os.path.join(root, f'lora-weights-{fam}')
        if os.path.isdir(d):
            out.append(d)
    return out


def _lora_checkpoint_num(name: str) -> int:
    """'checkpoint-1200' → 1200 (newest checkpoint first); unparsable → -1."""
    try:
        return int(str(name).split('-')[-1])
    except Exception:
        return -1


def _discover_char_lora_deep(char_id: str, dataset_dir: str | None, family: str) -> str | None:
    """Last-chance adapter resolution for preview slots (2026-07-31).

    _discover_char_sdxl_lora only ever looked at ``checkpoint-200/…`` — a char whose
    adapter sits at ``lora-weights-<fam>/pytorch_lora_weights.safetensors`` (the normal
    layout: c3345deb5bde is exactly that) resolved to None and the preview quietly fell
    through to an identity-free/img2img render.  Exhaust the honest options first, so
    the fail-closed guards below only fire when there really is nothing to load.
    """
    if not _preview_env_on('ZYG_PREVIEW_LORA_DEEP_DISCOVER'):
        return None
    _f = (family or '').lower()
    fam = _f if _f in ('sdxl', 'qwen', 'klein') else 'flux'
    other = 'flux' if fam == 'sdxl' else 'sdxl'
    for root in _char_lora_family_roots(char_id, dataset_dir):
        subs = [f'lora-weights-{fam}']
        # The un-suffixed legacy dir is ambiguous: only trust it for SDXL (the
        # pre-existing _discover_char_sdxl_lora assumption) or when no sibling
        # dir for the OTHER family exists. qwen postdates the legacy layout and
        # NEVER claims it.
        if fam not in ('qwen', 'klein') and (
            fam == 'sdxl' or not os.path.isdir(os.path.join(root or '', f'lora-weights-{other}'))
        ):
            subs.append('lora-weights')
        for sub in subs:
            base = os.path.join(root or '', sub)
            if not os.path.isdir(base):
                continue
            cand = os.path.join(base, 'pytorch_lora_weights.safetensors')
            if os.path.isfile(cand):
                return cand
            try:
                ckpts = [
                    e
                    for e in os.listdir(base)
                    if e.startswith('checkpoint-')
                    and os.path.isdir(os.path.join(base, e))
                    and '.broken' not in e
                    and 'backup' not in e.lower()
                ]
            except OSError:
                ckpts = []
            for ck in sorted(ckpts, key=_lora_checkpoint_num, reverse=True):
                for fn in ('pytorch_lora_weights.safetensors',):
                    p = os.path.join(base, ck, fn)
                    if os.path.isfile(p):
                        return p
                try:
                    for fn in sorted(os.listdir(os.path.join(base, ck))):
                        if fn.endswith('.safetensors'):
                            return os.path.join(base, ck, fn)
                except OSError as _exc:
                    _zyg_log.debug('checkpoint listing skipped, directory unreadable: %s', _exc)
            try:
                for fn in sorted(os.listdir(base)):
                    if fn.endswith('.safetensors') and not fn.startswith('.'):
                        return os.path.join(base, fn)
            except OSError as _exc:
                _zyg_log.debug('adapter listing skipped, directory unreadable: %s', _exc)
    return None


def _char_family_lora_weights_exist(char_id: str, dataset_dir: str | None, family: str) -> bool:
    """True when trained weights for *family* are physically on disk for this char.

    Used by the 2026-07-31 fail-closed preview guards: 'weights exist but we could not
    attach them' must abort the render, never degrade to a base-model/img2img stranger.
    """
    for d in _char_family_lora_dirs(char_id, dataset_dir, family):
        try:
            for entry in os.listdir(d):
                if entry.startswith('.') or '.broken' in entry or 'backup' in entry.lower():
                    continue
                p = os.path.join(d, entry)
                if os.path.isfile(p) and entry.endswith('.safetensors'):
                    return True
                if os.path.isdir(p) and entry.startswith('checkpoint-'):
                    if any(f.endswith('.safetensors') for f in os.listdir(p)):
                        return True
        except OSError as _exc:
            _zyg_log.debug('family weight scan skipped, directory unreadable: %s', _exc)
    return False


def _char_preview_slot_lora_path(
    cond: dict,
    slot_mf: str,
    char_id: str,
    dataset_dir: str,
) -> str | None:
    if slot_mf == 'sdxl':
        for p in (
            cond.get('sdxl_lora_path'),
            _discover_char_sdxl_lora(char_id, dataset_dir),
            _discover_char_lora_deep(char_id, dataset_dir, 'sdxl'),
        ):
            if p and os.path.isfile(p):
                return p
        return None
    if slot_mf in ('qwen', 'klein'):
        # Companion families read ONLY their own key: no FLUX-era fallback.
        for p in (
            cond.get(f'{slot_mf}_lora_path'),
            _discover_char_lora_deep(char_id, dataset_dir, slot_mf),
        ):
            if p and os.path.isfile(p):
                return p
        return None
    for p in (cond.get('flux_lora_path'), cond.get('lora_path')):
        if not p or not os.path.isfile(p):
            continue
        norm = p.replace('\\', '/').lower()
        if any(t in norm for t in ('lora-weights-sdxl', 'lora-weights-qwen', 'lora-weights-klein')):
            continue
        return p
    _deep_fl = _discover_char_lora_deep(char_id, dataset_dir, 'flux')
    if _deep_fl and os.path.isfile(_deep_fl):
        return _deep_fl
    return None


def _resolve_char_model_family(
    model_family: str | None,
    params: dict | None = None,
    info: dict | None = None,
) -> str:
    """Respect explicit Image Model choice; auto-pick only when unset."""
    for src in (model_family, (params or {}).get('model_family'), (info or {}).get('model_family')):
        mf = (src or '').strip().lower()
        if mf in ('flux', 'sdxl', 'qwen', 'klein'):
            return mf
    try:
        pkg = (info or {}).get('package') or {}
        mf = ((pkg.get('conditioning') or {}).get('model_family') or '').strip().lower()
        if mf in ('flux', 'sdxl', 'qwen', 'klein'):
            return mf
    except Exception as _exc:
        _zyg_log.debug('model family not readable from the package: %s', _exc)
    rs = _char_render_style(params, info)
    if rs == 'animated':
        return 'flux' if _ANIMATED_USE_FLUX else 'sdxl'
    if _char_is_photoreal_style(params, info):
        return _CHAR_DEFAULT_MODEL_FAMILY
    return _CHAR_DEFAULT_MODEL_FAMILY


def _normalize_char_model_family(model_family: str | None, params: dict | None = None, info: dict | None = None) -> str:
    return _resolve_char_model_family(model_family, params, info)


def _char_preview_slot_names(
    model_family: str | None = None, params: dict | None = None, info: dict | None = None
) -> tuple[str, str]:
    """Canonical preview file stems (no extension) for the active model family."""
    mf = _normalize_char_model_family(model_family, params, info)
    char_id = (info or {}).get('char_id') or (params or {}).get('char_id') or ''
    ds = (info or {}).get('dataset_dir') or ''
    if mf == 'flux' and _char_effective_hybrid_preview(params, info, char_id, ds):
        return 'preview_sdxl_front', 'preview_flux_face'
    if mf == 'sdxl':
        return 'preview_sdxl_front', 'preview_sdxl_face'
    return 'preview_flux_front', 'preview_flux_face'


def _char_preview_png_names(
    model_family: str | None = None, params: dict | None = None, info: dict | None = None
) -> tuple[str, str]:
    a, b = _char_preview_slot_names(model_family, params, info)
    return f'{a}.png', f'{b}.png'
