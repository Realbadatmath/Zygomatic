# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sheet_register.py — drive sheet_render.py over a pack GLB and register the result.

    python3 prop_mesh/sheet_register.py \
        --glb "data/assets/mesh_packs/kenney/survival-kit/Models/GLB format/workbench.glb" \
        --id kenney_workbench --name "Workbench (Kenney survival kit)" \
        --tags prop,kenney --samples 48 [--control] [--replace] [--dry-run]

WHY A SECOND FILE. `sheet_render.py` imports bpy at module scope, so it can only ever
run inside `blender -b`. Everything that happens either side of the render — resolving
the source pack's licence, calling `prop_mesh_library.register`, building the control
maps — is ordinary Python that must NOT run in Blender's bundled interpreter (it has no
cv2, which is what `geom/passes_io` is built on, so the control build would skip itself
and report success). Two interpreters, two files, one CLI.

LICENCE IS INHERITED, NOT ASSERTED. The channel is monetised, so "where did this
geometry come from" is a shipping question. Every registration made here carries the
pack's own PROVENANCE.json licence text, its evidence URL, the pack registry's per-file
sha256 and the object's source URL — copied, never retyped. A GLB whose pack has no
PROVENANCE.json is refused rather than registered as "probably CC0": an asset with a
guessed licence is worse than no asset, because nothing downstream can tell them apart.

The GLB's own bytes are what get hashed and stored. Blender never re-exports it.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

BLENDER = os.environ.get('ZYG_BLENDER', '/usr/local/bin/blender')
PACKS = os.path.join(_ROOT, 'data', 'assets', 'mesh_packs')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _load(p):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def pack_licence(glb):
    """{'licence': {...}, 'provenance': {...}} inherited from the GLB's own pack.

    EVERY ancestor directory holding a PROVENANCE.json is a candidate, and the one whose
    registry.json actually has a ROW for this file wins. Stopping at the first (nearest)
    one is wrong and was measured wrong: `smithsonian/Mammals/` carries its own unit
    PROVENANCE, so a cranium resolved against the unit rather than the pack, matched no
    row, and came back with the pack's DEMO_KEY search URL as its `source_url` and no
    record id — a licence that is still true and a provenance that points at nothing.
    Nearest-with-a-row first, then nearest-without, so a pack that genuinely has no
    per-file registry still resolves.

    Returns None when no ancestor claims the file, which the caller must treat as a
    refusal: an asset with a guessed licence is worse than no asset."""
    glb = os.path.abspath(glb)
    roots = []
    d = os.path.dirname(glb)
    while d.startswith(PACKS) and len(d) >= len(PACKS):
        if os.path.isfile(os.path.join(d, 'PROVENANCE.json')):
            roots.append(d)
        if d == PACKS:
            break
        d = os.path.dirname(d)
    best = None
    for root in roots:
        prov = _load(os.path.join(root, 'PROVENANCE.json'))
        if not prov:
            continue
        rel = os.path.relpath(glb, root)
        reg = _load(os.path.join(root, 'registry.json')) or {}
        rows = list(reg.values()) if isinstance(reg, dict) else list(reg)
        item = next((r for r in rows if isinstance(r, dict) and r.get('file') == rel), None)
        per_file = item is not None
        if item is None:
            # Kenney-shaped: one registry row per PACK (a zip of hundreds of meshes), so
            # the row is found by the first path segment rather than by the file.
            seg = rel.split(os.sep)[0]
            item = next((r for r in rows if isinstance(r, dict) and r.get('id') == seg), None)
        cand = (root, prov, rel, item or {}, per_file)
        if per_file:
            best = cand
            break
        if best is None:
            best = cand
    if best is None:
        return None
    pack_root, prov, rel, item, per_file = best
    pack = os.path.basename(pack_root)
    spdx = item.get('licence') or prov.get('license') or ''
    lic = {
        'spdx': spdx,
        'name': prov.get('license') or '',
        'source': prov.get('source_summary') or '',
        'evidence_url': prov.get('license_evidence_url') or '',
        'evidence_quote': prov.get('license_quote') or '',
        'commercial_use': True if str(spdx).upper().startswith('CC0') else None,
        'checked': 'inherited verbatim from %s/PROVENANCE.json — not re-asserted here' % pack,
    }
    provenance = {
        'pack': pack,
        'pack_item': item.get('id') or item.get('stem') or rel,
        'pack_item_name': item.get('name') or '',
        'source_url': item.get('source_url') or prov.get('license_evidence_url') or '',
        'source_file': rel,
        # WHOSE hash this is matters. A Smithsonian row keys on the file, so its sha256
        # is the GLB's. A Kenney row keys on the PACK, so its sha256 is the zip's and
        # says nothing about this mesh — recorded under its own name, with the file's
        # own hash measured here so the two can never be read as each other.
        'source_file_sha256': sha256_file(glb),
        ('source_sha256' if per_file else 'source_pack_sha256'): item.get('sha256') or '',
        'pack_ingested': item.get('ingested') or prov.get('curated') or '',
        'renderer': 'prop_mesh/sheet_render.py',
    }
    # What the pack already knows about this object and we would otherwise re-derive or
    # lose: the museum record id, the decimation/unit note, the pack's own size.
    for k in ('record', 'unit_name', 'derived', 'source_file', 'faces', 'faces_source', 'size_m'):
        if item.get(k) not in (None, '', []):
            provenance.setdefault('pack_' + k, item[k])
    return {'licence': lic, 'provenance': provenance}


def render(glb, out, *, samples=48, res=1024, scale=1.0, views=None, extra=(), log=print):
    """Run the Blender sheet renderer. Returns (returncode, tail-of-output)."""
    os.makedirs(out, exist_ok=True)
    cmd = [
        BLENDER,
        '-b',
        '--factory-startup',
        '-P',
        os.path.join(_HERE, 'sheet_render.py'),
        '--',
        '--glb',
        glb,
        '--out',
        out,
        '--samples',
        str(samples),
        '--res',
        str(res),
        '--scale',
        str(scale),
    ]
    if views:
        cmd += ['--views', ','.join(views)]
    cmd += list(extra)
    log('[sheet] %s' % ' '.join(('"%s"' % c if ' ' in c else c) for c in cmd))
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    out_txt = (p.stdout or '') + (p.stderr or '')
    keep = [
        l
        for l in out_txt.splitlines()
        if l.startswith('SR_') or 'Error' in l or 'Traceback' in l or 'error' in l.lower()[:20]
    ]
    log('[sheet] rc=%d in %.1fs' % (p.returncode, time.time() - t0))
    for l in keep[-40:]:
        log('  ' + l)
    return p.returncode, out_txt


if __name__ == '__main__':  # the CLI lives in sheet_register_cli
    from zyg_workflows.prop_mesh.sheet_register_cli import _main as _cli_main

    raise SystemExit(_cli_main())
