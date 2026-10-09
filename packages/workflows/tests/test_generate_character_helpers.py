# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the pure half of the character body builder.

Every behaviour asserted here was a behaviour of the 408-line
``build_character`` before it was split into ``generate_character_body``: the
muscle-mass interpolation, the ``auto`` style default, the hair buckets, the
facial-hair anchors and the material slot assignment.  ``generate_character_body``
imports ``bpy`` under a guard, so none of this needs Blender.
"""

from __future__ import annotations

import pytest

from zyg_workflows.blender_scripts import generate_character_body as body


class _FakeMesh:
    """A mesh with just the ``materials`` list ``assign_material`` touches."""

    def __init__(self, materials=()):
        self.materials = list(materials)


class _FakeObject:
    """An object with just the ``data`` attribute ``assign_material`` touches."""

    def __init__(self, materials=()):
        self.data = _FakeMesh(materials)


# ── assign_material ─────────────────────────────────────────────────────────


def test_assign_material_appends_when_the_mesh_has_no_slot():
    """A fresh mesh gets the material appended as its first slot."""
    obj = _FakeObject()
    body.assign_material(obj, 'skin')
    assert obj.data.materials == ['skin']


def test_assign_material_overwrites_slot_zero():
    """An existing slot 0 is replaced, and no slot is added."""
    obj = _FakeObject(['old', 'keep'])
    body.assign_material(obj, 'hair')
    assert obj.data.materials == ['hair', 'keep']


# ── body_proportions ────────────────────────────────────────────────────────


def test_body_proportions_at_minimum_muscle_mass():
    """Muscle mass 1 is the slim end: 0.85x shoulders, 0.80x arms."""
    prop = body.body_proportions('male', 1)
    assert prop.shoulder_scale == pytest.approx(0.85)
    assert prop.arm_scale == pytest.approx(0.80)
    assert prop.head_sz == pytest.approx(0.13)
    assert prop.shoulder_w == pytest.approx(0.28 * 0.85)
    assert prop.hip_w == pytest.approx(0.22 * (1.0 + (0.85 - 1.0) * 0.35))


def test_body_proportions_at_maximum_muscle_mass():
    """Muscle mass 100 is the muscular end: 1.42x shoulders, 1.50x arms."""
    prop = body.body_proportions('male', 100)
    assert prop.shoulder_scale == pytest.approx(1.42)
    assert prop.arm_scale == pytest.approx(1.50)
    assert prop.shoulder_w == pytest.approx(0.28 * 1.42)


def test_body_proportions_interpolate_linearly_at_the_midpoint():
    """Muscle mass 50.5 lands exactly halfway along both ramps."""
    prop = body.body_proportions('male', 50.5)
    assert prop.shoulder_scale == pytest.approx((0.85 + 1.42) / 2)
    assert prop.arm_scale == pytest.approx((0.80 + 1.50) / 2)


def test_female_proportions_are_narrower_shouldered_and_wider_hipped():
    """Gender picks the base widths: 0.22/0.24 female vs 0.28/0.22 otherwise."""
    female = body.body_proportions('female', 1)
    neutral = body.body_proportions('neutral', 1)
    assert female.shoulder_w == pytest.approx(0.22 * 0.85)
    assert neutral.shoulder_w == pytest.approx(0.28 * 0.85)
    assert female.hip_w > neutral.hip_w
    assert female.shoulder_scale == neutral.shoulder_scale


# ── resolve_hair_style ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('gender', 'expected'),
    [('female', 'long wavy'), ('male', 'short side part'), ('neutral', 'short side part')],
)
def test_auto_hair_style_takes_the_gender_default(gender, expected):
    """``'auto'`` resolves to the per-gender default style."""
    assert body.resolve_hair_style('auto', gender) == expected


def test_an_explicit_hair_style_passes_through_unchanged():
    """Anything other than ``'auto'`` is used verbatim, whatever the gender."""
    assert body.resolve_hair_style('braids', 'male') == 'braids'
    assert body.resolve_hair_style('nonsense style', 'female') == 'nonsense style'


# ── hair_length_bucket ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('style', 'bucket'),
    [
        ('buzz cut', 'short'),
        ('bob', 'short'),
        ('fade', 'short'),
        ('long wavy', 'long'),
        ('braids', 'long'),
        ('messy bun', 'long'),
        ('short side part', 'medium'),
        ('nonsense style', 'medium'),
    ],
)
def test_hair_length_buckets(style, bucket):
    """Known styles land in short/long; everything unknown falls to medium.

    ``'short side part'`` — the male ``auto`` default — is deliberately in
    neither table and so takes the medium fall, exactly as it did before.
    """
    assert body.hair_length_bucket(style) == bucket


def test_the_length_buckets_do_not_overlap():
    """No style is both short and long, or the fall geometry would be ambiguous."""
    assert not body.SHORT_STYLES & body.LONG_STYLES


# ── hair_cap_kind ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('style', 'kind'),
    [
        ('clean bald', 'bald'),
        ('bald', 'bald'),
        ('1mm shave', 'shaved'),
        ('close crop', 'shaved'),
        ('short afro', 'afro'),
        ('afro fade', 'afro'),
        ('long wavy', 'standard'),
        ('nonsense style', 'standard'),
    ],
)
def test_hair_cap_kinds(style, kind):
    """Bald/shaved/afro styles get their own cap; the rest take the standard one."""
    assert body.hair_cap_kind(style) == kind


def test_every_non_bald_cap_kind_has_a_cap():
    """``add_hair`` indexes HAIR_CAPS by kind, so each non-bald kind must be there."""
    kinds = {body.hair_cap_kind(s) for s in ('1mm shave', 'short afro', 'long wavy', 'bob')}
    assert kinds <= set(body.HAIR_CAPS)


def test_the_shaved_cap_is_the_flattest_and_the_afro_the_roundest():
    """The cap table keeps the original proportions: shaved flat, afro round."""
    assert body.HAIR_CAPS['shaved'].scale_z < body.HAIR_CAPS['standard'].scale_z
    assert body.HAIR_CAPS['afro'].scale_z > body.HAIR_CAPS['standard'].scale_z
    assert body.HAIR_CAPS['afro'].radius_mul > body.HAIR_CAPS['shaved'].radius_mul


# ── facial_hair_anchors ─────────────────────────────────────────────────────


def test_facial_hair_anchors_scale_with_the_character():
    """Lip, chin and face-front offsets are all plain multiples of the scale."""
    anchors = body.facial_hair_anchors(2.0)
    assert anchors.lip_z == pytest.approx(3.110)
    assert anchors.chin_z == pytest.approx(2.986)
    assert anchors.front == pytest.approx(0.200)
    assert anchors.lip_z > anchors.chin_z


# ── add_facial_hair's gating (no bpy needed: it returns before touching it) ──


@pytest.mark.parametrize(
    ('gender', 'facial_hair'),
    [('female', 'full beard'), ('neutral', 'goatee'), ('male', 'none'), ('male', '')],
)
def test_facial_hair_is_skipped_for_non_males_and_for_none(gender, facial_hair):
    """The gate returns before any bpy call, so this runs outside Blender."""
    ctx = body.CharacterBuild(
        s=1.0,
        gender=gender,
        hair_style='auto',
        facial_hair=facial_hair,
        mats=body.CharacterMaterials(
            skin=None,
            hair=None,
            eyes=None,
            eyewhite=None,
            cloth_top=None,
            cloth_bot=None,
            shoes=None,
            lips=None,
        ),
        prop=body.body_proportions(gender, 50),
    )
    body.add_facial_hair(ctx)
    assert ctx.objs == []


def test_a_bald_style_adds_no_hair_geometry():
    """``add_hair`` returns before any bpy call for a bald style."""
    ctx = body.CharacterBuild(
        s=1.0,
        gender='male',
        hair_style='clean bald',
        facial_hair='none',
        mats=body.CharacterMaterials(
            skin=None,
            hair=None,
            eyes=None,
            eyewhite=None,
            cloth_top=None,
            cloth_bot=None,
            shoes=None,
            lips=None,
        ),
        prop=body.body_proportions('male', 50),
    )
    body.add_hair(ctx)
    assert ctx.objs == []
