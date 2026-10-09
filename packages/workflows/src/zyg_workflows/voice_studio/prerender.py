# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.prerender — pre-rendering a bank of presets.

Moved verbatim from voice_studio.py lines 2281-2436 (2026-10-06 split).
"""

from __future__ import annotations

import os
import shutil
import threading
import time

from zyg_workflows.voice_studio.constants import (
    MAX_PREVIEW_CHARS,
    RENDER_ROOT,
)
from zyg_workflows.voice_studio.policy import (
    voice,
)
from zyg_workflows.voice_studio.params import (
    defaults,
    sanitize,
)
from zyg_workflows.voice_studio.synthesis import (
    measure,
)
from zyg_workflows.voice_studio.presets import (
    list_presets,
)
from zyg_workflows.voice_studio.jobs import (
    _JOBS,
    _JOBS_LOCK,
    _RENDER_GATE,
    _job_log,
    _job_set,
    _produce_take,
    _prune_jobs,
    _sweep_old_renders,
    _take_put,
    _yield_to_interactive,
    job,
    take_cached,
)


# ──────────────────────────────────────────────────────── pre-rendering a bank
# Auditioning a preset bank used to mean pressing Render on every row and waiting
# ~11 s each. This walks the bank once, in the background, and fills the take
# cache; afterwards the browser plays each preset from disk.
#
# The gate is taken and released PER PRESET rather than held for the batch, so an
# operator who twists a knob mid-sweep waits for one preset, not eleven. And the
# pass never touches _LATEST: that is the live loop's supersede channel, and a
# batch that claimed it would cancel the very render the operator is waiting on.
def _preset_text(rec: dict, text: str) -> str:
    """The line a preset will actually be heard on. A preset that carries its own
    text replaces the audition line when it loads (starters deliberately do not),
    so the cache has to be keyed on the same line the browser will play — or every
    such preset would be pre-rendered on a line nobody ever hears."""
    return ((rec.get('text') or '').strip() or text)[:MAX_PREVIEW_CHARS]


def prerender_state(vid: str, text: str) -> dict:
    """Which of this voice's presets already have a take for this line."""
    v = voice(vid)
    if not v:
        raise ValueError('unknown voice')
    text = (text or v['default_text']).strip()[:MAX_PREVIEW_CHARS]
    ready, missing = {}, []
    for rec in list_presets(vid)['presets']:
        hit = take_cached(vid, _preset_text(rec, text), rec['params'])
        if hit:
            ready[rec['slug']] = hit
        else:
            missing.append(rec['slug'])
    running = ''
    with _JOBS_LOCK:
        for jid, j in _JOBS.items():
            if j.get('kind') == 'prerender' and j.get('voice') == vid and j.get('state') in ('queued', 'running'):
                running = jid
    return {
        'voice': vid,
        'text': text,
        'ready': ready,
        'missing': missing,
        'total': len(ready) + len(missing),
        'job': running,
        # The take at the DEFAULT knob positions — what the panel loads when
        # a voice is clicked, and what the library bake renders. Returning it
        # here is what lets a voice click play immediately instead of
        # arriving at a silent player with a Render button.
        'base': take_cached(vid, text, defaults()),
    }


def start_prerender(vid: str, text: str, force: bool = False) -> dict:
    v = voice(vid)
    if not v:
        raise ValueError('unknown voice')
    if not os.path.isfile(v['seed']):
        raise ValueError('frozen seed missing — nothing can be rendered')
    text = (text or v['default_text']).strip()[:MAX_PREVIEW_CHARS]
    if not text:
        raise ValueError('nothing to say')
    presets = list_presets(vid)['presets']
    if not presets:
        raise ValueError('this voice has no presets yet')
    state = prerender_state(vid, text)
    if state['job']:
        return job(state['job'])
    todo = [r for r in presets if force or r['slug'] in state['missing']]
    jid = f'p{int(time.time() * 1000):x}{os.getpid():x}'
    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'voice': vid,
            'kind': 'prerender',
            'state': 'queued',
            'log': [],
            'text': text,
            'items': [
                {
                    'slug': r['slug'],
                    'name': r.get('name', r['slug']),
                    'text': _preset_text(r, text),
                    'params': r['params'],
                }
                for r in todo
            ],
            'total': len(todo),
            'done': 0,
            'failed': 0,
            'current': '',
            'cancel': False,
            'error': '',
            'wav': '',
            'metrics': {},
            'started': time.time(),
            'finished': 0.0,
        }
        _prune_jobs()
    threading.Thread(target=_prerender_worker, args=(jid,), daemon=True).start()
    return job(jid)


def cancel_job(jid: str) -> bool:
    """Ask a pre-render to stop after the preset it is on. The engine subprocess
    is not killed: a half-written wav in the cache is worse than an extra 11 s."""
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if not j or j.get('state') not in ('queued', 'running'):
            return False
        j['cancel'] = True
    _job_log(jid, 'cancelling after the current preset…')
    return True


def _prerender_worker(jid: str):
    j = job(jid)
    vid, text = j['voice'], j['text']
    v = voice(vid)
    log = lambda m: _job_log(jid, m)  # noqa: E731
    _job_set(jid, state='running')
    _sweep_old_renders()
    log(f'pre-rendering {j["total"]} preset(s) on "{text[:48]}…"')
    stopped = False
    for i, item in enumerate(j['items']):
        if job(jid).get('cancel'):
            stopped = True
            break
        p = sanitize(item['params'])
        line = item.get('text') or text
        if take_cached(vid, line, p):  # a live render may have beaten us to it
            _job_set(jid, done=i + 1)
            continue
        _job_set(jid, current=item['name'])
        work = os.path.join(RENDER_ROOT, vid, f'{jid}_{i:02d}')
        _yield_to_interactive(lambda: bool(job(jid).get('cancel')))
        _RENDER_GATE.acquire()
        try:
            os.makedirs(work, exist_ok=True)
            log(f'[{i + 1}/{j["total"]}] {item["name"]}')
            final, _reused = _produce_take(vid, line, p, work, log)
            met = measure(final, age_class=v.get('age_class', ''), identity_ref=v.get('identity_ref', ''))
            _take_put(vid, line, p, final, met)
        except Exception as e:  # noqa: BLE001 — one bad preset must not stop the bank
            _job_set(jid, failed=job(jid).get('failed', 0) + 1)
            log(f'[{i + 1}/{j["total"]}] {item["name"]} FAILED: {str(e)[:160]}')
        finally:
            _RENDER_GATE.release()
            shutil.rmtree(work, ignore_errors=True)
        _job_set(jid, done=i + 1)
    st = job(jid)
    _job_set(jid, state='done', current='', finished=time.time())
    log(
        ('stopped — ' if stopped else 'done — ')
        + f'{st.get("done", 0)}/{st.get("total", 0)} cached'
        + (f', {st["failed"]} failed' if st.get('failed') else '')
    )
