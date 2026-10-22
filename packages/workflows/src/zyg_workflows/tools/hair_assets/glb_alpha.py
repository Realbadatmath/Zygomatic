#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""glb_alpha.py — set alphaMode on the materials of a .glb, in place.

Blender 4.3's glTF exporter derives alphaMode from the shader graph and ignores
Material.blend_method, so every hair-card pack came out alphaMode=BLEND however
the material was set. Hundreds of overlapping cards under BLEND have to be
depth-sorted per frame and are wrong wherever two cards cross; MASK resolves
per fragment and is what game hair uses. Rather than fight the exporter, the
one field is rewritten here, where it can be read back and checked.

    python3 glb_alpha.py MASK 0.5 file.glb [file.glb ...]
"""

import json
import struct


def patch(path, mode='MASK', cutoff=0.5):
    with open(path, 'rb') as fh:
        blob = fh.read()
    if blob[:4] != b'glTF':
        return 'not a glb'
    _magic, _ver, _total = struct.unpack('<III', blob[:12])
    off = 12
    chunks = []
    while off < len(blob):
        ln, ty = struct.unpack('<II', blob[off : off + 8])
        chunks.append((ty, blob[off + 8 : off + 8 + ln]))
        off += 8 + ln
    if not chunks or chunks[0][0] != 0x4E4F534A:
        return 'no json chunk'
    doc = json.loads(chunks[0][1])
    n = 0
    for m in doc.get('materials', []):
        m['alphaMode'] = mode
        if mode == 'MASK':
            m['alphaCutoff'] = cutoff
        else:
            m.pop('alphaCutoff', None)
        m['doubleSided'] = True
        n += 1
    if not n:
        return 'no materials'
    js = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)  # chunks are 4-byte aligned
    out = bytearray(b'glTF')
    out += struct.pack('<I', 2)
    body = bytearray()
    body += struct.pack('<II', len(js), 0x4E4F534A) + js
    for ty, data in chunks[1:]:
        pad = b'\x00' * ((4 - len(data) % 4) % 4)
        body += struct.pack('<II', len(data) + len(pad), ty) + data + pad
    out += struct.pack('<I', 12 + len(body)) + body
    with open(path, 'wb') as fh:
        fh.write(out)
    return f'{n} materials -> {mode}'


if __name__ == '__main__':  # the CLI lives in glb_alpha_cli
    from zyg_workflows.tools.hair_assets.glb_alpha_cli import main as _cli_main

    raise SystemExit(_cli_main())
