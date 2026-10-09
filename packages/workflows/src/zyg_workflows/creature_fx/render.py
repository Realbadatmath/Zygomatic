# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / the render job: pixel-pre, Qwen-Image-Edit at N seeds, best by identity, pixel-post, bake.

Moved verbatim out of the old single-file creature_fx.py (lines 5490-5831).
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
import logging as _zyg_logging

from zyg_workflows.creature_fx.base import CELL_PX, JOBDIR
from zyg_workflows.creature_fx.ops_pixel import _px_trim
from zyg_workflows.creature_fx.ops_dock import OP_BY_ID
from zyg_workflows.creature_fx.resolve import (
    _anchor_path,
    _ensure_comfy_env,
    _write_bake,
    comfy_up,
    licence_of,
    resolve_image,
)
from zyg_workflows.creature_fx.compiler import apply_pixels, compile_stack
from zyg_workflows.creature_fx.preview import _ctx, _open
from zyg_workflows.creature_fx.measurement import _hamm, _phash, _tmp_png


_zyg_log = _zyg_logging.getLogger(__name__)


# ── the render job ──────────────────────────────────────────────────────────
# pixel-pre -> Qwen-Image-Edit (N seeds, best by identity) -> pixel-post -> bake.
# With no generative ops the whole thing is arithmetic and returns in a second,
# which is the deterministic half of the toolbox doing real work with no GPU.

JOBS = {}
_JOBLOCK = threading.Lock()


def _job(jid):
    with _JOBLOCK:
        return JOBS.get(jid)


def _set(jid, **kw):
    with _JOBLOCK:
        j = JOBS.setdefault(jid, {'id': jid})
        j.update(kw)
        j['t'] = time.time()
        return dict(j)


def job_status(jid):
    j = _job(jid)
    return j or {'error': 'no such job'}


def recent_jobs(n=25):
    with _JOBLOCK:
        js = sorted(JOBS.values(), key=lambda r: r.get('started', 0), reverse=True)
    return [dict(r) for r in js[:n]]


def start_render(cid, cat, name, stack, opts=None):
    """Kick off a bake. Returns immediately with a job id."""
    opts = opts or {}
    fp = resolve_image(cid, cat, name)
    x = _ctx(cid)
    comp = compile_stack(stack, x)
    lic = licence_of(cid)
    if not comp['rows']:
        return {'ok': False, 'error': 'the stack is empty — nothing to render'}
    if comp['gen_count'] and lic['render_blocked']:
        return {'ok': False, 'error': lic['block_note']}
    if comp['gen_count'] and not comfy_up():
        return {
            'ok': False,
            'error': 'ComfyUI is not reachable, so the generative half of '
            'this stack cannot run. Deterministic ops alone still '
            'bake — switch the generative ops off to do that.',
        }
    seed = int(opts.get('seed') or 0) or (
        int(hashlib.sha256((comp['instruction'] + str(time.time())).encode()).hexdigest()[:8], 16) % 10**8
    )
    jid = uuid.uuid4().hex[:12]
    plan = {
        'id': jid,
        'creature': cid,
        'name': x.get('name'),
        'source': f'{cat}/{name}',
        'source_path': fp,
        'seed': seed,
        'seeds': max(1, min(6, int(opts.get('best_of') or 1))),
        'steps': max(4, min(60, int(opts.get('steps') or int(os.environ.get('ZYG_QWEN_EDIT_STEPS', '36'))))),
        'cfg': max(1.0, min(12.0, float(opts.get('cfg') or 4.0))),
        'size': max(256, min(2048, int(opts.get('size') or CELL_PX))),
        'strength': max(0.0, min(1.5, float(opts.get('strength') or 1.0))),
        'band': str(opts.get('band') or 'front'),
        'summary': (
            comp['clauses'][0]['lb'].lower() if comp['clauses'] else (OP_BY_ID[comp['rows'][0]['op']]['lb'].lower())
        ),
        'gen_count': comp['gen_count'],
        'pix_count': comp['pix_count'],
        'licence': lic,
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'started': time.time(),
        'state': 'queued',
        'log': [],
    }
    _set(jid, **plan)
    threading.Thread(target=_render_worker, args=(jid, cid, fp, comp, plan), daemon=True).start()
    return {
        'ok': True,
        'job': jid,
        'gen': comp['gen_count'],
        'pix': comp['pix_count'],
        'seed': seed,
        'instruction': comp['instruction'],
    }


def _log(jid, msg):
    with _JOBLOCK:
        j = JOBS.setdefault(jid, {'id': jid})
        j.setdefault('log', []).append(f'{time.strftime("%H:%M:%S")}  {msg}')
        j['log'] = j['log'][-200:]


def _render_worker(jid, cid, fp, comp, plan):
    try:
        _set(jid, state='running', stage='pixel ops (pre)')
        src = _open(fp)
        cur = apply_pixels(src, comp['pre'])
        measured = {}
        if comp['gen_count']:
            cur, measured = _run_edit(jid, cid, cur, comp, plan)
        _set(jid, stage='pixel ops (post)')
        out = apply_pixels(cur, comp['post'])
        _set(jid, stage='measuring')
        measured.update(_measure_pair(cid, src, out, plan['band']))
        meta = dict(plan)
        meta.pop('log', None)
        meta['measured'] = measured
        meta['job'] = jid
        meta['derived_from'] = {'creature': cid, 'source': plan['source'], 'path': fp, 'sha256_source': _sha(fp)}
        png, meta = _write_bake(cid, out, comp, meta)
        _log(jid, f'wrote {os.path.basename(png)}')
        _set(jid, state='done', stage='', file=os.path.basename(png), path=png, measured=measured, finished=time.time())
    except Exception as ex:  # noqa: BLE001
        _log(jid, f'FAILED {type(ex).__name__}: {ex}')
        _set(jid, state='error', error=f'{type(ex).__name__}: {ex}', finished=time.time())


def _sha(fp):
    h = hashlib.sha256()
    with open(fp, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _mesh_control_depth(cid, view):
    """(depth_png, asset_id) for a creature's registered mesh, or (None, why-not).

    The link from creature to mesh is the registry's own `creature_id` field, not a
    path convention: prop_mesh_library hands assets out BY NAME precisely so nothing
    downstream has to guess a directory. A creature with no registered mesh is the
    normal case, and the reason it returns is written into the job log rather than
    swallowed — an op that quietly degrades to a wording change is the failure this
    toolbox exists to refuse.
    """
    try:
        from zyg_workflows import prop_mesh_library as _PML
        from zyg_workflows import mesh_control as _MC
    except Exception as ex:  # noqa: BLE001
        return None, f'the prop-mesh library is unavailable ({type(ex).__name__}: {ex})'
    try:
        aid = next((r['id'] for r in _PML.list_assets() if r.get('creature_id') == cid), None)
    except Exception as ex:  # noqa: BLE001
        return None, f'the prop-mesh registry is unreadable ({ex})'
    if not aid:
        return None, (
            'this creature has no registered mesh — render one with '
            'prop_mesh/sheet_render.py and register it with '
            'prop_mesh/sheet_register.py --creature-id ' + str(cid)
        )
    ids = _PML.view_ids(aid)
    if view not in ids:
        return None, f'{aid} has no view {view!r} (it has: {", ".join(ids)})'
    try:
        _MC.ensure(aid, kinds=('depth', 'matte'))
    except Exception as ex:  # noqa: BLE001
        return None, f'mesh_control could not build {aid} ({type(ex).__name__}: {ex})'
    d = _MC.control_dir(aid)
    p = os.path.join(d, f'{view}_depth.png') if d else ''
    if not p or not os.path.isfile(p):
        return None, (
            f'{aid}/{view} has no depth map — mesh_control skipped that view, which means its subject mask was empty'
        )
    return p, aid


def _run_edit(jid, cid, im, comp, plan):
    """The generative pass: N seeds through the same graph the sheet uses, and
    the winner picked by identity against the creature's own anchor.

    Best-of-N is not "keep the last one": each candidate is scored and the
    ranking is (identity, changed-at-all). A candidate that came back IDENTICAL
    to its source is ranked last however good its identity score is -- an
    unchanged frame trivially maximises identity, which is exactly the null this
    metric needs ([[feedback_measure_before_claim]])."""
    _ensure_comfy_env()
    from zyg_workflows import comfy_generation_service as cgs

    os.makedirs(JOBDIR, exist_ok=True)
    work = os.path.join(JOBDIR, jid)
    os.makedirs(work, exist_ok=True)
    ref = os.path.join(work, 'source.png')
    im.convert('RGB').save(ref)
    anchor, anchor_kind = _anchor_path(cid)
    try:
        from zyg_workflows import creature_identity as cidm

        anchor_emb = cidm.embed(anchor) if anchor else None
    except Exception:  # noqa: BLE001
        cidm, anchor_emb = None, None
    src_hash = _phash(im)
    pkg = {'style_profile': {'render_style': 'stylized'}, 'conditioning': {}}
    cands = []
    prev = os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE')
    # Camera ops are the only ones the multiple-angles LoRA is for. Creatures
    # measurably UNDER-rotate at the graph default, so a stack that asks for a
    # viewpoint runs it at full strength and one that does not runs it at zero:
    # a plain appearance edit is not a camera move and the angles LoRA makes it
    # one ([[creature_sheet_service]]).
    wants_angle = any(c['op'].startswith('cm_') for c in comp['clauses'])
    # `cm_mesh` is the exception: it supplies a TRUE depth pass out of the creature's
    # registered mesh, and comfy_generation_service already drops the angles LoRA to
    # ZYG_QWEN_EDIT_ANGLES_LORA_SCALE_CONTROL (0.0) whenever a control image reaches
    # the qwen_edit_angle branch. Reporting 1.0 here because the op id starts 'cm_'
    # would put a number in the sidecar that the render did not use.
    pose_image, mesh_note = None, ''
    _mv = next((r for r in comp['rows'] if r.get('op') == 'cm_mesh' and r.get('on')), None)
    if _mv is not None:
        pose_image, mesh_note = _mesh_control_depth(cid, str((_mv.get('p') or {}).get('v') or ''))
        if pose_image:
            _log(
                jid,
                f'mesh view: conditioned on {mesh_note}/'
                f'{os.path.basename(pose_image)} — a true Cycles depth pass as '
                'image2, angles LoRA forced to 0',
            )
            wants_angle = False
        else:
            _log(
                jid,
                f'mesh view: NOT conditioned — {mesh_note}. The clause still '
                'went into the instruction, so this render is a wording change.',
            )
    os.environ['ZYG_QWEN_EDIT_ANGLES_LORA_SCALE'] = f'{(1.0 if wants_angle else 0.0):.3f}'
    try:
        for k in range(plan['seeds']):
            seed = plan['seed'] + k * 7919
            dest = os.path.join(work, f'cand_{k}.png')
            _set(jid, stage=f'render {k + 1}/{plan["seeds"]} (seed {seed})')
            _log(jid, f'seed {seed}: {comp["instruction"][:110]}…')
            ok, backend = cgs.generate_still(
                dest,
                comp['instruction'],
                width=plan['size'],
                height=plan['size'],
                steps=plan['steps'],
                cfg=plan['cfg'],
                seed=seed,
                model_family='qwen',
                force_workflow='qwen_edit_angle',
                reference_image=ref,
                pose_image=pose_image,
                character_package=pkg,
                log_fn=lambda m: _log(jid, str(m)[:200]),
                extra_negative=comp['negative'],
                skip_qa=True,
                prompt_finalized=True,
                human_subject=False,
                clear_vram_after=False,
            )
            if not ok or not os.path.isfile(dest):
                _log(jid, f'seed {seed}: render failed ({backend})')
                continue
            cim = _open(dest)
            score = None
            if cidm is not None and anchor_emb is not None:
                try:
                    score = cidm.similarity_emb(anchor_emb, cidm.embed(dest))
                except Exception:  # noqa: BLE001
                    score = None
            moved = _hamm(src_hash, _phash(cim))
            cands.append({'seed': seed, 'path': dest, 'identity': score, 'change_bits': moved})
            _log(jid, f'seed {seed}: identity={score} change={moved}/64 bits')
    finally:
        if prev is None:
            os.environ.pop('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE', None)
        else:
            os.environ['ZYG_QWEN_EDIT_ANGLES_LORA_SCALE'] = prev
    if not cands:
        raise RuntimeError('every seed failed to render — see the job log')
    cands.sort(key=lambda r: (r['change_bits'] > 0, r['identity'] if r['identity'] is not None else -1), reverse=True)
    best = cands[0]
    _log(jid, f'picked seed {best["seed"]} of {len(cands)}')
    out = _open(best['path'])
    n = _strip_bars(out)
    if n:
        _log(jid, f'letterbox bars stripped ({n}px)')
        out = _px_trim(out, {'tol': 10})
    return out, {
        'identity': best['identity'],
        'change_bits': best['change_bits'],
        'seed_used': best['seed'],
        'anchor': os.path.basename(anchor) if anchor else '',
        'anchor_kind': anchor_kind,
        'candidates': cands
        and [{'seed': c_['seed'], 'identity': c_['identity'], 'change_bits': c_['change_bits']} for c_ in cands],
        'angles_lora': 1.0 if wants_angle else 0.0,
        'mesh_view': (
            {'asset': mesh_note, 'depth': os.path.basename(pose_image)}
            if pose_image
            else ({'unavailable': mesh_note} if _mv is not None else None)
        ),
    }


def _strip_bars(im):
    """How many pixels of flat bar sit on the frame, if any. Measured before the
    trim so the log can say it happened -- creature_sheet_service strips these
    after every edit for the same reason."""
    before = im.size
    after = _px_trim(im, {'tol': 10}).size
    return max(before[0] - after[0], before[1] - after[1])


def _measure_pair(cid, src, out, band):
    """Identity and change of the finished bake against its own source."""
    res = {'change_bits_total': _hamm(_phash(src), _phash(out)), 'size': f'{out.width}x{out.height}'}
    try:
        from zyg_workflows import creature_identity as cidm

        anchor, kind = _anchor_path(cid)
        if anchor:
            tmp = _tmp_png(out)
            try:
                sc = cidm.similarity(anchor, tmp)
            finally:
                try:
                    os.unlink(tmp)
                except OSError as _exc:
                    _zyg_log.debug('temp png cleanup skipped: %s', _exc)
            v = cidm.verdict(sc, band)
            res.update(
                {
                    'identity_final': sc,
                    'identity_floor': v['floor'],
                    'identity_pass': v['soft_ok'],
                    'identity_anchor': os.path.basename(anchor),
                    'identity_anchor_kind': kind,
                    'identity_model': cidm.model_id(),
                }
            )
    except Exception as ex:  # noqa: BLE001
        res['identity_error'] = f'{type(ex).__name__}: {ex}'
    return res
