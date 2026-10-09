# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character Studio — the File/Edit half of the dock, server side (2026-09-18).

Five ops behind /inspect/api/studio/char_file/:

  import       replace a character's bible from an uploaded package. The
               character_id in the package MUST name the character being
               written — an import is a restore, never a rename of somebody
               else's file onto this one. The file it overwrites is copied to
               <bible>.bak-import-<ts> FIRST, because this is the one op on the
               dock that destroys a bible outright.
  duplicate    fork a bible into a fresh 12-hex id. The copy is deliberately
               NOT a byte copy: the trained weights belong to the original, so
               every lora path is cleared and the trigger token is suffixed. A
               duplicate that kept them would render as the original and the
               operator would have no way to see that from the page.
  autodefaults run character_bible_service.apply_auto_defaults over the bible
               and return the diff WITHOUT saving. apply_auto_defaults takes a
               flat UI params dict, not a bible, so the mapping below is the
               same one build_from_character_generate writes back through —
               and only fields that were EMPTY are reported, because the
               engine resolves every key it is handed and reporting the rest
               would offer to overwrite deliberate choices.
  batch        one field, many characters, through character_studio.edit — so
               the whitelist, the coercion, the lock list and the age
               invariant all apply per character exactly as a single edit does.
  sheet        stream contact_sheet/contact_sheet_master.png. /inspect/img
               only serves the three image CATEGORIES (arcane_final, cells,
               tiles); the master sheet is not in any of them, so it needs its
               own route and its own fence.

Everything is fenced on _char_dir(): the id has to match the library's id
shape and the resolved directory has to be a direct child of the dataset root.
"""

import copy
import os
import re
import shutil
import time
import uuid
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_ROOT = os.path.realpath(str(paths.ZYG_LORA_DATASETS / 'storyteller_chars'))
_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_NEW_ID_RE = re.compile(r'^[a-f0-9]{12}$')

# A sheet image the page may ask for by name, mapped to its file under
# contact_sheet/. A closed list rather than a path parameter: the fence then
# has nothing to validate beyond the character id.
_SHEETS = {
    'master': 'contact_sheet_master.png',
    'arcane': 'contact_sheet_arcane.png',
    'training': 'contact_sheet_training.png',
    'anchor': 'contact_sheet_anchor_face.png',
}

# apply_auto_defaults' flat params key -> the bible path it is written back to.
# Read off character_bible_service.build_from_character_generate, which is the
# only writer that maps the two — copying it here rather than inferring it
# keeps an auto-default landing where the generator would have put it.
_AUTO_MAP = [
    ('gender', 'identity.gender'),
    ('age', 'identity.age'),
    ('height', 'identity.height_m'),
    ('skin_tone', 'identity.skin_tone'),
    ('hair_color', 'identity.hair_color'),
    ('hair_style', 'identity.hair_style'),
    ('hair_length', 'identity.hair_length'),
    ('hair_texture', 'identity.hair_texture'),
    ('eye_color', 'identity.eye_color'),
    ('eye_shape', 'identity.eye_shape'),
    ('eyebrow_style', 'identity.eyebrow_style'),
    ('face_shape', 'identity.face_shape'),
    ('nose_shape', 'identity.nose_shape'),
    ('lip_shape', 'identity.lip_shape'),
    ('body_build', 'identity.body_build'),
    ('muscle_mass', 'identity.muscle_mass'),
    ('facial_hair', 'identity.facial_hair'),
    ('distinctive_marks', 'identity.distinctive_marks'),
    ('ethnic_heritage', 'identity.ethnic_heritage'),
    ('default_clothing', 'default_presentation.default_clothing'),
    ('default_expression', 'default_presentation.default_expression'),
    ('accessories', 'default_presentation.accessories'),
    ('posture', 'default_presentation.posture'),
    ('render_style', 'style_profile.render_style'),
    ('genre', 'style_profile.genre'),
    ('lighting_profile', 'style_profile.lighting_profile'),
    ('color_palette', 'style_profile.color_palette'),
    ('camera_language', 'style_profile.camera_language'),
    ('quality_suffix', 'conditioning.quality_suffix'),
    ('negative_prompt', 'conditioning.negative_prompt'),
]


def _char_dir(cid):
    """The character's real directory, or None. A direct child of the root and
    nothing else — the same fence kanban_server._safe_char_dir applies."""
    cid = str(cid or '').strip()
    if not _ID_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(_ROOT, cid))
    if d != os.path.join(_ROOT, cid) or not os.path.isdir(d):
        return None
    return d


def _mods():
    from zyg_workflows import character_bible_service
    from zyg_workflows import character_studio

    return character_bible_service, character_studio


def _is_empty(v):
    """What apply_auto_defaults itself treats as unset: absent, blank, or the
    literal 'auto' the generation form writes for "you decide"."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == '' or v.strip().lower() == 'auto'
    return False


# ── import ───────────────────────────────────────────────────────────────────
def _import(payload, method):  # noqa: ARG001
    cbs, cs = _mods()
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    pkg = payload.get('package')
    if not isinstance(pkg, dict) or not pkg:
        return {'error': 'no package in the request — expected the JSON an Export wrote'}
    got = str(pkg.get('character_id') or '')
    if got != cid:
        return {
            'error': f'this package belongs to {got or "no character"}, '
            f'not to {cid}. An import restores a character from its '
            f'own export; it does not move one bible onto another.'
        }

    before = cs._values(cbs.load(cid) or {})
    path = cbs.bible_path(cid)
    backup = ''
    if os.path.isfile(path):
        backup = f'{path}.bak-import-{time.strftime("%Y%m%d_%H%M%S")}'
        try:
            shutil.copy2(path, backup)
        except OSError as e:
            return {'error': f'could not write the backup ({e}) — nothing was imported', 'code': 500}
    try:
        cbs.save(cbs.migrate_package(copy.deepcopy(pkg)))
    except Exception as e:  # noqa: BLE001 — shown in the panel
        return {'error': f'{type(e).__name__}: {e}'[:200], 'code': 500}

    after = cs._values(cbs.load(cid) or {})
    changed = sorted(p for p in after if after.get(p) != before.get(p) and p != 'updated_at')
    return {'ok': True, 'id': cid, 'backup': backup, 'changed': changed}


# ── duplicate ────────────────────────────────────────────────────────────────
def _duplicate(payload, method):  # noqa: ARG001
    cbs, _cs = _mods()
    cid = str(payload.get('id') or '').strip()
    if not _char_dir(cid):
        return {'error': 'unknown character', 'code': 404}
    name = str(payload.get('name') or '').strip()
    if not name:
        return {'error': 'a display name is required for the copy'}
    if len(name) > 120:
        return {'error': 'display name too long (max 120)'}

    src = cbs.load(cid)
    if src is None:
        return {'error': 'this character has no character_bible.json to copy', 'code': 404}

    new_id = ''
    for _ in range(20):
        cand = uuid.uuid4().hex[:12]
        if _NEW_ID_RE.match(cand) and not os.path.exists(os.path.join(_ROOT, cand)):
            new_id = cand
            break
    if not new_id:
        return {'error': 'could not mint a free id', 'code': 500}

    pkg = copy.deepcopy(src)
    pkg['character_id'] = new_id
    pkg['display_name'] = name
    pkg['created_at'] = cbs._utc_now()
    pkg['updated_at'] = cbs._utc_now()
    tok = str(pkg.get('trigger_token') or '').strip()
    pkg['trigger_token'] = f'{tok}_copy' if tok else f'{new_id}_copy'
    # the weights belong to the ORIGINAL. A copy that kept these paths would
    # render as the character it was forked from, and nothing on the page would
    # say so — so they are cleared and the fork has to be trained on its own.
    cond = pkg.setdefault('conditioning', {})
    for k in ('lora_path', 'flux_lora_path', 'sdxl_lora_path', 'klein_lora_path', 'qwen_lora_path'):
        if k in cond:
            cond[k] = ''
    # dataset_dir names a directory on disk. Left alone it would point at the
    # original's dataset, so the fork's own (empty) directory is named instead.
    if pkg.get('dataset_dir'):
        pkg['dataset_dir'] = os.path.join(_ROOT, new_id)

    try:
        out = cbs.save(pkg)
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:200], 'code': 500}
    return {'ok': True, 'id': new_id, 'name': name, 'from': cid, 'file': out}


# ── auto defaults (dry) ──────────────────────────────────────────────────────
def _autodefaults(payload, method):  # noqa: ARG001
    cbs, cs = _mods()
    cid = str(payload.get('id') or '').strip()
    if not _char_dir(cid):
        return {'error': 'unknown character', 'code': 404}
    pkg = cbs.load(cid)
    if pkg is None:
        return {'error': 'this character has no character_bible.json', 'code': 404}

    vals = cs._values(pkg)
    params = {'char_id': cid, 'name': pkg.get('display_name') or cid}
    for key, path in _AUTO_MAP:
        params[key] = cs._get(pkg, path)

    try:
        filled = cbs.apply_auto_defaults(dict(params), seed_key=cid)
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:200], 'code': 500}

    # apply_auto_defaults resolves EVERY key it is handed, including the ones
    # that were already set (it normalises them). Only the fields that were
    # empty before are offered — the rest are deliberate choices and an
    # "auto defaults" button must not be a way to lose them.
    changed, skipped = {}, []
    for key, path in _AUTO_MAP:
        spec = cs.FIELDS.get(path)
        if not spec or spec.get('t') == 'ro':
            continue
        old = cs._get(pkg, path)
        new = filled.get(key)
        if not _is_empty(old):
            continue
        if new is None or (isinstance(new, str) and not new.strip()):
            continue
        if new == old:
            continue
        try:
            new = cs._coerce(spec, new)
        except ValueError as e:
            skipped.append({'path': path, 'value': str(new)[:120], 'why': str(e)[:160]})
            continue
        if new == vals.get(path):
            continue
        changed[path] = [old, new]
    return {'ok': True, 'id': cid, 'changed': changed, 'skipped': skipped, 'saved': False}


# ── batch ────────────────────────────────────────────────────────────────────
def _batch(payload, method):  # noqa: ARG001
    _cbs, cs = _mods()
    path = str(payload.get('path') or '').strip()
    spec = cs.FIELDS.get(path)
    if not spec:
        return {'error': f'{path or "(no path)"} is not an editable field'}
    if spec.get('t') == 'ro':
        return {'error': f'{path} is read-only'}
    if 'value' not in payload:
        return {'error': 'no value'}
    ids = payload.get('ids')
    if not isinstance(ids, list) or not ids:
        return {'error': 'no characters selected'}
    if len(ids) > 60:
        return {'error': 'too many characters at once (max 60)'}

    rows = []
    for raw_id in ids:
        cid = str(raw_id or '').strip()
        cdir = _char_dir(cid)
        if not cdir:
            rows.append({'id': cid, 'ok': False, 'why': 'unknown character'})
            continue
        try:
            res = cs.edit(cid, cdir, {path: payload['value']})
        except Exception as e:  # noqa: BLE001
            rows.append({'id': cid, 'ok': False, 'why': f'{type(e).__name__}: {e}'[:160]})
            continue
        if not res.get('ok'):
            why = res.get('error') or ''
            rej = res.get('rejected') or {}
            if rej:
                why = '; '.join(f'{k}: {v}' for k, v in rej.items())
            rows.append({'id': cid, 'ok': False, 'why': why or 'refused'})
            continue
        rows.append(
            {
                'id': cid,
                'ok': True,
                'applied': res.get('applied') or {},
                'rejected': res.get('rejected') or {},
                'forced': res.get('forced') or {},
            }
        )
    return {'ok': True, 'path': path, 'value': payload['value'], 'results': rows}


# ── the contact-sheet master image ───────────────────────────────────────────
def _sheet(payload, method):  # noqa: ARG001
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    which = str(payload.get('which') or 'master').strip()
    fname = _SHEETS.get(which)
    if not fname:
        return {'error': f'unknown sheet {which!r}', 'code': 404}
    fp = os.path.join(cdir, 'contact_sheet', fname)
    if not os.path.isfile(fp):
        return {'error': 'no contact sheet on disk for this character', 'code': 404}
    try:
        with open(fp, 'rb') as fh:
            blob = fh.read()
    except OSError:
        return {'error': 'could not read the contact sheet', 'code': 404}
    return blob, 'image/png', f'{cid}_{which}.png'


def _sheets(payload, method):  # noqa: ARG001
    """Which of the sheet images this character actually has, so the page can
    offer the ones that exist instead of a broken <img>."""
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    out = []
    for key, fname in _SHEETS.items():
        fp = os.path.join(cdir, 'contact_sheet', fname)
        try:
            out.append(
                {'which': key, 'file': fname, 'bytes': os.path.getsize(fp), 'mtime': round(os.path.getmtime(fp), 1)}
            )
        except OSError as _exc:
            _zyg_log.debug('contact sheet %s stat skipped: %s', fname, _exc)
            continue
    return {'ok': True, 'id': cid, 'sheets': out}


# ── another character's bible, for Copy-from and Compare ─────────────────────
def _other(payload, method):  # noqa: ARG001
    """The VALUES of a second character, flattened the same way the studio's own
    /inspect/api/char/bible does. Copy-from and Compare both need a second
    character's fields beside the loaded one, and that route serves exactly one
    character at a time."""
    cbs, cs = _mods()
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    pkg = cbs.load(cid)
    if pkg is None:
        return {'error': 'this character has no character_bible.json', 'code': 404}
    return {'ok': True, 'id': cid, 'name': pkg.get('display_name') or cid, 'values': cs._values(pkg)}


ROUTES = {
    'import': _import,
    'duplicate': _duplicate,
    'autodefaults': _autodefaults,
    'batch': _batch,
    'sheet': _sheet,
    'sheets': _sheets,
    'other': _other,
}
