# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / FACE — where identity lives for a viewer and where DINO scores it hardest.

Moved verbatim out of the old single-file creature_fx.py (lines 912-1189).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, _pick, e, f, i, s


# ══ SIDE · FACE ═════════════════════════════════════════════════════════════
# The face is where identity lives for a viewer and where DINO scores it hardest.
# Every op in this section is the most likely to move the identity number, so the
# render report prints that number beside the picture rather than under it.

_edit(
    'cy_count',
    'Eye count',
    'Face',
    'Eye count — stated as a number, because "many eyes" comes back as three on one '
    'cell and six on the next and no judge question can catch a count that was never '
    'fixed.',
    '<path d="M2.6 12s3.4-5.4 8-5.4 8 5.4 8 5.4-3.4 5.4-8 5.4-8-5.4-8-5.4z"/>'
    '<circle cx="10.6" cy="12" r="2"/><circle cx="20.4" cy="7.6" r="1.6"/>',
    [
        i('n', 'Eyes', 2, 0, 12, 1),
        e(
            'where',
            'Placement',
            'forward-facing',
            [
                'forward-facing',
                'set wide on the sides',
                'stacked vertically',
                'in a ring',
                'on stalks',
                'scattered over the head',
            ],
        ),
    ],
    fn=lambda p, x: (
        'the creature has no eyes' if p['n'] == 0 else f'the creature has exactly {p["n"]} eyes, {p["where"]}'
    ),
)

_edit(
    'cy_size',
    'Eye size',
    'Face',
    'Eye size — the single strongest appeal cue there is. Large eyes read young, '
    'harmless and cute; small ones read alert or cruel.',
    '<ellipse cx="12" cy="12" rx="9" ry="6.4"/><circle cx="12" cy="12" r="3.6"/>'
    '<circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
    [f('v', 'Larger / smaller', 40, -100, 100, 1)],
    fn=lambda p, x: f'make the eyes {_amt(p["v"])} {"larger" if p["v"] > 0 else "smaller"}' if _amt(p['v']) else '',
)

_edit(
    'cy_colour',
    'Eye colour',
    'Face',
    'Eye colour — named, not sampled. A hex triplet means nothing to a text encoder; '
    '"amber" and "pale gold" are what actually land.',
    '<circle cx="12" cy="12" r="7.6"/><circle cx="12" cy="12" r="3.4"/>'
    '<path d="M12 4.4v3.4M12 16.2v3.4M4.4 12h3.4M16.2 12h3.4"/>',
    [s('v', 'Colour', 'amber', 'a colour word: amber, pale gold, ice blue, black…', pat=r"[A-Za-z ,'-]{0,60}")],
    fn=lambda p, x: f'give it {p["v"]} eyes' if _pick(p) else '',
)

_edit(
    'cy_pupil',
    'Pupil',
    'Face',
    'Pupil shape — slit, round, goat, compound, or none at all. A prey animal and a '
    'predator differ here and almost nowhere else on the eye.',
    '<ellipse cx="12" cy="12" rx="8.4" ry="6"/><ellipse cx="12" cy="12" rx="1.6" ry="4.4"/>',
    [
        e(
            'v',
            'Pupil',
            'round',
            [
                'round',
                'vertical slit',
                'horizontal goat slit',
                'compound',
                'star-shaped',
                'no visible pupil',
                'W-shaped',
            ],
        )
    ],
    fn=lambda p, x: f'give the eyes {p["v"]} pupils',
)

_edit(
    'cy_sclera',
    'Sclera',
    'Face',
    'Sclera — the white of the eye, or its absence. Visible sclera is a human tell, '
    'and leaving it in is the commonest way a creature drifts back toward a person.',
    '<ellipse cx="12" cy="12" rx="8.4" ry="6"/><circle cx="13.6" cy="12" r="3"/><path d="M4 12h3.2"/>',
    [e('v', 'Sclera', 'none, all iris', ['none, all iris', 'black', 'white and visible', 'bloodshot', 'glowing'])],
    fn=lambda p, x: f'the eyes have {p["v"]} sclera',
    neg='human eyes',
)

_edit(
    'cy_lids',
    'Eyelids',
    'Face',
    'Eyelids — how open the eye is, plus heavy lids and nictitating membranes. Also '
    'the eyelid metric the pipeline already measures on video ([[project_vace_prop_control]]).',
    '<path d="M3.4 12.4c3-4.4 5.8-6.4 8.6-6.4s5.6 2 8.6 6.4"/>'
    '<path d="M3.4 12.4c3 4 5.8 5.8 8.6 5.8s5.6-1.8 8.6-5.8"/><circle cx="12" cy="12.4" r="2.2"/>',
    [
        e(
            'v',
            'Lids',
            'open',
            [
                'open',
                'wide open',
                'half lidded',
                'heavy lidded',
                'narrowed',
                'closed',
                'a nictitating membrane half drawn',
            ],
        )
    ],
    fn=lambda p, x: f'the eyes are {p["v"]}',
)

_edit(
    'cy_brow',
    'Brow',
    'Face',
    'Brow — the ridge over the eye. Heavy brows read angry from any distance; absent ones read innocent or alien.',
    '<path d="M4.4 9c2.6-2.4 5-3.4 7.6-3.4s5 1 7.6 3.4"/>'
    '<ellipse cx="8.4" cy="14.4" rx="3" ry="2.4"/><ellipse cx="15.6" cy="14.4" rx="3" ry="2.4"/>',
    [e('v', 'Brow', 'neutral', ['neutral', 'heavy and overhanging', 'raised', 'furrowed', 'none at all', 'tufted'])],
    fn=lambda p, x: '' if p['v'] == 'neutral' else f'give it a {p["v"]} brow',
)

_edit(
    'cy_nose',
    'Nose',
    'Face',
    'Nose and nostrils — leathery pad, slit nostrils, a trunk, or nothing. Small in '
    'the frame, decisive in what the creature is.',
    '<path d="M12 5.4v7.2c0 1.6-1 2.6-2.4 2.6"/><path d="M8.4 17.4c2.4 1.4 4.8 1.4 7.2 0"/>'
    '<circle cx="9.6" cy="15.2" r="1"/><circle cx="14.4" cy="15.2" r="1"/>',
    [
        e(
            'v',
            'Nose',
            'a small nose',
            [
                'a small nose',
                'a broad leathery nose pad',
                'slit nostrils',
                'no visible nose',
                'a trunk',
                'a snout with wide nostrils',
                'a beak',
            ],
        )
    ],
    fn=lambda p, x: f'give it {p["v"]}',
)

_edit(
    'cy_ears',
    'Ears',
    'Face',
    'Ears — kind, size and set. Ears are the second silhouette after horns and they '
    'carry mood: pinned back and pricked up are different animals.',
    '<path d="M7.4 12.4C5.6 9 5.8 5.4 8 4.4c2 1 3.4 4.2 3.4 8"/>'
    '<path d="M16.6 12.4c1.8-3.4 1.6-7-0.6-8-2 1-3.4 4.2-3.4 8"/>'
    '<path d="M8.4 13.4c1.4 4.4 5.8 4.4 7.2 0"/>',
    [
        e(
            'kind',
            'Ears',
            'pointed',
            [
                'none',
                'pointed',
                'rounded',
                'long and drooping',
                'tufted',
                'fan-like',
                'internal, just holes',
                'frilled',
            ],
        ),
        e('set', 'Set', 'upright', ['upright', 'pinned back', 'swivelled forward', 'drooping']),
        f('sz', 'Size', 0, -100, 100, 1),
    ],
    fn=lambda p, x: (
        'the creature has no external ears'
        if p['kind'] == 'none'
        else f'give it {p["kind"]} ears, {p["set"]}'
        + (f', {_amt(p["sz"])} {"larger" if p["sz"] > 0 else "smaller"}' if _amt(p['sz']) else '')
    ),
)

_edit(
    'cy_whisk',
    'Whiskers',
    'Face',
    'Whiskers — vibrissae, barbels or feelers. Thin enough to be lost at sheet '
    'resolution, so this also says how prominent they should be.',
    '<ellipse cx="12" cy="13" rx="4.4" ry="3.6"/>'
    '<path d="M7.6 11.4L2.6 9.6M7.6 13.4l-5 1.4M16.4 11.4l5-1.8M16.4 13.4l5 1.4"/>',
    [
        e('kind', 'Kind', 'whiskers', ['whiskers', 'long vibrissae', 'catfish barbels', 'feathered feelers', 'none']),
        f('a', 'Prominence', 60, 0, 100, 1),
    ],
    fn=lambda p, x: (
        'no whiskers'
        if p['kind'] == 'none'
        else (f'give it {_amt(p["a"], ("faint", "clear", "long", "very long"))} {p["kind"]}' if _amt(p['a']) else '')
    ),
)

_edit(
    'cy_expr',
    'Expression',
    'Face',
    'Expression — what the face is doing. Distinct from mood: this is the muscles, '
    'not the read, and a judge can check it on a close cell.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M7.8 14.6c1 1.6 2.6 2.4 4.2 2.4s3.2-.8 4.2-2.4"/>'
    '<circle cx="9" cy="9.8" r="1"/><circle cx="15" cy="9.8" r="1"/>',
    [
        e(
            'v',
            'Face',
            'neutral',
            [
                'neutral',
                'smiling',
                'snarling',
                'roaring',
                'yawning',
                'curious',
                'startled',
                'sleepy',
                'sad',
                'alert',
                'threatening',
                'affectionate',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'neutral' else f'the creature is {p["v"]}',
)

_edit(
    'cy_mouth',
    'Mouth',
    'Face',
    'Mouth — open, closed, and what kind of opening. Separate from expression '
    "because an open mouth is a framing decision: it shows the teeth op's work.",
    '<path d="M4.6 11.4h14.8"/><path d="M6.6 11.4c1.6 4.4 9.2 4.4 10.8 0"/>'
    '<path d="M9.4 14.6l.6 1.6M14.6 14.6l-.6 1.6"/>',
    [
        e(
            'v',
            'Mouth',
            'closed',
            [
                'closed',
                'slightly open',
                'wide open',
                'grinning',
                'a beak, closed',
                'a beak, open',
                'a mandibled maw',
                'no mouth at all',
            ],
        )
    ],
    fn=lambda p, x: f'the mouth is {p["v"]}',
)
