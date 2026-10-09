# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""watch_active_run — intervention on a LIVE render (advisory only).

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os
import re
import time
import logging as _zyg_logging

from zyg_workflows.self_improve.base import _mklog, _read_json, _write_json

_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')


# ══════════════════════════════════════════════════════════════════════════════
# 14.  watch_active_run — intervention on a LIVE render (advisory only)
# ══════════════════════════════════════════════════════════════════════════════


def read_progress(run_dir):
    """Parse comfy_preview_watcher's progress.txt (`[HH:MM:SS] step N/M`).

    Returns {'ok','step','total','frac','last_line','age_s','stalled'}."""
    p = os.path.join(run_dir, 'progress.txt')
    out = {'ok': False, 'path': p}
    try:
        if not os.path.isfile(p):
            out['reason'] = 'no progress.txt'
            return out
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            tail = f.read()[-4000:]
        lines = [l for l in tail.splitlines() if l.strip()]
        out['last_line'] = lines[-1] if lines else ''
        step = total = None
        for l in reversed(lines):
            m = re.search(r'step\s+(\d+)\s*/\s*(\d+)', l)
            if m:
                step, total = int(m.group(1)), int(m.group(2))
                break
        out.update(
            {
                'step': step,
                'total': total,
                'frac': round(step / total, 3) if step and total else None,
                'age_s': round(time.time() - os.path.getmtime(p), 1),
                'done': any('execution_success' in l or 'watcher done' in l for l in lines[-4:]),
            }
        )
        out['stalled'] = bool(out['age_s'] and out['age_s'] > 600 and not out['done'])
        out['ok'] = True
    except Exception as e:
        out['error'] = str(e)[:200]
    return out


def read_preview_judge(run_dir):
    """PREVIEW_ALERT + the last preview_judge.jsonl ticks (written by preview_judge.py)."""
    out = {'alert': None, 'ticks': [], 'criticals': [], 'streak': 0}
    a = os.path.join(run_dir, 'PREVIEW_ALERT')
    if os.path.isfile(a):
        out['alert'] = _read_json(a, {'raw': 'unparseable'})
    j = os.path.join(run_dir, 'preview_judge.jsonl')
    try:
        if os.path.isfile(j):
            with open(j, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.read().splitlines()[-40:]
            for l in lines:
                try:
                    out['ticks'].append(json.loads(l))
                except ValueError as _exc:
                    _zyg_log.debug('tick line is not json, skipped: %s', _exc)
                    continue
            streak = 0
            for t in reversed(out['ticks']):
                if t.get('skipped'):
                    continue
                if t.get('criticals'):
                    streak += 1
                else:
                    break
            out['streak'] = streak
            out['criticals'] = sorted({c for t in out['ticks'] for c in (t.get('criticals') or [])})
    except Exception as e:
        out['error'] = str(e)[:200]
    return out


def watch_active_run(run_dir, poll_s=60, on_alert=None, max_minutes=240, alert_streak=2, once=False, log_fn=None):
    """Poll a LIVE render and return a structured ABORT RECOMMENDATION.

    Sources, in order of authority:
      1. <run_dir>/PREVIEW_ALERT — preview_judge already saw a critical streak.
      2. preview_judge.jsonl — an unwritten but forming critical streak.
      3. progress.txt — the sampler stalled (no tqdm movement for > 10 min).

    THIS FUNCTION DOES NOT KILL ANYTHING.  It returns
        {'ok','recommend': 'abort'|'watch'|'continue', 'reason', 'evidence',
         'confidence', 'what_to_do', 'run_dir', 'elapsed_s'}
    and logs it loudly.  Terminating a ~90-minute uninterruptible render on the
    word of a VLM squinting at a partially-denoised TAESD preview is the
    operator's decision, never the loop's — blur is the worst-documented VLM
    corruption class and a false positive destroys unrecoverable progress.
    `on_alert(rec)` is called once when the recommendation first becomes 'abort'.

    once=True does a single poll (what the CLI and tests use)."""
    log = _mklog(log_fn)
    run_dir = os.path.abspath(run_dir)
    t0 = time.time()
    fired = False
    rec = {'ok': False, 'run_dir': run_dir, 'recommend': 'continue'}
    while True:
        try:
            pj = read_preview_judge(run_dir)
            pr = read_progress(run_dir)
            rec = {
                'ok': True,
                'run_dir': run_dir,
                'when': time.strftime('%Y-%m-%d %H:%M:%S'),
                'elapsed_s': round(time.time() - t0, 1),
                'recommend': 'continue',
                'reason': 'no adverse signal',
                'confidence': 'low',
                'evidence': {
                    'progress': pr,
                    'preview_judge_streak': pj['streak'],
                    'criticals': pj['criticals'],
                    'alert': pj['alert'],
                },
                'what_to_do': 'let it run',
            }
            if pj['alert']:
                rec.update(
                    {
                        'recommend': 'abort',
                        'confidence': 'medium',
                        'reason': f'PREVIEW_ALERT present: {pj["alert"].get("criticals", pj["criticals"])}',
                        'what_to_do': (
                            'OPERATOR DECISION: the preview judge saw a '
                            'critical streak. Inspect '
                            f'{pj["alert"].get("frame")} before killing — '
                            'previews are partially denoised and the judge is '
                            'weak on blur. self_improve will not stop the '
                            'render.'
                        ),
                    }
                )
            elif pj['streak'] >= alert_streak:
                rec.update(
                    {
                        'recommend': 'abort',
                        'confidence': 'low',
                        'reason': f'{pj["streak"]} consecutive critical preview ticks '
                        f'({pj["criticals"]}) — alert file not yet written',
                        'what_to_do': 'OPERATOR DECISION: confirm on the latest preview.',
                    }
                )
            elif pj['streak'] == 1:
                rec.update(
                    {
                        'recommend': 'watch',
                        'confidence': 'low',
                        'reason': f'one critical preview tick ({pj["criticals"]}) '
                        f'— one bad blurry tick is noise, not evidence',
                    }
                )
            elif pr.get('stalled'):
                rec.update(
                    {
                        'recommend': 'watch',
                        'confidence': 'medium',
                        'reason': f'progress.txt has not moved for {pr["age_s"]}s (last: {pr.get("last_line")})',
                        'what_to_do': 'check ComfyUI is alive; do not kill on this alone',
                    }
                )
            elif pr.get('done'):
                rec.update(
                    {
                        'recommend': 'continue',
                        'reason': 'render finished',
                        'what_to_do': 'run `self_improve.py diagnose` on it',
                    }
                )

            # There is nothing to abort once the sampler has finished: a critical
            # preview verdict on a completed render is a DIAGNOSE instruction, not
            # a kill order. Saying 'abort' there would train operators to ignore it.
            if rec['recommend'] == 'abort' and pr.get('done'):
                rec.update(
                    {
                        'recommend': 'inspect',
                        'reason': rec['reason'] + ' — but the render has already '
                        'finished, so there is nothing to abort',
                        'what_to_do': 'run `self_improve.py diagnose` on the '
                        'finished output and let the pixel gates '
                        'confirm or refute the preview verdict',
                    }
                )

            if rec['recommend'] == 'abort':
                log('[self_improve] *** ABORT RECOMMENDATION *** ' + rec['reason'])
                log('[self_improve] ' + rec['what_to_do'])
                if on_alert and not fired:
                    fired = True
                    try:
                        on_alert(rec)
                    except Exception as e:
                        log(f'[self_improve] on_alert callback failed: {e}')
                _write_json(os.path.join(run_dir, 'abort_recommendation.json'), rec, log)
            elif rec['recommend'] == 'inspect':
                log('[self_improve] *** INSPECT *** ' + rec['reason'])
                log('[self_improve] ' + rec['what_to_do'])
            else:
                log(
                    f'[self_improve] watch: {rec["recommend"]} — {rec["reason"]} '
                    f'(step {pr.get("step")}/{pr.get("total")})'
                )
        except Exception as e:
            rec = {'ok': False, 'error': str(e)[:250], 'recommend': 'continue', 'run_dir': run_dir}
            log(f'[self_improve] watch error (non-fatal): {e}')
        if once or rec.get('recommend') in ('abort', 'inspect'):
            return rec
        if (time.time() - t0) > max_minutes * 60:
            log('[self_improve] watch: max_minutes reached')
            return rec
        if rec.get('evidence', {}).get('progress', {}).get('done'):
            return rec
        time.sleep(max(5.0, float(poll_s)))
