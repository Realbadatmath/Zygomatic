# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_library_service.py
===========================
List and describe trained creature LoRAs for the Creature Library UI.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from zyg_workflows.creature_training_service import DATASET_ROOT, OUTPUT_ROOT
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_PREVIEW_CANDIDATES = (
    'sheet.png',
    'preview_front.png',
    'preview_three_quarter.png',
    'preview_closeup.png',
    'ref_00.png',
    'ref_01.png',
)


def lora_output_ready(lora_dir: str) -> bool:
    """True when any LoRA safetensors exist under the creature output folder."""
    if not lora_dir or not os.path.isdir(lora_dir):
        return False
    for sub in (
        '',
        'lora-weights',
        'lora-weights-flux',
        'lora-weights-sdxl',
        'lora-weights-klein',
        'lora-weights-qwen',
    ):
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
            _zyg_log.debug('lora checkpoint scan skipped: %s', _exc)
    return False


def find_lora_path(creature_id: str) -> str | None:
    lora_dir = os.path.join(OUTPUT_ROOT, creature_id)
    if not os.path.isdir(lora_dir):
        return None
    for sub in (
        'lora-weights-klein',
        'lora-weights-qwen',
        'lora-weights-flux',
        'lora-weights-sdxl',
        'lora-weights',
        '',
    ):
        base = lora_dir if not sub else os.path.join(lora_dir, sub)
        if not os.path.isdir(base):
            continue
        try:
            for entry in sorted(os.listdir(base), reverse=True):
                path = os.path.join(base, entry)
                if os.path.isfile(path) and entry.endswith('.safetensors'):
                    return path
                if os.path.isdir(path) and entry.startswith('checkpoint-'):
                    for fn in os.listdir(path):
                        if fn.endswith('.safetensors'):
                            return os.path.join(path, fn)
        except OSError as _exc:
            _zyg_log.debug('lora weights listing skipped: %s', _exc)
            continue
    return None


def find_preview_file(dataset_dir: str) -> str | None:
    for pname in _PREVIEW_CANDIDATES:
        if os.path.isfile(os.path.join(dataset_dir, pname)):
            return pname
    try:
        pngs = sorted(f for f in os.listdir(dataset_dir) if f.endswith('.png'))
        return pngs[0] if pngs else None
    except OSError:
        return None


def _load_manifest(dataset_dir: str, lora_dir: str) -> dict:
    for root in (dataset_dir, lora_dir):
        path = os.path.join(root, 'manifest.json')
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    return json.load(fh)
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('creature manifest %s unreadable, continuing without it: %s', path, _exc)
    return {}


_RUNTIME_DIR = os.path.join(os.path.dirname(__file__), 'data', 'runtime')


def _trained_at(creature_id: str, lora_dir: str) -> str:
    runtime = os.path.join(_RUNTIME_DIR, f'creature_gen_{creature_id}.json')
    try:
        if os.path.isfile(runtime):
            with open(runtime, encoding='utf-8') as fh:
                st = json.load(fh)
            return str(st.get('ended') or st.get('started') or '')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('creature runtime state unreadable: %s', _exc)
    ts_path = os.path.join(lora_dir, 'training_status.json')
    try:
        if os.path.isfile(ts_path):
            with open(ts_path, encoding='utf-8') as fh:
                ts = json.load(fh)
            return str(ts.get('completed_at') or '')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('training status unreadable: %s', _exc)
    return ''


def format_library_label(name: str, species: str = '', creature_id: str = '') -> str:
    label = (name or species or '').strip()
    if label and len(label) > 28:
        label = label[:25].rstrip() + '…'
    return label or (creature_id[:8] if creature_id else 'Creature')


def list_creatures(*, include_training: bool = False) -> list[dict[str, Any]]:
    """Return creature library entries sorted newest first."""
    all_ids: set[str] = set()
    for root in (OUTPUT_ROOT, DATASET_ROOT):
        if os.path.isdir(root):
            try:
                all_ids.update(
                    d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and not d.startswith('.')
                )
            except OSError as _exc:
                _zyg_log.debug('creature root listing skipped: %s', _exc)

    creatures: list[dict[str, Any]] = []
    for cid in sorted(all_ids):
        dataset_dir = os.path.join(DATASET_ROOT, cid)
        lora_dir = os.path.join(OUTPUT_ROOT, cid)
        if not os.path.isdir(dataset_dir):
            continue

        meta = _load_manifest(dataset_dir, lora_dir)
        lora_ready = lora_output_ready(lora_dir)
        if not lora_ready and not include_training:
            continue

        trigger = meta.get('trigger_token') or ''
        if not trigger:
            ts_path = os.path.join(lora_dir, 'training_status.json')
            try:
                if os.path.isfile(ts_path):
                    with open(ts_path, encoding='utf-8') as tf:
                        trigger = json.load(tf).get('trigger_token') or ''
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('training status trigger read skipped: %s', _exc)
        if not trigger:
            caps = sorted(f for f in os.listdir(dataset_dir) if f.endswith('.txt'))
            if caps:
                try:
                    trigger = open(os.path.join(dataset_dir, caps[0]), encoding='utf-8').read().split()[0]
                except (OSError, IndexError, UnicodeDecodeError) as _exc:
                    _zyg_log.warning('caption trigger read failed, using a generated trigger: %s', _exc)
        if not trigger:
            trigger = f'ZYG_CREATURE_{cid[:6].upper()}'

        name = str(meta.get('name') or meta.get('description') or '')[:120]
        species = str(meta.get('species') or '')
        profile_key = str(meta.get('profile_key') or '')
        preview = find_preview_file(dataset_dir)
        sheet_ok = os.path.isfile(os.path.join(dataset_dir, 'sheet.png'))
        _sr = meta.get('sheet_report') or {}

        creatures.append(
            {
                'creature_id': cid,
                'name': name,
                'library_label': format_library_label(name, species, cid),
                'species': species,
                'description': str(meta.get('description') or '')[:300],
                # The operator body plan travels WITH the creature (2026-08-26). It is
                # in every training caption, so any consumer building a render prompt
                # from this entry needs it or it asks for a creature the LoRA was
                # never conditioned on — the Pufferball shipped a trigger + a
                # description naming no tail, no arms and no feet, and rendered
                # exactly that. Not truncated: it is a semicolon list of body parts
                # and a mid-part cut is worse than no cut.
                'body_plan': str(meta.get('body_plan') or ''),
                'profile_key': profile_key,
                'trigger_token': trigger,
                'lora_ready': lora_ready,
                'lora_path': find_lora_path(cid) if lora_ready else None,
                'preview_url': f'/api/creature/creature-image/{cid}/{preview}' if preview else None,
                'trained_at': _trained_at(cid, lora_dir),
                'image_count': int(
                    meta.get('total') or len([f for f in os.listdir(dataset_dir) if f.endswith('.png')])
                ),
                'sheet_url': f'/api/creature/creature-image/{cid}/sheet.png' if sheet_ok else None,
                'sheet_pass_rate': _sr.get('pass_rate'),
                'sheet_judged': _sr.get('judged_any'),
                'train_family': meta.get('train_family') or '',
                'manifest_status': meta.get('status') or ('trained' if lora_ready else ''),
                # A creature can also have BUILT geometry registered in the prop-mesh
                # library (2026-08-26). It travels with the entry because the two halves
                # answer different questions and are not interchangeable: the LoRA is a 2D
                # appearance prior, the GLB is the thing that actually rotates. A consumer
                # that asks this list for "the pufferball" and gets only a LoRA path will
                # try to rotate the LoRA — which is exactly the experiment that failed.
                'mesh_asset': (meta.get('mesh_asset') or {}).get('asset_id') or '',
                'mesh_glb': (meta.get('mesh_asset') or {}).get('glb') or '',
                'mesh_ready': bool(meta.get('mesh_asset')),
            }
        )

    creatures.sort(key=lambda c: c.get('trained_at') or '', reverse=True)
    return creatures


def validate_creature_id(creature_id: str) -> bool:
    return bool(re.match(r'^[a-f0-9]{12}$', creature_id or ''))


def validate_image_filename(filename: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_]+\.(png|jpg|jpeg)$', filename or ''))
