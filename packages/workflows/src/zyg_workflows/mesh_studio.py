# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio — the server-side registry the page draws its bars from.

Mesh Studio is the fourth studio in inspection.html and it is built the way
Creature Studio is built: the page holds NO tool list.  Everything that exists
-- its label, its section, which bar it sits on, its tooltip, its icon and its
knobs -- is declared here and shipped to the browser as one JSON payload.  Add
an op to a part file under ``mesh_studio_ops/`` and it appears in the rail on
the next reload without a line of the page changing.

**Every op in this registry is a PLACEHOLDER.**  ``ph=True`` is the default and
nothing overrides it yet.  That is deliberate and it is the honest state of the
studio: the list below is an advanced, complete description of what a mesh
studio *should* offer, published so the shape of the thing can be seen, argued
with and built against -- not a claim that any of it runs.  The page reads the
flag and draws a placeholder op dashed, with an amber pip, "[placeholder]" in
its tooltip and a sheet on click that says so.  An op stops being dashed the
day someone passes ``ph=False`` *and* wires ``fn``/``pfn``, and not before.

Layout of the registry:

    mesh_studio.py            this file — helpers, ``_op``, ``SECTION_ORDER``,
                              ``load_parts()``, ``ops_payload()``, ``spec()``
    mesh_studio_ops/a_*.py    the ops themselves, imported in NAME ORDER so the
                              registry order (and therefore the rail order) is
                              a property of the filenames, not of import luck.

Run ``python3 mesh_studio.py`` for a count per section.
"""

from __future__ import annotations

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS_DIR = os.path.join(HERE, 'mesh_studio_ops')


# ── parameter schema helpers (the same five types the VFX toolbox uses) ─────
# Shared shape with creature_fx.f/i/b/e/c/s on purpose: the page already knows
# how to draw these six dicts, so a new studio costs no new widget code.
def f(k, lb, df, mn, mx, st=0.01, tip=''):
    """Float slider."""
    return {'k': k, 'lb': lb, 't': 'f', 'df': df, 'mn': mn, 'mx': mx, 'st': st, 'tip': tip}


def i(k, lb, df, mn, mx, st=1, tip=''):
    """Integer slider."""
    return {'k': k, 'lb': lb, 't': 'i', 'df': df, 'mn': mn, 'mx': mx, 'st': st, 'tip': tip}


def b(k, lb, df=False, tip=''):
    """Checkbox."""
    return {'k': k, 'lb': lb, 't': 'b', 'df': bool(df), 'tip': tip}


def e(k, lb, df, opts, tip=''):
    """Enum — a select drawn from `opts`."""
    return {'k': k, 'lb': lb, 't': 'e', 'df': df, 'opts': list(opts), 'tip': tip}


def c(k, lb, df='#7fd8c8', tip=''):
    """Colour swatch."""
    return {'k': k, 'lb': lb, 't': 'c', 'df': df, 'tip': tip}


def s(k, lb, df='', tip='', pat=r"[-+0-9a-zA-Z_.,;:'()/ ]{0,300}"):
    """Free text, held to the full-match charset `pat`.

    Nothing typed here reaches a shell, but it does reach a JSON sidecar, a
    filename and a manifest, so it is bounded at the door rather than escaped
    at each of the places it lands."""
    return {'k': k, 'lb': lb, 't': 's', 'df': df, 'tip': tip, 'pat': pat}


# ── the registry ────────────────────────────────────────────────────────────
# `bar` says which of the three bars the icon lives on and NOTHING APPEARS ON
# MORE THAN ONE:
#
#   'side'  what the mesh IS — the geometry, the rig, the surface. Left rail.
#   'dock'  what the SESSION is — source, viewport, render, export (task 5).
#   'top'   the few global toggles that belong above the viewport (task 5).
#
# `needs` is honesty about reach, read by the page to grey an op out and say
# why rather than to offer it and fail late:
#
#   ''      always available once built
#   'mesh'  a mesh must be loaded
#   'rig'   the loaded mesh must be rigged
#   'gpu'   loads a model onto the GPU (image->mesh, auto-rig, bakes)
#
# `ph` is honesty about existence. True = declared, not implemented.
OPS = []
_SEEN = set()

NEEDS_OK = ('', 'mesh', 'rig', 'gpu')

#: Rail order. A section not named here still ships (appended in first-seen
#: order by ``ops_payload``), but naming it pins where it lands.
SECTION_ORDER = [
    # bar 'side' — what the mesh IS (task 4, this file's part a_shape.py)
    'Library',
    'Import',
    'Topology',
    'Transform',
    'Shape',
    'Rig',
    'Weights',
    'UV',
    'Material',
    # bar 'side'/'dock' — what the SESSION is (task 5, part b_session.py)
    'Texture',
    'Bake',
    'Inspect',
    'Measure',
    'Repair',
    'Export',
    'Viewport',
    'Render',
    'Session',
]


def _op(id_, lb, sec, bar, tip, svg, params=(), cls='edit', fn=None, pfn=None, needs='', tog=False, ph=True):
    """Register one op.

    id_     stable id, prefixed per section (lib_, imp_, top_, tr_, sh_, rig_,
            wt_, uv_, mat_). Duplicates are a hard error, not a last-one-wins.
    cls     'edit' a geometry operation that changes the mesh
            'pix'  a deterministic, previewable measurement or view change
            'act'  a button: no stack row, an action
    ph      True while the op is declared but not implemented.
    """
    if id_ in _SEEN:
        raise ValueError(f'duplicate op id {id_}')
    if needs not in NEEDS_OK:
        raise ValueError(f'{id_}: unknown needs {needs!r}')
    if not svg or '<svg' in svg:
        raise ValueError(f'{id_}: svg must be path fragments only')
    _SEEN.add(id_)
    OPS.append(
        {
            'id': id_,
            'lb': lb,
            'sec': sec,
            'bar': bar,
            'tip': tip,
            'svg': svg,
            'params': list(params),
            'cls': cls,
            'fn': fn,
            'pfn': pfn,
            'needs': needs,
            'tog': bool(tog),
            'ph': bool(ph),
            'act': cls == 'act',
        }
    )
    return OPS[-1]


def load_parts():
    """Import every ``mesh_studio_ops/*.py`` -- or ``*/__init__.py`` -- in NAME ORDER.

    Each part does ``from mesh_studio import _op, f, i, b, e, c, s`` and
    registers its ops at import time, so the registry order -- and therefore
    the order the rail draws -- is decided by the filenames. Idempotent: a
    part already in ``sys.modules`` is not re-imported, which is what keeps
    ``_op``'s duplicate assert from firing on a second call.

    A part may be a FILE or a PACKAGE DIRECTORY: the 2026-10 modularization turns
    the big ones (``a_shape``, ``b_session``) into ``<name>/__init__.py``, which a
    ``.py`` suffix test cannot see -- and a part that is not discovered registers
    nothing, so the rail silently loses its ops. The import below is by dotted
    name, which loads a file and a package the same way."""
    if not os.path.isdir(PARTS_DIR):
        return []
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    names = sorted(
        n[:-3] if n.endswith('.py') else n
        for n in os.listdir(PARTS_DIR)
        if not n.startswith('_') and (n.endswith('.py') or os.path.isfile(os.path.join(PARTS_DIR, n, '__init__.py')))
    )
    loaded = []
    for n in names:
        mod = f'mesh_studio_ops.{n}'
        if mod not in sys.modules:
            importlib.import_module(mod)
        loaded.append(mod)
    return loaded


# The parts register at import of THIS module, so `mesh_studio.OPS` is true the
# moment anything imports it -- a caller that reads OPS directly does not have
# to know it must call ops_payload() first. The parts do
# `from mesh_studio import _op, ...` while this module is still initialising;
# that resolves because every name they ask for is defined above this line.
#
# Skipped under `python3 mesh_studio.py`, where this module is `__main__` and a
# part's `from mesh_studio import ...` would import a SECOND copy with a second,
# separate OPS list. The `__main__` block at the bottom imports that copy
# explicitly instead.
if __name__ != '__main__':
    load_parts()


# ── what the page draws its bars from ───────────────────────────────────────
def ops_payload():
    """The single source of truth for what exists, what it is called, what it
    will do, what it looks like and what knobs it has.

    Groups OPS by (bar, sec) preserving registry order within a section and
    ``SECTION_ORDER`` between them, strips the callables (they do not survive
    JSON and the page has no use for them) and counts what it shipped."""
    load_parts()
    secs, order = {}, []
    for o in OPS:
        key = (o['bar'], o['sec'])
        if key not in secs:
            secs[key] = []
            order.append(key)
        secs[key].append({k: v for k, v in o.items() if k not in ('fn', 'pfn')})

    def rank(key):
        sec = key[1]
        return SECTION_ORDER.index(sec) if sec in SECTION_ORDER else len(SECTION_ORDER) + order.index(key)

    order.sort(key=rank)
    return {
        'ok': True,
        'sections': [{'bar': bar, 'sec': sec, 'items': secs[(bar, sec)]} for bar, sec in order],
        'section_order': list(SECTION_ORDER),
        'counts': {
            'side': sum(1 for o in OPS if o['bar'] == 'side'),
            'dock': sum(1 for o in OPS if o['bar'] == 'dock'),
            'top': sum(1 for o in OPS if o['bar'] == 'top'),
            'placeholder': sum(1 for o in OPS if o['ph']),
            'built': sum(1 for o in OPS if not o['ph']),
            'sections': len(order),
            'total': len(OPS),
        },
    }


def spec():
    """What the studio claims about itself — read by the page's about sheet
    and by anything auditing how much of this is real."""
    d = ops_payload()
    by_sec = [
        {'bar': s_['bar'], 'sec': s_['sec'], 'n': len(s_['items']), 'ph': sum(1 for it in s_['items'] if it['ph'])}
        for s_ in d['sections']
    ]
    return {
        'ok': True,
        'studio': 'mesh',
        'title': 'Mesh Studio',
        'blurb': (
            'Geometry, rig and surface for one mesh: open it, repair its '
            'topology, fit its proportions, rig it, weight it, unwrap it '
            'and dress it.'
        ),
        'bars': {'side': 'what the mesh IS', 'dock': 'what the SESSION is', 'top': 'global toggles'},
        'needs': list(NEEDS_OK),
        'counts': d['counts'],
        'sections': by_sec,
        'placeholder': d['counts']['placeholder'] == d['counts']['total'],
        'missing': MISSING,
    }


# ── what is deliberately absent ─────────────────────────────────────────────
# Named here so the gap is a decision on the record rather than an oversight
# someone has to rediscover. The about sheet prints it.
MISSING = [
    {
        'what': 'Sculpting brushes',
        'why': 'Grab, inflate, crease, clay strips and the rest need a live paint '
        'canvas over the viewport with per-stroke undo — a different input '
        'model from a bar of parameterised ops, and a build of its own. '
        'Shape morphs and the topology tools cover the cases a bar can '
        'honestly serve.',
    },
    {
        'what': 'Physics — cloth, softbody, collision, rigid-body drop',
        'why': 'Simulation is a solver with time in it, not an edit: it needs a '
        'frame range, a cache directory and a bake queue. It belongs with '
        'the render side of the house, not in a mesh bar.',
    },
    {
        'what': 'Animation timeline — keyframes, curves, NLA, motion clips',
        'why': 'Movement Studio owns motion. Mesh Studio rigs a mesh and tests a '
        'pose; the moment there is a second pose in time it is Movement '
        "Studio's file and Movement Studio's bar. Two studios owning one "
        'timeline is how the pose and the clip drift apart.',
    },
    {
        'what': 'Scene assembly — multiple meshes, lighting rigs, cameras',
        'why': 'One mesh at a time is the whole premise of this studio. Scenes '
        'are assembled by the scene bridge (scene_build -> plates).',
    },
]


if __name__ == '__main__':
    from zyg_workflows import mesh_studio as M  # the importable copy — see load_parts() above

    d = M.ops_payload()
    w = max((len(s_['sec']) for s_ in d['sections']), default=0)
    for s_ in d['sections']:
        ph = sum(1 for it in s_['items'] if it['ph'])
        print(f'  {s_["bar"]:<5} {s_["sec"]:<{w}}  {len(s_["items"]):>3} ops  ({ph} placeholder)')
    c_ = d['counts']
    print(f'\n  {c_["total"]} ops · {c_["sections"]} sections · {c_["placeholder"]} placeholder · {c_["built"]} built')
    print(
        f'  deliberately absent: {len(M.MISSING)} '
        f'({", ".join(m["what"].split(" —")[0].split(" -")[0] for m in M.MISSING)})'
    )
