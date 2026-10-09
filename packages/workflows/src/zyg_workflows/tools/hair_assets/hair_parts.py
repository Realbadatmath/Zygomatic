# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""hair_parts.py — which of a character's grooms is hair, beard or brows.

ONE rule, imported by both sides. groom_to_glb.py uses it to decide what to
bake into the viewport ribbons; char_cycles_render.py uses it to find the SAME
grooms at full density in the source .blend. When the two drifted apart, a
render asked for 'hair' and got the beard with it.

Matched as substrings against '<object>/<system>' lowercased, so nothing here
may be a substring of a part we want: 'tail' once cost Ellie her PONYTAIL,
which is most of the hairstyle."""

HEAD_KEYS = ('hair', 'beard', 'moustache', 'mustache', 'sideburn', 'stubble')
BROW_KEYS = ('brow', 'lash')
BEARD_KEYS = ('beard', 'moustache', 'mustache', 'sideburn', 'stubble')

# garments and body hair, never head hair
SKIP_KEYS = (
    'jacket',
    'pullover',
    'boots',
    'scarf',
    'glove',
    'pants',
    'sweater',
    'stitch',
    'fuzz',
    'dart_tail',
    'arms',
    'legs',
    'body_hair',
    'scales',
    'hair_nose',
    'hair_ears',
    'fluff',
)

# A groom's stray flyaway system is a handful of very long single hairs: half
# the bounding box, none of the look. '.messy' and '.distressed' are alternate
# takes of a groom the film could switch to, not separate hairstyles.
DROP_KEYS = ('loose', 'messy', 'distressed')


def kind(name):
    """'hair' | 'beard' | 'brows' | None for a groom object/system name."""
    nm = str(name or '').lower()
    if any(k in nm for k in SKIP_KEYS):
        return None
    if any(k in nm for k in DROP_KEYS):
        return None
    if any(k in nm for k in BROW_KEYS):
        return 'brows'
    if any(k in nm for k in BEARD_KEYS):
        return 'beard'
    if any(k in nm for k in HEAD_KEYS):
        return 'hair'
    return None
