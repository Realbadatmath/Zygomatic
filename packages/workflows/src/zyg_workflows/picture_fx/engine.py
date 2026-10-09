# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The engine: validating a stack, compiling it, previewing it and the bakes it writes.

`facts()` moved here from the end of the subject section: it is the one function in
that section that reads `list_bakes()`, which lives with the rest of the bake code
below, and a package cannot have subject.py and this module import each other."""

from __future__ import annotations

import json
import os
import re

from zyg_workflows import creature_fx as cfx

from zyg_workflows.picture_fx.constants import BAKE_DIR, NAME_RE, _zyg_log
from zyg_workflows.picture_fx.ops_dock import OP_BY_ID
from zyg_workflows.picture_fx.pixel_tone import _rgba
from zyg_workflows.picture_fx.subject import (
    _char_name,
    _listdir_images,
    bake_dir,
    check_scope,
    images,
    licence_of,
    resolve,
    subject_dir,
)

# ══════════════════════════════════════════════════════════════════════════════
#  THE ENGINE
# ══════════════════════════════════════════════════════════════════════════════


def validate(op_id, raw):
    """Coerce and clamp one op's parameters against its own schema.

    An out-of-schema KEY is dropped rather than passed through. Numbers are
    forced into their declared range, enums must be members, colours must match
    #rrggbb, and free text must match its declared charset. Text from here ends
    up in a diffusion prompt, a JSON sidecar and a recipe; none of those is a
    place to discover that a value was never checked."""
    o = OP_BY_ID.get(op_id)
    if not o:
        raise ValueError(f'unknown op: {op_id}')
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for spec in o['params']:
        k, t, df = spec['k'], spec['t'], spec['df']
        v = raw.get(k, df)
        if t in ('f', 'i'):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = float(df)
            if v != v or v in (float('inf'), float('-inf')):
                v = float(df)
            v = max(float(spec['mn']), min(float(spec['mx']), v))
            out[k] = int(round(v)) if t == 'i' else v
        elif t == 'b':
            out[k] = bool(v) if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'yes', 'on')
        elif t == 'e':
            out[k] = v if v in spec['opts'] else df
        elif t == 'c':
            v = str(v or df)
            out[k] = v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else df
        else:
            v = '' if v is None else str(v).strip()
            out[k] = v if re.fullmatch(spec.get('pat', r'.{0,300}'), v) else df
    return out


def normalise_stack(stack):
    """Clean a whole stack: drop unknown or action ops, validate every parameter.

    Returns ([{op,on,p}], dropped). A silent drop reads as "your stack ran" when
    part of it did not, so what went and why comes back with it."""
    out, dropped = [], []
    for row in stack or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get('op') or '')
        o = OP_BY_ID.get(oid)
        if not o or o['cls'] == 'act':
            dropped.append({'op': oid, 'why': 'no such tool'})
            continue
        out.append({'op': oid, 'on': row.get('on', True) is not False, 'p': validate(oid, row.get('p'))})
    return out, dropped


# The instruction the generative half sends is built the same way
# creature_sheet_service builds one: the clauses, then a KEEP sentence saying
# what must not change. The keep sentence is dropped clause by clause where the
# stack contradicts it — "make her hair red. Same hair colour" is a prompt
# arguing with itself, and that does not fail loudly, it returns the average.
_NEG_BASE = (
    'text, watermark, signature, extra limbs, deformed anatomy, extra fingers, '
    'blurry, lowres, letterbox bars, duplicate subject'
)

_KEEP_DROPS = {
    'identity': {'Subject'},
    'colour': {'Colour'},
    'style': {'Style'},
    'framing': {'Scene'},
}


def keep_sentence(changing=()):
    ch = set(changing or ())
    keeps = []
    if 'identity' not in ch:
        keeps.append('the same person or creature, with the same face and proportions')
    if 'colour' not in ch:
        keeps.append('the same colours')
    if 'framing' not in ch:
        keeps.append('the same framing and composition')
    if 'style' not in ch:
        keeps.append('the same rendering style')
    if not keeps:
        return 'One subject only. No text or watermarks in the image.'
    return 'Keep ' + ', '.join(keeps) + '. One subject only. No text or watermarks in the image.'


def compile_stack(stack, x=None):
    """A stack compiles into an ORDERED pipeline plus one edit instruction.

    Three kinds of step run in stack order:
      pix   Pillow. Instant, and the preview is the result.
      svc   a service (ESRGAN, u2net, a masked repair). Not previewable.
      edit  the merged Qwen instruction, placed where the FIRST generative op
            sits — because a deterministic op above it changes the image the
            model is handed and one below it changes the result, and collapsing
            that distinction is the one thing this compiler must not do."""
    x = x or {}
    rows, dropped = normalise_stack(stack)
    live = [r for r in rows if r['on']]
    clauses, negs, steps = [], [], []
    edit_placed = False
    for r in live:
        o = OP_BY_ID[r['op']]
        if o['cls'] == 'pix':
            steps.append({'kind': 'pix', 'row': r})
            continue
        if o['cls'] == 'svc':
            steps.append({'kind': 'svc', 'row': r, 'svc': o['svc']})
            continue
        cl = ''
        if o['fn']:
            try:
                cl = (o['fn'](r['p'], x) or '').strip().rstrip('.')
            except Exception as ex:  # noqa: BLE001
                dropped.append({'op': r['op'], 'why': f'{type(ex).__name__}: {ex}'})
                cl = ''
        if cl:
            clauses.append({'op': r['op'], 'lb': o['lb'], 'text': cl})
            if not edit_placed:
                steps.append({'kind': 'edit'})
                edit_placed = True
        if o['neg']:
            negs.append(o['neg'])
    body = '. '.join((c['text'][0].upper() + c['text'][1:]) for c in clauses if c['text'])
    ch = {k for k, secs in _KEEP_DROPS.items() if secs & {OP_BY_ID[c['op']]['sec'] for c in clauses}}
    instr = (body + '. ' + keep_sentence(ch)) if body else ''
    pix_rows = [st['row'] for st in steps if st['kind'] == 'pix']
    svc_rows = [st['row'] for st in steps if st['kind'] == 'svc']
    return {
        'rows': rows,
        'dropped': dropped,
        'steps': steps,
        'pix': pix_rows,
        'svc': svc_rows,
        'clauses': clauses,
        'instruction': instr,
        'negative': ', '.join([_NEG_BASE] + negs),
        'gen_count': len(clauses),
        'svc_count': len(svc_rows),
        'pix_count': len(pix_rows),
        'keep_dropped': sorted(ch),
    }


def apply_pixels(im, rows):
    """Run a list of validated pixel rows over a Pillow image, in order."""
    for r in rows:
        o = OP_BY_ID.get(r['op'])
        if not o or not o['pfn']:
            continue
        im = o['pfn'](im.convert('RGBA'), r['p'])
    return im


_open = cfx._open
_png = cfx._png
_checkerboard = cfx._checkerboard


def _ctx(lib, cid):
    """What the clause functions may read about the subject."""
    try:
        if lib == 'creature':
            man = cfx._manifest(cid)
            return {
                'lib': lib,
                'id': cid,
                'name': man.get('name') or cid,
                'body_plan': man.get('body_plan') or '',
                'style_hint': man.get('style_hint') or '',
            }
        return {'lib': lib, 'id': cid, 'name': _char_name(cid)}
    except Exception:  # noqa: BLE001
        return {'lib': lib, 'id': cid, 'name': cid}


def preview_frame(lib, cid, cat, name, stack, view='rgb', ab=False, maxw=0, ground='', grid=False, scope=''):
    """One PNG of the stack's DETERMINISTIC half, plus what it could not show.

    What the preview cannot show is every generative and service op in the
    stack — and it says so in a header rather than handing back a picture that
    quietly omits three of your eight ops."""
    fp = resolve(lib, cid, cat, name, scope)
    comp = compile_stack(stack, _ctx(lib, cid))
    src = _open(fp)
    out = apply_pixels(src, comp['pix'])
    if view == 'alpha':
        out = out.getchannel('A').convert('RGBA')
    if ab:
        from PIL import Image

        base = src if src.size == out.size else src.resize(out.size, Image.LANCZOS)
        half = out.width // 2
        merged = base.copy()
        merged.paste(out.crop((half, 0, out.width, out.height)), (half, 0))
        out = merged
    if ground and view != 'alpha':
        from PIL import Image

        if ground == 'checker':
            bg = _checkerboard(out.size)
        else:
            bg = Image.new(
                'RGBA',
                out.size,
                _rgba(
                    {'black': '#000000', 'white': '#ffffff', 'grey': '#7f7f7f', 'green': '#00b140'}.get(
                        ground, '#000000'
                    ),
                    100,
                ),
            )
        bg.alpha_composite(out)
        out = bg
    not_shown = [c['lb'] for c in comp['clauses']] + [OP_BY_ID[r['op']]['lb'] for r in comp['svc']]
    info = {
        'w': out.width,
        'h': out.height,
        'gen': comp['gen_count'],
        'svc': comp['svc_count'],
        'pix': comp['pix_count'],
        'dropped': comp['dropped'],
        'not_shown': not_shown,
    }
    return _png(out, maxw), info


def chain_text(lib, cid, cat, name, stack, scope=''):
    """The receipt: exactly what a render would do, before it does it."""
    fp = resolve(lib, cid, cat, name, scope)
    comp = compile_stack(stack, _ctx(lib, cid))
    lic = licence_of(lib, cid)
    lines = [
        f'SOURCE   {lib}/{cid}  {cat}/{name}',
        f'         {fp}',
        f'LICENCE  {lic["licence"]}'
        + ('   ** generative renders are BLOCKED for this subject **' if lic['render_blocked'] else ''),
        '',
    ]
    if not comp['rows']:
        lines.append('The stack is empty — there is nothing to render.')
        return {'ok': True, 'text': '\n'.join(lines), 'comp': _comp_public(comp)}
    lines.append('PIPELINE (in order)')
    n = 0
    for st in comp['steps']:
        n += 1
        if st['kind'] == 'edit':
            lines.append(
                f'  {n:>2}. [generative]  Qwen-Image-Edit — {comp["gen_count"]} clause'
                f'{"" if comp["gen_count"] == 1 else "s"}'
            )
            continue
        o = OP_BY_ID[st['row']['op']]
        kind = 'service    ' if st['kind'] == 'svc' else 'pixel      '
        knobs = ', '.join(f'{k}={v}' for k, v in sorted(st['row']['p'].items()))
        lines.append(f'  {n:>2}. [{kind}] {o["lb"]}' + (f'  ({knobs})' if knobs else ''))
    if comp['dropped']:
        lines += ['', 'DROPPED']
        for d in comp['dropped']:
            lines.append(f'  {d["op"]}: {d["why"]}')
    if comp['instruction']:
        lines += ['', 'INSTRUCTION', '  ' + comp['instruction'], '', 'NEGATIVE', '  ' + comp['negative']]
        if comp['keep_dropped']:
            lines += [
                '',
                'KEEP CLAUSES DROPPED (the stack asks to change them)',
                '  ' + ', '.join(comp['keep_dropped']),
            ]
    else:
        lines += ['', 'No generative op in this stack — the bake is arithmetic and needs no GPU.']
    return {'ok': True, 'text': '\n'.join(lines), 'comp': _comp_public(comp)}


def _comp_public(comp):
    return {k: v for k, v in comp.items() if k not in ('steps', 'pix', 'svc', 'rows')}


# ── bakes: the derived images this studio owns ──────────────────────────────
# Every bake is a PNG plus a JSON sidecar of the same stem, in the subject's
# own picture_studio/ directory. Nothing here can address a cell, a tile, an
# arcane final or a creature preview: cat_dir() resolves BAKE_DIR and only
# BAKE_DIR for every write and every delete below.


def _slug(t, n=28):
    t = re.sub(r'[^a-z0-9]+', '_', str(t or '').lower()).strip('_')
    return t[:n] or 'edit'


def list_bakes(lib, cid):
    d = bake_dir(lib, cid)
    out = []
    for r in _listdir_images(d, limit=200):
        side = os.path.join(d, r['name'][:-4] + '.json')
        rec = {}
        try:
            with open(side, encoding='utf-8') as fh:
                rec = json.load(fh) or {}
        except (OSError, ValueError):
            rec = {}
        out.append(
            {
                'name': r['name'],
                'cat': BAKE_DIR,
                'mtime': r['mtime'],
                'bytes': r['bytes'],
                'when': rec.get('when', ''),
                'summary': rec.get('summary', ''),
                'gen': rec.get('gen_count', 0),
                'seed': rec.get('seed'),
                'measured': rec.get('measured') or {},
                'licence': (rec.get('licence') or {}).get('licence', ''),
                'has_recipe': bool(rec),
            }
        )
    return out


def read_recipe(lib, cid, name, scope=''):
    check_scope(lib, cid, scope)
    if not NAME_RE.match(str(name or '')) or os.path.basename(name) != name:
        raise ValueError('bad name')
    fp = os.path.join(bake_dir(lib, cid), os.path.splitext(name)[0] + '.json')
    with open(fp, encoding='utf-8') as fh:
        return json.load(fh)


def _write_bake(lib, cid, im, comp, meta):
    d = bake_dir(lib, cid, make=True)
    stem = f'{_slug(meta.get("summary") or "edit")}_{meta["job"]}'
    png = os.path.join(d, stem + '.png')
    im.save(png)
    meta = dict(meta)
    meta.update(
        {
            'file': os.path.basename(png),
            'path': png,
            'stack': [{'op': r['op'], 'on': r['on'], 'p': r['p']} for r in comp['rows']],
            'instruction': comp['instruction'],
            'negative': comp['negative'],
            'gen_count': comp['gen_count'],
            'pix_count': comp['pix_count'],
            'svc_count': comp['svc_count'],
            'clauses': comp['clauses'],
        }
    )
    with open(os.path.join(d, stem + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2)
    return png, meta


def delete_bake(lib, cid, name, scope=''):
    """Delete one studio edit and its sidecar. Reaches BAKE_DIR and nowhere else."""
    fp = resolve(lib, cid, BAKE_DIR, name, scope)
    side = os.path.splitext(fp)[0] + '.json'
    os.unlink(fp)
    try:
        os.unlink(side)
    except OSError as _exc:
        _zyg_log.warning('sidecar %s not deleted alongside the image: %s', side, _exc)
    return {'ok': True, 'deleted': os.path.basename(fp)}


def facts(lib, cid, scope=''):
    """Everything the toolbox needs about one subject, in one read."""
    check_scope(lib, cid, scope)
    imgs = images(lib, cid, scope)
    lic = licence_of(lib, cid)
    if lib == 'char':
        name, extra = _char_name(cid), {}
    else:
        man = cfx._manifest(cid)
        name = man.get('name') or cid
        extra = {
            'species': man.get('species') or '',
            'description': man.get('description') or '',
            'body_plan': man.get('body_plan') or '',
            'style_hint': man.get('style_hint') or '',
            'trigger': man.get('trigger_token') or '',
        }
    cats = {}
    for r in imgs:
        cats[r['cat']] = cats.get(r['cat'], 0) + 1
    return {
        'ok': True,
        'lib': lib,
        'id': cid,
        'name': name,
        'licence': lic,
        'images': imgs,
        'counts': cats,
        'bakes': list_bakes(lib, cid),
        'paths': {'subject': subject_dir(lib, cid), 'bakes': bake_dir(lib, cid)},
        'comfy': cfx.comfy_up(),
        **extra,
    }
