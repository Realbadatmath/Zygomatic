# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_v3_seam.py — the V3 GROUND SEAM (2026-09-07).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_v3_seam.py

The v3 design is ONE sculpted heightfield per drawing: a `ground` record whose
height is the base noise plus the contribution of every `sculpt_*` record in the
same drawing, coloured per vertex from the studio's own material hexes. None of
that is possible unless a geometry builder can (a) see the OTHER records and
(b) hand back a colour per vertex — in all three engines, saying the same thing.

This proves exactly those two seams with the `v3probe` fixture family: a 2 m x
2 m quad whose far edge is lifted by the NUMBER OF `box` RECORDS IN THE DRAWING,
its four corners coloured red, green, blue and white.

  · the assistant  arch_assistant.current_drawing() inside a HEIGHTS call, and
                   sculpts_of()
  · the tab        arExtKit().records + a part's `vcolors` -> a `color` attribute
  · Blender        ext_kit()['records'] + the builder's third return value -> a
                   'Col' FLOAT_COLOR attribute and a material that reads it
  · the harness    `others` on a case (both engines), `vcolors` / `vcol` reported
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, browser_kinds, blender_kinds  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def probe_drawing(boxes, y=0.0):
    """A drawing holding the probe at the origin plus `boxes` box records."""
    d = A.Drawing({'objects': []})
    d.new('v3probe', {}, 0.0, 0.0, y)
    for i in range(boxes):
        d.new('box', {'w': 1, 'd': 1, 'h': 1}, 40.0 + i * 3, 40.0)
    return d


# ── the assistant ─────────────────────────────────────────────────────────────
print('python')
check(
    'the v3probe fixture family loaded',
    'v3probe' in A.EXT_HEIGHTS and 'v3probe' in A.KINDS,
    sorted(k for k in A.EXT_HEIGHTS),
)
check('current_drawing() is None outside a HEIGHTS call', A.current_drawing() is None, A.current_drawing())

d0 = probe_drawing(0)
check('probe with no boxes: the ground is 0', A.ground_height(d0, 0, 0) == 0.0, A.ground_height(d0, 0, 0))
d2 = probe_drawing(2)
check(
    'probe + 2 boxes: ground_height == 2 (the HEIGHTS fn read the other records)',
    abs(A.ground_height(d2, 0, 0) - 2.0) < 1e-9,
    A.ground_height(d2, 0, 0),
)
d5 = probe_drawing(5)
check('probe + 5 boxes: ground_height == 5', abs(A.ground_height(d5, 0, 0) - 5.0) < 1e-9, A.ground_height(d5, 0, 0))
check(
    'outside the 2 x 2 footprint the probe contributes nothing',
    A.ground_height(d5, 3.0, 0) == 0.0 and A.ground_height(d5, 0, -3.0) == 0.0,
    (A.ground_height(d5, 3.0, 0), A.ground_height(d5, 0, -3.0)),
)
check(
    'the record y still adds on top',
    abs(A.ground_height(probe_drawing(2, y=3.0), 0, 0) - 5.0) < 1e-9,
    A.ground_height(probe_drawing(2, y=3.0), 0, 0),
)
check(
    'current_drawing() is None again once the call returned (the context is restored)',
    A.current_drawing() is None,
    A.current_drawing(),
)

seen = {}


def _spy(p, lx, lz):
    seen['d'] = A.current_drawing()
    return None


A.EXT_HEIGHTS['v3probe_spy'] = _spy
ds = A.Drawing({'objects': []})
ds.new('v3probe_spy', {}, 0.0, 0.0)
A.ground_height(ds, 0, 0)
check('the drawing a HEIGHTS fn sees IS the drawing being walked', seen.get('d') is ds, seen.get('d'))
del A.EXT_HEIGHTS['v3probe_spy']

nested = {}


def _outer(p, lx, lz):
    nested['inner_before'] = A.current_drawing()
    A.ground_height(A.Drawing({'objects': []}), 0, 0)
    nested['inner_after'] = A.current_drawing()
    return None


A.EXT_HEIGHTS['v3probe_nest'] = _outer
dn = A.Drawing({'objects': []})
dn.new('v3probe_nest', {}, 0.0, 0.0)
A.ground_height(dn, 0, 0)
check(
    'a nested ground_height restores the outer drawing (the context manager is re-entrant)',
    nested.get('inner_before') is dn and nested.get('inner_after') is dn,
    nested,
)
del A.EXT_HEIGHTS['v3probe_nest']

dsc = A.Drawing({'objects': []})
dsc.new('ground', {'w': 100, 'd': 100}, 0.0, 0.0)
dsc.new('sculpt_peak', {'r': 30, 'h': 40}, 10.0, 10.0)
dsc.new('sculpt_cut', {'len': 80, 'w': 20, 'depth': 8}, -10.0, 0.0)
dsc.new('box', {'w': 1, 'd': 1, 'h': 1}, 0.0, 0.0)
hidden = dsc.new('sculpt_basin', {'rx': 20, 'rz': 12, 'depth': 4}, 30.0, 30.0)
hidden['hidden'] = True
check(
    'sculpts_of returns only the sculpt_* records',
    [o['kind'] for o in A.sculpts_of(dsc)] == ['sculpt_peak', 'sculpt_cut'],
    [o['kind'] for o in A.sculpts_of(dsc)],
)
check('sculpts_of leaves out a hidden sculpt', all(not o.get('hidden') for o in A.sculpts_of(dsc)))
check('sculpts_of(None) is empty, not a crash', A.sculpts_of(None) == [])
check('sculpts_of on a drawing with no sculpts is empty', A.sculpts_of(probe_drawing(2)) == [])

# ── the seam files carry the contract ─────────────────────────────────────────
# 2026-10: arch_blender_build.py became a package, so the contract this section
# greps for is spread over its submodules (ext_kit/build_kind/mat_rgb in kinds.py,
# the vertex-colour build in build_scene.py). Read them all, in a stable order.
import zyg_workflows  # noqa: E402

_BB_DIR = os.path.join(os.path.dirname(zyg_workflows.__file__), 'arch_blender_build')
_BB_SRCS = sorted(f for f in os.listdir(_BB_DIR) if f.endswith('.py'))
check('the arch_blender_build package is on disk', len(_BB_SRCS) >= 2, (_BB_DIR, _BB_SRCS))
bb = ''
for _src in _BB_SRCS:
    with open(os.path.join(_BB_DIR, _src), encoding='utf-8') as _fh:
        bb += _fh.read() + '\n'
check(
    "arch_blender_build.ext_kit takes records and offers 'records' + 'mat_rgb'",
    re.search(r'def ext_kit\(records=None\)', bb) is not None
    and "'records': list(records or [])" in bb
    and "'mat_rgb': mat_rgb" in bb,
)
check(
    'arch_blender_build.build_kind threads the records through',
    re.search(r'def build_kind\(bm, kind, p, records=None\)', bb) is not None,
)
check(
    "arch_blender_build creates a 'Col' FLOAT_COLOR POINT attribute for a vcolors build",
    "color_attributes.new(VCOL_ATTR, 'FLOAT_COLOR', 'POINT')" in bb and 'get_material_vc' in bb,
)
check(
    'a vertex-coloured build skips remove_doubles (it would merge the colours away)',
    'if not vcolors:' in bb and bb.index('if not vcolors:') < bb.index('remove_doubles(bm, verts=bm.verts'),
)
check('mat_rgb reads the studio hexes', 'MAT_COLOURS.get(key, MAT_FALLBACK)' in bb)

ins = open(os.path.join(HERE, 'inspection.html'), encoding='utf-8').read()
check('arExtKit hands the geometry function the live record list and matRGB', 'records:AR.objs, matRGB:arMatRGB' in ins)
check(
    'the tab has a vertex-coloured material twin, cached per preset',
    'function arMatVC(id)' in ins and 'AR.matCache[key]=m' in ins,
)
check(
    "a part's vcolors becomes the geometry's `color` attribute",
    "pt.g.setAttribute('color', new THREE.Float32BufferAttribute(pt.vcolors, 3))" in ins,
)
check(
    'a material change keeps a vertex-coloured mesh vertex-coloured',
    'o.userData.arVC ? arMatVC(rec.mat) : arMat(rec.mat)' in ins,
)
check(
    'arGroundRefresh exists, is debounced by rAF and only fires for sculpts',
    'function arGroundRefresh(rec)' in ins
    and 'AR._groundRAF=requestAnimationFrame' in ins
    and 'if(rec && !arIsSculpt(rec.kind)) return;' in ins,
)
check(
    'every place a sculpt appears, moves, changes or dies refreshes the ground',
    ins.count('arGroundRefresh(') >= 8,
    ins.count('arGroundRefresh('),
)

rd = open(os.path.join(HERE, 'arch_ext', 'README.md'), encoding='utf-8').read()
check(
    'the family contract documents v3 ground',
    '## v3 ground' in rd and 'kit.records' in rd and 'vcolors' in rd and 'current_drawing()' in rd,
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
box = {'kind': 'box', 'p': {'w': 1, 'd': 1, 'h': 1}, 'x': 0, 'y': 0, 'z': 0}
b = browser_kinds([{'kind': 'v3probe', 'others': [box, box, box]}, {'kind': 'v3probe'}])
p3, p0 = b[0], b[1]
check('tab: the probe builds real geometry', p3['ok'] and p3['registered'], p3)
check(
    'tab: 3 box records in the drawing make the quad 3 m tall — kit.records is live',
    abs(p3['size'][1] - 3.0) < 1e-3,
    p3['size'],
)
check('tab: the quad is 2 x 2 in plan', abs(p3['size'][0] - 2.0) < 1e-3 and abs(p3['size'][2] - 2.0) < 1e-3, p3['size'])
check('tab: the built mesh carries vertex colours', p3['vcolors'] is True, p3)
check('tab: two triangles, one part', p3['tris'] == 2 and p3['parts'] == 1, p3)
check(
    'tab: with NO others the same kind is flat — `others` really were injected and removed',
    abs(p0['size'][1]) < 1e-6 and p0['vcolors'] is True,
    p0['size'],
)
check('tab: the probe has its own label, not the raw kind', p3['label'] == 'v3 seam probe', p3['label'])

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds([{'kind': 'v3probe', 'others': [box, box, box]}])
r = bl.get('v3probe') or {}
check('blender: the probe builds', r.get('polys', 0) >= 2, bl)
check(
    'blender: 3 box records make it 3 m tall — ext_kit records is live',
    r.get('size') and abs(r['size'][1] - 3.0) < 1e-3,
    r.get('size'),
)
check(
    'blender: 2 x 2 in plan, the same quad as the tab',
    r.get('size') and abs(r['size'][0] - 2.0) < 1e-3 and abs(r['size'][2] - 2.0) < 1e-3,
    r.get('size'),
)
check("blender: the mesh has a colour attribute ('Col')", r.get('vcol') is True, r)
check(
    'blender: four vertices survive — remove_doubles did not merge the colours away',
    r.get('verts') == 4,
    r.get('verts'),
)
bl0 = blender_kinds([{'kind': 'v3probe'}])
r0 = bl0.get('v3probe') or {}
check(
    'blender: with no others the quad is flat, and still vertex-coloured',
    r0.get('size') and abs(r0['size'][1]) < 1e-6 and r0.get('vcol') is True,
    r0,
)
check(
    'blender and the tab agree about the probe',
    r.get('size') and abs(r['size'][1] - p3['size'][1]) < 1e-3 and abs(r['size'][0] - p3['size'][0]) < 1e-3,
    (r.get('size'), p3['size']),
)
finish()
