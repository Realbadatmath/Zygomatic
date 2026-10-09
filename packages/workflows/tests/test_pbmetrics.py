#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Invariants of prop_mesh/pbmetrics.py — the fit objective for the Pufferball.

These guard the MEASUREMENT, not the creature. The creature is allowed to change; what
must not change is the property that made the measurement trustworthy in the first place.
Three look-dev runs were steered by four metrics that were artefacts nobody had a test
for: an Otsu matte that cut a hole through the belly and inflated "solidity", an amber
"eye" detector locked onto warm belly fur, and anchor mattes made by a different rule from
render mattes. Every one of those would have been caught by a test of the kind below.

Run:  scripts/run_tests.sh tests/test_pbmetrics.py
"""

import os

import numpy as np
import pytest
from PIL import Image

ndimage = pytest.importorskip('scipy.ndimage', reason='pbmetrics needs scipy.ndimage')

from zyg_workflows import paths  # noqa: E402
from zyg_workflows.prop_mesh import pbmetrics as M  # noqa: E402

ANCHOR = str(paths.ZYG_LORA_DATASETS / 'creatures' / 'd0e44ab002ad' / 'contact_sheet' / 'anchors' / 'anchor_full.png')
RENDER = str(paths.ZYG_DATA_ROOT / 'assets' / 'prop_meshes' / 'pufferball' / 'beauty' / 'front_full.png')

needs_anchor = pytest.mark.skipif(not os.path.isfile(ANCHOR), reason='anchor not present')
needs_render = pytest.mark.skipif(not os.path.isfile(RENDER), reason='render not present')

# The accepted take, measured here with framing_stats on 2026-10-08: the anchor ANCHOR
# points at (unchanged since 2026-08-26) and the 2026-08-29 look-dev take of front_full,
# the render the framing finding below was written against. RENDER is a path into the
# operator's asset tree, so the take that answers it changes without this file changing;
# recording the accepted numbers is what keeps the test a statement about the metric.
ACCEPTED_ANCHOR_INK = 0.4748
ACCEPTED_RENDER_INK = 0.3250
ACCEPTED_INK_TOL = 0.05  # a re-render of the same take lands within 5% of its recorded ink


# ── synthetic fixtures: shapes whose answers are known by construction ────────
def _bg(h=256, w=256):
    """A backdrop with BOTH a vertical and a horizontal gradient — the two that broke the
    real matte. A per-row-only backdrop model reads the middle of a side-lit floor as
    subject; a flat one reads the top of the frame as subject."""
    yy, xx = np.mgrid[0:h, 0:w] / float(h)
    base = 0.06 + 0.10 * yy + 0.12 * xx
    return np.stack([base * 0.8, base * 0.9, base], axis=-1)


def _disc(h=256, w=256, r=60, cy=110, cx=128, colour=(0.9, 0.9, 0.85)):
    img = _bg(h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    m = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
    img[m] = colour
    return img, m


def _striped(h=256, w=256, period=8, angle=0.0):
    """A disc filled with parallel bars at a known angle — ground truth for the
    orientation field and the lock-scale spectrum."""
    img, m = _disc(h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    t = xx * np.cos(angle) + yy * np.sin(angle)
    bars = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * t / period))
    img[m] = np.stack([bars, bars, bars * 0.95], -1)[m] * 0.9 + 0.05
    return img, m


# ═════════════════════════════════════════════════════════════════════════════
# matte
# ═════════════════════════════════════════════════════════════════════════════
def test_matte_finds_a_disc_on_a_two_way_gradient():
    img, truth = _disc()
    m, _ = M.estimate_matte(img, close_px=1)
    inter = (m & truth).sum()
    union = (m | truth).sum()
    assert inter / union > 0.93, 'IoU %.3f against a disc of known position' % (inter / union)


def test_matte_backdrop_model_is_bilinear_not_per_row():
    """The per-row-only model is what welded the whole floor to the creature and put
    `ink` 34% high. A backdrop sampled from the edges must reproduce a horizontal
    gradient, not average it away."""
    img = _bg()
    bd = M._backdrop(img)
    left, right = bd[128, 5], bd[128, -5]
    assert right[2] - left[2] > 0.08, 'backdrop lost the horizontal gradient'
    assert np.abs(bd - img).max() < 0.02, 'backdrop should reproduce an empty frame'


def test_matte_rejects_a_disconnected_bright_blob():
    """Bokeh motes and specular pools are bright and are not the subject."""
    img, truth = _disc()
    img[220:228, 200:215] = 1.0  # a mote, far from the disc
    m, _ = M.estimate_matte(img, close_px=1)
    assert not m[224, 207], 'a disconnected bright blob joined the matte'
    assert m[110, 128], 'the subject itself was dropped'


def test_horizon_is_found_by_a_windowed_rise_not_a_single_row_step():
    """A per-row threshold missed the real horizon (largest single-row step 0.044 against
    a 0.06 threshold) and the cut silently never fired."""
    h = w = 256
    m = np.zeros((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]
    m[(yy - 100) ** 2 + (xx - 128) ** 2 <= 55 * 55] = True  # body
    for i, y in enumerate(range(158, 178)):  # floor, widening gradually
        half = 30 + int(4.5 * i)
        m[y, max(0, 128 - half) : min(w, 128 + half)] = True
    m[178:200, 10:246] = True
    y_h = M.find_horizon(m)
    assert y_h is not None, 'horizon not found on a mask that plainly has one'
    assert 150 <= y_h <= 185, 'horizon at %s, expected the widening band' % y_h


def test_horizon_widest_row_is_sought_above_the_floor():
    """A lit floor is WIDER than the creature on it. Taking a global argmax lands the
    'widest row' inside the floor, the downward scan then finds nothing, and the cut is
    dead code that raises nothing."""
    h = w = 256
    m = np.zeros((h, w), bool)
    yy, xx = np.mgrid[0:h, 0:w]
    m[(yy - 90) ** 2 + (xx - 128) ** 2 <= 45 * 45] = True
    m[150:210, 2:254] = True  # floor strictly wider than the body
    assert M.find_horizon(m) is not None


def test_matte_is_made_by_the_same_rule_for_both_sides():
    """measure() must not quietly use a supplied mask for one image and an estimate for
    the other. Phase 1 compared an anchor matte that was closed-and-filled against a raw
    render alpha and the roughness terms became incomparable."""
    img, _ = _disc()
    p = '/tmp/_pbm_same_rule.png'
    Image.fromarray((img * 255).astype(np.uint8)).save(p)
    try:
        assert M.measure(p)['matte_source'] == 'estimated'
        assert M.measure(p, mask_path='/does/not/exist.png')['matte_source'] == 'estimated'
    finally:
        os.remove(p)


# ═════════════════════════════════════════════════════════════════════════════
# orientation
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize('angle_deg', [0.0, 30.0, 60.0, 90.0, 135.0])
def test_orientation_field_recovers_a_known_bar_angle(angle_deg):
    """Bars drawn at a known angle must come back at that angle. `theta` is the direction
    the STRUCTURE runs, which is 90 degrees from the gradient — an easy sign to get wrong,
    and a wrong sign would make every coat comparison exactly backwards."""
    a = np.radians(angle_deg)
    img, m = _striped(angle=a, period=10)
    theta, coh = M.orientation_field(img)
    core = np.zeros_like(m)
    core[70:150, 90:170] = True  # interior only: skip the disc boundary
    use = m & core & (coh > 0.3)
    assert use.sum() > 500
    expect = np.mod(a + np.pi / 2, np.pi)  # bars run perpendicular to their normal
    d = np.abs(np.mod(theta[use] - expect + np.pi / 2, np.pi) - np.pi / 2)
    assert np.degrees(np.median(d)) < 8.0, 'median error %.1f deg at bar angle %s' % (
        np.degrees(np.median(d)),
        angle_deg,
    )


def test_orientation_is_a_director_not_a_vector():
    """Fur has no head or tail: rotating bars by 180 degrees is the SAME field. A metric
    that used a raw angle difference would report a 180-degree error here."""
    i1, _ = _striped(angle=np.radians(20.0))
    i2, _ = _striped(angle=np.radians(200.0))
    t1, c1 = M.orientation_field(i1)
    t2, _ = M.orientation_field(i2)
    use = c1 > 0.3
    d = np.abs(np.mod(t1[use] - t2[use] + np.pi / 2, np.pi) - np.pi / 2)
    assert np.degrees(np.median(d)) < 3.0


def test_radial_deviation_separates_spokes_from_rings():
    """The coat metric's whole job. Spokes (fur pointing straight out, our render) must
    read near 0 degrees; rings (fur laid over the body, the anchor) near 90."""
    h = w = 320
    cy = cx = 160
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    th = np.arctan2(yy - cy, xx - cx)
    disc = rr <= 120
    spokes = _bg(h, w).copy()
    v = 0.5 + 0.5 * np.sign(np.sin(th * 40))
    spokes[disc] = np.stack([v, v, v * 0.96], -1)[disc] * 0.9 + 0.05
    rings = _bg(h, w).copy()
    v = 0.5 + 0.5 * np.sign(np.sin(rr / 3.0))
    rings[disc] = np.stack([v, v, v * 0.96], -1)[disc] * 0.9 + 0.05
    ps = M.radial_deviation_profile(spokes, disc)
    pr = M.radial_deviation_profile(rings, disc)
    assert ps['mean'] < 25.0, 'spokes read %.1f deg, expected near 0' % ps['mean']
    assert pr['mean'] > 65.0, 'rings read %.1f deg, expected near 90' % pr['mean']
    assert M.orientation_distance(ps, pr) > 40.0


# ═════════════════════════════════════════════════════════════════════════════
# the null model — the rule the whole module exists to enforce
# ═════════════════════════════════════════════════════════════════════════════
def test_self_null_is_a_perturbation_not_an_identity():
    """Comparing an image to itself is 0 on every term, which makes selectivity infinite
    and the test vacuous — the first version of this module shipped that and every term
    scored a meaningless 1000."""
    img, _ = _striped()
    p = M.perturb(img, seed=1)
    assert not np.allclose(p, img), 'perturb() returned the input unchanged'
    assert np.abs(p - img).mean() < 0.05, 'perturb() changed the picture, not the sampling'


def test_usable_terms_refuses_a_term_that_cannot_separate():
    null = {'self': {t: 1.0 for t in M.TERMS}, 'far': {t: 1.5 for t in M.TERMS}}
    assert M.usable_terms(null) == {}, 'a selectivity of 1.5 must be refused'
    null['far']['orient'] = 10.0
    assert set(M.usable_terms(null)) == {'orient'}


def test_usable_terms_does_not_reward_a_zero_self_distance():
    """A term that cannot move at all under resampling is suspicious, not excellent; it
    must still be reported with a finite selectivity rather than an infinite one."""
    null = {'self': {t: 0.0 for t in M.TERMS}, 'far': {t: 1.0 for t in M.TERMS}}
    got = M.usable_terms(null)
    assert set(got) == set(M.TERMS)
    assert all(np.isfinite(v) for v in got.values())


# ═════════════════════════════════════════════════════════════════════════════
# real images
# ═════════════════════════════════════════════════════════════════════════════
@needs_anchor
def test_anchor_matte_excludes_the_floor():
    """Regression on the specific artefact that this module was built to notice: with a
    per-row backdrop and no floor cut the anchor matted at ink 0.577 and bbox width 0.994
    — the whole ground plane welded to the creature."""
    m, _ = M.estimate_matte(M.load_rgb(ANCHOR))
    f = M.framing_stats(m)
    assert f['ink'] < 0.52, 'ink %.3f — the floor is back in the matte' % f['ink']
    assert f['w_frac'] < 0.93, 'bbox width %.3f — the floor is back' % f['w_frac']
    assert f['ink'] > 0.36, 'ink %.3f — the cut has started eating the creature' % f['ink']


@needs_anchor
@needs_render
def test_render_reads_as_more_radial_than_the_anchor():
    """The measured coat defect, pinned. The anchor's fur lies over about 41 degrees from
    radial and the production render about 32: ours is the more spike-like coat. If this
    ever inverts, either the groom was fixed or the metric broke, and both need looking at.
    """
    a = M.measure(ANCHOR)['orientation']
    r = M.measure(RENDER)['orientation']
    assert a['mean'] > r['mean'], 'anchor %.1f deg vs render %.1f deg — the sign of the coat defect flipped' % (
        a['mean'],
        r['mean'],
    )
    assert a['kept'] > 0.5 and r['kept'] > 0.5, 'coherence floor is rejecting most pixels'


@needs_anchor
@needs_render
def test_render_is_short_of_the_anchor_in_frame():
    """Framing, which no look-dev round ever measured.

    Pinned to the accepted take's recorded numbers, not to whichever render sits in the
    operator's asset tree: a later look-dev take is a different measurement, and holding
    it to this bar reports the working tree rather than the metric. So the property is
    asserted on the constants (it holds with no files at all), the anchor is held to its
    recorded ink — the matte must not drift under us — and the render on disk is only
    measured against the anchor once its ink shows it IS the accepted take.
    """
    assert ACCEPTED_RENDER_INK < ACCEPTED_ANCHOR_INK, 'the accepted take is not short of the anchor'

    a = M.framing_stats(M.estimate_matte(M.load_rgb(ANCHOR))[0])
    r = M.framing_stats(M.estimate_matte(M.load_rgb(RENDER))[0])
    assert abs(a['ink'] - ACCEPTED_ANCHOR_INK) <= ACCEPTED_INK_TOL * ACCEPTED_ANCHOR_INK, (
        'anchor ink %.3f vs recorded %.3f — the anchor or the matte moved' % (a['ink'], ACCEPTED_ANCHOR_INK)
    )
    if abs(r['ink'] - ACCEPTED_RENDER_INK) > ACCEPTED_INK_TOL * ACCEPTED_RENDER_INK:
        pytest.skip(
            'render on disk is not the accepted take (ink %.3f vs accepted %.3f)' % (r['ink'], ACCEPTED_RENDER_INK)
        )
    assert r['ink'] < a['ink'], 'render ink %.3f vs anchor %.3f' % (r['ink'], a['ink'])


# ═════════════════════════════════════════════════════════════════════════════
# surface detail + the selectivity bar (added after CMA run 1)
# ═════════════════════════════════════════════════════════════════════════════
def _plate(detail_amp, h=256, w=256, seed=0):
    """A teal plate carrying a known amount of high-frequency relief."""
    img = _bg(h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    m = ((yy - 120) / 70.0) ** 2 + ((xx - 128) / 55.0) ** 2 <= 1.0
    rng = np.random.default_rng(seed)
    grain = ndimage.gaussian_filter(rng.standard_normal((h, w)), 1.4)
    grain /= grain.std() + 1e-9
    base = np.stack([np.full((h, w), 0.16), np.full((h, w), 0.55), np.full((h, w), 0.52)], -1)
    base = base * (1.0 + detail_amp * grain)[..., None]
    img[m] = np.clip(base, 0, 1)[m]
    return img, m


def test_plate_region_finds_teal_and_not_white_or_amber():
    img, truth = _plate(0.0)
    img[40:70, 40:90] = (0.95, 0.95, 0.92)  # white crown
    img[200:230, 40:90] = (0.85, 0.62, 0.12)  # amber eye
    m, _ = M.estimate_matte(img, close_px=1)
    reg = M.plate_region(img, m)
    assert reg is not None
    assert reg[120, 128], 'the plate itself was not found'
    assert not reg[55, 65], 'white crown joined the plate region'
    assert not reg[215, 65], 'amber joined the plate region'


@pytest.mark.parametrize('amp', [0.0, 0.05, 0.15])
def test_surface_detail_rises_with_relief(amp):
    img, _ = _plate(amp)
    m, _ = M.estimate_matte(img, close_px=1)
    d = M.surface_detail(img, m)
    assert np.isfinite(d)
    test_surface_detail_rises_with_relief.seen[amp] = d


test_surface_detail_rises_with_relief.seen = {}


def test_surface_detail_is_monotone_in_relief():
    seen = {}
    for amp in (0.0, 0.05, 0.15):
        img, _ = _plate(amp)
        m, _ = M.estimate_matte(img, close_px=1)
        seen[amp] = M.surface_detail(img, m)
    assert seen[0.0] < seen[0.05] < seen[0.15], seen


def test_surface_detail_is_scale_normalised():
    """A plate that is simply BIGGER in frame must not score as more detailed. The term
    exists to answer 'detail per unit of plate', because the framing parameters were the
    largest lever in the search and would otherwise have moved this term for free."""
    small, _ = _plate(0.10, h=256, w=256)
    big = (
        np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize((512, 512), Image.LANCZOS)).astype(float)
        / 255.0
    )
    ds = M.surface_detail(small, M.estimate_matte(small, close_px=1)[0])
    db = M.surface_detail(big, M.estimate_matte(big, close_px=1)[0])
    assert abs(ds - db) / max(ds, 1e-9) < 0.35, 'detail moved %.3f -> %.3f on rescale' % (ds, db)


def test_selectivity_bar_is_ten_not_three():
    """Raised after CMA run 1: at 3.0 the bar admitted `lock_k`, which scored 4.6 on the
    front view while every other term scored 23-270, then carried the largest magnitude in
    the loss and drove the coat to flat blades."""
    null = {'self': {t: 1.0 for t in M.TERMS}, 'far': {t: 5.0 for t in M.TERMS}}
    assert M.usable_terms(null) == {}, 'selectivity 5 must not pass the bar'
    null['far'] = {t: 12.0 for t in M.TERMS}
    assert set(M.usable_terms(null)) == set(M.TERMS)


@needs_anchor
def test_lock_k_is_refused_on_the_front_anchor():
    """The specific regression. lock_k's null denominator is degenerate on the front view:
    the v1 sphere's cross-lock wavenumber is 19.7 against the anchor's 20.1, because a
    smooth ball has no locks and its spectrum is noise that happened to land in the right
    place. A term normalised by an accidentally-correct null is amplified without bound."""
    null_dir = (
        '/tmp/claude-1000/-home-zygomatic-zygomatics-zero/'
        '6a05438a-252c-4117-83fb-c23b453a67d5/scratchpad/pbfit/baseline'
    )
    nullp = os.path.join(null_dir, 'front_full_beauty.png')
    if not os.path.isfile(nullp):
        pytest.skip('v1 null render not present')
    a = M.measure(ANCHOR)
    rgb = M.load_rgb(ANCHOR)
    far = M.compare(a, M.measure(nullp))
    selfd = {
        t: float(np.nanmean([M.compare(a, M.measure_rgb(M.perturb(rgb, seed=s)))[t] for s in range(3)]))
        for t in M.TERMS
    }
    usable = M.usable_terms({'self': selfd, 'far': far})
    assert 'lock_k' not in usable, 'lock_k passed the bar again on the front anchor'
    assert 'detail' in usable and 'orient' in usable and 'ink' in usable


# ═════════════════════════════════════════════════════════════════════════════
# THE COAT DEFENCE — added 2026-08-29 after a 400-evaluation CMA-ES fit drove the
# creature's coat OFF, and the loss rewarded it. Every one of these tests would have
# failed that day; that is what they are for.
# ═════════════════════════════════════════════════════════════════════════════
_NULLS = str(paths.ZYG_LORA_DATASETS / 'creatures' / 'd0e44ab002ad' / 'contact_sheet' / 'nulls')
_BALD_NULL = os.path.join(_NULLS, 'bald', 'front_full_beauty.png')
_SPHERE_NULL = os.path.join(_NULLS, 'sphere', 'front_full_beauty.png')
needs_nulls = pytest.mark.skipif(
    not (os.path.isfile(_BALD_NULL) and os.path.isfile(_SPHERE_NULL)), reason='null renders not present'
)


def _synth_furry(n=384, bare=False, seed=0):
    """A disc with fine oriented 'fur' texture; `bare` leaves a smooth patch on one side.

    Synthetic so the test does not depend on any render staying on disk.
    """
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n]
    cy = cx = n / 2.0
    r = np.hypot(y - cy, x - cx)
    mask = r < n * 0.40
    img = np.full((n, n), 0.45)
    fur = 0.16 * np.sin(r * 2.2 + rng.normal(0, 0.35, (n, n)))
    img = img + fur
    if bare:
        img[(x > cx) & mask] = 0.45  # one half smoothed to flat
    rgb = np.clip(np.dstack([img] * 3), 0, 1)
    return rgb, mask


def test_bald_term_sees_a_bare_patch_that_a_mean_would_average_away():
    """The defect is REGIONAL. Every other term in this file is a whole-subject scalar and
    averages a bare flank against the fur everywhere else; this one takes the largest
    connected smooth COMPONENT, which is what makes a local failure legible."""
    furry_rgb, m = _synth_furry(bare=False)
    bare_rgb, _ = _synth_furry(bare=True)
    furry = M.largest_smooth_patch(furry_rgb, m)
    bare = M.largest_smooth_patch(bare_rgb, m)
    assert bare > 3.0 * furry, 'bare %.4f vs furry %.4f — no separation' % (bare, furry)
    assert bare > 0.30, 'a half-bare subject should register a large patch, got %.4f' % bare


def test_bald_term_is_relative_so_a_uniform_contrast_change_does_not_move_it():
    """RELATIVE to the subject's own median contrast, because the anchors are generated
    images with soft fur and the candidates are sharp Cycles renders: measured, our renders
    carry ~1.7x the anchor's absolute fine-detail energy EVERYWHERE, so any absolute
    texture statistic reads 'less fur' as 'closer to the anchor'. Three absolute candidate
    terms were built and all three failed on exactly this."""
    rgb, m = _synth_furry()
    a = M.largest_smooth_patch(rgb, m)
    dim = np.clip(0.45 + (rgb - 0.45) * 0.5, 0, 1)  # halve every local contrast
    b = M.largest_smooth_patch(dim, m)
    assert abs(a - b) < 0.05, 'relative term moved %.4f under a pure contrast scale' % abs(a - b)


@needs_anchor
@needs_nulls
def test_a_coat_term_is_not_scaled_by_the_sphere_null():
    """THE ACCIDENTALLY-CORRECT-NULL TRAP, second occurrence. `lock_k` hit it in run 1 and
    the selectivity bar was raised to 10; `fill` hit it again here and slipped through.
    The v1 sphere is UNIFORMLY smooth, so relative to its own texture it has no smooth
    PATCH and reads like a well-furred creature. Measured selectivity for `bald` against
    the sphere: 48.9 front, 1.0 side. Against a bald render: 189.5 / 100.6."""
    a = M.measure(ANCHOR)
    self_d = np.mean([abs(M.measure_rgb(M.perturb(M.load_rgb(ANCHOR), seed=s))['bald'] - a['bald']) for s in range(3)])
    far_sphere = abs(M.measure(_SPHERE_NULL)['bald'] - a['bald'])
    far_bald = abs(M.measure(_BALD_NULL)['bald'] - a['bald'])
    assert far_bald / self_d > 50, 'bald null is not selective enough'
    assert far_bald > 2.0 * far_sphere, (
        'the bald null must be far more distant on this term than the sphere '
        '(bald %.4f, sphere %.4f)' % (far_bald, far_sphere)
    )


@needs_anchor
@needs_nulls
def test_usable_terms_routes_coat_terms_to_the_bald_null():
    """A term in COAT_TERMS must be scaled by `far_bald` when it is supplied, and must
    survive on BOTH views. Scaled by the sphere it dies on side_left at selectivity 1.0."""
    assert 'bald' in M.COAT_TERMS
    a = M.measure(ANCHOR)
    self_d = {t: 1e-4 for t in M.TERMS}
    far = M.compare(a, M.measure(_SPHERE_NULL))
    far_bald = M.compare(a, M.measure(_BALD_NULL))
    with_bald = M.usable_terms({'self': self_d, 'far': far, 'far_bald': far_bald})
    assert 'bald' in with_bald
    assert with_bald['bald'] == pytest.approx(far_bald['bald']), 'the coat term was scaled by the wrong null'


def test_the_coat_gate_is_a_gate_and_not_a_term():
    """COAT PRESENCE IS A VALIDITY CONDITION. Measured with framing held equal, only three
    of ten scored terms rank a bald render worse than a furry one; `fill` alone pays more
    for baldness (-0.772) than the `bald` term charges for it (+0.464). A scored term can
    be outvoted by terms that cannot see the defect. A gate cannot."""
    O = pytest.importorskip('zyg_workflows.prop_mesh.pbopt', reason='pbopt pulls the Blender look-dev stack')

    assert issubclass(O.CoatGateFailure, RuntimeError), (
        'must subclass RuntimeError so pre-existing handlers in this file fail SAFE'
    )
    assert 3.2 < O.COAT_GATE < 4.4, (
        'the gate must sit inside the measured separation: furriest passing render 3.19, '
        'least-bald rejected render 4.44'
    )


def test_undercoat_ceiling_is_below_the_coat_bar():
    """The search box must not be able to propose a vector the BUILD will refuse.

    A first cut put the SPEC ceiling at 0.0420 against a build-time bar of 0.0418 — 0.0002
    over, so the optimiser could still reach a region that crashed the build mid-run
    instead of one it simply could not enter."""
    O = pytest.importorskip('zyg_workflows.prop_mesh.pbopt', reason='pbopt pulls the Blender look-dev stack')

    hi = {p: h for p, _, h, _ in O.SPEC}['LOOK.UNDERCOAT2.len']
    shortest_lock, clearance = 0.045, 0.93  # pufferball_look: 'cap', COAT_CLEARANCE
    assert hi < shortest_lock * clearance, 'SPEC ceiling %.4f is not below the coat invariant bar %.4f' % (
        hi,
        shortest_lock * clearance,
    )


def test_the_lock_shape_box_brackets_the_approved_values():
    """Seven of twenty parameters finished PINNED to a bound, three of them this group's
    corner: widest, sparsest, flattest — loose petals, not fur. A search that ends in a
    corner says the box is wrong, not that the corner is good."""
    O = pytest.importorskip('zyg_workflows.prop_mesh.pbopt', reason='pbopt pulls the Blender look-dev stack')

    b = {p: (lo, hi) for p, lo, hi, _ in O.SPEC}
    for path, approved in (
        ('LOOK.TUFT7.w_per_L', 0.16),
        ('LOOK.TUFT7.w_max', 0.012),
        ('LOOK.TUFT7.spacing', 0.0075),
        ('LOOK.TUFT7.thick', 0.30),
    ):
        lo, hi = b[path]
        assert lo < approved < hi, '%s box [%g, %g] does not bracket approved %g' % (path, lo, hi, approved)


# ═════════════════════════════════════════════════════════════════════════════
# the direction test (2026-09-01)
#
# Selectivity says a term can tell the anchor from a known-bad. It cannot say the term
# points the right way on the failure you care about, and that gap cost two searches.
# Measured on the morning of 2026-09-01: with framing held equal the composite ranked the
# BALD null BETTER than the furry production render (0.4973 vs 0.5081), i.e. the repaired
# objective still paid for baldness. Every test below fails on that day's code.
# ═════════════════════════════════════════════════════════════════════════════
_DS = str(paths.ZYG_LORA_DATASETS / 'creatures' / 'd0e44ab002ad' / 'contact_sheet') + '/'
_BALD = _DS + 'nulls/bald/%s_beauty.png'
_FURRY = _DS + 'refs/furry/%s_beauty.png'
_ANCHORS = {'front_full': _DS + 'anchors/anchor_full.png', 'side_left': _DS + 'anchors/anchor_side.png'}


def _have(*paths):
    return all(os.path.isfile(p) for p in paths)


def test_fill_is_declared_a_coat_term():
    """`fill` is 'how solid the coat is' by its own definition, so it must be routed as a
    coat term — scaled by the bald null and subject to the direction test. It was scaled by
    the v1 sphere, whose fill (0.6469) is closer to the anchor (0.6755) than production
    (0.6311), which normalised it by 0.0286 into a term worth 1.55 that paid for baldness."""
    assert 'fill' in M.COAT_TERMS
    assert 'bald' in M.COAT_TERMS


def test_direction_report_marks_a_term_that_prefers_the_known_bad():
    """A term whose distance to the BAD reference is smaller than to the GOOD one fails."""
    prof = {'bins': list(np.zeros(M.N_AZIMUTH_BINS)), 'weight': list(np.ones(M.N_AZIMUTH_BINS))}
    anchor = {
        'framing': {'ink': 0.50, 'fill_bbox': 0.60},
        'lab': {'L': 50, 'a': 0, 'b': 0},
        'orientation': prof,
        'lock': {'k_centroid': 20.0},
        'silhouette': {'iso': {'0.004': 1.0, '0.02': 1.0}},
        'detail': 0.5,
        'bald': 0.02,
    }
    good = dict(anchor, framing={'ink': 0.49, 'fill_bbox': 0.50}, bald=0.03)
    bad = dict(anchor, framing={'ink': 0.30, 'fill_bbox': 0.61}, bald=0.10)
    rep = M.direction_report(anchor, bad, good)
    assert rep['ink']['passes'] is True  # bad is further on ink
    assert rep['fill']['passes'] is False  # bad is CLOSER on fill -> pays for the defect
    assert rep['bald']['passes'] is True


def test_usable_terms_refuses_a_coat_term_that_fails_direction():
    null = {
        'self': {'fill': 0.001, 'ink': 0.001},
        'far': {'fill': 0.10, 'ink': 0.10},
        'far_bald': {'fill': 0.10, 'ink': 0.10},
        'direction': {'fill': {'passes': False}, 'ink': {'passes': True}},
    }
    out = M.usable_terms(null)
    assert 'fill' not in out, 'a coat term that prefers the bald render must be refused'
    assert 'ink' in out


def test_usable_terms_keeps_a_NON_coat_term_that_fails_direction():
    """lab_L measuring colour is allowed to prefer a bald render's colour; it just must not
    be what decides whether the creature has a coat. Only COAT_TERMS are gated."""
    assert 'lab_L' not in M.COAT_TERMS
    null = {'self': {'lab_L': 0.01}, 'far': {'lab_L': 1.0}, 'direction': {'lab_L': {'passes': False}}}
    assert 'lab_L' in M.usable_terms(null)


def test_direction_gate_is_inert_when_no_reference_pair_is_supplied():
    """Fail SAFE: with no direction pair the gate must not silently drop terms."""
    null = {'self': {'fill': 0.001}, 'far': {'fill': 0.10}, 'far_bald': {'fill': 0.10}}
    assert 'fill' in M.usable_terms(null)


@pytest.mark.parametrize('vid', ['front_full', 'side_left'])
def test_composite_ranks_a_furry_render_better_than_a_bald_one(vid):
    """THE END-TO-END PROPERTY, and the one that was false. Framing is held equal (both are
    canon renders of the same creature), so the only thing separating them is the coat."""
    apath = _ANCHORS[vid]
    if not _have(apath, _BALD % vid, _FURRY % vid):
        pytest.skip('reference renders not on disk')
    anchor = M.measure(apath)
    bald, furry = M.measure(_BALD % vid), M.measure(_FURRY % vid)
    rgb = M.load_rgb(apath)
    self_d = {
        t: float(np.nanmean([M.compare(anchor, M.measure_rgb(M.perturb(rgb, seed=s)))[t] for s in range(3)]))
        for t in M.TERMS
    }
    scale = M.usable_terms(
        {
            'self': self_d,
            'far': M.compare(anchor, M.measure(_DS + 'nulls/sphere/%s_beauty.png' % vid)),
            'far_bald': M.compare(anchor, bald),
            'direction': M.direction_report(anchor, bald, furry),
        }
    )

    def loss(m):
        d = M.compare(anchor, m)
        return float(np.mean([min(d[t] / s, 2.0) for t, s in scale.items() if t in d and np.isfinite(d[t]) and s > 0]))

    assert loss(furry) < loss(bald), (
        '%s: the objective scores the BALD render as closer to the anchor '
        '(%.4f) than the furry one (%.4f)' % (vid, loss(bald), loss(furry))
    )


def test_pbopt_renders_one_process_per_view():
    """A view must be a function of the parameters, not of the views rendered before it.
    Measured 2026-09-01: side_left rendered after front_full differs from side_left
    rendered alone over 26% of its pixels, and `back` after two views drifts further —
    the drift is a pure function of how many views preceded it in the process."""
    from zyg_workflows.prop_mesh import pbopt

    assert pbopt.Evaluator.PER_VIEW_PROCESS is True
