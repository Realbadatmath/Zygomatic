# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""reference_model.views — the build script reader, the portfolio re-photographer, the placer, the material audit, and the TOOLS table.

Moved verbatim from reference_model.py (lines 745-1167) by the 2026-10 modularization split;
no logic, constant or comment was changed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import logging as _zyg_logging
from zyg_workflows.arch_assistant_ext.reference_model.helpers import (
    BLENDER,
    BUILDER,
    BUILD_TIMEOUT,
    Drawing,
    HERE,
    INSPECT_N,
    MAX_OBJECTS,
    PORTFOLIO_CHECKLIST,
    R,
    Reply,
    WORK_DIR,
    _BlenderLock,
    _audit_text,
    _num,
    _portfolio_folder,
    _resolve,
    _scale_note,
    _thumb,
    cell_centre,
    cell_name,
    parse_cell,
    place_height,
)
from zyg_workflows.arch_assistant_ext.reference_model.build import (
    t_build_reference_asset,
    t_list_reference_models,
    t_view_reference,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.reference_model')


def t_view_build_script(d: Drawing, a, model='', head=0, tail=0, find=''):
    """The bpy script the asset was last built from. Without it a second round
    of work on an asset is a rewrite from memory, and what is not remembered is
    quietly deleted."""
    rec, err = _resolve(model)
    if rec is None:
        return err
    asset = rec.get('asset') or {}
    src = asset.get('script') or ''
    for n, e in enumerate(asset.get('edits') or []):
        src += (
            f'\n\n# ── EDIT {n + 1} ({e.get("ts")}) — run ON TOP of everything above '
            f'(build_reference_asset extend=true) ──\n' + str(e.get('script') or '')
        )
    if not src:
        return f'"{rec.get("name")}" has no build script stored — it has not been built through this tool yet'
    lines = src.splitlines()
    head, tail = int(_num(head, 0)), int(_num(tail, 0))
    pick, why = lines, f'all {len(lines)} lines'
    if find:
        hits = [n for n, l in enumerate(lines) if str(find).lower() in l.lower()]
        if not hits:
            return (
                f'the build script of "{rec.get("name")}" is {len(lines)} lines and none of them contains '
                f'"{find}" — call again without find= to read it'
            )
        keep = sorted({n for h in hits for n in range(max(0, h - 6), min(len(lines), h + 7))})
        pick = [f'{n + 1:5d}  {lines[n]}' for n in keep]
        why = f'{len(hits)} line(s) matching "{find}", with six lines of context round each'
    elif head:
        pick, why = lines[:head], f'the first {head} of {len(lines)} lines'
    elif tail:
        pick, why = lines[-tail:], f'the last {tail} of {len(lines)} lines'
    body = '\n'.join(pick)
    if len(body) > 30000:
        body = body[:30000] + f'\n… CUT at 30000 characters ({len(src)} in all) — ask for head=, tail= or find='
    return (
        f'the script "{rec.get("name")}" was last built from, {why} '
        f'(built {(rec.get("asset") or {}).get("built")}):\n\n' + body
    )


def t_portfolio_reference_asset(d: Drawing, a, model='', width=1280, height=720, inspect=False):
    """THE PORTFOLIO of an asset that is ALREADY built — forty-odd pictures,
    without rebuilding it."""
    rec, err = _resolve(model)
    if rec is None:
        return err
    if not os.path.exists(BLENDER):
        return f'refused: Blender is not at {BLENDER}'
    asset = rec.get('asset') or {}
    blend = asset.get('blend') or ''
    if not blend or not os.path.exists(blend):
        return (
            f'refused: "{rec["name"]}" has no built asset on disk yet — call build_reference_asset first '
            '(it takes the portfolio itself, on every build)'
        )
    w = max(320, min(2560, int(_num(width, 1280))))
    h = max(240, min(1440, int(_num(height, 720))))
    want = 0  # always the whole plan — see the comment on `n` below
    stamp = time.strftime('%Y%m%d-%H%M%S')
    work = os.path.join(WORK_DIR, f'{rec["id"]}-pf-{stamp}')
    os.makedirs(work, exist_ok=True)
    full = dict(rec)
    full['images'] = [
        dict(i, path=os.path.join(R.model_dir(rec['id']), 'images', i['file'])) for i in rec.get('images') or []
    ]
    with open(os.path.join(work, 'ref.json'), 'w', encoding='utf-8') as fh:
        json.dump(full, fh)
    base = os.path.join(work, R.slug(rec.get('name')))
    cmd = (
        [
            BLENDER,
            '-b',
            '--factory-startup',
            '--python',
            BUILDER,
            '--',
            '--ref',
            os.path.join(work, 'ref.json'),
            '--out',
            base,
            '--from-blend',
            blend,
            '--portfolio',
        ]
        + ([str(want)] if want else [])
        + ['--portfolio-engine', 'eevee', '--width', str(w), '--height', str(h)]
    )
    # `n` used to be a parameter here. It was removed on 2026-09-24: a round
    # asked for a quick look with n=8, the pass wrote 34 pictures, and because
    # this tool writes THE DELIVERED FOLDER it replaced the operator's 52 with
    # 34 — under the standing floor of 40. A cheap look is what the contact
    # sheets the call hands back are for; the folder is always the whole plan.
    if inspect:
        cmd += ['--inspect', str(INSPECT_N)]
    try:
        with _BlenderLock():
            p2 = subprocess.run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    except subprocess.TimeoutExpired:
        shutil.rmtree(work, ignore_errors=True)
        return f'refused: the portfolio pass did not finish inside {BUILD_TIMEOUT}s — ask for fewer pictures'
    out = (p2.stdout or '') + (('\n[stderr] ' + p2.stderr[-600:]) if p2.returncode != 0 and p2.stderr else '')
    line = ''
    for ln in out.splitlines()[::-1]:
        if ln.startswith('REFBUILD_JSON '):
            line = ln[len('REFBUILD_JSON ') :]
            break
    if not line:
        shutil.rmtree(work, ignore_errors=True)
        return (
            'the portfolio pass produced no result line — Blender output below\n'
            + '\n'.join(l for l in out.splitlines() if l.strip())[-1500:]
        )
    res = json.loads(line)
    if not res.get('ok'):
        shutil.rmtree(work, ignore_errors=True)
        return 'the portfolio pass failed: ' + str(res.get('error') or 'unknown')[-1500:]
    dims0 = res.get('dims') or [0, 0, 0]
    pf = _portfolio_folder(
        rec,
        res.get('portfolio') or [],
        res.get('audit') or {},
        {
            'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'engine': 'eevee',
            'dims': f'{dims0[0]:g} x {dims0[1]:g} x {dims0[2]:g} m',
            'tris': res.get('tris') or 0,
        },
    )
    rec.setdefault('asset', {})
    rec['asset']['portfolio'] = {k: v for k, v in pf.items() if k != 'shots'}
    rec['asset']['portfolio_shots'] = (pf.get('shots') or [])[:60]
    rec['asset']['audit'] = res.get('audit') or {}
    R._write(rec)  # noqa: SLF001 — same package, one store
    shutil.rmtree(work, ignore_errors=True)
    images, titles = [], []
    for i, sheet in enumerate(pf.get('sheets') or []):
        b = _thumb(sheet)
        if b:
            images.append(b)
            titles.append(f'contact sheet {i + 1}')
    txt = (
        f'THE PORTFOLIO of "{rec.get("name")}" — {pf["n"]} pictures of {pf["planned"]} planned, in\n'
        f'  {pf["dir"]}\n'
        f'  index.html opens all of them with the measurement under each; '
        f'{len(pf.get("sheets") or [])} contact sheet(s) are handed to you here.\n'
        + '\n'.join(
            f'  {i + 1:2d} {r["title"]}: {r["note"]}' + ('' if r['file'] else '   [NO PICTURE]')
            for i, r in enumerate(pf.get('shots') or [])
        )
        + '\n\n'
        + _audit_text(res.get('audit') or {})
        + '\n\n'
        + PORTFOLIO_CHECKLIST
    )
    return Reply(text=txt, images=images[:6]) if images else txt


def t_place_reference_asset(d: Drawing, a, cell, model='', storey=0, rotation_deg=0, scale=1.0, name='', material=''):
    rec, err = _resolve(model)
    if rec is None:
        return err
    asset = rec.get('asset') or None
    if not asset or not asset.get('pack'):
        return f'refused: "{rec["name"]}" has no built asset yet — call build_reference_asset first'
    # The studio draws a placeholder crate for an asset id it cannot resolve,
    # which looks like a loader fault rather than a bad id. Check it here.
    try:
        from zyg_workflows import architecture_assets as _AA

        if _AA.resolve(asset['pack'], asset['item']) is None:
            return (
                f'refused: the catalogue cannot resolve {asset["pack"]}|{asset["item"]} — the asset was '
                'built before the pack was published, or the pack was removed. Build it again.'
            )
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('asset catalogue resolve check skipped: %s', _exc)
    if len(d.objs) >= MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    s = _num(scale, 1.0) or 1.0
    if s <= 0 or s > 100:
        return 'refused: scale must be between 0 and 100'
    try:
        c, r = parse_cell(cell)
    except ValueError as e:
        return f'refused: {e}'
    cx, cz = cell_centre(c, r)
    st = int(_num(storey, 0))
    y = place_height(d, cx, cz, None if st == 0 else st * d.storey_h)
    dims = asset.get('dims') or [1, 1, 1]
    p = {
        'pack': asset['pack'],
        'item': asset['item'],
        'bw': round(float(dims[0]), 4),
        'bh': round(float(dims[2]), 4),
        'bd': round(float(dims[1]), 4),
    }
    if asset.get('tris'):
        p['tris'] = int(asset['tris'])
    import math

    rads = math.radians(_num(rotation_deg, 0.0))
    mat = material if material in _materials() else 'mat_concrete'
    obj = d.new('asset', p, cx, cz, y, rads, mat, name=name or rec.get('name'), grp='reference')
    obj['s'] = round(float(s), 4)
    return (
        f'placed {obj["id"]} "{rec.get("name")}" ({asset["pack"]}|{asset["item"]}) on '
        f'{cell_name(c, r)} storey {st}'
        + (f', turned {_num(rotation_deg, 0.0):g}°' if _num(rotation_deg, 0.0) else '')
        + (f', scale {s:g}' if abs(s - 1.0) > 1e-6 else '')
        + f' — {p["bw"]:g} x {p["bd"]:g} m on plan, {p["bh"]:g} m tall.'
        + _scale_note(rec)
    )


def _materials():
    from zyg_workflows.arch_assistant import MATERIALS

    return MATERIALS


_VIEWS = 'iso, side, other_side, front, back, top, bottom'

TOOLS = [
    (
        {
            'name': 'list_reference_models',
            'description': (
                'The reference models the operator has parked: photographs and measured PLANS of a real '
                'thing to build from. Says what is measured on each (a model with no measured length can '
                'only give the right shape, never the right size) and whether an asset is already built. '
                'The one marked * is the one the operator has open.'
            ),
            'input_schema': {'type': 'object', 'properties': {'limit': {'type': 'integer'}}},
        },
        t_list_reference_models,
    ),
    (
        {
            'name': 'view_reference',
            'description': (
                "LOOK at a reference model's pictures — up to 3 come back as real images, with the role "
                'that says where each camera stood. Call this before modelling anything from a reference: '
                'the role and the measured dimensions are what turn pictures into geometry, and a picture '
                'you have not seen is a picture you are inventing.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'model': {
                        'type': 'string',
                        'description': 'reference model id or name; omit for the one the operator has open',
                    },
                    'role': {
                        'type': 'string',
                        'enum': list(R.ROLE_ORDER),
                        'description': 'only pictures taken from this direction',
                    },
                    'which': {'type': 'string', 'description': 'one picture id, from list_reference_models'},
                    'limit': {'type': 'integer', 'description': '1-3, default 3'},
                },
            },
        },
        t_view_reference,
    ),
    (
        {
            'name': 'build_reference_asset',
            'description': (
                'Build the reference model as a Blender asset and save it as .blend + .glb. Your `script` is bpy '
                'Python run in an EMPTY factory scene (NOT the drawing) — it is the WHOLE recipe, so improve one '
                'script rather than appending to a previous run. ' + R.LAYOUT + ' Available to the script, besides '
                'bpy/bmesh/math/mathutils: REF (the record, with length_m/beam_m/height_m and absolute image paths), '
                'ref_images(role), ref_path(role_or_id), ref_plane(role, width_m=None, at=0.0) which lays a plan into '
                'its own view at its measured size (a NEGATIVE `at` pushes it behind your geometry), ref_empty(...), '
                'ref_clear(), mirror(obj, axis="y") for a Mirror modifier — a hull or a facade is symmetric, so model '
                'one half and the halves cannot drift — asset_objects(), asset_meshes() and log(msg). Reference planes '
                'are tagged and are never exported or saved into the asset. With check=true (the default) every plan '
                'you laid out is rendered again with your geometry OVER it as a translucent blue overlay, in the '
                "plan's own view: that picture, not your intention, is the evidence the shape is right. "
                'Every build also comes back with the INSPECTION SET (ten views, four round it, one above, two '
                'cut planes and three from INSIDE, with a 1.75 m figure for scale): a single outside view cannot '
                'show a deck floating over the sides, a mast stepped in mid-air or a hull with no inside, and '
                'those are exactly the faults that survive to the end. Roles: '
                + ', '.join(R.ROLE_ORDER)
                + '. Views: '
                + _VIEWS
                + '.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'script': {
                        'type': 'string',
                        'description': 'the bpy Python that builds the asset. Everything you print or log() comes back.',
                    },
                    'model': {
                        'type': 'string',
                        'description': 'reference model id or name; omit for the one the operator has open',
                    },
                    'name': {'type': 'string', 'description': "the asset name; defaults to the reference model's name"},
                    'extend': {
                        'type': 'boolean',
                        'description': 'run this script ON TOP of the asset already built (it is opened first, with every object in it), instead of in an empty scene. Use it to ADD to a finished asset — cut a door, fit out a cabin, remake a material — without re-emitting the whole thing. Default false',
                    },
                    'portfolio': {
                        'type': 'boolean',
                        'description': "THE PORTFOLIO: ~50 renders into a folder the operator opens, with a surface audit. Default TRUE — the operator's standing rule is that every finished drawing is handed over with 40+ pictures",
                    },
                    'views': {
                        'type': 'string',
                        'description': 'up to 2 preview views, comma separated, from: ' + _VIEWS,
                    },
                    'check': {
                        'type': 'boolean',
                        'description': 'render the asset over each plan it used (default true)',
                    },
                    'inspect': {
                        'type': 'boolean',
                        'description': (
                            'take the INSPECTION SET after the build — ten '
                            'pictures: four standpoints round it, one from above, two cut planes and three from '
                            'INSIDE, each with the measurement its camera made and a 1.75 m figure for scale. '
                            'Default true, and you must answer for them before you call the asset finished.'
                        ),
                    },
                    'engine': {'type': 'string', 'enum': ['workbench', 'eevee']},
                    'width': {'type': 'integer'},
                    'height': {'type': 'integer'},
                },
                'required': ['script'],
            },
        },
        t_build_reference_asset,
    ),
    (
        {
            'name': 'view_build_script',
            'description': (
                'The bpy script the asset was last built from — read it before you change anything '
                'about a thing that is already built, and extend THAT rather than writing a new one '
                'from memory. find="gunport" returns just the lines that mention it with context; '
                'head=/tail= return the first or last lines.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string'},
                    'head': {'type': 'integer'},
                    'tail': {'type': 'integer'},
                    'find': {
                        'type': 'string',
                        'description': 'only the lines containing this, with six lines of context',
                    },
                },
                'required': [],
            },
        },
        t_view_build_script,
    ),
    (
        {
            'name': 'portfolio_reference_asset',
            'description': (
                'THE PORTFOLIO of an asset you have ALREADY built: forty-odd renders of it — twelve '
                'standpoints right round it, four from above, the six orthographic views, a cut on the '
                'centreline and six across the body, a plan cut over every deck, two interior views on '
                'every level, two raking shots along the flank and the bottom for FAIRNESS, and close '
                'lenses on the bow, stern, entry, cabin lights, tops and both decks. Written to a '
                'FOLDER the operator opens (index.html + contact sheets + every full-size frame), with '
                'the measurement each camera made under it and a surface audit (materials, smooth '
                'shading, how hard each mesh bends) beside it. build_reference_asset already does this '
                'on every build — use this one to re-photograph an asset you did not just build, or '
                'after editing it by hand. It always renders the WHOLE plan and rewrites the '
                "delivered folder: the operator's floor is 40+ pictures, so there is no way to ask "
                'for fewer. The contact sheets it hands back are the cheap look.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'model': {
                        'type': 'string',
                        'description': 'reference model name or id; default the one the operator has open',
                    },
                    'width': {'type': 'integer'},
                    'height': {'type': 'integer'},
                    'inspect': {
                        'type': 'boolean',
                        'description': 'also take the ten-picture inspection set (default false)',
                    },
                },
                'required': [],
            },
        },
        t_portfolio_reference_asset,
    ),
    (
        {
            'name': 'place_reference_asset',
            'description': (
                "Drop a reference model's BUILT asset into the drawing on a cell, as the studio's ordinary "
                '"asset" kind, so it saves, duplicates and rebuilds like any other. The asset must have been '
                'built first. It stands on whatever surface is under the cell — the ground at storey 0, the '
                'deck there on an upper storey.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string', 'description': 'a grid cell, like F12'},
                    'model': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'rotation_deg': {'type': 'number', 'description': '0 leaves the length along +X (east)'},
                    'scale': {'type': 'number'},
                    'name': {'type': 'string'},
                    'material': {'type': 'string'},
                },
                'required': ['cell'],
            },
        },
        t_place_reference_asset,
    ),
]
