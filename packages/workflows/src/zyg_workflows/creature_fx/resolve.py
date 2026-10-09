# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / resolving a creature, its images, its mesh and its bakes — the path fence that also writes.

Moved verbatim out of the old single-file creature_fx.py (lines 4420-4818, 5407-5489).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import logging as _zyg_logging

from zyg_workflows.creature_fx.base import (
    BASES_JSON,
    CATS,
    DS_ROOT,
    FLUX1_FAMILIES,
    GEN_PREVIEWS,
    ID_RE,
    IMG_EXT,
    LICENCES,
    NAME_RE,
    OUT_ROOT,
    PACKS_ROOT,
    PROP_ROOT,
    STUDIO_CAT,
)


_zyg_log = _zyg_logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  THE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

# ── resolving a creature and one of its images ──────────────────────────────
# The caller supplies (id, category, name) and NEVER a path fragment: the id is
# 12 hex, the name is basename-only against a bounded charset, the category is a
# key in CATS, and the final realpath must sit inside that category's directory
# inside the right root. Same fence as the image route, for the same reason --
# this one also WRITES.


def _cdir(cid, root=None):
    if not ID_RE.match(str(cid or '')):
        raise ValueError('bad creature id')
    root = root or DS_ROOT
    d = os.path.realpath(os.path.join(root, cid))
    if not (d == os.path.join(root, cid) and os.path.isdir(d)):
        raise ValueError('no such creature')
    return d


def _catdir(cid, cat, make=False):
    if cat not in CATS:
        raise ValueError(f'bad category: {cat}')
    sub, _ = CATS[cat]
    if cat == 'val':
        # Validation frames sit under <weights>/validation_images, not beside the
        # weights -- the same path the Creatures tab serves them from. And they
        # are the LoRA talking, not the dataset: a creature trained before
        # 2026-08-26 has HUMAN frames here, which is why the tab labels them
        # rather than presenting them as the creature ([[project_inspection_creatures_tab]]).
        base = _cdir(cid, OUT_ROOT)
        for fam in sorted(os.listdir(base)):
            if not fam.startswith('lora-weights-'):
                continue
            d = os.path.join(base, fam, 'validation_images')
            if os.path.isdir(d):
                return d
        return base
    base = _cdir(cid)
    d = os.path.realpath(os.path.join(base, sub)) if sub else base
    if make:
        os.makedirs(d, exist_ok=True)
    if not d.startswith(base):
        raise ValueError('category escaped the dataset')
    return d


def resolve_image(cid, cat, name):
    """(id, cat, name) -> an absolute path to a real image inside that category."""
    if not NAME_RE.match(str(name or '')) or os.path.basename(name) != name:
        raise ValueError('bad image name')
    if not str(name).lower().endswith(IMG_EXT):
        raise ValueError('not an image')
    d = _catdir(cid, cat)
    fp = os.path.realpath(os.path.join(d, name))
    if not (fp.startswith(d + os.sep) and os.path.isfile(fp)):
        raise ValueError('no such image')
    return fp


def _manifest(cid):
    d = _cdir(cid)
    man = {}
    for fn in ('manifest.json', 'brief.json'):
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as fh:
                man = {**(json.load(fh) or {}), **man}
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('creature manifest %s unreadable: %s', fn, _exc)
            continue
    return man


def licence_of(cid):
    """The licence a NEW image of this creature would inherit.

    Read off the family the same way the Creatures tab reads it -- weights
    directory name first, manifest second -- because the three May creatures
    predate `train_family` and a blank licence on a monetised channel is the
    one answer that must never be blank ([[project_licence_gate]])."""
    man = _manifest(cid)
    fam = (man.get('train_family') or '').strip().lower()
    if not fam:
        try:
            base = _cdir(cid, OUT_ROOT)
            for fn in sorted(os.listdir(base)):
                if fn.startswith('lora-weights-'):
                    fam = fn.split('lora-weights-', 1)[1].strip().lower()
                    break
        except Exception:  # noqa: BLE001
            fam = ''
    lic, ok, note = LICENCES.get(fam, ('unknown', None, 'no trained weights yet — licence follows the base model'))
    return {
        'family': fam,
        'licence': lic,
        'commercial_ok': ok,
        'note': note,
        'render_blocked': fam in FLUX1_FAMILIES,
        'block_note': (
            'FLUX.1-dev is non-commercial and the channel is monetised: '
            'the studio will not render NEW imagery for this creature. '
            'Deterministic pixel ops on what is already on disk still run.'
        )
        if fam in FLUX1_FAMILIES
        else '',
    }


def _imglist(cid):
    """Every image this creature owns, by category, newest first within one."""
    out = []
    for cat in CATS:
        try:
            d = _catdir(cid, cat)
        except ValueError as _exc:
            _zyg_log.debug('creature category dir unavailable: %s', _exc)
            continue
        try:
            names = os.listdir(d)
        except OSError as _exc:
            _zyg_log.debug('creature category listing skipped: %s', _exc)
            continue
        rows = []
        for n in sorted(names):
            if not n.lower().endswith(IMG_EXT) or not NAME_RE.match(n):
                continue
            fp = os.path.join(d, n)
            if not os.path.isfile(fp):
                continue
            if cat == 'preview' and not n.startswith('preview_'):
                continue
            if cat == 'ref' and not n.startswith('ref_'):
                continue
            rows.append(
                {
                    'cat': cat,
                    'name': n,
                    'label': CATS[cat][1],
                    'mtime': round(os.path.getmtime(fp), 3),
                    'bytes': os.path.getsize(fp),
                }
            )
        rows.sort(key=lambda r: r['name'])
        out.extend(rows[:80])
    return out


def _anchor_path(cid):
    """The identity anchor: what an edit is scored AGAINST.

    Priority is the operator's own full-body lock, then the derived anchor the
    sheet built, then the front preview. A lock beats a derived anchor because
    the operator picked it BY HAND as this creature ([[creature_sheet_service]])."""
    man = _manifest(cid)
    locks = man.get('anchor_locks') or {}
    for k in ('full_body', 'side'):
        p = locks.get(k)
        if p and os.path.isfile(p):
            return p, f'operator lock ({k})'
    for cat, pref in (('anchor', 'ref_00'), ('anchor', ''), ('preview', 'preview_front')):
        try:
            d = _catdir(cid, cat)
        except ValueError as _exc:
            _zyg_log.debug('anchor category dir unavailable: %s', _exc)
            continue
        try:
            names = sorted(n for n in os.listdir(d) if n.lower().endswith(IMG_EXT) and NAME_RE.match(n))
        except OSError as _exc:
            _zyg_log.debug('anchor category listing skipped: %s', _exc)
            continue
        hit = [n for n in names if n.startswith(pref)] if pref else names
        if hit:
            return os.path.join(d, hit[0]), CATS[cat][1]
    return '', ''


def _under(path, root):
    """Is `path` a real file inside `root` after every symlink is resolved?"""
    if not path:
        return ''
    full = os.path.realpath(str(path))
    if not (full == root or full.startswith(root + os.sep)):
        return ''
    return full if os.path.isfile(full) else ''


def mesh_glb_path(cid):
    """Absolute path of the GLB the studio route may stream for one creature.

    The fence for /inspect/api/studio/creature/glb: the id has to be an id, the
    file has to be a .glb, and after realpath it has to sit inside this
    creature's own dataset dir or inside the prop-mesh library. A manifest is
    operator-written data, so its path is a REQUEST, not permission."""
    cid = str(cid or '')
    if not ID_RE.match(cid):
        return ''
    try:
        man, cdir = _manifest(cid), os.path.realpath(_cdir(cid))
    except ValueError:  # a well-formed id for a creature that is not there
        return ''
    for key in ('mesh_asset', 'mesh_recon'):
        blk = man.get(key)
        if not isinstance(blk, dict):
            continue
        glb = str(blk.get('glb') or '')
        if not glb.lower().endswith('.glb'):
            continue
        hit = _under(glb, cdir) or _under(glb, PROP_ROOT)
        if hit:
            return hit
    return ''


def creature_mesh(cid, man=None):
    """Where the 3D view should get this creature's own mesh, or ''.

    Preference order is authored-then-reconstructed: a mesh somebody modelled
    beats a 34 MB TRELLIS point-cloud-with-triangles every time. An empty
    glb_url is not a failure -- it means the page shows a base creature."""
    man = _manifest(cid) if man is None else man
    for key, vfn in (
        ('mesh_asset', lambda b: b.get('vertices')),
        ('mesh_recon', lambda b: (b.get('geometry') or {}).get('vertices')),
    ):
        blk = man.get(key)
        if not isinstance(blk, dict):
            continue
        glb = str(blk.get('glb') or '')
        if not glb.lower().endswith('.glb'):
            continue
        pack_hit = _under(glb, PACKS_ROOT)
        if pack_hit:
            rel = os.path.relpath(pack_hit, PACKS_ROOT).replace(os.sep, '/')
            url = f'/inspect/arch-asset/{rel}'
        elif _under(glb, os.path.realpath(_cdir(cid))) or _under(glb, PROP_ROOT):
            url = f'/inspect/api/studio/creature/glb?id={cid}'
        else:
            continue
        verts = vfn(blk)
        # A reconstruction's `licence` is a whole chain-of-components dict, not
        # a word. Stringifying that puts 2 KB of JSON in a label, so a dict
        # without a single headline licence is reported as what it is.
        lic = blk.get('licence')
        if isinstance(lic, dict):
            lic = lic.get('licence') or 'mixed (see manifest)'
        return {
            'glb_url': url,
            'source': key,
            'verts': int(verts) if isinstance(verts, (int, float)) else None,
            'licence': str(lic or (licence_of(cid) or {}).get('licence') or ''),
        }
    return {'glb_url': '', 'source': '', 'verts': None, 'licence': ''}


def _asset_url(rel):
    """/inspect/arch-asset/<rel> with each path segment percent-encoded.

    The Kenney packs ship directories with a space in the name ("GLB format"),
    which is a perfectly good file name and a broken URL."""
    return '/inspect/arch-asset/' + '/'.join(urllib.parse.quote(seg) for seg in str(rel).split('/') if seg)


def _base_preview(pack, fn):
    """The library's pre-rendered thumbnail for one pack file, or ''.

    build_all_libraries writes them to mesh_packs/_generated_previews/<pack>/
    <first path segment>/<basename>.png. Not every pack has been rendered, so
    this is checked on disk and the picker falls back to a plain button."""
    parts = str(fn).split('/')
    stem = os.path.splitext(parts[-1])[0]
    rel = '/'.join([GEN_PREVIEWS, pack] + parts[:-1][:1] + [stem + '.png'])
    if not _under(os.path.join(PACKS_ROOT, rel), PACKS_ROOT):
        return ''
    return _asset_url(rel)


def base_creatures():
    """The third-party CC0 base creatures, read from BASES.json.

    The list is task 1's: Quaternius animals first, then the Kenney cube-pets,
    then the Smithsonian deer — every one of them CC0 and none of them ours.
    Each row keeps its declared fields and gains `url` (and `prev` when the
    library has a thumbnail). A row whose file is not on disk, or whose path
    escapes the pack root, is dropped rather than shipped as a dead button."""
    try:
        with open(BASES_JSON, encoding='utf-8') as fh:
            rows = json.load(fh)
    except (OSError, ValueError) as exc:
        _zyg_log.info(f'[creature_fx] no base creatures: {BASES_JSON}: {exc}')
        return []
    out = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        pack, fn = str(it.get('pack') or ''), str(it.get('file') or '')
        if not pack or not fn or not NAME_RE.match(pack):
            continue
        if not _under(os.path.join(PACKS_ROOT, pack, fn), PACKS_ROOT):
            continue
        rec = dict(it)
        # /inspect/arch-asset/ is served with max-age=86400 and no ETag, so a
        # rebuilt base (same path, new bytes) would sit behind the browser's
        # cache for a day. The file's mtime in the query busts it per build.
        try:
            ver = int(os.path.getmtime(os.path.join(PACKS_ROOT, pack, fn)))
        except OSError:
            ver = 0
        rec['url'] = _asset_url(f'{pack}/{fn}') + f'?v={ver}'
        rec['prev'] = _base_preview(pack, fn)
        if rec['prev']:
            rec['prev'] += f'?v={ver}'
        out.append(rec)
    return out


# Resolved once at import, like the rest of the registry: the pack is content,
# not state. Reload the module (or the server) after changing BASES.json.
BASE_CREATURES = base_creatures()


def creature_facts(cid):
    """Everything the toolbox needs about one creature, in one read."""
    man = _manifest(cid)
    lic = licence_of(cid)
    anchor, anchor_kind = _anchor_path(cid)
    imgs = _imglist(cid)
    hero = man.get('hero_image') if isinstance(man.get('hero_image'), dict) else None
    return {
        'ok': True,
        'id': cid,
        'name': man.get('name') or cid,
        'species': man.get('species') or '',
        'description': man.get('description') or '',
        'body_plan': man.get('body_plan') or '',
        'style_hint': man.get('style_hint') or '',
        'trigger': man.get('trigger_token') or '',
        'status': man.get('status') or '',
        'licence': lic,
        'anchor': ({'path': anchor, 'kind': anchor_kind, 'name': os.path.basename(anchor)} if anchor else None),
        'hero': hero,
        'mesh': creature_mesh(cid, man),
        'images': imgs,
        'counts': {c: sum(1 for r in imgs if r['cat'] == c) for c in CATS},
        'paths': {
            'dataset': _cdir(cid),
            'studio': os.path.join(_cdir(cid), 'studio'),
            'weights': man.get('lora_path') or '',
        },
        'sheet': man.get('sheet_report') or {},
        'comfy': comfy_up(),
        'bakes': list_bakes(cid),
    }


def comfy_up():
    """Is the render backend reachable? Cached briefly -- the rail asks on every
    redraw and a 2 s timeout per redraw would be its own bug."""
    now = time.time()
    if _COMFY['t'] > now - 20:
        return _COMFY['v']
    try:
        _ensure_comfy_env()
        from zyg_workflows import comfy_generation_service as cgs

        v = bool(cgs.is_available())
    except Exception:  # noqa: BLE001
        v = False
    _COMFY.update(t=now, v=v)
    return v


_COMFY = {'t': 0.0, 'v': False}


def _ensure_comfy_env():
    """Route stills through ComfyUI from THIS process.

    comfy_generation_service.is_available() is False unless ZYG_COMFY_PRIMARY
    (or the legacy ZYG_USE_COMFYUI) is set in the environment, and the
    kanban-server unit does not export either -- it runs a bare python with no
    EnvironmentFile, so the .env that sets them for the pipeline never reaches
    it. Every other in-process caller of the render backend does exactly this
    first (creature_training_service._ensure_comfy_env, video_studio,
    kids_video_service); without it the studio would report "ComfyUI
    unavailable" while ComfyUI was answering on :8188."""
    try:
        from zyg_workflows import _comfy_client as _cc
    except ImportError:
        return
    try:
        if _cc.server_reachable():
            os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
            os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    except Exception:  # noqa: BLE001
        return


# ── bakes: the derived images this studio owns ──────────────────────────────
# Every bake is a PNG plus a JSON sidecar of the same stem. The sidecar is the
# whole recipe -- source, stack, instruction, seeds, measurements, inherited
# licence -- because a bake you cannot reproduce is a bake you do not have.


def _studio_dir(cid, make=False):
    d = os.path.join(_cdir(cid), 'studio')
    if make:
        os.makedirs(d, exist_ok=True)
    return d


def _slug(t, n=28):
    t = re.sub(r'[^a-z0-9]+', '_', str(t or '').lower()).strip('_')
    return t[:n] or 'edit'


def list_bakes(cid):
    d = _studio_dir(cid)
    out = []
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return out
    for n in names:
        if not n.lower().endswith('.png'):
            continue
        side = os.path.join(d, n[:-4] + '.json')
        rec = {}
        try:
            with open(side, encoding='utf-8') as fh:
                rec = json.load(fh) or {}
        except (OSError, ValueError):
            rec = {}
        out.append(
            {
                'name': n,
                'cat': STUDIO_CAT,
                'when': rec.get('when', ''),
                'summary': rec.get('summary', ''),
                'identity': (rec.get('measured') or {}).get('identity'),
                'change': (rec.get('measured') or {}).get('change_bits'),
                'gen': rec.get('gen_count', 0),
                'seed': rec.get('seed'),
                'licence': (rec.get('licence') or {}).get('licence', ''),
                'has_recipe': bool(rec),
            }
        )
    return out[:120]


def read_recipe(cid, name):
    if not NAME_RE.match(str(name or '')):
        raise ValueError('bad name')
    fp = os.path.join(_studio_dir(cid), os.path.basename(name)[:-4] + '.json')
    with open(fp, encoding='utf-8') as fh:
        return json.load(fh)


def _write_bake(cid, im, comp, meta):
    d = _studio_dir(cid, make=True)
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
            'clauses': comp['clauses'],
        }
    )
    with open(os.path.join(d, stem + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2)
    return png, meta
