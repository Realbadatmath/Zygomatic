# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ltx_hidream_service — stills from HiDream-O1 and motion from LTX-2.5.

Both models run on the SECOND ComfyUI (v0.38, port 8189, ``~/ai-models/comfyui-ltx``),
not on the production 0.22 server, which has no LTX-2.5 nodes.  The two servers share
one GPU, so every GPU-touching call here runs under the production submit lock
(``_comfy_client._acquire_submit_lock``): a kids song's ACE-Step leg and its picture leg
can never overlap, and neither can two songs.  A lease evicts the production server's
weights before it starts and unloads this server's weights when it ends, so the 40 GB
LTX residency never sits under a Wan or ACE job.

Measured 2026-10-02 on the RTX 4090 (see memory project-ltx25-instance /
project-hidream-o1-install): HiDream 1024² = 4.0 s warm / 8.1 s cold, 1536x864 ≈ 5 s;
LTX-2.5 distilled 5 s at 1280x704 ≈ 25 s warm, 3 s clips ≈ 15 s.

Licences (file level, 2026-10-02): HiDream-O1-Image-Dev-2604 = MIT (model card + HF tag,
code and weights); LTX-2.5 = LTX-2.x Community License — royalty-free worldwide, paid
licence only for entities with ≥ $10M revenue, outputs belong to the user (§5).  Both are
registered in data/runtime/model_licences.json and every graph is attested before it
is submitted, exactly as the klein/Wan graphs are.

No paid SDK, no ollama: this module talks HTTP to localhost only.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
import uuid

import requests
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))

LTX_URL = paths.ZYG_LTX_COMFY_URL
LTX_ROOT = paths.ZYG_LTX_COMFY_ROOT
INPUT_DIR = os.path.join(LTX_ROOT, 'input')
OUTPUT_DIR = os.path.join(LTX_ROOT, 'output')
START_SH = os.path.join(LTX_ROOT, 'start_server.sh')

HIDREAM_CKPT = os.environ.get('ZYG_HIDREAM_CKPT', 'hidream_o1_image_dev_fp8_scaled.safetensors')
HIDREAM_STEPS = int(os.environ.get('ZYG_HIDREAM_STEPS', '28'))
HIDREAM_NOISE_SCALE = float(os.environ.get('ZYG_HIDREAM_NOISE_SCALE', '7.6'))

LTX_GRAPH = os.path.join(HERE, '_comfy_workflows', 'ltx25_i2v.json')
LTX_UNET = os.environ.get('ZYG_LTX_UNET', 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors')
LTX_ASPECT = os.environ.get('ZYG_LTX_ASPECT', '16:9 (Widescreen)')
LTX_MEGAPIXELS = float(os.environ.get('ZYG_LTX_MEGAPIXELS', '0.9'))

_POLL_S = 0.5


class LTXHiDreamError(RuntimeError):
    pass


def _log_noop(_m):
    pass


# ── server ───────────────────────────────────────────────────────────────────


def is_available(timeout_s: float = 2.0) -> bool:
    try:
        r = requests.get(f'{LTX_URL}/system_stats', timeout=timeout_s)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_up(log_fn=None, wait_s: float = 150.0) -> bool:
    """Start the :8189 server if it is down (it has no systemd unit) and wait for it."""
    log_fn = log_fn or _log_noop
    if is_available():
        return True
    if not os.path.isfile(START_SH):
        log_fn(f'ltx: {START_SH} missing — the second ComfyUI is not installed')
        return False
    log_fn('ltx: ComfyUI :8189 is down — starting it')
    try:
        os.makedirs(os.path.join(LTX_ROOT, 'logs'), exist_ok=True)
        logf = open(os.path.join(LTX_ROOT, 'logs', 'server.log'), 'ab')
        subprocess.Popen(
            ['setsid', 'nohup', START_SH],
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=LTX_ROOT,
            start_new_session=True,
        )
    except Exception as e:  # noqa: BLE001
        log_fn(f'ltx: could not start the server ({type(e).__name__}: {e})')
        return False
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if is_available():
            log_fn('ltx: ComfyUI :8189 is up')
            return True
        time.sleep(2.0)
    log_fn(f'ltx: ComfyUI :8189 did not answer within {wait_s:.0f}s')
    return False


def free(log_fn=None) -> bool:
    """Unload this server's models and free its VRAM (instant POST, no wait)."""
    try:
        r = requests.post(f'{LTX_URL}/free', json={'unload_models': True, 'free_memory': True}, timeout=5)
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        (log_fn or _log_noop)(f'ltx: /free failed ({type(e).__name__})')
        return False


def interrupt() -> None:
    try:
        requests.post(f'{LTX_URL}/interrupt', timeout=5)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('LTX interrupt request failed, the :8189 job may keep running: %s', _exc)


@contextlib.contextmanager
def gpu_lease(should_abort=None, log_fn=None, timeout_s: float = 3600.0):
    """Hold the production submit lock for a whole batch of :8189 jobs.

    Evicts the production server's weights first (so the 4090 is empty when LTX
    loads) and unloads this server's weights at the end, including on the error
    path, so the next Wan/ACE job never starts under a 40 GB LTX residency.
    """
    log_fn = log_fn or _log_noop
    fd = None
    cc = None
    try:
        from zyg_workflows import _comfy_client as cc  # noqa: PLC0415

        fd = cc._acquire_submit_lock(should_abort, timeout_s=timeout_s)  # noqa: SLF001
        try:
            cc.free_vram()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('comfy VRAM release skipped: %s', _exc)
    except Exception as e:  # noqa: BLE001 — lock unavailable: run unserialised
        if cc is not None and 'abort' in str(e).lower():
            raise
        log_fn(f'ltx: production lock unavailable ({type(e).__name__}) — running unserialised')
    try:
        yield
    finally:
        free(log_fn=log_fn)
        if cc is not None and fd is not None:
            try:
                cc._release_submit_lock(fd)  # noqa: SLF001
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('production submit lock release failed, it may stay held: %s', _exc)


# ── plumbing ─────────────────────────────────────────────────────────────────


def stage_input(src_path: str) -> str:
    """Copy a local image into the :8189 input dir; returns the basename LoadImage needs."""
    if not os.path.isfile(src_path):
        raise LTXHiDreamError(f'input image not found: {src_path}')
    os.makedirs(INPUT_DIR, exist_ok=True)
    name = f'{uuid.uuid4().hex[:8]}_{os.path.basename(src_path)}'
    shutil.copy2(src_path, os.path.join(INPUT_DIR, name))
    return name


def _attest(graph, tag, log_fn):
    """Every weight in the graph through the licence gate; False = refuse."""
    try:
        from zyg_workflows import licence_provenance as _lp  # noqa: PLC0415

        att = _lp.attest_licences(graph, log_fn=log_fn, tag=tag)
    except Exception as e:  # noqa: BLE001
        log_fn(f'{tag}: licence attestation unavailable ({type(e).__name__}: {e})')
        return True
    if att.get('ok') is False:
        log_fn(
            f'{tag}: REFUSED — licence attestation failed: '
            + ', '.join(a.get('name', '?') for a in att.get('violations') or [])
        )
        return False
    if att.get('unknowns'):
        log_fn(
            f'{tag}: licence UNKNOWN for '
            + ', '.join(a.get('name', '?') for a in att['unknowns'])
            + ' — not refused, but not cleared either'
        )
    return True


def _submit(graph, *, timeout_s: float, should_abort=None, log_fn=None, client_id='kids'):
    """POST a graph, poll until done, return the output file paths. Raises on error."""
    log_fn = log_fn or _log_noop
    abort = should_abort or (lambda: False)
    r = requests.post(f'{LTX_URL}/prompt', json={'prompt': graph, 'client_id': client_id}, timeout=30)
    if r.status_code != 200:
        raise LTXHiDreamError(f'submit rejected ({r.status_code}): {r.text[:400]}')
    body = r.json()
    pid = body.get('prompt_id')
    if not pid:
        raise LTXHiDreamError(f'submit returned no prompt_id: {json.dumps(body)[:400]}')
    deadline = time.monotonic() + timeout_s
    while True:
        if abort():
            interrupt()
            raise LTXHiDreamError('halted by operator')
        if time.monotonic() > deadline:
            interrupt()
            raise LTXHiDreamError(f'job {pid[:8]} exceeded {timeout_s:.0f}s')
        try:
            h = requests.get(f'{LTX_URL}/history/{pid}', timeout=10).json().get(pid)
        except Exception:  # noqa: BLE001
            h = None
        if h:
            st = h.get('status') or {}
            if st.get('status_str') == 'error':
                msg = ''
                for m in st.get('messages') or []:
                    if m[0] == 'execution_error':
                        msg = f'{m[1].get("node_type")}: {str(m[1].get("exception_message"))[:300]}'
                raise LTXHiDreamError(f'execution error — {msg or "unknown"}')
            if st.get('completed'):
                outs = []
                for o in (h.get('outputs') or {}).values():
                    for v in o.get('images') or []:
                        outs.append(os.path.join(OUTPUT_DIR, v.get('subfolder') or '', v.get('filename') or ''))
                return [p for p in outs if os.path.isfile(p)]
        time.sleep(_POLL_S)


def _align32(v: int) -> int:
    return max(32, (int(v) // 32) * 32)


# ── HiDream still ─────────────────────────────────────────────────────────────


def hidream_graph(prompt, *, width, height, seed, negative='', prefix='kids/hidream', ckpt=None, steps=None):
    """The official ``image_hidream_o1_dev`` template, text-to-image branch, in API form."""
    ckpt = ckpt or HIDREAM_CKPT
    steps = int(steps or HIDREAM_STEPS)
    return {
        '6': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': ckpt}},
        '124': {'class_type': 'ModelNoiseScale', 'inputs': {'model': ['6', 0], 'noise_scale': HIDREAM_NOISE_SCALE}},
        '110': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['6', 1], 'text': prompt}},
        '188': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['6', 1], 'text': negative or ''}},
        '125': {'class_type': 'SamplerLCM', 'inputs': {'s_noise': 1.0, 's_noise_end': 1.0, 'noise_clip_std': 2.5}},
        '112': {
            'class_type': 'BasicScheduler',
            'inputs': {'model': ['124', 0], 'scheduler': 'normal', 'steps': steps, 'denoise': 1.0},
        },
        '156': {
            'class_type': 'EmptyHiDreamO1LatentImage',
            'inputs': {'width': _align32(width), 'height': _align32(height), 'batch_size': 1},
        },
        '108': {
            'class_type': 'SamplerCustom',
            'inputs': {
                'model': ['124', 0],
                'add_noise': True,
                'noise_seed': int(seed),
                'cfg': 1.0,
                'positive': ['110', 0],
                'negative': ['188', 0],
                'sampler': ['125', 0],
                'sigmas': ['112', 0],
                'latent_image': ['156', 0],
            },
        },
        '105': {'class_type': 'VAEDecode', 'inputs': {'samples': ['108', 0], 'vae': ['6', 2]}},
        '227': {'class_type': 'SaveImage', 'inputs': {'images': ['105', 0], 'filename_prefix': prefix}},
    }


def hidream_still(
    prompt, out_path, *, width=1536, height=864, seed=0, negative='', log_fn=None, should_abort=None, timeout_s=300.0
) -> bool:
    """One picture through HiDream-O1 on :8189.  Call inside ``gpu_lease``."""
    log_fn = log_fn or _log_noop
    graph = hidream_graph(
        prompt, width=width, height=height, seed=seed, negative=negative, prefix=f'kids/hd_{uuid.uuid4().hex[:6]}'
    )
    if not _attest(graph, 'hidream_still', log_fn):
        return False
    try:
        paths = _submit(graph, timeout_s=timeout_s, should_abort=should_abort, log_fn=log_fn)
    except LTXHiDreamError as e:
        log_fn(f'hidream: {e}')
        return False
    if not paths:
        log_fn('hidream: no output file')
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    shutil.copy2(paths[0], out_path)
    try:
        os.remove(paths[0])
    except OSError as _exc:
        _zyg_log.debug('comfy output %s removal skipped: %s', paths[0], _exc)
    return os.path.isfile(out_path)


# ── LTX-2.5 image-to-video ───────────────────────────────────────────────────


def ltx_graph(image_name, prompt, *, seconds=3, seed=0, aspect=None, megapixels=None, prefix='video/kids', unet=None):
    """The official LTX-2.5 I2V template (two-stage, 8 distilled steps) with the kids inputs."""
    with open(LTX_GRAPH, 'r', encoding='utf-8') as fh:
        g = json.load(fh)
    for _k, e in g.items():
        ct = e.get('class_type')
        if ct == 'LoadImage':
            e['inputs']['image'] = image_name
        elif ct == 'ResolutionSelector':
            e['inputs']['aspect_ratio'] = aspect or LTX_ASPECT
            e['inputs']['megapixels'] = float(megapixels or LTX_MEGAPIXELS)
        elif ct == 'SaveVideo':
            e['inputs']['filename_prefix'] = prefix
        elif ct == 'PrimitiveStringMultiline':
            e['inputs']['value'] = prompt
        elif ct == 'RandomNoise':
            e['inputs']['noise_seed'] = int(seed) & 0xFFFFFFFFFFFF
        elif ct == 'UNETLoader':
            e['inputs']['unet_name'] = unet or LTX_UNET
    # sg362 is the duration primitive (seconds, integer) of the flattened template.
    if 'sg362' in g:
        g['sg362']['inputs']['value'] = max(1, int(round(seconds)))
    return g


def ltx_i2v(
    image_path,
    prompt,
    out_mp4,
    *,
    seconds=3,
    seed=0,
    aspect=None,
    megapixels=None,
    log_fn=None,
    should_abort=None,
    timeout_s=900.0,
) -> bool:
    """A still → a short LTX-2.5 clip with its own audio track.  Call inside ``gpu_lease``."""
    log_fn = log_fn or _log_noop
    try:
        name = stage_input(image_path)
    except LTXHiDreamError as e:
        log_fn(f'ltx: {e}')
        return False
    graph = ltx_graph(
        name,
        prompt,
        seconds=seconds,
        seed=seed,
        aspect=aspect,
        megapixels=megapixels,
        prefix=f'video/kids_{uuid.uuid4().hex[:6]}',
    )
    if not _attest(graph, 'ltx_i2v', log_fn):
        return False
    try:
        paths = _submit(graph, timeout_s=timeout_s, should_abort=should_abort, log_fn=log_fn)
    except LTXHiDreamError as e:
        log_fn(f'ltx: {e}')
        return False
    finally:
        try:
            os.remove(os.path.join(INPUT_DIR, name))
        except OSError as _exc:
            _zyg_log.debug('staged input %s removal skipped: %s', name, _exc)
    mp4s = [p for p in paths if p.lower().endswith('.mp4')] or paths
    if not mp4s:
        log_fn('ltx: no output clip')
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    shutil.copy2(mp4s[0], out_mp4)
    try:
        os.remove(mp4s[0])
    except OSError as _exc:
        _zyg_log.debug('comfy clip %s removal skipped: %s', mp4s[0], _exc)
    return os.path.isfile(out_mp4)


def clip_seconds(slot_s: float, transition_s: float = 0.3, minimum: int = 2) -> int:
    """Whole seconds a clip must run to cover a slot (the assembly's compensated slot
    length already includes the xfade) plus a safety margin; never under 2 s because
    LTX needs 8n+1 frames and 49 frames at 24 fps is the shortest clean clip."""
    import math

    return max(minimum, int(math.ceil(float(slot_s) + float(transition_s))))
