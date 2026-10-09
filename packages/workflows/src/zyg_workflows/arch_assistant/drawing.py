# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The drawing the model edits.

Moved verbatim out of the old single-file arch_assistant.py (lines 530-767).
"""

from __future__ import annotations

import json
import math
import re

from zyg_workflows.arch_assistant._base import _zyg_log

from zyg_workflows.arch_assistant.config import (
    STOREY_M,
    WALL_T,
)

# ── the drawing the model edits ─────────────────────────────────────────────
_FS_CACHE: list = [None]  # finish_schedule module, resolved once per process (see Drawing._finish_schedule)


class Drawing:
    def __init__(self, doc: dict | None, storey_h: float = STOREY_M, wall_t: float = WALL_T):
        doc = doc or {}
        self.name = str(doc.get('name') or 'Untitled drawing')
        self.objs: list[dict] = []
        self.storey_h = storey_h or STOREY_M
        self.wall_t = wall_t or WALL_T
        self.cell_m = _cell_size_of(doc.get('cell_m'))
        # document-level state the icon families keep (layers, units, north, rate card…)
        self.ext: dict = dict(doc.get('ext')) if isinstance(doc.get('ext'), dict) else {}
        # 2026-09-10: the request's OWN WORDS, for the checks that judge the drawing
        # against what was asked ("luxurious", "infinity pool"). Set per run by _run;
        # it is state of the RUN, not of the document, so to_doc() never writes it.
        self.request = str(doc.get('request') or '')
        mx = 0
        for o in doc.get('objects') or []:
            if not isinstance(o, dict) or not o.get('kind'):
                continue
            rec = {
                'id': str(o.get('id') or ''),
                'kind': str(o['kind']),
                'name': str(o.get('name') or o['kind']),
                'p': dict(o.get('p') or {}),
                'x': _num(o.get('x'), 0),
                'y': _num(o.get('y'), 0),
                'z': _num(o.get('z'), 0),
                'rx': _num(o.get('rx'), 0),
                'ry': _num(o.get('ry'), 0),
                'rz': _num(o.get('rz'), 0),
                's': _num(o.get('s'), 1),
                'mat': str(o.get('mat') or 'mat_concrete'),
                'hidden': bool(o.get('hidden')),
                'grp': str(o.get('grp') or ''),
                'meta': dict(o.get('meta')) if isinstance(o.get('meta'), dict) else {},
            }
            m = re.fullmatch(r'o(\d+)', rec['id'])
            if m:
                mx = max(mx, int(m.group(1)))
            self.objs.append(rec)
        self.seq = mx + 1
        for o in self.objs:  # ids the client never assigned
            if not o['id']:
                o['id'] = f'o{self.seq}'
                self.seq += 1
        self.before = {o['id']: json.dumps(o, sort_keys=True) for o in self.objs}
        self.added: list[str] = []
        self.removed: list[str] = []
        self.ui: list[dict] = []  # viewport commands for the tab to run after injection
        self.images: list[dict] = []  # {'title','data_url'} shown in the chat
        self.selected: list[str] = []  # ids the tab should select after injection (NOT `select`: that is the method)

    # 2026-09-16: the finishes arrive BY CONSTRUCTION. finish_schedule owns one
    # table (kind -> library id, per finish level) and Drawing.new asks it for the
    # material of every record it makes, so a luxury job is born with oak doors
    # and marble floors instead of spending 14 of its drawing calls repainting
    # flat presets. new() runs thousands of times per job, so the module is
    # fetched ONCE per Drawing and cached, and the hook may never raise.
    def _finish_schedule(self):
        # 2026-09-16 (creator): the module used to be cached ON the instance, and a
        # module attribute makes copy.deepcopy(drawing) raise "cannot pickle 'module'"
        # (test_water_v3 deep-copies a Drawing). A module-level cache keeps the
        # once-per-process lookup without touching the instance's state.
        if _FS_CACHE[0] is None:
            _FS_CACHE[0] = EXT_MODULES.get('finish_schedule') or False
        return _FS_CACHE[0] or None

    # records --------------------------------------------------------------
    def new(self, kind, p, x, z, y=0.0, ry=0.0, mat=None, name=None, grp=''):
        if len(self.objs) >= MAX_OBJECTS:
            raise ValueError(f'the drawing already holds {MAX_OBJECTS} objects — that is the ceiling')
        rec = {
            'id': f'o{self.seq}',
            'kind': kind,
            'name': name or _label(kind),
            'p': dict(p or {}),
            'x': round(float(x), 4),
            'y': round(float(y), 4),
            'z': round(float(z), 4),
            'rx': 0.0,
            'ry': round(float(ry), 6),
            'rz': 0.0,
            's': 1,
            'mat': mat or DEFAULT_MAT.get(kind, 'mat_concrete'),
            'hidden': False,
            'grp': grp or '',
            'meta': {},
        }
        fs = self._finish_schedule()
        if fs is not None:
            try:
                if fs.is_preset(rec['mat']):  # a library id is somebody's choice; leave it
                    rec['mat'] = fs.default_mat(self, kind, rec['mat']) or rec['mat']
            except Exception as _exc:  # noqa: BLE001 — a finish never blocks the drawing
                _zyg_log.debug('finish-schedule default material skipped: %s', _exc)
        self.seq += 1
        self.objs.append(rec)
        self.added.append(rec['id'])
        return rec

    def find(self, oid):
        for o in self.objs:
            if o['id'] == oid:
                return o
        return None

    def remove(self, recs):
        ids = {r['id'] for r in recs}
        self.objs = [o for o in self.objs if o['id'] not in ids]
        for i in ids:
            if i in self.added:
                self.added.remove(i)
            elif i in self.before:
                self.removed.append(i)

    def select(self, which) -> list[dict]:
        """'new' | 'all' | a kind | a group name | [ids] | id."""
        if isinstance(which, list):
            ids = {str(w) for w in which}
            return [o for o in self.objs if o['id'] in ids]
        w = str(which or 'new').strip()
        if w == 'new':
            return [o for o in self.objs if o['id'] in self.added]
        if w == 'all':
            return list(self.objs)
        if w in KINDS or w in ('walls',):
            k = 'wall' if w == 'walls' else w
            return [o for o in self.objs if o['kind'] == k or (k == 'wall' and o['kind'] == 'partition')]
        by_grp = [o for o in self.objs if o['grp'] == w]
        if by_grp:
            return by_grp
        one = self.find(w)
        return [one] if one else []

    def to_doc(self) -> dict:
        return {
            'name': self.name,
            'units': 'm',
            'schema': 1,
            'cell_m': self.cell_m,
            'ext': self.ext,
            'objects': [dict(o) for o in self.objs],
        }

    def changed_ids(self) -> list[str]:
        out = []
        for o in self.objs:
            b = self.before.get(o['id'])
            if b is not None and b != json.dumps(o, sort_keys=True):
                out.append(o['id'])
        return out

    # summaries ------------------------------------------------------------
    def summary(self) -> str:
        if not self.objs:
            return 'The drawing is empty.'
        kinds: dict[str, int] = {}
        grps: dict[str, int] = {}
        xs, zs, sts = [], [], []
        g = has_ground(self)
        for o in self.objs:
            kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
            if o['grp']:
                grps[o['grp']] = grps.get(o['grp'], 0) + 1
            xs.append(o['x'])
            zs.append(o['z'])
            sts.append(storey_index(self, o, self.storey_h, g))
        lines = [
            f'{len(self.objs)} objects: '
            + ', '.join(f'{v} {k}' for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))
        ]
        with _Scale(self.cell_m):
            lines.append(
                f'footprint cells {cell_of(min(xs), min(zs))}..{cell_of(max(xs) - 1e-6, max(zs) - 1e-6)}; '
                f'storeys {min(sts)}..{max(sts)}'
            )
        if self.cell_m != CELL_M:
            lines.append(
                f'grid: cells are {self.cell_m:g} m — the field is '
                f'{GRID_N * self.cell_m:g} x {GRID_N * self.cell_m:g} m'
            )
        if grps:
            lines.append('groups: ' + ', '.join(f'{g} ({n})' for g, n in list(grps.items())[:20]))
        return '\n'.join(lines)

    def listing(self, which='all', limit=300) -> str:
        recs = self.select(which)
        if not recs:
            return 'nothing matches'
        out = []
        g = has_ground(self)
        with _Scale(self.cell_m):
            for o in recs[:limit]:
                p = o['p']
                dim = ''
                if 'len' in p:
                    dim = f'len {_num(p["len"], 0):g}'
                elif 'w' in p and 'd' in p:
                    dim = f'{_num(p["w"], 0):g}x{_num(p["d"], 0):g}'
                elif 'w' in p:
                    dim = f'w {_num(p["w"], 0):g}'
                deg = round(math.degrees(o['ry'])) % 360
                st = storey_index(self, o, self.storey_h, g)
                out.append(
                    f'{o["id"]} {o["kind"]} @{cell_of(o["x"], o["z"])} st{st}'
                    + (f' {dim}' if dim else '')
                    + (f' rot{deg}' if deg else '')
                    + (f' grp:{o["grp"]}' if o['grp'] else '')
                    + f' {o["mat"]}'
                )
        if len(recs) > limit:
            out.append(f'... and {len(recs) - limit} more')
        return '\n'.join(out)


def _label(kind):
    return {
        'wall': 'Wall',
        'partition': 'Partition',
        'door': 'Door',
        'double_door': 'Double door',
        'window': 'Window',
        'opening': 'Opening',
        'column_rect': 'Column',
        'column_round': 'Column',
        'slab': 'Slab',
        'roof_flat': 'Flat roof',
        'roof_gable': 'Gable roof',
        'roof_hip': 'Hip roof',
        'roof_shed': 'Shed roof',
        'pad': 'Ground pad',
        'tree': 'Tree',
    }.get(kind, kind.replace('_', ' ').title())


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    CELL_M,
    DEFAULT_MAT,
    GRID_N,
    KINDS,
    MAX_OBJECTS,
    _Scale,
    _cell_size_of,
    _num,
    cell_of,
)
from zyg_workflows.arch_assistant.ground import (  # noqa: E402
    EXT_MODULES,
    has_ground,
    storey_index,
)
