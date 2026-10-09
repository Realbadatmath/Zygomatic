# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""What this install can do, and the VLM question channel — verbatim sections of the
former vfx_analyzer.py."""

import base64
import json
import os
import subprocess

from zyg_workflows.bin import exe
from zyg_workflows.vfx_analyzer.constants import (
    FFMPEG,
    FFPROBE,
    OLLAMA,
    TAXONOMY_PATH,
    VLM_MODEL,
    taxonomy,
)


# ── capability ───────────────────────────────────────────────────────────────


def capability():
    """What this install can actually do today. Printed into every run report:
    a blind spot that is stated is a blind spot the user can act on."""
    import importlib

    modules = {}
    for m in ('cv2', 'numpy', 'scipy', 'skimage', 'mediapipe'):
        try:
            mod = importlib.import_module(m)
            modules[m] = getattr(mod, '__version__', 'ok')
        except Exception as e:  # noqa: BLE001
            modules[m] = f'MISSING ({type(e).__name__})'
    cap = {'python': modules, 'binaries': {}, 'landmarks': {}, 'vlm': {}}
    for b, p in (('ffmpeg', FFMPEG), ('ffprobe', FFPROBE)):
        cap['binaries'][b] = p if os.path.isfile(p) else f'MISSING ({p})'
    try:
        from zyg_workflows import vfx_landmarks

        cap['landmarks'] = vfx_landmarks.available()
    except Exception as e:  # noqa: BLE001
        cap['landmarks'] = {'error': f'{type(e).__name__}: {e}'}
    cap['vlm'] = _vlm_available()
    try:
        from zyg_workflows import vfx_detectors

        reg = vfx_detectors.registry()
        cap['detectors'] = {'count': len(reg), 'ids': sorted(reg.keys())}
    except Exception as e:  # noqa: BLE001
        cap['detectors'] = {'error': f'{type(e).__name__}: {e}', 'count': 0, 'ids': []}
    try:
        from zyg_workflows import vfx_probes

        cap['probes'] = vfx_probes.capability()
    except Exception as e:  # noqa: BLE001
        cap['probes'] = {'error': f'{type(e).__name__}: {e}', 'probes': 0, 'shippable': 0}
    t = taxonomy()
    cap['taxonomy'] = {'count': t.get('count', 0), 'path': TAXONOMY_PATH, 'error': t.get('error', '')}
    return cap


def _free_vram_mb():
    """Free VRAM, or None if it cannot be read. Not a hard gate — just the
    difference between a useful warning and a mystery 500."""
    try:
        out = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        vals = [int(x.strip()) for x in out.stdout.split('\n') if x.strip().isdigit()]
        return max(vals) if vals else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _vlm_available():
    """Is the VLM tier ACTUALLY usable right now?

    'The model is listed' and 'the model can load' are different facts, and
    reporting the first as readiness is the exact overclaiming this analyzer's
    ledger exists to prevent. Measured case: /api/tags listed qwen2.5vl and
    every generate call returned 500, because ComfyUI was holding 44 GB of a
    48 GB card. The capability line said "VLM ready" the whole time.

    So: listed AND enough free VRAM to plausibly load it. The check is cheap
    (no generation) and its uncertainty is stated rather than hidden."""
    import urllib.error

    from zyg_workflows.net import safe_urlopen

    try:
        with safe_urlopen(f'{OLLAMA}/api/tags', timeout=3) as r:
            tags = json.loads(r.read().decode('utf-8') or '{}')
        models = tags.get('models') or []
        names = [m.get('name', '') for m in models]
        listed = VLM_MODEL in names
        size_mb = 0
        for m in models:
            if m.get('name') == VLM_MODEL:
                size_mb = int((m.get('size') or 0) / 1e6)
        free = _free_vram_mb()
        note, ok = '', listed
        if not listed:
            note = f'{VLM_MODEL} not pulled'
        elif free is not None and size_mb and free < size_mb * 1.15:
            ok = False
            note = (
                f'{VLM_MODEL} needs ~{size_mb} MB but only {free} MB of VRAM is free — '
                f'another process (usually ComfyUI) is holding the card. Ollama will '
                f'return HTTP 500 "model failed to load" until it is freed.'
            )
        elif free is not None:
            # Loading can still fail for a reason VRAM headroom does not predict:
            # ollama allocates OLLAMA_NUM_PARALLEL x num_ctx of KV cache before
            # it will load anything, and this model declares a 128k context.
            # vlm_ask pins num_ctx for exactly this reason; say so here so a
            # future 500 is diagnosed in seconds rather than blamed on the GPU.
            note = (
                f'ok — vlm_ask pins num_ctx={os.environ.get("ZYG_VFX_VLM_CTX", 4096)}; '
                f"without that, OLLAMA_NUM_PARALLEL x the model's 128k context "
                f'fails to allocate even with VRAM free'
            )
        return {
            'ok': ok,
            'listed': listed,
            'model': VLM_MODEL,
            'model_mb': size_mb,
            'free_vram_mb': free,
            'available_models': names,
            'note': note,
            'probe': 'listed + VRAM headroom; no generation was attempted',
        }
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {
            'ok': False,
            'listed': False,
            'model': VLM_MODEL,
            'available_models': [],
            'note': f'ollama unreachable at {OLLAMA}: {e}',
        }


# Questions that must NEVER be asked on a crop. See vlm_ask's docstring.
FULL_FRAME_ONLY = (
    'camera.',
    'lighting.direction',
    'lighting.key',
    'scene_semantics.shot',
    'editing_time.',
    'interaction_social.prox',
)


def vlm_ask(image_path, question, timeout=90, scope='crop'):
    """Ask the local VLM one closed question about one image.

    THE CROP RULE, AND ITS LIMIT (both measured on this project)
    -----------------------------------------------------------
    The original rule holds: a small VLM answers reliably about a tight crop and
    confabulates about a full frame. But it is PROPERTY-SCOPED, and the limit was
    measured here on qwen2.5vl, 5 repeats at temperature 0, full frame vs crop:

        LOCAL   eyes open/closed     full=open      crop=open      agree
        LOCAL   mouth open/closed    full=closed    crop=closed    agree
        GLOBAL  camera angle         full=eye level crop=above     DISAGREE
        GLOBAL  light direction      full=right     crop=left      DISAGREE
        GLOBAL  shot size            full=medium    crop=close-up  DISAGREE

    Every answer was STABLE across repeats and the global ones were still wrong:
    repeatability is not correctness. The reason is structural, not a model flaw —
    camera angle, shot size and light direction are properties OF THE FRAMING, and
    a crop is a new framing. Cropping does not reveal the answer, it replaces it.

    So: ask LOCAL properties (is this thing open/closed/present/defective) on a
    tight crop; ask GLOBAL properties (framing, camera, light direction, spatial
    relationships) on the WHOLE frame. Passing scope='full' documents that choice
    at the call site and is checked against FULL_FRAME_ONLY by the detector layer.

    num_ctx is pinned — see the payload comment; omitting it is a hard load failure.
    """
    import urllib.error
    import urllib.request
    from urllib.parse import urlsplit

    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
    except OSError as e:
        return {'ok': False, 'error': f'crop unreadable: {e}'}
    # num_ctx is NOT optional here. qwen2.5vl declares a 128k context, and this
    # host runs OLLAMA_NUM_PARALLEL=3, so omitting it makes ollama try to
    # allocate THREE 128k KV caches up front — the model then fails to load with
    # a generic HTTP 500 "resource limitations", on a card with 30 GB free.
    # One closed question about one crop needs a few thousand tokens at most.
    payload = json.dumps(
        {
            'model': VLM_MODEL,
            'prompt': question,
            'images': [b64],
            'stream': False,
            'options': {'temperature': 0.0, 'num_predict': 64, 'num_ctx': int(os.environ.get('ZYG_VFX_VLM_CTX', 4096))},
        }
    ).encode('utf-8')
    gen_url = f'{OLLAMA}/api/generate'
    # net.safe_urlopen cannot carry the JSON Content-Type header Ollama's POST needs, so the
    # scheme audit S310/B310 asks for is done here instead, on the only URL this call can reach.
    if urlsplit(gen_url).scheme not in ('http', 'https'):
        return {'ok': False, 'error': f'refusing to POST to {gen_url!r}: only http/https'}
    req = urllib.request.Request(gen_url, data=payload, headers={'Content-Type': 'application/json'})  # noqa: S310  scheme checked on the line above  # nosec B310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  scheme checked above  # nosec B310
            out = json.loads(r.read().decode('utf-8') or '{}')
        return {'ok': True, 'answer': str(out.get('response', '')).strip()}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
