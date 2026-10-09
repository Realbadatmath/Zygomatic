# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character Studio — the Run dock, server side (2026-09-18).

Four ops behind /inspect/api/studio/char_run/:

  start    queue ONE job for ONE character: kind still | sheet | restyle | train.
  status   the job record of one job (status, log tail, outputs).
  stop     write the job's ABORT file. It is a REQUEST, not a kill: the thread
           reads it between steps and unwinds. Nothing here signals a process.
  list     this character's jobs, newest first.

Why a job runner at all, when three of the four backends already have one:
the four Run buttons call four different subsystems (video_stills spawns a
child process, contact_sheet_pipeline runs in-thread for ~25 GPU-min,
arcane_restyle is a per-file loop, lora_trainer_service owns its own thread and
its own status dict) and the dock needs ONE shape to poll and ONE place the
operator can stop. So each kind is wrapped in a thread that writes the same
job.json, and the page polls that.

THE FENCES, in the order start() applies them:

  1. the id must resolve to a character directory under the dataset root
     (the same fence kanban_server._safe_char_dir applies);
  2. the plan must RESOLVE — a restyle with no style_profile.restyle, a train
     with an empty dataset, a sheet whose bible will not load are refused here
     with the reason, not discovered 40 minutes into a GPU run;
  3. sheet, restyle and train need `confirm: true`. Without it start() returns
     {ok: false, needs_confirm: true, plan: …} — the real plan, so the panel can
     state what will run and what it costs before anyone agrees to it. A still
     is ~60 s and needs no confirm;
  4. the GPU must be idle: utilisation < 60 % and free VRAM >= 10 GB, read off
     nvidia-smi and REPORTED in the refusal (a fence that will not say what it
     measured is a fence nobody trusts);
  5. one job at a time across all kinds and all characters — a second start
     gets 409 naming the job that holds the slot. The slot is held on disk (a
     job.json with status queued/running, heartbeated), so a kanban_server
     restart releases it after _STALE_S instead of wedging the dock forever.

comfy_generation_service is NEVER imported at module import time — it loads
models. Every backend import happens inside the worker thread.
"""

import json
import os
import re
import subprocess
import threading
import time
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.realpath(str(paths.ZYG_LORA_DATASETS / 'storyteller_chars'))
_JOBS_ROOT = os.path.join(HERE, 'output', 'charstudio_jobs')
_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_JOB_RE = re.compile(r'^[a-z0-9_]{6,48}$')

KINDS = ('still', 'sheet', 'restyle', 'train')
# A still is one png; the other three are long enough that the operator has to
# agree to them in writing before the GPU is taken.
NEEDS_CONFIRM = ('sheet', 'restyle', 'train')

_GPU_BUSY_PCT = 60  # the board's own threshold, kept identical
_GPU_FREE_MIN_MB = 10 * 1024
_STALE_S = 900  # a live job heartbeats well inside this
_LOG_KEEP = 300
_HEARTBEAT_S = 20

_LOCK = threading.Lock()

# What the still prompt is built from, and what the sheet's flat params dict is
# built from. Both mappings are copied from the module that owns them rather
# than inferred: _AUTO_MAP is character_bible_service.build_from_character_generate's
# own params->bible mapping (the same list studio_ext_server/char_file.py reads
# it off), used here in reverse to turn a saved bible back into the params a
# fresh sheet run would have been given.
_AUTO_MAP = [
    ('gender', 'identity.gender'),
    ('age', 'identity.age'),
    ('height', 'identity.height_m'),
    ('skin_tone', 'identity.skin_tone'),
    ('hair_color', 'identity.hair_color'),
    ('hair_style', 'identity.hair_style'),
    ('hair_length', 'identity.hair_length'),
    ('hair_texture', 'identity.hair_texture'),
    ('eye_color', 'identity.eye_color'),
    ('eye_shape', 'identity.eye_shape'),
    ('eyebrow_style', 'identity.eyebrow_style'),
    ('face_shape', 'identity.face_shape'),
    ('nose_shape', 'identity.nose_shape'),
    ('lip_shape', 'identity.lip_shape'),
    ('body_build', 'identity.body_build'),
    ('muscle_mass', 'identity.muscle_mass'),
    ('facial_hair', 'identity.facial_hair'),
    ('distinctive_marks', 'identity.distinctive_marks'),
    ('ethnic_heritage', 'identity.ethnic_heritage'),
    ('default_clothing', 'default_presentation.default_clothing'),
    ('default_expression', 'default_presentation.default_expression'),
    ('accessories', 'default_presentation.accessories'),
    ('posture', 'default_presentation.posture'),
    ('render_style', 'style_profile.render_style'),
    ('genre', 'style_profile.genre'),
    ('lighting_profile', 'style_profile.lighting_profile'),
    ('color_palette', 'style_profile.color_palette'),
    ('camera_language', 'style_profile.camera_language'),
    ('quality_suffix', 'conditioning.quality_suffix'),
    ('negative_prompt', 'conditioning.negative_prompt'),
]


# ── fences and small helpers ─────────────────────────────────────────────────
def _char_dir(cid):
    """The character's real directory, or None. A direct child of the root and
    nothing else."""
    cid = str(cid or '').strip()
    if not _ID_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(_ROOT, cid))
    if d != os.path.join(_ROOT, cid) or not os.path.isdir(d):
        return None
    return d


def _get(pkg, path):
    cur = pkg
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _gpu_state():
    """(utilisation %, free MiB, error). Both -1 when nvidia-smi is not there —
    which is NOT treated as 'free': a fence that opens when its instrument is
    missing is not a fence."""
    try:
        p = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=utilization.gpu,memory.free', '--format=csv,noheader,nounits'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except Exception as e:  # noqa: BLE001 — reported, not raised
        return -1, -1, f'{type(e).__name__}: {e}'
    if p.returncode != 0:
        return -1, -1, (p.stderr or '').strip()[:200] or f'nvidia-smi exit {p.returncode}'
    line = (p.stdout or '').strip().splitlines()[0] if (p.stdout or '').strip() else ''
    bits = [b.strip() for b in line.split(',')]
    try:
        return int(bits[0]), int(bits[1]), ''
    except (IndexError, ValueError):
        return -1, -1, f'unreadable nvidia-smi output {line!r}'


def _job_dir(jid):
    if not _JOB_RE.match(str(jid or '')):
        return None
    d = os.path.realpath(os.path.join(_JOBS_ROOT, str(jid)))
    if d != os.path.join(os.path.realpath(_JOBS_ROOT), str(jid)):
        return None
    return d


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
    """Atomically, because the page polls this file while the thread writes it —
    a half-written job.json would be a JSON error in the panel every few
    seconds."""
    d = _job_dir(rec['job'])
    if not d:
        return
    os.makedirs(d, exist_ok=True)
    rec['heartbeat'] = round(time.time(), 1)
    tmp = os.path.join(d, f'.job.json.{os.getpid()}.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, indent=1, default=str)
        os.replace(tmp, os.path.join(d, 'job.json'))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError as _exc:
            _zyg_log.debug('temporary job file cleanup skipped: %s', _exc)


def _live_job():
    """The job holding the single slot, or None. Live = status queued/running
    AND heartbeated inside _STALE_S — so a server restart frees the slot by
    itself instead of leaving the dock permanently 409."""
    now = time.time()
    try:
        names = os.listdir(_JOBS_ROOT)
    except OSError:
        return None
    best = None
    for name in names:
        rec = _read_job(name)
        if not rec or rec.get('status') not in ('queued', 'running'):
            continue
        hb = float(rec.get('heartbeat') or rec.get('started') or 0)
        if now - hb > _STALE_S:
            continue
        if best is None or float(rec.get('started') or 0) > float(best.get('started') or 0):
            best = rec
    return best


def _abort_path(jid):
    d = _job_dir(jid)
    return os.path.join(d, 'ABORT') if d else ''


def _aborted(jid):
    p = _abort_path(jid)
    return bool(p) and os.path.exists(p)


class _Abort(Exception):
    """Raised inside a worker when the ABORT file appears."""


# ── the job record the thread keeps ──────────────────────────────────────────
class _Job:
    def __init__(self, jid, kind, cid, name, plan, opts):
        self.rec = {
            'job': jid,
            'kind': kind,
            'id': cid,
            'name': name,
            'status': 'queued',
            'started': round(time.time(), 1),
            'finished': 0.0,
            'plan': plan,
            'opts': opts,
            'log': [],
            'outputs': [],
            'error': '',
        }
        self._last_write = 0.0
        _write_job(self.rec)

    @property
    def jid(self):
        return self.rec['job']

    def log(self, msg):
        self.rec['log'].append(f'{time.strftime("%H:%M:%S")} {str(msg)[:400]}')
        self.rec['log'] = self.rec['log'][-_LOG_KEEP:]
        # Throttled: a sheet run logs several lines a second and the page polls
        # every 3 s, so rewriting the file per line buys nothing and costs IO.
        if time.time() - self._last_write > 1.0:
            self.flush()

    def flush(self):
        self._last_write = time.time()
        _write_job(self.rec)

    def set(self, **kw):
        self.rec.update(kw)
        self.flush()

    def check(self):
        """Between steps. Raises _Abort when the stop route wrote the file."""
        if _aborted(self.jid):
            raise _Abort()
        if time.time() - self._last_write > _HEARTBEAT_S:
            self.flush()


# ── plans ────────────────────────────────────────────────────────────────────
# A plan is what the panel shows BEFORE the GPU is taken, and it is built from
# the same values the worker will use — not a prose description of them. If a
# plan cannot be resolved the job is refused here.
def _plan_still(cid, cdir, pkg, opts):  # noqa: ARG001
    from zyg_workflows import character_bible_service as cbs
    from zyg_workflows import video_stills

    desc = cbs.full_character_descriptor(pkg) or ''
    if not desc.strip():
        return {'error': 'this bible produces an empty descriptor — nothing to render'}

    lens = _get(pkg, 'render.lens_mm')
    ap = _get(pkg, 'render.aperture')
    bg = _get(pkg, 'render.background')
    words = []
    if lens:
        words.append(f'{int(lens)}mm lens')
    if ap:
        words.append(f'f/{float(ap):g}')
    if bg:
        words.append(f'{bg} background')
    qs = (_get(pkg, 'conditioning.quality_suffix') or '').strip().strip(',')
    prompt = ', '.join([p for p in [desc, ', '.join(words), qs] if p])[:2000]

    # conditioning.seed is -1 for "a fresh seed every render" (character_studio
    # FIELDS); video_stills takes 0 for that, so only a real seed is carried.
    try:
        seed = int(_get(pkg, 'conditioning.seed'))
    except (TypeError, ValueError):
        seed = -1
    seed = seed if seed >= 0 else 0

    fam = str(opts.get('family') or _get(pkg, 'conditioning.model_family') or '').lower()
    if fam not in video_stills.FAMILIES:
        # FLUX is paused and SDXL is not a still family here — qwen is what the
        # picture tool sends by default.
        fam = 'qwen'
    return {
        'kind': 'still',
        'id': cid,
        'caller': 'video_stills.generate(prompt, width, height, seed, negative, family)',
        'route': 'the same module POST /video/api/still queues (kanban_server L4370)',
        'prompt': prompt,
        'negative': (_get(pkg, 'conditioning.negative_prompt') or '')[:2000],
        'width': 1280,
        'height': 720,
        'seed': seed,
        'family': fam,
        'outputs': 'one png in output/video_studio/_stills/',
        'expect': 'one png, about 60 s',
    }


def _sheet_params(cid, pkg):
    """The flat params dict generate_contact_sheet reads, rebuilt from the saved
    bible through build_from_character_generate's own mapping and then run
    through apply_auto_defaults — which is exactly what the generation form
    does before a first sheet, so a re-sheet is the same call with the same
    shape of params."""
    from zyg_workflows import character_bible_service as cbs

    params = {'char_id': cid, 'name': pkg.get('display_name') or cid}
    for key, path in _AUTO_MAP:
        params[key] = _get(pkg, path)
    return cbs.apply_auto_defaults(params, seed_key=cid)


def _plan_sheet(cid, cdir, pkg, opts):  # noqa: ARG001
    from zyg_workflows import contact_sheet_pipeline as csp

    params = _sheet_params(cid, pkg)
    fam = str(opts.get('model_family') or _get(pkg, 'conditioning.model_family') or 'flux').strip().lower()
    if fam not in ('flux', 'sdxl', 'qwen', 'klein'):
        fam = 'flux'
    angle_set = str(opts.get('angle_set') or 'extended').strip().lower()
    if angle_set not in ('extended', 'classic'):
        # corpus and custom need a cell plan / an angle_ids selection this dock
        # does not collect — offering them here would start a run that the
        # pipeline then has to guess the shape of.
        return {'error': f'angle_set {angle_set!r} is not offered here — use extended (48 angles) or classic (24)'}
    return {
        'kind': 'sheet',
        'id': cid,
        'caller': 'contact_sheet_pipeline.generate_contact_sheet('
        'char_id, params, log_fn=…, model_family=…, angle_set=…)',
        'params': params,
        'model_family': fam,
        'angle_set': angle_set,
        'mode': csp._resolve_sheet_mode(None),
        'out': csp.master_sheet_path(cid),
        'outputs': 'contact_sheet/contact_sheet_master.png + contact_sheet/cells/',
        'expect': 'about 25 GPU-minutes (48 angles, per-cell)',
        'destructive': 'overwrites this character’s contact sheet and its cells',
    }


def _restyle_sources(cdir, limit):
    """The photoreal cells, which is what the restyle engines take as source —
    the same filter the page's 'cells' image category uses (kanban_server
    _CATS['cells'])."""
    src = os.path.join(cdir, 'contact_sheet', 'cells')
    try:
        names = sorted(
            n for n in os.listdir(src) if n.startswith('cell_') and 'cand' not in n and n.lower().endswith('.png')
        )
    except OSError:
        return src, []
    return src, names[:limit]


def _plan_restyle(cid, cdir, pkg, opts):
    from zyg_workflows import arcane_restyle as ar

    name = (_get(pkg, 'style_profile.restyle') or '').strip()
    if not name:
        return {
            'error': 'this character has no style_profile.restyle — there is no '
            'style to restyle into. The restyle path is an explicit '
            'per-character opt-in, not a default.'
        }
    prof = ar.load_profile(name)
    if not prof or not prof.get('restyle'):
        return {'error': f'style profile {name!r} does not load, or carries no "restyle" block'}
    cfg = prof['restyle']
    engine = (cfg.get('render_engine') or 'qwen_edit').strip().lower()
    fn = {
        'depth_controlnet_arcane': 'depth_controlnet_arcane_restyle',
        'instantid_arcane': 'instantid_arcane_restyle',
    }.get(engine, 'qwen_restyle_image')

    try:
        limit = max(1, min(24, int(opts.get('limit', 4))))
    except (TypeError, ValueError):
        limit = 4
    src_dir, names = _restyle_sources(cdir, limit)
    if not names:
        return {
            'error': f'no photoreal cells to restyle in {src_dir} — a restyle '
            f'reads the sheet cells, so the sheet has to exist first'
        }
    return {
        'kind': 'restyle',
        'id': cid,
        'caller': f'arcane_restyle.{fn}(char_id, style_cfg, src, dst, seed=…, log_fn=…)',
        'fn': fn,
        'profile': name,
        'engine': engine,
        'src_dir': src_dir,
        'sources': names,
        'count': len(names),
        'dst_dir': os.path.join(cdir, 'arcane_instantid'),
        'seed': int(opts.get('seed', 42) or 42),
        'outputs': 'arcane_instantid/ — the ★ Arcane FINAL category the Library shows',
        'expect': f'1–2 GPU-minutes per image, so about {len(names)}–{2 * len(names)} minutes',
        'destructive': 'overwrites any same-named file in arcane_instantid/',
    }


def _plan_train(cid, cdir, pkg, opts):  # noqa: ARG001
    from zyg_workflows import contact_sheet_pipeline as csp

    ds = csp.training_dataset_dir(cid)
    try:
        imgs = [n for n in os.listdir(ds) if n.lower().endswith(('.png', '.jpg', '.jpeg'))]
    except OSError:
        imgs = []
    if not imgs:
        return {
            'error': f'no training images in {ds} — training reads that subdir (png+txt pairs only), and it is empty'
        }
    fam = str(opts.get('model_family') or _get(pkg, 'conditioning.model_family') or 'flux').strip().lower()
    if fam not in ('flux', 'sdxl', 'qwen', 'klein'):
        fam = 'flux'
    tok = (pkg.get('trigger_token') or f'ZYG_CHAR_{cid[:6].upper()}').strip()
    epochs = max(5, int(os.environ.get('ZYG_LORA_EPOCHS', '26')))
    return {
        'kind': 'train',
        'id': cid,
        'caller': 'lora_trainer_service.get_trainer().start_training('
        'char_id, dataset_dir, trigger_token=…, model_family=…)',
        'dataset_dir': ds,
        'images': len(imgs),
        'trigger_token': tok,
        'model_family': fam,
        'steps': f'epoch-scaled by start_training itself — {len(imgs)} images x ~{epochs} epochs, clamped',
        'outputs': f'lora-weights-{fam} under the trainer’s output root',
        'expect': 'HOURS. This is the longest job the dock can start.',
        'destructive': 'replaces this character’s trained weights for that family',
    }


_PLANS = {'still': _plan_still, 'sheet': _plan_sheet, 'restyle': _plan_restyle, 'train': _plan_train}


# ── workers ──────────────────────────────────────────────────────────────────
def _run_still(job, cid, cdir, plan):  # noqa: ARG001
    from zyg_workflows import video_stills

    j = video_stills.generate(
        plan['prompt'], plan['width'], plan['height'], plan['seed'], plan['negative'], plan['family'], label=f'cs_{cid}'
    )
    sub = j.get('id') or ''
    job.set(backend_job=sub)
    job.log(f'video_stills job {sub} queued ({plan["width"]}x{plan["height"]} {plan["family"]} seed {plan["seed"]})')
    seen = 0
    while True:
        job.check()
        time.sleep(3)
        cur = video_stills.job(sub) or {}
        for line in (cur.get('log') or [])[seen:]:
            job.log(line)
        seen = len(cur.get('log') or [])
        state = cur.get('state') or ''
        if state == 'done':
            path = cur.get('path') or ''
            job.rec['outputs'].append(
                {
                    'kind': 'image',
                    'path': path,
                    'url': cur.get('url') or '',
                    'bytes': os.path.getsize(path) if os.path.isfile(path) else 0,
                    'seconds': cur.get('seconds') or 0,
                }
            )
            job.log(f'done in {cur.get("seconds") or "?"}s via {cur.get("backend") or "comfy"}')
            return
        if state == 'error':
            raise RuntimeError(cur.get('error') or 'still generation failed')


def _run_sheet(job, cid, cdir, plan):  # noqa: ARG001
    from zyg_workflows import contact_sheet_pipeline as csp

    def _log(msg):
        job.log(msg)

    def _prog(done, total):
        # The only hook generate_contact_sheet offers that is called often
        # enough to be a stop point — so the ABORT file is read here, and the
        # exception unwinds the generator. Nothing is signalled or killed.
        job.rec['progress'] = {'done': done, 'total': total}
        job.log(f'cell {done}/{total}')
        job.check()

    job.log(
        f'generate_contact_sheet({cid}, params, model_family={plan["model_family"]}, angle_set={plan["angle_set"]})'
    )
    out = csp.generate_contact_sheet(
        cid,
        plan['params'],
        log_fn=_log,
        model_family=plan['model_family'],
        angle_set=plan['angle_set'],
        on_cell_progress=_prog,
    )
    job.rec['outputs'].append(
        {
            'kind': 'sheet',
            'path': out,
            'url': f'/inspect/api/studio/char_file/sheet?id={cid}&which=master',
            'bytes': os.path.getsize(out) if os.path.isfile(out) else 0,
        }
    )
    job.log(f'master sheet written: {out}')


def _run_restyle(job, cid, cdir, plan):
    from zyg_workflows import arcane_restyle as ar

    from zyg_workflows import character_bible_service as cbs

    prof = ar.load_profile(plan['profile']) or {}
    cfg = prof.get('restyle') or {}
    fn = getattr(ar, plan['fn'])
    dst_dir = plan['dst_dir']
    os.makedirs(dst_dir, exist_ok=True)
    cbs.load(cid)  # fail loudly here, not per image
    for i, name in enumerate(plan['sources'], 1):
        job.check()
        src = os.path.join(plan['src_dir'], name)
        dst = os.path.join(dst_dir, name)
        job.log(f'[{i}/{len(plan["sources"])}] {plan["engine"]} {name}')
        ok = fn(cid, cfg, src, dst, seed=plan['seed'], log_fn=job.log)
        if ok and os.path.isfile(dst):
            # cat/name rather than a URL: /inspect/img is scope-fenced, so the
            # page builds the link with its own imgUrl() and withScope().
            job.rec['outputs'].append(
                {
                    'kind': 'image',
                    'path': dst,
                    'url': '',
                    'cat': 'arcane_final',
                    'name': name,
                    'bytes': os.path.getsize(dst),
                }
            )
            job.log(f'  -> {dst}')
        else:
            job.log(f'  no-op on {name} (the engine declined it)')
    if not job.rec['outputs']:
        raise RuntimeError('the restyle engine produced nothing for any source')


def _run_train(job, cid, cdir, plan):  # noqa: ARG001
    from zyg_workflows import lora_trainer_service as lts

    trainer = lts.get_trainer()
    tok = trainer.start_training(
        cid, plan['dataset_dir'], trigger_token=plan['trigger_token'], model_family=plan['model_family']
    )
    res = lts.last_start_result(cid) or {}
    if not tok and not res.get('started'):
        raise RuntimeError(f'start_training refused: {res.get("reason") or "unknown"}')
    job.log(f'training launched, trigger {tok or plan["trigger_token"]}')
    last = -1
    while True:
        job.check()
        time.sleep(10)
        st = trainer.get_status(cid, model_family=plan['model_family']) or {}
        pct = int(st.get('pct') or 0)
        if pct != last:
            last = pct
            job.rec['progress'] = {'done': pct, 'total': 100}
            job.log(f'{pct}% — step {st.get("step")}/{st.get("total_steps")}')
        if st.get('done'):
            path = st.get('lora_path') or trainer.get_lora_path(cid, model_family=plan['model_family'])
            if st.get('error'):
                raise RuntimeError(str(st['error'])[:300])
            job.rec['outputs'].append({'kind': 'lora', 'path': path or '', 'url': '', 'bytes': 0})
            job.log(f'training finished: {path or "(no path reported)"}')
            return


_RUNNERS = {'still': _run_still, 'sheet': _run_sheet, 'restyle': _run_restyle, 'train': _run_train}


def _thread(job, cid, cdir, kind, plan):
    job.set(status='running')
    try:
        _RUNNERS[kind](job, cid, cdir, plan)
    except _Abort:
        job.rec['status'] = 'aborted'
        job.rec['error'] = 'stopped by the operator'
        if kind == 'train':
            # Honest: start_training owns its own thread and its own subprocess.
            # This runner stops WATCHING; it does not stop the training.
            job.log(
                'ABORT honoured by this runner — but lora_trainer_service '
                'owns the training process and is still running it. '
                'Nothing here signals or kills it.'
            )
        else:
            job.log('ABORT honoured — the run was unwound between steps')
    except Exception as e:  # noqa: BLE001 — shown in the panel
        job.rec['status'] = 'error'
        job.rec['error'] = f'{type(e).__name__}: {e}'[:400]
        job.log(f'FAILED {type(e).__name__}: {e}')
    else:
        job.rec['status'] = 'done'
    job.rec['finished'] = round(time.time(), 1)
    job.flush()


# ── routes ───────────────────────────────────────────────────────────────────
def _start(payload, method):  # noqa: ARG001
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    kind = str(payload.get('kind') or '').strip().lower()
    if kind not in KINDS:
        return {'error': f'kind must be one of {", ".join(KINDS)}'}
    opts = payload.get('opts')
    opts = opts if isinstance(opts, dict) else {}

    from zyg_workflows import character_bible_service as cbs

    pkg = cbs.load(cid)
    if pkg is None:
        return {'error': 'this character has no character_bible.json — every Run action reads it', 'code': 404}

    try:
        plan = _PLANS[kind](cid, cdir, pkg, opts)
    except Exception as e:  # noqa: BLE001
        return {'error': f'could not plan this run — {type(e).__name__}: {e}'[:300], 'code': 500}
    if plan.get('error'):
        return {'error': plan['error'], 'code': int(plan.get('code') or 400)}

    if kind in NEEDS_CONFIRM and not payload.get('confirm'):
        return {'ok': False, 'needs_confirm': True, 'plan': plan}

    util, free, gerr = _gpu_state()
    if gerr:
        return {
            'error': f'cannot read the GPU ({gerr}) — refusing to start a GPU job blind',
            'code': 503,
            'gpu': {'util': util, 'free_mb': free},
        }
    if util >= _GPU_BUSY_PCT or free < _GPU_FREE_MIN_MB:
        return {
            'error': f'GPU busy — utilisation {util}% (limit {_GPU_BUSY_PCT}%), '
            f'free VRAM {free} MiB (need {_GPU_FREE_MIN_MB})',
            'code': 409,
            'gpu': {'util': util, 'free_mb': free},
        }

    with _LOCK:
        live = _live_job()
        if live:
            return {
                'error': f'{live.get("kind")} job {live.get("job")} is already '
                f'running for {live.get("id")} — one GPU job at a time',
                'code': 409,
                'busy': live.get('job'),
            }
        jid = f'{kind}_{cid[:8].lower()}_{int(time.time())}'
        os.makedirs(os.path.join(_JOBS_ROOT, jid), exist_ok=True)
        job = _Job(jid, kind, cid, pkg.get('display_name') or cid, plan, opts)

    job.log(f'{kind} queued for {cid}')
    threading.Thread(target=_thread, args=(job, cid, cdir, kind, plan), daemon=True, name=f'charrun-{jid}').start()
    return {'ok': True, 'job': jid, 'kind': kind, 'id': cid, 'plan': plan, 'gpu': {'util': util, 'free_mb': free}}


def _status(payload, method):  # noqa: ARG001
    rec = _read_job(str(payload.get('job') or ''))
    if rec is None:
        return {'error': 'unknown job', 'code': 404}
    rec['ok'] = True
    rec['aborting'] = _aborted(rec['job']) and rec.get('status') in ('queued', 'running')
    return rec


def _stop(payload, method):  # noqa: ARG001
    jid = str(payload.get('job') or '')
    rec = _read_job(jid)
    if rec is None:
        return {'error': 'unknown job', 'code': 404}
    if rec.get('status') not in ('queued', 'running'):
        return {'error': f'job {jid} is {rec.get("status")} — nothing to stop'}
    try:
        with open(_abort_path(jid), 'w', encoding='utf-8') as fh:
            fh.write(f'{time.time()}\n')
    except OSError as e:
        return {'error': f'could not write the ABORT file ({e})', 'code': 500}
    return {
        'ok': True,
        'job': jid,
        'aborting': True,
        'note': 'ABORT written. The runner reads it between steps and unwinds; no process is signalled.',
    }


def _list(payload, method):  # noqa: ARG001
    cid = str(payload.get('id') or '').strip()
    if cid and not _char_dir(cid):
        return {'error': 'unknown character', 'code': 404}
    out = []
    try:
        names = os.listdir(_JOBS_ROOT)
    except OSError:
        names = []
    for name in names:
        rec = _read_job(name)
        if not rec:
            continue
        if cid and rec.get('id') != cid:
            continue
        out.append(
            {k: rec.get(k) for k in ('job', 'kind', 'id', 'name', 'status', 'started', 'finished', 'error', 'progress')}
            | {
                'outputs': len(rec.get('outputs') or []),
                'running': rec.get('status') in ('queued', 'running')
                and (time.time() - float(rec.get('heartbeat') or 0)) < _STALE_S,
            }
        )
    out.sort(key=lambda r: float(r.get('started') or 0), reverse=True)
    live = _live_job()
    util, free, gerr = _gpu_state()
    return {
        'ok': True,
        'id': cid,
        'jobs': out[:40],
        'busy': (live or {}).get('job') or '',
        'gpu': {
            'util': util,
            'free_mb': free,
            'error': gerr,
            'busy_pct': _GPU_BUSY_PCT,
            'free_min_mb': _GPU_FREE_MIN_MB,
        },
    }


def _plan(payload, method):  # noqa: ARG001
    """The plan alone, with no slot taken and no GPU read — what the panel shows
    while it is still only a proposal."""
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    kind = str(payload.get('kind') or '').strip().lower()
    if kind not in KINDS:
        return {'error': f'kind must be one of {", ".join(KINDS)}'}
    opts = payload.get('opts')
    opts = opts if isinstance(opts, dict) else {}
    from zyg_workflows import character_bible_service as cbs

    pkg = cbs.load(cid)
    if pkg is None:
        return {'error': 'this character has no character_bible.json', 'code': 404}
    try:
        plan = _PLANS[kind](cid, cdir, pkg, opts)
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:300], 'code': 500}
    if plan.get('error'):
        return {'error': plan['error'], 'code': 400}
    return {'ok': True, 'id': cid, 'kind': kind, 'plan': plan, 'needs_confirm': kind in NEEDS_CONFIRM}


ROUTES = {
    'start': _start,
    'status': _status,
    'stop': _stop,
    'list': _list,
    'plan': _plan,
}
