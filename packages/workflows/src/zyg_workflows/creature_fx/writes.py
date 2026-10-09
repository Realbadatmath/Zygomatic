# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / the writes — hero, anchor lock and training tile are three blast radii, so three acts.

Moved verbatim out of the old single-file creature_fx.py (lines 5832-6018).
"""

from __future__ import annotations

import json
import os
import shutil
import time

from zyg_workflows.creature_fx.base import NAME_RE
from zyg_workflows.creature_fx.resolve import _cdir, _manifest, _studio_dir, resolve_image


# ── the writes ──────────────────────────────────────────────────────────────
# Everything here writes INTO the creature, and nothing here writes OVER one of
# its pipeline images. The three promotions are separate acts on purpose: hero
# changes what the card shows, anchor-lock changes what the next SHEET is
# rotated from, and training tile changes what the next LoRA is made of. Those
# are three different blast radii and a single "save" button would hide that.


def _read_json(fp):
    try:
        with open(fp, encoding='utf-8') as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _write_json(fp, data):
    tmp = fp + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, fp)


def _bake_path(cid, name):
    """Resolve a name that MUST be a studio bake of this creature.

    Every destructive or promoting action funnels through here, so there is
    exactly one place that decides what this dock is allowed to touch."""
    if not NAME_RE.match(str(name or '')) or not str(name).lower().endswith('.png'):
        raise ValueError('bad bake name')
    d = _studio_dir(cid)
    fp = os.path.realpath(os.path.join(d, os.path.basename(name)))
    if not (fp.startswith(d + os.sep) and os.path.isfile(fp)):
        raise ValueError('no such studio edit')
    return fp


def apply_action(body):
    """One entry point for every write the dock can make."""
    cid = str((body or {}).get('id') or '')
    act = str((body or {}).get('act') or '')
    _cdir(cid)
    ds = _cdir(cid)
    man_fp = os.path.join(ds, 'manifest.json')
    brief_fp = os.path.join(ds, 'brief.json')

    if act == 'hero':
        cat = str(body.get('cat') or '')
        name = str(body.get('name') or '')
        resolve_image(cid, cat, name)  # the fence, not a formality
        man = _read_json(man_fp)
        man['hero_image'] = {'cat': cat, 'name': name}
        _write_json(man_fp, man)
        return {'ok': True, 'msg': f'Hero image set to {cat}/{name}.'}

    if act == 'lock':
        which = str(body.get('which') or 'full_body')
        if which not in ('full_body', 'side'):
            return {'ok': False, 'error': 'a lock is full_body or side'}
        src = _bake_path(cid, body.get('name'))
        locks = os.path.join(ds, 'locks')
        os.makedirs(locks, exist_ok=True)
        dst = os.path.join(locks, f'{which}_studio_{int(time.time())}.png')
        shutil.copy2(src, dst)
        # brief.json is where creature_lock.py keeps them and where the sheet
        # service reads them; the manifest carries a copy for the card.
        for fp in (brief_fp, man_fp):
            d = _read_json(fp)
            if not d and fp == brief_fp:
                continue
            d.setdefault('anchor_locks', {})[which] = dst
            _write_json(fp, d)
        return {
            'ok': True,
            'msg': f'{which} lock set. Re-render the sheet to use it:',
            'cmd': f'scripts/creature_worker.py --resume {cid} --phase sheet',
            'note': 'Cells rotated from the changed anchor re-render; the rest come back from their checkpoints.',
        }

    if act == 'tile':
        src = _bake_path(cid, body.get('name'))
        cap = str(body.get('caption') or '').strip()
        man = _read_json(man_fp)
        trig = man.get('trigger_token') or ''
        if not cap:
            bits = [trig, man.get('description') or man.get('name') or '']
            cap = ', '.join([b_ for b_ in bits if b_])
        tdir = os.path.join(ds, 'training')
        os.makedirs(tdir, exist_ok=True)
        n = len([f_ for f_ in os.listdir(tdir) if f_.endswith('.png')])
        stem = f'studio_{n:02d}_{int(time.time()) % 100000}'
        shutil.copy2(src, os.path.join(tdir, stem + '.png'))
        with open(os.path.join(tdir, stem + '.txt'), 'w', encoding='utf-8') as fh:
            fh.write(cap)
        return {
            'ok': True,
            'msg': f'Added {stem}.png to the training set with its caption. '
            f'It trains on the NEXT LoRA run, not this one.',
            'caption': cap,
        }

    if act == 'ref':
        src = _bake_path(cid, body.get('name'))
        dst = os.path.join(ds, f'ref_studio_{int(time.time()) % 1000000}.png')
        shutil.copy2(src, dst)
        return {'ok': True, 'msg': f'Filed as {os.path.basename(dst)}.'}

    if act == 'delete':
        src = _bake_path(cid, body.get('name'))
        side = src[:-4] + '.json'
        os.unlink(src)
        if os.path.isfile(side):
            os.unlink(side)
        return {'ok': True, 'msg': f'Deleted {os.path.basename(src)} and its recipe.'}

    if act == 'brief':
        fields = {
            k: str(v)[:2000]
            for k, v in (body.get('fields') or {}).items()
            if k in ('name', 'species', 'description', 'body_plan', 'style_hint')
        }
        if not fields:
            return {'ok': False, 'error': 'nothing to write'}
        for fp in (brief_fp, man_fp):
            d = _read_json(fp)
            if not d and fp == brief_fp:
                continue
            d.update(fields)
            _write_json(fp, d)
        return {
            'ok': True,
            'msg': 'Brief updated. Every instruction, caption and judge question built from here on uses it.',
            'fields': fields,
        }

    return {'ok': False, 'error': f'no such action: {act}'}


def pipeline_commands(cid):
    """The exact commands for the two jobs this studio deliberately does NOT start.

    Rebuilding a sheet is ~25 GPU-minutes and retraining is hours. Both are
    started from the pipeline that owns them, and a studio that could launch
    either behind one click is a studio that eats a night's queue by mis-click.
    So it hands over the command, with the creature id already in it."""
    man = _manifest(cid)
    ds = _cdir(cid)
    return {
        'ok': True,
        'rows': [
            {
                'what': 'Re-render the contact sheet from the current anchors and body plan',
                'cmd': f'scripts/creature_worker.py --resume {cid} --phase sheet',
                'cost': '~25 minutes on the 4090; cells whose source did not change come back from their checkpoints',
            },
            {
                'what': 'Set or show the body-plan lock',
                'cmd': f'python3 scripts/creature_lock.py {cid} --show',
                'cost': 'instant',
            },
            {
                'what': "Render operator candidates through the pipeline's own conform pass",
                'cmd': f'python3 scripts/creature_variants.py {cid} --source IMG --out DIR '
                f'--variant "A=..." --variant "B=..."',
                'cost': 'minutes per variant per seed',
            },
            {
                'what': 'Re-judge and reclassify the existing sheet cells',
                'cmd': f'python3 scripts/creature_reclassify.py {cid}',
                'cost': 'VLM only, no image renders',
            },
            {
                'what': 'Retrain the LoRA on the current training tiles',
                'cmd': f'python3 scripts/creature_worker.py --resume {cid} --phase train',
                'cost': 'hours; replaces the weights every render of this creature uses',
            },
        ],
        'paths': {
            'dataset': ds,
            'training': os.path.join(ds, 'training'),
            'locks': os.path.join(ds, 'locks'),
            'studio': _studio_dir(cid),
            'weights': man.get('lora_path') or '(none)',
        },
    }
