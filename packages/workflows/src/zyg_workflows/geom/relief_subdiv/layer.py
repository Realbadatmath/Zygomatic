# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The layer, at subdivision level: apply_relief_at and the mirror audit.

Moved verbatim out of the old single-file relief_subdiv.py (lines 1154-1338).
"""

import time

import numpy as np

from zyg_workflows.geom.relief_subdiv.subdivision import (
    fast_mirror_map,
    mirror_map_override,
    subdiv_mirror_map,
    subdivide,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)
# ---------------------------------------------------------------------------------
# the layer, at subdivision level
# ---------------------------------------------------------------------------------


def apply_relief_at(
    v_cage,
    faces_cage,
    level,
    phenotype,
    bones,
    weights,
    bone_names,
    scale=1.0,
    include=None,
    mate_cage=None,
    mirror='combinatorial',
    verbose=True,
):
    """Subdivide the cage, then run relief.apply_relief ON THE SUBDIVIDED MESH.

    Returns (v_base, v_relief, faces_sub, report). `v_base` is the subdivided cage with no
    relief; `v_relief` is the same mesh with the layer applied AT THAT RESOLUTION. Both are
    returned because a before/after table needs both columns measured on the same surface.

    THIS IS THE POINT OF THE MODULE, so it is worth being explicit about what is NOT
    happening: the cage-level displacement field is not computed and interpolated. Every
    anchor is snapped to a SUBDIVIDED vertex by relief._snap's aspect ray, and every
    falloff weight is a graph geodesic over the SUBDIVIDED edge set. Interpolating a
    cage-level field onto more vertices would reproduce the cage-level result at a higher
    vertex count and would prove nothing.

    The rig is passed in, not rebuilt: bone positions are in the cage's frame and
    subdivision does not move that frame. `weights` is verified HERE, at cage level, where
    the (13718, 9) skinning arrays index the mesh they were authored for, and the record is
    carried into the report — see the module docstring.
    """
    from zyg_workflows.geom import relief as RL

    v_cage = np.asarray(v_cage, np.float64)
    S_cage = float(v_cage[:, 2].max() - v_cage[:, 2].min())

    used_bones = [
        'clavicle.L',
        'clavicle.R',
        'lowerarm01.L',
        'lowerarm02.L',
        'metacarpal1.L',
        'metacarpal4.L',
        'upperarm02.L',
        'foot.L',
        'lowerleg01.L',
        'pelvis.L',
        'spine01',
        'head',
    ]
    frame_cage = RL.verify_bone_frame(v_cage, bones, weights, bone_names, S_cage, used_bones)

    t0 = time.time()
    v_base, faces_sub, prov = subdivide(v_cage, faces_cage, level)
    t_sub = time.time() - t0
    S = float(v_base[:, 2].max() - v_base[:, 2].min())
    if verbose:
        _zyg_log.info(
            '    subdivide L%d  %d verts  %d quads  S=%.6f m (%+.2f mm)  %.1fs'
            % (level, len(v_base), len(faces_sub), S, 1e3 * (S - S_cage), t_sub)
        )

    # THE MIRROR MAP THE LAYER MIRRORS THROUGH. Default 'combinatorial', which is exact.
    # MEASURED on originals/male at level 2: the geometric mutual-nearest-neighbour search
    # — which is what relief.mirror_map does, and which is safe at cage resolution — pairs
    # 219,352 of 219,368 vertices and puts 40 of them with the WRONG partner, because the
    # male cage's own mirror residual (0.0599 mm) has stopped being small against the
    # subdivided vertex spacing. On originals/female (residual 0.0006 mm) it pairs all
    # 219,368 and disagrees on none. So the failure is not hypothetical, it is body
    # dependent, and it appears at the level the stills render from.
    t0 = time.time()
    geo, gdist = fast_mirror_map(v_base, RL.MIRROR_TOL_FRAC * S)
    if mirror == 'combinatorial':
        if mate_cage is None:
            mate_cage, _ = RL.mirror_map(v_cage, RL.MIRROR_TOL_FRAC * S_cage)
        mate = subdiv_mirror_map(mate_cage, faces_cage, level)
        mm = np.where(mate >= 0, mate, np.arange(len(mate)))
        mdist = np.where(mate >= 0, np.linalg.norm(v_base - v_base[mm] * np.array([-1.0, 1.0, 1.0]), axis=1), np.inf)
    elif mirror == 'geometric':
        mate, mdist = geo, gdist
    else:
        raise ValueError('mirror must be "combinatorial" or "geometric", got %r' % mirror)
    both = (geo >= 0) & (mate >= 0)
    t_mirror = time.time() - t0
    if verbose:
        _zyg_log.info(
            '    mirror map L%d  %.1fs  using %s: paired %d/%d  (geometric pairs %d and '
            'disagrees on %d)'
            % (
                level,
                t_mirror,
                mirror,
                int((mate >= 0).sum()),
                len(v_base),
                int((geo >= 0).sum()),
                int((geo[both] != mate[both]).sum()),
            )
        )

    t0 = time.time()
    with mirror_map_override(mate, mdist, len(v_base)):
        v_relief = RL.apply_relief(
            v_base,
            faces_sub,
            {RL.ANATOMY_KEY: float(scale)},
            phenotype=phenotype,
            bones=bones,
            weights=None,  # cage weights do not index this
            bone_names=bone_names,
            stature_m=S,
            include=include,
        )
        rep = dict(RL.apply_relief.last_report or {})
    t_field = time.time() - t0
    if verbose:
        _zyg_log.info(
            '    relief field L%d  %.0fs  displaced %d verts  max %.2f mm  field mirror '
            'residual %.2e mm'
            % (
                level,
                t_field,
                rep.get('displaced_vertices', -1),
                rep.get('max_displacement_mm', float('nan')),
                (rep.get('mirror') or {}).get('field_residual_after_symmetrise_mm', float('nan')),
            )
        )
    rep['subdivision'] = prov
    rep['bone_frame_cage'] = frame_cage
    rep['bone_frame_cage_failures'] = {k: r for k, r in frame_cage.items() if not r.get('ok')}
    rep['seconds'] = {'subdivide': t_sub, 'mirror_map': t_mirror, 'field': t_field}
    rep['mirror_map_used'] = {
        'kind': mirror,
        'paired': int((mate >= 0).sum()),
        'of': int(len(v_base)),
        'geometric_paired': int((geo >= 0).sum()),
        'geometric_disagreements': int((geo[both] != mate[both]).sum()),
    }
    return v_base, np.asarray(v_relief, np.float64), faces_sub, rep


def mirror_audit(v_sub, faces_sub, mate_cage, faces_cage, level, stature_m=None):
    """Geometric mirror map against the combinatorial one, at this level.

    A disagreement is a FINDING about the pairing at this resolution, not a reason to pick
    the answer that flatters the layer. Both maps are reported with the count of vertices
    they disagree on and the mesh's own mirror residual under each.
    """
    from zyg_workflows.geom import relief as RL

    v = np.asarray(v_sub, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    geo, _ = fast_mirror_map(v, RL.MIRROR_TOL_FRAC * S)
    comb = subdiv_mirror_map(mate_cage, faces_cage, level)

    def _res(mate):
        hv = np.nonzero(mate >= 0)[0]
        if not len(hv):
            return None, 0
        M = v[mate[hv]].copy()
        M[:, 0] *= -1.0
        return float(1e3 * np.abs(v[hv] - M).max()), int(len(hv))

    rg, ng = _res(geo)
    rc, nc = _res(comb)
    both = (geo >= 0) & (comb >= 0)
    dis = int((geo[both] != comb[both]).sum())
    return {
        'level': int(level),
        'geometric': {'paired': ng, 'mesh_mirror_residual_mm': rg},
        'combinatorial': {'paired': nc, 'mesh_mirror_residual_mm': rc},
        'disagreements_where_both_paired': dis,
        'agree': bool(dis == 0),
        'note': (
            'the geometric map is what relief.mirror_map computes inside the '
            'layer; the combinatorial one is derived through the subdivision and '
            'is exact. Disagreement means the mutual-nearest-neighbour pairing is '
            'no longer safe at this vertex spacing.'
        ),
    }
