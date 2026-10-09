#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the renders section, verbatim lines 745-1293, 1462-1480 of the original module."""

from __future__ import annotations

import json
import os
import shutil
import time
import numpy as np
import logging as _zyg_logging

from zyg_workflows.char_photoreal.constants import (
    BODIES,
    BODY_VIEWS,
    CFG,
    EYE_VIEWS,
    HAND_VIEWS,
    HEAD_VIEWS,
    PRIORITY,
    REF_OF,
    SIZE,
    STEPS,
    ZOOM_VIEWS,
    look_of,
)
from zyg_workflows.char_photoreal.plates import work_dir

_zyg_log = _zyg_logging.getLogger(__package__)


# ── klein renders ──────────────────────────────────────────────────────────
ECORCHE_LIGHT = (
    'even flat diffuse lighting, no shadows, plain white seamless background, medical textbook anatomy plate'
)
# The muscles a view can actually SEE. The full-figure prompt names the front
# groups; on a back view that same sentence asks for pectorals and a six-pack
# on a back — the exact failure the orientation gate exists to catch — so the
# clause is swapped, not merely negated.
ECORCHE_GROUPS_FRONT = (
    'deltoids, pectorals, rectus abdominis six-pack, external obliques, quadriceps, gastrocnemius clearly defined'
)
ECORCHE_GROUPS_BACK = (
    'trapezius, latissimus dorsi, erector spinae along the spine, deltoids, '
    'gluteus maximus, hamstrings, gastrocnemius clearly defined'
)
ECORCHE_HEAD_FRONT = (
    'facial muscles exposed: frontalis, temporalis, orbicularis oculi around '
    'closed eyes, masseter, zygomaticus, orbicularis oris'
)
ECORCHE_HEAD_BACK = (
    'the occipitalis over the back of the skull, the temporalis at the temples '
    'and the splenius and trapezius of the nape'
)


def _prompts_ecorche(body):
    """The muscular system, not skin. A separate branch rather than a string
    replacement on the photo prompt: every phrase the photo prompt asks for
    (bare skin, pores, freckles, mid-grey backdrop) is wrong here, and the
    close-up prompts in _view_prompt build themselves from these."""
    who = 'adult man' if BODIES[body]['gender'] == 'male' else 'adult woman'
    body_p = (
        f'full-length anatomical écorché illustration of the human muscular system, '
        f'{who} standing in a relaxed A-pose, arms slightly away from the body, all '
        f'skin removed, the superficial muscles exposed, red striated muscle fibres '
        f'with pale cream tendons and white fascia, {ECORCHE_GROUPS_FRONT}, no hair, '
        f'{ECORCHE_LIGHT}, highly detailed, sharp focus everywhere'
    )
    head_p = (
        f"close-up anatomical écorché illustration of the same {who.split()[-1]}'s head, "
        f'skin removed, {ECORCHE_HEAD_FRONT}, red striated fibres, cream tendons, no '
        f'hair, flat diffuse lighting, white background, medical anatomy plate'
    )
    neg = (
        'skin, clothing, bones, skeleton, ribs visible, text, labels, arrows, watermark, '
        'blurry, blue, green, cartoon, multiple people, background objects, shadow'
    )
    return body_p, head_p, neg


def _prompts(body):
    if look_of(body) == 'ecorche':
        return _prompts_ecorche(body)
    g = BODIES[body]['gender']
    who = 'adult man' if g == 'male' else 'adult woman'
    skin = (
        'natural bare skin with visible pores, light freckles across the nose, '
        'cheeks and shoulders, fine skin texture, subtle colour variation'
    )
    light = (
        'even soft diffuse studio lighting from all sides, flat lighting, no harsh '
        'shadows, no specular hotspots, plain mid-grey seamless background'
    )
    body_p = (
        f'full-length photograph of a nude {who} standing in a relaxed A-pose, arms '
        f'slightly away from the body, shaved bald head, no hair, neutral '
        f'expression, {skin}, {light}, 85mm lens, sharp focus everywhere, '
        f'photorealistic, anatomical reference figure'
    )
    head_p = (
        f'close-up portrait photograph of the same {who}, shaved bald head, no hair, '
        f'neutral relaxed expression, natural eyebrows, {skin}, {light}, 85mm lens, '
        f'sharp focus, photorealistic'
    )
    neg = (
        'clothing, underwear, fabric, hair, wig, hat, jewellery, tattoo, text, '
        'watermark, logo, cartoon, illustration, painting, cgi, plastic skin, '
        'waxy skin, blurry, harsh shadow, rim light, coloured light, multiple people'
    )
    return body_p, head_p, neg


def _view_prompt_ecorche(vid, v, body):
    """Same per-view orientation clauses as the photo route, écorché
    vocabulary. Written out rather than string-replaced into the photo prompt:
    the close-ups there are built by swapping 'full-length photograph of a
    nude' out of body_p, and an anatomy plate has no such phrase."""
    body_p, head_p, neg = _prompts_ecorche(body)
    who = 'man' if BODIES[body]['gender'] == 'male' else 'woman'
    kind = vid.split('_')[0]
    az = ((v['az'] + 180) % 360) - 180
    el = v['el']
    a = abs(az)
    side = 'right' if az < 0 else 'left'  # which way he faces IN THE FRAME
    extra_neg = ''
    if kind == 'eye':
        which = 'left' if vid == 'eye_l' else 'right'
        pos = (
            f'écorché close-up of the {which} eye region of the same {who}, the orbicularis '
            f'oculi ring of muscle around a closed eye, no skin, red striated muscle fibres '
            f'with pale cream tendons, the eyebrow ridge and the temporalis at the temple, '
            f'{ECORCHE_LIGHT}, macro lens, sharp focus'
        )
        return pos, neg + ', eyelashes, eyebrow hair, makeup, open eye, glass eye'
    if kind == 'hand':
        which = 'left' if vid == 'hand_l' else 'right'
        pos = (
            f"close-up anatomical écorché illustration of the same {who}'s {which} hand, "
            f'seen from the outside, the back of the hand and the fingers, all skin '
            f'removed, the extensor tendons fanning over the back of the hand to each '
            f'finger, the interosseous muscles between the metacarpals, red striated '
            f'fibres with pale cream tendons, fingers slightly apart, {ECORCHE_LIGHT}, '
            f'85mm lens, sharp focus'
        )
        return pos, neg + ', face, head, extra fingers, missing fingers, fused fingers, deformed hand'
    if kind in ('torso', 'legs'):
        if kind == 'torso':
            part = 'torso, chest and shoulders'
            groups = 'pectoralis major, deltoids, rectus abdominis six-pack, external obliques, serratus anterior'
            behind = 'trapezius, latissimus dorsi and the erector spinae along the spine'
        else:
            part = 'legs, hips and thighs'
            groups = 'gluteus medius, quadriceps, sartorius, adductors, gastrocnemius, tibialis anterior'
            behind = 'gluteus maximus, the hamstrings and the calves'
        if a > 100:
            groups = behind
        base = (
            f'medium shot anatomical écorché illustration of the {part} of a {who}, all '
            f'skin removed, the superficial muscles exposed, {groups}, red striated muscle '
            f'fibres with pale cream tendons and white fascia, {ECORCHE_LIGHT}, highly '
            f'detailed, sharp focus everywhere'
        )
        if a <= 10:
            o = f'seen from directly in front, the front of the {part}, no head in the frame'
        elif a <= 100:
            o = f'strict side view, photographed from the side, the {part} in profile, no head in the frame'
        else:
            o = f'photographed from directly behind, the back of the {part}, {behind}, no head in the frame, no face'
        return f'{o}, {base}', neg + ', head, face, eyes'
    base = head_p if kind == 'head' else body_p
    if a > 100:
        base = base.replace(ECORCHE_GROUPS_FRONT, ECORCHE_GROUPS_BACK).replace(ECORCHE_HEAD_FRONT, ECORCHE_HEAD_BACK)
    if a <= 10:
        if el > 20 and kind == 'head':
            o = 'seen from above, looking down at the top of the skull muscles and the face foreshortened'
        elif el > 20:
            o = (
                f'seen from a high angle above, looking down at the {who}, the top of the head '
                f'and the shoulders nearest, the body foreshortened'
            )
        elif el < -20 and kind == 'head':
            o = 'seen from below, looking up at the jaw, the masseter and the muscles under the chin'
        elif el < -20:
            o = (
                f'seen from a low angle below, looking up at the {who}, the feet and shins '
                f'nearest, the body foreshortened'
            )
        else:
            o = 'seen from directly in front, the front of the figure facing the viewer'
    elif a <= 50:
        o = (
            f'three-quarter front view, the {who} turned partly away to the {side} of the frame, '
            f'the near side of the face and the temporalis visible'
        )
        extra_neg = ', strict frontal view'
    elif a <= 100:
        o = (
            f'strict side profile, seen from the side, the {who} facing the {side} of the frame, '
            f'the masseter and temporalis in profile, only one side of the body visible'
        )
        extra_neg = ', frontal view, both sides visible, turned toward the viewer'
    elif a <= 150:
        o = (
            f'three-quarter view from behind, the {who} turned mostly away from the viewer, the '
            f'back muscles and one shoulder, the back of the skull, no face visible'
        )
        extra_neg = ', face, frontal view, turned toward the viewer, pectorals, six-pack, navel'
    elif kind == 'head':
        o = (
            'seen from directly behind, the back of the head, the occipitalis over the skull '
            'and the splenius and trapezius of the nape, no face visible'
        )
        extra_neg = ', face, frontal view, turned toward the viewer'
    else:
        o = (
            f'seen from directly behind, the back of the {who}, the trapezius, latissimus dorsi, '
            f'erector spinae along the spine and the back of the skull, gluteus maximus, the '
            f'hamstrings and the calves, no face visible'
        )
        extra_neg = ', face, frontal view, turned toward the viewer, pectorals, six-pack, navel'
    return f'{o}, {base}', neg + extra_neg


def _view_prompt(vid, v, body):
    """The prompt for ONE view says which way the man faces. 2026-09-20: one
    prompt for all views ("looking straight ahead") plus a frontal reference
    made klein paint a front on the back plate and a face on every head
    plate; the plate alone does not fix the orientation of a back or a
    profile, the words do. Returns (positive, negative)."""
    if look_of(body) == 'ecorche':
        return _view_prompt_ecorche(vid, v, body)
    body_p, head_p, neg = _prompts(body)
    who = 'man' if BODIES[body]['gender'] == 'male' else 'woman'
    kind = vid.split('_')[0]
    az = ((v['az'] + 180) % 360) - 180
    el = v['el']
    a = abs(az)
    side = 'right' if az < 0 else 'left'  # which way he faces IN THE FRAME
    extra_neg = ''
    if kind == 'eye':
        which = 'left' if vid == 'eye_l' else 'right'
        pos = (
            f"extreme close-up photograph of the same {who}'s {which} eye, the eyelids, "
            f'eyelashes and eyebrow, eye open looking straight ahead, natural bare skin with '
            f'visible pores and fine lines, even soft diffuse studio lighting from all sides, '
            f'flat lighting, no harsh shadows, macro lens, sharp focus, photorealistic'
        )
        return pos, neg + ', closed eye, second eye, glasses, makeup, mascara, eyeliner, red eye'
    if kind == 'hand':
        which = 'left' if vid == 'hand_l' else 'right'
        pos = (
            f"close-up photograph of the same {who}'s {which} hand, seen from the outside, "
            f'the back of the hand and the fingers, relaxed with the fingers slightly apart, '
            f'natural bare skin with visible pores and fine hair, knuckles, fingernails, '
            f'even soft diffuse studio lighting from all sides, flat lighting, no harsh '
            f'shadows, plain mid-grey seamless background, 85mm lens, sharp focus, photorealistic'
        )
        return pos, neg + ', face, head, red skin, extra fingers, missing fingers, fused fingers, deformed hand'
    base = head_p if kind == 'head' else body_p
    if kind in ('torso', 'legs'):
        part = 'bare torso, chest and shoulders' if kind == 'torso' else 'bare legs, hips and thighs'
        base = body_p.replace('full-length photograph of a nude', f'medium shot photograph of the {part} of a nude')
        base = base.replace('shaved bald head, no hair, neutral expression, ', '')
        if a <= 10:
            o = f'seen from directly in front, the front of the {part}, no head in the frame'
        elif a <= 100:
            o = f'strict side view, photographed from the side, the {part} in profile, no head in the frame'
        else:
            o = (
                f'photographed from directly behind, the back of the {part}, '
                f'{"shoulder blades and the spine" if kind == "torso" else "buttocks and the backs of the thighs"}, '
                f'no head in the frame, no face'
            )
        return f'{o}, {base}', neg + ', head, face, eyes'
    if a <= 10:
        if el > 20 and kind == 'head':
            o = 'photographed from above, looking down at the top of the head and the face foreshortened'
        elif el > 20:
            o = f'photographed from a high angle above, looking down at the {who}, the top of the head and the shoulders nearest, the body foreshortened'
        elif el < -20 and kind == 'head':
            o = 'photographed from below, looking up at the chin, the jaw and the underside of the nose'
        elif el < -20:
            o = f'photographed from a low angle below, looking up at the {who}, the feet and shins nearest, the body foreshortened'
        else:
            o = 'seen from directly in front, facing the camera, eyes open looking straight ahead'
    elif a <= 50:
        o = (
            f'three-quarter front view, the {who} turned partly away to the {side} of the frame, '
            f'the near cheek and one ear visible'
        )
        extra_neg = ', strict frontal view, looking at camera'
    elif a <= 100:
        o = (
            f'strict side profile, photographed from the side, the {who} facing the {side} of '
            f'the frame, one ear visible, only one eye visible, the nose in profile'
        )
        extra_neg = ', frontal face, both eyes visible, two eyes, looking at camera, turned toward the camera'
    elif a <= 150:
        o = (
            f'three-quarter view from behind, the {who} turned mostly away from the camera, '
            f'the back and one shoulder, the back of the head with one ear, no face visible'
        )
        extra_neg = ', face, eyes, nose, mouth, eyebrows, frontal view, looking at camera, turned toward the camera'
    else:
        o = (
            f'photographed from directly behind, the back of the {who}, the back of the head '
            f'and the nape of the neck, both ears seen from behind, shoulder blades, '
            f'{"buttocks and the backs of the legs, " if kind == "body" else ""}no face visible'
        )
        extra_neg = ', face, eyes, nose, mouth, eyebrows, frontal view, looking at camera, turned toward the camera'
    return f'{o}, {base}', neg + extra_neg


def _render_one(cgs, dest, prompt, neg, *, seed, pose=None, ref=None, log):
    kw = dict(
        width=SIZE,
        height=SIZE,
        steps=STEPS,
        cfg=CFG,
        seed=seed,
        model_family='klein',
        skip_qa=True,
        prompt_finalized=True,
        human_subject=True,
        solo_subject=True,
        clear_vram_after=False,
        extra_negative=neg,
        character_package={'style_profile': {'render_style': 'photoreal'}, 'conditioning': {}},
        log_fn=lambda m: log('    ' + str(m)[:160]),
    )
    if pose and ref:
        kw.update(force_workflow='klein_refcontrol', pose_image=pose, reference_image=ref)
    else:
        kw.update(force_workflow='klein_txt2img')
    t0 = time.time()
    ok, backend = cgs.generate_still(dest, prompt, **kw)
    dt = time.time() - t0
    if not ok or not os.path.isfile(dest):
        raise RuntimeError(f'render failed for {os.path.basename(dest)}: {backend}')
    log(f'[render] {os.path.basename(dest)} {dt:.1f}s via {backend}')
    return dest


def _head_box(vid, wd, S):
    """Pixel box of the head in a view: the whole frame for a head close-up,
    the top 16 % of the figure (from the plate mask) for a body view."""
    from PIL import Image

    if vid.startswith('head'):
        return (0, 0, S, S)
    m = np.asarray(Image.open(os.path.join(wd, 'plates', f'{vid}_mask.png'))) > 0
    rows = np.nonzero(m.any(1))[0]
    if len(rows) < 10:
        return (0, 0, S, S)
    top, bot = int(rows[0]), int(rows[-1])
    hh = max(24, int((bot - top) * 0.16))
    cols = np.nonzero(m[top : top + hh].any(0))[0]
    x0, x1 = int(cols[0]), int(cols[-1])
    pad = hh // 3
    return (max(0, x0 - pad), max(0, top - pad // 2), min(S, x1 + pad), min(S, top + hh + pad // 2))


def _frontal_faces(img_p, box):
    """How many FRONTAL faces the Haar cascade finds inside `box`. On this
    pipeline's renders (measured 2026-09-20): a true profile 0, a frontal
    portrait 1 at every head size down to ~190 px, a three-quarter back 2."""
    import cv2
    from PIL import Image

    g = np.asarray(Image.open(img_p).convert('L'))
    x0, y0, x1, y1 = box
    crop = np.ascontiguousarray(g[y0:y1, x0:x1])
    cc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    ms = max(24, int(0.22 * (x1 - x0)))
    faces = cc.detectMultiScale(crop, 1.08, 5, minSize=(ms, ms))
    return 0 if faces is None or len(faces) == 0 else int(len(faces))


def _silhouette_iou(vid, img_p, wd, S):
    """How well the photo's figure covers the plate's mask (IoU). 2026-09-20
    measured over 28 views: 26 at 0.87-0.99, legs_back 0.17 (klein painted a
    whole figure into a legs frame) and body_low 0.59 — the orientation gate
    cannot see either, this can."""
    import cv2
    from PIL import Image

    img = np.asarray(Image.open(img_p).convert('RGB'))
    if img.shape[0] != S:
        img = cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)
    fg = _photo_foreground(img) > 0
    m = np.asarray(Image.open(os.path.join(wd, 'plates', f'{vid}_mask.png'))) > 0
    return float((fg & m).sum() / max(1, (fg | m).sum()))


IOU_MIN = 0.80


def _orientation_gate(vid, v, img_p, wd, S, look=''):
    """Does the photo face the way the plate does? Views from behind or from
    the side must show NO frontal face; the two straight-front views must
    show one. Returns (ok, faces, rule).

    ÉCORCHÉ: a skinned face has no skin, and the Haar frontal cascade finds
    nothing on a muscle plate — so the "there must be a face here" rule would
    reject every good front. It is waived; the a >= 85 "there must be NO face
    here" rule stays, because that is what stops a front being painted on the
    back and it only ever fires on a false positive there."""
    kind = vid.split('_')[0]
    if kind in ('hand', 'eye', 'torso', 'legs'):
        return True, 0, 'none'
    a = abs(((v['az'] + 180) % 360) - 180)
    faces = _frontal_faces(img_p, _head_box(vid, wd, S))
    if look == 'ecorche' and a <= 10 and v['el'] == 0:
        return True, faces, 'ecorche-nogate'
    if a >= 85:
        return faces == 0, faces, 'no-frontal-face'
    if a <= 10 and v['el'] == 0:
        return faces >= 1, faces, 'frontal-face'
    return True, faces, 'free'


def _render_view(cgs, vid, v, body, wd, rd, seed, *, log, check=None, retries=2):
    """One view: prompt for its orientation, reference = nearest rendered
    neighbour, then the orientation gate. A failed gate re-renders with a new
    seed up to `retries` times and then FAILS the stage — a photo facing the
    wrong way baked into the atlas is worse than no atlas. Returns the gate
    record."""
    pos, neg = _view_prompt(vid, v, body)
    plate = os.path.join(wd, 'plates', f'{vid}_depth.png')
    ref = os.path.join(rd, f'{REF_OF.get(vid, "body_front")}.png')
    if not os.path.isfile(ref):
        ref = os.path.join(rd, 'body_front.png')
    dest = os.path.join(rd, f'{vid}.png')
    S = SIZE
    rec = {'ref': os.path.basename(ref), 'attempts': [], 'ok': False}
    for k in range(retries + 1):
        if check:
            check()
        sd = seed + 1000 * k
        _render_one(cgs, dest, pos, neg, seed=sd, pose=plate, ref=ref, log=log)
        ok, faces, rule = _orientation_gate(vid, v, dest, wd, S, look=look_of(body))
        iou = _silhouette_iou(vid, dest, wd, S)
        # a filler view (priority < 1) only ever wins texels nothing else sees,
        # so it may sit a little further off its plate
        fits = iou >= (IOU_MIN if PRIORITY.get(vid, 1.0) >= 1.0 else 0.70)
        rec['attempts'].append({'seed': sd, 'faces': faces, 'rule': rule, 'iou': round(iou, 3), 'ok': ok and fits})
        log(
            f'[gate] {vid:11s} {rule:16s} frontal faces {faces}  silhouette IoU {iou:.3f}  '
            f'{"OK" if ok and fits else ("WRONG WAY" if not ok else "OFF PLATE")}'
            f'{"" if (ok and fits) or k == retries else " -> new seed"}'
        )
        ok = ok and fits
        if ok:
            rec['ok'] = True
            break
        try:
            shutil.copy(dest, os.path.join(rd, f'{vid}.rejected{k}.png'))
        except OSError as _exc:
            _zyg_log.debug('rejected view copy not kept: %s', _exc)
    if not rec['ok']:
        if PRIORITY.get(vid, 1.0) < 1.0:
            # a filler view (top/low/up/down) is not worth failing the bake for:
            # drop it, the axial views cover what it would have added
            try:
                os.remove(dest)
            except OSError as _exc:
                _zyg_log.debug('rejected view removal skipped: %s', _exc)
            rec['skipped'] = True
            log(f'[gate] {vid:11s} dropped after {retries + 1} seeds (filler view, priority {PRIORITY.get(vid, 1.0)})')
            return rec
        raise RuntimeError(
            f'{vid}: no acceptable render after {retries + 1} seeds '
            f'(orientation gate {rule}, frontal faces {faces}, silhouette IoU {iou:.3f})'
        )
    return rec


def _ecorche_ref_seed(body, dest, log):
    """ref_seed for the écorché look is NOT generated: it is the operator's own
    anatomy plate. That plate is half skeleton, half muscle down the midline,
    so the muscle half is cropped and mirrored into a whole symmetric figure
    (the skeleton is exactly what the negative prompt excludes) and padded to
    a square on white — the same white backdrop the prompts ask for."""
    from PIL import Image

    src = BODIES[body]['ref']
    if not os.path.isfile(src):
        raise RuntimeError(f'{body}: reference plate not found: {src}')
    im = Image.open(src)
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        im = Image.alpha_composite(Image.new('RGBA', im.size, (255, 255, 255, 255)), im)
    im = im.convert('RGB')
    W, H = im.size
    mid = W // 2
    if BODIES[body].get('ref_muscle_half', 'right') == 'right':
        muscle = im.crop((mid, 0, W, H))
        left, right = muscle.transpose(Image.FLIP_LEFT_RIGHT), muscle
    else:
        muscle = im.crop((0, 0, mid, H))
        left, right = muscle, muscle.transpose(Image.FLIP_LEFT_RIGHT)
    full = Image.new('RGB', (2 * muscle.width, H), (255, 255, 255))
    full.paste(left, (0, 0))
    full.paste(right, (muscle.width, 0))
    side = max(full.size)
    sq = Image.new('RGB', (side, side), (255, 255, 255))
    sq.paste(full, ((side - full.width) // 2, (side - full.height) // 2))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    sq.save(dest)
    log(
        f'[render] ref_seed built from {os.path.basename(src)}: {W}x{H} plate, muscle half '
        f'x {mid}..{W} mirrored -> {full.width}x{full.height}, padded to {side}x{side}'
    )
    return dest


def stage_render(body, log, seed=7, force=False, check=None):
    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_workflows import comfy_generation_service as cgs

    if not cgs.is_available():
        raise RuntimeError('the render backend is not available (ComfyUI unreachable or disabled)')
    if not cgs.has_klein_refcontrol():
        raise RuntimeError('klein RefControl adapter is not installed — no licensed depth control')
    wd = work_dir(body)
    rd = os.path.join(wd, 'renders')
    os.makedirs(rd, exist_ok=True)
    cams = json.load(open(os.path.join(wd, 'cameras.json')))
    body_p, head_p, neg = _prompts(body)
    out = lambda vid: os.path.join(rd, f'{vid}.png')  # noqa: E731
    have = lambda p: os.path.isfile(p) and not force  # noqa: E731
    gate_p = os.path.join(rd, 'gate.json')
    try:
        gate = json.load(open(gate_p)) if not force else {}
    except (OSError, ValueError):
        gate = {}

    ref0 = os.path.join(rd, 'ref_seed.png')
    if not have(ref0):
        if look_of(body) == 'ecorche':
            _ecorche_ref_seed(body, ref0, log)
        else:
            if check:
                check()
            _render_one(cgs, ref0, body_p, neg, seed=seed, log=log)
    # REF_OF order: every view after the one it is referenced from
    order = []
    for vid in list(BODY_VIEWS) + list(HEAD_VIEWS) + list(HAND_VIEWS) + list(EYE_VIEWS) + list(ZOOM_VIEWS):
        if vid in cams['views'] and vid not in order:
            order.append(vid)
    order.sort(key=lambda vid: _depth_in_chain(vid))
    for vid in order:
        if have(out(vid)):
            continue
        gate[vid] = _render_view(cgs, vid, cams['views'][vid], body, wd, rd, seed, log=log, check=check)
        with open(gate_p, 'w', encoding='utf-8') as fh:
            json.dump(gate, fh, indent=1)
    first = sum(1 for g in gate.values() if g.get('ok') and len(g.get('attempts', [])) == 1)
    dropped = [k for k, g in gate.items() if g.get('skipped')]
    log(
        f'[gate] {first}/{len(gate)} views passed on the first take'
        + (f'; dropped {", ".join(dropped)}' if dropped else '')
    )
    try:
        cgs.free_vram()
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('vram release skipped: %s', _exc)
    return {v: out(v) for v in order}


def _depth_in_chain(vid):
    d, cur = 0, vid
    while cur in REF_OF and REF_OF[cur] != 'ref_seed' and d < 10:
        cur = REF_OF[cur]
        d += 1
    return d


def _photo_foreground(img):
    """Where the photograph shows the FIGURE rather than the grey backdrop.
    Chroma: skin has R - B well above the neutral backdrop's; a mild closing
    keeps dark details (nostrils, the mouth line) inside the figure."""
    import cv2

    r = img[..., 0].astype(np.int16)
    g = img[..., 1].astype(np.int16)
    b = img[..., 2].astype(np.int16)
    fg = ((r - b) > 16) & (r >= g)
    fg = fg.astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    # drop specks the backdrop's gradient could leave
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n > 1:
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] > 2000
        fg = keep[lab].astype(np.uint8)
    return fg
