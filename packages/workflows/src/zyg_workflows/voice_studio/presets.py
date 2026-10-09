# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.presets — the preset store.

Moved verbatim from voice_studio.py lines 1570-1768 (2026-10-06 split).
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import re
import shutil
import time

from zyg_workflows.voice_studio.constants import (
    MAX_PREVIEW_CHARS,
    PRESET_ROOT,
)
from zyg_workflows.voice_studio.policy import (
    voice,
)
from zyg_workflows.voice_studio.params import (
    sanitize,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


# ────────────────────────────────────────────────────────────── preset store
# Display names are permissive on purpose. They are stored as a JSON VALUE and
# rendered through the page's escaper, and the filename comes from _slugify's
# strict [a-z0-9-] alphabet — so nothing about a name can reach the filesystem or
# the DOM unescaped. An allowlist here bought no safety and cost real names: the
# first thing an operator types in this codebase is an em dash ("Ledger — calm"),
# and the old \w-based rule rejected it with a validation error.
_NAME_BAD = re.compile(r'[\x00-\x1f\x7f]')
_SLUG_OK = re.compile(r'^[a-z0-9][a-z0-9_-]{0,62}$')


def _voice_preset_dir(vid: str) -> str:
    return os.path.join(PRESET_ROOT, vid)


def _slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
    return (s or 'preset')[:60]


def list_presets(vid: str) -> dict:
    """All presets for a voice, newest first, plus which one is marked active."""
    d = _voice_preset_dir(vid)
    presets, active = [], ''
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for fn in names:
        if not fn.endswith('.json') or fn.startswith('_'):
            continue
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as f:
                rec = json.load(f)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('preset %s unreadable, leaving it out of the list: %s', fn, _exc)
            continue
        rec['slug'] = fn[:-5]
        rec['params'] = sanitize(rec.get('params') or {})
        wav = os.path.join(d, fn[:-5] + '.wav')
        rec['preview'] = f'pre/{vid}/{fn[:-5]}.wav' if os.path.isfile(wav) else ''
        presets.append(rec)
    try:
        with open(os.path.join(d, '_active.json'), encoding='utf-8') as f:
            active = (json.load(f) or {}).get('slug', '')
    except (OSError, ValueError):
        active = ''
    presets.sort(key=lambda r: r.get('updated', ''), reverse=True)
    if active and not any(r['slug'] == active for r in presets):
        active = ''
    return {'presets': presets, 'active': active}


def _next_auto_name(vid: str) -> str:
    """Unnamed saves become 'Preset 1', 'Preset 2', … — the highest existing
    number plus one, so deleting Preset 2 never makes the next save collide
    with a Preset 3 that is still there."""
    n = 0
    for rec in list_presets(vid)['presets']:
        m = re.match(r'^Preset (\d+)$', (rec.get('name') or '').strip())
        if m:
            n = max(n, int(m.group(1)))
    return f'Preset {n + 1}'


def save_preset(
    vid: str, name: str, params: dict, slug: str = '', metrics: dict = None, preview_wav: str = '', text: str = ''
) -> dict:
    """Create or overwrite one preset. Returns the stored record.

    `slug` empty  -> new preset (slug derived from the name, de-duplicated).
    `slug` given  -> overwrite that preset in place, keeping its slug/created.
    """
    v = voice(vid)
    if not v:
        raise ValueError('unknown voice')
    d = _voice_preset_dir(vid)
    os.makedirs(d, exist_ok=True)
    name = _NAME_BAD.sub('', (name or '')).strip()[:60] or _next_auto_name(vid)
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    created = now
    if slug:
        if not _SLUG_OK.match(slug):
            raise ValueError('bad preset id')
        path = os.path.join(d, slug + '.json')
        if not os.path.isfile(path):
            raise ValueError('preset not found')
        try:
            with open(path, encoding='utf-8') as f:
                created = (json.load(f) or {}).get('created', now)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('preset %s unreadable, stamping its created date as now: %s', path, _exc)
    else:
        base = _slugify(name)
        slug, i = base, 2
        while os.path.exists(os.path.join(d, slug + '.json')):
            slug = f'{base}-{i}'
            i += 1
        path = os.path.join(d, slug + '.json')

    rec = {
        'name': name,
        'voice': vid,
        'created': created,
        'updated': now,
        'params': sanitize(params),
        'text': (text or '')[:MAX_PREVIEW_CHARS],
        'metrics': metrics or {},
    }
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f, indent=2)
    os.replace(tmp, path)
    # Freeze the audition take alongside the numbers — a preset you cannot hear
    # months later is a row of knob values nobody dares to trust.
    if preview_wav and os.path.isfile(preview_wav):
        try:
            shutil.copyfile(preview_wav, os.path.join(d, slug + '.wav'))
        except OSError as _exc:
            _zyg_log.warning('audition take not frozen next to preset %s, it will have no preview: %s', slug, _exc)
    rec['slug'] = slug
    rec['preview'] = f'pre/{vid}/{slug}.wav' if os.path.isfile(os.path.join(d, slug + '.wav')) else ''
    return rec


def delete_preset(vid: str, slug: str) -> bool:
    if not (voice(vid) and _SLUG_OK.match(slug or '')):
        raise ValueError('bad request')
    d = _voice_preset_dir(vid)
    hit = False
    for ext in ('.json', '.wav'):
        p = os.path.join(d, slug + ext)
        if os.path.isfile(p):
            try:
                os.remove(p)
                hit = hit or ext == '.json'
            except OSError as _exc:
                _zyg_log.warning('preset file %s could not be deleted, it is still on disk: %s', p, _exc)
    if list_presets(vid)['active'] == '':
        try:
            os.remove(os.path.join(d, '_active.json'))
        except OSError as _exc:
            _zyg_log.debug('no active-preset bookmark to clear for %s: %s', vid, _exc)
    return hit


def set_active(vid: str, slug: str) -> str:
    """Mark a preset active. This is a BOOKMARK, not a switch: nothing reads it
    except the GUI and active_params(). See the module docstring."""
    if not voice(vid):
        raise ValueError('unknown voice')
    d = _voice_preset_dir(vid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, '_active.json')
    if not slug:
        try:
            os.remove(path)
        except OSError as _exc:
            _zyg_log.debug('active-preset bookmark for %s was already absent: %s', vid, _exc)
        return ''
    if not _SLUG_OK.match(slug) or not os.path.isfile(os.path.join(d, slug + '.json')):
        raise ValueError('preset not found')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'slug': slug, 'set': time.strftime('%Y-%m-%d %H:%M:%S')}, f, indent=2)
    os.replace(tmp, path)
    return slug


def active_params(vid: str) -> dict:
    """The active preset's params, or {} when none is marked.

    This is the seam a production caller would use to adopt a tuned voice. No
    caller does yet — see the module docstring."""
    st = list_presets(vid)
    if not st['active']:
        return {}
    for rec in st['presets']:
        if rec['slug'] == st['active']:
            return rec['params']
    return {}


def engine_kwargs(params: dict) -> dict:
    """Preset params -> the kwargs shape narration/abel_voice already speak."""
    p = sanitize(params)
    if p['engine'] == 'indextts2':
        return {'engine': 'indextts2', 'kwargs': {'emo_alpha': p['ix_emo_alpha'], 'emo_text': p['ix_emo_text']}}
    return {
        'engine': 'chatterbox',
        'kwargs': {
            'exaggeration': p['cb_exaggeration'],
            'cfg_weight': p['cb_cfg_weight'],
            'temperature': p['cb_temperature'],
            'seed': int(p['eng_seed']),
        },
    }
