# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Photoreal hair, eyes and skin on a character (grooms). 2026-09-30.

Question the sheet asks: can we get photoreal hair, eyes and skin on a character?
This step is where the house has its named failure modes written down, and the test is built
around them rather than around a general "does it look good": WAXY skin (a broad blown highlight
and no micro-detail — the recorded diagnosis), FRECKLE MOTTLING (a few large blotches instead of
many small dots), and skin tone welded to heritage (changing the tone changes the face). Every
one of those is asked as its own column with its own mechanical veto and its own blind question.

The four rows are shaders and grooms on ONE body — the CC0 Blender Studio human base sculpt that
char_photoreal.py textures — so nothing here is a comparison between different people:

  strand_hair     installed grooms: character_hair_assets.py's catalogue (MakeHuman hair-card
                  styles and Blender Studio production strand grooms, licence-gated per FILE)
                  rendered by char_cycles_render.py as real curve primitives 0.05 mm across
                  through the Principled Hair BSDF
                  ([[project_charstudio_hair_assets]], [[project_charstudio_eyes_strand_hair]]).
  hair_field      the grown hair field: ribbons raised off the clay body's own scalp field, the
                  path an unposed default head wears ([[project_charstudio_hair_field_zoom]]).
  real_eyes       the photoreal eye shader ([[project_charstudio_photoreal_eye]]).
  photoreal_skin  char_photoreal.py ([[project_charstudio_photoreal_skin]]) — the albedo atlas
                  projected back onto the base sculpt. Its `--stage previews` runs LAST; that
                  ordering is the `order` column and is a LOOKUP, because it is a written fact
                  about the pipeline and not something a render can show.

Shape of the test
-----------------
One fixture .blend of heads (the base body's head at three lighting setups: the standard
three-point portrait, a backlit ear rig for subsurface, and a 4x eye crop rig), plus a
MANIFEST.json holding the ANSWER KEYS: the hue range each named hair and iris colour is asked
for, the two heritage characters that share a measured skin tone, and the named styles the
catalogue must be able to reach. The MANIFEST is declared UNVERIFIED and BLOCKS hair_style,
hair_colour, iris and heritage until the operator has checked those keys — we do not grade a
shader against a hue range nobody measured.

What machines decide and what the operator decides
--------------------------------------------------
Strand counts, whether the strands are curves or cards, hue of a masked region, sclera luma,
transmitted light through a backlit ear, high-frequency energy in a 200 % crop, blown-highlight
area, blob statistics for freckles versus mottling, CIEDE2000 between two skin tones and ArcFace
cosine between two faces are all measured. Whether a face reads as REAL rather than as a doll is
not: the defect-judge bench of 2026-09-27 put the best local model at 2/8 on the hard cases. So
realism, eyes_real, waxy, freckles, heritage, skin_sss and hair_motion carry a written blind
operator question on top of whatever ran mechanically, and the mechanical check is always a veto
— it can only make a row fail, never pass it on its own.

Measurement zoom: every blind sheet is shown at the operator's working zoom of 67 %, the size a
picture is accepted at in this house. skin_pores is the one deliberate exception and says so.

Prompt bands
------------
All four rows are shaders and headless Blender scripts driven by parameters — a groom id, a
melanin value, an iris hue. There is no wording to damage, lengthen, translate or steer, so the
four prompt bands are `na` for the whole step; what the settings were is still measured, under
`receipts` in Operability.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/grooms'
BLEND = FX + '/heads.blend'
MANIFEST = FX + '/MANIFEST.json'

# ── check kinds this module adds ──────────────────────────────────────────────────────────
# Each is a small function over the rendered image and the masks the render script writes
# beside it (hair, iris, sclera, cheek skin, ear), or over the .blend through bpy.
#   when='render'  the image(s) this probe rendered, with their masks and the MANIFEST key
#   when='scene'   the .blend after the row's own build step, queried through bpy
CHECK_KINDS = {
    'bpy_strand_count_min': 'bpy reports at least `min` hair strands (curve splines, or '
    'particle-system hair children when the row uses one) on the '
    'object named `object`, counted after the render-time child '
    'interpolation the row ships with',
    'bpy_hair_is_curves': 'the hair on `object` is CURVE geometry (Curves / Hair Curves '
    'data, or a hair particle system), not cards: no mesh object in '
    'the hair collection may have more than `max_card_faces` quads '
    'carrying an alpha-blended texture',
    'catalogue_lists_styles': 'character_hair_assets.catalogue() returns a non-refused, '
    'licence-cleared item for every style name in `styles`, and the '
    'item carries a `fit` block (a groom with no head frame is not '
    'reachable)',
    'region_hue_range': 'mean hue of the mask named `region` (hair|iris|sclera|cheek|ear) '
    'in HSV, over pixels with saturation >= `min_sat` and value in '
    '0.08..0.95, is within `min`..`max` degrees (circular mean)',
    'region_luma_max': 'mean luma (Rec.709) inside the mask named `region` is <= `max` on the 0-255 scale',
    'backlit_transmission_min': 'in the backlit ear shot, mean RED channel inside the ear mask '
    'minus mean RED inside the adjacent opaque cheek mask is >= '
    "`min` levels on the 0-255 scale, and the ear's red-to-green "
    'ratio is >= `min_ratio` (light carrying blood colour through '
    'thin tissue is what subsurface looks like)',
    'high_frequency_energy_min': 'variance of the Laplacian over the `region` mask, on the image '
    'rendered at `scale` of display size, is >= `min` (a skin with '
    'no pores is smooth at every scale, which is the waxy signature '
    'seen from the other side)',
    'speckle_blob_stats': 'over the `region` mask, connected components more than `delta` '
    'levels darker than the local median: their count per 10000 px '
    'is within `min_density`..`max_density` AND the 95th-percentile '
    'blob area is <= `max_area_px` — many small dots are freckles, a '
    'few large patches are mottling, and the two fail differently',
    'specular_highlight_area_max': 'share of the `region` mask whose luma exceeds `luma` (0-255) is '
    '<= `max` — a broad blown highlight over the forehead and nose '
    'is the measurable half of the waxy diagnosis',
    'region_colour_distance_max': 'mean CIEDE2000 between the `region` masks of the two renders '
    'named in `between` is <= `max` (used to prove a tone was HELD '
    'constant while something else changed)',
    'strand_lag_min': 'across the ordered head-turn frames, the hair mask centroid '
    'reaches its extreme at least `min_frames` frames after the head '
    'mask centroid does, and the hair mask area changes by at least '
    '`min_area_delta` share between the first and the extreme frame '
    '(hair welded to the skull moves in lockstep and fails both)',
}


# ── the one fixed condition ───────────────────────────────────────────────────────────────
COND = {
    'repeats': 3,
    'scene': BLEND + " — the CC0 Blender Studio base body's head, in three saved lighting "
    'collections: portrait (three-point), backlit_ear (a single 3000 K key behind '
    'the ear, camera on the lit side) and eye_crop (a 4x macro on the right eye). '
    'Camera, lens, lights and world are saved in the file and never set by the '
    'runner.',
    'output': '1024x1024 PNG, RGBA, Standard view transform, plus the region masks the render '
    'script writes beside every frame (hair, iris, sclera, cheek, ear, head)',
    'settings': "the row's shipped settings, unchanged, copied verbatim into the trial — "
    'char_cycles_render renders hair as curve primitives 0.05 mm across through the '
    'Principled Hair BSDF; its own bench records 900x1125 at 128 samples at ~7 s render '
    'and ~22 s wall including the build',
    'zoom': 'every operator sheet is shown at the working zoom of 67 %, except skin_pores, which is '
    'explicitly a 200 % crop and says so in its own question',
    'timeout_s': 1800,
}

COND_NOTE = (
    'Three repeats on every probe; the FIRST is what first_take reads. A probe that times out at '
    '1800 s is a no on its columns; a Blender that will not start is untested with the error. The '
    "runner never edits heads.blend — it opens it, applies the row's own build step (install the "
    'groom, grow the field, assign the eye shader, apply the published albedo atlas) and renders.'
)

OPERATOR_PROTOCOL = [
    'The operator sees PNGs saved as A.png, B.png, C.png ... in shuffled order, with no row name, '
    'no groom id, no melanin value and no repeat index in the image or the filename; the '
    'letter-to-row map is written to disk before the sheets are shown and revealed only after every '
    'answer is saved.',
    'One written yes/no question per sheet, the wording fixed here and never improvised. A maybe is '
    'a no, and an answer may not be revised once the next sheet is open.',
    'The mechanical checks run FIRST and are a VETO: a render that fails its strand count, hue, '
    'luma, transmission, high-frequency, blob or highlight check is already a no, and its sheet is '
    'still shown blind so the operator is never told which renders machines rejected.',
]

SHOTS = [
    'portrait_front',
    'portrait_three_quarter',
    'portrait_profile',
    'head_back',
    'face_closeup',
    'hairline_closeup',
]

HAIR = ['strand_hair', 'hair_field']
SKIN = ['photoreal_skin']
EYES = ['real_eyes']
ALL = ['strand_hair', 'hair_field', 'real_eyes', 'photoreal_skin']


def _p(pid, title, feeds, checks, scene, rows=ALL, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': BLEND + '#' + scene, 'key': MANIFEST + '#' + scene, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


def _op(question):
    return {'check': 'operator', 'blind': True, 'question': question, 'when': 'render'}


PROBES = [
    _p(
        'gr_realism',
        'Six fixed shots read as a photograph of a person',
        ['realism'],
        [
            _op(
                'At 67 % zoom: does this read as a photograph of a real person rather than as a render '
                '— no plastic sheen, no doll eyes, no helmet of hair? yes/no'
            )
        ],
        'portrait',
        shots=SHOTS,
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note='Six shots x three repeats = 18 blind decisions per row. The finished-drawing '
        'portfolio rule ([[feedback_finished_build_ten_shots]]) is why this is a pass RATE '
        'over many pictures and not a verdict on one good frame.',
    ),
    _p(
        'gr_hair_strand',
        'Real strands, not cards',
        ['hair_strand'],
        [
            {'check': 'bpy_strand_count_min', 'min': 10000, 'object': 'hair', 'when': 'scene'},
            {'check': 'bpy_hair_is_curves', 'max_card_faces': 0, 'object': 'hair', 'when': 'scene'},
        ],
        'portrait',
        rows=HAIR,
        state_note='Purely mechanical: bpy counts the render-time strands and reports the geometry '
        'type. The card clause is the real question — a MakeHuman hair-card style '
        'installed through the catalogue is planks with an alpha texture, however good it '
        'looks, and this column is where that is said out loud rather than argued about. '
        '10 000 is a floor, not a target; the recorded answer is the count.',
    ),
    _p(
        'gr_hair_style',
        'Four named styles are reachable and recognisable',
        ['hair_style'],
        [
            {
                'check': 'catalogue_lists_styles',
                'when': 'scene',
                'styles': ['long straight', 'short cropped', 'tight curls', 'braided'],
            },
            _op(
                'At 67 % zoom: is the hairstyle on this head the one named above it — long straight, '
                'short cropped, tight curls or braided? yes/no'
            ),
        ],
        'portrait',
        rows=HAIR,
        grid={'style': ['long straight', 'short cropped', 'tight curls', 'braided']},
        state_note='Two halves, one column: the catalogue must OFFER the style (licence-cleared, '
        'with a fit block, or it is not reachable at all) and the render must show it. '
        'The style names are pinned in MANIFEST.styles and are BLOCKED until the operator '
        'has confirmed that each names exactly one catalogue item.',
    ),
    _p(
        'gr_hair_colour',
        'Hair colour is directable',
        ['hair_colour'],
        [
            {
                'check': 'region_hue_range',
                'region': 'hair',
                'min_sat': 0.12,
                'min': 'MANIFEST.colours[asked].hue_min',
                'max': 'MANIFEST.colours[asked].hue_max',
                'when': 'render',
            }
        ],
        'portrait',
        rows=HAIR,
        grid={'asked': ['black', 'auburn', 'ash blond']},
        state_note='Three asked colours, three renders each. Hue only, with a saturation floor, '
        'because the Principled Hair BSDF is melanin-parameterised and its lightness '
        'moves with the lighting; the asked hue window per colour is in MANIFEST.colours '
        'and is BLOCKED until the operator has measured it off a reference photograph. '
        'Mechanical alone — a hue is not something a human eye settles better.',
    ),
    _p(
        'gr_facial_hair',
        'Beards and brows are grooms too',
        ['facial_hair'],
        [
            {'check': 'bpy_strand_count_min', 'min': 2000, 'object': 'beard', 'when': 'scene'},
            {'check': 'bpy_strand_count_min', 'min': 400, 'object': 'brows', 'when': 'scene'},
            _op(
                'At 67 % zoom: do the beard and the eyebrows sit on the face like hair growing out of '
                'skin — following the jaw and the brow ridge, thinning at the edges — rather than like '
                'a shape stuck on? yes/no'
            ),
        ],
        'portrait',
        rows=HAIR,
        state_note='char_cycles_render.render() takes parts=(hair, beard, brows) and this probe asks '
        'for all three at once, because a groom path that only does scalp hair is a '
        'different capability from one that does a face.',
    ),
    _p(
        'gr_eyes_real',
        'The eye reads as an eye at 4x',
        ['eyes_real'],
        [
            _op(
                'This is a 4x macro crop of one eye. Is it a real eye — wet, with depth behind the '
                "cornea and a caustic on the iris — or a doll's eye (a flat disc behind clear glass)? "
                'Answer yes for real, no for doll.'
            )
        ],
        'eye_crop',
        rows=EYES,
        state_note='The one place this sheet leaves the 67 % working zoom on purpose: the eye is what '
        'the viewer looks at first and it is judged at the size a close-up would show it. '
        'No mechanical check exists for "reads as real", so this column is operator-only '
        'and says so.',
    ),
    _p(
        'gr_iris',
        'Iris colour lands where it was asked',
        ['iris'],
        [
            {
                'check': 'region_hue_range',
                'region': 'iris',
                'min_sat': 0.15,
                'min': 'MANIFEST.iris[asked].hue_min',
                'max': 'MANIFEST.iris[asked].hue_max',
                'when': 'render',
            },
            {'check': 'high_frequency_energy_min', 'region': 'iris', 'scale': 4.0, 'min': 90.0, 'when': 'render'},
        ],
        'eye_crop',
        rows=EYES,
        grid={'asked': ['brown', 'blue', 'green']},
        state_note='Hue for the colour and Laplacian variance over the iris mask for the DETAIL: a '
        'flat disc of the right hue passes the first check and fails the second, which is '
        'exactly the doll eye the column exists to catch. The asked hue windows are in '
        'MANIFEST.iris and are BLOCKED until verified.',
    ),
    _p(
        'gr_sclera',
        'The white of the eye is not white',
        ['sclera'],
        [
            {'check': 'region_luma_max', 'region': 'sclera', 'max': 245, 'when': 'render'},
            {'check': 'high_frequency_energy_min', 'region': 'sclera', 'scale': 4.0, 'min': 25.0, 'when': 'render'},
        ],
        'eye_crop',
        rows=EYES,
        state_note='Mean luma under 245 of 255 is the threshold: a sclera at 255 is paper, and a '
        'sclera shaded but featureless is paper with a gradient, which the variance check '
        'catches (veins, the shadow of the lid, the wet meniscus at the lower lash line).',
    ),
    _p(
        'gr_skin_sss',
        'Light goes through thin skin',
        ['skin_sss'],
        [
            {'check': 'backlit_transmission_min', 'min': 25, 'min_ratio': 1.35, 'when': 'render'},
            _op(
                'The light is behind this head. Does the ear glow red where it is thin, the way a real '
                'ear does against the sun, rather than going flat dark like card? yes/no'
            ),
        ],
        'backlit_ear',
        rows=SKIN,
        state_note='The backlit ear is the standard subsurface test because it is the one place the '
        'effect is unmistakable. The mechanical half asks for the ear to be BOTH brighter '
        'in red than the opaque cheek beside it and red-dominant; a shader with '
        'subsurface switched on but the radius set to zero fails both.',
    ),
    _p(
        'gr_skin_pores',
        'There is micro-detail at 200 %',
        ['skin_pores'],
        [{'check': 'high_frequency_energy_min', 'region': 'cheek', 'scale': 2.0, 'min': 60.0, 'when': 'render'}],
        'portrait',
        rows=SKIN,
        state_note='Deliberately measured at 200 %, not at the 67 % working zoom: pores are the one '
        'property of this sheet that is a close-up question. Laplacian variance over the '
        'cheek mask, so a noisy render cannot be told apart from a detailed one by eye — '
        'which is why the sample count is recorded in the trial beside the number.',
    ),
    _p(
        'gr_freckles',
        'Freckles, not mottling',
        ['freckles'],
        [
            {
                'check': 'speckle_blob_stats',
                'region': 'cheek',
                'delta': 12,
                'min_density': 8,
                'max_density': 140,
                'max_area_px': 40,
                'when': 'render',
            },
            _op(
                'At 67 % zoom: are these freckles — many small separate dots scattered over the cheek — '
                'or mottling, blotchy patches of uneven tone? Answer yes for freckles, no for '
                'mottling or for bare skin.'
            ),
        ],
        'portrait',
        rows=SKIN,
        state_note='Mottling is the named failure of this path, so the check is written to tell the '
        'two apart rather than to detect "spots": many small blobs pass, a few large ones '
        'fail on the 95th-percentile area even when the density looks right. The blind '
        'question is required on top, because a noisy bake produces small blobs too.',
    ),
    _p(
        'gr_waxy',
        'Not waxy',
        ['waxy'],
        [
            {'check': 'specular_highlight_area_max', 'region': 'cheek', 'luma': 235, 'max': 0.04, 'when': 'render'},
            _op(
                'At 67 % zoom: is this skin waxy — a broad soft sheen across the forehead and nose, '
                'skin with no grain, a face that looks moulded? Answer yes if it IS waxy. This is the '
                'only question on this sheet where yes is the failure.'
            ),
        ],
        'portrait',
        rows=SKIN,
        state_note='The recorded house diagnosis, asked as its own column. The mechanical half is '
        'the blown-highlight area, which is the part of "waxy" a number can hold; the '
        'grain half is the skin_pores column; the rest is the blind question. Note the '
        'inverted polarity — the runner stores the NEGATION, so the sheet reads like '
        'every other cell (yes = good).',
    ),
    _p(
        'gr_heritage',
        'Skin tone and heritage are separate dials',
        ['heritage'],
        [
            {
                'check': 'region_colour_distance_max',
                'region': 'cheek',
                'between': ['A', 'B'],
                'max': 4.0,
                'when': 'render',
            },
            {'check': 'face_identity_min', 'views': ['A', 'B'], 'max': 0.35, 'distinct': True, 'when': 'render'},
            _op(
                'These two faces were asked for the same skin tone and different features. Are they two '
                'different people with the same complexion — rather than one face twice, or two people '
                'whose complexions plainly differ? yes/no'
            ),
        ],
        'portrait',
        rows=SKIN,
        grid={'pair': ['A', 'B']},
        state_note='Two renders, one asked tone, two asked feature sets. CIEDE2000 <= 4 says the '
        'TONE was held (4 is about the point a side-by-side difference becomes obvious); '
        'ArcFace cosine <= 0.35 says the FACES really differ. A path that changes the '
        'face whenever the tone changes fails the first; a path that only repaints one '
        'face fails the second. The two characters and their asked tone are pinned in '
        'MANIFEST.heritage and are BLOCKED until the operator has verified that the two '
        'reference faces do share a tone.',
    ),
    _p(
        'gr_variation',
        'Two characters come out as two people',
        ['variation'],
        [
            {
                'check': 'face_identity_min',
                'views': ['char_1', 'char_2'],
                'max': 0.35,
                'distinct': True,
                'when': 'render',
            },
            _op(
                'Are these two visibly different individuals — different face, different hair, someone '
                'you could tell apart in a crowd — rather than one character with a changed setting? '
                'yes/no'
            ),
        ],
        'portrait',
        grid={'character': ['char_1', 'char_2']},
        state_note='ArcFace cosine below 0.35 is the house threshold for "not the same person". On '
        'the two hair rows the faces are identical by construction, so the identity check '
        'is run on the hair mask silhouette instead and the operator question decides; '
        'the trial records which of the two ran.',
    ),
    _p(
        'gr_hair_motion',
        'Hair follows the head rather than being welded to it',
        ['hair_motion'],
        [
            {'check': 'strand_lag_min', 'min_frames': 2, 'min_area_delta': 0.06, 'when': 'render'},
            _op(
                'The head turns ninety degrees over these frames. Does the hair lag and settle — moving '
                'after the skull and coming to rest a moment later — rather than turning as one solid '
                'piece with it? yes/no'
            ),
        ],
        'portrait',
        rows=HAIR,
        frames=12,
        state_note='A twelve-frame turn at 25 fps. The lag check is mechanical and cheap; the blind '
        'question catches the other failure, hair that moves but swings like a curtain of '
        'one rigid sheet.',
    ),
]

NA_BANDS = {
    'reason': 'All four rows are shaders and headless Blender build steps driven by parameters — a '
    'groom id, a melanin value, an iris hue, a published albedo atlas. There is no '
    'wording to damage, paraphrase, lengthen, translate, weight or steer, so the prompt '
    'bands measure a lever this step does not have. What the settings WERE is still '
    'measured: see `receipts` under Operability.',
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

_NO_SKIN = (
    'This row installs or grows hair. The skin it is rendered against is whatever the base '
    'body is already wearing, so an answer here would grade the photoreal_skin row twice '
    'and tell us nothing about this one.'
)
_NO_EYES = (
    'This row does not touch the eye. The eye it is rendered with is whatever the base body '
    "is already wearing, so scoring it here would attribute the eye shader's result to a "
    'groom.'
)
_NO_HAIR = (
    'This row does not produce hair. The head it is rendered on wears whatever groom the '
    "base body has, so scoring a hair property here would attribute another row's work to "
    'this one.'
)

_HAIR_NA = {c: _NO_SKIN for c in ('skin_sss', 'skin_pores', 'freckles', 'waxy', 'heritage')}
_HAIR_NA.update({c: _NO_EYES for c in ('eyes_real', 'iris', 'sclera')})

_EYES_NA = {c: _NO_HAIR for c in ('hair_strand', 'hair_style', 'hair_colour', 'facial_hair', 'hair_motion')}
_EYES_NA.update({c: _NO_SKIN for c in ('skin_sss', 'skin_pores', 'freckles', 'waxy', 'heritage')})

_SKIN_NA = {c: _NO_HAIR for c in ('hair_strand', 'hair_style', 'hair_colour', 'facial_hair', 'hair_motion')}
_SKIN_NA.update({c: _NO_EYES for c in ('eyes_real', 'iris', 'sclera')})

_FIELD_NA = dict(_HAIR_NA)
_FIELD_NA['hair_style'] = (
    "The hair field GROWS hair from the scalp's own parameters — density, "
    'length, curl — and has no catalogue of named styles to reach into. A '
    "named style is the installed-groom row's question; asking it here would "
    'score a procedural field against a list it was never given.'
)

TEST = {
    'step': 'grooms',
    'version': '2026-09-30.1',
    'title': 'One head, three lighting rigs, and the three named failure modes asked by name',
    'purpose': 'Put every hair, eye and skin path in the house on the same CC0 base head under the '
    'same saved lights, measure every property of hair, eye and skin a machine can '
    "settle, and decide the rest blind at the operator's working zoom of 67 %.",
    'include_shared': 'geometry',
    'conditions_note': COND_NOTE,
    'operator_protocol': OPERATOR_PROTOCOL,
    'shots': SHOTS,
    'rows': {
        'strand_hair': {
            'transport': 'blender',
            'where': 'character_hair_assets.catalogue() installs the groom; '
            'char_cycles_render.render(parts=(hair, beard, brows)) renders it '
            'as curve primitives 0.05 mm across through the Principled Hair '
            'BSDF ([[project_charstudio_hair_assets]], '
            '[[project_charstudio_eyes_strand_hair]])',
            'na': _HAIR_NA,
        },
        'hair_field': {
            'transport': 'blender',
            'where': "the grown hair field — ribbons raised off the clay body's own "
            "scalp field, the default unposed head's hair, rendered through "
            'the same char_cycles_render path '
            '([[project_charstudio_hair_field_zoom]])',
            'na': _FIELD_NA,
        },
        'real_eyes': {
            'transport': 'blender',
            'where': "the photoreal eye shader on the base body's eye geometry "
            '([[project_charstudio_photoreal_eye]]); rendered at the 4x eye_crop '
            'rig',
            'na': _EYES_NA,
            'budget': {
                'calls': 273,
                'minutes': 380,
                'gpu_minutes': 370,
                'operator_minutes': 134,
                'note': 'The eye rows render a 4x macro crop rather than a full '
                'head, which is cheaper per frame: 246 bank runs plus 27 '
                'domain renders (realism 18, eyes_real 3, iris 9 minus the '
                'overlap, sclera 3, variation 6) at ~1.4 min = ~380 min. '
                'Thirteen of the fifteen domain probes are na on this row, '
                "so its operator load is the bank's plus 24 decisions.",
            },
        },
        'photoreal_skin': {
            'transport': 'blender',
            'where': 'char_photoreal.py ([[project_charstudio_photoreal_skin]]) — the '
            'published albedo atlas under data/assets/mesh_packs/photoreal/'
            '<body>/ applied to the same CC0 base sculpt. Its `--stage '
            'previews` runs LAST, after plates, render, bake and publish',
            'na': _SKIN_NA,
            'budget': {
                'calls': 288,
                'minutes': 500,
                'gpu_minutes': 490,
                'operator_minutes': 148,
                'note': 'This row RENDERS from an already-published atlas; it '
                'does not rebuild one. Building the atlas is a '
                'one-off ~56 min per body (char_photoreal measured: '
                'plates 89 s CPU Cycles over 28 views, render ~33 min '
                'on the GPU, bake ~22 min CPU, publish ~40 s) and is '
                'NOT counted here because the fixture declares the '
                'published atlas as its input.',
            },
        },
    },
    'na_bands': NA_BANDS,
    'probes': PROBES,
    'derive': {
        'render_time': {
            'from': "wall-clock minutes for ONE 1024x1024 portrait frame at the row's "
            'shipped settings, median of the three repeats, with the scene-load '
            'and groom-build time of the first frame recorded SEPARATELY so a '
            "per-frame figure is not inflated by it. char_cycles_render's own "
            'bench is the receipt to check the hair rows against: 900x1125 at '
            '128 samples = ~7 s render, ~22 s wall including the build',
            'grade': 'measured',
            'unit': 'minutes per render',
        },
    },
    'lookup': {
        'order': {
            'ask': 'the written order of the character pipeline stages for this row, and '
            'specifically that the PREVIEWS stage runs LAST. For photoreal_skin that '
            "is char_photoreal.py's stage list — plates, render, bake, publish, and "
            "`--stage previews` after all of them — read off the module's own stage "
            'table and its CLI, not off a note. For a hair row it is the point in the '
            'build at which the groom is installed relative to the skin atlas. Record '
            'the file and line the order is written at, and the date read. "Not '
            'written down anywhere" is the honest answer where it is not, and is a no',
            'requires': ['module path and line of the stage table', 'the CLI stage names in order', 'date read'],
            'grade': 'receipt',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['hair_style', 'hair_colour', 'iris', 'heritage'],
            'generated': 'Written by hand beside heads.blend: `styles` (the four named hairstyles and '
            'the catalogue item id each must resolve to), `colours` (the asked hue window '
            'in degrees for black, auburn and ash blond), `iris` (the same for brown, '
            'blue and green), `heritage` (the two characters A and B, their asked shared '
            'skin tone as a Lab triple, and the feature sets that must differ), and '
            '`masks` (the region mask names the render script writes: hair, iris, sclera, '
            'cheek, ear, head).',
            'how_to_verify': 'Four checks, then set verified = true. (1) Each of the four style names '
            'resolves to exactly ONE licence-cleared item in '
            'character_hair_assets.catalogue() — the hair02 pack ships one style that '
            'declares AGPL3 in its own .mhclo header and is refused, so a style name '
            'that silently resolves to nothing would score every row a no for the '
            'wrong reason. (2) Each hue window in `colours` and `iris` was measured '
            'off a reference photograph, not guessed — a wrong window makes a correct '
            'shader fail. (3) The two heritage reference faces really do share the '
            'asked tone when measured on the cheek, or the CIEDE2000 check is '
            'comparing against a tone that never existed. (4) The mask names match '
            'what the render script actually writes. Until then those four columns '
            'are written untested with the note "key unverified".',
        },
        {
            'path': BLEND,
            'verified': True,
            'blocks': [],
            'generated': 'blender -b --factory-startup --python capability_tests/fixtures/grooms/'
            'build_heads.py -- --out capability_tests/fixtures/grooms/heads.blend — the '
            'builder appends the CC0 Blender Studio human base mesh head (the same base '
            'sculpt char_photoreal.py textures, clay, no groom, no atlas) and creates '
            'three lighting collections: portrait (three-point, the six camera markers in '
            '`shots`, plus a twelve-frame ninety-degree head turn on the armature for '
            'hair_motion), backlit_ear (one 3000 K key behind the right ear, camera on '
            'the lit side, no fill) and eye_crop (a 4x macro on the right eye at f/4). It '
            'also writes the region-mask compositor setup that produces the hair, iris, '
            'sclera, cheek, ear and head masks beside every frame. Nothing in this task '
            'creates it.',
            'how_to_verify': 'Confirm the file opens, holds all three lighting collections, and that '
            'one test frame writes all six region masks before the first run.',
        },
    ],
    'run_order': [
        'gr_hair_strand',
        'gr_hair_style',
        'gr_sclera',
        'gr_iris',
        'gr_hair_colour',
        'gr_skin_pores',
        'gr_freckles',
        'gr_waxy',
        'gr_skin_sss',
        'gr_variation',
        'gr_heritage',
        'gr_facial_hair',
        'gr_hair_motion',
        'gr_eyes_real',
        'gr_realism',
        'the geometry bank: Attributes, then the Capacity ladders last',
    ],
    'run_order_note': 'The two bpy queries (hair_strand) and the catalogue query (hair_style) need '
    'no render at all and answer two columns in seconds; the single-frame '
    'mechanical probes come next; the multi-frame and multi-render probes '
    "(hair_motion, heritage, variation, realism) after them; the geometry bank's "
    'capacity ladders, which are by far the largest item, last of all, so an '
    'interrupted run still leaves the whole Look band filled.',
    'budget': {
        'calls': 333,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'A shader takes parameters and a groom takes a file; no language model is '
        'called anywhere on this step, so no tokens are spent.',
        'minutes': 500,
        'gpu_minutes': 490,
        'operator_minutes': 150,
        'note': 'Per row. DOMAIN: 6 shots x 3 repeats (realism) + 3 hair_strand + 12 hair_style (4 '
        'styles x 3) + 9 hair_colour (3 colours x 3) + 3 facial_hair + 3 eyes_real + 9 iris '
        '(3 colours x 3) + 3 sclera + 3 skin_sss + 3 skin_pores + 3 freckles + 3 waxy + 6 '
        'heritage (2 characters x 3) + 6 variation (2 characters x 3) + 3 hair_motion (a '
        '12-frame turn each) = 87 render runs. Hair at 0.05 mm curve primitives is the slow '
        'case: char_cycles_render benches 900x1125 at 128 samples at ~22 s wall, and a '
        '1024x1024 portrait with a full groom is ~1.5 min, so ~130 min. SHARED GEOMETRY '
        'BANK: grooms does NOT ask the 132-subject Builds band or Space & relation, so what '
        'is left is 12 capacity ladders climbing up to 6 rungs x 3 seeds = ~216 runs plus 10 '
        'Attributes x 3 = 30, about 246 runs at ~1.5 min = ~370 min. Total ~500 min per row, '
        'essentially all of it GPU. OPERATOR: 18 realism + 12 hair_style + 3 facial_hair + 3 '
        'eyes_real + 3 skin_sss + 3 freckles + 3 waxy + 6 heritage + 6 variation + 3 '
        "hair_motion = 60 domain decisions, plus one blind question on each of the bank's "
        '~246 runs = ~306 decisions at 30 s = ~150 min. Two rows carry overrides because '
        'most domain probes are na on them. No claude_cli or anthropic_api row on this step, '
        'so the shared Claude week is not touched.',
    },
    'notes': [
        'The three named failure modes each got their own column and their own mechanical half: '
        'waxy is the blown-highlight area plus the blind question, freckle mottling is the blob '
        'statistic that tells small dots from large patches, and skin/heritage decoupling is '
        'CIEDE2000 on the tone against ArcFace on the faces. None of them is left to a general '
        '"does it look right".',
        'Every row renders the SAME CC0 base head, so a difference between two rows is a difference '
        'between a groom, a shader and an atlas — never between two people.',
        'skin_pores is measured at 200 % and every other blind sheet at the 67 % working zoom. That '
        'is deliberate and is written into the questions, so a run cannot quietly change the size a '
        'picture was judged at.',
        'photoreal_skin renders from a PUBLISHED atlas. Building one is a separate ~56 min job per '
        'body and the `--stage previews` step runs after all of it — that ordering is the `order` '
        'column, and it is a lookup because no render can show it.',
    ],
}
