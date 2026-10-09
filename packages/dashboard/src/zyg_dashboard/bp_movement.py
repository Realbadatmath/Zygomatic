# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_movement.py — launch + status routes for Movement Studio (2026-08-31).

Same shape as bp_kidsmusic.py: the composer/preview panel lives in the :8899
inspection page (a different origin, no dashboard session), so these routes
are LOCALHOST-ONLY and kanban_server.py reaches them the same way it reaches
kidsmusic's — a same-host HTTP hop (_km_forward), never a direct import of
wan_vace_service into the lightweight kanban process.

Subjects come from three existing registries, not a new one:
  character -> canon_service.canon_portrait/canon_prompt_binding (the same
               still + trigger phrase wan_face_restore.py already uses)
  creature  -> the creature dataset tree under ZYG_CREATURE_DATASETS, same
               hero-image priority (preview > sheet > cell > ref) the
               Creature Studio inject picker uses client-side, and the same
               FLUX.1-dev licence withholding kanban_server applies
  object    -> prop_mesh_library's registered prop/creature-mesh assets (the
               Mesh tab's props lane) — there is exactly one today
               (the Pufferball), and that is the whole "objects" catalogue
               until more get built and registered.

2026-09-02 — the full option surface. The eight canned presets and two frame
counts became movement_studio.py: a 56-entry action library and 66 dials, every
one of them reaching generate_vace_static_clip's signature, compose_prompt(), or
one of the eight ZYG_* switches wan_vace_service reads at graph-build time. This
file still owns SUBJECT resolution (still, binding, LoRA, refs) and the job
lifecycle; it owns none of the dial semantics. A caller that sends no `params`
gets movement_studio.defaults(), which is why the pre-existing GUI kept working
across the change.

A job is a directory under output/movement/<job_id>/ holding job.json (the
one source of truth status.html polls) and, once done, vace_static.mp4 (the
fixed filename generate_vace_static_clip always writes). Stopping a job is
render_abort.py's existing contract: touch <run_dir>/ABORT and the watchdog
armed around the render interrupts ComfyUI.
"""

from __future__ import annotations

import json
import os
import contextlib
import re
import threading
import time
import uuid

from flask import Blueprint, jsonify, request

from zyg_workflows import movement_studio as MS
from zyg_workflows.paths import (
    ZYG_COMFY_ROOT,
    ZYG_LORA_DATASETS,
    ZYG_LORA_OUTPUTS,
    ZYG_MODELS_DIR,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('movement', __name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_ROOT = os.path.realpath(os.path.join(_HERE, 'output', 'movement'))
_CHARS_ROOT = os.path.realpath(os.environ.get('ZYG_STORYTELLER_CHARS', str(ZYG_LORA_DATASETS / 'storyteller_chars')))
_CREATURE_ROOT = os.path.realpath(os.environ.get('ZYG_CREATURE_DATASETS', str(ZYG_LORA_DATASETS / 'creatures')))
_CREATURE_OUT_ROOT = os.path.realpath(os.environ.get('ZYG_CREATURE_OUTPUTS', str(ZYG_LORA_OUTPUTS / 'creatures')))
_PROP_ROOT = os.path.realpath(os.path.join(_HERE, 'data', 'assets', 'prop_meshes'))
_LORA_ROOT = str(ZYG_COMFY_ROOT / 'models' / 'loras')

_CHAR_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_CREATURE_ID_RE = re.compile(r'^[a-f0-9]{12}$')
_OBJ_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_JOB_ID_RE = re.compile(r'^[a-f0-9]{12}$')
_IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')
_FLUX1_FAMILIES = {'flux', 'flux1', 'flux-dev', 'flux_dev', 'flux.1-dev', 'flux1-dev'}

# a job at a time — the same "one pipeline at a time" rule bp_kidsmusic enforces,
# just scoped to this workflow's own renders rather than the whole _workflow_jobs
# dispatcher (Movement Studio jobs are ad-hoc single clips, not staged pipelines,
# so they do not register themselves into that dict)
_ACTIVE = {'job_id': None}


def _local_only():
    return request.remote_addr in ('127.0.0.1', '::1')


def _job_dir(job_id):
    return os.path.join(_OUT_ROOT, job_id)


def _write_job(run_dir, **fields):
    p = os.path.join(run_dir, 'job.json')
    cur = {}
    if os.path.isfile(p):
        try:
            with open(p, encoding='utf-8') as fh:
                cur = json.load(fh) or {}
        except (OSError, ValueError):
            cur = {}
    cur.update(fields)
    cur['updated'] = time.time()
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(cur, fh, indent=2)
    os.replace(tmp, p)
    return cur


def _read_job(job_id):
    if not _JOB_ID_RE.match(job_id):
        return None
    p = os.path.join(_job_dir(job_id), 'job.json')
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _append_log(job_id, run_dir, msg):
    j = _read_job(job_id) or {}
    lg = j.get('log') or []
    lg.append(f'{time.strftime("%H:%M:%S")} {msg}')
    _write_job(run_dir, log=lg[-200:])


# ── subject resolution: still image + optional Wan LoRA + prompt binding ────
def _images_in(d, prefix=None, limit=8):
    """Sorted image paths under one directory — the pool the identity-refs dial
    draws its extra stills from. Never recurses: a ref must be a portrait of the
    subject, and the first thing a recursive walk finds under a character folder
    is training crops."""
    try:
        names = sorted(
            n for n in os.listdir(d) if n.lower().endswith(_IMG_EXT) and (not prefix or n.startswith(prefix))
        )
    except OSError:
        return []
    return [os.path.join(d, n) for n in names[:limit]]


def _resolve_character(sid):
    if not _CHAR_ID_RE.match(sid):
        return None
    d = os.path.realpath(os.path.join(_CHARS_ROOT, sid))
    if not (d.startswith(_CHARS_ROOT + os.sep) and os.path.isdir(d)):
        return None
    from zyg_workflows import canon_service as CS

    still = CS.canon_portrait(sid)
    if not still or not os.path.isfile(still):
        return None
    lora = None
    for cand in (f'wan_chars/wan_char_{sid}_t2v.safetensors', f'wan_chars/wan_char_{sid}.safetensors'):
        if os.path.isfile(os.path.join(_LORA_ROOT, cand)):
            lora = cand
            break
    # ref candidates, best first. build_vace_ref is the one purpose-built for this
    # seat (white-background bust, per the VACE user guide) — the raw contact-sheet
    # cells behind it are a busier fallback, not an equal.
    refs = []
    try:
        vr = CS.build_vace_ref(sid)
        if vr and os.path.isfile(vr):
            refs.append(vr)
    except Exception as _exc:  # noqa: BLE001 — a missing ref is not a failed render
        _zyg_log.debug('vace reference build skipped: %s', _exc)
    for cells in (os.path.join(d, 'arcane_instantid'), os.path.join(d, 'contact_sheet', 'cells')):
        refs.extend(x for x in _images_in(cells, 'cell_', limit=4) if x not in refs)
    return {'still': still, 'binding': CS.canon_prompt_binding(sid), 'lora': lora, 'refs': refs}


def _first_image(d, prefix=None):
    try:
        names = sorted(
            n for n in os.listdir(d) if n.lower().endswith(_IMG_EXT) and (not prefix or n.startswith(prefix))
        )
    except OSError:
        return None
    return os.path.join(d, names[0]) if names else None


def _resolve_creature(sid):
    if not _CREATURE_ID_RE.match(sid):
        return None
    d = os.path.realpath(os.path.join(_CREATURE_ROOT, sid))
    if not (d.startswith(_CREATURE_ROOT + os.sep) and os.path.isdir(d)):
        return None
    man = {}
    for fn in ('manifest.json', 'brief.json'):
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as fh:
                man = {**(json.load(fh) or {}), **man}
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('creature %s unreadable, continuing without it: %s', fn, _exc)
            continue
    # FLUX.1-dev creatures are withheld everywhere else in the GUI (the base
    # licence is non-commercial and the channel is monetised) — a movement
    # clip built from one of those stills is the same exposure, so refuse it
    # here too rather than trusting the caller not to ask. The trained-weights
    # directory name wins over the manifest's train_family, same precedence
    # kanban_server._api_creatures uses — a creature retrained under a
    # different family after the brief was written must not fall back to a
    # stale manifest value.
    fam = ''
    out_dir = os.path.realpath(os.path.join(_CREATURE_OUT_ROOT, sid))
    if out_dir.startswith(_CREATURE_OUT_ROOT + os.sep) and os.path.isdir(out_dir):
        try:
            weight_dirs = sorted(e for e in os.listdir(out_dir) if e.startswith('lora-weights-'))
        except OSError:
            weight_dirs = []
        if weight_dirs:
            fam = weight_dirs[-1][len('lora-weights-') :]
    fam = fam or str(man.get('train_family') or '').strip().lower()
    if fam.strip().lower() in _FLUX1_FAMILIES:
        return None
    still = (
        _first_image(d, 'preview_')
        or _first_image(os.path.join(d, 'contact_sheet'), 'sheet')
        or _first_image(os.path.join(d, 'contact_sheet', 'cells'))
        or _first_image(d, 'ref_')
    )
    if not still:
        return None
    refs = [still] + [x for x in (_images_in(d, 'preview_', limit=3) + _images_in(d, 'ref_', limit=3)) if x != still]
    return {'still': still, 'binding': man.get('trigger_token') or '', 'lora': None, 'refs': refs}


def _resolve_object(sid):
    if not _OBJ_ID_RE.match(sid):
        return None
    try:
        from zyg_workflows import prop_mesh_library as PML
    except Exception:  # noqa: BLE001 — a missing registry must 404, not 500
        return None
    rec = PML.get(sid)
    prevs = (rec or {}).get('previews') or []
    if not prevs:
        return None
    still = os.path.realpath(os.path.join(_PROP_ROOT, prevs[0]))
    if not (still.startswith(_PROP_ROOT + os.sep) and os.path.isfile(still)):
        return None
    lora = None
    cand = f'wan_props/wan_prop_{sid}.safetensors'
    if os.path.isfile(os.path.join(_LORA_ROOT, cand)):
        lora = cand
    refs = []
    for rel in prevs[:4]:
        rp = os.path.realpath(os.path.join(_PROP_ROOT, rel))
        if rp.startswith(_PROP_ROOT + os.sep) and os.path.isfile(rp):
            refs.append(rp)
    return {'still': still, 'binding': rec.get('name') or sid, 'lora': lora, 'refs': refs}


_RESOLVERS = {'character': _resolve_character, 'creature': _resolve_creature, 'object': _resolve_object}


@contextlib.contextmanager
def _env_scope(overrides):
    """Apply movement_studio.env_overrides for exactly one render, then put the
    process environment back the way it was.

    These eight switches are read by wan_vace_service at graph-build time and
    there is no keyword route to them. Mutating os.environ is only safe because
    mv_start refuses to start a second job while one is running (and refuses
    while ANY workflow job is running), so nothing else can observe the window.
    Restore is in a finally, and a key that was UNSET goes back to unset rather
    than to an empty string — 'ZYG_LORA_ATTEST=""' and an absent
    ZYG_LORA_ATTEST are the same to that reader today, but the next reader to
    use os.environ.get(k) is not required to agree."""
    prev = {k: os.environ.get(k) for k in MS._ENV_KEYS}
    try:
        for k, v in (overrides or {}).items():
            if v == '':
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _score_run(run_dir, log):
    """identity_bank.score_run over the finished clip, or {} — ADVISORY.

    Called only when the attribute exists: score_run is S03's per-frame identity
    instrument and this tab must keep rendering while it does not. A score is
    never a gate here; nothing in this file reads the number back."""
    try:
        from zyg_workflows import identity_bank as IB

        fn = getattr(IB, 'score_run', None)
        if fn is None:
            return {}
        out = fn(run_dir)
        if isinstance(out, dict) and out:
            log(
                'identity (advisory): '
                + ', '.join(f'{k}={v}' for k, v in sorted(out.items()) if isinstance(v, (int, float, str)))[:400]
            )
            return out
    except Exception as e:  # noqa: BLE001 — a score must never fail a render
        log(f'identity score unavailable ({type(e).__name__}: {e})')
    return {}


def _run_job(job_id, run_dir, subj, prompt, mode, params, num_frames):
    _ACTIVE['job_id'] = job_id

    def log(msg):
        _append_log(job_id, run_dir, msg)

    _write_job(run_dir, status='running')
    log(f'render starting ({mode})')
    clip = None
    aborted = False
    try:
        from zyg_workflows import render_abort as RA
        from zyg_workflows import wan_vace_service as V

        # SCENE PLATE SET. The still is the one argument of this call that is
        # positional, so the override has to happen here rather than inside the
        # kwargs builder. Everything else about the subject — the LoRA chain and
        # the identity refs below — is untouched by the scene: the shot supplies
        # the frame, the subject still supplies who is in it.
        still = MS.still_for(params, subj['still'])
        if still != subj['still']:
            log(f'scene still <- {still}')
        kw = MS.render_kwargs(params, num_frames_override=num_frames, still_path=still, log_fn=log)
        # CONTROL PATH rack. control_kwargs RAISES rather than dropping an
        # argument the installed signature cannot take: a job asked to render
        # from a driver folder must fail loudly, not quietly produce a clip off
        # the still that looks like it was driven.
        kw.update(MS.control_kwargs(params, generate_fn=V.generate_vace_static_clip, log_fn=log))
        if kw.get('prop_plates'):
            pl = kw['prop_plates'][0]
            log(
                f'prop plate: {os.path.basename(pl["plate"])} '
                f'({pl["meta"].get("asset")}/{pl["meta"].get("view")}/'
                f'{pl["meta"].get("kind")}) strength={pl["strength"]}'
            )
        loras = MS.lora_chain(params, auto_name=subj.get('lora') or '')
        n_refs = int(params.get('identity_refs', 1))
        refs = [r for r in (subj.get('refs') or []) if os.path.isfile(r)][:n_refs]
        env = MS.env_overrides(params)
        nd = MS.nondefault(params)
        log(
            f'{kw["num_frames"]}f {kw["width"]}x{kw["height"]} shift={kw["shift"]} '
            f'cfg={kw["cfg"]} steps={kw["steps"]} seed={kw["seed"]} '
            f'pin={kw["vace_strength"]}/{kw["vace_start_percent"]}-{kw["vace_end_percent"]}'
        )
        log(
            f'loras={loras or "none"} refs={len(refs)} '
            f'windows={"on" if kw["context_windows"] else "off"} '
            f'pin_regions={"1 box" if kw["pin_regions"] else "off"}'
        )
        if nd:
            log('non-default dials: ' + ', '.join(f'{k}={v}' for k, v in sorted(nd.items())))
        wd = RA.watchdog(run_dir, log_fn=log).start()
        try:
            # Every value below now comes off the dial state. The two that used to be
            # hard-coded here and must never quietly drift back to the FUNCTION's own
            # defaults are shift (its default 2.0 renders a frozen clip; the spec
            # default is the measured 5.0) and vace_end_percent (0.35, which frees the
            # subject for the last two-thirds of the denoise).
            with _env_scope(env):
                clip = V.generate_vace_static_clip(
                    still, prompt, run_dir, loras=loras or None, ref_images_paths=refs or None, log_fn=log, **kw
                )
        finally:
            aborted = wd.stop()
    except Exception as e:  # noqa: BLE001 — a render must end the job, not the thread
        log(f'ERROR: {type(e).__name__}: {e}')
    if clip and os.path.isfile(clip):
        _write_job(
            run_dir,
            status='done',
            output_file=os.path.basename(clip),
            identity=_score_run(run_dir, log),
            ended=time.time(),
        )
        log('done')
    elif aborted:
        _write_job(run_dir, status='aborted', ended=time.time())
        log('aborted by operator')
    else:
        j = _read_job(job_id) or {}
        _write_job(run_dir, status='error', error=j.get('error') or 'render failed — see log', ended=time.time())
    _ACTIVE['job_id'] = None


def _resolve_prompt(data, params):
    """The motion sentence this request will render, and the action it came from.

    ONE composition path. A caller may send `motion_prompt` outright (the
    2026-08-31 GUI does, and so does anything replaying an old job), and that
    text wins verbatim — otherwise the sentence is composed from the dials by
    movement_studio, which is the same call /api/internal/movement/prompt makes
    for the preview. Two composition paths is how a preview starts lying."""
    action = str(data.get('action') or data.get('preset') or '')
    sent = str(data.get('motion_prompt') or '').strip()
    if sent:
        return sent, action
    return MS.compose_prompt(params, action), action


@bp.route('/api/internal/movement/spec', methods=['GET'])
def mv_spec():
    """Read-only, so not localhost-gated — the same rule km_status follows.
    Re-read on every tab enter, so a newly trained Wan LoRA appears in the
    picker after a process restart without a code change."""
    return jsonify(MS.spec())


@bp.route('/api/internal/movement/prompt', methods=['POST'])
def mv_prompt():
    """The exact sentence a render with these dials would submit, plus the two
    things the recipe adds that are not dials — so the preview shows the whole
    prompt rather than the half this file happens to own."""
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    params = MS.sanitize(data.get('params') or {})
    motion, action = _resolve_prompt(data, params)
    binding = ''
    subj_type, subj_id = str(data.get('subject_type') or ''), str(data.get('subject_id') or '')
    if subj_type in _RESOLVERS and subj_id:
        subj = _RESOLVERS[subj_type](subj_id)
        if subj and params.get('binding'):
            binding = subj.get('binding') or ''
    full = f'{binding}. {motion}' if binding else motion
    return jsonify(
        {
            'ok': True,
            'action': action,
            'motion_prompt': motion,
            'binding': binding,
            'prompt': full,
            'camera_prefix': '固定镜头, static shot, fixed camera, locked-off tripod shot.',
            'extra_negative': params.get('negative_prompt') or '',
            'nondefault': MS.nondefault(params),
            'render_kwargs': MS.render_kwargs(params),
            'env': MS.env_overrides(params),
        }
    )


# ── the two CONTROL PATH / PROP PLATES helpers the GUI calls ────────────────
_BODY_PY = str(ZYG_MODELS_DIR / 'sam3' / 'body_venv' / 'bin' / 'python')
_TRACK_ROOT = os.path.realpath(os.path.join(_OUT_ROOT, '_tracks'))


@bp.route('/api/internal/movement/plate', methods=['POST'])
def mv_plate():
    """Which control map this dial state will actually plate, or why none.

    Reads the manifest and stats the file — it never renders, so the chip
    cannot claim a plate that the render would not find."""
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    return jsonify(MS.plate_chip(MS.sanitize(data.get('params') or {})))


_PLATE_MODES = ('depth', 'normal', 'skeleton', 'seg', 'composite')
# One track at a time, for the same reason a render is one at a time: pose_track
# puts SAM 3D Body on the GPU. Separate from _ACTIVE because a track is not a
# render — you may well want to extract the next driver while a clip renders.
_ACTIVE_TRACK = {'job_id': None}


def _read_track_job(job_id):
    if not _JOB_ID_RE.match(job_id):
        return None
    p = os.path.join(_TRACK_ROOT, job_id, 'job.json')
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _run_track(job_id, out, clip, plate_mode, subject, subject_name):
    """pose_track then track_plates, both in the SAM 3D Body venv.

    The two subprocesses are minutes-to-an-hour of GPU work, which is why this
    is a thread behind a job.json rather than the body of an HTTP request: the
    GUI polls the same file the thread writes, so a lost connection or a reloaded
    page never loses the extraction.

    `subject` is the phrase SAM 3 is asked to find. It is not optional in
    practice: geom.pose_track without --subject falls back to a whole-image
    single-person track and writes NO masks at all (pose_track.py:474), which is
    why the first Track jobs came back with empty Mask frames. Resolution order
    is the typed phrase, then the loaded subject's name, then a generic noun —
    never nothing."""
    _ACTIVE_TRACK['job_id'] = job_id
    import subprocess

    def log(msg):
        j = _read_track_job(job_id) or {}
        lg = j.get('log') or []
        lg.append(f'{time.strftime("%H:%M:%S")} {msg}')
        _write_job(out, log=lg[-200:])

    def fail(msg):
        _write_job(out, status='error', error=msg, ended=time.time())
        log(f'ERROR: {msg}')

    subject = (subject or '').strip() or (subject_name or '').strip() or 'the person'
    _write_job(out, status='running', subject=subject)
    try:
        log(f'pose_track over {os.path.basename(clip)} — subject {subject!r}')
        r = subprocess.run(
            [_BODY_PY, '-m', 'geom.pose_track', clip, '--out', out, '--subject', subject],
            cwd=_HERE,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        for ln in (r.stdout or '').strip().splitlines()[-30:]:
            log('  ' + ln.strip()[:300])
        track = os.path.join(out, 'track.json')
        if r.returncode != 0 or not os.path.isfile(track):
            log((r.stderr or '').strip().splitlines()[-1][:300] if r.stderr else '')
            return fail(f'pose_track exit {r.returncode} — no track.json')
        # geom.pose_track's output contract: <out>/track.json, <out>/frames/f_*.png
        # (the extracted video frames) and <out>/masks/m_*.png (per-frame subject
        # masks). The control PLATES are geom.track_plates' job — the raw video
        # frames must never be handed over as control_dir, they are not a control
        # channel and would drive the render as if they were.
        masks = os.path.join(out, 'masks')
        n_masks = len([f for f in os.listdir(masks) if f.endswith('.png')]) if os.path.isdir(masks) else 0
        _write_job(
            out,
            track=track,
            mask_dir=masks if n_masks else '',
            masks=n_masks,
            mask_reason='' if n_masks else f'SAM 3 found no subject for {subject!r}',
        )
        log(
            f'track.json written, {n_masks} masks' + ('' if n_masks else f' — SAM 3 found nothing matching {subject!r}')
        )

        log('track_plates: ' + ','.join(_PLATE_MODES))
        r2 = subprocess.run(
            [_BODY_PY, '-m', 'geom.track_plates', track, '--modes', ','.join(_PLATE_MODES)],
            cwd=_HERE,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        for ln in (r2.stdout or '').strip().splitlines()[-30:]:
            log('  ' + ln.strip()[:300])
        # The report is the contract, not stdout: track_plates.build writes
        # <track_dir>/plates_report.json with {modes: {mode: {dir, frames, ...}}}.
        # Exit 2 means a requested mode came out CONSTANT grey (its own audit) —
        # the plates still exist, so that is a warning on the job, not a failure,
        # unless the mode being asked for is the constant one.
        rep = {}
        rp = os.path.join(out, 'plates_report.json')
        try:
            with open(rp, encoding='utf-8') as fh:
                rep = json.load(fh) or {}
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('plates report unreadable, falling back to the stderr tail: %s', _exc)
        m = (rep.get('modes') or {}).get(plate_mode) or {}
        if not m.get('dir'):
            log((r2.stderr or '').strip().splitlines()[-1][:300] if r2.stderr else '')
            return fail(f'track_plates exit {r2.returncode} — no {plate_mode} plates')
        if not m.get('audit_ok'):
            log(f'WARNING {plate_mode} plates audit: {m.get("audit_verdict")}')
        _write_job(
            out,
            status='done',
            control_dir=m['dir'],
            plate_mode=plate_mode,
            frames=int(m.get('frames') or 0),
            size=rep.get('size') or [],
            plates_report=rp,
            plate_audit_ok=bool(m.get('audit_ok')),
            plate_audit=str(m.get('audit_verdict') or ''),
            ended=time.time(),
        )
        log(f'done — {m.get("frames")} {plate_mode} plates')
    except subprocess.TimeoutExpired:
        fail('timed out after 3600s')
    except Exception as e:  # noqa: BLE001 — must end the job, not the thread
        fail(f'{type(e).__name__}: {e}')
    finally:
        _ACTIVE_TRACK['job_id'] = None


@bp.route('/api/internal/movement/driver', methods=['GET', 'POST'])
def mv_driver():
    """Extract a per-frame body track from a driver clip, as a background job.

    POST {clip, plate_mode?, subject?, subject_name?} starts it and returns the
    job id; GET ?job=<id> returns that job's job.json. The work is
    geom.pose_track (the fitted body track) followed by geom.track_plates (that
    track rasterised into VACE control plates), both run in the SAM 3D Body venv
    — the only interpreter with those weights' dependencies. On success
    `control_dir` is the plate folder for the Control frames field and
    `mask_dir` the per-frame masks — the masks only exist when pose_track was
    given a `subject` phrase to segment, so the job always sends one and records
    the phrase it used in job.json."""
    if request.method == 'GET':
        j = _read_track_job(str(request.args.get('job') or ''))
        if not j:
            return jsonify({'error': 'unknown track job'}), 404
        return jsonify(j)
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    clip = os.path.realpath(str(data.get('clip') or ''))
    plate_mode = str(data.get('plate_mode') or 'composite')
    subject = str(data.get('subject') or '').strip()
    subject_name = str(data.get('subject_name') or '').strip()
    if plate_mode not in _PLATE_MODES:
        return jsonify({'error': f'plate_mode must be one of {", ".join(_PLATE_MODES)}'}), 400
    if not os.path.isfile(clip):
        return jsonify({'error': f'driver clip not found: {clip}'}), 404
    if not os.path.isfile(_BODY_PY):
        return jsonify({'error': f'SAM 3D Body venv missing: {_BODY_PY}'}), 500
    if _ACTIVE_TRACK['job_id']:
        return jsonify(
            {'error': 'track_busy — one extraction at a time (one GPU)', 'running_id': _ACTIVE_TRACK['job_id']}
        ), 409
    job_id = uuid.uuid4().hex[:12]
    out = os.path.join(_TRACK_ROOT, job_id)
    os.makedirs(out, exist_ok=True)
    _write_job(
        out,
        job_id=job_id,
        status='queued',
        clip=clip,
        plate_mode=plate_mode,
        out_dir=out,
        track='',
        mask_dir='',
        control_dir='',
        masks=0,
        frames=0,
        subject='',
        mask_reason='',
        log=[],
        error='',
        started=time.time(),
    )
    threading.Thread(
        target=_run_track,
        name=f'movement-track-{job_id}',
        args=(job_id, out, clip, plate_mode, subject, subject_name),
        daemon=True,
    ).start()
    return jsonify({'ok': True, 'job_id': job_id, 'out_dir': out})


@bp.route('/api/internal/movement/presets', methods=['GET', 'POST'])
def mv_presets():
    if request.method == 'GET':
        return jsonify({'presets': MS.presets()})
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    d = request.get_json(silent=True) or {}
    op = str(d.get('op') or 'save')
    try:
        if op == 'save':
            return jsonify(
                {'ok': True, 'name': MS.preset_save(d.get('name'), d.get('params') or {}, d.get('action') or '')}
            )
        if op == 'load':
            p = MS.preset_load(d.get('name'))
            return jsonify({'ok': True, 'action': p.pop('_action', ''), 'params': p})
        if op == 'delete':
            MS.preset_delete(d.get('name'))
            return jsonify({'ok': True})
    except (OSError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'error': f'unknown op {op!r}'}), 400


@bp.route('/api/internal/movement/delete', methods=['POST'])
def mv_delete():
    """Remove one finished job folder. Refuses the RUNNING job outright rather
    than deleting the directory a watchdog and a ComfyUI submit are both still
    writing into — stop it first, then delete."""
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    job_id = str((request.get_json(silent=True) or {}).get('job_id') or '')
    if not _JOB_ID_RE.match(job_id):
        return jsonify({'error': 'bad job_id'}), 400
    if _ACTIVE['job_id'] == job_id:
        return jsonify({'error': 'that job is still running — stop it first'}), 409
    run_dir = os.path.realpath(_job_dir(job_id))
    if not (run_dir.startswith(_OUT_ROOT + os.sep) and os.path.isdir(run_dir)):
        return jsonify({'error': 'unknown job'}), 404
    import shutil

    try:
        shutil.rmtree(run_dir)
    except OSError as e:
        return jsonify({'error': f'could not delete: {e}'}), 500
    return jsonify({'ok': True, 'job_id': job_id})


@bp.route('/api/internal/movement/start', methods=['POST'])
def mv_start():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    subject_type = str(data.get('subject_type') or '')
    subject_id = str(data.get('subject_id') or '')
    mode = str(data.get('mode') or 'probe')
    params = MS.sanitize(data.get('params') or {})
    motion_prompt, action = _resolve_prompt(data, params)
    if subject_type not in _RESOLVERS:
        return jsonify({'error': f'unknown subject_type {subject_type!r}', 'allowed': sorted(_RESOLVERS)}), 400
    if not motion_prompt:
        return jsonify({'error': 'motion_prompt is required'}), 400
    if mode not in ('probe', 'full'):
        return jsonify({'error': "mode must be 'probe' or 'full'"}), 400
    # A probe is the SAME dial state at a short length — not a second recipe.
    # Anything else and the thing you approved on the probe is not the thing the
    # full render produces, which is the whole point of having a probe.
    num_frames = 33 if mode == 'probe' else int(params['num_frames'])
    if _ACTIVE['job_id']:
        return jsonify({'error': 'pipeline_busy', 'running_id': _ACTIVE['job_id']}), 409
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        running = [pid for pid, j in _workflow_jobs.items() if j.get('status') == 'running']
        if running:
            return jsonify({'error': 'pipeline_busy', 'running_id': running[0]}), 409
    except Exception as _exc:  # noqa: BLE001 — never block on the check
        _zyg_log.warning('busy check failed, starting the render anyway: %s', _exc)
    subj = _RESOLVERS[subject_type](subject_id)
    if not subj:
        return jsonify(
            {
                'error': f'{subject_type} {subject_id!r} has no usable still image '
                'yet (or its imagery is licence-withheld)'
            }
        ), 404
    binding = subj['binding'] if params.get('binding') else ''
    prompt = f'{binding}. {motion_prompt}' if binding else motion_prompt
    job_id = uuid.uuid4().hex[:12]
    run_dir = _job_dir(job_id)
    os.makedirs(run_dir, exist_ok=True)
    # params are stored WHOLE, not just the non-defaults: "recall this clip's
    # dials" has to reproduce the render even after a default in the spec moves.
    _write_job(
        run_dir,
        job_id=job_id,
        status='queued',
        subject_type=subject_type,
        subject_id=subject_id,
        subject_name=str(data.get('subject_name') or subject_id),
        preset=action,
        action=action,
        mode=mode,
        motion_prompt=motion_prompt,
        prompt=prompt,
        params=params,
        nondefault=MS.nondefault(params),
        num_frames=num_frames,
        log=[],
        error='',
        output_file='',
        started=time.time(),
    )
    t = threading.Thread(
        target=_run_job,
        name=f'movement-{job_id}',
        args=(job_id, run_dir, subj, prompt, mode, params, num_frames),
        daemon=True,
    )
    t.start()
    return jsonify({'ok': True, 'job_id': job_id})


@bp.route('/api/internal/movement/status', methods=['GET'])
def mv_status():
    """Read-only, so not localhost-gated — same rule km_status follows."""
    job_id = str(request.args.get('job_id') or '')
    j = _read_job(job_id)
    if not j:
        return jsonify({'error': 'unknown job'}), 404
    out = dict(j)
    if out.get('status') == 'done' and out.get('output_file'):
        out['video_url'] = f'/inspect/movement/file?id={job_id}'
    return jsonify(out)


@bp.route('/api/internal/movement/stop', methods=['POST'])
def mv_stop():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    job_id = str((request.get_json(silent=True) or {}).get('job_id') or '')
    if not _JOB_ID_RE.match(job_id):
        return jsonify({'error': 'bad job_id'}), 400
    run_dir = _job_dir(job_id)
    if not os.path.isdir(run_dir):
        return jsonify({'error': 'unknown job'}), 404
    try:
        with open(os.path.join(run_dir, 'ABORT'), 'w', encoding='utf-8') as fh:
            fh.write('stopped from Movement Studio\n')
    except OSError as e:
        return jsonify({'error': f'could not write ABORT: {e}'}), 500
    return jsonify(
        {'ok': True, 'job_id': job_id, 'note': "abort requested — the render stops at the watchdog's next poll"}
    )
