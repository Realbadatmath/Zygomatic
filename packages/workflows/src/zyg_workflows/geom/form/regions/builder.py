# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""regions — build / load / mirror-check / resolve and the CLI.

Moved verbatim out of regions.py; see the package __init__ for the full rationale.
"""

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom import mesh_skeletons as MS
import hashlib
import json
import numpy as np
import os
import sys
import tempfile
import time
from zyg_workflows.geom.form.regions.context import (
    CAGE_VERTS,
    FEATURE_MIN_CONTRAST,
    FEATURE_MIN_FRAC,
    FEATURE_PROBE_RADIUS,
    REGIONS_PATH,
    SCHEMA_VERSION,
    _RESOLVERS,
    _ctx,
    _joint_line,
    _left,
    _limb_frame,
    _relief,
    _sector,
    _support,
)
from zyg_workflows.geom.form.regions.spec import REGION_SPEC

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ---------------------------------------------------------------------------------
# build / persist / load
# ---------------------------------------------------------------------------------
_ARM_LABELS = ('measure-lowerarm-length-incr', 'measure-upperarm-length-incr', 'measure-wrist-circ-incr')


def _sector_ring(label):
    """A '-circ-incr' target is a GIRTH RING and its support IS the ring; a '-length-incr'
    or '-height-incr' target is a SEGMENT and its support's BOUNDARY is the joint line."""
    if label.endswith('-circ-incr'):
        return _left(_support(label))
    if label.endswith(('-length-incr', '-height-incr')):
        return _joint_line(label)
    raise ValueError(
        '%r is neither a girth ring nor a segment-length target, so this '
        'module cannot say what its support means' % label
    )


def _sector_axis_rings(args):
    """The ring itself, plus the limb frame — built from a PROXIMAL and a DISTAL ring of
    the same limb rather than from whatever the sector happens to sit on.

    MEASURED TRAP: taking the ankle ring's distal reference from the FOOT support gave an
    'axis' of (0.07, -0.90, -0.44) — pointing forward along the foot, not down the shank —
    so 'lateral' named the top of the foot and the two malleolar sectors were both wrong.
    """
    ring = _sector_ring(args['ring_label'])
    if args['ring_label'] in _ARM_LABELS:
        prox = _joint_line('measure-lowerarm-length-incr')
        dist = _left(_support('measure-wrist-circ-incr'))
    else:
        prox = _joint_line('measure-lowerleg-height-incr')
        dist = _left(_support('measure-ankle-circ-incr'))
    return ring, _limb_frame(prox, dist)


def _resolve_left(spec):
    how, args = spec['how'], dict(spec.get('args', {}))
    if how == 'ring_sector':
        ring, fr = _sector_axis_rings(args)
        o, a, post, lat = fr
        d = {'posterior': post, 'anterior': -post, 'lateral': lat, 'medial': -lat}[args['direction']]
        g = _sector(ring, fr, d, args['half_deg'], args['band_frac'], args['reach_frac'], args.get('offset_frac', 0.0))
        c = _ctx()
        ev = {
            'ring': args['ring_label'],
            'ring_n': int(len(ring)),
            'ring_frac_stature': round(float((c['v'][ring, 2].mean() - c['zmin']) / c['S']), 4),
            'limb_axis': [round(float(x), 4) for x in a],
            'direction': args['direction'],
            'half_angle_deg': args['half_deg'],
            'band_frac_stature': args['band_frac'],
            'reach_frac_stature': args['reach_frac'],
            'offset_frac_stature': args.get('offset_frac', 0.0),
        }
        return (g if len(g) else None), ev
    return _RESOLVERS[how](**args)


def build_regions(path=None, verbose=True):
    """Resolve every region on the NEUTRAL cage, mirror it, measure it, and persist.

    This is the authoring step and it is deliberately slow (the feature searches probe a
    few thousand geodesic balls). It runs once; everything downstream reads regions.json.
    """
    c = _ctx()
    path = REGIONS_PATH if path is None else path
    out = {}
    for spec in REGION_SPEC:
        t0 = time.time()
        try:
            gl, ev = _resolve_left(spec)
        except Exception as e:  # noqa: BLE001
            gl, ev = None, {'resolver_error': '%s: %s' % (type(e).__name__, e)}
        rec = {
            'name': spec['name'],
            'anchor': spec['anchor'],
            'anchor_kind': spec['anchor_kind'],
            'note': spec['note'],
            'resolver': spec['how'],
            'resolver_args': _jsonable(spec.get('args', {})),
            'evidence': _jsonable(ev),
            'seconds': round(time.time() - t0, 2),
        }
        if gl is None or not len(gl):
            rec.update(
                {
                    'status': 'unresolved',
                    'claim': None,
                    'confidence': 'unresolved',
                    'vertex_idx_l': [],
                    'vertex_idx_r': [],
                    'n': 0,
                }
            )
            if spec['confidence'] != 'unresolved':
                rec['note'] = ('RESOLVER RETURNED NOTHING although the table expected %s. ' % spec['confidence']) + rec[
                    'note'
                ]
        else:
            gl = np.unique(np.asarray(gl, np.int64))
            gr = np.unique(c['mirror'][gl])
            if len(gr) != len(gl):
                raise RuntimeError(
                    'region %r: mirroring %d left vertices produced %d right ones, so the '
                    'cage pairing is not injective over this patch and the two sides could '
                    'not be compared' % (spec['name'], len(gl), len(gr))
                )
            rel_l = _safe_relief(gl)
            rel_r = _safe_relief(gr)
            rec.update(
                {
                    'status': 'resolved',
                    'claim': spec['claim'],
                    'confidence': spec['confidence'],
                    'vertex_idx_l': [int(i) for i in gl],
                    'vertex_idx_r': [int(i) for i in gr],
                    'n': int(len(gl)),
                    'centroid_frac_stature_l': round(float((c['v'][gl, 2].mean() - c['zmin']) / c['S']), 4),
                    'neutral_relief_l': rel_l,
                    'neutral_relief_r': rel_r,
                }
            )
        out[spec['name']] = rec
        if verbose:
            _zyg_log.info('  %-24s %-11s n=%4d  %s' % (spec['name'], rec['status'], rec['n'], _one_line(rec)))
    doc = {
        'schema': SCHEMA_VERSION,
        'authored': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'authored_on': 'anny neutral, geom.anthro.landmarks.REF_MALE recipe',
        'cage_vertices': int(len(c['v'])),
        'cage_faces': int(np.asarray(c['faces']).shape[0]),
        'neutral_stature_m': round(c['S'], 6),
        'delivered_diagonal': CV.DELIVERED_DIAGONAL,
        'feature_thresholds': {
            'min_frac_stature': FEATURE_MIN_FRAC,
            'min_contrast': FEATURE_MIN_CONTRAST,
            'probe_radius_frac': FEATURE_PROBE_RADIUS,
            'provenance': 'p99 of curvature.relief_null on this cage',
        },
        'regions': out,
    }
    doc['content_sha256'] = _content_sha(doc)
    _atomic_json(path, doc)
    return doc


def _safe_relief(g):
    try:
        r = _relief(g)
    except ValueError as e:
        return {'error': str(e)}
    return {
        k: (round(r[k], 5) if isinstance(r[k], float) else r[k])
        for k in (
            'relief_mm',
            'relief_frac_stature',
            'collar_fit_rms_mm',
            'contrast',
            'verdict',
            'n_collar',
            'collar_normal_agreement',
        )
    }


def _one_line(rec):
    if rec['status'] != 'resolved':
        ev = rec.get('evidence', {})
        return ev.get('why', ev.get('resolver_error', ''))[:110]
    r = rec.get('neutral_relief_l', {})
    if 'error' in r:
        return 'relief REFUSED: ' + r['error'][:80]
    return 'fz %.3f  relief %+6.2f mm  contrast %+6.2f  rms %.2f  %s  [%s]' % (
        rec['centroid_frac_stature_l'],
        r['relief_mm'],
        r['contrast'],
        r['collar_fit_rms_mm'],
        r['verdict'],
        rec['claim'],
    )


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(x) for k, x in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


def _content_sha(doc):
    """Hash of the vertex lists and the anchors only. Deliberately excludes the timestamp
    and the timing, so re-authoring an unchanged cage produces the same hash and a real
    change is visible."""
    payload = [
        (name, r['status'], r.get('anchor'), r['vertex_idx_l'], r['vertex_idx_r'])
        for name, r in sorted(doc['regions'].items())
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _atomic_json(path, doc):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    fd, tmp = tempfile.mkstemp(dir=d or '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(doc, f, indent=1, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def load_regions(n_vertices=None, path=None):
    """Read the authored groups. REFUSES a cage with a different vertex count.

    Every index in regions.json is a vertex number on the 13,718-vertex anny cage. On any
    other mesh those integers still index something, which is precisely the danger: a form
    gate would run, produce numbers, and be measuring an arbitrary patch. So the count is
    checked before anything is returned, and the content hash is re-derived so a file
    edited by hand cannot pass itself off as the authored one.
    """
    path = REGIONS_PATH if path is None else path
    if not os.path.exists(path):
        raise FileNotFoundError(
            '%s has not been authored yet — run `python -m zyg_workflows.geom.form.regions build`' % path
        )
    with open(path) as f:
        doc = json.load(f)
    if doc.get('schema') != SCHEMA_VERSION:
        raise ValueError('regions.json is schema %r, this module speaks %r' % (doc.get('schema'), SCHEMA_VERSION))
    if n_vertices is not None and int(n_vertices) != int(doc['cage_vertices']):
        raise ValueError(
            'regions.json was authored against a %d-vertex cage and you are asking for it '
            'on a %d-vertex mesh. Every vertex index in it is invalid for that mesh.'
            % (doc['cage_vertices'], int(n_vertices))
        )
    got = _content_sha(doc)
    if got != doc.get('content_sha256'):
        raise ValueError(
            'regions.json content hash mismatch: file says %s, groups hash to '
            '%s. The file has been edited since it was authored.' % (doc.get('content_sha256'), got)
        )
    return doc


def mirror_check(doc=None):
    """Confirm every right group IS the mirror image of its left one, exactly."""
    doc = load_regions() if doc is None else doc
    mir = _ctx()['mirror']
    rows = []
    for name, r in sorted(doc['regions'].items()):
        if r['status'] != 'resolved':
            continue
        gl = np.array(r['vertex_idx_l'], np.int64)
        gr = np.array(r['vertex_idx_r'], np.int64)
        exact = bool(len(gl) == len(gr) and np.array_equal(np.sort(mir[gl]), np.sort(gr)))
        rows.append({'name': name, 'n_l': len(gl), 'n_r': len(gr), 'exact_mirror': exact})
    return rows


def resolve_regions(v, faces, doc=None, names=None, stature_m=None):
    """Measure the authored groups on ONE body.

    The groups themselves do not move — they are the same skin — so what this returns is
    per-body geometry: where the patch ended up as a fraction of stature, and what relief it
    reads there. That is the input a form predicate consumes.
    """
    v = np.asarray(v, np.float64)
    doc = load_regions(len(v)) if doc is None else doc
    if len(v) != int(doc['cage_vertices']):
        raise ValueError('regions.json is for a %d-vertex cage, got %d' % (doc['cage_vertices'], len(v)))
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    zmin = float(v[:, 2].min())
    areas = CV.mixed_voronoi_area(v, faces)
    nrm = CV.vertex_normals(v, faces)
    out = {}
    for name, r in doc['regions'].items():
        for side in ('l', 'r'):
            key = name + '_' + side
            if names is not None and key not in names:
                continue
            rec = {
                'status': r['status'],
                'claim': r['claim'],
                'confidence': r['confidence'],
                'anchor': r['anchor'],
                'anchor_kind': r['anchor_kind'],
                'n': r['n'],
                'note': r['note'],
                'evidence': r['evidence'],
                'centroid_frac_stature': None,
                'relief': None,
            }
            g = np.array(r['vertex_idx_' + side], np.int64)
            if r['status'] == 'resolved' and len(g):
                rec['centroid_frac_stature'] = float((v[g, 2].mean() - zmin) / S)
                rec['centroid_m'] = [float(x) for x in v[g].mean(0)]
                try:
                    rr = CV.region_relief(v, faces, g, stature_m=S, areas=areas, normals=nrm)
                    rec['relief'] = rr
                except ValueError as e:
                    rec['relief'] = {'error': str(e)}
            out[key] = rec
    return out


# ---------------------------------------------------------------------------------
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'report'

    if cmd == 'build' or not os.path.exists(REGIONS_PATH):
        print('=== authoring regions on the anny neutral (stature %.4f m) ===' % _ctx()['S'])
        doc = build_regions()
        print('wrote %s  (sha %s)' % (REGIONS_PATH, doc['content_sha256'][:16]))
        if cmd == 'build':
            return 0

    doc = load_regions(CAGE_VERTS)
    print(
        '\n=== regions.json: %d regions, cage %d verts, authored %s, sha %s ==='
        % (len(doc['regions']), doc['cage_vertices'], doc['authored'], doc['content_sha256'][:16])
    )
    res = [n for n, r in doc['regions'].items() if r['status'] == 'resolved']
    unres = [n for n, r in doc['regions'].items() if r['status'] != 'resolved']
    print('RESOLVED   (%d x2 sides): %s' % (len(res), ', '.join(sorted(res))))
    print('UNRESOLVED (%d x2 sides): %s' % (len(unres), ', '.join(sorted(unres))))

    print('\n--- mirror consistency (right group must BE the mirror of the left) ---')
    bad = 0
    for row in mirror_check(doc):
        if not row['exact_mirror']:
            bad += 1
            print('   %-24s n_l=%d n_r=%d  NOT AN EXACT MIRROR' % (row['name'], row['n_l'], row['n_r']))
    print('   %d of %d resolved regions are exact mirrors' % (len(mirror_check(doc)) - bad, len(mirror_check(doc))))

    print('\n--- why each unresolved region is unresolved (measured) ---')
    for name in sorted(unres):
        ev = doc['regions'][name]['evidence']
        print('   %-24s %s' % (name, ev.get('why', ev.get('resolver_error', '?'))))
        if 'best_relief_mm' in ev:
            print(
                '   %-24s   strongest in window: %+.2f mm (contrast %+.2f) at v%d, '
                'fz %.3f, xyz %s; window held %d verts'
                % (
                    '',
                    ev['best_relief_mm'],
                    ev['best_contrast'],
                    ev['best_vertex'],
                    ev['best_frac_stature_height'],
                    ev['best_xyz_m'],
                    ev['n_window'],
                )
            )

    reg = MS._registry()
    for sec in ('originals', 'derived'):
        for name in reg.get(sec, {}):
            p = reg[sec][name]['params']
            v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
            v = MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {})
            v = np.asarray(v, np.float64)
            S = float(v[:, 2].max() - v[:, 2].min())
            print('\n=== %s (stature %.4f m) ===' % (name, S))
            print(
                '   %-24s %4s %8s %10s %9s %9s %-12s %s'
                % ('region', 'n', 'cen_fz', 'relief_mm', 'frac', 'contrast', 'verdict', 'claim')
            )
            out = resolve_regions(v, faces, doc, stature_m=S)
            for key in sorted(out):
                r = out[key]
                if r['status'] != 'resolved':
                    print('   %-24s %4s %8s %10s %9s %9s %-12s %s' % (key, '-', '-', '-', '-', '-', 'UNRESOLVED', '-'))
                    continue
                rl = r['relief']
                if 'error' in rl:
                    print(
                        '   %-24s %4d %8.3f  relief REFUSED: %s'
                        % (key, r['n'], r['centroid_frac_stature'], rl['error'][:60])
                    )
                    continue
                print(
                    '   %-24s %4d %8.3f %+10.2f %+9.2e %+9.2f %-12s %s'
                    % (
                        key,
                        r['n'],
                        r['centroid_frac_stature'],
                        rl['relief_mm'],
                        rl['relief_frac_stature'],
                        rl['contrast'],
                        rl['verdict'],
                        r['claim'],
                    )
                )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
