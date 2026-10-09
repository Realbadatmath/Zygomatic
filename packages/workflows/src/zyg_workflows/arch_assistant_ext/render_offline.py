# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_offline — the assistant half of the Render family's offline icons.

No kinds and no geometry: it declares the four icons arch_ext/render_offline.js
wired (r_ray, r_denoise, r_pano, r_vr) as pressable, says what arguments each
takes, and gives the model a server-side twin of the ray trace
(`ray_trace_still`) so it can get a picture back in a request that never touches
the tab. The twin renders through the very same route the icon calls
(arch_server_ext/render_offline.render), so there is one arithmetic, not two.

Stdlib only.
"""

import base64
import importlib.util
import os

from zyg_workflows.arch_assistant import Drawing, _num  # noqa: F401

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KINDS: dict = {}
OPENINGS: list = []
BUTTONS = ['r_ray', 'r_denoise', 'r_pano', 'r_vr']

PROMPT = (
    'Offline and immersive rendering: press_button("r_ray", {"samples":64, "width":1280, "height":720, '
    '"view":"current"}) ray traces the current view in Blender Cycles and downloads a PNG — real reflections and '
    'soft shadows, 10-60 s, so ask once and only when the look of a surface is the question. "r_denoise" is its '
    'denoiser flag, "r_pano" {"size":2048} renders a 360 degree panorama, "r_vr" a stereo pair for WebXR. The '
    'tool ray_trace_still hands the image to you instead. explain("ray trace") has the detail.'
)


def _route():
    path = os.path.join(HERE, 'arch_server_ext', 'render_offline.py')
    spec = importlib.util.spec_from_file_location('arch_server_ext.render_offline', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def t_ray_trace_still(d: Drawing, a, view='iso', samples=64, width=960, height=600, denoise=True, name=''):
    """The server-side twin of r_ray: same route, same Blender, a picture back."""
    if not d.objs:
        return 'refused: the drawing is empty — draw something before ray tracing it'
    v = str(view or 'iso').lower()
    if v not in ('iso', 'top', 'front', 'right', 'back', 'left', 'bottom'):
        return 'refused: view must be one of iso, top, front, right, back, left, bottom'
    w, h = int(_num(width, 960) or 960), int(_num(height, 600) or 600)
    if not (160 <= w <= 3840 and 120 <= h <= 2160):
        return 'refused: width must be 160..3840 and height 120..2160 pixels'
    s = int(_num(samples, 64) or 64)
    if not (1 <= s <= 4096):
        return 'refused: samples must be 1..4096'
    doc = d.to_doc()
    # an ORTHO camera aimed down the named axis, framed on the whole drawing: the
    # tab's own arView directions, in studio coordinates.
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    for o in doc.get('objects') or []:
        for i, k in enumerate(('x', 'y', 'z')):
            c = _num(o.get(k), 0.0)
            lo[i] = min(lo[i], c)
            hi[i] = max(hi[i], c)
    if lo[0] > 1e8:
        lo, hi = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    ctr = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
    span = max(6.0, max(hi[i] - lo[i] for i in range(3)) + 6.0)
    dirs = {
        'iso': (1.0, 0.85, 1.0),
        'top': (0.0, 1.0, 0.001),
        'front': (0.0, 0.25, 1.0),
        'right': (1.0, 0.25, 0.0),
        'back': (0.0, 0.25, -1.0),
        'left': (-1.0, 0.25, 0.0),
        'bottom': (0.0, -1.0, 0.001),
    }[v]
    ln = max(1e-6, sum(c * c for c in dirs) ** 0.5)
    pos = [ctr[i] + dirs[i] / ln * span * 2.5 for i in range(3)]
    cam = {'p': pos, 't': ctr, 'fov': 45, 'ortho': 1, 'top': span * 0.75}
    out = _route().render(
        {'doc': doc, 'camera': cam, 'samples': s, 'width': w, 'height': h, 'denoise': 1 if denoise else 0}, 'POST'
    )
    if isinstance(out, dict):
        return 'refused: ' + str(out.get('error') or 'the ray trace failed')
    data = out[0]
    url = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    d.images.append({'title': name or ('ray trace · %s' % v), 'data_url': url})
    return (
        'ray traced %d objects in Blender Cycles: %s view, %dx%d, %d samples, denoise %s (%d KB).'
        % (len(d.objs), v, w, h, s, 'on' if denoise else 'off', len(data) // 1024),
        url,
    )


TOOLS = [
    (
        {
            'name': 'ray_trace_still',
            'description': (
                'A ray-traced picture of the drawing: Blender Cycles with real reflections, refraction, '
                'soft shadows and a denoiser. Slower than blender_render (10-60 s) — use it when the '
                'question is how a material or a light actually looks, not where something is.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'view': {'type': 'string', 'enum': ['iso', 'top', 'front', 'right', 'back', 'left', 'bottom']},
                    'samples': {'type': 'integer', 'description': '1..4096; 64 is plenty with the denoiser on'},
                    'width': {'type': 'integer'},
                    'height': {'type': 'integer'},
                    'denoise': {'type': 'boolean'},
                    'name': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_ray_trace_still,
    ),
]

EXAMPLES = [
    {
        'ask': 'ray trace this view properly',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'r_ray', 'args': {'samples': 64, 'width': 1280, 'height': 720}}}
        ],
    },
    {
        'ask': 'show me how the glass really looks',
        'calls': [{'tool': 'ray_trace_still', 'args': {'view': 'iso', 'samples': 96}}],
    },
    {
        'ask': 'turn the denoiser off, I want to see the raw samples',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_denoise', 'args': {'on': False}}}],
    },
    {
        'ask': 'give me a 360 panorama of the courtyard',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_pano', 'args': {'size': 2048, 'eye': 1.65}}}],
    },
    {
        'ask': 'let me look at it in stereo',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_vr', 'args': {'on': True}}}],
    },
    {
        'ask': 'ray trace the front elevation, big and clean',
        'calls': [{'tool': 'ray_trace_still', 'args': {'view': 'front', 'samples': 256, 'width': 1600, 'height': 900}}],
    },
    {
        'ask': 'a denoised top-down ray trace called plan_raytrace',
        'calls': [{'tool': 'ray_trace_still', 'args': {'view': 'top', 'denoise': True, 'name': 'plan_raytrace'}}],
    },
]
