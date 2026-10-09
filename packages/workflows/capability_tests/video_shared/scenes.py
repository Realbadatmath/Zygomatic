# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Counting, Space & relation and Attributes: one fixed scene per column."""

from __future__ import annotations

from .settings import (
    NEGATIVE,
    SAMPLE5,
    STATE_3OF3,
)
from .probes import (
    PROBES,
    _probe,
)

# ── Counting, Space & relation, Attributes: one fixed scene and one written key per column ──
SCENE_NOTE = (
    'The scene is rendered once per seed and read at frame 0 AND at the last frame. The column is '
    'yes only when both frames pass every check: an arrangement that is right at the start and '
    'wrong by the end is not an understood arrangement, it is a lucky first frame. The operator '
    'question is the key written out; the mechanical check is there so a column never passes on a '
    'generous reading alone. Where no detector can settle the thing (a barrel is not a COCO class), '
    'the operator decides and the note says so.'
)
FR2 = [0, 80]


def _scene(pid, col, title, prompt, motion, checks, cond=None, note=None):
    for c in checks:
        c.setdefault('for', col)
    return _probe(
        pid,
        title,
        [col],
        {'prompt': prompt, 'motion': motion, 'negative': NEGATIVE},
        checks,
        cond=cond,
        state_rule=STATE_3OF3,
        state_note=(note or SCENE_NOTE),
    )


def _op(q):
    return {'check': 'operator', 'question': q}


def _dc(label, n, sample=None, share=1.0):
    return {
        'check': 'detector_count',
        'detector': 'yolov8n-coco',
        'label': label,
        'n': n,
        'sample': sample or FR2,
        'share': share,
    }


PROBES += [
    _scene(
        'sc_count_exact',
        'count_exact',
        'counting: a small number exactly',
        'Three glass bottles stand in a row on a plain oak table, close-up, daylight. Nothing else on the table.',
        'the camera pushes slowly in on the three bottles',
        [
            _dc('bottle', 3),
            _op('Are there exactly three bottles — not two, not four — in both the first and the last frame? yes/no'),
        ],
    ),
    _scene(
        'sc_count_large',
        'count_large',
        'counting: past ten',
        'Twelve herring gulls stand in a row on a stone quay wall, side view, overcast daylight.',
        'the gulls shuffle a step and settle',
        [_dc('bird', 12), _op('Count the gulls in the first and the last frame. Is it exactly twelve in both? yes/no')],
    ),
    _scene(
        'sc_count_people',
        'count_people',
        'counting: people correctly',
        'Four Dutch dockworkers in brown wool coats stand apart on a stone quay, full body, daylight, 1671.',
        'each of them takes two steps and stops',
        [
            _dc('person', 4),
            _op('Are there exactly four people, and four only, in both the first and the last frame? yes/no'),
        ],
    ),
    _scene(
        'sc_count_fingers',
        'count_fingers',
        'counting: fingers correctly',
        'One open human hand held up palm towards the camera, fingers spread, plain background, soft daylight.',
        'the hand turns slowly to show the back, fingers still spread',
        [
            {'check': 'hand_landmarks_count', 'hands': 1, 'fingers': 5, 'sample': SAMPLE5, 'share': 0.8},
            _op(
                'Does the hand have exactly five fingers — four fingers and one thumb, none fused, none extra, none missing — at every point in the clip? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_count_legs',
        'count_legs',
        'counting: legs on an animal',
        'One brown horse stands side-on in a cobbled Dutch street, full body, daylight, 1671.',
        'the horse walks four steps to the left and stops',
        [
            _dc('horse', 1),
            _op(
                'Does the horse have exactly four legs throughout — no fifth leg, no missing leg, no leg fusing into another as it walks? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_count_windows',
        'count_windows',
        'counting: repeated architecture',
        'A Dutch brick house front with exactly six leaded windows, three on each of two floors, flat on to the camera, daylight, 1671.',
        'the camera pushes slowly in on the house front',
        [
            _op(
                'Count the windows in the first and the last frame. Is it exactly six, in two rows of three, in both? yes/no'
            ),
            {
                'check': 'flicker_max',
                'max': 12.0,
                'note': 'a facade whose windows churn between frames has not repeated anything',
            },
            _op(
                'Do the six windows stay in the same places for the whole clip — none appearing, disappearing or sliding? yes/no'
            ),
        ],
        note="No detector counts windows, so both checks here are the operator's, asked separately (how many, and do they hold still). "
        + SCENE_NOTE,
    ),
    _scene(
        'sc_count_absent',
        'count_absent',
        'counting: says when a thing is NOT there',
        'An empty stone quay in a Dutch harbour town at dawn. No birds anywhere. No people. Bare stone and water.',
        'the camera pans slowly along the empty quay',
        [
            _dc('bird', 0, sample=SAMPLE5),
            _dc('person', 0, sample=SAMPLE5),
            _op('Is the quay empty of birds and people in every frame — not one gull, not one figure? yes/no'),
        ],
    ),
    _scene(
        'sc_count_more_less',
        'count_more_less',
        'counting: more versus fewer',
        'On a stone quay: four glass bottles on the left half of the frame and one glass bottle on the right half. Daylight, wide shot.',
        'the camera holds still while a gust moves the water behind',
        [
            _dc('bottle', 5),
            _op(
                'Are there clearly MORE bottles on the left than on the right — four against one — in both the first and the last frame? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_sp_left_right',
        'sp_left_right',
        'space: left and right',
        'A red barrel on the left and a blue barrel on the right, side by side on a stone quay, wide shot, daylight.',
        'the camera holds still; gulls cross the sky behind',
        [
            {
                'check': 'named_colour_region',
                'region': 'the left barrel',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': FR2,
            },
            {
                'check': 'named_colour_region',
                'region': 'the right barrel',
                'colour': 'blue',
                'tolerance_deg': 25,
                'sample': FR2,
            },
            _op(
                'Is the RED barrel on the left and the BLUE barrel on the right — not swapped — in both the first and the last frame? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_sp_front_behind',
        'sp_front_behind',
        'space: in front of and behind',
        'A wooden hand cart in front of a brick wall, and one herring gull standing behind the cart so the cart hides its legs. Daylight, 1671.',
        'the gull steps sideways but stays behind the cart',
        [
            _dc('bird', 1, sample=SAMPLE5),
            _op(
                'Is the cart in front of the wall, and the gull behind the cart with its legs hidden by the cart, in both the first and the last frame? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_sp_on_under',
        'sp_on_under',
        'space: on top of and underneath',
        'A cat sitting on top of a plain oak table and a dog lying underneath the same table, side view, interior daylight.',
        'the cat turns its head; the dog stays lying down',
        [
            _dc('cat', 1),
            _dc('dog', 1),
            _op(
                'Is the cat ON the table and the dog UNDER it — not both on, not both under, not swapped — in both the first and the last frame? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_sp_inside',
        'sp_inside',
        'space: inside and outside',
        'An open wooden crate with a tin lantern inside it, and a second tin lantern standing on the ground outside the crate. Close-up, daylight.',
        'the camera pushes slowly in on the crate',
        [
            _op(
                'Is one lantern INSIDE the crate and the other OUTSIDE it on the ground — two lanterns, one in, one out — in both the first and the last frame? yes/no'
            ),
            {'check': 'flicker_max', 'max': 12.0},
        ],
        note='No detector settles containment; the operator decides, with the flicker ceiling to catch a crate that reforms each frame. '
        + SCENE_NOTE,
    ),
    _scene(
        'sc_sp_near_far',
        'sp_near_far',
        'space: near and far',
        'Two identical fishing boats on the water: one close to the camera filling the lower half of the frame, one far away near the horizon. Daylight.',
        'the camera holds still; both boats rock gently on the water',
        [
            _dc('boat', 2),
            {
                'check': 'bbox_frac',
                'subject': 'the near boat',
                'min': 0.35,
                'max': 0.95,
                'sample': FR2,
                'detector': 'yolov8n-coco',
            },
            {
                'check': 'bbox_frac',
                'subject': 'the far boat',
                'min': 0.0,
                'max': 0.12,
                'sample': FR2,
                'detector': 'yolov8n-coco',
            },
            _op(
                'Is one boat clearly near and the other clearly far away, both present, in the first and the last frame? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_sp_touching',
        'sp_touching',
        'space: touching versus apart',
        'Two human hands on a plain oak table: the two index fingers touching tip to tip, everything else apart. Close-up, soft daylight.',
        "the hands hold the touch, then draw apart a hand's width and stop",
        [
            {'check': 'hand_landmarks_count', 'hands': 2, 'sample': SAMPLE5, 'share': 0.8},
            _op(
                'At the start, are the two index fingertips touching, and by the end are the hands clearly apart — and are both hands whole throughout? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_sp_holding_who',
        'sp_holding_who',
        'space: which person holds the object',
        'Two Dutch dockworkers stand side by side on a stone quay. The one on the LEFT holds a pewter tankard in his right hand. The one on the right holds nothing. Daylight, 1671.',
        'the man on the left raises the tankard; the other keeps his hands at his sides',
        [
            _dc('person', 2),
            _op(
                "Is the tankard held by the man on the LEFT, and are the right-hand man's hands empty, in both the first and the last frame? yes/no"
            ),
        ],
    ),
    _scene(
        'sc_sp_relative_size',
        'sp_relative_size',
        'space: relative size of two things',
        'A wooden barrel standing beside a wooden crate on a stone quay. The barrel is twice as tall as the crate. Wide shot, daylight.',
        'the camera holds still; a gull lands on the barrel',
        [
            _op(
                'Is the barrel about twice the height of the crate — clearly bigger, not the same size, not smaller — in both the first and the last frame? yes/no'
            ),
            {'check': 'flicker_max', 'max': 12.0},
        ],
        note="Neither object is a detector class, so the size relation is the operator's call. " + SCENE_NOTE,
    ),
    _scene(
        'sc_sp_occlusion',
        'sp_occlusion',
        'space: what is hidden behind what',
        'One herring gull standing directly behind a stone bollard on a quay, so only its head and tail show past the bollard. Daylight.',
        'the gull stays where it is; the camera drifts slowly to the right',
        [
            _op(
                'Is the gull behind the bollard with its middle hidden by it — and does the hidden part stay hidden as the camera moves, rather than the gull sliding in front or the bollard turning transparent? yes/no'
            ),
            {
                'check': 'flow_direction',
                'direction': 'left',
                'min': 0.4,
                'note': 'the camera drift is what makes occlusion testable; if the frame did not move, the trial is untested, not a no',
            },
        ],
    ),
    _scene(
        'sc_sp_direction',
        'sp_direction',
        'space: which way something faces',
        'One Dutch dockworker standing on a stone quay with his back to the camera, facing out to the water. Full body, daylight, 1671.',
        'he stays facing the water and raises one arm to point at a boat',
        [
            _dc('person', 1),
            _op(
                'Is the man facing AWAY from the camera — his back to us, no face visible — for the whole clip? yes/no'
            ),
        ],
    ),
]

PROBES += [
    _scene(
        'sc_at_colour_named',
        'at_colour_named',
        'attributes: a named colour lands on the named thing',
        'One Dutch woman in a RED wool cloak stands on a stone quay, everything else grey stone and grey water, full body, daylight, 1671.',
        'she turns once on the spot and stops',
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
            },
            _op(
                'Is the cloak red — and is it the CLOAK that is red, not the stones, the water or her face — for the whole clip? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_at_colour_two',
        'at_colour_two',
        'attributes: two different colours on two things',
        'One Dutch woman in a RED wool cloak and a BLUE linen cap stands on a stone quay, full body, daylight, 1671.',
        'she turns once on the spot and stops',
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
            },
            {
                'check': 'named_colour_region',
                'region': 'the cap',
                'colour': 'blue',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
            },
            _op(
                'Is the cloak red AND the cap blue — not both red, not both blue, not swapped — for the whole clip? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_at_material',
        'at_material',
        'attributes: the right material',
        'A COPPER kettle on a plain oak table, close-up, interior daylight. Bright warm copper, not tin, not iron, not brass.',
        'the camera pushes slowly in on the kettle',
        [
            {
                'check': 'named_colour_region',
                'region': 'the kettle',
                'colour': 'orange',
                'tolerance_deg': 30,
                'sample': FR2,
                'note': 'copper reads as an orange-brown hue; this catches a grey tin or iron kettle mechanically',
            },
            _op(
                "Is the kettle copper — warm reddish metal with copper's soft sheen — rather than tin, iron, brass or painted wood? yes/no"
            ),
        ],
    ),
    _scene(
        'sc_at_texture',
        'at_texture',
        'attributes: the right surface texture',
        'A rough sawn oak plank with a visible saw-tooth surface and raised grain, close-up, raking daylight across the surface.',
        'the camera tracks slowly along the plank surface',
        [
            _op(
                'Is the wood clearly ROUGH SAWN — saw marks and raised grain visible under the raking light — rather than smooth, planed or polished? yes/no'
            ),
            {
                'check': 'flicker_max',
                'max': 12.0,
                'note': 'a texture that re-invents itself every frame is not a texture',
            },
        ],
        note='Texture has no detector. The raking light is in the prompt so there is something for the operator to see. '
        + SCENE_NOTE,
    ),
    _scene(
        'sc_at_age_object',
        'at_age_object',
        'attributes: new versus old',
        'Two ropes side by side on a stone quay: on the left a BRAND NEW pale hemp rope, tight and clean; on the right an OLD rope, frayed, dark and stiff with tar. Close-up, daylight.',
        'a hand enters and lifts the old rope, then puts it down',
        [
            _op(
                'Is the LEFT rope clearly new — pale, tight, unfrayed — and the RIGHT rope clearly old — frayed, darkened, stiff? Both, in both the first and the last frame? yes/no'
            ),
            {
                'check': 'hand_landmarks_count',
                'hands': 1,
                'sample': [40, 60],
                'share': 0.5,
                'note': 'the hand is in the prompt so the clip has to move; it also gives the hand checker something to fail on',
            },
        ],
    ),
    _scene(
        'sc_at_size',
        'at_size',
        'attributes: the right size',
        'A small pewter tankard held in one human hand, the tankard no taller than the palm, close-up, soft daylight.',
        'the hand turns the tankard once to show its side',
        [
            {
                'check': 'bbox_frac',
                'subject': 'the tankard',
                'min': 0.05,
                'max': 0.45,
                'sample': FR2,
                'detector': 'sam2-hiera-small',
            },
            _op(
                'Is the tankard hand-sized — no taller than the palm that holds it — rather than a barrel-sized vessel or a thimble? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_at_state',
        'at_state',
        'attributes: open versus shut, lit versus dark',
        'A wooden door standing WIDE OPEN in a brick wall, and beside it a tin lantern with its candle LIT, burning. Dusk, close-up.',
        'the door stays open and the candle flame flickers',
        [
            _op(
                'Is the door OPEN — not shut, not ajar — and is the lantern candle LIT and burning, in both the first and the last frame? yes/no'
            ),
            {'check': 'motion_min', 'min': 0.6, 'note': 'a lit flame moves; a painted-on flame does not'},
        ],
    ),
    _scene(
        'sc_at_wet_dry',
        'at_wet_dry',
        'attributes: wet versus dry',
        'Cobblestones in the foreground soaking WET and reflecting the sky, and a stone doorstep behind them completely DRY and matt. Overcast daylight, close-up.',
        'the camera drifts slowly forward over the wet cobbles',
        [
            _op(
                'Are the foreground cobbles clearly wet — dark and reflecting — and the doorstep behind clearly dry and matt, in both the first and the last frame? yes/no'
            ),
            {
                'check': 'flow_direction',
                'direction': 'in',
                'min': 0.4,
                'note': 'the forward drift is what makes the reflection testable; no camera move means untested, not a no',
            },
        ],
    ),
    _scene(
        'sc_at_clean_dirty',
        'at_clean_dirty',
        'attributes: clean versus dirty',
        'A clean white linen apron hanging on a hook, and directly below it a boot caked thick with brown mud. Interior daylight, close-up.',
        'the apron stirs in a draught; the boot stays still',
        [
            {
                'check': 'named_colour_region',
                'region': 'the apron',
                'colour': 'white',
                'tolerance_deg': 0,
                'sample': FR2,
                'note': 'white is checked as low saturation and high value, not as a hue (COLOUR_HUES white is None)',
            },
            _op(
                'Is the apron clean white — unmarked — and the boot thickly caked with mud, in both the first and the last frame? yes/no'
            ),
        ],
    ),
    _scene(
        'sc_at_emotion',
        'at_emotion',
        'attributes: the named emotion on the face',
        "Close-up of one Dutch dockworker's face, clearly FRIGHTENED: eyes wide, mouth open, brows raised. Daylight, 1671.",
        'the frightened expression holds and he draws a sharp breath',
        [
            _dc('person', 1, sample=SAMPLE5),
            {
                'check': 'identity_cosine_min',
                'a': 0,
                'b': -1,
                'min': 0.35,
                'detector': 'insightface-buffalo_l',
                'note': 'an expression that changes the face into a different person is not the named emotion',
            },
            _op(
                "Does the face read as FRIGHTENED — not angry, not surprised, not neutral — for the whole clip, on a face that stays the same man's face? yes/no"
            ),
        ],
    ),
]
