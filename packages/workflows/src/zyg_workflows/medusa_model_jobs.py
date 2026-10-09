#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Models tab's background chain: caption -> train -> switch on -> sample.

Everything here runs off the request thread. bp_medusa_models starts a chain
with start_pipeline() and the board reads progress back through state().

WHY CAPTIONING IS PART OF TRAINING
    lora_trainer_service writes SimpleTuner's data backend with
    caption_strategy='textfile', and SimpleTuner's
    prepare_instance_prompt_from_textfile RAISES FileNotFoundError for any image
    without a .txt beside it. The Models tab ingests bare images (uploads, links,
    folders), so without this step every run would die after ~9 minutes of
    model loading.

WHY DESCRIPTIVE CAPTIONS, NOT A TRIGGER TOKEN
    A character LoRA wants trigger-first captions: the trigger is how a render
    asks for that person. A BASE LoRA is the opposite case. It attaches to every
    Medusa render and those prompts never carry a trigger, so what it learns has
    to bind to the ordinary words people actually type. Each image gets a plain
    visual description from a local vision model, with the model's optional
    caption_prefix in front (the one thing guaranteed to be in every caption).

CAPTIONS PASS THE AGE FLOOR TOO
    Vision models routinely call adult women "girl". A caption that pairs a
    minor-coded word with explicit training images would teach the model exactly
    the association the age floor exists to prevent. So captions are normalised
    (girl -> woman, boy -> man) and then run through medusa_age_gate; any that
    still trip are replaced by the prefix-only caption and counted as flagged.
    This is an age rule only; nothing here softens or censors adult content.

SAMPLES
    When training finishes, the chain renders ONE picture from a caption of the
    model's own training set, with the adapter on, plus the same prompt and seed
    on the stock base so the difference is visible. Both run in a child process
    (importing comfy_generation_service loads CLIP at import time).
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import subprocess
import sys
import threading
import time

from zyg_workflows import medusa_age_gate as age_gate
from zyg_workflows import paths
from zyg_workflows import medusa_model_lora as mml
from zyg_workflows.net import safe_urlopen
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_PY = os.path.abspath(os.path.join(_CREWS_DIR, os.pardir, '.venv', 'bin', 'python'))

OLLAMA = paths.ZYG_OLLAMA_URL
CAPTION_MODEL = os.environ.get('ZYG_MEDUSA_CAPTION_MODEL', 'qwen3.5:9b')
VICKY_ACTIVE_URL = os.environ.get('ZYG_VICKY_ACTIVE_URL', f'http://{paths.BIND_HOST}:5300/api/vicky/active')

SAMPLE_SIZE = int(os.environ.get('ZYG_MEDUSA_SAMPLE_PX', '1024'))
SAMPLE_TIMEOUT_S = 1200
WATCH_EVERY_S = 30

_CAPTION_PROMPT = (
    'Write one training caption for this image: a single comma-separated line of '
    'plain visual description (subject, body, clothing or lack of it, pose, setting, '
    'lighting, camera framing). Describe adults as woman or man. No preamble, no '
    'quotes, no judgement, max 60 words.'
)

# In-memory live state per model: {'phase','done','total','error','started'}.
# Survives nothing on purpose — meta.json carries what must survive a restart.
_STATE: dict[str, dict] = {}
_LOCK = threading.Lock()
_BUSY: set[str] = set()


def state(model_id: str) -> dict:
    with _LOCK:
        return dict(_STATE.get(model_id) or {})


def _set(model_id: str, **kw) -> None:
    with _LOCK:
        cur = _STATE.setdefault(model_id, {})
        cur.update(kw)
        cur['at'] = time.time()


def _log(msg: str) -> None:
    _zyg_log.info(f'[MedusaModels] {msg}')


# ── captions ─────────────────────────────────────────────────────────────────
_REFUSAL_RE = re.compile(
    r"\b(sorry|i can(?:'|no)t|i cannot|unable to|not able to|i won't|i will not|"
    r'inappropriate|explicit content|against (?:my|the) (?:policy|guidelines)|'
    r"can't (?:help|assist|describe))\b",
    re.IGNORECASE,
)

# Adult rewrites for the words vision models reach for when describing adults.
_ADULTIFY = (
    (r'\byoung girls\b', 'young women'),
    (r'\byoung girl\b', 'young woman'),
    (r'\bgirls\b', 'women'),
    (r'\bgirl\b', 'woman'),
    (r'\bboys\b', 'men'),
    (r'\bboy\b', 'man'),
    (r'\bladies\b', 'women'),
    (r'\blady\b', 'woman'),
)


def normalize_caption(text: str) -> str:
    t = str(text or '').strip().strip('"\'`')
    t = re.sub(r'^\s*(caption|training caption)\s*:\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t.replace('\n', ' ')).strip()
    for pat, rep in _ADULTIFY:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    words = t.split(' ')
    if len(words) > 80:
        t = ' '.join(words[:80])
    return t.strip(' ,')


def _ollama_caption(png_path: str, keep_alive: str = '5m') -> str:
    with open(png_path, 'rb') as fh:
        b64 = base64.b64encode(fh.read()).decode()
    body = json.dumps(
        {
            'model': CAPTION_MODEL,
            'prompt': _CAPTION_PROMPT,
            'images': [b64],
            'stream': False,
            'think': False,
            'keep_alive': keep_alive,
            'options': {'temperature': 0.2, 'num_predict': 160},
        }
    ).encode()
    with safe_urlopen(f'{OLLAMA}/api/generate', data=body, timeout=300) as resp:
        return str(json.load(resp).get('response') or '')


def _ollama_unload(model: str) -> None:
    try:
        body = json.dumps({'model': model, 'keep_alive': 0}).encode()
        safe_urlopen(f'{OLLAMA}/api/generate', data=body, timeout=30).read()
    except Exception as _exc:
        _zyg_log.debug('ollama unload request for %s skipped: %s', model, _exc)


def caption_dataset(model_id: str) -> dict:
    """Write a .txt beside every image that lacks one. Returns counts."""
    meta = mml.load_meta(model_id) or {}
    prefix = str(meta.get('caption_prefix') or '').strip().strip(',')
    d = mml.images_dir(model_id)
    if not d or not os.path.isdir(d):
        raise RuntimeError('dataset folder missing')
    todo = sorted(
        f
        for f in os.listdir(d)
        if re.match(r'^img_[0-9a-f]{12}\.png$', f) and not os.path.isfile(os.path.join(d, f[:-4] + '.txt'))
    )
    stats = {
        'written': 0,
        'fallback': 0,
        'flagged': 0,
        'flagged_files': [],
        'skipped_existing': sum(1 for f in os.listdir(d) if f.endswith('.txt')),
    }
    _set(model_id, phase='captioning', done=0, total=len(todo), error='')
    fallback = prefix or 'photo'
    for i, name in enumerate(todo, 1):
        raw, cap = '', ''
        try:
            raw = _ollama_caption(os.path.join(d, name))
        except Exception as exc:
            _log(f'{model_id}: caption call failed for {name}: {exc}')
        cap = normalize_caption(raw)
        why = ''
        if not cap or len(cap) < 12 or _REFUSAL_RE.search(cap):
            why = 'fallback'
            cap = ''
        if cap:
            try:
                age_gate.assert_adult_prompt(cap, field='caption')
            except age_gate.MedusaAgeError:
                why = 'flagged'
                cap = ''
        full = ', '.join(x for x in (prefix, cap) if x) or fallback
        with open(os.path.join(d, name[:-4] + '.txt'), 'w', encoding='utf-8') as fh:
            fh.write(full + '\n')
        stats['written'] += 1
        if why:
            stats[why] += 1
            if why == 'flagged':
                # The operator attested these images are adults; a vision model
                # describing one as a minor is exactly what they should look at.
                stats['flagged_files'].append({'file': name, 'said': raw.strip()[:200]})
        _set(model_id, done=i)
    _ollama_unload(CAPTION_MODEL)
    return stats


# ── VRAM hand-off before training ────────────────────────────────────────────
def _vicky_idle() -> bool:
    try:
        with safe_urlopen(VICKY_ACTIVE_URL, timeout=5) as r:
            return int(json.load(r).get('running') or 0) == 0
    except Exception:
        # :5300 down => nothing of hers can be mid-turn.
        return True


def _free_ollama(model_id: str) -> None:
    """Unload resident Ollama models so training's ~36 GB fits.

    Only while Vicky is idle: unloading mid-reply would cut her turn off. Her
    memory is the chat store, not the loaded weights, so an unload costs her one
    ~20 s reload on the next message and nothing else. lora_trainer_service
    already evicts ComfyUI itself (try_evict) but knows nothing about Ollama.
    """
    deadline = time.time() + 600
    while not _vicky_idle() and time.time() < deadline:
        _set(model_id, phase='waiting', error='waiting for Vicky to finish a reply')
        time.sleep(10)
    try:
        with safe_urlopen(f'{OLLAMA}/api/ps', timeout=5) as r:
            loaded = [m.get('name') for m in (json.load(r).get('models') or [])]
    except Exception:
        loaded = []
    for m in loaded:
        if m:
            _ollama_unload(m)
            _log(f'{model_id}: unloaded ollama model {m} before training')


# ── the chain ────────────────────────────────────────────────────────────────
def start_pipeline(model_id: str, steps: int = 0) -> bool:
    """Caption, free VRAM, start training. False if this model is already busy."""
    with _LOCK:
        if model_id in _BUSY:
            return False
        _BUSY.add(model_id)
    threading.Thread(target=_run_pipeline, args=(model_id, steps), name=f'mdm-pipe-{model_id}', daemon=True).start()
    return True


def _run_pipeline(model_id: str, steps: int) -> None:
    try:
        meta = mml.load_meta(model_id) or {}
        fam = mml.normalize_family(meta.get('family'))
        age_gate.require_attestation(meta, what='this dataset')

        stats = caption_dataset(model_id)
        meta = mml.load_meta(model_id) or meta
        meta['captions'] = dict(stats, at=time.time())
        mml.save_meta(model_id, mml.touch(meta))

        _set(model_id, phase='freeing', error='')
        _free_ollama(model_id)

        _set(model_id, phase='starting')
        from zyg_workflows import lora_trainer_service as lts

        trainer = lts.get_trainer()
        trainer.start_training(
            model_id,
            mml.images_dir(model_id),
            trigger_token=str(meta.get('trigger') or ''),
            model_family=fam,
            output_root=mml.MODEL_OUTPUT_ROOT,
            **({'total_steps': steps} if steps > 0 else {}),
        )
        res = lts.last_start_result(model_id) or {}
        if not res.get('started', True):
            raise RuntimeError(f'trainer refused: {res.get("reason") or "unknown"}')

        meta = mml.load_meta(model_id) or meta
        meta['last_train_started'] = time.time()
        # The watcher picks the rest up from here: switch on, then sample. It
        # reads this flag from DISK, so a crews restart mid-training still ends
        # with a sample instead of a silently skipped one.
        meta['awaiting_sample'] = True
        meta.pop('sample', None)
        mml.save_meta(model_id, mml.touch(meta))
        _set(model_id, phase='training', error='')
    except Exception as exc:
        _log(f'{model_id}: pipeline failed: {exc}')
        _set(model_id, phase='failed', error=str(exc)[:400])
    finally:
        with _LOCK:
            _BUSY.discard(model_id)


# ── samples ──────────────────────────────────────────────────────────────────
_SAMPLE_CHILD = r"""
import json, os, sys, time
spec = json.loads(os.environ['ZYG_MDM_SAMPLE'])
from zyg_workflows import comfy_generation_service as c
out = {}
for which in ('lora', 'base'):
    kw = {'medusa_base_lora': spec['base_lora']} if which == 'lora' else {}
    t0 = time.time()
    ok, backend = c.generate_still(
        spec['paths'][which], spec['prompt'],
        width=spec['size'], height=spec['size'], steps=spec['steps'],
        cfg=spec['cfg'], seed=spec['seed'], model_family=spec['family'],
        skip_qa=True, prompt_finalized=True, solo_subject=False,
        human_subject=True, **kw)
    out[which] = {'ok': bool(ok) and os.path.isfile(spec['paths'][which]),
                  'backend': backend, 'seconds': round(time.time() - t0, 1)}
    print('SAMPLE', which, json.dumps(out[which]), flush=True)
print('RESULT ' + json.dumps(out), flush=True)
sys.exit(0 if out.get('lora', {}).get('ok') else 1)
"""

_FAMILY_STEPS = {'qwen': (20, 3.5), 'klein': (4, 1.0), 'sdxl': (30, 5.0)}


def _pick_training_caption(model_id: str, seed: int) -> str:
    d = mml.images_dir(model_id)
    caps = []
    if d and os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith('.txt'):
                try:
                    with open(os.path.join(d, f), encoding='utf-8') as fh:
                        t = fh.read().strip()
                    if t:
                        caps.append(t)
                except OSError as _exc:
                    _zyg_log.debug('caption file %s unreadable, skipped: %s', f, _exc)
    if not caps:
        return ''
    return random.Random(seed).choice(caps)


def generate_sample(model_id: str, prompt: str = '') -> dict:
    """Render the with/without pair. Blocking — call from a worker thread."""
    meta = mml.load_meta(model_id) or {}
    fam = mml.normalize_family(meta.get('family'))
    adapter = mml.adapter_path(model_id, fam)
    if not adapter:
        raise RuntimeError('no trained adapter on disk')
    seed = random.randint(1, 2**31 - 1)
    prompt = (
        prompt
        or str(meta.get('sample_prompt') or '').strip()
        or _pick_training_caption(model_id, seed)
        or 'photo of a woman'
    )
    age_gate.assert_adult_prompt(prompt, field='sample prompt')

    od = mml.output_dir(model_id)
    sd = os.path.join(od, 'samples')
    os.makedirs(sd, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    names = {'lora': f'{stamp}_lora.png', 'base': f'{stamp}_base.png'}
    steps, cfg = _FAMILY_STEPS.get(fam, (20, 3.5))
    spec = {
        'paths': {k: os.path.join(sd, v) for k, v in names.items()},
        'prompt': prompt,
        'seed': seed,
        'size': SAMPLE_SIZE,
        'family': fam,
        'steps': steps,
        'cfg': cfg,
        'base_lora': {'model_id': model_id, 'path': adapter, 'family': fam, 'scale': float(meta.get('scale') or 0.85)},
    }
    env = dict(os.environ)
    env['ZYG_MDM_SAMPLE'] = json.dumps(spec)
    env.setdefault('ZYG_COMFY_PRIMARY', '1')
    env.setdefault('ZYG_USE_COMFYUI', '1')
    env.setdefault('PYTHONUNBUFFERED', '1')
    py = _VENV_PY if os.access(_VENV_PY, os.X_OK) else sys.executable
    t0 = time.time()
    p = subprocess.run(
        [py, '-c', _SAMPLE_CHILD],
        cwd=_CREWS_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=SAMPLE_TIMEOUT_S,
    )
    result = {}
    for line in (p.stdout or '').splitlines():
        if line.startswith('RESULT '):
            try:
                result = json.loads(line[7:])
            except ValueError as _exc:
                _zyg_log.warning('sample result line did not parse, the sample record stays incomplete: %s', _exc)
    tail = '\n'.join((p.stdout or '').splitlines()[-12:])
    sample = {
        'prompt': prompt,
        'seed': seed,
        'at': time.time(),
        'seconds': round(time.time() - t0, 1),
        'lora': names['lora'] if (result.get('lora') or {}).get('ok') else '',
        'base': names['base'] if (result.get('base') or {}).get('ok') else '',
        'error': '' if (result.get('lora') or {}).get('ok') else f'render failed (exit {p.returncode}): {tail[-600:]}',
    }
    meta = mml.load_meta(model_id) or meta
    meta['sample'] = sample
    mml.save_meta(model_id, mml.touch(meta))
    return sample


def sample_async(model_id: str, prompt: str = '') -> bool:
    with _LOCK:
        if model_id in _BUSY:
            return False
        _BUSY.add(model_id)

    def run():
        try:
            _set(model_id, phase='sampling', error='')
            s = generate_sample(model_id, prompt)
            _set(model_id, phase='idle', error=s.get('error', ''))
        except Exception as exc:
            _log(f'{model_id}: sample failed: {exc}')
            meta = mml.load_meta(model_id) or {}
            meta['sample'] = {'error': str(exc)[:600], 'at': time.time(), 'prompt': prompt}
            mml.save_meta(model_id, mml.touch(meta))
            _set(model_id, phase='idle', error=str(exc)[:400])
        finally:
            with _LOCK:
                _BUSY.discard(model_id)

    threading.Thread(target=run, name=f'mdm-sample-{model_id}', daemon=True).start()
    return True


# ── watcher: training done -> switch on -> sample ────────────────────────────
def _train_status(model_id: str, fam: str) -> dict:
    try:
        from zyg_workflows import lora_trainer_service as lts

        return lts.get_trainer().get_status(model_id, model_family=fam, output_root=mml.MODEL_OUTPUT_ROOT) or {}
    except Exception:
        return {}


def _watch_once() -> None:
    for meta in mml.list_models():
        if not meta.get('awaiting_sample'):
            continue
        mid = meta.get('model_id', '')
        fam = mml.normalize_family(meta.get('family'))
        with _LOCK:
            if mid in _BUSY:
                continue
        st = _train_status(mid, fam)
        if st.get('failed'):
            meta['awaiting_sample'] = False
            meta['train_error'] = str(st.get('error') or 'training failed')[:400]
            mml.save_meta(mid, mml.touch(meta))
            _set(mid, phase='failed', error=meta['train_error'])
            continue
        if not st.get('done') or not mml.adapter_path(mid, fam):
            continue
        # Switch on automatically ONLY when nothing else is live on this family.
        # Silently swapping out a model the operator chose would change every
        # Medusa render under them with no action of theirs.
        if not mml.get_active_id(fam):
            try:
                age_gate.require_attestation(meta, what='this model')
                mml.set_active_id(fam, mid)
                meta['auto_activated'] = time.time()
                _log(f'{mid}: training done — switched on for {fam}')
            except age_gate.MedusaAgeError as exc:
                _log(f'{mid}: not switched on: {exc}')
        meta['awaiting_sample'] = False
        mml.save_meta(mid, mml.touch(meta))
        sample_async(mid)


def _watch_loop() -> None:
    while True:
        try:
            _watch_once()
        except Exception as exc:
            _log(f'watcher error: {exc}')
        time.sleep(WATCH_EVERY_S)


_WATCHER_STARTED = False


def start_watcher() -> None:
    global _WATCHER_STARTED
    with _LOCK:
        if _WATCHER_STARTED:
            return
        _WATCHER_STARTED = True
    threading.Thread(target=_watch_loop, name='mdm-watcher', daemon=True).start()
