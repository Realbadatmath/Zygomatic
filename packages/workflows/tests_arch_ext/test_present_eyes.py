# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_present_eyes.py — present() has to SEE the view it reports.

    /usr/bin/python3 tests_arch_ext/test_present_eyes.py

Measured 2026-09-11 on live job 94f5813b (the operator's own 20-storey tower,
saved here as fixtures/live_tower_20260911.json): present()'s 'lobby' view was a
blank grey partition — the camera stands LOBBY_INSIDE_M inside the entrance door
and landed 5 cm INSIDE the Lobby room's own wall — yet the tool cheerfully
reported '14 records in frame', because _bp_framed counted every mesh whose
ORIGIN projected into the frustum and never asked whether anything was in the
way. This test is the proof that both halves are fixed: the lobby camera probes
what is in front of it and steps back / turns until it has air and a sightline,
and the counts are now the records the camera can actually see.

One t_present() of the live fixture: 5 headless Blender renders, ~80 s.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from zyg_workflows.arch_ext_harness import check, finish, BLENDER  # noqa: E402

T0 = time.time()
FIXTURE = os.path.join(HERE, 'tests_arch_ext', 'fixtures', 'live_tower_20260911.json')

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
BP = A.EXT_MODULES.get('blender_power')

check('blender_power loaded', BP is not None)
check('blender is installed', os.path.exists(BLENDER), BLENDER)
check('the live tower fixture is here', os.path.exists(FIXTURE), FIXTURE)
if BP is None or not os.path.exists(BLENDER) or not os.path.exists(FIXTURE):
    finish()

d = A.Drawing(json.load(open(FIXTURE)))
check('the live drawing loads whole', len(d.objs) == 336, f'{len(d.objs)} records')

rep = str(BP.t_present(d, None, engine='eevee', width=640, height=360))
body = rep.split('design check')[0]
print(body.rstrip())
print('  (present took %.0f s)' % (time.time() - T0))

check('present rendered, it did not refuse', not body.lower().startswith('refused'), body[:120])

rows = {}
for line in body.splitlines():
    for title in getattr(BP, 'PRESENT_VIEWS', ('approach', 'section', 'elevation', 'aerial', 'lobby')):
        if line.startswith(title + ': '):
            rows[title] = line

check('every named view produced a row', len(rows) == 5, ', '.join(sorted(rows)))

# 1. every row reports VISIBLE records, not just records whose origin projected in
check(
    'every row counts visible records',
    bool(rows) and all('visible of' in r for r in rows.values()),
    ' | '.join(t for t, r in rows.items() if 'visible of' not in r) or 'all rows',
)

lobby = rows.get('lobby', '')
approach = rows.get('approach', '')

# 2. the lobby is a room, not a wall 5 cm from the lens
m = re.search(r'lobby: (\d+) visible of (\d+) in frustum', lobby)
nvis = int(m.group(1)) if m else -1
nfr = int(m.group(2)) if m else -1
check('the lobby camera can see at least 3 records', nvis >= 3, f'{nvis} visible of {nfr} in frustum')
check('visible is a subset of the frustum', 0 <= nvis <= nfr, f'{nvis} <= {nfr}')

mc = re.search(r'clear ahead ([0-9.]+) m', lobby)
clear = float(mc.group(1)) if mc else -1.0
check('the lobby camera has air in front of it', clear >= 2.0, f'clear ahead {clear} m')

check(
    'a lobby that sees something is not called blank',
    ('BLANK VIEW' in lobby) == (nvis < getattr(BP, 'BLANK_VIEW_N', 3)),
    lobby,
)
check('no blank view, no scolding line', ('a blank view is not a presentation' in body) == ('BLANK VIEW' in body))

# 3. the approach view still finds the front door — the probe must not have
#    disturbed any camera but the lobby's
check('the approach view still has the door in frame', 'door in frame: yes' in approach, approach)

# 4. the rest of the row format is untouched: tests parse it
check(
    'the section row still reports slab voids',
    'stairs/shafts crossing slabs without an opening' in rows.get('section', ''),
    rows.get('section', ''),
)
check('every row still names its png', all(re.search(r'\[view-[^,]+\.png, \d+ KB\]', r) for r in rows.values()))
check(
    'the head line still counts the records',
    bool(re.search(r'presented 5 of 5 views of 336 records', body)),
    body.splitlines()[0][:120],
)

check('the whole presentation fits in 5 minutes', time.time() - T0 < 300, '%.0f s' % (time.time() - T0))

finish()
