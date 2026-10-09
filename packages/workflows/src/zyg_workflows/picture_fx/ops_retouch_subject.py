# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registry entries: SIDE / RETOUCH and SIDE / SUBJECT — the generative clauses."""

from __future__ import annotations

from zyg_workflows.picture_fx.pixel_tone import (
    b,
    c,
    e,
    f,
    s,
)

from zyg_workflows.picture_fx.registry import _amt, _edit, _pick, colour_word

# ══ SIDE · RETOUCH (generative) ═════════════════════════════════════════════
# Every one of these compiles to a clause of one Qwen-Image-Edit instruction.
# They are the ops that can change WHO is in the picture, which is why the bake
# is measured against its source rather than trusted.

_edit(
    'rt_skin',
    'Skin',
    'Retouch',
    'Even the skin out or add texture back. Pushed positive this is the waxy look the '
    'pipeline already fights, so the negative direction — MORE pore and texture — is '
    'usually the one you want ([[project_waxy_skin_diagnosis]]).',
    '<circle cx="12" cy="12" r="8.4"/><circle cx="9.4" cy="10" r=".8"/>'
    '<circle cx="14" cy="9.4" r=".8"/><circle cx="12.4" cy="14" r=".8"/>',
    [f('v', 'Smooth ← → textured', 0, -100, 100, 1)],
    fn=lambda p, x: (
        f'give the skin {_amt(p["v"])} more visible pore texture and fine detail'
        if p['v'] > 0
        else (f'even out the skin {_amt(p["v"])}, keeping pores visible' if p['v'] < 0 else '')
    ),
)

_edit(
    'rt_blemish',
    'Blemishes',
    'Retouch',
    'Remove spots, stray marks and compression artefacts from the skin without touching its texture.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M9 9l6 6M15 9l-6 6"/>',
    [b('v', 'Remove blemishes', True)],
    fn=lambda p, x: (
        'remove blemishes, spots and stray marks from the skin while keeping its natural texture' if p['v'] else ''
    ),
)

_edit(
    'rt_hands',
    'Hands',
    'Retouch',
    'Rebuild the hands with correct anatomy. The single most common defect in this '
    "pipeline's output, and the one a VLM judge scores as fine "
    '([[project_hand_repair_arcane]]).',
    '<path d="M8.6 12V5.4a1.6 1.6 0 013.2 0V11"/><path d="M11.8 10.6V4.6a1.6 1.6 0 013.2 0V11"/>'
    '<path d="M15 10.6V6.4a1.6 1.6 0 013.2 0v8.2a6 6 0 01-6 6h-1.4a5 5 0 01-4-2l-2.6-3.6a1.6 1.6 0 012.4-2l1.6 1.6"/>',
    [b('v', 'Fix the hands', True)],
    fn=lambda p, x: (
        'correct the hands so each has exactly five well-formed fingers with natural joints and proportions'
        if p['v']
        else ''
    ),
    neg='extra fingers, fused fingers, malformed hands',
)

_edit(
    'rt_eyes',
    'Eyes',
    'Retouch',
    'Repair the eyes — pupils round and matched, catchlights consistent, irises the same colour in both.',
    '<path d="M2.6 12s3.6-6 9.4-6 9.4 6 9.4 6-3.6 6-9.4 6-9.4-6-9.4-6z"/><circle cx="12" cy="12" r="2.8"/>',
    [b('v', 'Fix the eyes', True)],
    fn=lambda p, x: (
        'make both eyes symmetrical and correctly formed, with round matched pupils and consistent catchlights'
        if p['v']
        else ''
    ),
    neg='crossed eyes, mismatched irises, extra pupils',
)

_edit(
    'rt_teeth',
    'Teeth',
    'Retouch',
    'Repair the teeth. A diffusion model gets the count wrong far more often than the '
    'shape, and a mouth is where that reads worst.',
    '<path d="M4 8.4h16v4.2a7 7 0 01-7 7h-2a7 7 0 01-7-7z"/><path d="M8 8.4v4M12 8.4v5M16 8.4v4"/>',
    [b('v', 'Fix the teeth', True)],
    fn=lambda p, x: 'render the teeth naturally, evenly spaced and correctly shaped' if p['v'] else '',
)

_edit(
    'rt_deblur',
    'Deblur',
    'Retouch',
    'Ask for the picture back sharp. A restoration, not a sharpen: it rebuilds the '
    'detail rather than raising the contrast of what is already blurred — and it is '
    'inventing that detail, which the identity check on the bake is there to catch.',
    '<circle cx="11" cy="11" r="6.4"/><path d="M15.8 15.8l4.8 4.8"/><path d="M8.4 11h5.2"/>',
    [f('v', 'Strength', 60, 10, 100, 1)],
    fn=lambda p, x: (
        f'restore {_amt(p["v"])} sharper detail across the whole image, recovering fine texture without adding halos'
    ),
)

_edit(
    'rt_denoise',
    'Clean up',
    'Retouch',
    'Remove noise, banding and compression artefacts generatively. Where the Detail '
    "section's median denoise smears fine hair, this rebuilds it — at the cost of "
    'inventing what it rebuilds.',
    '<path d="M4.6 16.4c2-4 4-6 7.4-6s5.4 2 7.4 6"/><path d="M6.6 8.6h.01M10 6.6h.01M14 7h.01M17.4 9h.01"/>',
    [b('v', 'Clean up artefacts', True)],
    fn=lambda p, x: (
        'remove noise, colour banding and compression artefacts while keeping fine texture' if p['v'] else ''
    ),
)

_edit(
    'rt_colourise',
    'Colourise',
    'Retouch',
    'Put plausible colour on a monochrome source. Every colour it chooses is invented — '
    'there is nothing in a greyscale frame that says the coat was blue.',
    '<path d="M12 3.6c3.4 4.6 5.6 7.8 5.6 10.4a5.6 5.6 0 11-11.2 0c0-2.6 2.2-5.8 5.6-10.4z"/><path d="M6.4 14h11.2"/>',
    [s('v', 'Palette hint', '', 'e.g. "muted autumn tones" — left blank the model chooses')],
    fn=lambda p, x: (
        'colourise this monochrome image with natural, plausible colour' + (f', in {_pick(p)}' if _pick(p) else '')
    ),
)

_edit(
    'rt_removetext',
    'Remove text',
    'Retouch',
    'Remove watermarks, captions and stray lettering. Diffusion models write text into '
    'frames unprompted, and the typography gate catches it downstream — this is the fix '
    '([[project_typography_gate]]).',
    '<path d="M4.6 6.4h14.8M12 6.4v13"/><path d="M3.4 3.4l17.2 17.2"/>',
    [b('v', 'Remove all lettering', True)],
    fn=lambda p, x: (
        'remove all text, watermarks, captions and lettering from the image, reconstructing what was behind them'
        if p['v']
        else ''
    ),
    neg='text, watermark, caption, signature, letters',
)

_edit(
    'rt_remove',
    'Remove object',
    'Retouch',
    'Name a thing and have it taken out, with what was behind it reconstructed. Says '
    'what to remove in words — for a region you can point at, Repair area is exact and '
    'this is not.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2"/><path d="M8.6 12h6.8"/>',
    [s('v', 'What to remove', '')],
    fn=lambda p, x: (
        f'remove the {_pick(p)} from the image entirely and reconstruct the background behind it' if _pick(p) else ''
    ),
)

_edit(
    'rt_add',
    'Add element',
    'Retouch',
    'Name a thing and have it put in. The counterpart to Remove, and the op most likely '
    'to change the composition out from under a locked framing.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2"/><path d="M12 8.4v7.2M8.4 12h7.2"/>',
    [
        s('v', 'What to add', ''),
        e('where', 'Where', 'in frame', ['in frame', 'foreground', 'background', 'left', 'right', 'above', 'below']),
    ],
    fn=lambda p, x: f'add {_pick(p)} {p["where"]}' if _pick(p) else '',
)

_edit(
    'rt_outpaint',
    'Extend scene',
    'Retouch',
    'Continue the picture past its own edges. Hand it a plate widened by Extend edges '
    'first: an outpaint with nothing to continue invents a different room '
    '([[project_shores_v20_quay_bird]]).',
    '<rect x="8" y="8" width="8" height="8" rx="1"/>'
    '<path d="M3.4 3.4h5M3.4 3.4v5M20.6 3.4h-5M20.6 3.4v5M3.4 20.6h5M3.4 20.6v-5M20.6 20.6h-5M20.6 20.6v-5"/>',
    [s('v', 'What is out there', '')],
    fn=lambda p, x: (
        'extend the scene naturally beyond the original framing, continuing the '
        'existing background' + (f' with {_pick(p)}' if _pick(p) else '')
    ),
)


# ══ SIDE · SUBJECT (generative) ═════════════════════════════════════════════
# What the person or creature IS. These are the edits most likely to break
# identity, which is why the bake is scored rather than trusted.

_edit(
    'sj_expression',
    'Expression',
    'Subject',
    'Change the expression without changing the face. The most reliable of the subject '
    'edits, and still worth checking against the source — a big expression change moves '
    'the whole lower face.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M8.6 10h.01M15.4 10h.01"/>'
    '<path d="M8.2 14.4c1 1.4 2.2 2.1 3.8 2.1s2.8-.7 3.8-2.1"/>',
    [
        e(
            'v',
            'Expression',
            'neutral',
            [
                'neutral',
                'slight smile',
                'broad smile',
                'laughing',
                'serious',
                'stern',
                'sad',
                'grieving',
                'surprised',
                'afraid',
                'angry',
                'disgusted',
                'thoughtful',
                'weary',
                'determined',
                'suspicious',
            ],
        )
    ],
    fn=lambda p, x: (
        f'change the facial expression to {p["v"]}'
        if p['v'] != 'neutral'
        else 'settle the face into a neutral expression'
    ),
)

_edit(
    'sj_gaze',
    'Gaze',
    'Subject',
    'Where the eyes are looking, independent of where the head is pointed. The two '
    'coming apart is what makes a portrait read as alive.',
    '<path d="M2.6 12s3.6-6 9.4-6 9.4 6 9.4 6-3.6 6-9.4 6-9.4-6-9.4-6z"/><circle cx="14" cy="12" r="2.4"/>',
    [
        e(
            'v',
            'Looking',
            'at camera',
            [
                'at camera',
                'slightly off camera',
                'to the left',
                'to the right',
                'upward',
                'downward',
                'into the distance',
                'at something below frame',
            ],
        )
    ],
    fn=lambda p, x: f'have the subject look {p["v"]}',
)

_edit(
    'sj_head',
    'Head angle',
    'Subject',
    'Turn or tilt the head. Camera ops and head ops disagree if you stack both — the '
    'model averages them rather than doing each ([[project_wan_motion_debug]]).',
    '<circle cx="12" cy="8.6" r="4"/><path d="M5.6 20.6c0-3.6 2.9-6.4 6.4-6.4s6.4 2.8 6.4 6.4"/>'
    '<path d="M18.6 6.6a5.6 5.6 0 00-3-2.6"/>',
    [
        e(
            'v',
            'Head',
            'three-quarter left',
            [
                'facing camera',
                'three-quarter left',
                'three-quarter right',
                'profile left',
                'profile right',
                'tilted left',
                'tilted right',
                'chin up',
                'chin down',
                'looking over the shoulder',
            ],
        )
    ],
    fn=lambda p, x: f'turn the head to {p["v"]}',
)

_edit(
    'sj_age',
    'Age',
    'Subject',
    'Age the subject up or down. It moves bone structure, not just skin — the pipeline '
    'has already been bitten by an age macro reshaping a body '
    '([[project_abel_self_intersection]]).',
    '<path d="M4.6 19.4c0-4 3.3-7.2 7.4-7.2s7.4 3.2 7.4 7.2"/><circle cx="12" cy="7.4" r="3.6"/>'
    '<path d="M17 3.4l1.2 2.4 2.4 1.2-2.4 1.2L17 10.6l-1.2-2.4L13.4 7l2.4-1.2z"/>',
    [f('v', 'Younger ← → older', 0, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the subject look {_amt(p["v"])} older'
        if p['v'] > 0
        else (f'make the subject look {_amt(p["v"])} younger' if p['v'] < 0 else '')
    ),
)

_edit(
    'sj_build',
    'Build',
    'Subject',
    'Heavier or leaner. A body-shape edit, so it will move the clothing with it and it '
    'will not respect a costume lock.',
    '<path d="M12 3.4a2.6 2.6 0 110 5.2 2.6 2.6 0 010-5.2z"/>'
    '<path d="M7 20.6v-5.2c0-3.2 2.2-5.4 5-5.4s5 2.2 5 5.4v5.2"/>',
    [f('v', 'Leaner ← → heavier', 0, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the subject {_amt(p["v"])} heavier and fuller in build'
        if p['v'] > 0
        else (f'make the subject {_amt(p["v"])} leaner' if p['v'] < 0 else '')
    ),
)

_edit(
    'sj_hair',
    'Hairstyle',
    'Subject',
    'The cut and the length. Hair is where the same-character checks fail first, so a '
    'hair edit on a locked character wants the drift gate run afterwards '
    '([[project_hair_age_dedup_fixes]]).',
    '<path d="M5.4 12.6c0-4.4 2.8-7.6 6.6-7.6s6.6 3.2 6.6 7.6"/>'
    '<path d="M6.6 12.6c-.6 3.6-.4 6 .6 8M17.4 12.6c.6 3.6.4 6-.6 8"/>',
    [s('v', 'Hairstyle', '', 'e.g. "short cropped waves", "long braided"')],
    fn=lambda p, x: f'change the hairstyle to {_pick(p)}' if _pick(p) else '',
)

_edit(
    'sj_haircol',
    'Hair colour',
    'Subject',
    'Recolour the hair only. Named as a colour word rather than a hex value, because a '
    'text encoder reads "ash blonde" and averages "#c9b48a" away.',
    '<path d="M5.4 13c0-4.4 2.8-7.6 6.6-7.6s6.6 3.2 6.6 7.6"/>'
    '<path d="M8 20.6c-.8-2.6-1-5.2-1-7.6M16 20.6c.8-2.6 1-5.2 1-7.6"/>'
    '<circle cx="19.4" cy="18.4" r="2"/>',
    [c('col', 'Colour', '#6b4a2f'), s('word', 'Colour in words', '', 'beats the swatch')],
    fn=lambda p, x: f'change the hair colour to {_pick(p, "word") or colour_word(p["col"])}',
)

_edit(
    'sj_eyecol',
    'Eye colour',
    'Subject',
    'Recolour the irises only, both to the same colour — which is the failure this fixes '
    'as often as it is the change asked for.',
    '<path d="M2.6 12s3.6-6 9.4-6 9.4 6 9.4 6-3.6 6-9.4 6-9.4-6-9.4-6z"/>'
    '<circle cx="12" cy="12" r="3.2"/><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none"/>',
    [c('col', 'Colour', '#4a7a8c'), s('word', 'Colour in words', '')],
    fn=lambda p, x: f'change both irises to {_pick(p, "word") or colour_word(p["col"])}, matched to each other',
)

_edit(
    'sj_facial',
    'Facial hair',
    'Subject',
    'Beard, moustache, stubble or clean-shaven. A jaw-line change as much as a hair one, '
    'so it moves the silhouette of the lower face.',
    '<circle cx="12" cy="8.6" r="4"/><path d="M7.6 11.4c0 4.4 2 7 4.4 7s4.4-2.6 4.4-7"/>',
    [
        e(
            'v',
            'Facial hair',
            'clean-shaven',
            [
                'clean-shaven',
                'light stubble',
                'heavy stubble',
                'short beard',
                'full beard',
                'long beard',
                'moustache',
                'goatee',
                'sideburns',
            ],
        )
    ],
    fn=lambda p, x: f'give the subject {p["v"]}' if p['v'] != 'clean-shaven' else 'make the subject clean-shaven',
)

_edit(
    'sj_outfit',
    'Outfit',
    'Subject',
    'Change what the subject is wearing. Period costume is where the anachronism gate '
    'earns its keep — a diffusion model will happily put a zip on a 1640s doublet '
    '([[project_anachronism_gate_qwen]]).',
    '<path d="M8.6 3.4l3.4 2.6 3.4-2.6 4.6 2.6-1.6 4.4-2 .6v9.6H7.6V11l-2-.6L4 6z"/>',
    [s('v', 'Outfit', '', 'e.g. "a plain linen shirt and leather jerkin"')],
    fn=lambda p, x: f'change the clothing to {_pick(p)}' if _pick(p) else '',
)

_edit(
    'sj_outfitcol',
    'Garment colour',
    'Subject',
    'Recolour the clothing without changing its cut. Far more reliable than asking for a '
    'new garment, and it will not touch the silhouette.',
    '<path d="M8.6 3.4l3.4 2.6 3.4-2.6 4.6 2.6-1.6 4.4-2 .6v9.6H7.6V11l-2-.6L4 6z"/><circle cx="12" cy="14" r="2.2"/>',
    [
        c('col', 'Colour', '#5a6f8c'),
        s('word', 'Colour in words', ''),
        s('what', 'Which garment', '', 'blank = all of it'),
    ],
    fn=lambda p, x: (
        f'recolour {_pick(p, "what") or "the clothing"} to '
        f'{_pick(p, "word") or colour_word(p["col"])}, keeping the same cut'
    ),
)

_edit(
    'sj_accessory',
    'Accessory',
    'Subject',
    'Add or remove a worn thing — glasses, a hat, jewellery, a weapon. Named ones are '
    'reliable; an invented one is a coin flip.',
    '<circle cx="7" cy="13.6" r="3.4"/><circle cx="17" cy="13.6" r="3.4"/>'
    '<path d="M10.4 13.6h3.2"/><path d="M3.6 11.4l1.6-2M20.4 11.4l-1.6-2"/>',
    [s('v', 'Accessory', ''), e('act', 'Action', 'add', ['add', 'remove'])],
    fn=lambda p, x: f'{p["act"]} {_pick(p)}' if _pick(p) else '',
)

_edit(
    'sj_makeup',
    'Makeup',
    'Subject',
    'Add or take away makeup. It changes the read of the face more than it changes the '
    'geometry, which makes it one of the safer identity edits.',
    '<path d="M9.4 3.4h5.2v5.2l-1.6 12h-2l-1.6-12z"/><path d="M9.4 8.6h5.2"/>',
    [s('v', 'Makeup', '', 'e.g. "subtle, natural" or "none at all"')],
    fn=lambda p, x: f'give the subject {_pick(p)} makeup' if _pick(p) else '',
)

_edit(
    'sj_pose',
    'Pose',
    'Subject',
    "Change the body's pose. The least reliable subject edit in this list: a pose change "
    'is a re-composition, and the framing will move with it.',
    '<circle cx="12" cy="4.6" r="2.2"/><path d="M12 6.8v6.4M12 13.2l-3.4 6.4M12 13.2l3.4 6.4"/>'
    '<path d="M6.6 9.4L12 8.2l5.4 1.2"/>',
    [s('v', 'Pose', '', 'e.g. "arms folded, weight on one hip"')],
    fn=lambda p, x: f'change the pose so the subject is {_pick(p)}' if _pick(p) else '',
)
