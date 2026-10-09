# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.portfolio — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    BLENDER,
    BLEND_DIR,
    Drawing,
    HERE,
    _num,
    hashlib,
    json,
    os,
    subprocess,
    time,
)
from zyg_workflows.arch_assistant_ext.blender_power.build import (
    _blender_ok,
    _build,
)
from zyg_workflows.arch_assistant_ext.blender_power.second_pass import (
    Reply,
    _thumb_jpeg,
)
from zyg_workflows.arch_assistant_ext.blender_power.present import (
    present_sig,
)

# ── THE PORTFOLIO for a DRAWING (2026-09-23) ─────────────────────────────────
# The operator's standing rule, given the day the reference assets got theirs:
# "i said 10 before but after every drawing, make sure ai assistant delivers
# portfolio folder with 40+ images from projects". present()'s five views are
# working drawings — they show the approach, one cut and the lobby, and a
# building can pass all five with an unlit back, a storey no one can reach and
# a facade that is one flat material.
#
# The camera plan is NOT written again here. arch_reference_build.py already
# generates one from the geometry it is given — orbit, orthographic set, cuts
# at six stations, a plan cut and two interior views per LEVEL (a storey is a
# level), raking shots for fairness, close lenses — and it renders the whole
# plan in ONE Blender launch. present() takes five launches for five frames;
# fifty that way would be fifty. So the drawing's .blend is handed to that
# builder in --from-blend mode, which never writes to it.
REF_BUILDER = os.path.join(HERE, 'arch_reference_build', 'entry.py')
PORTFOLIO_TIMEOUT = int(os.environ.get('ZYG_ARCH_PORTFOLIO_TIMEOUT', '1800'))
PORTFOLIO_CHECKLIST = (
    'THE PORTFOLIO IS THE HAND-OVER. Open the contact sheets and answer these before done(), naming the '
    'picture each answer comes from:\n'
    ' 1 OPENINGS: is every door, window and stair a hole that goes THROUGH? The plan cuts and the sections '
    'show it; an applied panel does not.\n'
    ' 2 INSIDE: does every level show a space that is used, or an empty slab sandwich?\n'
    ' 3 REACH: can a person get to every level in the interior views — a stair, a lift, a ladder?\n'
    ' 4 CURVES: in the orthographic views and the raking shots, does every line run FAIR?\n'
    ' 5 MATERIALS: read the audit findings — a mesh with no material, an untouched default or a big '
    'flat-shaded curve is a defect.\n'
    ' 6 SCALE: against the 1.75 m red figure inside, are the heights right?\n'
    ' 7 MEETING: do the parts MEET — nothing floating, nothing buried, no gap at a joint?'
)


def _pf_store():
    """arch_reference, imported here and nowhere near arch_assistant: the store
    owns the portfolio folder and imports nothing from the assistant."""
    from zyg_workflows import arch_reference

    return arch_reference


def t_portfolio(d: Drawing, a, width=1280, height=720):
    bad = _blender_ok()
    if bad:
        return bad
    if not d.objs:
        return 'refused: the drawing is empty — there is nothing to photograph'
    if not os.path.exists(REF_BUILDER):
        return 'refused: arch_reference_build/entry.py is missing'
    w = max(320, min(2560, int(_num(width, 1280) or 1280)))
    h = max(240, min(1440, int(_num(height, 720) or 720)))
    # No `n`. This call writes THE DELIVERED FOLDER, and the operator's floor is
    # 40+ pictures; a thinned run would quietly replace a full set with a short
    # one (it did, on the reference side, on 2026-09-24). The contact sheets
    # handed back here are the cheap look.
    want = 0
    try:
        blend, note = _build(d)
    except ValueError as ex:
        return f'refused: {ex}'
    R = _pf_store()
    base = os.path.join(BLEND_DIR, f'pf-{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}')
    cmd = (
        [
            BLENDER,
            '-b',
            '--factory-startup',
            '--python',
            REF_BUILDER,
            '--',
            '--out',
            base,
            '--from-blend',
            blend,
            '--portfolio',
        ]
        + ([str(want)] if want else [])
        + ['--portfolio-engine', 'eevee', '--width', str(w), '--height', str(h)]
    )
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=PORTFOLIO_TIMEOUT, cwd=HERE)
    except subprocess.TimeoutExpired:
        return (
            f'refused: the portfolio did not finish inside {PORTFOLIO_TIMEOUT}s — ask for fewer pictures '
            'with n=24, or smaller ones'
        )
    out = (p.stdout or '') + (('\n[stderr] ' + p.stderr[-600:]) if p.returncode != 0 and p.stderr else '')
    line = ''
    for ln in out.splitlines()[::-1]:
        if ln.startswith('REFBUILD_JSON '):
            line = ln[len('REFBUILD_JSON ') :]
            break
    if not line:
        return (
            'the portfolio produced no result line — Blender output below\n'
            + '\n'.join(l for l in out.splitlines() if l.strip())[-1500:]
        )
    res = json.loads(line)
    if not res.get('ok'):
        return 'the portfolio failed: ' + str(res.get('error') or 'unknown')[-1500:]
    shots = res.get('portfolio') or []
    if not shots:
        return 'the portfolio pass took no pictures — ' + '\n'.join(res.get('log') or [])[-800:]
    # the folder is keyed on the DRAWING's name, so a drawing photographed twice
    # overwrites its own folder instead of growing a second one
    rid = hashlib.sha1((d.name or 'drawing').encode('utf-8'), usedforsecurity=False).hexdigest()[:12]
    dims = res.get('dims') or [0, 0, 0]
    pf = R.write_portfolio(
        {'id': rid, 'name': f'{d.name or "drawing"} (drawing)'},
        shots,
        res.get('audit') or {},
        {
            'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'engine': 'eevee',
            'dims': f'{dims[0]:g} x {dims[1]:g} x {dims[2]:g} m',
            'tris': res.get('tris') or 0,
        },
    )
    d.ext['portfolio'] = {
        'sig': present_sig(d),
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'dir': pf['dir'],
        'n': pf['n'],
        'planned': pf['planned'],
    }
    audit = res.get('audit') or {}
    txt = (
        f'THE PORTFOLIO of "{d.name}" — {pf["n"]} pictures of {pf["planned"]} planned ({note}), in\n'
        f'  {pf["dir"]}\n  index.html opens every one at full size with the measurement under it.\n'
        + '\n'.join(
            f'  {i + 1:2d} {r["title"]}: {r["note"]}' + ('' if r['file'] else '   [NO PICTURE]')
            for i, r in enumerate(pf.get('shots') or [])
        )
        + (
            '\n\nTHE SURFACE AUDIT — curves and materials, measured off the mesh:\n'
            + '\n'.join('  ! ' + str(f) for f in audit.get('findings') or [])
            if audit.get('findings')
            else ''
        )
        + '\n\n'
        + PORTFOLIO_CHECKLIST
    )
    images = []
    for sheet in (pf.get('sheets') or [])[:5]:
        t = _thumb_jpeg(sheet)
        if t:
            images.append(t)
    return Reply({'text': txt, 'images': images}) if images else txt
