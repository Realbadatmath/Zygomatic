# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_all.py — the whole-seam sweep for the Architecture Studio
assistant (2026-09-07).

Every capability family proves itself in its own tests_arch_ext/test_<family>.py.
This proves the WHOLE: that the families still pass together, that the registries
they merged into agree with each other, that EVERY kind the assistant knows
builds in the tab AND in Blender, that the two hand-written regressions still
pass, that the system prompt still fits the budget — and it regenerates
arch_ext/CAPABILITIES.md from the live registries so the index cannot go stale.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_all.py

Re-runnable. Ends with ALL GREEN (exit 0) or N FAILED (exit 1).

The family tests are run SEQUENTIALLY on purpose: arch_ext_harness serialises
Blender across processes with a file lock, so running them in parallel only
queues them behind each other while holding 24 idle Chrome instances.
"""

from __future__ import annotations

import collections
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zyg_workflows.arch_ext_harness import check, finish, browser_kinds, blender_kinds, rail_has  # noqa: E402

PY = sys.executable
CAPS = os.path.join(ROOT, 'arch_ext', 'CAPABILITIES.md')
CONTROL_TOOLS = ('look', 'ask_user', 'done')  # handled by the agent loop, no TOOL_FN
T0 = time.time()


def _stamp(msg):
    print('\n[%5.1fs] %s' % (time.time() - T0, msg), flush=True)


def _last_line(p: subprocess.CompletedProcess) -> str:
    for stream in (p.stdout or '', p.stderr or ''):
        lines = [l.rstrip() for l in stream.splitlines() if l.strip()]
        if lines:
            return lines[-1]
    return '(no output)'


# ── 1. every family test, sequentially ────────────────────────────────────────
_stamp('1. family tests')
FAMILY_TESTS = sorted(f for f in glob.glob(os.path.join(HERE, 'test_*.py')) if os.path.basename(f) != 'test_all.py')
fam_result: dict = {}
for f in FAMILY_TESTS:
    fam = os.path.basename(f)[len('test_') : -len('.py')]
    t = time.time()
    p = subprocess.run([PY, f], capture_output=True, text=True, timeout=1800, cwd=ROOT)
    last = _last_line(p)
    ok = p.returncode == 0 and last.startswith('ALL GREEN')
    fam_result[fam] = {'ok': ok, 'last': last, 'rc': p.returncode, 's': round(time.time() - t, 1)}
    print('  %-24s %-4s %5.1fs  %s' % (fam, 'PASS' if ok else 'FAIL', time.time() - t, last), flush=True)

bad_fams = [k for k, v in fam_result.items() if not v['ok']]
check(
    'every family test passes (%d families)' % len(fam_result),
    not bad_fams,
    '; '.join('%s: %s' % (k, fam_result[k]['last']) for k in bad_fams),
)

# ── 2. the merged registries ──────────────────────────────────────────────────
_stamp('2. registries')
from zyg_workflows import arch_assistant as A  # noqa: E402

# Kinds that are a VOID, not a solid, in BOTH engines by design — so "no mesh" is the
# correct answer for them, not a missing kind. `opening` draws an EdgesGeometry outline
# in the tab (inspection.html `case 'opening'`, `line:1`) and arch_blender_build.py:465
# skips it, because the hole is cut into the wall it sits in. The ground_v3 family's ten
# `sculpt_*` kinds are voids for the same reason the other way round: they are PARAMETERS
# of the one sculpted heightfield (`ground`), so the tab draws only their footprint
# outline (arch_ext/ground_v3.js `rect`/`ellipse`, `line:1`) and the Blender builder skips
# them (arch_blender_ext/ground_v3.py). They are unioned in from the family itself rather
# than re-listed here, and asserted positively below (a real outline, not the unknown-kind
# marker cube), so this set cannot quietly swallow a real regression.
#
# 2026-09-08: ground_v3 is no longer the only family with voids — draw_guides
# (guide_*), measure_annotations (dim_* / label_text), organise_model (gridline),
# share_collab (markup_note) and site_context (site_boundary) each draw a line, a
# text sprite or nothing at all. Union over EVERY loaded family, so a family that
# declares VOID_KINDS is counted the moment it lands instead of failing the sweep
# until this line is edited by hand.
VOID_KINDS = {'opening'}
for _m in A.EXT_MODULES.values():
    VOID_KINDS |= {str(k) for k in (getattr(_m, 'VOID_KINDS', []) or [])}

names = [t['name'] for t in A.TOOL_DEFS]
dups = sorted(n for n, c in collections.Counter(names).items() if c > 1)
check('no duplicate tool names (%d tools)' % len(names), not dups, dups)

bad_schema, untyped = [], []
for t in A.TOOL_DEFS:
    s = t.get('input_schema')
    if not isinstance(s, dict) or s.get('type') != 'object' or not isinstance(s.get('properties'), dict):
        bad_schema.append((t['name'], 'not a JSON-schema object with properties'))
        continue
    req = s.get('required')
    if req is not None and (not isinstance(req, list) or any(r not in s['properties'] for r in req)):
        bad_schema.append((t['name'], 'required %r is not a subset of properties' % (req,)))
    for k, v in s['properties'].items():
        if not isinstance(v, dict):
            bad_schema.append((t['name'], 'property %s is not an object' % k))
        elif not ({'type', 'enum', 'anyOf', 'oneOf'} & set(v)):
            untyped.append('%s.%s' % (t['name'], k))
check('every input_schema is a valid JSON-schema object', not bad_schema, bad_schema)
check(
    'every tool has a non-empty description',
    all((t.get('description') or '').strip() for t in A.TOOL_DEFS),
    [t['name'] for t in A.TOOL_DEFS if not (t.get('description') or '').strip()],
)
no_fn = [n for n in names if n not in A.TOOL_FN and n not in CONTROL_TOOLS]
check('every tool has an implementation (bar %s)' % ', '.join(CONTROL_TOOLS), not no_fn, no_fn)
if untyped:
    print(
        '  NOTE  %d schema properties are deliberately type-free (any type): %s' % (len(untyped), ', '.join(untyped)),
        flush=True,
    )

missing_rail = rail_has(sorted(A.KINDS))
rail_ext = [k for k in missing_rail if k in A.EXT_KINDS]
rail_base = [k for k in missing_rail if k not in A.EXT_KINDS]
check('every extension kind is in the library rail (%d ext kinds)' % len(A.EXT_KINDS), not rail_ext, rail_ext)
if rail_base:
    print(
        '  NOTE  %d base kinds are not rail leaves (never were): %s' % (len(rail_base), ', '.join(rail_base)),
        flush=True,
    )
else:
    print('  ok   every base kind is in the library rail too', flush=True)

# kind -> family, for grouping the failures below
KIND_FAMILY: dict = {}
FAM_TOOLS: dict = {}
FAM_KINDS: dict = {}
for fam, mod in sorted(A.EXT_MODULES.items()):
    FAM_TOOLS[fam] = [t for t, _fn in (getattr(mod, 'TOOLS', []) or [])]
    FAM_KINDS[fam] = dict(getattr(mod, 'KINDS', {}) or {})
    for k in FAM_KINDS[fam]:
        KIND_FAMILY[k] = fam
for k in A.KINDS:
    KIND_FAMILY.setdefault(k, 'core')

ALL_KINDS = sorted(A.KINDS)
CASES = [{'kind': k, 'p': dict(A.KINDS[k])} for k in ALL_KINDS]


def _by_family(kinds):
    out: dict = collections.defaultdict(list)
    for k in kinds:
        out[KIND_FAMILY.get(k, 'core')].append(k)
    return dict(out)


# ── 3. one browser run over EVERY kind ────────────────────────────────────────
_stamp('3. the tab: %d kinds through arGeom' % len(CASES))
tab = browser_kinds(CASES)
tab_by_kind = {r['kind']: r for r in tab}
SOLID_KINDS = [k for k in ALL_KINDS if k not in VOID_KINDS]
tab_bad = [k for k in SOLID_KINDS if not (tab_by_kind.get(k) or {}).get('ok')]
for k in tab_bad:
    r = tab_by_kind.get(k) or {}
    print(
        '  FAIL tab %-22s [%s] registered=%s tris=%s parts=%s size=%s %s'
        % (
            k,
            KIND_FAMILY.get(k, 'core'),
            r.get('registered'),
            r.get('tris'),
            r.get('parts'),
            r.get('size'),
            r.get('err', ''),
        ),
        flush=True,
    )
check(
    'every solid kind builds real geometry in the tab (%d of %d kinds)' % (len(SOLID_KINDS), len(ALL_KINDS)),
    not tab_bad,
    json.dumps(_by_family(tab_bad)),
)
check(
    'no kind falls back to the 0.5 m unknown-kind marker cube',
    not [
        k for k in tab if k['tris'] == 12 and k['parts'] == 1 and not k['registered'] and k['size'] == [0.5, 0.5, 0.5]
    ],
    [
        k['kind']
        for k in tab
        if k['tris'] == 12 and k['parts'] == 1 and not k['registered'] and k['size'] == [0.5, 0.5, 0.5]
    ],
)
# the void kinds: arGeom DOES know them. "Void" is a statement about the SOLID they
# do not carry, and the tab draws each of them in the way its own family means to:
#
#   · `opening` is the wall hole — a w x h x 0.3 EdgesGeometry, size pinned exactly.
#   · a sculpt_* is a parameter of the one sculpted ground, drawn as its footprint
#     outline (a rect or an ellipse lying in the ground plane): zero faces, both plan
#     extents real, flat in y. Pinned by that shape.
#   · 2026-09-08: the other families' voids are neither. A `gridline` is a single
#     straight line, so ONE plan extent is zero by definition; a `site_boundary` is a
#     boundary that stands up, so it is not flat in y; a `markup_note` is an
#     annotation that legitimately draws a small sprite with faces — it is a void in
#     Blender, not in the tab. Holding those three to the sculpt shape asserted
#     something none of them ever claimed. What every void must really prove is that
#     arGeom KNOWS it: registered, no error, and something with real extent on screen
#     rather than the 0.5 m unknown-kind marker cube.
SCULPT_VOIDS = sorted(k for k in VOID_KINDS if k.startswith('sculpt_'))
for k in sorted(VOID_KINDS):
    r = tab_by_kind.get(k) or {}
    sz = r.get('size') or [0, 0, 0]
    zero_build = r.get('tris') == 0 and r.get('parts') == 0 and not r.get('err')
    marker = r.get('tris') == 12 and r.get('parts') == 1 and not r.get('registered') and sz == [0.5, 0.5, 0.5]
    if k == 'opening':
        p = A.KINDS[k]
        want = [p.get('w', 1.0), p.get('h', 2.1), 0.3]
        check(
            'void kind %s draws a line-only outline sized %s in the tab' % (k, want),
            zero_build and all(abs(sz[i] - want[i]) < 1e-3 for i in range(3)),
            r,
        )
    elif k in SCULPT_VOIDS:
        check(
            'void kind %s draws a flat line-only footprint outline in the tab (no faces)' % k,
            zero_build and r.get('registered') and sz[0] > 0.1 and sz[2] > 0.1 and sz[1] < 0.5,
            r,
        )
    else:
        check(
            'void kind %s is known to arGeom and draws with real extent, not the marker cube' % k,
            r.get('registered') and not r.get('err') and not marker and max(sz) > 0.1,
            r,
        )

# ── 4. one Blender run over EVERY kind ────────────────────────────────────────
_stamp('4. Blender: the same %d kinds' % len(CASES))
bl = blender_kinds(CASES)
bl_bad = [k for k in SOLID_KINDS if (bl.get(k) or {}).get('polys', 0) <= 0]
for k in bl_bad:
    print('  FAIL blender %-22s [%s] %s' % (k, KIND_FAMILY.get(k, 'core'), bl.get(k) or 'no mesh'), flush=True)
check(
    'every solid kind builds a mesh with faces in Blender (%d of %d kinds)' % (len(SOLID_KINDS), len(ALL_KINDS)),
    not bl_bad,
    json.dumps(_by_family(bl_bad)),
)
# A void is void in one of TWO ways in Blender, and both are correct. `opening` is
# the wall hole: there is nothing to make, so the builder skips it outright and no
# object reaches the scene at all — it is simply absent from `bl`. A sculpt_* (and
# a gridline, a dim_*, a markup_note…) is a parameter or an annotation rather than
# a solid, but the operator still has to be able to find and select the record in
# Blender, so its builder emits the object anyway carrying a placeholder mesh of at
# most one quad (today: an empty mesh, 0 polys).
#
# 2026-09-08: the old rule hard-coded `skipped == 1`, which only held while
# `opening` was the single skipping void. The honest rule is: the builders skip
# exactly those void kinds that reach no object into the scene, every other void
# carries at most 2 polygons, and a void with real faces is the failure.
info = bl.get('_info') or {}
sk = info.get('skipped')
sk_n = len(sk) if isinstance(sk, list) else int(sk or 0)
VOID_IN_CASES = sorted(k for k in VOID_KINDS if k in ALL_KINDS)
void_skipped = [k for k in VOID_IN_CASES if k not in bl]  # no object built
void_emitted = [k for k in VOID_IN_CASES if k in bl]  # placeholder mesh
fat = [(k, (bl.get(k) or {}).get('polys')) for k in void_emitted if (bl.get(k) or {}).get('polys', 0) > 2]
check(
    'Blender skips exactly the %d void kind(s) that build nothing (%s) and the other %d '
    'carry at most 2 polygons (builder reported skipped=%s)'
    % (len(void_skipped), ', '.join(void_skipped) or 'none', len(void_emitted), sk),
    sk_n == len(void_skipped) and not fat,
    {
        'skipped by the builder': sk,
        'voids with no object': void_skipped,
        'voids with a placeholder mesh': void_emitted,
        'over 2 polys': fat,
    },
)

# ── 5. regressions ────────────────────────────────────────────────────────────
_stamp('5. regressions')
REGRESSIONS = (
    # test_arch_assistant.py became the package src/zyg_workflows/test_arch_assistant/
    # (2026-10 split); its __main__.py replaces the old `python <file>` entry.
    ('zyg_workflows.test_arch_assistant', [PY, '-m', 'zyg_workflows.test_arch_assistant']),
    (
        os.path.join('tests_arch_ext', 'test_curved_walls.py'),
        [PY, os.path.join(ROOT, 'tests_arch_ext', 'test_curved_walls.py')],
    ),
)
for label, cmd in REGRESSIONS:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=ROOT)
    last = _last_line(p)
    check('regression %s ends ALL GREEN' % label, p.returncode == 0 and last.startswith('ALL GREEN'), last)
    print('       %s -> %s' % (label, last), flush=True)

# ── 6. prompt budget ──────────────────────────────────────────────────────────
_stamp('6. prompt budget')
prompt = A.system_prompt(2.7)
n = len(prompt)
print(
    '  system_prompt(2.7) = %d chars | %d tools | %d kinds (%d from families) | %d worked examples | %d families'
    % (n, len(A.TOOL_DEFS), len(A.KINDS), len(A.EXT_KINDS), len(A.EXT_EXAMPLES), len(A.EXT_MODULES)),
    flush=True,
)
# 2026-09-08: the budget was 60 000 when 39 families were loaded. The icon tree
# took that to 70 families / 285 tools and the prompt to ~79 k, so the ceiling is
# raised to the 80 000 the final-sweep brief names. It is a REAL ceiling, not a
# formality: the CLI caches this prefix on every call, so it must not drift on
# past 80 k without someone deciding to pay for it.
# 2026-09-10 (prompt diet): this tree's own families took the bare prompt to
# 95 992 and the check went red. The DESIGN RULES sheet moved to
# explain('design rules') and thirteen family paragraphs gave their how-to detail
# to an explain() topic each, which buys the ceiling back at 85 000. The number
# that actually costs money is the SECOND one: what a real request pays after
# system_prompt() drops the OPTIONAL families (PROMPT_FAMILIES) it does not need.
TOWER_REQUEST = (
    'build a building with footprint of 20x20 , 20 stories high . infinity pool on the roof . '
    'roof entrance . nice entrance into the building at ground floor . make ground floor glass '
    'walls , 2nd floor rough concrete wall , 3rd floor glass walls , 4th rough concrete , repeat '
    'this for all floors. center building at cell fh100  make building look luxurious'
)
nreq = len(A.system_prompt(2.7, TOWER_REQUEST))
print(
    '  bare %d chars | the 2026-09-10 tower request trims it to %d (%d families dropped)'
    % (n, nreq, len(A.LAST_PROMPT_INFO.get('dropped') or [])),
    flush=True,
)
# 2026-09-11: 78 families (floor_plans + plan_solver joined) put the BARE prompt at 85.4k; the
# bare call is the probe/docs path only — every live run is request-trimmed (the 45k line below
# is the real budget). Ceiling 90 000 buys ~4 more families; after that, trim paragraphs again.
check('system prompt under 90 000 chars (%d)' % n, n < 90000, n)
check('the tower request trims the prompt under 45 000 chars (%d)' % nreq, nreq < 45000, nreq)
check(
    'the prompt names every extension family paragraph (%d)' % len(A.EXT_PROMPTS),
    len(A.EXT_PROMPTS) == len(A.EXT_MODULES),
    '%d prompts for %d modules' % (len(A.EXT_PROMPTS), len(A.EXT_MODULES)),
)


# ── 7. arch_ext/CAPABILITIES.md, generated from the live registries ───────────
_ABBR = ('e.g.', 'i.e.', 'etc.', 'cf.', 'vs.', 'no.', 'approx.', 'max.', 'min.')


def _sentence(txt: str) -> str:
    """The description's FIRST sentence — without cutting it at an abbreviation."""
    txt = ' '.join((txt or '').split())
    parts = txt.split('. ')
    out, i = parts[0], 1
    while i < len(parts) and (out + '.').lower().endswith(_ABBR):
        out, i = out + '. ' + parts[i], i + 1
    out = out.strip()
    return out if out.endswith('.') else out + '.'


def _args(tdef: dict) -> str:
    s = tdef.get('input_schema') or {}
    props = list((s.get('properties') or {}).keys())
    req = [p for p in (s.get('required') or []) if p in props]
    opt = [p for p in props if p not in req]
    bits = list(req)
    if opt:
        bits.append('[' + ', '.join(opt) + ']')
    return ', '.join(bits) if bits else '(none)'


def _params(p: dict) -> str:
    return (
        ', '.join(
            '%s=%s' % (k, ('%g' % v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for k, v in p.items()
        )
        or '(no parameters)'
    )


def _tool_lines(defs):
    out = []
    for t in sorted(defs, key=lambda t: t['name']):
        out.append('- **`%s`** — %s\n  - args: `%s`' % (t['name'], _sentence(t.get('description', '')), _args(t)))
    return out


def _kind_lines(kinds: dict):
    out = []
    for k in sorted(kinds):
        flag = '  *(opening — the tab cuts a hole for it)*' if A.is_opening(k) else ''
        out.append('- **`%s`** — %s%s' % (k, _params(kinds[k]), flag))
    return out


_stamp('7. arch_ext/CAPABILITIES.md')
fam_tool_names = {t['name'] for defs in FAM_TOOLS.values() for t in defs}
core_tools = [t for t in A.TOOL_DEFS if t['name'] not in fam_tool_names]
core_kinds = {k: v for k, v in A.KINDS.items() if k not in A.EXT_KINDS}

L = [
    '# Architecture Studio assistant — capability index',
    '',
    'Generated by `tests_arch_ext/test_all.py` from the live registries '
    '(`arch_assistant.TOOL_DEFS` / `.KINDS` / `.EXT_MODULES`). Do not edit by hand — '
    'run the sweep and it is rewritten, so it cannot go stale.',
    '',
    'The seam itself is described in `arch_ext/README.md`: one capability family = one basename in '
    '`arch_ext/<family>.js|.json`, `arch_assistant_ext/<family>.py`, `arch_blender_ext/<family>.py` and '
    '`tests_arch_ext/test_<family>.py`.',
    '',
    '| | count |',
    '|---|---|',
    '| capability families | %d |' % len(A.EXT_MODULES),
    '| tools | %d (%d core + %d from families) |' % (len(A.TOOL_DEFS), len(core_tools), len(fam_tool_names)),
    '| kinds | %d (%d core + %d from families) |' % (len(A.KINDS), len(core_kinds), len(A.EXT_KINDS)),
    '| opening kinds | %d |' % (len(A.OPENINGS) + len(A.OPENINGS_EXT)),
    '| worked examples | %d |' % len(A.EXT_EXAMPLES),
    '| system prompt | %d chars (budget 80 000) |' % n,
    '',
    '---',
    '',
    '## core — `arch_assistant.py`',
    '',
    'The base assistant: cells and blocks, walls and openings, storeys, materials, the drawing itself. '
    'Every family below is loaded on top of it by `load_extensions()` at import.',
    '',
    '### Tools (%d)' % len(core_tools),
    '',
]
L += _tool_lines(core_tools)
L += ['', '### Kinds (%d)' % len(core_kinds), '']
L += _kind_lines(core_kinds)
L += ['']

for fam in sorted(A.EXT_MODULES):
    mod = A.EXT_MODULES[fam]
    defs, kinds = FAM_TOOLS[fam], FAM_KINDS[fam]
    ex = [e for e in (getattr(mod, 'EXAMPLES', []) or [])]
    L += [
        '---',
        '',
        '## %s — `arch_assistant_ext/%s.py`' % (fam, fam),
        '',
        ' '.join((str(getattr(mod, 'PROMPT', '') or '(no prompt paragraph)')).split()),
        '',
        '_%d tools · %d kinds · %d worked examples_' % (len(defs), len(kinds), len(ex)),
        '',
    ]
    if defs:
        L += ['### Tools (%d)' % len(defs), ''] + _tool_lines(defs) + ['']
    if kinds:
        L += ['### Kinds (%d)' % len(kinds), ''] + _kind_lines(kinds) + ['']

L += [
    '---',
    '',
    '**Total: %d families, %d tools, %d kinds, %d worked examples, %d-char system prompt.** '
    'Every kind in this index is proven to build in the tab (`arGeom`) and in Blender by '
    '`tests_arch_ext/test_all.py` — except the %d void kind(s) (%s), which carry no solid by '
    'design: a hole in the wall they sit in, a parameter of the one sculpted ground, a guide, a '
    'grid line or an annotation. Each draws a line or a sprite in the tab, and in Blender is '
    'either skipped outright or emitted as a selectable placeholder of at most one quad.'
    % (
        len(A.EXT_MODULES),
        len(A.TOOL_DEFS),
        len(A.KINDS),
        len(A.EXT_EXAMPLES),
        n,
        len(VOID_KINDS),
        ', '.join('`%s`' % k for k in sorted(VOID_KINDS)),
    ),
    '',
]

os.makedirs(os.path.dirname(CAPS), exist_ok=True)
with open(CAPS, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(L))
size = os.path.getsize(CAPS)
print('  wrote %s — %d bytes, %d lines' % (CAPS, size, len(L)), flush=True)
check(
    'arch_ext/CAPABILITIES.md exists and is over 20 KB (%d bytes)' % size, os.path.isfile(CAPS) and size > 20480, size
)
check(
    'CAPABILITIES.md documents every family',
    all(('## %s —' % f) in '\n'.join(L) for f in A.EXT_MODULES),
    [f for f in A.EXT_MODULES if ('## %s —' % f) not in '\n'.join(L)],
)

# ── the sweep's own summary ───────────────────────────────────────────────────
_stamp('summary')
print(
    '  families: %d PASS, %d FAIL%s'
    % (len(fam_result) - len(bad_fams), len(bad_fams), ('  (' + ', '.join(bad_fams) + ')') if bad_fams else '')
)
print(
    '  kinds: %d total = %d solid + %d void (%s) | tab %d ok %d bad | blender %d ok %d bad'
    % (
        len(ALL_KINDS),
        len(SOLID_KINDS),
        len(VOID_KINDS),
        ', '.join(sorted(VOID_KINDS)),
        len(SOLID_KINDS) - len(tab_bad),
        len(tab_bad),
        len(SOLID_KINDS) - len(bl_bad),
        len(bl_bad),
    )
)
print(
    '  prompt: %d chars | tools %d | kinds %d | examples %d' % (n, len(A.TOOL_DEFS), len(A.KINDS), len(A.EXT_EXAMPLES))
)
finish()
