# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service_steps.py — the stages of build_scene, one per step.

A pure extraction of storyteller_scene_service.build_scene's body, which had
grown to 1,254 lines in a single function. Every `_step_*` below is the block
that used to sit under the matching `# N ──` banner, with the locals it read
passed in explicitly and the ones the next stage needs returned; nothing was
reordered, no default changed, no call dropped.

The scene helpers the steps call still live in the service module and are
reached through `_svc()`, which imports it on use — the same pattern
comfy_generation_service_steps uses, so the service's monkeypatchable globals
stay live and no import order can turn this into a cycle.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import time
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe

# This module carries the original top import block verbatim; __init__.py and the
# sibling sections re-import these names from here, so attribute access such as
# storyteller_scene_service_steps.os keeps resolving.
__all__ = [
    'json',
    'math',
    'subprocess',
    'np',
    'Image',
    'ImageEnhance',
    'ImageFilter',
    '_seal',
    'exe',
]

# channel kept from the pre-split module
_zyg_log = logging.getLogger('zyg_workflows.storyteller_scene_service_steps')


def _svc() -> Any:
    """The parent service module, imported on use rather than at module scope.

    Same reason as comfy_generation_service_steps: going through the module
    object keeps the service's monkeypatchable globals live instead of
    snapshotting them, and a lazy import can never become an import cycle if the
    service ever needs this module at its own module scope.
    """
    from zyg_workflows import storyteller_scene_service as _service

    return _service


# ── gate receipts ────────────────────────────────────────────────────────────


class _GateReceipts:
    """The scene's quality-gate receipt registry.

    Same contract as pipeline_scholarly.py's Stage 3.7 fix (see that file's
    comment at its own `_GATES_EXPECTED`): a quality gate nested inside a
    branch that can go permanently false — an env var, a spec flag, a missing
    dependency — produces no log line and no state key when it is skipped that
    way. There is nothing in the run, and nothing in scene_state.json
    afterward, to notice. Every gate pre-registers as "not run yet" before the
    scene starts, files a receipt (ran/reason/stats) on every exit path, and
    `audit()` names any gate that filed literally nothing as a wiring defect —
    distinct from one that ran and reported a legitimate skip.

    'hand_qc' covers comfy_generation_service.apply_hand_fixer_pass, wired in
    step 1b2. apply_hand_fixer_pass takes an optional `receipt` out-param that
    reports ran=True/False + a skip reason (e.g. 'skip_clean',
    'detection_unavailable', 'halted') on every exit path — the per-shot
    receipts are aggregated into the scene-level gate.
    """

    EXPECTED = ('hand_qc', 'line_verify')

    def __init__(self, log):
        self._log = log
        self.receipts: dict = {}
        # Pre-register every expected gate as NOT RUN before anything can skip
        # it. Without this, a gate the run never reaches files nothing, and "no
        # receipt" can only be told apart from "no gate" by reading the source —
        # exactly the archaeology this pattern exists to avoid.
        for name in self.EXPECTED:
            self.receipts[name] = {
                'gate': name,
                'ran': False,
                'reason': 'scene build never reached this gate',
                'stats': {},
                'ts': round(time.time(), 3),
            }

    def file(self, name, ran, reason='', stats=None):
        """File a gate's run/skip receipt. Call this on every exit path."""
        rec = {
            'gate': str(name),
            'ran': bool(ran),
            'reason': str(reason or '')[:200],
            'stats': dict(stats or {}),
            'ts': round(time.time(), 3),
        }
        self.receipts[str(name)] = rec
        if ran:
            self._log(f'[scene] gate {name}: RAN — {rec["stats"] or "no stats"}')
        else:
            self._log(f'[scene] gate {name}: DID NOT RUN — {rec["reason"] or "no reason given"}')
        return rec

    def audit(self):
        """Name every expected gate that filed no receipt at all."""
        _missing = [_g for _g in self.EXPECTED if _g not in self.receipts]
        _skipped = [_r['gate'] for _r in self.receipts.values() if not _r['ran']]
        audit = {
            'expected': list(self.EXPECTED),
            'filed': sorted(self.receipts),
            'missing': _missing,
            'skipped': _skipped,
        }
        if _missing:
            self._log(
                f'[scene] GATE AUDIT — {len(_missing)} gate(s) filed NO receipt '
                f'at all: {", ".join(_missing)}. Pre-registration should make '
                f'this impossible, so it means the registry and the gates '
                f'disagree — a wiring defect, not a quality result.'
            )
        elif _skipped:
            self._log(f'[scene] GATE AUDIT — every gate reported in; {len(_skipped)} skipped: {", ".join(_skipped)}')
        else:
            self._log(f'[scene] GATE AUDIT — all {len(self.EXPECTED)} gates ran: {", ".join(sorted(self.receipts))}')
        return audit


def _free_comfy_vram() -> None:
    """Hand the sampler's VRAM back between stills. Best-effort: a scene that
    never talked to ComfyUI has nothing to free, and a failure here costs the
    next stage nothing but headroom."""
    try:
        from zyg_workflows import _comfy_client

        _comfy_client.free_vram()
    except Exception as _exc:
        _zyg_log.debug('comfy vram release skipped: %s', _exc)


# ── 1 ── stills ──────────────────────────────────────────────────────────────


def _step_stills(spec: dict, out_dir: str, W: int, H: int, log, gates: _GateReceipts) -> dict | None:
    """Stage 1: every shot's still, locked and repaired. Derived shots wait for
    their source + the wardrobe locks. Returns {shot_id: png} or None to abort."""
    stills: dict[str, str] = {}

    # 1a ── chart shots ──────────────────────────────────────────────────────
    # A `map` shot is not generated at all: it IS the series chart, drawn by
    # maritime_map_service from public-domain coastlines. That is the whole
    # reason it exists — the brief wants the same map in every episode, and a
    # sampler cannot promise that. The plate is linked in at native size rather
    # than copied, because at 5376×3072 a copy per scene directory is 30 MB of
    # duplicate for a file whose entire contract is that it never varies.
    for shot in spec['shots']:
        if shot.get('kind') != 'map':
            continue
        from zyg_workflows import maritime_map_service as mms

        chart = mms.get_chart(log_fn=log)
        p = os.path.join(out_dir, f'still_{shot["id"]}.png')
        hp = _svc()._hires_path(p)
        if not os.path.exists(hp):
            try:
                os.symlink(chart.path, hp)
            except OSError as _exc:
                _zyg_log.debug('chart symlink unavailable, copying the plate instead: %s', _exc)
                shutil.copyfile(chart.path, hp)
        if not os.path.isfile(p):
            Image.open(chart.path).convert('RGB').resize((W, H), Image.LANCZOS).save(p)
        stills[shot['id']] = p
        log(
            f'[scene] chart shot {shot["id"]}: {os.path.basename(chart.path)} '
            f'(rev {mms.CHART_REV}, ±{chart.lat_max:.1f}° mercator)'
        )

    for shot in spec['shots']:
        if shot.get('kind') in ('derived', 'crop', 'map'):
            continue
        p = os.path.join(out_dir, f'still_{shot["id"]}.png')
        r = _svc()._render_shot_still(shot, p, W, H, log_fn=log, continuity=spec.get('continuity'))
        if not r:
            log(f'[scene] ABORT — still {shot["id"]} failed')
            gates.audit()
            return None
        stills[shot['id']] = r
        _free_comfy_vram()

    _step_wardrobe_lock(spec, stills, log)
    _step_prop_edit(spec, stills, log)
    _step_hand_repair(spec, stills, W, H, log, gates)
    if _step_derived_stills(spec, stills, out_dir, W, H, log, gates) is None:
        return None
    return stills


def _step_wardrobe_lock(spec: dict, stills: dict, log) -> None:
    """1b ── wardrobe lock (zero-drift pass).

    Prompts steer but cannot GUARANTEE identical costumes across different
    render paths (solo vs multichar regional vs restyle re-synthesis). The
    Qwen-edit wardrobe pass enforces the exact canonical outfit per character
    on every continuity shot — face/pose/background/art-style preserved.
    Marker files make the pass idempotent across cached re-runs."""
    wlocks = spec.get('wardrobe_locks') or {}
    if not wlocks:
        return
    from zyg_workflows import wardrobe_service

    for shot in spec['shots']:
        # derived shots inherit their source's already-locked wardrobe
        if not shot.get('continuity') or shot.get('kind') in ('derived', 'crop', 'map'):
            continue
        sp = stills[shot['id']]
        for cid in shot.get('char_ids', []):
            wl = wlocks.get(cid)
            if not wl:
                continue
            marker = sp + f'.wlock_{cid[:8]}'
            if os.path.isfile(marker):
                continue
            ok = wardrobe_service.change_outfit(
                sp,
                {'prompt_clause': wl['outfit'], 'negative': wl.get('negative', '')},
                dst_path=sp,
                char_id=cid,
                seed=int(wl.get('seed', 42)),
                log_fn=log,
                subject=wl.get('subject', 'the person'),
            )
            if ok:
                with open(marker, 'w') as mfh:
                    mfh.write(wl['outfit'])
                log(f'[scene] wardrobe locked: {shot["id"]} / {cid[:8]}')
            else:
                log(f'[scene] WARN wardrobe lock failed: {shot["id"]} / {cid[:8]} — shipping unlocked still')
    _free_comfy_vram()


def _step_prop_edit(spec: dict, stills: dict, log) -> None:
    """1b1 ── prop edit (2026-08-21).

    Some props the sampler simply will not put in a hand. Cornelis smoking a
    long clay pipe was benched over three seeds with the pipe as the FIRST
    clause of the prompt, which fixed the room and the hand placement and
    still produced a sliver of stick every time: SDXL under a character LoRA
    holds the pose it was trained on, and a churchwarden pipe raised to the
    mouth is not in that pose.

    Qwen-edit is good at exactly this — the source enters as conditioning, so
    identity, pose, lighting and art style survive and only the named object
    changes. The stage sits HERE on purpose: after the wardrobe lock, so the
    costume is already canonical and cannot be re-invented by this pass, and
    BEFORE the hi-res upscale and hand repair, so the fixer repairs the hand
    that is holding the new prop rather than the empty one it replaced. Run it
    after the repair instead and the pipe arrives in a hand nothing will ever
    look at again."""
    for shot in spec['shots']:
        pe = shot.get('prop_edit')
        if not pe or shot.get('kind') in ('derived', 'crop', 'map'):
            continue
        sp = stills[shot['id']]
        marker = sp + '.propedit'
        if os.path.isfile(marker) and not pe.get('force'):
            continue
        if pe.get('box'):
            ok = _svc()._prop_edit_region(sp, pe, log_fn=log)
        else:
            tmp = sp + '.propedit.tmp.png'
            ok = _svc()._qwen_scene_edit(
                sp, tmp, pe['instruction'], negative=pe.get('negative', ''), seed=int(pe.get('seed', 42)), log_fn=log
            )
            if ok:
                shutil.move(tmp, sp)
        if ok:
            with open(marker, 'w') as mfh:
                mfh.write(pe['instruction'])
            log(f'[scene] prop edit {shot["id"]}: {pe["instruction"][:70]}…')
        else:
            log(f'[scene] WARN prop edit failed: {shot["id"]} — shipping the still without it')
        _free_comfy_vram()


def _step_hand_repair(spec: dict, stills: dict, W: int, H: int, log, gates: _GateReceipts) -> None:
    """1b2 ── hi-res base + hand repair (2026-08-11).

    Scene stills previously skipped anatomy repair entirely: they got the SDXL
    render, the arcane restyle and the Qwen wardrobe edit, but NO hand pass,
    so melted fingers shipped. The episode pipeline has run the repair since
    the 2026-07-24 rebuild — this wires the SAME entry point in, with three
    corrections that a first attempt on this scene proved are all necessary:

     1. UPSCALE FIRST. At delivery size a hand is ~90 px across and the fill
        has nothing to reconstruct from. The ESRGAN base the camera move needs
        anyway is built here instead of at frame time, and the repair runs on
        THAT — ~2× the linear pixel density, and the frames then use the
        repaired hi-res pixels directly.
     2. ACTION-FIRST PROMPT. apply_hand_fixer_pass keeps only prompt.split(',')[0],
        so an identity-first prompt tells the fill nothing about what the hand
        is DOING. With the canon phrase first, the fill kept erasing the quill
        hand (the erasure guard then reverted the whole frame, twice). A shot's
        `hand_prompt` leads with the action, so the held prop survives.
     3. PARTIAL DENOISE. At denoise 1.0 the fill re-synthesises in its own
        photoreal style and invents props — it gave the resting hand a second
        modern pen and left a visible seam against the arcane restyle. 0.60
        rebuilds finger structure while staying inside the existing painting.

    The skip-clean gate is also bypassed by default here: on arcane-restyled
    stills the Ollama hand judge scores plainly-melted hands 1.00 at HIGH
    confidence (measured on this scene), so "already clean" is not trustworthy
    for this art style. Every other guard in the fixer — VLM erasure check,
    tone guard, box-count conservation, whole-frame revert — still applies."""
    hf_cfg = spec.get('hand_fix')
    if hf_cfg is False:
        gates.file('hand_qc', False, 'hand_fix disabled in scene spec')
        return
    hf_cfg = hf_cfg if isinstance(hf_cfg, dict) else {}
    from zyg_workflows import character_bible_service as _cbs_hf
    from zyg_workflows import comfy_generation_service as _cgs_hf

    scales = _svc()._base_scale_for(spec)
    _hq_stats = {'attempted': 0, 'repaired': 0, 'cached': 0, 'not_applicable': 0}
    _hq_skip_reasons: dict = {}
    for shot in spec['shots']:
        if shot.get('kind') in ('derived', 'crop', 'map') or shot.get('hand_fix') is False:
            continue
        sp = stills[shot['id']]
        scale = float(scales.get(shot['id'], 1.0))
        hp = _svc()._hires_path(sp)
        if scale >= _svc()._HIRES_MIN and not os.path.isfile(hp):
            Image.open(sp).convert('RGB')
            big = _svc()._esrgan_resize(
                Image.open(sp).convert('RGB'), int(round(W * scale)), int(round(H * scale)), log_fn=log
            )
            big.save(hp)
            log(f'[scene] hi-res base {shot["id"]}: ×{scale:.2f} → {big.size}')
        target = hp if os.path.isfile(hp) else sp
        if not shot.get('char_ids'):
            _hq_stats['not_applicable'] += 1
            continue  # scenery has no hands to repair
        marker = target + '.handfix'
        if os.path.isfile(marker):
            _hq_stats['cached'] += 1
            continue
        cid0 = shot['char_ids'][0]
        hf_prompt = shot.get('hand_prompt') or ('a hand with correct anatomy, ' + (_svc()._canon_lock(cid0)[0] or ''))
        with _svc()._env_overrides(
            ZYG_HAND_FIXER_DENOISE=hf_cfg.get('denoise', 0.60),
            ZYG_HAND_FIXER_ATTEMPTS=hf_cfg.get('attempts', 3),
            ZYG_HAND_FIXER_CROP_CTX=hf_cfg.get('crop_ctx', 2.6),
            ZYG_HAND_FIXER_MAX_COLOR_DELTA=hf_cfg.get('max_color_delta', 75),
            ZYG_HAND_FIXER_SKIP_CLEAN=(1.01 if hf_cfg.get('force', True) else None),
        ):
            _hf_receipt: dict = {}
            ok = _cgs_hf.apply_hand_fixer_pass(
                target,
                hf_prompt,
                seed=int(shot.get('seed', 7)) + 101,
                log_fn=log,
                character_package=_cbs_hf.load(cid0) or None,
                receipt=_hf_receipt,
            )
        _hq_stats['attempted'] += 1
        if ok:
            _hq_stats['repaired'] += 1
        else:
            _hq_reason = str(_hf_receipt.get('reason') or 'unknown')
            _hq_skip_reasons[_hq_reason] = _hq_skip_reasons.get(_hq_reason, 0) + 1
        with open(marker, 'w') as mfh:
            mfh.write(f'applied={ok} reason={_hf_receipt.get("reason")}')
        log(
            f'[scene] hand repair {shot["id"]}: '
            f'{"applied" if ok else "skipped (" + str(_hf_receipt.get("reason", "unknown")) + ") — original kept"}'
        )
    _free_comfy_vram()
    if _hq_stats['attempted'] == 0:
        gates.file(
            'hand_qc',
            False,
            'no shot in this scene reached a hand-fixer attempt (no eligible shots, or all cached from a prior run)',
            _hq_stats,
        )
    else:
        gates.file('hand_qc', True, '', {**_hq_stats, 'skip_reasons': _hq_skip_reasons})


def _step_derived_stills(
    spec: dict, stills: dict, out_dir: str, W: int, H: int, log, gates: _GateReceipts
) -> dict | None:
    """1c ── derived shots: cut a second shot out of an already-locked still.

    A derived shot shares its source's wardrobe, identity, props, lighting and
    art style BY CONSTRUCTION — the strongest continuity guarantee available.
      kind 'crop'    : pure pixel crop + ESRGAN upscale. DETERMINISTIC — nothing
                       is re-generated, so nothing can drift. Preferred.
      kind 'derived' : qwen-edit (e.g. remove a figure). Generative, so use only
                       when a crop cannot express the shot; verify the result."""
    for shot in spec['shots']:
        if shot.get('kind') not in ('derived', 'crop'):
            continue
        p = os.path.join(out_dir, f'still_{shot["id"]}.png')
        if os.path.isfile(p) and not shot.get('force'):
            log(f'[scene] still exists, reusing: {os.path.basename(p)}')
            stills[shot['id']] = p
            continue
        src_id = shot['from']
        if src_id not in stills:
            log(f'[scene] ABORT — derived shot {shot["id"]} needs {src_id}')
            gates.audit()
            return None
        if shot['kind'] == 'crop':
            src_img = Image.open(stills[src_id]).convert('RGB')
            box = shot['box']
            if all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in box):
                sw, sh = src_img.size
                box = (int(box[0] * sw), int(box[1] * sh), int(box[2] * sw), int(box[3] * sh))
            crop = src_img.crop(tuple(int(v) for v in box))
            _svc()._esrgan_resize(crop, W, H, log_fn=log).save(p)
            log(f'[scene] crop still: {shot["id"]} ← {src_id} {tuple(box)}')
        else:
            if not _svc()._qwen_scene_edit(
                stills[src_id],
                p,
                shot['instruction'],
                negative=shot.get('negative', ''),
                seed=int(shot.get('seed', 42)),
                log_fn=log,
            ):
                log(f'[scene] ABORT — derived still {shot["id"]} failed')
                gates.audit()
                return None
            log(f'[scene] derived still: {shot["id"]} ← {src_id}')
        stills[shot['id']] = p
        _free_comfy_vram()
    return stills
