# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_icons_all.py — the whole-dock sweep (2026-09-08).

inspection.html ships AR_TOOLS with 231 icons, 138 of them marked `stub:1` —
placeholders drawn dashed with a '[placeholder]' tip. Each extension family
registers its icons in AR_EXT.tools / AR_EXT.modes, and arExtApplyTools() then
deletes the `stub` flag from the matching AR_TOOLS item, so a wired icon simply
stops being a placeholder. This test asks the LIVE tab, in ONE browser_eval,
what every one of those 231 icons is now, and holds the seam to five rules:

  (a) the dock still carries at least 231 icons
  (b) the set of icons still marked stub is EXACTLY the expected leftover set
  (c) no icon that stopped being a stub kept a dashed class or a [placeholder] tip
  (d) every AR_EXT.tools / AR_EXT.modes id is a real AR_TOOLS icon, apart from
      the pick-only modes named below (a mode with no icon of its own)
  (e) the Python EXT_BUTTONS set and the JS `assist:1` flags agree — the
      assistant may press exactly what the tab admits it may press

EXPECTED_STUBS is the honest escape hatch: if a family's task failed, its icons
are still placeholders and belong here WITH the family name, so the sweep stays
green for the right reason instead of by accident. It is empty: every family
landed.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, browser_eval  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ── icons a family did NOT wire: {icon id: 'family — why'} ───────────────────
# Empty = every placeholder in the source is now a real tool. Add an entry (with
# the family that owns it) rather than deleting a check when a family is reset.
EXPECTED_STUBS: dict = {}

# ── AR_EXT registrations that are deliberately NOT icons ─────────────────────
# A transient interaction mode the tab enters through arToolApply() while an
# icon's act() waits for a click. It has no dock button by design, so rule (d)
# names it instead of failing on it.
PICK_ONLY_MODES = {
    'pr_plane_pick': 'precision_input — the click-a-face mode the pr_plane icon '
    'applies while it waits for the user to pick a top face',
}

# ── what the SOURCE declares (the placeholders we started from) ──────────────
src = open(os.path.join(ROOT, 'inspection.html'), encoding='utf-8').read().splitlines()
start = next(i for i, l in enumerate(src) if l.startswith('var AR_TOOLS = ['))
depth = 0
end = start
for i in range(start, len(src)):
    depth += src[i].count('[') - src[i].count(']')
    if i > start and depth <= 0:
        end = i
        break
block = '\n'.join(src[start : end + 1])
SRC_ITEMS = re.findall(r"\{[^{}]*?\bid\s*:\s*'([^']+)'[^{}]*?\}", block)
SRC_STUBS = sorted(
    m.group(1)
    for m in re.finditer(r"\{[^{}]*?\bid\s*:\s*'([^']+)'[^{}]*?\}", block)
    if 'stub:1' in m.group(0) or 'stub: 1' in m.group(0)
)
print(
    'inspection.html AR_TOOLS (lines %d-%d): %d icons, %d marked stub:1\n'
    % (start + 1, end + 1, len(SRC_ITEMS), len(SRC_STUBS))
)

# ── ONE trip to the live tab for everything ─────────────────────────────────
JS = r"""() => {
  arToolsRender();
  const rows = {}, order = [];
  for (const s of AR_TOOLS) for (const t of s.items) {
    order.push(t.id);
    const el = document.querySelector('.ar-tool[data-tool="' + t.id + '"]');
    rows[t.id] = {stub: !!t.stub,
                  dashed: !!(el && el.classList.contains('stub')),
                  tip_placeholder: /\[placeholder\]/.test(el ? (el.getAttribute('title') || '') : ''),
                  section: s.sec, bar: s.bar};
  }
  const ext = window.AR_EXT || {};
  const tools = ext.tools || {}, modes = ext.modes || {};
  return {order: order, rows: rows,
          tools: Object.keys(tools), modes: Object.keys(modes),
          assist: Object.keys(tools).filter(k => !!tools[k].assist),
          native_assist: Object.keys(window.AR_ASSIST_TOOLS || {})};
}"""
r = browser_eval(JS)
v = r['value']
rows, order = v['rows'], v['order']

check(
    'the tab loaded the dock without a page error',
    not r['errors'] and not r['console'],
    (r['errors'] or []) + (r['console'] or []),
)

# ── the table: wired / total per section ────────────────────────────────────
sections: dict = {}
for i in order:
    s = rows[i]['section'] or '(none)'
    n, w = sections.get(s, (0, 0))
    sections[s] = (n + 1, w + (0 if rows[i]['stub'] else 1))
print('  %-34s %6s  %s' % ('SECTION', 'BAR', 'wired/total'))
for s in sorted(sections, key=lambda k: -sections[k][0]):
    n, w = sections[s]
    bar = next(rows[i]['bar'] for i in order if (rows[i]['section'] or '(none)') == s)
    print('  %-34s %6s  %3d/%-3d %s' % (s[:34], str(bar)[:6], w, n, '' if w == n else '  <-- placeholders left'))
tot_w = sum(w for _, w in sections.values())
print('  %-34s %6s  %3d/%-3d\n' % ('TOTAL', '', tot_w, len(order)))

# (a) ────────────────────────────────────────────────────────────────────────
check('the dock carries at least 231 icons (%d)' % len(order), len(order) >= 231, len(order))
check('every icon id is unique', len(set(order)) == len(order), [i for i in set(order) if order.count(i) > 1])
check(
    'the live dock holds every id inspection.html declares (%d)' % len(SRC_ITEMS),
    set(SRC_ITEMS) <= set(order),
    sorted(set(SRC_ITEMS) - set(order)),
)

# (b) ────────────────────────────────────────────────────────────────────────
live_stubs = sorted(i for i in order if rows[i]['stub'])
check(
    'the icons still marked stub are exactly the expected leftovers (%d expected, %d live)'
    % (len(EXPECTED_STUBS), len(live_stubs)),
    set(live_stubs) == set(EXPECTED_STUBS),
    {
        'unexpected still stub': sorted(set(live_stubs) - set(EXPECTED_STUBS)),
        'expected stub but wired': sorted(set(EXPECTED_STUBS) - set(live_stubs)),
    },
)
for i in sorted(EXPECTED_STUBS):
    print('    leftover placeholder %-16s %s' % (i, EXPECTED_STUBS[i]))
check(
    'all %d source placeholders are wired apart from the expected leftovers' % len(SRC_STUBS),
    set(SRC_STUBS) - set(live_stubs) == set(SRC_STUBS) - set(EXPECTED_STUBS),
    sorted((set(SRC_STUBS) & set(live_stubs)) - set(EXPECTED_STUBS)),
)

# (c) ────────────────────────────────────────────────────────────────────────
check(
    'no wired icon kept the dashed placeholder class',
    not [i for i in order if not rows[i]['stub'] and rows[i]['dashed']],
    [i for i in order if not rows[i]['stub'] and rows[i]['dashed']],
)
check(
    'no wired icon kept a [placeholder] tooltip',
    not [i for i in order if not rows[i]['stub'] and rows[i]['tip_placeholder']],
    [i for i in order if not rows[i]['stub'] and rows[i]['tip_placeholder']],
)
check(
    'every icon still marked stub is drawn as one (dashed + [placeholder] tip)',
    all(rows[i]['dashed'] and rows[i]['tip_placeholder'] for i in live_stubs),
    {i: rows[i] for i in live_stubs if not (rows[i]['dashed'] and rows[i]['tip_placeholder'])},
)

# (d) ────────────────────────────────────────────────────────────────────────
registered = set(v['tools']) | set(v['modes'])
orphans = sorted(registered - set(order))
check(
    'every AR_EXT registration (%d tools + %d modes) is a real icon, apart from '
    'the %d named pick-only mode(s)' % (len(v['tools']), len(v['modes']), len(PICK_ONLY_MODES)),
    set(orphans) == set(PICK_ONLY_MODES),
    {
        'unexplained orphans': sorted(set(orphans) - set(PICK_ONLY_MODES)),
        'named but absent': sorted(set(PICK_ONLY_MODES) - set(orphans)),
    },
)
for m in sorted(PICK_ONLY_MODES):
    print('    pick-only mode (no icon by design) %-16s %s' % (m, PICK_ONLY_MODES[m]))

# (e) ────────────────────────────────────────────────────────────────────────
from zyg_workflows import arch_assistant as A  # noqa: E402  (loads arch_assistant_ext/*.py, filling EXT_BUTTONS)

buttons, js_assist, native = set(A.EXT_BUTTONS), set(v['assist']), set(v['native_assist'])
check(
    "every extension tool flagged assist:1 in the JS is in a family's Python BUTTONS (%d)" % len(js_assist),
    js_assist <= buttons,
    sorted(js_assist - buttons),
)
stray = sorted(buttons - js_assist - native)
check(
    'every EXT_BUTTONS entry is either an assist:1 extension tool or a native '
    'AR_ASSIST_TOOLS button (%d buttons = %d ext + %d native)'
    % (len(buttons), len(buttons & js_assist), len(buttons & native)),
    not stray,
    stray,
)
check(
    'every EXT_BUTTONS entry names an icon that exists in the dock',
    buttons <= set(order) | set(PICK_ONLY_MODES),
    sorted(buttons - set(order) - set(PICK_ONLY_MODES)),
)
check(
    'the assistant can press every extension icon it registered a tool for',
    js_assist <= set(order),
    sorted(js_assist - set(order)),
)

print(
    '\n  registrations: %d AR_EXT.tools, %d AR_EXT.modes, %d assist:1'
    % (len(v['tools']), len(v['modes']), len(js_assist))
)
print('  EXT_BUTTONS: %d (%d extension + %d native)' % (len(buttons), len(buttons & js_assist), len(buttons & native)))
finish()
