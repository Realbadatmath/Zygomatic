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

import argparse
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


def _main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--glb', required=True)
    ap.add_argument('--id', required=True, help='asset_id in the prop-mesh registry')
    ap.add_argument('--name', default='')
    ap.add_argument('--kind', default='prop')
    ap.add_argument('--description', default='')
    ap.add_argument('--tags', default='')
    ap.add_argument('--creature-id', default=None)
    ap.add_argument('--build-dir', default=None)
    ap.add_argument('--samples', type=int, default=48)
    ap.add_argument('--res', type=int, default=1024)
    ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--views', nargs='*', default=None)
    ap.add_argument('--blender-arg', action='append', default=[], help='passed straight through to sheet_render.py')
    ap.add_argument('--control', action='store_true', help='run mesh_control.build on the registered asset')
    ap.add_argument('--kinds', nargs='*', default=['depth', 'normal', 'lineart', 'segment', 'matte'])
    ap.add_argument('--replace', action='store_true')
    ap.add_argument('--skip-render', action='store_true', help='reuse an existing build dir')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    glb = os.path.abspath(a.glb)
    if not os.path.isfile(glb):
        raise SystemExit('no such GLB: %s' % glb)
    meta = pack_licence(glb)
    if not meta:
        raise SystemExit(
            'REFUSED: %s is not under a mesh pack with a PROVENANCE.json. An asset with '
            'a guessed licence is worse than no asset — add the pack provenance first.' % glb
        )
    print('[licence] %s  (%s)' % (meta['licence']['spdx'], meta['provenance']['pack']))
    print('[licence] evidence: %s' % meta['licence']['evidence_url'])
    if a.dry_run:
        print(json.dumps(meta, indent=2))
        return 0

    build = a.build_dir or os.path.join(_ROOT, 'output', 'prop_sheets', a.id)
    if not a.skip_render:
        rc, _ = render(glb, build, samples=a.samples, res=a.res, scale=a.scale, views=a.views, extra=a.blender_arg)
        if rc != 0:
            raise SystemExit('sheet render failed (rc=%d) — nothing registered' % rc)
    sheet = _load(os.path.join(build, 'sheet.json'))
    if not sheet:
        raise SystemExit('no readable sheet.json in %s' % build)

    # trimesh is what geometry_stats and export_mesh3d are built on, and register()
    # swallows their failure into an {'error': ...} field. Measured: run under the
    # server venv (no trimesh) the record comes back with size_m null and no mesh3d.bin,
    # so the library card has no 3D preview and nothing can read the asset's real-world
    # size — a half-registered asset that verify() still calls ok. Refuse instead.
    try:
        import trimesh  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            'REFUSED: %s has no trimesh, so the record would carry no size_m and no '
            'mesh3d.bin. Re-run under /usr/bin/python3.12.' % sys.executable
        ) from exc

    from zyg_workflows import prop_mesh_library as PML

    rec = PML.register(
        a.id,
        build,
        name=a.name or a.id,
        kind=a.kind,
        creature_id=a.creature_id,
        description=a.description,
        tags=[t for t in a.tags.split(',') if t],
        licence=meta['licence'],
        provenance=dict(
            meta['provenance'],
            sheet_views=len(sheet.get('views') or []),
            samples=sheet.get('samples'),
            res=[sheet.get('w'), sheet.get('h')],
        ),
        registered=time.strftime('%Y-%m-%dT%H:%M:%S'),
        replace=a.replace,
    )
    print(
        '[register] %s  %d files  %.1f MB  views=%d passes=%d'
        % (a.id, len(rec['sha256']), rec['bytes'] / 1e6, rec['views']['beauty'], rec['views']['passes'])
    )
    print('[register] size_m %s' % json.dumps(rec['geometry'].get('size_m')))
    v = PML.verify(a.id)[a.id]
    print('[verify] ok=%s files=%d bad=%s missing=%s' % (v['ok'], v['files'], v['bad'], v['missing']))
    if not v['ok']:
        return 2

    if a.control:
        from zyg_workflows import mesh_control as MC

        man = MC.build(a.id, kinds=tuple(a.kinds), force=True, log_fn=print)
        print('[control] views=%d skipped=%s' % (len(man['views']), man['skipped'] or '{}'))
        if man['skipped']:
            return 4
    return 0


if __name__ == '__main__':
    sys.exit(_main())
