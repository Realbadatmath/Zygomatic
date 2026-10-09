# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.subjects_people_body — SUBJECTS: People (12) and The body (19).

Verbatim from the former geometry_shared.py, lines 198-437.
"""

from __future__ import annotations

from .constants import _hands, _mat, _people

# ── SUBJECTS ──────────────────────────────────────────────────────────────────────────────
# column id -> (label, prompt, (shell_min, shell_max), (axis, min_m, max_m), extras)
#   label    the operator's noun, dropped into the blind question verbatim
#   prompt   VERBATIM, under 40 words, the same text for every model in every geometry step
#   shells   expected connected components. A range, because a generator may split a subject
#            into body panels; the LOWER bound is what catches fusing (three barrels that come
#            out as one shell is the defect this band exists to find).
#   size     ('y', lo, hi) is standing height in metres; ('max', lo, hi) is the longest bbox
#            edge, used where the subject has no meaningful upright height.
#   extras   the mechanical detector check beside the operator's blind yes/no, or None.
SUBJECTS = {
    # ── People (12) ──
    'model_person_one': (
        'one person',
        'One standing adult man in a plain linen shirt and breeches, barefoot, arms at his sides, feet apart, looking straight ahead. One figure only.',
        (1, 8),
        ('y', 1.55, 2.00),
        _people(1),
    ),
    'model_person_two': (
        'two people standing together',
        'Two standing adults side by side, half a metre apart, both in plain period clothing, arms at their sides, facing the same way. Two separate figures.',
        (2, 16),
        ('y', 1.55, 2.00),
        _people(2),
    ),
    'model_person_three': (
        'three people',
        'Three standing adults in a row, half a metre between each, plain period clothing, all facing the same way. Three separate figures.',
        (3, 24),
        ('y', 1.55, 2.00),
        _people(3),
    ),
    'model_person_group': (
        'a group of five people',
        'Five standing adults in a loose group on flat ground, plain period clothing, none touching another. Five separate figures.',
        (5, 40),
        ('y', 1.55, 2.00),
        _people(5),
    ),
    'model_person_crowd': (
        'a crowd of twelve people',
        'Twelve standing adults filling a square of flat ground four metres across, plain period clothing, none touching another. Twelve separate figures.',
        (12, 96),
        ('y', 1.55, 2.00),
        _people(12),
    ),
    'model_child': (
        'a child',
        'One standing child of about eight years, plain shirt and trousers, barefoot, arms at the sides, looking straight ahead.',
        (1, 8),
        ('y', 1.05, 1.45),
        _people(1),
    ),
    'model_infant': (
        'an infant',
        'One infant of about one year, seated on the ground, wrapped in a plain cloth, head up.',
        (1, 6),
        ('max', 0.35, 0.80),
        _people(1),
    ),
    'model_teen': (
        'a teenager',
        'One standing teenager of about fifteen, plain shirt and trousers, barefoot, arms at the sides, looking straight ahead.',
        (1, 8),
        ('y', 1.45, 1.80),
        _people(1),
    ),
    'model_elderly': (
        'an elderly person',
        'One standing elderly man, stooped, leaning on a plain wooden stick, long coat, lined face, thin hair.',
        (2, 10),
        ('y', 1.40, 1.85),
        _people(1),
    ),
    'model_person_back': (
        'a person seen from behind',
        'One standing adult seen from behind, plain coat, hands clasped behind the back, head facing away from the viewer.',
        (1, 8),
        ('y', 1.55, 2.00),
        [{'check': 'bbox_facing', 'heading': 180, 'tolerance': 25, 'when': 'glb'}],
    ),
    'model_person_distant': (
        'a small distant figure on a large ground plane',
        'One standing adult on a flat square of ground twenty metres across, the figure at the far corner. Ground and figure as separate objects.',
        (2, 10),
        ('max', 15.0, 25.0),
        [{'check': 'shell_volume_ratio', 'a': 'largest', 'b': 'smallest', 'min': 50.0, 'max': 100000.0, 'when': 'glb'}],
    ),
    'model_person_partial': (
        'the upper half of a person',
        'The upper half of one adult, from the waist up, plain shirt, arms at the sides, cut flat at the waist. Nothing below the waist.',
        (1, 8),
        ('y', 0.60, 1.05),
        _people(1),
    ),
    # ── The body (19) ──
    'model_face_front': (
        'a face seen from the front',
        'One adult human head and neck, facing forward, mouth closed, eyes open, no hair, cut flat at the base of the neck.',
        (1, 4),
        ('y', 0.20, 0.32),
        [{'check': 'bbox_facing', 'heading': 0, 'tolerance': 20, 'when': 'glb'}],
    ),
    'model_face_profile': (
        'a face in profile',
        'One adult human head and neck with a pronounced nose and chin, mouth closed, no hair, cut flat at the base of the neck.',
        (1, 4),
        ('y', 0.20, 0.32),
        [{'check': 'bbox_aspect', 'axis': 'z', 'over': 'x', 'min': 1.05, 'max': 1.9, 'when': 'glb'}],
    ),
    'model_face_three_quarter': (
        'a head turned three-quarters away',
        'One adult human head and neck turned forty-five degrees to its left, mouth closed, eyes open, no hair, cut flat at the neck.',
        (1, 4),
        ('y', 0.20, 0.32),
        [{'check': 'bbox_facing', 'heading': 45, 'tolerance': 20, 'when': 'glb'}],
    ),
    'model_eyes_pair': (
        'a pair of eyes in a head',
        'One adult human head, both eyes open and clearly modelled with eyeball, lid and brow, mouth closed, no hair.',
        (1, 8),
        ('y', 0.20, 0.32),
        [{'check': 'mesh_part_names', 'terms': ['eye'], 'when': 'glb'}],
    ),
    'model_gaze': (
        'a head looking to its own left',
        'One adult human head facing forward with both eyes turned to look sharply to its own left, mouth closed, no hair.',
        (1, 8),
        ('y', 0.20, 0.32),
        None,
    ),
    'model_teeth': (
        'an open mouth with teeth',
        'One adult human head with the mouth open wide, upper and lower teeth modelled as separate geometry, tongue inside, no hair.',
        (2, 10),
        ('y', 0.20, 0.32),
        [{'check': 'mesh_part_names', 'terms': ['teeth'], 'when': 'glb'}],
    ),
    'model_ears': (
        'a head with both ears',
        'One adult human head, bald, both ears fully modelled with helix and lobe standing clear of the skull, mouth closed.',
        (1, 6),
        ('y', 0.20, 0.32),
        None,
    ),
    'model_hair_long': (
        'long hair on a head',
        'One adult human head with long straight hair falling to the shoulders, parted in the middle, hair as separate geometry from the head.',
        (2, 8),
        ('y', 0.28, 0.55),
        [{'check': 'mesh_part_names', 'terms': ['hair'], 'when': 'glb'}],
    ),
    'model_hair_curly': (
        'tightly curly hair on a head',
        'One adult human head with short tightly curly hair standing out from the skull, hair as separate geometry from the head.',
        (2, 8),
        ('y', 0.22, 0.40),
        [{'check': 'mesh_part_names', 'terms': ['hair'], 'when': 'glb'}],
    ),
    'model_beard': (
        'a full beard on a face',
        'One adult male head with a full beard and moustache reaching the collarbone, bald scalp, beard as separate geometry from the head.',
        (2, 8),
        ('y', 0.28, 0.50),
        None,
    ),
    'model_hand_one': (
        'one human hand',
        'One human left hand, open, palm forward, fingers together and straight, cut flat at the wrist. Nothing else.',
        (1, 3),
        ('max', 0.15, 0.26),
        _hands(1, 5),
    ),
    'model_hand_two': (
        'two human hands',
        'Two human hands, a left and a right, both open with palms forward, ten centimetres apart, each cut flat at the wrist.',
        (2, 6),
        ('max', 0.25, 0.45),
        _hands(2, 5),
    ),
    'model_hand_holding': (
        'a hand holding a cup',
        'One human right hand holding a plain clay cup by its body, fingers wrapped around it, cut flat at the wrist. Hand and cup separate.',
        (2, 6),
        ('max', 0.15, 0.30),
        [
            {
                'check': 'bbox_relation',
                'a': 'smallest',
                'b': 'largest',
                'relation': 'touching',
                'tolerance': 0.01,
                'when': 'glb',
            }
        ],
    ),
    'model_hand_gripping': (
        'a hand gripping a rope',
        'One human right hand closed in a fist around a thick rope that passes through it, cut flat at the wrist. Hand and rope separate.',
        (2, 6),
        ('max', 0.20, 0.60),
        None,
    ),
    'model_fingers_count': (
        'a hand with five spread fingers',
        'One human left hand, open, palm forward, the five fingers spread wide apart and clearly separate, cut flat at the wrist.',
        (1, 3),
        ('max', 0.16, 0.28),
        _hands(1, 5),
    ),
    'model_feet_bare': (
        'a pair of bare feet',
        'Two bare human feet, a left and a right, flat on the ground twenty centimetres apart, toes separate, each cut flat at the ankle.',
        (2, 6),
        ('max', 0.24, 0.45),
        None,
    ),
    'model_feet_shoes': (
        'a pair of period shoes on feet',
        'Two feet in buckled leather shoes, a left and a right, flat on the ground twenty centimetres apart, each cut flat at the ankle.',
        (2, 10),
        ('max', 0.24, 0.45),
        _mat('leather'),
    ),
    'model_arms_crossed': (
        'a person with arms folded',
        'One standing adult with both arms folded across the chest, plain shirt and breeches, barefoot, looking straight ahead.',
        (1, 8),
        ('y', 1.55, 2.00),
        _people(1),
    ),
    'model_muscle_flex': (
        'a raised arm with a flexed muscle',
        'One bare adult male torso with the right arm raised and bent, the upper arm muscle bunched, cut flat at the waist.',
        (1, 6),
        ('y', 0.60, 1.10),
        None,
    ),
}
