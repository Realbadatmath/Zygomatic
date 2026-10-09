# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_wiring_gates — the seams where the new families bite inside the live job.

The families were written in this tree; this proves they are actually CALLED by
arch_assistant.py, not merely importable:

  A. AT CREATION.  Drawing.new asks finish_schedule for the material of every
     record it makes, so a luxury job is born with oak door leaves and light
     plaster partitions instead of flat mat_* presets. A standard job keeps its
     presets — the schedule has no opinion about a mat_plaster partition there.
  B. AT DONE.      design_gate runs finish_schedule.autofinish BEFORE the design
     check, so records drawn before plan_building set the finish level are
     painted too and finish_rules.check_luxury_finishes has nothing left to say.
  C. THE FINDINGS. Eight findings that say the same thing about eight records
     collapse into one 'xN' line: the live tower reports circ_core_clash once
     per stair record, and eight copies of one fact is eight lines of the
     model's reading budget spent on repetition.
  D. THE BUDGET.   The repair tools (FIX_TOOLS) are free — a fix the gate itself
     demanded must not cost drawing calls — and the default budget is 36.
  E. THE PROMPT.   The recipe names the three macros, and both prompt ceilings
     still hold (bare < 90 000, the tower request < 45 000).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_wiring_gates.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
FS = A.EXT_MODULES['finish_schedule']
FR = A.EXT_MODULES['finish_rules']

# the same request test_all.py measures the prompt with
TOWER_REQUEST = (
    'build a building with footprint of 20x20 , 20 stories high . infinity pool on the roof . '
    'roof entrance . nice entrance into the building at ground floor . make ground floor glass '
    'walls , 2nd floor rough concrete wall , 3rd floor glass walls , 4th rough concrete , repeat '
    'this for all floors. center building at cell fh100  make building look luxurious'
)


def planned(request: str, **kw):
    """A drawing with a building programme — the thing that sets finish_level."""
    d = A.Drawing(None)
    d.request = request
    args = dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, name='tower')
    args.update(kw)
    A.call_tool(d, 'plan_building', args)
    return d


# ── A. auto-finish at creation (Drawing.new) ─────────────────────────────────
lux = planned('a luxurious 20-storey tower with an infinity pool on the roof')
check('a luxurious request plans a luxury finish level', FS.finish_level(lux) == 'luxury', FS.finish_level(lux))

door = lux.new('door', {'w': 1.0, 'h': 2.1, 'sill': 0.0}, 0, 0, grp='tower')
check('Drawing.new gives a luxury door the oak leaf (not mat_timber)', door['mat'] == FS.LUX_DOOR, door['mat'])

part = lux.new('partition', {'len': 4.0, 't': 0.1, 'h': 2.7}, 0, 0, grp='tower')
check(
    'Drawing.new gives a luxury partition the light partition plaster (Plaster001, tree 3)',
    part['mat'] == getattr(FS, 'LUX_PARTITION', FS.LUX_PLASTER),
    part['mat'],
)

slab = lux.new('slab', {'w': 20, 'd': 20, 't': 0.25}, 0, 0, grp='tower')
check('Drawing.new gives a luxury slab the marble floor', slab['mat'] == FS.LUX_FLOOR, slab['mat'])

named = lux.new('door', {'w': 1.0, 'h': 2.1}, 0, 0, mat='acg_Metal032', grp='tower')
check('a library material the caller named is never overruled', named['mat'] == 'acg_Metal032', named['mat'])

std = planned('a plain office block', use='office', storeys=6)
check('a plain request stays on the standard finish level', FS.finish_level(std) == 'standard', FS.finish_level(std))
std_part = std.new('partition', {'len': 4.0, 't': 0.1, 'h': 2.7}, 0, 0, mat='mat_plaster', grp='tower')
check(
    'a STANDARD partition keeps mat_plaster (the schedule has no opinion)',
    std_part['mat'] == 'mat_plaster',
    std_part['mat'],
)
std_door = std.new('door', {'w': 1.0, 'h': 2.1}, 0, 0, mat='mat_timber', grp='tower')
check('a standard door leaf is still not a mat_timber preset', std_door['mat'] == FS.LUX_DOOR, std_door['mat'])

bare = A.Drawing(None)  # no programme at all: must not raise
bare_wall = bare.new('wall', {'len': 4.0, 't': 0.24, 'h': 2.7}, 0, 0)
check('a drawing with no building programme still makes records', bare_wall['id'] == 'o1', bare_wall)


# ── B. auto-finish at done (design_gate) ─────────────────────────────────────
# the defect: the drawing is built BEFORE plan_building names the finish level,
# so every record is born a flat preset. This is the live failure of job
# 94f5813b — 8 set_material/set_finish calls and it still ended with presets open.
pre = A.Drawing(None)
A.call_tool(pre, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=6, roof='flat', name='tower'))
A.call_tool(pre, 'add_opening', dict(group='tower', side='south', storey=0, kind='double_door', width=2.8, height=3.0))
pre.request = 'a luxurious tower'
A.call_tool(pre, 'plan_building', dict(use='residential', storeys=6, centre='FH100', width=20, depth=20, name='tower'))
before = FR.check_luxury_finishes(pre)
check(
    'DEFECT: records drawn before plan_building leave luxury findings open',
    len(before) > 0,
    '%d finding(s)' % len(before),
)

lines = []
j = {'_gate': 0}
A.design_gate(j, pre, {}, lines.append)
after = FR.check_luxury_finishes(pre)
check('FIXED: design_gate painted them — check_luxury_finishes is empty', after == [], after[:3])
check(
    'design_gate logs the finishes line',
    any(li.startswith('finishes:') and 'painted by the luxury schedule before the check' in li for li in lines),
    lines[:4],
)
check(
    'the gate still ran the design check (j["_design"] is set)',
    isinstance(j.get('_design'), list),
    type(j.get('_design')),
)

lines2 = []
A.design_gate({'_gate': 0}, pre, {}, lines2.append)
check(
    'a second gate call has nothing left to paint (no finishes line)',
    not any(li.startswith('finishes:') for li in lines2),
    lines2[:4],
)


# ── C. the findings dedupe ───────────────────────────────────────────────────
four = [
    {
        'sev': 'error',
        'code': 'circ_core_clash',
        'text': f'o{i} stair stands inside elevator_shaft o334 — delete("o{i}") and call add_core(group)',
    }
    for i in (228, 229, 230, 231)
]
one = A.dedupe_findings(four)
check('4 findings of one shape collapse to 1', len(one) == 1, one)
check('the collapsed line carries the count x4', one and one[0]['text'].startswith('x4:'), one and one[0]['text'])
check(
    'the collapsed line still names the other record ids',
    one and all(i in one[0]['text'] for i in ('o228', 'o229', 'o230', 'o231')),
    one and one[0]['text'],
)
check(
    'the collapsed line keeps its severity and code',
    one and one[0]['sev'] == 'error' and one[0]['code'] == 'circ_core_clash',
    one,
)

mixed = [
    {'sev': 'error', 'code': 'a_one', 'text': 'o1 is wrong — delete("o1")'},
    {'sev': 'warn', 'code': 'b_two', 'text': 'o2 is odd — move("o2")'},
    {'sev': 'error', 'code': 'a_one', 'text': 'o3 is wrong — delete("o3")'},
]
out = A.dedupe_findings(mixed)
check('different codes are NOT collapsed', len(out) == 2, out)
check('order is kept (errors first stays first)', out[0]['code'] == 'a_one' and out[1]['code'] == 'b_two', out)
check('a finding that occurs once carries no count', not out[1]['text'].startswith('x'), out[1]['text'])
check(
    'an error and a warn of the same text are not merged',
    len(
        A.dedupe_findings(
            [{'sev': 'error', 'code': 'c', 'text': 'o1 bad'}, {'sev': 'warn', 'code': 'c', 'text': 'o2 bad'}]
        )
    )
    == 2,
)
check('dedupe of nothing is nothing', A.dedupe_findings([]) == [])


# ── D. the budget ────────────────────────────────────────────────────────────
TOOLS = {t['name'] for t in A.TOOL_DEFS}
for name in sorted(A.FIX_TOOLS):
    check('FIX_TOOLS "%s" is a real tool' % name, name in TOOLS, sorted(TOOLS)[:5])
    check('FIX_TOOLS "%s" costs no drawing budget' % name, A.draws(name) is False, A.draws(name))
check('draw_box still costs budget', A.draws('draw_box') is True, A.draws('draw_box'))
check('add_core still costs budget', A.draws('add_core') is True, A.draws('add_core'))
check('get_state is still free', A.draws('get_state') is False, A.draws('get_state'))
check('the default drawing budget is 36 calls', A.MAX_CALLS == 36, A.MAX_CALLS)
os.environ['ZYG_ARCH_MAX_CALLS'] = '999'
check('ZYG_ARCH_MAX_CALLS=999 clamps to 80', A._max_calls() == 80, A._max_calls())
os.environ['ZYG_ARCH_MAX_CALLS'] = '1'
check('ZYG_ARCH_MAX_CALLS=1 clamps to 6', A._max_calls() == 6, A._max_calls())
os.environ.pop('ZYG_ARCH_MAX_CALLS', None)
check('with no env var the default is 36 again', A._max_calls() == 36, A._max_calls())


# ── E. the prompt ────────────────────────────────────────────────────────────
recipe = A.tower_recipe()
for macro in ('add_core(', 'build_entrance(', 'build_roof_deck('):
    check('the recipe names %s' % macro, macro in recipe, recipe[:200])
check(
    'the recipe is 12 calls, in order',
    recipe.index('plan_building')
    < recipe.index('add_core(')
    < recipe.index('build_entrance(')
    < recipe.index('layout_floor')
    < recipe.index('build_roof_deck(')
    < recipe.index('present'),
    recipe,
)
check(
    'the recipe never names a tool that does not exist',
    all(
        n in TOOLS
        for n in (
            'plan_building',
            'draw_box',
            'add_curtain_wall',
            'add_facade_bands',
            'add_core',
            'build_entrance',
            'layout_floor',
            'repeat_floor',
            'build_roof_deck',
            'add_balconies',
            'present',
            'done',
        )
    ),
)

req_prompt = A.system_prompt(2.7, TOWER_REQUEST)
for macro in ('add_core(', 'build_entrance(', 'build_roof_deck('):
    check('the tower request prompt names %s' % macro, macro in req_prompt)
kept, _dropped = A.prompt_families(TOWER_REQUEST)
for fam in ('core_kit', 'entrance_kit', 'roof_kit', 'finish_schedule'):
    check('%s is KEPT for the tower request' % fam, fam in kept, sorted(kept)[:6])
check('the prompt no longer teaches the hand-built entrance', 'add_canopy(group=<group>' not in req_prompt)
check('the prompt quotes the real budget (%d)' % A.MAX_CALLS, ('%d DRAWING calls' % A.MAX_CALLS) in req_prompt)

n_bare = len(A.system_prompt(2.7))
n_req = len(req_prompt)
print('  PROMPT BUDGET: bare %d chars (< 90000), tower request %d chars (< 45000)' % (n_bare, n_req), flush=True)
check('the bare prompt is under 90 000 chars (%d)' % n_bare, n_bare < 90000, n_bare)
check('the tower request prompt is under 45 000 chars (%d)' % n_req, n_req < 45000, n_req)

finish()
