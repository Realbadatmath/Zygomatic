# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PHOTOGRAMMETRY SCAN INGEST — photographs in, high-frequency displacement out.

ORCHESTRATION, SYNTHETIC CAPTURE (plumbing test only), the consent gate, the self-test
and the command line. Moved verbatim out of the old single-file scan_ingest.py
(lines 2307-2646); the first line of this docstring is what `main()` prints as the CLI
description, so it is the old module docstring's first line unchanged.
"""

import argparse
import json
import math
import os
import time
import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    CONSENT_REQUIRED_KEYS,
    DEFAULT_SUBDIV_LEVEL,
    RESIDUAL_CUTOFF_FRAC,
    SCHEMA,
    STAGES,
    ScanIngestError,
    VALID_SCALE_KINDS,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _quads_to_tris,
    _stature_of,
    _target_cage,
    _try_cv2,
)
from zyg_workflows.geom.scan_ingest.sfm import (
    stage_sfm,
)
from zyg_workflows.geom.scan_ingest.scale import (
    stage_scale,
)
from zyg_workflows.geom.scan_ingest.dense import (
    stage_dense,
)
from zyg_workflows.geom.scan_ingest.align import (
    stage_align,
)
from zyg_workflows.geom.scan_ingest.residual import (
    stage_residual,
)
from zyg_workflows.geom.scan_ingest.emit import (
    _validate_consent,
    stage_emit,
)


# ==================================================================================
# ORCHESTRATION
# ==================================================================================
def ingest(
    photo_dir,
    target_character,
    out_dir,
    *,
    scale=None,
    consent=None,
    stages=STAGES,
    subdiv_level=DEFAULT_SUBDIV_LEVEL,
    cutoff_frac=RESIDUAL_CUTOFF_FRAC,
    dense_method='auto',
    verbose=True,
):
    """Photographs in, high-frequency displacement out. See the module docstring.

    `scale` and `consent` are both REQUIRED (and both are validated before the expensive
    SfM runs, so a missing consent record costs a second rather than an hour). Stages can
    be run individually by passing a subset of STAGES; each reads the previous stages'
    artefacts from out_dir.
    """
    os.makedirs(out_dir, exist_ok=True)
    if 'emit' in stages or 'sfm' in stages:
        _validate_consent(consent)  # fail before spending an hour on SIFT
    if 'sfm' in stages and not isinstance(scale, dict):
        raise ScanIngestError('scale declaration is required; see stage_scale.__doc__')

    report = {
        'schema': SCHEMA,
        'target_character': target_character,
        'photo_dir': os.path.abspath(photo_dir),
        'out_dir': os.path.abspath(out_dir),
        'stages_requested': list(stages),
        'stages': {},
    }
    t0 = time.time()
    for st in STAGES:
        if st not in stages:
            continue
        if st == 'sfm':
            report['stages'][st] = stage_sfm(photo_dir, out_dir, verbose=verbose)
        elif st == 'scale':
            report['stages'][st] = stage_scale(out_dir, scale, verbose=verbose)
        elif st == 'dense':
            report['stages'][st] = stage_dense(out_dir, method=dense_method, verbose=verbose)
        elif st == 'align':
            report['stages'][st] = stage_align(out_dir, target_character, verbose=verbose)
        elif st == 'residual':
            report['stages'][st] = stage_residual(
                out_dir, target_character, subdiv_level=subdiv_level, cutoff_frac=cutoff_frac, verbose=verbose
            )
        elif st == 'emit':
            report['stages'][st] = stage_emit(out_dir, consent=consent, verbose=verbose)
    report['seconds'] = round(time.time() - t0, 1)
    _atomic_json(os.path.join(out_dir, 'ingest_report.json'), report)
    return report


# ==================================================================================
# SYNTHETIC CAPTURE — PLUMBING TEST ONLY
# ==================================================================================
def synthetic_capture(
    out_dir, character='female', n_views=36, width=900, height=1200, subdiv_level=1, seed=0, ss=2, verbose=True
):
    """Render our OWN mesh from many perspective views, to exercise the ingest end to end.

    THIS IS A PLUMBING TEST AND NOTHING ELSE. Photogrammetry of our own renders can only
    ever recover our own mesh, so a good result here proves that the code runs — it proves
    NOTHING about what a real scan of a real person would yield. Every quality question
    (sway, speculars, hair, clothing, coverage) is a capture question and none of them
    exist in a synthetic render.

    Two things are deliberately made EASY here, and both would be hard in reality:
      * the surface is given a dense object-space pseudo-random albedo, so SIFT has
        features everywhere. Real skin is nearly featureless at this scale, which is
        precisely why real human photogrammetry is hard.
      * the light is fixed in WORLD space and purely Lambertian, so shading is
        view-independent. That is what cross-polarisation is trying to buy you.
    """
    cv2 = _try_cv2()
    if cv2 is None:
        raise ScanIngestError('cv2 is required for the synthetic capture')
    from zyg_workflows.geom import mesh_skeletons as MS

    os.makedirs(out_dir, exist_ok=True)

    v, f = _target_cage(character)
    if subdiv_level > 0:
        v, f, _ = MS._subdivide(v, f, subdiv_level)
        v = np.asarray(v, np.float64)
    tris = _quads_to_tris(f)

    # object-space albedo: a deterministic pseudo-random value per triangle, driven by the
    # centroid, so the SAME patch has the SAME colour from every view
    # THE FREQUENCY MATTERS. A first attempt used sinusoids at ~0.15 m wavelength and SfM
    # refused to initialise at all ("no good initial image pair"): smooth colour gradients
    # give SIFT almost nothing to key on. What SIFT wants is texture at the scale of a few
    # pixels on the subject, so the octaves below run at 0.02-0.005 m wavelength — a
    # random-looking mosaic over the skin. That is a statement about the TEST, not about
    # reality: real skin is nearly featureless at this scale, which is precisely why real
    # human photogrammetry is hard and why this synthetic run cannot speak to scan quality.
    cen = v[tris].mean(axis=1)
    rs = np.random.RandomState(seed)
    alb = np.zeros((len(tris), 3))
    for octave, k in enumerate((320.0, 690.0)):
        w = 0.5**octave
        for c in range(3):
            dirs = rs.normal(size=(2, 3))
            dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
            ph = rs.uniform(0, 2 * np.pi, 2)
            alb[:, c] += w * (np.sin(k * (cen @ dirs[0]) + ph[0]) * np.cos(k * (cen @ dirs[1]) + ph[1]))
    alb = np.clip(0.5 + 0.55 * alb / 1.5, 0.06, 1.0)

    e1 = v[tris[:, 1]] - v[tris[:, 0]]
    e2 = v[tris[:, 2]] - v[tris[:, 0]]
    fn = np.cross(e1, e2)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    L = np.array([0.3, -0.8, 0.5])
    L /= np.linalg.norm(L)  # FIXED IN WORLD SPACE

    c = v.mean(0)
    S = _stature_of(v)
    R_orbit = 1.6 * S
    # supersample: at subdiv 1 a triangle is ~1.4 px on the final image, and flat-shaded
    # subpixel triangles ALIAS — the texture turns to noise that does not repeat between
    # views and SIFT finds nothing stable. Rendering ss x and area-downsampling is what
    # makes the albedo actually view-consistent at the pixel level.
    Wr, Hr = width * ss, height * ss
    fpx = 0.9 * Hr  # ~35 mm equivalent
    K = np.array([[fpx, 0, Wr / 2.0], [0, fpx, Hr / 2.0], [0, 0, 1.0]])

    rings = ((0.30, 12), (0.52, 14), (0.72, 10))
    specs = []
    for zf, cnt in rings:
        cnt = max(4, int(round(cnt * n_views / 36.0)))
        for k in range(cnt):
            specs.append((2 * math.pi * k / cnt, zf))
    paths = []
    zmin = v[:, 2].min()
    for n, (a, zf) in enumerate(specs):
        eye = np.array([c[0] + R_orbit * math.cos(a), c[1] + R_orbit * math.sin(a), zmin + zf * S])
        fwd = c - eye
        fwd /= np.linalg.norm(fwd)
        up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, up)
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        Rcw = np.stack([right, -up, fwd])  # world -> camera
        tcw = -Rcw @ eye
        P = v @ Rcw.T + tcw
        vis = P[:, 2] > 1e-6
        uv = P @ K.T
        uv = uv[:, :2] / np.maximum(uv[:, 2:3], 1e-9)
        depth = P[tris].mean(axis=1)[:, 2]
        facing = np.einsum('ij,ij->i', fn, eye - v[tris[:, 0]]) > 0
        onscreen = vis[tris].all(axis=1)
        u = uv[tris]
        inview = (
            (u[:, :, 0].max(1) >= 0) & (u[:, :, 0].min(1) <= Wr) & (u[:, :, 1].max(1) >= 0) & (u[:, :, 1].min(1) <= Hr)
        )
        keep = np.nonzero(facing & onscreen & inview & (depth > 0))[0]
        keep = keep[np.argsort(-depth[keep])]  # painter's algorithm
        # FLAT light on purpose: a strong key leaves the shaded side of the body with
        # too little contrast for SIFT (measured: 790 keypoints on the lit side, 49 on the
        # shaded side at 0.25 ambient). This is the synthetic version of the protocol's
        # 'flat indirect light' rule in docs/photogrammetry_capture.md §3.3.
        lam = 0.62 + 0.38 * np.clip(fn @ L, 0, 1)
        img = np.full((Hr, Wr, 3), 30, np.uint8)
        pts = np.round(uv).astype(np.int32)
        for fi in keep:
            col = np.clip(255.0 * alb[fi] * lam[fi], 0, 255).astype(np.uint8)
            cv2.fillConvexPoly(img, pts[tris[fi]], (int(col[0]), int(col[1]), int(col[2])))
        if ss > 1:
            img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
        p = os.path.join(out_dir, 'synth_%03d.png' % n)
        cv2.imwrite(p, img)
        paths.append(p)
        if verbose and (n + 1) % 10 == 0:
            _log(verbose, '  rendered %d/%d' % (n + 1, len(specs)))
    _log(verbose, 'synthetic capture: %d views in %s (stature %.4f m)' % (len(paths), out_dir, S))
    return {
        'paths': paths,
        'stature_m': S,
        'character': character,
        'note': 'SYNTHETIC. Proves plumbing only; proves nothing about scan quality.',
    }


SYNTHETIC_CONSENT = {
    'subject': 'SYNTHETIC — geom.mesh_skeletons character render, no human subject',
    'granted_by': 'n/a (no human subject exists; do not substitute a real person here)',
    'date': 'n/a',
    'licence': 'house asset — generated in-repo from the anny parametric body',
    'licence_evidence': "no external asset; the source geometry is this repo's own "
    'registered character at data/assets/mesh_skeletons/registry.json. '
    'A REAL scan requires a signed grant quoted here, per '
    'docs/photogrammetry_capture.md §5.',
    'document': 'n/a — synthetic self-test',
    'recognisable_likeness_permitted': False,
    'scope': 'self-test only',
}


def _consent_gate_check():
    """The consent gate, exercised on records that must be refused.

    It is here rather than in a test file because the gate is the only thing standing
    between a null-filled JSON and a PROVENANCE.json that reads like a signed grant, and
    because a previous version of it accepted every one of these."""
    good = dict(SYNTHETIC_CONSENT)
    cases = [
        ('all null', {k: None for k in CONSENT_REQUIRED_KEYS}),
        ('all False', {k: False for k in CONSENT_REQUIRED_KEYS}),
        ('all True', {k: True for k in CONSENT_REQUIRED_KEYS}),
        ('all zero', {k: 0 for k in CONSENT_REQUIRED_KEYS}),
        ('all blank', {k: '' for k in CONSENT_REQUIRED_KEYS}),
        ('licence null', dict(good, licence=None)),
        ('likeness flag as string', dict(good, recognisable_likeness_permitted='yes')),
        ('licence_evidence is just a name', dict(good, licence_evidence='CC-BY')),
        ('not a dict', 'I promise she said yes'),
    ]
    refused, accepted = [], []
    for name, rec in cases:
        try:
            _validate_consent(rec)
            accepted.append(name)
        except ScanIngestError:
            refused.append(name)
    _validate_consent(good)  # the good record must still pass
    if accepted:
        raise ScanIngestError('the consent gate ACCEPTED records it must refuse: %s' % ', '.join(accepted))
    return {'refused': refused, 'accepted': accepted, 'good_record_accepted': True, 'n_cases': len(cases)}


def self_test(work_dir=None, character='female', verbose=True, subdiv_level=1):
    """End-to-end synthetic run. Plumbing only — see synthetic_capture.__doc__.

    subdiv_level DEFAULTS TO 1 AND IS NOW A PARAMETER. It used to be hardcoded to 1 while
    DEFAULT_SUBDIV_LEVEL was 2, so the level the CLI actually runs at was never exercised —
    and the level-2 path was the one where the iteration guard bound and the low-pass never
    reached its cutoff. Level 1 stays the default here because it is ~10x cheaper; run
    `--selftest --subdiv-level 2` to exercise the shipped default end to end.
    """
    work_dir = work_dir or os.path.join(os.path.expanduser('~'), '.cache', 'zyg_scan_ingest_selftest')
    photos = os.path.join(work_dir, 'photos')
    out = os.path.join(work_dir, 'out')
    consent_check = _consent_gate_check()
    cap = synthetic_capture(photos, character=character, verbose=verbose)
    rep = ingest(
        photos,
        character,
        out,
        scale={
            'kind': 'stature_m',
            'value': cap['stature_m'],
            'source': 'SYNTHETIC: the exact stature of the source mesh. On a '
            'real capture this is a tape measure and a time of day.',
        },
        consent=SYNTHETIC_CONSENT,
        subdiv_level=int(subdiv_level),
        verbose=verbose,
    )
    rep['consent_gate_check'] = consent_check
    rep['subdiv_level_run'] = int(subdiv_level)
    rep['default_subdiv_level'] = DEFAULT_SUBDIV_LEVEL
    rep['synthetic'] = True
    rep['synthetic_caveat'] = (
        'Photogrammetry of our own renders can only recover our own '
        'mesh. A pass here means the code runs. It says nothing '
        'about what a real scan would produce.'
    )
    _atomic_json(os.path.join(out, 'selftest_report.json'), rep)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--photos')
    ap.add_argument('--character', default='female')
    ap.add_argument('--out')
    ap.add_argument('--scale-kind', choices=VALID_SCALE_KINDS)
    ap.add_argument('--scale-value', type=float)
    ap.add_argument('--scale-source', default='')
    ap.add_argument('--consent', help='path to a JSON consent record; see docs/photogrammetry_capture.md §5')
    ap.add_argument('--stages', default=','.join(STAGES))
    ap.add_argument(
        '--subdiv-level',
        type=int,
        default=None,
        help='default %d for an ingest; the self-test defaults to 1 because it '
        'is ~10x cheaper, and takes this flag to exercise the shipped '
        'default end to end' % DEFAULT_SUBDIV_LEVEL,
    )
    ap.add_argument('--cutoff-frac', type=float, default=RESIDUAL_CUTOFF_FRAC)
    ap.add_argument('--dense-method', default='auto', choices=('auto', 'sgbm', 'sparse', 'patchmatch'))
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        # the self-test's own default is 1 (cheap); --subdiv-level 2 runs the shipped default
        r = self_test(
            work_dir=a.out,
            character=a.character,
            verbose=not a.quiet,
            subdiv_level=1 if a.subdiv_level is None else a.subdiv_level,
        )
        print(json.dumps({k: v for k, v in r.items() if k != 'stages'}, indent=1))
        rs = r['stages'].get('residual', {})
        print(
            'residual rms %.4f mm, coverage %.3f'
            % (
                rs.get('residual_mm', {}).get('rms', float('nan')),
                rs.get('shrinkwrap', {}).get('coverage', float('nan')),
            )
        )
        return 0
    if not (a.photos and a.out):
        ap.error('--photos and --out are required (or use --selftest)')
    consent = None
    if a.consent:
        with open(a.consent) as f:
            consent = json.load(f)
    scale = None
    if a.scale_kind is not None:
        scale = {'kind': a.scale_kind, 'value': a.scale_value, 'source': a.scale_source}
    ingest(
        a.photos,
        a.character,
        a.out,
        scale=scale,
        consent=consent,
        stages=tuple(s for s in a.stages.split(',') if s),
        subdiv_level=(DEFAULT_SUBDIV_LEVEL if a.subdiv_level is None else a.subdiv_level),
        cutoff_frac=a.cutoff_frac,
        dense_method=a.dense_method,
        verbose=not a.quiet,
    )
    return 0
