# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
animal_library_service.py
=========================
List and describe trained animal LoRAs for the Animal Library UI.

Cloned from ``creature_library_service.py`` and adapted human/creature -> animal.
Animals are stored *character-bible-shaped* (an ``animal_bible.json`` conditioning
block beside their dataset), NOT creature-manifest-shaped, so the video renderer
consumes them directly. This service therefore scans for ``animal_bible.json``
rather than ``manifest.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from zyg_workflows import paths

# The animal training service owns the shared DATASET_ROOT / OUTPUT_ROOT
# constants (mirroring creature_library_service importing from
# creature_training_service). It may be built in parallel with this module, so
# fall back to the SHARED CONTRACT constants when it is not importable yet.
try:  # pragma: no cover - import wiring
    from zyg_workflows.animal_training_service import DATASET_ROOT, OUTPUT_ROOT  # type: ignore
except Exception:  # pragma: no cover - contract fallback
    DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'animals')
    OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'animals')
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_BIBLE_FILENAME = 'animal_bible.json'

_PREVIEW_CANDIDATES = (
    'preview_front.png',
    'preview_three_quarter.png',
    'preview_closeup.png',
    'ref_00.png',
    'ref_01.png',
)


def lora_output_ready(lora_dir: str) -> bool:
    """True when any LoRA safetensors exist under the animal output folder."""
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
            _zyg_log.debug('lora dir listing skipped: %s', _exc)
    return False


def _find_family_lora_path(animal_id: str, family: str) -> str | None:
    """Resolve the newest LoRA safetensors for one model family.

    Honors the SHARED CONTRACT: family-suffixed dirs only
    (``lora-weights-<family>``). The renderer rejects a flux LoRA on the sdxl
    leg via the path substring ``lora-weights-<family>``, so we never fall back
    to the un-suffixed ``lora-weights`` dir for a specific family.
    """
    family = (family or '').strip().lower()
    if family not in ('flux', 'sdxl'):
        return None
    base = os.path.join(OUTPUT_ROOT, animal_id, f'lora-weights-{family}')
    if not os.path.isdir(base):
        return None
    try:
        for entry in sorted(os.listdir(base), reverse=True):
            path = os.path.join(base, entry)
            if os.path.isfile(path) and entry.endswith('.safetensors'):
                return path
            if os.path.isdir(path) and entry.startswith('checkpoint-'):
                for fn in sorted(os.listdir(path), reverse=True):
                    if fn.endswith('.safetensors'):
                        return os.path.join(path, fn)
    except OSError:
        return None
    return None


def find_flux_lora_path(animal_id: str) -> str | None:
    return _find_family_lora_path(animal_id, 'flux')


def find_sdxl_lora_path(animal_id: str) -> str | None:
    return _find_family_lora_path(animal_id, 'sdxl')


def find_lora_path(animal_id: str) -> str | None:
    """Best available LoRA for the animal (prefers flux, then family-agnostic)."""
    flux = _find_family_lora_path(animal_id, 'flux')
    if flux:
        return flux
    sdxl = _find_family_lora_path(animal_id, 'sdxl')
    if sdxl:
        return sdxl
    lora_dir = os.path.join(OUTPUT_ROOT, animal_id)
    base = os.path.join(lora_dir, 'lora-weights')
    if os.path.isdir(base):
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
            _zyg_log.debug('lora-weights dir listing skipped: %s', _exc)
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


def _load_bible(dataset_dir: str, lora_dir: str) -> dict:
    """Load the animal_bible.json conditioning block.

    Beside the dataset first (canonical location), then the output dir as a
    fallback (mirrors the creature template's manifest lookup order).
    """
    for root in (dataset_dir, lora_dir):
        path = os.path.join(root, _BIBLE_FILENAME)
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('animal bible %s unreadable, treating it as empty: %s', path, _exc)
    return {}


_RUNTIME_DIR = os.path.join(os.path.dirname(__file__), 'data', 'runtime')


def _trained_at(animal_id: str, lora_dir: str) -> str:
    runtime = os.path.join(_RUNTIME_DIR, f'animal_gen_{animal_id}.json')
    try:
        if os.path.isfile(runtime):
            with open(runtime, encoding='utf-8') as fh:
                st = json.load(fh)
            return str(st.get('ended') or st.get('started') or '')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('animal run state unreadable: %s', _exc)
    ts_path = os.path.join(lora_dir, 'training_status.json')
    try:
        if os.path.isfile(ts_path):
            with open(ts_path, encoding='utf-8') as fh:
                ts = json.load(fh)
            return str(ts.get('completed_at') or '')
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('training status unreadable: %s', _exc)
    return ''


def format_library_label(name: str, species: str = '', animal_id: str = '') -> str:
    label = (name or species or '').strip()
    if label and len(label) > 28:
        label = label[:25].rstrip() + '…'
    return label or (animal_id[:8] if animal_id else 'Animal')


def _bible_species(bible: dict) -> str:
    ident = bible.get('identity') if isinstance(bible.get('identity'), dict) else {}
    return str(bible.get('species') or ident.get('species') or '')


def _image_count(dataset_dir: str, bible: dict) -> int:
    stats = bible.get('generation_stats') if isinstance(bible.get('generation_stats'), dict) else {}
    for key in ('total', 'image_count', 'dataset_images'):
        val = stats.get(key)
        if isinstance(val, int) and val > 0:
            return val
    try:
        return len([f for f in os.listdir(dataset_dir) if f.endswith('.png')])
    except OSError:
        return 0


def _entry_for(animal_id: str, *, include_training: bool) -> dict[str, Any] | None:
    dataset_dir = os.path.join(DATASET_ROOT, animal_id)
    lora_dir = os.path.join(OUTPUT_ROOT, animal_id)
    bible_here = os.path.isfile(os.path.join(dataset_dir, _BIBLE_FILENAME))
    if not os.path.isdir(dataset_dir) or not bible_here:
        return None

    bible = _load_bible(dataset_dir, lora_dir)
    flux_lora_path = find_flux_lora_path(animal_id)
    sdxl_lora_path = find_sdxl_lora_path(animal_id)
    lora_ready = bool(flux_lora_path or sdxl_lora_path) or lora_output_ready(lora_dir)
    if not lora_ready and not include_training:
        return None

    trigger = str(bible.get('trigger_token') or '')
    if not trigger:
        trigger = f'ZYG_ANIMAL_{animal_id[:6].upper()}'

    name = str(bible.get('display_name') or '')[:120]
    species = _bible_species(bible)
    preview = find_preview_file(dataset_dir)

    return {
        'animal_id': animal_id,
        'name': name,
        'library_label': format_library_label(name, species, animal_id),
        'species': species,
        'trigger_token': trigger,
        'lora_ready': lora_ready,
        'flux_lora_path': flux_lora_path,
        'sdxl_lora_path': sdxl_lora_path,
        'lora_path': find_lora_path(animal_id) if lora_ready else None,
        'preview_url': f'/api/animal/animal-image/{animal_id}/{preview}' if preview else None,
        'kind': '3d' if sdxl_lora_path else '2d',
        'trained_at': _trained_at(animal_id, lora_dir),
        'image_count': _image_count(dataset_dir, bible),
    }


def list_animals(*, include_training: bool = False) -> list[dict[str, Any]]:
    """Scan DATASET_ROOT for ``*/animal_bible.json`` and return library entries.

    Sorted newest first. ``kind`` is ``'3d'`` when an sdxl LoRA is present,
    otherwise ``'2d'``.
    """
    all_ids: set[str] = set()
    if os.path.isdir(DATASET_ROOT):
        try:
            for d in os.listdir(DATASET_ROOT):
                if d.startswith('.'):
                    continue
                if os.path.isfile(os.path.join(DATASET_ROOT, d, _BIBLE_FILENAME)):
                    all_ids.add(d)
        except OSError as _exc:
            _zyg_log.debug('dataset root listing skipped: %s', _exc)

    animals: list[dict[str, Any]] = []
    for aid in sorted(all_ids):
        entry = _entry_for(aid, include_training=include_training)
        if entry is not None:
            animals.append(entry)

    animals.sort(key=lambda a: a.get('trained_at') or '', reverse=True)
    return animals


def get_animal(animal_id: str) -> dict[str, Any] | None:
    """Return the full ``animal_bible.json`` for one animal, or None.

    The returned dict is augmented with resolved on-disk LoRA paths and a
    ``lora_ready``/``kind`` summary so callers get a live view.
    """
    if not validate_animal_id(animal_id):
        return None
    dataset_dir = os.path.join(DATASET_ROOT, animal_id)
    lora_dir = os.path.join(OUTPUT_ROOT, animal_id)
    if not os.path.isfile(os.path.join(dataset_dir, _BIBLE_FILENAME)):
        return None

    bible = _load_bible(dataset_dir, lora_dir)
    if not bible:
        return None

    flux_lora_path = find_flux_lora_path(animal_id)
    sdxl_lora_path = find_sdxl_lora_path(animal_id)
    preview = find_preview_file(dataset_dir)
    bible['_resolved'] = {
        'flux_lora_path': flux_lora_path,
        'sdxl_lora_path': sdxl_lora_path,
        'lora_path': find_lora_path(animal_id),
        'lora_ready': bool(flux_lora_path or sdxl_lora_path) or lora_output_ready(lora_dir),
        'kind': '3d' if sdxl_lora_path else '2d',
        'preview_url': f'/api/animal/animal-image/{animal_id}/{preview}' if preview else None,
        'trained_at': _trained_at(animal_id, lora_dir),
        'dataset_dir': dataset_dir,
        'output_dir': lora_dir,
    }
    return bible


def _safe_under_root(path: str, root: str) -> bool:
    """True when ``path`` really resolves to a direct child inside ``root``."""
    try:
        real_root = os.path.realpath(root)
        real_path = os.path.realpath(path)
    except OSError:
        return False
    parent = os.path.dirname(real_path)
    return parent == real_root and real_path != real_root


def delete_animal(animal_id: str) -> dict[str, Any]:
    """Remove an animal's dataset and output directories safely.

    Guards against path traversal and only ever deletes direct children of
    DATASET_ROOT / OUTPUT_ROOT whose name matches the animal_id contract.
    Returns a summary of what was removed.
    """
    result: dict[str, Any] = {
        'animal_id': animal_id,
        'deleted': [],
        'errors': [],
        'ok': False,
    }
    if not validate_animal_id(animal_id):
        result['errors'].append('invalid animal_id')
        return result

    for root in (DATASET_ROOT, OUTPUT_ROOT):
        target = os.path.join(root, animal_id)
        if not os.path.isdir(target):
            continue
        if not _safe_under_root(target, root):
            result['errors'].append(f'refused unsafe path: {target}')
            continue
        try:
            shutil.rmtree(target)
            result['deleted'].append(target)
        except OSError as exc:
            result['errors'].append(f'{target}: {exc}')

    result['ok'] = bool(result['deleted']) and not result['errors']
    return result


def validate_animal_id(animal_id: str) -> bool:
    return bool(re.match(r'^[a-f0-9]{12}$', animal_id or ''))


def validate_image_filename(filename: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_]+\.(png|jpg|jpeg)$', filename or ''))
