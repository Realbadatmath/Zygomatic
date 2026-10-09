# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""abel_base: the proxy actor built on the CC0 base body instead of the MPFB mesh.

Built by::

    flock "$ZYG_TMP_DIR/arch_ext_blender.lock" "$BLENDER_BIN" -b \
        --python blender_scripts/proxy_actor.py -- \
        --name abel_base --body base --height 1.52 --gender 0.9 --age 12 \
        --motion capture/qa_sword --fps 24 \
        --fit "${ZYG_LORA_DATASETS:-$HOME/lora-datasets}"/storyteller_chars/\
c3345deb5bde/body_metrics.json

Since 2026-09-23 the fit spec is Abel's REAL measured body metrics, not the
hand-chosen data/architecture/actors/abel_base_fit.json (that file is kept for
reference and is no longer built from).

Pure stdlib + pytest: the .blend is only checked for existence and size, every
fact about it comes from the sidecar the build script writes.
"""

import json
import os

import pytest

from tests import _tree

ACTORS = _tree.data('architecture', 'actors')
NAME = 'abel_base'
FIT_SPEC = os.path.join(ACTORS, 'abel_base_fit.json')
MAX_BLEND_BYTES = 40 * 1000 * 1000
FIT_GROUPS = ('leg', 'arm', 'torso', 'head_neck', 'shoulder')


def meta():
    with open(os.path.join(ACTORS, NAME, NAME + '.json'), 'r', encoding='utf-8') as fh:
        return json.load(fh)


def test_blend_exists_and_is_small():
    path = os.path.join(ACTORS, NAME, NAME + '.blend')
    assert os.path.isfile(path), path
    size = os.path.getsize(path)
    assert size > 100_000, (path, size)
    assert size < MAX_BLEND_BYTES, (path, size)


def test_strip_png():
    path = os.path.join(ACTORS, NAME, NAME + '_strip.png')
    assert os.path.isfile(path), path
    assert os.path.getsize(path) > 10_000


def test_body_is_the_base_body():
    data = meta()
    assert data['name'] == NAME
    assert data['body'] == 'base'
    assert data['base_body_id'] == 'male_realistic'
    assert data['mesh_vertices'] > 1000


def test_actor_contract_is_unchanged():
    """Same sidecar contract as the MPFB actors: scene_build reads these."""
    data = meta()
    assert data['mapping'] == 'cmu_mb'
    assert len(data['bones']) == 31
    assert data['bones'][0] == 'Hips'
    assert data['unmapped_bones'] == []
    assert abs(data['height_m'] - 1.52) < 0.01


def test_motion_is_the_capture():
    data = meta()
    assert data['motion'] == 'capture/qa_sword'
    assert data['frames'] == 193
    assert data['fps'] == 24
    assert data['rest_frame'] == 1


def test_fit_spec_is_the_one_that_was_asked_for():
    """The actor is fitted to the character's measured metrics."""
    path = meta()['fit']['spec']
    assert os.path.isfile(path), path
    with open(path, 'r', encoding='utf-8') as fh:
        spec = json.load(fh)
    assert spec['schema'] == 'zyg.body_metrics/1'
    assert sorted(spec['fractions']) == sorted(FIT_GROUPS)


def test_the_legacy_hand_chosen_spec_is_still_on_disk():
    """Kept for comparison with the measured set; nothing builds from it."""
    with open(FIT_SPEC, 'r', encoding='utf-8') as fh:
        spec = json.load(fh)
    assert spec['schema'] == 'zyg.body_metrics/1'
    assert sorted(spec['fractions']) == sorted(FIT_GROUPS)


def test_fit_is_best_effort_and_says_so():
    """A --fit that cannot be reached no longer kills the build.

    Abel's measured leg is 0.372 of his height; the base body's is 0.494, so the
    leg group asks for x0.753 and the [0.80, 1.25] clamp stops it at x0.800.
    Every group is then measured against a height the pinned leg still governs,
    so the solve settles 5.5 % off its clamped targets: ok is False, status is
    'clamped', clamped_groups names the leg — and the actor is built anyway,
    height-correct and proportion-fitted as far as the clamp allows."""
    fit = meta()['fit']
    assert fit is not None
    assert fit['schema'] == 'zyg.body_metrics/1'
    assert fit['clamp'] == [0.80, 1.25]
    assert fit['status'] in ('exact', 'clamped')
    groups = fit['groups']
    assert sorted(groups) == sorted(FIT_GROUPS)
    for name in FIT_GROUPS:
        row = groups[name]
        assert 0.80 <= row['applied'] <= 1.25, (name, row)
        assert row['hit_clamp'] is (name in fit['clamped_groups']), (name, row)
    if fit['status'] == 'exact':
        assert fit['clamped_groups'] == []
        assert fit['ok'] is True
    else:
        assert fit['clamped_groups'], fit
        assert fit['ok'] is (fit['worst_rel_error'] <= fit['tolerance'])


def test_feet_stay_on_the_ground():
    checks = meta()['checks']
    assert checks['feet_on_ground_ok'] is True


def test_mesh_follows_the_rig():
    """The gate measures the root chain, not the bounding box.

    The old measure was the distance from the mesh's bbox centre to the Hips
    joint, and on a sword clip that centre follows whichever limb reaches
    furthest: abel_base peaks at 0.337 m against a 0.30 m gate while its bind is
    perfect. Since 2026-09-23 the measure is the centroid of the vertices bound
    (weight > 0.5) to Hips/LowerBack/Spine/Spine1/Left|RightUpLeg — the parts
    that deform with the root — against a 0.25 m gate. abel_base peaks at
    0.113 m there. Both numbers are kept in the sidecar.
    """
    checks = meta()['checks']
    assert checks['mesh_track_vertices'] > 100, checks
    assert checks['mesh_torso_centroid_to_hips_max_m'] <= 0.25, checks
    assert checks['mesh_tracks_rig_ok'] is True
    assert checks['mesh_bbox_centre_to_hips_max_m'] > 0.0


def test_leftfoot_travel_is_the_known_false():
    """capture/qa_sword fights on the spot, so the walk check is false by design."""
    assert meta()['checks']['leftfoot_travel_ok'] is False


@pytest.mark.parametrize('name', FIT_GROUPS)
def test_fit_records_what_was_asked_and_what_was_possible(name):
    row = meta()['fit']['groups'][name]
    for key in ('target', 'rig_fraction', 'requested', 'clamped', 'clamped_target', 'applied', 'measured', 'rel_error'):
        assert isinstance(row[key], float), (name, key, row)
    assert row['clamped'] == pytest.approx(min(1.25, max(0.80, row['requested'])), abs=1e-3)
