# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The second half of the ``FIELDS`` registry — the 2026-09-18 toolkit.

Moved verbatim from ``character_studio.py`` lines 420-934 by the 2026-10-06
modularization split. The entries are appended to the one ``FIELDS`` dict
``fields`` opened, so the registry is the same object with the same keys in
the same order as the single file built it.
"""

from __future__ import annotations

from .fields import FIELDS

_FIELDS_NEW = {
    # ═════════════════════════════════════════════════════════════════════════
    # 2026-09-18 — the second half of the toolkit.
    # ═════════════════════════════════════════════════════════════════════════
    # Everything above this line was a field the bibles ALREADY held. Everything
    # below is a field the bibles did not hold: new top-level groups
    # (appearance, wardrobe, accessories, grooming, expression, pose, render,
    # checks, studio) that land as new dicts on the next save, because
    # character_bible_service.save() dumps the package with no schema check.
    #
    # They are declared here anyway, with a `default`, for the same reason rule 1
    # at the top of this file exists: the page builds its editors from this
    # registry, so a knob that is missing from a bible must still show its
    # default rather than `undefined`. read()/spec() serve the default when the
    # bible lacks the key — the value only reaches disk when someone edits it.
    #
    # The enum choice strings are the contract with the page (task 2) and with
    # the 3D mapping (tasks 8/9). Do not reword them.
    # ── Face (new) ───────────────────────────────────────────────────────────
    'appearance.jaw': {
        't': 'enum',
        'sec': 'face',
        'label': 'Jaw',
        'default': 'natural',
        'choices': ['natural', 'narrow', 'wide', 'square', 'pointed', 'soft', 'cleft chin', 'strong chin', 'weak chin'],
    },
    'appearance.cheekbones': {
        't': 'enum',
        'sec': 'face',
        'label': 'Cheeks',
        'default': 'natural',
        'choices': ['natural', 'high', 'low', 'prominent', 'soft', 'hollow cheeks', 'full cheeks'],
    },
    'appearance.ears': {
        't': 'enum',
        'sec': 'face',
        'label': 'Ears',
        'default': 'natural',
        'choices': ['natural', 'small', 'large', 'protruding', 'close-set', 'pointed', 'hidden by hair'],
    },
    'appearance.teeth': {
        't': 'enum',
        'sec': 'face',
        'label': 'Teeth',
        'default': 'not shown',
        'choices': ['not shown', 'even', 'slightly uneven', 'gap', 'crooked', 'missing tooth', 'gold tooth'],
        'help': '"not shown" is the honest default — a closed mouth has no '
        'teeth to describe, and naming them anyway pushes the '
        'renderer towards an open mouth.',
    },
    'appearance.complexion': {
        't': 'enum',
        'sec': 'face',
        'label': 'Complexion',
        'default': 'natural',
        'choices': [
            'natural',
            'matte',
            'dewy',
            'oily sheen',
            'visible pores',
            'blemished',
            'freckled',
            'weathered',
            'porcelain',
        ],
    },
    'appearance.ageing': {
        't': 'enum',
        'sec': 'face',
        'label': 'Wrinkles',
        'default': 'none',
        'choices': ['none', 'faint lines', "crow's feet", 'forehead lines', 'deep creases', 'sagging', 'weathered'],
    },
    'appearance.asymmetry': {
        't': 'int',
        'sec': 'face',
        'label': 'Symmetry',
        'min': 0,
        'max': 100,
        'default': 15,
        'help': '0 is a perfect mirror, which no face is. Render-time only — it does not enter the identity prompt.',
    },
    # ── Eyes (new) ───────────────────────────────────────────────────────────
    'appearance.eyelids': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Lids',
        'default': 'natural',
        'choices': ['natural', 'hooded', 'double fold', 'monolid', 'heavy', 'tired'],
    },
    'appearance.lashes': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Lashes',
        'default': 'natural',
        'choices': ['natural', 'short', 'long', 'thick', 'sparse', 'very long'],
    },
    'appearance.gaze': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Gaze',
        'default': 'to camera',
        'choices': ['to camera', 'off camera', 'up', 'down', 'distant', 'sidelong'],
        'help': 'Where the eyes point in THIS shot — staging, not identity.',
    },
    'appearance.pupils': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Pupils',
        'default': 'natural',
        'choices': ['natural', 'dilated', 'pinpoint', 'cat-slit', 'ringed'],
    },
    'appearance.heterochromia': {
        't': 'text',
        'sec': 'eyes',
        'label': 'Heterochromia',
        'default': '',
        'help': 'Empty means none. Otherwise say which eye is which — "left blue, right brown".',
    },
    'appearance.under_eye': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Under-eye',
        'default': 'none',
        'choices': ['none', 'faint shadow', 'dark circles', 'puffy', 'tired band'],
    },
    # ── Hair (new) ───────────────────────────────────────────────────────────
    'appearance.hairline': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Hairline',
        'default': 'natural',
        'choices': ['natural', 'low', 'high', 'receding temples', "widow's peak", 'bald crown', 'fully bald'],
    },
    'appearance.parting': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Parting',
        'default': 'none',
        'choices': ['none', 'centre', 'left', 'right', 'zigzag'],
    },
    'appearance.greying': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Greying',
        'default': 'none',
        'choices': ['none', 'temples', 'streaks', 'salt and pepper', 'mostly grey', 'fully grey'],
    },
    'appearance.body_hair': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Body hair',
        'default': 'light',
        'choices': ['none', 'light', 'moderate', 'heavy'],
    },
    'appearance.hair_behaviour': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Hair physics',
        'default': 'still',
        'choices': ['still', 'soft flyaways', 'wind-blown', 'glossy', 'matte', 'wet'],
    },
    # ── Body (new) ───────────────────────────────────────────────────────────
    'appearance.tattoos': {
        't': 'area',
        'sec': 'body',
        'label': 'Tattoos',
        'default': '',
        'help': 'Where and what. A tattoo that is not placed drifts from shot to shot.',
    },
    'appearance.body_scars': {'t': 'area', 'sec': 'body', 'label': 'Body scars', 'default': ''},
    # ── Wardrobe (new) ───────────────────────────────────────────────────────
    'wardrobe.outfit_variants': {
        't': 'area',
        'sec': 'wardrobe',
        'label': 'Outfit variants',
        'default': '',
        'help': 'One per line, "name: description". These are the alternates a scene may call for by name.',
    },
    'wardrobe.layers': {'t': 'area', 'sec': 'wardrobe', 'label': 'Layers', 'default': ''},
    'wardrobe.fabric': {
        't': 'enum',
        'sec': 'wardrobe',
        'label': 'Fabric',
        'default': 'cotton',
        'choices': ['wool', 'linen', 'cotton', 'silk', 'leather', 'velvet', 'denim', 'synthetic', 'fur', 'mixed'],
    },
    'wardrobe.colour_top': {'t': 'colour', 'sec': 'wardrobe', 'label': 'Top colour', 'default': ''},
    'wardrobe.colour_bottom': {'t': 'colour', 'sec': 'wardrobe', 'label': 'Bottom colour', 'default': ''},
    'wardrobe.colour_shoes': {'t': 'colour', 'sec': 'wardrobe', 'label': 'Shoe colour', 'default': ''},
    'wardrobe.period': {
        't': 'enum',
        'sec': 'wardrobe',
        'label': 'Era',
        'default': 'contemporary',
        'choices': [
            'contemporary',
            '2000s',
            '1980s',
            '1950s',
            '1920s',
            'victorian',
            'regency',
            '18th century',
            '17th century',
            'renaissance',
            'medieval',
            'ancient',
            'timeless fantasy',
            'science fiction',
        ],
    },
    'wardrobe.footwear': {
        't': 'enum',
        'sec': 'wardrobe',
        'label': 'Footwear',
        'default': 'shoes',
        'choices': ['boots', 'shoes', 'sandals', 'bare feet', 'heels', 'sneakers', 'riding boots', 'slippers'],
    },
    'wardrobe.headwear': {
        't': 'enum',
        'sec': 'wardrobe',
        'label': 'Headwear',
        'default': 'none',
        'choices': [
            'none',
            'cap',
            'flat cap',
            'hat',
            'wide-brim hat',
            'hood',
            'veil',
            'helmet',
            'headscarf',
            'crown',
            'beanie',
        ],
    },
    'wardrobe.outerwear': {
        't': 'enum',
        'sec': 'wardrobe',
        'label': 'Outerwear',
        'default': 'none',
        'choices': ['none', 'coat', 'cloak', 'jacket', 'armour', 'robe', 'waistcoat', 'shawl'],
    },
    'wardrobe.condition': {
        't': 'enum',
        'sec': 'wardrobe',
        'label': 'Wear',
        'default': 'clean',
        'choices': ['clean', 'worn', 'dusty', 'wet', 'torn', 'muddy', 'bloodied', 'immaculate'],
    },
    # ── Accessories (new) ────────────────────────────────────────────────────
    'accessories.jewellery': {'t': 'area', 'sec': 'accessories', 'label': 'Jewellery', 'default': ''},
    'accessories.eyewear': {
        't': 'enum',
        'sec': 'accessories',
        'label': 'Eyewear',
        'default': 'none',
        'choices': ['none', 'glasses', 'round glasses', 'sunglasses', 'monocle', 'goggles', 'pince-nez'],
    },
    'accessories.bags': {
        't': 'enum',
        'sec': 'accessories',
        'label': 'Bags',
        'default': 'none',
        'choices': ['none', 'satchel', 'backpack', 'purse', 'shoulder bag', 'sack', 'briefcase'],
    },
    'accessories.weapons': {'t': 'area', 'sec': 'accessories', 'label': 'Weapons', 'default': ''},
    'accessories.insignia': {
        't': 'area',
        'sec': 'accessories',
        'label': 'Insignia',
        'default': '',
        'help': 'Badges, ranks, house marks. The detail continuity notices first when it moves.',
    },
    # ── Grooming (new section) ───────────────────────────────────────────────
    'grooming.makeup': {
        't': 'enum',
        'sec': 'grooming',
        'label': 'Make-up',
        'default': 'none',
        'choices': ['none', 'natural', 'light', 'heavy', 'stage', 'smoky eyes', 'red lips', 'period-appropriate'],
    },
    'grooming.kept': {
        't': 'enum',
        'sec': 'grooming',
        'label': 'Grooming',
        'default': 'neat',
        'choices': ['immaculate', 'neat', 'everyday', 'unkempt', 'dishevelled', 'wild'],
    },
    'grooming.dirt': {
        't': 'int',
        'sec': 'grooming',
        'label': 'Dirt',
        'min': 0,
        'max': 100,
        'default': 0,
        'help': 'Above 40 the presentation fragment starts saying "dusty".',
    },
    'grooming.sweat': {
        't': 'int',
        'sec': 'grooming',
        'label': 'Sweat',
        'min': 0,
        'max': 100,
        'default': 0,
        'help': 'Above 40 the presentation fragment starts saying "sweating".',
    },
    'grooming.injury': {'t': 'area', 'sec': 'grooming', 'label': 'Injury', 'default': ''},
    'grooming.nails': {
        't': 'enum',
        'sec': 'grooming',
        'label': 'Nails',
        'default': 'natural',
        'choices': ['natural', 'short', 'long', 'painted', 'dirty', 'bitten', 'broken'],
    },
    # ── Expression (new) ─────────────────────────────────────────────────────
    'expression.emotion_set': {
        't': 'area',
        'sec': 'expression',
        'label': 'Emotion set',
        'default': '',
        'help': 'One per line.',
    },
    'expression.brows': {
        't': 'enum',
        'sec': 'expression',
        'label': 'Brows',
        'default': 'level',
        'choices': ['level', 'raised', 'drawn together', 'one raised', 'lowered', 'relaxed'],
    },
    'expression.mouth': {
        't': 'enum',
        'sec': 'expression',
        'label': 'Mouth',
        'default': 'closed',
        'choices': ['closed', 'parted', 'open', 'pressed', 'pursed', 'smiling closed', 'smiling open', 'grimace'],
    },
    'expression.eyes': {
        't': 'enum',
        'sec': 'expression',
        'label': 'Eye expression',
        'default': 'neutral',
        'choices': ['neutral', 'soft', 'bright', 'narrowed', 'wide', 'tired', 'glaring', 'tearful'],
    },
    'expression.micro': {
        't': 'int',
        'sec': 'expression',
        'label': 'Micro-expression',
        'min': 0,
        'max': 100,
        'default': 20,
    },
    'expression.locked': {'t': 'bool', 'sec': 'expression', 'label': 'Lock expression', 'default': False},
    # ── Pose (new) ───────────────────────────────────────────────────────────
    'pose.library': {
        't': 'area',
        'sec': 'pose',
        'label': 'Pose library',
        'default': '',
        'help': 'Named poses, one per line.',
    },
    'pose.gesture': {
        't': 'enum',
        'sec': 'pose',
        'label': 'Gesture',
        'default': 'at rest',
        'choices': [
            'at rest',
            'arms folded',
            'hands on hips',
            'pointing',
            'reaching',
            'hands clasped',
            'hands in pockets',
            'arms raised',
            'one hand raised',
        ],
    },
    'pose.head_turn': {
        't': 'enum',
        'sec': 'pose',
        'label': 'Head turn',
        'default': 'to camera',
        'choices': [
            'to camera',
            'quarter left',
            'quarter right',
            'profile left',
            'profile right',
            'tilted',
            'looking up',
            'looking down',
        ],
    },
    'pose.stance': {
        't': 'enum',
        'sec': 'pose',
        'label': 'Stance',
        'default': 'square',
        'choices': ['square', 'contrapposto', 'striding', 'seated', 'leaning', 'kneeling', 'crouched'],
    },
    'pose.hands': {
        't': 'enum',
        'sec': 'pose',
        'label': 'Hands',
        'default': 'relaxed',
        'choices': ['relaxed', 'fists', 'open palms', 'holding object', 'fingers spread', 'pointing', 'gripping'],
    },
    'pose.framing': {
        't': 'enum',
        'sec': 'pose',
        'label': 'Framing',
        'default': 'standing',
        'choices': ['standing', 'seated', 'leaning', 'lying'],
    },
    # ── Render (new) ─────────────────────────────────────────────────────────
    'render.lens_mm': {
        't': 'int',
        'sec': 'render',
        'label': 'Lens (mm)',
        'min': 14,
        'max': 200,
        'default': 85,
        'help': 'Portrait lenses start around 85mm; below ~35mm a face '
        'close-up distorts, which is a look, not a mistake.',
    },
    'render.aperture': {
        't': 'float',
        'sec': 'render',
        'label': 'Aperture (f/)',
        'min': 1.2,
        'max': 16,
        'step': 0.1,
        'default': 2.8,
    },
    'render.background': {
        't': 'enum',
        'sec': 'render',
        'label': 'Background',
        'default': 'neutral grey',
        'choices': ['neutral grey', 'white', 'black', 'studio gradient', 'plate', 'set', 'outdoor', 'bokeh'],
    },
    # ── Model (new) ──────────────────────────────────────────────────────────
    'conditioning.seed': {
        't': 'int',
        'sec': 'model',
        'label': 'Seed',
        'min': -1,
        'max': 2147483647,
        'default': -1,
        'help': '-1 draws a fresh seed every render. A fixed seed is how a comparison stays a comparison.',
    },
    # ── Voice (new) ──────────────────────────────────────────────────────────
    'voice_profile.pitch_semitones': {
        't': 'float',
        'sec': 'voice',
        'label': 'Pitch (semitones)',
        'min': -12,
        'max': 12,
        'step': 0.5,
        'default': 0,
    },
    'voice_profile.tract_cm': {
        't': 'float',
        'sec': 'voice',
        'label': 'Vocal tract (cm)',
        'min': 12,
        'max': 20,
        'step': 0.01,
        'default': 15.0,
    },
    'voice_profile.accent': {'t': 'text', 'sec': 'voice', 'label': 'Accent', 'default': ''},
    # ── Motion (new) ─────────────────────────────────────────────────────────
    'motion_profile.gait': {
        't': 'enum',
        'sec': 'motion',
        'label': 'Gait',
        'default': 'neutral',
        'choices': ['neutral', 'brisk', 'slow', 'heavy', 'light', 'limping', 'swaggering', 'shuffling', 'marching'],
    },
    'motion_profile.idle': {
        't': 'enum',
        'sec': 'motion',
        'label': 'Idle',
        'default': 'breathing',
        'choices': ['still', 'breathing', 'weight shift', 'fidgeting', 'looking around', 'swaying'],
    },
    'motion_profile.preset': {'t': 'text', 'sec': 'motion', 'label': 'Motion preset', 'default': ''},
    # ── Checks (new section) ─────────────────────────────────────────────────
    'checks.drift_max': {
        't': 'float',
        'sec': 'checks',
        'label': 'Max identity drift',
        'min': 0,
        'max': 1,
        'step': 0.01,
        'default': 0.35,
    },
    # ── Studio (new section) ─────────────────────────────────────────────────
    # No tool draws this one. It is the lock list: a JSON array of dotted paths
    # that edit() refuses to write. It is stored as an area so it survives the
    # same text round trip as every other field, and parsed defensively —
    # a malformed list locks nothing rather than locking everything.
    'studio.locked_fields': {
        't': 'area',
        'sec': 'studio',
        'label': 'Locked fields',
        'default': '',
        'help': 'A JSON list of dotted paths, e.g. '
        '["appearance.jaw", "wardrobe.period"]. Edits to a '
        'locked path are refused until it is unlocked in the '
        'same request.',
    },
}

FIELDS.update(_FIELDS_NEW)
