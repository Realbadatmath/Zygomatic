# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.asset_library_service.assets — verbatim from asset_library_service.py lines 621-834.

the asset records themselves (load/save/get/add/remove) and the card
previews (preview_path / has_preview / generate_preview / ensure_previews)
"""

import json
import os
import logging as _zyg_logging
from zyg_workflows.asset_library_service import catalog as _zyg_catalog
from zyg_workflows.asset_library_service import audio_meta as _zyg_audio_meta

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file asset_library_service.py.
_AUDIO_EXTS = _zyg_catalog._AUDIO_EXTS
_CATEGORIES = _zyg_catalog._CATEGORIES
_DEFAULTS = _zyg_catalog._DEFAULTS
_HERE = _zyg_catalog._HERE
_audio_dir = _zyg_catalog._audio_dir
_lib_path = _zyg_catalog._lib_path
_log_noop = _zyg_catalog._log_noop
_load_audio_meta = _zyg_audio_meta._load_audio_meta
set_audio_meta = _zyg_audio_meta.set_audio_meta

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.asset_library_service')


def load_assets(cat):
    info = _CATEGORIES.get(cat)
    if not info:
        return []
    if info['kind'] == 'audio':
        # file-backed: every audio file in the category dir is a record. The id is the FULL
        # filename (not the stem) so boom.wav and boom.mp3 stay distinct records.
        d = _audio_dir(cat)
        out = []
        meta_all = _load_audio_meta(cat)
        try:
            for fn in sorted(os.listdir(d)):
                ext = os.path.splitext(fn)[1].lower()
                if ext not in _AUDIO_EXTS:
                    continue
                stem = os.path.splitext(fn)[0]
                try:
                    sz = os.path.getsize(os.path.join(d, fn))
                except OSError:
                    sz = 0
                rec = {
                    'id': fn,
                    'name': stem.replace('_', ' ').title(),
                    'file': fn,
                    'size': sz,
                    'anchor': 'audio',
                    'prompt_clause': '',
                }
                m = meta_all.get(fn)
                if isinstance(m, dict):
                    for k, v in m.items():
                        if k not in ('id', 'file', 'size'):
                            rec[k] = v
                out.append(rec)
        except OSError as _exc:
            _zyg_log.warning('audio asset listing incomplete, directory unreadable: %s', _exc)
        return out
    try:
        with open(_lib_path(cat), 'r', encoding='utf-8') as f:
            doc = json.load(f)
        items = doc.get('assets') if isinstance(doc, dict) else doc
        if isinstance(items, list):
            # an existing file wins even when EMPTY — otherwise deleting the last asset
            # would silently resurrect the whole default library on the next load
            return items
    except (FileNotFoundError, ValueError) as _exc:
        _zyg_log.warning('asset library unreadable, falling back to the seeded defaults: %s', _exc)
    seeded = list(_DEFAULTS.get(cat) or [])
    if seeded:
        save_assets(cat, seeded)
    return seeded


def save_assets(cat, assets):
    os.makedirs(os.path.dirname(_lib_path(cat)), exist_ok=True)
    with open(_lib_path(cat), 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'category': cat, 'assets': assets}, f, indent=2)


def get_asset(cat, asset_id):
    for a in load_assets(cat):
        if a.get('id') == asset_id:
            return a
    return None


def add_asset(cat, rec):
    info = _CATEGORIES.get(cat)
    if not info or info['kind'] == 'audio':
        return False
    aid = str(rec.get('id') or '').strip()
    if not aid:
        return False
    save_assets(cat, [a for a in load_assets(cat) if a.get('id') != aid] + [rec])
    return True


def remove_asset(cat, asset_id):
    info = _CATEGORIES.get(cat)
    if not info:
        return False
    if info['kind'] == 'audio':
        a = get_asset(cat, asset_id)
        if not a:
            return False
        fn = a.get('file') or ''
        if os.path.basename(fn) != fn:
            return False
        fp = os.path.join(_audio_dir(cat), fn)
        trash = os.path.join(_audio_dir(cat), '.deleted')
        try:
            os.makedirs(trash, exist_ok=True)
            os.rename(fp, os.path.join(trash, fn))
        except OSError:
            return False
        # Tombstone the sidecar entry: license history survives, but
        # ambience_ingest._violation_reasons treats 'deleted' as a violation,
        # so stale meta can never wave the (gone) file through license_gate.
        # Best-effort — the gate's file-existence check is the backstop.
        import time

        set_audio_meta(cat, fn, {'deleted': time.time()})
        return True
    before = load_assets(cat)
    after = [a for a in before if a.get('id') != asset_id]
    if len(after) == len(before):
        return False  # nothing matched — report honestly instead of a blind True
    save_assets(cat, after)
    return True


def _preview_dir(cat):
    d = os.path.join(_HERE, 'output', f'assetlib_{cat}', '_previews')
    os.makedirs(d, exist_ok=True)
    return d


def preview_path(cat, asset_id):
    info = _CATEGORIES.get(cat) or {}
    if info.get('kind') == 'audio':
        a = get_asset(cat, asset_id)
        return os.path.join(_audio_dir(cat), a['file']) if a and a.get('file') else ''
    return os.path.join(_preview_dir(cat), f'{asset_id}.png')


def has_preview(cat, asset_id):
    p = preview_path(cat, asset_id)
    return bool(p) and os.path.isfile(p)


def generate_preview(cat, asset, force=False, seed=7, log_fn=None):
    """Render a card preview (SDXL txt2img): objects as clean product shots, scenes as
    landscape plates. Audio categories need no generation (the file is the preview)."""
    log = log_fn or _log_noop
    info = _CATEGORIES.get(cat)
    if not info or info['kind'] == 'audio':
        return None
    rec = asset if isinstance(asset, dict) else get_asset(cat, str(asset))
    if not rec:
        return None
    aid = rec.get('id')
    out = preview_path(cat, aid)
    if os.path.isfile(out) and not force:
        return out
    try:
        from zyg_workflows import _comfy_client as CC
    except Exception as e:
        log(f'[assetlib] preview: comfy unavailable ({e})')
        return None
    clause = rec.get('prompt_clause') or rec.get('name') or aid
    if info.get('preview_shape') == 'scene':
        prompt = f'{clause}, cinematic wide landscape shot, natural light, highly detailed, photorealistic, no people'
        neg = 'person, human, face, hands, text, watermark, frame, border, lowres'
        W, H = 1024, 576
    else:
        prompt = (
            f'a single {clause}, centered museum product photograph on a plain light-grey '
            f'seamless background, soft even studio lighting, sharp focus, highly detailed'
        )
        neg = 'person, human, face, hands, multiple objects, clutter, text, watermark, lowres'
        W, H = 768, 768
    g = {
        '10': {
            'class_type': 'CheckpointLoaderSimple',
            'inputs': {'ckpt_name': 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'},
        },
        '20': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': prompt}},
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': neg}},
        '30': {'class_type': 'EmptyLatentImage', 'inputs': {'width': W, 'height': H, 'batch_size': 1}},
        '31': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['10', 0],
                'positive': ['20', 0],
                'negative': ['21', 0],
                'latent_image': ['30', 0],
                'seed': seed,
                'steps': 26,
                'cfg': 6.5,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': 1.0,
            },
        },
        '40': {'class_type': 'VAEDecode', 'inputs': {'samples': ['31', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['40', 0], 'filename_prefix': f'ZygAsset_{cat}'}},
    }
    try:
        import shutil as _sh

        outs = CC.submit(g, timeout_s=600)
        if outs and os.path.isfile(outs[0]):
            _sh.copy2(outs[0], out)
            log(f'[assetlib] preview → {cat}/{aid}')
            return out
    except Exception as e:
        log(f'[assetlib] preview failed {cat}/{aid}: {e}')
    return None


def ensure_previews(cat=None, force=False, log_fn=None):
    n = 0
    cats = [cat] if cat else [c for c, i in _CATEGORIES.items() if i['kind'] == 'visual']
    for c in cats:
        info = _CATEGORIES.get(c)
        if not info or info['kind'] != 'visual':
            continue
        for a in load_assets(c):
            if force or not has_preview(c, a.get('id')):
                if generate_preview(c, a, force=force, log_fn=log_fn):
                    n += 1
    return n
