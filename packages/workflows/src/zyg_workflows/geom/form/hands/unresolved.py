# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""What this cage and this rig cannot answer, with the measurement that proves it.

Moved verbatim out of the old single-file hands.py (lines 1235-1288, 3388-3515).
"""

from zyg_workflows.geom.form.hands.rig import (
    REPORT,
    UNMEASURABLE,
    NOT_IMPLEMENTABLE,
)


# ---------------------------------------------------------------------------------
# What this cage cannot answer, with the measurement that proves it
# ---------------------------------------------------------------------------------
MESH_UNRESOLVED = (
    {
        'predicate': 'webbing',
        'part': 'first web space (thumb-index commissure)',
        'status': NOT_IMPLEMENTABLE,
        'evidence': (
            'the rig blends 2 cage vertices between finger1-2 and finger2-1 at '
            'weight>0.01 and 0 at weight>0.05, against 40-55 for every '
            'finger-to-finger pair. There is no thumb-web skinning signature on '
            'this cage, and the inter-digital mid-plane construction needs one to '
            'know which faces belong to the web.'
        ),
        'measured': '2026-08-06 on the neutral male, both sides',
    },
    {
        'predicate': 'thumb_opposition',
        'part': 'the fingernail plate itself',
        'status': NOT_IMPLEMENTABLE,
        'evidence': (
            'the cage carries no nail geometry that can be isolated: the median '
            'dihedral angle across the index distal phalanx is 15.8 deg and the '
            'maximum 76.0 deg, with no closed high-dihedral loop that could be a '
            "nail border. What is measured is the DISTAL BLOCK'S dorso-palmar "
            'axis, which is the direction the nail would face, not the nail.'
        ),
        'measured': '2026-08-06 on the male original, delivered triangulation',
    },
)

IMAGE_UNRESOLVED = (
    {
        'predicate': 'webbing',
        'status': UNMEASURABLE,
        'evidence': (
            "MediaPipe's hand topology is 21 joint points. It has no commissure "
            'point and no surface, so there is nothing in it from which a web '
            'position could be read. Approximating one would be inventing an '
            'anchor.'
        ),
    },
    {
        'predicate': 'dorsal_over_palmar',
        'status': UNMEASURABLE,
        'evidence': (
            'the same 21 points are joint centres. A dorsal and a palmar surface '
            'path cannot be distinguished in them at all.'
        ),
    },
)


# ---------------------------------------------------------------------------------
# What the rig cannot answer, with the measurement that proves it
# ---------------------------------------------------------------------------------
DIGIT_UNRESOLVED_FOOT_RATIO = (
    'NO EXTERNAL NORMATIVE TABLE OF TOE PHALANX LENGTHS was located, so the foot ratios '
    'are measured and reported and nothing is gated on them. The literature reachable '
    'from this machine on hallux phalanges is hallux-valgus ANGLE work (interphalangeal '
    'angle, CORA classification), which publishes angles and not lengths; the one '
    'osteometric series that carries both hand and foot bone lengths, Case & Ross 2007 '
    'J. Forensic Sci. 52:264-270 (Terry Collection, n=259), is behind a paywall and its '
    'tables could not be read. Setting a foot band from the hand surveys, or from our '
    'own cage, would both be inventions.'
)

DIGIT_UNRESOLVED = (
    {
        'predicate': 'digit_chains',
        'part': 'toe5-2, the little toe middle phalanx',
        'status': 'fail',
        'evidence': (
            'THIS IS THE ONE SUB-CHECK THAT FAILS t5_digit_chains on every body, and it is '
            'diagnosed rather than merely reported. toe5-2.L reaches a maximum rig weight '
            'of 0.3062 over the whole cage, is above SEGMENT_W_MIN=0.5 on ZERO vertices, '
            'and — the threshold-free form of the same question — is the DOMINANT influence '
            'on zero vertices too: every one of the 135 vertices it touches is dominated by '
            'toe5-3 or toe4-1. Both a majority test and a rank test agree, so the failure '
            'is not an artefact of where 0.5 was put. 27 of the 28 phalanx bones pass; this '
            'is the only one.\n'
            'SUBDIVISION PROVABLY CANNOT FIX IT, so it was not tried: Catmull-Clark places '
            'every new vertex at a convex combination of existing ones, weights carried '
            'through the same stencils are convex combinations too, and a convex '
            'combination cannot exceed its largest input. If no cage vertex reaches 0.5, no '
            'vertex at any subdivision level can.\n'
            'A REPAINT HAS SOMETHING REAL TO CORRECT BUT WOULD HAVE TO INVENT THE AMOUNT. '
            'Measured by point-to-segment distance in rest space, 54 of the 191 toe5 '
            'vertices are physically NEAREST to the 9.15 mm toe5-2 segment while the rig '
            'gives them to toe5-3 (37) or toe5-1 (16), so the painting does disagree with '
            'the geometry. But geometry says only WHICH vertices, never HOW MUCH: any '
            'falloff we chose would be a house invention layered onto a third-party rig, '
            'and it would change the deformation of the whole toe to fix a 4 mm segment '
            'that no render resolves. Left failing on purpose — a true finding about the '
            'asset, not a gate to be widened.'
        ),
        'measured': '2026-08-08',
    },
    {
        'predicate': 'digit_chains',
        'part': 'the five metatarsals',
        'status': UNMEASURABLE,
        'evidence': (
            "anny's rig carries NO metatarsal bone. The path from the shank to "
            'the toes is lowerleg02 -> foot -> toeN-1, a single bone for the '
            'whole tarsus and metatarsus, against the hand where metacarpal1..4 '
            'plus finger1-1 give five separate metapodials. Measured on the '
            "neutral, foot.L's tail sits 81.63 mm off the line through the "
            "toe2-5 proximal heads while every toe's proximal head sits within "
            '12.54 mm of it, so `foot` spans the metatarsus rather than ending at '
            'it. Five metatarsals can be INFERRED from five rays; they cannot be '
            'counted, and this pack does not report an inference as a count.'
        ),
        'measured': '2026-08-06 on the anny neutral, both sides',
    },
    {
        'predicate': 'digit_chains',
        'part': 'the three cuneiforms',
        'status': NOT_IMPLEMENTABLE,
        'evidence': (
            'the rig has no tarsal bone of any kind — a name search over all 163 '
            'bones for talus/calcaneus/navicular/cuboid/cuneiform/tarsal returns '
            'nothing. Unlike the metatarsals this is not merely a rigging choice '
            'that a denser rig could fix for us: the cuneiforms are deep midfoot '
            'bones with no surface signature, so even a perfect cage plus the '
            'sculpt layer of plan section 2 could not resolve a count of three. '
            'This one stays not-implementable in mesh space.'
        ),
        'measured': '2026-08-06, rig roster name search',
    },
    {
        'predicate': 'digit_chains',
        'part': 'the eight carpals',
        'status': NOT_IMPLEMENTABLE,
        'evidence': (
            'the same search over scaphoid/lunate/triquetrum/pisiform/trapezium/'
            'trapezoid/capitate/hamate/carpal returns nothing; the wrist is one '
            'bone named `wrist`. Same reasoning as the cuneiforms.'
        ),
        'measured': '2026-08-06, rig roster name search',
    },
    {
        'predicate': 'digit_chains',
        'part': 'foot chain root',
        'status': REPORT,
        'evidence': (
            "the foot's toe chains are internally exact — every toeN-k tail lands "
            "on toeN-(k+1)'s head to 0.000000 mm — but the chain does NOT start "
            "at foot's tail: the gap from foot.L's tail to each toe's proximal "
            'head is 80.8-87.6 mm, against 0.000000 mm for every '
            'metacarpal-to-finger join in the hand. That is the absent metatarsus '
            'showing up as a hole in the kinematic chain, and it is why '
            'chain_continuity() checks joins WITHIN a digit and not the join to '
            'the carrier.'
        ),
        'measured': '2026-08-06 on the anny neutral',
    },
    {
        'predicate': 'phalanx_ratio',
        'part': 'every toe',
        'status': UNMEASURABLE,
        'evidence': DIGIT_UNRESOLVED_FOOT_RATIO,
        'measured': '2026-08-06',
    },
    {
        'predicate': 'phalanx_ratio',
        'part': 'the thumb and the hallux',
        'status': REPORT,
        'evidence': (
            'a two-phalanx digit has no middle-to-proximal ratio, so the pack '
            'reports distal-over-proximal for both and gates neither. HD2002 '
            'publishes no thumb figure, leaving BK2010 as a single source; there '
            'is no hallux source at all. The two are serially homologous, so the '
            'thumb reading is carried beside the hallux one as the only '
            'measurable comparison available.'
        ),
        'measured': '2026-08-06',
    },
)
