# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Preview provenance sidecars and the legacy preview-alias sync.

Moved verbatim out of the old single-file char_state_service.py (lines 1297-1520).
"""

import json
import os
from datetime import datetime
from zyg_workflows.runtime import (
    _ams_iso,
)
from zyg_workflows.char_state_service._common import (
    _preview_env_on,
    _zyg_log,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _char_effective_hybrid_preview,
    _char_preview_png_names,
    _char_restyle_profile,
    _normalize_char_model_family,
)


def _preview_provenance_path(png_path: str) -> str:
    """<dataset_dir>/<slot>.png → <dataset_dir>/<slot>.meta.json (contract D)."""
    return os.path.splitext(png_path or '')[0] + '.meta.json'


def _preview_restyle_name(model_family: str | None = None, params: dict | None = None, info: dict | None = None) -> str:
    """Restyle profile name that ACTUALLY applied to this render, else ''.

    2026-07-31: mirrors _build_char_preview_slots — the arcane/restyle clause is only
    injected when the whole preview render family is SDXL, so a photoreal FLUX twin
    leg of the same character must report restyle=''.
    """
    try:
        mf = _normalize_char_model_family(model_family, params, info)
        if mf != 'sdxl' or not _char_restyle_profile(params, info):
            return ''
        return str(
            (((info or {}).get('package') or {}).get('style_profile') or {}).get('restyle') or '',
        ).strip()
    except Exception:
        return ''


def _write_preview_provenance(
    png_path: str,
    *,
    slot: str = '',
    model_family: str = '',
    lora_used: bool = False,
    lora_path: str | None = None,
    trigger_token: str = '',
    restyle: str = '',
    backend: str = '',
    rendered_at: str = '',
    extra: dict | None = None,
    log_fn=None,
) -> str | None:
    """Write the contract-D provenance sidecar next to a preview PNG.

    2026-07-31: a preview on disk carried NO marker of how it was made — base-model
    sweep artifact, LoRA-locked render, img2img fallback and Arcane restyle all ended
    up as `preview_flux_front.png`, which is how a cel-shaded adult woman was served
    under "LoRA trained — full character consistency" for a 12-year-old boy.  Every
    preview write now drops <slot>.meta.json beside the PNG; a preview WITHOUT a
    sidecar is "unverified provenance" and must never be labelled LoRA-locked.
    """
    if not png_path or not _preview_env_on('ZYG_PREVIEW_PROVENANCE_SIDECAR'):
        return None
    _log = log_fn or (lambda m: None)
    try:
        _rendered_at = str(rendered_at or '')
        if not _rendered_at:
            try:
                _rendered_at = _ams_iso()
            except Exception:
                _rendered_at = datetime.now().astimezone().isoformat(timespec='seconds')
        payload: dict = dict(extra or {})
        payload.update(
            {
                'slot': str(slot or os.path.splitext(os.path.basename(png_path))[0]),
                'model_family': str(model_family or ''),
                'lora_used': bool(lora_used),
                'lora_path': str(lora_path) if lora_path else None,
                'trigger_token': str(trigger_token or ''),
                'restyle': str(restyle or ''),
                'backend': str(backend or ''),
                'rendered_at': _rendered_at,
            }
        )
        out = _preview_provenance_path(png_path)
        tmp = out + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as _pf:
            json.dump(payload, _pf, indent=2, sort_keys=True, default=str)
        os.replace(tmp, out)
        return out
    except Exception as _pe:
        _log(f'Preview provenance sidecar failed for {os.path.basename(png_path)}: {_pe}')
        return None


def _read_preview_provenance(png_path: str) -> dict | None:
    """Read a preview's provenance sidecar, or None when unverified."""
    try:
        p = _preview_provenance_path(png_path)
        if not p or not os.path.isfile(p):
            return None
        with open(p, encoding='utf-8') as _pf:
            data = json.load(_pf)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _preview_family_from_name(png_name: str) -> str:
    """'preview_sdxl_front.png' → 'sdxl'; 'preview_flux_face.png' → 'flux'; else ''."""
    n = (png_name or '').lower()
    if 'sdxl' in n:
        return 'sdxl'
    if 'flux' in n:
        return 'flux'
    return ''


def _char_sync_preview_legacy_aliases(
    dataset_dir: str, model_family: str | None = None, params: dict | None = None, info: dict | None = None
) -> None:
    """Copy family-specific previews to legacy preview_flux_*.png for older API clients."""
    if not dataset_dir or not os.path.isdir(dataset_dir):
        return
    front, face = _char_preview_png_names(model_family, params, info)
    import shutil as _sh_prev

    mf = _normalize_char_model_family(model_family, params, info)
    legacy_pairs = [(front, 'preview_flux_front.png'), (face, 'preview_flux_face.png')]
    if mf == 'flux' and _char_effective_hybrid_preview(
        params,
        info,
        char_id=(info or {}).get('char_id') or '',
        dataset_dir=dataset_dir,
    ):
        legacy_pairs = [
            ('preview_sdxl_front.png', 'preview_flux_front.png'),
            (face, 'preview_flux_face.png'),
        ]
    # 2026-07-31: the alias copy used to be a silent lie — a painterly Arcane SDXL
    # render (style_profile.restyle) was copied onto preview_flux_front.png and the
    # public UI labelled it "Preview (FLUX)" next to "LoRA trained".  Cross-family
    # aliases are now (a) refused outright for restyled renders, (b) refused when the
    # destination is a VERIFIED genuine FLUX preview, and (c) otherwise stamped with a
    # provenance sidecar recording the TRUE family so consumers can label honestly.
    _honest = _preview_env_on('ZYG_PREVIEW_ALIAS_HONEST')
    _restyle_nm = _preview_restyle_name(model_family, params, info) if _honest else ''
    _trigger = str((info or {}).get('trigger_token') or ((info or {}).get('package') or {}).get('trigger_token') or '')
    for canon_png, legacy_png in legacy_pairs:
        canon_path = os.path.join(dataset_dir, canon_png)
        legacy_path = os.path.join(dataset_dir, legacy_png)
        src_fam = _preview_family_from_name(canon_png) or mf
        dst_fam = _preview_family_from_name(legacy_png) or 'flux'
        cross_family = bool(canon_png != legacy_png and src_fam and dst_fam and src_fam != dst_fam)
        _src_prov = _read_preview_provenance(canon_path) or {}
        _true_fam = str(_src_prov.get('model_family') or src_fam or mf)
        _true_restyle = str(_src_prov.get('restyle') or _restyle_nm or '')

        if _honest and cross_family:
            _dst_prov = _read_preview_provenance(legacy_path) or {}
            _dst_genuine = bool(
                _dst_prov and str(_dst_prov.get('model_family') or '') == dst_fam and not _dst_prov.get('alias_of')
            )
            _block = ''
            if _true_restyle:
                _block = f'restyled render ({_true_restyle}) must not pose as {dst_fam.upper()}'
            elif _dst_genuine:
                _block = f'destination is a genuine {dst_fam.upper()} preview'
            if _block:
                # Do not touch the PNG — but if the stale destination has NO provenance
                # record, stamp it as unverified so nothing downstream can present it
                # as LoRA-locked (contract D: no sidecar ⇒ unverified provenance).
                try:
                    if os.path.isfile(legacy_path) and not _read_preview_provenance(legacy_path):
                        try:
                            _mt = (
                                datetime.fromtimestamp(os.path.getmtime(legacy_path))
                                .astimezone()
                                .isoformat(timespec='seconds')
                            )
                        except Exception:
                            _mt = ''
                        _write_preview_provenance(
                            legacy_path,
                            slot=os.path.splitext(legacy_png)[0],
                            model_family='',
                            lora_used=False,
                            lora_path=None,
                            trigger_token=_trigger,
                            restyle='',
                            backend='unverified_legacy_alias',
                            # rendered_at must describe the FILE, never "now"
                            rendered_at=_mt,
                            extra={
                                'provenance': 'unverified',
                                'rendered_at_source': 'file_mtime' if _mt else 'unknown',
                                'note': (
                                    f'pre-existing file with no provenance record '
                                    f'(alias from {canon_png} refused: {_block})'
                                ),
                            },
                        )
                except Exception as _exc:
                    _zyg_log.warning('legacy preview provenance not written: %s', _exc)
                continue

        _copied = False
        for src_name, dst_name in (
            (canon_png, legacy_png),
            (canon_png.replace('.png', '.txt'), legacy_png.replace('.png', '.txt')),
        ):
            src = os.path.join(dataset_dir, src_name)
            dst = os.path.join(dataset_dir, dst_name)
            try:
                if os.path.isfile(src) and (not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst)):
                    _sh_prev.copy2(src, dst)
                    if src_name.endswith('.png'):
                        _copied = True
            except Exception as _exc:
                _zyg_log.warning('legacy preview alias copy failed: %s', _exc)

        if _copied and canon_png != legacy_png:
            # Alias now carries the TRUE provenance of the image it duplicates.
            _write_preview_provenance(
                legacy_path,
                slot=os.path.splitext(legacy_png)[0],
                model_family=_true_fam,
                lora_used=bool(_src_prov.get('lora_used', False)),
                lora_path=_src_prov.get('lora_path'),
                trigger_token=str(_src_prov.get('trigger_token') or _trigger),
                restyle=_true_restyle,
                backend=str(_src_prov.get('backend') or ''),
                extra={
                    'alias_of': canon_png,
                    'alias_named_family': dst_fam,
                    'provenance': 'alias' if _src_prov else 'alias_unverified_source',
                },
            )
