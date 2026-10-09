#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_variants.py — operator candidates rendered through the pipeline's own
conform pass (plain Qwen-Image-Edit, angles LoRA off, judged + DINO), so what
you pick was made by the code that will use it.

    python3 scripts/creature_variants.py CID --source IMG --out DIR \\
        --variant "A=Keep the tail exactly as it is." \\
        --variant "B=Add a small tuft of white fur at the tip of the tail." \\
        [--prefix "Make the body a plumper ball shape ..."] [--seeds 2] \\
        [--band side --angle-desc "a true side profile from the right"] \\
        [--identity IMG] [--body-plan "..."] [--label "tail candidates"]

Every variant's instruction is `prefix + " " + text`; with no --variant the
single variant is the pipeline's conform_instruction(body_plan). Body plan,
style hint, negative and identity anchor default to the creature's brief.json /
sheet.json. Writes <out>/variants.json and a labelled <out>/variants_sheet.png
(the best seed of every variant, verdict + DINO under each cell). Pick one and
lock it with scripts/creature_lock.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from zyg_workflows import paths

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)
os.chdir(_CREWS)

DATASET_ROOT = os.environ.get('ZYG_CREATURE_DATASET_ROOT', str(paths.ZYG_LORA_DATASETS / 'creatures'))


def _load(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cid')
    ap.add_argument('--source', required=True, help='image to edit (a cell, an anchor, a reference)')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--variant', action='append', default=[], help='"TAG=instruction" (repeatable)')
    ap.add_argument('--prefix', default='', help='instruction text prepended to every variant')
    ap.add_argument('--seeds', type=int, default=2, help='seeds per variant (best one is shown)')
    ap.add_argument(
        '--band', default='front', choices=('front', 'quarter', 'side', 'back', 'top', 'close', 'wide', 'detail')
    )
    ap.add_argument('--angle-desc', default='a straight-on front view showing the whole body')
    ap.add_argument('--kind', default='body', choices=('body', 'head', 'wide', 'detail'))
    ap.add_argument(
        '--identity', default='', help='identity anchor for the judge strips (default: sheet.json anchors.identity)'
    )
    ap.add_argument('--body-plan', default=None, help='override brief.body_plan for this run')
    ap.add_argument('--label', default='variants')
    ap.add_argument('--seed-base', type=int, default=4400)
    ap.add_argument(
        '--angles-lora',
        type=float,
        default=0.0,
        help='multiple-angles LoRA strength (default 0.0 = a plain in-place edit). '
        'Use 1.0 when the variant is a CAMERA MOVE, e.g. re-deriving the side '
        'lock from the front lock; at 0.0 a creature under-rotates.',
    )
    a = ap.parse_args()

    ds = os.path.join(DATASET_ROOT, a.cid)
    brief = _load(os.path.join(ds, 'brief.json'))
    report = _load(os.path.join(ds, 'contact_sheet', 'sheet.json'))
    body_plan = (a.body_plan if a.body_plan is not None else brief.get('body_plan') or '').strip()
    identity = a.identity or ((report.get('anchors') or {}).get('identity') or {}).get('path') or ''
    if not os.path.isfile(a.source):
        sys.exit(f'source not found: {a.source}')
    if not identity or not os.path.isfile(identity):
        sys.exit('no identity anchor — pass --identity IMG')

    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_workflows import creature_identity as cid
    from zyg_workflows import creature_judge as cj
    from zyg_workflows import creature_sheet_service as css

    variants: list[tuple[str, str]] = []
    for v in a.variant:
        tag, _, text = v.partition('=')
        tag = tag.strip()
        if not tag or not text.strip():
            sys.exit(f'bad --variant {v!r} (want "TAG=instruction")')
        variants.append((tag, f'{a.prefix.strip()} {text.strip()}'.strip()))
    if not variants:
        variants = [
            ('conform', (f'{a.prefix.strip()} ' if a.prefix.strip() else '') + css.conform_instruction(body_plan))
        ]
    os.makedirs(a.out, exist_ok=True)

    def log(m: str) -> None:
        print(f'[{time.strftime("%H:%M:%S")}] {m}'[:220], flush=True)

    log(
        f'{len(variants)} variant(s) x {a.seeds} seed(s) from {os.path.basename(a.source)}; identity={os.path.basename(identity)}'
    )
    log(f'body plan: {body_plan!r}')
    log(f'angles LoRA: {a.angles_lora}' + ('  (camera move)' if a.angles_lora else '  (in-place edit)'))
    t0 = time.time()
    try:
        res = css.conform_variants(
            a.source,
            body_plan,
            a.out,
            identity,
            log,
            variants=variants,
            seeds=a.seeds,
            style_hint=(brief.get('style_hint') or ''),
            angle_desc=a.angle_desc,
            kind=a.kind,
            band=a.band,
            extra_negative=(brief.get('negative') or ''),
            seed_base=a.seed_base,
            angles_scale=a.angles_lora,
        )
    finally:
        cj.shutdown(log_fn=log)
        cid.release()
    cells = []
    for i, (tag, instr) in enumerate(variants):
        r = res.get(tag) or {}
        best = (r.get('candidates') or [{}])[0] if r.get('candidates') else {}
        cells.append(
            {
                'idx': i,
                'id': tag,
                'label': f'{tag}: {instr[len(a.prefix.strip()) :].strip()[:36]}',
                'path': r.get('path'),
                'ok': bool(best.get('ok', False)) if best else False,
                'soft': best.get('soft') or [],
                'reasons': best.get('reasons') or ['render_failed'] if not best else best.get('reasons') or [],
                'dino': best.get('dino'),
                'caption_mode': 'angle',
            }
        )
    sheet = os.path.join(a.out, 'variants_sheet.png')
    css.stitch_sheet(
        cells,
        sheet,
        cols=min(4, max(1, len(cells))),
        cell_px=512,
        title=f'{brief.get("name") or a.cid} — {a.label} ({a.seeds} seed(s) each, best shown)',
    )
    summary = {
        'cid': a.cid,
        'source': a.source,
        'identity': identity,
        'body_plan': body_plan,
        'prefix': a.prefix,
        'seeds': a.seeds,
        'band': a.band,
        'angle_desc': a.angle_desc,
        'variants': {tag: res.get(tag) for tag, _ in variants},
        'sheet': sheet,
        'seconds': round(time.time() - t0, 1),
    }
    with open(os.path.join(a.out, 'variants.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2, default=str)
    print()
    for tag, _instr in variants:
        r = res.get(tag) or {}
        for c in r.get('candidates') or []:
            print(
                f'{tag:>8} {os.path.basename(c["path"]):24} {"PASS" if c.get("ok") else "FLAG"}'
                f'{"*" if c.get("soft") else " "} dino={c.get("dino")} flags={c.get("flags")}'
            )
        if not r.get('candidates'):
            print(f'{tag:>8} — no image')
    print(f'\nsheet: {sheet}\njson : {os.path.join(a.out, "variants.json")}\n{summary["seconds"]}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
