#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Persistence for user-created schematics.

One JSON file per schematic under hub/schematics/, holding both the SOURCE (the
recipe: ops + params, or captured/imported voxels) and the COMPILED output (the
proven build order + scaffold). Keeping the source is what makes a schematic
editable later; keeping the compiled output is what makes it runnable without
re-proving it on every hub start.

The compiler version is stamped on save. If the bot's constraints ever change,
`needs_recompile()` flags every stored schematic whose proof is stale rather than
letting the hub run a build certified against rules that no longer hold.
"""

import json
import re
import time
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent
STORE_DIR = HUB_DIR / 'schematics'

# Bump when the compiler's model changes in a way that invalidates old proofs.
COMPILER_VERSION = 1

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def slugify(name, taken=()):
    base = _SLUG_RE.sub('-', (name or 'untitled').lower()).strip('-') or 'untitled'
    base = base[:40]
    sid = base
    n = 2
    while sid in taken:
        sid = f'{base}-{n}'
        n += 1
    return sid


def _path(sid):
    return STORE_DIR / f'{sid}.json'


def list_ids():
    if not STORE_DIR.is_dir():
        return []
    return sorted(p.stem for p in STORE_DIR.glob('*.json'))


def load(sid):
    p = _path(sid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def load_all():
    """Every stored schematic, newest first. Unreadable files are skipped rather
    than taking the hub down on boot."""
    out = []
    for sid in list_ids():
        d = load(sid)
        if d and d.get('blocks'):
            out.append(d)
    out.sort(key=lambda d: d.get('updated_at', 0), reverse=True)
    return out


def save(record):
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    record['updated_at'] = time.time()
    record['compiler_version'] = COMPILER_VERSION
    _path(record['id']).write_text(json.dumps(record, indent=1))
    return record


def delete(sid):
    p = _path(sid)
    if p.exists():
        p.unlink()
        return True
    return False


def needs_recompile(record):
    return record.get('compiler_version') != COMPILER_VERSION


def make_record(
    sid, name, desc, category, difficulty, blocks, source=None, report=None, scaffold=None, origin='creator'
):
    """Assemble a stored schematic in the same shape the hub's built-ins use, so
    custom cards are indistinguishable from built-in ones downstream."""
    xs = [b['x'] for b in blocks]
    ys = [b['y'] for b in blocks]
    zs = [b['z'] for b in blocks]
    mats = {}
    for b in blocks:
        mats[b['mat']] = mats.get(b['mat'], 0) + 1
    return {
        'id': sid,
        'name': name,
        'desc': desc,
        'category': category,
        'difficulty': difficulty,
        'blocks': blocks,
        'materials': mats,
        'block_count': len(blocks),
        'size': {'w': max(xs) - min(xs) + 1, 'h': max(ys) - min(ys) + 1, 'd': max(zs) - min(zs) + 1},
        'est_minutes': max(1, round(len(blocks) * 1.8 / 60) + 2),
        'custom': True,
        'origin': origin,
        'source': source or {},
        'scaffold_count': len(scaffold or []),
        'report': {k: report.get(k) for k in ('certified', 'stats', 'warnings', 'passes', 'slots')} if report else None,
        'created_at': time.time(),
    }
