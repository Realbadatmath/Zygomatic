# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""T1B — the still generation endpoint, proven by generating a still.

Compiles kanban_server.py (the routes must at least parse), then drives
video_stills end to end on the GPU and checks the PNG is the size asked for,
is not a black frame, and carries no lettering.
"""

import compileall
import importlib.util
import json
import os
import py_compile
import sys
import time

from zyg_workflows.paths import ZYG_CREWS_ROOT

# 2026-10: in THIS repo kanban_server.py is the package
# packages/dashboard/src/zyg_dashboard/kanban_server/. Resolve it BEFORE the
# os.chdir below, and compile it alongside the legacy single file.
_DASH = importlib.util.find_spec('zyg_dashboard')
KANBAN_PKG = os.path.join(next(iter(_DASH.submodule_search_locations)), 'kanban_server')

CWD = str(ZYG_CREWS_ROOT)
os.chdir(CWD)
sys.path.insert(0, CWD)

py_compile.compile(os.path.join(CWD, 'kanban_server.py'), doraise=True)
print('kanban_server.py compiles')

if not compileall.compile_dir(KANBAN_PKG, quiet=1, force=True):
    raise SystemExit('kanban_server package does not compile: %s' % KANBAN_PKG)
print('kanban_server package compiles:', KANBAN_PKG)

from zyg_workflows import video_stills as vst  # noqa: E402

PROMPT = (
    'Aerial first-person view from high above a vast empty desert at '
    'golden hour, endless rippled sand dunes to a hazy horizon in the '
    'upper middle of the frame, fine sand grains streaming low across '
    'the ground in the wind, warm low sun from the left, long soft '
    'shadows, ultra-detailed, photoreal, wide angle'
)
NEG = 'people, animals, text, watermark, buildings, roads, tornado'

j = vst.generate(PROMPT, 1280, 720, 11, NEG, 'qwen', 't1b')
jid = j['id']
print(f'job {jid} queued')

deadline = time.time() + 900
while time.time() < deadline:
    j = vst.job(jid)
    if j.get('state') in ('done', 'error'):
        break
    time.sleep(5)

print('--- job log tail ---')
for line in j.get('log', [])[-20:]:
    print(line)
print('--- end log tail ---')

assert j.get('state') == 'done', f'state={j.get("state")} error={j.get("error")}'
path = j['path']
assert os.path.isfile(path), path

from PIL import Image  # noqa: E402

with Image.open(path) as im:
    assert im.size == (1280, 720), im.size
    lum = im.convert('L')
    mean = sum(i * n for i, n in enumerate(lum.histogram())) / (im.width * im.height)
print(f'size {im.size} mean luminance {mean:.1f}')
assert mean > 40, f'frame too dark: {mean:.1f}'

from zyg_workflows import typography_ocr  # noqa: E402

verdict = typography_ocr.judge(path)
assert verdict is not None, 'typography_ocr engine unavailable'
assert verdict[0] is True, f'lettering found: {verdict[1]}'
print(f'typography_ocr: clean ({verdict[0]})')

side = os.path.splitext(path)[0] + '.json'
assert os.path.isfile(side), side
print('sidecar ok:', json.load(open(side))['backend'])

receipt = os.path.join(CWD, 'output', 'video_studio', '_stills', 't1b_receipt.json')
with open(receipt, 'w', encoding='utf-8') as fh:
    json.dump({'path': path, 'seconds': j.get('seconds', 0.0), 'backend': j.get('backend', '')}, fh, indent=2)
print('receipt:', receipt)
print('T1B OK')
