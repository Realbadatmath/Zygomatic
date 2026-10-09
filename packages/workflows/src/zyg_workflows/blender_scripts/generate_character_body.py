# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Body geometry for ``blender_scripts/generate_character.py``.

Everything ``build_character()`` used to do inline, in the same order: the hair
style buckets, the gender + muscle-mass proportions, the facial-hair ladder and
one ``add_*`` builder per body part.  The script keeps the argument parsing, the
materials, the lights, the camera rig and the render loop; it calls the builders
here through a :class:`CharacterBuild`.

The pure helpers — :func:`body_proportions`, :func:`resolve_hair_style`,
:func:`hair_length_bucket`, :func:`hair_cap_kind`, :func:`facial_hair_anchors` —
import without Blender and are unit-tested in
``tests/test_generate_character_helpers.py``.  The ``add_*`` builders need
``bpy`` and only ever run inside Blender.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

try:  # inside Blender
    import bpy
except ImportError:  # the pure helpers below do not need it
    bpy = None


# ── Hair style buckets ──────────────────────────────────────────────────────────
SHORT_STYLES = frozenset(
    {
        'buzz cut',
        'crew cut',
        'buzz',
        'crew',
        'military cut',
        'undercut',
        'fade',
        'side part short',
        'pompadour',
        'slick back',
        'pixie',
        'pixie cut',
        'bob',
        'chin-length bob',
        'asymmetrical bob',
        'french bob',
        'sleek bob',
        'textured bob',
    }
)
LONG_STYLES = frozenset(
    {
        'long straight',
        'long wavy',
        'long curly',
        'beach waves',
        'boho waves',
        'voluminous blowout',
        'sleek straight',
        'layered',
        'shag',
        'braids',
        'twin braids',
        'fishtail braid',
        'dutch braid',
        'ponytail',
        'high ponytail',
        'low ponytail',
        'side ponytail',
        'bun',
        'messy bun',
        'top knot',
        'french twist',
    }
)
BUN_STYLES = frozenset({'bun', 'messy bun', 'top knot', 'french twist'})
PONY_STYLES = frozenset({'ponytail', 'high ponytail', 'low ponytail', 'side ponytail'})
BRAID_STYLES = frozenset({'braids', 'twin braids', 'fishtail braid', 'dutch braid'})
BALD_STYLES = frozenset({'bald', 'completely bald', 'bald head', 'clean bald'})
SHAVED_STYLES = frozenset({'1mm shave', '1mm', 'shaved 1mm', 'close crop'})
SHORT_AFRO_STYLES = frozenset({'short afro', 'taper afro', 'afro fade', 'short afro m'})

# ── Facial hair buckets (male only) ─────────────────────────────────────────────
MOUSTACHE_STYLES = frozenset({'mustache', 'classic mustache'})
HANDLEBAR_STYLES = frozenset({'handlebar mustache'})
CHIN_STYLES = frozenset({'goatee', 'chinstrap', 'mutton chops'})
SHORT_BEARD_STYLES = frozenset({'short beard', 'anchor beard', 'extended goatee'})
FULL_BEARD_STYLES = frozenset({'full beard', 'van dyke', 'circle beard'})


@dataclass(frozen=True)
class HairCap:
    """The five numbers one hair-cap ellipsoid is built from."""

    radius_mul: float
    z: float
    segments: int
    rings: int
    scale_z: float


HAIR_CAPS = {
    'shaved': HairCap(1.008, 1.623, 18, 10, 0.28),  # 1 mm stubble cap — almost-flat ellipsoid
    'afro': HairCap(1.30, 1.67, 20, 14, 0.78),  # compact round afro, stays close to head
    'standard': HairCap(1.06, 1.64, 20, 12, 0.55),
}


@dataclass(frozen=True)
class CharacterMaterials:
    """The eight materials the script pre-builds, named by the part that wears them."""

    skin: object
    hair: object
    eyes: object
    eyewhite: object
    cloth_top: object
    cloth_bot: object
    shoes: object
    lips: object


@dataclass(frozen=True)
class BodyProportions:
    """Scale-free widths derived from gender and muscle mass.

    ``shoulder_scale``/``arm_scale`` are the old ``_mm_sw``/``_mm_aw``: the
    continuous 1-100 muscle mass interpolated onto 0.85→1.42 (shoulders) and
    0.80→1.50 (arm radii).
    """

    head_sz: float
    shoulder_w: float
    hip_w: float
    shoulder_scale: float
    arm_scale: float


@dataclass(frozen=True)
class FacialHairAnchors:
    """Where male facial hair hangs: upper lip, chin, and the face-side y offset."""

    lip_z: float
    chin_z: float
    front: float


@dataclass
class CharacterBuild:
    """Everything the part builders need, plus the objects they have made so far."""

    s: float
    gender: str
    hair_style: str
    facial_hair: str
    mats: CharacterMaterials
    prop: BodyProportions
    objs: list = field(default_factory=list)


# ── Pure helpers ────────────────────────────────────────────────────────────────


def assign_material(obj, mat):
    """Put *mat* in slot 0 of *obj*, creating the slot when the mesh has none."""
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def body_proportions(gender: str, muscle_mass: int) -> BodyProportions:
    """Shoulder/hip/head widths for a gender at a muscle mass of 1-100."""
    shoulder_w = 0.22 if gender == 'female' else 0.28
    hip_w = 0.24 if gender == 'female' else 0.22
    head_sz = 0.13

    # Muscle mass scaling — continuous 1-100 interpolated onto 0.0→1.0
    _t = (muscle_mass - 1) / 99.0
    _mm_sw = 0.85 + _t * (1.42 - 0.85)  # shoulder: 0.85x (slim) → 1.42x (very muscular)
    _mm_aw = 0.80 + _t * (1.50 - 0.80)  # arm radii: 0.80x → 1.50x
    return BodyProportions(
        head_sz=head_sz,
        shoulder_w=shoulder_w * _mm_sw,
        hip_w=hip_w * (1.0 + (_mm_sw - 1.0) * 0.35),
        shoulder_scale=_mm_sw,
        arm_scale=_mm_aw,
    )


def resolve_hair_style(hair_style: str, gender: str) -> str:
    """Turn ``'auto'`` into the gender default; any other style passes through."""
    _default_style = 'long wavy' if gender == 'female' else 'short side part'
    return hair_style if hair_style != 'auto' else _default_style


def hair_length_bucket(style: str) -> str:
    """Classify a resolved hair style as ``'short'``, ``'long'`` or ``'medium'``."""
    if style in SHORT_STYLES:
        return 'short'
    if style in LONG_STYLES:
        return 'long'
    return 'medium'


def hair_cap_kind(style: str) -> str:
    """Which cap a resolved style needs: ``bald``, ``shaved``, ``afro`` or ``standard``.

    Only ``standard`` grows a length fall and accessories; ``bald`` gets no
    geometry at all.
    """
    if style in BALD_STYLES:
        return 'bald'
    if style in SHAVED_STYLES:
        return 'shaved'
    if style in SHORT_AFRO_STYLES:
        return 'afro'
    return 'standard'


def facial_hair_anchors(s: float) -> FacialHairAnchors:
    """Facial-hair anchor heights for a character scaled by *s*."""
    return FacialHairAnchors(
        lip_z=1.555 * s,  # upper lip height
        chin_z=1.493 * s,  # chin height
        front=0.100 * s,  # y offset (face is on +Y side)
    )


# ── Head and hair ───────────────────────────────────────────────────────────────


def add_head(ctx: CharacterBuild) -> None:
    """Add the head sphere at 1.62 m, skinned."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    bpy.ops.mesh.primitive_uv_sphere_add(radius=head_sz * S, location=(0, 0, 1.62 * S), segments=24, ring_count=16)
    head = bpy.context.active_object
    head.name = 'head'
    assign_material(head, ctx.mats.skin)
    objs.append(head)


def _add_hair_cap(ctx: CharacterBuild, cap: HairCap) -> None:
    """Add the flattened ellipsoid that sits on the skull for *cap*."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=head_sz * S * cap.radius_mul,
        location=(0, 0, cap.z * S),
        segments=cap.segments,
        ring_count=cap.rings,
    )
    hair_cap = bpy.context.active_object
    hair_cap.name = 'hair_cap'
    assign_material(hair_cap, ctx.mats.hair)
    hair_cap.scale.z = cap.scale_z
    bpy.ops.object.transform_apply(scale=True)
    objs.append(hair_cap)


def _add_hair_fall(ctx: CharacterBuild, bucket: str) -> None:
    """Add the hair that hangs behind the head for a ``long``/``medium`` bucket."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    if bucket == 'long':
        # Long flowing hair — tall ellipsoid behind head
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.85, location=(0, -0.05 * S, 1.40 * S), segments=16, ring_count=10
        )
        hair_long = bpy.context.active_object
        hair_long.name = 'hair_long'
        hair_long.scale = (0.70, 0.60, 2.20)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(hair_long, ctx.mats.hair)
        objs.append(hair_long)

    elif bucket == 'medium':
        # Medium hair — down to chin/shoulder
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.78, location=(0, -0.03 * S, 1.50 * S), segments=16, ring_count=10
        )
        hair_med = bpy.context.active_object
        hair_med.name = 'hair_medium'
        hair_med.scale = (0.70, 0.58, 1.40)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(hair_med, ctx.mats.hair)
        objs.append(hair_med)


def _add_hair_accessories(ctx: CharacterBuild, style: str) -> None:
    """Add the bun, ponytail and braids a resolved *style* asks for."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    if style in BUN_STYLES:
        # Bun on top of head
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.42, location=(0, 0, 1.82 * S), segments=12, ring_count=8
        )
        bun = bpy.context.active_object
        bun.name = 'hair_bun'
        bun.scale = (1.0, 0.85, 0.75)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(bun, ctx.mats.hair)
        objs.append(bun)

    if style in PONY_STYLES:
        # Ponytail — cylinder extending behind head
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.05 * S, depth=0.45 * S, location=(0, -head_sz * S * 0.9, 1.56 * S), vertices=10
        )
        pony = bpy.context.active_object
        pony.name = 'hair_ponytail'
        pony.rotation_euler.x = math.radians(25)
        assign_material(pony, ctx.mats.hair)
        objs.append(pony)

    if style in BRAID_STYLES:
        # Twin braids — two narrow cylinders in front
        for _bx in (0.07 * S, -0.07 * S):
            bpy.ops.mesh.primitive_cylinder_add(
                radius=0.035 * S, depth=0.50 * S, location=(_bx, 0.02 * S, 1.28 * S), vertices=8
            )
            braid = bpy.context.active_object
            braid.name = f'hair_braid_{int(_bx * 100)}'
            braid.rotation_euler.x = math.radians(-5)
            assign_material(braid, ctx.mats.hair)
            objs.append(braid)


def add_hair(ctx: CharacterBuild) -> None:
    """Add all hair geometry driven by ``ctx.hair_style``.

    Bald adds nothing, a shave or a short afro gets only its cap, and every other
    style gets the standard cap plus the length fall and accessories.
    """
    style = resolve_hair_style(ctx.hair_style, ctx.gender)
    kind = hair_cap_kind(style)
    if kind == 'bald':
        return  # completely bald — no hair geometry
    _add_hair_cap(ctx, HAIR_CAPS[kind])
    if kind != 'standard':
        return
    _add_hair_fall(ctx, hair_length_bucket(style))
    _add_hair_accessories(ctx, style)


# ── Facial hair ─────────────────────────────────────────────────────────────────


def _add_moustache(ctx: CharacterBuild, anchors: FacialHairAnchors, style: str) -> None:
    """Add a classic or handlebar moustache on the upper lip."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    _lip_z, _front = anchors.lip_z, anchors.front
    if style in MOUSTACHE_STYLES:
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.22, location=(0, _front * 1.12, _lip_z), segments=10, ring_count=6
        )
        fh = bpy.context.active_object
        fh.name = 'facial_mustache'
        fh.scale = (1.60, 0.38, 0.48)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)

    elif style in HANDLEBAR_STYLES:
        for _mx, _rz in ((0.065 * S, 18), (-0.065 * S, -18)):
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=head_sz * S * 0.18, location=(_mx, _front * 1.10, _lip_z), segments=10, ring_count=6
            )
            fh = bpy.context.active_object
            fh.name = f'facial_handlebar_{int(_mx * 100)}'
            fh.scale = (1.18, 0.38, 0.46)
            fh.rotation_euler.z = math.radians(_rz)
            bpy.ops.object.transform_apply(scale=True, rotation=True)
            assign_material(fh, ctx.mats.hair)
            objs.append(fh)


def _add_chin_hair(ctx: CharacterBuild, anchors: FacialHairAnchors, style: str) -> None:
    """Add a goatee, a chinstrap or mutton chops."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    _chin_z, _front = anchors.chin_z, anchors.front
    if style == 'goatee':
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.30, location=(0, _front, _chin_z + 0.01 * S), segments=10, ring_count=8
        )
        fh = bpy.context.active_object
        fh.name = 'facial_goatee'
        fh.scale = (0.70, 0.52, 0.85)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)

    elif style == 'chinstrap':
        for _cx, _ra in ((0.085 * S, 20), (-0.085 * S, 20)):
            bpy.ops.mesh.primitive_cylinder_add(
                radius=0.019 * S, depth=0.18 * S, location=(_cx, _front * 0.28, 1.516 * S), vertices=8
            )
            fh = bpy.context.active_object
            fh.name = f'facial_chinstrap_{int(_cx * 100)}'
            fh.rotation_euler.x = math.radians(_ra)
            assign_material(fh, ctx.mats.hair)
            objs.append(fh)
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.20, location=(0, _front, _chin_z), segments=8, ring_count=6
        )
        fh = bpy.context.active_object
        fh.name = 'facial_chinstrap_chin'
        fh.scale = (0.65, 0.42, 0.52)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)

    elif style == 'mutton chops':
        for _mx in (0.092 * S, -0.092 * S):
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=head_sz * S * 0.34, location=(_mx, _front * 0.32, 1.530 * S), segments=10, ring_count=7
            )
            fh = bpy.context.active_object
            fh.name = f'facial_mutton_{int(_mx * 100)}'
            fh.scale = (0.70, 0.54, 0.72)
            bpy.ops.object.transform_apply(scale=True)
            assign_material(fh, ctx.mats.hair)
            objs.append(fh)


def _add_beard(ctx: CharacterBuild, anchors: FacialHairAnchors, style: str) -> None:
    """Add stubble or one of the jaw-covering beards; unknown styles add nothing."""
    S, head_sz, objs = ctx.s, ctx.prop.head_sz, ctx.objs
    _front = anchors.front
    if style == 'stubble':
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.76, location=(0, _front * 0.75, 1.528 * S), segments=12, ring_count=8
        )
        fh = bpy.context.active_object
        fh.name = 'facial_stubble'
        fh.scale = (0.86, 0.35, 0.50)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)

    elif style in SHORT_BEARD_STYLES:
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.68, location=(0, _front * 0.65, 1.518 * S), segments=12, ring_count=8
        )
        fh = bpy.context.active_object
        fh.name = 'facial_short_beard'
        fh.scale = (0.84, 0.42, 0.62)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)

    elif style in FULL_BEARD_STYLES:
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.78, location=(0, _front * 0.58, 1.516 * S), segments=12, ring_count=8
        )
        fh = bpy.context.active_object
        fh.name = 'facial_full_beard'
        fh.scale = (0.88, 0.46, 0.72)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)

    elif style == 'long beard':
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_sz * S * 0.76, location=(0, _front * 0.58, 1.516 * S), segments=12, ring_count=8
        )
        fh = bpy.context.active_object
        fh.name = 'facial_beard_upper'
        fh.scale = (0.80, 0.46, 0.68)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(fh, ctx.mats.hair)
        objs.append(fh)
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.060 * S, depth=0.26 * S, location=(0, _front * 0.65, 1.372 * S), vertices=10
        )
        fh2 = bpy.context.active_object
        fh2.name = 'facial_beard_long'
        assign_material(fh2, ctx.mats.hair)
        objs.append(fh2)


def add_facial_hair(ctx: CharacterBuild) -> None:
    """Add male facial hair for ``ctx.facial_hair``; a no-op for anyone else."""
    if ctx.gender != 'male' or ctx.facial_hair in ('none', ''):
        return
    anchors = facial_hair_anchors(ctx.s)
    style = ctx.facial_hair
    if style in MOUSTACHE_STYLES or style in HANDLEBAR_STYLES:
        _add_moustache(ctx, anchors, style)
    elif style in CHIN_STYLES:
        _add_chin_hair(ctx, anchors, style)
    else:
        _add_beard(ctx, anchors, style)


# ── Eyes, trunk and limbs ───────────────────────────────────────────────────────


def add_eyes(ctx: CharacterBuild) -> None:
    """Add both eyeballs and their irises."""
    S, objs = ctx.s, ctx.objs
    for side, x in (('L', 0.045), ('R', -0.045)):
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.018 * S, location=(x * S, 0.11 * S, 1.64 * S), segments=10, ring_count=8
        )
        eyeball = bpy.context.active_object
        eyeball.name = f'eye_{side}'
        assign_material(eyeball, ctx.mats.eyewhite)
        objs.append(eyeball)

        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.011 * S, location=(x * S, 0.125 * S, 1.64 * S), segments=10, ring_count=8
        )
        iris = bpy.context.active_object
        iris.name = f'iris_{side}'
        assign_material(iris, ctx.mats.eyes)
        objs.append(iris)


def add_trunk(ctx: CharacterBuild) -> None:
    """Add the neck, the tapered torso and the hips."""
    S, objs = ctx.s, ctx.objs
    shoulder_w, hip_w = ctx.prop.shoulder_w, ctx.prop.hip_w

    # --- Neck ---
    bpy.ops.mesh.primitive_cylinder_add(radius=0.038 * S, depth=0.10 * S, location=(0, 0, 1.49 * S), vertices=12)
    neck = bpy.context.active_object
    neck.name = 'neck'
    assign_material(neck, ctx.mats.skin)
    objs.append(neck)

    # --- Torso ---
    bpy.ops.mesh.primitive_cylinder_add(radius=shoulder_w * S, depth=0.45 * S, location=(0, 0, 1.21 * S), vertices=16)
    torso = bpy.context.active_object
    torso.name = 'torso'
    # Taper torso: shoulders wider, waist narrower
    torso.scale.x = 1.0
    torso.scale.y = 0.68
    assign_material(torso, ctx.mats.cloth_top)
    objs.append(torso)

    # --- Pelvis / hips ---
    bpy.ops.mesh.primitive_cylinder_add(radius=hip_w * S, depth=0.18 * S, location=(0, 0, 0.90 * S), vertices=16)
    hips = bpy.context.active_object
    hips.name = 'hips'
    hips.scale.y = 0.72
    assign_material(hips, ctx.mats.cloth_bot)
    objs.append(hips)


def add_arms(ctx: CharacterBuild) -> None:
    """Add both upper arms, forearms and hands, scaled by the muscle mass."""
    S, objs = ctx.s, ctx.objs
    shoulder_w, _mm_aw = ctx.prop.shoulder_w, ctx.prop.arm_scale
    for side, x in (('L', shoulder_w * S + 0.04 * S), ('R', -(shoulder_w * S + 0.04 * S))):
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.048 * S * _mm_aw, depth=0.26 * S, location=(x, 0, 1.17 * S), vertices=10
        )
        uarm = bpy.context.active_object
        uarm.name = f'upper_arm_{side}'
        uarm.rotation_euler.y = math.radians(10 if side == 'L' else -10)
        assign_material(uarm, ctx.mats.cloth_top)
        objs.append(uarm)

        # Forearm
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.040 * S * _mm_aw, depth=0.24 * S, location=(x * 1.05, 0, 0.93 * S), vertices=10
        )
        farm = bpy.context.active_object
        farm.name = f'forearm_{side}'
        farm.rotation_euler.y = math.radians(12 if side == 'L' else -12)
        assign_material(farm, ctx.mats.skin)
        objs.append(farm)

        # Hand
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.045 * S, location=(x * 1.10, 0, 0.77 * S), segments=8, ring_count=6
        )
        hand = bpy.context.active_object
        hand.name = f'hand_{side}'
        hand.scale.z = 0.7
        bpy.ops.object.transform_apply(scale=True)
        assign_material(hand, ctx.mats.skin)
        objs.append(hand)


def add_legs(ctx: CharacterBuild) -> None:
    """Add both thighs, shins and shoes."""
    S, objs = ctx.s, ctx.objs
    for side, x in (('L', 0.10 * S), ('R', -0.10 * S)):
        # Upper leg / thigh
        bpy.ops.mesh.primitive_cylinder_add(radius=0.065 * S, depth=0.36 * S, location=(x, 0, 0.60 * S), vertices=12)
        thigh = bpy.context.active_object
        thigh.name = f'thigh_{side}'
        assign_material(thigh, ctx.mats.cloth_bot)
        objs.append(thigh)

        # Lower leg / shin
        bpy.ops.mesh.primitive_cylinder_add(radius=0.052 * S, depth=0.34 * S, location=(x, 0, 0.24 * S), vertices=12)
        shin = bpy.context.active_object
        shin.name = f'shin_{side}'
        assign_material(shin, ctx.mats.skin)
        objs.append(shin)

        # Shoe / foot
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0.03 * S, 0.04 * S))
        shoe = bpy.context.active_object
        shoe.name = f'shoe_{side}'
        shoe.scale = (0.07 * S, 0.11 * S, 0.04 * S)
        bpy.ops.object.transform_apply(scale=True)
        assign_material(shoe, ctx.mats.shoes)
        objs.append(shoe)
