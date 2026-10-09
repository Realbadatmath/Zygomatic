# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The render job, the presets, the dock writes, and the payload all three bars are drawn from."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid

from zyg_workflows import creature_fx as cfx

from zyg_workflows.picture_fx.constants import BAKE_DIR, JOBDIR, LIBS, PRESETS
from zyg_workflows.picture_fx.engine import (
    _ctx,
    _open,
    _write_bake,
    compile_stack,
    delete_bake,
    keep_sentence,
    normalise_stack,
    read_recipe,
)
from zyg_workflows.picture_fx.ops_dock import OP_BY_ID
from zyg_workflows.picture_fx.registry import OPS
from zyg_workflows.picture_fx.subject import licence_of, resolve

# ── the render job ──────────────────────────────────────────────────────────
# pixel ops -> services -> Qwen-Image-Edit (N seeds, best by how far it moved)
# -> the rest of the pixel ops -> bake. With no generative and no service op
# the whole thing is arithmetic and returns in under a second; that is not a
# degraded mode, it is the deterministic half of the toolbox doing real work
# with no GPU at all.

JOBS = {}
_JOBLOCK = threading.Lock()
_JOB_KEEP = 40


def _set(jid, **kw):
    with _JOBLOCK:
        j = JOBS.setdefault(jid, {'id': jid})
        j.update(kw)
        j['t'] = time.time()
        return dict(j)


def _log(jid, msg):
    with _JOBLOCK:
        j = JOBS.setdefault(jid, {'id': jid})
        j.setdefault('log', []).append(f'{time.strftime("%H:%M:%S")}  {msg}')
        j['log'] = j['log'][-200:]


def job_status(jid):
    with _JOBLOCK:
        j = JOBS.get(jid)
        return dict(j) if j else {'error': 'no such job'}


def recent_jobs(n=25):
    with _JOBLOCK:
        js = sorted(JOBS.values(), key=lambda r: r.get('started', 0), reverse=True)
    return [dict(r) for r in js[:n]]


def _prune_jobs():
    with _JOBLOCK:
        live = {k for k, j in JOBS.items() if j.get('state') in ('queued', 'running')}
        done = [k for k in sorted(JOBS, key=lambda k: JOBS[k].get('started', 0)) if k not in live]
        for old in done[: max(0, len(done) - _JOB_KEEP)]:
            JOBS.pop(old, None)


def start_render(body):
    """Kick off a bake. Returns immediately with a job id."""
    lib = str(body.get('lib') or '')
    cid = str(body.get('id') or '')
    cat = str(body.get('cat') or '')
    name = str(body.get('name') or '')
    scope = str(body.get('scope') or '')
    stack = body.get('stack') or []
    opts = body.get('opts') or {}
    fp = resolve(lib, cid, cat, name, scope)
    comp = compile_stack(stack, _ctx(lib, cid))
    lic = licence_of(lib, cid)
    if not comp['rows'] and not body.get('mask_b64'):
        return {'ok': False, 'error': 'the stack is empty — nothing to render'}
    needs_gpu = (
        comp['gen_count']
        or bool(body.get('mask_b64'))
        or any(OP_BY_ID[r['op']]['svc'] in ('face_restore',) for r in comp['svc'])
    )
    if needs_gpu and lic['render_blocked']:
        return {'ok': False, 'error': lic['block_note']}
    if comp['gen_count'] and not cfx.comfy_up():
        return {
            'ok': False,
            'error': 'ComfyUI is not reachable, so the generative half of this stack '
            'cannot run. The deterministic ops alone still bake — switch the '
            'generative ops off to do that.',
        }
    mask_b64 = str(body.get('mask_b64') or '')
    repair_prompt = str(body.get('repair_prompt') or '')[:300]
    if mask_b64:
        # A masked repair is a generative pass whether or not any Style/Subject
        # op put a clause in the instruction, so it gets its own step rather
        # than riding on one that may not exist -- an empty instruction used to
        # mean no edit step at all, which silently threw the mask away and
        # re-saved the source as if it had worked.
        #
        # It is appended LAST on purpose. The mask was painted on the PREVIEW,
        # which is the source with every deterministic op already applied, so
        # the only position at which the mask lines up with what the operator
        # actually painted over is after all of them.
        comp['steps'] = [st for st in comp['steps'] if st['kind'] != 'edit'] + [{'kind': 'edit'}]
        comp['repair'] = True
        summary_override = 'repair'
    else:
        summary_override = ''
    seed = int(opts.get('seed') or 0) or (
        int(hashlib.sha256((comp['instruction'] + str(time.time())).encode()).hexdigest()[:8], 16) % 10**8
    )
    jid = uuid.uuid4().hex[:12]
    summary = summary_override or (
        comp['clauses'][0]['lb'].lower() if comp['clauses'] else OP_BY_ID[comp['rows'][0]['op']]['lb'].lower()
    )
    plan = {
        'id': jid,
        'lib': lib,
        'subject': cid,
        'name': _ctx(lib, cid).get('name'),
        'source': f'{cat}/{name}',
        'source_path': fp,
        'scope': scope,
        'seed': seed,
        'seeds': max(1, min(6, int(opts.get('best_of') or 1))),
        'steps': max(4, min(60, int(opts.get('steps') or 36))),
        'cfg': max(1.0, min(12.0, float(opts.get('cfg') or 4.0))),
        'size': max(256, min(2048, int(opts.get('size') or 1024))),
        'summary': summary,
        'gen_count': comp['gen_count'],
        'pix_count': comp['pix_count'],
        'svc_count': comp['svc_count'],
        'licence': lic,
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'started': time.time(),
        'state': 'queued',
        'log': [],
    }
    _set(jid, **plan)
    _prune_jobs()
    threading.Thread(
        target=_render_worker, args=(jid, comp, plan, mask_b64, repair_prompt), daemon=True, name=f'picfx-{jid}'
    ).start()
    return {
        'ok': True,
        'job': jid,
        'gen': comp['gen_count'],
        'svc': comp['svc_count'],
        'pix': comp['pix_count'],
        'seed': seed,
        'instruction': comp['instruction'],
    }


def _render_worker(jid, comp, plan, mask_b64='', repair_prompt=''):
    try:
        _set(jid, state='running', stage='reading source')
        src = _open(plan['source_path'])
        cur = src
        n = 0
        for st in comp['steps']:
            n += 1
            if st['kind'] == 'pix':
                o = OP_BY_ID[st['row']['op']]
                _set(jid, stage=f'{n}. {o["lb"]}')
                cur = o['pfn'](cur.convert('RGBA'), st['row']['p'])
            elif st['kind'] == 'svc':
                o = OP_BY_ID[st['row']['op']]
                _set(jid, stage=f'{n}. {o["lb"]}')
                cur = _run_service(jid, o, st['row']['p'], cur, plan, comp)
            else:
                _set(jid, stage=f'{n}. ' + ('masked repair' if mask_b64 else 'Qwen-Image-Edit'))
                cur = _run_edit(jid, cur, comp, plan, mask_b64, repair_prompt)
        _set(jid, stage='measuring')
        measured = _measure_pair(src, cur)
        meta = dict(plan)
        meta.pop('log', None)
        meta['measured'] = measured
        meta['job'] = jid
        meta['derived_from'] = {
            'lib': plan['lib'],
            'subject': plan['subject'],
            'source': plan['source'],
            'path': plan['source_path'],
            'sha256_source': _sha(plan['source_path']),
        }
        png, meta = _write_bake(plan['lib'], plan['subject'], cur, comp, meta)
        _log(jid, f'wrote {os.path.basename(png)}')
        _set(
            jid,
            state='done',
            stage='',
            file=os.path.basename(png),
            path=png,
            cat=BAKE_DIR,
            measured=measured,
            finished=time.time(),
        )
    except Exception as ex:  # noqa: BLE001
        _log(jid, f'FAILED {type(ex).__name__}: {ex}')
        _set(jid, state='error', error=f'{type(ex).__name__}: {ex}', finished=time.time())


def _sha(fp):
    h = hashlib.sha256()
    with open(fp, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _tmpdir(jid):
    d = os.path.join(JOBDIR, jid)
    os.makedirs(d, exist_ok=True)
    return d


def _run_service(jid, o, p, im, plan, comp):
    """Run one service op. Each one reports WHICH backend actually ran — a PIL
    fallback and an ESRGAN pass are not the same picture, and a log that does
    not say which one happened is a log that cannot be read back."""
    work = _tmpdir(jid)
    src = os.path.join(work, f'svc_in_{o["id"]}.png')
    dst = os.path.join(work, f'svc_out_{o["id"]}.png')
    im.convert('RGBA').save(src)
    if o['svc'] == 'upscale':
        scale = int(p.get('scale') or 2)
        try:
            from zyg_workflows import contact_sheet_pipeline as csp

            csp._upscale_sheet_comfy(src, dst, scale=scale, log_fn=lambda m: _log(jid, str(m)[:200]))
            _log(jid, f'upscale {scale}x: Comfy ESRGAN')
        except Exception as ex:  # noqa: BLE001
            _log(
                jid,
                f'upscale {scale}x: Comfy ESRGAN unavailable ({type(ex).__name__}: '
                f'{str(ex)[:110]}) — PIL LANCZOS fallback, which enlarges detail '
                'rather than adding any',
            )
            from zyg_workflows import contact_sheet_pipeline as csp

            csp._upscale_sheet_pil(src, dst, scale=scale, log_fn=lambda m: _log(jid, str(m)[:200]))
        return _open(dst)
    if o['svc'] == 'bg_remove':
        from zyg_workflows import bg_remove_service as bgr

        bgr.remove_background(src, dst, log_fn=lambda m: _log(jid, str(m)[:200]))
        _log(jid, 'background removed (u2net matte)')
        return _open(dst)
    if o['svc'] == 'face_restore':
        _log(jid, 'face restore: a generative pass over the whole frame asked only to restore facial detail')
        sub = dict(comp)
        sub['instruction'] = (
            'restore natural, sharp facial detail — skin texture, eyes, '
            'hair strands — without changing the identity, expression, '
            'framing or colour. ' + keep_sentence()
        )
        return _run_edit(jid, im, sub, dict(plan, seeds=1, strength=float(p.get('strength') or 0.45)), '')
    raise ValueError(f'unknown service: {o["svc"]}')


def _phash(im):
    return cfx._phash(im)


def _run_edit(jid, im, comp, plan, mask_b64='', repair_prompt=''):
    """The generative pass: N seeds through the same Qwen-Image-Edit graph the
    rest of this pipeline uses, and the winner picked on a MEASUREMENT.

    Best-of-N is not "keep the last one". A candidate that came back
    structurally IDENTICAL to its source is ranked last however clean it looks:
    an unchanged frame is what a failed edit returns, and it is exactly the null
    this metric needs ([[feedback_measure_before_claim]])."""
    if mask_b64:
        return _run_masked_repair(jid, im, comp, plan, mask_b64, repair_prompt)
    cfx._ensure_comfy_env()
    from zyg_workflows import comfy_generation_service as cgs

    work = _tmpdir(jid)
    ref = os.path.join(work, 'source.png')
    im.convert('RGB').save(ref)
    src_hash = _phash(im)
    cands = []
    for k in range(int(plan.get('seeds') or 1)):
        seed = plan['seed'] + k * 7919
        dest = os.path.join(work, f'cand_{k}.png')
        _set(jid, stage=f'render {k + 1}/{plan.get("seeds", 1)} (seed {seed})')
        _log(jid, f'seed {seed}: {comp["instruction"][:130]}…')
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
            character_package={'style_profile': {'render_style': 'photoreal'}, 'conditioning': {}},
            log_fn=lambda m: _log(jid, str(m)[:200]),
            extra_negative=comp['negative'],
            skip_qa=True,
            prompt_finalized=True,
            human_subject=(plan.get('lib') == 'char'),
            clear_vram_after=False,
        )
        if not ok or not os.path.isfile(dest):
            _log(jid, f'seed {seed}: render failed ({backend})')
            continue
        cim = _open(dest)
        moved = cfx._hamm(src_hash, _phash(cim))
        cands.append({'seed': seed, 'path': dest, 'change_bits': moved})
        _log(jid, f'seed {seed}: change={moved}/64 bits')
    if not cands:
        raise RuntimeError('every seed failed to render — see the job log')
    cands.sort(key=lambda r: r['change_bits'], reverse=True)
    best = cands[0]
    if best['change_bits'] == 0:
        _log(
            jid,
            'WARNING: every candidate came back structurally identical to its '
            'source. The edit did not take — treat this bake as a null result.',
        )
    _log(jid, f'picked seed {best["seed"]} of {len(cands)}')
    out = _open(best['path'])
    bars = cfx._strip_bars(out)
    if bars:
        _log(jid, f'letterbox bars stripped ({bars}px)')
        out = cfx._px_trim(out, {'tol': 10})
    _set(
        jid, seed_used=best['seed'], candidates=[{'seed': c_['seed'], 'change_bits': c_['change_bits']} for c_ in cands]
    )
    return out


def _run_masked_repair(jid, im, comp, plan, mask_b64, repair_prompt=''):
    """A repair confined to a painted region. The mask is resized to the
    image's NATIVE resolution before it is sent, because a mask that does not
    line up repaints the wrong part of the picture and looks like a bad model."""
    import base64
    import cv2
    import numpy as np
    from zyg_workflows import flux_fill_service as ffs

    work = _tmpdir(jid)
    src = os.path.join(work, 'repair_in.png')
    im.convert('RGB').save(src)
    raw = base64.b64decode(mask_b64)
    mask = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise RuntimeError('could not decode the painted mask')
    if mask.shape[1] != im.width or mask.shape[0] != im.height:
        mask = cv2.resize(mask, (im.width, im.height), interpolation=cv2.INTER_NEAREST)
    if mask.max() == 0:
        raise RuntimeError('the mask is empty — paint over the area to repair first')
    prompt = (
        repair_prompt
        or comp['instruction']
        or 'restore this region with correct anatomy and natural photographic detail, matching the surrounding image'
    )
    _log(jid, f'masked repair over {int((mask > 0).sum())} px')
    out_path, tier = ffs._repair_via_qwen_comfyui(src, mask, prompt, lambda m: _log(jid, str(m)[:200]))
    if not out_path or not os.path.isfile(out_path):
        raise RuntimeError(f'the masked repair failed on the {tier} tier — see the job log')
    _log(jid, f'repaired on the {tier} tier')
    return _open(out_path)


def _measure_pair(src, out):
    """How far the bake moved from its own source, and how big it came back.

    Structural distance only: there is no per-character identity anchor in this
    library the way creature_fx has one, and reporting a number without saying
    what it is measured against would be worse than reporting none
    ([[feedback_measure_before_claim]])."""
    return {
        'change_bits_total': cfx._hamm(_phash(src), _phash(out)),
        'change_of': 64,
        'size_source': f'{src.width}x{src.height}',
        'size': f'{out.width}x{out.height}',
        'note': 'structural pHash distance from the source. There is no identity '
        'anchor for a Picture Studio subject, so this says how much moved '
        'and NOT whether it is still the same person.',
    }


# ── presets ─────────────────────────────────────────────────────────────────
# A preset is a STACK, not a picture: it carries no subject, no source and no
# library with it, which is what makes it droppable onto anything.

_PRESET_LOCK = threading.Lock()


def load_presets():
    try:
        with open(PRESETS, encoding='utf-8') as fh:
            return json.load(fh) or []
    except (OSError, ValueError):
        return []


def save_preset(name, stack, note=''):
    name = str(name or '').strip()[:60]
    if not name:
        return {'ok': False, 'error': 'a preset needs a name'}
    rows, dropped = normalise_stack(stack)
    if not rows:
        return {'ok': False, 'error': 'nothing in the stack to save'}
    rec = {
        'id': uuid.uuid4().hex[:10],
        'name': name,
        'note': str(note or '')[:200],
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'stack': [{'op': r['op'], 'on': r['on'], 'p': r['p']} for r in rows],
    }
    with _PRESET_LOCK:
        rows_all = load_presets()
        rows_all = [r for r in rows_all if r.get('name') != name]
        rows_all.insert(0, rec)
        os.makedirs(os.path.dirname(PRESETS), exist_ok=True)
        with open(PRESETS, 'w', encoding='utf-8') as fh:
            json.dump(rows_all[:200], fh, indent=2)
    return {'ok': True, 'preset': rec, 'dropped': dropped}


def delete_preset(pid):
    with _PRESET_LOCK:
        rows = [r for r in load_presets() if r.get('id') != pid]
        with open(PRESETS, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, indent=2)
    return {'ok': True, 'presets': rows}


# ── writes the dock can ask for ─────────────────────────────────────────────


def apply_action(body):
    act = str(body.get('act') or '')
    lib = str(body.get('lib') or '')
    cid = str(body.get('id') or '')
    scope = str(body.get('scope') or '')
    if act == 'delete_bake':
        return delete_bake(lib, cid, str(body.get('name') or ''), scope)
    if act == 'recipe':
        return {'ok': True, 'recipe': read_recipe(lib, cid, str(body.get('name') or ''), scope)}
    return {'ok': False, 'error': f'unknown action: {act}'}


# ── what the page draws all three bars from ─────────────────────────────────


def ops_payload():
    """The single source of truth for what exists, what it is called, what it
    does, what it looks like and what knobs it has.

    The page holds no tool list: add an op above and it appears in its bar with
    its icon and its panel without a line of the page changing."""
    secs, order = {}, []
    for o in OPS:
        key = (o['bar'], o['sec'])
        if key not in secs:
            secs[key] = []
            order.append(key)
        secs[key].append({k: v for k, v in o.items() if k not in ('fn', 'pfn')})
    return {
        'ok': True,
        'sections': [{'bar': bar, 'sec': sec, 'items': secs[(bar, sec)]} for bar, sec in order],
        'presets': load_presets(),
        'comfy': cfx.comfy_up(),
        'libs': list(LIBS),
        'counts': {
            'side': sum(1 for o in OPS if o['bar'] == 'side'),
            'dock': sum(1 for o in OPS if o['bar'] == 'dock'),
            'generative': sum(1 for o in OPS if o['cls'] == 'edit'),
            'service': sum(1 for o in OPS if o['cls'] == 'svc'),
            'deterministic': sum(1 for o in OPS if o['cls'] == 'pix'),
            'total': len(OPS),
        },
    }
