# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cage topology and the skinning-weight arm mask, resolved once per process.

Moved verbatim out of the old single-file measure.py (lines 250-516).
"""

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro.measure.constants import (
    ARM_BONE_KEEP_SUBSTRINGS,
    ARM_BONE_SUBSTRINGS,
    ARM_MASK_LABELS,
    ARM_SKIN_WEIGHT_THRESHOLD,
    CAGE_FACES,
    CAGE_VERTS,
    _zyg_log,
)


# ---------------------------------------------------------------------------------
# topology — fixed for the cage, so resolved once per process
# ---------------------------------------------------------------------------------
_TOPO = {}
_ARM_SKIN = {}


def arm_skin_weights():
    """Per-vertex summed skinning weight on the arm bones, with the mask's provenance.

    Returns {'weight': (V,) float64 or None, 'provenance': {...}}. The weight is None,
    with a reason, when the rig cannot be reached or does not match this cage — never
    silently zero, because a silently zero arm mask is an arm mask that is not running.

    The rig is a property of the model, not of a character's parameters, so this is
    resolved once per process.
    """
    if 'w' in _ARM_SKIN:
        return _ARM_SKIN['w']
    prov = {
        'method': 'skinning weights: sum of model.vertex_bone_weights over the bones '
        'whose lowercase name contains any of %s; a vertex at or above the '
        'threshold is arm' % (ARM_BONE_SUBSTRINGS,),
        'threshold': ARM_SKIN_WEIGHT_THRESHOLD,
        'bones_kept_on_purpose': list(ARM_BONE_KEEP_SUBSTRINGS),
        'kept_because': 'clavicle and shoulder01 carry genuine shoulder breadth',
        'same_rule_as': 'geom/fit_reference.py::_kept_mask',
    }
    out = {'weight': None, 'provenance': prov}
    try:
        model = MS._model()
        names = [str(n).lower() for n in MS._bone_names(model)]
        bad = np.array([any(k in nm for k in ARM_BONE_SUBSTRINGS) for nm in names])
        kept_shoulder = [nm for nm in names if any(k in nm for k in ARM_BONE_KEEP_SUBSTRINGS)]
        w = np.asarray(model.vertex_bone_weights.detach().cpu().numpy(), np.float64)
        i = np.asarray(model.vertex_bone_indices.detach().cpu().numpy(), np.int64)
    except Exception as e:  # noqa: BLE001
        prov['available'] = False
        prov['reason'] = 'the anny rig could not be read: %s' % e
        _ARM_SKIN['w'] = out
        return out
    if w.shape != i.shape or w.shape[0] != CAGE_VERTS:
        prov['available'] = False
        prov['reason'] = (
            'rig weights are %s / indices %s, which does not match the '
            '%d-vertex cage this module is written against' % (w.shape, i.shape, CAGE_VERTS)
        )
        _ARM_SKIN['w'] = out
        return out
    if not bad.any():
        prov['available'] = False
        prov['reason'] = 'no bone name matched %s, so the mask would pass every vertex through as trunk' % (
            ARM_BONE_SUBSTRINGS,
        )
        _ARM_SKIN['w'] = out
        return out
    aw = (w * bad[i]).sum(axis=1)
    prov.update(
        available=True,
        bones_total=len(names),
        bones_masked=int(bad.sum()),
        bones_masked_names=[names[k] for k in np.nonzero(bad)[0]],
        bones_kept_names=kept_shoulder,
        vertices_total=int(len(aw)),
        vertices_arm=int((aw >= ARM_SKIN_WEIGHT_THRESHOLD).sum()),
    )
    out['weight'] = aw
    _ARM_SKIN['w'] = out
    return out


def _split_arm_points(loop):
    """(keep_mask, n_dropped, max_arm_weight) for one contour under the skinning rule.

    keep_mask is None when the mask is unavailable — the caller must then say so rather
    than behave as if every point were trunk.
    """
    aw = loop.get('arm_w')
    if aw is None:
        return None, None, None
    aw = np.asarray(aw, np.float64)
    if not len(aw):
        return None, None, None
    keep = aw < ARM_SKIN_WEIGHT_THRESHOLD
    return keep, int((~keep).sum()), float(aw.max())


def _arm_mask_record(scope, keep, ndrop, wmax, met, met_af):
    """The provenance block every sliced measurement carries about the arm mask.

    It says what the mask is, whether it ran, whether it changed anything, and by how
    much. A mask that reports nothing is indistinguishable from a mask that is not
    running, which is the failure this block exists to make impossible.
    """
    prov = arm_skin_weights()['provenance']
    if keep is None:
        return {
            'applied': False,
            'available': False,
            'unavailable_because': prov.get(
                'reason', 'the per-contour-point arm weight was not available for this section'
            ),
            'method': prov['method'],
            'threshold': ARM_SKIN_WEIGHT_THRESHOLD,
        }
    d = {
        'applied': scope in ('torso', 'head'),
        'available': True,
        'method': prov['method'],
        'threshold': ARM_SKIN_WEIGHT_THRESHOLD,
        'bones_masked': prov.get('bones_masked'),
        'bones_kept_on_purpose': prov.get('bones_kept_names'),
        'contour_points_total': int(len(keep)),
        'contour_points_dropped': int(ndrop),
        'max_arm_weight_on_section': round(float(wmax), 4),
        'changed_the_value': bool(ndrop) and scope in ('torso', 'head'),
    }
    if scope == 'all':
        d['not_applied_because'] = (
            'this site is DEFINED to include the arms (the tape passes over both '
            'deltoids), so the mask is measured and reported but the primary value stays '
            'unmasked'
        )
    elif scope not in ('torso', 'head'):
        d['not_applied_because'] = (
            'scope %r is a LIMB section, which is arm on purpose; the limb guard in '
            '_girth_at owns this case, not the arm mask' % scope
        )
    if not ndrop:
        d['note'] = (
            'the selected section carried no arm surface at all, so the mask is a '
            'no-op here and the topological loop selection had already excluded '
            'the arms. max_arm_weight_on_section is how close it came.'
        )
    if not d['applied']:
        # Everything below describes what the mask DID to the value. It has to stay off a
        # site the mask was not applied to, or the block reads as if it had been.
        return d
    if met is not None and ndrop:
        d['x_extent_without_mask_mm'] = met['x_extent_m'] * 1000
        d['y_extent_without_mask_mm'] = met['y_extent_m'] * 1000
        d['hull_without_mask_mm'] = None if met['hull_m'] is None else met['hull_m'] * 1000
    if met_af is None and ndrop:
        d['note'] = 'fewer than 3 contour points survived the mask, so no arm-free section exists at this plane'
    return d


def _vendor_triangles(quads):
    """anny's OWN triangulation of the quad cage, validated against the quads passed in.

    This is not pedantry. The vendor does not use one fixed diagonal: measured on this
    cage, 7,024 quads are split across 0-2 and 6,686 across 1-3, and the quads are
    non-planar by 0.57 mm on average and up to 8.65 mm. Picking the other diagonal moves
    the actual surface a slice cuts through, so a home-rolled split would silently give a
    different girth from anny's own volume and from anything else built on the vendor
    triangles. Returns None if the model cannot be reached or the pairing does not check
    out, and the caller falls back with a note rather than pretending.
    """
    try:
        tri = np.asarray(MS._model().get_triangular_faces())
    except Exception:  # noqa: BLE001
        return None
    if tri.shape != (2 * len(quads), 3):
        return None
    t0, t1 = tri[0::2], tri[1::2]
    for i in range(len(quads)):
        qs = set(int(x) for x in quads[i])
        a, b = set(int(x) for x in t0[i]), set(int(x) for x in t1[i])
        if not (a <= qs and b <= qs and (a | b) == qs):
            return None
    return tri.astype(np.int64)


def _topology(faces):
    """Triangles, unique edges, per-triangle edge ids, shell labels and the arm mask.

    The cage ships as quads and is triangulated with the VENDOR's own diagonals (see
    _vendor_triangles for why the diagonal is load-bearing rather than cosmetic).
    """
    f = np.asarray(faces)
    if f.shape != (CAGE_FACES, 4):
        raise ValueError(
            'measure.py is written against the %d-quad anny cage; got faces '
            '%s. Every cached index would be wrong for that mesh.' % (CAGE_FACES, (f.shape,))
        )
    key = int(f.sum()) ^ (f.shape[0] << 8)
    if key in _TOPO:
        return _TOPO[key]

    tri = _vendor_triangles(f)
    tri_src = "anny's own model.get_triangular_faces(), validated quad by quad"
    if tri is None:
        tri = np.vstack([f[:, [0, 1, 2]], f[:, [0, 2, 3]]]).astype(np.int64)
        tri_src = (
            'FALLBACK: fixed 0-2 diagonal. The vendor triangulation was '
            'unavailable or did not match these quads, so the sliced surface is '
            "ours, not anny's, on every non-planar quad (up to 8.65 mm apart on "
            'this cage).'
        )
    e = np.sort(np.stack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], 1).reshape(-1, 2), axis=1)
    uniq, inv = np.unique(e, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    use = np.bincount(inv, minlength=len(uniq))
    if not (use == 2).all():
        raise ValueError(
            'cage is not edge-manifold: %d edges are used %s times. The '
            'loop tracer assumes every crossing point has exactly two '
            'neighbours and would produce silently open contours.'
            % (int((use != 2).sum()), sorted(set(use[use != 2].tolist())))
        )
    E = inv.reshape(-1, 3)

    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    pairs = np.argsort(inv, kind='stable').reshape(-1, 2) // 3
    adj = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(tri), len(tri)))
    n_shell, shell = connected_components(adj, directed=False)
    sizes = np.bincount(shell)
    body_shell = int(np.argmax(sizes))
    body_tris = shell == body_shell

    arm_v = np.zeros(CAGE_VERTS, bool)
    for lab in ARM_MASK_LABELS:
        try:
            arm_v[MS._morph_support(lab)[0]] = True
        except RuntimeError as _exc:
            _zyg_log.debug('arm mask label %s has no morph support: %s', lab, _exc)
    arm_tris = arm_v[tri].all(axis=1)

    skin = arm_skin_weights()
    aw = skin['weight']
    skin_v = None if aw is None else (aw >= ARM_SKIN_WEIGHT_THRESHOLD)
    skin_tris = None if skin_v is None else skin_v[tri].all(axis=1)

    out = {
        'tri': tri,
        'edges': uniq,
        'tri_edges': E,
        'triangulation': tri_src,
        'shell': shell,
        'n_shells': int(n_shell),
        'shell_sizes': sizes.tolist(),
        'body_tris': body_tris,
        'arm_vertices': arm_v,
        'arm_tris': arm_tris,
        'arm_skin_weight': aw,
        'arm_skin_vertices': skin_v,
        'arm_skin_tris': skin_tris,
        'arm_mask_provenance': skin['provenance'],
        'shell_note': (
            '%d closed shells: the body (%d triangles) plus %d inclusions '
            '(eyes / mouth parts, %s triangles). Volume and every slice use '
            'the body shell only — an eyeball inside the head would '
            'otherwise contribute its own contour loop.'
            % (
                n_shell,
                int(sizes[body_shell]),
                n_shell - 1,
                sorted(int(s) for i, s in enumerate(sizes) if i != body_shell),
            )
        ),
    }
    _TOPO[key] = out
    return out
