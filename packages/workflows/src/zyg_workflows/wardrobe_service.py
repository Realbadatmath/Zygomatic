# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wardrobe_service.py — a SHARED, character-agnostic outfit wardrobe.

One library of preset outfits, applied to ANY trained-LoRA character WITHOUT retraining.
The outfit-change engine is Qwen-Image-Edit (the same infra the contact-sheet per-cell edits
use): the source render enters as conditioning at denoise 1.0, so the instruction changes ONLY
the clothing while face / hair / body / pose / background / art-style are preserved. Works on
photoreal and arcane renders alike (the base render already carries the style).

Public API:
    load_wardrobe()                       -> list of outfit dicts (seeds the JSON on first call)
    get_outfit(outfit_id)                 -> one outfit dict or None
    add_outfit(outfit)/remove_outfit(id)  -> mutate the shared library
    change_outfit(src, outfit, dst, ...)  -> qwen-edit a rendered image into the outfit
    apply_outfit(char_id, outfit_id, ...) -> outfit onto a character (base image or its cell_00)
"""

import os
import json
import copy
import math
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_WARDROBE_PATH = os.path.join(_HERE, 'data', 'runtime', 'wardrobe.json')
_CHARS_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

# Shared preset wardrobe. Each: id, name, prompt_clause (what to change into),
# negative (bleed suppression), coverage (torso/arms/legs — informational, drives future VTON masks).
_DEFAULT_WARDROBE = [
    {
        'id': 'peacoat_navy',
        'name': 'Navy Peacoat',
        'prompt_clause': 'a heavy navy-blue wool double-breasted peacoat with two rows of dark buttons, over a cream linen shirt',
        'negative': '',
        'coverage': 'torso_arms',
    },
    {
        'id': 'merchant_fine',
        'name': 'Fine Merchant Coat',
        'prompt_clause': 'a rich dark-green brocade merchant coat with gold-embroidered trim, a white lace collar and cuffs',
        'negative': '',
        'coverage': 'torso_arms',
    },
    {
        'id': 'peasant_tunic',
        'name': 'Peasant Tunic',
        'prompt_clause': 'a plain undyed linen peasant tunic with a rope belt, roughspun and worn',
        'negative': 'ornate, gold, embroidery',
        'coverage': 'torso_arms',
    },
    {
        'id': 'sailor',
        'name': "Mariner's Outfit",
        'prompt_clause': "a weathered mariner's outfit: a short dark wool jacket, a striped undershirt and a knotted neckerchief",
        'negative': '',
        'coverage': 'torso_arms',
    },
    {
        'id': 'winter_fur',
        'name': 'Fur-Lined Winter Coat',
        'prompt_clause': 'a thick fur-lined winter greatcoat in deep brown, collar turned up against the cold',
        'negative': '',
        'coverage': 'torso_arms',
    },
    {
        'id': 'formal_black',
        'name': 'Formal Black Doublet',
        'prompt_clause': 'a formal black velvet doublet with silver buttons and a crisp white ruff collar',
        'negative': '',
        'coverage': 'torso_arms',
    },
    {
        'id': 'redcoat',
        'name': 'Red Military Coat',
        'prompt_clause': 'a scarlet military-style coat with brass buttons and gold epaulettes, black facings',
        'negative': '',
        'coverage': 'torso_arms',
    },
    {
        'id': 'scholar_robe',
        'name': "Scholar's Robe",
        'prompt_clause': "a long dark scholar's robe with a soft flat cap, ink-stained cuffs",
        'negative': '',
        'coverage': 'full',
    },
]


def _log_noop(_m):
    pass


def load_wardrobe():
    """Return the shared wardrobe list; seed the JSON with defaults on first call."""
    try:
        with open(_WARDROBE_PATH, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        items = doc.get('outfits') if isinstance(doc, dict) else doc
        if isinstance(items, list) and items:
            return items
    except FileNotFoundError as _exc:
        _zyg_log.debug('no wardrobe file yet, seeding %s with the defaults: %s', _WARDROBE_PATH, _exc)
    except ValueError as _exc:
        _zyg_log.warning('wardrobe file %s is corrupt, overwriting it with the defaults: %s', _WARDROBE_PATH, _exc)
    save_wardrobe(_DEFAULT_WARDROBE)
    return list(_DEFAULT_WARDROBE)


def save_wardrobe(outfits):
    os.makedirs(os.path.dirname(_WARDROBE_PATH), exist_ok=True)
    with open(_WARDROBE_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'outfits': outfits}, f, indent=2)


def get_outfit(outfit_id):
    for o in load_wardrobe():
        if o.get('id') == outfit_id:
            return o
    return None


def add_outfit(outfit):
    outfits = load_wardrobe()
    oid = str(outfit.get('id') or '').strip()
    if not oid:
        return False
    outfits = [o for o in outfits if o.get('id') != oid] + [outfit]
    save_wardrobe(outfits)
    return True


def remove_outfit(outfit_id):
    outfits = [o for o in load_wardrobe() if o.get('id') != outfit_id]
    save_wardrobe(outfits)
    return True


def _preview_dir():
    d = os.path.join(_HERE, 'output', 'wardrobe', '_previews')
    os.makedirs(d, exist_ok=True)
    return d


def preview_path(outfit_id):
    return os.path.join(_preview_dir(), f'{outfit_id}.png')


def has_preview(outfit_id):
    return os.path.isfile(preview_path(outfit_id))


def generate_outfit_preview(outfit, force=False, seed=7, log_fn=None):
    """Render a card preview of an outfit on a neutral mannequin (SDXL txt2img, no character).
    Cached to output/wardrobe/_previews/<id>.png. Returns the path or None."""
    log = log_fn or _log_noop
    oid = outfit.get('id') if isinstance(outfit, dict) else str(outfit)
    out = preview_path(oid)
    if os.path.isfile(out) and not force:
        return out
    clause = outfit['prompt_clause'] if isinstance(outfit, dict) else str(outfit)
    try:
        from zyg_workflows import _comfy_client as CC
    except Exception as e:
        log(f'[wardrobe] preview: comfy unavailable ({e})')
        return None
    prompt = (
        f'{clause}, worn on a plain featureless neutral-grey mannequin, full outfit visible, '
        f'studio product photograph, soft even lighting, plain light-grey seamless background, centered'
    )
    neg = 'face, head, person, human, skin, hands, text, watermark, deformed, extra limbs, busy background'
    g = {
        '10': {
            'class_type': 'CheckpointLoaderSimple',
            'inputs': {'ckpt_name': 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'},
        },
        '20': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': prompt}},
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': neg}},
        '30': {'class_type': 'EmptyLatentImage', 'inputs': {'width': 768, 'height': 1024, 'batch_size': 1}},
        '31': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['10', 0],
                'positive': ['20', 0],
                'negative': ['21', 0],
                'latent_image': ['30', 0],
                'seed': seed,
                'steps': 28,
                'cfg': 6.5,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': 1.0,
            },
        },
        '40': {'class_type': 'VAEDecode', 'inputs': {'samples': ['31', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['40', 0], 'filename_prefix': 'ZygOutfitPrev'}},
    }
    try:
        import shutil as _sh

        outs = CC.submit(g, timeout_s=600)
        if outs and os.path.isfile(outs[0]):
            _sh.copy2(outs[0], out)
            log(f'[wardrobe] preview → {oid}')
            return out
    except Exception as e:
        log(f'[wardrobe] preview render failed for {oid}: {e}')
    return None


def ensure_previews(force=False, log_fn=None):
    """Generate any missing outfit previews. Returns count generated."""
    n = 0
    for o in load_wardrobe():
        if force or not has_preview(o.get('id')):
            if generate_outfit_preview(o, force=force, log_fn=log_fn):
                n += 1
    return n


def _char_default_clothing(char_id):
    try:
        from zyg_workflows import character_bible_service as CBS

        p = CBS.load(char_id) or {}
        return (
            (p.get('default_presentation') or {}).get('default_clothing')
            or (p.get('style_profile') or {}).get('default_clothing')
            or ''
        )
    except Exception:
        return ''


def change_outfit(src_path, outfit, dst_path=None, char_id=None, seed=42, log_fn=None, subject='the person'):
    """Qwen-edit a rendered image so the person wears `outfit` — face/hair/body/pose/background/
    art-style preserved. `outfit` is a wardrobe dict (or a plain clause string). Returns True/False.

    subject: which figure the edit targets, e.g. 'the man' / 'the boy' — lets a
    multi-character frame be wardrobe-locked one figure at a time (the default
    'the person' keeps single-figure behaviour byte-identical)."""
    log = log_fn or _log_noop
    dst_path = dst_path or src_path
    if not os.path.isfile(src_path):
        log(f'[wardrobe] source missing: {src_path}')
        return False
    clause = outfit['prompt_clause'] if isinstance(outfit, dict) else str(outfit)
    out_neg = (outfit.get('negative') or '') if isinstance(outfit, dict) else ''

    comfy_root = os.environ.get('ZYG_COMFY_ROOT', str(paths.ZYG_COMFY_ROOT))
    try:
        from zyg_workflows import comfy_generation_service as _cgs

        qwen_unet = _cgs.qwen_edit_unet() or ''
    except Exception:
        qwen_unet = ''
    if not qwen_unet or not os.path.isfile(os.path.join(comfy_root, 'models', 'diffusion_models', qwen_unet)):
        log(f'[wardrobe] qwen unet not found ({qwen_unet or "none"}) — cannot change outfit')
        return False

    instr = (
        f'Change only the clothing {subject} is wearing to {clause}. '
        f'Keep the face, hairstyle, hair color, skin, body, exact pose, background, '
        f'every other person and the art style completely unchanged and identical — '
        f'replace ONLY that outfit. Keep the same framing and lighting.'
    )
    # suppress snap-back to the character's trained/default outfit
    old = _char_default_clothing(char_id) if char_id else ''
    neg = 'nude, naked, deformed, extra limbs, changed face, different person, blurry, watermark, text'
    if old:
        neg = f'{old}, {neg}'
    if out_neg:
        neg = f'{out_neg}, {neg}'

    try:
        from PIL import Image

        with Image.open(src_path) as im:
            ow, oh = im.size
    except Exception as e:
        log(f'[wardrobe] cannot read {src_path} ({e})')
        return False
    w, h = ow, oh
    budget = 1.0 * 1024 * 1024
    if w * h > budget:
        s = math.sqrt(budget / float(w * h))
        w, h = int(w * s), int(h * s)
    try:
        from zyg_workflows import _comfy_client as _comfy

        g = copy.deepcopy(_comfy.load_workflow('qwen_edit_angle'))
        src_name = _comfy.stage_input_image(src_path)
    except Exception as e:
        log(f'[wardrobe] stage/load failed ({e})')
        return False
    g['10']['inputs']['unet_name'] = qwen_unet
    g['14']['inputs']['strength_model'] = 0.0  # no angle LoRA — pure edit
    g['15']['inputs']['image'] = src_name
    g['20']['inputs']['prompt'] = instr
    g['21']['inputs']['prompt'] = neg
    g['30']['inputs']['width'] = max(256, (w // 16) * 16)
    g['30']['inputs']['height'] = max(256, (h // 16) * 16)
    g['31']['inputs'].update({'seed': int(seed), 'steps': 32, 'cfg': 3.0, 'denoise': 1.0})
    g['50']['inputs']['filename_prefix'] = 'ZygWardrobe'
    try:
        outs = _comfy.submit(g, timeout_s=600)
    except Exception as e:
        log(f'[wardrobe] qwen submit failed ({e})')
        return False
    if not (outs and os.path.isfile(outs[0])):
        log('[wardrobe] qwen produced no output')
        return False
    try:
        from PIL import Image as _I

        res = _I.open(outs[0]).convert('RGB')
        if res.size != (ow, oh):
            res = res.resize((ow, oh), _I.LANCZOS)
        res.save(dst_path)
    except Exception as e:
        log(f'[wardrobe] save failed ({e})')
        return False
    log(f'[wardrobe] outfit applied → {os.path.basename(dst_path)}')
    return True


def _char_base_image(char_id):
    """A sensible default base render for a character (its front arcane cell, else a cell)."""
    d = os.path.join(_CHARS_ROOT, char_id)
    for cand in (
        os.path.join(d, 'arcane_instantid', 'cell_00.png'),
        os.path.join(d, 'contact_sheet', 'cells', 'cell_00.png'),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def apply_outfit(char_id, outfit_id, out_path, base_image=None, seed=42, log_fn=None):
    """Apply a wardrobe outfit to a character. Uses `base_image` if given, else the character's
    front render. Returns out_path or None."""
    log = log_fn or _log_noop
    outfit = get_outfit(outfit_id)
    if not outfit:
        log(f'[wardrobe] unknown outfit "{outfit_id}"')
        return None
    base = base_image or _char_base_image(char_id)
    if not (base and os.path.isfile(base)):
        log(f'[wardrobe] no base image for {char_id}')
        return None
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if change_outfit(base, outfit, out_path, char_id=char_id, seed=seed, log_fn=log):
        return out_path
    return None
