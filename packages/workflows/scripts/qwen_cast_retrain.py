#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sequential Qwen-Image-2512 cast-retrain driver (runs OUTSIDE the GUI).

For each storyteller character it: frees ComfyUI VRAM, launches a 'qwen'
family LoRA training via an HTTP call to the ALREADY-RUNNING crewai-gui
service (http://127.0.0.1:5000), polls its status endpoint every 30 s until
a terminal state (with a step-progress stall watchdog that records 'stalled'
but never kills the job), and appends one JSONL row per character to the
report file.

2026-08-09: rewritten to launch/poll over HTTP instead of importing
lora_trainer_service directly. The old direct-import shape ran
start_training() inside THIS script's own OS process, which created the
TrainingJob in a module-level dict that lives only here — invisible to the
already-running crewai-gui service (a separate process) and therefore
invisible to every live view that reads THAT process's in-memory state
(Medusa :5300 Training tab, /gpu_schedule.html). Launching via HTTP against
the running service creates the TrainingJob inside that process instead, so
it shows up everywhere the GUI already shows training.

2026-08-09 (later same day): bp_medusa_training.py's /api/medusa/training/*
routes are hard-walled to the mdt_<12hex> namespace (ISOLATION CONTRACT in
that file's own docstring) and categorically refuse this script's bare
12-hex storyteller_chars ids (confirmed live: HTTP 404 'unknown character').
Rather than touch that isolation boundary, two new routes were added to
bp_storyteller.py instead — POST/GET /api/storyteller/training/characters/
<char_id>/retrain{,/status} — mirroring bp_medusa_training.py's response
shape exactly, so only the URL templates below needed to change.

Safe to Ctrl-C between characters: the current character gets an
'interrupted' row and the loop stops. A SimpleTuner subprocess that is
already mid-flight keeps running after this script exits — it is a thread
inside the GUI's own OS process, not this script's; its status stays
recoverable through the GUI's status endpoint (or from disk after a GUI
restart).

Usage:
    python3 qwen_cast_retrain.py --dry-run
    python3 qwen_cast_retrain.py --pilot
    python3 qwen_cast_retrain.py --chars c3345deb5bde,0015c8a3f2e3
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

from zyg_workflows import paths

_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
_DEFAULT_REPORT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars' / 'qwen_retrain_report.jsonl')
_COMFY_FREE_URL = os.environ.get('ZYG_COMFY_FREE_URL', 'http://127.0.0.1:8188/free')

# The already-running crewai-gui service — NOT this script's own process.
_GUI_BASE_URL = os.environ.get('ZYG_GUI_BASE_URL', 'http://127.0.0.1:5000').rstrip('/')
_TRAIN_URL_TMPL = _GUI_BASE_URL + '/api/storyteller/training/characters/{char_id}/retrain'
_STATUS_URL_TMPL = _GUI_BASE_URL + '/api/storyteller/training/characters/{char_id}/retrain/status'
_HTTP_TIMEOUT_S = float(os.environ.get('ZYG_QWEN_RETRAIN_HTTP_TIMEOUT_S', '30'))

_POLL_S = float(os.environ.get('ZYG_QWEN_RETRAIN_POLL_S', '30'))
# No step advance for this many minutes → record 'stalled', stop polling,
# do NOT kill the job (it may be quantizing / caching / validating).
_STALL_MIN = float(os.environ.get('ZYG_QWEN_RETRAIN_STALL_MIN', '90'))


def _log(msg: str) -> None:
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] [qwen-retrain] {msg}', flush=True)


def _utc_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _free_comfy_vram() -> None:
    """Ask ComfyUI to drop its models before SimpleTuner loads 20B+TE; tolerate failure."""
    try:
        if urlsplit(_COMFY_FREE_URL).scheme not in ('http', 'https'):
            _log(f'refusing to POST to {_COMFY_FREE_URL!r}: only http/https')
            return
        payload = json.dumps({'unload_models': True, 'free_memory': True}).encode('utf-8')
        req = urllib.request.Request(  # noqa: S310  scheme checked above
            _COMFY_FREE_URL,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310  scheme checked above
            _log(f'ComfyUI /free → HTTP {resp.status}')
    except Exception as exc:
        _log(f'ComfyUI /free failed (tolerated): {exc}')


def _count_training_pairs(training_dir: str) -> int:
    """png files with a caption .txt beside them."""
    try:
        names = set(os.listdir(training_dir))
    except OSError:
        return 0
    n = 0
    for fn in names:
        if fn.lower().endswith('.png') and (os.path.splitext(fn)[0] + '.txt') in names:
            n += 1
    return n


def _discover_chars(min_images: int) -> list[str]:
    out: list[str] = []
    try:
        entries = sorted(os.listdir(_DATASET_ROOT))
    except OSError as exc:
        _log(f'cannot list {_DATASET_ROOT}: {exc}')
        return out
    for name in entries:
        char_dir = os.path.join(_DATASET_ROOT, name)
        if not os.path.isdir(char_dir):
            continue
        if not os.path.isfile(os.path.join(char_dir, 'character_bible.json')):
            continue
        training_dir = os.path.join(char_dir, 'training')
        if not os.path.isdir(training_dir):
            continue
        pairs = _count_training_pairs(training_dir)
        if pairs >= min_images:
            out.append(name)
    return out


def _bible_trigger_token(char_id: str) -> str | None:
    try:
        with open(os.path.join(_DATASET_ROOT, char_id, 'character_bible.json'), encoding='utf-8') as fh:
            return (json.load(fh) or {}).get('trigger_token') or None
    except Exception:
        return None


def _append_report_row(report_path: str, row: dict) -> None:
    try:
        os.makedirs(os.path.dirname(report_path) or '.', exist_ok=True)
        with open(report_path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception as exc:
        _log(f'could not append report row for {row.get("char_id")}: {exc}')


# ── HTTP against the already-running crewai-gui service ─────────────────────


def _http_json(
    url: str,
    method: str = 'GET',
    payload: dict | None = None,
    timeout: float = _HTTP_TIMEOUT_S,
) -> tuple[int, dict | None]:
    """GET/POST a JSON endpoint; never raises.

    Returns (http_status, parsed_json). http_status is 0 for a transport-level
    failure (connection refused, timeout, DNS, ...) that never got a response
    at all; parsed_json is None when a response came back but its body wasn't
    valid JSON. Flask's error responses (404/400/...) still carry a JSON body
    ({'ok': False, 'error': ...}), so those are read via urllib's HTTPError
    branch rather than treated as failures.
    """
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if urlsplit(url).scheme not in ('http', 'https'):
        # net.safe_urlopen cannot carry the JSON Content-Type this POST needs, so the scheme
        # audit S310 asks for is done here instead, before the request object is built at all.
        _log(f'refusing to request {url!r}: only http/https')
        return 0, None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310  scheme checked above
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  scheme checked above
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read()
        except Exception:
            body = b''
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, {'ok': False, 'error': f'HTTP request failed: {exc}'}
    try:
        parsed = json.loads(body.decode('utf-8')) if body else {}
    except (ValueError, UnicodeDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        parsed = None
    return status, parsed


def _parse_status_response(http_status: int, parsed: dict | None) -> dict:
    """Normalize a GET .../status response into the trainer's status shape.

    Success (200, {'ok': True, 'status': {...}}) returns that inner dict
    as-is — it's TrainingJob.to_dict() plus a 'status' string, or the
    disk-recovery / not_found shape from lora_trainer_service.get_status().
    Anything else (transport failure, non-200, ok:false, malformed body —
    including the 404 'unknown character' this script's char_ids currently
    always get, see the module docstring's KNOWN GAP) collapses to a single
    safe 'no news' shape: done/failed both False, no step/eta data, and the
    server's error message preserved for logging. Pure function, no I/O —
    this is what the read-only smoke test below calls directly.
    """
    if http_status == 200 and isinstance(parsed, dict) and parsed.get('ok') and isinstance(parsed.get('status'), dict):
        return dict(parsed['status'])
    err = None
    if isinstance(parsed, dict):
        err = parsed.get('error')
    return {
        'step': 0,
        'total_steps': 0,
        'pct': None,
        'done': False,
        'failed': False,
        'error': None,
        'lora_path': None,
        'trigger_token': None,
        'status': 'http_error',
        'elapsed_s': None,
        'eta_s': None,
        'http_status': http_status,
        'http_error': err or f'HTTP {http_status}',
    }


def _launch_training(char_id: str) -> tuple[bool, dict]:
    """POST the train route. Returns (started, info).

    info carries {'reason': ...} on refusal, or the server's 'result' dict
    (last_start_result(char_id) — {'started','reason','model_family',
    'trigger_token','ts'}) on a real launch. The route reads only
    'model_family' from the JSON body (see api_training_start in
    bp_medusa_training.py) — trigger_token is not accepted there, so it is
    looked up only for the log line / report row, not sent.
    """
    url = _TRAIN_URL_TMPL.format(char_id=urllib.parse.quote(char_id, safe=''))
    status, parsed = _http_json(url, method='POST', payload={'model_family': 'qwen'})
    if status == 200 and isinstance(parsed, dict) and parsed.get('ok'):
        return True, (parsed.get('result') or {})
    reason = (parsed or {}).get('error') if isinstance(parsed, dict) else None
    return False, {'reason': reason or f'HTTP {status}'}


def _poll_status(char_id: str) -> dict:
    url = (
        _STATUS_URL_TMPL.format(char_id=urllib.parse.quote(char_id, safe=''))
        + '?'
        + urllib.parse.urlencode({'model_family': 'qwen'})
    )
    status, parsed = _http_json(url, method='GET')
    return _parse_status_response(status, parsed)


def _fmt_minutes(seconds) -> str | None:
    try:
        return f'{int(float(seconds) // 60)}m'
    except (TypeError, ValueError):
        return None


def _run_one(char_id: str, report_path: str) -> str:
    """Train one character to a terminal state; append its row; return the state."""
    training_dir = os.path.join(_DATASET_ROOT, char_id, 'training')
    started = _utc_iso()
    wall_start = time.time()
    row = {
        'char_id': char_id,
        'started': started,
        'ended': None,
        'state': '',
        'lora_path': None,
        'error': None,
        # Server's real eta_s (seconds) as of the last successful poll; None
        # if the server never reported one for this run.
        'eta_at_last_poll': None,
        # Computed locally from wall-clock at completion — never trusted from
        # the server, per the task's own instruction.
        'actual_duration_s': None,
    }

    def _finish(**kw) -> str:
        row.update(**kw)
        row['actual_duration_s'] = round(time.time() - wall_start, 2)
        _append_report_row(report_path, row)
        return row['state']

    if not os.path.isdir(training_dir):
        state = _finish(state='missing_training_dir', ended=_utc_iso(), error=f'no training dir at {training_dir}')
        _log(f'{char_id}: SKIP — {row["error"]}')
        return state

    # (a) ComfyUI must not be holding 20-30 GB when SimpleTuner loads Qwen.
    _free_comfy_vram()

    # (b) Launch via the already-running crewai-gui service, not an in-process
    # import — see module docstring for why, and its KNOWN GAP for why real
    # storyteller char_ids currently get refused by the route itself.
    trig = _bible_trigger_token(char_id)  # informational only, see _launch_training
    started_ok, info = _launch_training(char_id)
    if not started_ok:
        state = _finish(state='refused', ended=_utc_iso(), error=info.get('reason') or 'refused (no reason recorded)')
        _log(f'{char_id}: REFUSED — {row["error"]}')
        return state
    _log(
        f'{char_id}: training launch requested via HTTP '
        f'(trigger={trig or info.get("trigger_token") or "server-default"})'
    )

    # (c) Poll to terminal state with a step-progress stall watchdog.
    last_step = -1
    last_advance_wall = time.time()
    last_advance_elapsed_s = None  # server's elapsed_s at the last observed step advance
    last_eta_s = None
    st: dict = {}
    try:
        while True:
            time.sleep(_POLL_S)
            st = _poll_status(char_id)
            step = int(st.get('step') or 0)
            total = st.get('total_steps') or '?'
            pct = st.get('pct')
            real_elapsed = st.get('elapsed_s')
            real_eta = st.get('eta_s')
            if real_eta is not None:
                last_eta_s = real_eta

            if step > last_step:
                last_step = step
                last_advance_wall = time.time()
                last_advance_elapsed_s = real_elapsed

            pct_txt = f' ({pct}%)' if pct is not None else ''
            eta_txt = f', eta {_fmt_minutes(real_eta)}' if _fmt_minutes(real_eta) else ''
            elapsed_txt = f', elapsed {_fmt_minutes(real_elapsed)}' if _fmt_minutes(real_elapsed) else ''
            extra = ''
            if st.get('status') == 'http_error':
                extra = f' [{st.get("http_error")}]'
            _log(f'{char_id}: step {step}/{total}{pct_txt}{elapsed_txt}{eta_txt}{extra}')

            if st.get('done'):
                return _finish(
                    state='done', ended=_utc_iso(), lora_path=st.get('lora_path'), eta_at_last_poll=last_eta_s
                )
            if st.get('failed'):
                return _finish(
                    state='failed',
                    ended=_utc_iso(),
                    lora_path=st.get('lora_path'),
                    error=st.get('error') or 'unknown',
                    eta_at_last_poll=last_eta_s,
                )

            # Stall duration: prefer the server's real elapsed_s deltas (immune
            # to this script's own polling jitter — a late/slow poll never
            # looks like a stall); fall back to the script's own wall-clock
            # timer when elapsed_s is briefly missing from a poll (e.g. a job
            # recovered from disk with no live status yet).
            if real_elapsed is not None and last_advance_elapsed_s is not None:
                stalled_min = max(0.0, (real_elapsed - last_advance_elapsed_s) / 60.0)
            else:
                stalled_min = (time.time() - last_advance_wall) / 60.0
            if stalled_min >= _STALL_MIN:
                # Do NOT kill the job — just stop polling and record the stall.
                return _finish(
                    state='stalled',
                    ended=_utc_iso(),
                    error=f'no step advance for {stalled_min:.0f} min (last step {max(last_step, 0)})',
                    eta_at_last_poll=last_eta_s,
                )
    except KeyboardInterrupt:
        # Record what we know about THIS character, then let main() stop cleanly.
        state = _finish(
            state='interrupted',
            ended=_utc_iso(),
            error=f'operator Ctrl-C at step {max(last_step, 0)}',
            eta_at_last_poll=last_eta_s,
        )
        _log(f'{char_id}: interrupted at step {max(last_step, 0)}')
        raise
    finally:
        if row['state'] not in ('', 'interrupted'):
            _log(
                f'{char_id}: {row["state"]}'
                + (f' → {row["lora_path"]}' if row.get('lora_path') else '')
                + (f' ({row["error"]})' if row.get('error') else '')
            )


def main() -> int:
    ap = argparse.ArgumentParser(description='Sequential Qwen-Image-2512 cast retrain (outside the GUI)')
    ap.add_argument('--chars', default='', help='comma-separated char_ids (default: auto-discover)')
    ap.add_argument('--min-images', type=int, default=20, help='minimum png+txt training pairs for auto-discovery')
    ap.add_argument('--pilot', action='store_true', help='first character only')
    ap.add_argument('--dry-run', action='store_true', help='list the plan, train nothing')
    ap.add_argument('--report', default=_DEFAULT_REPORT, help='JSONL report path')
    args = ap.parse_args()

    if args.chars.strip():
        chars = [c.strip() for c in args.chars.split(',') if c.strip()]
    else:
        chars = _discover_chars(args.min_images)
    if args.pilot:
        chars = chars[:1]
    if not chars:
        _log('no characters matched — nothing to do')
        return 1

    _log(
        f'plan: {len(chars)} character(s), sequential, family=qwen, '
        f'launch/poll via {_GUI_BASE_URL}, '
        f'stall watchdog {_STALL_MIN:.0f} min, report → {args.report}'
    )
    for c in chars:
        pairs = _count_training_pairs(os.path.join(_DATASET_ROOT, c, 'training'))
        _log(f'  - {c} ({pairs} training pairs)')
    if args.dry_run:
        _log('dry-run: exiting without training')
        return 0

    counts: dict[str, int] = {}
    try:
        for idx, char_id in enumerate(chars, 1):
            _log(f'=== [{idx}/{len(chars)}] {char_id} ===')
            state = _run_one(char_id, args.report)
            counts[state] = counts.get(state, 0) + 1
    except KeyboardInterrupt:
        _log(
            'Ctrl-C — stopping. A SimpleTuner subprocess already mid-flight '
            'keeps running inside the GUI service; its status stays '
            'recoverable via the status endpoint (or from disk after a '
            'GUI restart).'
        )
        return 130
    _log('all done: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    return 0 if counts.get('done', 0) == len(chars) else 2


if __name__ == '__main__':
    sys.exit(main())
