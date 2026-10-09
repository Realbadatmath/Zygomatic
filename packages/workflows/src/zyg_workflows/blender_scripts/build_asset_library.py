# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_asset_library.py — turn a CC0 mesh pack into a Blender asset library.

    blender -b --python build_asset_library.py -- --pack kenney/building-kit

WHY THIS EXISTS. Blender's Asset Browser cannot browse a directory of .glb
files. It browses .blend files whose datablocks have been MARKED as assets and
filed into a catalogue. So the packs the Architecture Studio loads directly —
glTF over HTTP, no conversion — have to be imported once to be reachable from
Blender at all. The two consumers read the same bytes; only Blender needs the
index built for it.

THREE THINGS THAT ARE EASY TO GET WRONG AND ARE HANDLED HERE.

  * Textures stay EXTERNAL, and that takes an explicit flag. The glTF
    importer's `import_pack_images` DEFAULTS TO TRUE: built without it,
    polyhaven_arch.blend came out at 4.63 GB — a second, silently diverging
    copy of the 4.9 GB the ingest had already downloaded and hashed. With it
    off the image datablocks reference the files on disk and the same library
    is a few hundred megabytes.

  * The catalogue file is written BY US. Catalogs live in a sidecar
    `blender_assets.cats.txt` keyed by UUID; an asset whose catalog_id names a
    UUID that file does not contain is filed under "Unassigned" and looks lost.

  * Previews are LOADED, not generated. `ed.lib_id_generate_preview` needs a
    GPU and a window; in background mode it is a no-op that leaves a grey
    square. So the picture comes off disk via `ed.lib_id_load_custom_preview`,
    and WHICH picture is the catalogue's decision, not this script's: `pv` is
    already generated-render-first with the vendor's own art behind it. Asking
    the pack directory directly - which is what this did until 2026-09-01 -
    finds nothing for any pack that ships no art, and 520 Poly Haven models
    went into a library with grey tiles while the build reported success.
"""

import argparse
import os
import sys
import uuid

import bpy
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
PACKS_ROOT = os.path.join(CREWS, 'data', 'assets', 'mesh_packs')
LIB_ROOT = os.path.join(CREWS, 'data', 'assets', 'blender_library')

PREVIEW_DIRS = ('Previews', 'Isometric', 'Preview', '_previews')
PREVIEW_EXT = ('.png', '.jpg', '.jpeg', '.webp')


def argv_after_dashes():
    return sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []


def wipe_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def find_preview(pack_dir, stem):
    for d in PREVIEW_DIRS:
        pd = os.path.join(pack_dir, d)
        if not os.path.isdir(pd):
            continue
        for root, _dirs, files in os.walk(pd):
            for fn in files:
                base, ext = os.path.splitext(fn)
                if ext.lower() in PREVIEW_EXT and base.lower() == stem.lower():
                    return os.path.join(root, fn)
    return None


def import_one(path):
    """Import one glTF/GLB and return the objects it created."""
    before = set(bpy.data.objects)
    try:
        # import_pack_images DEFAULTS TO TRUE, which copies every texture
        # INTO the .blend: polyhaven_arch came out at 4.6 GB, a second and
        # silently diverging copy of bytes the ingest already hashed on disk.
        bpy.ops.import_scene.gltf(filepath=path, import_pack_images=False)
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'  SKIP {os.path.basename(path)}: {type(e).__name__}: {e}')
        return []
    return [o for o in bpy.data.objects if o not in before]


def consolidate(objs, name):
    """One asset per FILE. A kit model arrives as a hierarchy of empties and
    meshes; marking each mesh separately would put five nameless fragments in
    the browser where the pack ships one wall."""
    meshes = [o for o in objs if o.type == 'MESH']
    if not meshes:
        return None
    # Work in NAMES, not in object references. `object.join()` deletes the
    # objects it merged, and every Python wrapper pointing at one of them
    # raises ReferenceError on the next attribute access — including the
    # `.name` read in a cleanup loop.
    all_names = [o.name for o in objs]
    keep_name = meshes[0].name
    for o in objs:
        o.select_set(False)
    if len(meshes) > 1:
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        try:
            bpy.ops.object.join()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('joining the imported meshes failed: %s', _exc)
    obj = bpy.data.objects.get(keep_name)
    if obj is None:
        return None
    # The importer parents meshes to empties that carry the scene transform;
    # dropping the parent without keeping it would move the model.
    if obj.parent:
        mw = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = mw
    for nm in all_names:
        if nm == keep_name:
            continue
        leftover = bpy.data.objects.get(nm)
        if leftover is not None:
            bpy.data.objects.remove(leftover, do_unlink=True)
    obj.name = name
    if obj.data:
        obj.data.name = name
    return obj


def write_catalogs(out_dir, cats):
    """blender_assets.cats.txt — the sidecar that turns a catalog UUID on an
    asset into a name in the browser's tree.

    MERGES rather than overwrites. One library directory holds every pack, and
    this script runs once per pack: rewriting the file would leave only the
    last pack with a named catalog and file all the others under Unassigned."""
    p = os.path.join(out_dir, 'blender_assets.cats.txt')
    merged = {}
    if os.path.isfile(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(('VERSION', '#')):
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    merged[parts[1]] = parts[0]
    merged.update({path: cid for path, cid in cats.items()})
    lines = ['VERSION 1', '']
    for path, cid in sorted(merged.items()):
        lines.append(f'{cid}:{path}:{path.replace("/", "-")}')
    with open(p, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return p


def build(pack: str, licence: str) -> dict:
    pack_dir = os.path.join(PACKS_ROOT, pack)
    if not os.path.isdir(pack_dir):
        return {'pack': pack, 'error': 'no such pack'}

    sys.path.insert(0, CREWS)
    from zyg_workflows import architecture_assets as aa

    cat = aa.catalogue()
    items = [i for g in cat['groups'] if g['pack'] == pack for i in g['items']]
    if not items:
        return {'pack': pack, 'error': 'no catalogued items'}

    wipe_scene()
    catalog_path = pack.replace('/', '/')
    cid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'zygomatic:asset-cat:{pack}'))

    made, previews, skipped = 0, 0, 0
    for it in items:
        src = os.path.join(PACKS_ROOT, it['u'])
        if not os.path.isfile(src):
            skipped += 1
            continue
        stem = it['p']['item']
        objs = import_one(src)
        obj = consolidate(objs, stem)
        if obj is None:
            skipped += 1
            continue
        obj.asset_mark()
        ad = obj.asset_data
        ad.catalog_id = cid
        ad.description = f'{it["n"]} — {pack} ({licence})'
        ad.tags.new(pack.split('/')[0])
        ad.tags.new(licence)
        # The catalogue already resolved this: `pv` is generated-preview-first
        # and falls back to the vendor's art, which is the same policy the web
        # rail uses. find_preview() only ever looked INSIDE the pack, so every
        # pack that ships no art of its own - polyhaven_arch, every Smithsonian
        # unit - was built with zero previews while reporting success.
        pv = os.path.join(PACKS_ROOT, it['pv']) if it.get('pv') else find_preview(pack_dir, stem)
        if pv and os.path.isfile(pv):
            try:
                with bpy.context.temp_override(id=obj):
                    bpy.ops.ed.lib_id_load_custom_preview(filepath=pv)
                previews += 1
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('custom preview not loaded for this asset: %s', _exc)
        made += 1

    out_dir = os.path.join(LIB_ROOT, os.path.dirname(pack) or pack)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.basename(pack) + '.blend')
    write_catalogs(LIB_ROOT, {catalog_path: cid})
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    return {
        'pack': pack,
        'assets': made,
        'previews': previews,
        'skipped': skipped,
        'blend': out,
        'bytes': os.path.getsize(out) if os.path.isfile(out) else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True)
    ap.add_argument('--licence', default='CC0-1.0')
    a = ap.parse_args(argv_after_dashes())
    r = build(a.pack, a.licence)
    print('@@RESULT@@ ' + repr(r))


if __name__ == '__main__':
    main()
