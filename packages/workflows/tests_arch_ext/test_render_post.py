# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_render_post.py — proves the six Render post-processing
icons (r_preset, r_ao, r_bloom, r_dof, r_aa, r_res) are real.

Three browser passes only (icon_state is one of them), because every one opens
headless Chrome on SwiftShader and the composer is a software rasteriser there:
the effect pass keeps the drawing buffer tiny (r_res 0.25) and the preset pass
never renders a frame at print resolution.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['r_preset', 'r_ao', 'r_bloom', 'r_dof', 'r_aa', 'r_res']

# ── 1. the icons stopped being placeholders ──────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is in the dock and no longer a placeholder (stub/dashed/[placeholder] all gone)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )
check(
    'all six sit in the Render section of the dock',
    all((st.get(i) or {}).get('section') == 'Render' and (st.get(i) or {}).get('bar') == 'dock' for i in IDS),
    {i: (st.get(i) or {}).get('section') for i in IDS},
)

# ── 2. the effects: composer chain, a real frame, the focal plane ────────────
r = browser_eval("""async () => {
  await (AR_EXT.tools.r_ao._ready || Promise.resolve());
  const out = {}, RP = window.arRenderPost;
  arTool('r_res', {scale: 0.25});                 // SwiftShader: keep the buffer tiny
  out.render_null_before = AR_EXT.render === null;

  const slab = arNewObj('slab', {w: 8, d: 8, t: 0.4}, 0, 0, 0);
  arSelect([slab.id]); arZoomFit(true);

  arTool('r_ao', {on: true});
  out.ao_latched = !!AR_EXT.tools.r_ao.on();
  out.render_is_fn = typeof AR_EXT.render === 'function';
  out.has_ssao = RP.composer.passes.some(p => p instanceof THREE.SSAOPass);
  out.has_renderpass = RP.composer.passes.some(p => p instanceof THREE.RenderPass);
  out.ssao_radius = RP.passes.ssao.kernelRadius;
  out.ssao_min = RP.passes.ssao.minDistance;
  out.ssao_max = RP.passes.ssao.maxDistance;

  const shot = arShot(320);
  out.shot_len = (shot || '').length;
  out.shot_is_jpeg = /^data:image\\/jpeg/.test(shot || '');
  arRender();
  const gl = AR.renderer.getContext(), cv = AR.renderer.domElement, px = new Uint8Array(4);
  gl.readPixels(Math.floor(cv.width / 2), Math.floor(cv.height / 2), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
  out.centre = [px[0], px[1], px[2], px[3]];
  out.canvas = [cv.width, cv.height];

  arTool('r_aa', {on: true});
  out.has_smaa = RP.composer.passes.some(p => p instanceof THREE.SMAAPass);
  out.aa_latched = !!AR_EXT.tools.r_aa.on();

  arTool('r_dof', {on: true});
  arRender();
  out.has_bokeh = RP.composer.passes.some(p => p instanceof THREE.BokehPass);
  out.focus = RP.passes.bokeh.uniforms.focus.value;
  out.aperture = RP.passes.bokeh.uniforms.aperture.value;
  out.maxblur = RP.passes.bokeh.uniforms.maxblur.value;
  out.dist = AR.cam.position.distanceTo(arBounds(true).c);
  out.cam_follows = RP.passes.render.camera === AR.cam;

  arTool('r_bloom', {on: true});
  out.has_bloom = RP.composer.passes.some(p => p instanceof THREE.UnrealBloomPass);
  out.bloom_params = [RP.passes.bloom.strength, RP.passes.bloom.threshold, RP.passes.bloom.radius];
  out.ext = JSON.parse(JSON.stringify(AR.doc.ext.render_post));
  out.doc_out_ext = arDocOut().ext.render_post;

  arTool('r_ao', {on: false}); arTool('r_aa', {on: false});
  arTool('r_dof', {on: false}); arTool('r_bloom', {on: false});
  out.render_null_after = AR_EXT.render === null;
  out.all_off = [AR_EXT.tools.r_ao.on(), AR_EXT.tools.r_bloom.on(),
                 AR_EXT.tools.r_dof.on(), AR_EXT.tools.r_aa.on()];
  return out;
}""")
v = r['value'] or {}
check(
    'with nothing on the studio keeps its plain render path (AR_EXT.render null)',
    v.get('render_null_before') is True,
    v,
)
check(
    'r_ao ON latches and hands the frame to the composer (AR_EXT.render is a function)',
    v.get('ao_latched') and v.get('render_is_fn'),
    v,
)
check(
    'r_ao puts a real SSAOPass behind a RenderPass, tuned in scene units (0.6 m / .005 / .1)',
    v.get('has_ssao')
    and v.get('has_renderpass')
    and abs((v.get('ssao_radius') or 0) - 0.6) < 1e-6
    and abs((v.get('ssao_min') or 0) - 0.005) < 1e-9
    and abs((v.get('ssao_max') or 0) - 0.1) < 1e-9,
    v,
)
check(
    'arShot still returns a jpeg data-url with the composer active',
    v.get('shot_is_jpeg') and (v.get('shot_len') or 0) > 2000,
    {'len': v.get('shot_len')},
)
check(
    'the composited frame is not black — readPixels at the canvas centre',
    sum((v.get('centre') or [0, 0, 0, 0])[:3]) > 0,
    {'centre': v.get('centre'), 'canvas': v.get('canvas')},
)
check('r_aa ON adds an SMAAPass', v.get('has_smaa') and v.get('aa_latched'), v)
check(
    'r_dof ON adds a BokehPass (aperture .00015, maxblur .01)',
    v.get('has_bokeh')
    and abs((v.get('aperture') or 0) - 0.00015) < 1e-9
    and abs((v.get('maxblur') or 0) - 0.01) < 1e-9,
    v,
)
check(
    'the bokeh focus follows the distance from the camera to the selection',
    v.get('dist') and abs((v.get('focus') or 0) - v['dist']) < max(0.5, 0.1 * v['dist']),
    {'focus': v.get('focus'), 'dist': v.get('dist')},
)
check('the RenderPass camera is the live AR.cam (the ortho toggle swaps it)', v.get('cam_follows') is True, v)
check(
    'r_bloom ON adds an UnrealBloomPass (strength .35, threshold .9, radius .4)',
    v.get('has_bloom') and v.get('bloom_params') == [0.35, 0.9, 0.4],
    v,
)
check(
    'the switches persist in AR.doc.ext.render_post and travel with the drawing',
    (v.get('ext') or {}).get('ao') is True
    and (v.get('ext') or {}).get('dof') is True
    and (v.get('doc_out_ext') or {}).get('bloom') is True,
    v.get('ext'),
)
check(
    'turning every effect off gives the plain render path back (AR_EXT.render null)',
    v.get('render_null_after') is True and v.get('all_off') == [False, False, False, False],
    v,
)
check('no page errors while the passes loaded and ran', not r['errors'], r['errors'])

# ── 3. resolution and presets (no frame is rendered at print size) ───────────
r2 = browser_eval("""async () => {
  await (AR_EXT.tools.r_ao._ready || Promise.resolve());
  const out = {}, cv = AR.renderer.domElement;
  arTool('r_res', {scale: 1});
  out.w1 = cv.width; out.h1 = cv.height;
  arTool('r_res', {scale: 2});
  out.w2 = cv.width; out.h2 = cv.height;
  out.res_toast = document.getElementById('ar-toast').innerHTML;
  out.res_state = AR.doc.ext.render_post.scale;
  arTool('r_res', {scale: 0.5});
  out.w3 = cv.width;
  arTool('r_res', {scale: 1});

  arTool('r_preset', {preset: 'print'});
  out.print = Object.assign({}, AR.doc.ext.render_post,
    {shadows: AR.shadows, shadowRes: AR.shadowRes, canvasW: cv.width});
  out.print_latched = !!AR_EXT.tools.r_preset.on();

  arTool('r_preset', {preset: 'presentation'});
  out.pres = Object.assign({}, AR.doc.ext.render_post, {shadows: AR.shadows, shadowRes: AR.shadowRes});

  arTool('r_preset', {preset: 'draft'});
  out.draft = Object.assign({}, AR.doc.ext.render_post, {shadows: AR.shadows, canvasW: cv.width});
  out.draft_render_null = AR_EXT.render === null;

  arTool('r_preset');                       // no args = cycle on to the next preset
  out.cycled = AR.doc.ext.render_post.preset;
  arTool('r_preset', {preset: 'draft'});
  arTool('r_ao', {on: true});               // a hand toggle drops out of the preset
  out.custom = AR.doc.ext.render_post.preset;
  out.custom_unlatched = !!AR_EXT.tools.r_preset.on();
  arTool('r_ao', {on: false});
  arTool('r_res', {scale: 0.25});           // leave the tab cheap for the teardown frame
  return out;
}""")
w = r2['value'] or {}
w1 = w.get('w1') or 0
# the studio's stage is laid out at a browser zoom, so clientWidth carries half a
# pixel: allow the rounding, not the scale (1 px of slack per doubling).
check(
    'r_res {scale:2} doubles the drawing buffer, {scale:0.5} halves it',
    w1 > 0
    and abs((w.get('w2') or 0) - 2 * w1) <= 2
    and abs((w.get('h2') or 0) - 2 * (w.get('h1') or 0)) <= 2
    and abs((w.get('w3') or 0) - math.floor(w1 * 0.5)) <= 2,
    {k: w.get(k) for k in ('w1', 'h1', 'w2', 'h2', 'w3')},
)
check(
    'r_res says the resulting canvas size out loud and stores the scale',
    'Output resolution' in (w.get('res_toast') or '')
    and str(w.get('w2')) in (w.get('res_toast') or '')
    and w.get('res_state') == 2,
    w.get('res_toast'),
)
p = w.get('print') or {}
check(
    "r_preset 'print' = occlusion + anti-alias, no bloom/DOF, x2 resolution, 4096 shadows",
    p.get('ao') is True
    and p.get('aa') is True
    and p.get('bloom') is False
    and p.get('dof') is False
    and p.get('scale') == 2
    and p.get('shadows') is True
    and p.get('shadowRes') == 4096
    and abs((p.get('canvasW') or 0) - 2 * w1) <= 2
    and w.get('print_latched') is True,
    p,
)
pr = w.get('pres') or {}
check(
    "r_preset 'presentation' = occlusion + anti-alias + low bloom, x1, 2048 shadows",
    pr.get('ao') is True
    and pr.get('aa') is True
    and pr.get('bloom') is True
    and pr.get('dof') is False
    and pr.get('bloom_strength') == 0.2
    and pr.get('scale') == 1
    and pr.get('shadows') is True
    and pr.get('shadowRes') == 2048,
    pr,
)
dr = w.get('draft') or {}
check(
    "r_preset 'draft' clears every effect, drops to 0.75x and turns the shadows off",
    dr.get('ao') is False
    and dr.get('bloom') is False
    and dr.get('dof') is False
    and dr.get('aa') is False
    and dr.get('scale') == 0.75
    and dr.get('shadows') is False
    and w.get('draft_render_null') is True
    and abs((dr.get('canvasW') or 0) - math.floor(0.75 * w1)) <= 2,
    dr,
)
check('pressing r_preset with no args cycles on to the next preset', w.get('cycled') == 'presentation', w.get('cycled'))
check(
    'a hand toggle drops the preset to custom and unlatches the preset icon',
    w.get('custom') == 'custom' and w.get('custom_unlatched') is False,
    w,
)
check('no page errors while the presets ran', not r2['errors'], r2['errors'])

# ── 4. the assistant may press all six ───────────────────────────────────────
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
check(
    'every icon is declared pressable to the assistant (EXT_BUTTONS)',
    all(i in A.EXT_BUTTONS for i in IDS),
    sorted(i for i in IDS if i not in A.EXT_BUTTONS),
)
txt, d = assistant('press_button', {'id': 'r_preset', 'args': {'preset': 'presentation'}})
check(
    'press_button("r_preset", {preset}) reaches the tab with its args',
    txt.startswith('pressed')
    and d.ui[-1]['args']['id'] == 'r_preset'
    and d.ui[-1]['args']['args'] == {'preset': 'presentation'},
    (txt, d.ui[-1:]),
)
txt2, d2 = assistant('press_button', {'id': 'r_res', 'args': {'scale': 2}})
check(
    'press_button("r_res", {scale}) reaches the tab with its args',
    txt2.startswith('pressed') and d2.ui[-1]['args']['args'] == {'scale': 2},
    (txt2, d2.ui[-1:]),
)
txt3, d3 = assistant('press_button', {'id': 'r_ao', 'args': {'on': True}})
check(
    'press_button("r_ao", {on}) reaches the tab with its args',
    txt3.startswith('pressed') and d3.ui[-1]['args']['args'] == {'on': True},
    (txt3, d3.ui[-1:]),
)
import zyg_workflows.arch_assistant_ext.render_post as RPX  # noqa: E402

check(
    'the family prompt names every icon and the arguments it takes',
    all(i in RPX.PROMPT for i in IDS) and 'preset' in RPX.PROMPT and 'scale' in RPX.PROMPT and len(RPX.EXAMPLES) >= 5,
    RPX.PROMPT[:120],
)

finish()
