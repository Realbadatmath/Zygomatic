# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""reference_model.build — the tools that look at a reference and build it: list_reference_models, view_reference and build_reference_asset with its pack writer.

Moved verbatim from reference_model.py (lines 293-744) by the 2026-10 modularization split;
no logic, constant or comment was changed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import logging as _zyg_logging
from zyg_workflows.arch_assistant_ext.reference_model import build_stages as _stages
from zyg_workflows.arch_assistant_ext.reference_model.helpers import (
    BLENDER,
    BUILDER,
    BUILD_TIMEOUT,
    Drawing,
    HERE,
    INSPECT_CHECKLIST,
    PORTFOLIO_CHECKLIST,
    R,
    Reply,
    _BlenderLock,
    _num,
    _resolve,
    _scale_note,
    _thumb,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.reference_model')


# ── tools ────────────────────────────────────────────────────────────────────
def t_list_reference_models(d: Drawing, a, limit=12):
    models = R.models()
    if not models:
        return (
            'There are no reference models. The operator adds one from the picture icon in the rail beside '
            'the chat panel: a name, the photographs and plans, and at least one real dimension.'
        )
    cur = R.current()
    lines = [('* ' if m['id'] == cur else '  ') + R.brief(m, verbose=False) for m in models[: int(_num(limit, 12))]]
    return (
        'Reference models (* = the one the operator has open):\n'
        + '\n'.join(lines)
        + '\n\n'
        + R.LAYOUT
        + '\nUse view_reference to LOOK at the pictures before you model anything.'
    )


def t_view_reference(d: Drawing, a, model='', role='', which='', limit=3):
    rec, err = _resolve(model)
    if rec is None:
        return err
    imgs = rec.get('images') or []
    if not imgs:
        return f'refused: "{rec["name"]}" has no pictures yet'
    want = (
        [i for i in imgs if str(i.get('id')) == str(which)]
        if which
        else [i for i in imgs if not role or i.get('role') == role]
    )
    if not want:
        have = ', '.join(sorted({str(i.get('role')) for i in imgs}))
        return f'refused: no picture with role "{role}" or id "{which}" — this reference has: {have}'
    order = {r: n for n, r in enumerate(R.ROLE_ORDER)}
    want.sort(key=lambda i: order.get(i.get('role'), 99))
    n = max(1, min(3, int(_num(limit, 3))))
    want = want[:n]
    blocks = []
    for i in want:
        b = R.image_b64(rec['id'], i['id'])
        if b:
            blocks.append(b)
    head = (
        f'"{rec["name"]}" — {len(blocks)} picture'
        + ('' if len(blocks) == 1 else 's')
        + ', in this order: '
        + '; '.join(
            f'{i["id"]} [{i.get("role")}] {R.ROLES.get(i.get("role"), {}).get("label", "")}'
            + (f' — {i["note"]}' if i.get('note') else '')
            for i in want
        )
    )
    body = (
        head
        + '\n'
        + R.LAYOUT
        + _scale_note(rec)
        + '\nA view role tells you where the camera stood; a "photo" does not, so never take geometry off a '
        'photo that a view or a measurement could give you.'
    )
    if not blocks:
        return body + '\n(the pictures could not be encoded)'
    return Reply(text=body, images=blocks)


def _write_pack(rec: dict, glb: str, dims, tris: int, item: str) -> str:
    """Copy the built GLB into a mesh pack so search_assets / place_asset can
    find it like any other model. The licence line is the honest one: this was
    built HERE, from the operator's own reference material.

    The FILE is named after the asset, not the reference model, because the
    catalogue's item id is the glb's stem and place_reference_asset quotes the
    asset name. Named after the model, every placement resolved to nothing and
    the studio drew a placeholder crate — a whole ship that looked like a bug
    in the loader."""
    slug = R.slug(rec.get('name'))
    pdir = os.path.join(R.PACKS_DIR, slug)
    os.makedirs(pdir, exist_ok=True)
    dest = os.path.join(pdir, item + '.glb')
    shutil.copy2(glb, dest)
    with open(os.path.join(pdir, 'PROVENANCE.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'pack': f'zyg_reference/{slug}',
                'license': 'OWN-WORK',
                'license_quote': (
                    'Built on this machine by Architecture Studio from reference model '
                    f'{rec["id"]} ("{rec.get("name")}"), which holds the operator\'s own '
                    'pictures. No third-party mesh is embedded. The operator owns it.'
                ),
                'source': f'reference model {rec["id"]}',
                'subject': rec.get('subject') or '',
                'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
            },
            fh,
            indent=1,
        )
    # metres, glTF axes (Y-up): the exporter wrote yup, so Blender (x, y, z) is
    # glTF (x, z, y) in EXTENT terms.
    if dims and len(dims) == 3:
        with open(os.path.join(pdir, 'DIMENSIONS.json'), 'w', encoding='utf-8') as fh:
            json.dump(
                {
                    'dims': {item + '.glb': [round(dims[0], 4), round(dims[2], 4), round(dims[1], 4)]},
                    'tris': {item + '.glb': int(tris or 0)},
                },
                fh,
                indent=1,
            )
    return f'zyg_reference/{slug}'


def t_build_reference_asset(
    d: Drawing,
    a,
    script,
    model='',
    name='',
    views='iso',
    check=True,
    engine='workbench',
    width=1280,
    height=720,
    inspect=True,
    portfolio=True,
    extend=False,
):
    if not os.path.exists(BLENDER):
        return f'refused: Blender is not at {BLENDER}'
    if not os.path.exists(BUILDER):
        return 'refused: arch_reference_build/entry.py is missing'
    rec, err = _resolve(model)
    if rec is None:
        return err
    spec, refusal = _stages.validate_build_request(script, engine, views)
    if spec is None:
        return refusal
    target, refusal = _stages.extend_target(rec, name, extend)
    if target is None:
        return refusal
    name = target.name

    work, base = _stages.prepare_work_dir(rec, spec.src, name)
    cmd = _stages.blender_command(
        work=work,
        base=base,
        spec=spec,
        width=width,
        height=height,
        prev=target.blend,
        check=check,
        inspect=inspect,
        portfolio=portfolio,
    )
    try:
        with _BlenderLock():
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    except subprocess.TimeoutExpired:
        return f'refused: the Blender build did not finish inside {BUILD_TIMEOUT}s — build less per call'
    out = (p.stdout or '') + (('\n[stderr] ' + p.stderr[-800:]) if p.returncode != 0 and p.stderr else '')
    res, no_result = _stages.parse_build_result(out)
    if res is None:
        return no_result
    log = '\n'.join(res.get('log') or [])

    printed = str(res.get('stdout') or '').strip()
    failed = _stages.build_error_text(res, log, printed)
    if failed:
        return failed

    outs = _stages.keep_build_outputs(rec, res, name, inspect=inspect, check=check)
    insp = outs.inspect
    pf, log = _stages.portfolio_folder(rec, res, log)

    # The model is handed the CONTACT SHEETS rather than forty separate frames:
    # forty pictures is not a bigger check than four sheets, it is the same
    # check at four times the cost, and the faults show when the views are seen
    # TOGETHER anyway. The full-size files are in the folder for the eye that
    # wants one.
    images, titles = [], []
    shown = outs.shown
    shown += [{'path': x, 'title': f'PORTFOLIO contact sheet {i + 1}'} for i, x in enumerate(pf.get('sheets') or [])]
    for im in shown[:14]:
        b = _thumb(im.get('path') or '')
        if b:
            images.append(b)
            titles.append(im.get('title') or '')

    pack = ''
    item = R.slug(name or rec.get('name'))
    if outs.kept.get('glb'):
        try:
            pack = _write_pack(rec, outs.kept['glb'], res.get('dims'), res.get('tris') or 0, item)
        except OSError as e:
            log += f'\nthe asset was NOT published to the pack catalogue: {e}'

    rec['asset'] = _stages.asset_record(
        rec,
        res,
        outs,
        item=item,
        pack=pack,
        pf=pf,
        inspect=inspect,
        target=target,
        src=spec.src,
    )
    R._write(rec)  # noqa: SLF001 — same package, one store
    shutil.rmtree(work, ignore_errors=True)

    txt = _stages.summary_text(
        rec,
        res,
        outs,
        name=name,
        pack=pack,
        pf=pf,
        titles=titles,
        printed=printed,
        log=log,
    )
    if images:
        for im in res.get('images') or []:
            if im.get('check'):
                txt += (
                    '\nThe overlay is the CHECK: the blue is your geometry, the lines underneath are the '
                    "operator's plan, in the plan's own view. Where they disagree, the geometry is wrong."
                )
                break
        if insp:
            txt += '\n' + INSPECT_CHECKLIST
        if pf:
            txt += '\n\n' + PORTFOLIO_CHECKLIST
        return Reply(text=txt, images=images)
    return txt
