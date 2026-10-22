#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""VFX volume previews — give the Volumes rail something the preview pane can PLAY.

The Plates category plays (it is video) and the Sprites category draws (it is
image); Volumes was the one kind with nothing to show, because a VDB pack is a
render input, not a clip.  The preview pane said so in words:

    "Render it in Blender/Houdini; there are no frames to play here."

True, and useless — you cannot pick an explosion out of fifteen packs by reading
their file sizes.  This module makes the render happen ONCE, ahead of time, and
caches a small mp4 next to the library so the pane plays a volume like anything
else.  The masters in ``_originals/`` are never modified and never extracted
except into a temp dir that is deleted on the way out.

Two sources, in this order — a vendor render always beats ours:

  vendor  Nine of the fifteen JangaFX packs ship EmberGen's OWN turntable mp4
          inside the archive (``smallCampfire/smallCampfire.mp4``).  It is the
          same CC0 licence as the volumes, it is H.264/yuv420p already, and it
          is a better render than a 30-second Cycles pass will ever be.  Extract
          it, normalise it, done — seconds, not minutes.
  render  The six older (.rar) packs ship no preview.  Those get extracted to a
          temp dir and rendered with Blender/Cycles on the GPU: a fixed
          three-quarter camera framed on the simulation's own bounds, one pass
          over the frame sequence, encoded to the same shape as a vendor clip.

**The .rar packs need `unrar`.**  p7zip lists RAR5 but cannot decode it — it
extracts 101 zero-byte files and reports "Sub items Errors", which is exactly
the kind of plausible-looking success that has bitten this library before.  So
extraction VERIFIES: every frame must be non-empty or the build fails loudly.
``unrar`` is looked up on PATH, then ``~/.local/bin``, then the sabnzbd snap.
This box had none installed and no passwordless sudo, so the binary at
``~/.local/bin/unrar`` was built from rarlab's own ``unrarsrc-7.0.9.tar.gz``
(plain ``make``, no dependencies). The snap copy is a fallback and deliberately
not the first choice — its path carries a snap revision that changes under it.

Outputs, written into the ``vfx_volumes`` library dir so the existing
``/inspect/vfx/asset`` route serves them under its existing containment rules:

    <slug>.mp4   the preview, H.264 yuv420p, <=720 tall, +faststart
    <slug>.jpg   a poster frame

and two sidecar fields on the pack's record: ``preview`` and ``poster``, plus
``preview_src`` (vendor|render) so the caption can say which it is looking at.

Usage
    python3 vfx_volume_preview.py --all              # build everything missing
    python3 vfx_volume_preview.py --pack Fire_01.rar # one pack
    python3 vfx_volume_preview.py --all --force      # rebuild even if present
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile

from zyg_workflows import vfx_ingest as VI
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = VI.LIBS
ORIG = VI.ORIG
VOLDIR = os.path.join(LIBS, 'vfx_volumes')

# Preview shape. Small on purpose: this is a browse-and-pick clip, not the
# element you composite — that is what the 32 GB of masters are for.
PV_HEIGHT = 720  # vendor clips are downscaled to this if taller
RENDER_W, RENDER_H = 1280, 720  # rendered wide, then cropped to the element
OUT_W, OUT_H = 854, 480  # what the preview pane actually gets
RENDER_SAMPLES = 64
RENDER_FPS = 24
MAX_RENDER_FRAMES = 160  # a longer sim is strided, never truncated
CROP_MARGIN = 0.10  # of the measured element box, per side
VENDOR_EXT = ('.mp4', '.mov', '.webm')


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _slug(name: str) -> str:
    base = re.sub(r'\.(zip|rar|7z)$', '', name, flags=re.I)
    return re.sub(r'[^a-z0-9]+', '_', base.lower()).strip('_') or 'volume'


# ── archive access ─────────────────────────────────────────────────────────
def unrar_bin() -> str:
    """The one tool that can actually decode these RAR5 archives.

    p7zip *lists* them and then extracts zero-byte files, so this is not
    interchangeable with `7z x` and the caller must not silently fall back."""
    cand = [shutil.which('unrar'), shutil.which('unrar-free'), os.path.expanduser('~/.local/bin/unrar')]
    cand += sorted(__import__('glob').glob('/snap/sabnzbd/*/usr/bin/unrar'), reverse=True)
    for c in cand:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ''


def list_archive(path: str) -> list:
    """Member names, listing only. zipfile for .zip, `7z l` for .rar — p7zip
    reads RAR headers fine, it is only decoding that it cannot do."""
    low = path.lower()
    if low.endswith('.zip'):
        try:
            with zipfile.ZipFile(path) as zf:
                return [i.filename for i in zf.infolist() if not i.is_dir()]
        except (OSError, zipfile.BadZipFile):
            return []
    r = _run(['7z', 'l', '-ba', '-slt', path])
    if r.returncode != 0:
        return []
    return [ln[7:].strip() for ln in r.stdout.splitlines() if ln.startswith('Path = ')]


def extract_members(path: str, members: list, dest: str) -> list:
    """Extract exactly these members into `dest` (flattened). Returns the list
    of extracted paths, and RAISES if any of them came out empty — the p7zip
    RAR5 failure mode writes a full set of zero-byte files and exits 2, which
    reads as success to anything that only counts files."""
    os.makedirs(dest, exist_ok=True)
    low = path.lower()
    out = []
    if low.endswith('.zip'):
        with zipfile.ZipFile(path) as zf:
            for m in members:
                fp = os.path.join(dest, os.path.basename(m))
                with zf.open(m) as src, open(fp, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                out.append(fp)
    else:
        ub = unrar_bin()
        if not ub:
            raise RuntimeError(
                'no unrar available — p7zip cannot decode RAR5 (it writes '
                'zero-byte files). Put an `unrar` binary on PATH or in '
                '~/.local/bin.'
            )
        # `e` flattens; -inul silences; members are passed verbatim.
        r = _run([ub, 'e', '-y', '-inul', path] + list(members) + [dest + os.sep])
        if r.returncode != 0:
            raise RuntimeError(f'unrar failed ({r.returncode}): {r.stderr[-300:]}')
        for m in members:
            fp = os.path.join(dest, os.path.basename(m))
            out.append(fp)
    missing = [p for p in out if not os.path.isfile(p) or os.path.getsize(p) == 0]
    if missing:
        raise RuntimeError(
            f'{len(missing)}/{len(out)} extracted members are missing or empty (first: {os.path.basename(missing[0])})'
        )
    return out


# ── source 1: the vendor's own render, shipped inside the archive ──────────
def vendor_clip(members: list) -> str:
    vids = [m for m in members if m.lower().endswith(VENDOR_EXT)]
    if not vids:
        return ''
    # Prefer the one named after the pack folder over any secondary clip.
    vids.sort(key=lambda m: (len(m.split('/')), len(m)))
    return vids[0]


def normalise_video(src: str, out_mp4: str, out_jpg: str) -> dict:
    """One H.264/yuv420p/faststart shape for every preview, whatever came in."""
    vf = f'scale=-2:min({PV_HEIGHT}\\,ih)'
    r = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-i',
            src,
            '-vf',
            vf,
            '-c:v',
            'libx264',
            '-crf',
            '23',
            '-preset',
            'veryfast',
            '-pix_fmt',
            'yuv420p',
            '-an',
            '-movflags',
            '+faststart',
            out_mp4,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out_mp4):
        raise RuntimeError(f'ffmpeg normalise failed: {r.stderr[-300:]}')
    p = VI.probe(out_mp4)
    if not p.get('w') or not p.get('dur'):
        raise RuntimeError(f'normalised clip has no video stream or no duration: {p}')
    # Poster from ~40% in: frame 0 of an explosion is an empty box.
    ss = max(0.0, (p.get('dur') or 0) * 0.4)
    _run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-ss',
            f'{ss:.2f}',
            '-i',
            out_mp4,
            '-frames:v',
            '1',
            '-vf',
            'scale=480:-2',
            out_jpg,
        ]
    )
    return p


# ── source 2: render the volumes ourselves ─────────────────────────────────
BLENDER_SCRIPT = os.path.join(HERE, 'vfx_volume_render.py')


def blender_bin() -> str:
    return shutil.which('blender') or '/usr/local/bin/blender'


def render_pack(archive: str, members: list, workdir: str, out_mp4: str, out_jpg: str, log=print) -> dict:
    """Extract the VDB sequence, render it, encode it.

    Frames are RENAMED to a zero-padded run on extraction. EmberGen's own
    numbering is `_0 … _100` — unpadded, so it sorts 0,1,10,100,11 as text and
    Blender's sequence detection has to guess at the width. Padding removes the
    guess; it costs nothing because these are throwaway copies."""
    vdbs = sorted((m for m in members if m.lower().endswith('.vdb')), key=lambda m: _frame_no(m))
    if not vdbs:
        raise RuntimeError('archive holds no .vdb frames')
    stride = max(1, (len(vdbs) + MAX_RENDER_FRAMES - 1) // MAX_RENDER_FRAMES)
    picked = vdbs[::stride]
    if stride > 1:
        log(f'  {len(vdbs)} frames → every {stride}th ({len(picked)} rendered)')
    raw = os.path.join(workdir, 'vdb')
    log(f'  extracting {len(picked)} frame(s)…')
    got = extract_members(archive, picked, raw)
    seq = os.path.join(workdir, 'seq')
    os.makedirs(seq, exist_ok=True)
    for i, fp in enumerate(got):
        os.rename(fp, os.path.join(seq, 'f_%04d.vdb' % i))
    frames = os.path.join(workdir, 'frames')
    os.makedirs(frames, exist_ok=True)
    cfg = {'seq': seq, 'n': len(got), 'out': frames + os.sep, 'w': RENDER_W, 'h': RENDER_H, 'samples': RENDER_SAMPLES}
    log(f'  blender: rendering {len(got)} frame(s) at {RENDER_W}x{RENDER_H}…')
    t0 = time.time()
    r = _run([blender_bin(), '-b', '--factory-startup', '-P', BLENDER_SCRIPT, '--', json.dumps(cfg)])
    pngs = sorted(f for f in os.listdir(frames) if f.endswith('.png'))
    if not pngs:
        tail = (r.stdout or '')[-800:] + (r.stderr or '')[-800:]
        raise RuntimeError(f'blender produced no frames:\n{tail}')
    log(f'  rendered {len(pngs)} frame(s) in {time.time() - t0:.0f}s')
    crop = measure_crop([os.path.join(frames, f) for f in pngs])
    if not crop:
        # NOT a cropping fallback — an empty render. measure_crop only comes
        # back None when no sampled frame holds a single pixel more than 14
        # levels above its own background, i.e. Blender rendered the volume
        # away and wrote 116 pictures of the backdrop.
        #
        # This is here because it already happened: the camera's clip_end
        # defaults to 1000, the framing distance for a large domain is past
        # that, and every density-only pack came out black. The builder saved
        # those as previews and reported success — a 0.0 MB clip that the pane
        # would have played as an empty grey box. Refuse them instead.
        raise RuntimeError(
            f'render is empty — {len(pngs)} frames hold nothing brighter than '
            f'their own background. The volume did not reach the camera '
            f'(check the clip range, the framing distance and the density '
            f'attribute in the [render] log lines).'
        )
    cw, ch, cx, cy = crop
    log(f'  element occupies {cw}x{ch} at {cx},{cy} — cropping to it')
    vf = f'crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{OUT_H}'
    # Blender numbers its output from the scene's first frame, which is 1 —
    # the default -start_number of 0 makes ffmpeg find nothing at all.
    r = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-framerate',
            str(RENDER_FPS),
            '-start_number',
            str(_first_index(pngs)),
            '-i',
            os.path.join(frames, 'f_%04d.png'),
            '-vf',
            vf,
            '-c:v',
            'libx264',
            '-crf',
            '20',
            '-preset',
            'veryfast',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            out_mp4,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out_mp4):
        raise RuntimeError(f'ffmpeg encode failed: {r.stderr[-300:]}')
    mid = os.path.join(frames, pngs[int(len(pngs) * 0.55)])
    _run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-i',
            mid,
            '-vf',
            vf.replace(f'scale={OUT_W}:{OUT_H}', 'scale=480:-2'),
            out_jpg,
        ]
    )
    return VI.probe(out_mp4)


def _first_index(pngs: list) -> int:
    m = re.search(r'(\d+)', pngs[0])
    return int(m.group(1)) if m else 0


def measure_crop(paths: list, sample=14):
    """Union bounding box of the ELEMENT across the rendered frames, as
    (w, h, x, y) at the output aspect.

    Framing from the VDB's bounding box alone puts the element in a corner of
    the frame: that box is the simulation DOMAIN, not the smoke — Fire_01's
    domain is 127 units wide and the flame occupies maybe a fifth of it, so the
    first test render was a thumbnail-sized fire in an empty grey field. The
    rendered pixels are the only honest measure of where the effect actually
    is, and they are already on disk by the time this runs.

    Returns None if nothing stands out from the background, in which case the
    caller falls back to the full frame rather than cropping to noise."""
    try:
        from PIL import Image
    except ImportError:
        return None
    step = max(1, len(paths) // sample)
    lo_x = lo_y = 10**9
    hi_x = hi_y = -1
    W = H = 0
    for p in paths[::step]:
        try:
            im = Image.open(p).convert('L')
        except OSError as _exc:
            _zyg_log.debug('frame unreadable, excluded from the crop measure: %s', _exc)
            continue
        W, H = im.size
        # The world background is a flat near-black; the element is anything
        # meaningfully brighter than the frame's own corner pixel.
        bg = im.getpixel((2, 2))
        thr = bg + 14
        bbox = im.point(lambda v, t=thr: 255 if v > t else 0).getbbox()
        if not bbox:
            continue
        lo_x, lo_y = min(lo_x, bbox[0]), min(lo_y, bbox[1])
        hi_x, hi_y = max(hi_x, bbox[2]), max(hi_y, bbox[3])
    if hi_x < 0 or not W:
        return None
    bw, bh = hi_x - lo_x, hi_y - lo_y
    if bw < 8 or bh < 8:
        return None
    mx, my = bw * CROP_MARGIN, bh * CROP_MARGIN
    lo_x, hi_x = lo_x - mx, hi_x + mx
    lo_y, hi_y = lo_y - my, hi_y + my
    cx, cy = (lo_x + hi_x) / 2, (lo_y + hi_y) / 2
    aspect = OUT_W / OUT_H
    cw, ch = hi_x - lo_x, hi_y - lo_y
    if cw / ch < aspect:
        cw = ch * aspect
    else:
        ch = cw / aspect
    # Never crop bigger than the frame, and never off the edge of it.
    if cw > W:
        cw, ch = W, W / aspect
    if ch > H:
        ch, cw = H, H * aspect
    x = min(max(0, int(round(cx - cw / 2))), W - int(cw))
    y = min(max(0, int(round(cy - ch / 2))), H - int(ch))
    # x264 wants even dimensions; the crop filter does not round for us.
    return int(cw) & ~1, int(ch) & ~1, x & ~1, y & ~1


def _frame_no(name: str) -> tuple:
    m = re.findall(r'(\d+)', os.path.basename(name))
    return (int(m[-1]) if m else 0, name)


# ── the build ──────────────────────────────────────────────────────────────
def commit(key: str, rec: dict) -> None:
    """Write ONE record back, against a freshly read sidecar.

    A build is minutes long and `save_sidecar` writes the whole dict, so
    holding the copy that was read at the start and saving it at the end
    silently reverts everything any other writer did in between — which is
    exactly what happened the first time this ran: a concurrent
    `vfx_ingest.py --fix-dims` measured all 174 sprites, and the next pack to
    finish wrote them all back to zero. Same class as the manifest overwrite in
    the worn-voice bench. Re-read, set one key, save."""
    meta = VI.load_sidecar()
    meta[key] = rec
    VI.save_sidecar(meta)


def build_one(key: str, rec: dict, meta: dict, force=False, log=print) -> dict:
    """Build (or reuse) the preview for one volume pack. Returns a small status
    dict; never raises for a single pack's failure — it records the reason on
    the sidecar so the rail can say why instead of showing a dead card."""
    fn = rec.get('file') or ''
    archive = os.path.join(LIBS, rec.get('master') or '')
    slug = _slug(fn)
    os.makedirs(VOLDIR, exist_ok=True)
    out_mp4 = os.path.join(VOLDIR, slug + '.mp4')
    out_jpg = os.path.join(VOLDIR, slug + '.jpg')
    have = os.path.isfile(out_mp4) and os.path.getsize(out_mp4) > 0
    if have and not force and rec.get('preview'):
        return {'ok': True, 'skipped': True, 'file': slug + '.mp4'}
    if not os.path.isfile(archive):
        return {'ok': False, 'error': f'master missing: {archive}'}

    log(f'[vol] {rec.get("name") or fn}')
    t0 = time.time()
    try:
        members = list_archive(archive)
        if not members:
            raise RuntimeError('archive listing empty')
        vend = vendor_clip(members)
        with tempfile.TemporaryDirectory(prefix='vfxvol_') as tmp:
            if vend:
                log(f'  vendor clip: {vend}')
                src = extract_members(archive, [vend], tmp)[0]
                p = normalise_video(src, out_mp4, out_jpg)
                src_kind = 'vendor'
            else:
                p = render_pack(archive, members, tmp, out_mp4, out_jpg, log=log)
                src_kind = 'render'
    except Exception as e:  # noqa: BLE001 — one pack only
        rec['preview'] = ''
        rec['preview_error'] = f'{type(e).__name__}: {e}'
        meta[key] = rec
        commit(key, rec)
        log(f'  FAILED — {e}')
        return {'ok': False, 'error': str(e)}

    rec['preview'] = os.path.basename(out_mp4)
    rec['poster'] = os.path.basename(out_jpg) if os.path.isfile(out_jpg) else ''
    rec['preview_src'] = src_kind
    rec['preview_bytes'] = os.path.getsize(out_mp4)
    rec['preview_dur'] = p.get('dur') or 0
    rec['preview_w'] = p.get('w') or 0
    rec['preview_h'] = p.get('h') or 0
    rec['preview_error'] = ''  # blanked, not popped: save_sidecar merges
    meta[key] = rec  # field by field and would keep a popped one
    commit(key, rec)
    log(
        f'  → {rec["preview"]}  {src_kind}  '
        f'{rec["preview_bytes"] / 1e6:.1f} MB  {rec["preview_dur"]:.1f}s  '
        f'({time.time() - t0:.0f}s)'
    )
    return {'ok': True, 'file': rec['preview'], 'src': src_kind}


def reconcile(log=print) -> dict:
    """Re-attach preview clips that are ON DISK but not named by the sidecar.

    Needed because the sidecar is shared: a writer holding a stale copy can save
    over freshly written `preview` fields, and the mp4s then sit in the library
    unreferenced while the pane offers to build them again. Rather than
    re-render 40 minutes of GPU work to recover a JSON field, this walks the
    library dir, matches each clip back to its pack by slug, and restores the
    record from the file itself.

    Cheap, idempotent, and safe to run any time — it only ever ADDS a preview
    the file system already proves exists, and re-probes it rather than trusting
    what the record used to say."""
    meta = VI.load_sidecar()
    fixed = ok = 0
    for key, rec in volume_records(meta):
        slug = _slug(rec.get('file') or '')
        mp4 = os.path.join(VOLDIR, slug + '.mp4')
        jpg = os.path.join(VOLDIR, slug + '.jpg')
        if not (os.path.isfile(mp4) and os.path.getsize(mp4) > 0):
            continue
        if rec.get('preview') == os.path.basename(mp4):
            ok += 1
            continue
        p = VI.probe(mp4)
        rec['preview'] = os.path.basename(mp4)
        rec['poster'] = os.path.basename(jpg) if os.path.isfile(jpg) else ''
        # The clip's own shape is the tell: a vendor turntable keeps whatever
        # aspect its author rendered, ours is always OUT_W x OUT_H.
        rec['preview_src'] = rec.get('preview_src') or (
            'render' if (p.get('w'), p.get('h')) == (OUT_W, OUT_H) else 'vendor'
        )
        rec['preview_bytes'] = os.path.getsize(mp4)
        rec['preview_dur'] = p.get('dur') or 0
        rec['preview_w'], rec['preview_h'] = p.get('w') or 0, p.get('h') or 0
        rec['preview_error'] = ''
        commit(key, rec)
        log(f'  re-attached {rec["name"]}: {rec["preview"]} [{rec["preview_src"]}]')
        fixed += 1
    log(f'[vol] reconcile: {fixed} re-attached, {ok} already correct')
    return {'fixed': fixed, 'ok': ok}


def volume_records(meta: dict) -> list:
    return sorted(
        ((k, r) for k, r in meta.items() if r.get('cat') == 'vfx_volumes'), key=lambda kr: kr[1].get('file') or ''
    )


def build_all(only=None, force=False, log=print) -> dict:
    meta = VI.load_sidecar()
    todo = volume_records(meta)
    if only:
        todo = [(k, r) for k, r in todo if r.get('file') == only or _slug(r.get('file') or '') == _slug(only)]
        if not todo:
            log(f'[vol] no volume pack matches {only!r}')
            return {'built': 0, 'failed': 0, 'skipped': 0}
    n_ok = n_skip = n_bad = 0
    for k, r in todo:
        out = build_one(k, r, meta, force=force, log=log)
        if out.get('skipped'):
            n_skip += 1
        elif out.get('ok'):
            n_ok += 1
        else:
            n_bad += 1
    log(f'[vol] built={n_ok} skipped={n_skip} failed={n_bad}')
    return {'built': n_ok, 'skipped': n_skip, 'failed': n_bad}


if __name__ == '__main__':  # the CLI lives in vfx_volume_preview_cli
    from zyg_workflows.vfx_volume_preview_cli import main as _cli_main

    raise SystemExit(_cli_main())
