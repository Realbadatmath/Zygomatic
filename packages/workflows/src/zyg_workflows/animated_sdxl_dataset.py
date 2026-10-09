# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build an ANIMATED (3D-toon) SDXL training dataset from a character's
photoreal contact-sheet training images (2026-07-25).

SDXL is the animated path (FLUX stays photoreal). To train an animated SDXL
LoRA that renders on-model, we need animated training images of the SAME
identity — produced by img2img-ing each photoreal training tile through the
3D-toon SDXL checkpoint (DynaVision XL) at a denoise that restyles to toon
while preserving pose + identity (validated at denoise 0.55). Captions are
re-styled: photoreal texture terms stripped, a 3D-toon clause appended, the
trigger token + pose/expression kept.

Reused by both the manual Runa twin build and the forward dual-LoRA SDXL leg.
"""

from __future__ import annotations

import os
import re
from typing import Callable
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_ANIM_CKPT = os.environ.get('ZYG_SDXL_ANIMATED_CKPT', 'DynaVisionXL.safetensors')
# 0.55 (was 0.65): higher denoise let DynaVision's light-skin/straight-hair
# prior override identity on close-up tiles (skin lightened, box braids became
# straight hair). Lower denoise + explicit identity tokens keep the character.
_ANIM_DENOISE = float(os.environ.get('ZYG_ANIM_DATASET_DENOISE', '0.55'))
_ANIM_CFG = float(os.environ.get('ZYG_ANIM_DATASET_CFG', '6.5'))
_ANIM_STEPS = int(os.environ.get('ZYG_ANIM_DATASET_STEPS', '30'))
_ANIM_STYLE = os.environ.get(
    'ZYG_ANIM_STYLE_CLAUSE',
    '3D Pixar animation style, stylized 3d animated character, Disney Pixar 3d render, '
    'cel-shaded, smooth subsurface shading, natural proportional eyes, '
    'realistic eye size, clean high quality 3d character render',
)
# Style/quality-only negatives (character-agnostic). Identity-contradicting
# terms (skin/hair) are derived PER CHARACTER from the bible in
# _identity_negatives — a hardcoded 'anti-light-skin/anti-blonde/anti-straight-
# hair' tail would corrupt a fair-skinned or blonde character (review finding).
_ANIM_NEG = os.environ.get(
    'ZYG_ANIM_DATASET_NEG',
    'photorealistic, photograph, realistic, dslr, raw photo, film grain, visible skin pores, '
    'skin texture, hyperreal, blurry, low quality, deformed face, bad anatomy, extra fingers, '
    'watermark, text, '
    # keep eyes proportional (DynaVision defaults to oversized Pixar eyes)
    'oversized eyes, huge eyes, big anime eyes, bug eyes, enlarged eyes, disproportionate eyes',
)


def _identity_negatives(char_id: str) -> str:
    """Per-character identity guard: negate the tones/hair colours that
    CONTRADICT the bible (reuses the same symmetric defences the FLUX prompt
    builder uses), so DynaVision's light-skin / straight-hair prior can't
    override the character — without hardcoding any one character's look."""
    try:
        from zyg_workflows import character_bible_service as _cbs

        ident = (_cbs.load(char_id) or {}).get('identity') or {}
        bits = []
        try:
            _sn = _cbs.skin_tone_negatives(ident.get('skin_tone', ''), ident.get('ethnic_heritage'))
            if _sn:
                bits.append(_sn)
        except Exception as _exc:
            _zyg_log.debug('skin tone negatives unavailable: %s', _exc)
        try:
            _hn = _cbs.hair_color_negatives(ident.get('hair_color', ''), ident.get('ethnic_heritage'))
            if _hn:
                bits.append(_hn)
        except Exception as _exc:
            _zyg_log.debug('hair colour negatives unavailable: %s', _exc)
        # coily/curly/braided hair drifts to 'straight' under the toon prior
        _tex = (ident.get('hair_texture') or '').lower()
        _sty = (ident.get('hair_style') or '').lower()
        if any(t in (_tex + ' ' + _sty) for t in ('coil', 'curl', 'braid', 'afro', 'kinky')):
            bits.append('straight hair, sleek hair')
        return ', '.join(b for b in bits if b)
    except Exception:
        return ''


def _identity_clause(char_id: str) -> str:
    """Load the character's load-bearing visual attributes from the bible so
    every restyled tile re-asserts identity (skin tone + hair keep DynaVision
    from drifting to its light-skin / straight-hair default)."""
    try:
        from zyg_workflows import character_bible_service as _cbs

        ident = (_cbs.load(char_id) or {}).get('identity') or {}
    except Exception:
        ident = {}
    bits: list[str] = []
    age = ident.get('age')
    gender = ident.get('gender') or 'person'
    if age:
        bits.append(f'{age} year old {gender}')
    else:
        bits.append(gender)
    skin = (ident.get('skin_tone') or '').strip()
    if skin:
        bits.append(f'{skin} brown skin' if skin in ('medium', 'tan', 'olive') else f'{skin} skin')
    hair = ' '.join(
        x
        for x in (ident.get('hair_length'), ident.get('hair_texture'), ident.get('hair_color'), ident.get('hair_style'))
        if x
    )
    if hair:
        bits.append(f'{hair} hair')
    if ident.get('eye_color'):
        bits.append(f'{ident["eye_color"]} eyes')
    return ', '.join(bits)


# photoreal caption terms to drop so the LoRA learns TOON, not photo
_STRIP_TERMS = re.compile(
    r'\b(photorealistic|photo realistic|film photography|photograph|dslr|raw photo|'
    r'natural skin texture|visible pores|visible skin pores|unretouched|fine film grain|'
    r'film grain|hyperreal(?:istic)?|skin microdetail|85mm[^,]*|f/\d[^,]*)\b',
    re.IGNORECASE,
)


def _toon_caption(photoreal_caption: str, identity_clause: str = '') -> str:
    txt = _STRIP_TERMS.sub('', photoreal_caption or '')
    txt = re.sub(r',\s*,+', ', ', txt)
    txt = re.sub(r'\s{2,}', ' ', txt).strip(' ,\n')
    # Insert identity right after the trigger-token segment so the trigger
    # stays FIRST (trigger→identity binding). Find the segment that CONTAINS
    # the trigger, not just parts[0] (some captions read 'photograph of
    # ZYG_CHAR_X person, …' → the trigger isn't the first comma-segment).
    if identity_clause:
        parts = [p.strip() for p in txt.split(',') if p.strip()]
        _ti = next((i for i, p in enumerate(parts) if 'ZYG_CHAR' in p), -1)
        if _ti >= 0:
            txt = ', '.join(parts[: _ti + 1] + [identity_clause] + parts[_ti + 1 :])
        else:
            txt = f'{identity_clause}, {txt}' if txt else identity_clause
    return f'{txt}, {_ANIM_STYLE}' if txt else _ANIM_STYLE


def _tile_identity_ok(tile_path: str, skin: str, hair: str, log_fn: Callable[[str], None] | None = None) -> bool:
    """Best-effort per-tile identity screen via the local VLM (ArcFace can't
    read toon faces). Rejects a restyled tile only on a CONFIDENT mismatch of
    skin tone or hair — DynaVision's light-skin/straight-hair drift is the
    failure mode. Returns True on any uncertainty or if the VLM is unavailable
    (never block the dataset on an inference hiccup)."""
    if os.environ.get('ZYG_ANIM_TILE_SCREEN', '1').strip().lower() in ('0', 'false', 'no'):
        return True
    if not (skin or hair):
        return True
    try:
        import base64 as _b64
        import json as _json

        with open(tile_path, 'rb') as fh:
            img = _b64.b64encode(fh.read()).decode()
        want = []
        if skin:
            want.append(f'{skin} skin')
        if hair:
            want.append(hair)
        prompt = (
            f'This is a 3D animated character. Expected: a person with {" and ".join(want)}. '
            'Reply STRICT JSON: {"skin_matches":true/false,"hair_matches":true/false,'
            '"confident":true/false}. skin_matches=false only if the skin tone is clearly '
            'different (e.g. expected brown but shown pale/white). hair_matches=false only if '
            'hair type is clearly wrong (e.g. expected braids but shown straight loose hair).'
        )
        from zyg_workflows import llm_audit as _la_an

        _resp_an = _la_an.ollama_post(
            f'{os.environ.get("ZYG_OLLAMA_HOST", paths.ZYG_OLLAMA_URL).rstrip("/")}/api/generate',
            {
                'model': (_m := os.environ.get('ZYG_HAND_VLM_MODEL', 'qwen3.5:9b')),
                'prompt': prompt,
                'images': [img],
                'stream': False,
                **({'think': False} if _m.startswith('qwen3') else {}),
                'keep_alive': '5m',
                'options': {'temperature': 0.0, 'num_predict': 120},
            },
            timeout=float(os.environ.get('ZYG_ANIM_TILE_TIMEOUT', '60')),
            stage='anim_dataset/tile',
        )
        import re as _re

        m = _re.search(r'\{.*\}', _resp_an.get('response') or '', _re.DOTALL)
        v = _json.loads(m.group(0)) if m else {}
        if v.get('confident') and (v.get('skin_matches') is False or v.get('hair_matches') is False):
            if log_fn:
                log_fn(
                    f'[anim-dataset] tile dropped — identity mismatch '
                    f'(skin_ok={v.get("skin_matches")} hair_ok={v.get("hair_matches")})'
                )
            return False
        return True
    except Exception:
        return True


def identity_check_frames(char_id: str, img_paths, log_fn=None) -> list:
    """Ship-time animated identity gate (VLM, since ArcFace can't embed toon
    faces). Returns [(scene_index, reason), ...] for frames whose skin tone or
    hair CONFIDENTLY mismatches the bible. Empty on unavailability (never a
    false fail). scene_index is 1-based to match the storyteller's registries."""
    try:
        from zyg_workflows import character_bible_service as _cbs

        ident = (_cbs.load(char_id) or {}).get('identity') or {}
    except Exception:
        ident = {}
    skin = (
        f'{ident.get("skin_tone")} brown'
        if ident.get('skin_tone') in ('medium', 'tan', 'olive')
        else (ident.get('skin_tone') or '')
    )
    hair = ' '.join(x for x in (ident.get('hair_texture'), ident.get('hair_style')) if x)
    if not (skin or hair):
        return []
    out = []
    for i, p in enumerate(img_paths):
        try:
            if p and os.path.isfile(p) and not _tile_identity_ok(p, skin, hair, None):
                out.append((i + 1, 'animated identity mismatch (skin/hair)'))
        except Exception as _exc:
            _zyg_log.warning('identity screen failed for frame %s, not flagged: %s', i + 1, _exc)
            continue
    if out and log_fn:
        log_fn(f'[anim-identity] {len(out)}/{len(img_paths)} frames mismatch skin/hair')
    return out


def build_animated_sdxl_dataset(
    char_id: str,
    photoreal_dir: str,
    *,
    out_dir: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    comfy_host: str = paths.ZYG_COMFY_URL,
    seed: int = 7788,
    force: bool = False,
) -> str:
    """img2img every <photoreal_dir>/*.png (with matching .txt) through the
    animated checkpoint. Returns the animated dataset dir (…/training_sdxl_animated).
    """

    def _log(m: str) -> None:
        (log_fn or print)(m)

    from zyg_workflows import _comfy_client as _comfy

    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(photoreal_dir.rstrip('/')), 'training_sdxl_animated')
    os.makedirs(out_dir, exist_ok=True)

    pngs = sorted(
        f
        for f in os.listdir(photoreal_dir)
        if f.lower().endswith('.png') and os.path.isfile(os.path.join(photoreal_dir, os.path.splitext(f)[0] + '.txt'))
    )
    if not pngs:
        raise RuntimeError(f'no captioned .png training images under {photoreal_dir}')

    ckpt_dir = os.path.join(str(paths.ZYG_COMFY_ROOT), 'models', 'checkpoints')
    if not os.path.isfile(os.path.join(ckpt_dir, _ANIM_CKPT)):
        raise RuntimeError(f'animated checkpoint missing: {os.path.join(ckpt_dir, _ANIM_CKPT)}')

    base_wf = _comfy.load_workflow('sdxl_img2img')
    _ident = _identity_clause(char_id)
    _id_neg = _identity_negatives(char_id)
    _neg = f'{_ANIM_NEG}, {_id_neg}' if _id_neg else _ANIM_NEG
    # attributes the per-tile screen guards (skin lightening, braids→straight)
    try:
        from zyg_workflows import character_bible_service as _cbs_id

        _bi = (_cbs_id.load(char_id) or {}).get('identity') or {}
        _ident_skin = (
            f'{_bi.get("skin_tone")} brown'
            if _bi.get('skin_tone') in ('medium', 'tan', 'olive')
            else (_bi.get('skin_tone') or '')
        )
        _ident_hair = ' '.join(x for x in (_bi.get('hair_texture'), _bi.get('hair_style')) if x)
    except Exception:
        _ident_skin, _ident_hair = '', ''
    _log(
        f'[anim-dataset] {char_id}: restyling {len(pngs)} tiles → 3D-toon '
        f'({_ANIM_CKPT}, denoise {_ANIM_DENOISE}); identity="{_ident}"'
    )
    made = 0
    for i, png in enumerate(pngs):
        stem = os.path.splitext(png)[0]
        out_png = os.path.join(out_dir, png)
        out_txt = os.path.join(out_dir, stem + '.txt')
        cap = ''
        try:
            with open(os.path.join(photoreal_dir, stem + '.txt'), encoding='utf-8') as fh:
                cap = fh.read().strip()
        except OSError as _exc:
            _zyg_log.debug('source caption unreadable for %s: %s', stem, _exc)
        toon_cap = _toon_caption(cap, _ident)
        with open(out_txt, 'w', encoding='utf-8') as fh:
            fh.write(toon_cap)
        if os.path.isfile(out_png) and not force:
            made += 1
            continue
        import copy as _copy

        g = _copy.deepcopy(base_wf)
        src_name = _comfy.stage_input_image(os.path.join(photoreal_dir, png))
        g['10']['inputs']['ckpt_name'] = _ANIM_CKPT
        g['14']['inputs']['image'] = src_name
        g['20']['inputs']['text'] = toon_cap
        g['21']['inputs']['text'] = _neg
        g['31']['inputs'].update({'seed': seed + i, 'denoise': _ANIM_DENOISE, 'cfg': _ANIM_CFG, 'steps': _ANIM_STEPS})
        g['50']['inputs']['filename_prefix'] = f'ZygAnimDS_{char_id[:8]}_{stem}'
        try:
            outs = _comfy.submit(g, timeout_s=300)
        except Exception as exc:
            _log(f'[anim-dataset] tile {png} FAILED: {exc!r}')
            continue
        if outs and os.path.isfile(outs[0]):
            # per-tile identity screen: retry once at lower denoise on a
            # confident mismatch, then drop the tile (do not poison the LoRA).
            _skin = _ident_skin or ''
            _hair = _ident_hair or ''
            if not _tile_identity_ok(outs[0], _skin, _hair, _log):
                g2 = _copy.deepcopy(g)
                g2['31']['inputs']['denoise'] = max(0.42, _ANIM_DENOISE - 0.12)
                g2['31']['inputs']['seed'] = seed + i + 5000
                try:
                    outs2 = _comfy.submit(g2, timeout_s=300)
                except Exception:
                    outs2 = None
                if outs2 and os.path.isfile(outs2[0]) and _tile_identity_ok(outs2[0], _skin, _hair, _log):
                    outs = outs2
                else:
                    try:
                        os.remove(out_txt)
                    except OSError as _exc:
                        _zyg_log.debug('dropped tile caption cleanup skipped: %s', _exc)
                    _log(f'[anim-dataset] tile {png} dropped (identity screen)')
                    continue
            import shutil

            shutil.copy2(outs[0], out_png)
            made += 1
            if (i + 1) % 5 == 0 or i + 1 == len(pngs):
                _log(f'[anim-dataset] {made}/{len(pngs)} tiles done')
    if made < max(4, len(pngs) // 2):
        raise RuntimeError(f'animated dataset too small: {made}/{len(pngs)} tiles produced')
    _log(f'[anim-dataset] {char_id}: {made}/{len(pngs)} animated tiles → {out_dir}')
    return out_dir
