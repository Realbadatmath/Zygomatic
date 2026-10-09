# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The body axes — the Anny phenotype/bone/morph dials and the candidates.

Moved verbatim from ``character_studio.py`` lines 1296-1669 by the 2026-10-06
modularization split.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
import logging as _zyg_logging

from zyg_workflows import paths

from .registry import _cbs

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_studio')

# ═══════════════════════════════════════════════════════════════════════════
# THE BODY AXES (2026-09-02, S05)
# ═══════════════════════════════════════════════════════════════════════════
# Character Studio's Body section had seven drawn-but-unwired tools —
# proportions, shoulders, waist, hands, feet, neck, bodyfat. They are not new
# knobs: they are the Anny axes the Mesh card already displays, which is why the
# same three rules at the top of this file apply to them unchanged.
#
# 1. A KNOB EDITS SOMETHING REAL. Every key below is checked at runtime against
#    the roster the ORIGINAL body's own params.json publishes
#    (adjustable.phenotype_axes, adjustable.bone_scale_names — 163 rig bones
#    matched as case-insensitive substrings — and adjustable.local_change_labels,
#    256 morphs). An axis whose key is not in the roster is served as
#    unavailable with the reason, never as a slider that does nothing.
#
# 2. A BODY EDIT DOES NOT TOUCH THE REGISTRY. Edits are written to
#    data/assets/mesh_skeletons/candidates/<name>_studio.json, which nothing
#    renders from. Turning a candidate into geometry is a REISSUE, and a reissue
#    is the operator's click on two cage hashes (kanban_server /mesh/api/*).
#
# 3. THE VERDICT IS SHOWN, NOT INTERPRETED. The anthro verdict beside the axes
#    is read off the registry as it stands. A FAIL there may be PRE-EXISTING and
#    is not evidence about the edit: the gate roster is itself under repair
#    (the phalanx split-brain), and gates that NEVER RAN count as blocking.

MESH_ROOT = os.path.realpath(paths.DATA_DIR / 'assets' / 'mesh_skeletons')
CANDIDATES = os.path.join(MESH_ROOT, 'candidates')

# tool id -> the axis it edits. `kind` says WHICH roster validates the key:
#   phenotype  -> adjustable.phenotype_axes, 0..1
#   bone       -> adjustable.bone_scale_names, a scale around 1.0
#   local      -> adjustable.local_change_labels, a morph weight
BODY_AXES: dict[str, dict[str, Any]] = {
    'proportions': {
        'label': 'Proportions',
        'kind': 'phenotype',
        'key': 'proportions',
        'min': 0.0,
        'max': 1.0,
        'step': 0.01,
        'def': 0.5,
        'help': "Anny's own proportions axis — the head-to-body count and limb "
        'ratio beneath the build word. The Mesh card shows this value.',
    },
    'bodyfat': {
        'label': 'Body fat',
        'kind': 'phenotype',
        'key': 'weight',
        'min': 0.0,
        'max': 1.0,
        'step': 0.01,
        'def': 0.5,
        'help': 'The phenotype WEIGHT axis. Softness over the frame, which the '
        'single build descriptor in the bible cannot hold on its own.',
    },
    'shoulders': {
        'label': 'Shoulders',
        'kind': 'bone',
        'key': 'clavicle',
        'min': 0.85,
        'max': 1.2,
        'step': 0.01,
        'def': 1.0,
        'extra': ['shoulder01'],
        'help': 'Scales clavicle.L/.R (and shoulder01 with it) — the silhouette '
        'read that carries at distance. Substring match, so both sides move.',
    },
    'waist': {
        'label': 'Waist & hips',
        'kind': 'local',
        'key': 'measure-waist-circ-incr',
        'min': -1.0,
        'max': 1.0,
        'step': 0.02,
        'def': 0.0,
        'extra': ['hip-scale-horiz-incr'],
        'help': 'The waist circumference morph, with the hip width morph beside '
        'it — the taper between them is the pair, not one number.',
    },
    'hands': {
        'label': 'Hands',
        'kind': 'local',
        'key': 'l-hand-scale-incr',
        'min': -1.0,
        'max': 1.0,
        'step': 0.02,
        'def': 0.0,
        'extra': ['r-hand-scale-incr'],
        'help': 'Hand scale, written to BOTH sides. The melted-hand failure lives '
        'here; the phalanx correction is a separate house layer applied at '
        'reissue and is not this dial.',
    },
    'feet': {
        'label': 'Feet',
        'kind': 'bone',
        'key': 'foot',
        'min': 0.85,
        'max': 1.15,
        'step': 0.01,
        'def': 1.0,
        'help': 'Scales foot.L/.R. The declash layer that keeps toes out of each other is anatomy, not this scale.',
    },
    'neck': {
        'label': 'Neck',
        'kind': 'bone',
        'key': 'neck',
        'min': 0.85,
        'max': 1.2,
        'step': 0.01,
        'def': 1.0,
        'help': 'Scales neck01/02/03 as a substring match — the join the head-swap failures show up at.',
    },
}


def _mesh_registry() -> dict:
    try:
        with open(os.path.join(MESH_ROOT, 'registry.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _roster(base: str = 'male') -> dict:
    """The three key rosters, read off an ORIGINAL body's params.json.

    Read, never hard-coded: the rosters are Anny's, they move when Anny moves,
    and a list frozen in this file would drift into offering keys the builder
    rejects."""
    reg = _mesh_registry()
    for want in (base, 'male', 'female'):
        rec = (reg.get('originals') or {}).get(want)
        if not rec:
            continue
        p = os.path.join(MESH_ROOT, rec.get('dir', ''), 'params.json')
        try:
            with open(p, encoding='utf-8') as fh:
                adj = json.load(fh).get('adjustable') or {}
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('roster params unreadable, trying the next base: %s', _exc)
            continue
        return {
            'phenotype': list(adj.get('phenotype_axes') or []),
            'bone': list(adj.get('bone_scale_names') or []),
            'local': list(adj.get('local_change_labels') or []),
        }
    return {'phenotype': [], 'bone': [], 'local': []}


def _key_is_real(kind: str, key: str, roster: dict) -> bool:
    names = roster.get(kind) or []
    if not names:
        return False
    if kind == 'bone':
        # the builder matches bone keys as case-insensitive SUBSTRINGS
        return any(key.lower() in n.lower() for n in names)
    return key in names


def candidate_path(name: str) -> str:
    return os.path.join(CANDIDATES, f'{name}_studio.json')


def load_candidate(name: str) -> dict:
    try:
        with open(candidate_path(name), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def body_axes(name: str) -> dict:
    """The Body panel's whole state for one registered body.

    Every axis carries its own four-state availability so the UI can mark a
    dead one instead of drawing a live-looking slider over a key the builder
    would reject."""
    reg = _mesh_registry()
    rec = (reg.get('derived') or {}).get(name) or (reg.get('originals') or {}).get(name)
    if not rec:
        return {
            'ok': False,
            'error': f'{name} has no registered body — the Body axes '
            'edit an Anny cage, and there is none for this '
            'character yet',
        }
    params = rec.get('params') or {}
    base = str(params.get('base') or 'male')
    roster = _roster(base)
    cand = load_candidate(name)
    edits = cand.get('edits') or {}

    pheno = params.get('phenotype') or {}
    bones = params.get('bone_scales') or {}
    locals_ = params.get('local_changes') or {}
    out = {}
    for tid, ax in BODY_AXES.items():
        keys = [ax['key']] + list(ax.get('extra') or [])
        real = [k for k in keys if _key_is_real(ax['kind'], k, roster)]
        cur = None
        if ax['kind'] == 'phenotype':
            cur = pheno.get(ax['key'])
        elif ax['kind'] == 'bone':
            cur = bones.get(ax['key'])
        else:
            cur = locals_.get(ax['key'])
        entry = {k: v for k, v in ax.items() if k != 'extra'}
        entry.update(
            {
                'id': tid,
                'keys': keys,
                'keys_valid': real,
                'issued': cur,
                'candidate': edits.get(tid),
                'state': 'found' if len(real) == len(keys) else ('not_found' if real else 'unavailable'),
                'why': ''
                if len(real) == len(keys)
                else "not in this build's roster: %s" % ', '.join(k for k in keys if k not in real),
            }
        )
        out[tid] = entry

    anthro = rec.get('anthro') or {}
    return {
        'ok': True,
        'name': name,
        'base': base,
        'axes': out,
        'cage_vert_sha256': params.get('cage_vert_sha256') or '',
        'candidate_path': candidate_path(name),
        'candidate': cand,
        'anthro': {
            'verdict': anthro.get('verdict') or anthro.get('state') or 'unknown',
            'report': anthro.get('report') or '',
            'blocking': len(anthro.get('blocking') or []),
            'note': 'A FAIL here may be PRE-EXISTING and is not caused by these '
            'axes. The gate roster is still under repair (the phalanx '
            'split-brain), and a gate that NEVER RAN is counted as '
            'blocking.',
        },
        'roster_sizes': {k: len(v) for k, v in roster.items()},
    }


def write_candidate(name: str, edits: dict, note: str = '') -> dict:
    """Write the Body panel's edits to candidates/<name>_studio.json.

    NEVER the registry. The file this writes is an input to a REISSUE, and a
    reissue is a separate, operator-confirmed act against two cage hashes."""
    st = body_axes(name)
    if not st.get('ok'):
        return {'ok': False, 'error': st.get('error')}
    if not isinstance(edits, dict) or not edits:
        return {'ok': False, 'error': 'no edits'}
    applied, rejected = {}, {}
    for tid, raw in edits.items():
        ax = BODY_AXES.get(tid)
        if not ax:
            rejected[tid] = 'not a body axis'
            continue
        if st['axes'][tid]['state'] != 'found':
            rejected[tid] = st['axes'][tid]['why'] or 'axis unavailable in this build'
            continue
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            applied[tid] = None  # explicitly cleared
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            rejected[tid] = f'not a number: {str(raw)[:40]!r}'
            continue
        if v < ax['min'] or v > ax['max']:
            rejected[tid] = f'outside {ax["min"]}..{ax["max"]}'
            continue
        applied[tid] = v
    if not applied:
        return {'ok': False, 'error': 'nothing applied', 'rejected': rejected}

    cand = load_candidate(name)
    cur = dict(cand.get('edits') or {})
    cur.update({k: v for k, v in applied.items() if v is not None})
    for k, v in applied.items():
        if v is None:
            cur.pop(k, None)
    # The CLI form is written beside the values so the operator can see exactly
    # what a reissue would DECLARE, rather than trusting a mapping they cannot read.
    cli = {'phenotype': {}, 'bone_scale': {}, 'local': {}}
    for tid, v in cur.items():
        ax = BODY_AXES[tid]
        bucket = {'phenotype': 'phenotype', 'bone': 'bone_scale', 'local': 'local'}[ax['kind']]
        for k in [ax['key']] + list(ax.get('extra') or []):
            cli[bucket][k] = v
    cand.update(
        {
            'name': name,
            'edits': cur,
            'cli': cli,
            'note': str(note or '')[:400],
            'written_by': 'character_studio.write_candidate',
            'cage_vert_sha256_at_write': st.get('cage_vert_sha256'),
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'not_applied': 'This file is a CANDIDATE. Nothing renders from it. '
            'Turning it into geometry is a reissue, which the '
            'operator confirms against two cage hashes.',
        }
    )
    os.makedirs(CANDIDATES, exist_ok=True)
    tmp = candidate_path(name) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(cand, fh, indent=2)
        fh.write('\n')
    os.replace(tmp, candidate_path(name))  # whole-file swap, never a partial read
    return {'ok': True, 'path': candidate_path(name), 'applied': applied, 'rejected': rejected, 'candidate': cand}


def resolve_body(char_id: str) -> dict:
    """Which registered body belongs to this character, and HOW that was decided.

    Nothing on disk records the link. The registry keys bodies by a friendly
    name and carries params.char_id set to that same friendly name ('abel'),
    while a storyteller dataset is keyed by a hash id ('c3345deb5bde'). So this
    reports its method rather than returning a bare name, and the panel prints
    the method: binding the wrong body silently is the same failure shape as the
    shared-filename LoRA staging that rendered the wrong character.

    method: 'id' (the registry name IS the character id — exact, no inference)
            'display_name' (the character's display name matched a body name —
                            an INFERENCE, shown as one)
            'none'
    """
    reg = _mesh_registry()
    bodies = dict(reg.get('derived') or {})
    if char_id in bodies:
        return {
            'body': char_id,
            'method': 'id',
            'certain': True,
            'why': 'the registry holds a body under exactly this id',
        }
    name = ''
    try:
        pkg = _cbs().load(char_id) or {}
        name = str(pkg.get('display_name') or '').strip()
    except Exception:  # noqa: BLE001
        pkg = {}
    if name:
        first = name.split()[0].lower()
        hits = [b for b in bodies if b.lower() == first or b.lower() == name.lower()]
        if len(hits) == 1:
            return {
                'body': hits[0],
                'method': 'display_name',
                'certain': False,
                'why': f'matched the display name {name!r} to the registered body '
                f'{hits[0]!r}. Nothing on disk records this link — check it '
                'before reissuing anything.',
            }
        if len(hits) > 1:
            return {
                'body': '',
                'method': 'none',
                'certain': False,
                'why': f'{name!r} matches more than one registered body: {hits}',
            }
    return {
        'body': '',
        'method': 'none',
        'certain': False,
        'why': f'no registered body for {char_id!r}'
        + (f' (display name {name!r})' if name else '')
        + '. Derive one from the Mesh tab first.',
    }
