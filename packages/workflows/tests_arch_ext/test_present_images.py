# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_present_images.py — present() hands the model PICTURES.

    /usr/bin/python3 tests_arch_ext/test_present_images.py

Measured 2026-09-11 on live job 94f5813b (the operator's own 20-storey tower,
saved here as fixtures/live_tower_20260911.json): present() answered in NUMBERS
only. Every count was honest and the presentation was green, yet the building
had a CONCRETE canopy, black marble floors in a "luxury" lobby and lamp posts
taller than the canopy — because the model never saw a single picture of what
it had drawn.

So present() now sends the approach, aerial and lobby renders back as real
images (downscaled JPEGs) with a checklist the model must answer before done().
This test proves the three halves of that seam:

  1. t_present returns {'text', 'images'} — three small JPEGs and the checklist,
     while still str()-ing to its old text so nothing else breaks.
  2. arch_mcp_shim.content_blocks turns that into 1 text + 3 image blocks.
  3. arch_assistant.shim_tool passes text + images through and writes the
     'present: 3 pictures handed to the model' line into the job log.

One t_present() of the live fixture: 5 headless Blender renders, ~80 s.
"""

import base64
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from zyg_workflows.arch_ext_harness import check, finish, BLENDER  # noqa: E402

T0 = time.time()
FIXTURE = os.path.join(HERE, 'tests_arch_ext', 'fixtures', 'live_tower_20260911.json')

from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows import arch_mcp_shim as S  # noqa: E402

A.load_extensions()
BP = A.EXT_MODULES.get('blender_power')

check('blender_power loaded', BP is not None)
check('blender is installed', os.path.exists(BLENDER), BLENDER)
check('the live tower fixture is here', os.path.exists(FIXTURE), FIXTURE)
if BP is None or not os.path.exists(BLENDER) or not os.path.exists(FIXTURE):
    finish()

# ── 2. the shim's block builder (no render needed) ───────────────────────────
print('arch_mcp_shim.content_blocks')
THREE = [['image/jpeg', 'AAA'], ['image/jpeg', 'BBB'], ['image/jpeg', 'CCC']]
blocks = S.content_blocks({'ok': True, 'text': 'hello', 'images': THREE})
kinds = [b['type'] for b in blocks]
check('three pictures make 1 text + 3 image blocks', kinds == ['text', 'image', 'image', 'image'], kinds)
check('the text block is the text', blocks[0].get('text') == 'hello', blocks[0])
check(
    'the pictures keep their order and mime',
    [(b['mimeType'], b['data']) for b in blocks[1:]] == [tuple(i) for i in THREE],
    blocks[1:],
)
check(
    'no more than three pictures go through',
    [b['type'] for b in S.content_blocks({'ok': True, 'text': 't', 'images': THREE + [['image/jpeg', 'DDD']]})]
    == ['text', 'image', 'image', 'image'],
)
check(
    'a reply with no pictures is still one text block',
    [b['type'] for b in S.content_blocks({'ok': True, 'text': 't'})] == ['text'],
)
check(
    "look's single `image` still comes FIRST",
    [b['type'] for b in S.content_blocks({'ok': True, 'text': 't', 'image': ['image/png', 'ZZZ']})]
    == ['image', 'text'],
)
check(
    'a failed tool is an error text block, pictures ignored',
    S.content_blocks({'ok': False, 'error': 'nope', 'images': THREE}) == [{'type': 'text', 'text': 'nope'}],
)

# ── 1. t_present on the live drawing ─────────────────────────────────────────
d = A.Drawing(json.load(open(FIXTURE)))
check('the live drawing loads whole', len(d.objs) == 336, f'{len(d.objs)} records')

print('present (5 renders, ~80 s)')
rep = BP.t_present(d, None, engine='eevee', width=640, height=360)
print('  (present took %.0f s)' % (time.time() - T0))
text = str(rep)
check('present rendered, it did not refuse', not text.lower().startswith('refused'), text[:200])

check('present hands back a dict', isinstance(rep, dict), type(rep).__name__)
if not isinstance(rep, dict):
    finish()
imgs = rep.get('images') or []
check('three pictures come back', len(imgs) == 3, f'{len(imgs)} pictures')
check(
    'every picture is [mime, b64] with mime image/jpeg',
    all(isinstance(i, list) and len(i) == 2 and i[0] == 'image/jpeg' for i in imgs),
    [i[0] if isinstance(i, list) and i else i for i in imgs],
)
check('every base64 payload is under 270 000 chars', all(len(i[1]) < 270_000 for i in imgs), [len(i[1]) for i in imgs])

raws = [base64.b64decode(i[1]) for i in imgs]
check('every payload decodes to a real JPEG', all(r[:2] == b'\xff\xd8' for r in raws), [r[:2] for r in raws])
check('every picture is under 200 KB', all(len(r) < 200 * 1024 for r in raws), [f'{len(r) // 1024} KB' for r in raws])
try:
    from PIL import Image

    widths = []
    for r in raws:
        with Image.open(io.BytesIO(r)) as im:
            widths.append(im.width)
    check('every picture is at most 800 px wide', all(w <= 800 for w in widths), widths)
except Exception as ex:  # noqa: BLE001
    check('PIL can measure the pictures', False, repr(ex))

check(
    'the text asks the model to LOOK at the three pictures',
    'LOOK at the three pictures' in rep.get('text', ''),
    rep.get('text', '')[-300:],
)
check(
    'the checklist asks all five questions',
    all(
        q in rep['text']
        for q in ('1 canopy', '2 lamp posts', '3 lobby', '4 floors/finishes', '5 nothing hangs outside')
    ),
    rep['text'][-400:],
)
check(
    'the old reply is still the text, unchanged in shape',
    text == rep['text'] and 'presented 5 of 5 views of 336 records' in text,
    text.splitlines()[0][:160],
)
check(
    'the five views still each have a row',
    all(('\n%s: ' % v) in text for v in BP.PRESENT_VIEWS),
    [v for v in BP.PRESENT_VIEWS if ('\n%s: ' % v) not in text] or 'all five',
)
check('the design check still rides along', 'design check' in text, text[-200:])

# ── 3. shim_tool unwraps text + images and logs the hand-over ────────────────
# The render above is reused: call_tool is stood in for, so this costs no Blender.
print('shim_tool')
job = {'_token': 'tok-present-images', 'cancel': False, '_d': d, 'log': [], '_draw_calls': 0}
A.JOBS['test-present-images'] = job
orig = A.call_tool
A.call_tool = lambda dd, name, args: rep
try:
    out = A.shim_tool({'id': 'test-present-images', 'token': 'tok-present-images', 'name': 'present', 'args': {}})
finally:
    A.call_tool = orig
    A.JOBS.pop('test-present-images', None)

check('shim_tool says ok', out.get('ok') is True, out.get('error'))
check('shim_tool passes the text through', out.get('text') == rep['text'], str(out.get('text'))[:200])
check('shim_tool passes three pictures through', len(out.get('images') or []) == 3, len(out.get('images') or []))
check('shim_tool sends no base64 down the single-image field', out.get('image') is None, out.get('image'))
check(
    'the job log records the hand-over',
    any('present: 3 pictures handed to the model' in l for l in job['log']),
    job['log'][-3:],
)
check(
    'the blocks the CLI finally sees are 1 text + 3 images',
    [b['type'] for b in S.content_blocks(out)] == ['text', 'image', 'image', 'image'],
    [b['type'] for b in S.content_blocks(out)],
)

# a plain string tool reply must still come back as a string, untouched
plain = A.call_tool(A.Drawing({'objects': []}), 'get_state', {})
check('a normal tool still returns a string', isinstance(plain, str), type(plain).__name__)

check('the whole test fits in 5 minutes', time.time() - T0 < 300, '%.0f s' % (time.time() - T0))

finish()
