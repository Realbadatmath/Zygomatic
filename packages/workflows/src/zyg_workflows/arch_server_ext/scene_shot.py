# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_shot — the server half of the Architecture Studio's shot bridge.

The operator draws a city in the studio, drops VFX volumes and actors into it,
presses **Draft** and sees a low-quality clip within seconds; then presses
**Full**.  Everything the browser cannot do lives here: shot.json on disk, the
two headless Blender runs (``blender_scripts/scene_build.py`` and
``blender_scripts/scene_render.py``), and the mp4/placement.json they leave
behind.

    POST /inspect/api/architecture/ext/scene_shot/<op>

    list                              -> every shot under data/architecture/shots
    get           {id}                -> the shot record + what exists on disk
    save          {shot, doc?}        -> validate + write shot.json
    new           {id, name, doc, camera?}
    add_effect    {id, effect}        remove_effect {id, effect_id}
    add_actor     {id, actor}         remove_actor  {id, actor_id}
    set_camera_key{id, key}
    build         {id}                -> {job}   scene_build.py
    draft         {id, frames?}       -> {job}   build (if stale) + scene_render draft
    full          {id}                -> {job}   scene_render full
    job           {jid}               -> {state, log tail, result}
    media         {id, kind}          -> (mp4 bytes, 'video/mp4', '<id>_<kind>.mp4')
    placement     {id, kind}          -> placement.json
    actors_available                  -> the proxy actors that have a .blend
    motions                           -> data/assets/motion_library/library.json
    current       {}                  -> {id} of the shot the studio is editing
    set_current   {id}                -> park that id in shots/current.json

``current``/``set_current`` exist so a tool in ANOTHER studio (the VFX
Studio's "Place in 3D scene") can put something into the shot the operator is
working on without being told which one that is.

ONE Blender job at a time: a second build/draft/full while one is running is a
409, and every launch holds the same advisory lock the harness and
``render_offline`` use (``$ZYG_TMP_DIR/arch_ext_blender.lock``) — two
headless Blenders at once SIGBUS the Bonsai add-on.

Licences: stdlib only; Blender (GPL) is a subprocess, never imported.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import logging as _zyg_logging

from zyg_workflows.paths import ZYG_TMP_DIR, tmp_dir

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# This file and the contract module it needs are BOTH called scene_shot, so a
# bare `import scene_shot` can find this one and import itself. Load the crews
# root module by its path, under a name nothing else uses.
if '_scene_shot_contract' in sys.modules:
    SS = sys.modules['_scene_shot_contract']
else:
    _spec = importlib.util.spec_from_file_location('_scene_shot_contract', os.path.join(HERE, 'scene_shot.py'))
    SS = importlib.util.module_from_spec(_spec)
    sys.modules['_scene_shot_contract'] = SS
    _spec.loader.exec_module(SS)

SHOTS_DIR = SS.SHOTS_DIR
CURRENT_JSON = os.path.join(SHOTS_DIR, 'current.json')
ACTORS_DIR = os.path.join(HERE, 'data', 'architecture', 'actors')
MOTION_LIB = os.path.join(HERE, 'data', 'assets', 'motion_library', 'library.json')
BUILD_PY = os.path.join(HERE, 'blender_scripts', 'scene_build.py')
RENDER_PY = os.path.join(HERE, 'blender_scripts', 'scene_render.py')
BLENDER = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')

TIMEOUT_BUILD_S = 1800
TIMEOUT_DRAFT_S = 1800
TIMEOUT_FULL_S = 7200
LOG_CAP = 400  # lines kept per job; the tail is what the UI shows

_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


class _BlenderLock:
    """Blender runs are SERIALISED across processes — the same advisory lock
    arch_ext_harness._BlenderLock and arch_server_ext/render_offline.py take,
    so the tab, the tests and this family queue behind one lock, not three."""

    # Every holder of this lock derives the path the same way, so they still meet in one file;
    # tmp_dir() creates the directory owner-only instead of the old world-writable /tmp path.
    PATH = str(ZYG_TMP_DIR / 'arch_ext_blender.lock')

    def __enter__(self):
        import fcntl

        tmp_dir()
        self.fh = open(self.PATH, 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        import fcntl

        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# ── small helpers ─────────────────────────────────────────────────────────
def _err(msg, code=400):
    return {'error': str(msg)[:400], 'code': code}


def _last_json(lines):
    for line in list(lines)[::-1]:
        line = str(line).strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('non-JSON line skipped while scanning the shot log: %s', _exc)
                continue
    return {}


def _shot_path(sid):
    return os.path.join(SHOTS_DIR, str(sid), 'shot.json')


def _read(sid):
    """(shot, error). The shot is returned even when invalid, so the sheet can
    show what is wrong instead of an empty panel."""
    if not isinstance(sid, str) or not SS.ID_RE.match(sid):
        return None, _err('shot id %r must match %s' % (sid, SS.ID_RE.pattern))
    path = _shot_path(sid)
    if not os.path.isfile(path):
        return None, _err('no shot %r' % sid, 404)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh), None
    except Exception as exc:  # noqa: BLE001
        return None, _err('shot.json does not parse: %s' % exc, 500)


def _write(shot):
    """Validate then save. Returns (reply, error); reply carries the warnings."""
    warnings: list = []
    errs = SS.validate(shot, warnings)
    if errs:
        return None, {'error': 'the shot is not valid: ' + '; '.join(errs)[:360], 'errors': errs, 'code': 400}
    path = SS.save(shot)
    return {'ok': True, 'shot': shot, 'path': path, 'warnings': warnings}, None


def _save_doc(sid, doc):
    """The drawing the browser is holding, parked beside the shot it belongs to."""
    d = os.path.join(SHOTS_DIR, str(sid))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, 'drawing.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, separators=(',', ':'))
    os.replace(tmp, path)
    return path


def _disk(sid):
    d = os.path.join(SHOTS_DIR, str(sid))
    return {
        'blend': os.path.isfile(os.path.join(d, 'scene.blend')),
        'draft': os.path.isfile(os.path.join(d, 'draft', 'draft.mp4')),
        'full': os.path.isfile(os.path.join(d, 'full', 'full.mp4')),
        'draft_placement': os.path.isfile(os.path.join(d, 'draft', 'placement.json')),
        'full_placement': os.path.isfile(os.path.join(d, 'full', 'placement.json')),
    }


def _next_id(items, stem):
    taken = {i.get('id') for i in items if isinstance(i, dict)}
    n = 1
    while '%s%d' % (stem, n) in taken:
        n += 1
    return '%s%d' % (stem, n)


def _blend_is_stale(sid):
    d = os.path.join(SHOTS_DIR, str(sid))
    blend, shot = os.path.join(d, 'scene.blend'), os.path.join(d, 'shot.json')
    if not os.path.isfile(blend):
        return True
    try:
        return os.path.getmtime(blend) < os.path.getmtime(shot)
    except OSError:
        return True


# ── the job runner: one Blender at a time ─────────────────────────────────
def _pump(job, cmd, timeout_s):
    """Run one command under the Blender lock, streaming its stdout into the
    job log. Returns (returncode, the last JSON line it printed)."""
    job['log'].append('$ ' + ' '.join(cmd))
    with _BlenderLock():
        p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        t0 = time.time()
        killed = False
        try:
            for line in p.stdout:
                job['log'].append(line.rstrip())
                if len(job['log']) > LOG_CAP:
                    del job['log'][: len(job['log']) - LOG_CAP]
                if time.time() - t0 > timeout_s:
                    killed = True
                    p.kill()
                    break
        finally:
            try:
                p.stdout.close()
            except (OSError, AttributeError) as _exc:
                _zyg_log.debug('closing the child stdout failed: %s', _exc)
            rc = p.wait()
    if killed:
        job['log'].append('[scene_shot] killed after %d s' % timeout_s)
        return 124, {}
    return rc, _last_json(job['log'])


def _worker(jid, steps):
    job = _JOBS[jid]
    job['state'] = 'running'
    try:
        for label, cmd, timeout_s in steps:
            job['step'] = label
            rc, info = _pump(job, cmd, timeout_s)
            job['result'] = info
            if rc != 0 or not info.get('ok'):
                job['state'] = 'failed'
                job['error'] = (info.get('error') or ('%s exited %d' % (label, rc)) or 'unknown failure')[:400]
                job['ended'] = time.time()
                return
        job['state'] = 'done'
    except Exception as exc:  # noqa: BLE001
        job['state'] = 'failed'
        job['error'] = '%s: %s' % (type(exc).__name__, exc)
    finally:
        if job['state'] == 'running':
            job['state'] = 'failed'
            job.setdefault('error', 'the worker stopped without a result')
        job['ended'] = time.time()


def _start(kind, sid, steps):
    """One Blender job at a time; a second one is a 409, not a queue."""
    with _JOBS_LOCK:
        for j in _JOBS.values():
            if j['state'] in ('queued', 'running'):
                return None, {
                    'error': 'Blender is busy with %s on %r — wait for it to finish' % (j['kind'], j['shot']),
                    'job': j['id'],
                    'code': 409,
                }
        jid = '%s-%s' % (kind, uuid.uuid4().hex[:8])
        job = {
            'id': jid,
            'kind': kind,
            'shot': sid,
            'state': 'queued',
            'step': '',
            'log': [],
            'result': {},
            'error': '',
            'started': time.time(),
            'ended': 0,
        }
        _JOBS[jid] = job
        for old in [
            k for k, v in _JOBS.items() if v['state'] in ('done', 'failed') and time.time() - v['ended'] > 3600
        ]:
            _JOBS.pop(old, None)
    threading.Thread(target=_worker, args=(jid, steps), daemon=True).start()
    return job, None


def _job_view(job, tail=40):
    return {
        'id': job['id'],
        'kind': job['kind'],
        'shot': job['shot'],
        'state': job['state'],
        'step': job['step'],
        'log': job['log'][-tail:],
        'result': job['result'],
        'error': job['error'],
        'seconds': round((job['ended'] or time.time()) - job['started'], 1),
    }


def _build_cmd(sid):
    return [BLENDER, '-b', '--python', BUILD_PY, '--', '--shot', _shot_path(sid)]


def _render_cmd(sid, mode, frames=''):
    cmd = [
        BLENDER,
        '-b',
        os.path.join(SHOTS_DIR, str(sid), 'scene.blend'),
        '--python',
        RENDER_PY,
        '--',
        '--shot',
        _shot_path(sid),
        '--mode',
        mode,
    ]
    if frames:
        cmd += ['--frames', frames]
    return cmd


def _frames_arg(v):
    """`frames` may be a count (1:N) or an explicit 'a:b'. '' = the whole shot."""
    if v in (None, '', 0):
        return ''
    if isinstance(v, str) and ':' in v:
        a, b = v.split(':', 1)
        try:
            return '%d:%d' % (int(a), int(b))
        except ValueError:
            return ''
    try:
        n = int(v)
    except (TypeError, ValueError):
        return ''
    return '1:%d' % n if n > 0 else ''


# ── ops ───────────────────────────────────────────────────────────────────
def op_list(payload, method):
    out = []
    if os.path.isdir(SHOTS_DIR):
        for name in sorted(os.listdir(SHOTS_DIR)):
            path = _shot_path(name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    shot = json.load(fh)
            except Exception:  # noqa: BLE001
                shot = {}
            row = {
                'id': name,
                'name': shot.get('name') or name,
                'frames': shot.get('frames'),
                'fps': shot.get('fps'),
                'effects': len(shot.get('effects') or []),
                'actors': len(shot.get('actors') or []),
            }
            row.update(_disk(name))
            out.append(row)
    return {'ok': True, 'shots': out, 'dir': SHOTS_DIR}


def op_get(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    warnings: list = []
    return {
        'ok': True,
        'shot': shot,
        'errors': SS.validate(shot, warnings),
        'warnings': warnings,
        'files': _disk(shot.get('id')),
    }


def op_save(payload, method):
    shot = payload.get('shot')
    if not isinstance(shot, dict):
        return _err('save needs a shot object')
    sid = shot.get('id')
    if not isinstance(sid, str) or not SS.ID_RE.match(sid):
        return _err('shot id %r must match %s' % (sid, SS.ID_RE.pattern))
    doc = payload.get('doc')
    if isinstance(doc, dict):
        shot['drawing'] = _save_doc(sid, doc)
    reply, err = _write(shot)
    return err or reply


def op_new(payload, method):
    sid = payload.get('id')
    if not isinstance(sid, str) or not SS.ID_RE.match(sid):
        return _err('a new shot needs an id matching %s' % SS.ID_RE.pattern)
    if os.path.isfile(_shot_path(sid)):
        return _err('shot %r already exists' % sid, 409)
    doc = payload.get('doc')
    if isinstance(doc, dict):
        drawing = _save_doc(sid, doc)
    else:
        drawing = payload.get('drawing')
        if not isinstance(drawing, str) or not os.path.isfile(drawing):
            return _err('a new shot needs the drawing (doc) the tab is holding')
    kw = {}
    if payload.get('name'):
        kw['name'] = str(payload['name'])[:120]
    shot = SS.new_shot(sid, drawing, **kw)
    cam = payload.get('camera')
    if isinstance(cam, dict) and cam.get('p') and cam.get('t'):
        shot['camera'] = {
            'keys': [
                {
                    'f': 1,
                    'p': [float(c) for c in cam['p']],
                    't': [float(c) for c in cam['t']],
                    'fov': float(cam.get('fov') or 50.0),
                }
            ]
        }
    for k in ('fps', 'frames', 'resolution'):
        if payload.get(k) is not None:
            shot[k] = payload[k]
    reply, err = _write(shot)
    return err or reply


def op_add_effect(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    fx = payload.get('effect')
    if not isinstance(fx, dict):
        return _err('add_effect needs an effect object')
    fx = dict(fx)
    shot.setdefault('effects', [])
    if not fx.get('id'):
        fx['id'] = _next_id(shot['effects'], 'fx')
    if any(e.get('id') == fx['id'] for e in shot['effects']):
        return _err('effect %r is already in this shot' % fx['id'], 409)
    fx.setdefault('size_m', 1.5)
    fx.setdefault('start_frame', 1)
    if 'p' not in fx and 'rel' not in fx:
        fx['p'] = [0.0, 0.0, 0.0]
    shot['effects'].append(fx)
    reply, err = _write(shot)
    return err or reply


def op_remove_effect(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    fid = payload.get('effect_id')
    keep = [e for e in shot.get('effects') or [] if e.get('id') != fid]
    if len(keep) == len(shot.get('effects') or []):
        return _err('no effect %r in this shot' % fid, 404)
    shot['effects'] = keep
    reply, err = _write(shot)
    return err or reply


def op_add_actor(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    actor = payload.get('actor')
    if not isinstance(actor, dict):
        return _err('add_actor needs an actor object')
    actor = dict(actor)
    shot.setdefault('actors', [])
    if not actor.get('id'):
        actor['id'] = _next_id(shot['actors'], 'actor')
    if any(a.get('id') == actor['id'] for a in shot['actors']):
        return _err('actor %r is already in this shot' % actor['id'], 409)
    actor.setdefault('height_m', 1.7)
    actor.setdefault('start_frame', 1)
    if not actor.get('path'):
        # a standing actor is still an actor: one key, held for the whole shot
        actor['path'] = [{'f': 1, 'p': [0.0, 0.0, 0.0], 'ry': 180.0}]
    shot['actors'].append(actor)
    reply, err = _write(shot)
    return err or reply


def op_remove_actor(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    aid = payload.get('actor_id')
    keep = [a for a in shot.get('actors') or [] if a.get('id') != aid]
    if len(keep) == len(shot.get('actors') or []):
        return _err('no actor %r in this shot' % aid, 404)
    # an effect anchored to a departing actor would fail validation with a
    # message about rel.to, which reads like a bug; say what really happened
    held = [
        e.get('id') for e in shot.get('effects') or [] if isinstance(e.get('rel'), dict) and e['rel'].get('to') == aid
    ]
    if held:
        return _err(
            'effect(s) %s are placed relative to %r — move or remove them first'
            % (', '.join(str(h) for h in held), aid),
            409,
        )
    shot['actors'] = keep
    reply, err = _write(shot)
    return err or reply


def op_set_camera_key(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    key = payload.get('key')
    if not isinstance(key, dict) or key.get('p') is None or key.get('t') is None:
        return _err('set_camera_key needs a key {f, p:[x,y,z], t:[x,y,z], fov}')
    try:
        k = {
            'f': float(key.get('f', 1)),
            'p': [float(c) for c in key['p']],
            't': [float(c) for c in key['t']],
            'fov': float(key.get('fov') or 50.0),
        }
    except (TypeError, ValueError, IndexError) as exc:
        return _err('camera key is not three numbers: %s' % exc)
    keys = [
        x for x in (shot.get('camera') or {}).get('keys') or [] if float(x.get('f', 0)) != k['f']
    ]  # a key at that frame is replaced
    keys.append(k)
    keys.sort(key=lambda x: float(x.get('f', 0)))
    shot['camera'] = {'keys': keys}
    reply, err = _write(shot)
    return err or reply


def op_build(payload, method):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    if not os.path.exists(BLENDER):
        return _err('Blender not found at %s (set BLENDER_BIN)' % BLENDER, 500)
    sid = shot['id']
    job, busy = _start('build', sid, [('build', _build_cmd(sid), TIMEOUT_BUILD_S)])
    return busy or {'ok': True, 'job': _job_view(job)}


def _render(payload, mode):
    shot, err = _read(payload.get('id'))
    if err:
        return err
    if not os.path.exists(BLENDER):
        return _err('Blender not found at %s (set BLENDER_BIN)' % BLENDER, 500)
    sid = shot['id']
    steps = []
    if _blend_is_stale(sid):
        # the operator pressed Draft, not Build: the .blend is our problem
        steps.append(('build', _build_cmd(sid), TIMEOUT_BUILD_S))
    frames = _frames_arg(payload.get('frames')) if mode == 'draft' else ''
    steps.append((mode, _render_cmd(sid, mode, frames), TIMEOUT_DRAFT_S if mode == 'draft' else TIMEOUT_FULL_S))
    job, busy = _start(mode, sid, steps)
    return busy or {'ok': True, 'job': _job_view(job), 'rebuilt': len(steps) > 1}


def op_draft(payload, method):
    return _render(payload, 'draft')


def op_full(payload, method):
    return _render(payload, 'full')


def op_job(payload, method):
    job = _JOBS.get(payload.get('jid') or payload.get('id'))
    if not job:
        return _err('no job %r' % (payload.get('jid') or payload.get('id')), 404)
    return {'ok': True, 'job': _job_view(job, tail=int(payload.get('tail') or 40))}


def _kind_dir(payload):
    sid = payload.get('id')
    kind = str(payload.get('kind') or 'draft')
    if kind not in ('draft', 'full'):
        return None, None, _err('kind must be draft or full')
    if not isinstance(sid, str) or not SS.ID_RE.match(sid):
        return None, None, _err('shot id %r must match %s' % (sid, SS.ID_RE.pattern))
    return sid, os.path.join(SHOTS_DIR, sid, kind), None


def op_media(payload, method):
    sid, d, err = _kind_dir(payload)
    if err:
        return err
    kind = str(payload.get('kind') or 'draft')
    mp4 = os.path.join(d, '%s.mp4' % kind)
    if not os.path.isfile(mp4):
        return _err('no %s render for %r yet' % (kind, sid), 404)
    with open(mp4, 'rb') as fh:
        data = fh.read()
    return (data, 'video/mp4', '%s_%s.mp4' % (sid, kind))


def op_placement(payload, method):
    sid, d, err = _kind_dir(payload)
    if err:
        return err
    path = os.path.join(d, 'placement.json')
    if not os.path.isfile(path):
        return _err('no %s placement for %r yet' % (payload.get('kind'), sid), 404)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return {'ok': True, 'placement': json.load(fh)}
    except Exception as exc:  # noqa: BLE001
        return _err('placement.json does not parse: %s' % exc, 500)


def op_actors_available(payload, method):
    out = []
    if os.path.isdir(ACTORS_DIR):
        for name in sorted(os.listdir(ACTORS_DIR)):
            d = os.path.join(ACTORS_DIR, name)
            blend = os.path.join(d, name + '.blend')
            if not os.path.isfile(blend):
                continue
            row = {'id': name, 'blend': blend, 'height_m': None, 'motion': '', 'strip': ''}
            meta = os.path.join(d, name + '.json')
            if os.path.isfile(meta):
                try:
                    with open(meta, 'r', encoding='utf-8') as fh:
                        m = json.load(fh)
                    row['height_m'] = m.get('height_m')
                    row['motion'] = m.get('motion') or ''
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('shot meta unreadable, row left without height/motion: %s', _exc)
            strip = os.path.join(d, name + '_strip.png')
            if os.path.isfile(strip):
                row['strip'] = strip
            out.append(row)
    return {'ok': True, 'actors': out, 'dir': ACTORS_DIR}


def op_motions(payload, method):
    if not os.path.isfile(MOTION_LIB):
        return {'ok': True, 'motions': [], 'note': 'no motion library at %s' % MOTION_LIB}
    try:
        with open(MOTION_LIB, 'r', encoding='utf-8') as fh:
            lib = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return _err('the motion library does not parse: %s' % exc, 500)
    out = [
        {
            'id': c.get('id'),
            'label': c.get('label') or c.get('id'),
            'tags': c.get('tags') or [],
            'frames': c.get('frames'),
            'fps': c.get('fps'),
        }
        for c in (lib.get('clips') or []) + (lib.get('capture') or [])
        if c.get('id')
    ]
    return {'ok': True, 'motions': out, 'source': lib.get('source') or ''}


def _read_current():
    """The id parked in shots/current.json, or '' when there is none. A shot
    that has since been deleted reads as no current shot, not as a dangling id."""
    try:
        with open(CURRENT_JSON, 'r', encoding='utf-8') as fh:
            sid = (json.load(fh) or {}).get('id') or ''
    except Exception:  # noqa: BLE001
        return ''
    if not isinstance(sid, str) or not SS.ID_RE.match(sid) or not os.path.isfile(_shot_path(sid)):
        return ''
    return sid


def op_current(payload, method):
    """Which shot is the studio editing? '' when the operator has not opened one."""
    sid = _read_current()
    return {'ok': True, 'id': sid, 'path': CURRENT_JSON}


def op_set_current(payload, method):
    sid = payload.get('id')
    if not isinstance(sid, str) or not SS.ID_RE.match(sid):
        return _err('shot id %r must match %s' % (sid, SS.ID_RE.pattern))
    if not os.path.isfile(_shot_path(sid)):
        return _err('no shot %r' % sid, 404)
    os.makedirs(SHOTS_DIR, exist_ok=True)
    tmp = CURRENT_JSON + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'id': sid, 'at': time.time()}, fh)
    os.replace(tmp, CURRENT_JSON)
    return {'ok': True, 'id': sid, 'path': CURRENT_JSON}


def op_info(payload, method):
    """What the sheet shows before it asks for anything: is the bridge there."""
    with _JOBS_LOCK:
        busy = [_job_view(j, tail=3) for j in _JOBS.values() if j['state'] in ('queued', 'running')]
    return {
        'ok': True,
        'blender': BLENDER,
        'present': os.path.exists(BLENDER),
        'build_py': os.path.isfile(BUILD_PY),
        'render_py': os.path.isfile(RENDER_PY),
        'shots_dir': SHOTS_DIR,
        'vdb_dir': SS.VDB_DIR,
        'busy': busy,
        'schema': SS.SCHEMA,
    }


ROUTES = {
    'list': op_list,
    'get': op_get,
    'save': op_save,
    'new': op_new,
    'add_effect': op_add_effect,
    'remove_effect': op_remove_effect,
    'add_actor': op_add_actor,
    'remove_actor': op_remove_actor,
    'set_camera_key': op_set_camera_key,
    'build': op_build,
    'draft': op_draft,
    'full': op_full,
    'job': op_job,
    'media': op_media,
    'placement': op_placement,
    'actors_available': op_actors_available,
    'motions': op_motions,
    'info': op_info,
    'current': op_current,
    'set_current': op_set_current,
}
