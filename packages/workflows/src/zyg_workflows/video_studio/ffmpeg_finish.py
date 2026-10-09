# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, ffmpeg finish — everything done to a clip after frames exist.

Moved verbatim (lines 4163-5130 of the old single-file module): the grade
chain, the stabilise pre-pass, the loop post-pass, watermark/burn-in, the
side exports, the motion series, the audio spec and _post_process(), which
assembles one filtergraph out of them and seals every deliverable it writes.
"""

import json
import os
import subprocess

from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe

from . import _LUT_DIR, _zyg_log


# ──────────────────────────────────────────────────────────── ffmpeg finish
_GRADES = {
    'teal_orange': "curves=r='0/0 0.5/0.56 1/1':b='0/0.05 0.5/0.44 1/0.95'",
    'bleach': 'eq=saturation=0.35:contrast=1.25',
    'warm': 'colorbalance=rs=0.08:gs=0.02:bs=-0.06',
    'cool': 'colorbalance=rs=-0.07:gs=0.0:bs=0.09',
    'sepia': 'colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131',
    'mono': 'hue=s=0',
    'contrast': 'eq=contrast=1.3:gamma=0.98',
    'faded': "curves=all='0/0.08 1/0.92',eq=saturation=0.8",
}


def _color_match_filter(ref_png: str, clip_path: str, log) -> str:
    """Per-channel mean/std match of a RENDER back to its seed frame, returned as
    an ffmpeg lutrgb so the finish pass can apply it to every frame in the one
    encode it already does.

    wan_video_service._color_match_to() does the same arithmetic but opens its
    target with PIL — hand it an .mp4 and it raises, logs "color-match skipped"
    and returns False. That is a silent no-op, not a colour match, so the video
    form is implemented here: measure frame 0, emit the linear map."""
    try:
        from PIL import Image
        import numpy as np

        probe_png = clip_path + '.f0.png'
        r = subprocess.run(
            [exe('ffmpeg'), '-y', '-v', 'error', '-i', clip_path, '-frames:v', '1', probe_png],
            capture_output=True,
            timeout=60,
        )
        if r.returncode != 0 or not os.path.isfile(probe_png):
            log('colour match skipped — could not read frame 0 of the render')
            return ''
        ref = np.asarray(Image.open(ref_png).convert('RGB'), dtype=np.float32)
        tgt = np.asarray(Image.open(probe_png).convert('RGB'), dtype=np.float32)
        try:
            os.remove(probe_png)
        except OSError as _exc:
            _zyg_log.debug('colour probe frame cleanup skipped: %s', _exc)
        # Guard: a clip that opens on black (a fade-in, a hard cut) has almost no
        # spread, and mean/std matching against it produces a gain that crushes
        # the whole clip. Refusing to match is the correct answer there — an
        # unguarded ratio here would have shipped a black render as "matched".
        if float(ref.std()) < 3.0 or float(tgt.std()) < 3.0:
            log(
                "colour match skipped — the seed frame or the render's first "
                'frame is near-flat (fade from black?), nothing to match against'
            )
            return ''
        parts, shown = [], []
        for i, ch in enumerate('rgb'):
            t, rr = tgt[:, :, i], ref[:, :, i]
            gain = max(0.5, min(2.0, float(rr.std()) / max(float(t.std()), 1e-3)))
            off = float(rr.mean()) - gain * float(t.mean())
            parts.append(f"{ch}='clip(val*{gain:.5f}{off:+.4f},0,255)'")
            shown.append(f'{ch} x{gain:.3f}{off:+.1f}')
        log('colour match to the seed frame: ' + ', '.join(shown))
        return 'lutrgb=' + ':'.join(parts)
    except Exception as e:  # noqa: BLE001
        log(f'colour match skipped ({e})')
        return ''


def _probe(path: str) -> dict:
    """width/height/duration of a clip, or {} — every ffmpeg length calculation
    below (fade start, trim window) needs the real duration, not the nominal
    one, because minterpolate and setpts both change it."""
    try:
        r = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height:format=duration',
                '-of',
                'json',
                path,
            ],
            capture_output=True,
            timeout=30,
        )
        d = json.loads(r.stdout.decode() or '{}')
        st = (d.get('streams') or [{}])[0]
        return {
            'w': int(st.get('width') or 0),
            'h': int(st.get('height') or 0),
            'dur': float((d.get('format') or {}).get('duration') or 0.0),
        }
    except Exception:
        return {}


def _run_ff(args: list, log, tag: str, timeout: int = 900) -> bool:
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        if r.returncode == 0:
            return True
        tail = r.stderr.decode(errors='replace').strip().splitlines()[-2:]
        log(f'{tag} failed (rc={r.returncode}): {" | ".join(tail)}')
        return False
    except Exception as e:  # noqa: BLE001
        log(f'{tag} error: {e}')
        return False


def _stabilize(src: str, dst: str, log) -> bool:
    trf = src + '.trf'
    if not _run_ff(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            src,
            '-vf',
            f'vidstabdetect=shakiness=6:accuracy=12:result={trf}',
            '-f',
            'null',
            '-',
        ],
        log,
        'stabilise (detect)',
    ):
        return False
    ok = _run_ff(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            src,
            '-vf',
            f'vidstabtransform=input={trf}:zoom=1:smoothing=24,unsharp=5:5:0.3',
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '18',
            '-pix_fmt',
            'yuv420p',
            dst,
        ],
        log,
        'stabilise (transform)',
    )
    try:
        os.remove(trf)
    except OSError as _exc:
        _zyg_log.debug('stabiliser transform file cleanup skipped: %s', _exc)
    return ok


def _loop_pass(src: str, dst: str, mode: str, log) -> bool:
    work = os.path.dirname(src)
    if mode == 'pingpong':
        rev = os.path.join(work, '_pp_rev.mp4')
        if not _run_ff(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                src,
                '-vf',
                'reverse',
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '18',
                '-pix_fmt',
                'yuv420p',
                rev,
            ],
            log,
            'ping-pong (reverse)',
        ):
            return False
        lst = os.path.join(work, '_pp_list.txt')
        with open(lst, 'w') as fh:
            fh.write(f"file '{src}'\nfile '{rev}'\n")
        ok = _run_ff(
            [exe('ffmpeg'), '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', dst], log, 'ping-pong (concat)'
        )
        for f in (rev, lst):
            try:
                os.remove(f)
            except OSError as _exc:
                _zyg_log.debug('loop intermediate cleanup skipped: %s', _exc)
        return ok
    n = {'x2': 2, 'x3': 3}.get(mode, 0)
    if n < 2:
        return False
    lst = os.path.join(work, '_loop_list.txt')
    with open(lst, 'w') as fh:
        fh.write(''.join(f"file '{src}'\n" for _ in range(n)))
    ok = _run_ff(
        [exe('ffmpeg'), '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', dst], log, 'loop (concat)'
    )
    try:
        os.remove(lst)
    except OSError as _exc:
        _zyg_log.debug('concat list cleanup skipped: %s', _exc)
    return ok


_WM_POS = {  # drawtext x:y for each corner, with a
    'tl': 'x=24:y=24',  # 24px safe margin
    'tr': 'x=w-tw-24:y=24',
    'bl': 'x=24:y=h-th-24',
    'br': 'x=w-tw-24:y=h-th-24',
    'c': 'x=(w-tw)/2:y=(h-th)/2',
}
_CONTAINER_EXT = {'mp4': '.mp4', 'mov': '.mov', 'mkv': '.mkv', 'webm': '.webm'}
_VCODEC = {'h264': 'libx264', 'h265': 'libx265', 'vp9': 'libvpx-vp9', 'prores': 'prores_ks'}


def _esc_dt(text: str) -> str:
    """Escape a string for ffmpeg drawtext, which parses ':' and '\\' inside
    an option value and ''' inside the filtergraph."""
    return text.replace('\\', r'\\\\').replace(':', r'\:').replace("'", r'\'').replace('%', r'\%')


def _grade_chain(p: dict) -> tuple:
    """The GRADE rack as a list of filter links, plus the notes for the log.

    Ordered the way a colourist works: white balance first (temperature, tint),
    then the tone curve (lift, brightness/contrast/gamma), then colour
    (saturation, vibrance, hue), then the LUT, which is a look and has to see
    a graded image rather than make one."""
    chain, notes = [], []
    if abs(float(p['color_temp']) - 6500.0) > 1:
        chain.append(f'colortemperature=temperature={float(p["color_temp"]):.0f}')
        notes.append(f'temp {int(p["color_temp"])}K')
    if abs(float(p['tint'])) > 1e-6:
        g = float(p['tint'])
        chain.append(f'colorbalance=gm={g:.3f}:gs={g * 0.5:.3f}:gh={g * 0.5:.3f}')
        notes.append(f'tint {g:+.2f}')
    if abs(float(p['lift'])) > 1e-6:
        lo = max(0.0, min(0.5, 0.0 + float(p['lift'])))
        chain.append(f"curves=all='0/{lo:.3f} 1/1'")
        notes.append(f'lift {float(p["lift"]):+.2f}')
    eq = []
    for key, arg, dflt in (
        ('brightness', 'brightness', 0.0),
        ('contrast', 'contrast', 1.0),
        ('saturation', 'saturation', 1.0),
        ('gamma', 'gamma', 1.0),
    ):
        if abs(float(p[key]) - dflt) > 1e-6:
            eq.append(f'{arg}={float(p[key]):.3f}')
            notes.append(f'{key} {float(p[key]):g}')
    if eq:
        chain.append('eq=' + ':'.join(eq))
    if abs(float(p['vibrance'])) > 1e-6:
        chain.append(f'vibrance=intensity={float(p["vibrance"]):.3f}')
        notes.append(f'vibrance {float(p["vibrance"]):g}')
    if abs(float(p['hue_shift'])) > 1e-6:
        chain.append(f'hue=h={float(p["hue_shift"]):.1f}')
        notes.append(f'hue {float(p["hue_shift"]):g}deg')
    if p['lut']:
        lut = os.path.join(_LUT_DIR, os.path.basename(str(p['lut'])))
        if os.path.isfile(lut):
            chain.append('lut3d=file=' + lut.replace(':', r'\:'))
            notes.append(f'lut {p["lut"]}')
    return chain, notes


def _bloom_pass(src: str, dst: str, amount: float, log, crf: int = 12) -> bool:
    """Screen a blurred copy of the frame over itself, so only the bright parts
    glow. It cannot live in the main chain: every other finishing step is a
    single link, and this one has to split the stream and recombine it."""
    sigma = 6 + 10 * amount
    graph = f'split[a][b];[b]gblur=sigma={sigma:.1f}[bb];[a][bb]blend=all_mode=screen:all_opacity={amount:.3f}'
    return _run_ff(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            src,
            '-filter_complex',
            graph,
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            str(crf),
            '-pix_fmt',
            'yuv420p',
            dst,
        ],
        log,
        'bloom',
    )


def _detect(path: str, filt: str, log) -> list:
    """Run a detection-only filter and return the lines it printed.

    blackdetect / freezedetect / scdet all report through the ffmpeg log rather
    than through an output file, so the null muxer is the whole point: nothing
    is written and the measurement is the stderr."""
    try:
        r = subprocess.run(
            [exe('ffmpeg'), '-hide_banner', '-nostats', '-i', path, '-vf', filt, '-f', 'null', '-'],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f'qc: {filt.split("=")[0]} failed: {exc}')
        return []
    key = filt.split('=')[0].split(',')[0]
    return [
        ln.strip()
        for ln in (r.stderr or '').splitlines()
        if key in ln
        and ('lavfi' in ln or key + ' @' in ln or 'black_start' in ln or 'freeze_start' in ln or 'lavfi.scd' in ln)
    ]


def _side_exports(path: str, p: dict, log) -> list:
    """GIF / WebP / poster / contact sheet / scope, written BESIDE the clip.

    Every one of these is derived from the finished file rather than from an
    intermediate, so what you look at is what shipped.

    Returns the files it actually wrote, in the order it wrote them, so the
    caller can seal each one — a deliverable nobody names is a deliverable
    that ships without its content credential."""
    base = os.path.splitext(path)[0]
    info = _probe(path)
    dur = max(0.1, info.get('dur', 1.0))
    wrote: list = []

    if p['gif_export']:
        pal = base + '.pal.png'
        f = 'fps=15,scale=480:-1:flags=lanczos'
        if _run_ff([exe('ffmpeg'), '-y', '-i', path, '-vf', f + ',palettegen', pal], log, 'gif palette'):
            if _run_ff(
                [exe('ffmpeg'), '-y', '-i', path, '-i', pal, '-lavfi', f + '[x];[x][1:v]paletteuse', base + '.gif'],
                log,
                'gif',
            ):
                wrote.append(base + '.gif')
            try:
                os.remove(pal)
            except OSError as _exc:
                _zyg_log.debug('gif palette cleanup skipped: %s', _exc)
    if p['webp_export']:
        if _run_ff(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                path,
                '-vf',
                'fps=18,scale=640:-1:flags=lanczos',
                '-c:v',
                'libwebp_anim',
                '-lossless',
                '0',
                '-q:v',
                '72',
                '-loop',
                '0',
                base + '.webp',
            ],
            log,
            'webp',
        ):
            wrote.append(base + '.webp')
    if p['poster_frame']:
        if _run_ff(
            [exe('ffmpeg'), '-y', '-ss', f'{dur / 2:.3f}', '-i', path, '-frames:v', '1', base + '.poster.png'],
            log,
            'poster',
        ):
            wrote.append(base + '.poster.png')
    if p['contact_sheet']:
        # 10 stills evenly across the clip. fps is derived from the duration so
        # the grid always fills, whatever the clip's real length turned out to be.
        if _run_ff(
            [
                exe('ffmpeg'),
                '-y',
                '-i',
                path,
                '-vf',
                f'fps={10 / dur:.4f},scale=320:-1,tile=5x2',
                '-frames:v',
                '1',
                base + '.sheet.png',
            ],
            log,
            'contact sheet',
        ):
            wrote.append(base + '.sheet.png')
    if p['scope_export'] != 'off':
        scope = {
            'waveform': 'waveform=intensity=0.1:mirror=1:display=overlay',
            'vectorscope': 'vectorscope=mode=color3:envelope=peak',
            'histogram': 'histogram=display_mode=stack',
        }[p['scope_export']]
        if _run_ff(
            [
                exe('ffmpeg'),
                '-y',
                '-ss',
                f'{dur / 2:.3f}',
                '-i',
                path,
                '-frames:v',
                '1',
                '-vf',
                scope,
                f'{base}.{p["scope_export"]}.png',
            ],
            log,
            'scope',
        ):
            wrote.append(f'{base}.{p["scope_export"]}.png')
    if p['probe_report']:
        try:
            with open(base + '.probe.json', 'w') as fh:
                json.dump(_probe(path), fh, indent=1)
            log('qc: probe report written')
            wrote.append(base + '.probe.json')
        except OSError as exc:
            log(f'qc: probe report failed: {exc}')
    return wrote


def _motion_series(path: str, log) -> list:
    """Per-frame mean luma difference, written beside the clip as JSON.

    The frozen-clip gate reduces the whole clip to one number (the fraction of
    its duration ffmpeg freezedetect did NOT call frozen), which is why it
    cannot tell a clip that never moves from one that moves and then stalls.
    This writes the series itself, so "it dies at the four-second mark" is a
    measurement rather than an impression.

    Pure ffmpeg on purpose — tblend=difference into signalstats, read back off
    the metadata printer. An opencv version would be shorter and would make
    this option depend on an import the serving process is not guaranteed to
    have, which is exactly how a QC feature ends up silently doing nothing.
    """
    try:
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-hide_banner',
                '-nostats',
                '-i',
                path,
                '-vf',
                'tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f'qc: motion log failed: {exc}')
        return []
    series = []
    for ln in (r.stdout or '').splitlines():
        if 'YAVG=' in ln:
            try:
                series.append(round(float(ln.split('=', 1)[1]) / 255.0, 6))
            except ValueError as _exc:
                _zyg_log.debug('unparsable motion log line ignored: %s', _exc)
    if not series:
        log('qc: motion log — ffmpeg reported no frames')
        return []
    lo = min(series)
    out = os.path.splitext(path)[0] + '.motion.json'
    try:
        with open(out, 'w') as fh:
            json.dump(
                {
                    'per_frame_abs_diff': series,
                    'mean': round(sum(series) / len(series), 6),
                    'min': lo,
                    'max': max(series),
                    'min_at_frame': series.index(lo) + 1,
                    'frames': len(series) + 1,
                },
                fh,
            )
        log(
            f'qc: motion log written — mean {sum(series) / len(series):.4f}, '
            f'quietest frame {series.index(lo) + 1} at {lo:.4f}'
        )
    except OSError as exc:
        log(f'qc: motion log failed: {exc}')
    return series


def _audio_spec(p: dict) -> dict:
    """The AUDIO rack as a video_audio spec, or {} when there is nothing to mix.

    Shared by the finishing chain and the assembly job so a clip and a
    programme built from clips are mixed by the same rules. The bed file
    override wins over the library dropdown; a bed fade-out of 0 means "follow
    the picture", i.e. the FINISH fade-out."""
    try:
        cues = json.loads(str(p.get('audio_cues') or '[]') or '[]')
    except (TypeError, ValueError):
        cues = []
    if not isinstance(cues, list):
        cues = []
    cues = [c for c in cues if isinstance(c, dict)]
    bed_ref = str(p.get('audio_bed_path') or '').strip() or (
        '' if str(p.get('audio_bed', 'off')) == 'off' else str(p['audio_bed'])
    )
    if not bed_ref and not cues:
        return {}
    spec = {'cues': cues, 'target_lufs': float(p['audio_target_lufs'])}
    if bed_ref:
        spec['bed'] = {
            'file': bed_ref,
            'gain_db': float(p['audio_bed_gain']),
            'fade_in_s': float(p['audio_bed_fade_in']),
            'fade_out_s': float(p['audio_fade_out'] or p['fade_out']),
            'loop': True,
        }
    return spec


def _post_process(path: str, p: dict, log, pre_filter: str = '', run_id: str = '') -> None:
    """Apply the FRAME / GRADE / FINISH / OUTPUT racks to ``path`` in place.

    One filtergraph for everything that composes, plus the passes that cannot:
    stabilise (vidstab needs two passes), bloom (needs a split) and loop
    (concat needs a demuxer). Every stage is skipped when its dial is at
    default, so a defaults-only render still produces the same bytes it did
    before this rack existed.

    Five passes live OUTSIDE the filtergraph because they are other modules:
    RealESRGAN upscale and RIFE interpolation run BEFORE it (so the grade,
    the geometry and the burn-ins all see the final pixel size and the final
    frame rate), and the VFX metric placement, the overlay composite and the
    audio mix run AFTER it (so they sit on the delivered picture). The VFX
    element goes on BEFORE the overlays for the same reason it goes on after
    the grade: it is part of the photography, and an overlay is a mark made on
    top of the finished photograph. Each is wrapped so an unavailable
    module or a missing binary logs one line and leaves the clip it was
    handed intact — a finishing pass is never allowed to lose a render.

    The QC gates in _render_worker have already measured the RAW render by the
    time this runs; that order is deliberate and must not change.

    Last of all, every file this leaves on disk is sealed with a content
    credential: the mp4 master as an original, the alternate-codec delivery and
    the side exports as transcodes of it, because that is what they are.

    Every stage below lives in ffmpeg_finish_post; what is left here is the
    running order, which is the part that must not change."""
    from . import ffmpeg_finish_post as _fp

    pad_col = p['pad_color']
    rife_done = _fp.pre_passes(path, p, log)

    # Probed AFTER the pre-passes: the upscale changed w/h and RIFE changed the
    # frame rate, and every filter built below is sized off these numbers.
    info = _probe(path)
    w, h, dur = info.get('w', 0), info.get('h', 0), info.get('dur', 0.0)

    chain, notes, w, h, eff_dur = _fp.filter_chain(p, pre_filter, w, h, dur, rife_done, pad_col)

    # ── encode, then the passes that cannot be a filter link ────────────
    plan, ok = _fp.encode_master(path, p, log, chain, notes, dur)
    if not ok:
        return
    _fp.bloom_and_loop(path, p, log, plan.master_crf)
    _fp.vfx_pass(path, p, log)
    _fp.overlay_pass(path, p, log)
    _fp.audio_pass(path, p, log, eff_dur)
    alt = _fp.delivery_encode(path, p, log, plan)

    sides = _side_exports(path, p, log)

    # ── (f) content credentials, on everything this render ships ────────
    # The master is signed first so the files cut from it can name it as their
    # parent ingredient; a re-encode strips the manifest, so each one is signed
    # in its own right. The seal is fail-safe — it never costs a render.
    _seal.seal(path, pipeline='video_studio', run_id=run_id, log_fn=log)
    for derived in [alt, *sides]:
        if derived and os.path.splitext(derived)[1].lower() in _seal.SUPPORTED:
            _seal.seal_derived(derived, path, pipeline='video_studio', run_id=run_id, log_fn=log)
