# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.preview_judge`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.preview_judge` still reaches it.
"""

import argparse
import json
import os
import shutil
import sys
import time

from zyg_workflows.preview_judge import _default_tier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--interval', type=float, default=180.0, help='seconds between judged previews (default 180)')
    ap.add_argument('--max-minutes', type=float, default=180.0)
    ap.add_argument('--checklist', default='catastrophic_preview')
    ap.add_argument('--tier', default=_default_tier(), choices=['cpu', 'resident', 'boundary'])
    ap.add_argument(
        '--preview', default='preview_latest.jpg', help='preview file inside run_dir (comfy_preview_watcher output)'
    )
    ap.add_argument(
        '--alert-streak', type=int, default=2, help='consecutive critical ticks before PREVIEW_ALERT (default 2)'
    )
    ap.add_argument('--max-unavailable', type=int, default=3, help='give up after N ticks with no judge installed')
    a = ap.parse_args()

    run_dir = os.path.abspath(a.run_dir)
    os.makedirs(run_dir, exist_ok=True)
    judged_dir = os.path.join(run_dir, 'preview_judge')
    os.makedirs(judged_dir, exist_ok=True)
    jsonl = os.path.join(run_dir, 'preview_judge.jsonl')
    alert = os.path.join(run_dir, 'PREVIEW_ALERT')
    stop_file = os.path.join(run_dir, 'PREVIEW_JUDGE_STOP')
    preview = os.path.join(run_dir, a.preview)

    def log(msg):
        print(f'[{time.strftime("%H:%M:%S")}] [preview_judge] {msg}', flush=True)

    def append(rec):
        try:
            with open(jsonl, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, default=str) + '\n')
        except Exception as e:
            log(f'jsonl write failed: {e}')

    if a.tier != 'cpu':
        log(
            f'WARNING: tier={a.tier} runs on the GPU while the render holds it — '
            f'this is opt-in territory (ZYG_PREVIEW_JUDGE_GPU)'
        )

    try:
        from zyg_workflows import vlm_inspector as VLM
    except Exception as e:
        log(f'vlm_inspector unavailable ({e}) — nothing to do')
        append({'t': time.time(), 'iso': time.strftime('%H:%M:%S'), 'skipped': True, 'reason': f'import_failed:{e}'})
        return 0

    log(
        f'watching {preview} every {a.interval:.0f}s (tier={a.tier}, '
        f'checklist={a.checklist}, alert_streak={a.alert_streak}, '
        f'max {a.max_minutes:.0f} min)'
    )
    t_end = time.time() + a.max_minutes * 60
    last_mtime, streak, unavailable, ticks = None, 0, 0, 0

    while time.time() < t_end:
        if os.path.exists(stop_file):
            log('stop file present — exiting')
            break
        t_tick = time.time()
        try:
            mtime = os.path.getmtime(preview) if os.path.isfile(preview) else None
        except OSError:
            mtime = None
        if mtime is None:
            log('no preview yet')
        elif mtime == last_mtime:
            log('preview unchanged since last tick — skipping')
        else:
            last_mtime = mtime
            ticks += 1
            snap = os.path.join(judged_dir, f'judged_{time.strftime("%H%M%S")}.jpg')
            res = {}
            try:
                shutil.copy2(preview, snap)
                # offload=False ALWAYS: never hand the render's VRAM away here.
                res = VLM.inspect_frames(
                    [snap], checklist=a.checklist, tier=a.tier, offload=False, frame_kind='all', log_fn=log
                )
            except Exception as e:
                log(f'inspection error (non-fatal): {e}')
                res = {'ok': True, 'skipped': True, 'reason': f'error:{e}'}
            rec = {
                't': round(t_tick, 1),
                'iso': time.strftime('%H:%M:%S'),
                'frame': snap,
                'tick': ticks,
                'ok': res.get('ok'),
                'skipped': bool(res.get('skipped')),
                'reason': res.get('reason'),
                'tier': res.get('tier'),
                'model': res.get('model'),
                'seconds': res.get('seconds'),
                'criticals': res.get('criticals') or [],
                'majors': res.get('majors') or [],
                'verdicts': res.get('verdicts') or [],
            }
            append(rec)
            if res.get('skipped'):
                reason = str(res.get('reason') or '')
                log(f'tick {ticks}: skipped ({reason})')
                if reason in ('worker_unavailable', 'checklist_unavailable', 'disabled'):
                    unavailable += 1
                    if unavailable >= a.max_unavailable:
                        log(f'judge unavailable {unavailable}x — exiting (render untouched)')
                        break
            else:
                unavailable = 0
                crit = res.get('criticals') or []
                log(
                    f'tick {ticks}: ok={res.get("ok")} critical={crit} '
                    f'major={res.get("majors") or []} ({res.get("seconds")}s)'
                )
                streak = streak + 1 if crit else 0
                if crit and streak >= a.alert_streak and not os.path.exists(alert):
                    try:
                        with open(alert, 'w', encoding='utf-8') as f:
                            json.dump(
                                {
                                    'when': time.strftime('%Y-%m-%d %H:%M:%S'),
                                    'streak': streak,
                                    'criticals': crit,
                                    'frame': snap,
                                    'checklist': a.checklist,
                                    'verdicts': res.get('verdicts') or [],
                                    'note': 'ADVISORY — render NOT interrupted',
                                },
                                f,
                                indent=1,
                                default=str,
                            )
                        log(
                            f'*** PREVIEW_ALERT written: {crit} (streak {streak}) — advisory only, render continues ***'
                        )
                    except Exception as e:
                        log(f'alert write failed: {e}')

        # sleep out the rest of the interval, checking the stop file as we go
        while time.time() < min(t_tick + a.interval, t_end):
            if os.path.exists(stop_file):
                break
            time.sleep(min(5.0, max(0.5, t_tick + a.interval - time.time())))

    log(f'done after {ticks} judged preview(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
