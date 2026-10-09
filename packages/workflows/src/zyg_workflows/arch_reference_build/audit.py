# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build.audit — curves and materials as NUMBERS, because "it
looks smooth" is not a check (lines 1705-1871 of the original single file,
moved verbatim).
"""

import logging as _zyg_logging
import math

import bmesh
import bpy

from .api import asset_meshes

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_reference_build')

# ── the audit: curves and materials, as NUMBERS ──────────────────────────────
# "make sure drawing curves and material quality is done perfectly" cannot be
# answered by looking; a facet is a facet at 1200 px and a fair curve at 600.
# So the surface is measured: what carries a material, what is smooth, and how
# hard each mesh turns between one face and the next.
SHARP_RAD = 0.35  # 20 degrees: past this an edge reads as a crease
CREASE_RAD = 1.05  # 60 degrees: past THIS it is a deliberate corner, not
# unfairness. 2026-09-24: the first version counted every
# edge over 20 degrees, so one mesh holding 27 rectangular
# deck beams — whose edges are 90 degrees by design — was
# reported as an unfair surface, and the assistant was sent
# to 'fix' geometry that was right. Unfairness lives in the
# middle band: a fair loft has almost nothing there.
FLAT_FACES = 200  # a mesh this big, flat-shaded, is a faceted curve
DEFAULT_GREY = 0.8  # Blender's untouched Principled base colour


def _mat_row(mt):
    """What one material actually is: textured, coloured, or still default."""
    row = {
        'name': mt.name,
        'nodes': bool(mt.use_nodes),
        'image': False,
        'base': None,
        'rough': None,
        'metal': None,
        'alpha': None,
        'default': False,
    }
    if not mt.use_nodes or mt.node_tree is None:
        row['base'] = [round(c, 3) for c in (mt.diffuse_color or [])[:3]]
        return row
    for nd in mt.node_tree.nodes:
        if nd.type in ('TEX_IMAGE', 'TEX_ENVIRONMENT') and getattr(nd, 'image', None):
            row['image'] = True
        if nd.type == 'BSDF_PRINCIPLED':

            def _in(k, d=None, _nd=nd):
                try:
                    s = _nd.inputs[k]
                    return None if s.is_linked else s.default_value
                except (KeyError, TypeError):
                    return d

            b = _in('Base Color')
            row['base'] = [round(c, 3) for c in b[:3]] if b is not None else 'linked'
            r = _in('Roughness')
            row['rough'] = round(r, 3) if isinstance(r, float) else r
            m = _in('Metallic')
            row['metal'] = round(m, 3) if isinstance(m, float) else m
            a = _in('Alpha')
            row['alpha'] = round(a, 3) if isinstance(a, float) else a
    if (
        not row['image']
        and isinstance(row['base'], list)
        and all(abs(c - DEFAULT_GREY) < 0.02 for c in row['base'])
        and row['rough'] in (0.5, 0.45, 0.55)
    ):
        row['default'] = True
    return row


def _audit():
    """{'meshes': [...], 'materials': [...], 'findings': [str]} — the surface
    of the asset, measured. Every number here is checkable from the .blend."""
    dg = bpy.context.evaluated_depsgraph_get()
    meshes, seen = [], {}
    for ob in asset_meshes():
        try:
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('object mesh skipped in the geometry report, not evaluable: %s', _exc)
            continue
        bm = bmesh.new()
        bm.from_mesh(me)
        nf, nv = len(bm.faces), len(bm.verts)
        smooth = sum(1 for f in bm.faces if f.smooth)
        angs = []
        for e in bm.edges:
            if len(e.link_faces) == 2:
                try:
                    angs.append(e.calc_face_angle(0.0))
                except (ValueError, RuntimeError) as _exc:
                    _zyg_log.debug('edge angle skipped, degenerate edge: %s', _exc)
        loose = sum(1 for e in bm.edges if len(e.link_faces) == 0)
        open_e = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        bm.free()
        ev.to_mesh_clear()
        mats = [m.name for m in ob.data.materials if m]
        for m in ob.data.materials:
            if m is not None and m.name not in seen:
                seen[m.name] = _mat_row(m)
        unfair = sum(1 for a in angs if SHARP_RAD < a < CREASE_RAD)
        corners = sum(1 for a in angs if a >= CREASE_RAD)
        meshes.append(
            {
                'name': ob.name,
                'verts': nv,
                'faces': nf,
                'smooth_pct': round(100.0 * smooth / max(1, nf)),
                'max_bend_deg': round(math.degrees(max(angs)) if angs else 0.0),
                'unfair_pct': round(100.0 * unfair / max(1, len(angs))),
                'corner_pct': round(100.0 * corners / max(1, len(angs))),
                'open_edges': open_e,
                'loose_edges': loose,
                'mats': mats,
                'mods': [m.type for m in ob.modifiers],
            }
        )
    meshes.sort(key=lambda r: -r['faces'])
    find = []
    no_mat = [r['name'] for r in meshes if not r['mats']]
    if no_mat:
        find.append(
            f'{len(no_mat)} mesh(es) carry NO MATERIAL at all — they render as Blender grey: '
            + ', '.join(no_mat[:10])
            + ('…' if len(no_mat) > 10 else '')
        )
    dflt = [k for k, v in seen.items() if v.get('default')]
    if dflt:
        find.append(
            f'{len(dflt)} material(s) are still the UNTOUCHED default (grey 0.8, roughness 0.5, no '
            'texture): ' + ', '.join(dflt[:10]) + ('…' if len(dflt) > 10 else '')
        )
    tex = [k for k, v in seen.items() if v.get('image')]
    find.append(
        f'{len(seen)} material(s) in all, {len(tex)} with an image texture'
        + (': ' + ', '.join(tex[:6]) if tex else ' — every surface is a flat colour')
    )
    faceted = [r['name'] for r in meshes if r['faces'] >= FLAT_FACES and r['smooth_pct'] < 5 and r['max_bend_deg'] < 45]
    if faceted:
        find.append(
            f'{len(faceted)} mesh(es) are big, FLAT-SHADED and turn by less than 45 degrees anywhere '
            '— that is a curved surface drawn as facets; shade it smooth or raise its segments: '
            + ', '.join(faceted[:10])
            + ('…' if len(faceted) > 10 else '')
        )
    # ... and only on a mesh that is a SURFACE rather than a box. A bevelled
    # corner is two edges at about 45 degrees, which lands in the same band as
    # unfairness — so hard-surface geometry that has been properly bevelled
    # would be reported as unfair for doing the right thing. A loft has almost
    # no edges over 60 degrees (the pinas's hull: 3 %); a box full of corners
    # has plenty (its deck beams: 14 %). That is the discriminator.
    rough = [
        r['name']
        for r in meshes
        if r['faces'] >= FLAT_FACES and r['smooth_pct'] >= 50 and r['unfair_pct'] >= 12 and r['corner_pct'] < 5
    ]
    if rough:
        find.append(
            f'{len(rough)} smooth mesh(es) have more than 12 % of their edges bending between 20 and '
            '60 degrees — a fair surface has almost none there, so these sections are not fair, or '
            'too few (edges OVER 60 degrees are counted as deliberate corners and ignored): '
            + ', '.join(rough[:10])
            + ('…' if len(rough) > 10 else '')
        )
    holes = [r['name'] for r in meshes if r['open_edges'] > max(24, r['faces'] // 12)]
    if holes:
        find.append(
            f'{len(holes)} mesh(es) are full of OPEN edges (a hole, or a surface with no thickness): '
            + ', '.join(holes[:10])
            + ('…' if len(holes) > 10 else '')
        )
    return {'meshes': meshes[:60], 'materials': [dict(v) for v in seen.values()], 'findings': find}
