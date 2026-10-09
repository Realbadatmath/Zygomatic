# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""object_specs — the assistant's OBJECT KNOWLEDGE BASE (2026-09-08).

Why this family exists: the design rules of 2026-09-08 fixed the relations the
model got wrong on ONE building (pool inside a deck, columns through a canopy,
trees in a blob).  They did not fix the general case: the model does not know
what most objects ARE, how much room they need, or what a bad one looks like —
and there is nowhere to put that knowledge once it has been worked out.

The store answers six questions per object, once, forever:

    what   — what is it
    looks  — what does it look like
    how    — how do I build it here (the tool call, with arguments)
    avoid  — what to avoid while building it
    quality— how to build it in high quality
    space  — how much room it needs in relation to its surroundings

`space` is the half that MATTERS and the only half that is machine-readable:
prose cannot be checked, and a rule the model must choose to read gets skipped
under turn pressure (measured: the model routed around plant_trees to
plant_tree_line the moment plant_trees refused).  So `space` is a dict the
design check reads, and prose is only what is left over.

WHY THE STORE IS ON DISK AND NOT IN THE PROMPT: the assistant already carries
88k chars of system prompt and 198k chars of tool schemas — ~72k cached tokens
a step — and its 491 worked examples are TRUNCATED to 40 because they do not
fit.  A knowledge base that grows with every build cannot live there.  One
tool, `spec(of)`, retrieves ≤ 1.5k chars on demand.

WHERE THE CONTENT COMES FROM: never from the drawing job.  The CLI is spawned
with `--tools '' --allowedTools mcp__arch` — it has no web access at all, and a
job that already cannot finish in 28 turns is the worst place to put research.
A build that meets a kind with no spec records a GAP (that is the "log it once"
half of the operator's request); `arch_spec_research.py` fills gaps offline,
with sources, and installs validated JSON.

Files: data/architecture/specs/<key>.json (the store),
       data/runtime/arch_assistant/spec_gaps.jsonl (the gaps).
No new kinds.  One model-facing tool.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time

from zyg_workflows.arch_assistant import Drawing, _num, deck_tops, ground_height
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.environ.get('ZYG_ARCH_SPEC_DIR') or os.path.join(HERE, 'data', 'architecture', 'specs')
GAP_LOG = os.environ.get('ZYG_ARCH_SPEC_GAPS') or os.path.join(
    HERE, 'data', 'runtime', 'arch_assistant', 'spec_gaps.jsonl'
)

PROSE_MAX = 1500  # chars a spec may spend in the model's context
_LOCK = threading.Lock()
_CACHE: dict = {'stamp': -1.0, 'specs': {}, 'index': {}, 'kind_index': {}}

# the six answers; `space` is the machine half
FIELDS = ('what', 'looks', 'how', 'avoid', 'quality')
HOSTS = ('floor', 'deck', 'ground', 'wall', 'ceiling', 'roof', 'water', 'any')
SEVS = ('warn', 'error', 'info')


# ── the store ────────────────────────────────────────────────────────────────
def _norm(t) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(t or '').strip().lower()).strip('_')


def validate_spec(s: dict) -> list:
    """[] when the record may be installed, else the reasons it may not.
    Used by the seeder, by the offline researcher and by the loader."""
    bad = []
    if not isinstance(s, dict):
        return ['not a JSON object']
    key = _norm(s.get('key'))
    if not key:
        bad.append('key is missing')
    if not str(s.get('title') or '').strip():
        bad.append('title is missing')
    for f in FIELDS:
        v = s.get(f)
        if f in ('avoid', 'quality'):
            if not isinstance(v, list) or not [x for x in v if str(x).strip()]:
                bad.append(f'{f} must be a non-empty list of short sentences')
        elif not str(v or '').strip():
            bad.append(f'{f} is empty — the six questions are all required')
    sp = s.get('space')
    if not isinstance(sp, dict):
        bad.append('space is missing (the machine half: clear_r, host, dims)')
    else:
        if sp.get('host') and sp['host'] not in HOSTS:
            bad.append(f'space.host must be one of {", ".join(HOSTS)}')
        if sp.get('severity') and sp['severity'] not in SEVS:
            bad.append("space.severity must be 'warn', 'error' or 'info'")
        for k in ('clear_r', 'clear_front', 'headroom'):
            if sp.get(k) is not None and not isinstance(sp[k], (int, float)):
                bad.append(f'space.{k} must be a number in metres')
        for k in ('w', 'd', 'h'):
            v = sp.get(k)
            if v is not None and not (
                isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v) and v[0] <= v[1]
            ):
                bad.append(f'space.{k} must be [min, max] in metres')
        if sp.get('facing') not in (None, '', '+z', '-z', '+x', '-x'):
            bad.append("space.facing must be '+z', '-z', '+x' or '-x' (the record's LOCAL front)")
    if s.get('source') not in ('seeded', 'researched'):
        bad.append("source must be 'seeded' (conventional practice, unverified) or 'researched' (with sources)")
    if s.get('source') == 'researched' and not (isinstance(s.get('sources'), list) and s['sources']):
        bad.append('a researched spec must cite at least one source')
    for k in ('kinds', 'tools', 'aliases'):
        if s.get(k) is not None and not isinstance(s[k], list):
            bad.append(f'{k} must be a list')
    return bad


def _dir_stamp() -> float:
    try:
        st = os.stat(SPEC_DIR)
    except OSError:
        return -1.0
    return st.st_mtime


def load_specs(force=False) -> dict:
    """{key: spec}, reloaded when the directory changes. A file that fails
    validation is SKIPPED with a note in the spec's own '_bad' list — never
    raised: a broken spec must not stop a drawing."""
    with _LOCK:
        stamp = _dir_stamp()
        if not force and stamp == _CACHE['stamp']:
            return _CACHE['specs']
        specs, index, kind_index = {}, {}, {}
        try:
            names = sorted(os.listdir(SPEC_DIR))
        except OSError:
            names = []
        for fn in names:
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(SPEC_DIR, fn), encoding='utf-8') as fh:
                    s = json.load(fh)
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('object spec %s unreadable, skipped: %s', fn, _exc)
                continue
            if validate_spec(s):
                continue
            key = _norm(s['key'])
            s['key'] = key
            specs[key] = s
            index[key] = key
            kind_index[key] = key
            for a in s.get('aliases') or []:
                index.setdefault(_norm(a), key)
            for k in s.get('kinds') or []:
                index.setdefault(_norm(k), key)
                kind_index.setdefault(_norm(k), key)
            for t in s.get('tools') or []:
                index.setdefault(_norm(t), key)
        _CACHE.update({'stamp': stamp, 'specs': specs, 'index': index, 'kind_index': kind_index})
        return specs


def spec_for(term) -> dict | None:
    """The spec for a key, a record kind, a tool name, an alias, or a close word."""
    specs = load_specs()
    t = _norm(term)
    if not t:
        return None
    idx = _CACHE['index']
    if t in idx:
        return specs[idx[t]]
    for k in ('add_' + t, t + 's', t.rstrip('s'), 'draw_' + t):
        if k in idx:
            return specs[idx[k]]
    # whole WORDS only: "stable" must not resolve to the dining_table sheet
    words = [w for w in t.split('_') if len(w) > 2]
    for cand, key in idx.items():
        cw = cand.split('_')
        if words and all(w in cw for w in words):
            return specs[key]
    for cand, key in idx.items():
        cw = [w for w in cand.split('_') if len(w) > 3]
        if cw and all(w in words for w in cw):
            return specs[key]
    return None


# Kinds that are a CONTAINER, not a thing: `asset` is any library model at all,
# `component` any block. They must never resolve to a sheet — 'asset' once
# reached the BED sheet through the tool name place_asset, and every lamp post
# in a drawing was then reported as an undersized bed.
GENERIC_KINDS = {
    'asset',
    'component',
    'mesh_file',
    'point_cloud',
    'csg',
    'link',
    'box',
    'cylinder',
    'sphere',
    'plane',
    'cone',
    'disc',
    'capsule',
    'torus',
    'wedge',
    'pyramid',
    'prism',
}


def spec_for_kind(kind) -> dict | None:
    """The sheet for a RECORD KIND, exactly — key or declared `kinds` only.

    The fuzzy `spec_for` is right for the model asking "what is a dining
    table?" and wrong for a check asking "what is this record?": a near miss
    there is not a helpful guess, it is a false finding against the wrong
    object. Every design check goes through this one.
    """
    k = _norm(kind)
    if not k or k in GENERIC_KINDS:
        return None
    load_specs()
    key = _CACHE['kind_index'].get(k)
    return load_specs().get(key) if key else None


def kinds_covered() -> set:
    load_specs()
    return {k for k, v in _CACHE['index'].items()}


# ── gaps: what a build met and the store could not answer ────────────────────
def record_gap(term, why='asked', drawing='') -> None:
    """One line per unanswered object. The offline filler reads this; the
    drawing job never researches."""
    t = _norm(term)
    if not t:
        return
    row = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'key': t, 'why': why, 'drawing': str(drawing or '')[:80]}
    try:
        os.makedirs(os.path.dirname(GAP_LOG), exist_ok=True)
        with open(GAP_LOG, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError as _exc:
        _zyg_log.warning('research gap log write failed: %s', _exc)


def gaps(days=90) -> list:
    """[{key, n, last, why}] newest first — what the store still owes."""
    cut = time.time() - days * 86400
    seen: dict = {}
    try:
        with open(GAP_LOG, encoding='utf-8') as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('non-JSON gap log line skipped: %s', _exc)
                    continue
                try:
                    ts = time.mktime(time.strptime(r.get('at', ''), '%Y-%m-%dT%H:%M:%S'))
                except ValueError:
                    ts = time.time()
                if ts < cut:
                    continue
                k = _norm(r.get('key'))
                if not k or spec_for(k):
                    continue  # already answered since
                e = seen.setdefault(k, {'key': k, 'n': 0, 'last': r.get('at', ''), 'why': r.get('why', '')})
                e['n'] += 1
                e['last'] = r.get('at', e['last'])
    except OSError:
        return []
    return sorted(seen.values(), key=lambda e: (-e['n'], e['key']))


# ── the prose half ───────────────────────────────────────────────────────────
def _space_line(sp: dict) -> str:
    if not isinstance(sp, dict):
        return ''
    bits = []
    for k, lbl in (('w', 'width'), ('d', 'depth'), ('h', 'height')):
        v = sp.get(k)
        if isinstance(v, list) and len(v) == 2:
            bits.append(f'{lbl} {v[0]:g}-{v[1]:g} m' if v[0] != v[1] else f'{lbl} {v[0]:g} m')
    if sp.get('clear_r'):
        bits.append(f'{sp["clear_r"]:g} m clear all round')
    if sp.get('clear_front'):
        f = sp.get('facing') or 'the front'
        bits.append(f'{sp["clear_front"]:g} m clear in front ({f})')
    if sp.get('headroom'):
        bits.append(f'{sp["headroom"]:g} m headroom')
    if sp.get('host'):
        bits.append(f'stands on the {sp["host"]}')
    if sp.get('per'):
        p = sp['per']
        bits.append(f'one per {p.get("n")} {p.get("unit")}' if isinstance(p, dict) else str(p))
    out = '; '.join(bits)
    if sp.get('note'):
        out += ('. ' if out else '') + str(sp['note'])
    return out


def prose(s: dict, budget=PROSE_MAX) -> str:
    """The spec as the model reads it — six answers, hard-capped."""
    if not s:
        return ''
    L = [f'{s.get("title") or s["key"]} ({s["key"]})']
    L.append('WHAT: ' + str(s.get('what') or '').strip())
    L.append('LOOKS: ' + str(s.get('looks') or '').strip())
    L.append('HOW: ' + str(s.get('how') or '').strip())
    av = [str(x).strip() for x in (s.get('avoid') or []) if str(x).strip()]
    if av:
        L.append('AVOID: ' + ' · '.join(av))
    q = [str(x).strip() for x in (s.get('quality') or []) if str(x).strip()]
    if q:
        L.append('QUALITY: ' + ' · '.join(q))
    sl = _space_line(s.get('space') or {})
    if sl:
        L.append('SPACE: ' + sl)
    tag = 'checked by design_check' if (s.get('space') or {}).get('severity') in ('warn', 'error') else ''
    prov = s.get('source')
    if prov == 'seeded':
        L.append('(seeded: conventional practice, not code-verified' + ((' — ' + tag) if tag else '') + ')')
    elif tag:
        L.append('(' + tag + ')')
    txt = '\n'.join(x for x in L if x.strip() and not x.endswith(': '))
    return txt[:budget]


# ── the machine half: what the design check enforces ─────────────────────────
SOLID_SKIP = {
    'ground',
    'terrain',
    'zone',
    'component',
    'link',
    'annotation',
    'dimension',
    'dim_linear',
    'dim_angle',
    'label_text',
    'markup_note',
    'site_boundary',
    'gridline',
    'opening',
    'guide_arc',
    'guide_path',
    'guide_poly',
    'floor_finish',
    'skirting',
    'pad',
    'road',
    'path',
    'sidewalk',
    'ceiling',
    'suspended_ceiling',
    'raised_floor',
}


def _foot(o: dict) -> tuple | None:
    """(w, d) footprint of a record in metres, or None when it has no plan size."""
    p = o.get('p') or {}
    s = o.get('s') or 1.0
    w, dd = _num(p.get('w'), 0.0), _num(p.get('d'), 0.0)
    if w <= 0 or dd <= 0:
        w, dd = _num(p.get('bw'), 0.0), _num(p.get('bd'), 0.0)
    if w <= 0 or dd <= 0:
        r = _num(p.get('r'), 0.0)
        if r > 0:
            w = dd = 2 * r
    if w <= 0 or dd <= 0:
        return None
    return w * s, dd * s


def _rect_of(o: dict) -> tuple | None:
    """(cx, cz, hw, hd, ry) — the record's plan rectangle."""
    f = _foot(o)
    if not f:
        return None
    return o['x'], o['z'], f[0] / 2, f[1] / 2, (o.get('ry') or 0.0)


def _overlap(a: tuple, b: tuple) -> float:
    """Overlap of two plan rectangles, approximated in A's frame (0 when apart).
    Both are treated as axis-aligned in A's frame: exact when they share a
    rotation, conservative-in-the-right-direction otherwise."""
    ax, az, ahw, ahd, ary = a
    bx, bz, bhw, bhd, bry = b
    dx, dz = bx - ax, bz - az
    c, s = math.cos(ary), math.sin(ary)
    lx, lz = dx * c - dz * s, dx * s + dz * c
    da = abs(bry - ary) % math.pi
    if min(da, math.pi - da) > math.pi / 4:  # b is turned across a: swap its half-sizes
        bhw, bhd = bhd, bhw
    ox = (ahw + bhw) - abs(lx)
    oz = (ahd + bhd) - abs(lz)
    return min(ox, oz) if ox > 0 and oz > 0 else 0.0


def _grown(a: tuple, r: float, front: float, facing: str) -> tuple:
    """A's rectangle grown by the clear ring, and by `front` along `facing`."""
    ax, az, ahw, ahd, ary = a
    hw, hd = ahw + r, ahd + r
    cx, cz = 0.0, 0.0
    if front > 0 and facing in ('+z', '-z'):
        hd += front / 2
        cz = (front / 2) * (1 if facing == '+z' else -1)
    elif front > 0 and facing in ('+x', '-x'):
        hw += front / 2
        cx = (front / 2) * (1 if facing == '+x' else -1)
    c, s = math.cos(ary), math.sin(ary)  # local offset -> world
    wx = ax + cx * c + cz * s
    wz = az - cx * s + cz * c
    return wx, wz, hw, hd, ary


def check_clearances(d: Drawing) -> list:
    """Nothing solid stands inside the room an object needs. The rule comes from
    the object's own spec (space.clear_r / clear_front), so a table keeps its
    chair-pull-out and a lift keeps its lobby without either being hard-coded."""
    H = d.storey_h or 2.7
    out, seen = [], 0
    recs = [o for o in d.objs if not o.get('hidden') and o.get('kind') not in SOLID_SKIP]
    for o in recs:
        s = spec_for_kind(o.get('kind'))
        sp = (s or {}).get('space') or {}
        r = _num(sp.get('clear_r'), 0.0)
        fr = _num(sp.get('clear_front'), 0.0)
        if r <= 0 and fr <= 0:
            continue
        a = _rect_of(o)
        if not a:
            continue
        seen += 1
        zone = _grown(a, r, fr, sp.get('facing') or '')
        sev = sp.get('severity') or 'warn'
        for b in recs:
            if b is o or b.get('grp') and b.get('grp') == o.get('grp') and b.get('kind') == o.get('kind'):
                continue
            if abs((b.get('y') or 0) - (o.get('y') or 0)) > H * 0.6:
                continue
            rb = _rect_of(b)
            if not rb:
                continue
            if _overlap(a, rb) > 0.02:  # already touching: that is a different fault
                continue
            ov = _overlap(zone, rb)
            if ov > 0.15:
                out.append(
                    {
                        'sev': sev,
                        'code': 'clearance',
                        'text': f'{o["id"]} {o.get("name") or o["kind"]} needs {r:g} m clear'
                        + (f' and {fr:g} m in front' if fr else '')
                        + f' — {b["id"]} {b.get("name") or b["kind"]} stands {ov:.2f} m inside it'
                        f' (spec "{s["key"]}": {(sp.get("note") or "move one of them")})',
                    }
                )
                break  # one finding per object, not per pair
    return out[:12]


def check_dims(d: Drawing) -> list:
    """A record smaller than its spec's minimum — the 0.9 m corridor, the 1.0 m
    lift car, the stair too narrow to pass on."""
    out = []
    for o in d.objs:
        if o.get('hidden'):
            continue
        s = spec_for_kind(o.get('kind'))
        sp = (s or {}).get('space') or {}
        f = _foot(o)
        if not f or not sp:
            continue
        for val, rng, lbl in ((f[0], sp.get('w'), 'width'), (f[1], sp.get('d'), 'depth')):
            if isinstance(rng, list) and len(rng) == 2 and val + 1e-6 < rng[0]:
                out.append(
                    {
                        'sev': sp.get('severity') or 'warn',
                        'code': 'undersize',
                        'text': f'{o["id"]} {o.get("name") or o["kind"]}: {lbl} {val:.2f} m is under the '
                        f'{rng[0]:g} m minimum for a {s["title"].lower()} '
                        f'({(sp.get("note") or "spec " + s["key"])})',
                    }
                )
                break
    return out[:8]


VOID_HOST_TOL = 0.35  # the same 0.35 m the host test uses
VOID_FAMILY = (('stair', 'stair'), ('lift', 'elevator'), ('lift', 'lift'))


def _in_core_void(d: Drawing, o: dict) -> bool:
    """The record stands in a slab void that was cut for its OWN core.

    A stair in the stair void and a lift car in the lift void have no floor
    under them by construction — that is what the void is. Reading them as
    'not standing on anything' is what produced eight identical warnings about
    the one stair on the live tower. Two ways in:

      * the void's reason names this record's family (reason 'stair' and a
        stair kind, reason 'lift' and an elevator kind), or
      * the record is a stair standing on the slab the void was cut OUT of —
        the flight starts on the floor whose hole it climbs through."""
    kind = str(o.get('kind') or '')
    x, z, y = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), _num(o.get('y'), 0.0)
    for v in (getattr(d, 'ext', None) or {}).get('slab_voids') or []:
        if not (
            _num(v.get('xmin'), 0.0) <= x <= _num(v.get('xmax'), 0.0)
            and _num(v.get('zmin'), 0.0) <= z <= _num(v.get('zmax'), 0.0)
        ):
            continue
        reason = str(v.get('reason') or '')
        orig = v.get('orig') or {}
        cut_top = _num(orig.get('y'), 0.0) + _num(orig.get('t'), 0.0) if orig else None
        on_cut_slab = cut_top is not None and abs(y - cut_top) <= VOID_HOST_TOL
        if any(reason == r and kind.startswith(k) for r, k in VOID_FAMILY):
            if cut_top is None or on_cut_slab or abs(y - _num(orig.get('y'), 0.0)) <= VOID_HOST_TOL:
                return True
        if kind.startswith('stair') and on_cut_slab:
            return True
    return False


def check_hosts(d: Drawing) -> list:
    """An object that belongs on a walkable surface is on one. Catches the
    lounger left on storey 0 under twenty floors from the other side: not
    'indoors' but 'not standing on anything'. A core standing in its own
    registered slab void is excused — the hole is the point."""
    out = []
    for o in d.objs:
        if o.get('hidden'):
            continue
        s = spec_for_kind(o.get('kind'))
        sp = (s or {}).get('space') or {}
        host = sp.get('host')
        if host not in ('floor', 'deck', 'ground'):
            continue
        if _in_core_void(d, o):
            continue
        y = o.get('y') or 0.0
        tops = [t for t, _ in deck_tops(d, o['x'], o['z'])]
        g = ground_height(d, o['x'], o['z'])
        ok = abs(y - g) <= 0.35 or any(abs(y - t) <= 0.35 for t in tops)
        if not ok:
            near = min([abs(y - t) for t in tops] + [abs(y - g)])
            out.append(
                {
                    'sev': 'warn',
                    'code': 'unsupported',
                    'text': f'{o["id"]} {o.get("name") or o["kind"]} sits at y {y:.2f} m with no floor, deck or '
                    f'ground within 0.35 m (nearest surface {near:.2f} m away) — '
                    f'a {s["title"].lower()} stands on the {host}',
                }
            )
    return out[:8]


def check_gaps(d: Drawing) -> list:
    """Every kind this drawing used that the store cannot describe is recorded
    for the offline filler. This is the "log it once" half: build a thing once
    and the question it raised is queued, with no research inside the job."""
    unknown = set()
    for o in d.objs:
        k = _norm(o.get('kind'))
        if not k or k in SOLID_SKIP or k in GENERIC_KINDS:
            continue
        if not spec_for_kind(k):
            unknown.add(k)
    for k in sorted(unknown):
        record_gap(k, why='built', drawing=getattr(d, 'name', ''))
    if not unknown:
        return []
    return [
        {
            'sev': 'info',
            'code': 'spec_gap',
            'text': f'{len(unknown)} kind(s) in this drawing have no spec yet '
            f'({", ".join(sorted(unknown)[:6])}{"…" if len(unknown) > 6 else ""}) — '
            f'queued for the offline filler; nothing for you to do',
        }
    ]


DESIGN_CHECKS = [check_dims, check_clearances, check_hosts, check_gaps]


# ── the tool ─────────────────────────────────────────────────────────────────
def t_spec(d: Drawing, a, of=''):
    term = str(of or '').strip()
    if not term:
        return 'refused: name the thing to look up, e.g. spec("elevator"), spec("corridor"), spec("dining table")'
    s = spec_for(term)
    if not s:
        record_gap(term, why='asked', drawing=getattr(d, 'name', ''))
        near = sorted({v for v in load_specs()})[:14]
        return (
            f'no spec for "{term[:40]}" yet — it is now queued for the offline filler. Build it with the '
            f'closest tool and normal practice, and say in the summary that it was built without a spec. '
            f'Specs that DO exist: {", ".join(near)}' + (' …' if len(load_specs()) > 14 else '')
        )
    return prose(s)


TOOLS = [
    (
        {
            'name': 'spec',
            'description': 'The knowledge sheet for ONE thing you are about to build: what it is, what it looks like, how '
            'to build it here (the tool and arguments), what to avoid, what makes it high quality, and how '
            'much room it needs around it. Call it for any object whose size, clearance or detail you are '
            'not certain of BEFORE placing it — a lift, an entrance, a corridor, a table, a parking bay. '
            'Answers come back in ≤ 1500 chars. If there is no sheet you are told so and the question is '
            'queued for research; build it anyway with the closest tool. The SPACE line of a sheet is '
            'enforced by design_check, so following it is also how done stops refusing.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'of': {
                        'type': 'string',
                        'description': 'a record kind (elevator), a tool (add_corridor), or a plain '
                        'word (dining table, porte-cochere, wheelchair turning)',
                    }
                },
                'required': ['of'],
            },
        },
        t_spec,
    ),
]

PROMPT = (
    'OBJECT SPECS: spec(of) is the sheet for one thing — what it is, what it looks like, how to build it '
    'here, what to avoid, what makes it good, and how much room it needs around it. Call it before placing '
    'anything whose size or clearance you are unsure of: it costs one step and saves a refused done, because '
    "design_check enforces the sheet's SPACE line (minimum sizes, clear ring, clear space in front, standing "
    'on a floor/deck/ground). A kind with no sheet is queued for research automatically — build it with the '
    'closest tool and say so in the summary.'
)
if len(PROMPT) > 900:
    raise RuntimeError(f'PROMPT is {len(PROMPT)} chars (max 900)')

EXAMPLES = [
    {
        'ask': 'put a lift in the core',
        'core': True,
        'calls': [
            {'tool': 'spec', 'args': {'of': 'elevator'}},
            {'tool': 'add_elevator', 'args': {'cell': 'FG150', 'from_storey': 0, 'to_storey': 19}},
        ],
    },
    {'ask': 'how wide should the corridor be?', 'calls': [{'tool': 'spec', 'args': {'of': 'corridor'}}]},
]
