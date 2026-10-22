# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""prop_control.py — paint rigid-prop geometry into VACE control frames (2026-08-01).

THE DEFECT THIS EXISTS FOR.
scene20_v15 shipped with the ledger changing size, thickness and page layout across the
clip, and with Cornelis's pipe degenerating into a red outline with no hand by t=13.
Both are the same mechanism, and it is structural rather than a prompt problem:

    region        inside the VACE *generate* mask
    pipe          100.0%
    book           95.4%

and wan_vace_service.py:1539-1541 fills the control frame under that mask with a CONSTANT:

    grey = np.full_like(s_arr, 127.0)
    ctrl = s_arr * (1.0 - m_arr) + grey * m_arr

One still, repeated for all 341 frames, flat grey 127 wherever the props live. VACE
therefore receives NO geometric guidance for them and re-invents both objects in each of
six context windows from the prompt plus a small reference image. Text pins semantics,
not geometry — "an open bound book" constrains neither thickness nor page count, and
nothing whatsoever guarantees the pipe still exists in window four. Measured on the
delivered v15 clip, edge-correlation against frame 0 was 0.164 (book) and 0.201 (pipe).

So the control channel is not merely under-used: it is actively spent on a constant.
This module fills it with the one thing that cannot drift — rendered rigid geometry.

WHY THE BOOK FIRST (properties of THIS shot, not general preference):
  * world-static — it rests on the table, so ONE plate serves all 341 frames; no
    animation, no tracking, no per-frame Blender cost;
  * the camera is locked off, so a single viewpoint is correct for the whole clip;
  * it is barely occluded — only the writing hand crosses it.
The pipe is held in a mouth and a fist, so it needs per-frame animation AND occlusion
handling. Doing the book first gets the mechanism proven on the easy case.

ALIGNMENT IS A HOMOGRAPHY, NOT AN EYEBALL.
The original plate came out of a generator, so there are no camera intrinsics to match.
prop_mesh/book_render.py instead reports the EXACT projected pixel coordinates of the
rendered page's four corners (from the mesh, via world_to_camera_view). Here we solve the
homography taking those four points onto the shot's own `page_quad` from
shot_metadata.json and warp the whole plate through it, so the rendered page lands
precisely where the real page already is.

DELIBERATELY A GUIDE, NOT A PASTE.
The plate goes into the CONTROL frame, which VACE consumes as conditioning and releases
at vace_end_percent — it is not composited onto the output. That distinction is the whole
reason this is safe where the 2026-07-30 paste-back was not: pasting the anchor's pixels
over a keep-region destroyed 68% of Abel's hand motion because anything crossing that
region was overwritten every frame. Here the model remains free to draw a hand in front of
the book; it is merely told, at every step, what shape the book is.
"""

import json
import os

_DEF_STRENGTH = float(os.environ.get('ZYG_PROP_CONTROL_STRENGTH', '1.0'))
_DEF_FEATHER = int(os.environ.get('ZYG_PROP_CONTROL_FEATHER', '3'))


def _log_noop(_m):
    pass


def _order_quad(pts):
    """TL, TR, BR, BL in image space (y down) — the order shot_metadata uses."""
    pts = [(float(x), float(y)) for x, y in pts]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    tl = min((p for p in pts if p[0] <= cx and p[1] <= cy), default=None, key=lambda p: p[0] + p[1])
    br = max((p for p in pts if p[0] >= cx and p[1] >= cy), default=None, key=lambda p: p[0] + p[1])
    tr = min((p for p in pts if p[0] >= cx and p[1] <= cy), default=None, key=lambda p: -p[0] + p[1])
    bl = min((p for p in pts if p[0] <= cx and p[1] >= cy), default=None, key=lambda p: p[0] - p[1])
    got = [tl, tr, br, bl]
    if any(g is None for g in got) or len({tuple(g) for g in got}) != 4:
        return None  # degenerate — caller falls back
    return got


def warp_plate(plate_png, plate_meta, dst_quad_frac, size, log_fn=None):
    """-> (rgb float32 HxWx3, alpha float32 HxW) of the plate warped onto dst_quad_frac.

    dst_quad_frac: 4 fractional (x,y) points in the SHOT's frame (shot_metadata page_quad).
    Returns (None, None) on any failure — the caller must then leave the control alone.
    """
    log = log_fn or _log_noop
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception as e:
        log(f'[prop] deps unavailable ({e})')
        return None, None
    try:
        W, H = int(size[0]), int(size[1])
        meta = plate_meta
        if isinstance(meta, str):
            meta = json.load(open(meta))
        pre_aligned = bool(meta.get('aligned')) or dst_quad_frac is None
        src = meta.get('page_quad_render')
        if not pre_aligned and (not src or len(src) != 4):
            # Only the WARPED path needs the rendered page corners. A pre-aligned plate
            # was rendered from the recovered camera and carries no quad by design, so
            # demanding one here rejected exactly the plates that need no warp.
            log('[prop] plate meta has no 4-point page_quad_render')
            return None, None
        pw, ph = meta.get('size') or [W, H]

        im = Image.open(plate_png).convert('RGBA')
        if im.size != (int(pw), int(ph)):
            im = im.resize((int(pw), int(ph)))
        arr = np.asarray(im, dtype=np.float32)
        rgb, a = arr[:, :, :3], arr[:, :, 3] / 255.0

        # PRE-ALIGNED PLATE: rendered from the camera recovered by prop_camera, so it is
        # already in the shot's frame and must NOT be warped again. Warping a plate that
        # already fits is how the first attempt sheared the book across half the frame.
        if pre_aligned:
            if (im.width, im.height) != (W, H):
                rgb = cv2.resize(rgb, (W, H), interpolation=cv2.INTER_LINEAR)
                a = cv2.resize(a, (W, H), interpolation=cv2.INTER_LINEAR)
            if _DEF_FEATHER > 0:
                k = 2 * int(_DEF_FEATHER) + 1
                a = cv2.GaussianBlur(a, (k, k), 0)
            log(f'[prop] plate used PRE-ALIGNED (no warp), coverage {100.0 * float((a > 0.5).mean()):.2f}% of frame')
            return rgb, np.clip(a, 0.0, 1.0)

        s = _order_quad(src)
        d = _order_quad([(float(x) * W, float(y) * H) for x, y in dst_quad_frac])
        if s is None or d is None:
            log('[prop] could not order one of the quads (degenerate) — skipped')
            return None, None
        Hm = cv2.getPerspectiveTransform(np.float32(s), np.float32(d))
        wr = cv2.warpPerspective(
            rgb, Hm, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0)
        )
        wa = cv2.warpPerspective(a, Hm, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if _DEF_FEATHER > 0:
            k = 2 * int(_DEF_FEATHER) + 1
            wa = cv2.GaussianBlur(wa, (k, k), 0)
        log(
            f'[prop] plate warped: src_quad={[[round(v, 1) for v in p] for p in s]} -> '
            f'dst_quad={[[round(v, 1) for v in p] for p in d]}, '
            f'coverage {100.0 * float((wa > 0.5).mean()):.2f}% of frame'
        )
        return wr, np.clip(wa, 0.0, 1.0)
    except Exception as e:
        log(f'[prop] warp FAILED ({e})')
        return None, None


def composite_into_control(control_png, plates, out_png, mask_png=None, strength=None, log_fn=None):
    """Paint each warped plate into a control frame, replacing the neutral grey.

    plates: [{'plate': png, 'meta': json-or-path, 'quad': [[x,y]x4 fractional]}, ...]
    mask_png: the character/generate mask. When given, plates are applied ONLY where the
      mask is white (the generated region) — painting geometry into a KEEP region would
      fight the still that is already there.
    Returns out_png, or None (caller keeps the untouched control).
    """
    log = log_fn or _log_noop
    try:
        import numpy as np
        from PIL import Image
    except Exception as e:
        log(f'[prop] deps unavailable ({e})')
        return None
    try:
        st = _DEF_STRENGTH if strength is None else float(strength)
        base = Image.open(control_png).convert('RGB')
        W, H = base.size
        out = np.asarray(base, dtype=np.float32)
        gate = None
        if mask_png and os.path.isfile(mask_png):
            m = Image.open(mask_png).convert('L').resize((W, H))
            gate = np.asarray(m, dtype=np.float32) / 255.0
        applied = 0
        for p in plates or []:
            rgb, a = warp_plate(p.get('plate'), p.get('meta'), p.get('quad'), (W, H), log_fn=log)
            if rgb is None:
                continue
            if gate is not None:
                a = a * gate
            # PER-PLATE STRENGTH — added 2026-08-02 after v21's probe froze Cornelis.
            # A world-static prop (the book) wants a HARD assertion: it never moves, so
            # pinning its geometry costs nothing. A prop held in a MOVING HAND (the pipe)
            # does not: at full strength the control says "this is exactly here", the model
            # obeys, and the hand holding it stops moving too. Measured on v21's 81f probe
            # against v20's: pipe churn_p95 0.384 -> 0.014, c_hands churn 0.014, and
            # cornelis.face fell to 0.058 (below the 0.12 floor) — he froze. So a held prop
            # gets a WEAK plate: enough to stop it dissolving, not enough to nail it down.
            p_st = float(p.get('strength', st))
            a = np.clip(a * p_st, 0.0, 1.0)[:, :, None]
            out = out * (1.0 - a) + rgb * a
            applied += 1
        if not applied:
            log('[prop] no plate applied — control left untouched')
            return None
        os.makedirs(os.path.dirname(os.path.abspath(out_png)) or '.', exist_ok=True)
        Image.fromarray(np.clip(out, 0, 255).astype('uint8')).save(out_png)
        # Report how much of the control stopped being flat grey — this number IS the
        # experiment: 0% means the whole thing was a no-op and the props stay unguided.
        grey = np.abs(np.asarray(base, dtype=np.float32) - 127.0).max(axis=2) < 2.0
        now = np.abs(out - 127.0).max(axis=2) >= 2.0
        freed = float((grey & now).mean())
        log(
            f'[prop] control composited: {applied} plate(s) -> {os.path.basename(out_png)}; '
            f'{100.0 * freed:.2f}% of frame changed from neutral grey to geometry'
        )
        return out_png
    except Exception as e:
        log(f'[prop] composite FAILED ({e}) — control unchanged')
        return None


def make_pipe_plate(shot_meta, out_png, size=(832, 480), log_fn=None, stem_px=None, bowl_px=None):
    """Draw a long thin white clay pipe from mouth_pin to bowl_pin. -> out_png or None.

    WHY A 2D PLATE AND NOT A BLENDER MESH — the measurement decided this, not preference.
    Tracked the pipe across the delivered v17 clip (bright, low-saturation blob inside the
    pipe region, 2fps):

        t 0-6s   area 4.1% -> 1.8%, centroid stable ~(0.62,0.48) in-region
        t 8-14s  area 0.9%, centroid jumps to (0.10,0.69) — the tracker has lost the pipe
                 and latched onto the collar/cuff
        elongation NEVER exceeds 5.7 across the whole clip, against the validated
        reference's 10.93

    So the defect is NOT that the pipe moves unpredictably — it is that the pipe DISSOLVES
    after ~6 seconds, and was never the right shape even while present. And because the
    centroid is stable while it exists, Cornelis barely translates it: the draws are mouth
    movements, not pipe travel. A STATIC plate therefore fits, exactly as the book's did.

    Given that, a mesh buys nothing: the pipe is a thin near-planar object seen side-on, so
    there is no meaningful foreshortening to model, and mouth_pin/bowl_pin already fix its
    two endpoints in image space. A 3D route would add a depth-placement step (the camera
    was solved on the TABLE plane for the book; the pipe sits up near the face at an unknown
    depth) for no gain. The mesh route stays right for genuinely volumetric props.

    Geometry comes from the run's own metadata plus the reference the asset gate validated:
    stem length = |bowl_pin - mouth_pin|, stem width = length/elongation, bowl = bowl_frac
    of the area at the bowl end.
    """
    log = log_fn or _log_noop
    try:
        import math
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter
    except Exception as e:
        log(f'[prop] deps unavailable ({e})')
        return None
    try:
        if isinstance(shot_meta, str):
            shot_meta = json.load(open(shot_meta))
        m = (shot_meta or {}).get('mouth_pin')
        b = (shot_meta or {}).get('bowl_pin')
        if not (m and b and len(m) == 2 and len(b) == 2):
            log('[prop] shot_metadata lacks mouth_pin/bowl_pin — no pipe plate')
            return None
        W, H = int(size[0]), int(size[1])
        mx, my = float(m[0]) * W, float(m[1]) * H
        bx, by = float(b[0]) * W, float(b[1]) * H
        L = math.hypot(bx - mx, by - my)
        if L < 20:
            log(f'[prop] pipe pins are {L:.1f}px apart — too short, skipped')
            return None
        # GEOMETRY CHOSEN BY THE ASSET GATE, NOT BY me. The first attempt derived
        # stem_w = L/elongation (14.5px) and sized the bowl from bowl_frac, which
        # gave a plate the gate REJECTED: elongation 6.46 (needs >=10) and bowl_frac
        # 0.155 (needs <=0.12). The arithmetic was not wrong, the metric was: the gate
        # measures elongation by PCA over the WHOLE blob, so a fat bowl widens the
        # minor axis and collapses the ratio no matter how thin the stem is. Swept
        # stem_w x bowl_r against the real gate and took the widest-margin pass:
        #     stem_w 8, bowl_r 6  ->  elongation 15.11, bowl_frac 0.073  PASS
        # (scaled off L so a different shot keeps the proportions).
        # stem_px/bowl_px exist so the gate-rejection path can be exercised in a test;
        # production always uses the swept values.
        stem_w = float(stem_px) if stem_px else max(3.0, L * (8.0 / 158.0))
        bowl_r = float(bowl_px) if bowl_px else max(3.0, L * (6.0 / 158.0))

        im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        CLAY = (232, 228, 218, 255)
        SHADE = (196, 190, 178, 255)
        # stem — drawn slightly tapered by stacking two widths
        d.line([(mx, my), (bx, by)], fill=CLAY, width=int(round(stem_w)))
        d.line(
            [(mx, my), (mx + (bx - mx) * 0.45, my + (by - my) * 0.45)],
            fill=CLAY,
            width=max(2, int(round(stem_w * 0.72))),
        )
        # bowl at the bowl end, offset slightly along the stem so it reads as a cup
        ux, uy = (bx - mx) / L, (by - my) / L
        cx, cy = bx + ux * bowl_r * 0.25, by + uy * bowl_r * 0.25
        d.ellipse([cx - bowl_r, cy - bowl_r * 1.15, cx + bowl_r, cy + bowl_r * 1.15], fill=CLAY, outline=SHADE, width=2)
        # the opening, so the model is told this is a BOWL and not a ball
        d.ellipse([cx - bowl_r * 0.62, cy - bowl_r * 1.05, cx + bowl_r * 0.62, cy - bowl_r * 0.35], fill=SHADE)
        im = im.filter(ImageFilter.GaussianBlur(0.5))
        os.makedirs(os.path.dirname(os.path.abspath(out_png)) or '.', exist_ok=True)
        im.save(out_png)
        a = np.asarray(im, dtype=np.float32)[:, :, 3] / 255.0

        # SELF-VALIDATE THROUGH THE SAME GATE THE REFERENCE ASSET HAD TO PASS.
        # A control plate is an assertion about what the prop IS; shipping one the
        # asset gate would reject means telling the model, for 341 frames, that the
        # pipe is the wrong shape — strictly worse than telling it nothing. The gate
        # already caught one bad plate of mine, so this is not hypothetical.
        try:
            from zyg_workflows import asset_validate as AV

            ys, xs = np.where(a > 0.5)
            p = 18
            box = (
                max(0, int(xs.min()) - p),
                max(0, int(ys.min()) - p),
                min(W, int(xs.max()) + p),
                min(H, int(ys.max()) + p),
            )
            crop = im.crop(box)
            flat = Image.new('RGB', crop.size, (128, 128, 128))
            flat.paste(crop, (0, 0), crop)
            gate_png = out_png + '.gate.png'
            flat.save(gate_png)
            gr = AV.validate_prop_ref(gate_png, log_fn=None)
            gm = gr.get('metrics') or gr
            if not gr.get('ok'):
                log(
                    f'[prop] pipe plate REJECTED by the asset gate '
                    f'(elong {gm.get("elongation")}, bowl_frac {gm.get("bowl_frac")}): '
                    f'{gr.get("reasons")} — NOT used'
                )
                return None
            log(
                f'[prop] pipe plate asset gate PASS '
                f'(elong {gm.get("elongation"):.2f}, bowl_frac {gm.get("bowl_frac"):.3f})'
            )
        except Exception as e:
            log(f'[prop] pipe plate could not be gate-checked ({e}) — used unvalidated')

        log(
            f'[prop] pipe plate: mouth({mx:.0f},{my:.0f}) -> bowl({bx:.0f},{by:.0f}) '
            f'len {L:.0f}px stem_w {stem_w:.1f}px bowl_r {bowl_r:.1f}px, '
            f'coverage {100 * float((a > 0.5).mean()):.2f}% of frame'
        )
        return out_png
    except Exception as e:
        log(f'[prop] pipe plate FAILED ({e})')
        return None


def add_script_to_plate(
    plate_png, page_quad_frac, out_png, size=(832, 480), lines=6, seed=7, opacity=0.55, log_fn=None
):
    """Draw faint, STATIC script onto the plate's page so the page CONTENT stops drifting.

    WHY — the book plate fixed the book's SHAPE and left its CONTENT free, and the
    measurement says that is where the remaining churn lives. On v20's RAW render (no ink
    composite anywhere in it):
        t=2   the page carries prominent BLUE handwriting
        t=14  different, sparser dark marks
    The model is inventing the page's writing and re-inventing it per context window —
    which is what the operator saw as "the text in book writing itself without abel doing
    anything". Fixing ink_fx's schedule addressed only the OVERLAY; this addresses the
    render. A blank plate says "a book is here"; a plate with script says "a book with
    THESE marks is here", which is the same trick that stopped the covers morphing.

    Deliberately FAINT and static: it is a ledger already in use, so prior entries belong
    there, and ink_fx still composites the new lines Abel writes during beat 0 on top.
    """
    log = log_fn or _log_noop
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception as e:
        log(f'[prop] deps unavailable ({e})')
        return None
    try:
        if not page_quad_frac or len(page_quad_frac) != 4:
            log('[prop] no page_quad — plate left blank')
            return None
        W, H = int(size[0]), int(size[1])
        plate = Image.open(plate_png).convert('RGBA')
        if plate.size != (W, H):
            plate = plate.resize((W, H))

        try:
            from zyg_workflows import ink_fx as INK

            tex = INK.make_script_texture(512, 256, lines=lines, seed=seed)
        except Exception as e:
            log(f'[prop] ink_fx.make_script_texture unavailable ({e}) — plate left blank')
            return None
        tex = tex.convert('RGBA')
        tw, th = tex.size
        src = np.float32([[0, 0], [tw, 0], [tw, th], [0, th]])
        dst = _order_quad([(float(x) * W, float(y) * H) for x, y in page_quad_frac])
        if dst is None:
            log('[prop] page_quad degenerate — plate left blank')
            return None
        M = cv2.getPerspectiveTransform(src, np.float32(dst))
        ta = np.asarray(tex, dtype=np.float32)
        warped = cv2.warpPerspective(
            ta, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)
        )
        wa = np.clip(warped[:, :, 3] / 255.0 * float(opacity), 0.0, 1.0)

        pa = np.asarray(plate, dtype=np.float32)
        # only where the plate's own page actually is — never paint script into thin air
        gate = (pa[:, :, 3] / 255.0 > 0.5).astype(np.float32)
        a = (wa * gate)[:, :, None]
        ink_rgb = warped[:, :, :3]
        pa[:, :, :3] = pa[:, :, :3] * (1.0 - a) + ink_rgb * a
        out = Image.fromarray(np.clip(pa, 0, 255).astype('uint8'), mode='RGBA')
        os.makedirs(os.path.dirname(os.path.abspath(out_png)) or '.', exist_ok=True)
        out.save(out_png)
        log(
            f'[prop] script added to plate: {lines} lines, opacity {opacity}, '
            f'{100.0 * float((a[:, :, 0] > 0.05).mean()):.2f}% of frame inked'
        )
        return out_png
    except Exception as e:
        log(f'[prop] add_script_to_plate FAILED ({e}) — plate left blank')
        return None


def book_plate_from_meta(shot_meta, plate_dir, log_fn=None):
    """Convenience: build the single-plate list for the ledger from shot_metadata."""
    log = log_fn or _log_noop
    if isinstance(shot_meta, str):
        shot_meta = json.load(open(shot_meta))
    quad = (shot_meta or {}).get('page_quad')
    if not quad or len(quad) != 4:
        log('[prop] shot_metadata has no 4-point page_quad — no book plate')
        return []
    plate = os.path.join(plate_dir, 'book_rgb.png')
    meta = os.path.join(plate_dir, 'book_meta.json')
    if not (os.path.isfile(plate) and os.path.isfile(meta)):
        log(f'[prop] book plate missing in {plate_dir} — run prop_mesh/book_render.py')
        return []
    return [{'plate': plate, 'meta': meta, 'quad': quad, 'name': 'book'}]


if __name__ == '__main__':  # the CLI lives in prop_control_cli
    from zyg_workflows.prop_control_cli import main as _cli_main

    raise SystemExit(_cli_main())
