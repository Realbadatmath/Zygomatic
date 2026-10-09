# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""canon_service.py — the SINGLE SOURCE OF VISUAL TRUTH per character (2026-07-29).

Root cause of the video identity drift: text (bible), photoreal LoRA data, arcane LoRA
data and scene anchors all described DIFFERENT-looking people, and every pipeline stage
listened to a different authority. This module canonizes one appearance per character
per style, derived from the actual LoRA-training pixels (not from free text):

    canon_phrase(char_id)        -> prompt-ready appearance descriptor (drawn from pixels)
    canon_portrait(char_id)      -> path to the canonical arcane portrait cell
    canon_face_crop(char_id)     -> face/bust crop (cached) for re-lock + identity QC
    build_vace_ref(char_id)      -> white-background bust cutout for VACE ref_images
    canon_prompt_binding(char_id)-> 'trigger, descriptor' phrase for video prompts

Stored in the bible under `canon_appearance` (additive key — nothing existing reads it),
seeded here for the Second Ledger leads from direct inspection of their 48-cell sheets.
"""

import json
import os

from PIL import Image
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_CHARS_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

# Seeded from the canon arcane cells (visual truth, NOT the old bible text).
_SEED_CANON = {
    '0015c8a3f2e3': {
        'phrase': (
            'a distinguished 60-year-old Dutch merchant captain with a full white-grey '
            'beard and weathered tanned face, wearing a black wide-brimmed hat, a brown '
            'wool coat with gold embroidery and a crimson sash across the chest'
        ),
        'negative': 'dark beard, brown beard, young man, bareheaded, no hat, plain coat',
        'trigger': 'zygcornelis',
    },
    'c3345deb5bde': {
        'phrase': (
            'a pale slight 13-year-old boy with tousled light-brown hair and soft '
            'boyish features, wearing a plain sober dark-brown doublet with a flat '
            'white linen collar, no lace'
        ),
        'negative': 'young man, adult, handsome, stylish, navy coat, gold buttons, lace jabot',
        'trigger': 'zygabel',
    },
}


def _bible_path(cid):
    return os.path.join(_CHARS_ROOT, cid, 'character_bible.json')


def get_canon(cid):
    """Canon record for a character: bible['canon_appearance'] if present, else seed
    (which is also persisted into the bible on first read)."""
    try:
        with open(_bible_path(cid), encoding='utf-8') as f:
            b = json.load(f)
        rec = b.get('canon_appearance')
        if isinstance(rec, dict) and rec.get('phrase'):
            return rec
    except Exception:
        b = None
    rec = _SEED_CANON.get(cid)
    if rec and b is not None:
        try:
            b['canon_appearance'] = rec
            with open(_bible_path(cid), 'w', encoding='utf-8') as f:
                json.dump(b, f, indent=2, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as _exc:
            _zyg_log.warning('canon appearance not written to the bible: %s', _exc)
    return rec


def set_canon(cid, phrase, negative='', trigger=''):
    try:
        with open(_bible_path(cid), encoding='utf-8') as f:
            b = json.load(f)
        b['canon_appearance'] = {'phrase': phrase, 'negative': negative, 'trigger': trigger}
        with open(_bible_path(cid), 'w', encoding='utf-8') as f:
            json.dump(b, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def canon_phrase(cid):
    rec = get_canon(cid) or {}
    return rec.get('phrase') or ''


def canon_negative(cid):
    rec = get_canon(cid) or {}
    return rec.get('negative') or ''


def canon_prompt_binding(cid):
    """'trigger, canon phrase' — put next to the character in every video prompt so the
    text channel reinforces (not fights) the LoRA + refs."""
    rec = get_canon(cid) or {}
    t = rec.get('trigger') or ''
    p = rec.get('phrase') or ''
    return f'{t}, {p}' if t else p


def canon_portrait(cid):
    """Canonical arcane portrait cell (front-facing cell_00 of the LoRA training set)."""
    for cand in (
        os.path.join(_CHARS_ROOT, cid, 'arcane_instantid', 'cell_00.png'),
        os.path.join(_CHARS_ROOT, cid, 'contact_sheet', 'cells', 'cell_00.png'),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def _cache_dir(cid):
    d = os.path.join(_CHARS_ROOT, cid, '.canon_cache')
    os.makedirs(d, exist_ok=True)
    return d


def canon_face_crop(cid, force=False):
    """Face/bust crop of the canon portrait (top-center region; detector-free and stable)."""
    p = canon_portrait(cid)
    if not p:
        return None
    out = os.path.join(_cache_dir(cid), 'face_crop.png')
    if os.path.isfile(out) and not force:
        return out
    im = Image.open(p).convert('RGB')
    W, H = im.size
    im.crop((int(W * 0.18), 0, int(W * 0.82), int(H * 0.72))).save(out)
    return out


def build_scene_ref(name, scene_path, box_frac, size=512, force=False):
    """White-bg cutout from a SCENE image (e.g. the father WITH his pipe from the anchor).
    Refs link to prompt tokens in VACE — a with-prop cutout pins prop ownership+look.
    box_frac: (fx0, fy0, fx1, fy1)."""
    out = os.path.join(os.path.dirname(scene_path), f'.ref_{name}.png')
    if os.path.isfile(out) and not force:
        return out
    im = Image.open(scene_path).convert('RGB')
    W, H = im.size
    fx0, fy0, fx1, fy1 = box_frac
    crop = im.crop((int(W * fx0), int(H * fy0), int(W * fx1), int(H * fy1)))
    crop.thumbnail((size - 40, size - 40))
    canvas = Image.new('RGB', (size, size), (255, 255, 255))
    canvas.paste(crop, ((size - crop.width) // 2, (size - crop.height) // 2))
    canvas.save(out)
    return out


def build_vace_ref(cid, size=512, force=False):
    """White-background bust cutout for VACE ref_images (per VACE UserGuide: salient
    subject on clean background). Centered pad-to-square."""
    crop = canon_face_crop(cid, force=force)
    if not crop:
        return None
    out = os.path.join(_cache_dir(cid), 'vace_ref.png')
    if os.path.isfile(out) and not force:
        return out
    im = Image.open(crop).convert('RGB')
    im.thumbnail((size - 40, size - 40))
    canvas = Image.new('RGB', (size, size), (255, 255, 255))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    canvas.save(out)
    return out
