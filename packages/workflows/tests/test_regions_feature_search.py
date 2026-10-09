#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression test for geom.form.regions._r_feature_search patch seeding.

THE BUG. The resolver grows a connected patch of same-polarity hits and it used to seed
that growth from `best`, the argmax over RELIEF ALONE, while `seeds` holds only the
vertices that clear relief AND contrast:

    regions.py:336   g = seeds[lab == lab[list(seeds).index(int(idx[best]))]]
    ValueError: 11467 is not in list

When the strongest-relief vertex fails the contrast cut it is not in `seeds`, the
vertex-id lookup misses, and the resolver raises instead of returning. It never fired on
the 20 shipped body regions — the 9 feature_search ones have zero hits and return before
this line — but it fires reliably on head windows, where relief is large and the collar is
itself curved so contrast is low. MEASURED on the anny neutral: the orbital-margin window
(+20.03 mm peak at contrast 2.65, against a 3.70 floor) crashes.

WHAT THE FIX MUST PRESERVE. The patch is grown from the strongest QUALIFYING vertex, but
the evidence still reports the GLOBAL peak in best_relief_mm / best_contrast, because that
is what makes a negative result checkable rather than merely asserted.

The fast test builds the condition synthetically — no cage, no anny — so it states exactly
which arrangement of relief and contrast was broken. The slow test replays the real head
window that crashed.

    python3 -m pytest tests/test_regions_feature_search.py -q
"""

import os
import sys

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

np = pytest.importorskip('numpy', reason='geom.form needs numpy')
sparse = pytest.importorskip('scipy.sparse', reason='_r_feature_search needs scipy.csgraph')

try:
    from zyg_workflows.geom.form import regions as RG
    from zyg_workflows.geom.form.regions import context as RGC  # the module _r_feature_search runs in
except Exception as e:  # noqa: BLE001
    pytest.skip('geom.form.regions will not import here (%s: %s)' % (type(e).__name__, e), allow_module_level=True)


# ── the synthetic window ────────────────────────────────────────────────────
# 12 window vertices on a path graph, given NON-CONTIGUOUS cage ids starting at 100. The
# ids must not equal their positions: the bug was precisely a vertex-id used where a
# position into `seeds` was wanted, and contiguous-from-zero ids would hide it.
_N_CAGE = 200
_WIN_IDS = np.arange(100, 112)  # 12 vertices, path 100-101-...-111
_PEAK_POS = 7  # window position of the global peak
_STRONG = (2, 3, 4)  # qualifying cluster, the expected patch
_WEAK = (9, 10)  # a second, weaker qualifying cluster

# relief as a fraction of stature, and contrast. FEATURE_MIN_FRAC = 2.45e-3 and
# FEATURE_MIN_CONTRAST = 3.7 are the cage's own relief null p99 (curvature.RELIEF_NULL_P99)
# and are read, never restated, so this test cannot drift away from the shipped cut.
_MIN_F = RG.FEATURE_MIN_FRAC
_MIN_C = RG.FEATURE_MIN_CONTRAST


def _profile(peak_contrast):
    """(relief_frac, contrast) per window position. peak_contrast is the whole experiment."""
    rel = np.full(len(_WIN_IDS), 0.2 * _MIN_F)  # ordinary skin: nowhere near the cut
    con = np.full(len(_WIN_IDS), 0.5 * _MIN_C)
    rel[_PEAK_POS] = 3.7 * _MIN_F  # the global relief peak, by a wide margin
    con[_PEAK_POS] = peak_contrast
    for p in _STRONG:  # clears both cuts; strongest that does
        rel[p], con[p] = 2.0 * _MIN_F, 1.35 * _MIN_C
    for p in _WEAK:  # clears both cuts, but weaker
        rel[p], con[p] = 1.2 * _MIN_F, 1.13 * _MIN_C
    return rel, con


class _FakeCage:
    """Just enough of the module's shared context to run one resolver call."""

    def __init__(self, peak_contrast):
        self.rel, self.con = _profile(peak_contrast)
        v = np.zeros((_N_CAGE, 3), np.float64)
        v[:, 2] = np.linspace(0.0, 1.7, _N_CAGE)
        # a plain path 100-101-...-111. _STRONG and _WEAK come out as separate components
        # without cutting anything, because connected_components runs on the SEED subgraph
        # and positions 5-8 never qualify, so nothing joins {2,3,4} to {9,10}.
        rows = list(_WIN_IDS[:-1]) + list(_WIN_IDS[1:])
        cols = list(_WIN_IDS[1:]) + list(_WIN_IDS[:-1])
        adj = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(_N_CAGE, _N_CAGE))
        self.ctx = {'v': v, 'faces': None, 'zmin': 0.0, 'S': 1.686, 'fz': np.linspace(0.0, 1.0, _N_CAGE), 'adj': adj}

    def install(self, monkeypatch):
        # Patch the module that _r_feature_search actually reads its helpers from: since
        # regions became a package (bd96d10) the resolver and _ctx/_window_mask/_ball/_relief
        # all live in regions/context.py, and the package __init__ only re-exports them --
        # a patch on the package would never reach the call sites.
        monkeypatch.setattr(RGC, '_ctx', lambda: self.ctx)
        mask = np.zeros(_N_CAGE, bool)
        mask[_WIN_IDS] = True
        monkeypatch.setattr(RGC, '_window_mask', lambda w: mask)
        monkeypatch.setattr(RGC, '_ball', lambda seed, radius_frac: int(seed))
        monkeypatch.setattr(RGC, '_relief', self._relief)

    def _relief(self, g, **kw):
        pos = int(np.nonzero(_WIN_IDS == int(g))[0][0])
        return {'relief_frac_stature': float(self.rel[pos]), 'contrast': float(self.con[pos])}


def _peak_vertex():
    return int(_WIN_IDS[_PEAK_POS])


# ── the regression ──────────────────────────────────────────────────────────
def test_peak_outside_seeds_does_not_raise(monkeypatch):
    """High relief, low contrast, peak absent from seeds — the exact crashing condition."""
    cage = _FakeCage(peak_contrast=0.64 * _MIN_C)  # 2.35 at the shipped 3.7 floor
    cage.install(monkeypatch)
    monkeypatch.delenv('ZYG_REGIONS_PATCH_SEED_FIX', raising=False)

    g, ev = RG._r_feature_search({'synthetic': True}, 'protrusion')

    assert g is not None and len(g), 'the window has qualifying vertices; it must resolve'
    assert ev['peak_qualifies'] is False, 'test is not constructing the bug any more'
    assert _peak_vertex() not in set(int(i) for i in g)


def test_patch_grows_from_the_strongest_QUALIFYING_vertex(monkeypatch):
    """Intent preserved: the patch is the connected component of the best vertex that
    actually cleared both cuts — not the global peak's, and not the weaker cluster's."""
    cage = _FakeCage(peak_contrast=0.64 * _MIN_C)
    cage.install(monkeypatch)
    g, ev = RG._r_feature_search({'synthetic': True}, 'protrusion')

    assert sorted(int(i) for i in g) == sorted(int(_WIN_IDS[p]) for p in _STRONG)
    assert ev['patch_seed_vertex'] in set(int(_WIN_IDS[p]) for p in _STRONG)
    assert ev['n_hits'] == len(_STRONG) + len(_WEAK)
    assert ev['n_patch'] == len(_STRONG)


def test_evidence_still_reports_the_GLOBAL_peak(monkeypatch):
    """The negative-result evidence is the reason this resolver is trustworthy. The patch
    seed must not overwrite it, or a reader can no longer check what the window held."""
    cage = _FakeCage(peak_contrast=0.64 * _MIN_C)
    cage.install(monkeypatch)
    g, ev = RG._r_feature_search({'synthetic': True}, 'protrusion')

    S_mm = cage.ctx['S'] * 1000.0
    assert ev['best_vertex'] == _peak_vertex()
    assert ev['best_relief_frac'] == pytest.approx(3.7 * _MIN_F)
    assert ev['best_relief_mm'] == pytest.approx(3.7 * _MIN_F * S_mm)
    assert ev['best_contrast'] == pytest.approx(0.64 * _MIN_C)
    # and the peak really is stronger than the patch it did not seed
    assert abs(ev['best_relief_mm']) > abs(ev['patch_seed_relief_mm'])
    assert ev['peak_in_patch'] is False


def test_qualifying_peak_is_unchanged_by_the_fix(monkeypatch):
    """Control. When the global peak DOES clear both cuts it is the best qualifying vertex
    too, so the fix must return exactly what the pre-fix line returned."""
    cage = _FakeCage(peak_contrast=1.5 * _MIN_C)
    cage.install(monkeypatch)

    monkeypatch.setenv('ZYG_REGIONS_PATCH_SEED_FIX', '1')
    g_new, ev_new = RG._r_feature_search({'synthetic': True}, 'protrusion')
    monkeypatch.setenv('ZYG_REGIONS_PATCH_SEED_FIX', '0')
    g_old, ev_old = RG._r_feature_search({'synthetic': True}, 'protrusion')

    assert sorted(int(i) for i in g_new) == sorted(int(i) for i in g_old)
    assert ev_new['patch_seed_vertex'] == ev_old['patch_seed_vertex'] == _peak_vertex()
    assert ev_new['peak_qualifies'] is True


def test_rollback_flag_restores_the_crash(monkeypatch):
    """ZYG_REGIONS_PATCH_SEED_FIX=0 is a real rollback, and this pins what it rolls back to.
    If this stops raising, the flag has quietly stopped meaning anything."""
    cage = _FakeCage(peak_contrast=0.64 * _MIN_C)
    cage.install(monkeypatch)
    monkeypatch.setenv('ZYG_REGIONS_PATCH_SEED_FIX', '0')

    with pytest.raises(ValueError, match='is not in list'):
        RG._r_feature_search({'synthetic': True}, 'protrusion')


# ── slow layer: the real window that crashed ────────────────────────────────
@pytest.mark.slow
def test_real_orbital_margin_window_resolves(monkeypatch):
    pytest.importorskip('torch', reason='_r_feature_search builds its context on torch (the gpu extra)')
    """Replay the measured head window on the actual anny neutral. ~40 s: it builds the
    13,718-vertex cage and probes a geodesic ball per window vertex.
        python3 -m pytest tests/ -q -m slow
    """
    monkeypatch.delenv('ZYG_REGIONS_PATCH_SEED_FIX', raising=False)
    window = dict(fz=(0.930, 0.955), x=(0.015, 0.055), y=(-0.120, -0.050))
    g, ev = RG._r_feature_search(window, 'protrusion')  # used to raise ValueError here

    assert g is not None and len(g)
    assert ev['best_relief_mm'] > 15.0  # measured +20.03 mm
    assert ev['best_contrast'] < RG.FEATURE_MIN_CONTRAST  # measured +2.65 vs 3.70
    assert ev['peak_qualifies'] is False
