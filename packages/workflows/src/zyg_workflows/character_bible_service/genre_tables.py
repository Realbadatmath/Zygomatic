# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Auto-defaults engine: wardrobe / lighting / accessory / palette pools by genre."""

from __future__ import annotations


# ──────────────────────────────────────────────────────────────────────────────
# Auto-defaults engine
# ──────────────────────────────────────────────────────────────────────────────
# Wardrobe / accessory / palette suggestions keyed on (genre, gender).
_GENRE_WARDROBE: dict[str, dict[str, str]] = {
    'general': {
        'female': 'modern casual blouse and slacks, neutral palette, plain white sneakers',
        'male': 'modern casual shirt and slacks, neutral palette, plain white sneakers',
    },
    'action': {
        'female': 'battle-ready tactical outfit, leather and armor details, heavy black combat boots',
        'male': 'battle-ready armored outfit, leather and steel details, heavy black combat boots',
    },
    'romance': {
        'female': 'elegant flowing dress, soft warm tones, refined jewelry, elegant nude heels',
        'male': 'tailored shirt and waistcoat, soft warm tones, polished brown oxford shoes',
    },
    'religion': {
        'female': 'traditional robes in muted tones, modest accessories, simple leather sandals',
        'male': 'traditional robes in muted tones, simple cord belt, simple leather sandals',
    },
    'finance': {
        'female': 'sharp tailored business suit, silk blouse, minimal jewelry, classic black pumps',
        'male': 'sharp tailored business suit, crisp white shirt, silk tie, polished black oxford shoes',
    },
    'medieval': {
        'female': 'period-accurate kirtle and surcoat, woven belt, period leather turnshoes',
        'male': 'tunic with leather belt and travel cloak, period-accurate, worn leather boots',
    },
    'education': {
        'female': 'tweed blazer over button-down, scholarly attire, brown leather brogues',
        'male': 'tweed blazer over button-down, scholarly attire, brown leather brogues',
    },
}

# Per-character variety pools (2026-07-18). One fixed outfit + one fixed
# lighting per genre made every character shoot look like the same session —
# identical olive shirt, identical grey key — which amplifies perceived
# same-person similarity even between different faces. Auto picks one option
# seeded per character; the first entry of each pool is the legacy value.
_GENRE_WARDROBE_POOL: dict[str, dict[str, tuple[str, ...]]] = {
    'general': {
        'female': (
            'modern casual blouse and slacks, neutral palette, plain white sneakers',
            'fitted knit sweater and dark jeans, casual modern look, simple black sneakers',
            'linen shirt and tailored trousers, relaxed earth tones, brown leather loafers',
            'denim jacket over plain tee, everyday casual, white canvas sneakers',
            'wrap top and midi skirt, soft muted colours, flat ankle boots',
        ),
        'male': (
            'modern casual shirt and slacks, neutral palette, plain white sneakers',
            'crew-neck sweater over collared shirt, dark jeans, simple black sneakers',
            'linen shirt and chinos, relaxed earth tones, brown leather loafers',
            'denim jacket over plain tee, everyday casual, white canvas sneakers',
            'lightweight bomber jacket and dark trousers, black low-top sneakers',
        ),
    },
    'action': {
        'female': (
            'battle-ready tactical outfit, leather and armor details, heavy black combat boots',
            'worn field jacket, cargo trousers, fingerless gloves, scuffed brown combat boots',
            'scuffed leather jacket over reinforced vest, combat boots',
        ),
        'male': (
            'battle-ready armored outfit, leather and steel details, heavy black combat boots',
            'worn field jacket, cargo trousers, tactical harness, scuffed brown combat boots',
            'scuffed leather jacket over reinforced vest, combat boots',
        ),
    },
    'romance': {
        'female': (
            'elegant flowing dress, soft warm tones, refined jewelry, elegant nude heels',
            'silk blouse and high-waist skirt, gentle pastel palette, classic black pumps',
            'off-shoulder knit dress, warm candlelight tones, strappy flat sandals',
        ),
        'male': (
            'tailored shirt and waistcoat, soft warm tones, polished brown oxford shoes',
            'open-collar linen shirt, rolled sleeves, warm palette, brown leather loafers',
            'fine-knit sweater and wool trousers, relaxed elegance, suede desert boots',
        ),
    },
    'religion': {
        'female': (
            'traditional robes in muted tones, modest accessories, simple leather sandals',
            'layered linen habit in undyed tones, simple head covering, simple leather sandals',
        ),
        'male': (
            'traditional robes in muted tones, simple cord belt, simple leather sandals',
            'layered linen vestments in undyed tones, plain sandals',
        ),
    },
    'finance': {
        'female': (
            'sharp tailored business suit, silk blouse, minimal jewelry, classic black pumps',
            'charcoal pencil-skirt suit, crisp white shirt, classic black pumps',
            'navy blazer over turtleneck, tailored trousers, black leather flats',
        ),
        'male': (
            'sharp tailored business suit, crisp white shirt, silk tie, polished black oxford shoes',
            'charcoal three-piece suit, subtle pinstripe, polished black oxford shoes',
            'navy blazer over open-collar shirt, tailored trousers, brown leather derby shoes',
        ),
    },
    'medieval': {
        'female': (
            'period-accurate kirtle and surcoat, woven belt, period leather turnshoes',
            'wool travelling dress with hooded cloak, leather pouch, worn leather ankle boots',
        ),
        'male': (
            'tunic with leather belt and travel cloak, period-accurate, worn leather boots',
            'padded gambeson over linen shirt, leather bracers, worn leather boots',
        ),
    },
    'education': {
        'female': (
            'tweed blazer over button-down, scholarly attire, brown leather brogues',
            'cardigan over blouse, wool skirt, satchel-ready look, low block-heel shoes',
        ),
        'male': (
            'tweed blazer over button-down, scholarly attire, brown leather brogues',
            'cardigan over oxford shirt, corduroy trousers, brown leather brogues',
        ),
    },
}
_GENRE_LIGHTING_POOL: dict[str, tuple[str, ...]] = {
    'general': (
        'controlled studio key with moderate shadow definition, neutral fill',
        'soft window daylight from camera left, gentle natural fill',
        'warm late-afternoon key, soft directional shadows',
    ),
    'action': (
        'dramatic rim light, deep shadows, hard key light',
        'low-key side lighting, smoke haze, hard edge light',
    ),
    'romance': (
        'warm studio key with gentle shadow definition, not beauty-dish soft',
        'golden-hour warm key, soft halation, gentle backlight',
    ),
    'religion': (
        'top-down divine light, soft golden glow, dust motes',
        'candlelit warm ambience, soft flickering key',
    ),
    'finance': (
        'crisp daylight through large windows, clean shadows',
        'cool overhead office key, neutral bounce fill',
    ),
    'medieval': (
        'torchlit interior, warm fire glow, soft candle ambience',
        'overcast daylight through narrow windows, cool stone bounce',
    ),
    'education': (
        'natural window light, soft directional, indoor cinematic',
        'warm desk-lamp key, library ambience, soft shadows',
    ),
}
_GENRE_ACCESSORY_POOL: dict[str, dict[str, tuple[str, ...]]] = {
    'general': {
        'female': ('simple stud earrings', 'thin pendant necklace', 'small hoop earrings', 'minimal wristwatch'),
        'male': ('simple wristwatch', 'thin leather bracelet', 'plain silver chain'),
    },
    'action': {
        'female': ('fingerless gloves, utility belt', 'dog-tag chain, wrist wraps'),
        'male': ('fingerless gloves, weapon scabbard', 'dog-tag chain, utility belt'),
    },
    'romance': {
        'female': ('pearl earrings, delicate pendant', 'thin gold bracelet, small drop earrings'),
        'male': ('leather wristband', 'thin silver chain'),
    },
    'religion': {
        'female': ('simple woven cord', 'small wooden pendant'),
        'male': ('wooden prayer beads', 'simple woven cord belt'),
    },
    'finance': {
        'female': ('pearl studs, slim watch', 'thin gold necklace, stud earrings'),
        'male': ('silver cufflinks, slim wristwatch', 'tie bar, leather-strap watch'),
    },
    'medieval': {
        'female': ('leather pouch on belt', 'simple pewter brooch'),
        'male': ('leather pouch on belt, simple silver brooch', 'iron belt buckle, leather bracers'),
    },
    'education': {
        'female': ('reading glasses', 'thin-framed glasses, stud earrings'),
        'male': ('reading glasses', 'thin-framed glasses, leather watch'),
    },
}

_GENRE_PALETTE: dict[str, str] = {
    'general': 'warm neutrals, consistent skin tones, low variance',
    'action': 'desaturated steel and amber, high contrast',
    'romance': 'warm peach, soft rose, golden hour tones',
    'religion': 'muted earth tones, candlelit warm yellows',
    'finance': 'cool charcoal, navy, polished neutrals',
    'medieval': 'earthy browns, forest greens, torchlit amber',
    'education': 'warm wood tones, library browns, soft daylight',
}
