# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T1 proof: one prompt per chained link, dry run walks EVERY link.

No GPU, no ComfyUI, no kanban-server: start_render() runs the real worker in a
thread with dry_run on, so the log it leaves is the log a real render would
write, minus the submit.
"""

import compileall
import importlib.util
import os
import sys
import time
import py_compile

from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
py_compile.compile(os.path.join(CREWS, 'video_studio.py'), doraise=True)
py_compile.compile(os.path.join(CREWS, 'kanban_server.py'), doraise=True)

# 2026-10: in THIS repo kanban_server.py is the package
# packages/dashboard/src/zyg_dashboard/kanban_server/ — compile it too, so the
# routes this harness drives are parse-checked where they actually live.
_DASH = importlib.util.find_spec('zyg_dashboard')
KANBAN_PKG = os.path.join(next(iter(_DASH.submodule_search_locations)), 'kanban_server')
if not compileall.compile_dir(KANBAN_PKG, quiet=1, force=True):
    raise SystemExit('kanban_server package does not compile: %s' % KANBAN_PKG)
print('kanban_server package compiles:', KANBAN_PKG)

sys.path.insert(0, CREWS)
from zyg_workflows import video_studio as vs  # noqa: E402
from PIL import Image  # noqa: E402

os.makedirs('/tmp/claude-1000/vstwire', exist_ok=True)
still = '/tmp/claude-1000/vstwire/t1_still.png'
Image.new('RGB', (832, 480), (120, 100, 80)).save(still)

p = dict(vs.defaults())
p.update(
    {
        'dry_run': True,
        'link_prompts': 'LINK ONE fly forward || LINK TWO turn left || LINK THREE dive',
        'duration_s': '10.2',
        'frames': 61,
        'fps': 17,
        'motion_gate': False,
    }
)

j = vs.start_render('still', 'T1 test', still, p)
jid = j['id']
deadline = time.time() + 120
while time.time() < deadline:
    st = vs.job(jid)['state']
    if st in ('done', 'error'):
        break
    time.sleep(0.5)

j = vs.job(jid)
log = '\n'.join(j['log'])
print(log[-3000:])
print('--- state:', j['state'])

# The brief's literal `'link 1/3 positive: LINK ONE' in log` cannot hold: the
# piece is fed to compose_prompt as scene_prompt, and compose_prompt leads with
# the camera phrase before the scene text ("gentle dolly push-in, ... LINK ONE
# fly forward. medium shot. ..."). That IS the required behaviour — "every link
# still gets the camera/motion/look phrases". So the check asserts the piece is
# in link i's own positive LINE, which is the same claim without the false
# assumption about word order.
pos_lines = [ln for ln in j['log'] if 'positive:' in ln and 'link ' in ln]
assert len(pos_lines) == 3, f'expected 3 link positive lines, got {len(pos_lines)}'
for i, piece in enumerate(('LINK ONE fly forward', 'LINK TWO turn left', 'LINK THREE dive')):
    assert f'link {i + 1}/3 positive:' in pos_lines[i], f'link {i + 1} line out of order: {pos_lines[i][:120]}'
    assert piece in pos_lines[i], f'link {i + 1} missing its piece: {pos_lines[i][:200]}'
for i in range(3):
    assert f'link {i + 1}/3 dry run — nothing submitted' in log, f'link {i + 1} did not report a dry-run skip'
print('3 link positive lines, in order, each carrying its own piece')

print('4th link fallback:', vs.compose_link_prompts(p, 'x', 4)[3][0][:80])
print('T1 OK')
