#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Invariants of Character Studio's Body axes and the pose-reference whitelist.

The two properties these exist to hold, both of which are safety and not taste:

  1. A BODY EDIT NEVER REACHES THE REGISTRY. write_candidate writes exactly one
     file, candidates/<name>_studio.json, and a registry whose mtime moves under
     a body edit is the failure. Turning a candidate into geometry is a reissue,
     which the operator confirms against two cage hashes.

  2. THE POSE REFERENCE IS A WHITELIST OF FILES, NOT A SHAPE CHECK ON A STRING.
     The renderer loads whatever is in conditioning.controlnet_pose_reference as
     a ControlNet input, so an arbitrary path there is an arbitrary image
     reaching the render. Only plates body_plates rendered for THIS character
     are accepted.

A third, quieter one: an axis whose key is not in Anny's roster must be served
as unavailable, never as a slider that writes a key the builder would reject.

Run:  .venv-test/bin/python -m pytest tests/test_charstudio_body.py -q
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)

from zyg_workflows import character_studio as CS  # noqa: E402
from zyg_workflows import paths  # noqa: E402
import zyg_workflows.geom.body_plates as BP  # noqa: E402

REG = os.path.join(CS.MESH_ROOT, 'registry.json')


def _a_body():
    reg = CS._mesh_registry()
    names = sorted(reg.get('derived') or {})
    if not names:
        pytest.skip('no derived body registered')
    return names[0]


# ── the axes are real keys, checked against Anny's own roster ──────────────
@pytest.fixture
def roster():
    """Anny's three key rosters, read off an original body's params.json.

    Deliberately read and never hard-coded, which means the body has to be on the machine:
    the mesh tree is not in this repository, and a frozen copy of the lists here would be
    the exact drift these tests exist to catch.
    """
    r = CS._roster('male')
    if not (r['phenotype'] and r['bone'] and r['local']):
        pytest.skip('no Anny original body in this checkout: %s' % CS.MESH_ROOT)
    return r


def test_every_axis_key_is_in_the_roster(roster):
    """The test that makes these seven sliders more than decoration: each key
    must be one Anny actually accepts, matched the way the builder matches it."""
    bad = []
    for tid, ax in CS.BODY_AXES.items():
        for k in [ax['key']] + list(ax.get('extra') or []):
            if not CS._key_is_real(ax['kind'], k, roster):
                bad.append(f'{tid}:{ax["kind"]}:{k}')
    assert not bad, f'axis keys not in the roster: {bad}'


def test_bone_keys_match_as_substrings_both_sides(roster):
    assert CS._key_is_real('bone', 'clavicle', roster)
    assert len([b for b in roster['bone'] if 'clavicle' in b.lower()]) == 2
    assert not CS._key_is_real('bone', 'thigh', roster), 'there is no bone called thigh — the CLI documents this'


def test_body_axes_reports_state_per_axis():
    st = CS.body_axes(_a_body())
    assert st['ok']
    assert set(st['axes']) == set(CS.BODY_AXES)
    for _tid, ax in st['axes'].items():
        assert ax['state'] in ('found', 'not_found', 'unavailable')
        assert ax['state'] == 'found' or ax['why']


def test_body_axes_refuses_a_character_with_no_body():
    st = CS.body_axes('not-a-registered-body')
    assert st['ok'] is False and 'no registered body' in st['error']


def test_the_anthro_verdict_is_shown_with_its_caveat():
    st = CS.body_axes(_a_body())
    assert st['anthro']['verdict']
    assert 'PRE-EXISTING' in st['anthro']['note']


# ── the write goes to the candidate, and nowhere else ──────────────────────
def test_write_candidate_does_not_touch_the_registry():
    name = _a_body()
    before = os.path.getmtime(REG)
    out = CS.write_candidate(name, {'neck': 0.97}, note='pytest')
    assert out['ok'], out
    assert out['path'].endswith(f'{name}_studio.json')
    assert os.path.getmtime(REG) == before, 'a body edit moved the REGISTRY'
    assert os.path.isfile(out['path'])


def test_the_candidate_records_the_cli_a_reissue_would_declare():
    name = _a_body()
    out = CS.write_candidate(name, {'shoulders': 1.05})
    cli = out['candidate']['cli']
    # shoulders is a bone axis with an extra key; BOTH must be declared
    assert cli['bone_scale']['clavicle'] == 1.05
    assert cli['bone_scale']['shoulder01'] == 1.05
    assert out['candidate']['not_applied'].startswith('This file is a CANDIDATE')


@pytest.mark.parametrize(
    'edits,why',
    [
        ({'shoulders': 9.9}, 'outside'),
        ({'shoulders': 'wide'}, 'not a number'),
        ({'not_an_axis': 1.0}, 'not a body axis'),
    ],
)
def test_out_of_range_and_unknown_axes_are_refused(edits, why):
    out = CS.write_candidate(_a_body(), edits)
    assert out['ok'] is False
    assert any(why in v for v in out['rejected'].values()), out


def test_no_edits_is_refused():
    assert CS.write_candidate(_a_body(), {})['ok'] is False


# ── the pose reference whitelist ───────────────────────────────────────────
def test_pose_reference_is_writable_but_validated():
    spec = CS.FIELDS['conditioning.controlnet_pose_reference']
    assert spec['t'] == 'plate', 'it was read-only; the point was to make it writable'


@pytest.mark.parametrize(
    'bad',
    [
        '/etc/passwd',
        str(paths.ZYG_LORA_DATASETS / 'storyteller_chars') + '/../../../etc/hosts',
        '/tmp/anything.png',
    ],
)
def test_a_path_outside_this_character_s_plates_is_rejected(bad):
    with pytest.raises(ValueError, match='rendered plates'):
        CS._coerce(dict(CS.FIELDS['conditioning.controlnet_pose_reference'], _char=_a_body()), bad)


def test_clearing_the_pose_reference_is_allowed():
    assert CS._coerce(dict(CS.FIELDS['conditioning.controlnet_pose_reference'], _char=_a_body()), '') == ''


def test_is_plate_path_needs_the_file_to_exist(tmp_path):
    name = _a_body()
    d = BP.plates_dir(name)
    assert BP.is_plate_path(name, os.path.join(d, 'front_depth.png')) == os.path.isfile(
        os.path.join(d, 'front_depth.png')
    )
    # a correctly-named file in the WRONG directory is still not a plate
    fake = tmp_path / 'front_depth.png'
    fake.write_bytes(b'x')
    assert BP.is_plate_path(name, str(fake)) is False


def test_a_rendered_plate_is_accepted_when_one_exists():
    name = _a_body()
    man = BP.load_manifest(name)
    if not man:
        pytest.skip('no plates rendered yet')
    view = next(iter(man['views']))
    p = BP.path_for(name, view, 'depth')
    if not os.path.isfile(p):
        pytest.skip('depth plate not on disk')
    assert BP.is_plate_path(name, p) is True
    assert CS._coerce(dict(CS.FIELDS['conditioning.controlnet_pose_reference'], _char=name), p) == os.path.realpath(p)


# ── the character -> body link is reported, never assumed ──────────────────
def test_resolve_body_says_how_it_decided():
    name = _a_body()
    r = CS.resolve_body(name)
    assert r['body'] == name and r['method'] == 'id' and r['certain'] is True
    miss = CS.resolve_body('0000000000ff')
    assert miss['body'] == '' and miss['method'] == 'none' and miss['why']


def test_a_display_name_match_is_marked_uncertain():
    """An inferred link must never be served as a certain one — binding the
    wrong body silently is the shared-filename LoRA failure again."""
    if not os.path.isdir(BP.CHARS_ROOT):
        pytest.skip('no character root on this box')
    for cid in os.listdir(BP.CHARS_ROOT)[:400]:
        r = CS.resolve_body(cid)
        if r['method'] == 'display_name':
            assert r['certain'] is False and 'Nothing on disk records' in r['why']
            return
    pytest.skip('no display-name link on this box')


# ── the plate ledger is four-state ─────────────────────────────────────────
def test_pose_channel_declares_its_state_rather_than_going_missing():
    name = _a_body()
    _rec, glb = BP.body_record(name)
    if not glb:
        pytest.skip('registered GLB missing')
    st = BP._pose_state(glb)
    assert st['state'] in ('found', 'not_found', 'unmeasurable', 'unavailable')
    assert st['why'], 'a non-found state without a reason is a silent gap'


def test_manifest_is_json_and_carries_the_cage_hash():
    man = BP.load_manifest(_a_body())
    if not man:
        pytest.skip('no plates rendered yet')
    json.dumps(man)
    assert 'cage_vert_sha256' in man and 'ledger' in man


# ── the two defects the first plate render shipped, as regressions ─────────
# Both were found by MEASURING the output against something that already
# existed, not by reading the code, which is why they are tests and not
# comments.


def _plate_arrays(name, view):
    import numpy as np
    from PIL import Image

    man = BP.load_manifest(name)
    if not man or view not in (man.get('views') or {}):
        pytest.skip('no plates rendered yet')
    d = BP.plates_dir(name)
    got = {}
    for k in ('depth', 'normal', 'matte'):
        p = os.path.join(d, f'{view}_{k}.png')
        if not os.path.isfile(p):
            pytest.skip(f'{view}_{k}.png not rendered')
        got[k] = np.asarray(Image.open(p).convert('RGB' if k == 'normal' else 'L'), dtype=float)
    return got


def test_normals_are_camera_space_not_world_space():
    """The camera-facing channel must DOMINATE and stay put across views.

    conditioning.normal_map rotates world normals into camera space only when it
    is handed a rotation whose COLUMNS are the camera basis; iterating a Blender
    Matrix yields rows, so the first build transposed one time too many. The
    signature of getting it wrong is the one that module's docstring records:
    B collapses and the channels swing view by view. Measured against
    mesh_control's own pufferball plates, which are known good: front B=215,
    side B=218. The pre-fix body plates read front B=31, side B=126.
    """

    blues = {}
    for view in ('front', 'side'):
        a = _plate_arrays(_a_body(), view)
        m = a['matte'] > 127
        if not m.any():
            pytest.skip('empty matte')
        blues[view] = float(a['normal'][m][:, 2].mean())
    for view, b in blues.items():
        assert b > 170, (
            f'{view} normal mean B={b:.1f} — the camera-facing channel '
            'has collapsed, so this map is not camera-space '
            '(reference sheet reads ~215)'
        )
    assert abs(blues['front'] - blues['side']) < 60, f'B swings between views ({blues}) — the world-space signature'


def test_the_body_is_standing_up_in_its_own_plates():
    """mesh_skeletons exports the cage Z-UP into a glTF, which is Y-up by
    definition, so Blender's importer rotates a file that never needed it and
    the body arrives LYING DOWN — every camera then aimed along its length.
    Measured on skeleton_abel.glb: the registry records stature 1.52 m; the
    file spans 1.5200 in Z and 0.3922 in Y; the pre-fix render reported
    height_m 0.3922, the thickness. The manifest must now agree with the
    registry.
    """
    name = _a_body()
    man = BP.load_manifest(name)
    if not man:
        pytest.skip('no plates rendered yet')
    stature = man.get('stature_recorded_m') or 0.0
    if not stature:
        pytest.skip('this body records no measured stature')
    assert abs(man['height_m'] - stature) <= 0.05 * stature, (
        f'the rendered body measures {man["height_m"]:.4f} m against a recorded '
        f'stature of {stature:.4f} m — it is lying down (up_fix='
        f'{man.get("up_fix")!r})'
    )


def test_a_plate_is_not_a_blank_frame():
    """A failed render writes a valid-looking PNG. The null a plate has to beat:
    a subject that covers the whole frame, or a depth map with one value in it."""
    import numpy as np

    a = _plate_arrays(_a_body(), 'front')
    m = a['matte'] > 127
    cov = float(m.mean())
    assert 0.02 < cov < 0.95, f'matte covers {cov:.3f} of the frame — not a subject'
    assert len(np.unique(a['depth'][m])) > 16, 'depth is flat — nothing was rendered'
