# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for ``zyg_workflows.geom.drift_gate``.

The gate reads a character's processed ``cell_*`` directories, summarises each
identity-bearing region's colour in CIELAB and flags cells that sit further than
``k*MAD`` from the corpus median. Every test here builds a synthetic corpus of
tiny PNGs under ``tmp_path`` and redirects the module's ``OUT_ROOT`` there, so
nothing touches the repo's tracked output trees and nothing needs a service.
"""

import json
import os
import sys
import types

import cv2
import numpy as np
import pytest

from zyg_workflows.geom import drift_gate as DG
from zyg_workflows.geom.regions import REGION_IDX

CHAR = 'charabcd1234'

H, W = 80, 80

# (region, row span, column span) — areas chosen to clear drift_gate.MIN_PX:
# hair 1600/900, skin 1600/1200, lips 240/120, brow 40/40, iris 30/24.
BANDS = (
    ('hair_head', (0, 20), (0, 80)),
    ('face_skin', (20, 40), (0, 80)),
    ('lips', (40, 43), (0, 80)),
    ('brow_left', (43, 44), (0, 40)),
    ('brow_right', (43, 44), (40, 80)),
    ('iris_left', (44, 45), (0, 30)),
    ('iris_right', (44, 45), (30, 60)),
)

# BGR. The iris base measures Lab ~(49.8, 0.0, -19.0) — inside the 'grey-blue'
# family box; BROWN_IRIS measures ~(34.9, 18.0, 27.0), well outside it.
BASE_BGR = {
    'hair_head': (30, 30, 30),
    'face_skin': (170, 190, 210),
    'lips': (110, 110, 190),
    'brow_left': (40, 40, 40),
    'brow_right': (40, 40, 40),
    'iris_left': (150, 120, 100),
    'iris_right': (150, 120, 100),
}
BROWN_IRIS = (40, 70, 120)


def _write_cell(root, idx, colours=None, omit=(), areas=None, no_regions=False, no_image=False):
    """Write one ``cell_NN`` directory: regions.png, frame.png and mesh.json."""
    name = 'cell_%02d' % idx
    cell = os.path.join(root, name)
    os.makedirs(cell, exist_ok=True)
    region_map = np.zeros((H, W), np.uint8)
    img = np.zeros((H, W, 3), np.uint8)
    cols = dict(BASE_BGR)
    cols.update(colours or {})
    for reg, (r0, r1), (c0, c1) in BANDS:
        if reg in omit:
            continue
        if areas and reg in areas:
            c1 = c0 + areas[reg]
        region_map[r0:r1, c0:c1] = REGION_IDX[reg]
        img[r0:r1, c0:c1] = cols[reg]
    if not no_regions:
        assert cv2.imwrite(os.path.join(cell, 'regions.png'), region_map)
    img_path = os.path.join(cell, 'frame.png')
    if not no_image:
        assert cv2.imwrite(img_path, img)
    with open(os.path.join(cell, 'mesh.json'), 'w') as fh:
        json.dump({'image': img_path}, fh)
    return name


def _root(tmp_path, monkeypatch):
    """Point the module's OUT_ROOT at tmp_path and return the character root."""
    out = tmp_path / 'char_mesh'
    root = out / CHAR
    root.mkdir(parents=True)
    monkeypatch.setattr(DG, 'OUT_ROOT', str(out))
    return str(root)


def _corpus(root, n=6, colours_by_cell=None, **kw):
    return [_write_cell(root, i, colours=(colours_by_cell or {}).get(i), **kw) for i in range(n)]


def _install_manifest(monkeypatch, entries=None, boom=False):
    """Replace ``zyg_workflows.geom.manifest`` so no real manifest file is read."""

    class _Manifest:
        def __init__(self):
            if boom:
                raise RuntimeError('no manifest on this runner')

        def list(self, kind=None):
            return list(entries or [])

    fake = types.ModuleType('zyg_workflows.geom.manifest')
    fake.Manifest = _Manifest
    import zyg_workflows.geom as geom_pkg

    monkeypatch.setattr(geom_pkg, 'manifest', fake, raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.geom.manifest', fake)
    return fake


def _finding(doc, check, obj):
    return next(f for f in doc['findings'] if f['check'] == check and f['obj'] == obj)


# ── module constants ─────────────────────────────────────────────────────────


def test_clothing_regions_are_not_drift_regions():
    assert set(DG.DRIFT_REGIONS) <= set(REGION_IDX)
    assert 'torso' not in DG.DRIFT_REGIONS
    assert set(DG.MIN_PX) == set(DG.DRIFT_REGIONS)
    assert DG.L_RELAX > 1.0


@pytest.mark.parametrize('family', sorted(DG.FAMILIES))
def test_every_family_box_is_a_non_empty_interval(family):
    box = DG.FAMILIES[family]
    for axis in ('a', 'b'):
        lo, hi = box[axis]
        assert lo < hi


# ── _region_lab ──────────────────────────────────────────────────────────────


def test_region_lab_measures_the_masked_pixels_only():
    img = np.zeros((8, 8, 3), np.uint8)
    region_map = np.zeros((8, 8), np.uint8)
    img[0:4] = BASE_BGR['iris_left']
    region_map[0:4] = REGION_IDX['iris_left']
    lab, n = DG._region_lab(img, region_map, REGION_IDX['iris_left'])
    assert n == 32
    assert lab[0] == pytest.approx(49.8, abs=1.5)
    assert lab[2] < -10.0  # blue-ish: negative b*


def test_region_lab_reports_nothing_for_an_absent_region():
    img = np.zeros((8, 8, 3), np.uint8)
    region_map = np.zeros((8, 8), np.uint8)
    assert DG._region_lab(img, region_map, REGION_IDX['iris_left']) == (None, 0)


# ── run(): corpus assembly ───────────────────────────────────────────────────


def test_run_refuses_a_character_with_no_processed_cells(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match='no processed cells'):
        DG.run(CHAR)


def test_a_consistent_corpus_passes_the_gate(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6)

    doc = DG.run(CHAR)

    assert doc['passed'] is True
    assert doc['n_failed'] == 0
    assert doc['title'] == 'region drift gate — %s' % CHAR
    assert set(doc['regions']) == set(DG.DRIFT_REGIONS)
    for reg, info in doc['regions'].items():
        assert info['cells'] == 6, reg
        assert info['outliers'] == {}, reg
        assert len(info['median_lab']) == 3
        assert len(info['mad']) == 3
    assert [f['check'] for f in doc['findings']] == ['GD1'] * len(DG.DRIFT_REGIONS)


def test_run_writes_the_drift_report_next_to_the_cells(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6)

    doc = DG.run(CHAR)

    written = json.loads((tmp_path / 'char_mesh' / CHAR / 'drift_report.json').read_text())
    assert written['regions'] == doc['regions']
    assert written['passed'] is True
    assert os.path.isdir(root)


def test_a_corpus_too_small_to_judge_is_noted_not_failed(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 4)

    doc = DG.run(CHAR)

    assert doc['passed'] is True
    assert doc['findings'] == []
    for reg, info in doc['regions'].items():
        assert info == {'cells': 4, 'note': 'too few readable cells to judge drift'}, reg


def test_cells_without_a_readable_image_pair_are_skipped(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 5)
    _write_cell(root, 90, no_regions=True)
    _write_cell(root, 91, no_image=True)

    doc = DG.run(CHAR)

    assert doc['regions']['iris_left']['cells'] == 5
    assert 'cell_90' not in doc['regions']['iris_left']['outliers']
    assert 'cell_91' not in doc['regions']['iris_left']['outliers']


def test_an_absent_region_is_never_measured(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6, omit=('lips',))

    doc = DG.run(CHAR)

    assert doc['regions']['lips'] == {'cells': 0, 'note': 'too few readable cells to judge drift'}
    assert doc['regions']['face_skin']['cells'] == 6


def test_a_region_below_its_pixel_floor_is_not_measured(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6, areas={'iris_left': 10, 'brow_left': 8})

    doc = DG.run(CHAR)

    assert doc['regions']['iris_left']['cells'] == 0
    assert doc['regions']['brow_left']['cells'] == 0
    assert doc['regions']['iris_right']['cells'] == 6


# ── run(): outlier detection ─────────────────────────────────────────────────


def test_one_drifted_iris_fails_only_its_own_region(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6, colours_by_cell={3: {'iris_left': BROWN_IRIS}})

    doc = DG.run(CHAR)

    assert doc['passed'] is False
    assert doc['n_failed'] == 1
    outliers = doc['regions']['iris_left']['outliers']
    assert list(outliers) == ['cell_03']
    assert outliers['cell_03']['axis'] in 'Lab'
    assert len(outliers['cell_03']['z']) == 3
    assert outliers['cell_03']['lab'][2] > 0  # warm brown, not blue
    assert _finding(doc, 'GD1', 'iris_left')['passed'] is False
    assert _finding(doc, 'GD1', 'iris_left')['value'] == 1.0
    assert _finding(doc, 'GD1', 'iris_right')['passed'] is True
    assert doc['regions']['iris_right']['outliers'] == {}


def test_drift_on_two_regions_reports_both(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(
        root,
        6,
        colours_by_cell={
            1: {'iris_left': BROWN_IRIS, 'iris_right': BROWN_IRIS},
            4: {'hair_head': (20, 40, 160)},
        },
    )

    doc = DG.run(CHAR)

    assert doc['n_failed'] == 3
    assert list(doc['regions']['iris_left']['outliers']) == ['cell_01']
    assert list(doc['regions']['iris_right']['outliers']) == ['cell_01']
    assert list(doc['regions']['hair_head']['outliers']) == ['cell_04']


@pytest.mark.parametrize(
    ('k', 'expect_outliers'),
    [(0.01, True), (1000.0, False)],
)
def test_k_sets_how_far_from_the_median_is_still_normal(tmp_path, monkeypatch, k, expect_outliers):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    # Spread the iris blue channel so the corpus has a real, non-degenerate MAD.
    jitter = {i: {'iris_left': (100 + 4 * i, 120, 100)} for i in range(6)}
    _corpus(root, 6, colours_by_cell=jitter)

    doc = DG.run(CHAR, k=k)

    assert bool(doc['regions']['iris_left']['outliers']) is expect_outliers
    assert doc['passed'] is not expect_outliers


# ── run(): declared characteristics ──────────────────────────────────────────


@pytest.mark.parametrize('match_by', ['notes', 'refs'])
def test_a_declared_colour_inside_its_family_box_passes(tmp_path, monkeypatch, match_by):
    root = _root(tmp_path, monkeypatch)
    entry = {'mesh': {'characteristics': {'iris_left': {'colour': 'grey-blue'}}}}
    if match_by == 'notes':
        entry['notes'] = 'CharABCD, the lead'
    else:
        entry['refs'] = ['chars/%s/sheet.png' % CHAR]
        entry['notes'] = None
    _install_manifest(monkeypatch, entries=[entry])
    _corpus(root, 6)

    doc = DG.run(CHAR)

    gd2 = _finding(doc, 'GD2', 'iris_left')
    assert gd2['passed'] is True
    assert 'inside the grey-blue family box' in gd2['detail']
    assert gd2['units'] == 'b*'
    assert gd2['threshold'] is None
    assert doc['passed'] is True


def test_a_declared_colour_outside_its_family_box_fails(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(
        monkeypatch,
        entries=[
            {
                'notes': 'charabcd lead',
                'mesh': {'characteristics': {'iris_left': {'colour': 'grey-blue'}}},
            }
        ],
    )
    _corpus(root, 6, colours_by_cell={i: {'iris_left': BROWN_IRIS} for i in range(6)})

    doc = DG.run(CHAR)

    gd2 = _finding(doc, 'GD2', 'iris_left')
    assert gd2['passed'] is False
    assert 'OUTSIDE the grey-blue family box' in gd2['detail']
    assert doc['passed'] is False
    # Uniformly brown is consistent, so no cell is a drift outlier — only GD2 fails.
    assert doc['n_failed'] == 1


@pytest.mark.parametrize(
    'characteristics',
    [
        {'iris_left': {'colour': ''}},  # nothing declared
        {'iris_left': None},  # no properties at all
        {'iris_left': {'colour': 'puce'}},  # not a known family
        {'nose': {'colour': 'brown'}},  # not a drift region: never measured
        {'lips': {'hair': 'long'}},  # declared, but not a colour
    ],
)
def test_undecidable_declarations_add_no_finding(tmp_path, monkeypatch, characteristics):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(
        monkeypatch,
        entries=[{'notes': 'charabcd lead', 'mesh': {'characteristics': characteristics}}],
    )
    _corpus(root, 6)

    doc = DG.run(CHAR)

    assert [f['check'] for f in doc['findings']] == ['GD1'] * len(DG.DRIFT_REGIONS)


@pytest.mark.parametrize(
    'entries',
    [
        [],  # empty manifest
        [{'notes': 'somebody else', 'refs': []}],  # no entry for this character
        [{'notes': 'charabcd lead'}],  # found, but it declares no mesh
        [{'notes': 'charabcd lead', 'mesh': {}}],  # mesh without characteristics
    ],
)
def test_a_character_without_declarations_is_judged_on_drift_alone(tmp_path, monkeypatch, entries):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, entries=entries)
    _corpus(root, 6)

    doc = DG.run(CHAR)

    assert all(f['check'] == 'GD1' for f in doc['findings'])
    assert doc['passed'] is True


def test_an_unreadable_manifest_does_not_sink_the_gate(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6)

    doc = DG.run(CHAR)

    assert doc['passed'] is True
    assert all(f['check'] == 'GD1' for f in doc['findings'])


# ── main() ───────────────────────────────────────────────────────────────────


def test_main_returns_zero_and_prints_one_line_per_region(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6)

    assert DG.main([CHAR]) == 0

    out = capsys.readouterr().out
    for reg in DG.DRIFT_REGIONS:
        assert reg in out
    assert out.count('cells=6') == len(DG.DRIFT_REGIONS)
    assert 'OUTLIERS' not in out


def test_main_returns_two_and_names_the_drifted_cells(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    _corpus(root, 6, colours_by_cell={2: {'iris_left': BROWN_IRIS}})

    assert DG.main([CHAR]) == 2

    out = capsys.readouterr().out
    assert 'OUTLIERS: cell_02(' in out


def test_main_passes_k_through_to_run(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path, monkeypatch)
    _install_manifest(monkeypatch, boom=True)
    jitter = {i: {'iris_left': (100 + 4 * i, 120, 100)} for i in range(6)}
    _corpus(root, 6, colours_by_cell=jitter)

    assert DG.main(['--k', '0.01', CHAR]) == 2
    assert 'OUTLIERS' in capsys.readouterr().out

    assert DG.main(['--k', '1000', CHAR]) == 0
    assert 'OUTLIERS' not in capsys.readouterr().out


def test_main_rejects_a_missing_char_id(capsys):
    with pytest.raises(SystemExit) as excinfo:
        DG.main([])
    assert excinfo.value.code == 2
    assert 'char_id' in capsys.readouterr().err
