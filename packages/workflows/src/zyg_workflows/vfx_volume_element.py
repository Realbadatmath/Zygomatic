#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""VFX volume ELEMENTS — render a VDB pack as something you can composite.

`vfx_volume_preview` answers "which explosion is this?" and answers it with a
720p opaque clip, because that is what browsing fifteen packs needs. This module
answers the other question — "put that dust in my shot" — and nothing about the
preview shape survives contact with it:

  resolution  The preview is 720 tall. This renders 3840 WIDE.
  alpha       The preview is matted onto a near-black world. An element carries
              its own coverage, so the render is `film_transparent` RGBA and the
              delivery formats are the two that can hold an alpha channel.
  framing     The preview camera fits a sphere of radius = half the bounding-box
              DIAGONAL. Safe, and ruinous here: Dust Shockwave's bounds are
              1127 x 1103 x 143 units — a pancake — so that fit put 353 of 2160
              rows on the element and a "4K" pass would have delivered 1233 px
              of dust, no better than the vendor's 1080p turntable. `fit:
              element` in the Blender half projects the bounds across the
              sequence and frames THAT, and the output height is the element's
              own aspect rather than a forced 16:9. Measured on Dust Shockwave:
              1233x353 -> 2620x748, 4.5x the pixels for less render time.
  view        AgX exists in the preview path because fire is an HDR emitter that
              clips to white under Standard. An element is graded downstream, so
              a density-only pack renders Standard and keeps its own values.

Two deliverables, because no single file does both jobs:

    <slug>_4k.webm   VP9 / yuva420p — what the Inspection pane can actually
                     PLAY with transparency. H.264 has no alpha channel, which
                     is the whole reason this is not an .mp4; `.webm` was
                     already in the server's extension allowlist.
    <slug>_4k.mov    ProRes 4444 / yuva444p10le — the compositing master, 10-bit
                     alpha, one file, opens in any NLE.

The PNG RGBA sequence both are built from is kept only if --keep-frames: it is
the true master but it is ~155 files, and everything downstream of here reads
one of the two containers.

**The alpha is VERIFIED after encoding, not assumed.** libvpx will accept
`-pix_fmt yuva420p`, drop the alpha plane, and exit 0 if `-auto-alt-ref` is
left on; the result plays, looks right against a dark pane, and is silently
opaque. So a frame is decoded back out of the finished file and its alpha
channel must actually vary. Same reason the extraction path counts non-empty
frames instead of counting files.

Usage
    python3 vfx_volume_element.py --pack DustShockwaveVDB.zip
    python3 vfx_volume_element.py --pack Fire_01.rar --width 2560 --samples 96
    python3 vfx_volume_element.py --pack DustShockwaveVDB.zip \
        --frames /path/to/already/rendered   # skip the render, encode + commit
"""

from __future__ import annotations

import argparse
import glob
import logging as _zyg_logging
import json
import os
import shutil
import subprocess
import sys
import tempfile
from zyg_workflows.bin import exe

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_workflows import vfx_ingest as VI  # noqa: E402
from zyg_workflows import vfx_volume_preview as PV  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

LIBS = VI.LIBS
CAT = 'vfx_volumes'
WIDTH = 3840  # "4K" is a WIDTH here; the height is the element's own
SAMPLES = 128  # the preview path uses 64 — this one is delivered
# Stops, applied before the view transform. NOT zero, and not a taste setting:
# `setup_lights` was built against AgX, whose highlight rolloff hides how hot
# the key/fill/rim rig actually is. Under 'Standard' that rig blows a smoke-only
# pack out — Dust Shockwave's first element pass measured 59.3% of its pixels at
# pure 255, a featureless white slab with nothing left to grade. -1.5 measured
# 0.0% clipped on the same frame while staying bright. A pack whose rig differs
# (an emissive fire pack lights itself and its rig drops to a tenth) may want
# another value, which is why CLIP_MAX below fails the build instead of trusting
# this default to be right everywhere.
EXPOSURE = -1.5
CLIP_MAX = 2.0  # % of element pixels allowed at pure white
# Per-channel gain applied at ENCODE time, not render time. Legitimate because
# this volume has no emission: every pixel is light x albedo, so re-tinting the
# finished frames and re-lighting the render are the same multiply. It buys a
# 3-minute regrade instead of a 70-minute re-render — but ONLY for hue and
# level. Camera angle, light DIRECTION and shadow are baked and cannot be
# recovered here.
#   Dust Shockwave: the vendor's own EmberGen render is warm sand (R/G 1.217,
#   B/G 0.846); this rig is neutral-to-cool (0.998 / 1.039) because the preview
#   fill and rim lights are blue, to separate grey dust from a dark pane. The
#   hue ratios below are the vendor's, measured; the 0.90 that scales them is
#   the largest level that keeps clipping under 1% (10.25% at k=1.00).
GRADES = {'vendor': (1.220 * 0.90, 1.000 * 0.90, 0.815 * 0.90)}
BLENDER_SCRIPT = os.path.join(HERE, 'vfx_volume_render.py')


def log(m):
    _zyg_log.info(m)


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def pack_fps(rec) -> str:
    """These packs are NOT all 30fps and the element must not resample them.

    Dust Shockwave is 29.97, Grenade Dust Impact is 45 and Tornado Looping is
    24 — encoding every pack at a hardcoded 30000/1001 stretches or squeezes
    the sim and silently changes how fast the effect moves. The vendor preview
    already sitting in the library is the authority; the record's frames over
    its duration is the fallback for a pack built by our own render, where the
    two agree by construction."""
    pv = rec.get('preview')
    if pv:
        fp = os.path.join(LIBS, CAT, pv)
        if os.path.exists(fp):
            f = float(VI.probe(fp).get('fps') or 0)
            if f > 0:
                return f'{round(f * 1000)}/1000' if abs(f - round(f)) > 1e-3 else str(int(round(f)))
    n = int(rec.get('frames') or 0)
    d = float(rec.get('preview_dur') or 0)
    if n and d:
        return str(int(round(n / d)))
    return '30000/1001'


# ── render ─────────────────────────────────────────────────────────────────
def render_frames(
    archive: str, members: list, workdir: str, out: str, width=WIDTH, samples=SAMPLES, exposure=EXPOSURE
) -> int:
    """Extract the pack's VDBs and render the element pass. Frames are renamed
    to a zero-padded run for the same reason the preview path does it: EmberGen
    numbers `_0 … _100`, which sorts 0,1,10,100,11 as text."""
    seq = os.path.join(workdir, 'seq')
    os.makedirs(seq, exist_ok=True)
    got = PV.extract_members(archive, members, seq)
    got.sort(key=PV._frame_no)
    for i, fp in enumerate(got):
        os.rename(fp, os.path.join(seq, 'f_%04d.vdb' % i))
    os.makedirs(out, exist_ok=True)
    cfg = {
        'seq': seq,
        'n': len(got),
        'out': out + os.sep,
        'w': width,
        'h': int(width * 9 / 16),
        'samples': samples,
        'alpha': True,
        'view': 'Standard',
        'fit': 'element',
        'depth': 16,
        'exposure': exposure,
    }
    log(f'  blender: {len(got)} frame(s), {width} wide, alpha, element fit…')
    r = _run([PV.blender_bin(), '-b', '-P', BLENDER_SCRIPT, '--', json.dumps(cfg)])
    if r.returncode != 0:
        raise RuntimeError(f'blender failed ({r.returncode}): {r.stdout[-600:]}')
    for ln in r.stdout.splitlines():
        if ln.startswith('[render]'):
            log('   ' + ln)
    return len(got)


def frame_list(frames: str) -> list:
    """The rendered frames, verified CONTIGUOUS.

    ffmpeg reads the sequence as `f_%04d.png` from a start number, so a hole in
    the middle does not error — it ends the encode early and hands back a short
    clip that plays perfectly. A render killed and restarted, or a stray delete,
    leaves exactly that. Cheap to check, invisible if not."""
    pngs = sorted(glob.glob(os.path.join(frames, '*.png')), key=PV._frame_no)
    if not pngs:
        raise RuntimeError(f'no rendered frames in {frames}')
    nums = [PV._frame_no(p)[0] for p in pngs]
    missing = sorted(set(range(nums[0], nums[-1] + 1)) - set(nums))
    if missing:
        raise RuntimeError(
            f'{len(missing)} frame(s) missing from {frames} between '
            f'{nums[0]} and {nums[-1]} (first: {missing[0]}) — the encode '
            f'would silently stop at the gap'
        )
    return pngs


def frame_shape(png: str) -> tuple:
    from PIL import Image

    with Image.open(png) as im:
        return im.size


# ── encode ─────────────────────────────────────────────────────────────────
def solve_vendor_grade(pngs: list, rec: dict, fps: str, probes=5, limit=1.0) -> tuple:
    """Derive the per-channel gain that puts our render on the vendor's hue.

    Legitimate for the same reason the fixed grades are: no emission, so colour
    is a multiply. What is NOT assumed is the number — it is measured off the
    pack's own preview, frame-paired with ours, so each pack gets its own.

    Two separate things are solved, in this order:
      hue    the ratios R/G and B/G the vendor renders, divided by the ones we
             render. This is what actually matches the look.
      level  a single scale on all three, chosen as the LARGEST that keeps
             clipping within `limit`. Matching the vendor's absolute brightness
             is explicitly not the goal: their render is opaque over black and
             ours is a matte, and pushing to their luma clipped 10.25% of Dust
             Shockwave. Hue is what the eye reads as "the same dust"; level is
             what you have left to grade with.
    """
    from PIL import Image

    pv = rec.get('preview')
    src = os.path.join(LIBS, CAT, pv) if pv else ''
    if not src or not os.path.exists(src):
        raise RuntimeError('no vendor preview to match against')
    fnum, fden = (fps.split('/') + ['1'])[:2]
    rate = float(fnum) / float(fden)
    step = max(1, len(pngs) // (probes + 1))
    idx = [i for i in range(step, len(pngs) - 1, step)][:probes]
    tmp = tempfile.mkdtemp(prefix='vgrade_')
    mine = [0.0, 0.0, 0.0]
    vend = [0.0, 0.0, 0.0]
    npairs = 0
    try:
        for i in idx:
            with Image.open(pngs[i]) as im:
                im = im.convert('RGBA')
                px = im.load()
                w, h = im.size
                n = 0
                acc = [0, 0, 0]
                for y in range(0, h, 4):
                    for x in range(0, w, 4):
                        r, g, b, a = px[x, y]
                        if a < 200:
                            continue
                        acc[0] += r
                        acc[1] += g
                        acc[2] += b
                        n += 1
            if n < 500:
                continue
            t = PV._frame_no(pngs[i])[0] / rate
            vp = os.path.join(tmp, 'v_%04d.png' % i)
            r_ = _run([exe('ffmpeg'), '-y', '-v', 'error', '-ss', f'{t:.3f}', '-i', src, '-frames:v', '1', vp])
            if r_.returncode != 0 or not os.path.exists(vp):
                continue
            with Image.open(vp) as vi:
                vi = vi.convert('RGB')
                vpx = vi.load()
                vw, vh = vi.size
                vn = 0
                vacc = [0, 0, 0]
                for y in range(0, vh, 2):
                    for x in range(0, vw, 2):
                        r, g, b = vpx[x, y]
                        if (r + g + b) / 3 < 40:  # vendor mattes on black
                            continue
                        vacc[0] += r
                        vacc[1] += g
                        vacc[2] += b
                        vn += 1
            if vn < 500:
                continue
            for c in range(3):
                mine[c] += acc[c] / n
                vend[c] += vacc[c] / vn
            npairs += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if npairs < 2:
        raise RuntimeError(f'only {npairs} usable frame pair(s) — cannot measure the vendor hue')
    mine = [c / npairs for c in mine]
    vend = [c / npairs for c in vend]
    hue = ((vend[0] / vend[1]) / (mine[0] / mine[1]), 1.0, (vend[2] / vend[1]) / (mine[2] / mine[1]))
    log(
        f'  vendor hue R/G {vend[0] / vend[1]:.3f} B/G {vend[2] / vend[1]:.3f}  |  '
        f'ours R/G {mine[0] / mine[1]:.3f} B/G {mine[2] / mine[1]:.3f}  '
        f'({npairs} frame pairs)'
    )

    # level: largest k whose clipping stays within limit, measured on real px
    samples = []
    for i in idx[:3]:
        with Image.open(pngs[i]) as im:
            im = im.convert('RGBA')
            px = im.load()
            w, h = im.size
            for y in range(0, h, 8):
                for x in range(0, w, 8):
                    r, g, b, a = px[x, y]
                    if a < 40:
                        continue
                    samples.append((r, g, b))
    best = None
    for k in [x / 100 for x in range(100, 49, -2)]:
        clip = sum(1 for r, g, b in samples if r * hue[0] * k >= 255 or g * hue[1] * k >= 255 or b * hue[2] * k >= 255)
        pct = clip / len(samples) * 100 if samples else 0
        if pct <= limit:
            best = (k, pct)
            break
    if not best:
        raise RuntimeError('no level kept clipping within the limit')
    k, pct = best
    gains = tuple(c * k for c in hue)
    log(
        f'  solved grade: hue R{hue[0]:.3f} B{hue[2]:.3f} x level {k:.2f} '
        f'-> R{gains[0]:.3f} G{gains[1]:.3f} B{gains[2]:.3f} ({pct:.2f}% clip)'
    )
    return gains, {'hue': hue, 'level': k, 'clip_pct': round(pct, 2)}


def _grade_filter(gains) -> list:
    """`colorchannelmixer` in the rgba domain, before the yuv conversion, so the
    multiply happens on straight (unpremultiplied) colour — which is what
    Blender writes and what makes the tint equivalent to re-lighting.

    **rgba64, not rgba**: the render master is written at `depth: 16` and comes
    off disk as rgba64be, so `format=rgba` quantises to 8 bits BEFORE the
    multiply and throws away everything a downward grade needs. Invisible near
    unity gain and irrelevant to the webm (8-bit either way), but a black pass
    at x0.10 landed on 26 code values where the master holds 6063 — and the
    ProRes master is 10-bit, so it could have carried them. Measured after the
    fix: 5388. The file played, the alpha verified and the clip gate read 0.00%
    throughout, which is why this had to be measured to be seen."""
    if not gains:
        return []
    r, g, b = gains
    return ['-vf', f'format=rgba64,colorchannelmixer=rr={r:.4f}:gg={g:.4f}:bb={b:.4f}']


def encode_webm(frames: list, out: str, fps: str, gains=None) -> None:
    """VP9 + alpha. `-auto-alt-ref 0` is NOT optional — libvpx silently drops
    the alpha plane with alt-ref frames on, and still exits 0."""
    first = frames[0]
    pat = os.path.join(os.path.dirname(first), os.path.basename(first).rsplit('_', 1)[0] + '_%04d.png')
    start = PV._frame_no(first)[0]
    r = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-framerate',
            fps,
            '-start_number',
            str(start),
            '-i',
            pat,
            *_grade_filter(gains),
            '-c:v',
            'libvpx-vp9',
            '-pix_fmt',
            'yuva420p',
            '-auto-alt-ref',
            '0',
            '-crf',
            '26',
            '-b:v',
            '0',
            '-row-mt',
            '1',
            '-threads',
            '16',
            '-deadline',
            'good',
            '-cpu-used',
            '2',
            '-an',
            out,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f'vp9 encode failed: {r.stderr[-400:]}')


def encode_prores(frames: list, out: str, fps: str, gains=None) -> None:
    """ProRes 4444 — profile 4 is the one with an alpha channel."""
    first = frames[0]
    pat = os.path.join(os.path.dirname(first), os.path.basename(first).rsplit('_', 1)[0] + '_%04d.png')
    start = PV._frame_no(first)[0]
    r = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-framerate',
            fps,
            '-start_number',
            str(start),
            '-i',
            pat,
            *_grade_filter(gains),
            '-c:v',
            'prores_ks',
            '-profile:v',
            '4444',
            '-pix_fmt',
            'yuva444p10le',
            '-alpha_bits',
            '16',
            '-vendor',
            'apl0',
            '-an',
            out,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f'prores encode failed: {r.stderr[-400:]}')


def verify_clipping(pngs: list, probes=7) -> dict:
    """How much of the element is burned to pure white, sampled across the run.

    An element that clips is not a look, it is missing data: 255,255,255 cannot
    be graded back down into billows, and the pane shows a white slab. The alpha
    check upstream cannot see this at all — a fully blown frame still has a
    perfect matte, which is exactly how the first pass got as far as playing in
    the browser before anyone noticed."""
    from PIL import Image

    step = max(1, len(pngs) // probes)
    worst = {'pct': -1.0}
    tot_all = clip_all = 0
    for fp in pngs[::step]:
        with Image.open(fp) as im:
            im = im.convert('RGBA')
            px = im.load()
            w, h = im.size
            tot = clip = 0
            for y in range(0, h, 4):
                for x in range(0, w, 4):
                    r, g, b, a = px[x, y]
                    if a < 40:
                        continue
                    tot += 1
                    if r >= 254 and g >= 254 and b >= 254:
                        clip += 1
        if not tot:
            continue
        pct = clip / tot * 100.0
        tot_all += tot
        clip_all += clip
        if pct > worst['pct']:
            worst = {'pct': pct, 'frame': os.path.basename(fp)}
    overall = (clip_all / tot_all * 100.0) if tot_all else 0.0
    if worst['pct'] > CLIP_MAX:
        raise RuntimeError(
            f'{worst["pct"]:.1f}% of the element is clipped to pure white on '
            f'{worst["frame"]} (limit {CLIP_MAX}%) — lower --exposure and '
            f'render again; a blown element cannot be graded back'
        )
    return {
        'worst_pct': round(worst['pct'], 2),
        'worst_frame': worst.get('frame', ''),
        'overall_pct': round(overall, 2),
    }


def verify_alpha(path: str, at=0.5) -> dict:
    """Decode a frame back OUT of the finished file and prove the alpha channel
    survived and varies. An encoder that dropped it produces a file that plays,
    looks correct on a dark pane, and is uniformly opaque."""
    p = VI.probe(path)
    dur = float(p.get('dur') or 0)
    # VP9 carries alpha as a SEPARATE track (the container's `alpha_mode=1`),
    # and ffmpeg's NATIVE vp9 decoder ignores it: it reports the stream as
    # yuv420p and hands back a fully opaque frame. Decoding a known-good file
    # that way reads exactly like an encoder that dropped the alpha, so the
    # decoder is pinned to libvpx, which does reconstruct it. (Measured: the
    # same file reads alpha 255-255 through the native decoder and 0-255,
    # 79.6% transparent, through libvpx.)
    dec = ['-c:v', 'libvpx-vp9'] if path.lower().endswith('.webm') else []
    tmp = tempfile.mkdtemp(prefix='alphaverify_')
    try:
        png = os.path.join(tmp, 'probe.png')
        r = _run(
            [exe('ffmpeg'), '-y', '-v', 'error']
            + dec
            + ['-i', path, '-ss', f'{dur * at:.2f}', '-frames:v', '1', '-pix_fmt', 'rgba', png]
        )
        if r.returncode != 0 or not os.path.exists(png):
            raise RuntimeError(f'could not decode a frame back: {r.stderr[-300:]}')
        from PIL import Image

        with Image.open(png) as im:
            if im.mode != 'RGBA':
                raise RuntimeError(f'decoded frame is {im.mode}, not RGBA — the alpha channel did not survive encoding')
            al = im.getchannel('A')
            lo, hi = al.getextrema()
            h = al.histogram()
            tot = sum(h)
            clear = h[0] / tot
            opaque = sum(h[254:]) / tot
            # Clipping is measured AGAIN here, on the encoded file, because
            # verify_clipping upstream reads the ungraded master: a --grade
            # that pushes a channel over 255 would otherwise ship unchecked.
            px = im.load()
            w, hh = im.size
            ntot = nclip = 0
            for y in range(0, hh, 4):
                for x in range(0, w, 4):
                    r, g, b, a = px[x, y]
                    if a < 40:
                        continue
                    ntot += 1
                    if r >= 254 and g >= 254 and b >= 254:
                        nclip += 1
            clipped = (nclip / ntot * 100.0) if ntot else 0.0
        if lo == hi:
            raise RuntimeError(
                f'alpha is CONSTANT at {lo} in {os.path.basename(path)} — the element is a solid card, not a matte'
            )
        if clear < 0.02:
            raise RuntimeError(
                f'only {clear * 100:.1f}% of the frame is transparent — this does not look like a keyed element'
            )
        if clipped > CLIP_MAX:
            raise RuntimeError(
                f'{clipped:.1f}% of {os.path.basename(path)} is clipped to pure '
                f'white after encoding (limit {CLIP_MAX}%) — the grade is too '
                f'hot; lower its level in GRADES'
            )
        return {
            'w': p.get('w'),
            'h': p.get('h'),
            'dur': dur,
            'alpha_min': lo,
            'alpha_max': hi,
            'clipped': round(clipped, 2),
            'clear': round(clear * 100, 1),
            'opaque': round(opaque * 100, 1),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── build ──────────────────────────────────────────────────────────────────
def build(
    pack: str,
    width=WIDTH,
    samples=SAMPLES,
    frames_dir=None,
    keep_frames=None,
    prores=True,
    force=False,
    exposure=EXPOSURE,
    grade=None,
) -> dict:
    meta = VI.load_sidecar()
    key = f'{CAT}/{pack}'
    rec = meta.get(key)
    if not rec:
        cand = [k for k in meta if k.startswith(CAT + '/') and pack.lower() in k.lower()]
        if len(cand) != 1:
            raise SystemExit(f'no single volume pack matches {pack!r} (candidates: {cand or "none"})')
        key = cand[0]
        rec = meta[key]
    fn = rec['file']
    slug = PV._slug(os.path.splitext(fn)[0])
    fps = pack_fps(rec)
    out_webm = os.path.join(LIBS, CAT, f'{slug}_4k.webm')
    out_mov = os.path.join(LIBS, CAT, f'{slug}_4k.mov')
    if rec.get('element') and os.path.exists(out_webm) and not force:
        log(f'{rec["name"]}: element already built — {rec["element"]}')
        return {'ok': True, 'skipped': True}

    log(f'{rec["name"]}  ({fn})  {fps} fps')
    work = None
    try:
        if frames_dir:
            log(f'  using rendered frames in {frames_dir}')
        else:
            archive = os.path.join(LIBS, rec['master']) if not os.path.isabs(rec['master']) else rec['master']
            if not os.path.exists(archive):
                archive = os.path.join(os.path.dirname(LIBS), rec['master'])
            members = [m for m in PV.list_archive(archive) if m.lower().endswith('.vdb')]
            if not members:
                raise RuntimeError('pack holds no .vdb members')
            work = tempfile.mkdtemp(prefix='vfxel_')
            frames_dir = os.path.join(work, 'frames')
            render_frames(archive, members, work, frames_dir, width, samples)

        pngs = frame_list(frames_dir)
        w, h = frame_shape(pngs[0])
        log(f'  {len(pngs)} frame(s) at {w}x{h} RGBA')
        c = verify_clipping(pngs)
        log(
            f'  clipping: {c["overall_pct"]}% overall, worst {c["worst_pct"]}% '
            f'on {c["worst_frame"]} (limit {CLIP_MAX}%)'
        )

        if grade == 'match':
            gains, ginfo = solve_vendor_grade(pngs, rec, fps)
        else:
            gains = GRADES.get(grade) if grade else None
            ginfo = None
            if grade and not gains:
                raise SystemExit(f'unknown grade {grade!r} (have: match, {sorted(GRADES)})')
        if gains:
            log(f'  grade {grade!r}: R x{gains[0]:.3f} G x{gains[1]:.3f} B x{gains[2]:.3f}')
        log('  encoding VP9 + alpha (webm)…')
        encode_webm(pngs, out_webm, fps, gains)
        v = verify_alpha(out_webm)
        log(
            f'   webm {v["w"]}x{v["h"]} {v["dur"]:.2f}s  alpha {v["alpha_min"]}-'
            f'{v["alpha_max"]}  clear {v["clear"]}%  opaque {v["opaque"]}%  '
            f'clipped {v["clipped"]}%'
        )

        mov_bytes = 0
        if prores:
            log('  encoding ProRes 4444 (mov)…')
            encode_prores(pngs, out_mov, fps, gains)
            m = verify_alpha(out_mov)
            mov_bytes = os.path.getsize(out_mov)
            log(
                f'   mov  {m["w"]}x{m["h"]}  alpha {m["alpha_min"]}-{m["alpha_max"]}'
                f'  clear {m["clear"]}%  ({PV_size(mov_bytes)})'
            )

        if keep_frames:
            os.makedirs(keep_frames, exist_ok=True)
            for p in pngs:
                shutil.copy2(p, os.path.join(keep_frames, os.path.basename(p)))
            log(f'  kept {len(pngs)} RGBA frame(s) in {keep_frames}')

        rec = dict(rec)
        rec['element'] = os.path.basename(out_webm)
        rec['element_w'] = int(v['w'] or w)
        rec['element_h'] = int(v['h'] or h)
        rec['element_bytes'] = os.path.getsize(out_webm)
        rec['element_master'] = os.path.basename(out_mov) if mov_bytes else ''
        rec['element_frames'] = len(pngs)
        rec['element_grade'] = grade or ''
        if ginfo:
            rec['element_grade_gains'] = [round(g, 4) for g in gains]
        rec.pop('element_error', None)
        PV.commit(key, rec)
        log(
            f'  committed: element={rec["element"]} '
            f'({rec["element_w"]}x{rec["element_h"]}, {PV_size(rec["element_bytes"])})'
        )
        return {'ok': True, 'element': rec['element'], 'verify': v}
    except Exception as e:  # noqa: BLE001
        rec = dict(rec)
        rec['element_error'] = f'{type(e).__name__}: {e}'[:300]
        PV.commit(key, rec)
        log(f'  FAILED: {rec["element_error"]}')
        raise
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)


def PV_size(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return f'{n:.0f}{u}' if u == 'B' else f'{n:.1f}{u}'
        n /= 1024.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pack', required=True, help='archive name or a unique fragment of it')
    ap.add_argument('--width', type=int, default=WIDTH)
    ap.add_argument('--samples', type=int, default=SAMPLES)
    ap.add_argument(
        '--exposure', type=float, default=EXPOSURE, help='stops before the view transform (default %(default)s)'
    )
    ap.add_argument('--frames', default=None, help='use an already-rendered RGBA png sequence')
    ap.add_argument('--keep-frames', default=None, help='copy the RGBA png master into this dir')
    ap.add_argument('--no-prores', action='store_true')
    ap.add_argument(
        '--grade', default=None, choices=['match'] + sorted(GRADES), help='per-channel gain applied at encode time'
    )
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    build(
        a.pack,
        width=a.width,
        samples=a.samples,
        frames_dir=a.frames,
        keep_frames=a.keep_frames,
        prores=not a.no_prores,
        force=a.force,
        exposure=a.exposure,
        grade=a.grade,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
