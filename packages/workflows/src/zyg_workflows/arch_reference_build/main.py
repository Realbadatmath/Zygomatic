# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build.main — the builder's ``main()``: read the arguments,
build or open the asset, render, audit, export, print one JSON line (lines
1872-2075 of the original single file, moved verbatim).

It is DEFINED here and called by ``entry.py`` only — importing this module must
not start a build.
"""

import contextlib
import io
import json
import math
import os
import traceback

import bmesh
import bpy
import mathutils

from .api import asset_meshes, asset_objects, mirror, ref_clear, ref_empty, ref_images, ref_plane, ref_width
from .audit import _audit
from .base import LOG, ORIENT, _REF_OBJS, arg, flag, log
from .inspection import INSPECT_ALL, INSPECT_N, _inspect
from .portfolio import _portfolio
from .scene import _bounds, _empty_scene, _export_glb, _overlay, _render, _tris

# The reference record. ``main()`` rebinds this (``global REF``) once it has read
# ``--ref``; ``api.REF`` is a live view onto it, as it was one global before the
# split. The empty start is the original module-level ``REF = {}``.
REF = {}


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    global REF
    out = {
        'ok': False,
        'blend': '',
        'glb': '',
        'images': [],
        'inspect': [],
        'portfolio': [],
        'audit': None,
        'objects': 0,
        'tris': 0,
        'dims': None,
        'script_error': None,
        'stdout': '',
        'log': LOG,
    }
    try:
        # --ref is the reference model's record. A portfolio pass over a
        # .blend that is not an asset (a DRAWING, photographed by
        # blender_power.portfolio) has no record and needs none: nothing in the
        # camera plan reads REF.
        ref_path = arg('--ref')
        if ref_path:
            with open(ref_path, encoding='utf-8') as fh:
                REF = json.load(fh)
        elif not arg('--from-blend'):
            raise ValueError('--ref is required unless --from-blend is given')
        base = arg('--out')
        width, height = int(arg('--width', '1280') or 1280), int(arg('--height', '720') or 720)
        engine = (arg('--engine', 'workbench') or 'workbench').lower()
        views = [v.strip() for v in (arg('--views', 'iso') or 'iso').split(',') if v.strip()]
        check = flag('--check')
        # --inspect            the operator's ten
        # --inspect 6          the first six of them
        # --inspect bow,beam   exactly these
        # --portfolio          the operator's forty-odd (2026-09-23)
        # --portfolio 24       fewer, thinned from the orbit ring first
        pf = arg('--portfolio', '') if flag('--portfolio') else ''
        pf_n = (max(1, int(pf)) if pf.isdigit() else 0) if flag('--portfolio') else 0
        pf_on = flag('--portfolio')
        pf_engine = (arg('--portfolio-engine', 'eevee') or 'eevee').lower()
        from_blend = arg('--from-blend', '')
        edit_blend = arg('--edit-blend', '')
        insp = arg('--inspect', '') if flag('--inspect') else ''
        if flag('--inspect'):
            if insp.isdigit():
                inspect_views = list(INSPECT_ALL[: max(1, min(len(INSPECT_ALL), int(insp)))])
            elif insp and not insp.startswith('--'):
                inspect_views = [v.strip() for v in insp.replace(' ', ',').split(',') if v.strip() in INSPECT_ALL]
            else:
                inspect_views = list(INSPECT_ALL[:INSPECT_N])
        else:
            inspect_views = []

        # --from-blend: photograph an asset that is ALREADY built, without
        # rebuilding it. A portfolio is a report on the thing on disk; making
        # one must never be able to change the thing it reports on, so this
        # path writes no .blend, exports no GLB and runs no script.
        if from_blend:
            bpy.ops.wm.open_mainfile(filepath=from_blend)
            log(f'opened {os.path.basename(from_blend)} — reporting on it, not rebuilding it')
            bpy.context.view_layer.update()
            objs = asset_meshes()
            out['objects'] = len(asset_objects())
            out['tris'] = _tris(objs)
            b = _bounds(objs)
            if b:
                lo, hi = b
                out['dims'] = [round(hi[0] - lo[0], 4), round(hi[1] - lo[1], 4), round(hi[2] - lo[2], 4)]
            out['audit'] = _audit()
            for f in out['audit']['findings']:
                log('audit: ' + f)
            if inspect_views:
                out['inspect'] = _inspect(
                    inspect_views, base, width, height, (arg('--inspect-engine', engine) or engine).lower()
                )
                out['images'].extend(out['inspect'])
            if pf_on:
                out['portfolio'] = _portfolio(base, width, height, pf_engine, pf_n)
                out['images'].extend(out['portfolio'])
            out['ok'] = True
            out['log'] = LOG[-80:]
            print('REFBUILD_JSON ' + json.dumps(out), flush=True)
            return

        # --edit-blend: open the asset that is already built and run the
        # script ON it. An asset is not finished in one pass — doors get cut,
        # cabins get fitted out, a material gets remade — and re-emitting forty
        # thousand characters of hull to add a window is how detail gets lost
        # between rounds. The script sees exactly what is in the file.
        if edit_blend:
            bpy.ops.wm.open_mainfile(filepath=edit_blend)
            log(f'opened {os.path.basename(edit_blend)} to EDIT: {len(asset_objects())} objects already in it')
        else:
            _empty_scene()
        g = {
            '__name__': '__main__',
            'bpy': bpy,
            'bmesh': bmesh,
            'math': math,
            'mathutils': mathutils,
            'os': os,
            'json': json,
            'REF': REF,
            'ORIENT': ORIENT,
            'log': log,
            'ref_images': ref_images,
            'ref_path': ref_path,
            'ref_width': ref_width,
            'ref_plane': ref_plane,
            'ref_empty': ref_empty,
            'ref_clear': ref_clear,
            'mirror': mirror,
            'asset_objects': asset_objects,
            'asset_meshes': asset_meshes,
        }
        src = arg('--script')
        if src:
            # The script's own print() is captured and handed back: the tool
            # promises "everything you print comes back", and a promise the
            # caller cannot see through is worse than no promise. Blender's own
            # chatter stays on the real stdout, where the log tail can find it.
            buf = io.StringIO()
            try:
                with open(src, encoding='utf-8') as fh:
                    code = fh.read()
                with contextlib.redirect_stdout(buf):
                    # This IS the feature: --script names the bpy the assistant wrote for THIS
                    # build and running it is the whole point of the builder. There is no
                    # narrower primitive that executes arbitrary bpy.
                    exec(compile(code, src, 'exec'), g)  # nosec B102  # noqa: S102  the builder's purpose
                log('script ran')
            except Exception:  # noqa: BLE001
                out['script_error'] = traceback.format_exc()[-3000:]
                log('SCRIPT RAISED')
            out['stdout'] = buf.getvalue()[-4000:]
            if out['stdout']:
                print('[refbuild] --- script printed ---\n' + out['stdout'], flush=True)

        bpy.context.view_layer.update()
        objs = asset_meshes()
        out['objects'] = len(asset_objects())
        out['tris'] = _tris(objs)
        b = _bounds(objs)
        if b:
            lo, hi = b
            out['dims'] = [round(hi[0] - lo[0], 4), round(hi[1] - lo[1], 4), round(hi[2] - lo[2], 4)]

        # the CHECK renders come first: they need the reference scaffolding
        if check:
            roles = sorted({str(o.name).replace('ref_', '') for o in _REF_OBJS if o.name.startswith('ref_')})
            for role in roles[:2]:
                png = f'{base}-check-{role}.png'
                got = _overlay(role, png, width, height)
                if got:
                    out['images'].append({'path': got, 'title': f'the asset over the {role} reference', 'check': True})

        nref = ref_clear()
        if nref:
            log(f'cleared {nref} reference object(s) before saving the asset')

        for v in views[:2]:
            png = f'{base}-{v}.png'
            if _render(v, png, width, height, engine):
                out['images'].append({'path': png, 'title': f'{v} view', 'check': False})

        # THE INSPECTION SET — the ten pictures the finished asset is judged on.
        # It runs after ref_clear (the plates are scaffolding, not the subject)
        # and before the export, and every camera it made is removed again, so
        # what ships is the asset and nothing else.
        # The audit is measured BEFORE the cameras go in: curves and materials
        # as numbers, because "it looks smooth" is not a check.
        out['audit'] = _audit()
        for f in out['audit']['findings']:
            log('audit: ' + f)

        if inspect_views:
            out['inspect'] = _inspect(
                inspect_views, base, width, height, (arg('--inspect-engine', engine) or engine).lower()
            )
            out['images'].extend(out['inspect'])

        # THE PORTFOLIO — the operator's standing rule since 2026-09-23: every
        # finished drawing is handed over with forty-odd pictures, not ten.
        if pf_on:
            out['portfolio'] = _portfolio(base, width, height, pf_engine, pf_n)
            out['images'].extend(out['portfolio'])

        if out['objects']:
            try:
                out['glb'] = _export_glb(base + '.glb')
            except Exception as e:  # noqa: BLE001
                log(f'GLB export failed: {type(e).__name__}: {e}')
        bpy.ops.wm.save_as_mainfile(filepath=base + '.blend')
        out['blend'] = base + '.blend'
        out['ok'] = True
    except Exception:  # noqa: BLE001
        out['error'] = traceback.format_exc()[-2000:]
    out['log'] = LOG[-60:]
    print('REFBUILD_JSON ' + json.dumps(out), flush=True)
