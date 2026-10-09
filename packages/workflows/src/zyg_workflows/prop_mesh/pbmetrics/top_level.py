# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pbmetrics.py — dense, null-validated image measurements for the Pufferball fit.

WHY THIS EXISTS. Three look-dev convergence runs (68 agents, ~10 h) closed on a critic
verdict of "zero majors / close" against a render the operator called far off at a glance.
Two causes, both structural:

  1. The severity rubric was `major = "different creature" or "obviously CG-flat"`. A coat
     of radial needles where the anchor has overlapping locks is still the same creature and
     is not flat, so it scored MINOR. "Zero majors" never meant "matches".
  2. The only dense number in the loop was a DINO embedding similarity. DINO gives 0.78 to
     the picture in question and 0.83 to a WORSE one, so at this fidelity it has no
     discriminating power at all. It is a coarse identity alarm, not a fit metric.

Phase 1 of that same work also died on FOUR harness terms that were artefacts (an Otsu matte
that cut a hole through the belly and inflated "solidity"; an amber "eye" gate that matched
warm-lit belly fur; anchor mattes closed-and-filled while render mattes were raw alpha).
The agents chased all four and the picture got worse while the score went up.

So this module has one rule, enforced in code, not in comments:

    NO METRIC IS USABLE UNTIL ITS NULL MODEL IS MEASURED.

`null_report()` runs every metric over pairs whose answer is known in advance — anchor vs
itself (must be ~perfect), anchor vs its own mirror (must be ~perfect for direction-free
terms), anchor vs the v1 sphere render (must be terrible) — and prints the dynamic range.
A metric that cannot separate those is not a metric, and `usable_terms()` will refuse to
include it in the composite loss. That refusal is the whole point of the file.

WHAT IT MEASURES, and why each term exists:

  matte / silhouette     the outline, at several blur scales. Multi-scale because BOTH
                         images are spiky — the question is spiky at WHICH scale.
  orientation field      structure-tensor direction + coherence of the fur. This is the
                         term the old harness never had, and the coat is the biggest
                         visible defect. Compared REGISTRATION-FREE, as deviation from the
                         radial direction, so it needs no correspondence between two
                         differently-shaped subjects.
  lock scale             characteristic cross-lock wavelength from the power spectrum,
                         normalised by subject width: "how many locks across the body".
                         Needles and shingles differ here by construction.
  framing                subject extent and ink coverage in frame. Measured, because the
                         current render is 25-29% short of the anchor and nothing in the
                         old loop looked at it.
  colour                 CIELAB medians inside the matte, and per-region when an index
                         pass is supplied.

DEPENDENCIES are numpy + scipy + PIL ONLY. Deliberately not cv2: geom/passes_io imports cv2
at module scope, the test venv does not carry it, and a test that skips itself when cv2 is
missing stops guarding the thing it exists for.

CONVENTIONS. Images are float64 RGB in [0,1] unless named `_u8`. Masks are bool. Angles for
orientation are DIRECTORS in [0, pi) — fur has no head or tail — so every comparison goes
through the double-angle representation and never through a raw angle difference.
"""

import math
import os
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

from zyg_workflows.prop_mesh.pbmetrics.colour import lab_stats, largest_smooth_patch, surface_detail
from zyg_workflows.prop_mesh.pbmetrics.constants import COHERENCE_FLOOR
from zyg_workflows.prop_mesh.pbmetrics.fields import (
    framing_stats,
    lock_scale,
    orientation_distance,
    orientation_field,
    radial_deviation_profile,
    silhouette_stats,
)
from zyg_workflows.prop_mesh.pbmetrics.io_matte import estimate_matte, largest_component, load_mask, load_rgb


# ═════════════════════════════════════════════════════════════════════════════
# top level
# ═════════════════════════════════════════════════════════════════════════════
def measure_rgb(rgb, mask=None, label=''):
    """Every metric for one already-loaded image."""
    if mask is None:
        mask, _ = estimate_matte(rgb)
    return {
        'path': label,
        'framing': framing_stats(mask),
        'silhouette': silhouette_stats(mask),
        'orientation': radial_deviation_profile(rgb, mask),
        'lock': lock_scale(rgb, mask),
        'lab': lab_stats(rgb, mask),
        'detail': surface_detail(rgb, mask),
        'bald': largest_smooth_patch(rgb, mask),
        '_mask': mask,
    }


def measure(path, mask_path=None):
    """Every metric for one image on disk.

    `mask_path` is accepted but should almost never be used HERE. The pufferball data
    passes render BALD (`set_fur(False)` in pufferball_sheet.py), so the shipped
    control/*_matte.png covers the SOLID body only — 20% of frame against the furry
    subject's 29% — and feeding it in would compare the anchor's furry outline with the
    render's shaved one. Phase 1 of the look-dev lost two rounds to exactly this class of
    mistake (anchor matte closed-and-filled vs render raw alpha). Both sides therefore get
    estimate_matte() by default, which is the only treatment that is identical for a
    painting and a render.
    """
    rgb = load_rgb(path)
    mask = None
    src = 'estimated'
    if mask_path and os.path.isfile(mask_path):
        mask = load_mask(mask_path)
        if mask.shape != rgb.shape[:2]:
            raise ValueError('mask %s is %s, image %s is %s' % (mask_path, mask.shape, path, rgb.shape[:2]))
        mask = largest_component(mask)
        src = 'supplied'
    out = measure_rgb(rgb, mask, label=path)
    out['matte_source'] = src
    return out


def dump_visuals(path, out_dir, mask_path=None, tag=None):
    """Write what the metrics actually SAW: the matte, and the orientation field.

    This is not a nicety. Four of phase 1's harness terms were artefacts nobody looked at
    — a matte with a hole through the belly inflated "solidity" for two rounds, and an
    "eye" detector that had locked onto warm belly fur set an eye target 93% too high. A
    metric you have not looked at is a rumour. Every number this module reports is
    reproduced here as a picture.

    Writes <tag>_matte.png (subject in white, rejected pixels dimmed) and
    <tag>_orient.png (hue = lock direction, value = coherence, masked to the subject).
    """
    os.makedirs(out_dir, exist_ok=True)
    tag = tag or os.path.splitext(os.path.basename(path))[0]
    rgb = load_rgb(path)
    if mask_path and os.path.isfile(mask_path):
        mask = largest_component(load_mask(mask_path))
    else:
        mask, _ = estimate_matte(rgb)
    over = rgb * np.where(mask, 1.0, 0.25)[..., None]
    edge = mask & ~ndimage.binary_erosion(mask, np.ones((3, 3), bool))
    over[edge] = (1.0, 0.0, 1.0)
    p_m = os.path.join(out_dir, '%s_matte.png' % tag)
    Image.fromarray((np.clip(over, 0, 1) * 255).astype(np.uint8)).save(p_m)

    theta, coh = orientation_field(rgb)
    hue = theta / np.pi  # director -> full hue wheel
    val = np.clip(coh / 0.5, 0, 1) * mask
    i = (hue * 6.0).astype(int) % 6
    f = hue * 6.0 - np.floor(hue * 6.0)
    q, t = 1 - f, f
    z = np.zeros_like(hue)
    r = np.choose(i, [np.ones_like(hue), q, z, z, t, np.ones_like(hue)])
    g = np.choose(i, [t, np.ones_like(hue), np.ones_like(hue), q, z, z])
    b = np.choose(i, [z, z, t, np.ones_like(hue), np.ones_like(hue), q])
    vis = np.stack([r, g, b], -1) * val[..., None]
    p_o = os.path.join(out_dir, '%s_orient.png' % tag)
    Image.fromarray((np.clip(vis, 0, 1) * 255).astype(np.uint8)).save(p_o)
    return {
        'matte': p_m,
        'orient': p_o,
        'fg_frac': float(mask.mean()),
        'coh_kept': float((mask & (coh >= COHERENCE_FLOOR)).sum()) / max(mask.sum(), 1),
    }


# Term definitions for the composite loss. `scale` is filled in by null_report() from the
# measured dynamic range; a term with no measured scale is REFUSED by usable_terms().
TERMS = {
    'orient': {'what': 'radial-deviation profile RMS, degrees'},
    'lock_k': {'what': 'cross-lock wavenumber, cycles per subject width'},
    'iso_fine': {'what': 'fine-scale outline roughness'},
    'iso_mid': {'what': 'lock-scale outline roughness'},
    'ink': {'what': 'frame coverage'},
    'fill': {'what': 'coverage inside own bbox — how solid the coat is'},
    'lab_L': {'what': 'median lightness'},
    'lab_ab': {'what': 'median chroma, a/b euclidean'},
    'detail': {'what': 'plate surface relief, scale-normalised'},
    'bald': {'what': 'largest contiguous bare patch, fraction of subject'},
}


def compare(a, b):
    """Raw per-term distances between two `measure()` results. Unweighted and unnormalised
    — normalisation belongs to null_report(), which is the only thing that knows each
    term's real range."""
    out = {}
    out['orient'] = orientation_distance(a['orientation'], b['orientation'])
    out['lock_k'] = abs(a['lock']['k_centroid'] - b['lock']['k_centroid'])
    ai, bi = a['silhouette']['iso'], b['silhouette']['iso']
    ks = sorted(set(ai) & set(bi), key=float)
    out['iso_fine'] = abs(ai[ks[0]] - bi[ks[0]]) if ks else float('nan')
    out['iso_mid'] = abs(ai[ks[1]] - bi[ks[1]]) if len(ks) > 1 else float('nan')
    out['ink'] = abs(a['framing']['ink'] - b['framing']['ink'])
    out['fill'] = abs(a['framing']['fill_bbox'] - b['framing']['fill_bbox'])
    out['lab_L'] = abs(a['lab']['L'] - b['lab']['L'])
    out['lab_ab'] = math.hypot(a['lab']['a'] - b['lab']['a'], a['lab']['b'] - b['lab']['b'])
    out['detail'] = abs(a.get('detail', float('nan')) - b.get('detail', float('nan')))
    out['bald'] = abs(a.get('bald', float('nan')) - b.get('bald', float('nan')))
    return out


def perturb(rgb, seed=0):
    """The SELF null: the same picture, resampled.

    Comparing an image to itself gives exactly 0 on every term, which makes a selectivity
    ratio infinite and the whole test vacuous — the first version of this file shipped that
    mistake and every term scored a meaningless 1000. The honest question is not "does the
    metric return 0 on identical bytes" but "does it stay put under changes that a human
    would call the same picture": sensor/sampling noise, a small exposure shift, and a
    sub-pixel resample. Anything that moves MORE than this under a real difference is
    measuring something; anything that does not, is not.
    """
    rng = np.random.default_rng(seed)
    a = rgb.copy()
    a = a * (1.0 + 0.02)  # +2% exposure
    a = a + rng.normal(0.0, 0.004, a.shape)  # ~1/255 sensor noise
    a = ndimage.gaussian_filter(a, (0.5, 0.5, 0.0))  # sub-pixel resample softening
    return np.clip(a, 0.0, 1.0)


# Terms whose KNOWN-BAD is a bald render rather than the v1 sphere. A coat term scored
# against the sphere is meaningless: the sphere is uniformly smooth, so RELATIVE to its own
# median texture it has no smooth PATCH and reads like a well-furred creature (measured
# selectivity 1.0 on side_left). Scored against a bald-but-correctly-framed render it is
# 100-190. Any term added here must be supplied a 'far_bald' null; if it is not, it falls
# back to the sphere and will simply fail the selectivity bar, which is the safe direction.
COAT_TERMS = ('bald', 'fill')

# THE DIRECTION TEST — the check selectivity cannot make.
#
# Selectivity asks "can this term tell the anchor from a known-bad?". It cannot ask "does
# this term point the right way on the failure I care about", and that gap has now cost
# this project two searches: `lock_k` (a null accidentally right, amplified without bound)
# and `fill` (a term that scores a BALD shell as closer to the anchor than a furred one,
# because skin has no gaps between locks).
#
# So a term routed as a coat term must also pass a pair whose answer is known by
# construction: nulls/bald (known-bad coat) vs refs/furry (known-good coat). A term that
# ranks the bald render CLOSER to the anchor is refused for that view.
#
# MEASURED 2026-09-01, with framing held equal, d(anchor, bald) vs d(anchor, furry):
#   front_full   PASS: bald +86%, ink +328%, iso_fine +215%, lock_k +1%
#                FAIL: fill -67%, iso_mid -95%, lab_L -17%, orient -12%, detail -5%, lab_ab -3%
#   side_left    PASS: bald +184%, iso_fine +41%, fill +42%, ink +20%, iso_mid +14%
#                FAIL: lock_k -49%, detail -58%, lab_L -36%, orient -16%, lab_ab -2%
# `fill` fails on the FRONT and passes on the SIDE, so the refusal is per view — the same
# per-view gating this file already applies to lock_k.
#
# The non-coat terms are NOT refused on this test. `lab_L` measuring colour is allowed to
# prefer a bald render's colour; it simply must not be the thing deciding whether the
# creature has a coat. That is what routing to COAT_TERMS means.
DIRECTION_MARGIN = 0.0


def direction_report(anchor, bad, good):
    """Per-term: is `bad` scored as FURTHER from `anchor` than `good`, as it must be?

    All three are `measure()` results. Returns {term: {'bad', 'good', 'passes'}}.
    """
    db, dg = compare(anchor, bad), compare(anchor, good)
    out = {}
    for t in TERMS:
        b, g = db.get(t, float('nan')), dg.get(t, float('nan'))
        ok = bool(np.isfinite(b) and np.isfinite(g) and b > g * (1.0 + DIRECTION_MARGIN))
        out[t] = {'bad': float(b), 'good': float(g), 'passes': ok}
    return out


def usable_terms(null, min_selectivity=10.0):
    """Which terms earned the right to be in the loss.

    A term is usable when its SELF distance (anchor vs a perturbed anchor — see perturb())
    is small against its FAR distance (anchor vs the v1 sphere render). The ratio is the
    term's selectivity; the same word, and the same bar, that geom/detail_filter.py uses
    for its frequency separator, where the shipped filter scored 1.14 (i.e. no separation
    at all) and the replacement scored 10.25.

    THE BAR IS 10, NOT 3, AND THE REASON IS A MEASURED FAILURE. At 3.0 the first CMA run
    admitted `lock_k`, which scored 4.6 on the front view while every other term scored
    23-270. It then carried the LARGEST magnitude in the whole loss (4.66 against a mean
    of 1.31) and dominated the search, driving the coat to maximum lock width, minimum
    thickness and double spacing — flat blades, which is no more the anchor's plush than
    the needles it replaced.

    The mechanism is worth stating plainly because it is not obvious: every term is
    normalised by its distance to the null, so a null that happens to be nearly RIGHT on
    some term gets a tiny denominator and that term is amplified without bound. The v1
    sphere's cross-lock wavenumber is 19.7 against the anchor's 20.1 — accidentally almost
    correct, because a smooth ball has no locks at all and its spectrum is set by noise.
    Selectivity is necessary and NOT sufficient; scoring also caps each term (see
    pbopt.Evaluator.score) so no single one can run away again.

    ONE NULL CANNOT SCALE EVERY TERM. The v1 sphere is bald and smooth, so it is the right
    known-bad for shape, framing and colour and the WRONG one for anything measuring the
    coat: a term that is fooled in the sphere's own direction gets an accidentally-small
    denominator, which is exactly how `fill` reached 1.55 while preferring a bald render.
    Terms in COAT_TERMS are therefore scaled by `null['far_bald']` when it is supplied.

    Returns {term: scale} for usable terms only, where scale = that term's FAR distance, so
    a normalised term is ~0 for a perfect match and ~1 for "as wrong as its own null".
    """
    out = {}
    for t in TERMS:
        self_d = null['self'].get(t, float('nan'))
        # A term is scaled by the null that is actually BAD at what it measures.
        far_src = null.get('far_bald') if t in COAT_TERMS else None
        far_d = (far_src or null['far']).get(t, float('nan'))
        if not (np.isfinite(self_d) and np.isfinite(far_d)) or far_d <= 1e-12:
            continue
        if self_d <= 1e-12:
            # a term that literally cannot move under resampling is suspicious, not
            # excellent — floor it at 1e-3 of far so selectivity stays finite and reported
            self_d = far_d * 1e-3
        if far_d / self_d < min_selectivity:
            continue
        # A coat term must also point the right way — see DIRECTION_MARGIN above.
        dr = null.get('direction')
        if dr and t in COAT_TERMS and not dr.get(t, {}).get('passes', True):
            continue
        out[t] = far_d
    return out


def null_report(anchor, far, near=None, mirror=True, far_mask=None, near_mask=None, n_self=3):
    """Measure every term against pairs whose answer is known, and print the range.

    `anchor` is the reference image. `far` is an image KNOWN to be badly wrong (the v1
    sphere render). `near` is optional and is the thing under test.

    Columns:
      self    anchor vs perturb(anchor) — the noise floor. Averaged over n_self seeds so
              one unlucky draw cannot set the floor.
      mirror  anchor vs its own mirror. Direction-free terms must be ~0 here. `orient` is
              NOT expected to be 0: its bins are indexed by azimuth around the centroid, so
              a mirror reverses the bin order, and a coat that is genuinely asymmetric (this
              creature's tail is on one side) must show up. Reported, not gated on.
      far     anchor vs the null. Sets each term's scale.

    Nothing in this module may be used in a loss until this has been run and looked at.
    """
    a = measure(anchor)
    f = measure(far, far_mask)
    rgb_a = load_rgb(anchor)
    selfs = [compare(a, measure_rgb(perturb(rgb_a, seed=s), label='perturb%d' % s)) for s in range(n_self)]
    rep = {
        'anchor': anchor,
        'far_path': far,
        'self': {t: float(np.nanmean([s[t] for s in selfs])) for t in TERMS},
        'self_spread': {t: float(np.nanmax([s[t] for s in selfs])) for t in TERMS},
        'far': compare(a, f),
        'raw': {'anchor': _raw(a), 'far': _raw(f)},
    }
    if mirror:
        rep['mirror'] = compare(a, measure_rgb(rgb_a[:, ::-1], label='mirror'))
    if near:
        n = measure(near, near_mask)
        rep['near'] = compare(a, n)
        rep['raw']['near'] = _raw(n)
    rep['usable'] = usable_terms(rep)
    return rep


def _raw(m):
    """The handful of raw numbers behind the distances, for eyeballing artefacts."""
    iso = m['silhouette']['iso']
    ks = sorted(iso, key=float)
    return {
        'ink': m['framing']['ink'],
        'fill_bbox': m['framing']['fill_bbox'],
        'w_frac': m['framing']['w_frac'],
        'h_frac': m['framing']['h_frac'],
        'bottom': m['framing']['bottom'],
        'iso_fine': iso.get(ks[0]) if ks else float('nan'),
        'iso_mid': iso.get(ks[1]) if len(ks) > 1 else float('nan'),
        'orient_mean': m['orientation']['mean'],
        'orient_kept': m['orientation']['kept'],
        'k_centroid': m['lock']['k_centroid'],
        'k_peak': m['lock']['k_peak'],
        'slope': m['lock']['slope'],
        'L': m['lab']['L'],
        'a': m['lab']['a'],
        'b': m['lab']['b'],
    }


def _fmt(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return '    n/a'
    return '%7.4f' % v


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    opts = [a for a in argv[1:] if a.startswith('--')]
    if len(args) < 2:
        print(__doc__)
        print('usage: pbmetrics.py [--dump DIR] <anchor.png> <far.png> [near.png]')
        return 2
    anchor, far = args[0], args[1]
    near = args[2] if len(args) > 2 else None
    near_mask = args[3] if len(args) > 3 else None
    dump = None
    for o in opts:
        if o.startswith('--dump='):
            dump = o.split('=', 1)[1]
    if dump:
        for p, t in [(anchor, 'anchor'), (far, 'null'), (near, 'near')]:
            if p:
                r = dump_visuals(p, dump, tag=t)
                print('dumped %-6s fg=%.3f coh_kept=%.3f -> %s' % (t, r['fg_frac'], r['coh_kept'], r['matte']))
        print()
    rep = null_report(anchor, far, near, near_mask=near_mask)
    print('\nRAW MEASURES')
    keys = list(rep['raw']['anchor'].keys())
    who = [k for k in ('anchor', 'far', 'near') if k in rep['raw']]
    print('%-12s %s' % ('', ' '.join('%9s' % w for w in who)))
    for k in keys:
        print('%-12s %s' % (k, ' '.join('%9.4f' % rep['raw'][w][k] for w in who)))
    cols = ['self', 'mirror', 'far'] + (['near'] if near else [])
    print('\nNULL MODEL — every term, over pairs whose answer is known')
    print('  anchor : %s' % anchor)
    print('  far    : %s   (must be BAD)' % far)
    if near:
        print('  near   : %s   (the thing under test)' % near)
    print()
    print('%-10s %s   %s' % ('term', ' '.join('%8s' % c for c in cols), 'selectivity  verdict'))
    print('-' * 78)
    usable = rep['usable']
    for t in TERMS:
        row = ' '.join(_fmt(rep.get(c, {}).get(t)) for c in cols)
        sd, fd = rep['self'].get(t, float('nan')), rep['far'].get(t, float('nan'))
        sel = (fd / max(sd, fd * 1e-3)) if (np.isfinite(sd) and np.isfinite(fd) and fd > 0) else float('nan')
        mark = 'USABLE' if t in usable else 'REFUSED'
        print(
            '%-10s %s   %8s  %s   %s' % (t, row, ('%.1f' % sel) if np.isfinite(sel) else 'n/a', mark, TERMS[t]['what'])
        )
    print('-' * 78)
    print('%d/%d terms usable (selectivity >= 3.0 against the v1 null)' % (len(usable), len(TERMS)))
    if near:
        print('\nNORMALISED near-distance (0 = anchor, 1 = as wrong as the null):')
        for t, scale in sorted(usable.items()):
            v = rep['near'].get(t, float('nan'))
            if np.isfinite(v):
                print('   %-10s %.3f' % (t, v / scale))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
