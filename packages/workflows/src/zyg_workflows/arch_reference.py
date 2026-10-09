# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference — the Architecture Studio's REFERENCE MODEL store (2026-09-23).

A *reference model* is a named folder of pictures of one real thing — a ship, a
bridge, a lamp post, a building — plus the few numbers that turn pictures into
geometry: what it is, how long it really is, and which view each picture is.
The operator fills it from the icon rail beside the assistant chat panel; the
assistant reads it, LOOKS at the pictures, and builds a Blender asset from them.

Why the numbers matter, and why the store insists on them:

    One photograph cannot determine a shape. Every pixel is a ray, so depth and
    size trade off exactly, and nothing in the file says which. What breaks the
    tie is knowledge from outside the picture — a real dimension, an
    orthographic plan, bilateral symmetry. So an image here is never just an
    image: it carries a ROLE (which direction it was seen from) and the model
    carries at least one measured length. A reference model with only `photo`
    images and no length is honestly reported as "shape only, not measurable",
    and the assistant is told to say so rather than invent a scale.

Layout (under data/architecture/reference/<model id>/):

    model.json          the record below
    images/<id>.<ext>   the pictures, as uploaded (re-encoded only when huge)
    images/<id>.th.jpg  a 320 px thumbnail, made on demand
    asset/              what a build left behind: .blend, .glb, preview.png

model.json:

    {id, name, subject, notes, length_m, beam_m, height_m, created, updated,
     images: [{id, file, role, note, w, h, bytes, added}],
     asset:  {glb, blend, preview, pack, item, dims, tris, built, script}}

Licence: stdlib + Pillow (HPND) only. Nothing here imports arch_assistant —
importing that module closes live conversations as "killed"
(feedback_no_import_arch_assistant), and this store is read by the tab's routes
on every keystroke.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import time
import uuid
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(HERE, 'data', 'architecture', 'reference')
PACKS_DIR = os.path.join(HERE, 'data', 'assets', 'mesh_packs', 'zyg_reference')

# One picture may be 12 MB; a whole model is capped so a runaway upload cannot
# fill the disk behind the operator's back.
MAX_IMAGE_BYTES = 12 << 20
MAX_MODEL_BYTES = 400 << 20
MAX_IMAGES = 60
MAX_EDGE = 4096  # longest side kept; anything bigger is resampled once
THUMB_EDGE = 320

_LOCK = threading.Lock()

# ── the layout convention ────────────────────────────────────────────────────
# Stated ONCE, here, and quoted verbatim by the tab, the assistant's prompt and
# the Blender harness. Without it the role names contradict each other: a
# "right elevation" and a "top plan" of the same ship can only both be laid out
# if everyone already agrees which way the ship points.
LAYOUT = (
    'The subject lies with its LENGTH along +X (front/bow towards +X), its WIDTH along Y and its '
    'HEIGHT along +Z, centred on the origin. Blender is Z-up, +X east, +Y north — the same frame '
    'arch_blender_build.py maps the studio into. So a side view shows length x height, a front view '
    'shows width x height, and a top view shows length x width.'
)

# ── roles ────────────────────────────────────────────────────────────────────
# The role is the ONLY thing that makes a picture usable as geometry. A photo
# is a view from somewhere unknown; a view is taken from a named direction, and
# a named direction is a rotation Blender can be told.
#
# `blender` is the Euler (x, y, z) in HALF-TURNS that lays a default XY plane
# (u -> +X, v -> +Y, normal +Z) into that view. `eye` is where the camera
# stands. `across` names the measured dimension that spans the picture's width.
#
# Derived, not guessed: for each view take forward (from the eye towards the
# subject) and up, then right = cross(forward, up); the image's u must land on
# right and its v on up. Checked against a rendered fixture, not on paper.
ROLES = {
    'view_side': {
        'plan': True,
        'blender': (0.5, 0.0, 0.0),
        'eye': (0.0, -1.0, 0.0),
        'across': 'length_m',
        'label': 'side view — length runs left to right, bow/front on the RIGHT',
        'short': 'side view',
    },
    'view_side_other': {
        'plan': True,
        'blender': (0.5, 0.0, 1.0),
        'eye': (0.0, 1.0, 0.0),
        'across': 'length_m',
        'label': 'the opposite side — bow/front on the LEFT',
        'short': 'other side',
    },
    'view_front': {
        'plan': True,
        'blender': (0.5, 0.0, 0.5),
        'eye': (1.0, 0.0, 0.0),
        'across': 'beam_m',
        'label': 'front view (bow / face) — width runs left to right',
        'short': 'front view',
    },
    'view_back': {
        'plan': True,
        'blender': (0.5, 0.0, -0.5),
        'eye': (-1.0, 0.0, 0.0),
        'across': 'beam_m',
        'label': 'back view (stern / rear) — width runs left to right',
        'short': 'back view',
    },
    'view_top': {
        'plan': True,
        'blender': (0.0, 0.0, 0.0),
        'eye': (0.0, 0.0, 1.0),
        'across': 'length_m',
        'label': 'plan from above — length runs left to right, bow/front on the RIGHT',
        'short': 'top view',
    },
    'view_bottom': {
        'plan': True,
        'blender': (0.0, 1.0, 0.0),
        'eye': (0.0, 0.0, -1.0),
        'across': 'length_m',
        'label': 'plan from below',
        'short': 'bottom view',
    },
    'section': {
        'plan': True,
        'blender': (0.5, 0.0, 0.5),
        'eye': (1.0, 0.0, 0.0),
        'across': 'beam_m',
        'label': 'a cross-section / body plan — laid out like a front view',
        'short': 'section',
    },
    'photo': {
        'plan': False,
        'blender': None,
        'eye': None,
        'across': '',
        'label': 'photograph — viewpoint unknown, shape and colour only',
        'short': 'photograph',
    },
    'detail': {
        'plan': False,
        'blender': None,
        'eye': None,
        'across': '',
        'label': 'a close-up of one part',
        'short': 'detail',
    },
    'texture': {
        'plan': False,
        'blender': None,
        'eye': None,
        'across': '',
        'label': 'a surface to use as a texture',
        'short': 'texture',
    },
}
ROLE_ORDER = [
    'view_side',
    'view_side_other',
    'view_front',
    'view_back',
    'view_top',
    'view_bottom',
    'section',
    'photo',
    'detail',
    'texture',
]
DEFAULT_ROLE = 'photo'

MIME_EXT = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
EXT_MIME = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}

_ID = re.compile(r'^[0-9a-f]{6,32}$')


def slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(name or '').lower()).strip('-') or 'reference'


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _mid_ok(mid: str) -> bool:
    return bool(_ID.match(str(mid or '')))


def model_dir(mid: str) -> str:
    if not _mid_ok(mid):
        raise ValueError('bad reference model id')
    return os.path.join(REF_DIR, mid)


def _json_path(mid: str) -> str:
    return os.path.join(model_dir(mid), 'model.json')


def _num(v, d=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return d
    return f if f == f and abs(f) != float('inf') else d


# ── records ──────────────────────────────────────────────────────────────────
def _blank(name: str, subject: str = '') -> dict:
    return {
        'id': uuid.uuid4().hex[:12],
        'name': str(name or 'Untitled reference')[:120],
        'subject': str(subject or '')[:120],
        'notes': '',
        'length_m': 0.0,
        'beam_m': 0.0,
        'height_m': 0.0,
        'images': [],
        'asset': None,
        'created': _now(),
        'updated': _now(),
    }


def read(mid: str) -> dict | None:
    try:
        with open(_json_path(mid), encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    rec.setdefault('images', [])
    rec.setdefault('asset', None)
    rec['id'] = mid
    return rec


def _write(rec: dict) -> dict:
    mid = rec['id']
    d = model_dir(mid)
    os.makedirs(os.path.join(d, 'images'), exist_ok=True)
    rec['updated'] = _now()
    tmp = _json_path(mid) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _json_path(mid))
    return rec


def create(name: str, subject: str = '') -> dict:
    with _LOCK:
        rec = _blank(name, subject)
        os.makedirs(os.path.join(model_dir(rec['id']), 'images'), exist_ok=True)
        return _write(rec)


def update(mid: str, fields: dict) -> dict | None:
    with _LOCK:
        rec = read(mid)
        if rec is None:
            return None
        for k in ('name', 'subject', 'notes'):
            if k in fields:
                rec[k] = str(fields.get(k) or '')[: 4000 if k == 'notes' else 120]
        for k in ('length_m', 'beam_m', 'height_m'):
            if k in fields:
                rec[k] = round(max(0.0, _num(fields.get(k), 0.0)), 4)
        return _write(rec)


def delete(mid: str) -> bool:
    with _LOCK:
        d = model_dir(mid)
        if not os.path.isdir(d):
            return False
        rec = read(mid)
        shutil.rmtree(d, ignore_errors=True)
        # THE PORTFOLIO FOLDER GOES WITH IT. It lives outside the model's own
        # directory, so it survived a delete and went on being listed on the
        # portfolio index page — four probe runs left four ghost projects there
        # before this existed. The path is derived, never taken off the wire.
        if rec:
            try:
                shutil.rmtree(portfolio_dir(rec), ignore_errors=True)
                _pf_root_index()
            except (OSError, KeyError) as _exc:
                _zyg_log.warning('portfolio cleanup after model delete failed, stale files remain: %s', _exc)
        # ...and let go of it if it was the open one. Leaving the id parked in
        # current.json makes current() answer '' for ever after, which the tab
        # shows as NO model selected and resolve('') turns into "which ship?" —
        # a rail that went quietly blank, with a live model sitting beside it.
        # (2026-09-23: current.json pointed at 3d7f96ccfb2b, a probe model
        # deleted at the end of a test run.)
        try:
            if current() == '' and _cur_id_raw() == str(mid):
                set_current('')
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('releasing the deleted model from current.json failed, the rail may stay blank: %s', _exc)
        return True


def _cur_id_raw() -> str:
    """What current.json literally says, valid or not."""
    try:
        with open(_cur_path(), encoding='utf-8') as fh:
            return str(json.load(fh).get('id') or '')
    except (OSError, ValueError):
        return ''


def models() -> list:
    out = []
    try:
        ids = sorted(os.listdir(REF_DIR))
    except OSError:
        return out
    for mid in ids:
        if not _mid_ok(mid) or not os.path.isdir(os.path.join(REF_DIR, mid)):
            continue
        rec = read(mid)
        if rec:
            out.append(rec)
    out.sort(key=lambda r: str(r.get('updated') or ''), reverse=True)
    return out


# ── the current model ────────────────────────────────────────────────────────
# Which reference the operator is working on. Parked on disk rather than in the
# tab, because the ASSISTANT has to know it too and it runs in another process.
def _cur_path() -> str:
    return os.path.join(REF_DIR, 'current.json')


def current() -> str:
    try:
        with open(_cur_path(), encoding='utf-8') as fh:
            mid = str(json.load(fh).get('id') or '')
    except (OSError, ValueError):
        return ''
    return mid if _mid_ok(mid) and os.path.isdir(os.path.join(REF_DIR, mid)) else ''


def set_current(mid: str) -> str:
    mid = str(mid or '')
    os.makedirs(REF_DIR, exist_ok=True)
    if mid and not (_mid_ok(mid) and os.path.isdir(os.path.join(REF_DIR, mid))):
        raise ValueError('no such reference model')
    with open(_cur_path(), 'w', encoding='utf-8') as fh:
        json.dump({'id': mid}, fh)
    return mid


def resolve(which: str = '') -> dict | None:
    """A model by id, by exact name, by slug, or — given nothing — the current
    one, or the only one there is. Returns None when the name is ambiguous or
    unknown, so a caller never silently builds against the wrong ship."""
    w = str(which or '').strip()
    if not w:
        mid = current()
        if mid:
            return read(mid)
        all_ = models()
        return all_[0] if len(all_) == 1 else None
    if _mid_ok(w):
        rec = read(w)
        if rec:
            return rec
    lw = w.lower()
    hits = [r for r in models() if str(r.get('name') or '').lower() == lw or slug(r.get('name')) == slug(w)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        hits = [r for r in models() if lw in str(r.get('name') or '').lower()]
    return hits[0] if len(hits) == 1 else None


# ── images ───────────────────────────────────────────────────────────────────
def _decode(data_url: str) -> tuple:
    """'data:image/png;base64,...' -> (bytes, mime). Raises ValueError."""
    m = re.match(r'data:(image/(?:jpeg|png|webp));base64,(.+)$', str(data_url or ''), re.S)
    if not m:
        raise ValueError('not a jpeg, png or webp data URL')
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f'the picture did not decode ({e})') from e
    if not raw:
        raise ValueError('the picture is empty')
    return raw, m.group(1)


def _pillow():
    try:
        from PIL import Image

        return Image
    except Exception:  # noqa: BLE001
        return None


def _normalise(raw: bytes, mime: str) -> tuple:
    """(bytes, mime, w, h). Resamples once when a side is over MAX_EDGE or the
    file is over MAX_IMAGE_BYTES — a plan keeps PNG (its value is crisp lines);
    a photograph becomes JPEG. Without Pillow the bytes are stored untouched."""
    Image = _pillow()
    if Image is None:
        return raw, mime, 0, 0
    import io

    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            w, h = im.size
            big = max(w, h) > MAX_EDGE
            if not big and len(raw) <= MAX_IMAGE_BYTES:
                return raw, mime, w, h
            if big:
                k = MAX_EDGE / float(max(w, h))
                im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
            buf = io.BytesIO()
            if mime == 'image/png' and im.mode in ('RGBA', 'LA', 'P'):
                im.save(buf, 'PNG', optimize=True)
                out_mime = 'image/png'
            else:
                im.convert('RGB').save(buf, 'JPEG', quality=92, optimize=True)
                out_mime = 'image/jpeg'
            return buf.getvalue(), out_mime, im.size[0], im.size[1]
    except Exception:  # noqa: BLE001
        return raw, mime, 0, 0


def model_bytes(mid: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(model_dir(mid)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError as _exc:
                _zyg_log.debug('disk-usage scan skipped a file: %s', _exc)
    return total


def add_image(mid: str, data_url: str, filename: str = '', role: str = DEFAULT_ROLE, note: str = '') -> dict:
    with _LOCK:
        rec = read(mid)
        if rec is None:
            raise ValueError('no such reference model')
        if len(rec['images']) >= MAX_IMAGES:
            raise ValueError(f'this reference model already holds {MAX_IMAGES} pictures')
        raw, mime = _decode(data_url)
        raw, mime, w, h = _normalise(raw, mime)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f'that picture is {len(raw) >> 20} MB — the limit is {MAX_IMAGE_BYTES >> 20} MB')
        if model_bytes(mid) + len(raw) > MAX_MODEL_BYTES:
            raise ValueError(f'this reference model is at its {MAX_MODEL_BYTES >> 20} MB ceiling')
        iid = uuid.uuid4().hex[:12]
        fn = iid + MIME_EXT.get(mime, '.jpg')
        with open(os.path.join(model_dir(mid), 'images', fn), 'wb') as fh:
            fh.write(raw)
        img = {
            'id': iid,
            'file': fn,
            'role': role if role in ROLES else DEFAULT_ROLE,
            'note': str(note or '')[:400],
            'name': str(filename or '')[:160],
            # span_m: how many metres the picture's FULL WIDTH covers. A plate
            # is rarely cropped to the subject's ends, so without this every
            # plan would be laid out too big by however much margin it carries.
            # flip: the plate reads the other way round (bow on the wrong
            # side). The file is never touched — only how it is laid out.
            'span_m': 0.0,
            'flip': False,
            # datum: the point IN THE PICTURE (u from the left, v from the
            # bottom, both 0..1) that is placed at the model's origin. A
            # plate is almost never drawn with the subject centred, and a
            # centred plate is the one thing a laid-out reference cannot
            # recover from — the geometry lines up in plan and floats in
            # section. Default (0.5, 0.5): the middle, as before.
            'datum': [0.5, 0.5],
            'w': w,
            'h': h,
            'bytes': len(raw),
            'added': _now(),
        }
        rec['images'].append(img)
        _write(rec)
        return img


def set_image(mid: str, iid: str, fields: dict) -> dict | None:
    with _LOCK:
        rec = read(mid)
        if rec is None:
            return None
        for img in rec['images']:
            if img.get('id') != iid:
                continue
            if 'role' in fields:
                r = str(fields.get('role') or '')
                img['role'] = r if r in ROLES else img.get('role', DEFAULT_ROLE)
            if 'note' in fields:
                img['note'] = str(fields.get('note') or '')[:400]
            if 'span_m' in fields:
                img['span_m'] = round(max(0.0, _num(fields.get('span_m'), 0.0)), 4)
            if 'flip' in fields:
                img['flip'] = bool(fields.get('flip') in (True, 1, '1', 'true', 'True', 'on'))
            if 'datum' in fields:
                d = fields.get('datum')
                if isinstance(d, str):
                    d = [x for x in re.split(r'[,\s]+', d.strip()) if x]
                try:
                    u, v = (min(1.0, max(0.0, float(d[0]))), min(1.0, max(0.0, float(d[1]))))
                except (TypeError, ValueError, IndexError):
                    u, v = 0.5, 0.5
                img['datum'] = [round(u, 4), round(v, 4)]
            _write(rec)
            return img
    return None


def del_image(mid: str, iid: str) -> bool:
    with _LOCK:
        rec = read(mid)
        if rec is None:
            return False
        gone = next((i for i in rec['images'] if i.get('id') == iid), None)
        if gone is None:
            return False
        keep = [i for i in rec['images'] if i.get('id') != iid]
        rec['images'] = keep
        for suffix in ('', '.th.jpg'):
            p = os.path.join(model_dir(mid), 'images', gone['file'] + suffix if suffix else gone['file'])
            try:
                os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('image file removal skipped: %s', _exc)
        _write(rec)
        return True


def image_path(mid: str, iid: str) -> str:
    rec = read(mid)
    for img in (rec or {}).get('images', []):
        if img.get('id') == iid:
            return os.path.join(model_dir(mid), 'images', img['file'])
    raise ValueError('no such picture')


def image_bytes(mid: str, iid: str, thumb: bool = False) -> tuple:
    """(bytes, mime) for one picture, or its cached 320 px thumbnail."""
    path = image_path(mid, iid)
    mime = EXT_MIME.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
    if not thumb:
        with open(path, 'rb') as fh:
            return fh.read(), mime
    tpath = path + '.th.jpg'
    if not os.path.exists(tpath) or os.path.getmtime(tpath) < os.path.getmtime(path):
        Image = _pillow()
        if Image is None:
            with open(path, 'rb') as fh:
                return fh.read(), mime
        with Image.open(path) as im:
            im = im.convert('RGB')
            k = THUMB_EDGE / float(max(im.size)) if max(im.size) > THUMB_EDGE else 1.0
            if k < 1.0:
                im = im.resize((max(1, round(im.size[0] * k)), max(1, round(im.size[1] * k))), Image.LANCZOS)
            im.save(tpath, 'JPEG', quality=78, optimize=True)
    with open(tpath, 'rb') as fh:
        return fh.read(), 'image/jpeg'


def image_b64(mid: str, iid: str, max_edge: int = 1400, max_bytes: int = 900_000) -> list | None:
    """[mime, base64] sized for a MODEL to look at. The cap is the point: a 4096
    px plan is ~4 MB of tokens and reads no better than 1400 px."""
    path = image_path(mid, iid)
    Image = _pillow()
    if Image is None:
        with open(path, 'rb') as fh:
            raw = fh.read()
        return [EXT_MIME.get(os.path.splitext(path)[1].lower(), 'image/jpeg'), base64.b64encode(raw).decode('ascii')]
    import io

    with Image.open(path) as im:
        im = im.convert('RGB')
        k = max_edge / float(max(im.size)) if max(im.size) > max_edge else 1.0
        if k < 1.0:
            im = im.resize((max(1, round(im.size[0] * k)), max(1, round(im.size[1] * k))), Image.LANCZOS)
        for q in (88, 72, 58, 44, 32):
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=q, optimize=True)
            if buf.tell() <= max_bytes or q == 32:
                return ['image/jpeg', base64.b64encode(buf.getvalue()).decode('ascii')]
    return None


# ── what the assistant is told ───────────────────────────────────────────────
def measurable(rec: dict) -> bool:
    """True when this reference can produce a model at real size. One measured
    length is the whole difference between a shape and a building."""
    return (
        _num((rec or {}).get('length_m')) > 0
        or _num((rec or {}).get('beam_m')) > 0
        or _num((rec or {}).get('height_m')) > 0
    )


def brief(rec: dict, verbose: bool = True) -> str:
    """The reference model in words, for a prompt or a tool reply."""
    if not rec:
        return 'no reference model'
    imgs = rec.get('images') or []
    by: dict = {}
    for i in imgs:
        by.setdefault(i.get('role') or DEFAULT_ROLE, []).append(i)
    parts = [f'"{rec.get("name")}" ({rec["id"]})']
    if rec.get('subject'):
        parts.append(f'subject: {rec["subject"]}')
    dims = [f'{k[:-2]} {_num(rec.get(k)):g} m' for k in ('length_m', 'beam_m', 'height_m') if _num(rec.get(k)) > 0]
    parts.append(
        'measured: ' + (', '.join(dims) if dims else 'NOTHING — shape only, this reference cannot fix a real size')
    )
    parts.append(
        f'{len(imgs)} picture'
        + ('' if len(imgs) == 1 else 's')
        + (': ' + ', '.join(f'{len(v)} {k}' for k, v in sorted(by.items())) if by else '')
    )
    if rec.get('asset'):
        a = rec['asset']
        parts.append(
            f'asset BUILT {a.get("built")}: {os.path.basename(a.get("glb") or "")}'
            + (f', place it with place_reference_asset (pack {a.get("pack")})' if a.get('pack') else '')
        )
    else:
        parts.append('no asset built yet')
    if verbose and rec.get('notes'):
        parts.append('notes: ' + str(rec['notes'])[:600])
    out = '; '.join(parts)
    if verbose and imgs:
        out += '\npictures:\n' + '\n'.join(
            f'  {i["id"]}  {i.get("role")}  {i.get("w") or "?"}x{i.get("h") or "?"}'
            + (f'  spans {_num(i.get("span_m")):g} m across' if _num(i.get('span_m')) > 0 else '')
            + ('  [laid out MIRRORED]' if i.get('flip') else '')
            + ('  datum %g,%g' % tuple(i['datum']) if (i.get('datum') or [0.5, 0.5]) != [0.5, 0.5] else '')
            + f'  {i.get("name") or ""}{("  — " + i["note"]) if i.get("note") else ""}'
            for i in sorted(imgs, key=lambda x: ROLE_ORDER.index(x.get('role')) if x.get('role') in ROLE_ORDER else 99)
        )
    return out


def public(rec: dict) -> dict:
    """The record as the tab wants it: no paths, thumbnails by URL."""
    if not rec:
        return {}
    out = dict(rec)
    out['measurable'] = measurable(rec)
    out['images'] = [
        dict(
            i,
            url=f'/inspect/api/architecture/ext/reference_model/image?m={rec["id"]}&i={i["id"]}',
            thumb=f'/inspect/api/architecture/ext/reference_model/image?m={rec["id"]}&i={i["id"]}&t=1',
        )
        for i in rec.get('images') or []
    ]
    a = rec.get('asset') or None
    if a:
        base = f'/inspect/api/architecture/ext/reference_model/preview?m={rec["id"]}'
        out['asset'] = dict(
            a,
            preview_url=(base if a.get('preview') else ''),
            sheet_url=(f'{base}&s=1' if a.get('sheet') else ''),
            check_urls=[
                {'url': f'{base}&k={n}', 'title': c.get('title') or ''} for n, c in enumerate(a.get('checks') or [])
            ],
            # a view that could not be taken is recorded with an
            # empty path and its reason; it must not become a
            # broken <img>, so it is dropped here and its note
            # travels on its own
            inspect_urls=[
                {'url': f'{base}&n={n}', 'title': i.get('title') or '', 'note': i.get('note') or ''}
                for n, i in enumerate(a.get('inspect') or [])
                if i.get('path')
            ],
            inspect_notes=[
                {'title': i.get('title') or '', 'note': i.get('note') or ''}
                for i in (a.get('inspect') or [])
                if not i.get('path')
            ],
            # THE PORTFOLIO: the sheets first (four glances at
            # fifty pictures), then every frame by index, and
            # the folder on disk as plain words — the operator
            # opens that folder, and a payload that only had
            # URLs in it would not tell them where it is
            portfolio_sheets=[
                {'url': f'{base}&ps={n}', 'title': f'contact sheet {n + 1}'}
                for n, _x in enumerate((a.get('portfolio') or {}).get('sheets') or [])
            ],
            portfolio_urls=[
                {'url': f'{base}&p={n}', 'title': i.get('title') or '', 'note': i.get('note') or ''}
                for n, i in enumerate(a.get('portfolio_shots') or [])
                if i.get('file')
            ],
            portfolio_notes=[
                {'title': i.get('title') or '', 'note': i.get('note') or ''}
                for i in (a.get('portfolio_shots') or [])
                if not i.get('file')
            ],
            portfolio_dir=((a.get('portfolio') or {}).get('dir') or ''),
            audit_findings=list((a.get('audit') or {}).get('findings') or []),
        )
        # "no paths" is the docstring's promise: the record holds absolute
        # filesystem paths for every render and they have no business in a
        # browser payload. glb/blend stay as BARE FILE NAMES — the sheet uses
        # `a.glb` as its "is anything built?" test, so dropping them outright
        # blanks the panel.
        for named in ('glb', 'blend'):
            out['asset'][named] = os.path.basename(a.get(named) or '')
        for dead in (
            'preview',
            'sheet',
            'checks',
            'inspect',
            'script',
            'edits',
            'portfolio',
            'portfolio_shots',
            'audit',
        ):
            out['asset'].pop(dead, None)
    return out


# ── THE PORTFOLIO FOLDER (2026-09-23) ────────────────────────────────────────
# The operator's standing rule after the ten-picture inspection set: "after
# every drawing, make sure ai assistant delivers portfolio folder with 40+
# images from projects". The folder is the DELIVERABLE — data/architecture/
# portfolio/<name>-<id>/ — with every frame numbered in the order the cameras
# were planned, the measurement each camera made under it, contact sheets, and
# the surface audit at the top of index.html.
#
# It lives in the store rather than in the assistant's tool module because it
# needs nothing from a drawing: a probe, a cron job or a standalone script must
# be able to write one, and importing arch_assistant to do it would close every
# live conversation the studio has open.
PORTFOLIO_DIR = os.path.join(HERE, 'data', 'architecture', 'portfolio')
SHEET_COLS, SHEET_PER = 5, 12


def contact_sheet(shots: list, dest: str) -> str:
    """A captioned contact sheet of the frames in `shots` ({path, title}).
    Returns dest, or '' when Pillow is missing or nothing could be drawn."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ''
    live = [s for s in shots if s.get('path') and os.path.isfile(s['path'])]
    if not live:
        return ''
    cols, cw, ch, pad, bar = SHEET_COLS, 520, 300, 8, 22
    rows = (len(live) + cols - 1) // cols
    try:
        sheet = Image.new('RGB', (cols * cw + (cols + 1) * pad, rows * (ch + bar) + (rows + 1) * pad), (250, 250, 248))
        dr = ImageDraw.Draw(sheet)
        for n, s in enumerate(live):
            with Image.open(s['path']) as im:
                im = im.convert('RGB')
                im.thumbnail((cw, ch), Image.LANCZOS)
                cx = pad + (n % cols) * (cw + pad)
                cy = pad + (n // cols) * (ch + bar + pad)
                sheet.paste(im, (cx + (cw - im.width) // 2, cy + (ch - im.height) // 2))
            dr.rectangle([cx, cy + ch, cx + cw, cy + ch + bar], fill=(232, 232, 228))
            dr.text((cx + 6, cy + ch + 5), f'{n + 1}. {s.get("title") or ""}', fill=(25, 25, 25))
        sheet.save(dest)
    except Exception:  # noqa: BLE001
        return ''
    return dest if os.path.isfile(dest) else ''


def _pf_sheets(shots: list, root: str) -> list:
    """The portfolio in sheets of SHEET_PER, so fifty pictures read in four
    glances. Returns the sheet paths."""
    out = []
    live = [s for s in shots if s.get('path') and os.path.isfile(s['path'])]
    for n in range(0, len(live), SHEET_PER):
        got = contact_sheet(live[n : n + SHEET_PER], os.path.join(root, f'contact-sheet-{n // SHEET_PER + 1}.png'))
        if got:
            out.append(got)
    return out


def _pf_index(root: str, rec: dict, kept: list, sheets: list, audit: dict, meta: dict) -> str:
    """One page that opens the whole folder in a browser: every picture with
    the measurement its camera made under it, the audit findings at the top,
    and a link to each full-size file. A folder of fifty PNGs named by number
    is not a deliverable — it is a pile."""

    def esc(t):
        return (
            str(t if t is not None else '')
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

    rows = []
    for n, k in enumerate(kept):
        cap = f'<figcaption><b>{n + 1}. {esc(k["title"])}</b><br>{esc(k["note"])}</figcaption>'
        if k.get('file'):
            rows.append(
                f'<figure><a href="{esc(k["file"])}"><img src="{esc(k["file"])}" loading="lazy"></a>'
                + cap
                + '</figure>'
            )
        else:
            rows.append('<figure class="none"><div class="no">NO PICTURE</div>' + cap + '</figure>')
    html = (
        '<!doctype html><meta charset="utf-8"><title>' + esc(rec.get('name')) + ' — portfolio</title>'
        '<style>body{background:#14161a;color:#e8e6e1;font:14px/1.45 system-ui,sans-serif;margin:24px}'
        'h1{font-size:20px;margin:0 0 4px}.sub{color:#9aa0a6;margin-bottom:18px}'
        '.find{background:#2a1d1d;border-left:3px solid #c0554a;padding:8px 12px;margin:6px 0;border-radius:4px}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}'
        'figure{margin:0;background:#1c1f24;border-radius:6px;overflow:hidden}'
        'img{width:100%;display:block}figcaption{padding:8px 10px;color:#b8bcc2;font-size:12px}'
        '.no{padding:48px 0;text-align:center;color:#c0554a;font-weight:600}a{color:#7fb3ff}</style>'
        f'<h1>{esc(rec.get("name"))} — portfolio</h1>'
        f'<div class="sub">{len([k for k in kept if k.get("file")])} pictures · {esc(meta.get("built"))} · '
        f'{esc(meta.get("dims"))} · {meta.get("tris", 0)} triangles · engine {esc(meta.get("engine"))}</div>'
        + ''.join(f'<div class="find">{esc(f)}</div>' for f in (audit or {}).get('findings') or [])
        + (
            '<p>'
            + ' · '.join(
                f'<a href="{esc(os.path.basename(x))}">contact sheet {i + 1}</a>' for i, x in enumerate(sheets)
            )
            + '</p>'
            if sheets
            else ''
        )
        + '<div class="grid">'
        + ''.join(rows)
        + '</div>'
    )
    dest = os.path.join(root, 'index.html')
    with open(dest, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return dest


def portfolio_dir(rec: dict) -> str:
    return os.path.join(PORTFOLIO_DIR, f'{slug(rec.get("name")) or "model"}-{rec["id"]}')


def write_portfolio(rec: dict, shots: list, audit: dict, meta: dict) -> dict:
    """Write THE PORTFOLIO FOLDER and return {dir, index, shots, sheets, n,
    planned}. The folder is SWEPT of its own last build first: a folder that
    mixes two builds says nothing about either, and that trap was already paid
    for once beside the asset."""
    root = portfolio_dir(rec)
    os.makedirs(root, exist_ok=True)
    for name in os.listdir(root):
        if name.endswith('.png') or name in ('index.html', 'portfolio.json'):
            try:
                os.remove(os.path.join(root, name))
            except OSError as _exc:
                _zyg_log.debug('stale portfolio file removal skipped: %s', _exc)
    kept = []
    for n, im in enumerate(shots):
        title = str(im.get('title') or 'view')
        s = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        src = im.get('path') or ''
        row = {'title': title, 'note': str(im.get('note') or ''), 'file': '', 'path': ''}
        if src and os.path.exists(src):
            dst = os.path.join(root, f'{n + 1:02d}-{s}.png')
            shutil.copy2(src, dst)
            row['file'], row['path'] = os.path.basename(dst), dst
        kept.append(row)
    sheets = _pf_sheets(kept, root)
    index = _pf_index(root, rec, kept, sheets, audit, meta)
    with open(os.path.join(root, 'portfolio.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'model': rec.get('id'),
                'name': rec.get('name'),
                'built': meta.get('built'),
                'engine': meta.get('engine'),
                'dims': meta.get('dims'),
                'tris': meta.get('tris'),
                'shots': [{k: v for k, v in r.items() if k != 'path'} for r in kept],
                'sheets': [os.path.basename(x) for x in sheets],
                'audit': audit or {},
            },
            fh,
            indent=1,
        )
    _pf_root_index()
    return {
        'dir': root,
        'index': index,
        'shots': kept,
        'sheets': sheets,
        'n': len([k for k in kept if k['file']]),
        'planned': len(kept),
    }


def _pf_root_index() -> str:
    """data/architecture/portfolio/index.html — ONE page listing every project
    that has a portfolio, newest first, each with its first contact sheet.

    The operator asked for "portfolio folder with 40+ images from projects",
    plural: a folder per project is only half of that if you have to know the
    folder's name to find it. Rebuilt on every write, from what is on disk, so
    a folder deleted by hand simply stops being listed."""
    rows = []
    try:
        names = sorted(os.listdir(PORTFOLIO_DIR))
    except OSError:
        return ''
    for name in names:
        d = os.path.join(PORTFOLIO_DIR, name)
        meta = os.path.join(d, 'portfolio.json')
        if not os.path.isdir(d) or not os.path.isfile(meta):
            continue
        try:
            with open(meta, encoding='utf-8') as fh:
                j = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('portfolio meta unreadable, folder skipped in the listing: %s', _exc)
            continue
        shots = j.get('shots') or []
        rows.append((os.path.getmtime(meta), name, j, len([x for x in shots if x.get('file')]), len(shots)))
    rows.sort(reverse=True)

    def esc(t):
        return (
            str(t if t is not None else '')
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

    cards = []
    for _mt, name, j, n, planned in rows:
        sheet = (j.get('sheets') or [''])[0]
        find = (j.get('audit') or {}).get('findings') or []
        cards.append(
            f'<a class="card" href="{esc(name)}/index.html">'
            + (f'<img src="{esc(name)}/{esc(sheet)}" loading="lazy">' if sheet else '')
            + f'<div class="cap"><b>{esc(j.get("name"))}</b><br>{n} of {planned} pictures · '
            f'{esc(j.get("built"))} · {esc(j.get("dims"))}'
            + (f'<br><span class="bad">{len(find)} audit finding(s)</span>' if find else '')
            + '</div></a>'
        )
    html = (
        '<!doctype html><meta charset="utf-8"><title>Architecture portfolios</title>'
        '<style>body{background:#14161a;color:#e8e6e1;font:14px/1.45 system-ui,sans-serif;margin:24px}'
        'h1{font-size:20px;margin:0 0 14px}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}'
        '.card{display:block;background:#1c1f24;border-radius:8px;overflow:hidden;text-decoration:none;'
        'color:inherit}.card img{width:100%;display:block}.cap{padding:10px 12px;font-size:12px;'
        'color:#b8bcc2}.bad{color:#ff9c8a}</style>'
        f'<h1>Architecture portfolios — {len(rows)} project'
        + ('' if len(rows) == 1 else 's')
        + '</h1><div class="grid">'
        + ''.join(cards)
        + '</div>'
    )
    dest = os.path.join(PORTFOLIO_DIR, 'index.html')
    try:
        with open(dest, 'w', encoding='utf-8') as fh:
            fh.write(html)
    except OSError:
        return ''
    return dest
