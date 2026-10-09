# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""comfy_preview_watcher.py — live TAESD preview snapshots for long renders (2026-07-30).

Problem: a single-stream diffusion render (341 frames, ~90 min) produces NOTHING
inspectable until the final step + decode. With ComfyUI started with
--preview-method taesd (see start_server.sh) the sampler emits blurry per-step preview
frames over the websocket to the submitting client. This watcher subscribes with the
SAME client_id (set ZYG_COMFY_CLIENT_ID before the driver submits), and:
  - writes the newest preview to <out_dir>/preview_latest.jpg (atomic replace)
  - keeps a timestamped snapshot every --interval seconds (default 120)
  - appends sampler progress lines (step k/N) to <out_dir>/progress.txt
This catches CATASTROPHIC failures (composition collapse, wrong scene) mid-flight —
it cannot judge fine temporal quality; that stays with the post-render QC battery.

Usage (from a driver, best-effort):
    os.environ['ZYG_COMFY_CLIENT_ID'] = 'zyg-run-xyz'
    subprocess.Popen([sys.executable, 'comfy_preview_watcher.py', out_dir,
                      '--client-id', 'zyg-run-xyz'], start_new_session=True)
Or standalone: python comfy_preview_watcher.py <out_dir> --client-id zyg-run-xyz
Exits on --max-minutes (default 180) or when the websocket closes.
"""

import argparse
import os
import struct
import time
import logging as _zyg_logging
from urllib.parse import urlsplit

from zyg_workflows.paths import ZYG_COMFY_URL

_zyg_log = _zyg_logging.getLogger(__name__)

#: host:port only — the ws:// URL below is built by hand.
_COMFY_NETLOC = urlsplit(ZYG_COMFY_URL).netloc or ZYG_COMFY_URL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out_dir')
    ap.add_argument('--client-id', default=os.environ.get('ZYG_COMFY_CLIENT_ID', 'zyg-watch'))
    ap.add_argument('--server', default=_COMFY_NETLOC)
    ap.add_argument('--interval', type=float, default=120.0)
    ap.add_argument('--max-minutes', type=float, default=180.0)
    a = ap.parse_args()

    import websocket  # websocket-client

    os.makedirs(a.out_dir, exist_ok=True)
    prog_path = os.path.join(a.out_dir, 'progress.txt')
    latest = os.path.join(a.out_dir, 'preview_latest.jpg')
    t_end = time.time() + a.max_minutes * 60
    last_snap = 0.0

    def log_progress(msg):
        with open(prog_path, 'a') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')

    ws = websocket.WebSocket()
    ws.connect(f'ws://{a.server}/ws?clientId={a.client_id}', timeout=30)
    log_progress(f'watcher connected (client_id={a.client_id})')
    ws.settimeout(60)
    while time.time() < t_end:
        try:
            frame = ws.recv()
        except websocket.WebSocketTimeoutException as _exc:
            _zyg_log.debug('websocket recv timed out, continuing: %s', _exc)
            continue
        except Exception as e:
            log_progress(f'ws closed ({e})')
            break
        if isinstance(frame, bytes):
            # binary preview: [4B event][4B format][image bytes]; event 1 = preview image
            if len(frame) > 8:
                (event,) = struct.unpack('>I', frame[:4])
                if event == 1:
                    img = frame[8:]
                    tmp = latest + '.tmp'
                    with open(tmp, 'wb') as f:
                        f.write(img)
                    os.replace(tmp, latest)
                    now = time.time()
                    if now - last_snap >= a.interval:
                        snap = os.path.join(a.out_dir, f'preview_{time.strftime("%H%M%S")}.jpg')
                        with open(snap, 'wb') as f:
                            f.write(img)
                        last_snap = now
                        log_progress(f'snapshot {os.path.basename(snap)} ({len(img)}B)')
        else:
            try:
                import json

                m = json.loads(frame)
                if m.get('type') == 'progress':
                    d = m.get('data', {})
                    log_progress(f'step {d.get("value")}/{d.get("max")}')
                elif m.get('type') in (
                    'execution_start',
                    'execution_success',
                    'execution_error',
                    'execution_interrupted',
                ):
                    log_progress(m.get('type'))
                    if m.get('type') != 'execution_start':
                        break
            except Exception as _exc:
                _zyg_log.debug('websocket progress frame ignored: %s', _exc)
    try:
        ws.close()
    except Exception as _exc:
        _zyg_log.debug('websocket close skipped: %s', _exc)
    log_progress('watcher done')


if __name__ == '__main__':
    main()
