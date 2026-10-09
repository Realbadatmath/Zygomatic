# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""view_rank.py — does a registered asset's own depth pass actually steer the render?

    python3 prop_mesh/view_rank.py --asset kenney_workbench --view top_down \
        [--ref front_full] [--seed 7] [--steps 24] [--size 1024]

THE QUESTION, AND WHY IT NEEDS A NULL.
"The depth map conditioned the render" is the easiest claim in this repo to make and
the easiest to fake: hand a model a top-down depth map and a front-view photograph of
the same object and it will produce a plausible picture of that object, which looks
like success in every log. The measurement that separates conditioning from decoration
is a RANK: render once, then score the result by DINOv2 against all 16 of the asset's
own beauty views and ask where the TRUE view — the one the depth map came from — lands.
Chance is 8.5 of 16. A rank of 1-3 is control; a rank near 8.5 is a picture of the
object with the geometry ignored.

THE ARMS.
  ctrl  klein_refcontrol: depth as reference image 1, the FRONT beauty view as
        reference image 2, the RefControl adapter loaded with its trigger word.
  null  the same prompt and the same front reference with NO control image and NO
        adapter (klein_edit_angle). This is the honest null: it is not "nothing", it
        is everything except the geometry, so the difference between the two ranks is
        attributable to the depth map and to nothing else.

THE REFERENCE IS DELIBERATELY THE WRONG VIEW. Using `top_down`'s own beauty render as
the appearance reference would leak the answer — the adapter could be inert and the
render would still match top_down best, because it would be a copy of it. Pointing the
appearance at `front_full` puts the two conditioning signals in OPPOSITION: the
reference argues for the front, the depth argues for the top. Whichever wins is
readable off the rank table, and both ranks are reported for that reason.

WHAT THIS DOES NOT MEASURE. n=1 render per arm per asset (the brief's budget). This is
a directional receipt, not a calibration: it can distinguish rank 2 from rank 9, and it
cannot distinguish rank 2 from rank 3. The per-view cosine table is written out so a
later run can pool seeds instead of re-rendering these.
"""

import argparse
import json
import os
import sys
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

OUTROOT = os.path.join(_ROOT, 'output', 'view_rank')


def rank_table(image, beauty):
    """[(view_id, cosine)] newest-best-first, by DINOv2 CLS cosine.

    creature_identity is the repo's DINOv2 surface and is structure-sensitive by
    construction — which is what this needs, because the question is about VIEWPOINT,
    not about colour. A CLIP score would happily call every view of the workbench the
    same workbench."""
    from zyg_workflows import creature_identity as cid

    emb = cid.embed(image)
    if emb is None:
        raise SystemExit('DINOv2 unavailable: %s' % cid.unavailable_reason())
    rows = []
    for vid, path in beauty:
        e = cid.embed(path)
        rows.append((vid, cid.similarity_emb(emb, e)))
    rows.sort(key=lambda r: (r[1] is not None, r[1]), reverse=True)
    return rows


def _rank_of(rows, vid):
    for i, (v, _s) in enumerate(rows):
        if v == vid:
            return i + 1
    return None


def ensure_comfy_env():
    """Route stills through ComfyUI from THIS process.

    `comfy_generation_service.is_available()` is False unless ZYG_COMFY_PRIMARY (or the
    legacy ZYG_USE_COMFYUI) is set in the environment, and nothing sets it for a plain
    CLI: the .env that exports it belongs to the pipeline. Measured 2026-09-03 — the
    first run of this script returned `FAILED (unavailable)` for both arms while ComfyUI
    was answering on :8188 and `has_klein_refcontrol()` was True, because that guard
    only asks whether the server is REACHABLE. Every other in-process caller of the
    render backend does exactly this first (creature_fx._ensure_comfy_env,
    creature_training_service, video_studio, kids_video_service)."""
    try:
        from zyg_workflows import _comfy_client as _cc
    except ImportError:
        return False
    try:
        if _cc.server_reachable():
            # BOTH, and they are not synonyms: is_available() requires
            # is_primary_backend() (either flag) AND _comfy.is_enabled(), which reads
            # ZYG_USE_COMFYUI specifically. Setting only the modern one leaves
            # is_available() False with no error anywhere.
            os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
            os.environ.setdefault('ZYG_USE_COMFYUI', '1')
            return True
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('comfy reachability probe failed, treating comfy as unavailable: %s', _exc)
    return False


def run(asset, view, ref_view, *, seed=7, steps=24, size=1024, prompt=None, log=print):
    ensure_comfy_env()
    from zyg_workflows import prop_mesh_library as PML
    from zyg_workflows import mesh_control as MC
    from zyg_workflows import comfy_generation_service as cgs

    rec = PML.get(asset)
    if not rec:
        raise SystemExit('not registered: %s' % asset)
    ids = PML.view_ids(asset)
    if view not in ids:
        raise SystemExit('%s has no view %r (has %s)' % (asset, view, ','.join(ids)))
    beauty = [(v, PML.beauty_path(asset, v)) for v in ids]
    missing = [v for v, p in beauty if not p]
    if missing:
        raise SystemExit('missing beauty renders for %s' % ','.join(missing))

    MC.ensure(asset, kinds=('depth', 'matte'))
    depth = os.path.join(MC.control_dir(asset), '%s_depth.png' % view)
    if not os.path.isfile(depth):
        raise SystemExit('no control depth for %s/%s — run mesh_control.build' % (asset, view))
    ref = PML.beauty_path(asset, ref_view)

    work = os.path.join(OUTROOT, asset)
    os.makedirs(work, exist_ok=True)
    name = rec.get('name') or asset
    prompt = prompt or (
        'a %s, single object, plain neutral studio background, '
        'even soft lighting, sharp focus, product photograph' % name
    )

    if not cgs.is_available():
        raise SystemExit(
            'the render backend is not available (is_available() False; '
            'enabled=%s reachable=%s) — nothing would render' % (cgs._comfy.is_enabled(), cgs._comfy.server_reachable())
        )
    if not cgs.has_klein_refcontrol():
        raise SystemExit('klein RefControl is not installed — nothing to measure')

    out = {
        'asset': asset,
        'true_view': view,
        'ref_view': ref_view,
        'seed': seed,
        'steps': steps,
        'size': size,
        'prompt': prompt,
        'depth': depth,
        'reference': ref,
        'n_views': len(ids),
        'chance_rank': round((len(ids) + 1) / 2.0, 1),
        'control_lora': cgs.klein_control_lora_name(),
        'control_lora_scale': cgs.klein_control_lora_scale(),
        'arms': {},
    }

    arms = (
        # (label, workflow, pose_image) — the null is everything EXCEPT the geometry.
        ('ctrl', 'klein_refcontrol', depth),
        ('null_adapter_off', 'klein_edit_angle', None),
    )
    for label, wf, pose in arms:
        dest = os.path.join(work, '%s_%s_%s.png' % (view, label, seed))
        t0 = time.time()
        ok, backend = cgs.generate_still(
            dest,
            prompt,
            width=size,
            height=size,
            steps=steps,
            cfg=3.5,
            seed=seed,
            model_family='klein',
            force_workflow=wf,
            reference_image=ref,
            pose_image=pose,
            character_package={'style_profile': {'render_style': 'photoreal'}, 'conditioning': {}},
            log_fn=lambda m: log('    ' + str(m)[:170]),
            skip_qa=True,
            prompt_finalized=True,
            human_subject=False,
            solo_subject=True,
            clear_vram_after=False,
        )
        dt = time.time() - t0
        if not ok or not os.path.isfile(dest):
            out['arms'][label] = {'ok': False, 'backend': backend, 'seconds': round(dt, 1)}
            log('  %-18s FAILED (%s)' % (label, backend))
            continue
        rows = rank_table(dest, beauty)
        r_true, r_ref = _rank_of(rows, view), _rank_of(rows, ref_view)
        out['arms'][label] = {
            'ok': True,
            'workflow': wf,
            'image': dest,
            'seconds': round(dt, 1),
            'rank_true_view': r_true,
            'rank_ref_view': r_ref,
            'top1': rows[0][0],
            'top1_cos': rows[0][1],
            'cos_true_view': dict(rows).get(view),
            'table': [{'view': v, 'cos': s} for v, s in rows],
        }
        log(
            '  %-18s rank(%s)=%s  rank(%s)=%s  top1=%s (%.4f)  %.0fs'
            % (label, view, r_true, ref_view, r_ref, rows[0][0], rows[0][1] or 0, dt)
        )

    c = out['arms'].get('ctrl', {})
    n = out['arms'].get('null_adapter_off', {})
    if c.get('ok') and n.get('ok'):
        out['delta_rank'] = n['rank_true_view'] - c['rank_true_view']
        out['verdict'] = (
            'depth steers: %s -> %s of %d (chance %s)'
            % (n['rank_true_view'], c['rank_true_view'], len(ids), out['chance_rank'])
            if c['rank_true_view'] < n['rank_true_view']
            else 'NO measured steer: ctrl rank %s is not better than the '
            'adapter-off null %s' % (c['rank_true_view'], n['rank_true_view'])
        )
    p = os.path.join(work, 'view_rank_%s_%s.json' % (view, seed))
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)
        fh.write('\n')
    log('[view-rank] %s' % p)
    return out


def _main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--asset', required=True)
    ap.add_argument('--view', default='top_down')
    ap.add_argument('--ref', dest='ref_view', default='front_full')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--steps', type=int, default=24)
    ap.add_argument('--size', type=int, default=1024)
    ap.add_argument('--prompt', default=None)
    a = ap.parse_args()
    r = run(a.asset, a.view, a.ref_view, seed=a.seed, steps=a.steps, size=a.size, prompt=a.prompt)
    print(json.dumps({k: v for k, v in r.items() if k != 'arms'}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(_main())
