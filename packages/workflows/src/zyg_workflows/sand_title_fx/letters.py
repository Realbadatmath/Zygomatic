# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The letters themselves and the render passes through Qwen-Image-Edit — verbatim
sections of the former sand_title_fx.py."""

from __future__ import annotations

import difflib
import os
import tempfile

import cv2
import numpy as np
from PIL import Image
import logging as _zyg_logging
from zyg_workflows.sand_title_fx.constants import (
    INSTRUCTION,
    EXTRA_INSTRUCTION,
    NEGATIVE,
    PLATE_PROMPT,
    DIFF_THRESH,
    DILATE_PX,
    MIN_COMP_FRAC,
    _log,
)
from zyg_workflows.sand_title_fx.ocr_gate import (
    normalise,
    judge_lettering,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sand_title_fx')


# ── the letters themselves ──────────────────────────────────────────────────
def _luma(path_or_arr) -> np.ndarray:
    if isinstance(path_or_arr, str):
        arr = cv2.imread(path_or_arr, cv2.IMREAD_COLOR)
        if arr is None:
            raise FileNotFoundError(path_or_arr)
    else:
        arr = path_or_arr
    return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)


def letters_mask(src_png, words_png) -> np.ndarray:
    """uint8 0/255 mask of what the edit added — the lettering, nothing else.

    Small specks are dropped by component area, not by blur: a grain of sand
    that moved between the two renders is not a letter."""
    a = _luma(src_png)
    b = _luma(words_png)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    d = cv2.absdiff(b, a)
    d = cv2.medianBlur(d, 3)
    m = (d > DIFF_THRESH).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DILATE_PX + 1, 2 * DILATE_PX + 1))
    m = cv2.dilate(m, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    floor = MIN_COMP_FRAC * a.shape[0] * a.shape[1]
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= floor:
            keep[lab == i] = 255
    return keep


def _paste_letters(src_png, cand_png, out_png):
    """Full-resolution plate + only the letter region of the candidate.

    The edit graph hands back ~1-2 MP whatever it is given, so a straight
    upscale would soften the whole plate. Only the pixels the edit actually
    changed are carried back."""
    src = cv2.imread(src_png, cv2.IMREAD_COLOR)
    cand = cv2.imread(cand_png, cv2.IMREAD_COLOR)
    if cand is None or src is None:
        raise FileNotFoundError(cand_png if cand is None else src_png)
    H, W = src.shape[:2]
    if cand.shape[:2] != (H, W):
        cand = cv2.resize(cand, (W, H), interpolation=cv2.INTER_LANCZOS4)
    m = letters_mask(src_png, cand)
    if not m.any():
        cv2.imwrite(out_png, cand)
        return out_png, m
    a = (cv2.GaussianBlur(m, (5, 5), 0).astype(np.float32) / 255.0)[..., None]
    out = src.astype(np.float32) * (1 - a) + cand.astype(np.float32) * a
    cv2.imwrite(out_png, np.clip(out, 0, 255).astype(np.uint8))
    return out_png, m


# ── the render passes ───────────────────────────────────────────────────────
def _ensure_comfy_env():
    """Route stills through ComfyUI from THIS process (never kanban-server)."""
    try:
        from zyg_workflows import _comfy_client as _cc
    except ImportError:
        return
    try:
        if _cc.server_reachable():
            os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
            os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    except Exception:  # noqa: BLE001
        return


def render_plate(out_png, prompt=PLATE_PROMPT, width=1280, height=720, seed=5, log=None):
    """A plain sand plate — text-to-image, no reference, no character."""
    _ensure_comfy_env()
    from zyg_workflows import comfy_generation_service as cgs

    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    ok, backend = cgs.generate_still(
        out_png,
        prompt,
        width=width,
        height=height,
        steps=20,
        cfg=4.0,
        seed=seed,
        model_family='qwen',
        skip_qa=True,
        prompt_finalized=True,
        solo_subject=False,
        human_subject=False,
        clear_vram_after=False,
        log_fn=lambda m: _log(log, str(m)[:200]),
    )
    if not ok or not os.path.isfile(out_png):
        raise RuntimeError(f'plate render failed ({backend})')
    _log(log, f'plate rendered via {backend}: {out_png}')
    return out_png


def _score(verdict, want):
    """How close this candidate came, for picking a loser to keep."""
    got = max(
        (normalise(verdict.get(k) or '') for k in ('ocr_full', 'ocr_crop')),
        key=lambda g: difflib.SequenceMatcher(None, want, g).ratio(),
        default='',
    )
    return difflib.SequenceMatcher(None, want, got).ratio()


def write_words_in_sand(
    src_png, words, out_png, seeds=6, log=None, extra_instruction=None, first_seed=7, precheck=None
) -> dict:
    """Best-of-N through Qwen-Image-Edit, decided by the two-reader gate.

    Early exit on the first exact read — a second exact hit cannot be more
    exact, and every extra seed is 20 GPU-seconds spent proving that.

    extra_instruction : appended to the instruction. None = EXTRA_INSTRUCTION
                        (the default, so every caller inherits it); '' turns
                        the suffix off.
    first_seed        : seed of candidate 0; candidate k is first_seed+k*7919.
    precheck          : (seed, path) of an already-composited candidate to
                        judge BEFORE anything is rendered. A pass there costs
                        no GPU at all."""
    src = Image.open(src_png).convert('RGB')
    W, H = src.size
    want = normalise(words)
    suffix = EXTRA_INSTRUCTION if extra_instruction is None else extra_instruction
    instruction = INSTRUCTION.format(words=words) + suffix
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    work = tempfile.mkdtemp(prefix='sandtitle_')

    tried, best_exact, best_close = [], None, None

    def _consider(seed, path, rendered):
        nonlocal best_exact, best_close
        v = judge_lettering(path, words, mask=letters_mask(src_png, path), log=log)
        row = {
            'seed': seed,
            'ocr_full': v['ocr_full'],
            'ocr_crop': v['ocr_crop'],
            'vlm_quote': v['vlm_quote'],
            'exact': v['exact'],
            'conf': v['conf'],
            'rendered': rendered,
        }
        tried.append(row)
        rec = dict(row, path=path, by=v['by'], ratio=_score(v, want))
        if v['exact']:
            best_exact = rec
            return True
        if best_close is None or rec['ratio'] > best_close['ratio']:
            best_close = rec
        return False

    done = False
    if precheck:
        p_seed, p_path = precheck
        if p_path and os.path.isfile(p_path):
            _log(log, f'seed {p_seed}: re-judging the frame already on disk ({p_path})')
            done = _consider(p_seed, p_path, False)

    if not done:
        _ensure_comfy_env()
        from zyg_workflows import comfy_generation_service as cgs

        ref = os.path.join(work, 'source.png')
        src.save(ref)
        for k in range(int(seeds)):
            seed = int(first_seed) + k * 7919
            dest = os.path.join(work, f'cand_{k}.png')
            _log(log, f'seed {seed}: writing "{words}" in the sand…')
            ok, backend = cgs.generate_still(
                dest,
                instruction,
                width=W,
                height=H,
                steps=20,
                cfg=4.0,
                seed=seed,
                model_family='qwen',
                force_workflow='qwen_edit_angle',
                reference_image=ref,
                character_package={'style_profile': {'render_style': 'photoreal'}, 'conditioning': {}},
                extra_negative=NEGATIVE,
                skip_qa=True,
                prompt_finalized=True,
                solo_subject=False,
                human_subject=False,
                qwen_max_mp=2.2,
                clear_vram_after=False,
                log_fn=lambda m: _log(log, str(m)[:200]),
            )
            if not ok or not os.path.isfile(dest):
                _log(log, f'seed {seed}: render failed ({backend})')
                tried.append(
                    {
                        'seed': seed,
                        'ocr_full': None,
                        'ocr_crop': None,
                        'vlm_quote': None,
                        'exact': False,
                        'conf': 0.0,
                        'rendered': True,
                    }
                )
                continue
            comp = os.path.join(work, f'comp_{k}.png')
            _paste_letters(src_png, dest, comp)
            if _consider(seed, comp, True):
                break

    pick = best_exact or best_close
    if pick is None:
        raise RuntimeError('every seed failed to render — see the log')
    matched = (
        pick.get('vlm_quote')
        if pick.get('by') == 'vlm'
        else pick.get('ocr_crop')
        if pick.get('by') == 'ocr_crop'
        else pick.get('ocr_full')
    )
    reused = not pick['rendered']
    if os.path.abspath(pick['path']) != os.path.abspath(out_png):
        Image.open(pick['path']).convert('RGB').save(out_png)
    receipt = {
        'exact': best_exact is not None,
        'ocr_text': matched,
        'ocr_full': pick.get('ocr_full'),
        'ocr_crop': pick.get('ocr_crop'),
        'vlm_quote': pick.get('vlm_quote'),
        'read_by': pick.get('by'),
        'seed': pick['seed'],
        'reused': reused,
        'tried': tried,
        'out': os.path.abspath(out_png),
    }
    _log(log, f'picked seed {pick["seed"]} — exact={receipt["exact"]} ({matched!r} by {pick.get("by")}) → {out_png}')
    return receipt
