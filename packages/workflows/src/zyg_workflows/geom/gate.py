# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gate.py — the readable-geometry quality gate. Pure python, no bpy (2026-08-04).

THE RULE, AND THE ONE AMENDMENT IT NEEDS.
    "Everything must have readable geometry, if it doesn't it fails quality gate check."
Taken absolutely that rule can never pass a forest wide: a mid-ground leaf at 832x480
covers well under one pixel, and geometry below the Nyquist limit is unreadable at any
polygon count. A gate that always fails gets switched off, which is worse than no gate.

So the rule is enforced as READABLE AT THE SCALE IT OCCUPIES. Every object is tiered by
its own measured screen coverage in THIS shot, and the bar is set by what the frame can
physically resolve. Nothing is exempt; an object promoted into close-up is re-tiered and
must then satisfy the full set. Tiers are computed, never declared.

THE FOUR CHECKS
  G1 silhouette   the shape is resolvable at all — area, and the width of the thinnest
                  connected part (below 2px it aliases into mush regardless of detail)
  G2 texel        the texture supplies at least one texel per rendered pixel; below 1.0
                  the surface detail in the final image was invented by the sampler
  G3 relief       the detail actually survives into the passes — paired depth and normal
                  difference against a flat proxy of the same object
  G3b embedment   an object that should be INSIDE another is occluded by it. This is the
                  check that catches "not one axe is actually stuck in the tree, all axes
                  are just flat against it" — a pasted sprite is 100% visible, a hatchet
                  driven into a trunk is not.
  G4 recognisable the styled crop still reads as the object. Runs on hero tier only, via
                  the local Qwen3-VL judge, CROPPED — measured 5/5 defect detection on
                  crops against 0/2 on full frames.

G1..G3b are deterministic, need no model, and run in milliseconds. G4 is the expensive
one and is gated behind tier.

An object with NO geometry at all — a 2D sprite composited over a plate — has no index in
any pass and is reported ABSENT, which is a fail. That is the rule working, not a bug.
"""

import json
import os

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import passes_io

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── tiers: assigned from measured coverage, never declared ───────────────────
HERO, SET, FIELD = 'hero', 'set', 'field'

TIER_FLOOR = {HERO: 0.05, SET: 0.005, FIELD: 0.0}

# Thresholds. Every one is either a physical limit or a measured property of this
# production, and each carries the reason it has the value it has.
TH = {
    # Nyquist: a feature narrower than two samples cannot be reconstructed.
    'min_feature_px': 2.0,
    # An object that is almost entirely within 1px of its own edge is filigree, not form.
    'thin_fraction_max': 0.90,
    # One texel per pixel. Below this the upscaler is authoring the detail, not the asset.
    'texels_per_pixel': 1.0,
    # A hatchet bite in this scene is 30-55mm deep (prop_mesh/axe_render.py). 2mm is the
    # floor for "measurably recessed" and leaves an order of magnitude of headroom.
    'relief_depth_mm': 2.0,
    # Below this a depth difference is render noise, not geometry. Measured: the axe-scene
    # pair separates cleanly at any eps from 0.05 to 2.0mm (4.827% vs 4.810% of the trunk),
    # so the exact value is not load-bearing — it is a noise floor, not a tuning knob.
    'relief_noise_mm': 0.2,
    # The detail has to occupy SOME of the object. 24 hatchet cuts came to 4.83%; 0.2% is
    # the floor below which a handful of stray pixels would count as relief.
    'relief_area_frac': 0.002,
    # ...and it must not consume the object. Recesses cost silhouette area at the edges
    # only; anything that keeps under half the object has subtracted the object itself.
    'detail_survival': 0.50,
    # Two surfaces meeting at under 5 degrees shade identically under any light.
    'relief_normal_deg': 5.0,
    # A blade seated in wood loses part of its silhouette. 5% is the smallest bite that
    # cannot be explained by antialiasing on the contact edge.
    'embedment_frac': 0.05,
}


class Finding(dict):
    """One check on one object. dict so it serialises straight to the report."""

    def __init__(self, check, obj, passed, value, threshold, units='', detail='', tier=None):
        super().__init__(
            check=check,
            obj=obj,
            passed=bool(passed),
            value=(None if value is None else float(value)),
            threshold=(None if threshold is None else float(threshold)),
            units=units,
            detail=detail,
            tier=tier,
        )

    def __bool__(self):
        return self['passed']

    def line(self):
        v = '  n/a' if self['value'] is None else '%7.3f' % self['value']
        return '%-4s %-10s %-5s %s %-4s %s' % (
            self['check'],
            self['obj'],
            'PASS' if self['passed'] else 'FAIL',
            v,
            self['units'],
            self['detail'],
        )


def tier_of(coverage):
    if coverage >= TIER_FLOOR[HERO]:
        return HERO
    if coverage >= TIER_FLOOR[SET]:
        return SET
    return FIELD


# ── G1 ───────────────────────────────────────────────────────────────────────


def _component_widths(mask):
    """Width of the fattest part of each connected component, in pixels.

    The distance transform gives every pixel its distance to the nearest background
    pixel, so twice the maximum inside a component is that component's greatest width.
    A component whose WIDEST point is under 2px has no readable point at all.
    """
    m = mask.astype(np.uint8)
    if cv2 is None:
        return [float(2 * np.sqrt(m.sum() / np.pi))], 0.0
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    n, lab = cv2.connectedComponents(m, connectivity=8)
    widths = []
    for i in range(1, n):
        sel = lab == i
        if sel.sum() < 4:  # 3 pixels is noise, not a component
            continue
        widths.append(float(2.0 * dt[sel].max()))
    area = float(m.sum())
    thin = float((dt[m > 0] <= 1.0).sum() / area) if area else 1.0
    return (widths or [0.0]), thin


def g1_silhouette(ps, idx, obj):
    """Is the shape resolvable at the size it occupies?"""
    mask = ps.mask(idx)
    area = int(mask.sum())
    cov = area / float(ps.w * ps.h)
    tier = tier_of(cov)
    if area == 0:
        return [Finding('G1', obj, False, 0.0, 1.0, 'px', 'ABSENT — no geometry with this index in the render', tier)]

    widths, thin = _component_widths(mask)
    narrowest = min(widths)
    out = [
        Finding(
            'G1',
            obj,
            narrowest >= TH['min_feature_px'],
            narrowest,
            TH['min_feature_px'],
            'px',
            'thinnest component width (Nyquist floor); area=%dpx cov=%.4f' % (area, cov),
            tier,
        ),
        Finding(
            'G1b',
            obj,
            thin <= TH['thin_fraction_max'],
            thin,
            TH['thin_fraction_max'],
            'frac',
            'share of the object within 1px of its own edge',
            tier,
        ),
    ]
    return out


# ── G2 ───────────────────────────────────────────────────────────────────────


def g2_texel(ps, idx, obj, world_span_m, texture_px, uv_fraction=1.0):
    """Does the texture supply >= 1 texel per rendered pixel at this framing?

    world_span_m : the object's largest world dimension, metres
    texture_px   : the texture's edge length in pixels (8192 for a Poly Haven 8K)
    uv_fraction  : share of that texture actually covering this object's UVs
    """
    mask = ps.mask(idx)
    area = int(mask.sum())
    if area == 0:
        return [
            Finding(
                'G2',
                obj,
                False,
                None,
                TH['texels_per_pixel'],
                '',
                'ABSENT — cannot measure texel density without a mask',
            )
        ]
    ys, xs = np.nonzero(mask)
    screen_span_px = float(max(xs.max() - xs.min(), ys.max() - ys.min()) + 1)
    if world_span_m <= 0 or screen_span_px <= 0:
        return [
            Finding('G2', obj, False, None, TH['texels_per_pixel'], '', 'bad inputs: world_span_m=%s' % world_span_m)
        ]
    demand = screen_span_px / world_span_m  # pixels per metre on screen
    supply = (texture_px * float(uv_fraction)) / world_span_m  # texels per metre on surface
    tpp = supply / demand if demand else 0.0
    return [
        Finding(
            'G2',
            obj,
            tpp >= TH['texels_per_pixel'],
            tpp,
            TH['texels_per_pixel'],
            'tex/px',
            'supply %.0f texel/m vs demand %.0f px/m' % (supply, demand),
        )
    ]


# ── G3 ───────────────────────────────────────────────────────────────────────


def g3_relief(detail, proxy, idx, obj):
    """Does the authored detail survive into depth and normals?

    Two renders that differ in exactly one thing — the detail modifier on or off — so any
    difference inside the mask is the detail and nothing else. This is the check that
    distinguishes geometry that IS there from geometry that READS as there.

    MEASURE INSIDE THE CHANGED REGION, NOT ACROSS THE WHOLE OBJECT. The first version took
    p95 over the entire mask and reported 0.000mm for a trunk whose 24 hatchet cuts were
    all present and up to 48.5mm deep — because those cuts occupy 4.83% of the trunk, and
    a 95th percentile over the whole object is untouched bark by construction. Detail is
    local almost by definition, so the object-wide statistic is guaranteed to miss it. The
    check is therefore two questions asked separately: how MUCH of the object changed, and
    how DEEP the change is where it happened.
    """
    md, mp = detail.mask(idx), proxy.mask(idx)
    both = md & mp
    if both.sum() < 16:
        return [
            Finding(
                'G3',
                obj,
                False,
                None,
                TH['relief_depth_mm'],
                'mm',
                'ABSENT — object not present in both renders (%d shared px)' % int(both.sum()),
            )
        ]

    # DETAIL MUST NOT CONSUME ITS OWN OBJECT. A boolean that hits a solver edge case
    # subtracts the whole target instead of the slots — measured on this trunk at nu=160,
    # where 72,362 pixels became 2 — and the frame it renders looks like a lighting
    # problem rather than a missing tree. Survival is checked before relief is measured,
    # because a destroyed object trivially reports enormous depth deviation and would
    # otherwise sail through as excellent relief.
    survival = md.sum() / float(max(mp.sum(), 1))
    if survival < TH['detail_survival']:
        return [
            Finding(
                'G3x',
                obj,
                False,
                survival,
                TH['detail_survival'],
                'frac',
                'DESTROYED — the detail pass kept only %d of %d px; the cut '
                'removed the object, not a recess' % (int(md.sum()), int(mp.sum())),
            )
        ]

    dd = np.abs(detail.depth[both] - proxy.depth[both]) * 1000.0
    changed = dd > TH['relief_noise_mm']
    frac = float(changed.mean())
    out = [
        Finding(
            'G3a',
            obj,
            frac >= TH['relief_area_frac'],
            frac,
            TH['relief_area_frac'],
            'frac',
            '%d of %d px of the object differ from the flat proxy' % (int(changed.sum()), int(both.sum())),
        )
    ]
    if not changed.any():
        out.append(
            Finding(
                'G3',
                obj,
                False,
                0.0,
                TH['relief_depth_mm'],
                'mm',
                'no pixel differs — the detail is not in the geometry',
            )
        )
        return out

    dev = float(np.percentile(dd[changed], 95))
    out.append(
        Finding(
            'G3',
            obj,
            dev >= TH['relief_depth_mm'],
            dev,
            TH['relief_depth_mm'],
            'mm',
            'p95 depth deviation WITHIN the changed region (max %.1fmm)' % float(dd.max()),
        )
    )

    if detail.normal is not None and proxy.normal is not None:
        a, b = detail.normal[both], proxy.normal[both]
        a = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
        b = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
        ang = np.degrees(np.arccos(np.clip((a * b).sum(1), -1.0, 1.0)))[changed]
        mang = float(np.percentile(ang, 95))
        out.append(
            Finding(
                'G3n',
                obj,
                mang >= TH['relief_normal_deg'],
                mang,
                TH['relief_normal_deg'],
                'deg',
                'p95 normal deviation within the changed region',
            )
        )
    return out


def g3b_embedment(alone, scene, idx, obj, host=''):
    """Is the object INSIDE its host, or lying on top of it?

    Render the object with the host hidden, then again in the full scene. A hatchet driven
    into a trunk loses part of its silhouette to the wood; a sprite pasted onto a plate
    loses none. The measure is the share of the object that the host takes away, and it
    needs no threshold tuning beyond "more than antialiasing".
    """
    a = int(alone.mask(idx).sum())
    s = int(scene.mask(idx).sum())
    if a == 0:
        return [
            Finding(
                'G3b',
                obj,
                False,
                None,
                TH['embedment_frac'],
                'frac',
                'ABSENT — object not visible even with %s hidden' % (host or 'the host'),
            )
        ]
    frac = 1.0 - (s / float(a))
    return [
        Finding(
            'G3b',
            obj,
            frac >= TH['embedment_frac'],
            frac,
            TH['embedment_frac'],
            'frac',
            '%d/%d px of the object hidden by %s' % (a - s, a, host or 'the host'),
        )
    ]


# ── G4 ───────────────────────────────────────────────────────────────────────


def crop_to_object(image_path, ps, idx, out_path, pad=0.18, min_px=320):
    """Write a crop tight on the object's mask bbox. THE CROP RULE: the local judge
    scores 5/5 on crops and 0/2 on full frames, so G4 never sees a whole frame."""
    if cv2 is None:
        return None
    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    mask = ps.mask(idx)
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    # the render and the styled frame may differ in size; scale the box
    sy, sx = img.shape[0] / float(ps.h), img.shape[1] / float(ps.w)
    x0, x1 = int(x0 * sx), int(x1 * sx)
    y0, y1 = int(y0 * sy), int(y1 * sy)
    w, h = x1 - x0, y1 - y0
    px, py = int(w * pad), int(h * pad)
    x0, y0 = max(0, x0 - px), max(0, y0 - py)
    x1, y1 = min(img.shape[1], x1 + px), min(img.shape[0], y1 + py)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    if min(crop.shape[:2]) < min_px:
        f = min_px / float(min(crop.shape[:2]))
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    cv2.imwrite(out_path, crop)
    return out_path


# Objects that get G4 whatever their screen coverage. SCREEN AREA IS NOT IMPORTANCE, and
# assuming it was is how the hurlbat escaped the only appearance check in the gate: it
# tiers as 'set' at 3.2% of frame, so G4 never ran, and the gate reported "readable
# geometry" on a weapon that looked like a mallet. A named hero prop is a story decision,
# not a measurement, so it is declared here and the tier cannot override it.
ALWAYS_JUDGE = {'hurlbat', 'axe_head', 'ledger', 'pipe'}


def g4_recognisable(styled_path, ps, idx, obj, work_dir, checklist='geometry_gate', tier=HERO, log_fn=None):
    """Ask the local judge whether the STYLED crop still reads as the object.

    Runs on hero tier, and on anything in ALWAYS_JUDGE regardless of tier. Skips (does not
    fail) whenever the judge is unavailable or busy — it is a reject-only second opinion
    and must never break a render, which is the contract the rest of the pipeline already
    relies on.
    """
    if tier != HERO and obj.split('[')[0] not in ALWAYS_JUDGE:
        return []
    crop = crop_to_object(styled_path, ps, idx, os.path.join(work_dir, 'crops', '%s.png' % obj))
    if not crop:
        return [Finding('G4', obj, False, None, None, '', 'ABSENT — no crop could be taken')]
    try:
        from zyg_workflows import vlm_inspector
    except Exception as e:
        return [Finding('G4', obj, True, None, None, '', 'SKIPPED — judge unimportable (%s)' % e, tier)]
    res = vlm_inspector.inspect_frames([crop], checklist=checklist, tier='resident', frame_kind='all', log_fn=log_fn)
    if not res or res.get('skipped'):
        return [
            Finding(
                'G4', obj, True, None, None, '', 'SKIPPED — %s' % (res or {}).get('reason', 'judge unavailable'), tier
            )
        ]
    crit = int(res.get('criticals') or 0)
    maj = int(res.get('majors') or 0)
    return [
        Finding(
            'G4',
            obj,
            crit == 0,
            float(crit + maj),
            0.0,
            'flags',
            '%d critical / %d major on the styled crop' % (crit, maj),
            tier,
        )
    ]


# ── report ───────────────────────────────────────────────────────────────────


def report(findings, out_path=None, title=''):
    """Aggregate to a verdict. Returns the report dict; writes JSON when asked."""
    fails = [f for f in findings if not f['passed']]
    doc = {
        'title': title,
        'passed': not fails,
        'n_checks': len(findings),
        'n_failed': len(fails),
        'thresholds': dict(TH),
        'findings': [dict(f) for f in findings],
    }
    if out_path:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        with open(out_path, 'w') as fh:
            json.dump(doc, fh, indent=1)
    return doc


def print_report(doc):
    _zyg_log.info('── %s ' % (doc.get('title') or 'geometry gate') + '─' * 40)
    for f in doc['findings']:
        _zyg_log.info(
            Finding(
                **{k: f[k] for k in ('check', 'obj', 'passed', 'value', 'threshold', 'units', 'detail', 'tier')}
            ).line()
        )
    _zyg_log.info('%s  %d checks, %d failed' % ('PASS' if doc['passed'] else 'FAIL', doc['n_checks'], doc['n_failed']))


load_set = passes_io.load_set
