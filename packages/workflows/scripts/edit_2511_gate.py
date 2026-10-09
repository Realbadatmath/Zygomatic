#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Edit-2511 cutover gate — does Edit-2511 retire the 2509 angles LoRA?

Renders the same fixed-seed angle plan (a yaw sweep + pitch labels from the
extended-48 contact-sheet lists) under three conditions and scores every
output against the character's identity anchor:

  A baseline  : 2509 UNet + stock 2509 angles LoRA (current defaults)
  B bare-2511 : ZYG_QWEN_EDIT_UNET=qwen_image_edit_2511_fp8mixed.safetensors
                + ZYG_QWEN_EDIT_ANGLES_LORA_SCALE=0
  C 2511+fal  : 2511 UNet + ZYG_QWEN_EDIT_ANGLES_LORA=
                qwen_edit_2511/qwen-image-edit-2511-multiple-angles-lora.safetensors

Each condition runs in a CLEAN CHILD PROCESS (this script re-invokes itself
with --_run-condition) so env vars and module-level caches cannot leak
between conditions. The render call replicates the contact-sheet rotation
cell (qwen_edit_angle, edit of the anchor CELL) faithfully, with a fixed
per-angle seed table so conditions are comparable.

Invocation (agents venv, from the crews dir):

    cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}" && \
        ZYG_USE_COMFYUI=1 \
        ../.venv/bin/python scripts/edit_2511_gate.py --char <char_id> [--dry-run]

NOTE: generate_still gates qwen_edit_angle renders behind the FLUX licence
pause because the pipeline plumbs them as model_family='flux' — a real run
additionally needs ZYG_FLUX_RENDERS=allowed (operator decision), which this
script checks for and reports but never sets itself.

Exit codes: 0 = verdict written (or --dry-run OK), 1 = no condition produced
scores, 2 = precondition failure (char/anchor invalid, ComfyUI down, flux
paused, missing model files for every requested condition).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

os.environ.setdefault('ZYG_USE_COMFYUI', '1')

_CREWS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS_DIR not in sys.path:
    sys.path.insert(0, _CREWS_DIR)

_DEFAULT_OUT_ROOT = os.environ.get('ZYG_EDIT2511_OUT_ROOT') or str(paths.ZYG_TMP_DIR / 'edit_2511_gate')
# Fixed seed table: seed_i = (_BASE_SEED + i*9973) % 2**31 — identical across
# conditions (9973 is the contact-sheet per-cell seed stride).
_BASE_SEED = int(os.environ.get('ZYG_EDIT2511_SEED', '424242'))
_COMFY_ROOT = str(paths.ZYG_COMFY_ROOT)

_UNET_2511 = 'qwen_image_edit_2511_fp8mixed.safetensors'
_LORA_2511 = 'qwen_edit_2511/qwen-image-edit-2511-multiple-angles-lora.safetensors'

# env_set is applied on top of the parent env; env_pop keys are removed so a
# stale operator export can't bleed into a condition.
_CONDITIONS: dict[str, dict] = {
    'A': {
        'label': 'baseline_2509',
        'env_set': {},
        'env_pop': ['ZYG_QWEN_EDIT_UNET', 'ZYG_QWEN_EDIT_ANGLES_LORA', 'ZYG_QWEN_EDIT_ANGLES_LORA_SCALE'],
        'files': [],
    },
    'B': {
        'label': 'bare_2511',
        'env_set': {'ZYG_QWEN_EDIT_UNET': _UNET_2511, 'ZYG_QWEN_EDIT_ANGLES_LORA_SCALE': '0'},
        'env_pop': ['ZYG_QWEN_EDIT_ANGLES_LORA'],
        'files': [os.path.join(_COMFY_ROOT, 'models', 'diffusion_models', _UNET_2511)],
    },
    'C': {
        'label': '2511_fal_angles',
        'env_set': {'ZYG_QWEN_EDIT_UNET': _UNET_2511, 'ZYG_QWEN_EDIT_ANGLES_LORA': _LORA_2511},
        'env_pop': ['ZYG_QWEN_EDIT_ANGLES_LORA_SCALE'],
        'files': [
            os.path.join(_COMFY_ROOT, 'models', 'diffusion_models', _UNET_2511),
            os.path.join(_COMFY_ROOT, 'models', 'loras', _LORA_2511),
        ],
    },
}

# Angle plan as (sheet_part, index) refs into SHEET_ANGLES_BY_PART so labels
# can never drift from the pipeline's own extended-48 lists. Default 12 =
# yaw sweep 20/35/60 (face-visible) + 90/120 (steep) + high/low pitch fronts;
# --angles beyond 12 adds pitch three-quarters and the slight-pitch fronts.
_PLAN_REFS: list[tuple[str, int]] = [
    ('g', 0),
    ('g', 1),  # 20 deg left / right (near-frontal)
    ('a', 1),
    ('a', 2),  # 35 deg left / right (three-quarter)
    ('g', 2),
    ('g', 3),  # 60 deg left / right (strong three-quarter)
    ('a', 3),
    ('a', 4),  # 90 deg left / right (true profile — steep)
    ('g', 4),
    ('g', 5),  # 120 deg left / right (back three-quarter — steep)
    ('f', 0),
    ('f', 3),  # high-angle 30 front / low-angle 20 front (pitch)
    ('f', 1),
    ('f', 5),  # high-angle 3/4 left / low-angle 3/4 right
    ('b', 0),
    ('b', 1),  # slightly above / slightly below front
]


def _log(msg: str) -> None:
    print(f'[edit2511-gate] {msg}', flush=True)


def _comfy_url() -> str:
    host = os.environ.get('ZYG_COMFY_HOST', '127.0.0.1')
    port = os.environ.get('ZYG_COMFY_PORT', '8188')
    return f'http://{host}:{port}'


def _comfy_up() -> tuple[bool, str]:
    try:
        import requests

        r = requests.get(f'{_comfy_url()}/system_stats', timeout=5)
        r.raise_for_status()
        return True, f'HTTP {r.status_code}'
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'


def _flux_paused() -> bool | None:
    try:
        from zyg_workflows import licence_provenance as _lp

        return bool(_lp.flux_paused())
    except Exception:
        return None


def _seed_for(i: int) -> int:
    return (_BASE_SEED + i * 9973) % (2**31)


def _build_plan(n_angles: int) -> list[dict]:
    from zyg_workflows import contact_sheet_pipeline as _csp

    refs = _PLAN_REFS[: max(1, min(n_angles, len(_PLAN_REFS)))]
    if n_angles > len(_PLAN_REFS):
        _log(f'--angles {n_angles} capped to {len(_PLAN_REFS)} (plan size)')
    plan = []
    for i, (part, idx) in enumerate(refs):
        label = _csp.SHEET_ANGLES_BY_PART[part][idx]
        plan.append({'index': i, 'part': part, 'part_index': idx, 'angle': label, 'seed': _seed_for(i)})
    return plan


def _load_char_params(char_id: str) -> dict:
    """Rebuild the pipeline's params dict from the character's own records:
    top-level manifest (style/identity basics) + bible (heritage, marks,
    default_clothing) — the fields _qwen_angle_instruction and the cell
    negative builder actually consume."""
    from zyg_workflows import contact_sheet_pipeline as _csp

    root = os.path.join(_csp._DATASET_ROOT, char_id)
    params: dict = {}
    try:
        with open(os.path.join(root, 'manifest.json'), encoding='utf-8') as fh:
            top = json.load(fh)
        for k in ('name', 'gender', 'hair_color', 'eye_color', 'skin_tone', 'style', 'trigger_token'):
            if top.get(k):
                params[k] = top[k]
    except Exception as exc:
        _log(f'top-level manifest unavailable ({exc!r}) — params from bible only')
    try:
        with open(os.path.join(root, 'character_bible.json'), encoding='utf-8') as fh:
            bible = json.load(fh)
        ident = bible.get('identity') or {}
        for k in ('age', 'ethnic_heritage', 'distinctive_marks', 'skin_tone', 'hair_color', 'eye_color', 'gender'):
            if ident.get(k) is not None and k not in params:
                params[k] = ident[k]
        style_p = bible.get('style_profile') or {}
        if style_p.get('render_style'):
            params.setdefault('render_style', style_p['render_style'])
        pres = bible.get('default_presentation') or {}
        clothing = style_p.get('default_clothing') or pres.get('default_clothing')
        if clothing:
            params['default_clothing'] = clothing
    except Exception as exc:
        _log(f'character bible unavailable ({exc!r})')
    params.setdefault('style', params.get('render_style', 'photorealistic'))
    return params


def _anchor_paths(char_id: str) -> dict:
    """Anchor discovery exactly as run_identity_qc does it: manifest override
    first, then the canonical contact_sheet path."""
    from zyg_workflows import contact_sheet_pipeline as _csp

    manifest = _csp.load_manifest(char_id) or {}
    face = manifest.get('identity_anchor_face') or _csp.identity_anchor_face_path(char_id)
    cdir = os.path.join(_csp.contact_sheet_dir(char_id), 'cells')
    return {
        'anchor_face': face,
        'profile_anchor_face': _csp.identity_profile_anchor_face_path(char_id),
        'anchor_cell': os.path.join(cdir, 'cell_00.png'),
        'anchor_cell_body': os.path.join(cdir, 'cell_00_body.png'),
    }


def _build_cell_neg(params: dict) -> str:
    """Replicates the per-cell negative from the sheet loop (freckle
    governance + symmetric skin/hair/age defence)."""
    cell_neg = (
        'blurry, low quality, multiple people, two people, collage, grid of panels, '
        'split image, duplicate faces, inconsistent identity, deformed body, '
        'text, watermark, 3d render, cartoon, doll, illustration, anime, cgi, '
        'manhwa, webtoon, korean webtoon, digital painting, concept art, '
        'stylized, cel shading, render, game character, vector art, '
        'airbrushed skin, smooth plastic skin, waxy skin, porcelain doll skin, '
        'poreless skin, silky smooth skin, overly smooth skin, retouched skin, '
        'oversized anime eyes, big eyes, beauty-filter face, '
        'shorts, mini skirt, changed outfit, different clothes, '
        'lingerie, underwear, bare midriff'
    )
    if 'freckle' not in str((params or {}).get('distinctive_marks') or '').lower():
        cell_neg += (
            ', heavy freckles, dense freckle field, freckled face, mottled skin, smeared freckles, scar-like blotches'
        )
    try:
        from zyg_workflows import character_bible_service as _cbs

        _skin = _cbs.skin_tone_negatives(
            (params or {}).get('skin_tone', ''),
            (params or {}).get('ethnic_heritage'),
        )
        if _skin:
            cell_neg += ', ' + _skin
        _hair = _cbs.hair_color_negatives(
            (params or {}).get('hair_color', ''),
            (params or {}).get('ethnic_heritage'),
        )
        if _hair:
            cell_neg += ', ' + _hair
        _age = _cbs.age_negatives((params or {}).get('age'))
        if _age:
            cell_neg += ', ' + _age
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return cell_neg


def _run_condition(args) -> int:
    """Child-process body: renders + scores ONE condition with the env the
    parent staged. Never spawns further processes."""
    cond = args._run_condition
    spec = _CONDITIONS[cond]
    out_dir = os.path.join(args.out, cond)
    os.makedirs(out_dir, exist_ok=True)

    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import contact_sheet_pipeline as _csp

    effective = {
        'ZYG_QWEN_EDIT_UNET': os.environ.get('ZYG_QWEN_EDIT_UNET', ''),
        'ZYG_QWEN_EDIT_ANGLES_LORA': os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA', ''),
        'ZYG_QWEN_EDIT_ANGLES_LORA_SCALE': os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE', '0.9 (default)'),
        'resolved_unet': None,
        'resolved_angles_lora': None,
        'has_qwen_edit_angles': None,
    }
    try:
        effective['resolved_unet'] = _cgs.qwen_edit_unet()
        effective['resolved_angles_lora'] = _cgs.qwen_edit_angles_lora_name()
        effective['has_qwen_edit_angles'] = bool(_cgs.has_qwen_edit_angles())
    except Exception as exc:
        effective['probe_error'] = f'{type(exc).__name__}: {exc}'
    _log(f'condition {cond} ({spec["label"]}) effective: {json.dumps(effective)}')

    params = _load_char_params(args.char)
    anchors = _anchor_paths(args.char)
    plan = _build_plan(args.angles)

    # Character package + conditioning — mirrors the per-cell sheet loop.
    pkg = _csp._build_sheet_character_package(args.char, params, 'flux', log_fn=_log)
    gen_pkg = copy.deepcopy(pkg) if pkg else {}
    cond_d = gen_pkg.setdefault('conditioning', {})
    cond_d['hand_detail_pass'] = False
    cond_d['instantid_enabled'] = False
    if (params or {}).get('style', 'photorealistic').lower() in ('photorealistic', 'photoreal', 'photo'):
        cond_d['skin_pore_pass'] = True

    cell_neg = _build_cell_neg(params)
    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '28'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5'))

    results: list[dict] = []
    for entry in plan:
        angle = entry['angle']
        rec = dict(entry)
        instruction = _csp._qwen_angle_instruction(angle, params)
        if not instruction:
            rec['skipped'] = 'no qwen instruction for label (PuLID territory)'
            results.append(rec)
            _log(f'angle {entry["index"]:02d} skipped — no instruction')
            continue
        rec['instruction'] = instruction
        cell_w, cell_h = _csp._cell_size_for_angle(angle)
        ref = (
            anchors['anchor_cell_body']
            if (_csp._is_full_body_angle(angle) and os.path.isfile(anchors['anchor_cell_body']))
            else anchors['anchor_cell']
        )
        rec['reference_image'] = ref
        out_png = os.path.join(out_dir, f'angle_{entry["index"]:02d}.png')
        rec['path'] = out_png
        # Faithful replica of the sheet loop's rotation-cell generate_still
        # call (contact_sheet_pipeline ~2552-2598) — including flux_guidance
        # and cfg_start_frac, which the qwen_edit_angle graph patch owns.
        gen_kwargs: dict = {
            'width': cell_w,
            'height': cell_h,
            'steps': steps,
            'cfg': cfg,
            'seed': entry['seed'],
            'character_package': gen_pkg,
            'char_id': args.char,
            'model_family': 'flux',
            'log_fn': _log,
            'skip_qa': True,
            'studio_preview': True,
            'prompt_finalized': True,
            'flux_guidance': cfg,
            'extra_negative': cell_neg,
            'cfg_start_frac': float(os.environ.get('ZYG_FLUX_CFG_START_FRAC', '0.18')),
            'reference_image': ref,
            'force_workflow': 'qwen_edit_angle',
        }
        _csp._strip_detailer_for_steep(gen_kwargs, angle)
        t0 = time.time()
        try:
            ok, backend = _cgs.generate_still(out_png, instruction, **gen_kwargs)
        except Exception as exc:
            ok, backend = False, f'exception:{type(exc).__name__}: {exc}'
        rec['ok'] = bool(ok and os.path.isfile(out_png))
        rec['backend'] = backend
        rec['seconds'] = round(time.time() - t0, 1)
        _log(
            f'angle {entry["index"]:02d} [{angle[:60]}] -> '
            f'{"OK" if rec["ok"] else "FAILED"} ({backend}, {rec["seconds"]}s)'
        )
        results.append(rec)

    rendered = [r for r in results if r.get('ok')]
    idqc_report: dict = {}
    if rendered:
        try:
            from zyg_workflows import identity_qc_service as _idqc

            items = [{'path': r['path'], 'angle': r['angle']} for r in rendered]
            idqc_report = _idqc.score_images_against_anchor(
                anchors['anchor_face'],
                items,
                profile_anchor_path=anchors['profile_anchor_face'],
                log_fn=_log,
            )
        except Exception as exc:
            idqc_report = {'ok': False, 'reason': f'{type(exc).__name__}: {exc}'}
        for r in rendered:
            e = (idqc_report.get('results') or {}).get(r['path']) or {}
            r['identity_score'] = e.get('score')
            r['identity_verdict'] = e.get('verdict')
            r['identity_visibility'] = e.get('visibility')
            r['face_yaw'] = e.get('yaw')

    if args.vlm and rendered:
        # Optional mislabel/ghost screen; cloud tier stays off unless the
        # operator opts in (paid calls).
        try:
            from zyg_workflows import cell_vlm_judge as _cvj

            if _cvj.enabled():
                _cloud_ok = os.environ.get('ZYG_EDIT2511_VLM_CLOUD', '0').strip().lower() in ('1', 'true', 'yes')
                for r in rendered:
                    r['vlm'] = _cvj.judge_cell(
                        r['path'],
                        anchor_path=anchors['anchor_face'],
                        angle=r['angle'],
                        log_fn=_log,
                        allow_cloud=_cloud_ok,
                    )
            else:
                _log('cell_vlm_judge disabled — skipping VLM check')
        except Exception as exc:
            _log(f'VLM judge unavailable ({exc!r})')

    scoreable = [r for r in rendered if r.get('identity_verdict') not in (None, 'no_face_expected')]
    scores = [r['identity_score'] for r in scoreable if isinstance(r.get('identity_score'), (int, float))]
    passes = [r for r in scoreable if r.get('identity_verdict') == 'pass']
    fail_list = [
        {'angle': r['angle'], 'verdict': r.get('identity_verdict'), 'score': r.get('identity_score')}
        for r in scoreable
        if r.get('identity_verdict') != 'pass'
    ]
    fail_list += [
        {'angle': r['angle'], 'verdict': 'render_failed', 'score': None}
        for r in results
        if not r.get('ok') and not r.get('skipped')
    ]
    summary = {
        'condition': cond,
        'label': spec['label'],
        'effective': effective,
        'planned': len(plan),
        'rendered': len(rendered),
        'scoreable': len(scoreable),
        'mean_sim': round(sum(scores) / len(scores), 4) if scores else None,
        'pass_rate': round(len(passes) / len(scoreable), 4) if scoreable else 0.0,
        'angle_fail_list': fail_list,
        'idqc_summary': idqc_report.get('summary') or {},
        'idqc_ok': idqc_report.get('ok'),
        'idqc_reason': idqc_report.get('reason'),
    }
    report = {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'char_id': args.char,
        'summary': summary,
        'angles': results,
    }
    rpt = os.path.join(out_dir, 'condition_report.json')
    with open(rpt, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2)
    _log(
        f'condition {cond} report: {rpt} — mean_sim={summary["mean_sim"]} '
        f'pass_rate={summary["pass_rate"]} fails={len(fail_list)}'
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--char', required=True, help='character id (dataset root subdir)')
    ap.add_argument('--conditions', default='A,B,C', help='comma list from A,B,C (default all)')
    ap.add_argument('--angles', type=int, default=12, help=f'angle count from the fixed plan (max {len(_PLAN_REFS)})')
    ap.add_argument('--out', default='', help='output dir (default <scratch>/edit_2511_gate/<char>)')
    ap.add_argument('--vlm', action='store_true', help='also run cell_vlm_judge on each rendered cell')
    ap.add_argument('--dry-run', action='store_true', help='validate char/anchors, print plan + env deltas, no GPU')
    ap.add_argument(
        '--_run-condition', dest='_run_condition', default='', help=argparse.SUPPRESS
    )  # internal: child-process mode
    args = ap.parse_args()
    args.out = args.out or os.path.join(_DEFAULT_OUT_ROOT, args.char)

    conds = [c.strip().upper() for c in args.conditions.split(',') if c.strip()]
    bad = [c for c in conds if c not in _CONDITIONS]
    if bad or not conds:
        _log(f'invalid --conditions {args.conditions!r} (valid: A,B,C)')
        return 2

    if args._run_condition:
        if args._run_condition not in _CONDITIONS:
            _log(f'invalid --_run-condition {args._run_condition!r}')
            return 2
        return _run_condition(args)

    # ── char + anchor validation (how run_identity_qc finds the anchor) ──
    anchors = _anchor_paths(args.char)
    anchor_ok = os.path.isfile(anchors['anchor_face'])
    cell_ok = os.path.isfile(anchors['anchor_cell'])
    _log(f'char {args.char}: anchor_face {"OK" if anchor_ok else "MISSING"} ({anchors["anchor_face"]})')
    _log(f'char {args.char}: anchor_cell {"OK" if cell_ok else "MISSING"} ({anchors["anchor_cell"]})')
    if not anchor_ok or not cell_ok:
        _log(
            'PRECONDITION FAILED: identity anchor face and anchor cell are both '
            'required (contact sheet must have run for this character)'
        )
        return 2

    params = _load_char_params(args.char)
    plan = _build_plan(args.angles)
    _log(
        f'params: style={params.get("style")!r} skin={params.get("skin_tone")!r} '
        f'clothing={"yes" if params.get("default_clothing") else "no"}'
    )

    comfy_ok, comfy_why = _comfy_up()
    paused = _flux_paused()
    _log(f'ComfyUI {_comfy_url()}: {"UP" if comfy_ok else "DOWN — " + comfy_why}')
    _log(
        f'flux licence pause: {paused} '
        f'(qwen_edit_angle is plumbed as model_family=flux, so a real run '
        f'needs ZYG_FLUX_RENDERS=allowed)'
    )

    cond_status: dict[str, str] = {}
    for c in conds:
        spec = _CONDITIONS[c]
        missing = [f for f in spec['files'] if not os.path.isfile(f)]
        cond_status[c] = ('missing: ' + '; '.join(missing)) if missing else 'ready'
        _log(f'condition {c} ({spec["label"]}): {cond_status[c]}')
        _log(f'  env set: {spec["env_set"] or "(defaults)"}  env unset: {spec["env_pop"]}')

    if args.dry_run:
        from zyg_workflows import contact_sheet_pipeline as _csp

        for entry in plan:
            instr = _csp._qwen_angle_instruction(entry['angle'], params)
            _log(
                f'  angle {entry["index"]:02d} seed={entry["seed"]} '
                f'[{entry["part"]}{entry["part_index"]}] {entry["angle"][:64]}'
            )
            _log(f'    instruction: {(instr or "NONE — would skip")[:96]}')
        try:
            os.makedirs(args.out, exist_ok=True)
            plan_path = os.path.join(args.out, 'angle_plan.json')
            with open(plan_path, 'w', encoding='utf-8') as fh:
                json.dump({'char_id': args.char, 'conditions': cond_status, 'plan': plan}, fh, indent=2)
            _log(f'plan written: {plan_path}')
        except Exception as exc:
            _log(f'plan write skipped ({exc!r})')
        _log(f'DRY RUN complete — {len(plan)} angles x {len(conds)} conditions, out={args.out}')
        return 0

    if not comfy_ok:
        _log(f'PRECONDITION FAILED: ComfyUI unreachable ({comfy_why})')
        return 2
    if paused:
        _log(
            'PRECONDITION FAILED: FLUX renders are paused and generate_still '
            'refuses model_family=flux calls (including qwen_edit_angle). '
            'Re-run with ZYG_FLUX_RENDERS=allowed if the operator clears it.'
        )
        return 2
    runnable = [c for c in conds if cond_status[c] == 'ready']
    if not runnable:
        _log('PRECONDITION FAILED: no requested condition has its model files')
        return 2

    os.makedirs(args.out, exist_ok=True)
    verdict: dict[str, dict] = {}
    for c in conds:
        if cond_status[c] != 'ready':
            _log(f'condition {c} BLOCKED — {cond_status[c]}')
            verdict[c] = {'mean_sim': None, 'pass_rate': None, 'angle_fail_list': [], 'blocked': cond_status[c]}
            continue
        spec = _CONDITIONS[c]
        child_env = os.environ.copy()
        for k in spec['env_pop']:
            child_env.pop(k, None)
        child_env.update(spec['env_set'])
        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            '--_run-condition',
            c,
            '--char',
            args.char,
            '--angles',
            str(args.angles),
            '--conditions',
            c,
            '--out',
            args.out,
        ]
        if args.vlm:
            cmd.append('--vlm')
        _log(f'condition {c}: spawning clean child process')
        try:
            proc = subprocess.run(cmd, env=child_env, cwd=_CREWS_DIR)
            rc = proc.returncode
        except Exception as exc:
            _log(f'condition {c} spawn failed ({exc!r})')
            rc = -1
        rpt_path = os.path.join(args.out, c, 'condition_report.json')
        entry: dict = {'mean_sim': None, 'pass_rate': None, 'angle_fail_list': []}
        if os.path.isfile(rpt_path):
            try:
                with open(rpt_path, encoding='utf-8') as fh:
                    s = json.load(fh).get('summary') or {}
                entry['mean_sim'] = s.get('mean_sim')
                entry['pass_rate'] = s.get('pass_rate')
                entry['angle_fail_list'] = s.get('angle_fail_list') or []
                entry['label'] = s.get('label')
                entry['rendered'] = s.get('rendered')
                entry['report'] = rpt_path
            except Exception as exc:
                entry['error'] = f'report unreadable: {exc!r}'
        else:
            entry['error'] = f'child exited {rc} with no report'
        verdict[c] = entry

    verdict_path = os.path.join(args.out, 'verdict.json')
    with open(verdict_path, 'w', encoding='utf-8') as fh:
        json.dump(verdict, fh, indent=2)
    _log(f'verdict written: {verdict_path}')
    _log(f'{"cond":<5} {"mean_sim":>9} {"pass_rate":>10}  fails')
    for c in conds:
        v = verdict[c]
        fails = v.get('angle_fail_list') or []
        _log(
            f'{c:<5} {str(v.get("mean_sim")):>9} {str(v.get("pass_rate")):>10}  '
            f'{len(fails)}{" [" + (v.get("blocked") or v.get("error") or "") + "]" if (v.get("blocked") or v.get("error")) else ""}'
        )

    scored = [c for c in conds if verdict[c].get('mean_sim') is not None]
    return 0 if scored else 1


if __name__ == '__main__':
    sys.exit(main())
