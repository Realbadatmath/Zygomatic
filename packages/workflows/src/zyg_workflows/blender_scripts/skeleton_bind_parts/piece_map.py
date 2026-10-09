# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Piece name -> rig bone: the maps, the splitter and ``bone_for_piece``."""

# --------------------------------------------------------------------------
# piece -> rig bone
# --------------------------------------------------------------------------

_MIDLINE_MAP = {
    'skull': 'Head',
    'spine_cervical_c1': 'Neck1',
    'spine_cervical_c2': 'Neck1',
    'spine_cervical_c3': 'Neck1',
    'spine_cervical_c4': 'Neck',
    'spine_cervical_c5': 'Neck',
    'spine_cervical_c6': 'Neck',
    'spine_cervical_c7': 'Neck',
    # the bundle spells the thoracic vertebrae t1, 2, t3, 4, 5, 6, 7 ... t11, t12
    'spine_thoracic_t1': 'Spine1',
    'spine_thoracic_2': 'Spine1',
    'spine_thoracic_t3': 'Spine1',
    'spine_thoracic_4': 'Spine1',
    'spine_thoracic_5': 'Spine1',
    'spine_thoracic_6': 'Spine1',
    'spine_thoracic_7': 'Spine',
    'spine_thoracic_8': 'Spine',
    'spine_thoracic_9': 'Spine',
    'spine_thoracic_10': 'Spine',
    'spine_thoracic_t11': 'Spine',
    'spine_thoracic_t12': 'Spine',
    'ripcage': 'Spine1',
    'sacral': 'Hips',
    'coccygeal': 'Hips',
    'hip': 'Hips',
}

_SIDED_MAP = {
    'clavicle': '{S}Shoulder',
    'shoulder_scapula': '{S}Shoulder',
    'arm_humerus': '{S}Arm',
    'arm_radius': '{S}ForeArm',
    'arm_ulna': '{S}ForeArm',
    'hand_center': '{S}Hand',
    'leg_femur': '{S}UpLeg',
    'leg_patella': '{S}UpLeg',
    'leg_tibula': '{S}Leg',
    'leg_fibula': '{S}Leg',
    'foot_calcaneus': '{S}Foot',
    'foot_talus': '{S}Foot',
    'foot_center': '{S}Foot',
}

FINGERS = ('index', 'middle', 'ring', 'little', 'thumb')
PHALANX_ROWS = ('proximal', 'middle', 'distal')

TRUNK_BONES = (
    'Hips',
    'LowerBack',
    'Spine',
    'Spine1',
    'Neck',
    'Neck1',
    'Head',
    'LeftShoulder',
    'RightShoulder',
)

# group bone -> (proximal piece stem, distal reference); resolved per side.
# The distal reference is either a piece stem or a callable over the side's
# origin table.  a_s = distal - J_s, exactly the segment the bone spans.
LIMB_GROUPS = ('Arm', 'ForeArm', 'Hand', 'UpLeg', 'Leg', 'Foot', 'ToeBase')

# rig bones that the mapping folds into a parent group: their body vertices
# belong to the parent's comparison box.
_ABSORBED = {
    'LHipJoint': 'Hips',
    'RHipJoint': 'Hips',
    'LThumb': 'LeftHand',
    'LeftFingerBase': 'LeftHand',
    'LeftHandIndex1': 'LeftHand',
    'RThumb': 'RightHand',
    'RightFingerBase': 'RightHand',
    'RightHandIndex1': 'RightHand',
}


def _split_piece(short: str):
    """'distal.index.L' -> (['distal','index'], 'L').  'spine_lumbar_l1.5' -> (...,None)."""
    parts = short.split('.')
    side = None
    if parts[-1] in ('L', 'R'):
        side = parts[-1]
        parts = parts[:-1]
    return parts, side


def bone_for_piece(short: str):
    """Map a piece short name (no ``GEO-skeletion.`` prefix) to a rig bone name."""
    parts, side = _split_piece(short)
    stem = '.'.join(parts)

    if side is None:
        if stem.startswith('spine_lumbar_l'):
            return 'LowerBack'
        return _MIDLINE_MAP.get(stem)

    S = 'Left' if side == 'L' else 'Right'

    tmpl = _SIDED_MAP.get(stem)
    if tmpl:
        return tmpl.format(S=S)

    if parts[0] == 'metacarpal':
        return S + 'Hand'
    if parts[0] == 'metatarsal':
        return S + 'Foot'
    if parts[0] in PHALANX_ROWS and len(parts) == 2:
        which = parts[1]
        if which in FINGERS:
            return S + 'Hand'
        if which.isdigit():  # numeric phalanges are toes
            return S + 'ToeBase'
    return None
