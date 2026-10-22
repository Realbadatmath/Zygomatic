# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_2d_ifc — the IFC writer, run INSIDE Blender by arch_server_ext/file_2d.py.

    blender -b --python arch_server_ext/file_2d_ifc.py -- \
        --in doc.json --out out.ifc --schema IFC4 --name "House"

Why Blender: ifcopenshell only exists on this machine inside Blender's own
site-packages (it ships with the Bonsai extension, bl_ext.blender_org.bonsai),
and the geometry an IFC element needs is exactly the geometry arch_blender_build
already makes — boolean openings cut, hip roofs solved, assets imported. So this
script imports arch_blender_build BY PATH, calls build() the way
arch_assistant.start_blender's CLI does, and then walks the built objects.

The mapping is by the record's kind, because that is the only place the studio
says what a thing IS: a slab and a roof are both boxes and only the kind tells
them apart. Geometry is the mesh in LOCAL metres plus the object's world matrix
as the placement, so an IFC viewer puts the wall exactly where the studio does
(Blender's frame — X east, Y north, Z up — is already IFC's).

One JSON line on stdout, prefixed IFCOUT, is the contract.

Licences: ifcopenshell LGPL-3.0 (executed in Blender's process, not imported
into the server's), Blender GPL-2.0-or-later. Nothing is installed by this file.
"""

from __future__ import annotations

import json
import os
import sys
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# The record's kind is the whole ontology. Anything unrecognised becomes a
# proxy rather than a guess — a consultant would rather see an untyped solid in
# the right place than a wall that is really a bench.
KIND_CLASS = {
    'wall': 'IfcWall',
    'partition': 'IfcWall',
    'wall_arc': 'IfcWall',
    'wall_curved': 'IfcWall',
    'slab': 'IfcSlab',
    'floor': 'IfcSlab',
    'ceiling': 'IfcCovering',
    'ramp': 'IfcRamp',
    'column': 'IfcColumn',
    'beam': 'IfcBeam',
    'footing': 'IfcFooting',
    'pile': 'IfcPile',
    'door': 'IfcDoor',
    'window': 'IfcWindow',
    'railing': 'IfcRailing',
    'balustrade': 'IfcRailing',
    'stair': 'IfcStair',
    'staircase': 'IfcStair',
    'roof': 'IfcRoof',
    'curtain_wall': 'IfcCurtainWall',
    'plate': 'IfcPlate',
    'member': 'IfcMember',
    'duct': 'IfcDuctSegment',
    'pipe': 'IfcPipeSegment',
    'furniture': 'IfcFurnishingElement',
}
PREFIX_CLASS = (
    ('roof_', 'IfcRoof'),
    ('stair_', 'IfcStair'),
    ('wall_', 'IfcWall'),
    ('slab_', 'IfcSlab'),
    ('column_', 'IfcColumn'),
    ('beam_', 'IfcBeam'),
    ('door_', 'IfcDoor'),
    ('window_', 'IfcWindow'),
    ('railing_', 'IfcRailing'),
    ('furniture_', 'IfcFurnishingElement'),
)
DEFAULT_CLASS = 'IfcBuildingElementProxy'

# Notation, not matter: a guide line and a dimension are the drawing's, not the
# building's, and IFC has no room for them among the building elements.
SKIP_PREFIX = ('guide_', 'sculpt_', 'dim_', 'label_')


def ifc_class_for(kind: str) -> str:
    k = str(kind or '').strip().lower()
    if k in KIND_CLASS:
        return KIND_CLASS[k]
    for pre, cls in PREFIX_CLASS:
        if k.startswith(pre):
            return cls
    return DEFAULT_CLASS


# Every ifcopenshell.api usecase this script calls, imported BEFORE the build.
# arch_blender_build.build() starts with bpy.ops.wm.read_factory_settings(), which
# disables the Bonsai extension and takes its site-packages back off sys.path —
# after that `ifcopenshell.api.run` cannot import a usecase it has not already
# loaded ("No module named 'ifcopenshell.api.unit'"). Holding the functions is
# what makes the order build-then-write possible at all.
API_USECASES = (
    'project.create_file',
    'root.create_entity',
    'unit.add_si_unit',
    'unit.assign_unit',
    'context.add_context',
    'aggregate.assign_object',
    'spatial.assign_container',
    'geometry.add_mesh_representation',
    'geometry.assign_representation',
    'geometry.edit_object_placement',
)


def load_api() -> dict:
    import importlib
    import ifcopenshell  # noqa: F401 — the package must be live first

    api = {}
    for path in API_USECASES:
        mod, use = path.split('.')
        api[path] = getattr(importlib.import_module('ifcopenshell.api.%s.%s' % (mod, use)), use)
    return api


def load_builder(here: str):
    """arch_blender_build.py, imported by path under a private name so its
    `if __name__ == '__main__'` never fires."""
    import importlib.util

    path = os.path.join(here, 'arch_blender_build', '__main__.py')
    spec = importlib.util.spec_from_file_location('arch_blender_build_f2d', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['arch_blender_build_f2d'] = mod
    spec.loader.exec_module(mod)
    return mod


def run(args) -> dict:
    import bpy
    import numpy as np

    api = load_api()  # before the factory reset, see above
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(args.inp, 'r', encoding='utf-8') as fh:
        drawing = json.load(fh)
    if not isinstance(drawing, dict):
        raise ValueError('the drawing JSON must be an object')
    records = {}
    for i, rec in enumerate(drawing.get('objects') or []):
        if isinstance(rec, dict):
            records[str(rec.get('id') or 'o%d' % i)] = rec

    storey_h = 2.7
    defaults = drawing.get('defaults')
    if isinstance(defaults, dict):
        try:
            storey_h = float(defaults.get('wall_h') or storey_h) or 2.7
        except (TypeError, ValueError):
            storey_h = 2.7

    # (a) the project skeleton, BEFORE the build for the same reason the api
    # functions are: create_file parses the schema's express file out of the
    # extension's own directory, and the factory reset takes that path away.
    f = api['project.create_file'](version=args.schema)
    project = api['root.create_entity'](f, ifc_class='IfcProject', name=args.name or 'Drawing')
    metre = api['unit.add_si_unit'](f, unit_type='LENGTHUNIT')
    api['unit.assign_unit'](f, units=[metre])
    model = api['context.add_context'](f, context_type='Model')
    body = api['context.add_context'](
        f, context_type='Model', context_identifier='Body', target_view='MODEL_VIEW', parent=model
    )
    site = api['root.create_entity'](f, ifc_class='IfcSite', name='Site')
    building = api['root.create_entity'](f, ifc_class='IfcBuilding', name='Building')
    api['aggregate.assign_object'](f, products=[site], relating_object=project)
    api['aggregate.assign_object'](f, products=[building], relating_object=site)

    # (b) the same scene the .blend and the .glb are made of
    builder = load_builder(here)
    blend = os.path.splitext(args.out)[0] + '.f2d.blend'
    info = builder.build(drawing, blend, None)
    try:
        os.remove(blend)  # the IFC is the deliverable
    except OSError as _exc:
        _zyg_log.debug('intermediate .blend removal skipped: %s', _exc)

    storeys: dict = {}

    def storey_for(level: int):
        if level not in storeys:
            st = api['root.create_entity'](f, ifc_class='IfcBuildingStorey', name='Level %d' % level)
            st.Elevation = float(level) * storey_h
            api['aggregate.assign_object'](f, products=[st], relating_object=building)
            storeys[level] = st
        return storeys[level]

    # (c) one element per built mesh, typed by the record's kind
    made = 0
    skipped = 0
    by_class: dict = {}
    objects = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('studio_id')]
    objects.sort(key=lambda o: o.name)
    for obj in objects:
        rid = str(obj['studio_id'])
        rec = records.get(rid) or {}
        kind = str(obj.get('studio_kind') or rec.get('kind') or 'box')
        if any(kind.startswith(p) for p in SKIP_PREFIX):
            skipped += 1
            continue
        me = obj.data
        if not me or not len(me.polygons):
            skipped += 1
            continue
        cls = ifc_class_for(kind)
        nm = str(obj.get('studio_name') or rec.get('name') or kind)[:120]
        elem = api['root.create_entity'](f, ifc_class=cls, name=nm)
        # the studio's own id, so a round trip can find the record again
        try:
            elem.Description = 'studio_id=%s kind=%s' % (rid, kind)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('IFC element description not settable: %s', _exc)

        verts = [tuple(v.co) for v in me.vertices]
        faces = [list(poly.vertices) for poly in me.polygons]
        rep = api['geometry.add_mesh_representation'](f, context=body, vertices=[verts], faces=[faces])
        api['geometry.assign_representation'](f, product=elem, representation=rep)
        api['geometry.edit_object_placement'](f, product=elem, matrix=np.array(obj.matrix_world), is_si=True)

        try:
            y = float(rec.get('y') or 0.0)
        except (TypeError, ValueError):
            y = 0.0
        level = int(round(y / storey_h)) if storey_h else 0
        api['spatial.assign_container'](f, products=[elem], relating_structure=storey_for(level))
        by_class[cls] = by_class.get(cls, 0) + 1
        made += 1

    if not storeys:  # an empty building still needs a level
        storey_for(0)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or '.', exist_ok=True)
    f.write(args.out)
    return {
        'ok': True,
        'elements': made,
        'skipped': skipped,
        'by_class': by_class,
        'storeys': len(storeys),
        'schema': args.schema,
        'built': int(info.get('objects') or 0),
        'path': os.path.abspath(args.out),
        'bytes': os.path.getsize(args.out),
    }


if __name__ == '__main__':  # the CLI lives in file_2d_ifc_cli
    try:
        from zyg_workflows.arch_server_ext.file_2d_ifc_cli import main as _cli_main
    except ImportError:  # inside Blender's python, which has no zyg_workflows installed
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from zyg_workflows.arch_server_ext.file_2d_ifc_cli import main as _cli_main

    raise SystemExit(_cli_main())
