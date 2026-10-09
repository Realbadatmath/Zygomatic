# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build.api — the API the build script gets: the reference
pictures, the image planes and empties made from them, and the asset/scaffolding
split (lines 133-320 of the original single file, moved verbatim).
"""

import logging as _zyg_logging
import math
import os
import sys as _sys

import bpy
import mathutils

from .base import ACROSS, ORIENT, _num, _REF_OBJS, log

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_reference_build')


class _LiveRef:
    """``REF`` as the readers below still see it.

    ``main.main`` REBINDS ``REF`` (``global REF``) the moment ``--ref`` is read.
    That rebinding and these readers were one module's globals before the split;
    now the rebinding lands in ``.main`` and only a live view can follow it, so
    every moved ``REF.get(...)`` / ``REF[k]`` below is kept byte for byte and
    reads the dict ``main`` is holding right now (``{}`` before it has read one).
    """

    @staticmethod
    def _live():
        m = _sys.modules.get(__package__ + '.main')
        ref = getattr(m, 'REF', None) if m is not None else None
        return ref if isinstance(ref, dict) else {}

    def __getattr__(self, name):
        return getattr(self._live(), name)

    def __getitem__(self, key):
        return self._live()[key]

    def __contains__(self, key):
        return key in self._live()

    def __iter__(self):
        return iter(self._live())

    def __len__(self):
        return len(self._live())

    def __bool__(self):
        return bool(self._live())

    def __repr__(self):
        return repr(self._live())


REF = _LiveRef()


# ── the API the script gets ──────────────────────────────────────────────────
def ref_images(role=None):
    """The reference pictures, newest last. role may be one role or a list."""
    imgs = REF.get('images') or []
    if role is None:
        return list(imgs)
    want = {role} if isinstance(role, str) else set(role)
    return [i for i in imgs if i.get('role') in want]


def ref_path(role_or_id):
    """One picture's absolute path — by picture id, or the first of a role."""
    for i in REF.get('images') or []:
        if i.get('id') == role_or_id:
            return i['path']
    hits = ref_images(role_or_id)
    if not hits:
        raise ValueError(
            'no reference picture with role or id %r (have: %s)'
            % (role_or_id, ', '.join(sorted({i.get('role') for i in REF.get('images') or []})) or 'none')
        )
    return hits[0]['path']


def ref_width(role, width_m=None, img=None):
    """The real-world width the plan `role` should span, in metres.

    Order: an explicit width_m, then the PICTURE's own span_m (what the
    operator measured for that plate — a plate is rarely cropped to the
    subject's ends, so the subject's length is usually NOT the image's width),
    then the measured dimension the role runs across."""
    if width_m:
        return float(width_m)
    if img and _num(img.get('span_m')) > 0:
        return _num(img['span_m'])
    key = ACROSS.get(role, 'length_m')
    v = _num(REF.get(key))
    if v > 0:
        return v
    for k in ('length_m', 'height_m', 'beam_m'):
        if _num(REF.get(k)) > 0:
            log('NOTE: %s has no measured %s — using %s = %g m across' % (role, key, k, _num(REF[k])))
            return _num(REF[k])
    log(
        'NOTE: nothing is measured on this reference — %s is laid out 10 m across, '
        'so the asset will be the RIGHT SHAPE at the WRONG SIZE' % role
    )
    return 10.0


def _tag(ob):
    ob['zyg_ref'] = 1
    _REF_OBJS.append(ob)
    return ob


def _img_for(role_or_id):
    for i in REF.get('images') or []:
        if i.get('id') == role_or_id:
            return i
    hits = ref_images(role_or_id)
    return hits[0] if hits else None


def ref_plane(role, width_m=None, at=0.0, name=None, image_id=None, datum=None):
    """A mesh plane carrying the reference picture, laid into that view's plane.

    A MESH, not only an empty, so it shows up in a render: the way to know a
    hull is right is to render it through the same view as the plan and look at
    the difference, which needs both in one picture.

      at     — metres along the view's normal. NEGATIVE pushes the plate behind
               your geometry, which is where you want it.
      datum  — (u, v) in 0..1 from the picture's bottom-left: the point in the
               PICTURE that belongs at the model's origin. Defaults to the
               picture's own stored datum, else its middle. This is not a
               nicety: a plate is almost never drawn with its subject centred,
               and a centred plate lines up along one axis while floating along
               the other, which reads exactly like a modelling error.
    """
    rec = _img_for(image_id or role)
    path = ref_path(image_id or role)
    if role not in ORIENT:
        raise ValueError(
            'role %r is a photograph, not a view — only %s can be laid out' % (role, ', '.join(sorted(ORIENT)))
        )
    img = bpy.data.images.load(path, check_existing=True)
    w_px, h_px = (img.size[0] or 1), (img.size[1] or 1)
    w = ref_width(role, width_m, rec)
    h = w * (h_px / float(w_px))
    flip = bool(rec and rec.get('flip'))
    du, dv = datum if datum is not None else ((rec or {}).get('datum') or (0.5, 0.5))
    du, dv = float(du), float(dv)

    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
    ob = bpy.context.active_object
    ob.name = name or ('ref_' + role)
    ob.scale = ((-w if flip else w) / 2.0, h / 2.0, 1.0)
    e = ORIENT[role][0]
    ob.rotation_euler = (e[0] * math.pi, e[1] * math.pi, e[2] * math.pi)
    bpy.context.view_layer.update()

    # The datum shift runs along the plane's OWN u and v axes, so it has to be
    # applied after the rotation. A mirrored plate's u runs the other way.
    rot = mathutils.Euler(ob.rotation_euler).to_matrix()
    u_ax = rot @ mathutils.Vector((1.0, 0.0, 0.0))
    v_ax = rot @ mathutils.Vector((0.0, 1.0, 0.0))
    if flip:
        u_ax = -u_ax
    n = mathutils.Vector(ORIENT[role][1])
    ob.location = n * float(at) - u_ax * ((du - 0.5) * w) - v_ax * ((dv - 0.5) * h)

    mat = bpy.data.materials.new('ref_' + role)
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    emi = nt.nodes.new('ShaderNodeEmission')
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    tex.interpolation = 'Closest' if max(w_px, h_px) < 900 else 'Linear'
    nt.links.new(tex.outputs['Color'], emi.inputs['Color'])
    nt.links.new(emi.outputs['Emission'], out.inputs['Surface'])
    ob.data.materials.append(mat)
    log(
        'ref_plane %s: %s, %.3f x %.3f m at %g, datum %g,%g%s'
        % (role, os.path.basename(path), w, h, at, du, dv, ' MIRRORED' if flip else '')
    )
    return _tag(ob)


def ref_empty(role, width_m=None, at=0.0, name=None, image_id=None):
    """The same view as an image EMPTY — viewport reference, never rendered."""
    rec = _img_for(image_id or role)
    path = ref_path(image_id or role)
    if role not in ORIENT:
        raise ValueError('role %r is a photograph, not a view' % (role,))
    e = ORIENT[role][0]
    n = mathutils.Vector(ORIENT[role][1]) * float(at)
    bpy.ops.object.empty_image_add(
        filepath=path, align='WORLD', location=tuple(n), rotation=(e[0] * math.pi, e[1] * math.pi, e[2] * math.pi)
    )
    ob = bpy.context.active_object
    ob.name = name or ('refempty_' + role)
    img = ob.data
    w_px = (img.size[0] or 1) if img else 1
    ob.empty_display_size = ref_width(role, width_m, rec) / 2.0 if w_px else 1.0
    return _tag(ob)


def ref_clear():
    """Remove every reference plane and empty."""
    n = 0
    for ob in list(_REF_OBJS):
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            n += 1
        except (ReferenceError, RuntimeError) as _exc:
            _zyg_log.debug('reference object removal skipped: %s', _exc)
    _REF_OBJS[:] = []
    # anything tagged by hand as well
    for ob in list(bpy.data.objects):
        if ob.get('zyg_ref'):
            bpy.data.objects.remove(ob, do_unlink=True)
            n += 1
    return n


def mirror(obj, axis='y', merge=0.001):
    """A Mirror modifier across the named axis. A hull, a fuselage and a facade
    are symmetric: model one half and the halves can never drift apart."""
    m = obj.modifiers.new('Mirror', 'MIRROR')
    m.use_axis = (axis == 'x', axis == 'y', axis == 'z')
    m.use_clip = True
    m.merge_threshold = merge
    return m


def asset_objects():
    """Everything that is NOT reference scaffolding."""
    return [o for o in bpy.data.objects if not o.get('zyg_ref')]


def asset_meshes():
    return [o for o in asset_objects() if o.type == 'MESH']
