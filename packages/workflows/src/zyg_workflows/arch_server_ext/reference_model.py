# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""reference_model — the server half of the REFERENCE MODEL rail (2026-09-23).

The icon beside the assistant chat panel talks to these ops. Everything about
the store itself lives in ``arch_reference``; this file is only the door, so
that a change to the store needs no restart either (``ext_dispatch`` reloads a
file whose mtime moved).

    GET/POST /inspect/api/architecture/ext/reference_model/<op>

    list          {}                        -> {models: [...], current, roles}
    get           {m}                       -> {model}
    create        {name, subject?}          -> {model}
    update        {m, name?, subject?, notes?, length_m?, beam_m?, height_m?}
    delete        {m}
    add_image     {m, data, filename?, role?, note?}   data = a data: URL
    set_image     {m, i, role?, note?}
    del_image     {m, i}
    image         GET {m, i, t?}            -> the picture's bytes (t=1: 320 px)
    preview       GET {m, k?, n?, s?}                   -> the built asset's preview png
    current       {}                        -> {id}
    set_current   {m}                       -> {id}          ('' clears it)
    build_brief   {m}                       -> {text}  what the assistant is told

`image` and `preview` answer a TUPLE, which kanban_server sends as bytes. The
third element (a filename) is deliberately omitted: with one the server adds
Content-Disposition: attachment and the thumbnails download instead of
displaying.

Licence: stdlib + Pillow, through arch_reference. Nothing here imports
arch_assistant.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_workflows import arch_reference as R  # noqa: E402


def _err(msg, code=400):
    return {'ok': False, 'error': str(msg)[:300], 'code': code}


def _mid(p):
    return str(p.get('m') or p.get('model') or p.get('id') or '')


def op_list(p, method):
    return {
        'ok': True,
        'current': R.current(),
        'roles': [
            {'id': k, 'label': v['label'], 'short': v.get('short') or k, 'plan': v['plan']}
            for k, v in sorted(
                R.ROLES.items(), key=lambda kv: R.ROLE_ORDER.index(kv[0]) if kv[0] in R.ROLE_ORDER else 99
            )
        ],
        'models': [R.public(m) for m in R.models()],
    }


def op_get(p, method):
    rec = R.read(_mid(p)) if _mid(p) else None
    if rec is None:
        return _err('no such reference model', 404)
    return {'ok': True, 'model': R.public(rec), 'current': R.current()}


def op_create(p, method):
    name = str(p.get('name') or '').strip()
    if not name:
        return _err('give the reference model a name')
    rec = R.create(name, str(p.get('subject') or ''))
    R.set_current(rec['id'])
    return {'ok': True, 'model': R.public(rec), 'current': rec['id']}


def op_update(p, method):
    rec = R.update(_mid(p), p)
    if rec is None:
        return _err('no such reference model', 404)
    return {'ok': True, 'model': R.public(rec)}


def op_delete(p, method):
    mid = _mid(p)
    if not R.delete(mid):
        return _err('no such reference model', 404)
    if R.current() == mid:
        R.set_current('')
    return {'ok': True, 'current': R.current()}


def op_add_image(p, method):
    try:
        img = R.add_image(
            _mid(p),
            p.get('data') or '',
            str(p.get('filename') or ''),
            str(p.get('role') or R.DEFAULT_ROLE),
            str(p.get('note') or ''),
        )
    except ValueError as e:
        return _err(e)
    rec = R.read(_mid(p))
    return {'ok': True, 'image': img, 'model': R.public(rec)}


def op_set_image(p, method):
    img = R.set_image(_mid(p), str(p.get('i') or ''), p)
    if img is None:
        return _err('no such picture', 404)
    return {'ok': True, 'image': img, 'model': R.public(R.read(_mid(p)))}


def op_del_image(p, method):
    if not R.del_image(_mid(p), str(p.get('i') or '')):
        return _err('no such picture', 404)
    return {'ok': True, 'model': R.public(R.read(_mid(p)))}


def op_image(p, method):
    try:
        raw, mime = R.image_bytes(_mid(p), str(p.get('i') or ''), thumb=str(p.get('t') or '') in ('1', 'true'))
    except (ValueError, OSError) as e:
        return _err(e, 404)
    return (raw, mime)


def _at(seq, raw, what):
    """seq[int(raw)], refusing a NEGATIVE index. Python would happily read k=-1
    as the last check, which is a picture the caller never asked for and a
    quiet way past an index bound."""
    try:
        i = int(raw)
        if i < 0:
            raise IndexError(raw)
        return (seq or [])[i].get('path') or ''
    except (ValueError, IndexError, KeyError, TypeError, AttributeError) as _exc:
        raise ValueError(f'no such {what}') from _exc


def op_preview(p, method):
    """The built asset's preview; k=<n> the n-th CHECK overlay, n=<i> the i-th
    INSPECTION view, s=1 the ten-up contact sheet of the whole set, p=<i> the
    i-th PORTFOLIO picture and ps=<i> the i-th portfolio contact sheet.

    Everything here is addressed by a validated model id plus an INDEX, and the
    path comes out of the record — never off the wire. That is the wall the
    picture routes already stand behind and a new op must not be the first hole
    in it."""
    rec = R.read(_mid(p))
    asset = (rec or {}).get('asset') or {}
    k, n = str(p.get('k') or ''), str(p.get('n') or '')
    pf = asset.get('portfolio') or {}
    try:
        if str(p.get('p') or '') != '':
            # the portfolio rows carry `file` (a basename) — the DIRECTORY comes
            # out of the record, so a name off the wire can never leave it
            row = asset.get('portfolio_shots') or []
            i = int(p.get('p'))
            if i < 0 or i >= len(row) or not row[i].get('file'):
                return _err('no such portfolio picture', 404)
            path = os.path.join(pf.get('dir') or '', os.path.basename(row[i]['file']))
        elif str(p.get('ps') or '') != '':
            i = int(p.get('ps'))
            sheets = pf.get('sheets') or []
            if i < 0 or i >= len(sheets):
                return _err('no such portfolio contact sheet', 404)
            path = sheets[i]
        elif n != '':
            path = _at(asset.get('inspect'), n, 'inspection picture')
        elif k != '':
            path = _at(asset.get('checks'), k, 'check picture')
        elif str(p.get('s') or '') not in ('', '0'):
            path = asset.get('sheet') or ''
        else:
            path = asset.get('preview') or ''
    except ValueError as e:
        return _err(str(e), 404)
    if not path or not os.path.isfile(path):
        return _err('this reference model has no built preview', 404)
    with open(path, 'rb') as fh:
        return (fh.read(), 'image/png')


def op_current(p, method):
    return {'ok': True, 'id': R.current()}


def op_set_current(p, method):
    try:
        return {'ok': True, 'id': R.set_current(_mid(p))}
    except ValueError as e:
        return _err(e, 404)


def op_build_brief(p, method):
    rec = R.resolve(_mid(p))
    if rec is None:
        return _err('no such reference model', 404)
    return {'ok': True, 'text': R.brief(rec)}


ROUTES = {
    'list': op_list,
    'get': op_get,
    'create': op_create,
    'update': op_update,
    'delete': op_delete,
    'add_image': op_add_image,
    'set_image': op_set_image,
    'del_image': op_del_image,
    'image': op_image,
    'preview': op_preview,
    'current': op_current,
    'set_current': op_set_current,
    'build_brief': op_build_brief,
}
