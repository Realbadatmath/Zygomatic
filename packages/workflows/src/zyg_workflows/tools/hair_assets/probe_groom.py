# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""probe_groom.py — what a Blender Studio character's hair actually IS.
blender -b <file.blend> --python probe_groom.py -- <out.json>

Particle counts in the FILE are the settings; the strands an edited groom
actually carries only exist once the depsgraph has evaluated it. This asks the
evaluated object, and it also finds the body mesh the head frame is measured
from, so the converter never has to guess either."""

import json

import bpy

HAIRISH = ('hair', 'beard', 'brow', 'lash', 'fur', 'stubble', 'moustache', 'sideburn')


def main():
    out = {'objects': [], 'curves': [], 'particles': []}
    dg = bpy.context.evaluated_depsgraph_get()
    for ob in bpy.context.scene.objects:
        if ob.type == 'MESH':
            ev = ob.evaluated_get(dg)
            try:
                nv = len(ev.data.vertices)
            except Exception:  # noqa: BLE001
                nv = 0
            out['objects'].append(
                {
                    'name': ob.name,
                    'verts': nv,
                    'hidden': ob.hide_render,
                    'hairish': any(k in ob.name.lower() for k in HAIRISH),
                }
            )
        if ob.type == 'CURVES':
            out['curves'].append(
                {
                    'name': ob.name,
                    'strands': len(ob.data.curves),
                    'points': len(ob.data.points),
                    'hidden': ob.hide_render,
                }
            )
        ev = ob.evaluated_get(dg)
        for ps in getattr(ev, 'particle_systems', []):
            if ps.settings.type != 'HAIR':
                continue
            out['particles'].append(
                {
                    'obj': ob.name,
                    'ps': ps.name,
                    'parents': len(ps.particles),
                    'keys': (len(ps.particles[0].hair_keys) if len(ps.particles) else 0),
                    'children': len(ps.child_particles),
                    'child_type': ps.settings.child_type,
                    'child_nbr': getattr(ps.settings, 'child_nbr', getattr(ps.settings, 'child_percent', 0)),
                    'rendered_children': getattr(ps.settings, 'rendered_child_count', 0),
                    'hidden': ob.hide_render,
                }
            )
    print('ZYGPROBE' + json.dumps(out))


main()
