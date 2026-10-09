# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Resolving a subject and one of its images, and the licence verdict that follows it."""

from __future__ import annotations

import json
import os
import re
import time

from zyg_workflows import creature_fx as cfx

from zyg_workflows.picture_fx.constants import (
    BAKE_DIR,
    CHAR_CATS,
    CHAR_ID_RE,
    CHARS_ROOT,
    IMG_EXT,
    LIBS,
    NAME_RE,
    RUNTIME,
    _zyg_log,
)

# ══════════════════════════════════════════════════════════════════════════════
#  RESOLVING A SUBJECT AND ONE OF ITS IMAGES
# ══════════════════════════════════════════════════════════════════════════════
# The caller supplies (lib, id, cat, name) and NEVER a path fragment. The
# library is one of two literals, the id is held to that library's own id
# charset, the category is a key in that library's map, the name is basename-
# only, and the final realpath must sit inside the resolved category directory
# inside the right root. Same fence as the image routes, for the same reason —
# this one also WRITES.

_MEDUSA_IDS = {'ts': 0.0, 'ids': None}


def _medusa_id_set():
    """Which character ids came out of the Medusa lane.

    Same two-signal check kanban_server and bp_picture_studio make: a marker
    file in the character's own directory, or a medusa runtime state file
    carrying its id. Cached for four seconds because the listing asks per
    subject and a directory scan per row would be its own bug."""
    now = time.monotonic()
    c = _MEDUSA_IDS
    if c['ids'] is not None and (now - c['ts']) < 4.0:
        return c['ids']
    ids = set()
    try:
        for fn in os.listdir(RUNTIME):
            if fn.startswith('medusa_') and fn.endswith('_state.json'):
                cid = fn[len('medusa_') : -len('_state.json')]
                if cid:
                    ids.add(cid)
    except OSError as _exc:
        _zyg_log.debug('medusa state scan of %s skipped: %s', RUNTIME, _exc)
    c['ts'] = now
    c['ids'] = ids
    return ids


def _char_dir(cid):
    if not CHAR_ID_RE.match(str(cid or '')):
        raise ValueError('bad character id')
    d = os.path.realpath(os.path.join(CHARS_ROOT, cid))
    if d != os.path.join(CHARS_ROOT, cid) or not os.path.isdir(d):
        raise ValueError('no such character')
    return d


def is_medusa(cid):
    try:
        if os.path.exists(os.path.join(_char_dir(cid), '.medusa_origin')):
            return True
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('origin marker check for %s failed, falling back to the state scan: %s', cid, _exc)
    return cid in _medusa_id_set()


def check_scope(lib, cid, scope):
    """Fail closed on the origin split.

    Only characters carry it — a creature has no medusa lane — so a creature
    request is scope-free by construction rather than by omission."""
    if lib != 'char':
        return
    if is_medusa(cid) != (str(scope or '') == 'medusa'):
        raise ValueError('image not found in this scope')


def subject_dir(lib, cid):
    if lib == 'char':
        return _char_dir(cid)
    if lib == 'creature':
        return cfx._cdir(cid)
    raise ValueError(f'bad library: {lib}')


def bake_dir(lib, cid, make=False):
    d = os.path.join(subject_dir(lib, cid), BAKE_DIR)
    if make:
        os.makedirs(d, exist_ok=True)
    return d


def cat_dir(lib, cid, cat, make=False):
    """(lib, id, cat) -> the directory that category resolves to."""
    if lib == 'char':
        if cat not in CHAR_CATS:
            raise ValueError(f'bad category: {cat}')
        base = _char_dir(cid)
        d = os.path.realpath(os.path.join(base, CHAR_CATS[cat][0]))
        if not d.startswith(base):
            raise ValueError('category escaped the character')
        if make:
            os.makedirs(d, exist_ok=True)
        return d
    if lib == 'creature':
        if cat == BAKE_DIR:
            return bake_dir(lib, cid, make=make)
        return cfx._catdir(cid, cat, make=make)
    raise ValueError(f'bad library: {lib}')


def cat_label(lib, cat):
    if cat == BAKE_DIR:
        return 'Studio edit'
    if lib == 'char':
        return CHAR_CATS.get(cat, ('', cat))[1]
    return cfx.CATS.get(cat, ('', cat))[1]


def resolve(lib, cid, cat, name, scope=''):
    """(lib, id, cat, name) -> an absolute path to a real image in that category."""
    if lib not in LIBS:
        raise ValueError(f'bad library: {lib}')
    name = str(name or '')
    if not NAME_RE.match(name) or os.path.basename(name) != name:
        raise ValueError('bad image name')
    if not name.lower().endswith(IMG_EXT):
        raise ValueError('not an image')
    check_scope(lib, cid, scope)
    if lib == 'creature' and cfx.licence_of(cid).get('render_blocked'):
        # The Creatures tab withholds a FLUX.1-dev creature's imagery outright and
        # kanban_server._creature_img 404s it, so a studio that displayed the same
        # pixels through a different route would BE the hole that withholding is
        # there to close. Refused at resolve(), which is the one door every reader
        # here goes through -- the preview, the frame, the raw image and the render
        # ([[project_licence_gate]]).
        raise ValueError(
            "this creature's imagery is withheld by the licence gate "
            '(FLUX.1-dev base, non-commercial, on a monetised channel)'
        )
    d = cat_dir(lib, cid, cat)
    fp = os.path.realpath(os.path.join(d, name))
    if not (fp.startswith(d + os.sep) and os.path.isfile(fp)):
        raise ValueError('no such image')
    return fp


def _listdir_images(d, limit=400):
    try:
        names = os.listdir(d)
    except OSError:
        return []
    rows = []
    for n in sorted(names):
        if not n.lower().endswith(IMG_EXT) or not NAME_RE.match(n):
            continue
        fp = os.path.join(d, n)
        if not os.path.isfile(fp):
            continue
        rows.append({'name': n, 'mtime': round(os.path.getmtime(fp), 3), 'bytes': os.path.getsize(fp)})
    rows.sort(key=lambda r: r['mtime'], reverse=True)
    return rows[:limit]


def images(lib, cid, scope=''):
    """Every image this subject owns, by category, newest first within one."""
    check_scope(lib, cid, scope)
    cats = list(CHAR_CATS) if lib == 'char' else (list(cfx.CATS) + [BAKE_DIR])
    out = []
    for cat in cats:
        try:
            d = cat_dir(lib, cid, cat)
        except ValueError as _exc:
            _zyg_log.debug('category %s has no directory for %s: %s', cat, cid, _exc)
            continue
        for r in _listdir_images(d):
            if lib == 'creature' and cat == 'preview' and not r['name'].startswith('preview_'):
                continue
            if lib == 'creature' and cat == 'ref' and not r['name'].startswith('ref_'):
                continue
            out.append(
                {
                    'lib': lib,
                    'id': cid,
                    'cat': cat,
                    'name': r['name'],
                    'label': cat_label(lib, cat),
                    'mtime': r['mtime'],
                    'bytes': r['bytes'],
                }
            )
    return out


def _char_name(cid):
    """The character's display name, read the same way the Library tab reads it."""
    d = _char_dir(cid)
    for fn in ('character_bible.json', 'params.json', 'manifest.json'):
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as fh:
                rec = json.load(fh) or {}
            for k in ('name', 'character_name', 'display_name'):
                if rec.get(k):
                    return str(rec[k])[:80]
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('metadata %s unreadable, trying the next file: %s', fn, _exc)
            continue
    return cid


# A character's licence follows the base model its imagery was made on, the same
# way a creature's follows its train_family. NOTHING in the character library
# records that field, so this reports what it can PROVE off disk and refuses to
# guess: an explicit record first, then FILE-LEVEL evidence (a weights file or a
# render whose name carries a family token with a word boundary, not a loose
# substring — "qwen_edit_source.png" must never clear a FLUX character for
# commercial use).
#
# Two rules, both in the conservative direction, because the channel is
# monetised and a wrong verdict here is a live exposure
# ([[project_licence_gate]], [[feedback_licence_policy]]):
#   * FLUX evidence WINS over any other family found alongside it.
#   * NO evidence blocks generative renders too. An unknown base is not a green
#     light, and the studio says so rather than rendering and hoping.
# Deterministic pixel ops, the ESRGAN upscale and the u2net matte are unaffected
# either way: they transform what is already on disk and mint no new model output.
_FAMILY_TOKEN = re.compile(r'(?:^|[^a-z0-9])(flux1|flux|klein|qwen|sdxl)(?:$|[^a-z0-9])', re.IGNORECASE)


def _family_evidence(cid):
    """(family, what-said-so). Explicit record first, file names second."""
    d = _char_dir(cid)
    for fn in ('character_bible.json', 'params.json', 'manifest.json'):
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as fh:
                rec = json.load(fh) or {}
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('metadata %s unreadable, trying the next file: %s', fn, _exc)
            continue
        for k in ('train_family', 'base_family', 'base_model', 'model_family'):
            v = str(rec.get(k) or '').strip().lower()
            if v in cfx.LICENCES:
                return v, f'{fn} → {k}: {v}'
    hits = {}
    probes = [d] + [os.path.join(d, sub) for sub in ('lora', 'lora-weights', 'training')]
    for pdir in probes:
        try:
            names = sorted(os.listdir(pdir))[:400]
        except OSError as _exc:
            _zyg_log.debug('licence probe dir %s unreadable, skipped: %s', pdir, _exc)
            continue
        for n in names:
            m = _FAMILY_TOKEN.search(n)
            if m:
                fam = m.group(1).lower()
                fam = 'flux' if fam == 'flux1' else fam
                if fam in cfx.LICENCES:
                    hits.setdefault(fam, os.path.join(os.path.basename(pdir), n) if pdir != d else n)
    if 'flux' in hits:
        return 'flux', f'file on disk: {hits["flux"]}'
    for fam in ('klein', 'qwen', 'sdxl'):
        if fam in hits:
            return fam, f'file on disk: {hits[fam]}'
    return '', 'no base-model record and no file on disk names one'


def _char_licence(cid):
    fam, why = _family_evidence(cid)
    if not fam:
        return {
            'family': '',
            'licence': 'unknown',
            'commercial_ok': None,
            'evidence': why,
            'note': 'no base-model family is recorded for this character and no file '
            'on disk names one, so the licence of a NEW render cannot be '
            'established.',
            'render_blocked': True,
            'block_note': 'The base model this character was made on is unknown, the '
            'channel is monetised, and an unknown licence is not a green '
            'light — so the studio will not render NEW imagery for it. '
            "Record train_family in the character's params.json to lift "
            'this. Every deterministic op, the upscale and the background '
            'matte still run: they transform what is already on disk.',
        }
    lic, ok, note = cfx.LICENCES[fam]
    blocked = fam in cfx.FLUX1_FAMILIES
    return {
        'family': fam,
        'licence': lic,
        'commercial_ok': ok,
        'note': note,
        'evidence': why,
        'render_blocked': blocked,
        'block_note': (
            'FLUX.1-dev is non-commercial and the channel is monetised: the '
            'studio will not render NEW imagery for this subject. '
            'Deterministic pixel ops on what is already on disk still run.'
        )
        if blocked
        else '',
    }


def licence_of(lib, cid):
    return _char_licence(cid) if lib == 'char' else cfx.licence_of(cid)
