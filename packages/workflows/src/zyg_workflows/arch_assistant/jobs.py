# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Jobs, the run loop, the hero picture, the Blender hand-off and the HTTP glue.

Moved verbatim out of the old single-file arch_assistant.py (lines 3846-4336).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid

from zyg_workflows import arch_blend_store as BSTORE  # retention: nothing here ever read a build back

from zyg_workflows.arch_assistant._base import ARCH_DIR, BLEND_DIR, HERE, _zyg_log

from zyg_workflows.arch_assistant.ledger import _close_orphans

# ── jobs ────────────────────────────────────────────────────────────────────
JOBS: dict[str, dict] = {}
_JLOCK = threading.Lock()
_JOB_TTL = 3600


def _gc():
    now = time.time()
    with _JLOCK:
        for k in [k for k, j in JOBS.items() if now - j['t0'] > _JOB_TTL]:
            JOBS.pop(k, None)


def _job_view(j: dict) -> dict:
    out = {
        k: j.get(k)
        for k in (
            'id',
            'status',
            'phase',
            'question',
            'error',
            'need',
            'steps',
            'backend',
            'usage',
            'reply',
            'session',
            'model',
            'thinking',
            'think_s',
            'reply_live',
            'auth',
            'incomplete',
            'stop',
        )
    }
    out['draw_calls'] = int(j.get('_draw_calls') or 0)
    out['budget'] = MAX_CALLS
    out['thoughts_n'] = len(j.get('thoughts') or [])
    if j['status'] in ('done', 'question', 'error'):  # the whole list only once, with the answer
        out['thoughts'] = j.get('thoughts') or []
    out['log'] = j['log'][-40:]
    out['elapsed'] = round(time.time() - j['t0'], 1)
    if j['status'] == 'done' and j.get('result') is not None:
        out['result'] = j['result']
    return out


def start_job(body: dict) -> dict:
    """POST /assistant/start — begin one request. Returns {ok, id}."""
    _gc()
    text = str(body.get('text') or '').strip()
    if not text:
        return {'ok': False, 'error': 'empty request'}
    jid = uuid.uuid4().hex[:12]
    job = {
        'id': jid,
        'status': 'running',
        'phase': 'drawing',
        'log': [],
        't0': time.time(),
        'steps': 0,
        'question': None,
        'error': None,
        'need': None,
        'result': None,
        'reply': '',
        'backend': str(body.get('backend') or 'claude'),
        'cancel': False,
        'usage': None,
        'session': None,
        'model': None,
        'thinking': '',
        'thoughts': [],
        'think_s': 0.0,
        'reply_live': '',
        'auth': None,
        'incomplete': False,
        'stop': None,
        '_render': None,
        '_ev': threading.Event(),
        '_proc': None,
        '_token': None,
        '_d': None,
        '_final': '',
        '_draw_calls': 0,
        'body': body,
    }
    with _JLOCK:
        JOBS[jid] = job
    _conv_start(job)
    threading.Thread(target=_run, args=(job,), name=f'arch-assist-{jid}', daemon=True).start()
    return {'ok': True, 'id': jid}


def job_status(jid: str) -> dict:
    j = JOBS.get(str(jid or ''))
    if not j:
        return {'ok': False, 'error': 'no such job'}
    v = _job_view(j)
    v['ok'] = True
    return v


def provide_render(body: dict) -> dict:
    """POST /assistant/render — the studio answers a `look`."""
    j = JOBS.get(str(body.get('id') or ''))
    if not j:
        return {'ok': False, 'error': 'no such job'}
    j['_render'] = body.get('image') or ''
    j['need'] = None
    j['_ev'].set()
    return {'ok': True}


def cancel_job(body: dict) -> dict:
    j = JOBS.get(str(body.get('id') or ''))
    if not j:
        return {'ok': False, 'error': 'no such job'}
    j['cancel'] = True
    j['_ev'].set()
    if j.get('_proc') is not None:
        _kill(j['_proc'])
    return {'ok': True}


def _run_loop(job: dict, d: Drawing, m, log, backend: str, system: str):
    """The in-process tool loop for the API / Ollama backends (dormant since
    2026-09-07; the CLI backend runs the loop inside Claude Code). Returns the
    final text, or None when the model asked the user a question."""
    log(f'{backend}: thinking about the request')
    final = ''
    for n in range(MAX_CALLS):
        if job['cancel']:
            raise RuntimeError('cancelled')
        job['steps'] = n + 1
        text, calls, stop = m.step(system, TOOL_DEFS)
        if text:
            job['reply'] = text
            log('assistant: ' + text[:200])
        if not calls:
            if stop == 'max_tokens':
                raise RuntimeError('the model ran out of output tokens')
            final = text
            break
        items = []
        finished = False
        for c in calls:
            name, args = c['name'], c['args']
            if name == 'ask_user':
                job['question'] = str(args.get('question') or text or 'What do you mean?')
                job['status'] = 'question'
                job['phase'] = 'question'
                job['usage'] = m.usage
                log('question: ' + job['question'][:200])
                return None
            if name == 'done':
                refusal = design_gate(job, d, args, log)
                if refusal:
                    items.append((c['id'], refusal, None))
                    continue
                final = str(args.get('summary') or text or 'Done.') + design_note(job)
                items.append((c['id'], 'ok', None))
                finished = True
                continue
            if name == 'look':
                job['need'] = {
                    'kind': 'render',
                    'view': args.get('view') or 'iso',
                    'storey': args.get('storey'),
                    'cells': bool(args.get('cells')),
                    'doc': d.to_doc(),
                }
                job['status'] = 'need_client'
                job['_ev'].clear()
                log(
                    f'look: {args.get("view")} view'
                    + (f' storey {args.get("storey")}' if args.get('storey') is not None else '')
                )
                got = job['_ev'].wait(120)
                job['status'] = 'running'
                if job['cancel']:
                    raise RuntimeError('cancelled')
                img = _img_parts(job.get('_render') or '') if got else None
                items.append((c['id'], 'here is the view' if img else 'the studio did not answer with a picture', img))
                continue
            arg_txt = ', '.join(f'{k}={v}' for k, v in list(args.items())[:6])
            log(f'{name}({arg_txt[:160]})')
            res = call_tool(d, name, args)
            img = None
            if isinstance(res, tuple):  # (text, data_url): a tool that hands back a picture
                res, img = str(res[0]), _img_parts(res[1] if len(res) > 1 else '')
            res = str(res)
            log('  ' + res[:200])
            items.append((c['id'], res, img))
        m.results(items)
        if finished:
            break
    else:
        raise RuntimeError(f'stopped after {MAX_CALLS} steps without finishing')
    job['usage'] = m.usage
    return final


# ── the hero picture (2026-09-16) ────────────────────────────────────────────
# The preview the operator is handed after a build used to be one of present()'s
# 800 px EEVEE JPEGs, inlined as a data URL. This renders the finished drawing
# once more with CYCLES on the GPU at 4K and hands the panel a URL instead: a 4K
# PNG is 10-20 MB and would never survive the chat panel's localStorage.
RENDER_DIR = os.path.join(ARCH_DIR, 'renders')


def _hero_pass(job: dict, d, log) -> list:
    """The photoreal frames as image records, or [] — never raises. Off with
    ZYG_ARCH_HERO=0."""
    if os.environ.get('ZYG_ARCH_HERO', '1') == '0' or not d.objs or job.get('cancel'):
        return []
    bp = EXT_MODULES.get('blender_power')
    if bp is None or not hasattr(bp, 'hero_render'):
        return []
    job['phase'] = 'hero'
    log('hero: rendering photoreal 4K preview (Cycles)…')
    try:
        hero = bp.hero_render(d, job['id'])
    except Exception as e:  # noqa: BLE001 — a missing hero is not a failed request
        log(f'hero: not rendered ({type(e).__name__}: {str(e)[:160]})')
        return []
    for h in hero:
        log(
            f'hero: {h.get("title")} {h.get("samples")} samples on {h.get("device")} '
            f'{h.get("backend")} in {h.get("seconds")}s, {int(h.get("bytes") or 0) // 1024} KB'
        )
    try:
        return bp.hero_images(hero)
    except Exception as e:  # noqa: BLE001
        log(f'hero: could not publish ({type(e).__name__}: {str(e)[:120]})')
        return []


def _picture(name: str):
    """GET /assistant/picture?f= — one hero render, by BASENAME, out of
    RENDER_DIR and nowhere else. Returns (bytes, mime) or ({'error'}, code)."""
    base = os.path.basename(str(name or ''))
    if not base or base != str(name or '') or '..' in base or '/' in base or '\\' in base:
        return {'error': 'f must be a bare file name'}, 400
    mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}.get(os.path.splitext(base)[1].lower())
    if not mime:
        return {'error': 'not a picture'}, 400
    path = os.path.join(RENDER_DIR, base)
    if os.path.realpath(os.path.dirname(path)) != os.path.realpath(RENDER_DIR) or not os.path.isfile(path):
        return {'error': 'no such picture'}, 404
    with open(path, 'rb') as fh:
        return (fh.read(), mime), 200


def _run(job: dict):
    body = job['body']

    def log(line):
        job['log'].append(str(line)[:300])

    try:
        au = _audit()
        if au:  # the audit is per-thread context; this IS the thread
            au.set_context(pipeline_id='arch_assistant', stage='arch_assistant', pipeline_type='architecture')
        backend = pick_backend(job['backend'], log)
        job['backend'] = backend
        defaults = body.get('defaults') or {}
        d = Drawing(body.get('doc'), _num(defaults.get('wall_h'), STOREY_M), _num(defaults.get('wall_t'), WALL_T))
        d.name = str(body.get('name') or d.name)
        d.request = str(body.get('text') or '')  # the request's own words, for the checks that read them
        state = body.get('state') or {}
        ctx = [f'Current drawing "{d.name}": ' + d.summary().replace('\n', ' | ')]
        ctx.append(
            f'Drawing plane: storey {int(_num(state.get("storey"), 0))}. '
            f'Cell labels {"ON" if state.get("cells") else "off"}. '
            f'View: {state.get("view") or "perspective"}.'
            + (f' Selected: {", ".join(map(str, state.get("selected") or []))}.' if state.get('selected') else '')
        )
        # 2026-09-23: the reference model the operator has open. Without this the
        # assistant only learns a reference exists if it thinks to go looking,
        # and "build the ship from my pictures" names no tool at all.
        try:
            from zyg_workflows import arch_reference as _ref

            _cur = _ref.resolve('')
            if _cur is not None:
                ctx.append(
                    'Reference model open in the rail beside the chat panel: '
                    + _ref.brief(_cur, verbose=False)
                    + ' — view_reference() shows you its pictures.'
                )
        except Exception as _exc:  # noqa: BLE001 — a missing store must not stop a drawing
            _zyg_log.debug('reference-model context unavailable: %s', _exc)
        user_text = '\n'.join(ctx) + '\n\nRequest: ' + str(body['text']).strip()
        brief = str(body.get('brief') or '').strip()  # 2026-09-17 contest: a planner's brief rides beside the request
        if brief:
            user_text += (
                '\n\nBUILD BRIEF from your lead architect (follow it; when a tool result contradicts it, '
                'trust the tool result and adapt):\n' + brief
            )
            log(f'brief: {len(brief)} chars from the planner')
        image = _img_parts(body.get('screenshot'))
        system = system_prompt(d.storey_h, str(body.get('text') or ''), d)
        log(
            f'prompt: {len(LAST_PROMPT_INFO.get("kept") or [])} families in, '
            f'{len(LAST_PROMPT_INFO.get("dropped") or [])} out, {LAST_PROMPT_INFO.get("chars", 0) // 1000}k chars'
        )
        if backend == 'claude':
            final = _run_cli(job, d, log, user_text, image, system)
            if job.get('question'):
                job['status'] = 'question'
                job['phase'] = 'question'
                return
        else:
            m = _Anthropic(log) if backend == 'anthropic' else _Ollama(log)
            m.history(body.get('history') or [])
            m.user(user_text, image)
            final = _run_loop(job, d, m, log, backend, system)
            if final is None:
                return
        notes = [l[6:] for l in job['log'] if l.startswith('NOTE: ')]
        images = (_hero_pass(job, d, log) + d.images)[:6]
        job['result'] = {
            'doc': d.to_doc(),
            'added': d.added,
            'removed': d.removed,
            'changed': d.changed_ids(),
            'ui': d.ui[:40],
            'images': images,
            'select': d.selected[:200],
            'summary': (final or job['reply'] or 'Done.') + ''.join('\n(' + n + ')' for n in notes),
        }
        job['reply'] = final or job['reply']
        job['phase'] = 'injecting'
        job['status'] = 'done'
        log(f'done: +{len(d.added)} −{len(d.removed)} ~{len(job["result"]["changed"])}')
    except Exception as e:  # noqa: BLE001 — the panel shows it
        job['error'] = str(e)[:400]
        job['status'] = 'error'
        job['phase'] = 'error'
        log('error: ' + job['error'])
        au = _audit()
        if au:  # the ledger of failures, not only of successes
            try:
                au.record(
                    source='claude_code' if job.get('backend') == 'claude' else job.get('backend'),
                    direction='error',
                    llm=job.get('model'),
                    backend=job.get('backend'),
                    error=job['error'],
                    session_id=job.get('session'),
                    steps=job.get('steps'),
                    request=str(body.get('text') or '')[:500],
                )
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('assistant ledger error record failed for job %s: %s', job.get('id'), _exc)
    finally:
        _conv_end(job)


# ── Blender hand-off ─────────────────────────────────────────────────────────
def start_blender(body: dict) -> dict:
    """POST /assistant/blender — rebuild the drawing in Blender, headless."""
    doc = body.get('doc') or {}
    if not isinstance(doc.get('objects'), list) or not doc['objects']:
        return {'ok': False, 'error': 'nothing to send — the drawing is empty'}
    script = os.path.join(HERE, 'arch_blender_build', '__main__.py')
    if not os.path.exists(script):
        return {'ok': False, 'error': 'arch_blender_build.py is missing'}
    blender = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')
    if not os.path.exists(blender):
        return {'ok': False, 'error': f'Blender not found at {blender}'}
    os.makedirs(BLEND_DIR, exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', str(doc.get('name') or 'drawing').lower()).strip('-') or 'drawing'
    stamp = time.strftime('%Y%m%d-%H%M%S')
    base = os.path.join(BLEND_DIR, f'{slug}-{stamp}')
    src = base + '.json'
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)
    jid = 'b' + uuid.uuid4().hex[:11]
    job = {
        'id': jid,
        'status': 'running',
        'phase': 'blender',
        'log': [f'blender: {len(doc["objects"])} objects'],
        't0': time.time(),
        'steps': 0,
        'question': None,
        'error': None,
        'need': None,
        'result': None,
        'reply': '',
        'backend': 'blender',
        'cancel': False,
        'usage': None,
        '_ev': threading.Event(),
    }
    with _JLOCK:
        JOBS[jid] = job

    def run():
        cmd = [blender, '-b', '--python', script, '--', '--in', src, '--out', base + '.blend']
        if body.get('glb', True):
            cmd += ['--glb', base + '.glb']
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            last = ''
            for line in (p.stdout or '').splitlines()[::-1]:
                if line.startswith('{'):
                    last = line
                    break
            info = json.loads(last) if last else {}
            if p.returncode != 0 or not info.get('ok'):
                raise RuntimeError(
                    info.get('error') or (p.stderr or p.stdout or '')[-300:] or f'blender exit {p.returncode}'
                )
            job['result'] = {
                'blend': base + '.blend',
                'glb': info.get('glb'),
                'objects': info.get('objects'),
                'skipped': info.get('skipped'),
            }
            job['reply'] = f'Blender file written: {base}.blend ({info.get("objects")} objects)'
            job['log'].append(job['reply'])
            job['status'] = 'done'
            job['phase'] = 'done'
            # this hand-off .blend is a deliverable, so it is protected here and
            # carries no document signature — only the byte cap ever prunes it
            BSTORE.sweep(protect=[base + '.blend'])
        except Exception as e:  # noqa: BLE001
            job['error'] = str(e)[:400]
            job['status'] = 'error'
            job['phase'] = 'error'
            job['log'].append('error: ' + job['error'])

    threading.Thread(target=run, name=f'arch-blender-{jid}', daemon=True).start()
    return {'ok': True, 'id': jid, 'blend': base + '.blend'}


# ── HTTP glue (kanban_server calls these) ────────────────────────────────────
PREFIX = '/inspect/api/architecture/assistant'
BODY_LIMIT = 24 << 20  # a drawing plus a screenshot


def handle_get(path: str, q: dict):
    if path == PREFIX + '/job':
        return job_status(q.get('id', '')), 200
    if path == PREFIX + '/tools':
        out = shim_tools(q)
        return out, (200 if out.get('ok') else 403)
    if path == PREFIX + '/log':
        return conversations(q.get('n') or 50, q.get('day') or ''), 200
    if path == PREFIX + '/active':
        return active_jobs(), 200
    if path == PREFIX + '/picture':
        return _picture(q.get('f', ''))
    if path == PREFIX + '/info':
        _load_env()
        return {
            'ok': True,
            'backend': 'claude' if cli_available() else 'auto',
            'cli': {'bin': CLI_BIN, 'model': _cli_model(), 'available': cli_available(), 'login': cli_login_present()},
            'anthropic': bool(os.environ.get('ANTHROPIC_API_KEY')),
            'anthropic_model': ANTHROPIC_MODEL,
            'local_model': OLLAMA_MODEL,
            'local_need_gb': OLLAMA_NEED_GB,
            'free_gb': round(free_vram_gb(), 1),
            'grid': {'n': GRID_N, 'cell_m': CELL_M, 'origin': ORIGIN},
        }, 200
    return {'error': 'not found'}, 404


def handle_post(path: str, body: dict):
    if path == PREFIX + '/start':
        out = start_job(body)
    elif path == PREFIX + '/render':
        out = provide_render(body)
    elif path == PREFIX + '/cancel':
        out = cancel_job(body)
    elif path == PREFIX + '/tool':
        out = shim_tool(body)
    elif path == PREFIX + '/blender':
        out = start_blender(body)
    else:
        return {'error': 'not found'}, 404
    return out, (200 if out.get('ok') else 400)


_close_orphans()


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    ANTHROPIC_MODEL,
    CELL_M,
    CLI_BIN,
    GRID_N,
    MAX_CALLS,
    OLLAMA_MODEL,
    OLLAMA_NEED_GB,
    ORIGIN,
    STOREY_M,
    WALL_T,
    _num,
)
from zyg_workflows.arch_assistant.drawing import Drawing  # noqa: E402
from zyg_workflows.arch_assistant.walls import TOOL_DEFS  # noqa: E402
from zyg_workflows.arch_assistant.ground import EXT_MODULES  # noqa: E402
from zyg_workflows.arch_assistant.prompts import (  # noqa: E402
    LAST_PROMPT_INFO,
    call_tool,
    system_prompt,
)
from zyg_workflows.arch_assistant.backends import (  # noqa: E402
    _Anthropic,
    _Ollama,
    _audit,
    _img_parts,
    _load_env,
    free_vram_gb,
    pick_backend,
)
from zyg_workflows.arch_assistant.cli_backend import (  # noqa: E402
    _cli_model,
    _kill,
    _run_cli,
    cli_available,
    cli_login_present,
)
from zyg_workflows.arch_assistant.gate import (  # noqa: E402
    design_gate,
    design_note,
    shim_tool,
    shim_tools,
)
from zyg_workflows.arch_assistant.ledger import (  # noqa: E402
    _conv_end,
    _conv_start,
    active_jobs,
    conversations,
)
