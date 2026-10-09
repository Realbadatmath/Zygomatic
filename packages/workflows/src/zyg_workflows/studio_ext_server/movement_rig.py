# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Movement Studio — the skeleton view, server side (2026-09-22).

ONE skeleton runs through this whole file: MPFB's ``cmu_mb`` rig, 31 bones named
exactly like the CMU MotionBuilder BVH joints (``motion_library.CMU_MB_JOINTS``).
Every movement in ``data/assets/motion_library/library.json`` targets it, and
every actor built here wears it. What changed on 2026-09-22 is only what the
bones live INSIDE: not an MPFB-generated proxy any more but the Character Studio
clay base body (Blender Studio Human Base Meshes v1.4.1, CC0) of
``data/assets/base_body_rig/``, fitted to the character's own measurements.

The actor .blend contract that ``scene_build.place_actor`` reads is untouched —
collection 'actor': actor_root empty -> armature (custom props actor_name,
actor_height_m, motion_id, mapping='cmu_mb', root_offset_z) -> mesh; action
'motion'; sidecar ``<name>.json``. So the shot runner and the VACE recipe of
``data/architecture/shots/fixture_capture`` keep working on the new body, and
``render`` below can copy that fixture verbatim and only swap the actor.

TEN OPS behind /inspect/api/studio/movement_rig/:

  subjects  the characters a skeleton can be built for (bible + body cell +
            metrics + the actors already built for them). Cached 30 s because
            it stats 134 dataset directories.
  clips     motion_library.clips() — cmu / auth / capture / edit in one list.
  metrics   geom.body_metrics.measure(char_id) — the five height fractions a
            bone-length fitter needs. 404 when no cell of the sheet shows a
            whole body; that is a fact about the sheet, not an error here.
  build     actor <char_id>__<motion with / -> _>: proxy_actor (Blender, CPU)
            then rig_export_glb. Returns at once when the GLB is already newer
            than both its inputs.
  job       the job.json of any job this module started.
  glb       the bytes of an actor's GLB, for the browser's glTF loader.
  video     the bytes of a finished render job's final.mp4.
  edit      motion_edit trim/speed/mirror/loop -> a new edit/<slug> clip.
  capture   motion_capture.capture_from_video — video -> GEM-X -> cmu_mb BVH.
  render    the take-10 VACE recipe re-pointed at one actor.

THREE FENCES, and why each exists.

  * THE NAME FENCE. ``glb`` takes a name from the query string and opens a file.
    Both halves are checked: the name must match ``^[A-Za-z0-9_]{1,80}$`` (so
    '../x' never becomes a path) AND the realpath must land inside the actors
    directory (so a symlink planted in it cannot point out). A regex alone is a
    fence that only watches the front door.

  * ONE BLENDER AT A TIME, one heavy job at a time. ``build`` shells out to
    Blender under the same ``/tmp/claude-1000/arch_ext_blender.lock`` flock the
    architecture studio uses, so the two studios cannot open Blender at once;
    ``capture`` and ``render`` take the GPU for tens of minutes and refuse each
    other with 409 naming the job that holds the slot. The slot is held by a
    job.json on disk, so a kanban_server restart releases it instead of wedging
    the panel forever.

  * RENDER WILL NOT START BLIND. A VACE run without ComfyUI is 30 minutes of
    waiting for a failure, so ``render`` probes $ZYG_COMFY_URL/system_stats
    first and refuses with 409 saying what it could not reach.

comfy_generation_service is never imported here — not at module import, not in a
worker. The render leg is a subprocess (``scene_shot_run.py``), which is where
that import belongs.
"""

import json
import logging as _zyg_logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from zyg_workflows import net, paths

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATASET_ROOT = os.path.realpath(str(paths.ZYG_LORA_DATASETS / 'storyteller_chars'))
ACTORS_DIR = os.path.realpath(os.path.join(HERE, 'data', 'architecture', 'actors'))
BASE_BODY_ROOT = os.path.join(HERE, 'data', 'assets', 'base_body_rig')
SHOTS_DIR = os.path.join(HERE, 'data', 'architecture', 'shots')
FIXTURE_SHOT = os.path.join(SHOTS_DIR, 'fixture_capture', 'shot.json')
JOBS_ROOT = os.path.join(HERE, 'output', 'movement', '_rigs')

VENV_PYTHON = sys.executable
BLENDER = str(paths.BLENDER_BIN)
BLENDER_LOCK = '/tmp/claude-1000/arch_ext_blender.lock'  # nosec B108  # noqa: S108  shared flock path, not a temp file
COMFY_STATS = paths.ZYG_COMFY_URL + '/system_stats'

_CHAR_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_ACTOR_RE = re.compile(r'^[A-Za-z0-9_]{1,80}$')
_JOB_RE = re.compile(r'^[a-f0-9]{12}$')
_SLUG_RE = re.compile(r'^[A-Za-z0-9_-]{1,48}$')

# A capture is ~10 GPU-minutes and a render ~30; both heartbeat well inside this.
_STALE_S = 3600
_LOG_KEEP = 400
# proxy_actor on a long CMU clip is minutes of CPU, not seconds.
_BLENDER_TIMEOUT_S = 3600
_SUBJECTS_TTL_S = 30
# the fixture is 97 frames; a longer VACE run is a different decision, not a default
_RENDER_MAX_FRAMES = 97

_LOCK = threading.Lock()
_SUBJECTS_CACHE = {'at': 0.0, 'rows': None}


# ── fences ───────────────────────────────────────────────────────────────────
def _char_dir(cid):
    """The character's real dataset directory, or None."""
    cid = str(cid or '').strip()
    if not _CHAR_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(DATASET_ROOT, cid))
    if d != os.path.join(DATASET_ROOT, cid) or not os.path.isdir(d):
        return None
    return d


def _actor_dir(name):
    """The actor's real directory, or None. Name shape AND realpath, because a
    regex only guards the name and a symlink only the path."""
    name = str(name or '').strip()
    if not _ACTOR_RE.match(name):
        return None
    d = os.path.realpath(os.path.join(ACTORS_DIR, name))
    if os.path.dirname(d) != ACTORS_DIR:
        return None
    return d


def actor_name(char_id, motion_id):
    """'<char_id>__<motion with / -> _>' — the one naming rule of this module."""
    return '%s__%s' % (char_id, str(motion_id or '').replace('/', '_'))


# 2026-09-23, operator: the tab opens on the plain CLAY BASE BODY, not on a
# character. These two pseudo-subjects have no bible and no fit: the rig is the
# base body at its own height, playing whatever motion is asked for.
BASE_SUBJECTS = {'base_male_realistic': 'male_realistic', 'base_female_realistic': 'female_realistic'}


def base_kind(cid):
    """'male_realistic' / 'female_realistic' for a base subject id, else None."""
    return BASE_SUBJECTS.get(str(cid or '').strip())


def _base_meta(kind):
    try:
        with open(os.path.join(BASE_BODY_ROOT, kind, kind + '.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _base_rows():
    rows = []
    for cid, kind in BASE_SUBJECTS.items():
        meta = _base_meta(kind)
        rows.append(
            {
                'id': cid,
                'name': 'Base body · ' + kind.replace('_', ' '),
                'height_m': meta.get('height_m'),
                'gender': 'male' if kind.startswith('male') else 'female',
                'age': None,
                'body_build': 'CC0 clay base body',
                'has_body_cell': False,
                'has_metrics': False,
                'is_base': True,
                'actors': [],
            }
        )
    return rows


def _bible(cid):
    """The character bible package, read only. None when it does not load."""
    cdir = _char_dir(cid)
    if not cdir:
        return None
    try:
        with open(os.path.join(cdir, 'character_bible.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _body_cell(cid):
    """The body-anchor cell path, with contact_sheet_pipeline's 03d/02d read
    compatibility, or '' when neither exists."""
    cells = os.path.join(DATASET_ROOT, cid, 'contact_sheet', 'cells')
    for name in ('cell_000_body.png', 'cell_00_body.png'):
        p = os.path.join(cells, name)
        if os.path.isfile(p):
            return p
    return ''


def _gender_macro(gender):
    """MPFB's macro: 1.0 male, 0.0 female, 0.5 for anything else — and the same
    0.5 threshold proxy_actor uses to pick the base body (line 239)."""
    g = str(gender or '').strip().lower()
    if g.startswith('male') or g in ('m', 'boy', 'man'):
        return 1.0
    if g.startswith('female') or g in ('f', 'girl', 'woman'):
        return 0.0
    return 0.5


def _base_blend(gender_macro):
    kind = 'male_realistic' if float(gender_macro) >= 0.5 else 'female_realistic'
    return os.path.join(BASE_BODY_ROOT, kind, kind + '.blend')


def _comfy_up():
    """True when ComfyUI answers /system_stats. Its own function so a test can
    monkeypatch the probe without a socket."""
    try:
        with net.safe_urlopen(COMFY_STATS, timeout=4) as r:
            return 200 <= int(r.status) < 300
    except Exception:  # noqa: BLE001 — any failure is 'down'
        return False


# ── jobs ─────────────────────────────────────────────────────────────────────
def _job_dir(jid):
    jid = str(jid or '')
    if not _JOB_RE.match(jid):
        return None
    root = os.path.realpath(JOBS_ROOT)
    d = os.path.realpath(os.path.join(root, jid))
    return d if os.path.dirname(d) == root else None


def _read_job(jid):
    d = _job_dir(jid)
    if not d:
        return None
    try:
        with open(os.path.join(d, 'job.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_job(rec):
    """Atomically — the panel polls this file while the worker rewrites it, and
    a half-written job.json is a JSON error in the browser every few seconds."""
    d = _job_dir(rec.get('job_id'))
    if not d:
        return
    os.makedirs(d, exist_ok=True)
    rec['heartbeat'] = round(time.time(), 1)
    tmp = os.path.join(d, '.job.json.%d.tmp' % os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, indent=1, default=str)
        os.replace(tmp, os.path.join(d, 'job.json'))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError as _exc:
            _zyg_log.debug('temporary job file cleanup skipped: %s', _exc)


class _Job:
    def __init__(self, kind, **extra):
        self.rec = {
            'job_id': uuid.uuid4().hex[:12],
            'kind': kind,
            'status': 'queued',
            'started': round(time.time(), 1),
            'finished': 0.0,
            'log': [],
            'error': '',
            'actor': '',
            'glb': '',
        }
        self.rec.update(extra)
        self._last = 0.0
        _write_job(self.rec)

    @property
    def jid(self):
        return self.rec['job_id']

    def log(self, msg):
        self.rec['log'].append('%s %s' % (time.strftime('%H:%M:%S'), str(msg)[:400]))
        self.rec['log'] = self.rec['log'][-_LOG_KEEP:]
        if time.time() - self._last > 1.0:
            self.flush()

    def flush(self):
        self._last = time.time()
        _write_job(self.rec)

    def set(self, **kw):
        self.rec.update(kw)
        self.flush()


def _live_heavy():
    """The capture/render job holding the single GPU slot, or None. Live =
    queued/running AND heartbeated inside _STALE_S, so a server restart frees
    the slot by itself."""
    now = time.time()
    try:
        names = os.listdir(JOBS_ROOT)
    except OSError:
        return None
    for name in names:
        rec = _read_job(name)
        if not rec or rec.get('kind') not in ('capture', 'render'):
            continue
        if rec.get('status') not in ('queued', 'running'):
            continue
        if now - float(rec.get('heartbeat') or rec.get('started') or 0) > _STALE_S:
            continue
        return rec
    return None


def _spawn(job, fn, *args):
    def _run():
        job.set(status='running')
        try:
            fn(job, *args)
        except Exception as e:  # noqa: BLE001 — shown in the panel
            job.rec['status'] = 'failed'
            job.rec['error'] = ('%s: %s' % (type(e).__name__, e))[:400]
            job.log('FAILED %s: %s' % (type(e).__name__, e))
        else:
            job.rec['status'] = 'done'
        job.rec['finished'] = round(time.time(), 1)
        job.flush()

    threading.Thread(target=_run, daemon=True, name='mvrig-%s' % job.jid).start()
    return {'ok': True, 'job_id': job.jid, 'kind': job.rec['kind']}


def _run_logged(job, args, cwd=None, timeout=_BLENDER_TIMEOUT_S, check=True):
    """Run a child process, copying its output into the job log. Returns
    (returncode, output) and raises only when `check` — so a caller that wants
    to READ a failure instead of dying on it can."""
    job.log('$ ' + ' '.join(args))
    p = subprocess.run(
        args, cwd=cwd or HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout
    )
    for line in (p.stdout or '').splitlines()[-_LOG_KEEP:]:
        job.log('  ' + line)
    if check and p.returncode != 0:
        raise RuntimeError('%s exited %d' % (os.path.basename(args[0]), p.returncode))
    return p.returncode, (p.stdout or '')


# ── subjects ─────────────────────────────────────────────────────────────────
def _actors_of(cid, names):
    prefix = cid + '__'
    return sorted(n for n in names if n.startswith(prefix))


def _subjects():
    now = time.time()
    if _SUBJECTS_CACHE['rows'] is not None and now - _SUBJECTS_CACHE['at'] < _SUBJECTS_TTL_S:
        return _SUBJECTS_CACHE['rows']
    try:
        actor_names = [n for n in os.listdir(ACTORS_DIR) if os.path.isdir(os.path.join(ACTORS_DIR, n))]
    except OSError:
        actor_names = []
    rows = []
    try:
        ids = sorted(os.listdir(DATASET_ROOT))
    except OSError:
        ids = []
    for cid in ids:
        if not _CHAR_RE.match(cid):
            continue
        pkg = None
        try:
            with open(os.path.join(DATASET_ROOT, cid, 'character_bible.json'), encoding='utf-8') as fh:
                pkg = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('subject %s skipped, its character_bible.json did not load: %s', cid, _exc)
            continue
        ident = pkg.get('identity') or {}
        rows.append(
            {
                'id': cid,
                'name': pkg.get('display_name') or cid,
                'height_m': ident.get('height_m'),
                'gender': ident.get('gender'),
                'age': ident.get('age'),
                'body_build': ident.get('body_build'),
                'has_body_cell': bool(_body_cell(cid)),
                'has_metrics': os.path.isfile(os.path.join(DATASET_ROOT, cid, 'body_metrics.json')),
                'actors': _actors_of(cid, actor_names),
            }
        )
    rows.sort(key=lambda r: str(r['name']).lower())
    base = _base_rows()
    for r in base:
        r['actors'] = _actors_of(r['id'], actor_names)
    rows = base + rows
    _SUBJECTS_CACHE.update(at=now, rows=rows)
    return rows


def _op_subjects(payload, method):  # noqa: ARG001
    rows = _subjects()
    return {'ok': True, 'count': len(rows), 'subjects': rows}


# ── clips ────────────────────────────────────────────────────────────────────
def _op_clips(payload, method):  # noqa: ARG001
    from zyg_workflows import motion_library as ML

    out = []
    for rec in ML.clips():
        cid = rec.get('id') or ''
        out.append(
            {
                'id': cid,
                'bucket': cid.split('/', 1)[0] if '/' in cid else '',
                'label': rec.get('label') or cid,
                'tags': list(rec.get('tags') or []),
                'frames': rec.get('frames'),
                'fps': rec.get('fps'),
                'rest_frame': rec.get('rest_frame'),
                'publishable': rec.get('publishable'),
                'licence': rec.get('licence'),
            }
        )
    return {'ok': True, 'count': len(out), 'clips': out}


# ── metrics ──────────────────────────────────────────────────────────────────
def _op_metrics(payload, method):  # noqa: ARG001
    cid = str(payload.get('char_id') or '').strip()
    if not _char_dir(cid):
        return {'error': 'unknown character %r' % cid, 'code': 404}
    from zyg_workflows.geom import body_metrics as BM

    try:
        return dict(BM.measure(cid), ok=True)
    except (FileNotFoundError, ValueError) as e:
        return {'error': str(e)[:400], 'code': 404}


# ── build ────────────────────────────────────────────────────────────────────
def _build_worker(job, cid, motion, fit, name, adir):
    from zyg_workflows import motion_library as ML

    kind = base_kind(cid)
    if kind:
        # the base body as itself: its own height, no bible, never a fit
        ident = {}
        gender = 1.0 if kind.startswith('male') else 0.0
        height = float(_base_meta(kind).get('height_m') or 1.70)
        age = 25.0
        fit = False
        job.log('base body %s at its own height %.3f m (no fit)' % (kind, height))
    else:
        ident = (_bible(cid) or {}).get('identity') or {}
        gender = _gender_macro(ident.get('gender'))
        try:
            height = float(ident.get('height_m') or 1.70)
        except (TypeError, ValueError):
            height = 1.70
        try:
            age = float(ident.get('age') or 30.0)
        except (TypeError, ValueError):
            age = 30.0

    fit_json = ''
    if fit:
        from zyg_workflows.geom import body_metrics as BM

        fit_json = BM.out_path(cid)
        if not os.path.isfile(fit_json):
            if not _body_cell(cid):
                job.log('no body cell — bible height only (%s)' % cid)
                fit_json = ''
            else:
                job.log('measuring %s (no body_metrics.json yet)' % cid)
                try:
                    BM.measure(cid)
                except (FileNotFoundError, ValueError) as e:
                    job.log('no body cell — bible height only (body_metrics declined: %s)' % e)
                    fit_json = ''
        if fit_json and not os.path.isfile(fit_json):
            fit_json = ''

    args = [
        BLENDER,
        '-b',
        '--python',
        os.path.join(HERE, 'blender_scripts', 'proxy_actor', '__main__.py'),  # a package since 2026-10
        '--',
        '--body',
        'base',
        '--name',
        name,
        '--height',
        '%.4f' % height,
        '--gender',
        '%.2f' % gender,
        '--age',
        '%.1f' % age,
        '--motion',
        motion,
        '--fps',
        '24',
    ]
    job.set(fit=fit_json, height_m=height, gender=gender, age=age, base_blend=_base_blend(gender))
    # A fit is no longer all-or-nothing: proxy_actor applies what the clamp allows
    # and reports status exact/clamped/off, so a build asked for with fit:true
    # always carries the fit. A non-zero exit is a real failure again.
    if fit_json:
        args += ['--fit', fit_json]
    _run_logged(job, ['flock', BLENDER_LOCK] + args)

    blend = os.path.join(adir, name + '.blend')
    if not os.path.isfile(blend):
        raise RuntimeError('proxy_actor wrote no %s' % blend)
    job.log('actor built: %s' % blend)

    _run_logged(
        job,
        [
            'flock',
            BLENDER_LOCK,
            BLENDER,
            '-b',
            '--python',
            os.path.join(HERE, 'blender_scripts', 'rig_export_glb.py'),
            '--',
            '--actor',
            name,
        ],
    )
    glb = os.path.join(adir, name + '.glb')
    if not os.path.isfile(glb):
        raise RuntimeError('rig_export_glb wrote no %s' % glb)
    job.set(glb=_glb_url(name), glb_path=glb, glb_bytes=os.path.getsize(glb), meta=_actor_meta(name))
    job.log('GLB exported: %s (%d bytes)' % (glb, os.path.getsize(glb)))
    _SUBJECTS_CACHE['rows'] = None  # a new actor is a new row
    # motion_library.clip is re-read here only to record what was played
    rec = ML.clip(motion) or {}
    job.set(clip={'id': motion, 'frames': rec.get('frames'), 'fps': rec.get('fps')})


def _glb_url(name):
    return '/inspect/api/studio/movement_rig/glb?name=%s' % name


def _actor_meta(name):
    adir = _actor_dir(name)
    if not adir:
        return {}
    try:
        with open(os.path.join(adir, name + '.json'), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _glb_is_fresh(name, motion, fit=False):
    """True when <name>.glb is newer than ALL its inputs — the base rig .blend,
    the character's own body_metrics.json (the fit targets) and the motion's own
    file. An authored motion has no file, and the base body has no metrics, so
    those inputs simply drop out. An actor built without a fit is never fresh for
    a build that asks for one."""
    from zyg_workflows import motion_library as ML

    adir = _actor_dir(name)
    glb = os.path.join(adir, name + '.glb') if adir else ''
    if not glb or not os.path.isfile(glb):
        return False
    if fit and not (_actor_meta(name).get('fit') or {}).get('status'):
        return False
    made = os.path.getmtime(glb)
    cid = name.split('__', 1)[0]
    kind = base_kind(cid)
    if kind:
        inputs = [os.path.join(BASE_BODY_ROOT, kind, kind + '.blend')]
    else:
        ident = (_bible(cid) or {}).get('identity') or {}
        inputs = [_base_blend(_gender_macro(ident.get('gender')))]
        from zyg_workflows.geom import body_metrics as BM

        inputs.append(BM.out_path(cid))
    # the actor's own .blend is the GLB's immediate input: when proxy_actor has
    # rewritten it but rig_export_glb has not run yet (a build still queued on
    # the Blender flock), the sidecar already reports the new fit while the GLB
    # is still the old geometry — that pair must never be served as fresh
    inputs.append(os.path.join(adir, name + '.blend'))
    # the build scripts themselves are inputs: an actor built before the
    # skeleton mesh / UV export landed must rebuild itself, not be served stale
    inputs.extend(os.path.join(HERE, 'blender_scripts', f) for f in ('rig_export_glb.py', 'skeleton_bind.py'))
    # proxy_actor is a package since 2026-10: every module of it is a build input
    _pa_dir = os.path.join(HERE, 'blender_scripts', 'proxy_actor')
    if os.path.isdir(_pa_dir):
        inputs.extend(os.path.join(_pa_dir, f) for f in sorted(os.listdir(_pa_dir)) if f.endswith('.py'))
    src = ML.clip_path(motion)
    if src:
        inputs.append(src)
    for p in inputs:
        if os.path.isfile(p) and os.path.getmtime(p) > made:
            return False
    return True


def _op_build(payload, method):  # noqa: ARG001
    from zyg_workflows import motion_library as ML

    cid = str(payload.get('char_id') or '').strip()
    if not base_kind(cid) and (not _char_dir(cid) or _bible(cid) is None):
        return {
            'error': 'unknown character %r — a skeleton is built for a character '
            'with a bible, or for base_male_realistic / '
            'base_female_realistic' % cid,
            'code': 404,
        }
    motion = str(payload.get('motion') or '').strip()
    if ML.clip(motion) is None:
        return {'error': 'unknown motion %r' % motion, 'code': 404}
    name = actor_name(cid, motion)
    if not _ACTOR_RE.match(name):
        return {'error': 'motion %r does not make a usable actor name' % motion}
    fit = bool(payload.get('fit', True)) and not base_kind(cid)

    if _glb_is_fresh(name, motion, fit):
        return {'ok': True, 'cached': True, 'actor': name, 'glb': _glb_url(name), 'meta': _actor_meta(name)}

    adir = os.path.join(ACTORS_DIR, name)
    os.makedirs(adir, exist_ok=True)
    job = _Job('build', actor=name, char_id=cid, motion=motion, fit=bool(fit))
    job.log('build %s (%s, fit=%s)' % (name, motion, bool(fit)))
    res = _spawn(job, _build_worker, cid, motion, fit, name, adir)
    res['actor'] = name
    return res


def _op_job(payload, method):  # noqa: ARG001
    rec = _read_job(str(payload.get('job_id') or ''))
    if rec is None:
        return {'error': 'unknown job', 'code': 404}
    rec['ok'] = True
    return rec


# ── bytes ────────────────────────────────────────────────────────────────────
def _op_glb(payload, method):  # noqa: ARG001
    name = str(payload.get('name') or '').strip()
    adir = _actor_dir(name)
    if not adir:
        return {'error': 'bad actor name %r' % name, 'code': 404}
    path = os.path.join(adir, name + '.glb')
    try:
        with open(path, 'rb') as fh:
            blob = fh.read()
    except OSError:
        return {'error': 'no GLB for %r — build it first' % name, 'code': 404}
    # filename None: the browser's glTF loader fetches this, it is not a download
    return blob, 'model/gltf-binary', None


def _op_video(payload, method):  # noqa: ARG001
    rec = _read_job(str(payload.get('job_id') or ''))
    if rec is None:
        return {'error': 'unknown job', 'code': 404}
    path = str(rec.get('video') or '')
    if not path or not os.path.isfile(path):
        return {'error': 'job %s has no final.mp4 (status %s)' % (rec.get('job_id'), rec.get('status')), 'code': 404}
    try:
        with open(path, 'rb') as fh:
            blob = fh.read()
    except OSError:
        return {'error': 'cannot read %s' % path, 'code': 404}
    return blob, 'video/mp4', None


# ── edit ─────────────────────────────────────────────────────────────────────
def _op_edit(payload, method):  # noqa: ARG001
    from zyg_workflows import motion_edit as ME
    from zyg_workflows import motion_library as ML

    src = str(payload.get('src') or '').strip()
    if ML.clip(src) is None:
        return {'error': 'unknown source clip %r' % src, 'code': 404}
    save = str(payload.get('save') or '').strip()
    if not _SLUG_RE.match(save):
        return {'error': 'save must be a slug matching %s' % _SLUG_RE.pattern}

    ops = []
    trim = payload.get('trim')
    if trim is not None:
        if not (isinstance(trim, (list, tuple)) and len(trim) == 2):
            return {'error': 'trim must be [first, last]'}
        try:
            ops.append({'op': 'trim', 'first': int(trim[0]), 'last': int(trim[1])})
        except (TypeError, ValueError):
            return {'error': 'trim frames must be integers'}
    if payload.get('speed') is not None:
        try:
            factor = float(payload['speed'])
        except (TypeError, ValueError):
            return {'error': 'speed must be a number'}
        if not factor > 0:
            return {'error': 'speed must be positive'}
        ops.append({'op': 'speed', 'factor': factor})
    if payload.get('mirror'):
        ops.append({'op': 'mirror'})
    if payload.get('loop') is not None:
        try:
            ops.append({'op': 'loop', 'frames': int(payload['loop'])})
        except (TypeError, ValueError):
            return {'error': 'loop must be a frame count'}
    if not ops:
        return {'error': 'nothing to do — give at least one of trim, speed, mirror, loop'}
    try:
        rec = ME.edit(src, ops, save, label=payload.get('label') or None, tags=payload.get('tags') or None)
    except (ValueError, OSError) as e:
        return {'error': str(e)[:400]}
    return {'ok': True, 'clip': rec}


# ── capture ──────────────────────────────────────────────────────────────────
def _capture_worker(job, video, clip_id, label, tags, licence):
    from zyg_workflows import motion_capture as MC

    rec = MC.capture_from_video(video, clip_id, label, tags=tags, licence=licence, log=job.log)
    job.set(clip=rec, motion=clip_id)


def _op_capture(payload, method):  # noqa: ARG001
    video = str(payload.get('video') or '').strip()
    if not video or not os.path.isfile(video):
        return {'error': 'no such video: %r' % video, 'code': 404}
    clip_id = str(payload.get('clip_id') or '').strip()
    if not clip_id.startswith('capture/') or not _SLUG_RE.match(clip_id.split('/', 1)[1]):
        return {'error': "clip_id must be 'capture/<slug>'"}
    label = str(payload.get('label') or '').strip()
    if not label:
        return {'error': 'a capture needs a label — it is what the library shows'}

    with _LOCK:
        live = _live_heavy()
        if live:
            return {
                'error': '%s job %s is already running — capture and render '
                'take the whole GPU, one at a time' % (live.get('kind'), live.get('job_id')),
                'code': 409,
                'busy': live.get('job_id'),
            }
        job = _Job('capture', motion=clip_id, video=video, label=label)
    job.log('capture %s from %s' % (clip_id, video))
    return _spawn(
        job, _capture_worker, video, clip_id, label, tuple(payload.get('tags') or ()), str(payload.get('licence') or '')
    )


# ── render ───────────────────────────────────────────────────────────────────
def _render_shot(job_id, actor, prompt, frames):
    """The take-10 recipe with one actor swapped in. Everything else — camera,
    sun, the whole video block with its refs, keyframe and character_composite —
    is copied verbatim, because that recipe is what makes the identity hold."""
    with open(FIXTURE_SHOT, encoding='utf-8') as fh:
        shot = json.load(fh)
    meta = _actor_meta(actor)
    shot_id = 'mvr_%s' % job_id
    shot['id'] = shot_id
    shot['name'] = 'Movement Studio — %s' % actor
    a = shot['actors'][0]
    a['proxy'] = actor
    if meta.get('motion'):
        a['motion'] = meta['motion']
    if meta.get('height_m'):
        a['height_m'] = meta['height_m']

    if frames is None:
        # the playable range is everything AFTER the rest frame — exporting from
        # the rest frame itself puts a one-frame snap at the head of the clip
        total = int(meta.get('frames') or _RENDER_MAX_FRAMES)
        frames = max(1, total - int(meta.get('rest_frame') or 0))
    frames = max(1, min(int(frames), _RENDER_MAX_FRAMES))
    shot['frames'] = frames
    for key in shot.get('camera', {}).get('keys', []):
        if int(key.get('f') or 0) > frames:
            key['f'] = frames
    for key in a.get('path', []):
        if int(key.get('f') or 0) > frames:
            key['f'] = frames
    if prompt:
        shot['video']['prompt'] = prompt

    sdir = os.path.join(SHOTS_DIR, shot_id)
    os.makedirs(sdir, exist_ok=True)
    src_plates = os.path.join(SHOTS_DIR, 'fixture_capture', 'plates')
    dst_plates = os.path.join(sdir, 'plates')
    if os.path.isdir(src_plates) and not os.path.isdir(dst_plates):
        shutil.copytree(src_plates, dst_plates)
    path = os.path.join(sdir, 'shot.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(shot, fh, indent=1)
    os.replace(tmp, path)
    return path, sdir, frames


def _render_worker(job, actor, prompt, frames):
    path, sdir, n = _render_shot(job.jid, actor, prompt, frames)
    job.set(shot=path, shot_dir=sdir, frames=n)
    job.log('shot written: %s (%d frames)' % (path, n))
    # scene_shot_run is a package since 2026-10: run it as a module, not by file path
    _run_logged(job, [VENV_PYTHON, '-m', 'zyg_workflows.scene_shot_run', path, '--engine', 'vace'], timeout=4 * 3600)
    final = os.path.join(sdir, 'final.mp4')
    if not os.path.isfile(final):
        raise RuntimeError('scene_shot_run wrote no %s' % final)
    job.set(video=final, video_bytes=os.path.getsize(final))
    job.log('final.mp4: %s (%d bytes)' % (final, os.path.getsize(final)))

    # fidelity is EVIDENCE, not a gate: a missing tool must not fail the render
    motion = (_actor_meta(actor) or {}).get('motion') or ''
    try:
        p = subprocess.run(
            [VENV_PYTHON, os.path.join(HERE, 'tools', 'motion_fidelity.py'), motion, sdir],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=900,
        )
        job.set(fidelity=(p.stdout or '').strip()[-4000:])
    except Exception as e:  # noqa: BLE001 — non-fatal by design
        job.log('motion_fidelity did not run: %s: %s' % (type(e).__name__, e))


def _op_render(payload, method):  # noqa: ARG001
    actor = str(payload.get('actor') or '').strip()
    adir = _actor_dir(actor)
    if not adir or not os.path.isfile(os.path.join(adir, actor + '.blend')):
        return {'error': 'unknown actor %r — build it first' % actor, 'code': 404}
    if base_kind(actor.split('__', 1)[0]):
        return {'error': 'the base body has no character to paint — inject a character, then render', 'code': 400}
    frames = payload.get('frames')
    if frames is not None:
        try:
            frames = int(frames)
        except (TypeError, ValueError):
            return {'error': 'frames must be an integer'}
    prompt = str(payload.get('prompt') or '').strip()

    if not _comfy_up():
        return {
            'error': 'ComfyUI is not answering %s — a VACE render without it '
            'is half an hour of waiting for a failure' % COMFY_STATS,
            'code': 409,
        }
    with _LOCK:
        live = _live_heavy()
        if live:
            return {
                'error': '%s job %s is already running — capture and render '
                'take the whole GPU, one at a time' % (live.get('kind'), live.get('job_id')),
                'code': 409,
                'busy': live.get('job_id'),
            }
        job = _Job('render', actor=actor)
    job.log('render %s' % actor)
    return _spawn(job, _render_worker, actor, prompt, frames)


# ── the écorché atlas ────────────────────────────────────────────────────────
# The Muscles layer is a second skin on the body wearing the écorché atlas
# char_photoreal.py bakes into data/assets/mesh_packs/photoreal/<body>_ecorche/.
# Its albedo.jpg and bump.jpg are already served by /inspect/arch-asset/ — the
# MANIFEST is not, because that route's extension allowlist is meshes and
# textures only, and widening it would open every .json under mesh_packs. So the
# manifest comes through here, with the two texture urls resolved, and the
# allowlist stays exactly as tight as it was.
_ECORCHE_ROOT = os.path.join(HERE, 'data', 'assets', 'mesh_packs', 'photoreal')
_ECORCHE_RE = re.compile(r'^[a-z]{1,16}_ecorche$')


def _op_ecorche(payload, method):  # noqa: ARG001
    body = str(payload.get('body') or '').strip()
    if not _ECORCHE_RE.match(body):
        return {'error': 'bad ecorche body %r' % body, 'code': 404}
    d = os.path.join(_ECORCHE_ROOT, body)
    try:
        with open(os.path.join(d, 'manifest.json'), encoding='utf-8') as fh:
            man = json.load(fh)
    except (OSError, ValueError):
        return {'error': 'no ecorche atlas published for %r' % body, 'code': 404}
    base = '/inspect/arch-asset/photoreal/%s/' % body
    out = dict(man)
    out['body'] = body
    for key, default in (('albedo', 'albedo.jpg'), ('bump', 'bump.jpg')):
        name = str(man.get(key) or default)
        fp = os.path.join(d, name)
        if not os.path.isfile(fp):
            return {'error': 'ecorche %s has no %s' % (body, key), 'code': 404}
        out[key + '_url'] = base + name
        out[key + '_mtime'] = os.path.getmtime(fp)
    out['ok'] = True
    return out


ROUTES = {
    'subjects': _op_subjects,
    'ecorche': _op_ecorche,
    'clips': _op_clips,
    'metrics': _op_metrics,
    'build': _op_build,
    'job': _op_job,
    'glb': _op_glb,
    'video': _op_video,
    'edit': _op_edit,
    'capture': _op_capture,
    'render': _op_render,
}
