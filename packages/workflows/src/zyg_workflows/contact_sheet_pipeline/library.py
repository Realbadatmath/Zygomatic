# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Library/preview surface for the dashboard.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 4914-5241).
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from zyg_workflows import paths
from zyg_workflows.contact_sheet_pipeline.constants import (
    LIBRARY_GATE_DECLINED,
    LIBRARY_STRICT_CHAR_IDS,
    MULTI_PART_SHEET_COUNTS,
    PREVIEW_PROVENANCE_PREFERRED,
    _AMS,
    _DATASET_ROOT,
    _MASTER_SHEET_PART_SCAN,
    _OUTPUT_ROOT,
    _zyg_log,
    is_servable_char_id,
)
from zyg_workflows.contact_sheet_pipeline.layout import (
    _stem_index,
    load_manifest,
    manifest_path,
    master_sheet_path,
    master_sheet_path_part,
    trigger_token_for,
)


def derive_pipeline_stage(job: dict) -> str:
    return (job.get('stage') or 'sheet_generate').strip()


def is_contact_sheet_char(char_id: str, meta: dict | None = None) -> bool:
    meta = meta or {}
    if meta.get('source') == 'contact_sheet' or meta.get('render_mode') == 'contact_sheet':
        return True
    if os.path.isfile(manifest_path(char_id)):
        return True
    return False


def contact_sheet_image_api_path(char_id: str) -> str:
    return f'/api/storyteller/contact-sheet/image/{char_id}'


def any_master_sheet_path(char_id: str) -> str | None:
    """Path to SOME master contact sheet for *char_id*, or None (2026-07-31).

    Deterministic order:
      1. the monolithic ``contact_sheet_master.png``
      2. else the first multi-part ``contact_sheet_master_<x>.png`` in
         alphabetical part order (a, b, c, … — see _MASTER_SHEET_PART_SCAN)
      3. else None

    The 48-angle pipeline stitches per-part masters and only composites the
    monolithic sheet at the end, so an interrupted/declined run leaves parts
    with no monolith (731946728aa3, 9dcefc018582 on disk today). Callers that
    only knew about the monolith concluded such a character had no contact
    sheet at all.
    """
    try:
        mono = master_sheet_path(char_id)
        if os.path.isfile(mono):
            return mono
        if not MULTI_PART_SHEET_COUNTS:
            return None
        for _part in _MASTER_SHEET_PART_SCAN:
            _p = master_sheet_path_part(char_id, _part)
            if os.path.isfile(_p):
                return _p
    except Exception:
        return None
    return None


def master_sheet_exists(char_id: str) -> bool:
    """True when the character has ANY master contact sheet on disk.

    2026-07-31: was ``os.path.isfile(master_sheet_path(char_id))`` — monolithic
    only. Signature unchanged; multi-part sheets now satisfy it too.
    """
    return any_master_sheet_path(char_id) is not None


def preview_meta_sidecar_path(dataset_dir: str, preview_name: str) -> str:
    """Sibling provenance sidecar for a preview PNG (contract D, 2026-07-31).

    ``preview_flux_front.png`` → ``<dataset_dir>/preview_flux_front.meta.json``.
    """
    stem = preview_name or ''
    if stem.lower().endswith('.png'):
        stem = stem[:-4]
    return os.path.join(dataset_dir or '', f'{stem}.meta.json')


def preview_provenance_ok(dataset_dir: str, preview_name: str) -> bool:
    """True when a preview PNG carries its ``<slot>.meta.json`` sidecar.

    2026-07-31: the legitimate preview renderer writes the sidecar. A preview
    WITHOUT one has unverified provenance — it may be debris from the
    destructive preview sweep that overwrote real portraits with a generic
    non-LoRA render — so it must never outrank a sidecar-backed file.
    """
    try:
        return os.path.isfile(preview_meta_sidecar_path(dataset_dir, preview_name))
    except Exception:
        return False


# Preview filenames, best first. 2026-07-31: kept as a module constant so the
# ranking is one list instead of three drifting copies.
_LIBRARY_PREVIEW_NAMES = (
    'preview_flux_front.png',
    'preview_flux_face.png',
    'preview_sdxl_front.png',
    'preview_sdxl_face.png',
    'preview_sdxl_animated.png',
    'face_00_000deg.png',
    'portrait_00_000deg.png',
)


def _contact_sheet_tile_previews(dataset_dir: str) -> list[str]:
    """``contactsheet_NN.png`` tiles sitting directly in the dataset dir.

    2026-07-31: the old list hard-coded only _00 and _01, so a character whose
    first two tiles were QC-excluded looked tile-less. Enumerate instead.
    """
    try:
        return sorted(
            (f for f in os.listdir(dataset_dir) if f.startswith('contactsheet_') and f.lower().endswith('.png')),
            key=_stem_index,
        )
    except OSError:
        return []


def preview_file_for_library(char_id: str, dataset_dir: str, meta: dict | None = None) -> str | None:
    """Best preview filename under dataset_dir (not subpaths).

    Returns None when the character has ANY contact sheet — a contact sheet
    always outranks a preview_*.png, and the caller serves the sheet route
    instead (2026-07-31).
    """
    if master_sheet_exists(char_id):
        return None
    meta = meta or {}
    if is_contact_sheet_char(char_id, meta):
        tiles = _contact_sheet_tile_previews(dataset_dir)
        if tiles:
            return tiles[0]
    # 2026-07-31 (contract D): two passes — sidecar-backed previews first,
    # unverified ones only as a last resort.
    passes = (True, False) if PREVIEW_PROVENANCE_PREFERRED else (False,)
    for require_sidecar in passes:
        for pname in _LIBRARY_PREVIEW_NAMES:
            if not os.path.isfile(os.path.join(dataset_dir, pname)):
                continue
            if require_sidecar and not preview_provenance_ok(dataset_dir, pname):
                continue
            return pname
    try:
        pngs = sorted(f for f in os.listdir(dataset_dir) if f.endswith('.png'))
        return pngs[0] if pngs else None
    except OSError:
        return None


def library_preview_urls(char_id: str, dataset_dir: str, meta: dict | None = None) -> dict:
    """preview_url + contact_sheet_url for library cards.

    2026-07-31: keyed off any_master_sheet_path, so a parts-only character gets
    a contact-sheet URL instead of preview_url=None. preview_url=None on a
    character that HAS a sheet is what the public wizard read as "needs a
    preview" before firing the destructive GPU sweep.
    """
    out: dict[str, str | None] = {
        'preview_url': None,
        'contact_sheet_url': None,
    }
    if any_master_sheet_path(char_id) is not None:
        out['contact_sheet_url'] = contact_sheet_image_api_path(char_id)
        out['preview_url'] = out['contact_sheet_url']
        return out
    pf = preview_file_for_library(char_id, dataset_dir, meta)
    if pf:
        out['preview_url'] = f'/api/storyteller/char-image/{char_id}/{pf}'
    return out


def _read_meta(dataset_dir: str, lora_dir: str) -> dict:
    for mdir in (dataset_dir, lora_dir):
        mp = os.path.join(mdir, 'manifest.json')
        if os.path.isfile(mp):
            try:
                with open(mp, encoding='utf-8') as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError) as _exc:
                _zyg_log.warning('manifest %s unreadable, falling back to the next location: %s', mp, _exc)
    return {}


def _job_from_runtime(char_id: str, runtime_dir: str) -> dict | None:
    path = os.path.join(runtime_dir, f'contact_sheet_{char_id}.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def list_contact_sheet_library(
    *,
    model_family: str = '',
    runtime_dir: str | None = None,
    include_trained: bool = True,
) -> list[dict]:
    """
    All contact-sheet characters: in-progress jobs and completed LoRA entries.
    """
    from zyg_workflows import character_lora_family as _clf

    mf = (model_family or '').strip().lower()
    runtime_dir = runtime_dir or str(paths.DATA_DIR / 'runtime')
    seen: set[str] = set()
    entries: list[dict] = []

    def _add_entry(char_id: str, job: dict | None = None) -> None:
        if not char_id or char_id in seen:
            return
        # 2026-07-31: both image routes gate on ^[a-f0-9]{12}$, so a slug id
        # (abel_van_haren) can only ever yield a row with unservable images.
        if LIBRARY_STRICT_CHAR_IDS and not is_servable_char_id(char_id):
            return
        seen.add(char_id)
        dataset_dir = os.path.join(_DATASET_ROOT, char_id)
        lora_dir = os.path.join(_OUTPUT_ROOT, char_id)
        if not os.path.isdir(dataset_dir) and not job:
            return
        meta = _read_meta(dataset_dir, lora_dir)
        if not is_contact_sheet_char(char_id, meta) and not (
            job and job.get('pipeline') == 'multi_angle_contact_sheet'
        ):
            return
        job = job or _job_from_runtime(char_id, runtime_dir) or {}
        params = job.get('params') or {}
        name = params.get('name') or meta.get('name') or char_id[:8]
        lora_families = _clf.char_lora_families_for_dir(lora_dir) if os.path.isdir(lora_dir) else []
        lora_on_disk = bool(lora_families) or (
            include_trained and _clf.char_lora_ready_for_family(lora_dir, mf) if mf else bool(lora_families)
        )
        # 2026-07-31: a declined review or a failed QC safety valve means the
        # run never produced an accepted character — safetensors on disk alone
        # used to be reported as 'lora_ready', so the UI and downstream
        # readiness checks presented c3345deb5bde (status 'declined', stage
        # 'review_declined', qc_safety_valve.verdict 'fail') as fully trained.
        _valve = job.get('qc_safety_valve') if isinstance(job.get('qc_safety_valve'), dict) else {}
        qc_verdict = str((_valve or {}).get('verdict') or '').strip().lower()
        review_declined = bool(
            job.get('review_declined')
            or (job.get('stage') or '') == 'review_declined'
            or (job.get('status') or '') == 'declined'
        )
        qc_failed = qc_verdict == 'fail'
        training_blocked = bool(review_declined or qc_failed)
        lora_ready = lora_on_disk and not (LIBRARY_GATE_DECLINED and training_blocked)
        if mf and lora_families and mf not in lora_families:
            if job.get('status') != 'running':
                return
        previews = library_preview_urls(char_id, dataset_dir, meta)
        cs_manifest = load_manifest(char_id) or {}
        created = job.get('started') or cs_manifest.get('approved_at') or cs_manifest.get('updated_at') or ''
        if not created:
            # No job/manifest timestamp (very old chars) — fall back to disk mtime.
            # 2026-07-31: any_master_sheet_path so parts-only chars date from
            # their sheet rather than the dataset dir.
            for probe in (any_master_sheet_path(char_id) or master_sheet_path(char_id), dataset_dir):
                try:
                    created = datetime.fromtimestamp(
                        os.path.getmtime(probe),
                        _AMS,
                    ).isoformat(timespec='milliseconds')
                    break
                except OSError as _exc:
                    _zyg_log.debug('mtime probe on %s failed: %s', probe, _exc)
                    continue
        entries.append(
            {
                'char_id': char_id,
                'name': name,
                'created_at': created,
                'library_label': name.split()[0] + ' ' + (name.split()[-1][:1] if len(name.split()) > 1 else ''),
                'status': job.get('status') or ('done' if lora_ready else 'unknown'),
                'stage': job.get('stage') or ('done' if lora_ready else ''),
                'model_family': job.get('model_family') or meta.get('model_family') or 'flux',
                'lora_families': lora_families,
                'lora_ready': lora_ready,
                # 2026-07-31: raw on-disk fact, unfiltered by the decline gate —
                # callers that genuinely want "are there safetensors" use this.
                'lora_on_disk': lora_on_disk,
                'review_declined': review_declined,
                'qc_verdict': qc_verdict,
                'qc_failed': qc_failed,
                'training_blocked': training_blocked,
                'approved': bool(job.get('approved') or cs_manifest.get('approved')),
                'source': 'contact_sheet',
                'render_mode': 'contact_sheet',
                'creation_pipeline': 'multi_angle_contact_sheet',
                'trigger_token': job.get('trigger_token') or meta.get('trigger_token') or trigger_token_for(char_id),
                'tile_count': job.get('tile_count') or len(cs_manifest.get('tiles') or []),
                'preview_url': previews.get('preview_url'),
                'contact_sheet_url': previews.get('contact_sheet_url'),
                'awaiting_approval': (job.get('stage') == 'awaiting_approval'),
            }
        )

    if os.path.isdir(runtime_dir):
        import glob as _glob

        for path in _glob.glob(os.path.join(runtime_dir, 'contact_sheet_*.json')):
            try:
                with open(path, encoding='utf-8') as fh:
                    job = json.load(fh)
                cid = (job.get('char_id') or '').strip()
                if job.get('pipeline') == 'multi_angle_contact_sheet' or cid:
                    _add_entry(cid, job)
            except Exception as _exc:
                _zyg_log.warning('runtime job file %s skipped: %s', path, _exc)
                continue

    if os.path.isdir(_DATASET_ROOT):
        for cid in os.listdir(_DATASET_ROOT):
            if cid.startswith('.'):
                continue
            # 2026-07-31: skip slug dirs before touching disk (see _add_entry),
            # and discover parts-only characters via master_sheet_exists.
            if LIBRARY_STRICT_CHAR_IDS and not is_servable_char_id(cid):
                continue
            mp = manifest_path(cid)
            if os.path.isfile(mp) or master_sheet_exists(cid):
                _add_entry(cid)

    # Running first, then newest → oldest (ISO timestamps sort lexicographically).
    entries.sort(
        key=lambda e: (1 if e.get('status') == 'running' else 0, e.get('created_at') or ''),
        reverse=True,
    )
    return entries
