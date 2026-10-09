# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, the finishing stages `_post_process` orchestrates.

`ffmpeg_finish._post_process` used to be one 428-line function: the pre-passes
that replace the clip before it is measured, six blocks that each append a few
links to ONE filtergraph, the master encode, the three passes that cannot live
in a filtergraph, and the alternate-codec delivery. Each of those is a function
here, so the orchestrator reads as the running order it always was and every
block can be exercised on its own.

The filtergraph builders are pure: they take the sanitised parameter dict and
return `(chain, notes)` — the filter links in order, and the words the finish
log line is made of. Nothing in them touches the disk, which is what makes
them testable without ffmpeg.

Import direction: this module reads the shared helpers and tables off
`ffmpeg_finish` at call time (through the module object, so a patched
`_run_ff` is seen), and `_post_process` imports this module inside its own
body. That keeps the cycle from ever forming at import time.
"""

import json
import math
import os
from dataclasses import dataclass

from zyg_workflows.bin import exe

from . import _FONT
from . import ffmpeg_finish as _ff


def pre_passes(path: str, p: dict, log) -> bool:
    """Run the passes that must happen BEFORE the frame is measured.

    Stabilise (vidstab needs two ffmpeg passes), the RealESRGAN upscale and the
    RIFE interpolation each replace ``path`` in place so the grade, the geometry
    and the burn-ins all see the final pixel size and the final frame rate.
    Returns True when RIFE conformed the rate — a successful RIFE pass OWNS the
    frame rate, so `_rate_chain` must not also run minterpolate over it.
    """
    if p['stabilize']:
        tmp = path + '.stab.mp4'
        if _ff._stabilize(path, tmp, log):
            os.replace(tmp, path)
            log('finish: stabilised')
        else:
            log('finish: stabilise skipped (see error above)')

    # ── (a) AI upscale, before everything that measures the frame size ──
    if str(p.get('upscale', 'off')) != 'off':
        try:
            from zyg_workflows import video_finish as _vfin

            scale = int(str(p['upscale']).lstrip('xX'))
            tmp = path + '.up.mp4'
            rec = _vfin.esrgan_clip(path, tmp, scale=scale, log=log)
            os.replace(tmp, path)
            log(
                f'finish: AI upscale x{scale} — {rec.get("w_in")}x{rec.get("h_in")}'
                f' -> {rec.get("w_out")}x{rec.get("h_out")}, '
                f'{rec.get("frames")} frames in {rec.get("seconds", 0):.0f}s'
            )
        except Exception as exc:  # noqa: BLE001
            log(f'upscale unavailable: {exc}')

    # ── (b) RIFE, when Interp mode asks for it ──────────────────────────
    rife_done = False
    if p['interpolate'] != 'off' and p['interp_mode'] == 'rife':
        try:
            from zyg_workflows import video_finish as _vfin

            tmp = path + '.rife.mp4'
            rec = _vfin.rife_2x(path, tmp, out_fps=float(int(p['interpolate'])), log=log)
            os.replace(tmp, path)
            rife_done = True
            log(
                f'finish: RIFE 2x — {rec.get("fps_in")} -> {rec.get("fps_out")} fps, '
                f'{rec.get("frames_in")} -> {rec.get("frames_out")} frames in '
                f'{rec.get("seconds", 0):.0f}s'
            )
        except Exception as exc:  # noqa: BLE001
            log(f'rife unavailable: {exc}')
    return rife_done


def _timeline_chain(p: dict, pre_filter: str, w: int, h: int) -> tuple:
    """The links that act on the TIMELINE, in the only order they compose in.

    tpad first (holding a frame has to happen before trim measures anything and
    before speed remaps the timeline it sits on), then the colour match, the
    reverse, the one combined speed remap, deflicker, denoise and the resample.

    Returns ``(chain, notes, w, h, eff_speed)``: the resample changes the frame
    size every later block is built off, and `eff_speed` is the single setpts
    factor the fade arithmetic and the rate conform both need.
    """
    chain, notes = [], []
    if p['hold_head'] > 0 or p['hold_tail'] > 0:
        tp = []
        if p['hold_head'] > 0:
            tp.append(f'start_mode=clone:start_duration={p["hold_head"]:.2f}')
        if p['hold_tail'] > 0:
            tp.append(f'stop_mode=clone:stop_duration={p["hold_tail"]:.2f}')
        chain.append('tpad=' + ':'.join(tp))
        notes.append('hold ' + '+'.join(f'{x:g}s' for x in (p['hold_head'], p['hold_tail']) if x))
    if pre_filter:  # colour match runs before anything
        chain.append(pre_filter)  # that changes the colours on purpose
        notes.append('colour match')
    if p['reverse']:
        chain.append('reverse')
        notes.append('reverse')
    # Speed and Fast forward are ONE remap: the select multiplies the knob, so
    # the chain never carries two setpts and eff_dur below stays computable.
    eff_speed = float(p['speed']) * (1.0 if p['speed_x'] == 'off' else float(p['speed_x']))
    if abs(eff_speed - 1.0) > 1e-6:
        chain.append(f'setpts={1.0 / eff_speed:.6f}*PTS')
        notes.append(f'speed {eff_speed:g}x')
    if p['deflicker']:
        chain.append('deflicker=size=5:mode=am')
        notes.append('deflicker')
    if p['denoise'] > 0:
        s = p['denoise']
        chain.append(f'hqdn3d={4 * s:.2f}:{3 * s:.2f}:{6 * s:.2f}:{4.5 * s:.2f}')
        notes.append(f'denoise {s:g}')
    if p['resample'] != 'off' and w and h:
        f = float(p['resample'])
        nw, nh = int(w * f) // 2 * 2, int(h * f) // 2 * 2
        chain.append(f'scale={nw}:{nh}:flags=lanczos')
        notes.append(f'resample {p["resample"]}x -> {nw}x{nh}')
        w, h = nw, nh
    return chain, notes, w, h, eff_speed


def _geometry_chain(p: dict, w: int, h: int, dur: float, pad_col: str) -> tuple:
    """The FRAME rack: lens distortion, the punch-in, the post move, rotation
    and the two flips, as filter links plus their notes.

    Needs the frame size (every zoom crops back to it) and the duration (zoompan
    works per output frame, so the Ken Burns step is one over the frame count).
    """
    chain, notes = [], []
    if float(p['lens_distort']) != 0 and w and h:
        k = float(p['lens_distort'])
        chain.append(f'lenscorrection=k1={k:.3f}:k2={k * 0.5:.3f}')
        notes.append(f'lens {k:+.2f}')
    if float(p['crop_zoom']) > 1.0 and w and h:
        z = float(p['crop_zoom'])
        sw, sh = int(w * z) // 2 * 2, int(h * z) // 2 * 2
        # pan_x/-y are -1..1 across the slack the zoom created; 0 is centred
        ox = int((sw - w) / 2 * (1 + float(p['pan_x'])))
        oy = int((sh - h) / 2 * (1 + float(p['pan_y'])))
        chain.append(f'scale={sw}:{sh}:flags=lanczos,crop={w}:{h}:{ox}:{oy}')
        notes.append(f'punch in {z:g}x')
    if p['ken_burns'] != 'off' and w and h:
        a = float(p['ken_burns_amount'])
        n = max(1, int(round(dur * float(p['fps']))))
        # zoompan works per output frame; d=1 keeps one output per input frame
        if p['ken_burns'] in ('in', 'out'):
            z = (
                f"'min(zoom+{a / n:.6f},{1 + a:.4f})'"
                if p['ken_burns'] == 'in'
                else f"'max({1 + a:.4f}-{a / n:.6f}*on,1.0)'"
            )
            xy = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        else:
            z = f"'{1 + a:.4f}'"
            trav = {
                'left': ("x='(iw-iw/zoom)*(1-on/%d)':y='ih/2-(ih/zoom/2)'" % n),
                'right': ("x='(iw-iw/zoom)*(on/%d)':y='ih/2-(ih/zoom/2)'" % n),
                'up': ("x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/%d)'" % n),
                'down': ("x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(on/%d)'" % n),
            }
            xy = trav[p['ken_burns']]
        chain.append(f'zoompan=z={z}:{xy}:d=1:s={w}x{h}:fps={float(p["fps"]):g}')
        notes.append(f'post move {p["ken_burns"]} {a:g}')
    if float(p['rotate']) != 0:
        r = math.radians(float(p['rotate']))
        # rotate leaves triangular corners; zoom back in by just enough to lose them
        cover = abs(math.cos(r)) + abs(math.sin(r))
        chain.append(f'rotate={r:.5f}:fillcolor={pad_col}')
        if w and h:
            sw, sh = int(w * cover) // 2 * 2, int(h * cover) // 2 * 2
            chain.append(f'scale={sw}:{sh}:flags=lanczos,crop={w}:{h}')
        notes.append(f'rotate {float(p["rotate"]):g}deg')
    if p['flip_h']:
        chain.append('hflip')
        notes.append('flip h')
    if p['flip_v']:
        chain.append('vflip')
        notes.append('flip v')
    return chain, notes


def _look_chain(p: dict, w: int, h: int, pad_col: str) -> tuple:
    """The LOOK preset, then the GRADE rack, then the texture dials and the matte.

    The named grade goes on first and `_grade_chain` second, because a LOOK is a
    starting point the operator then grades on top of. The matte is last: it
    crops and pads, and nothing after it should see the bars.
    """
    chain, notes = [], []
    if p['grade'] != 'none' and p['grade'] in _ff._GRADES:
        chain.append(_ff._GRADES[p['grade']])
        notes.append(f'grade {p["grade"]}')
    g_chain, g_notes = _ff._grade_chain(p)
    chain += g_chain
    notes += g_notes
    if p['deband']:
        chain.append('deband=1thr=0.02:2thr=0.02:3thr=0.02:4thr=0.02')
        notes.append('deband')

    if p['sharpen'] > 0:
        chain.append(f'unsharp=5:5:{p["sharpen"]:.2f}:5:5:0.0')
        notes.append(f'sharpen {p["sharpen"]:g}')
    if p['grain'] > 0:
        chain.append(f'noise=alls={int(p["grain"])}:allf=t+u')
        notes.append(f'grain {int(p["grain"])}')
    if float(p['chroma_shift']) > 0:
        c = int(p['chroma_shift'])
        chain.append(f'chromashift=cbh={c}:crh={-c}')
        notes.append(f'chroma shift {c}px')
    if p['vignette'] > 0:
        # PI/5 is a mild lens falloff, PI/2.4 is heavy — map the dial across it
        ang = 3.14159 / (5.0 - 2.6 * p['vignette'])
        chain.append(f'vignette=angle={ang:.4f}')
        notes.append(f'vignette {p["vignette"]:g}')
    if p['letterbox'] != 'off' and w and h:
        tar = float(p['letterbox'])
        src_ar = w / float(h)
        if tar < src_ar:  # narrower than source → crop width
            cw = int(h * tar) // 2 * 2
            chain.append(f'crop={cw}:{h},pad={w}:{h}:{(w - cw) // 2}:0:{pad_col}')
        else:  # wider → crop height (scope matte)
            ch = int(w / tar) // 2 * 2
            chain.append(f'crop={w}:{ch},pad={w}:{h}:0:{(h - ch) // 2}:{pad_col}')
        notes.append(f'matte {p["letterbox"]}')
    return chain, notes


def _rate_chain(p: dict, rife_done: bool, eff_speed: float) -> tuple:
    """The one frame-rate decision, as a ladder with exactly one winner.

    RIFE already conformed the rate when it ran; a FAILED RIFE conforms without
    synthesising and says so; otherwise minterpolate, or the output-rate dial,
    or — past 2x — the render rate, because setpts alone multiplies the
    timestamps as well as the pace and a 480 fps file scrubs like nothing.
    """
    chain, notes = [], []
    if p['interpolate'] != 'off' and rife_done:
        pass  # RIFE already conformed the rate
    elif p['interpolate'] != 'off' and p['interp_mode'] == 'rife':
        # RIFE was asked for and failed above; minterpolate is not a silent
        # substitute for it — conform the rate and say so.
        chain.append(f'fps={int(p["interpolate"])}')
        notes.append(f'conform {p["interpolate"]}fps (RIFE unavailable, no frames synthesised)')
    elif p['interpolate'] != 'off':
        chain.append(f'minterpolate=fps={int(p["interpolate"])}:mi_mode={p["interp_mode"]}')
        notes.append(f'interpolate {p["interpolate"]}fps/{p["interp_mode"]}')
    elif p['out_fps'] != 'off':
        chain.append(f'fps={int(p["out_fps"])}')
        notes.append(f'conform {p["out_fps"]}fps')
    elif eff_speed > 2.0:
        _fr = max(1, int(round(float(p['fps']))))
        chain.append(f'fps={_fr}')
        notes.append(f'conform {_fr}fps after speed')
    return chain, notes


def _burn_in_chain(p: dict) -> tuple:
    """The watermark and the timecode, the last thing before the fades.

    Both need the bundled font: with no font file on disk there is nothing to
    draw with, so the link is left out rather than failing the encode.
    """
    chain, notes = [], []
    if str(p['watermark']).strip() and os.path.isfile(_FONT):
        chain.append(
            f"drawtext=fontfile={_FONT}:text='{_ff._esc_dt(str(p['watermark']).strip())}'"
            f':fontsize=h/26:fontcolor=white@0.72:borderw=2:bordercolor=black@0.5'
            f':{_ff._WM_POS.get(p["watermark_pos"], _ff._WM_POS["br"])}'
        )
        notes.append('burn-in text')
    if p['burn_timecode'] and os.path.isfile(_FONT):
        chain.append(
            f"drawtext=fontfile={_FONT}:text='%{{n}}  %{{pts\\:hms}}'"
            f':fontsize=h/32:fontcolor=#7cf9ff@0.9:borderw=2:bordercolor=black@0.6'
            f':x=24:y=h-th-24'
        )
        notes.append('timecode')
    return chain, notes


def _fade_chain(p: dict, dur: float, eff_speed: float) -> tuple:
    """The fades, plus the effective duration they are placed against.

    The fade-out needs the length AFTER hold, trim and speed, which is computed
    from the probed duration rather than re-probed: the file on disk has not
    been through the chain yet. Returns ``(chain, notes, eff_dur)`` — the audio
    mix falls back to the same `eff_dur` when it cannot probe the muxed file.
    """
    chain, notes = [], []
    eff_dur = max(0.0, dur + p['hold_head'] + p['hold_tail'] - p['trim_head'] - p['trim_tail']) / max(0.01, eff_speed)
    fcol = p['fade_color']
    if p['fade_in'] > 0:
        chain.append(f'fade=t=in:st=0:d={p["fade_in"]:.2f}:color={fcol}')
        notes.append(f'fade in {p["fade_in"]:g}s')
    if p['fade_out'] > 0 and eff_dur > p['fade_out']:
        chain.append(f'fade=t=out:st={eff_dur - p["fade_out"]:.2f}:d={p["fade_out"]:.2f}:color={fcol}')
        notes.append(f'fade out {p["fade_out"]:g}s')
    return chain, notes, eff_dur


def filter_chain(p: dict, pre_filter: str, w: int, h: int, dur: float, rife_done: bool, pad_col: str) -> tuple:
    """THE filtergraph: every link that composes, in the one order they compose in.

    The timeline block runs first because the resample inside it changes the
    frame size the geometry and the look are then built off; the fades run last
    because the fade-out has to be placed against the duration the blocks before
    it produced. Returns ``(chain, notes, w, h, eff_dur)`` — the frame size as
    the resample left it, and the effective duration the audio mix falls back
    on.
    """
    chain, notes, w, h, eff_speed = _timeline_chain(p, pre_filter, w, h)
    for _links, _words in (
        _geometry_chain(p, w, h, dur, pad_col),
        _look_chain(p, w, h, pad_col),
        _rate_chain(p, rife_done, eff_speed),
        _burn_in_chain(p),
    ):
        chain += _links
        notes += _words
    _links, _words, eff_dur = _fade_chain(p, dur, eff_speed)
    chain += _links
    notes += _words
    return chain, notes, w, h, eff_dur


@dataclass(frozen=True)
class EncodePlan:
    """What the two encodes will be, decided once before either of them runs.

    `delivery_default` is True when the requested delivery IS a plain crf mp4,
    i.e. when the master already is the delivery and no second encode is owed.
    `master_crf` is the dial when the master ships as-is and near-lossless when
    something will be encoded from it, so the delivery is the only encode that
    costs quality. `reencode` is False only for a defaults-only render with an
    empty filtergraph — which is what makes such a render produce the same bytes
    it did before this rack existed.
    """

    vcodec: str
    ext: str
    delivery_default: bool
    master_crf: int
    reencode: bool
    trimming: bool


def _encode_plan(p: dict, chain: list) -> EncodePlan:
    """Decide both encodes from the params and the filtergraph that was built.

    Two encodes at most, and only when they are both earned. The MASTER is
    always an mp4 — the preview player needs one, and bloom and loop are
    separate passes that have to have something to run on.
    """
    trimming = p['trim_head'] > 0 or p['trim_tail'] > 0
    vcodec = _ff._VCODEC.get(p['codec'], 'libx264')
    ext = _ff._CONTAINER_EXT.get(p['container'], '.mp4')
    delivery_default = ext == '.mp4' and vcodec == 'libx264' and p['rate_mode'] == 'crf'
    post_passes = float(p['bloom']) > 0 or p['loop_mode'] != 'off'
    master_crf = int(p['crf']) if (delivery_default and not post_passes) else min(int(p['crf']), 12)
    reencode = (
        bool(chain)
        or trimming
        or not delivery_default
        or p['crf'] != 20
        or p['pix_fmt'] != 'yuv420p'
        or p['x_preset'] != 'veryfast'
        or p['x_tune']
    )
    return EncodePlan(
        vcodec=vcodec,
        ext=ext,
        delivery_default=delivery_default,
        master_crf=master_crf,
        reencode=reencode,
        trimming=trimming,
    )


def _master_args(path: str, out: str, p: dict, chain: list, dur: float, master_crf: int) -> list:
    """The ffmpeg argv for the FINISH encode: the trim window, the filtergraph
    and the x264 settings, writing ``out`` from ``path``.

    The trim is done with -ss/-to on the input rather than a trim filter, so the
    decoder seeks instead of the graph discarding frames; -to needs the probed
    duration, and is left out when there is none.
    """
    args = [exe('ffmpeg'), '-y']
    if p['trim_head'] > 0:
        args += ['-ss', f'{p["trim_head"]:.3f}']
    if p['trim_tail'] > 0 and dur > 0:
        args += ['-to', f'{max(0.1, dur - p["trim_tail"]):.3f}']
    args += ['-i', path]
    if chain:
        args += ['-vf', ','.join(chain)]
    args += ['-c:v', 'libx264', '-preset', p['x_preset']]
    if p['x_tune']:
        args += ['-tune', p['x_tune']]
    args += ['-crf', str(master_crf), '-pix_fmt', p['pix_fmt']]
    if p['faststart']:
        args += ['-movflags', '+faststart']
    args += [out]
    return args


def encode_master(path: str, p: dict, log, chain: list, notes: list, dur: float) -> tuple:
    """Plan both encodes, then encode the finished master over ``path`` and log
    what went into it.

    Returns ``(plan, ok)``. The plan is decided here because the master encode
    is the first thing that acts on it, and the passes after it need the same
    one; it is handed back rather than re-derived. `ok` False means the post
    chain failed and the un-finished render was kept — the caller must then
    stop, because every pass after this one would be applied to a clip that is
    not the one the notes describe. A plan that owes no re-encode skips the
    encode entirely and is still `ok`: the render already IS the master.
    """
    plan = _encode_plan(p, chain)
    if not plan.reencode:
        return plan, True
    out = path + '.fin.mp4'
    if _ff._run_ff(_master_args(path, out, p, chain, dur, plan.master_crf), log, 'finish'):
        os.replace(out, path)
        log('finish: ' + (', '.join(notes) if notes else 'trim/encode only'))
        return plan, True
    log('finish: post chain failed — keeping the un-finished render')
    return plan, False


def bloom_and_loop(path: str, p: dict, log, master_crf: int) -> None:
    """The two passes that cannot be one filter link: bloom needs the stream
    split and recombined, and a loop needs the concat demuxer. Each replaces
    ``path`` only when it produced something."""
    if float(p['bloom']) > 0:
        tmp = path + '.bloom.mp4'
        if _ff._bloom_pass(path, tmp, float(p['bloom']), log, crf=master_crf):
            os.replace(tmp, path)
            log(f'finish: bloom {float(p["bloom"]):g}')

    if p['loop_mode'] != 'off':
        tmp = path + '.loop.mp4'
        if _ff._loop_pass(path, tmp, p['loop_mode'], log):
            os.replace(tmp, path)
            log(f'finish: loop {p["loop_mode"]}')


def vfx_pass(path: str, p: dict, log) -> None:
    """Bake the VFX place rack at full quality, over the graded picture.

    The draft the operator approved in the GUI ran vfx_place on the SAME params
    through the SAME solver at 320p; this is that composite at full resolution
    with the real 4K matte instead of the preview. An unavailable module logs
    one line and leaves the clip intact.
    """
    if str(p.get('vfx_element', 'none')) != 'none':
        try:
            from zyg_workflows import vfx_place as _vfxp

            tmp = path + '.vfx.mp4'
            vrec = _vfxp.bake(path, p, tmp)
            os.replace(tmp, path)
            pl = vrec['placement']
            log(
                f'finish: vfx {vrec["element"]["name"]} [{vrec["element"]["mode"]}] '
                f'at {pl["depth"]:.2f}m, {pl["size_m"]:g}m tall '
                f'({pl["height_px"]:.0f}px) — camera {vrec["cam_source"]} '
                f'in {vrec["seconds"]:.1f}s'
            )
        except Exception as exc:  # noqa: BLE001
            log(f'vfx placement unavailable: {exc}')


def _overlay_layers(p: dict, log) -> tuple:
    """The overlay placement record and its layer list, or ``({}, None)``.

    The record is JSON the GUI wrote; unreadable JSON is a missing overlay, not
    a failed render, so it logs one line and composites nothing.
    """
    try:
        rec_txt = str(p.get('overlay_record') or '').strip()
        rec = json.loads(rec_txt) if rec_txt else {}
        layers = rec.get('layers') if isinstance(rec, dict) else None
    except (TypeError, ValueError) as exc:
        rec, layers = {}, None
        log(f'overlay unavailable: unreadable placement record ({exc})')
    return rec, layers


def overlay_pass(path: str, p: dict, log) -> None:
    """Composite the overlay elements over the finished picture.

    An overlay is a mark made on top of the finished photograph, which is why it
    goes on after the grade and after the VFX element.
    """
    rec, layers = _overlay_layers(p, log)
    if layers:
        try:
            from zyg_workflows import video_overlay as _vov

            tmp = path + '.ovl.mp4'
            orec = _vov.composite(path, rec, tmp, draft=bool(p['overlay_draft']), log=log)
            os.replace(tmp, path)
            log(
                f'finish: overlay {len(layers)} layer(s)'
                f'{" [DRAFT]" if p["overlay_draft"] else ""} — '
                f'{orec.get("width")}x{orec.get("height")} @ {orec.get("fps")}fps '
                f'in {float(orec.get("seconds", 0) or 0):.0f}s'
            )
        except Exception as exc:  # noqa: BLE001
            log(f'overlay unavailable: {exc}')


def audio_pass(path: str, p: dict, log, eff_dur: float) -> None:
    """Build the bed and the cues and mux them under the delivered picture.

    The track is built to the muxed file's own duration when it can be probed,
    and to the computed `eff_dur` when it cannot. A mux that produces nothing is
    raised as an error so the clip is left with no audio rather than truncated.
    """
    spec = _ff._audio_spec(p)
    if spec:
        bed_ref = (spec.get('bed') or {}).get('file', '')
        try:
            from zyg_workflows import video_audio as _vaud

            a_dur = _ff._probe(path).get('dur', 0.0) or eff_dur
            wav = os.path.splitext(path)[0] + '.mix.wav'
            arec = _vaud.build_track(spec, a_dur, wav, log=log)
            tmp = path + '.mux.mp4'
            if not _vaud.mux(path, wav, tmp, log=log):
                raise RuntimeError('mux produced nothing')
            os.replace(tmp, path)
            _onsets = ', '.join(
                f'{os.path.basename(str(c.get("file", "")))}@{c.get("measured_onset_s")}'
                for c in (arec.get('cues') or [])
            )
            log(
                f'finish: audio {float(arec.get("duration_s", 0) or 0):.2f}s at '
                f'{arec.get("lufs")} LUFS — bed '
                f'{os.path.basename(bed_ref) if bed_ref else "none"}, '
                f'{len(arec.get("cues") or [])} cue(s)'
                + (f' [{_onsets}]' if _onsets else '')
                + (f' — warnings: {"; ".join(arec.get("warnings") or [])}' if arec.get('warnings') else '')
            )
        except Exception as exc:  # noqa: BLE001
            log(f'audio unavailable: {exc}')


def _delivery_args(path: str, delivery: str, p: dict, plan: EncodePlan) -> list:
    """The ffmpeg argv for the alternate-codec delivery, encoded FROM the master.

    ProRes has no 4:2:0 profile, so a 4:2:0 pixel format is lifted to 10-bit
    4:2:2; VP9 needs `-b:v 0` beside its crf for constant quality; and a bitrate
    rate mode is meaningless for ProRes, which is intra-frame at a fixed
    profile.
    """
    args = [exe('ffmpeg'), '-y', '-i', path, '-c:v', plan.vcodec]
    if plan.vcodec in ('libx264', 'libx265'):
        args += ['-preset', p['x_preset']]
        if p['x_tune']:
            args += ['-tune', p['x_tune']]
    elif plan.vcodec == 'prores_ks':
        args += ['-profile:v', '3']  # 422 HQ
    pix = p['pix_fmt']
    if plan.vcodec == 'prores_ks' and not pix.startswith('yuv422'):
        pix = 'yuv422p10le'  # ProRes has no 4:2:0 profile
    if p['rate_mode'] == 'bitrate' and plan.vcodec != 'prores_ks':
        args += ['-b:v', f'{int(p["bitrate"])}k']
    elif plan.vcodec == 'libvpx-vp9':
        args += ['-crf', str(int(p['crf'])), '-b:v', '0']
    elif plan.vcodec != 'prores_ks':
        args += ['-crf', str(int(p['crf']))]
    args += ['-pix_fmt', pix]
    if p['faststart'] and plan.ext in ('.mp4', '.mov'):
        args += ['-movflags', '+faststart']
    args += [delivery]
    return args


def _delivery_path(path: str, p: dict, ext: str) -> str:
    """Where the alternate-codec delivery goes: beside the master, named by
    CODEC as well as container.

    An h265 delivery is still an mp4, and `clip.mp4` is already the master —
    writing to the same name makes ffmpeg read and write one file and fail.
    """
    return f'{os.path.splitext(path)[0]}.{p["codec"]}{ext}'


def delivery_encode(path: str, p: dict, log, plan: EncodePlan) -> str:
    """Write the delivery from the finished master, and return its path or ''.

    It sits BESIDE the mp4 rather than replacing it: the job's url points at the
    mp4 the preview can play. Encoding it from the master is what makes it carry
    the grade, the burn-ins, the bloom and the loop — all of which happened
    above.
    """
    if plan.delivery_default:
        return ''
    delivery = _delivery_path(path, p, plan.ext)
    if _ff._run_ff(_delivery_args(path, delivery, p, plan), log, 'delivery'):
        log(f'finish: delivery {os.path.basename(delivery)} ({p["codec"]}) written from the finished mp4')
        return delivery
    return ''
