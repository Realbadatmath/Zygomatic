#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
run_creature_sheet.py — start a Creature Creation run through the GUI API and
follow it to the review gate (or to completion).

    .venv/bin/python scripts/run_creature_sheet.py --ref "/path/ref.png" [--ref more.png] \\
        --name "Zygo AI Pufferball" [--angles standard|compact] [--no-review]
    .venv/bin/python scripts/run_creature_sheet.py --scratch "a teal furry pufferball creature with amber eyes"
    .venv/bin/python scripts/run_creature_sheet.py --approve <creature_id>     # resume: captions → LoRA → previews
    .venv/bin/python scripts/run_creature_sheet.py --reject  <creature_id> [--reason "..."]
    .venv/bin/python scripts/run_creature_sheet.py --status  <creature_id>

Goes through POST /api/internal/pipeline/start exactly like the public page
does, so the kanban board lights up and state persists under
data/runtime/creature_gen_<id>.json. Authenticates with ZERO_PUBLIC_TOKEN from
<repo>/.env (the same secret zero_public_server uses).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.environ.get('ZYG_GUI_URL', 'http://127.0.0.1:5000')


def _token() -> str:
    t = os.environ.get('ZERO_PUBLIC_TOKEN', '')
    if t:
        return t
    for envf in (os.path.join(os.path.dirname(os.path.dirname(_CREWS)), '.env'), os.path.join(_CREWS, '.env')):
        try:
            for line in open(envf, encoding='utf-8'):
                if line.startswith('ZERO_PUBLIC_TOKEN='):
                    return line.split('=', 1)[1].strip().strip('"\'')
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return ''


def _hdr() -> dict:
    return {'X-Zero-Public-Token': _token(), 'Content-Type': 'application/json'}


def status(cid: str) -> dict:
    r = requests.get(f'{GUI}/api/internal/pipeline/status/{cid}', headers=_hdr(), timeout=20)
    return r.json() if r.status_code == 200 else {'status': f'http_{r.status_code}', 'error': r.text[:200]}


def follow(cid: str, stop_at_review: bool = True) -> dict:
    last = None
    t0 = time.time()
    down = 0
    while True:
        try:
            st = status(cid)
            down = 0
        except requests.exceptions.ConnectionError:
            down += 1
            if down == 1:
                print(f'[{time.time() - t0:6.0f}s] GUI unreachable — waiting for it to come back', flush=True)
            if down > 60:
                return {'status': 'gui_unreachable'}
            time.sleep(5)
            continue
        key = (st.get('status'), st.get('current_stage'))
        if key != last:
            print(f'[{time.time() - t0:6.0f}s] {st.get("status")}  {st.get("current_stage") or ""}', flush=True)
            last = key
        if st.get('status') in ('completed', 'failed', 'stopped', 'rejected', 'interrupted'):
            return st
        if st.get('status') == 'awaiting_review' and stop_at_review:
            return st
        if st.get('status', '').startswith('http_'):
            return st
        time.sleep(8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', action='append', default=[], help='reference image (repeatable)')
    ap.add_argument('--scratch', default='', help='text brief — from-scratch mode')
    ap.add_argument('--name', default='', help='creature name / directive')
    ap.add_argument('--angles', default='standard', choices=('standard', 'compact'))
    ap.add_argument('--no-review', action='store_true', help='skip the review gate and train immediately')
    ap.add_argument('--resume', default='', help='resume an interrupted/failed run (sheet checkpoints reused)')
    ap.add_argument('--phase', default='full', choices=('full', 'sheet'))
    ap.add_argument('--approve', default='')
    ap.add_argument('--reject', default='')
    ap.add_argument('--reason', default='')
    ap.add_argument('--status', default='')
    ap.add_argument('--no-follow', action='store_true')
    a = ap.parse_args()

    if a.status:
        print(json.dumps(status(a.status), indent=1, default=str)[:4000])
        return 0
    if a.reject:
        r = requests.post(
            f'{GUI}/api/internal/creature/{a.reject}/reject', headers=_hdr(), json={'reason': a.reason}, timeout=20
        )
        print(r.status_code, r.text[:300])
        return 0 if r.status_code == 200 else 1
    if a.resume:
        r = requests.post(
            f'{GUI}/api/internal/creature/{a.resume}/resume', headers=_hdr(), json={'phase': a.phase}, timeout=20
        )
        print(r.status_code, r.text[:300])
        if r.status_code != 200:
            return 1
        if not a.no_follow:
            st = follow(a.resume, stop_at_review=True)
            print(
                json.dumps(
                    {k: st.get(k) for k in ('status', 'current_stage', 'sheet_path', 'sheet_report', 'error')},
                    indent=1,
                    default=str,
                )
            )
            if st.get('status') == 'awaiting_review':
                print(f'\nSHEET READY FOR REVIEW: {st.get("sheet_path")}')
        return 0
    if a.approve:
        r = requests.post(f'{GUI}/api/internal/creature/{a.approve}/approve', headers=_hdr(), timeout=20)
        print(r.status_code, r.text[:300])
        if r.status_code != 200:
            return 1
        if not a.no_follow:
            st = follow(a.approve, stop_at_review=False)
            print(
                json.dumps(
                    {k: st.get(k) for k in ('status', 'lora_path', 'preview_report', 'error')}, indent=1, default=str
                )
            )
        return 0

    refs = [os.path.abspath(p) for p in a.ref]
    for p in refs:
        if not os.path.isfile(p):
            print(f'reference not found: {p}')
            return 2
    if not refs and not a.scratch:
        print('give --ref IMAGE (reference mode) or --scratch "brief" (from-scratch mode)')
        return 2
    payload = {
        'pipeline_type': 'creature',
        'directive': a.name or a.scratch,
        'image_paths': refs,
        'model_family': 'klein',
        'creature_options': {
            'source': 'scratch' if a.scratch and not refs else 'reference',
            'angles': a.angles,
            'review_gate': not a.no_review,
        },
    }
    r = requests.post(f'{GUI}/api/internal/pipeline/start', headers=_hdr(), json=payload, timeout=30)
    if r.status_code != 200:
        print(f'start failed HTTP {r.status_code}: {r.text[:300]}')
        return 1
    info = r.json()
    cid = info.get('job_id') or info.get('pipeline_id')
    print(
        f'started creature {cid} ({payload["creature_options"]["source"]}, {a.angles}, review_gate={not a.no_review})'
    )
    if a.no_follow:
        return 0
    st = follow(cid, stop_at_review=True)
    print(
        json.dumps(
            {k: st.get(k) for k in ('status', 'current_stage', 'sheet_path', 'sheet_report', 'error')},
            indent=1,
            default=str,
        )
    )
    if st.get('status') == 'awaiting_review':
        print(
            f'\nSHEET READY FOR REVIEW: {st.get("sheet_path")}\n'
            f'  approve: scripts/run_creature_sheet.py --approve {cid}\n'
            f'  reject : scripts/run_creature_sheet.py --reject {cid}'
        )
    return 0 if st.get('status') in ('awaiting_review', 'completed') else 1


if __name__ == '__main__':
    sys.exit(main())
