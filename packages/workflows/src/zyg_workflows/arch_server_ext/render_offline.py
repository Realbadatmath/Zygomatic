# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_offline — the server half of the Render family's offline icons.

One route, `render`: the browser hands over the whole document plus its camera,
and a headless Blender Cycles renders one PNG and hands the bytes back as a
download. Everything the browser cannot do (a file on disk, a subprocess, a
denoiser) happens here; r_pano and r_vr are pure WebGL and never reach this file.

    POST /inspect/api/architecture/ext/render_offline/render
    {"doc": {...}, "camera": {"p":[x,y,z], "t":[x,y,z], "fov":50, "ortho":0, "top":10},
     "samples": 64, "width": 1280, "height": 720, "denoise": 1}
    -> (png bytes, 'image/png', 'raytrace.png')

Blender runs are SERIALISED with the same advisory file lock the family tests
use (arch_ext_harness._BlenderLock): two headless Blenders at once under the
board's load crashed the Bonsai import with SIGBUS.

Licences: stdlib only; Blender (GPL) is a subprocess, never imported.
"""

import json
import os
import re
import subprocess
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows import arch_blend_store as BSTORE  # noqa: E402  (retention for the -ray builds)
import logging as _zyg_logging

from zyg_workflows.paths import ZYG_TMP_DIR, tmp_dir  # noqa: E402  the sys.path line above must run first

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLEND_DIR = os.path.join(HERE, 'data', 'architecture', 'blender')
SCRIPT = os.path.join(HERE, 'arch_server_ext', 'render_offline_blender.py')
BLENDER = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')

TIMEOUT_S = 600
MAX_SAMPLES = 4096
MAX_PIXELS = 3840 * 2160


class _BlenderLock:
    """Blender runs are SERIALISED across processes — copied verbatim from
    arch_ext_harness._BlenderLock so the tab, the tests and this route all queue
    behind one lock instead of three."""

    # Every holder of this lock derives the path the same way, so they still meet in one file;
    # tmp_dir() creates the directory owner-only instead of the old world-writable /tmp path.
    PATH = str(ZYG_TMP_DIR / 'arch_ext_blender.lock')

    def __enter__(self):
        import fcntl

        tmp_dir()
        self.fh = open(self.PATH, 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        import fcntl

        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '-', str(name or 'drawing').lower()).strip('-') or 'drawing'


def _int(v, d, lo, hi):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = int(d)
    return max(lo, min(hi, n))


def _last_json(out):
    for line in (out or '').splitlines()[::-1]:
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('non-JSON line skipped while scanning the render log: %s', _exc)
                continue
    return {}


def render(payload, method):
    doc = payload.get('doc') if isinstance(payload.get('doc'), dict) else None
    if not doc or not isinstance(doc.get('objects'), list) or not doc['objects']:
        return {'error': 'nothing to render — the drawing is empty', 'code': 400}
    if not os.path.exists(BLENDER):
        return {'error': 'Blender not found at %s (set BLENDER_BIN)' % BLENDER, 'code': 500}
    if not os.path.exists(SCRIPT):
        return {'error': 'render_offline_blender.py is missing', 'code': 500}

    w = _int(payload.get('width'), 1280, 16, 3840)
    h = _int(payload.get('height'), 720, 16, 2160)
    if w * h > MAX_PIXELS:
        return {'error': 'refused: %dx%d is more than %d pixels' % (w, h, MAX_PIXELS), 'code': 400}
    samples = _int(payload.get('samples'), 64, 1, MAX_SAMPLES)
    denoise = 1 if payload.get('denoise', 1) else 0
    cam = payload.get('camera') if isinstance(payload.get('camera'), dict) else {}

    os.makedirs(BLEND_DIR, exist_ok=True)
    base = os.path.join(BLEND_DIR, '%s-%s-ray' % (_slug(doc.get('name')), time.strftime('%Y%m%d-%H%M%S')))
    src, png, blend = base + '.json', base + '.png', base + '.blend'
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)

    cmd = [
        BLENDER,
        '-b',
        '--python',
        SCRIPT,
        '--',
        '--in',
        src,
        '--out',
        png,
        '--blend',
        blend,
        '--samples',
        str(samples),
        '--width',
        str(w),
        '--height',
        str(h),
        '--denoise',
        str(denoise),
        '--cam',
        json.dumps(cam),
    ]
    t0 = time.time()
    try:
        with _BlenderLock():
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=HERE)
    except subprocess.TimeoutExpired:
        return {'error': 'Blender took longer than %ds to ray trace this view' % TIMEOUT_S, 'code': 504}
    info = _last_json(p.stdout)
    if p.returncode != 0 or not info.get('ok') or not os.path.exists(png):
        tail = info.get('error') or (p.stderr or p.stdout or '')[-300:] or 'exit %d' % p.returncode
        return {'error': 'the ray trace failed: ' + str(tail)[:300], 'code': 500}
    with open(png, 'rb') as fh:
        data = fh.read()
    if len(data) < 8 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return {'error': 'Blender wrote something that is not a PNG', 'code': 500}
    info['seconds'] = round(time.time() - t0, 1)
    # the .blend beside the PNG is a debugging byproduct — the picture is the
    # return value and nothing ever opens the file again
    BSTORE.sweep(protect=[blend])
    # the numbers a caller may want (device, samples, seconds) ride on the headers,
    # because the body is the picture itself
    return (data, 'image/png', 'raytrace.png')


def info(payload, method):
    """What the tab shows before it asks for a render: is Blender there at all."""
    return {
        'ok': True,
        'blender': BLENDER,
        'present': os.path.exists(BLENDER),
        'script': os.path.exists(SCRIPT),
        'timeout_s': TIMEOUT_S,
        'max_samples': MAX_SAMPLES,
        'blend_dir': BLEND_DIR,
    }


ROUTES = {'render': render, 'info': info}
