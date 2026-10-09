#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_glass_water — glass reads as glass and water reads as water (2026-09-16).

WHAT WENT WRONG. The live acceptance run (job aba5ab208439) built the operator's
tower correctly in geometry, and the creator looked at the pictures: every glass
surface — 39 curtain wall panels, the entrance canopy, the pool weir — rendered
MILKY WHITE. arch_blender_build's mat_glass was a Principled with alpha 0.35 in
BLEND mode: no reflection, no refraction, nothing of the lobby behind it, and an
opaque shadow under the canopy. The pool water (alpha 0.7) was a flat blue plate.

The builder now writes a transmissive glass (Transmission 1.0, IOR 1.5, alpha
1.0) in three looks — a thin PANEL for curtain walls / canopies / balustrades /
the pool weir, CLEAR for an entrance door, and the default thickness of glass
for a glass wall — and routes the SHADOW ray through a tinted Transparent BSDF,
because Cycles blocks a shadow ray at a transmissive BSDF and the canopy would
still throw a black shadow. Water is transmissive at IOR 1.33 over a noise bump
ripple with a Volume Absorption. EEVEE has no thickness to refract a thin pane
through, so blender_power's EEVEE branch calls tune_glass_for_eevee(), which
switches those materials to BLENDED alpha (0.15 for a pane, 0.6 for water).

THE PROOF is measured, never asserted from the shader alone:

  · THE SHADER — a bpy probe on the .blend: the three glass looks and the water,
    their transmission / IOR / roughness, the shadow-ray mix, the ripple and the
    absorption, and that the EEVEE tune retunes exactly those materials.
  · THE PICTURE — the SAME live fixture built twice, once with the builder as it
    was (arch_blender_build.py.bak-glass-20260916) and once with the builder as
    it is, rendered through the same camera in Cycles at 960x540. Every number
    below was measured on this machine on 2026-09-16 (16 samples):

      front elevation, the pixels the change touched (8.8 % of the frame, the
      curtain wall bands):     flat field (within +-3 of the median)  59.4 % -> 12.9 %
                               pixels brighter than 200 (milky white) 78.0 % ->  1.6 %
                               luminance std-dev                      34.50 -> 43.53
      the brief's band (rows 40-60 %, cols 30-70 %): std 28.30, mean 122.95
      roof pool close-up, the flat blue plate's pixels:
                               ripple (mean neighbour difference)      0.59 ->  1.56
                               luminance std-dev                      23.23 -> 33.01
      a 12 x 12 m canopy 5 m over a concrete pad, glass vs concrete, top view:
                               the ground under it        135.04 -> 208.02 (+72.98)

Run: "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_glass_water.py
"""

import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)

os.environ.setdefault('ZYG_ARCH_HERO_SAMPLES', '16')

import zyg_workflows  # noqa: E402
from zyg_workflows.arch_ext_harness import BLENDER, check, finish, _blender  # noqa: E402

PKG = os.path.dirname(zyg_workflows.__file__)
FIXTURE = os.path.join(HERE, 'fixtures', 'live_tower_20260916.json')
# 2026-10: the builder script became the package zyg_workflows/arch_blender_build/;
# `blender -b --python <pkg>/__main__.py -- --in X --out Y` is the entry it kept.
BUILDER = os.path.join(PKG, 'arch_blender_build', '__main__.py')
OLD_BUILDER = os.path.join(CREWS, 'arch_blender_build.py.bak-glass-20260916')
W, H = 960, 540
OUT = os.path.join('/tmp', 'arch_glass_water')

PROBE = r"""
import bpy, json, sys
sys.path.insert(0, CREWS_DIR)
out = {}
for m in bpy.data.materials:
    if m.get('zyg_eevee_alpha') is None:
        continue
    nt = m.node_tree
    b = nt.nodes.get('Principled BSDF')
    def val(name):
        s = b.inputs.get(name) if b else None
        if s is None:
            return None
        v = s.default_value
        return [round(float(q), 3) for q in v] if hasattr(v, '__len__') else round(float(v), 4)
    ids = sorted({n.bl_idname for n in nt.nodes})
    out[m.name] = {
        'nodes': ids,
        'transmission': val('Transmission Weight'), 'ior': val('IOR'), 'alpha': val('Alpha'),
        'roughness': val('Roughness'), 'base': val('Base Color'),
        'shadow_mix': bool([l for l in nt.links if l.from_node.bl_idname == 'ShaderNodeLightPath'
                            and l.from_socket.name == 'Is Shadow Ray']),
        'transparent': 'ShaderNodeBsdfTransparent' in ids,
        'volume': bool([l for l in nt.links if l.to_socket.name == 'Volume']),
        'bump': bool([l for l in nt.links if l.to_socket.name == 'Normal'
                      and l.from_node.bl_idname == 'ShaderNodeBump']),
        'images': len([n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexImage']),
        'eevee_alpha': round(float(m.get('zyg_eevee_alpha')), 3),
        'glass': m.get('zyg_glass'), 'water': bool(m.get('zyg_water')),
        'srm': getattr(m, 'surface_render_method', None),
        'raytrace_refraction': getattr(m, 'use_raytrace_refraction', None),
        'transparent_shadow': getattr(m, 'use_transparent_shadow', None),
    }
print('PROBE ' + json.dumps(out, sort_keys=True))
from zyg_workflows import arch_blender_build as ABB
n = ABB.tune_glass_for_eevee()
after = {m.name: [round(float(m.node_tree.nodes['Principled BSDF'].inputs['Alpha'].default_value), 3),
                  getattr(m, 'surface_render_method', None)]
         for m in bpy.data.materials if m.get('zyg_eevee_alpha') is not None}
print('TUNED %d' % n)
print('AFTER ' + json.dumps(after, sort_keys=True))
"""


# ── plumbing ────────────────────────────────────────────────────────────────
def build(objs, tag, builder=BUILDER, name='glass'):
    """Run one builder over one drawing; returns the .blend path (or '')."""
    src, blend = os.path.join(OUT, tag + '.json'), os.path.join(OUT, tag + '.blend')
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump({'name': name, 'units': 'm', 'objects': objs}, fh)
    p = _blender([BLENDER, '-b', '--python', builder, '--', '--in', src, '--out', blend], 1800)
    info = {}
    for line in (p.stdout or '').splitlines():
        if line.startswith('{'):
            try:
                info = json.loads(line)
            except ValueError:
                pass
    return (blend if info.get('ok') and os.path.exists(blend) else ''), info


def render(blend, view, tag, cam=None):
    """One Cycles frame at 960x540 through blender_power's own render pass."""
    png = os.path.join(OUT, tag + '.png')
    t0 = time.time()
    rc, txt, _ = B._second_pass(blend, render=(view, 'cycles', W, H, SUN, cam, None, png), timeout=3600)
    print(
        '    %-14s %s  %.0fs' % (tag, 'rendered' if os.path.exists(png) else 'FAILED rc=%s' % rc, time.time() - t0),
        flush=True,
    )
    return png if os.path.exists(png) else ''


def pixels(png, k=1):
    """(width, [rgb], [luminance]) — k>1 box-averages the frame down, which
    strips Cycles' per-pixel noise and leaves the structure."""
    from PIL import Image

    im = Image.open(png).convert('RGB')
    if k > 1:
        im = im.resize((im.width // k, im.height // k), Image.BOX)
    getter = getattr(im, 'get_flattened_data', None) or im.getdata
    px = list(getter())
    return im.width, px, [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]


def changed(a, b, thr):
    return [i for i in range(min(len(a), len(b))) if abs(a[i] - b[i]) > thr]


def ripple(lum, idx, width):
    """Mean |difference to the pixel on the right| inside a mask: a flat plate
    is ~0, a rippled surface is not."""
    s = set(idx)
    v = [abs(lum[i] - lum[i + 1]) for i in idx if (i + 1) in s and (i + 1) % width]
    return statistics.fmean(v) if v else 0.0


def stats(lum, idx):
    sel = [lum[i] for i in idx]
    med = statistics.median(sel)
    return {
        'mean': statistics.fmean(sel),
        'std': statistics.pstdev(sel),
        'flat': 100.0 * sum(1 for v in sel if abs(v - med) <= 3) / len(sel),
        'hi200': 100.0 * sum(1 for v in sel if v > 200) / len(sel),
        'hi220': 100.0 * sum(1 for v in sel if v > 220) / len(sel),
        'max': max(sel),
        'n': len(sel),
    }


def line(name, s, extra=''):
    print(
        '    %-22s mean %6.2f  std %5.2f  flat %5.1f%%  >200 %5.2f%%  >220 %5.2f%%  %s'
        % (name, s['mean'], s['std'], s['flat'], s['hi200'], s['hi220'], extra),
        flush=True,
    )


os.makedirs(OUT, exist_ok=True)
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
import zyg_workflows.arch_assistant_ext.blender_power as B  # noqa: E402

with open(FIXTURE, encoding='utf-8') as fh:
    DOC = json.load(fh)
d = A.Drawing(DOC)
SUN = B._sun_hour(d)
check('the live acceptance fixture loads (983 records)', len(d.objs) == 983, len(d.objs))
HAVE_OLD = os.path.exists(OLD_BUILDER)
if HAVE_OLD:
    check('the builder as it was is kept for the A/B', True, OLD_BUILDER)
else:
    # The .bak-glass-20260916 snapshot lived in the legacy tree and was never
    # committed here, so the A/B half of this harness cannot run in this repo.
    print('  skip legacy A/B builder not shipped — %s' % OLD_BUILDER, flush=True)

# ── 1. the shader ───────────────────────────────────────────────────────────
print('  -- the shader', flush=True)
probe_objs = [
    {
        'id': 'o1',
        'kind': 'curtain_wall',
        'p': {'len': 6, 'h': 3, 't': 0.06},
        'x': 0,
        'y': 0,
        'z': 0,
        'mat': 'mat_glass',
    },
    {'id': 'o2', 'kind': 'wall', 'p': {'len': 6, 'h': 3, 't': 0.24}, 'x': 20, 'y': 0, 'z': 0, 'mat': 'mat_glass'},
    {'id': 'o3', 'kind': 'door', 'p': {'w': 1.2, 'h': 2.4}, 'x': 40, 'y': 0, 'z': 0, 'mat': 'mat_glass'},
    {
        'id': 'o4',
        'kind': 'pool',
        'p': {'w': 6, 'd': 4, 'depth': 1.4, 'inf': 's'},
        'x': 60,
        'y': 0,
        'z': 0,
        'mat': 'acg_Tiles135A',
    },
]
pb, info = build(probe_objs, 'probe')
check('a curtain wall, a glass wall, a glass door and a pool build', bool(pb), info)
spath = os.path.join(OUT, 'probe.py')
with open(spath, 'w', encoding='utf-8') as fh:
    fh.write('CREWS_DIR = %r\n' % CREWS + PROBE)
q = _blender([BLENDER, '-b', pb, '--python', spath], 600)
got, tuned, after = {}, -1, {}
for ln in (q.stdout or '').splitlines():
    if ln.startswith('PROBE '):
        got = json.loads(ln[6:])
    elif ln.startswith('TUNED '):
        tuned = int(ln.split()[1])
    elif ln.startswith('AFTER '):
        after = json.loads(ln[6:])
check('the bpy probe ran', bool(got), (q.stderr or q.stdout or '')[-300:])
check(
    'four surfaces: the three glass looks and the water',
    sorted(got) == ['mat_glass', 'mat_glass clear', 'mat_glass panel', 'mat_water'],
    sorted(got),
)
for nm, want_rough, want_ior in (
    ('mat_glass', 0.02, 1.5),
    ('mat_glass panel', 0.04, 1.5),
    ('mat_glass clear', 0.02, 1.5),
    ('mat_water', 0.05, 1.33),
):
    g = got.get(nm) or {}
    check(
        f'{nm}: Transmission 1.0, IOR {want_ior}, Alpha 1.0, Roughness {want_rough}',
        g.get('transmission') == 1.0
        and g.get('ior') == want_ior
        and g.get('alpha') == 1.0
        and g.get('roughness') == want_rough,
        {k: g.get(k) for k in ('transmission', 'ior', 'alpha', 'roughness')},
    )
check(
    'the curtain wall pane is tinted blue-green (0.85, 0.93, 0.95)',
    (got.get('mat_glass panel') or {}).get('base')[:3] == [0.85, 0.93, 0.95],
    (got.get('mat_glass panel') or {}).get('base'),
)
check(
    'the entrance door glass is clear (0.96, 0.99, 1.0)',
    (got.get('mat_glass clear') or {}).get('base')[:3] == [0.96, 0.99, 1.0],
    (got.get('mat_glass clear') or {}).get('base'),
)
for nm in ('mat_glass', 'mat_glass panel', 'mat_glass clear'):
    g = got.get(nm) or {}
    check(
        f'{nm}: the shadow ray goes through a Transparent BSDF (Is Shadow Ray -> Mix)',
        g.get('shadow_mix') and g.get('transparent'),
        g,
    )
    check(f'{nm}: still a preset, no image textures', g.get('images') == 0, g.get('images'))
    check(
        f'{nm}: EEVEE refraction and transparent shadows are on',
        g.get('raytrace_refraction') is True and g.get('transparent_shadow') is True,
        g,
    )
wa = got.get('mat_water') or {}
check(
    'water: a Noise Texture through a Bump into Normal',
    wa.get('bump') and 'ShaderNodeTexNoise' in (wa.get('nodes') or []),
    wa.get('nodes'),
)
check('water: a Volume Absorption on the output', wa.get('volume'), wa.get('nodes'))
check(
    'the panes carry the EEVEE alpha the brief asked for (0.15 pane, 0.6 water)',
    (got.get('mat_glass panel') or {}).get('eevee_alpha') == 0.15 and wa.get('eevee_alpha') == 0.6,
    {k: (got.get(k) or {}).get('eevee_alpha') for k in got},
)
check(
    'tune_glass_for_eevee retunes exactly those four to BLENDED alpha',
    tuned == 4 and after.get('mat_glass panel') == [0.15, 'BLENDED'] and after.get('mat_water') == [0.6, 'BLENDED'],
    (tuned, after),
)

# ── 2. the picture: the live tower, old builder vs new ──────────────────────
print(
    '  -- the live tower, built twice (front elevation, Cycles %s samples)' % os.environ['ZYG_ARCH_HERO_SAMPLES'],
    flush=True,
)
new_blend, ni = build(DOC['objects'], 'new', BUILDER, 'tower new')
old_blend, oi = build(DOC['objects'], 'old', OLD_BUILDER, 'tower old')
# 2026-09-16: the NEW builder skips plan annotations (zone / gridline / opening — arch_blender_build.RENDER_SKIP_KINDS);
# the old builder, frozen in its .bak, still builds every record
_RENDERED = sum(
    1
    for o in DOC['objects']
    if isinstance(o, dict)
    and not o.get('hidden')
    and str(o.get('kind') or 'box') not in ('opening', 'zone', 'gridline')
)
check(
    'the new builder builds every rendered record (zones and gridlines are plan annotations), the old one all 983',
    ni.get('objects') == _RENDERED and oi.get('objects') == 983,
    (ni.get('objects'), _RENDERED, oi.get('objects')),
)
new_front = render(new_blend, 'front', 'new-front') if new_blend else ''
old_front = render(old_blend, 'front', 'old-front') if old_blend else ''
check('both front elevations rendered', bool(new_front and old_front), (new_front, old_front))

if new_front and old_front:
    w, _, Ln = pixels(new_front)
    _, _, Lo = pixels(old_front)
    # the brief's band: rows 40-60 %, columns 30-70 %
    h = len(Ln) // w
    band = [y * w + x for y in range(int(h * 0.40), int(h * 0.60)) for x in range(int(w * 0.30), int(w * 0.70))]
    bs, bo = stats(Ln, band), stats(Lo, band)
    line('band (new)', bs)
    line('band (old)', bo)
    check('the glass band is not a flat field (std-dev > 18)', bs['std'] > 18.0, bs['std'])
    check('the glass band is not milky white (mean < 200)', bs['mean'] < 200.0, bs['mean'])
    # everything the change touched: the curtain wall bands, and nothing else
    mask = changed(Lo, Ln, 10)
    check(
        'the change touched the glass and only the glass (5-15 % of the frame)',
        0.05 < len(mask) / float(len(Ln)) < 0.15,
        '%.2f%%' % (100.0 * len(mask) / len(Ln)),
    )
    gs, go = stats(Ln, mask), stats(Lo, mask)
    line('glass pixels (new)', gs, 'ripple %.3f' % ripple(Ln, mask, w))
    line('glass pixels (old)', go, 'ripple %.3f' % ripple(Lo, mask, w))
    check(
        'MILKY WHITE is gone: pixels brighter than 200 fall from %.1f%% to under 15%%' % go['hi200'],
        gs['hi200'] < 15.0 and go['hi200'] > 50.0,
        (go['hi200'], gs['hi200']),
    )
    check(
        'the flat field is gone: pixels within +-3 of the median fall from %.1f%% to under 25%%' % go['flat'],
        gs['flat'] < 25.0 and go['flat'] > 45.0,
        (go['flat'], gs['flat']),
    )
    check(
        'the glass carries more structure than the milky plate did (std-dev)',
        gs['std'] > go['std'],
        (go['std'], gs['std']),
    )

# ── 3. the roof pool, close up, old builder vs new ─────────────────────────
print('  -- the roof pool (o1315, 16 x 5.4 m at y 54.3), same camera on both builds', flush=True)
# a 35 mm camera on the deck south of the pool, aimed at the water surface
POOL_CAM = B._persp_cam((13.0, 58.0, 58.0), (13.0, 44.3, 54.32), 35.0)
new_pool = render(new_blend, 'eye', 'new-pool', POOL_CAM) if new_blend else ''
old_pool = render(old_blend, 'eye', 'old-pool', POOL_CAM) if old_blend else ''
check('both pool frames rendered', bool(new_pool and old_pool), (new_pool, old_pool))
if new_pool and old_pool:
    # 4x box downsample first: what is left is structure, not Cycles noise
    w4, po, Lo4 = pixels(old_pool, 4)
    _, _, Ln4 = pixels(new_pool, 4)
    blue = [i for i, (r, g, b) in enumerate(po) if b > r + 18 and b > g + 6 and b > 30]
    chg = set(changed(Lo4, Ln4, 8))
    mask = [i for i in blue if i in chg]
    check('the flat blue plate is found in the old frame and the change touched it', len(mask) > 2000, len(mask))
    if len(mask) > 2000:
        rn, ro = ripple(Ln4, mask, w4), ripple(Lo4, mask, w4)
        sn, so = stats(Ln4, mask), stats(Lo4, mask)
        line('water (new)', sn, 'ripple %.3f' % rn)
        line('water (old)', so, 'ripple %.3f' % ro)
        check(
            'the water ripples: neighbour difference %.3f -> %.3f (at least 1.5x)' % (ro, rn),
            rn > ro * 1.5 and rn > 0.9,
            (ro, rn),
        )
        check(
            'the water carries more structure than the flat plate (std-dev %.2f -> %.2f)' % (so['std'], sn['std']),
            sn['std'] > so['std'] + 4.0,
            (so['std'], sn['std']),
        )
        check(
            'the flat plate is gone (pixels within +-3 of the median %.1f%% -> %.1f%%)' % (so['flat'], sn['flat']),
            sn['flat'] < so['flat'],
            (so['flat'], sn['flat']),
        )
        print(
            '    specular pixels (luminance > 220): old %.2f%%, new %.2f%% — see not_done' % (so['hi220'], sn['hi220']),
            flush=True,
        )

# ── 4. the canopy shadow: glass against concrete, same geometry ────────────
print('  -- a 12 x 12 m canopy 5 m over a concrete pad, glass against concrete', flush=True)


def canopy_scene(mat):
    return [
        {'id': 'o1', 'kind': 'pad', 'p': {'w': 60, 'd': 60, 't': 0.2}, 'x': 0, 'y': 0, 'z': 0, 'mat': 'mat_concrete'},
        {
            'id': 'o2',
            'kind': 'canopy',
            'p': {'w': 12, 'd': 12, 't': 0.12, 'h_drop': 0},
            'x': 0,
            'y': 5,
            'z': 0,
            'mat': mat,
        },
    ]


gb, _ = build(canopy_scene('mat_glass'), 'can-glass', BUILDER, 'canopy glass')
cb, _ = build(canopy_scene('mat_concrete'), 'can-conc', BUILDER, 'canopy concrete')
gp = render(gb, 'top', 'can-glass-top') if gb else ''
cp = render(cb, 'top', 'can-conc-top') if cb else ''
check('both canopy frames rendered', bool(gp and cp), (gp, cp))
if gp and cp:
    w, _, Lg = pixels(gp)
    _, _, Lc = pixels(cp)
    mask = changed(Lg, Lc, 6)
    med = statistics.median(Lc)
    shadow = [i for i in mask if Lc[i] < med - 12]  # dark under the CONCRETE slab = its shadow
    slab = [i for i in mask if Lc[i] >= med - 12]
    check('the concrete canopy throws a shadow the frame can see', len(shadow) > 2000, len(shadow))
    if len(shadow) > 2000:
        mg, mc = statistics.fmean([Lg[i] for i in shadow]), statistics.fmean([Lc[i] for i in shadow])
        print(
            '    the ground under the canopy: concrete %.2f -> glass %.2f (+%.2f), '
            'the slab itself %.2f vs %.2f, shadow %d px'
            % (
                mc,
                mg,
                mg - mc,
                statistics.fmean([Lc[i] for i in slab]),
                statistics.fmean([Lg[i] for i in slab]),
                len(shadow),
            ),
            flush=True,
        )
        check(
            'what stands under a GLASS canopy is lit: more than 15 luminance levels lighter than under a concrete one',
            mg > mc + 15.0,
            (mc, mg),
        )

# ── 5. the two pictures the creator asked to look at ───────────────────────
print('  -- the hand-over frames (hero_render, Cycles %s samples)' % os.environ['ZYG_ARCH_HERO_SAMPLES'], flush=True)
hero = []
try:
    hero = B.hero_render(d, 'glasswater', views=('approach', 'aerial'), width=W, height=H)
except Exception as e:  # noqa: BLE001
    check('hero_render rendered the approach and the aerial', False, repr(e))
check(
    'hero_render rendered the approach and the aerial',
    len(hero) == 2 and all(os.path.exists(h['png']) for h in hero),
    [(h['title'], h['png'], h['seconds']) for h in hero],
)
for h in hero:
    print('    %-9s %s (%.1fs, %d samples)' % (h['title'], h['png'], h['seconds'], h.get('samples') or 0), flush=True)
    w, _, L = pixels(h['png'])
    hh = len(L) // w
    band = [y * w + x for y in range(int(hh * 0.40), int(hh * 0.60)) for x in range(int(w * 0.30), int(w * 0.70))]
    s = stats(L, band)
    line('  band ' + h['title'], s)
    if h['title'] == 'approach':
        check(
            'the approach frame: the glass band is not a flat milky field (std > 18, mean < 200)',
            s['std'] > 18.0 and s['mean'] < 200.0,
            s,
        )

finish()
