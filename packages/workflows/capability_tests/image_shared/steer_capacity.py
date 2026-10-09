# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.steer_capacity — steering probes and the capacity counts read off a ladder."""

from __future__ import annotations

from capability_tests.image_shared.probes import PROBES, _probe
from capability_tests.image_shared.prompt_ladders import CLARITY_LADDER

# ── Prompt: steering ───────────────────────────────────────────────────────────────────────
STEER_BASE = (
    'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, '
    'whole body in frame, facing the camera, an unlit lantern in his right hand.'
)

PROBES += [
    _probe(
        'pd_edit_chain',
        'Prompt steering: one word changed at the same seed',
        ['pd_small_edit', 'pd_fix_lands', 'pd_fix_breaks'],
        STEER_BASE,
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'open_vocab_present', 'terms': ['candle'], 'min_score': 0.3},
            {'check': 'open_vocab_absent', 'terms': ['lantern'], 'min_score': 0.3},
            {'check': 'image_distance', 'to': 'pd_edit_chain:base', 'metric': 'lpips', 'max': 0.35},
            {
                'check': 'operator',
                'question': 'Apart from the object in his right hand, is this the same picture as the other one — same man, same pose, same quay, same light? yes/no',
            },
        ],
        chain=[
            'base: STEER_BASE at seed 11',
            'edit: the same prompt with "an unlit lantern" replaced by "a lit candle", '
            'same seed 11, nothing else changed',
            'fix: the base prompt plus ", both his hands whole with five fingers each", same seed 11',
        ],
        reads={
            'pd_small_edit': 'the edit run: yes if the candle arrives AND lpips to base is <= 0.35 (only the hand changed), partial if the candle arrives but the whole frame moved, no if the candle does not arrive.',
            'pd_fix_lands': 'the fix run: yes if MediaPipe finds one or two hands with five separated fingertips each where the base run did not, partial if it improves on one seed of three.',
            'pd_fix_breaks': 'the fix run against the base: yes if NOTHING else broke (person count still 1, lantern still there, operator says same picture), no if fixing the hands cost the lantern or the pose. yes here is good.',
        },
        state_note='One chain at ONE seed, because a steering question asked across seeds '
        'measures the seed. lpips carries "did only the intended thing change"; '
        'MediaPipe carries the hand fix; the operator carries everything a metric '
        'cannot see. The checks as written are the edit run; the trial holds all '
        'three runs and the runner applies each cell own rule.',
    ),
    _probe(
        'pd_seed_vs_prompt',
        'Prompt steering: does the seed or the prompt decide the picture',
        ['pd_seed_vs_prompt'],
        STEER_BASE,
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'image_distance',
                'to': 'pd_seed_vs_prompt:same_seed_other_prompt',
                'metric': 'lpips',
                'min': 0.45,
            },
            {
                'check': 'image_distance',
                'to': 'pd_seed_vs_prompt:other_seed_same_prompt',
                'metric': 'lpips',
                'max': 0.45,
            },
        ],
        grid={
            'same_prompt_seeds': 'STEER_BASE at seeds 11, 12, 13',
            'same_seed_prompts': 'seed 11 with STEER_BASE, with the lantern swapped for a '
            'coil of rope, and with the quay swapped for a farmhouse '
            'yard',
        },
        state_note='A 3x3 grid of lpips distances, no operator. yes means the PROMPT decides: '
        'changing the prompt at a fixed seed moves the picture further than '
        'changing the seed at a fixed prompt. no means the seed decides, and the '
        'row must then be driven by seed search rather than by prompt writing — '
        'which is a scheduling fact, not a defect.',
    ),
    _probe(
        'pd_reusable',
        'Prompt steering: does a working prompt survive a change of subject',
        ['pd_reusable'],
        CLARITY_LADDER[4],
        [
            {'check': 'open_vocab_count', 'query': 'wicker basket', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wicker basket', 'colour': 'brown', 'min_share': 0.3},
            {'check': 'detector_count', 'class': 'person', 'count': 0},
            {
                'check': 'operator',
                'question': 'Is this the same kind of picture as the other one — same 1671 quay, same plain light, one object, nobody present? yes/no',
            },
        ],
        pair=[
            'the rung-5 brief with its red barrel',
            'the same brief word for word with "a red barrel bound with three iron hoops" '
            'replaced by "a brown wicker basket"',
        ],
        state_note='The scaffold is held word for word and only the subject moves. yes means '
        'the brief is a TEMPLATE the house can reuse; no means it only worked for '
        'the barrel. Mechanical on the object and the emptiness, operator on '
        '"same kind of picture".',
    ),
    _probe(
        'pd_pos_neg_split',
        'Prompt steering: does the fix belong in the positive or the negative',
        ['pd_pos_neg_split'],
        'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, whole '
        'body in frame, facing the camera, bare-headed.',
        [
            {'check': 'open_vocab_absent', 'terms': ['hat', 'cap'], 'min_score': 0.3},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
        ],
        pair=[
            'positive: ", bare-headed" in the prompt, the shared negative unchanged',
            'negative: the prompt without ", bare-headed", and "hat, cap" added to the front of the negative prompt',
        ],
        state_note='The standing house rule from the Arcane full-frame work is that the fix '
        'goes in the NEGATIVE, and this cell is where that rule is checked per '
        'row instead of assumed. Wholly mechanical. yes means the negative half '
        'wins (the house rule holds), partial means both halves work, no means '
        'only the positive works and this row is the exception.',
    ),
    _probe(
        'pd_verbatim',
        'Prompt steering: an instruction carried word for word against reworded',
        ['pd_verbatim'],
        'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, whole '
        'body in frame, facing the camera, in a dark green wool coat.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wool coat', 'colour': 'green', 'min_share': 0.4},
            {
                'check': 'operator',
                'question': 'Is the coat the only green garment, with the rest of the clothing left as it was in the other picture? yes/no',
            },
        ],
        pair=[
            'verbatim: the clause "in a dark green wool coat" exactly as written',
            'paraphrased: the same clause reworded as "wearing a coat of dark green wool, woollen and green and dark"',
        ],
        state_note='The receipt for this column is the i2i work where a verbatim instruction '
        'recoloured nothing it was not asked to and the paraphrase recoloured the '
        'whole costume, so the pair measures SPREAD, not just arrival: the colour '
        'must land on the coat (mechanical) and nothing else (operator). yes '
        'means verbatim is safe and the paraphrase is not; partial means both '
        'behave; no means the row cannot hold a garment colour either way.',
    ),
]

# ── Capacity — every cell is a COUNT read off a ladder ─────────────────────────────────────
QUAY = 'on the stone quay at Kattenburg, Amsterdam, 1671, plain daylight'
CAP_NOTE = (
    'A capacity cell is a NUMBER, not a yes/no: the HIGHEST rung whose checks pass on 3/3 seeds '
    '(2/3 writes the number with a partial state). The runner climbs the ladder from the bottom '
    'and stops two rungs after the first failure, so one bad seed does not end the climb. Every '
    'rung is rendered at the fixed settings; only the count in the prompt moves.'
)

PROBES += [
    _probe(
        'cap_people',
        'Capacity: how many whole people in one frame',
        ['cap_people'],
        'Three Dutch dockworkers stand in a row ' + QUAY + ', all whole bodies in frame, facing the camera.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 3},
            {
                'check': 'operator',
                'question': 'Is every person in this picture whole and separate — no merged bodies, no extra or missing limbs, no half figures? yes/no',
            },
        ],
        ladder=[1, 2, 3, 5, 8, 12],
        ladder_rule='rung N writes the number as a word and the person count check becomes N',
        unit='count',
        state_note=CAP_NOTE + ' YOLO decides the number; the operator decides '
        'whether the bodies are whole, which is where this ladder really ends.',
    ),
    _probe(
        'cap_named',
        'Capacity: how many distinct named people stay distinct',
        ['cap_named'],
        'Two Dutch dockworkers stand ' + QUAY + ': Jan, a thin bearded man in a red cap, and '
        'Piet, a heavy clean-shaven man in a blue coat, both whole bodies in frame.',
        [
            {'check': 'detector_count', 'class': 'face', 'count': 2},
            {'check': 'identity_cosine_min', 'ref': 'cap_named:rung1', 'min': 0.35},
            {
                'check': 'operator',
                'question': 'Does every person match the description the prompt gave their name — the right build, beard and garment on each? yes/no',
            },
        ],
        ladder=[1, 2, 3, 4, 5],
        ladder_rule='rung N names the first N of: Jan (thin, bearded, red cap), Piet (heavy, '
        'clean-shaven, blue coat), Klaas (young, fair, white apron), Dirk (old, '
        'grey, black hat), Willem (tall, dark, green scarf).',
        unit='count',
        state_note=CAP_NOTE + ' ArcFace is the mechanical half and it answers a narrower '
        'question than the column: whether the person the prompt calls Jan is the SAME face '
        'as rung 1 Jan (cosine >= 0.35 on buffalo_l). Whether each named person matches their '
        'own description is the operator. Both must hold.',
    ),
    _probe(
        'cap_faces',
        'Capacity: how many usable faces in one frame',
        ['cap_faces'],
        'Three Dutch dockworkers stand shoulder to shoulder ' + QUAY + ', all three faces '
        'turned to the camera and fully visible.',
        [
            {'check': 'detector_count', 'class': 'face', 'count': 3},
            {
                'check': 'operator',
                'question': 'Is every face in this picture whole and correct — two eyes, one nose, one mouth, nothing melted or doubled? yes/no',
            },
        ],
        ladder=[1, 2, 3, 5, 8],
        ladder_rule='rung N asks for N dockworkers with N faces to camera',
        unit='count',
        state_note=CAP_NOTE + ' InsightFace finds the faces; only the operator '
        'can say a found face is not ruined, and on the 2026-09-27 bench no local judge could.',
    ),
    _probe(
        'cap_hands',
        'Capacity: how many correct hands in one frame',
        ['cap_hands'],
        'Two Dutch dockworkers stand ' + QUAY + ', all four of their hands open, empty and '
        'clearly visible at their sides, palms to the camera.',
        [
            {'check': 'hand_landmarks', 'hands': 4, 'min_tip_px': 10},
            {
                'check': 'operator',
                'question': 'Does every hand in this picture have exactly five separate fingers, correctly jointed? yes/no',
            },
        ],
        ladder=[1, 2, 4, 6, 8],
        ladder_rule='rung N asks for N open hands, N/2 people rounded up',
        unit='count',
        state_note=CAP_NOTE + ' MediaPipe hand_landmarker is the only detector the house '
        'trusts on hands, and it is authority for the COUNT and the five fingertips. The '
        'operator still answers, because a hand with five landmarks can be jointed backwards.',
    ),
    _probe(
        'cap_objects',
        'Capacity: how many separate objects stay separate',
        ['cap_objects'],
        'Three things stand apart from one another ' + QUAY + ': a red barrel, a blue crate, '
        'a coiled rope, nobody present.',
        [
            {
                'check': 'open_vocab_present',
                'terms': ['wooden barrel', 'wooden crate', 'coiled rope'],
                'min_score': 0.3,
            },
            {'check': 'detector_count', 'class': 'person', 'count': 0},
        ],
        ladder=[3, 5, 8, 12, 16, 24],
        ladder_rule='the same ordered object list as pd_unique_things, but the prompt says '
        'the things stand APART from one another and the operator question asks '
        'whether they are separate rather than merged.',
        unit='count',
        state_note=CAP_NOTE + ' This column and pd_unique_things climb the same object list '
        'for different reasons: pd_unique_things asks whether the model READS N terms, this '
        'asks whether N things survive as N things in one frame. Both cells cite the other.',
    ),
    _probe(
        'cap_words',
        'Capacity: how many legible words in one frame',
        ['cap_words'],
        'A painted notice board ' + QUAY + ', reading HARING TE KOOP in plain black capitals '
        'on one line, nothing else written anywhere in the picture.',
        [{'check': 'ocr_equals', 'text': 'HARING TE KOOP'}],
        ladder=[1, 2, 3, 5, 8],
        ladder_rule='rung N paints the first N words of "HARING TE KOOP OP DE WERF VAN '
        'KATTENBURG" and the ocr_equals text is exactly those N words.',
        unit='count',
        state_note=CAP_NOTE + ' Wholly mechanical: PaddleOCR reads the board and the text '
        'either equals the key or it does not. A frame with the right words plus invented '
        'extra lettering FAILS ocr_equals, which is correct — invented lettering is a defect.',
    ),
    _probe(
        'cap_digits',
        'Capacity: how many correct digits in one frame',
        ['cap_digits'],
        'A painted white board on a brick wall, Amsterdam, 1671, plain daylight, the digits '
        '1671 painted on it in plain black, nothing else written anywhere.',
        [{'check': 'ocr_equals', 'text': '1671'}],
        ladder=[1, 2, 3, 4, 6],
        ladder_rule='rung N paints the first N digits of 167142: 1, 16, 167, 1671, 167142.',
        unit='count',
        state_note=CAP_NOTE + ' Wholly mechanical. Digits fail differently from words — a '
        'model that renders 1B71 fails here and the trial keeps what OCR actually read, so '
        'the sheet can say what went wrong rather than only that it did.',
    ),
    _probe(
        'cap_animals',
        'Capacity: how many whole animals in one frame',
        ['cap_animals'],
        'Three sheep stand together in a flat grass field, Holland, 1671, plain daylight, all '
        'three whole bodies in frame, seen from the side.',
        [
            {'check': 'detector_count', 'class': 'sheep', 'count': 3},
            {
                'check': 'operator',
                'question': 'Is every animal whole and separate — four legs each, one head each, no merged or extra parts? yes/no',
            },
        ],
        ladder=[1, 2, 3, 5, 8],
        ladder_rule='rung N asks for N sheep and the sheep count becomes N',
        unit='count',
        state_note=CAP_NOTE + ' Sheep because YOLO-COCO has the class and the '
        'house world has the animal. Legs are the failure and only the operator sees them.',
    ),
    _probe(
        'cap_prompt_terms',
        'Capacity: how many prompt terms are still obeyed at once',
        ['cap_prompt_terms'],
        'A red barrel ' + QUAY + ', iron hoops, wet cobbles, a brick gable behind, nobody present.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
            {'check': 'detector_count', 'class': 'person', 'count': 0},
        ],
        ladder=[4, 8, 12, 16, 24, 32],
        ladder_rule='rung N carries N comma-separated terms, added in a fixed order, each '
        'with its own mechanical or operator test: the object, its colour, its '
        'hoops, the emptiness, the wet cobbles, the gable, three gulls, the '
        'HARING lettering, a blue crate to the right, a lantern on the wall, and '
        'so on down the list in pd_unique_things. Rung N is scored on ALL N.',
        unit='count',
        state_note=CAP_NOTE + ' This is the honest version of "how long a prompt can be": '
        'not how many words the encoder swallows (pd_max_soft) but how many INSTRUCTIONS are '
        'still true in the frame. The two cells are expected to disagree and the notes say so.',
    ),
    _probe(
        'cap_res',
        'Capacity: how large a frame the row still renders correctly',
        ['cap_res'],
        'A Dutch shipwright stands alone ' + QUAY + ', whole body in frame, facing the camera.',
        [
            {'check': 'render_returned'},
            {'check': 'image_size', 'width': 1024, 'height': 1024},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'operator',
                'question': 'Is this picture free of a repeated or doubled body, a second head, or a seam across the frame? yes/no',
            },
        ],
        ladder=[1024, 1280, 1536, 2048, 3072],
        ladder_rule='rung R renders R x R, and the image_size check becomes R x R; nothing '
        'else changes. The ONE probe in this bank that moves the frame size.',
        unit='count',
        state_note=CAP_NOTE + ' The cell is the largest square in PIXELS. Mechanical on the '
        'size, the return and the person count; the operator carries the failure that matters '
        'at high resolution, which is the doubled body SDXL produces past its training size. '
        'An out-of-memory error is untested for that rung with the error, not a no.',
    ),
    _probe(
        'cap_panels',
        'Capacity: how many panels of one sheet come out usable',
        ['cap_panels'],
        'A sheet of two panels side by side, each showing the same Dutch shipwright '
        + QUAY
        + ', 1671, plain daylight: in the left panel he stands facing the camera, in the right '
        'panel he stands in profile. A plain white gutter between the panels.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 2},
            {
                'check': 'operator',
                'question': 'Does this sheet have the number of panels asked for, each holding one whole figure, with clean gutters and no figure crossing a gutter? yes/no',
            },
        ],
        ladder=[2, 4, 6, 9, 12],
        ladder_rule='rung N asks for an N-panel sheet in a fixed arrangement (2 side by side, '
        '2x2, 2x3, 3x3, 3x4) with the same man in a listed pose per panel; the '
        'person count check becomes N.',
        unit='count',
        state_note=CAP_NOTE + ' A contact sheet in one render is how the house makes pose '
        'sheets, so the capacity is worth a column. YOLO counts the figures; only the '
        'operator can see a gutter a figure has walked through.',
    ),
    _probe(
        'cap_cells_clean',
        'Capacity: how many cells of a nine-cell sheet are clean',
        ['cap_cells_clean'],
        'A sheet of nine panels in three rows of three, each showing the same Dutch shipwright '
        + QUAY
        + ', 1671, plain daylight, one listed pose per panel, plain white gutters '
        'between all panels.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 9},
            {
                'check': 'operator',
                'question': 'Is THIS cell clean — one whole figure, correct pose, nothing crossing its edges, no second figure? yes/no',
            },
        ],
        unit='count',
        state_note=CAP_NOTE.replace(
            'the HIGHEST rung whose checks pass on 3/3 seeds', 'the NUMBER OF CELLS the operator passes'
        )
        + ' No ladder: one fixed nine-cell sheet, and the cell is how many of the nine the '
        'operator passes, averaged over the three seeds and rounded down. The operator is '
        'shown the nine cells cut apart, shuffled, without the sheet — so a sheet that looks '
        'good as a whole cannot carry a bad cell.',
    ),
]
