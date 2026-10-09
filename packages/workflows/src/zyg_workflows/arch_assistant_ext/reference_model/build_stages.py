# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of t_build_reference_asset, each with explicit parameters.

Extracted from reference_model/build.py by the 2026-10 function-size split: the
337-line tool is now an orchestrator that calls these in the same order, with the
same refusal lines, log text and side effects. Nothing here talks to Blender; the
subprocess call stays in the orchestrator, so every stage below is testable on
plain dicts and a temporary directory.
"""

from __future__ import annotations

import glob
import json
import logging as _zyg_logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field

from zyg_workflows.arch_assistant_ext.reference_model.helpers import (
    BLENDER,
    BUILDER,
    INSPECT_N,
    MAX_SCRIPT,
    R,
    WORK_DIR,
    _audit_text,
    _contact_sheet,
    _num,
    _portfolio_folder,
    _scale_note,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.reference_model')

ENGINES = ('workbench', 'eevee')
VIEW_NAMES = ('iso', 'side', 'other_side', 'front', 'back', 'top', 'bottom')


@dataclass
class BuildSpec:
    """One validated build request: the script text, the engine, the views."""

    src: str
    engine: str
    views: list[str]


@dataclass
class ExtendTarget:
    """What an extend=true build inherits from the asset already on disk."""

    blend: str
    name: str
    script: str
    edits: list[dict]


@dataclass
class BuildOutputs:
    """The deliverables one build left beside the reference model."""

    kept: dict = field(default_factory=dict)
    preview: str = ''
    checks: list[dict] = field(default_factory=list)
    inspect: list[dict] = field(default_factory=list)
    sheet: str = ''
    shown: list[dict] = field(default_factory=list)


def validate_build_request(script, engine, views) -> tuple[BuildSpec | None, str]:
    """Check the script text, the engine name and the view list of a request.

    Returns (spec, '') when the request can be built, else (None, refusal) with the
    refusal line the tool returns to the model, in the tool's original order: the
    script first, then the engine, then the views.
    """
    src = str(script or '').strip()
    if not src:
        return None, 'refused: script is empty — pass the bpy Python that builds the asset'
    if len(src) > MAX_SCRIPT:
        return None, f'refused: the script is over {MAX_SCRIPT} characters — send a shorter one'
    eng = str(engine or 'workbench').lower()
    if eng not in ENGINES:
        return None, 'refused: engine must be workbench or eevee'
    vs = [v.strip() for v in str(views or 'iso').replace(' ', ',').split(',') if v.strip()]
    bad = [v for v in vs if v not in VIEW_NAMES]
    if bad:
        return None, (
            'refused: view ' + ', '.join(bad) + ' is not one of iso, side, other_side, front, back, top, bottom'
        )
    return BuildSpec(src=src, engine=eng, views=vs), ''


def extend_target(rec: dict, name, extend) -> tuple[ExtendTarget | None, str]:
    """Resolve what an extend= build runs on top of.

    EXTEND: run this script on top of the asset that is already built, rather
    than in an empty scene. Adding a door to a ship must not mean re-emitting
    the ship: detail is lost between rounds that way, and the operator's fix
    list is longer than one script.

    EXTEND KEEPS THE ASSET'S OWN NAME. 2026-09-24: a round of stern windows
    was built with extend=true and no name=, so `name` fell back to the
    MODEL's name, the build was saved as a second .blend and published as a
    SECOND catalogue item — and the operator's drawing, which places the
    first item, went on showing the ship without the windows. An extend adds
    to a thing that already exists; it may not quietly fork it.

    Returns (target, '') — target.blend is '' for a plain build — or (None, refusal)
    when extend=true and there is nothing on disk to extend.
    """
    prev = ((rec.get('asset') or {}).get('blend') or '') if extend else ''
    if prev and not str(name or '').strip():
        name = (rec.get('asset') or {}).get('item') or ''
    prev_script = (rec.get('asset') or {}).get('script') or ''
    prev_edits = list((rec.get('asset') or {}).get('edits') or [])
    if extend and (not prev or not os.path.exists(prev)):
        return None, (
            'refused: extend=true, but there is no built asset on disk to extend — build it once with '
            'extend=false (the whole script in an empty scene), then extend it'
        )
    return ExtendTarget(blend=prev, name=name, script=prev_script, edits=prev_edits), ''


def prepare_work_dir(rec: dict, src: str, name: str) -> tuple[str, str]:
    """Lay out one build's work directory: ref.json and script.py.

    Returns (work dir, output base) — the base path, without extension, the
    builder writes the .blend, the .glb and the renders beside.
    """
    stamp = time.strftime('%Y%m%d-%H%M%S')
    work = os.path.join(WORK_DIR, f'{rec["id"]}-{stamp}')
    os.makedirs(work, exist_ok=True)
    full = dict(rec)
    full['images'] = [
        dict(i, path=os.path.join(R.model_dir(rec['id']), 'images', i['file'])) for i in rec.get('images') or []
    ]
    with open(os.path.join(work, 'ref.json'), 'w', encoding='utf-8') as fh:
        json.dump(full, fh)
    with open(os.path.join(work, 'script.py'), 'w', encoding='utf-8') as fh:
        fh.write(src)
    return work, os.path.join(work, R.slug(name or rec.get('name')))


def blender_command(
    *,
    work: str,
    base: str,
    spec: BuildSpec,
    width,
    height,
    prev: str,
    check: bool,
    inspect: bool,
    portfolio: bool,
) -> list[str]:
    """Build the background-Blender argv for one reference build.

    THE INSPECTION SET, 2026-09-23, the operator's standing rule: "when the ai
    assistant is finished with a drawing, have it take 10 screenshots from
    different angles and from within the ship". It is on by DEFAULT, because
    the build this rule came out of passed a single iso view while the decks
    floated two metres over the sides and the hull never touched its keel.

    THE PORTFOLIO, 2026-09-23, the operator's standing rule after the ten:
    "after every drawing, make sure ai assistant delivers portfolio folder
    with 40+ images from projects". On by DEFAULT, and rendered in EEVEE
    whatever the build's own engine is — Workbench has no materials, and half
    of what the portfolio is for is judging the material and the curve.
    """
    cmd = [
        BLENDER,
        '-b',
        '--factory-startup',
        '--python',
        BUILDER,
        '--',
        '--ref',
        os.path.join(work, 'ref.json'),
        '--script',
        os.path.join(work, 'script.py'),
        '--out',
        base,
        '--views',
        ','.join(spec.views[:2]) or 'iso',
        '--engine',
        spec.engine,
        '--width',
        str(max(320, min(2560, int(_num(width, 1280))))),
        '--height',
        str(max(240, min(1440, int(_num(height, 720))))),
    ]
    if prev:
        cmd += ['--edit-blend', prev]
    if check:
        cmd.append('--check')
    if inspect:
        cmd += ['--inspect', str(INSPECT_N)]
    if portfolio:
        cmd += ['--portfolio', '--portfolio-engine', 'eevee']
    return cmd


def parse_build_result(out: str) -> tuple[dict | None, str]:
    """Pull the last REFBUILD_JSON line out of Blender's output.

    Returns (result dict, '') or (None, the text to return to the model) when the
    build printed no result line at all.
    """
    line = ''
    for ln in out.splitlines()[::-1]:
        if ln.startswith('REFBUILD_JSON '):
            line = ln[len('REFBUILD_JSON ') :]
            break
    if not line:
        return None, (
            'the build produced no result line — Blender output below\n--- output ---\n'
            + '\n'.join(ln for ln in out.splitlines() if ln.strip())[-1800:]
        )
    return json.loads(line), ''


def build_error_text(res: dict, log: str, printed: str) -> str:
    """The reply for a build that did not produce geometry, or '' when it did.

    Three failures, in the tool's original order: the script raised inside
    Blender, the builder itself reported an error, or the script ran and left no
    geometry at all (ref_plane scaffolding does not count as the asset).
    """
    if res.get('script_error'):
        return (
            'the script RAISED inside Blender — nothing was saved. Traceback:\n'
            + str(res['script_error'])[-2200:]
            + (f'\n--- what it printed first ---\n{printed[-1200:]}' if printed else '')
            + (f'\n--- log ---\n{log}' if log else '')
        )
    if not res.get('ok'):
        return 'the build failed: ' + str(res.get('error') or 'unknown')[-1800:]
    if not res.get('objects'):
        return (
            'the script ran but left NO geometry — every object it made was reference scaffolding, or it '
            'made none. ref_plane objects do not count as the asset.\n' + log
        )
    return ''


def sweep_stale_previews(adir: str, *, inspect: bool, check: bool) -> list[str]:
    """Delete the preview sets THIS build is about to re-shoot, and only those.

    A rebuild with a different view set used to leave the OLD renders beside
    the new ones: after one reorder the folder held 16 inspect-*.png, six of
    them stale, and nothing in the names said which build they came from. The
    record points at the new ones; the folder has to agree with the record.
    ... and it only sweeps what it is about to REPLACE. Sweeping the
    inspection set on a build that did not take one deleted the files while
    the record still pointed at them: the rail's sheet went 404 and the work
    looked lost. A set is swept by the build that re-shoots it, and by no
    other.

    Returns the paths it removed.
    """
    stale = []
    if inspect:
        stale += glob.glob(os.path.join(adir, 'inspect-[0-9]*.png'))
        stale += glob.glob(os.path.join(adir, 'inspection-sheet.png'))
    if check:
        stale += glob.glob(os.path.join(adir, 'check-[0-9]*.png'))
    gone = []
    for old_png in stale:
        try:
            os.remove(old_png)
            gone.append(old_png)
        except OSError as _exc:
            _zyg_log.debug('stale preview removal skipped: %s', _exc)
    return gone


def keep_build_outputs(rec: dict, res: dict, name: str, *, inspect: bool, check: bool) -> BuildOutputs:
    """Keep the deliverables beside the reference model, not in the work dir.

    Every render is KEPT beside the asset, not only handed to the model. The
    check overlay is the most useful thing the build produces — it is how the
    operator sees the same error the model saw — and the work directory it
    was written into is swept at the end of this call.

    `name` is the asset name the .blend and .glb are slugged after. The returned
    BuildOutputs carries the kept files, the preview, the check overlays, the
    inspection set, its contact sheet, and `shown` — the pictures, by their work
    dir paths, that the model is handed and has to answer for.
    """
    adir = os.path.join(R.model_dir(rec['id']), 'asset')
    os.makedirs(adir, exist_ok=True)
    kept = {}
    for key, ext in (('blend', '.blend'), ('glb', '.glb')):
        srcp = res.get(key) or ''
        if srcp and os.path.exists(srcp):
            dst = os.path.join(adir, R.slug(name or rec.get('name')) + ext)
            shutil.copy2(srcp, dst)
            kept[key] = dst
    sweep_stale_previews(adir, inspect=inspect, check=check)
    preview, checks, insp = '', [], []
    # the check overlays and the plain preview first, then the inspection set:
    # all of it is KEPT beside the asset, and the pictures the model is handed
    # are the ones it has to answer for below.
    shown = [im for im in (res.get('images') or []) if im.get('check')][:2]
    shown += [im for im in (res.get('images') or []) if not im.get('check') and not im.get('inspect')][:1]
    shown += [im for im in (res.get('images') or []) if im.get('inspect')][:INSPECT_N]
    for n, im in enumerate(res.get('images') or []):
        src2 = im.get('path') or ''
        if not src2 or not os.path.exists(src2):
            if im.get('inspect'):  # a view with no picture still
                insp.append(
                    {
                        'path': '',
                        'title': im.get('title') or '',  # carries its finding
                        'note': im.get('note') or '',
                    }
                )
            continue
        slug2 = re.sub(r'[^a-z0-9]+', '-', str(im.get('title') or 'view').lower()).strip('-')
        if im.get('check'):
            dst2 = os.path.join(adir, f'check-{n}-{slug2}.png')
            shutil.copy2(src2, dst2)
            checks.append({'path': dst2, 'title': im.get('title') or ''})
        elif im.get('portfolio'):
            continue  # the portfolio has its own FOLDER, written below
        elif im.get('inspect'):
            dst2 = os.path.join(adir, f'inspect-{len(insp)}-{slug2}.png')
            shutil.copy2(src2, dst2)
            insp.append({'path': dst2, 'title': im.get('title') or '', 'note': im.get('note') or ''})
        elif not preview:
            preview = os.path.join(adir, 'preview.png')
            shutil.copy2(src2, preview)
    sheet = _contact_sheet(insp, os.path.join(adir, 'inspection-sheet.png')) if insp else ''
    return BuildOutputs(kept=kept, preview=preview, checks=checks, inspect=insp, sheet=sheet, shown=shown)


def portfolio_folder(rec: dict, res: dict, log: str) -> tuple[dict, str]:
    """Write THE PORTFOLIO FOLDER — the deliverable, on disk, where the operator
    opens it: every picture numbered, the contact sheets, index.html, the audit.

    Returns (portfolio record, log). The log gains one line when the folder could
    not be written; the build itself is not failed by it.
    """
    pf: dict = {}
    if res.get('portfolio'):
        dims0 = res.get('dims') or [0, 0, 0]
        try:
            pf = _portfolio_folder(
                rec,
                res['portfolio'],
                res.get('audit') or {},
                {
                    'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'engine': 'eevee',
                    'dims': f'{dims0[0]:g} x {dims0[1]:g} x {dims0[2]:g} m',
                    'tris': res.get('tris') or 0,
                },
            )
        except OSError as e:
            log += f'\nthe portfolio folder could not be written: {e}'
    return pf, log


def asset_record(
    rec: dict,
    res: dict,
    outs: BuildOutputs,
    *,
    item: str,
    pack: str,
    pf: dict,
    inspect: bool,
    target: ExtendTarget,
    src: str,
) -> dict:
    """The asset block to store on the reference model after a build.

    A build that did not take a set does not DELETE the last one. An extend
    with inspect=false / portfolio=false used to replace the whole asset
    record, so the rail lost its inspection pictures and its contact sheet
    while the files sat on disk — the work looked undone because the record
    had forgotten it. Only a set that was actually re-shot replaces its
    predecessor.
    """
    old_asset = rec.get('asset') or {}
    prev = target.blend
    return {
        'blend': outs.kept.get('blend', ''),
        'glb': outs.kept.get('glb', ''),
        'preview': outs.preview or old_asset.get('preview', ''),
        'checks': outs.checks or (old_asset.get('checks') or []),
        'inspect': outs.inspect if inspect else (old_asset.get('inspect') or []),
        'sheet': outs.sheet or old_asset.get('sheet', ''),
        'portfolio': ({k: v for k, v in pf.items() if k != 'shots'} if pf else (old_asset.get('portfolio') or {})),
        'portfolio_shots': ((pf.get('shots') or [])[:60] if pf else (old_asset.get('portfolio_shots') or [])),
        'audit': res.get('audit') or old_asset.get('audit') or {},
        'pack': pack,
        'item': item,
        'dims': res.get('dims'),
        'tris': res.get('tris') or 0,
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
        # The BASE script stays the one that built the thing from an empty
        # scene; every extend is kept beside it in order. Overwriting the
        # base with a twenty-line "cut the doors" patch would lose the ship.
        'script': (target.script if prev else src)[:MAX_SCRIPT],
        'edits': (target.edits + [{'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'script': src[:MAX_SCRIPT]}])[-12:]
        if prev
        else [],
    }


def summary_text(
    rec: dict,
    res: dict,
    outs: BuildOutputs,
    *,
    name: str,
    pack: str,
    pf: dict,
    titles: list[str],
    printed: str,
    log: str,
) -> str:
    """The build report the model reads: what was built, where it is, what to do next."""
    dims = res.get('dims') or [0, 0, 0]
    insp = outs.inspect
    return (
        f'built "{name or rec.get("name")}" from reference {rec["id"]}: {res["objects"]} object'
        + ('' if res['objects'] == 1 else 's')
        + f', {res.get("tris") or 0} triangles, '
        + f'{dims[0]:g} long x {dims[1]:g} wide x {dims[2]:g} tall (metres, length along +X)'
        + _scale_note(rec)
        + (
            f'\nplace it with place_reference_asset(cell=...) — pack {pack}'
            if pack
            else '\n(no GLB, so it cannot be placed in the drawing yet)'
        )
        + (f'\nfiles: {outs.kept.get("blend", "-")}' if outs.kept else '')
        + (f'\npictures, in order: {"; ".join(titles)}' if titles else '')
        + (
            (
                f'\n\nTHE PORTFOLIO — {pf["n"]} pictures of {pf["planned"]} planned, in\n  {pf["dir"]}\n'
                f'  open {os.path.basename(pf.get("index") or "index.html")} in that folder for all of them '
                f'with the measurement under each, or the {len(pf.get("sheets") or [])} contact sheet(s) '
                'handed to you above.'
            )
            if pf
            else ''
        )
        + ('\n\n' + _audit_text(res.get('audit') or {}) if res.get('audit') else '')
        + (
            (
                '\n\nTHE INSPECTION SET — what each camera measured:\n'
                + '\n'.join(f'  {i["title"]}: {i["note"]}' + ('' if i['path'] else '   [NO PICTURE]') for i in insp)
            )
            if insp
            else ''
        )
        + (f'\n--- your script printed ---\n{printed[-2500:]}' if printed else '')
        + (f'\n--- log ---\n{log}' if log else '')
    )
