#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build the text_judges fixture set: 12 planted anachronisms, their 12 clean twins, and one
sign board in five variants. PIL only — no model, no render, no network.

The fixture set for `capability_tests/text_judges.py`. The plant table and the sign table live
in the TEST module, not here, so the test and the pictures can never drift: this script imports
them. What lives here is only the operator's local wiring — which approved still each plant
goes into, and where the cutout PNG for it sits.

    python3 capability_tests/fixtures/text_judges/plant.py --write-manifest
    python3 capability_tests/fixtures/text_judges/plant.py --clean
    python3 capability_tests/fixtures/text_judges/plant.py --planted
    python3 capability_tests/fixtures/text_judges/plant.py --signs

Run from the crews root. `--write-manifest` first: the other three read MANIFEST.json.

What the operator fills in before the first run
-----------------------------------------------
SOURCES: one line per plant id, naming an APPROVED 1671 still (run id, S slot, path) that
already contains nothing anachronistic, plus the path of the cutout PNG with alpha. Nothing
is downloaded — the cutouts are CC0 images the operator has already saved under `cutouts/`,
and every plant's provenance sentence is in the TEST module's PLANTS table.

SLOT_NOUNS: per plant id, the checkable nouns that slot's render prompt supports, written by
hand. That list is the key `prompt_derived` is scored against; the whole point is that it is
NOT era_gate's own output.

Why `--clean` exists as a separate pass: recall and false alarms must be read off the SAME
twelve pictures. A clean twin is a byte copy of the source still, so any difference between
the two directories is exactly one pasted object.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, 'MANIFEST.json')

# ── operator wiring, filled in by hand ───────────────────────────────────────────────
# plant id -> the approved still it goes into and the cutout to paste.
# `still` is a path under output/ ; `run` and `slot` are recorded so the render prompt can be
# found again. `cutout` is None for the four plants the TEST module says this script DRAWS
# (wir_powerline, wir_wirefence, obj_poster, obj_clock).
SOURCES: dict[str, dict] = {
    # 'veh_bicycle': {'run': '<run id>', 'slot': 'S03',
    #                 'still': 'output/scholarly/<run id>/stills/S03.png',
    #                 'cutout': 'capability_tests/fixtures/text_judges/cutouts/bicycle.png'},
}

# plant id -> the checkable nouns that slot's render prompt supports, written by the operator.
SLOT_NOUNS: dict[str, list[str]] = {
    # 'veh_bicycle': ['quay', 'rope', 'barrel', 'sailor', 'hull'],
}

# The sign variants are drawn onto one still, named here.
SIGN_PLATE: dict = {
    # 'run': '<run id>', 'slot': 'S07', 'still': 'output/scholarly/<run id>/stills/S07.png',
    # 'board': [0.22, 0.28, 0.78, 0.52],   # the board rectangle, 0-1 fractions
}

# Absolute paths to the two faces the sign table names. Installed with fonts-dejavu.
FACES = {
    'DejaVuSerif-Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
    'DejaVuSans-Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
}


def _test():
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', '..')))
    from capability_tests.text_judges import PLANTS, SIGNS_TABLE

    return PLANTS, SIGNS_TABLE


def _need(what, why):
    raise SystemExit(f'plant.py: {what} is empty — {why}. Fill it in and run again; nothing was written.')


def write_manifest():
    plants, signs = _test()
    if not SOURCES:
        _need('SOURCES', 'the script cannot guess which approved still each plant belongs in')
    if not SIGN_PLATE:
        _need('SIGN_PLATE', 'the five sign variants are drawn onto one named still')
    out = {
        'built_by': 'capability_tests/fixtures/text_judges/plant.py',
        'plants': [],
        'signs': [],
        'note': 'boxes are 0-1 fractions of the still. Every probe in capability_tests/text_judges.py '
        'scores a flag bbox against the box recorded here, so this file is the key.',
    }
    for p in plants:
        src = SOURCES.get(p['id']) or _need(f'SOURCES[{p["id"]!r}]', 'every plant needs a still')
        nouns = SLOT_NOUNS.get(p['id'])
        if not nouns:
            _need(f'SLOT_NOUNS[{p["id"]!r}]', "prompt_derived is scored against the operator's noun list")
        out['plants'].append(
            {
                'id': p['id'],
                'class': p['class'],
                'what': p['what'],
                'box': list(p['box']),
                'from': p['from'],
                'run': src['run'],
                'slot': src['slot'],
                'still': src['still'],
                'cutout': src.get('cutout'),
                'checkable_nouns': list(nouns),
                'planted': f'planted/{p["id"]}.png',
                'clean': f'clean/{p["id"]}.png',
            }
        )
    for s in signs:
        out['signs'].append(
            {
                'id': s['id'],
                'fault': s['fault'],
                'text': s['text'],
                'face': s['face'],
                'note': s['note'],
                'board': list(SIGN_PLATE['board']),
                'run': SIGN_PLATE['run'],
                'slot': SIGN_PLATE['slot'],
                'still': SIGN_PLATE['still'],
                'path': f'signs/{s["id"]}.png',
            }
        )
    with open(MANIFEST, 'w') as fh:
        json.dump(out, fh, indent=2)
    print(f'wrote {MANIFEST}: {len(out["plants"])} plants, {len(out["signs"])} signs')
    print('verified stays FALSE in the TEST until the operator has read the prompts and checked the boxes')


def _manifest():
    if not os.path.exists(MANIFEST):
        raise SystemExit('plant.py: no MANIFEST.json — run --write-manifest first')
    with open(MANIFEST) as fh:
        return json.load(fh)


def clean():
    m = _manifest()
    os.makedirs(os.path.join(HERE, 'clean'), exist_ok=True)
    for p in m['plants']:
        shutil.copyfile(p['still'], os.path.join(HERE, p['clean']))
    print(f'copied {len(m["plants"])} clean twins — byte copies, so any difference from planted/ is one pasted object')


def planted():
    from PIL import Image, ImageDraw

    m = _manifest()
    os.makedirs(os.path.join(HERE, 'planted'), exist_ok=True)
    for p in m['plants']:
        base = Image.open(p['still']).convert('RGBA')
        w, h = base.size
        x0, y0, x1, y1 = (int(round(f * (w if i % 2 == 0 else h))) for i, f in enumerate(p['box']))
        if p.get('cutout'):
            cut = Image.open(p['cutout']).convert('RGBA').resize((x1 - x0, y1 - y0), Image.LANCZOS)
            base.alpha_composite(cut, (x0, y0))
        else:
            _draw_plant(ImageDraw.Draw(base, 'RGBA'), p['id'], (x0, y0, x1, y1))
        base.convert('RGB').save(os.path.join(HERE, p['planted']))
    print(f'wrote {len(m["plants"])} planted frames — one anachronism each, at the recorded box')


def _draw_plant(d, pid, box):
    """The four plants the TEST module says are DRAWN, not cut out. Deterministic geometry."""
    x0, y0, x1, y1 = box
    if pid == 'wir_powerline':
        for k in range(4):
            y = y0 + (y1 - y0) * (k + 0.5) / 4
            d.line([(x0, y), ((x0 + x1) / 2, y + (y1 - y0) * 0.08), (x1, y)], fill=(24, 24, 28, 235), width=2)
    elif pid == 'wir_wirefence':
        step = max(8, (x1 - x0) // 24)
        for x in range(x0, x1, step):
            d.line([(x, y1), (min(x + step * 2, x1), y0)], fill=(150, 150, 155, 102), width=1)
            d.line([(x, y0), (min(x + step * 2, x1), y1)], fill=(150, 150, 155, 102), width=1)
    elif pid == 'obj_poster':
        d.rectangle(box, fill=(238, 232, 220, 255), outline=(40, 40, 40, 255), width=2)
        for k, col in enumerate(((214, 42, 48, 255), (24, 92, 186, 255), (248, 200, 32, 255))):
            t = y0 + (y1 - y0) * (0.12 + 0.24 * k)
            d.rectangle([x0 + 8, t, x1 - 8, t + (y1 - y0) * 0.18], fill=col)
    elif pid == 'obj_clock':
        d.rectangle(box, fill=(8, 8, 10, 255))
        seg = (x1 - x0) / 6.0
        for k in range(4):
            cx = x0 + seg * (k + 0.6 + (0.4 if k > 1 else 0))
            d.rectangle(
                [cx, y0 + (y1 - y0) * 0.25, cx + seg * 0.5, y0 + (y1 - y0) * 0.75], outline=(228, 24, 24, 255), width=3
            )
        d.rectangle(
            [x0 + seg * 2.75, y0 + (y1 - y0) * 0.42, x0 + seg * 2.9, y0 + (y1 - y0) * 0.58], fill=(228, 24, 24, 255)
        )
    else:
        raise SystemExit(f'plant.py: {pid} has no cutout and no drawing rule')


def signs():
    from PIL import Image, ImageDraw, ImageFont

    m = _manifest()
    os.makedirs(os.path.join(HERE, 'signs'), exist_ok=True)
    for s in m['signs']:
        base = Image.open(s['still']).convert('RGB')
        w, h = base.size
        bx0, by0, bx1, by1 = (int(round(f * (w if i % 2 == 0 else h))) for i, f in enumerate(s['board']))
        d = ImageDraw.Draw(base)
        d.rectangle([bx0, by0, bx1, by1], fill=(46, 36, 24), outline=(22, 16, 10), width=3)
        words = s['text'].split()
        lines = [' '.join(words[:2]), ' '.join(words[2:4]), ' '.join(words[4:])]
        face = FACES[s['face']]
        size = max(10, int((by1 - by0) / (len(lines) * 1.6)))
        font = ImageFont.truetype(face, size)
        for k, line in enumerate(lines):
            tw = d.textlength(line, font=font)
            y = by0 + (by1 - by0) * (0.12 + 0.28 * k)
            d.text(((bx0 + bx1) / 2 - tw / 2, y), line, font=font, fill=(232, 222, 198))
        base.save(os.path.join(HERE, s['path']))
    print(f'wrote {len(m["signs"])} sign variants — one fault each, faces exactly as the table names them')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--write-manifest', action='store_true')
    ap.add_argument('--clean', action='store_true')
    ap.add_argument('--planted', action='store_true')
    ap.add_argument('--signs', action='store_true')
    a = ap.parse_args()
    did = False
    for flag, fn in (('write_manifest', write_manifest), ('clean', clean), ('planted', planted), ('signs', signs)):
        if getattr(a, flag):
            fn()
            did = True
    if not did:
        ap.print_help()


if __name__ == '__main__':
    main()
