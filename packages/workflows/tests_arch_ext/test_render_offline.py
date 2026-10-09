# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_render_offline.py — proves the Render family's four
offline/immersive icons are real: r_ray (Blender Cycles on the server),
r_denoise (the flag it sends, stored in the document), r_pano (a 2:1
equirectangular PNG out of six cube faces) and r_vr (a side-by-side stereo pair
that hands AR_EXT.render back exactly as it found it).

Three browser_eval calls and one real Blender run (320x200 at 8 samples, about
10 s on the GPU) — the whole file stays well under the board's 180 s.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, server_ext  # noqa: E402

IDS = ['r_ray', 'r_denoise', 'r_pano', 'r_vr']
DOC = {
    'objects': [
        {'id': 'o1', 'kind': 'slab', 'p': {'w': 8, 'd': 6, 't': 0.2}, 'x': 0, 'y': 0, 'z': 0, 'mat': 'mat_concrete'},
        {
            'id': 'o2',
            'kind': 'wall',
            'p': {'len': 8, 'h': 2.7, 't': 0.24},
            'x': 0,
            'y': 0.2,
            'z': -3,
            'mat': 'mat_brick',
        },
        {'id': 'o3', 'kind': 'box', 'p': {'w': 1, 'd': 1, 'h': 1}, 'x': 2, 'y': 0.2, 'z': 0, 'mat': 'mat_timber'},
    ]
}


def png_size(data):
    """(width, height) from the IHDR of a PNG, or (0, 0)."""
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        return (0, 0)
    return struct.unpack('>II', data[16:24])


# ── 1. every icon of ours stopped being a placeholder ────────────────────────
st = icon_state(IDS)
check(
    'all four Render icons exist and no longer carry the placeholder mark (stub / dashed / [placeholder] tip)',
    all(
        st[i].get('exists') and not st[i].get('stub') and not st[i].get('dashed') and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)

# ── 2. the tab side: pano pixels, the stereo switch, the denoise flag ────────
r = browser_eval(
    """() => {
  const out = {};
  /* r_pano: six cube faces stitched into a 2:1 equirect PNG, as a Promise of a blob */
  return AR_EXT.tools.r_pano.act({size: 256, eye: 1.65}).then(blob => {
    out.pano_type = blob && blob.type;
    out.pano_bytes = blob ? blob.size : 0;
    out.pano_sheet = !!document.querySelector('#ar-sheet img');
    return createImageBitmap(blob);
  }).then(bm => {
    out.pano_w = bm.width; out.pano_h = bm.height;

    /* r_vr: a marker render function must come back byte-identical after off */
    const marker = function markerRender(){ AR.renderer.render(AR.scene, AR.cam); };
    AR_EXT.render = marker;
    const onres = AR_EXT.tools.r_vr.act({on: true});
    out.vr_on = !!AR_EXT.tools.r_vr.on();
    out.vr_act_returned = onres;
    out.vr_is_fn = typeof AR_EXT.render === 'function';
    out.vr_replaced = AR_EXT.render !== marker;
    arRender();                                     /* the frame really goes through our function */
    out.vr_frame = AR_EXT.tools.r_vr.state().last;
    const cw = AR.renderer.getSize(new THREE.Vector2()).x;
    out.vr_canvas_w = cw;
    out.vr_still_on = AR_EXT.tools.r_vr.act({on: true}) === true;   /* idempotent: still on */

    AR_EXT.tools.r_vr.act({on: false});
    out.vr_off = !AR_EXT.tools.r_vr.on();
    out.vr_restored = AR_EXT.render === marker;
    AR_EXT.render = null;

    /* r_denoise: a document-level flag, default on, toggled behind arPush */
    out.dn_default = AR_EXT.tools.r_denoise.on();
    const undo0 = AR.undo.length;
    AR_EXT.tools.r_denoise.act({on: false});
    out.dn_after_off = AR_EXT.tools.r_denoise.on();
    out.dn_ext = AR.doc.ext.render_offline.denoise;
    out.dn_in_doc = arDocOut().ext.render_offline.denoise;
    out.dn_pushed = AR.undo.length > undo0;
    AR_EXT.tools.r_denoise.act();                                  /* no args: plain toggle */
    out.dn_toggled_back = AR_EXT.tools.r_denoise.on();

    /* r_ray must build the camera payload the server wants (studio coords) */
    out.assist = [!!AR_EXT.tools.r_ray.assist, !!AR_EXT.tools.r_denoise.assist,
                  !!AR_EXT.tools.r_pano.assist, !!AR_EXT.tools.r_vr.assist];
    out.togs = [!!AR_EXT.tools.r_denoise.tog, !!AR_EXT.tools.r_vr.tog];
    out.ray_is_fn = typeof AR_EXT.tools.r_ray.act === 'function';
    return out;
  });
}""",
    doc=DOC,
    timeout_s=180,
)
v = r['value']
check('r_pano returns a Promise of a PNG blob', v['pano_type'] == 'image/png' and v['pano_bytes'] > 200, v)
check(
    'the panorama is a 2:1 equirectangular image at the size asked for (256 x 128)',
    v['pano_w'] == 256 and v['pano_h'] == 128,
    v,
)
check('the panorama also opens in a sheet the user can look at', v['pano_sheet'], v)
check(
    'r_vr on latches, installs a render function of its own, and stays on when pressed on again',
    v['vr_on'] and v['vr_is_fn'] and v['vr_replaced'] and v['vr_still_on'],
    v,
)
f = v['vr_frame'] or {}
check(
    'the frame goes through the stereo function and draws two eyes 64 mm apart into the two halves of the canvas',
    abs(f.get('sep', 0) - 0.064) < 1e-6
    and f.get('left') != f.get('right')
    and f.get('halves') == [[0, 0, f.get('w'), f.get('h')], [f.get('w'), 0, v['vr_canvas_w'] - f.get('w'), f.get('h')]]
    and abs(f.get('w', 0) * 2 - v['vr_canvas_w']) <= 1,
    {'frame': f, 'canvas_w': v['vr_canvas_w']},
)
check('r_vr off restores the PREVIOUS render function, by identity, not null', v['vr_off'] and v['vr_restored'], v)
check(
    'r_denoise defaults on, toggles the document flag, and toggles back',
    v['dn_default'] is True and v['dn_after_off'] is False and v['dn_ext'] == 0 and v['dn_toggled_back'] is True,
    v,
)
check('the denoise flag lives in doc.ext.render_offline and goes out with the document', v['dn_in_doc'] == 0, v)
check('the document edit went behind arPush()', v['dn_pushed'], v)
check(
    'all four icons are assist-pressable and the two switches are marked tog',
    v['assist'] == [True, True, True, True] and v['togs'] == [True, True],
    v,
)
check('no page errors while the four icons ran', not r['errors'], r['errors'])

# ── 3. the server side: one real Blender Cycles run ──────────────────────────
i = server_ext('render_offline', 'info', {})
check(
    'the server extension knows where Blender is and finds its render script',
    i.get('ok') and i.get('present') and i.get('script'),
    i,
)

cam = {'p': [10, 7, 10], 't': [0, 1, 0], 'fov': 50, 'ortho': 0, 'top': 8}
out = server_ext(
    'render_offline',
    'render',
    {
        'doc': {'name': 'ray probe', 'objects': DOC['objects']},
        'camera': cam,
        'samples': 8,
        'width': 320,
        'height': 200,
        'denoise': 1,
    },
    timeout_s=150,
)
data = out.get('bytes') if isinstance(out, dict) else b''
check(
    "r_ray's route hands back a real PNG from Blender Cycles (>3 KB, PNG signature)",
    isinstance(data, bytes) and data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) > 3072,
    {'len': len(data or b''), 'head': (data or b'')[:8], 'mime': out.get('mime'), 'err': out.get('error')},
)
check(
    'the ray trace is the size that was asked for, and comes back as raytrace.png',
    png_size(data) == (320, 200) and out.get('filename') == 'raytrace.png' and out.get('mime') == 'image/png',
    {'size': png_size(data), 'filename': out.get('filename'), 'mime': out.get('mime')},
)
bad = server_ext('render_offline', 'render', {'doc': {'objects': []}})
check('an empty drawing is refused instead of launching Blender', bad.get('code') == 400, bad)

# ── 3b. r_ray from the ICON: the tab really reaches Blender and gets a picture ─
r3 = browser_eval(
    """() => {
  const out = {};
  return AR_EXT.tools.r_ray.act({samples: 4, width: 160, height: 100, denoise: 1, view: 'current'})
    .then(blob => {
      out.type = blob && blob.type; out.bytes = blob ? blob.size : 0;
      out.sheet = !!document.querySelector('#ar-sheet img');
      return createImageBitmap(blob);
    }).then(bm => { out.w = bm.width; out.h = bm.height; return out; });
}""",
    doc=DOC,
    timeout_s=180,
)
v3 = r3['value']
check(
    'pressing r_ray in the tab comes back with a Cycles PNG of the current view and opens it in a sheet',
    v3['type'] == 'image/png' and v3['bytes'] > 1024 and v3['w'] == 160 and v3['h'] == 100 and v3['sheet'],
    {'value': v3, 'errors': r3['errors']},
)

# ── 4. the assistant side ────────────────────────────────────────────────────
for icon in IDS:
    txt, d = assistant('press_button', {'id': icon, 'args': {'on': True}})
    check(
        'the assistant may press %s' % icon,
        txt.startswith('pressed') and d.ui[-1]['args']['id'] == icon and d.ui[-1]['args'].get('args') == {'on': True},
        txt,
    )

txt, d = assistant('ray_trace_still', {}, doc={'objects': []})
check('the server-side twin refuses an empty drawing without touching Blender', txt.startswith('refused'), txt)
txt, d = assistant('ray_trace_still', {'view': 'sideways'}, doc=DOC)
check('the twin refuses a view the studio does not have', txt.startswith('refused'), txt)
finish()
