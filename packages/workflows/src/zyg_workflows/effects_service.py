# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""effects_service.py — a shared EFFECTS library (presets) with preview windows.

Mirrors wardrobe_service: a growable library of effect presets, each with a cached PREVIEW
(a still for 2D compositing effects, a short clip for 3D particle effects). Effects apply to any
rendered image/clip — 2D via pipeline_effects.apply_effect_2d (identity-safe compositing), 3D via
pipeline_effects.composite_fx_clip (scene-preserving particle overlay). No GPU needed.

Public API:
    load_effects()/get_effect(id)/add_effect/remove_effect
    preview_path(id) / has_preview(id) / generate_effect_preview / ensure_previews
    apply_effect(effect_id, base_image, out_dir) -> path (image or clip)
"""

import os
import json
import shutil
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_EFFECTS_PATH = os.path.join(_HERE, 'data', 'runtime', 'effects_library.json')
_CHARS_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

# 2D = compositing chains (still). 3D = particle overlay (clip). Shared across characters.
_DEFAULT_EFFECTS = [
    {
        'id': 'atmosphere',
        'name': 'Atmosphere',
        'kind': '2d',
        'fx_kinds': ['bloom', 'vignette', 'grain'],
        'description': 'Soft bloom + vignette + film grain — cinematic depth.',
    },
    {
        'id': 'godrays',
        'name': 'God Rays',
        'kind': '2d',
        'fx_kinds': ['godrays', 'warm', 'vignette'],
        'description': 'Volumetric light streaks with a warm grade.',
    },
    {
        'id': 'warm_film',
        'name': 'Warm Film',
        'kind': '2d',
        'fx_kinds': ['warm', 'bloom', 'vignette', 'grain'],
        'description': 'Warm cinematic film look.',
    },
    {
        'id': 'cool_film',
        'name': 'Cool Film',
        'kind': '2d',
        'fx_kinds': ['cool', 'vignette', 'grain'],
        'description': 'Cool, moody film grade.',
    },
    {
        'id': 'embers',
        'name': 'Embers',
        'kind': '3d',
        'particle': 'embers',
        'description': 'Warm glowing embers drifting up — scene preserved.',
    },
    {
        'id': 'snow',
        'name': 'Snow',
        'kind': '3d',
        'particle': 'snow',
        'description': 'Soft snow falling across the scene.',
    },
    {'id': 'rain', 'name': 'Rain', 'kind': '3d', 'particle': 'rain', 'description': 'Rain streaks over the scene.'},
    {
        'id': 'dust',
        'name': 'Dust',
        'kind': '3d',
        'particle': 'dust',
        'description': 'Faint dust motes slowly drifting.',
    },
]


def _log_noop(_m):
    pass


def load_effects():
    try:
        with open(_EFFECTS_PATH, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        items = doc.get('effects') if isinstance(doc, dict) else doc
        if isinstance(items, list) and items:
            return items
    except (FileNotFoundError, ValueError) as _exc:
        _zyg_log.warning('effects config unreadable, rewriting the defaults: %s', _exc)
    save_effects(_DEFAULT_EFFECTS)
    return list(_DEFAULT_EFFECTS)


def save_effects(effects):
    os.makedirs(os.path.dirname(_EFFECTS_PATH), exist_ok=True)
    with open(_EFFECTS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'effects': effects}, f, indent=2)


def get_effect(effect_id):
    for e in load_effects():
        if e.get('id') == effect_id:
            return e
    return None


def add_effect(effect):
    eff = load_effects()
    eid = str(effect.get('id') or '').strip()
    if not eid:
        return False
    save_effects([e for e in eff if e.get('id') != eid] + [effect])
    return True


def remove_effect(effect_id):
    save_effects([e for e in load_effects() if e.get('id') != effect_id])
    return True


def _preview_dir():
    d = os.path.join(_HERE, 'output', 'effects', '_previews')
    os.makedirs(d, exist_ok=True)
    return d


def preview_path(effect_id):
    """2D previews are .png, 3D previews are .mp4."""
    e = get_effect(effect_id)
    ext = 'mp4' if (e and e.get('kind') == '3d') else 'png'
    return os.path.join(_preview_dir(), f'{effect_id}.{ext}')


def has_preview(effect_id):
    return os.path.isfile(preview_path(effect_id))


def _sample_image():
    """A representative scene to demo effects on."""
    for cand in (
        os.path.join(_HERE, 'output', 'environments', 'env_demo_2d', 'scenery.png'),
        os.path.join(_CHARS_ROOT, 'c3345deb5bde', 'arcane_instantid', 'cell_00.png'),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def generate_effect_preview(effect, force=False, log_fn=None):
    """Cache a preview: 2D → still with the effect applied; 3D → a short particle clip."""
    log = log_fn or _log_noop
    eid = effect.get('id') if isinstance(effect, dict) else str(effect)
    e = effect if isinstance(effect, dict) else get_effect(eid)
    if not e:
        return None
    out = preview_path(eid)
    if os.path.isfile(out) and not force:
        return out
    sample = _sample_image()
    if not sample:
        log('[fx] no sample image for previews')
        return None
    try:
        from zyg_workflows import pipeline_effects as FX

        if e.get('kind') == '3d':
            clip = FX.composite_fx_clip(
                sample, _preview_dir(), fx=e.get('particle', 'embers'), seconds=4, fps=20, log_fn=log
            )
            if clip and os.path.isfile(clip):
                shutil.move(clip, out)
                log(f'[fx] preview clip → {eid}')
                return out
        else:
            r = FX.apply_effect_2d(sample, out, fx_kinds=tuple(e.get('fx_kinds', ['bloom'])), log_fn=log)
            if r:
                log(f'[fx] preview → {eid}')
                return out
    except Exception as ex:
        log(f'[fx] preview failed for {eid}: {ex}')
    return None


def ensure_previews(force=False, log_fn=None):
    n = 0
    for e in load_effects():
        if force or not has_preview(e.get('id')):
            if generate_effect_preview(e, force=force, log_fn=log_fn):
                n += 1
    return n


def _char_base_image(char_id):
    d = os.path.join(_CHARS_ROOT, char_id)
    for cand in (
        os.path.join(d, 'arcane_instantid', 'cell_00.png'),
        os.path.join(d, 'contact_sheet', 'cells', 'cell_00.png'),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def apply_effect(effect_id, base_image, out_dir, char_id=None, log_fn=None):
    """Apply an effect preset to a base image (or a character's render). 2D → still, 3D → clip.
    Returns the output path or None."""
    log = log_fn or _log_noop
    e = get_effect(effect_id)
    if not e:
        log(f'[fx] unknown effect "{effect_id}"')
        return None
    base = base_image or (_char_base_image(char_id) if char_id else None) or _sample_image()
    if not (base and os.path.isfile(base)):
        log('[fx] no base image')
        return None
    os.makedirs(out_dir, exist_ok=True)
    from zyg_workflows import pipeline_effects as FX

    if e.get('kind') == '3d':
        return FX.composite_fx_clip(base, out_dir, fx=e.get('particle', 'embers'), log_fn=log)
    out = os.path.join(out_dir, f'{effect_id}.png')
    return FX.apply_effect_2d(base, out, fx_kinds=tuple(e.get('fx_kinds', ['bloom'])), log_fn=log)
