# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""(4) per-frame mask sequence and (S01) external per-frame control frames (original lines 1451-1915).

Split out of wan_vace_service.py; the code below is unchanged.
"""

from zyg_workflows.wan_vace_service.base import Image, _log_noop, exe, os, shutil

# ---------------------------------------------------------------------------
# (4) PER-FRAME MASK SEQUENCE  —  ZYG_VACE_MASK_SEQ (default OFF)
#
# WHY: WanVideoVACEEncode's `input_masks` is typed MASK and its BATCH AXIS IS TIME —
# nodes.py:1762-1765 slices it as input_masks[:num_frames] and permutes to B,C,T,H,W. So the
# mask has always been allowed to vary per frame. We defeat that: the graph does
# LoadImage -> RepeatImageBatch(341) -> ImageToMask, i.e. 341 identical copies of one PNG.
# One static envelope has to be the UNION of everywhere anything moves for the whole shot,
# which is why it ends up huge and why parts of the set that only move for two seconds stay
# open (and therefore invented) for twenty.
#
# THE CONTROL FRAMES MUST FOLLOW. VACE splits inactive=i*(1-m) / reactive=i*m
# (nodes.py:1827-1831). If the mask shrinks at frame t but the control frame still has flat
# grey baked in over the union region, then those pixels are handed to `inactive` as
# "keep this content" — and the content is grey. That paints grey walls. So sequence mode
# builds a MATCHING per-frame control sequence (still, greyed under THAT frame's mask) and
# loads both with LoadImagesFromFolderKJ.
#
# LoadImagesFromFolderKJ GOTCHA (known in this codebase, see generate_vace_clip_from_frames):
# image_load_cap and start_index are declared optional in INPUT_TYPES but are POSITIONAL
# WITH NO DEFAULT in load_images() (ComfyUI-KJNodes/nodes/image_nodes.py:3416) — omit them
# and the node raises TypeError at execution. Both are always passed here. The node also
# sorts lexicographically (image_nodes.py:3434), hence the zero-padded %05d names.
# ---------------------------------------------------------------------------

_SEQ_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.tga')
_VID_EXT = ('.mp4', '.mov', '.mkv', '.webm', '.avi')
# Mask-frame name patterns, best first — the same prefix-then-fallback rule
# control_frames_in() already applies to control plates (_CTRL_GLOBS). A scene
# plate set is ONE directory holding six channels (bg_/ctrl_/depth_/face_/m_/
# pose_), so a bare `*.png` sweep sorts `bg_00001.png` to the front and hands the
# sampler the beauty plates as its mask. Those are photographs: white_frac ~0.94,
# soft_band 1.0, and the preflight blocks the render before submit.
_MASK_GLOBS = ('m_*.png', 'mask_*.png', '*.png')


def is_mask_sequence(mask_path):
    """True when mask_path names a directory of frames or a video file."""
    if not mask_path:
        return False
    p = str(mask_path)
    if os.path.isdir(p):
        return True
    return os.path.isfile(p) and p.lower().endswith(_VID_EXT)


def _seq_source_frames(mask_path, work_dir, log):
    """-> list of source frame paths (decoding a video into work_dir when needed)."""
    p = str(mask_path)
    import glob as _glob

    if os.path.isdir(p):
        for pat in _MASK_GLOBS:
            hits = sorted(_glob.glob(os.path.join(p, pat)))
            if hits:
                return hits
        return sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(_SEQ_EXT))
    import subprocess

    dec = os.path.join(work_dir, '_decoded')
    shutil.rmtree(dec, ignore_errors=True)
    os.makedirs(dec, exist_ok=True)
    r = subprocess.run(
        [exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', p, '-vsync', '0', os.path.join(dec, 'd_%05d.png')],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        log(f'[mask-seq] ffmpeg could not decode {os.path.basename(p)}: {(r.stderr or "").strip()[:200]}')
        return []
    return sorted(_glob.glob(os.path.join(dec, 'd_*.png')))


def build_mask_sequence(mask_path, out_dir, num_frames, size, log_fn=None):
    """Normalize a mask directory/video into exactly num_frames 8-bit L PNGs at `size`.

    Short sequences are PADDED by repeating the last frame — a short input_masks batch does
    not fail gracefully, it broadcast-errors inside vace_encode_frames hours in. Long ones
    are truncated (VACE would truncate anyway, at nodes.py:1762). Resampling re-introduces a
    soft band, so the tails are re-crushed exactly as _feather_and_crush does.

    Returns (mask_dir, union_png_path, n_source_frames) or (None, None, 0)."""
    log = log_fn or _log_noop
    try:
        import numpy as _np

        W, H = int(size[0]), int(size[1])
        seq_dir = os.path.join(out_dir, '_vace_maskseq')
        srcs = _seq_source_frames(mask_path, out_dir, log)
        if not srcs:
            log(f'[mask-seq] no frames found in {mask_path}')
            return None, None, 0
        n_src = len(srcs)
        if n_src < num_frames:
            log(
                f'[mask-seq] WARNING: only {n_src} mask frames for {num_frames} render '
                f'frames — padding with the last frame (a short input_masks batch '
                'broadcast-errors inside vace_encode_frames)'
            )
        elif n_src > num_frames:
            log(f'[mask-seq] {n_src} mask frames > {num_frames} render frames — truncating')
        shutil.rmtree(seq_dir, ignore_errors=True)
        os.makedirs(seq_dir, exist_ok=True)
        union = _np.zeros((H, W), dtype='uint8')
        for i in range(int(num_frames)):
            src = srcs[min(i, n_src - 1)]
            im = Image.open(src).convert('L')
            if im.size != (W, H):
                im = im.resize((W, H), Image.LANCZOS)
            a = _np.array(_np.asarray(im), dtype='uint8', copy=True)
            a[a < 24] = 0
            a[a > 231] = 255
            union = _np.maximum(union, a)
            Image.fromarray(a, mode='L').save(os.path.join(seq_dir, f'm_{i:05d}.png'))
        union_path = os.path.join(out_dir, '_vace_maskseq_union.png')
        Image.fromarray(union, mode='L').save(union_path)
        log(
            f'[mask-seq] → {seq_dir} ({num_frames} frames from {n_src} source, '
            f'{W}x{H}); union white_frac {float((union > 127).mean()):.4f}'
        )
        return seq_dir, union_path, n_src
    except Exception as e:
        log(f'[mask-seq] FAILED ({e})')
        return None, None, 0


def build_control_sequence(still_fit, mask_dir, out_dir, num_frames, size, log_fn=None):
    """Per-frame neutral-grey control frames matching a per-frame mask (see header).

    ctrl_t = still*(1-m_t) + 127*m_t. Returns ctrl_dir or None (fail-safe)."""
    log = log_fn or _log_noop
    try:
        import numpy as _np

        W, H = int(size[0]), int(size[1])
        ctrl_dir = os.path.join(out_dir, '_vace_ctrlseq')
        shutil.rmtree(ctrl_dir, ignore_errors=True)
        os.makedirs(ctrl_dir, exist_ok=True)
        s_arr = _np.asarray(Image.open(still_fit).convert('RGB').resize((W, H)), dtype=_np.float32)
        grey = _np.full_like(s_arr, 127.0)
        for i in range(int(num_frames)):
            mp = os.path.join(mask_dir, f'm_{i:05d}.png')
            m = _np.asarray(Image.open(mp).convert('L'), dtype=_np.float32)[:, :, None] / 255.0
            c = s_arr * (1.0 - m) + grey * m
            Image.fromarray(c.astype('uint8')).save(os.path.join(ctrl_dir, f'c_{i:05d}.png'))
        log(f'[mask-seq] control frames neutralized per-frame → {ctrl_dir}')
        return ctrl_dir
    except Exception as e:
        log(f'[mask-seq] control sequence FAILED ({e})')
        return None


# ── (S01, 2026-09-02) EXTERNAL PER-FRAME CONTROL FRAMES ───────────────────────────────
# Everything below the folder already existed: node 13 is LoadImagesFromFolderKJ and will
# read ANY directory of control frames. What did not exist was a way for a caller to hand
# one over — build_control_sequence built the only sequence the service would accept, and
# it is `still*(1-m) + 127*m`, i.e. a constant where generation happens. The two painters
# that put geometry back into that constant (prop_control, char_vace) sat inside the
# single-image branch, so they were unreachable exactly when a per-frame path was used.
#
# THE FAIL-SAFE CONTRACT IS THE SAME AS THE PAINTERS': any failure here logs and returns
# None, and the caller falls back to the behaviour it had yesterday. A missing frame, an
# unreadable PNG, a plate that would ship a black control — all downgrade, none abort.

_CTRL_GLOBS = ('ctrl_*.png', 'c_*.png', 'frame_*.png', '*.png')


def control_frames_in(control_dir):
    """The plate frames of a control directory, in render order.

    `vace_control.build` writes `ctrl_%05d.png`; `build_control_sequence` writes
    `c_%05d.png`; a Blender frames dir writes `frame_%05d.png`. All three are zero-padded,
    so sorted() IS render order — the same assumption node 13 makes when it reads the
    folder. A bare `*.png` fallback is last so an unpadded directory still works, badly
    and visibly, rather than silently."""
    import glob as _glob

    for pat in _CTRL_GLOBS:
        hits = sorted(_glob.glob(os.path.join(control_dir, pat)))
        if hits:
            return hits
    return []


def build_control_from_dir(
    control_dir, still_fit, out_dir, num_frames, size, mask_dir=None, mask_png=None, blend='mask', log_fn=None
):
    """Normalise an EXTERNAL folder of control frames into the run's ctrl dir.

    Same pad-or-truncate rule as build_mask_sequence (a short input_frames batch
    broadcast-errors inside vace_encode_frames hours in, so it is padded by repeating the
    last plate; a long one is truncated, as VACE would truncate it anyway).

    blend='mask'  (default) ctrl_t = still*(1-m_t) + plate_t*m_t — the plate replaces the
            flat grey 127 INSIDE the generate region and the set outside it stays hard
            per-frame control. This is the inpaint semantics the rest of the function is
            built on; a depth/skeleton plate is a full-frame raster on black, and handing
            that in raw would pin a black set.
    blend='raw'   the plate IS the control frame (geom/vace_control.py's "for a scene we
            render there is no homography to solve" case, where the plate already contains
            the whole scene). Guarded: a near-black result aborts back to the caller.

    Returns (ctrl_dir, {audit}) or (None, {reason}). Never a black or missing frame."""
    log = log_fn or _log_noop
    try:
        import numpy as _np

        W, H = int(size[0]), int(size[1])
        srcs = control_frames_in(control_dir)
        if not srcs:
            return None, {'reason': f'no control frames found in {control_dir}'}
        n_src = len(srcs)
        if n_src < num_frames:
            log(
                f'[ctrl-dir] WARNING: only {n_src} control frames for {num_frames} render '
                f'frames — padding with the last plate'
            )
        elif n_src > num_frames:
            log(f'[ctrl-dir] {n_src} control frames > {num_frames} render frames — truncating')
        seq_dir = os.path.join(out_dir, '_vace_ctrlseq')
        shutil.rmtree(seq_dir, ignore_errors=True)
        os.makedirs(seq_dir, exist_ok=True)
        still_arr = _np.asarray(Image.open(still_fit).convert('RGB').resize((W, H)), dtype=_np.float32)
        blend = 'raw' if str(blend).lower() == 'raw' else 'mask'
        static_m = None
        if blend == 'mask' and not mask_dir:
            if not (mask_png and os.path.isfile(mask_png)):
                return None, {'reason': 'blend=mask needs a mask (dir or png)'}
            static_m = (
                _np.asarray(Image.open(mask_png).convert('L').resize((W, H)), dtype=_np.float32)[:, :, None] / 255.0
            )
        greys, means, last_good = [], [], None
        for i in range(int(num_frames)):
            src = srcs[min(i, n_src - 1)]
            try:
                pl = Image.open(src).convert('RGB')
            except Exception as e:
                # never a missing frame: hold the previous plate, exactly as the pad rule
                if last_good is None:
                    return None, {'reason': f'first plate unreadable ({src}): {e}'}
                log(f'[ctrl-dir] frame {i} unreadable ({os.path.basename(src)}) — holding the previous plate')
                pl = Image.fromarray(last_good.astype('uint8'))
            if pl.size != (W, H):
                pl = pl.resize((W, H), Image.LANCZOS)
            p_arr = _np.asarray(pl, dtype=_np.float32)
            last_good = p_arr
            if blend == 'raw':
                c = p_arr
            else:
                if mask_dir:
                    mp = os.path.join(mask_dir, f'm_{i:05d}.png')
                    m = _np.asarray(Image.open(mp).convert('L'), dtype=_np.float32)[:, :, None] / 255.0
                else:
                    m = static_m
                c = still_arr * (1.0 - m) + p_arr * m
            greys.append(float((_np.abs(c - 127.0).max(axis=2) < 2.0).mean()))
            means.append(float(c.mean()))
            Image.fromarray(c.astype('uint8')).save(os.path.join(seq_dir, f'c_{i:05d}.png'))
        # BLACK-FRAME GUARD. A raw depth plate on a black background is the natural way to
        # ship an all-black control channel and have every log look normal.
        dark = [i for i, mv in enumerate(means) if mv < 4.0]
        if dark and float(still_arr.mean()) >= 4.0:
            return None, {
                'reason': f'{len(dark)} control frames are near-black (mean<4) while the still is not — refusing'
            }
        audit = {
            'frames': int(num_frames),
            'source_frames': n_src,
            'blend': blend,
            'grey_fraction_mean': round(sum(greys) / len(greys), 6),
            'grey_fraction_max': round(max(greys), 6),
            'luma_mean': round(sum(means) / len(means), 3),
        }
        log(
            f'[ctrl-dir] {control_dir} -> {seq_dir} ({num_frames} from {n_src} source, '
            f'{W}x{H}, blend={blend}); grey_fraction_mean {audit["grey_fraction_mean"]:.6f}'
        )
        if audit['grey_fraction_mean'] > 0.95:
            log(
                '[ctrl-dir] WARNING: the control channel is still ~constant grey — VACE '
                'will re-invent whatever lives there (geom/vace_control.audit semantics)'
            )
        return seq_dir, audit
    except Exception as e:
        return None, {'reason': f'{type(e).__name__}: {e}'}


def paint_control_frame(
    control_src,
    mask_png,
    props_out,
    char_out,
    prop_plates=None,
    char_painter=None,
    still_fit=None,
    log_fn=None,
    quiet=False,
):
    """Paint rigid prop plates and character geometry into ONE control frame.

    This is the single-image branch's painting block, lifted verbatim into a function so
    the per-frame path can call it for every frame. Returns the path of the control frame
    to use — the painted one, or `control_src` untouched when nothing painted. Never
    raises: each painter is independently fail-safe, as it was inline."""
    log = log_fn or _log_noop
    q = _log_noop if quiet else log
    src = control_src
    if prop_plates:
        try:
            from zyg_workflows import prop_control as _PROP

            _pc = _PROP.composite_into_control(
                src, prop_plates, props_out, mask_png=mask_png, log_fn=(_log_noop if quiet else log)
            )
            if _pc:
                src = _pc
                q(f'[vace] PROP CONTROL ON ({len(prop_plates)} plate(s)) -> {os.path.basename(_pc)}')
            else:
                q('[vace] prop plates produced nothing — neutral control kept')
        except Exception as _e:
            log(f'[vace] prop control FAILED ({_e}) — neutral control kept')
    if os.environ.get('ZYG_CHAR_GEOM_CTRL', '1') != '0':
        try:
            if char_painter is not None:
                _cg = char_painter.paint(src, mask_png, char_out)
            else:
                from zyg_workflows.geom import char_vace as _CHARGEOM

                _cg = _CHARGEOM.composite_char_geometry(
                    still_fit, src, mask_png, char_out, log_fn=(_log_noop if quiet else log)
                )
            if _cg:
                src = _cg
                q(f'[vace] CHAR GEOMETRY CONTROL ON -> {os.path.basename(_cg)}')
        except Exception as _e:
            log(f'[vace] char geometry control FAILED ({_e}) — control kept')
    return src


def paint_control_sequence(
    ctrl_dir, still_fit, out_dir, num_frames, mask_dir=None, mask_png=None, prop_plates=None, log_fn=None
):
    """Apply paint_control_frame to EVERY frame of a control sequence.

    Why this exists: `prop_plates` and ZYG_CHAR_GEOM_CTRL were `if neutral_control:` /
    single-image children, so in sequence mode — the one mode with per-frame control — no
    geometry was ever painted. Fail-safe: on any failure the ORIGINAL ctrl_dir is returned
    unchanged, so the run keeps the control frames it already had."""
    log = log_fn or _log_noop
    want_char = os.environ.get('ZYG_CHAR_GEOM_CTRL', '1') != '0'
    if not prop_plates and not want_char:
        return ctrl_dir, {'painted': 0, 'why': 'nothing to paint'}
    try:
        painter = None
        if want_char:
            from zyg_workflows.geom import char_vace as _CHARGEOM

            painter = _CHARGEOM.CharGeometryPainter(still_fit, log_fn=log)
            if not painter.ok:
                log(f'[char-geom] {painter.reason} — control frames left neutral')
                painter = None
                if not prop_plates:
                    return ctrl_dir, {'painted': 0, 'why': 'no character detected'}
        paint_dir = os.path.join(out_dir, '_vace_ctrlseq_painted')
        shutil.rmtree(paint_dir, ignore_errors=True)
        os.makedirs(paint_dir, exist_ok=True)
        tmp = os.path.join(out_dir, '_vace_paint_tmp')
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        painted = 0
        for i in range(int(num_frames)):
            fsrc = os.path.join(ctrl_dir, f'c_{i:05d}.png')
            if not os.path.isfile(fsrc):
                break
            mp = os.path.join(mask_dir, f'm_{i:05d}.png') if mask_dir else mask_png
            got = paint_control_frame(
                fsrc,
                mp,
                os.path.join(tmp, 'props.png'),
                os.path.join(tmp, 'char.png'),
                prop_plates=prop_plates,
                char_painter=painter,
                still_fit=still_fit,
                log_fn=log,
                quiet=(i > 0),
            )
            if i == 0 and painter is not None:
                painter.log = _log_noop  # one line per run, not one per frame
            dst = os.path.join(paint_dir, f'c_{i:05d}.png')
            shutil.copyfile(got, dst)
            if got != fsrc:
                painted += 1
        shutil.rmtree(tmp, ignore_errors=True)
        if painted == 0:
            log('[vace] per-frame painting changed nothing — keeping the plain sequence')
            shutil.rmtree(paint_dir, ignore_errors=True)
            return ctrl_dir, {'painted': 0, 'why': 'painters produced nothing'}
        log(
            f'[vace] PER-FRAME PAINTING: {painted}/{num_frames} control frames carry '
            f'geometry -> {os.path.basename(paint_dir)}'
        )
        return paint_dir, {'painted': painted, 'dir': paint_dir, 'props': bool(prop_plates), 'char': bool(painter)}
    except Exception as e:
        log(f'[vace] per-frame painting FAILED ({e}) — keeping the plain sequence')
        return ctrl_dir, {'painted': 0, 'why': f'{type(e).__name__}: {e}'}


def stamp_control_channel(out_dir, ctrl_dir, num_frames, detail, log_fn=None):
    """Record in the run's LOGBOOK what the control channel ACTUALLY was.

    geom/controls.runtime_stamp's rule: a value copied from config describes intent. The
    sha1 of the first and last control frame is the only thing that distinguishes 'the
    plate reached the render' from 'the plate was configured'."""
    log = log_fn or _log_noop
    try:
        import glob as _glob
        import hashlib
        import json

        def _sha1(p):
            h = hashlib.sha1(usedforsecurity=False)
            with open(p, 'rb') as fh:
                for blk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(blk)
            return h.hexdigest()

        if ctrl_dir and os.path.isdir(ctrl_dir):
            fr = sorted(_glob.glob(os.path.join(ctrl_dir, '*.png')))
        elif ctrl_dir and os.path.isfile(ctrl_dir):
            fr = [ctrl_dir]  # single control image: first and last are the same
        else:
            fr = []
        det = dict(detail or {})
        det.update(
            {
                'ctrl_dir': ctrl_dir,
                'ctrl_frames_on_disk': len(fr),
                'num_frames': int(num_frames),
                'sha1_first': _sha1(fr[0]) if fr else None,
                'sha1_last': _sha1(fr[-1]) if fr else None,
            }
        )
        try:
            from zyg_workflows.geom import controls as _C

            stamp = _C.runtime_stamp('vace control channel', **det)
        except Exception:
            stamp = {'what_ran': 'vace control channel', 'detail': det}
        with open(os.path.join(out_dir, '_vace_control_stamp.json'), 'w') as fh:
            json.dump(stamp, fh, indent=1)
        try:
            from zyg_workflows import run_logbook as _RL

            _RL.record_metrics(out_dir, {'control': det}, source='vace.control_channel', log_fn=log)
        except Exception as e:
            log(f'[ctrl-stamp] logbook not written ({e}) — stamp json kept')
        log(
            f'[ctrl-stamp] control={det.get("mode")} frames={det["ctrl_frames_on_disk"]} '
            f'sha1[0]={str(det["sha1_first"])[:12]} sha1[-1]={str(det["sha1_last"])[:12]}'
        )
        return stamp
    except Exception as e:
        log(f'[ctrl-stamp] FAILED ({e}) — render is unaffected')
        return None
