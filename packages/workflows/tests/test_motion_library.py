# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The CMU motion library: every clip present, parseable and cmu_mb-shaped."""

import json
import os

import pytest

from zyg_workflows import motion_library as ML

# The clips are ~2 GB of CMU BVH and are not redistributable from here, so the library
# lives in the asset tree and this whole file is about what is in it.
if not os.path.isfile(ML.LIBRARY_JSON):
    pytest.skip('the motion library is not in this checkout: %s' % ML.ROOT, allow_module_level=True)

EXPECTED_IDS = [
    'cmu/02_01',
    'cmu/07_01',
    'cmu/02_03',
    'cmu/09_01',
    'cmu/02_04',
    'cmu/02_05',
    'cmu/13_17',
    'cmu/14_01',
    'cmu/10_01',
    'cmu/05_02',
    'cmu/05_11',
    'cmu/13_01',
    'cmu/13_26',
    'cmu/13_33',
    'cmu/13_30',
]

VALID_FPS = {60, 120, 240}


@pytest.fixture(scope='module')
def library():
    with open(ML.LIBRARY_JSON, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def test_schema_and_clip_count(library):
    assert library['schema'] == 'zyg.motion_library/1'
    assert library['source'] == 'cmu_mb_bvh'
    assert len(library['clips']) == 15
    assert [c['id'] for c in library['clips']] == EXPECTED_IDS


def test_clips_helper_matches_library(library):
    # clips() is every source; bvh_clips() is the mocap one on its own.
    assert ML.bvh_clips() == library['clips']
    assert ML.authored_clips() == library['authored']
    assert ML.capture_clips() == library.get('capture', [])
    assert ML.edit_clips() == library.get('edit', [])
    assert ML.clips() == (library['clips'] + library['authored'] + library.get('capture', []) + library.get('edit', []))
    for clip_id in EXPECTED_IDS:
        assert ML.clip(clip_id)['id'] == clip_id
        assert ML.clip_path(clip_id).endswith('.bvh')
    assert ML.clip('cmu/nope') is None


@pytest.mark.parametrize('clip_id', EXPECTED_IDS)
def test_clip_file_parses_as_cmu_mb(clip_id):
    rec = ML.clip(clip_id)
    path = ML.clip_path(clip_id)
    assert os.path.isfile(path), path

    hdr = ML.parse_bvh_header(path)
    assert hdr['joints'] == ML.CMU_MB_JOINTS
    assert len(hdr['joints']) == 31
    assert hdr['joints'][0] == 'Hips'
    assert hdr['channels']['Hips'] == [
        'Xposition',
        'Yposition',
        'Zposition',
        'Zrotation',
        'Yrotation',
        'Xrotation',
    ]

    assert hdr['frames'] > 100, clip_id
    assert hdr['frames'] == rec['frames']
    assert hdr['frame_time'] == rec['frame_time']
    assert rec['fps'] == round(1.0 / hdr['frame_time'])
    assert rec['fps'] in VALID_FPS, rec['fps']
    assert rec['root'] == 'Hips'
    assert rec['joints'] == 31
    assert rec['height_units'] == pytest.approx(ML.root_height(hdr))
    assert rec['height_units'] > 0
    assert rec['label'] and rec['tags'] and rec['index_text']


def test_licence_allows_commercial_use(library):
    licence, ack = ML.licence()
    assert licence == library['licence']
    assert 'commercial' in licence
    assert 'free for use in research and commercial' in licence
    assert 'mocap.cs.cmu.edu' in ack
    assert 'NSF EIA-0196217' in ack
    assert library['source_url'] and library['mirror']
    assert library['retrieved'] == '2026-09-15'


def test_licence_and_provenance_files_exist():
    licence_md = os.path.join(ML.ROOT, 'LICENCE.md')
    provenance = os.path.join(ML.ROOT, 'PROVENANCE.json')
    assert os.path.isfile(licence_md)
    assert os.path.isfile(provenance)

    with open(licence_md, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'commercial' in text
    assert 'NSF EIA-0196217' in text

    with open(provenance, 'r', encoding='utf-8') as fh:
        prov = json.load(fh)
    assert prov['commercial'] is True
    assert 'commercial' in prov['licence']
    assert len(prov['files']) == 15


def test_pending_ledger_entry():
    path = os.path.join(
        os.path.dirname(ML.ROOT.rstrip('/')), '..', 'runtime', 'model_licences_pending', 'SCENE_BRIDGE.json'
    )
    path = os.path.normpath(path)
    assert os.path.isfile(path), path

    with open(path, 'r', encoding='utf-8') as fh:
        ledger = json.load(fh)
    assert ledger['rejected'] == []
    entries = [w for w in ledger['weights'] if '*/motion_library/cmu/*.bvh' in w['match']]
    assert len(entries) == 1
    entry = entries[0]
    assert entry['commercial'] is True
    assert 'commercial' in entry['licence']
    assert entry['territory_excluded'] == []
    assert len(entry['sha256']) == 64
    assert entry['verified'] == '2026-09-15'
