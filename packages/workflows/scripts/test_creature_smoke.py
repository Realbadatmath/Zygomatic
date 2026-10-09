#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
test_creature_smoke.py — creature sheet workflow smoke tests.

    scripts/run_tests.sh                                   # unit layer (fast, no GPU)
    .venv/bin/python scripts/test_creature_smoke.py        # wiring: GUI endpoints, kanban, registry
    .venv/bin/python scripts/test_creature_smoke.py --gpu REF.png [--scratch "brief"]
                                                           # real 2-cell mini sheet through
                                                           # ComfyUI + Qwen3-VL judge + DINOv2 (~4-6 min)

The --gpu layer is the same code path the production run takes (build_sheet with
preset=compact trimmed to two cells) so a wiring fault surfaces in minutes, not
after a 16-cell render. Nothing here trains a LoRA.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)
os.chdir(_CREWS)

GUI = os.environ.get('ZYG_GUI_URL', 'http://127.0.0.1:5000')
TOKEN = os.environ.get('ZERO_PUBLIC_TOKEN', '')


def _hdr():
    return (
        {'X-Zero-Public-Token': TOKEN, 'Content-Type': 'application/json'}
        if TOKEN
        else {'Content-Type': 'application/json'}
    )


def _load_token():
    global TOKEN
    if TOKEN:
        return
    # crewai_web_gui loads <repo>/.env (two levels up); crews/.env is empty
    for envf in (os.path.join(os.path.dirname(os.path.dirname(_CREWS)), '.env'), os.path.join(_CREWS, '.env')):
        try:
            for line in open(envf, encoding='utf-8'):
                if line.startswith('ZERO_PUBLIC_TOKEN='):
                    TOKEN = line.split('=', 1)[1].strip().strip('"\'')
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  — {detail}' if detail else ''))
    return bool(ok)


def wiring() -> bool:
    import requests

    ok = True
    r = subprocess.run(
        [os.path.join(_CREWS, '.venv-test', 'bin', 'python'), '-m', 'pytest', 'tests/test_creature_sheet.py', '-q'],
        capture_output=True,
        text=True,
    )
    ok &= check('unit tests', r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-300:])
    try:
        ks = requests.get(f'{GUI}/api/kanban/status', timeout=10)
        ok &= check('/api/kanban/status reachable', ks.status_code == 200, f'template={ks.json().get("template")}')
    except Exception as exc:
        ok &= check('/api/kanban/status reachable', False, str(exc)[:120])
    try:
        cl = requests.get(f'{GUI}/api/internal/creature/list', headers=_hdr(), timeout=10)
        ok &= check('/api/internal/creature/list', cl.status_code == 200, f'{cl.json().get("count")} creature(s)')
    except Exception as exc:
        ok &= check('/api/internal/creature/list', False, str(exc)[:120])
    try:
        rj = requests.post(f'{GUI}/api/internal/creature/zzzzzzzzzzzz/approve', headers=_hdr(), timeout=10)
        ok &= check('approve route mounted (400 on bad id)', rj.status_code == 400, f'HTTP {rj.status_code}')
        rj = requests.post(f'{GUI}/api/internal/creature/000000000000/reject', headers=_hdr(), timeout=10)
        ok &= check('reject route mounted (404 unknown id)', rj.status_code == 404, f'HTTP {rj.status_code}')
    except Exception as exc:
        ok &= check('review routes', False, str(exc)[:120])
    try:
        kb = requests.get('http://127.0.0.1:8899/kanban_assets/kanban_main.js?v=16', timeout=10).text
        ok &= check('kanban serves new creature cards', "prompt: 'Sheet Review'" in kb)
    except Exception as exc:
        ok &= check('kanban serves new creature cards', False, str(exc)[:120])
    r = subprocess.run(
        [sys.executable, os.path.join(_CREWS, 'scripts', 'creature_deps_check.py')], capture_output=True, text=True
    )
    ok &= check('dependency check', r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout else '')
    return ok


def gpu(ref: str | None, scratch: str | None) -> bool:
    from zyg_workflows import creature_judge as cj
    from zyg_workflows import creature_sheet_service as css
    from zyg_workflows import creature_training_service as cts

    css_plan = css.angle_plan
    two = [a for a in css.ANGLES if a['id'] in ('front_full', 'q45_left')]
    css.angle_plan = lambda preset='standard': two  # 2-cell mini sheet
    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    ds = tempfile.mkdtemp(prefix='creature_smoke_', dir=str(paths.ZYG_LORA_DATASETS / 'creatures'))
    logs = []

    def log(m):
        logs.append(m)
        print('   ', m[:160], flush=True)

    t0 = time.time()
    ok = True
    try:
        if scratch:
            brief = cts._generate_creature_brief(scratch, log)
            src, refs = 'scratch', []
        else:
            brief = cts._generate_creature_brief('smoke creature', log, reference_paths=[ref])
            src, refs = 'reference', [ref]
        ok &= check(
            'brief generated',
            bool(brief.get('description')),
            f'{brief.get("brief_source")}: {brief.get("name")} / {brief.get("species")}',
        )
        rep = css.build_sheet(ds, brief, source=src, reference_paths=refs, preset='compact', log_fn=log)
        ok &= check('sheet built', os.path.isfile(rep['sheet_path']), rep['sheet_path'])
        ok &= check('2 cells rendered', rep['cell_count'] == 2 and all(c.get('path') for c in rep['cells']))
        judged = rep.get('judged_any')
        ok &= check(
            'VLM judge ran',
            bool(judged),
            'JUDGE OFFLINE' if not judged else f'tier={rep["cells"][0].get("judge_tier")}',
        )
        # a judge that "ran" but errored on every question looks like a wall of
        # flags — count the worker's own error records, not just the flags
        errs = [v for c in rep['cells'] for v in (c.get('verdicts') or []) if v.get('error')]
        answered = [v for c in rep['cells'] for v in (c.get('verdicts') or []) if v.get('answer') in ('yes', 'no')]
        ok &= check(
            'judge answered its questions',
            bool(answered) and not errs,
            f'{len(answered)} answered, {len(errs)} errored' + (f' — first: {errs[0].get("error")}' if errs else ''),
        )
        d = [c.get('dino') for c in rep['cells']]
        ok &= check('DINO measured', all(isinstance(x, (int, float)) for x in d), f'{d}')
        ok &= check('anchor cell passes', rep['cells'][0]['ok'], ','.join(rep['cells'][0].get('reasons') or []))
        print(f'    report: {css.report_path(ds)}')
    except Exception as exc:
        import traceback

        traceback.print_exc()
        ok = check('gpu smoke', False, str(exc)[:200])
    finally:
        css.angle_plan = css_plan
        cj.shutdown()
    print(f'    {time.time() - t0:.0f}s')
    return ok


if __name__ == '__main__':
    _load_token()
    args = sys.argv[1:]
    if '--gpu' in args:
        i = args.index('--gpu')
        ref = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith('--') else None
        sc = args[args.index('--scratch') + 1] if '--scratch' in args else None
        sys.exit(0 if gpu(ref, sc) else 1)
    sys.exit(0 if wiring() else 1)
