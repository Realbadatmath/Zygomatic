# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character Studio — the Photoreal skin bake, server side (2026-09-19).

Three ops behind /inspect/api/studio/char_photoreal/:

  status   {body} -> what is published for that base body (manifest, albedo
           URL under the arch-asset route, render strip) plus the live job if
           one is running. Nothing is inferred: 'published' is the manifest
           file on disk, 'job' is job.json with a fresh heartbeat.
  start    POST {body, force?} -> spawns `char_photoreal.py <body> --job <dir>`
           under the server's own interpreter as a CHILD PROCESS, never in
           this thread: the bake imports comfy_generation_service (CLIP at
           import) and runs Blender for minutes, neither of which belongs in
           the GUI process. One bake at a time — a second start while one is
           live answers 409 with the running job's id.
  stop     POST {job} -> writes the ABORT file. The bake checks it between
           renders; a Blender pass already running finishes first.

The body id is fenced against char_photoreal.BODIES; the job id is fenced
against its own shape and must resolve to a direct child of the jobs root.
"""

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JOBS_ROOT = os.path.join(HERE, 'output', 'charstudio_jobs')
_JOB_RE = re.compile(r'^pr_[a-z0-9_]{4,40}$')
_STALE_S = 900


def _mod():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from zyg_workflows import char_photoreal

    return char_photoreal


def _job_dir(jid):
    if not _JOB_RE.match(str(jid or '')):
        return None
    d = os.path.realpath(os.path.join(_JOBS_ROOT, jid))
    if d != os.path.join(os.path.realpath(_JOBS_ROOT), jid):
        return None
    return d


def _read_job(jid):
    d = _job_dir(jid)
    if not d:
        return None
    try:
        with open(os.path.join(d, 'job.json'), encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    rec['job'] = jid
    return rec


def _live_job():
    now = time.time()
    try:
        names = [n for n in os.listdir(_JOBS_ROOT) if n.startswith('pr_')]
    except OSError:
        return None
    best = None
    for n in names:
        rec = _read_job(n)
        if not rec or rec.get('status') != 'running':
            continue
        if now - float(rec.get('heartbeat') or 0) > _STALE_S:
            continue
        if best is None or float(rec.get('started') or 0) > float(best.get('started') or 0):
            best = rec
    return best


def _published(body):
    cp = _mod()
    man = cp.published(body)
    if not man:
        return None
    base = '/inspect/arch-asset/photoreal/%s/' % body
    out = dict(man)
    # THE DE-HAIRED ATLAS WINS. klein paints eyebrows, stubble and scalp into
    # the photographs and the bake projects them into the skin; char_skin_dehair
    # takes them out again so char_hair.js can grow the real thing where they
    # were. Serving the original would leave a flat painted brow under a grown
    # one. `dehaired` travels with it — the client reads it to stop suppressing.
    _alb = man.get('albedo', 'albedo.jpg')
    if (
        man.get('dehaired')
        and man.get('albedo_nohair')
        and os.path.isfile(os.path.join(cp.PUB_ROOT, body, man['albedo_nohair']))
    ):
        _alb = man['albedo_nohair']
    out['albedo_used'] = _alb
    out['albedo_url'] = base + _alb
    # the panel's strip = klein's bake photos; the card's strip = the studio shots
    if man.get('klein_strip') or man.get('renders_strip'):
        out['strip_url'] = base + (man.get('klein_strip') or man['renders_strip'])
    if man.get('renders_strip'):
        out['card_strip_url'] = base + man['renders_strip']
    try:
        out['albedo_mtime'] = os.path.getmtime(os.path.join(cp.PUB_ROOT, body, _alb))
    except OSError:
        out['albedo_mtime'] = 0
    try:
        out['preview_mtime'] = os.path.getmtime(os.path.join(cp.PUB_ROOT, body, man.get('preview') or 'preview.jpg'))
    except OSError:
        out['preview_mtime'] = out['albedo_mtime']
    return out


def _status(payload, method):  # noqa: ARG001
    cp = _mod()
    body = str(payload.get('body') or '').strip()
    if body not in cp.BODIES:
        return {'error': 'unknown body %r' % body, 'code': 400, 'bodies': sorted(cp.BODIES)}
    jid = str(payload.get('job') or '').strip()
    job = _read_job(jid) if jid else None
    if job and job.get('status') == 'running' and time.time() - float(job.get('heartbeat') or 0) > _STALE_S:
        job['status'] = 'stale'
    live = _live_job()
    return {
        'ok': True,
        'body': body,
        'published': _published(body),
        'job': job,
        'live': {'job': live['job'], 'stage': live.get('stage', '')} if live else None,
        'bodies': sorted(cp.BODIES),
    }


def _start(payload, method):
    if method != 'POST':
        return {'error': 'POST', 'code': 405}
    cp = _mod()
    body = str(payload.get('body') or '').strip()
    if body not in cp.BODIES:
        return {'error': 'unknown body %r' % body, 'code': 400}
    live = _live_job()
    if live:
        return {'error': 'a bake is already running', 'code': 409, 'job': live['job']}
    jid = 'pr_%s_%s' % (body[:12], time.strftime('%m%d%H%M%S'))
    d = _job_dir(jid)
    os.makedirs(d, exist_ok=True)
    # char_photoreal is a package since 2026-10 (char_photoreal/__main__.py), so it runs as a module
    cmd = [sys.executable, '-m', 'zyg_workflows.char_photoreal', body, '--job', d]
    if payload.get('force'):
        cmd.append('--force')
    stage = str(payload.get('stage') or 'all')
    if stage != 'all':
        cmd += ['--stage', stage]
    env = dict(os.environ)
    env.setdefault('PYTHONUNBUFFERED', '1')
    env.setdefault('ZYG_COMFY_PRIMARY', '1')
    env.setdefault('ZYG_USE_COMFYUI', '1')
    with open(os.path.join(d, 'stdout.log'), 'ab') as out:
        p = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    with open(os.path.join(d, 'pid'), 'w') as fh:
        fh.write(str(p.pid))
    # a job.json before the child writes its own, so the poll never 404s
    if not os.path.isfile(os.path.join(d, 'job.json')):
        with open(os.path.join(d, 'job.json'), 'w', encoding='utf-8') as fh:
            json.dump(
                {'status': 'running', 'stage': 'starting', 'log': [], 'started': time.time(), 'heartbeat': time.time()},
                fh,
            )
    return {'ok': True, 'job': jid, 'body': body, 'pid': p.pid}


def _stop(payload, method):
    if method != 'POST':
        return {'error': 'POST', 'code': 405}
    jid = str(payload.get('job') or '').strip()
    d = _job_dir(jid)
    if not d or not os.path.isdir(d):
        return {'error': 'no such job', 'code': 404}
    with open(os.path.join(d, 'ABORT'), 'w') as fh:
        fh.write(str(time.time()))
    return {'ok': True, 'job': jid, 'note': 'ABORT written; the bake stops before its next render'}


_PREVIEWS = 'blender_human_base/_previews/'
_LABELS = {
    'male_realistic': 'Male · realistic',
    'female_realistic': 'Female · realistic',
    'male_stylized': 'Male · stylized',
    'female_stylized': 'Female · stylized',
}


def _variants(payload, method):  # noqa: ARG001
    """Every model the studio can stand in the frame, grouped by base body:
    the four CC0 base bodies themselves, and everything GENERATED FROM one of
    them — today the photoreal skins char_photoreal.py published. A variant
    is only listed when its files exist on disk; nothing is inferred."""
    cp = _mod()
    out = []
    for bid, rec in cp.BODIES.items():
        stem = rec['file'][:-4]
        prev = os.path.join(cp.PACK_DIR, '..', '_previews', stem + '_threequarter.png')
        front = os.path.join(cp.PACK_DIR, '..', '_previews', stem + '_front.png')
        out.append(
            {
                'id': bid,
                'kind': 'base',
                'base': bid,
                'label': _LABELS.get(bid, bid),
                'sub': 'Blender Studio Human Base Meshes v1.4.1 · CC0 · clay',
                'preview_url': ('/inspect/arch-asset/' + _PREVIEWS + stem + '_threequarter.png')
                if os.path.isfile(prev)
                else '',
                'preview2_url': ('/inspect/arch-asset/' + _PREVIEWS + stem + '_front.png')
                if os.path.isfile(front)
                else '',
            }
        )
        pub = _published(bid)
        if pub:
            base = '/inspect/arch-asset/photoreal/%s/' % bid
            out.append(
                {
                    'id': bid + ':photoreal',
                    'kind': 'photoreal',
                    'base': bid,
                    'label': 'Photoreal skin · ' + _LABELS.get(bid, bid),
                    'sub': 'baked %s · %d views · %dx%d atlas · coverage %d%%'
                    % (
                        pub.get('built', ''),
                        len(pub.get('views') or {}),
                        pub['atlas']['width'],
                        pub['atlas']['height'],
                        round(100 * float(pub.get('coverage') or 0)),
                    ),
                    # ?v= so a re-shot card is not served from the browser cache
                    'preview_url': (base + pub['preview'] + '?v=%d' % int(pub.get('preview_mtime') or 0))
                    if pub.get('preview')
                    else pub.get('card_strip_url', ''),
                    'preview2_url': (pub['card_strip_url'] + '?v=%d' % int(pub.get('preview_mtime') or 0))
                    if pub.get('card_strip_url')
                    else '',
                    'previews': (pub.get('previews') or {}).get('source', 'klein'),
                    'built': pub.get('built', ''),
                    'mtime': pub.get('albedo_mtime', 0),
                }
            )
    return {'ok': True, 'models': out}


ROUTES = {
    'variants': _variants,
    'status': _status,
    'start': _start,
    'stop': _stop,
}
