# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ComfyUI calls: the per-cell edit, scratch txt2img and the conform pass."""

from __future__ import annotations

import os

from zyg_workflows import creature_identity as _cid
from zyg_workflows import creature_judge as _cj

from .base import CELL_SIZE, CONFORM_SEEDS, SOFT_FLAGS, _score_key, keep_sentence
from .images import make_strip, strip_letterbox

# ── ComfyUI calls ────────────────────────────────────────────────────────────

# 2026-08-26: the bare token 'hands' is gone. It was here to keep HUMAN hands
# out (the clause beside it, 'human hand', already does that job precisely), but
# a text encoder cannot tell "human hands" from "this creature's hands" — and
# the creature two lines below in the brief has two short arms ending in stubby
# hands. On the Pufferball it helped render him with no arms at all. Anything
# more that is person-only ('extra fingers', 'claw hands', …) is stripped
# downstream by comfy_generation_service._NONHUMAN_NEG_STRIP when the caller
# passes human_subject=False, so this constant only has to stop being wrong.
_NEG = (
    'human, person, man, woman, child, people, human face, human hand, text, '
    'letters, watermark, logo, second creature, duplicate creature, extra limbs, '
    'extra eyes, deformed anatomy, melted, blurry, cropped body'
)


def _edit(
    ref: str,
    instruction: str,
    dest: str,
    seed: int,
    log,
    *,
    size: int = CELL_SIZE,
    style_hint: str = '',
    body_plan: str = '',
    angles_scale: float | None = None,
    extra_negative: str = '',
) -> bool:
    """One Qwen-Image-Edit edit of `ref` → `dest` (qwen_edit_angle graph).

    body_plan is spliced into the keep clause (keep_sentence); angles_scale
    overrides the multiple-angles LoRA strength for this call (0.0 = a plain
    edit that is not a camera move, e.g. the conform pass); extra_negative
    extends _NEG."""
    from zyg_workflows import comfy_generation_service as _cgs

    if not _cgs.is_available():
        raise RuntimeError('ComfyUI unavailable — creature sheet needs the qwen_edit_angle graph')
    prompt = f'{instruction} {keep_sentence(body_plan)}'
    if style_hint:
        prompt += f' Same rendering style: {style_hint}.'
    # A minimal package whose render_style is NOT photoreal keeps the
    # qwen-edit-skin (human pore) LoRA and its trigger phrase off the edit.
    pkg = {'style_profile': {'render_style': 'stylized'}, 'conditioning': {}}
    # Creatures under-rotate (measured: "side profile" came out three-quarter,
    # "back three-quarter" came out frontal on 6/16 pufferball cells at the
    # graph's 0.9). Run the multiple-angles LoRA at full strength for the
    # duration of this call; pipelines are serialised by the busy guard so no
    # human sheet renders concurrently.
    _prev_scale = os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE')
    os.environ['ZYG_QWEN_EDIT_ANGLES_LORA_SCALE'] = (
        f'{float(angles_scale):.3f}'
        if angles_scale is not None
        else os.environ.get('ZYG_CREATURE_ANGLES_LORA_SCALE', '1.0')
    )
    try:
        ok, backend = _cgs.generate_still(
            dest,
            prompt,
            width=size,
            height=size,
            steps=int(os.environ.get('ZYG_QWEN_EDIT_STEPS', '36')),
            cfg=float(os.environ.get('ZYG_QWEN_EDIT_CFG', '4.0')),
            seed=seed,
            model_family='qwen',
            force_workflow='qwen_edit_angle',
            reference_image=ref,
            character_package=pkg,
            log_fn=log,
            extra_negative=(f'{_NEG}, {extra_negative}' if extra_negative else _NEG),
            skip_qa=True,
            prompt_finalized=True,
            human_subject=False,
            # every cell uses the same 41 GB edit model: clearing VRAM between
            # stills cost a full reload per cell (2h37m for 16 cells + regens)
            clear_vram_after=False,
        )
    finally:
        if _prev_scale is None:
            os.environ.pop('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE', None)
        else:
            os.environ['ZYG_QWEN_EDIT_ANGLES_LORA_SCALE'] = _prev_scale
    if not ok:
        log(f'edit failed ({backend}) seed={seed}')
    if ok and os.path.isfile(dest):
        n = strip_letterbox(dest)
        if n:
            log(f'letterbox bars stripped ({n}px) from {os.path.basename(dest)}')
        return True
    return False


def _txt2img(prompt: str, dest: str, seed: int, log, *, size: int = CELL_SIZE, family: str | None = None) -> bool:
    """From-scratch anchor: FLUX.2 klein-4B (default) or Qwen-2512 txt2img."""
    from zyg_workflows import comfy_generation_service as _cgs

    if not _cgs.is_available():
        raise RuntimeError('ComfyUI unavailable — creature anchor needs a txt2img graph')
    fam = (family or os.environ.get('ZYG_CREATURE_T2I_FAMILY') or 'klein').strip().lower()
    if fam == 'flux':
        raise RuntimeError('FLUX.1-dev is paused under the licence gate; creature anchors render on klein or qwen')
    wf = 'klein_txt2img' if fam == 'klein' else 'qwen_txt2img'
    cfg = float(os.environ.get('ZYG_KLEIN_ANCHOR_CFG', '4.0')) if fam == 'klein' else 4.0
    ok, backend = _cgs.generate_still(
        dest,
        prompt,
        width=size,
        height=size,
        steps=20,
        cfg=cfg,
        seed=seed,
        model_family=fam,
        force_workflow=wf,
        log_fn=log,
        extra_negative=_NEG,
        skip_qa=True,
        prompt_finalized=True,
        human_subject=False,
    )
    if not ok:
        log(f'txt2img failed ({backend}) seed={seed} family={fam}')
    if ok and os.path.isfile(dest):
        n = strip_letterbox(dest)
        if n:
            log(f'letterbox bars stripped ({n}px) from {os.path.basename(dest)}')
        return True
    return False


def conform_instruction(body_plan: str) -> str:
    bp = (body_plan or '').strip().rstrip('.')
    return (
        f'Adjust the creature so that it has {bp}. Keep the face, eyes, mouth, fur texture, '
        'colours, pose, lighting, background and camera angle exactly the same; change nothing else.'
    )


def check_anchor_agreement(front: str, side: str, body_plan: str, sheet_dir_: str, log) -> dict | None:
    """Do the two operator locks agree about the creature's anatomy?

    The sheet routes cells off TWO anchors (side/back/top from the side lock,
    everything else from the front lock), so locks that disagree about an
    appendage split the sheet into two families that no per-cell check can catch
    — every cell is faithful to the anchor it came from. MEASURED on the
    pufferball (2026-08-26): the front lock carried a tail arcing above the head,
    the side lock a short one at shoulder height, and 16 cells rendered for
    76 minutes before anyone saw it. DINO between the locks read 0.9237 and
    passed: on a creature that is mostly one round furry mass the tail is a
    rounding error.

    Each question is asked of ONE lock at a time and the answers compared here.
    Comparing the panels in the PROMPT was measured useless the same day — across
    a front and a side view the projected angle of every limb genuinely differs,
    so "held at the same angle in both panels?" answered 'no' on all four pairs
    tested, the known-bad one and the good candidates alike. A question whose
    answer never changes cannot arbitrate anything.

    Returns None when it cannot run (no body plan, no covered part, judge
    offline); otherwise {'ok', 'judged', 'disagree': [ids], 'answers': {...}}.
    """
    if not (front and side and os.path.isfile(front) and os.path.isfile(side)):
        return None
    items = _cj.pair_items(body_plan)
    if not items:
        return None
    pre = _cj.pair_preamble()
    jobs = [
        {'key': 'front', 'image': front, 'items': items, 'preamble': pre},
        {'key': 'side', 'image': side, 'items': items, 'preamble': pre},
    ]
    res = _cj.judge_batch(jobs, log_fn=log) or {}
    got = {k: (res.get(k) or {}) for k in ('front', 'side')}
    if not all(v.get('judged') for v in got.values()):
        log('anchor agreement: judge did not answer — locks NOT compared')
        return {'ok': None, 'judged': False, 'reason': 'judge offline'}

    def _answers(v: dict) -> dict[str, str]:
        return {
            q.get('id'): str(q.get('answer') or '').strip().lower()
            for q in (v.get('verdicts') or [])
            if not q.get('error')
        }

    fa, sa = _answers(got['front']), _answers(got['side'])
    shared = [
        i['id']
        for i in items
        if i['id'] in fa and i['id'] in sa and fa[i['id']] in ('yes', 'no') and sa[i['id']] in ('yes', 'no')
    ]
    n_err = len(items) - len(shared)
    if not shared:
        log(f'anchor agreement: no question answered on both locks ({n_err} unusable) — locks NOT compared')
        return {'ok': None, 'judged': False, 'errors': n_err, 'reason': 'no comparable answers'}
    disagree = [q for q in shared if fa[q] != sa[q]]
    strip = make_strip(
        front,
        side,
        os.path.join(sheet_dir_, 'anchors', 'anchor_pair_strip.png'),
        ref_label='FRONT LOCK',
        cand_label='SIDE LOCK',
    )
    out = {
        'ok': not disagree,
        'judged': True,
        'strip': strip,
        'disagree': disagree,
        'asked': shared,
        'errors': n_err,
        'answers': {'front': fa, 'side': sa},
    }
    if n_err:
        log(f'anchor agreement: {n_err}/{len(items)} question(s) unusable — verdict is partial')
    if out['ok']:
        log(f'anchor agreement: locks agree on all {len(shared)} question(s) ({", ".join(shared)})')
    else:
        log(
            f'WARNING: the two anchor locks DISAGREE on {", ".join(disagree)} — '
            f"side/back/top cells will carry the side lock's version and the rest the "
            f"front lock's. Re-derive one lock from the other before spending a full "
            f'sheet: scripts/creature_variants.py --source <the lock to keep> '
            f'--angles-lora 1.0. Strip: {strip}'
        )
        for q in disagree:
            log(f'  {q}: front={fa[q]} side={sa[q]}')
    return out


def conform_variants(
    src: str,
    body_plan: str,
    out_dir: str,
    identity_ref: str,
    log,
    *,
    variants: list[tuple[str, str]],
    style_hint: str = '',
    seeds: int | None = None,
    angle_desc: str = 'a straight-on front view showing the whole body',
    kind: str = 'body',
    band: str = 'front',
    extra_negative: str = '',
    seed_base: int = 4300,
    angles_scale: float = 0.0,
) -> dict[str, dict]:
    """Edits of `src`, one
    instruction per (tag, instruction) variant, `seeds` seeds each, ALL judged in
    a single batch against `identity_ref` (cell checklist incl. the body-plan
    question) + DINO, so the 41 GB edit model is swapped out once, not per
    variant. Returns {tag: {'path': best or None, 'candidates': [ranked],
    'instruction'}}. The engine behind the in-run conform pass and behind
    scripts/creature_variants.py, so an operator pick runs the pipeline's own
    code path.

    angles_scale defaults to 0.0 - the conform pass and most operator variants
    restyle a part in place ("add fur to the tail") and the multiple-angles LoRA
    only fights that. Pass 1.0 when the variant IS a camera move: re-deriving one
    locked anchor FROM the other (e.g. a side profile from the front lock, so
    both locks carry the same tail) is a rotation, and at 0.0 Qwen under-rotates
    a creature so badly that "90 degrees" lands on three-quarter."""
    n = max(1, int(seeds if seeds is not None else CONFORM_SEEDS))
    os.makedirs(out_dir, exist_ok=True)
    made: list[tuple[str, int, str]] = []  # (tag, k, path)
    for vi, (tag, instr) in enumerate(variants):
        for k in range(n):
            dst = os.path.join(out_dir, f'{tag}_cand_{k}.png')
            if _edit(
                src,
                instr,
                dst,
                seed_base + vi * 10 + k,
                log,
                style_hint=style_hint,
                body_plan=body_plan,
                angles_scale=angles_scale,
                extra_negative=extra_negative,
            ):
                made.append((tag, k, dst))
    base = _cj.load_items(_cj.CELL_CHECKLIST)
    jobs = []
    for tag, k, c in made:
        sp = os.path.join(out_dir, f'{tag}_strip_{k}.png')
        make_strip(identity_ref, c, sp)
        jobs.append(
            {
                'key': f'{tag}:{k}',
                'image': sp,
                'items': _cj.cell_items(angle_desc, kind=kind, band=band, base=base, body_plan=body_plan),
                'preamble': base.get('preamble', ''),
            }
        )
    vs = _cj.judge_batch(jobs, offload=True, log_fn=log) if jobs else {}
    out: dict[str, dict] = {}
    for tag, instr in variants:
        ranked = []
        for t, k, c in made:
            if t != tag:
                continue
            v = vs.get(f'{tag}:{k}') or {}
            d = _cid.similarity(identity_ref, c) if _cid.enabled() else None
            flags = list(v.get('flags') or [])
            hard = [f for f in flags if f not in SOFT_FLAGS]
            ranked.append(
                {
                    'path': c,
                    'seed': seed_base + [x[0] for x in variants].index(tag) * 10 + k,
                    'ok': (not hard) if v.get('judged') else bool(v.get('ok', True)),
                    'judged': bool(v.get('judged')),
                    'flags': flags,
                    'soft': [f'vlm:{f}' for f in flags if f in SOFT_FLAGS],
                    'dino': d,
                    'reasons': [f'vlm:{f}' for f in hard],
                    'verdicts': v.get('verdicts', []),
                }
            )
        ranked.sort(key=_score_key, reverse=True)
        out[tag] = {'path': ranked[0]['path'] if ranked else None, 'candidates': ranked, 'instruction': instr}
    return out


def conform_anchor(
    src: str,
    body_plan: str,
    out_dir: str,
    identity_ref: str,
    log,
    *,
    style_hint: str = '',
    seeds: int | None = None,
    tag: str = 'conform',
    angle_desc: str = 'a straight-on front view showing the whole body',
    kind: str = 'body',
    band: str = 'front',
    instruction: str | None = None,
    extra_negative: str = '',
    seed_base: int = 4300,
) -> dict:
    """Best-of-N conform edit of one image (see conform_variants)."""
    instr = instruction or conform_instruction(body_plan)
    return conform_variants(
        src,
        body_plan,
        out_dir,
        identity_ref,
        log,
        variants=[(tag, instr)],
        style_hint=style_hint,
        seeds=seeds,
        angle_desc=angle_desc,
        kind=kind,
        band=band,
        extra_negative=extra_negative,
        seed_base=seed_base,
    )[tag]
