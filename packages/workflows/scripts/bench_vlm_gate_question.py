#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bench anatomy-gate question wordings against the production VLM judge.

    python3 scripts/bench_vlm_gate_question.py <frames_dir> [--truth 1,7,9] [--model moondream]

frames_dir : directory of frames named slot_NNN.jpg (or any *.jpg; sorted order = slot)
--truth    : 0-based slots a human/panel has CONFIRMED carry a structural anatomy
             failure (wrong finger count, fused hands, melted face, limb ownership)
--model    : ollama model tag (default: moondream, the production anatomy judge)

Why this exists (2026-08-24). A rewrite of the anatomy question — longer, with an
explicit "strong expressions are NOT defects" clause — looked better and shipped
0/9 recall on a real episode: moondream echoed "Say no to those." or answered "0",
9 of 41 checks came back unreadable (prior episodes: 2/52). Measured on 40 frames:

    original                              2/40 unreadable   4/9 caught   2 false
    original minus "screaming" (shipped)  1/40              6/9          8 false
    long "these are NOT defects" version  9/40              0/9
    "Answer yes or no. Does ..."         40/40 empty replies
    any wording naming hands/fingers      yes on 26-35 of 40 frames
    Qwen3-VL-8B, same frames              0/9  (VLMs do not count fingers)

moondream only parses "Say yes if X, otherwise say no" as ONE sentence. Every
extra clause degrades it. Do not edit the gate question without running this.
The ask/parse code below is a verbatim copy of production _vlm_ask/_vlm_verdict.
"""

import argparse
import base64
import glob
import json
import os
import re
import sys
import time
import urllib.request

QUESTIONS = {
    'ORIGINAL': (
        'Say yes if this image contains grotesquely distorted or screaming faces, '
        'melted facial features, or deformed anatomy, otherwise say no.'
    ),
    'SHIPPED': (
        'Say yes if this image contains grotesquely distorted faces, melted facial '
        'features, or deformed anatomy, otherwise say no.'
    ),
    'LONG_NOT': (
        'Say yes if this image contains melted or smeared facial features, faces with '
        'missing or duplicated features, hands with the wrong number of fingers, fused or '
        'duplicated limbs, or limbs attached at impossible angles. Strong facial '
        'expressions — shouting, crying, fear, pain, anger — are NOT defects, and neither '
        'are dirt, injuries or dramatic lighting. Say no to those. Otherwise say no.'
    ),
    'ASK_FORM': (
        'Answer yes or no. Does this image contain melted faces, hands with the wrong '
        'number of fingers, fused limbs, or body parts joined at impossible angles?'
    ),
}


def ask(model, question, path):
    b64 = base64.b64encode(open(path, 'rb').read()).decode()
    payload = json.dumps(
        {
            'model': model,
            'prompt': question,
            'images': [b64],
            'stream': False,
            'options': {'temperature': 0.0, 'num_predict': 30},
        }
    ).encode()
    req = urllib.request.Request(
        'http://localhost:11434/api/generate', data=payload, headers={'Content-Type': 'application/json'}, method='POST'
    )
    # The URL is the literal above: http, Ollama on loopback, so there is no scheme to audit.
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310  literal loopback http:// URL
        return json.loads(r.read()).get('response', '')


def verdict(raw):
    t = (raw or '').strip().lower()
    if not t:
        return None
    hy = re.search(r'\byes\b', t) is not None
    hn = re.search(r'\bno\b|\bnot\b|\bnone\b', t) is not None
    if hy and not hn:
        return True
    if hn and not hy:
        return False
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames_dir')
    ap.add_argument('--truth', default='', help='comma-separated 0-based slots with confirmed anatomy failures')
    ap.add_argument('--model', default='moondream')
    ap.add_argument('--extra', action='append', default=[], help='NAME=question to bench in addition')
    a = ap.parse_args()
    frames = sorted(glob.glob(os.path.join(a.frames_dir, '*.jpg')))
    if not frames:
        sys.exit(f'no *.jpg in {a.frames_dir}')
    truth = {int(x) for x in a.truth.split(',') if x.strip()}
    qs = dict(QUESTIONS)
    for e in a.extra:
        k, _, q = e.partition('=')
        qs[k] = q
    print(f'{len(frames)} frames | model={a.model} | truth slots={sorted(truth) or "none given"}\n')
    for key, q in qs.items():
        t0 = time.time()
        rows = [(i, verdict(r := ask(a.model, q, p)), r.strip()[:60]) for i, p in enumerate(frames)]
        n_none = sum(1 for _, v, _ in rows if v is None)
        yes = [i for i, v, _ in rows if v is True]
        tp = len([i for i in yes if i in truth])
        fp = len([i for i in yes if i not in truth])
        print(
            f'{key:9s} | unreadable {n_none:2d}/{len(rows)} | yes {len(yes):2d}'
            + (f' | caught {tp}/{len(truth)} | false-yes {fp}' if truth else '')
            + f' | {time.time() - t0:.0f}s'
        )
        for i, v, raw in rows:
            if v is None or v is True:
                print(f'     slot {i:3d} {"T" if i in truth else " "} -> {v!s:5s} {raw!r}')
        print()


if __name__ == '__main__':
    main()
