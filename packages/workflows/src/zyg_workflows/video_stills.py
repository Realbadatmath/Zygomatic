# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Still generation for Video Studio — the other way into /video/api/render.

A render needs a start image. Video Studio could already continue an existing
clip or use anything dropped in output/video_studio/_stills/; this module makes
the intro frame itself, so a workflow can start from a prompt and nothing else.

The generation runs as a CHILD PROCESS, not in kanban-server. Importing
comfy_generation_service loads CLIP at import time, which the board process must
never pay for (and never hold): the child is spawned per job, does one still and
exits, so the VRAM goes back when it does.

Same job contract as video_studio: start -> {'id','state','log',...}, poll with
job(jid), list with jobs().
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


CWD = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(CWD, 'output', 'video_studio', '_stills')

# The crews venv — numpy 2.5 / cv2 / PIL. The system python3 has no numpy, so
# the child must be this interpreter even when the parent is something else.
_VENV_PY = os.path.abspath(os.path.join(CWD, os.pardir, '.venv', 'bin', 'python'))

# FLUX is paused on this path (licence); Wan/Qwen/Klein are Apache-2.0/BSD.
FAMILIES = ('qwen', 'klein')

STEPS = 20
CFG = 3.5
# A 1280x720 Qwen still takes ~40-90 s once the model is resident; the first
# one of a session also pays the load. 15 min is a hang, not a slow render.
TIMEOUT_S = 900

_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()
_JOB_KEEP = 24

# ── Medusa workflow beacon (2026-09-23) ──────────────────────────────────────
# "A picture of X" asked for in the Medusa app is a Medusa workflow, and the
# Workflows board must light up for it. The board's status endpoint lives in the
# GUI process (:5000, bp_medusa.api_medusa_kanban_status) and reads running work
# out of its OWN sys.modules — it cannot see this process at all. While the
# assistant turn that asked for the picture is open the Medusa app's own beacon
# covers it, but a still started with wait=False, or one still rendering when
# the turn hands back, left the board idle in the middle of a live render.
# So publish the count the same way the Medusa app does: one small file,
# refreshed on a tick while work is in flight, stale-checked by the reader.
# Only medusa=True jobs are counted — a Video Studio still is not Medusa work.
_BEACON_PATH = os.path.join(CWD, 'data', 'runtime', 'medusa_beacons', 'stills.json')
_BEACON_TICK = 10.0
_beacon_thread = None
_beacon_lock = threading.Lock()


def _medusa_live() -> int:
    with _JOBS_LOCK:
        return sum(1 for j in _JOBS.values() if j.get('medusa') and j.get('state') in ('queued', 'running'))


def _beacon_write() -> None:
    n = _medusa_live()
    try:
        os.makedirs(os.path.dirname(_BEACON_PATH), exist_ok=True)
        tmp = f'{_BEACON_PATH}.tmp.{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(
                {'running': n, 'label': ('Picture ×%d' % n) if n > 1 else ('Picture' if n else ''), 'ts': time.time()},
                fh,
            )
        os.replace(tmp, _BEACON_PATH)
    except Exception as _exc:  # noqa: BLE001 — a beacon must never break a render
        _zyg_log.debug('beacon write skipped: %s', _exc)


def _beacon_pulse() -> None:
    """Keep the beacon fresh while Medusa stills are in flight, then stop. One
    thread at most, started on demand, so an idle board process carries none."""
    global _beacon_thread
    _beacon_write()
    with _beacon_lock:
        if _beacon_thread is not None and _beacon_thread.is_alive():
            return

        def _loop():
            while _medusa_live() > 0:
                time.sleep(_BEACON_TICK)
                _beacon_write()
            _beacon_write()  # final: running = 0

        _beacon_thread = threading.Thread(target=_loop, name='medusa-still-beacon', daemon=True)
        _beacon_thread.start()


def _python() -> str:
    if os.path.isfile(_VENV_PY) and os.access(_VENV_PY, os.X_OK):
        return _VENV_PY
    return sys.executable


def _job_set(jid: str, **kw):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j.update(kw)


def _job_log(jid: str, msg: str):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j['log'].append(f'{time.strftime("%H:%M:%S")} {msg}')
            j['log'] = j['log'][-240:]


def job(jid: str) -> dict:
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else {}


def jobs() -> list:
    """Recent stills, newest first."""
    with _JOBS_LOCK:
        out = sorted(_JOBS.values(), key=lambda j: j['started'], reverse=True)
        return [
            {
                'id': j['id'],
                'label': j['label'],
                'state': j['state'],
                'url': j['url'],
                'path': j['path'],
                'error': j['error'],
                'seed': j['seed'],
                'family': j['family'],
                'started': j['started'],
                'finished': j['finished'],
            }
            for j in out
        ]


def _prune_jobs():
    """Keep the last _JOB_KEEP jobs, never evicting one still in flight. Caller
    holds _JOBS_LOCK."""
    live = {k for k, j in _JOBS.items() if j.get('state') in ('queued', 'running')}
    finished = [k for k in sorted(_JOBS, key=lambda k: _JOBS[k]['started']) if k not in live]
    for old in finished[: max(0, len(finished) - _JOB_KEEP)]:
        _JOBS.pop(old, None)


def _slug(text: str, n: int = 20) -> str:
    s = re.sub(r'[^a-z0-9]+', '_', str(text).lower()).strip('_')
    return s[:n].strip('_') or 'still'


# The child: one still, then exit. The spec arrives as JSON in the environment
# so no operator text is ever interpolated into a command line.
_CHILD = r"""
import json, os, sys, time
spec = json.loads(os.environ['ZYG_STILL_SPEC'])
from zyg_workflows import comfy_generation_service as c
# Medusa-only extras. spec['medusa'] is set exclusively by a caller that opted
# in (Vicky's picture_generate); Video Studio never sets it, so this whole
# block is unreachable from the general still path.
kw = {}
if spec.get('medusa'):
    from zyg_workflows import medusa_model_lora as mml
    base = mml.resolve_active(spec['family'])
    if base:
        kw['medusa_base_lora'] = base
        print('MEDUSA_BASE %s %s' % (base['model_id'], base['name']), flush=True)
t0 = time.time()
ok, backend = c.generate_still(
    spec['out'], spec['prompt'],
    width=spec['width'], height=spec['height'],
    steps=spec['steps'], cfg=spec['cfg'], seed=spec['seed'],
    model_family=spec['family'], skip_qa=True, prompt_finalized=True,
    solo_subject=False, human_subject=False,
    extra_negative=spec['negative'], **kw)
print('SECONDS %.1f' % (time.time() - t0), flush=True)
print('RESULT', ok, backend, flush=True)
sys.exit(0 if ok else 1)
"""


def _worker(jid: str, spec: dict):
    try:
        _worker_run(jid, spec)
    finally:
        # Whatever happened — done, error, timeout, dead child — the board must
        # stop being told this render is live within one tick.
        if spec.get('medusa'):
            _beacon_write()


def _worker_run(jid: str, spec: dict):
    _job_set(jid, state='running')
    _job_log(jid, f'still {spec["width"]}x{spec["height"]} seed {spec["seed"]} family {spec["family"]}')
    env = dict(os.environ)
    env['ZYG_STILL_SPEC'] = json.dumps(spec)
    env.setdefault('PYTHONUNBUFFERED', '1')
    # comfy_generation_service.is_available() is gated on these two; without
    # them generate_still refuses with (False, 'unavailable') in 0.0 s. Same
    # setdefault the other ComfyUI callers use (video_studio ~3650), so an
    # operator who exported them off still wins.
    env.setdefault('ZYG_COMFY_PRIMARY', '1')
    env.setdefault('ZYG_USE_COMFYUI', '1')
    t0 = time.time()
    backend = ''
    seconds = 0.0
    try:
        p = subprocess.run(
            [_python(), '-c', _CHILD],
            cwd=CWD,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT_S,
        )
        out = p.stdout or ''
        for line in out.splitlines():
            line = line.rstrip()
            if line:
                _job_log(jid, line[:400])
            if line.startswith('SECONDS '):
                try:
                    seconds = float(line.split()[1])
                except (IndexError, ValueError) as _exc:
                    _zyg_log.debug('unparsable worker TIME line ignored: %s', _exc)
            elif line.startswith('RESULT '):
                bits = line.split(None, 2)
                backend = bits[2] if len(bits) > 2 else ''
        rc = p.returncode
    except subprocess.TimeoutExpired:
        _job_log(jid, f'timeout after {TIMEOUT_S}s')
        _job_set(jid, state='error', error=f'timed out after {TIMEOUT_S}s', finished=time.time())
        return
    except Exception as e:  # noqa: BLE001 — a dead child must not kill the thread
        _job_log(jid, f'spawn failed: {type(e).__name__}: {e}')
        _job_set(jid, state='error', error=f'{type(e).__name__}: {e}'[:300], finished=time.time())
        return

    seconds = seconds or round(time.time() - t0, 1)
    if rc != 0 or not os.path.isfile(spec['out']):
        _job_set(jid, state='error', finished=time.time(), error=f'generation failed (exit {rc})')
        return

    # 2026-09-23: 'medusa' is recorded here too. The stills folder is shared
    # with Video Studio, so the file itself says nothing about which app asked
    # for it — and Medusa's Library ("Pictures") is exactly the question "which
    # of these did Medusa make". The flag is the only durable answer: the job
    # registry is in-memory and pruned, and the chat that ordered the picture
    # can be deleted. Old sidecars were backfilled from the Medusa chat store.
    side = {
        'prompt': spec['prompt'],
        'negative': spec['negative'],
        'seed': spec['seed'],
        'family': spec['family'],
        'width': spec['width'],
        'height': spec['height'],
        'backend': backend,
        'seconds': seconds,
        'medusa': bool(spec.get('medusa')),
    }
    try:
        with open(os.path.splitext(spec['out'])[0] + '.json', 'w', encoding='utf-8') as fh:
            json.dump(side, fh, indent=2)
    except OSError as e:
        _job_log(jid, f'sidecar not written: {e}')

    name = os.path.basename(spec['out'])
    _job_log(jid, f'done in {seconds:.1f}s via {backend or "comfy"}')
    _job_set(
        jid,
        state='done',
        finished=time.time(),
        path=spec['out'],
        url=f'/inspect/media?path=out/video_studio/_stills/{name}',
        backend=backend,
        seconds=seconds,
    )


def generate(
    prompt: str,
    width: int = 1280,
    height: int = 720,
    seed: int = 0,
    negative: str = '',
    family: str = 'qwen',
    label: str = '',
    medusa: bool = False,
) -> dict:
    """Queue one still. Returns the job dict; poll it with job(jid).

    medusa=True marks this as Medusa-app content: it attaches the active Medusa
    BASE LoRA for *family* (if any) and enforces the adults-only prompt floor.
    It is opt-in and defaults False, so the Video Studio path is unchanged.
    """
    prompt = str(prompt or '').strip()
    if not prompt:
        raise ValueError('prompt is required')
    if medusa:
        # AGE floor only (medusa_age_gate, no env override). There is no age
        # field on a free-text still, so this is the minor-language check; it
        # raises ValueError, which the HTTP layer already turns into a 400.
        from zyg_workflows import medusa_age_gate as _age

        _age.assert_adult_prompt(prompt, field='prompt')
    family = str(family or 'qwen').strip().lower()
    if family not in FAMILIES:
        raise ValueError(f'family must be one of {", ".join(FAMILIES)} (FLUX is paused)')
    width, height = int(width), int(height)
    seed = int(seed)

    jid = f'{int(time.time() * 1000):x}{os.getpid():x}'
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f'{jid}_{_slug(label or prompt)}.png')
    spec = {
        'out': out,
        'prompt': prompt,
        'negative': str(negative or ''),
        'width': width,
        'height': height,
        'seed': seed,
        'family': family,
        'steps': STEPS,
        'cfg': CFG,
        'medusa': bool(medusa),
    }

    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'state': 'queued',
            'log': [],
            'url': '',
            'path': '',
            'error': '',
            'backend': '',
            'seconds': 0.0,
            'label': label or _slug(prompt),
            'prompt': prompt,
            'seed': seed,
            'family': family,
            'width': width,
            'height': height,
            'started': time.time(),
            'finished': 0.0,
            'medusa': bool(medusa),
        }
        _prune_jobs()
    if medusa:
        _beacon_pulse()  # the board goes live on the QUEUED edge, not on first paint
    threading.Thread(target=_worker, args=(jid, spec), daemon=True).start()
    return job(jid)
