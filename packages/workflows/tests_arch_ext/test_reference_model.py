# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_reference_model — the REFERENCE MODEL rail, store, tools and build.

Four things that can each be right while the others are wrong:

  · THE STORE       (arch_reference): records, pictures, span/flip/datum, brief
  · THE ROUTES      (arch_server_ext/reference_model.py) on the LIVE server
  · THE ASSISTANT   (arch_assistant_ext/reference_model.py): its four tools
  · THE TAB         (arch_ext/reference_model.js): the rail beside the chat
                     panel, its one icon, and the sheet behind it
  · BLENDER         a real headless build, including the two placements that
                    are easy to get wrong and invisible until you render:
                    a MIRRORED plate and a DATUM that is not the picture's
                    middle.

The Blender checks are the slow ones; pass --fast to skip them.

SAFETY: importing arch_assistant closes any LIVE conversation in today's ledger
as "killed" (feedback_no_import_arch_assistant), so the assistant checks are
gated on the ledger having no open conversation. They are SKIPPED, loudly,
rather than run, if one is open.
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from zyg_workflows.arch_ext_harness import browser_eval, check, finish, server_ext  # noqa: E402

FAST = '--fast' in sys.argv


def ledger_is_quiet() -> bool:
    files = sorted(glob.glob(os.path.join(HERE, 'data/runtime/arch_assistant/conversations/*.jsonl')))
    if not files:
        return True
    rows = [json.loads(l) for l in open(files[-1], encoding='utf-8') if l.strip()]
    start = {r['id'] for r in rows if r.get('event') == 'start'}
    end = {r['id'] for r in rows if r.get('event') == 'end'}
    return not (start - end)


def _png_size(path):
    """(w, h) of a PNG, from its header — the probe must not need Pillow."""
    try:
        with open(path, 'rb') as fh:
            head = fh.read(24)
        return (int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big'))
    except OSError:
        return (0, 0)


def png(w, h, colour=(255, 255, 255), mark=True):
    from PIL import Image, ImageDraw

    im = Image.new('RGB', (w, h), colour)
    if mark:
        d = ImageDraw.Draw(im)
        d.rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], outline=(0, 0, 0), width=3)
    b = io.BytesIO()
    im.save(b, 'PNG')
    import base64

    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()


# ── the store ────────────────────────────────────────────────────────────────
from zyg_workflows import arch_reference as R  # noqa: E402

print('\n== the store ==')
check('LAYOUT states the frame once', 'LENGTH along +X' in R.LAYOUT and 'Z-up' in R.LAYOUT)
check('every ordered role exists', set(R.ROLE_ORDER) == set(R.ROLES), sorted(set(R.ROLE_ORDER) ^ set(R.ROLES)))
check(
    'every view role carries a rotation and an eye',
    all(R.ROLES[r]['blender'] and R.ROLES[r]['eye'] for r in R.ROLES if R.ROLES[r]['plan']),
)
check(
    'no photo role pretends to be a view', all(R.ROLES[r]['blender'] is None for r in R.ROLES if not R.ROLES[r]['plan'])
)
check('every role has a short label for the dropdown', all(R.ROLES[r].get('short') for r in R.ROLES))

rec = R.create('probe reference', 'test')
MID = rec['id']
try:
    check('a new model is not measurable', not R.measurable(R.read(MID)))
    check('brief says so in words', 'cannot fix a real size' in R.brief(R.read(MID)))
    R.update(MID, {'length_m': 20, 'beam_m': 5, 'height_m': 4, 'notes': 'n'})
    check('one measured dimension makes it measurable', R.measurable(R.read(MID)))

    a = R.add_image(MID, png(400, 200), 'side.png', 'view_side', 'bow right')
    b = R.add_image(MID, png(300, 300), 'plan.png', 'view_top', '')
    check('two pictures stored', len(R.read(MID)['images']) == 2)
    check('size read off the file', (a['w'], a['h']) == (400, 200), a)
    check('span/flip/datum default to unset', a['span_m'] == 0.0 and a['flip'] is False and a['datum'] == [0.5, 0.5])

    R.set_image(MID, a['id'], {'span_m': 23.5, 'flip': True, 'datum': '0.48,0.06'})
    got = [i for i in R.read(MID)['images'] if i['id'] == a['id']][0]
    check('span stored', got['span_m'] == 23.5, got)
    check('flip stored', got['flip'] is True)
    check('datum parsed from a string', got['datum'] == [0.48, 0.06], got['datum'])
    R.set_image(MID, b['id'], {'datum': [2.0, -1.0]})
    got_b = [i for i in R.read(MID)['images'] if i['id'] == b['id']][0]
    check('datum is clamped into the picture', got_b['datum'] == [1.0, 0.0], got_b['datum'])
    br = R.brief(R.read(MID))
    check('brief names the span', 'spans 23.5 m across' in br, br)
    check('brief flags the mirror', 'MIRRORED' in br, br)

    raw, mime = R.image_bytes(MID, a['id'], thumb=True)
    check('a thumbnail is made on demand', mime == 'image/jpeg' and len(raw) > 100)
    blk = R.image_b64(MID, a['id'])
    check('a picture encodes for a model', blk and blk[0] == 'image/jpeg' and len(blk[1]) > 100)

    check('resolve by id', (R.resolve(MID) or {}).get('id') == MID)
    # 2026-09-23: a probe model set as current and then deleted left its id in
    # current.json, so current() answered '' for ever and the rail showed NO
    # model beside a live one. delete() has to let go.
    check('the open model can be parked and read back', R.set_current(MID) == MID and R.current() == MID)
    check('resolve by name', (R.resolve('probe reference') or {}).get('id') == MID)
    check('an unknown name resolves to nothing', R.resolve('no such ship at all') is None)

    R.del_image(MID, b['id'])
    check('a picture can be removed', len(R.read(MID)['images']) == 1)

    # ── the routes, on the live server ───────────────────────────────────────
    # ── THE PORTFOLIO FOLDER (2026-09-23) ───────────────────────────────
    # The operator's rule after the ten: "after every drawing … portfolio
    # folder with 40+ images". The folder is the deliverable, so the store is
    # what is probed, not the tool that calls it.
    import shutil as _sh

    _one = R.image_path(MID, a['id'])
    _fake = [
        {'path': _one, 'title': 'orbit_000', 'note': 'on the ring, 35 mm, 40 m out'},
        {'path': _one, 'title': 'section_at_50', 'note': 'CUT across at 50 %'},
        {'path': '', 'title': 'inside_0_fwd', 'note': 'no surface to stand on near 3.00 m'},
    ]
    _pf = R.write_portfolio(
        R.read(MID),
        _fake,
        {'findings': ['2 mesh(es) carry NO MATERIAL at all']},
        {'built': 'now', 'engine': 'eevee', 'dims': '1 x 2 x 3 m', 'tris': 12},
    )
    check(
        'the portfolio folder is written under the portfolio root',
        _pf['dir'].startswith(R.PORTFOLIO_DIR) and os.path.isdir(_pf['dir']),
        _pf['dir'],
    )
    check(
        '...one numbered file per picture, in plan order',
        sorted(os.path.basename(x['file']) for x in _pf['shots'] if x['file'])
        == ['01-orbit-000.png', '02-section-at-50.png'],
        [x['file'] for x in _pf['shots']],
    )
    check(
        '...a view that could not be taken still carries its finding',
        _pf['planned'] == 3 and _pf['n'] == 2 and 'no surface to stand on' in _pf['shots'][2]['note'],
    )
    check('...a contact sheet', _pf['sheets'] and os.path.isfile(_pf['sheets'][0]), _pf['sheets'])
    _idx = open(_pf['index'], encoding='utf-8').read()
    check(
        '...index.html shows every picture with its measurement',
        'orbit_000' in _idx and 'on the ring' in _idx and 'NO PICTURE' in _idx,
    )
    check('...with the audit findings at the top, as defects', 'NO MATERIAL' in _idx and 'class="find"' in _idx)
    _js = json.load(open(os.path.join(_pf['dir'], 'portfolio.json'), encoding='utf-8'))
    check(
        '...and portfolio.json carries the shots and the audit',
        len(_js['shots']) == 3 and _js['audit']['findings'],
        _js.get('audit'),
    )
    # a folder that mixes two builds says nothing about either
    _pf2 = R.write_portfolio(R.read(MID), _fake[:1], {}, {'built': 'now', 'engine': 'eevee'})
    check(
        'a second portfolio SWEEPS the first — no stale frames beside the new ones',
        not os.path.exists(os.path.join(_pf['dir'], '02-section-at-50.png'))
        and os.path.isfile(os.path.join(_pf2['dir'], '01-orbit-000.png')),
        sorted(os.listdir(_pf2['dir'])),
    )
    _rec_pf = R.read(MID)
    _rec_pf['asset'] = _rec_pf.get('asset') or {}
    _rec_pf['asset']['portfolio'] = {k: v for k, v in _pf.items() if k != 'shots'}
    _rec_pf['asset']['portfolio_shots'] = _pf['shots']
    _rec_pf['asset']['audit'] = {'findings': ['x']}
    R._write(_rec_pf)  # noqa: SLF001
    _pub_pf = R.public(R.read(MID))['asset']
    check(
        'the tab payload offers the portfolio as URLs and names the folder',
        len(_pub_pf.get('portfolio_urls') or []) == 2 and _pub_pf.get('portfolio_dir', '').endswith(MID),
        _pub_pf.get('portfolio_urls'),
    )
    check('...the sheets separately', len(_pub_pf.get('portfolio_sheets') or []) == len(_pf['sheets']))
    check('...a view with no picture never becomes a broken img', len(_pub_pf.get('portfolio_notes') or []) == 1)
    check(
        '...and the audit findings ride with them',
        _pub_pf.get('audit_findings') == ['x'],
        _pub_pf.get('audit_findings'),
    )
    # a deleted model must not leave its pictures on the portfolio index — four
    # probe runs left four ghost projects listed there before delete() swept it
    _ghost = R.create('pf ghost', 'test')
    _gdir = R.write_portfolio(
        _ghost, [{'path': _one, 'title': 'orbit_000', 'note': 'n'}], {}, {'built': 'now', 'engine': 'eevee'}
    )['dir']
    R.delete(_ghost['id'])
    check('deleting a model takes its portfolio folder with it', not os.path.exists(_gdir), _gdir)
    _sh.rmtree(_pf['dir'], ignore_errors=True)

    print('\n== the routes (live server) ==')
    d = server_ext('reference_model', 'list', {})
    check('list answers', d.get('ok') and isinstance(d.get('models'), list))
    check('list carries the role vocabulary', any(r['id'] == 'view_side' for r in d.get('roles', [])))
    check('the probe model is listed', any(m['id'] == MID for m in d['models']))
    one = server_ext('reference_model', 'get', {'m': MID})
    check('get answers', one.get('ok') and one['model']['id'] == MID)
    check('get hands the tab thumbnail URLs', one['model']['images'][0]['thumb'].endswith('&t=1'))
    check('get reports measurability', one['model']['measurable'] is True)
    img = server_ext('reference_model', 'image', {'m': MID, 'i': one['model']['images'][0]['id']}, method='GET')
    check('a picture comes back as bytes', isinstance(img, dict) and img.get('bytes'), str(img)[:120])
    server_ext('reference_model', 'set_current', {'m': MID})
    check('set_current sticks', server_ext('reference_model', 'current', {})['id'] == MID)
    bad = server_ext('reference_model', 'get', {'m': '0' * 12})
    check('an unknown model is a 404, not a crash', not bad.get('ok') and bad.get('code') == 404, bad)

    # ── the assistant ────────────────────────────────────────────────────────
    print('\n== the assistant ==')
    if not ledger_is_quiet():
        check(
            'SKIPPED: a conversation is open in the ledger — not importing arch_assistant',
            True,
            'run again when the assistant is idle',
        )
    else:
        from zyg_workflows.arch_ext_harness import assistant
        from zyg_workflows import arch_assistant as A

        names = {t['name'] for t in A.TOOL_DEFS}
        for t in ('list_reference_models', 'view_reference', 'build_reference_asset', 'place_reference_asset'):
            check(f'tool {t} is registered', t in names)
        mod = A.EXT_MODULES.get('reference_model')
        check('the family loaded', mod is not None)
        check('its prompt is always in (not gated on a request word)', 'reference_model' not in A.PROMPT_FAMILIES)
        check('the prompt states the frame', mod is not None and 'LENGTH along +X' in mod.PROMPT)

        txt, dr = assistant('list_reference_models', {})
        check('list_reference_models names the probe model', 'probe reference' in str(txt), str(txt)[:200])
        check('...and marks the open one', '*' in str(txt).split('\n')[1])

        v, _ = assistant('view_reference', {'model': MID, 'role': 'view_side'}, drawing=dr)
        check(
            'view_reference hands back a real picture',
            isinstance(v, dict) and len(v.get('images') or []) == 1,
            str(v)[:200],
        )
        check('...and says which role it is', 'view_side' in str(v))
        miss, _ = assistant('view_reference', {'model': MID, 'role': 'view_bottom'}, drawing=dr)
        check(
            'a role with no picture is refused, and says what there is',
            str(miss).startswith('refused:') and 'view_side' in str(miss),
            str(miss)[:200],
        )
        nope, _ = assistant('view_reference', {'model': 'no such ship at all'}, drawing=dr)
        check('an unknown model is refused by name', str(nope).startswith('refused:'), str(nope)[:160])
        early, _ = assistant('place_reference_asset', {'model': MID, 'cell': 'F12'}, drawing=dr)
        check('placing before building is refused', 'no built asset' in str(early), str(early)[:160])

        if FAST:
            check('SKIPPED the Blender build (--fast)', True)
        else:
            print('\n== Blender ==')
            script = (
                'import bpy, bmesh\n'
                # the plate is MIRRORED and its datum is near the bottom-left:
                # both placements are wrong-by-default and invisible without a render
                "p = ref_plane('view_side', at=-3.0)\n"
                "print('PLANE_LOC %.4f %.4f %.4f' % tuple(p.location))\n"
                "print('PLANE_SX %.4f' % p.scale.x)\n"
                'bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1))\n'
                "bpy.context.active_object.name = 'box'\n"
                "log('probe geometry built')\n"
            )
            out, _ = assistant(
                'build_reference_asset',
                {'model': MID, 'script': script, 'name': 'probe asset', 'views': 'iso', 'check': True},
                drawing=dr,
            )
            s = str(out)
            check('the build reports what it made', 'built "probe asset"' in s, s[:300])
            check('...and hands back pictures', isinstance(out, dict) and len(out.get('images') or []) >= 1)
            check('...including the overlay, explained', 'blue is your geometry' in s, s[:400])
            after = R.read(MID)['asset'] or {}
            check('a .glb was written', after.get('glb') and os.path.isfile(after['glb']), after)
            check('a .blend was written', after.get('blend') and os.path.isfile(after['blend']))
            check('a preview was kept for the operator', after.get('preview') and os.path.isfile(after['preview']))
            check(
                'the check overlay was kept too, not swept with the work dir',
                after.get('checks') and os.path.isfile(after['checks'][0]['path']),
                after.get('checks'),
            )
            check('the script is recorded with the asset', after.get('script', '').startswith('import bpy'))

            # ── THE INSPECTION SET (2026-09-23) ─────────────────────────────
            # The operator's rule: ten pictures when a build finishes, from
            # different angles and from INSIDE. The build it came out of passed
            # a single iso view while the decks floated clear of the hull.
            insp = after.get('inspect') or []
            check('the inspection set was taken', len(insp) == 10, [i['title'] for i in insp])
            check(
                '...four standpoints round it, one above, two cuts, three inside',
                [i['title'] for i in insp]
                == [
                    'bow_quarter',
                    'beam',
                    'bow',
                    'stern',
                    'aerial',
                    'section_long',
                    'section_mid',
                    'inside_fwd',
                    'inside_aft',
                    'inside_below',
                ],
                [i['title'] for i in insp],
            )
            shots = [i for i in insp if i['path']]
            check(
                '...and every picture it could take is on disk beside the asset',
                shots
                and all(
                    os.path.isfile(i['path']) and os.path.dirname(i['path']) == os.path.dirname(after['glb'])
                    for i in shots
                ),
                [i['path'] for i in insp],
            )
            tall = [i for i in shots if i['title'] in ('bow', 'stern', 'section_mid')]
            check(
                '...a tall subject gets a PORTRAIT frame, not two thirds of empty 16:9',
                tall and all(_png_size(i['path'])[0] < _png_size(i['path'])[1] for i in tall),
                [(i['title'], _png_size(i['path'])) for i in tall],
            )
            wide = [i for i in shots if i['title'] in ('beam', 'aerial', 'section_long')]
            check(
                '...and a long one keeps the landscape frame',
                wide and all(_png_size(i['path'])[0] > _png_size(i['path'])[1] for i in wide),
            )
            inside = [i for i in insp if i['title'].startswith('inside')]
            check(
                'an inside camera says WHAT IT STOOD ON, by ray cast, not by guess',
                all(
                    (
                        'standing on the surface at' in i['note']
                        or 'NOTHING TO STAND ON' in i['note']
                        or 'no deck below' in i['note']
                        or 'no second level' in i['note']
                    )
                    for i in inside
                ),
                [i['note'][:80] for i in inside],
            )
            check(
                '...and how much air is in front of it',
                all('clear ahead' in i['note'] for i in inside if i['path']),
                [i['note'][:80] for i in inside],
            )
            check(
                '...and it carries a 1.75 m figure for scale',
                all('1.75 m tall' in i['note'] for i in inside if i['path']),
            )
            check(
                'the outside views say how far out the camera stands',
                all('m out' in i['note'] for i in insp if i['title'] in ('beam', 'bow', 'aerial')),
                [i['note'][:60] for i in insp[:3]],
            )
            # ── THE PORTFOLIO, on every build (2026-09-23) ──────────────
            # "after every drawing, make sure ai assistant delivers portfolio
            # folder with 40+ images from projects" — so it is a DEFAULT, and
            # the probe asserts the default rather than the flag.
            pf = after.get('portfolio') or {}
            rows = after.get('portfolio_shots') or []
            check(
                'the build took the portfolio without being asked',
                pf.get('n', 0) >= 20 and os.path.isdir(pf.get('dir') or ''),
                pf,
            )
            check(
                '...right round it, the orthographic set, cuts, rakes and detail lenses',
                all(
                    any(r['title'].startswith(fam) for r in rows)
                    for fam in ('orbit_', 'high_', 'ortho_', 'section_at_', 'rake_', 'detail_')
                ),
                sorted({r['title'].split('_')[0] for r in rows}),
            )
            check(
                '...and NO deck plans or interiors, because a 2 m cube has no level to stand on '
                '(the plan reports the asset, it does not assume a ship)',
                not any(r['title'].startswith(('deckplan_', 'inside_')) for r in rows),
                [r['title'] for r in rows if r['title'].startswith(('deckplan_', 'inside_'))],
            )
            check(
                '...every picture carrying the measurement its camera made',
                all(r['note'] for r in rows),
                [r['title'] for r in rows if not r['note']][:5],
            )
            check(
                '...a close lens says how much of the thing it holds, not how near it stands',
                all('across the frame' in r['note'] for r in rows if r['title'].startswith('detail_')),
                [r['note'][:70] for r in rows if r['title'].startswith('detail_')][:2],
            )
            check(
                '...the folder holds index.html and the contact sheets',
                os.path.isfile(os.path.join(pf.get('dir') or '', 'index.html'))
                and (pf.get('sheets') or [])
                and os.path.isfile(pf['sheets'][0]),
                pf.get('sheets'),
            )
            aud = after.get('audit') or {}
            check(
                'the surface audit measured every mesh',
                any(m['name'] == 'box' for m in aud.get('meshes') or []),
                aud.get('meshes'),
            )
            check(
                '...and said so in findings a model can act on',
                any('NO MATERIAL' in f or 'material(s) in all' in f for f in aud.get('findings') or []),
                aud.get('findings'),
            )
            check(
                'a mesh row carries what a curve is judged by',
                all(
                    k in (aud.get('meshes') or [{}])[0]
                    for k in ('smooth_pct', 'max_bend_deg', 'unfair_pct', 'corner_pct', 'open_edges')
                ),
                (aud.get('meshes') or [{}])[0],
            )
            gotp = server_ext('reference_model', 'preview', {'m': MID, 'p': 0})
            check(
                'the route serves a portfolio picture',
                isinstance(gotp, dict) and len(gotp.get('bytes') or b'') > 1000,
                str(gotp)[:120],
            )
            check(
                '...and refuses a negative index, which Python would read as the last one',
                not (server_ext('reference_model', 'preview', {'m': MID, 'p': -1}) or {}).get('ok', True),
            )
            check(
                '...and one past the end',
                not (server_ext('reference_model', 'preview', {'m': MID, 'p': len(rows) + 5}) or {}).get('ok', True),
            )
            check(
                'the route serves a portfolio contact sheet',
                len((server_ext('reference_model', 'preview', {'m': MID, 'ps': 0}) or {}).get('bytes') or b'') > 1000,
            )

            # ── EXTEND: add to what is built, do not rewrite it ─────────
            out_x, _ = assistant(
                'build_reference_asset',
                {
                    'model': MID,
                    'script': 'import bpy\n'
                    'bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=2, location=(3,0,1))\n'
                    "bpy.context.active_object.name = 'mast'\n",
                    'name': 'probe asset',
                    'extend': True,
                    'portfolio': False,
                    'inspect': False,
                    'check': False,
                },
                drawing=dr,
            )
            ext_rec = R.read(MID)['asset'] or {}
            check(
                'extend runs the script ON the asset already built, keeping what was there',
                'built "probe asset"' in str(out_x) and (ext_rec.get('dims') or [0])[0] > 3.0,
                (str(out_x)[:160], ext_rec.get('dims')),
            )
            check(
                '...the BASE script is not overwritten by the patch',
                ext_rec.get('script', '').startswith('import bpy, bmesh'),
                ext_rec.get('script', '')[:40],
            )
            check(
                '...and the patch is kept beside it, in order',
                len(ext_rec.get('edits') or []) == 1 and 'primitive_cylinder_add' in ext_rec['edits'][0]['script'],
                ext_rec.get('edits'),
            )
            src_out, _ = assistant('view_build_script', {'model': MID}, drawing=dr)
            check(
                'view_build_script hands back the base AND every edit, so a fix extends what exists',
                'import bpy, bmesh' in str(src_out)
                and 'EDIT 1' in str(src_out)
                and 'primitive_cylinder_add' in str(src_out),
                str(src_out)[:200],
            )
            find_out, _ = assistant('view_build_script', {'model': MID, 'find': 'cylinder'}, drawing=dr)
            check(
                '...and find= returns just the lines that matter, numbered',
                'primitive_cylinder_add' in str(find_out) and 'matching "cylinder"' in str(find_out),
            )

            # ── the set has to be REACHABLE, not just written ───────────
            pub = R.public(R.read(MID))['asset']
            check(
                'the tab payload offers every inspection picture as a URL',
                len(pub.get('inspect_urls') or []) == len(shots),
                [u['url'] for u in (pub.get('inspect_urls') or [])],
            )
            check(
                '...each carrying what its camera measured', all(u.get('note') for u in (pub.get('inspect_urls') or []))
            )
            check(
                '...and the ten-up sheet',
                bool(pub.get('sheet_url')) and os.path.isfile((R.read(MID)['asset'] or {}).get('sheet') or ''),
                pub.get('sheet_url'),
            )
            # portfolio_dir is the ONE deliberate path in the payload: the
            # folder is the deliverable and the operator has to be told where
            # it is. Everything else that looks like a path is a leak.
            _leak = [
                k
                for k, v in pub.items()
                if isinstance(v, str) and k != 'portfolio_dir' and (v.startswith('/home/') or v.startswith(HERE))
            ]
            check('the payload leaks no filesystem path but the portfolio folder it names on purpose', not _leak, _leak)
            check(
                '...and names the built files without their directories',
                pub.get('glb') == os.path.basename(pub.get('glb') or 'x/y'),
                pub.get('glb'),
            )
            got0 = server_ext('reference_model', 'preview', {'m': MID, 'n': 0})
            check(
                'the route serves an inspection picture',
                isinstance(got0, dict) and len(got0.get('bytes') or b'') > 1000,
                str(got0)[:120],
            )
            check(
                '...and refuses one past the end',
                not (server_ext('reference_model', 'preview', {'m': MID, 'n': len(shots)}) or {}).get('ok', True),
            )
            # Python would read k=-1 as the LAST check — a picture the caller
            # never asked for, and a quiet way past an index bound.
            check(
                '...and refuses a NEGATIVE index instead of wrapping to the last one',
                not (server_ext('reference_model', 'preview', {'m': MID, 'k': -1}) or {}).get('ok', True),
            )
            sheet = server_ext('reference_model', 'preview', {'m': MID, 's': 1})
            check(
                'the route serves the ten-up sheet',
                isinstance(sheet, dict) and len(sheet.get('bytes') or b'') > 10000,
                str(sheet)[:120],
            )

            check(
                'the reply lists what every camera measured',
                'THE INSPECTION SET' in s and 'standing on the surface at' in s,
                s[-600:],
            )
            check(
                '...and asks the six questions the pictures exist to answer',
                'hanging in the air' in s and 'A no is a fix' in s,
                s[-400:],
            )
            check(
                'the reference plane did NOT end up in the asset',
                (after.get('dims') or [9, 9, 9])[0] < 5,
                after.get('dims'),
            )
            # the two placements, read back from what Blender printed
            loc = next((l for l in (after.get('script') and s or '').splitlines() if 'PLANE_LOC' in l), '')
            loc = next((l for l in s.splitlines() if 'PLANE_LOC' in l), '')
            sx = next((l for l in s.splitlines() if 'PLANE_SX' in l), '')
            check('the mirrored plate has a negative x scale', sx and float(sx.split()[1]) < 0, sx)
            if loc:
                x, y, z = (float(v) for v in loc.split()[1:4])
                # datum 0.48,0.06 of a 23.5 m wide plate, laid as view_side
                # (u -> +X, v -> +Z): the origin must sit LEFT of and BELOW centre
                check('the datum lifted the plate so its datum point is at the origin', z > 3.0, f'z={z}')
                check('the datum shifted it along the length too', abs(x) > 0.1, f'x={x}')

            placed, dr2 = assistant('place_reference_asset', {'model': MID, 'cell': 'F12'}, drawing=dr)
            check('the built asset places into the drawing', 'placed ' in str(placed), str(placed)[:200])
            check(
                "...as the studio's ordinary asset kind",
                any(o['kind'] == 'asset' for o in dr2.objs),
                [o['kind'] for o in dr2.objs],
            )
            rec2 = next(o for o in dr2.objs if o['kind'] == 'asset')
            check(
                '...carrying its pack and measured size',
                rec2['p']['pack'].startswith('zyg_reference/') and rec2['p']['bw'] > 0,
                rec2['p'],
            )
            from zyg_workflows import architecture_assets as AA

            AA._CACHE['data'] = None
            cat = AA.catalogue()
            check(
                'the pack is accepted by the asset catalogue, not refused',
                any(p['id'] == rec2['p']['pack'] for p in cat['packs']),
                [r for r in cat['refused'] if 'zyg_reference' in r['pack']],
            )
            # 2026-09-23: the pack named its GLB after the reference MODEL while
            # the placer quoted the ASSET name, so every placement resolved to
            # nothing and the studio drew a 12-triangle placeholder crate — a
            # whole ship that looked like a fault in the loader. The id has to
            # RESOLVE, not merely be well formed.
            check(
                'the placed id resolves to a real file on disk',
                AA.resolve(rec2['p']['pack'], rec2['p']['item']) is not None,
                f'{rec2["p"]["pack"]}|{rec2["p"]["item"]} -> None',
            )
            # 2026-09-23: /inspect/arch-asset/ is max-age=86400 with no ETag, so
            # a REBUILT asset at the same path stayed behind the browser's cache
            # for a day — the operator reloaded and saw the old ship. The url
            # the tab is given has to move when the bytes do.
            want = f'{rec2["p"]["pack"]}|{rec2["p"]["item"]}'
            item = next((i for g in cat['groups'] for i in g['items'] if i['id'] == want), None)
            check(
                'the catalogue hands the tab a VERSIONED url',
                item and '?v=' in (item.get('uv') or ''),
                item and item.get('uv'),
            )
            check(
                "...while 'u' stays a bare path for the build scripts that join it onto PACKS_ROOT",
                item and '?' not in (item.get('u') or ''),
                item and item.get('u'),
            )
            _before = item.get('uv')
            os.utime(AA.resolve(rec2['p']['pack'], rec2['p']['item']), (1790000000, 1790000000))
            AA._CACHE['data'] = None
            cat2 = AA.catalogue()
            item2 = next((i for g in cat2['groups'] for i in g['items'] if i['id'] == want), None)
            check(
                '...and it CHANGES when the file is overwritten in place',
                item2 and item2.get('uv') != _before,
                f'{_before} -> {item2 and item2.get("uv")}',
            )

    # ── the tab ──────────────────────────────────────────────────────────────
    print('\n== the tab ==')
    r = browser_eval("""() => {
      const o = {};
      AR.assist.open = false; arAssistRender();
      const before = document.getElementById('ar-refrail');
      o.hidden_with_panel = !before || !before.classList.contains('on');
      AR.assist.open = true; arAssistRender();
      const rail = document.getElementById('ar-refrail');
      o.exists = !!rail;
      o.shown = !!rail && rail.classList.contains('on');
      o.icons = rail ? rail.querySelectorAll('[data-reftool]').length : 0;
      const p = document.getElementById('ar-assist').getBoundingClientRect();
      const b = rail.getBoundingClientRect();
      o.right_of_panel = b.left >= p.right;
      o.gap = Math.round(b.left - p.right);
      o.top_aligned = Math.abs(b.top - p.top) < 2;
      const opts = document.querySelector('.ar-opts');
      o.clears_option_strip = !opts || opts.getBoundingClientRect().left >= b.right;
      const svg = rail.querySelector('[data-reftool] svg');
      o.icon_drawn = !!svg && svg.querySelectorAll('path,circle').length > 0;
      o.icon_is_svg_not_text = !!svg && (rail.textContent || '').replace(/REF|\\d/g, '').trim() === '';
      return o;
    }""")
    v = r['value']
    check('the rail is hidden while the chat panel is', v['hidden_with_panel'])
    check('the rail appears with the chat panel', v['exists'] and v['shown'])
    check('it holds exactly one icon for now', v['icons'] == 1, v['icons'])
    check('it sits against the RIGHT side of the panel', v['right_of_panel'] and 0 <= v['gap'] <= 20, v['gap'])
    check('...top-aligned with it', v['top_aligned'])
    check('the option strip was pushed clear of it', v['clears_option_strip'])
    check('the icon is drawn SVG, not a character', v['icon_drawn'] and v['icon_is_svg_not_text'])
    check('no page errors', not r['errors'], r['errors'][:3])

    r2 = browser_eval("""() => {
      AR.assist.open = true; arAssistRender();
      window.refmOpen();
      return new Promise(res => setTimeout(() => {
        const sheet = document.getElementById('ar-sheet');
        const rail = document.getElementById('ar-refrail');
        res({shown: !!sheet && sheet.style.display !== 'none',
             title: (sheet.querySelector('.hd span') || {}).textContent,
             has_picker: !!document.getElementById('refm-pick'),
             has_drop: !!document.getElementById('refm-drop'),
             has_dims: !!document.getElementById('refm-length_m'),
             icon_lit: !!rail.querySelector('[data-reftool="refmodel"].on')});
      }, 1600));
    }""")
    v2 = r2['value']
    check('the icon opens a sheet', v2['shown'] and v2['title'] == 'Reference model', v2)
    check('the sheet has the model picker', v2['has_picker'])
    check('the sheet takes pictures', v2['has_drop'])
    check('the sheet takes the measured dimensions', v2['has_dims'])
    check('the icon is lit while its sheet is open', v2['icon_lit'])
    check('no page errors opening it', not r2['errors'], r2['errors'][:3])

finally:
    R.set_current(MID)
    R.delete(MID)
    # 2026-09-23: this teardown is how current.json came to name a model that
    # was not there — the rail then showed NO model beside a live one, and
    # resolve('') turned "the one the operator has open" into "which ship?".
    check(
        'deleting the open model lets go of it, so the rail does not go blank',
        R._cur_id_raw() != MID and R.current() == '',
        R._cur_id_raw(),
    )  # noqa: SLF001
    import shutil

    shutil.rmtree(os.path.join(R.PACKS_DIR, 'probe-reference'), ignore_errors=True)
    print('\n(probe model and its pack removed)')

finish()
