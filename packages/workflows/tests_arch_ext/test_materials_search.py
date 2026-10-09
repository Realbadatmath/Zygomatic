# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_materials_search — a white marble is white, and every word counts.

Measured on the operator's own live job 94f5813b (the 20-storey tower saved as
fixtures/live_tower_20260911.json): search_materials('white marble floor')
answered pht_asphalt_floor, pht_blue_floor_tiles_01, pht_brick_floor — three
floors, no marble — because the scorer read words only, and the word "white"
is in none of the 1,500 library names. The luxury floor preset it fell back on,
acg_Marble006, is a BLACK marble: the mean luminance of its albedo map is
25/255.

So the tone now comes off the texture itself (architecture_materials stamps
'lum' and 'tone' on every entry, cached against the map file's mtime) and the
search scores name, group, tone and the rest of the haystack separately, with
the number of DISTINCT query words a row answers winning over the points.

No new kinds, so no browser/Blender pass — this is search over the catalogue.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows import architecture_materials as AM  # noqa: E402

A.load_extensions()
MS = A.EXT_MODULES['materials_search']
HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'live_tower_20260911.json')

# ── the drawing this came from ──────────────────────────────────────────────
d_live = A.Drawing(json.load(open(FIX)))
check('the live tower fixture loads — 336 records', len(d_live.objs) == 336, len(d_live.objs))
check("the live job's finish level is luxury", A.finish_level(d_live) == 'luxury')

CAT = AM.catalogue()
DEFS = CAT['defs']


def tone(kind):
    return (DEFS.get(kind) or {}).get('tone', '')


def lum(kind):
    return (DEFS.get(kind) or {}).get('lum')


def ids(rows):
    return [r['id'] for r in rows]


# ── (1) tone is measured off the albedo map, not guessed from the name ──────
check(
    'every entry carries a tone and a luminance',
    all(x.get('tone') and x.get('lum') is not None for x in DEFS.values()),
    [k for k, x in DEFS.items() if not x.get('tone')][:5],
)
check(
    'acg_Marble006 is BLACK (the old luxury floor), lum ~25',
    tone('acg_Marble006') == 'black' and lum('acg_Marble006') < 40,
    (lum('acg_Marble006'), tone('acg_Marble006')),
)
check(
    'acg_Marble021 is WHITE, lum > 200',
    tone('acg_Marble021') == 'white' and lum('acg_Marble021') > 200,
    (lum('acg_Marble021'), tone('acg_Marble021')),
)
check(
    'the luxury floor of the live job is a white marble',
    tone(A.finish_mat(d_live, 'floor')) == 'white',
    (A.finish_mat(d_live, 'floor'), tone(A.finish_mat(d_live, 'floor'))),
)
check(
    'tone_of buckets on the published edges',
    [AM.tone_of(v) for v in (0, 39.9, 40, 89.9, 90, 149.9, 150, 199.9, 200, 255)]
    == ['black', 'black', 'dark', 'dark', 'mid', 'mid', 'light', 'light', 'white', 'white'],
)
check(
    'the library spreads over every bucket',
    len({x['tone'] for x in DEFS.values()}) == 5,
    sorted({x['tone'] for x in DEFS.values()}),
)
check(
    'the catalogue items carry the tone too (that is what search reads)',
    all(it['p'].get('tone') for g in CAT['groups'] for it in g['items']),
)

# ── (2) the cache: a rescan of an unchanged library costs nothing ───────────
check('the tone cache file exists', os.path.exists(AM.TONE_CACHE), AM.TONE_CACHE)
cache = json.load(open(AM.TONE_CACHE))
check(
    'the tone cache parses and holds one row per entry',
    isinstance(cache.get('entries'), dict) and len(cache['entries']) == len(DEFS),
    (len(cache.get('entries') or {}), len(DEFS)),
)
row = cache['entries'].get('acg_Marble021') or {}
check(
    'a cache row is keyed by id and holds lum, tone and the map mtime',
    row.get('tone') == 'white'
    and row.get('lum') == lum('acg_Marble021')
    and abs(row.get('mtime', 0) - os.path.getmtime(os.path.join(AM.PACKS_ROOT, DEFS['acg_Marble021']['maps']['map'])))
    < 0.01,
    row,
)
AM._CACHE.update({'ts': 0.0, 'mtime': 0.0, 'data': None})
t0 = time.time()
AM.catalogue()
dt = time.time() - t0
check('a full rebuild on the warm cache takes under a second (no re-measuring)', dt < 1.0, f'{dt:.2f}s')

# ── (3) the query that failed live ─────────────────────────────────────────
top3 = MS.search('white marble floor')[:3]
check(
    '"white marble floor" answers with marble',
    len(top3) == 3 and all(r['group'] == 'Marble' for r in top3),
    [(r['id'], r['group']) for r in top3],
)
check(
    '...and every one of them is light or white',
    all(r['tone'] in ('light', 'white') for r in top3),
    [(r['id'], r['tone']) for r in top3],
)
check(
    '...and the black marble is nowhere near the top',
    'acg_Marble006' not in ids(MS.search('white marble floor', 10)),
    ids(MS.search('white marble floor', 10)),
)
check(
    '"dark marble" answers with a dark or black marble',
    MS.search('dark marble')[0]['tone'] in ('dark', 'black'),
    [(r['id'], r['tone']) for r in MS.search('dark marble', 3)],
)
check(
    '"dark marble" answers with marble, not with any dark thing',
    MS.search('dark marble')[0]['group'] == 'Marble',
    MS.search('dark marble')[0],
)
check(
    '"black oak" is the black oak veneer',
    MS.search('black oak')[0]['id'] == 'pht_black_oak_veneer',
    ids(MS.search('black oak', 3)),
)
check(
    '"rough concrete" is the rough concrete',
    MS.search('rough concrete')[0]['id'].startswith('pht_rough_concrete'),
    ids(MS.search('rough concrete', 3)),
)


# ── (4) ranking: more distinct words beats more points ─────────────────────
def hits(q, r):
    return sum(1 for w in re.split(r'[^a-z0-9]+', q.lower()) if w and MS._word_score(w, r))


for q in ('white marble floor', 'dark marble', 'rough concrete', 'black oak', 'red brick'):
    got = [hits(q, r) for r in MS.search(q, 10)]
    check(f'"{q}": rows answering more of the query come first', got == sorted(got, reverse=True), got)

check(
    'a tone word scores where it belongs: exactly asked > neighbour > absent',
    MS._word_score('white', {'n': '', 'group': '', 'hay': '', 'tone': 'white', 'tone_words': {'white', 'light'}}) == 2
    and MS._word_score('white', {'n': '', 'group': '', 'hay': '', 'tone': 'light', 'tone_words': {'light', 'white'}})
    == 1
    and MS._word_score('white', {'n': '', 'group': '', 'hay': '', 'tone': 'mid', 'tone_words': {'mid'}}) == 0,
)
check(
    'a name hit is 3, a group hit 2, the rest of the haystack 1',
    MS._word_score(
        'marble', {'n': 'Marble 021', 'group': 'Other', 'hay': 'marble 021 other', 'tone': '', 'tone_words': set()}
    )
    == 3
    and MS._word_score('marble', {'n': 'X', 'group': 'Marble', 'hay': 'x marble', 'tone': '', 'tone_words': set()}) == 2
    and MS._word_score(
        'marble', {'n': 'X', 'group': 'Other', 'hay': 'x other acg marble 7', 'tone': '', 'tone_words': set()}
    )
    == 1,
)
check(
    '"light marble" and "white marble" both reach the white ones',
    tone(MS.search('light marble')[0]['id']) in ('light', 'white'),
    MS.search('light marble')[0],
)

# ── (5) what the assistant actually reads ──────────────────────────────────
txt = MS.t_search_materials(d_live, None, 'white marble', 5)
check(
    'the reply says the tone of every hit',
    'tile size, tone' in txt.splitlines()[0]
    and all(l.rsplit(', ', 1)[-1] in ('black', 'dark', 'mid', 'light', 'white') for l in txt.splitlines()[1:]),
    txt,
)
check(
    'the reply reads "acg_Marble021 — Marble 021 (Marble), 1x1 m, white"',
    'acg_Marble021 — Marble 021 (Marble), 1x1 m, white' in txt,
    txt,
)
desc = MS.TOOLS[0][0]['description'].lower()
check('the tool description says tone words are understood', 'tone' in desc and 'white marble' in desc, desc[:200])
check('the family PROMPT stays under the 900-char ceiling', len(MS.PROMPT) <= 900, len(MS.PROMPT))

finish()
