#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pathway_bakeoff.py — render the same prompts on two model pathways and compare.

    python3 scripts/pathway_bakeoff.py                    # klein vs qwen, 8 images each
    python3 scripts/pathway_bakeoff.py --pathways klein,qwen,sdxl
    python3 scripts/pathway_bakeoff.py --n 4 --steps 20 --size 1024

WHY A SEPARATE HARNESS AND NOT THE REAL SHEET PIPELINE
------------------------------------------------------
The production contact sheet renders ONE anchor and then derives every other
cell by editing it, so identity holds across angles. That is the right design
for a character, and the wrong instrument for this question: an edit chain adds
a second model (the edit graph), a resize, and a reference-latent conditioning
step, all of which differ between pathways. Comparing finished sheets would
measure the edit chains as much as the bases.

Here every image is an independent txt2img from an identical prompt at an
identical seed, so the ONLY variable is the base model. That is what makes the
result readable.

WHAT IT DOES NOT MEASURE
------------------------
Identity consistency, LoRA response, and edit fidelity — the three things the
real pipeline cares most about — are all invisible to this test. A base can win
here and still lose where it counts, because none of these characters have a
klein LoRA yet. Treat the output as "which base draws better unaided", not
"which pathway to ship".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)

# The production interpreter — same reasoning as the documentary suite: the ML
# stack lives in the venv, and a run under /usr/bin/python3 would half-work.
_VENV_DIR = os.path.join(os.path.dirname(CREWS), '.venv')
_VENV_PY = os.path.join(_VENV_DIR, 'bin', 'python')
if (
    os.path.exists(_VENV_PY)
    and os.path.abspath(sys.prefix) != os.path.abspath(_VENV_DIR)
    and not os.environ.get('ZYG_TEST_NO_REEXEC')
):
    print(f'[re-exec] {sys.executable} -> {_VENV_PY}')
    sys.stdout.flush()
    os.execv(_VENV_PY, [_VENV_PY, '-u', os.path.abspath(__file__)] + sys.argv[1:])  # noqa: S606  re-exec under the venv interpreter: no shell, argv is this file's own


def _load_env() -> None:
    """ComfyUI is gated on ZYG_USE_COMFYUI / ZYG_COMFY_PRIMARY, which live in
    .env and are normally injected by the GUI's systemd unit. Without them
    is_available() returns False and every render reports backend=unavailable —
    a failure that looks like a broken model rather than a missing variable."""
    for cand in (
        os.path.join(os.path.dirname(os.path.dirname(CREWS)), '.env'),
        os.path.join(os.path.dirname(CREWS), '.env'),
        os.path.join(CREWS, '.env'),
    ):
        if not os.path.isfile(cand):
            continue
        with open(cand, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))
        return


_load_env()

# Eight prompts spanning what actually breaks in this pipeline: hands, faces at
# distance, low light, crowds, and the lettering that Stage 3.6 exists to catch.
PROMPTS = [
    (
        'portrait',
        'a weathered Dutch sea captain in his fifties, grey beard, heavy wool coat, '
        'standing in a candlelit ship cabin, 1650s, photorealistic, natural skin texture',
    ),
    (
        'hands',
        "close-up of a bookkeeper's hands writing in a leather ledger with a quill, "
        '1650s Amsterdam counting house, warm lamplight, photorealistic',
    ),
    (
        'wide',
        'wide establishing shot of Amsterdam harbour at dawn, 1650s, tall ships at anchor, '
        'mist over the water, dock workers in the foreground, photorealistic',
    ),
    (
        'face_close',
        "extreme close-up of a teenage boy's face, freckles, wind-reddened cheeks, "
        'looking out to sea, overcast north-sea light, photorealistic, shallow depth of field',
    ),
    (
        'lettering',
        "a merchant's desk covered in maritime charts and handwritten documents, "
        '1650s, quill and inkpot, candlelight, photorealistic',
    ),
    (
        'crowd',
        'a crowded Dutch quayside market, 1650s, dozens of figures haggling over fish barrels, '
        'overcast daylight, photorealistic',
    ),
    (
        'nightlow',
        'a lone watchman with a lantern on a wet cobbled street at night, 1650s Amsterdam, '
        'fog, reflected lamplight on stone, photorealistic',
    ),
    (
        'texture',
        'macro detail of frayed tarred rope and salt-crusted oak planking on a ship deck, '
        'raking morning light, photorealistic',
    ),
]

# Character mode: the SAME person across framings that stress identity in
# different ways — the anchor framing, a turn, a profile (ArcFace scores these
# ~0.25 against a frontal anchor by nature, so the profile anchor is used), a
# full body, and four narrative shots where the pipeline actually lives.
CHAR_PROMPTS = [
    (
        'front',
        'head and shoulders portrait, front view, eyes to camera, neutral gray studio background, soft key light',
        'front view',
    ),
    (
        'threeq',
        'three-quarter view portrait, looking slightly off camera, warm window light, plain background',
        'three-quarter view',
    ),
    ('profile', 'left profile portrait, neutral background, even soft light', 'left profile'),
    (
        'fullbody',
        'full body standing, 1650s Dutch merchant clothing, wooden harbour dock, overcast daylight',
        'full body front view',
    ),
    (
        'ledger',
        'seated at a desk writing in a leather ledger by candlelight, 1650s ship cabin, medium shot',
        'three-quarter view',
    ),
    ('laugh', 'laughing mid-conversation, tavern interior, warm lamplight, medium close-up', 'front view'),
    ('rain', 'close-up of the face, rain on skin, stormy grey light, wet hair, looking past camera', 'front view'),
    (
        'canal',
        'walking along an Amsterdam canal, 1650s, morning mist, medium shot, looking toward camera',
        'front view',
    ),
]

NEG = 'blurry, low quality, deformed face, bad anatomy, extra fingers, extra limbs, watermark, text, multiple people'


def _vram_free_mb() -> int:
    try:
        import subprocess

        out = (
            subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            .stdout.strip()
            .splitlines()
        )
        return int(out[0])
    except Exception:
        return -1


def _char_package(char_id: str, family: str, *, with_lora: bool, lora_scale: float | None):
    """The bible package for one leg. with_lora=False strips EVERY family's
    adapter key so the control leg is genuinely LoRA-less; with_lora=True keeps
    only this family's key. Nothing else about the package changes, so the
    adapter is the single variable between the two legs."""
    import copy
    from zyg_workflows import character_bible_service as cbs

    pkg = copy.deepcopy(cbs.load(char_id) or {})
    cond = pkg.setdefault('conditioning', {})
    keys = ('lora_path', 'flux_lora_path', 'sdxl_lora_path', 'qwen_lora_path', 'klein_lora_path')
    keep = cond.get(f'{family}_lora_path') if with_lora else None
    for k in keys:
        cond.pop(k, None)
    if with_lora:
        if not (keep and os.path.isfile(keep)):
            raise RuntimeError(f'no {family} LoRA recorded in the bible for {char_id}')
        cond[f'{family}_lora_path'] = keep
        if lora_scale is not None:
            cond['lora_scale'] = float(lora_scale)
    # identity via the ADAPTER only: no IP-Adapter / reference conditioning
    cond['instantid_enabled'] = False
    cond['ipadapter_reference_images'] = []
    cond['master_reference_image'] = None
    return pkg


def render_pathway(
    name: str,
    prompts,
    *,
    size: int,
    steps: int,
    cfg: float,
    seed0: int,
    outdir: str,
    char_id: str = '',
    lora_scale: float | None = None,
) -> dict:
    from zyg_workflows import comfy_generation_service as cgs

    os.makedirs(outdir, exist_ok=True)
    rows = []
    print(f'\n=== pathway: {name} ===')
    # 'klein_lora' -> family klein with the character's klein adapter staged
    family = name.split('_')[0]
    with_lora = name.endswith('_lora')
    pkg = None
    trigger = ''
    if char_id:
        pkg = _char_package(char_id, family, with_lora=with_lora, lora_scale=lora_scale)
        trigger = pkg.get('trigger_token') or ''
        print(
            f'  character {char_id}  trigger={trigger}  lora={with_lora}  scale={pkg["conditioning"].get("lora_scale")}'
        )
    if family == 'klein':
        miss = cgs.klein_missing_parts()
        if miss:
            print(f'  SKIP — missing {miss}')
            return {'pathway': name, 'skipped': f'missing {miss}', 'images': []}
        print(
            f'  unet={cgs.klein_t2i_unet()}  distilled={cgs.klein_is_distilled()}  '
            f'clip={cgs.klein_text_encoder()}  vae={cgs.klein_vae()}'
        )
    elif name == 'qwen':
        if not cgs.has_qwen_t2i():
            print('  SKIP — qwen 2512 checkpoint not found')
            return {'pathway': name, 'skipped': 'no qwen checkpoint', 'images': []}
        print(f'  unet={cgs.qwen_t2i_unet()}')

    for i, entry in enumerate(prompts):
        tag, prompt = entry[0], entry[1]
        angle = entry[2] if len(entry) > 2 else ''
        out = os.path.join(outdir, f'{i:02d}_{tag}.png')
        seed = seed0 + i  # identical across pathways — same seed, same prompt
        free_before = _vram_free_mb()
        if char_id:
            # Same finalized string on every leg: trigger + scene + the bible's
            # own quality suffix. The control leg carries the trigger too — a
            # token the base has never seen is just a word, and leaving it out
            # would make the prompt a second variable.
            q = (pkg.get('conditioning') or {}).get('quality_suffix') or ''
            prompt = ', '.join(p for p in (trigger, prompt, q) if p)
        t0 = time.time()
        try:
            ok, backend = cgs.generate_still(
                out,
                prompt,
                width=size,
                height=size,
                steps=steps,
                cfg=cfg,
                seed=seed,
                model_family=family,
                prompt_finalized=True,
                skip_qa=True,
                character_package=pkg,
                char_id=char_id or '',
                extra_negative=NEG,
                log_fn=lambda m: None,
            )
        except Exception as exc:
            ok, backend = False, f'raised {type(exc).__name__}: {exc}'
        dt = time.time() - t0
        size_b = os.path.getsize(out) if os.path.isfile(out) else 0
        rows.append(
            {
                'idx': i,
                'tag': tag,
                'seed': seed,
                'ok': bool(ok),
                'backend': backend,
                'seconds': round(dt, 1),
                'path': out if size_b else '',
                'bytes': size_b,
                'angle': angle,
                'vram_free_before_mb': free_before,
            }
        )
        print(f'  [{i + 1}/{len(prompts)}] {tag:11s} {"OK " if ok else "FAIL"} {dt:6.1f}s  {backend}')
    done = [r for r in rows if r['ok']]
    return {
        'pathway': name,
        'images': rows,
        'ok_count': len(done),
        'total_seconds': round(sum(r['seconds'] for r in rows), 1),
        'mean_seconds': round(sum(r['seconds'] for r in done) / max(len(done), 1), 1),
    }


def score_identity(results: list[dict], char_id: str, outdir: str) -> dict:
    """ArcFace similarity of every rendered cell against the character's
    verified anchor face (and profile anchor, when present). The number is
    the same one identity_qc_service uses to gate the real contact sheet, so
    a score here means what it means there. Returns {anchor, profile_anchor,
    per_pathway_mean}. Writes 'identity' into every cell row in place."""
    import shutil
    from zyg_workflows import contact_sheet_pipeline as csp
    from zyg_workflows import identity_qc_service as idqc

    ok, why = idqc.available()
    if not ok:
        print(f'identity scoring unavailable: {why}')
        return {}
    anchor = csp.identity_anchor_face_path(char_id)
    prof = csp.identity_profile_anchor_face_path(char_id)
    if not os.path.isfile(anchor):
        print(f'no anchor face for {char_id}: {anchor}')
        return {}
    # copy the anchor into the run so the tab can show it beside the renders
    a_copy = os.path.join(outdir, 'anchor_face.png')
    shutil.copy2(anchor, a_copy)
    p_copy = ''
    if prof and os.path.isfile(prof):
        p_copy = os.path.join(outdir, 'profile_anchor_face.png')
        shutil.copy2(prof, p_copy)
    means = {}
    for res in results:
        items = [
            {'path': r['path'], 'angle': r.get('angle') or 'front view'}
            for r in res.get('images') or []
            if r.get('path')
        ]
        if not items:
            continue
        sc = idqc.score_images_against_anchor(anchor, items, profile_anchor_path=p_copy or None, log_fn=lambda m: None)
        vals = []
        for r in res['images']:
            e = (sc.get('results') or {}).get(r.get('path')) or {}
            r['identity'] = None if e.get('score') is None else round(float(e['score']), 3)
            r['identity_verdict'] = e.get('verdict')
            r['face_detected'] = e.get('face_detected')
            if r['identity'] is not None:
                vals.append(r['identity'])
        res['mean_identity'] = round(sum(vals) / len(vals), 3) if vals else None
        res['faces_detected'] = sum(1 for r in res['images'] if r.get('face_detected'))
        means[res['pathway']] = res['mean_identity']
        print(
            f'  identity {res["pathway"]:12s} mean {res["mean_identity"]}  '
            f'faces {res["faces_detected"]}/{len(res["images"])}  '
            + ' '.join(f'{r["tag"]}={r.get("identity")}' for r in res['images'])
        )
    return {'anchor': a_copy, 'profile_anchor': p_copy, 'per_pathway_mean': means}


def stitch(results: list[dict], outdir: str, *, cell: int = 512) -> str | None:
    """One row per pathway, one column per prompt, labelled. Side by side is the
    whole point — two separate sheets in two files get compared from memory."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print('PIL unavailable — no stitched sheet')
        return None
    live = [r for r in results if r.get('images')]
    if not live:
        return None
    ncol = max(len(r['images']) for r in live)
    pad, label_h, row_h = 6, 26, cell + 26
    W = ncol * (cell + pad) + pad
    H = len(live) * (row_h + label_h + pad) + pad
    sheet = Image.new('RGB', (W, H), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    y = pad
    for res in live:
        d.text(
            (pad, y),
            f'{res["pathway"]}   mean {res.get("mean_seconds", 0)}s/img   '
            f'{res.get("ok_count", 0)}/{len(res["images"])} ok',
            fill=(235, 235, 235),
        )
        y += label_h
        for c, row in enumerate(res['images']):
            x = pad + c * (cell + pad)
            if row.get('path') and os.path.isfile(row['path']):
                with Image.open(row['path']) as im:
                    sheet.paste(im.convert('RGB').resize((cell, cell), Image.LANCZOS), (x, y))
            else:
                d.rectangle([x, y, x + cell, y + cell], fill=(60, 24, 24))
                d.text((x + 8, y + 8), 'FAILED', fill=(255, 160, 160))
            _id = f'  id {row["identity"]}' if row.get('identity') is not None else ''
            d.text((x + 4, y + cell + 4), f'{row["tag"]}  {row["seconds"]}s{_id}', fill=(190, 190, 190))
        y += row_h + pad
    out = os.path.join(outdir, 'bakeoff_sheet.png')
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--pathways', default='klein,qwen')
    ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--size', type=int, default=1024)
    ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--cfg', type=float, default=5.0)
    ap.add_argument('--seed', type=int, default=770001)
    ap.add_argument('--outdir', default='')
    ap.add_argument('--char', default='', help='character id: identity mode (trigger + adapter legs, ArcFace-scored)')
    ap.add_argument('--lora-scale', type=float, default=None, help='override the bible lora_scale on *_lora legs')
    a = ap.parse_args()

    outroot = a.outdir or os.path.join(CREWS, 'data', 'output', 'bakeoff', time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(outroot, exist_ok=True)
    prompts = (CHAR_PROMPTS if a.char else PROMPTS)[: max(1, a.n)]
    if a.char and a.pathways == 'klein,qwen':
        a.pathways = 'klein,klein_lora'

    from zyg_workflows import comfy_generation_service as cgs

    if not cgs.is_available():
        print('ComfyUI not available — check ZYG_USE_COMFYUI / server on :8188')
        return 2

    results = []
    for p in [x.strip().lower() for x in a.pathways.split(',') if x.strip()]:
        try:
            results.append(
                render_pathway(
                    p,
                    prompts,
                    size=a.size,
                    steps=a.steps,
                    cfg=a.cfg,
                    seed0=a.seed,
                    outdir=os.path.join(outroot, p),
                    char_id=a.char,
                    lora_scale=a.lora_scale,
                )
            )
        except Exception as exc:
            print(f'  {p}: SKIPPED — {exc}')
            results.append({'pathway': p, 'skipped': str(exc)[:160], 'images': []})

    ident = score_identity(results, a.char, outroot) if a.char else {}
    sheet = stitch(results, outroot)
    report = {
        'when': time.strftime('%Y-%m-%d %H:%M:%S'),
        'size': a.size,
        'steps': a.steps,
        'cfg': a.cfg,
        'seed0': a.seed,
        'char': a.char,
        'identity': ident,
        'sheet': sheet,
        'results': results,
    }
    with open(os.path.join(outroot, 'report.json'), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2)

    print('\n' + '=' * 62)
    for r in results:
        if r.get('skipped'):
            print(f'  {r["pathway"]:8s} SKIPPED — {r["skipped"]}')
        else:
            _mi = f'   identity {r["mean_identity"]}' if r.get('mean_identity') is not None else ''
            print(
                f'  {r["pathway"]:12s} {r["ok_count"]}/{len(r["images"])} ok   '
                f'mean {r["mean_seconds"]}s/img   total {r["total_seconds"]}s{_mi}'
            )
    print(f'\n  sheet:  {sheet}')
    print(f'  report: {os.path.join(outroot, "report.json")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
