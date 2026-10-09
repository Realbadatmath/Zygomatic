# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Angle classification and the Qwen edit-instruction vocabulary.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 428-470, 2424-2944).
"""

from __future__ import annotations

import os

from zyg_workflows.contact_sheet_pipeline.constants import _zyg_log


# ── Corpus expression axis (2026-08-09) ──────────────────────────────────────
# The angle-label STRING is the entire cell-spec API: every phrase here must
# stay recognizable to _qwen_angle_instruction (which appends the matching
# instruction clause) and must NEVER contain a token another classifier claims
# (close-up/fill frame → crop path, warm/cool/rim/golden/dramatic → relight,
# full body/t-pose → body sizing). Keys are the label tokens; values are the
# Qwen edit instruction clauses.
EXPRESSIONS: dict[str, str] = {
    'gentle smile': 'a gentle, soft closed-mouth smile',
    'broad laugh': 'a broad open-mouthed laugh with visible teeth',
    'serious expression': 'a serious, composed expression',
    'surprised expression': 'a surprised expression with raised eyebrows and slightly open mouth',
    'eyes closed calm': 'a calm relaxed face with both eyes gently closed',
    'thoughtful expression': 'a thoughtful, pensive expression',
    'slight frown': 'a slight displeased frown',
    'confident smirk': 'a confident one-sided smirk',
    'curious expression': 'a curious, attentive expression with slightly raised eyebrows',
    'speaking expression': 'a natural mid-speech expression, mouth slightly open as if talking',
    'concerned expression': 'a concerned, worried expression',
    'playful grin': 'a playful, mischievous grin',
}

# Derived-axis phrases the corpus plan appends to a source view. Lighting
# phrases must hit _RELIGHT_KINDS substrings; close-up phrases must hit
# _CLOSEUP_ZOOM_KEYS. Longest-first so the caption splitter strips greedily.
_CORPUS_LIGHTING_PHRASES: tuple[str, ...] = (
    'warm golden hour lighting on face',
    'dramatic rim light on face and hair',
    'cool neutral lighting',
)
_CORPUS_CLOSEUP_PHRASES: tuple[str, ...] = (
    'close-up face fill frame, extreme close skin detail',
    'close-up face, sharp facial detail',
)


def _expression_in_label(angle: str) -> str | None:
    a = (angle or '').lower()
    for key in EXPRESSIONS:
        if key in a:
            return key
    return None


_STEEP_ANGLE_KEYS = (
    'high angle',
    'low angle',
    'overhead',
    'top-down',
    'crown',
    'worm eye',
    'below eye level',
    'below chin',
    'from above',
    'from behind',
    'back view',
    'back of head',
    'back of the head',
    'back three-quarter',
    # Extreme close-ups added 2026-07-20: tile 12 on run 0cc9541b carried
    # severe scar-like mottling across the midface with a STRONG identity
    # score — magnified skin is where mottling lives, and the local VLM
    # misses it. Close-ups get cloud eyes like steep angles do.
    'close-up',
    'close up',
    'fill frame',
    'extreme close',
)


def _is_steep_or_back_angle(angle: str) -> bool:
    """Angle classes where Qwen re-synthesizes the whole head (2026-07-19):
    steep pitch, crown and back views — the classes that produced soft,
    smear-patched faces on run 0cc9541b (Iris Weber). Drives: forced cloud
    VLM review, FaceDetailer skip, and the even-illumination clause."""
    a = (angle or '').lower()
    return any(k in a for k in _STEEP_ANGLE_KEYS)


# Close-up ZOOM angles (2026-07-21): a close-up asks Qwen-Image-Edit to zoom
# IN on the anchor — a scale change that breaks the reference↔target spatial
# correspondence, so the model copies the whole composition at the wrong scale
# and stamps a shrunk translucent double-exposure of the person onto the skin
# (Bianca Lindqvist run 682dbf49 tile 11: a full-figure "reflection" on the
# cheek). Fix: produce these by CROPPING an existing render (no scale change
# through the edit model) instead of a Qwen zoom. Relight-only angles (rim
# light, golden hour) are NOT here — they change lighting, not scale.
_CLOSEUP_ZOOM_KEYS = ('close-up', 'close up', 'fill frame', 'extreme close')


def _is_closeup_zoom_angle(angle: str) -> bool:
    a = (angle or '').lower()
    if _is_full_body_angle(a):
        return False
    return any(k in a for k in _CLOSEUP_ZOOM_KEYS)


def _angle_rotation_deg(angle: str) -> int | None:
    """Signed camera yaw parsed from an angle label (left negative, right
    positive; front/straight-on = 0). None when unparseable."""
    a = (angle or '').lower()
    import re as _re

    m = _re.search(r'(\d+)\s*degree', a)
    if m:
        deg = int(m.group(1))
        return -deg if 'left' in a else (deg if 'right' in a else 0)
    if 'straight on' in a or 'front' in a:
        return 0
    return None


def _closeup_source_cell(angle, anchor_cell, done_paths, done_angles):
    """Best already-rendered cell to crop a close-up FROM: same camera rotation,
    not itself a close-up/full-body/back/steep view. Falls back to the frontal
    anchor (a frontal crop for a rotated close-up is kept by the mislabeled-angle
    handler with a neutral caption). (2026-07-21)"""
    want = _angle_rotation_deg(angle)
    best = None
    for p, a in zip(done_paths or [], done_angles or []):
        al = (a or '').lower()
        if (
            any(k in al for k in _CLOSEUP_ZOOM_KEYS)
            or _is_full_body_angle(a)
            or _is_steep_or_back_angle(a)
            or _is_relight_angle(a)  # never crop FROM an already-graded relight cell
        ):
            continue
        if want is not None and _angle_rotation_deg(a) != want:
            continue
        if not (p and os.path.isfile(p)):
            continue
        best = p
        if any(k in al for k in ('three-quarter', 'medium', 'chest', 'head and shoulder')):
            break  # a roomier framing crops to a cleaner close-up
    return best or anchor_cell


def _closeup_crop_from(source_path, cell_w, cell_h, out_path, *, tight=False, lighting=None, log_fn=None):
    """Produce a close-up by cropping the head region of an existing render and
    Lanczos-upscaling to the cell size — NO scale change through the edit model,
    so no double-exposure ghost (2026-07-21). Detects the face to centre the
    crop; falls back to an upper-centre crop. ``lighting`` (warm|cool|rim)
    applies a deterministic grade for relight tiles. Returns True on success."""
    try:
        from PIL import Image as _PILImg

        img = _PILImg.open(source_path).convert('RGB')
        W, H = img.size
        if W < 64 or H < 64:
            return False
        aspect = cell_w / float(cell_h)
        bbox = None
        try:
            from zyg_workflows import identity_qc_service as _idqc_cc

            _emb = _idqc_cc.embed_images([source_path], log_fn=None)
            bbox = (_emb.get(source_path) or {}).get('bbox')
        except Exception:
            bbox = None
        # face-height multiple for the crop: tighter for fill-frame/extreme.
        _mult = 1.55 if tight else 1.95
        if bbox and len(bbox) == 4:
            x0, y0, x1, y1 = (float(v) for v in bbox)
            fw, fh = x1 - x0, y1 - y0
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            crop_h = fh * _mult
            crop_w = crop_h * aspect
            if crop_w < fw * 1.15:  # never crop tighter than the face
                crop_w = fw * 1.15
                crop_h = crop_w / aspect
            cy = cy + fh * 0.12  # a little headroom for hair
        else:
            crop_h = H * (0.50 if tight else 0.62)
            crop_w = crop_h * aspect
            cx, cy = W / 2.0, H * 0.42
        # fit within the image, preserving the target aspect
        if crop_w > W:
            crop_w, crop_h = W, W / aspect
        if crop_h > H:
            crop_h, crop_w = H, H * aspect
        left = int(max(0, min(W - crop_w, cx - crop_w / 2.0)))
        top = int(max(0, min(H - crop_h, cy - crop_h / 2.0)))
        crop = img.crop((left, top, left + int(crop_w), top + int(crop_h)))
        _upscaling = (int(cell_w) * int(cell_h)) > (crop.width * crop.height)
        crop = crop.resize((int(cell_w), int(cell_h)), _PILImg.LANCZOS)
        # Light unsharp mask ONLY when we upscaled — the Lanczos enlargement of
        # the anchor face (~1.8x on a tight close-up) softens micro-detail;
        # a gentle unsharp restores crispness with no re-synthesis (2026-07-21).
        # Deliberately mild (no halos); env ZYG_CLOSEUP_SHARPEN=0 disables.
        if _upscaling and os.environ.get('ZYG_CLOSEUP_SHARPEN', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
            try:
                from PIL import ImageFilter as _ImageFilter

                crop = crop.filter(_ImageFilter.UnsharpMask(radius=1.6, percent=65, threshold=3))
            except Exception as _exc:
                _zyg_log.debug('close-up unsharp mask skipped: %s', _exc)
        if lighting:
            crop = _apply_lighting_grade(crop, lighting)
        crop.save(out_path)
        return True
    except Exception as exc:
        if log_fn:
            log_fn(f'Close-up crop failed ({exc})')
        return False


_RELIGHT_KINDS = {
    'golden hour': 'warm',
    'warm golden': 'warm',
    'golden': 'warm',
    'cool neutral': 'cool',
    'cool': 'cool',
    'rim light': 'rim',
    'dramatic': 'rim',
}


def _lighting_grade_kind(angle: str) -> str | None:
    """Map a relight angle to a grade kind — 'warm' | 'cool' | 'rim' — or None.
    'neutral lighting' alone maps to nothing (a plain crop is already neutral)."""
    a = (angle or '').lower()
    for key, kind in _RELIGHT_KINDS.items():
        if key in a:
            return kind
    return None


def _is_relight_angle(angle: str) -> bool:
    """A lighting-variation angle (warm/cool/rim) that Qwen produces by
    RE-LIGHTING the face — re-synthesis that leaves a ghost double-exposure
    (Bianca tile 23). Generated by crop + a deterministic lighting grade
    instead: real lighting variety, perfect identity, no ghost (2026-07-21)."""
    if _is_full_body_angle(angle):
        return False
    return _lighting_grade_kind(angle) is not None


def _apply_lighting_grade(pil_img, kind: str):
    """Deterministic, realistic lighting grade on a cropped face (2026-07-21).
    'warm' / 'cool' are white-balance shifts (exactly what a photographer's
    colour temperature does); 'rim' is a soft directional key-light gradient
    (a believable soft edge light, NOT a hard fake rim). No re-synthesis."""
    try:
        import numpy as _np
        from PIL import Image as _PILImg

        a = _np.asarray(pil_img.convert('RGB'), dtype=_np.float32)
        h, w, _ = a.shape
        if kind == 'warm':
            a[..., 0] *= 1.09
            a[..., 1] *= 1.01
            a[..., 2] *= 0.87
            _grad = _np.linspace(1.05, 0.99, h, dtype=_np.float32)[:, None, None]
            a *= _grad
        elif kind == 'cool':
            a[..., 0] *= 0.92
            a[..., 1] *= 0.99
            a[..., 2] *= 1.09
        elif kind == 'rim':
            # soft key from upper-right: brighten that corner ~18%, gentle
            # global contrast; subtle enough to read as real soft lighting.
            _xx = _np.linspace(0.0, 1.0, w, dtype=_np.float32)[None, :, None]
            _yy = _np.linspace(1.0, 0.0, h, dtype=_np.float32)[:, None, None]
            _edge = _xx * 0.6 + _yy * 0.4
            a = a * 0.94 + a * _edge * 0.18
            a = (a - 128.0) * 1.06 + 128.0
        return _PILImg.fromarray(_np.clip(a, 0, 255).astype('uint8'))
    except Exception:
        return pil_img


def _strip_detailer_for_steep(gen_kwargs: dict, angle: str) -> None:
    """Disable the FaceDetailer second pass for steep/back cells — the
    detailer's redraw softens tilted faces (Impact-Pack guidance: blurred
    output wants lower denoise), and Qwen already re-synthesized the face."""
    if not _is_steep_or_back_angle(angle):
        return
    import copy as _c

    pkg = gen_kwargs.get('character_package')
    if isinstance(pkg, dict):
        pkg2 = _c.deepcopy(pkg)
        pkg2.setdefault('conditioning', {})['face_detail_pass'] = False
        gen_kwargs['character_package'] = pkg2


def _qwen_angle_instruction(angle: str, params: dict | None = None) -> str | None:
    """Map an angle label to a Qwen-Image-Edit camera instruction, or None when
    the cell is frontal/expression/lighting work (PuLID territory).

    Edit-model rotation is the 2026-verified approach for yaw/pitch/back cells:
    identity comes from editing the anchor rather than re-generating, so it
    cannot drift the way adapter-conditioned txt2img does.
    """
    import re as _re

    a = (angle or '').lower()
    # Expression variants (corpus, 2026-08-09): strip the expression phrase so
    # the camera-cue detection below sees the plain view label ('gentle smile'
    # must not hijack the legacy 'smile' branch), then append the expression
    # clause to whatever base the view resolves to. Expression labels always
    # stay on the qwen_edit generate path — never the PuLID/IPA fallback.
    _expr = _expression_in_label(a)
    if _expr:
        a = a.replace(_expr, ' ')
    base: str | None = None
    if any(
        k in a
        for k in (
            'from directly behind',
            'straight behind',
            'from behind',
            'back view',
            'back of head',
            'back of the head',
        )
    ):
        base = (
            'Rotate the camera a full 180 degrees to show the person directly '
            'from behind — only the back of the head, the hair and the back are '
            'visible, no face at all'
        )
    else:
        m = _re.search(r'rotated (\d+) degrees (left|right)', a)
        if m:
            _deg = int(m.group(1))
            _side = m.group(2)
            # Distinguish side profile (~90°) from BACK three-quarter (>=110°):
            # the old code called both "true side profile", so 120° cells were
            # mislabelled and the QC gate flagged them (2026-07-12). Spell out the
            # actual pose so Qwen turns the head correctly, not just the shoulders.
            if _deg >= 110:
                base = (
                    f'Turn the person {_deg} degrees away to the {_side} into a '
                    f'back three-quarter view, so mostly the back and side of the '
                    f'head are visible with only a sliver of the far cheek'
                )
            elif _deg >= 80:
                base = (
                    f'Turn the person a full {_deg} degrees to the {_side} into a '
                    f'true side profile, so the face points toward the {_side} edge '
                    f'of the frame and only one side of the face is visible'
                )
            else:
                base = f'Rotate the camera {_deg} degrees to the {_side}'
        elif 'directly overhead' in a or 'top-down' in a:
            # "Rotate the camera to a top-down view" reliably produced a face on
            # the crown (cell_42 failed identically on two consecutive runs,
            # 2026-07-16). Spell out the no-face constraint like the working
            # from-behind instruction does.
            base = (
                'Move the camera directly above the person, photographing '
                'straight down onto the top of the head — only the hair crown, '
                'the parting and the shoulders are visible from above, the face '
                'is not visible at all'
            )
        elif 'high angle' in a or 'low angle' in a or 'worm eye' in a or 'below eye level' in a or 'below chin' in a:
            # Preserve the HORIZONTAL component: "high angle 3/4 left" must not
            # collapse to the same string as "high angle front" (2026-07-12: cells
            # 31/32/33 and 34/35/36 submitted byte-identical prompts, destroying
            # angular coverage and filling the dataset with near-duplicates).
            # "Tilt the camera to a high angle looking down" made qwen tilt the
            # FRAME — cell_30 came out fully upside-down on two consecutive runs
            # (roll ±179°, 2026-07-16). Say where the camera MOVES and pin the
            # subject upright instead of using "tilt".
            _vert = (
                'Move the camera higher, above eye level, looking down at the person from above'
                if 'high angle' in a
                else 'Move the camera lower, below eye level, looking up at the person from below'
            )
            _horiz = ''
            _mh = _re.search(r'(three-quarter|3/4|3⁄4)\s*(left|right)', a)
            if _mh:
                _horiz = f', rotated to a three-quarter {_mh.group(2)} view'
            elif 'left' in a:
                _horiz = ', rotated slightly to the left'
            elif 'right' in a:
                _horiz = ', rotated slightly to the right'
            base = f'{_vert}{_horiz}. The person stays upright and vertical in the frame with the head at the top'
    # Frontal expression / lighting / framing variants — route these through
    # Qwen too (edit the photographic anchor) instead of PuLID, which
    # reconstructs an idealized 3D-render/anime face from an ID embedding. The
    # anchor's real skin texture is preserved by editing rather than regenerating.
    if base is None and not _is_full_body_angle(a):
        if 'slightly above' in a or 'upward angle' in a:
            base = 'Tilt the camera slightly above eye level, looking a little down at the face'
        elif 'slightly below' in a or 'downward angle' in a:
            base = 'Tilt the camera slightly below eye level, looking a little up at the face'
        elif 'smile' in a:
            base = 'Keep the camera straight on and give the person a natural, genuine smile'
        elif 'close-up' in a or 'close up' in a or 'fill frame' in a:
            base = 'Keep the camera straight on and zoom in to a tight head-and-shoulders close-up of the face'
        elif 'golden hour' in a or 'warm' in a:
            base = 'Keep the camera straight on and relight the scene with warm golden-hour light on the face'
        elif 'cool' in a or 'neutral lighting' in a:
            base = 'Keep the camera straight on with cool, even neutral studio lighting'
        elif 'rim light' in a or 'dramatic' in a:
            base = 'Keep the camera straight on and add a soft dramatic rim light on the face and hair'
        elif 'chest up' in a or 'medium shot' in a:
            base = 'Keep the camera straight on and frame a medium shot from the chest up'
        elif 'front' in a or 'straight on' in a:
            base = 'Keep the camera facing the person straight on with a natural neutral expression'
    if base is None:
        if _is_full_body_angle(a):
            # Frontal full-body: still a Qwen edit (zoom-out, no rotation).
            # FLUX txt2img renders "T-pose" as 3D-doll reference art; editing
            # the photographic anchor cannot change medium or undress it.
            base = 'Keep the camera facing the person straight on'
        elif _expr:
            # A bare expression label with no other camera cue is frontal work
            # — still a Qwen edit of the anchor, never the fallback.
            base = 'Keep the camera facing the person straight on'
        else:
            return None
    if _expr:
        # The neutral-expression tail of the frontal default would contradict
        # the requested expression — drop it before appending the clause.
        _neutral_tail = ' with a natural neutral expression'
        if base.endswith(_neutral_tail):
            base = base[: -len(_neutral_tail)]
        base += f', same person, identical facial features, {EXPRESSIONS[_expr]}'
    if 't-pose' in a:
        base += (
            ', zoom out to a wide shot showing the entire body from head to feet, '
            'standing in a T-pose with both arms stretched straight out to the '
            'sides and fully visible inside the frame with clear margin around the figure'
        )
    elif _is_full_body_angle(a):
        base += (
            ', zoom out to a wide shot showing the entire body from head to feet '
            'with the whole figure inside the frame and margin on all sides'
        )
    # Even-illumination clause for pitch/overhead views (2026-07-19): steep
    # re-projection under a hard directional key smeared facial shadows into
    # bruise-like patches on run 0cc9541b — ask for flat facial light and
    # sharp detail on exactly these cells (back views excluded — no face).
    if any(
        k in a
        for k in (
            'high angle',
            'low angle',
            'overhead',
            'top-down',
            'worm eye',
            'below eye level',
            'below chin',
            'slightly above',
            'slightly below',
        )
    ):
        base += (
            ', with even soft illumination across the face, no harsh shadows or '
            'dark patches on the skin, keeping facial detail crisp and sharp'
        )
    # Build style-aware suffix from params so animated/painterly characters don't
    # get photorealism instructions, and so character-bible clothing is honoured.
    _p = params or {}
    _render_style = (_p.get('render_style') or _p.get('style') or 'photorealistic').strip().lower()
    _clothing = (_p.get('default_clothing') or '').strip()

    # Footwear/trouser boilerplate only where the lower body is in frame:
    # on head/close-up cells it pulled Qwen toward full-length framing (the
    # 2026-07-09 audit found the two "close-up, pores/freckles" cells rendered
    # as full-body shots with tiny airbrushed faces because of this clause).
    _lower_body_visible = _is_full_body_angle(a) or 'medium shot' in a or 'chest up' in a or 'upper body' in a
    if not _lower_body_visible:
        if _clothing:
            _clothing_clause = f'Keep the identical clothing — the exact same {_clothing}'
        else:
            _clothing_clause = 'Keep the identical clothing — the exact same top'
    elif _clothing:
        _clothing_clause = (
            f'Keep the identical clothing — the exact same {_clothing}, '
            f'and the exact same footwear as in the reference image '
            f'(do not change the shoes, boots or sandals — copy them exactly)'
        )
    else:
        _clothing_clause = (
            'Keep the identical clothing — the exact same top, the same '
            'full-length trousers (never shorts, never a skirt, never a '
            'jumpsuit), and the exact same footwear as in the reference image '
            '(do not change the shoes, boots or sandals — copy them exactly)'
        )

    if 'animated' in _render_style or 'cartoon' in _render_style:
        _medium_clause = (
            f'Keep the same {_render_style} art style — consistent line art, '
            f'cel-shading and colour palette throughout; do not change to a '
            f'photograph or realistic rendering'
        )
    elif 'painterly' in _render_style or 'illustration' in _render_style or 'comic' in _render_style:
        _medium_clause = (
            f'Maintain the {_render_style} medium — same brushwork, texture and palette; not a photograph or 3D render'
        )
    else:
        _medium_clause = (
            'RAW candid photograph, natural uneven skin with visible pores and '
            'fine texture, subtle film grain, unretouched — not airbrushed, not '
            'a 3D render, not an illustration'
        )

    return (
        f'{base}, while keeping the exact same person with an identical face, '
        f'identical skin tone and complexion (do not lighten or change the skin '
        f'colour), identical skin texture — do not add, exaggerate or '
        f'redistribute freckles, spots or blemishes — hairstyle and body. '
        f'{_clothing_clause} — against the same '
        f'plain studio background. {_medium_clause}'
    )


def _framing_clause(angle: str) -> str:
    """Framing emphasis so a 'head and shoulders' label doesn't render as a wide
    3/4-body shot — which also wastes the 1024px cell's pixels on background
    instead of skin. Full-body / medium / chest-up angles keep their framing.
    """
    a = (angle or '').lower()
    if _is_full_body_angle(a) or 'medium shot' in a or 'chest up' in a or 'wide' in a or 'upper body' in a:
        return ''
    if 'head and shoulders' in a or 'head-and-shoulders' in a or 'portrait' in a or 'close-up' in a or 'close up' in a:
        return (
            ', tightly framed head-and-shoulders close-up portrait, face fills the '
            'upper half of the frame, sharp facial detail'
        )
    return ''


_FULL_BODY_MARKERS = ('full body', 'whole figure', 'head to feet', 't-pose')


def _is_full_body_angle(angle: str) -> bool:
    a = (angle or '').lower()
    return any(k in a for k in _FULL_BODY_MARKERS)


def _cell_size_for_angle(angle: str) -> tuple[int, int]:
    """Per-angle generation size — SimpleTuner aspect-buckets mixed sizes.

    T-pose cells are SQUARE: outstretched arms need horizontal room (the
    640×960 portrait frame amputated them). Other full-body cells get a wider
    3:4-ish portrait so the figure keeps margin on both sides.
    """
    a = (angle or '').lower()
    if 't-pose' in a:
        return (
            int(os.environ.get('ZYG_CONTACT_SHEET_TPOSE_CELL_W', '1024')),
            int(os.environ.get('ZYG_CONTACT_SHEET_TPOSE_CELL_H', '1024')),
        )
    if _is_full_body_angle(angle):
        return (
            int(os.environ.get('ZYG_CONTACT_SHEET_BODY_CELL_W', '832')),
            int(os.environ.get('ZYG_CONTACT_SHEET_BODY_CELL_H', '1216')),
        )
    # Head/standard cells at ~1.2MP: pores are sub-pixel at 640×720 (face
    # ≈300×400px there) — no prompt can request detail the pixel grid can't
    # hold. Costs ~2× generation time; texture fidelity is what LoRA training
    # immortalizes.
    return (
        int(os.environ.get('ZYG_CONTACT_SHEET_HEAD_CELL_W', '1024')),
        int(os.environ.get('ZYG_CONTACT_SHEET_HEAD_CELL_H', '1152')),
    )
