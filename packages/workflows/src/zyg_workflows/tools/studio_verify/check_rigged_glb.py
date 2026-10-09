#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Structural proof for a rigged base-creature GLB.

    python3 tools/studio_verify/check_rigged_glb.py FILE.glb [--joints 51] [--anims 12]
        [--min-tris 50000] [--max-tris 400000] [--color0] [--basecolor-alpha]

Exit 0 only when every primitive carries JOINTS_0 + WEIGHTS_0, the skin has the
expected joint count, the animation count matches, the triangle count is in
range, and (flags) COLOR_0 is present on every primitive / the coat material's
baseColorTexture PNG has an alpha channel (the fur-length channel). Prints one
JSON line either way.
"""

import argparse
import io
import json
import struct
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('--joints', type=int, default=51)
    ap.add_argument('--anims', type=int, default=12)
    ap.add_argument('--min-tris', type=int, default=50000)
    ap.add_argument('--max-tris', type=int, default=400000)
    ap.add_argument('--color0', action='store_true')
    ap.add_argument('--basecolor-alpha', action='store_true')
    a = ap.parse_args()
    b = open(a.glb, 'rb').read()
    if b[:4] != b'glTF':
        raise ValueError('not a GLB')
    jl = struct.unpack('<I', b[12:16])[0]
    g = json.loads(b[20 : 20 + jl])
    off = 20 + jl + 8
    prims = [p for m in g['meshes'] for p in m['primitives']]
    tris = sum(g['accessors'][p['indices']]['count'] // 3 for p in prims if 'indices' in p)
    skinned = all('JOINTS_0' in p['attributes'] and 'WEIGHTS_0' in p['attributes'] for p in prims)
    joints = [len(s['joints']) for s in g.get('skins', [])]
    anims = [x.get('name') for x in g.get('animations', [])]
    color0 = all('COLOR_0' in p['attributes'] for p in prims)
    alpha = None
    if a.basecolor_alpha:
        from PIL import Image

        alpha = False
        for m in g['materials']:
            t = m.get('pbrMetallicRoughness', {}).get('baseColorTexture')
            if not t:
                continue
            img = g['images'][g['textures'][t['index']]['source']]
            bv = g['bufferViews'][img['bufferView']]
            data = b[off + bv['byteOffset'] : off + bv['byteOffset'] + bv['byteLength']]
            if Image.open(io.BytesIO(data)).mode == 'RGBA':
                alpha = True
    ok = (
        skinned
        and joints == [a.joints]
        and len(anims) == a.anims
        and a.min_tris <= tris <= a.max_tris
        and (color0 or not a.color0)
        and (alpha or not a.basecolor_alpha)
    )
    print(
        json.dumps(
            {
                'ok': ok,
                'tris': tris,
                'prims': len(prims),
                'skinned': skinned,
                'joints': joints,
                'anims': anims,
                'color0': color0,
                'basecolor_alpha': alpha,
                'idle_present': 'Idle' in anims,
            }
        )
    )
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
