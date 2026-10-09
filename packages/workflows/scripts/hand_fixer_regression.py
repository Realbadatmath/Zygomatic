#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""No-harm regression harness for the HandFixer (qwen inpaint engine).

Reconstructs the documented no-harm regression: run the fixer over the
known-bad frames of run 6278904c (canonical case scene_015.png) plus a
known-good control set from run 59e8d33f and verify the pass never makes a
frame WORSE — post hand score >= pre score and no hand boxes lost. A frame
the fixer declines to touch (file unchanged) passes by definition.

The report distinguishes a genuine 'no-harm PASS' from a VACUOUS run: a down
ComfyUI (or a declining stack) makes no-harm trivially true, so per-frame we
record whether a repaint actually landed (content hash change + the returned
bool) and the aggregate verdict downgrades to 'vacuous' when nothing engaged.

Invocation (agents venv, from the crews dir):

    cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}" && \
        ZYG_USE_COMFYUI=1 ZYG_HAND_FIXER_ENGINE=qwen \
        ../.venv/bin/python scripts/hand_fixer_regression.py [--dry-run]

Exit codes: 0 = no-harm PASS (or --dry-run completed), 1 = harm detected,
2 = precondition failure (ComfyUI/ollama down, fixtures missing),
3 = vacuous run (fixer never engaged a single frame — NOT a pass).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import time

from zyg_workflows import paths

# Env preconditions BEFORE any crews import — hand_qc_service freezes
# ZYG_OLLAMA_HOST / VLM settings at import time; setdefault so an explicit
# operator override in the environment always wins.
os.environ.setdefault('ZYG_USE_COMFYUI', '1')
os.environ.setdefault('ZYG_HAND_FIXER_ENGINE', 'qwen')

_CREWS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS_DIR not in sys.path:
    sys.path.insert(0, _CREWS_DIR)

_BAD_DIR = os.environ.get(
    'ZYG_HANDFIX_REG_BAD_DIR',
    os.path.join(_CREWS_DIR, 'data', 'output', 'clips', '6278904c-a6a5-4174-9a2e-53cba4caa2cd'),
)
_GOOD_DIR = os.environ.get(
    'ZYG_HANDFIX_REG_GOOD_DIR',
    os.path.join(_CREWS_DIR, 'data', 'output', 'clips', '59e8d33f-a277-41be-a165-472301def385'),
)
# Canonical documented case — always included in the bad selection even when
# --limit-bad would slice it away.
_CANONICAL_BAD = os.environ.get('ZYG_HANDFIX_REG_CANONICAL', 'scene_015.png')
_DEFAULT_SCRATCH = os.environ.get('ZYG_HANDFIX_REG_SCRATCH') or str(paths.ZYG_TMP_DIR / 'handfix_regression')
_FIXER_PROMPT = os.environ.get('ZYG_HANDFIX_REG_PROMPT', 'portrait of a person')
_FIXER_SEED = int(os.environ.get('ZYG_HANDFIX_REG_SEED', '42'))
_SCORE_EPS = 1e-9


def _log(msg: str) -> None:
    print(f'[handfix-reg] {msg}', flush=True)


def _comfy_url() -> str:
    host = os.environ.get('ZYG_COMFY_HOST', '127.0.0.1')
    port = os.environ.get('ZYG_COMFY_PORT', '8188')
    return f'http://{host}:{port}'


def _ollama_url() -> str:
    return os.environ.get('ZYG_OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')


def _http_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        import requests

        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return True, f'HTTP {r.status_code}'
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'


def _preflight() -> dict:
    comfy_ok, comfy_why = _http_ok(f'{_comfy_url()}/system_stats')
    ollama_ok, ollama_why = _http_ok(f'{_ollama_url()}/api/tags')
    return {
        'comfy_url': _comfy_url(),
        'comfy_ok': comfy_ok,
        'comfy_detail': comfy_why,
        'ollama_url': _ollama_url(),
        'ollama_ok': ollama_ok,
        'ollama_detail': ollama_why,
        'engine': os.environ.get('ZYG_HAND_FIXER_ENGINE', ''),
        'use_comfyui': os.environ.get('ZYG_USE_COMFYUI', ''),
    }


def _stack_readiness() -> dict:
    """Fixer stack probes — pure file/HTTP checks, no GPU work."""
    out: dict = {}
    try:
        from zyg_workflows import comfy_generation_service as _cgs

        out['hand_fixer_enabled'] = bool(_cgs.hand_fixer_enabled())
        out['qwen_inpaint_ready'] = bool(_cgs.has_qwen_hand_inpaint())
        out['hand_fixer_stack_ready'] = bool(_cgs.hand_fixer_stack_ready())
    except Exception as exc:
        out['error'] = f'{type(exc).__name__}: {exc}'
    return out


def _collect_fixtures(
    dir_path: str, limit: int | None, force_include: str | None = None
) -> tuple[list[str], list[str]]:
    """(all scene frames, selected frames). limit<=0 or None means all."""
    files = sorted(glob.glob(os.path.join(dir_path, 'scene_*.png')))
    if limit is None or limit <= 0 or limit >= len(files):
        selected = list(files)
    else:
        selected = files[:limit]
    if force_include:
        fp = os.path.join(dir_path, force_include)
        if fp in files and fp not in selected:
            selected.append(fp)
    return files, selected


def _sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _run_frame(fixture_label: str, src: str, scratch: str) -> dict:
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import hand_qc_service as _hqs

    rec: dict = {'fixture': fixture_label, 'source': src, 'file': os.path.basename(src)}
    dst_dir = os.path.join(scratch, fixture_label)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    # The fixer OVERWRITES its input — always operate on a scratch copy.
    shutil.copy2(src, dst)
    rec['work_copy'] = dst

    pre_score, pre_issues = _hqs.hand_quality(dst)
    rec['pre_score'] = pre_score
    rec['pre_issues'] = pre_issues
    try:
        rec['pre_boxes'] = len(_hqs.detect_hand_boxes(dst) or [])
    except Exception as exc:
        # fail-closed detector: unavailability is 'unknown', never a fail
        rec['pre_boxes'] = None
        rec['pre_boxes_error'] = f'{type(exc).__name__}: {exc}'

    st0 = os.stat(dst)
    hash0 = _sha256(dst)
    t0 = time.time()
    try:
        applied = bool(
            _cgs.apply_hand_fixer_pass(
                dst,
                _FIXER_PROMPT,
                seed=_FIXER_SEED,
                log_fn=_log,
            )
        )
    except Exception as exc:
        # apply_hand_fixer_pass is exception-safe by contract; belt-and-braces
        applied = False
        rec['fixer_error'] = f'{type(exc).__name__}: {exc}'
    rec['fixer_returned'] = applied
    rec['fixer_seconds'] = round(time.time() - t0, 1)

    try:
        st1 = os.stat(dst)
        mtime_changed = st1.st_mtime_ns != st0.st_mtime_ns or st1.st_size != st0.st_size
    except OSError:
        mtime_changed = True
    hash1 = _sha256(dst)
    content_changed = bool(hash0 and hash1 and hash0 != hash1)
    rec['mtime_or_size_changed'] = mtime_changed
    rec['content_changed'] = content_changed
    # 'engaged' = a repaint actually landed in the file OR the fixer claims it
    # applied — either alone is suspicious, both False means declined/vacuous.
    rec['engaged'] = bool(content_changed or applied)

    post_score, post_issues = _hqs.hand_quality(dst)
    rec['post_score'] = post_score
    rec['post_issues'] = post_issues
    try:
        rec['post_boxes'] = len(_hqs.detect_hand_boxes(dst) or [])
    except Exception as exc:
        rec['post_boxes'] = None
        rec['post_boxes_error'] = f'{type(exc).__name__}: {exc}'

    pre_b, post_b = rec['pre_boxes'], rec['post_boxes']
    if not content_changed:
        rec['verdict'] = 'pass_declined'  # unchanged file = pass by definition
    elif pre_score is None or post_score is None:
        rec['verdict'] = 'unknown'  # recorded, not a fail (scoring unavailable)
    elif post_score < pre_score - _SCORE_EPS:
        rec['verdict'] = 'fail_score'
    elif pre_b is not None and post_b is not None and post_b < pre_b:
        rec['verdict'] = 'fail_boxes'
    elif pre_b is None or post_b is None:
        rec['verdict'] = 'unknown_boxes'
    else:
        rec['verdict'] = 'pass'
    _log(
        f'{fixture_label}/{rec["file"]}: {rec["verdict"]} '
        f'(score {pre_score}->{post_score}, boxes {pre_b}->{post_b}, '
        f'engaged={rec["engaged"]})',
    )
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        '--limit-bad', type=int, default=0, help='max known-bad frames (0 = all; canonical case always included)'
    )
    ap.add_argument('--limit-good', type=int, default=6, help='max known-good control frames (0 = all)')
    ap.add_argument(
        '--scratch', default=_DEFAULT_SCRATCH, help='scratch dir for work copies (fixer overwrites its input)'
    )
    ap.add_argument('--report', default='', help='report JSON path (default <scratch>/handfix_regression_report.json)')
    ap.add_argument('--dry-run', action='store_true', help='list fixtures + env checks, no GPU work')
    args = ap.parse_args()

    report_path = args.report or os.path.join(args.scratch, 'handfix_regression_report.json')

    missing = [d for d in (_BAD_DIR, _GOOD_DIR) if not os.path.isdir(d)]
    if missing:
        for d in missing:
            _log(f'FIXTURE DIR MISSING: {d}')
        return 2

    bad_all, bad_sel = _collect_fixtures(_BAD_DIR, args.limit_bad, force_include=_CANONICAL_BAD)
    good_all, good_sel = _collect_fixtures(_GOOD_DIR, args.limit_good)
    _log(f'known-bad  {_BAD_DIR}: {len(bad_all)} frames, {len(bad_sel)} selected')
    _log(f'known-good {_GOOD_DIR}: {len(good_all)} frames, {len(good_sel)} selected')
    canonical_present = os.path.join(_BAD_DIR, _CANONICAL_BAD) in bad_sel
    _log(f'canonical case {_CANONICAL_BAD}: {"selected" if canonical_present else "MISSING from selection"}')
    if not bad_all and not good_all:
        _log('no scene_*.png fixtures found — aborting')
        return 2

    pre = _preflight()
    _log(f'ComfyUI {pre["comfy_url"]}: {"UP" if pre["comfy_ok"] else "DOWN — " + pre["comfy_detail"]}')
    _log(f'ollama  {pre["ollama_url"]}: {"UP" if pre["ollama_ok"] else "DOWN — " + pre["ollama_detail"]}')

    if args.dry_run:
        stack = _stack_readiness()
        _log(f'stack readiness: {json.dumps(stack)}')
        for label, sel in (('bad', bad_sel), ('good', good_sel)):
            for p in sel:
                _log(f'  fixture[{label}] {os.path.basename(p)}')
        _log(
            f'DRY RUN complete — would run {len(bad_sel) + len(good_sel)} frames; '
            f'scratch={args.scratch}, report={report_path}'
        )
        return 0

    # A down ComfyUI makes the no-harm pass vacuously succeed (fixer refuses
    # every frame); a down ollama makes every score None (all-unknown). Both
    # are FAIL-LOUD preconditions, not soft degradations.
    if not pre['comfy_ok']:
        _log(
            f'PRECONDITION FAILED: ComfyUI unreachable ({pre["comfy_detail"]}) '
            f'— a no-harm result without a live fixer is vacuous. Aborting.'
        )
        return 2
    if not pre['ollama_ok']:
        _log(
            f'PRECONDITION FAILED: ollama unreachable ({pre["ollama_detail"]}) '
            f'— hand scoring would be unavailable on every frame. Aborting.'
        )
        return 2

    stack = _stack_readiness()
    _log(f'stack readiness: {json.dumps(stack)}')

    os.makedirs(args.scratch, exist_ok=True)
    records: list[dict] = []
    for label, sel in (('bad', bad_sel), ('good', good_sel)):
        for src in sel:
            records.append(_run_frame(label, src, args.scratch))

    fails = [r for r in records if str(r.get('verdict', '')).startswith('fail')]
    unknowns = [r for r in records if str(r.get('verdict', '')).startswith('unknown')]
    engaged = [r for r in records if r.get('engaged')]
    declined = [r for r in records if r.get('verdict') == 'pass_declined']
    no_harm = not fails
    vacuous = not engaged
    if fails:
        status = 'FAIL — harm detected'
    elif vacuous:
        status = 'VACUOUS — fixer never engaged (NOT a no-harm pass)'
    else:
        status = 'NO-HARM PASS'

    report = {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'invocation': ' '.join(sys.argv),
        'preflight': pre,
        'stack': stack,
        'fixer': {'prompt': _FIXER_PROMPT, 'seed': _FIXER_SEED, 'engine': os.environ.get('ZYG_HAND_FIXER_ENGINE', '')},
        'fixtures': {
            'bad': {
                'dir': _BAD_DIR,
                'total': len(bad_all),
                'selected': len(bad_sel),
                'canonical': _CANONICAL_BAD,
                'canonical_selected': canonical_present,
            },
            'good': {'dir': _GOOD_DIR, 'total': len(good_all), 'selected': len(good_sel)},
        },
        'frames': records,
        'summary': {
            'frames': len(records),
            'fails': len(fails),
            'unknowns': len(unknowns),
            'engaged': len(engaged),
            'declined': len(declined),
            'no_harm': no_harm,
            'vacuous': vacuous,
        },
        'status': status,
    }
    try:
        os.makedirs(os.path.dirname(report_path) or '.', exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, indent=2)
        _log(f'report written: {report_path}')
    except Exception as exc:
        _log(f'REPORT WRITE FAILED ({exc!r}) — dumping to stdout')
        print(json.dumps(report, indent=2))

    _log(
        f'RESULT: {status} — {len(records)} frames, {len(fails)} fail, '
        f'{len(unknowns)} unknown, {len(engaged)} engaged, {len(declined)} declined'
    )
    if fails:
        for r in fails:
            _log(
                f'  HARM: {r["fixture"]}/{r["file"]} {r["verdict"]} '
                f'score {r.get("pre_score")}->{r.get("post_score")} '
                f'boxes {r.get("pre_boxes")}->{r.get("post_boxes")}'
            )
        return 1
    if vacuous:
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
