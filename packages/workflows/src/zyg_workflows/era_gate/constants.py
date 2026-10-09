# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""era_gate.constants — the original import block, period buckets, the
positive period vocabulary, the universal tells and the per-kind question
templates (verbatim from era_gate.py lines 53-307).
"""

# ruff: noqa: F401  era_gate.py's original top import block is kept here verbatim;
# the names it binds are re-exported by __init__ so era_gate.json / era_gate.os
# still resolve for importers that used them off the module.
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from typing import Callable
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.era_gate')


_DIR = str(paths.PKG_DIR)

# ── period buckets ───────────────────────────────────────────────────────────
# Coarse enough to be right, fine enough that "wooden sailing cog" is not
# offered for Republican Rome.
BUCKETS = ('antiquity', 'medieval', 'early_modern', 'nineteenth', 'unknown')


def period_bucket(era: dict | None) -> str:
    """Map an era-lock dict to one of BUCKETS from its end (or start) year."""
    era = era or {}
    yr = era.get('period_end')
    if yr is None:
        yr = era.get('period_start')
    if yr is None:
        lbl = str(era.get('period_label') or '').lower()
        m = re.search(r'(\d{1,4})\s*(bc|bce)\b', lbl)
        if m:
            return 'antiquity'
        m = re.findall(r'\b(1[0-9]{3})\b', lbl)
        if m:
            yr = int(m[-1])
        elif re.search(r'\b(ancient|roman|rome|greek|greece|antiquity|pharaoh|egypt|byzantine)\b', lbl):
            return 'antiquity'
        elif re.search(r'\b(medieval|middle ages|crusade|viking|norman)\b', lbl):
            return 'medieval'
        else:
            return 'unknown'
    try:
        yr = int(yr)
    except Exception:
        return 'unknown'
    if yr <= 500:
        return 'antiquity'
    if yr <= 1500:
        return 'medieval'
    if yr <= 1800:
        return 'early_modern'
    return 'nineteenth'


# Positive-phrased period vocabulary per bucket. Used by the retry ladder as
# the "fix" for a universal flag, and by the offline check derivation.
PERIOD_VOCAB = {
    'antiquity': {
        'boat': 'a wooden oared galley or square-sailed merchant ship, no engine, wheelhouse or glass',
        'clothing': 'wool and linen tunics, cloaks pinned at the shoulder, no buttons or zips',
        'footwear': 'leather sandals or bare feet',
        'hair': 'short cropped hair or a simple head-cloth, women with hair bound up',
        'lighting': 'lit only by daylight, oil lamps, torches or braziers',
        'window': 'small unglazed window openings with wooden shutters',
        'map': 'a hand-inked papyrus or parchment chart with faded outlines only',
        'cart': 'a wooden cart with solid wooden wheels drawn by oxen',
        'street': 'a paved stone road or packed earth, no markings',
    },
    'medieval': {
        'boat': 'a single-masted wooden sailing cog with a square sail, no engine, wheelhouse or glass',
        'clothing': 'ankle-length wool kirtles and tunics, linen chemises, cloaks, no buttons in rows, no zips',
        'footwear': 'leather turnshoes or bare feet',
        'hair': 'hair under a linen coif or wool hood, men bowl-cut or shoulder-length, women veiled, clergy tonsured',
        'lighting': 'lit only by daylight, tallow candles, rushlights or torch flame',
        'window': 'small window openings with plank shutters, no glass',
        'map': 'a hand-drawn parchment map with faded ink outlines and no symbols',
        'cart': 'a wooden cart with iron-rimmed wooden wheels drawn by oxen or a horse',
        'street': 'a rutted earth lane or rough cobbles, no markings',
    },
    'early_modern': {
        'boat': 'a wooden sailing ship with canvas sails and hemp rigging, no engine or wheelhouse',
        'clothing': 'wool doublets and breeches, linen shirts, long coats, bodices and petticoats, no zips',
        'footwear': 'leather shoes with buckles or riding boots',
        'hair': 'hair under linen caps and felt hats, men long-haired or in period wigs',
        'lighting': 'lit only by daylight, candles, oil lamps or firelight',
        'window': 'small leaded window panes in timber frames',
        'map': 'a hand-drawn or copperplate-engraved chart on paper, faded ink only',
        'cart': 'a wooden cart or coach with iron-rimmed wooden wheels',
        'street': 'cobbles or packed earth, no markings',
    },
    'nineteenth': {
        'boat': 'a wooden sailing vessel or early paddle steamer, no modern wheelhouse or glass cabin',
        'clothing': 'wool frock coats, waistcoats, high collars, long dresses with bonnets, no zips',
        'footwear': 'leather lace-up boots',
        'hair': 'period hairstyles, men side-parted with whiskers, women with hair pinned up under bonnets',
        'lighting': 'lit only by daylight, candles, oil lamps or gas lamps',
        'window': 'sash windows with small panes in wooden frames',
        'map': 'an engraved paper map with hand-coloured borders, faded ink only',
        'cart': 'a horse-drawn cart or carriage with iron-rimmed wooden wheels',
        'street': 'cobbles or macadam, no markings',
    },
    'unknown': {
        'boat': 'a wooden sailing vessel of the period, no engine, wheelhouse or glass',
        'clothing': 'hand-sewn period garments of wool and linen, no buttons in rows, no zips',
        'footwear': 'hand-made leather footwear of the period',
        'hair': 'period-accurate hairstyles and head coverings',
        'lighting': 'lit only by daylight, candle, oil lamp or fire',
        'window': 'small period window openings with wooden shutters',
        'map': 'a hand-drawn period map with faded ink outlines and no symbols',
        'cart': 'a wooden cart with wooden wheels',
        'street': 'earth or cobbles, no markings',
    },
}

# ── universal tells ──────────────────────────────────────────────────────────
# Asked on every historical frame regardless of prompt, on the TILES. Each is
# one atomic question where YES means an anachronism is visible. 'fix' is the
# positive phrase the ladder appends on a failure (keyed into PERIOD_VOCAB when
# it depends on the era).
UNIVERSAL_ITEMS = [
    {
        'id': 'era_poles_wires',
        'question': 'Is there anything from {after} standing above or strung between the buildings — a telegraph pole, utility pole, street-lamp post, overhead wire, cable, or antenna?',
        'fix': 'open sky and bare rooflines above the street, nothing strung between the buildings',
        'small': False,
    },
    {
        'id': 'era_shopfront_sign',
        'question': 'Is there signage or a shopfront from {after} — a glass shopfront, a printed sign, a poster, typeset lettering, or a logo?',
        'fix': 'blank timber and plaster walls, painted wooden trade signs only',
        'small': True,
    },
    {
        'id': 'era_wrist',
        # MEASURED (API v4): both "painted fingernails" flags were wrong and the one
        # true catch was a bangle — nails are out, the wrist object stays.
        'question': (
            'Can you actually see a wristwatch face or strap, a metal bangle, or a chain bracelet on '
            "someone's wrist? A sleeve cuff, a leather cord, a rope, a bandage, a rolled sleeve or "
            'bare skin are NOT this.'
        ),
        'fix': 'bare wrists and unpainted work-worn hands',
        'small': True,
    },
    {
        'id': 'era_haircut',
        'question': (
            'Does anyone have an unmistakably modern haircut — a shaved undercut, a fade with a hard line, '
            'gelled spikes, or a salon blow-dry? Ordinary short, long, tousled or bowl-cut hair is NOT this; '
            'answer yes only when the cut could not have been made with shears.'
        ),
        'fix': '@hair',
        'small': False,
        # MEASURED (bench v2, Haiku): 7 flags, 1 in truth. Hair reads are subjective;
        # reported and written into the outcomes, never a retry on their own.
        'severity': 'major',
    },
    {
        'id': 'era_modern_dress',
        'question': 'Is anyone dressed in clothing from {after} — a T-shirt, jeans, a zip, a sundress, a hoodie, a collared shirt with lapels, sneakers, or trainers — rather than period dress?',
        'fix': '@clothing',
        'small': False,
    },
    {
        'id': 'era_electric',
        'question': (
            'Is there an electric light FITTING visible — a glass bulb, a string of festoon bulbs on a wire, '
            'a floodlight or spotlight housing, a street lamp on a post, or a neon tube? Candle flames, oil '
            'lamps, torches, fireplaces and their glow are NOT electric however bright or uniform they look; '
            'answer yes only for a bulb, tube, wire or lamp housing you can actually see.'
        ),
        'fix': '@lighting',
        'small': True,
    },
    {
        'id': 'era_photo_modern',
        'question': 'Does this look like a photograph of a present-day place — a modern town street, parked vehicles, rendered facades, paving, or anything else that could not exist {after_neg}?',
        'fix': 'a hand-built period townscape of timber, plaster, thatch and stone, nothing manufactured',
        'small': False,
    },
]

GORE_ITEM = {
    'id': 'gore_wound_bone',
    'question': (
        'On a living or freshly dead PERSON, is there an open wound with torn flesh, bone showing through '
        'the skin, exposed internal organs or entrails, or a torn-open chest or belly? Skeletons, skulls, '
        'old bones in a grave, pit or ossuary, bruises, swellings and dried blood are NOT this; answer '
        'yes only for fresh open flesh or bone breaking through skin.'
    ),
    'fix': 'intact skin, injury shown only as bruise-dark discolouration and swelling under the skin',
    'small': False,
}

# ── question templates by object KIND ────────────────────────────────────────
# MEASURED 2026-08-25 (bench, 40 Black Death frames): letting the extraction
# model WRITE the questions produced "Does the ship show a wheelhouse, engine,
# metal hull, or wooden construction?" — a period-correct option inside the
# yes-list — and texture questions ("machine-stitching, uniform weave") no judge
# can answer from pixels. Recall 2/7. So the model only names WHICH kinds of
# object the prompt contains (and the period fix for each); the question is
# always one of these fixed, concrete templates naming modern TELLS only.
# ERA-FRAMED (measured 2026-08-25 on the motor-boat frame, Qwen3-VL-8B): a
# tell-list ("engine, wheelhouse, metal hull?") is answered "no — clearly a
# traditional sailing vessel" on every crop mode; the same frame framed as
# "a vessel from after 1351 rather than a period sailing ship?" is answered
# yes. The judge decides period FIRST and then rationalises the tells, so the
# question has to ask about the period and list the tells as evidence.
# "{after}" resolves to the episode's period_end ("after 1351").
QUESTION_TEMPLATES = {
    'boat': 'Is any boat or ship a vessel from {after} — motorised, or with an engine, outboard motor, wheelhouse or cabin with windows, metal hull, or radio mast — rather than a period sailing or rowing vessel?',
    'vehicle': 'Is there any vehicle from {after} — a car, truck, bus, tractor, motorcycle, or bicycle?',
    'clothing': 'Is anyone dressed in clothing from {after} — a T-shirt, jeans, a sundress, a zip, a collared shirt with lapels, tailored seams, or printed fabric — rather than period dress?',
    'footwear': 'Is any footwear from {after} — a sneaker, trainer, rubber-soled shoe, or a laced shoe with metal eyelets and a stitched toe cap — rather than period footwear?',
    'headwear': 'Does anyone wear headwear from {after} — a baseball cap, a knitted beanie, a hard hat, or sunglasses?',
    'window': 'Is any window unmistakably from {after} — a large single sheet of clear plate glass, louvred slatted shutters, an aluminium or PVC frame, or a modern handle — rather than small leaded panes, plank shutters or an open hole? Answer no for church windows, stained glass and small panes.',
    'map': 'If a map, chart or document is visible, does it carry printed pictogram symbols, coloured dots or markers, pins, virus, germ or biohazard icons, or neatly typeset labels — rather than only hand-inked lines and script? Answer no if no map or document is visible.',
    'cart': 'Is any cart, wagon or carriage built {after} — rubber tyres, thin metal spoked wheels, or a metal chassis?',
    'street': 'Is the street surface from {after} — asphalt, tarmac, painted road markings, a concrete kerb, a drain grate, or a manhole cover?',
    'tool': 'Is any tool or instrument from {after} — plastic, stainless steel, a modern pencil, a syringe, a screw-lid jar, or a clipboard?',
    'weapon': 'Is there a weapon from {after} — a firearm, rifle, pistol, or modern metal weapon?',
    'furniture': 'Is any furniture from {after} — a metal frame, plastic, an upholstered modern chair, or flat-pack joinery?',
    'jewellery': 'Is anyone wearing jewellery or grooming from {after} — a wristwatch, a metal bangle, a modern bracelet, painted fingernails, or modern earrings?',
    'building': 'Is any building from {after} — concrete walls, steel beams, corrugated metal roofs, satellite dishes, rendered modern facades, or plate-glass windows?',
    'container': 'Is any container from {after} — a glass jar with a screw lid, a plastic bottle, a tin can, or a machine-made glass bottle?',
    'animal': 'Is the animal drawn wrong for what it is — an insect with large transparent wings shown as a flea, a rodent with cartoon features, or a mechanical object shown as an animal?',
}


def _after_phrase(era: dict | None) -> str:
    """'after 1351' from the era lock; 'the modern era (after 1900)' when unknown."""
    era = era or {}
    yr = era.get('period_end') or era.get('period_start')
    try:
        yr = int(yr)
    except Exception:
        yr = None
    if yr is None:
        return 'the modern era (after 1900)'
    if yr < 0:
        return f'after {abs(yr)} BC'
    return f'after {yr}'


_KIND_TO_VOCAB = {
    'boat': 'boat',
    'clothing': 'clothing',
    'footwear': 'footwear',
    'window': 'window',
    'map': 'map',
    'cart': 'cart',
    'street': 'street',
    'headwear': 'hair',
}
