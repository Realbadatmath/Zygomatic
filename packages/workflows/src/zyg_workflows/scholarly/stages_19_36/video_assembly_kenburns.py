# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ken-Burns slot rendering, lifted out of `stage_15_video_assembly`.

The stage carried this as one 240-line nested `def` plus the thread pool that
drove it. Nothing here knows about `RunContext`: every helper takes plain
values and the stage's `log`/`debug` callables, so the camera move, the
per-frame geometry, the encoder command lines and the slot bookkeeping are all
reachable from a unit test without a GPU, an image or an ffmpeg on PATH.
"""

from dataclasses import dataclass

from ._common import (
    _FORCE_CPU_POST_ENCODE,
    _KB_THREAD_STAGGER_S,
    _NVENC_SEM,
    _cq_for_crf,
    _kb_encode_wait_seconds,
    _nvenc_vcodec_args,
    _x264_vcodec_args,
    _zyg_log,
    exe,
    os,
)

# ── Ken Burns: PIL frame-by-frame rendering for smooth sub-pixel motion ──
# Replaces FFmpeg zoompan, which quantises float crop coordinates to
# integers causing a freeze-then-snap stutter pattern.
# PIL Image.transform(AFFINE) maps an exact float source rectangle to the
# output size using bicubic interpolation — true sub-pixel motion with no
# integer quantisation at all, exactly like Final Cut Pro / Premiere.
_SLIDE_W, _SLIDE_H = 1920, 1080
_KB_FPS = 30

# Emotion → move speed multiplier (Murch rhythm rule applied to the camera
# rather than the cut: a shocked beat pushes harder than a grieving one).
_KB_EMOTION_SPEED = {
    'shock': 1.5,
    'tension': 1.4,
    'triumph': 1.1,
    'awe': 1.0,
    'unease': 0.85,
    'mystery': 0.8,
    'calm': 0.7,
    'grief': 0.55,
}

# Centre-framed slots rotate through these anchors so consecutive pushes do
# not land on the identical point of the frame.
_KB_CENTRE_ANCHORS = [
    (0.50, 0.45),
    (0.55, 0.50),
    (0.50, 0.55),
    (0.45, 0.50),
    (0.50, 0.50),
    (0.52, 0.47),
    (0.48, 0.52),
    (0.52, 0.53),
]


@dataclass(frozen=True)
class KenBurnsEnv:
    """The three `ZYG_*` flags the stage resolves once, before any slot renders."""

    worker_cap: int
    dust_on: bool
    grain_on: bool


@dataclass(frozen=True)
class KenBurnsSlot:
    """One image slot queued for a PIL Ken Burns render."""

    index: int
    img_path: str
    out_path: str
    duration: float
    fps: int
    shot_type: str
    emotion: str
    focal_zone: str


@dataclass(frozen=True)
class KenBurnsMove:
    """The primary camera move of one slot: which motion, how much zoom, which anchor."""

    motion: str
    z_delta: float
    z_fixed: float
    z_max: float
    ax: float
    ay: float


@dataclass
class KenBurnsClip:
    """Everything the frame pump needs for one slot — source, move, film look, encode."""

    img: object
    dfl: object
    slot_idx: int
    move: KenBurnsMove
    film_plan: object
    overlay: object
    frames: int
    fps: int
    src_w: int
    src_h: int
    affine: object
    bicubic: object
    out_path: str
    wait_s: float


def plan_move(slot):
    """The camera move for *slot*: shot type picks the motion, emotion its speed.

    Pure — a `KenBurnsSlot` in, a `KenBurnsMove` out, no image touched.
    """
    _sl = (slot.shot_type or '').lower()
    _emo = (slot.emotion or 'calm').lower()
    _fz = (slot.focal_zone or 'center').lower()

    _spd = _KB_EMOTION_SPEED.get(_emo, 1.0)

    if _fz == 'center':
        _ax, _ay = _KB_CENTRE_ANCHORS[slot.index % len(_KB_CENTRE_ANCHORS)]
    else:
        _ax = {'left': 0.25, 'right': 0.75}.get(_fz, 0.50)
        _ay = {'top': 0.20, 'bottom': 0.80}.get(_fz, 0.50)

    _z_delta = 0.0
    _z_fixed = 1.0
    if 'extreme' in _sl or 'tight' in _sl:
        _motion = 'push_in'
        _z_delta = 0.06 * _spd
    elif 'close' in _sl:
        _motion = 'push_in'
        _z_delta = 0.10 * _spd
    elif any(_k in _sl for _k in ('overhead', 'drone', 'aerial', 'bird')):
        _motion = 'drift'
        _z_fixed = 1.0 + 0.07 * _spd
    elif 'wide' in _sl or 'establishing' in _sl:
        _motion = 'pan_r' if slot.index % 2 == 0 else 'pan_l'
        _z_fixed = 1.0 + 0.08 * _spd
    else:
        _motion = 'pull_out' if slot.index % 3 == 2 else 'push_in'
        _z_delta = 0.10 * _spd

    return KenBurnsMove(motion=_motion, z_delta=_z_delta, z_fixed=_z_fixed, z_max=1.0 + _z_delta, ax=_ax, ay=_ay)


def encode_commands(slot, film_vf):
    """The NVENC and x264 ffmpeg command lines for *slot*, plus the pipe wait budget.

    `film_vf` is the documentary film-look filter chain, '' when it is off; it
    doubles the wait because the filters run on CPU ahead of the encoder.
    """
    _kb_prefix = [
        exe('ffmpeg'),
        '-y',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'rgb24',
        '-s',
        f'{_SLIDE_W}x{_SLIDE_H}',
        '-r',
        str(slot.fps),
        '-i',
        'pipe:0',
    ]
    if film_vf:
        _kb_prefix += ['-vf', film_vf]
    return (
        _kb_prefix + _nvenc_vcodec_args(_cq_for_crf(15), 'p3') + [slot.out_path],
        _kb_prefix + _x264_vcodec_args(15, 'ultrafast') + [slot.out_path],
        # Filters run on CPU ahead of the encoder — give the pipe more room.
        _kb_encode_wait_seconds(slot.duration) * (2 if film_vf else 1),
    )


def view_at(clip, t):
    """Frame *t* of *clip* as (prog, tsec, cx, cy, vw, vh, roll) in source pixels.

    The viewport is a float rectangle centred on (cx, cy): the primary move
    sets the zoom, the film-look plan adds breathing zoom, handheld sway and
    roll, and the result is clamped so no black creeps into a corner.
    """
    _n = clip.frames
    _prog_lin = t / (_n - 1) if _n > 1 else 0.0  # 0.0 → 1.0
    _tsec = t / float(clip.fps)

    # Eased progress replaces the old linear ramp — a move
    # that accelerates and settles instead of starting and
    # stopping dead. Plus breathing zoom, handheld sway and
    # roll drift, all resolved into one affine sample.
    if clip.film_plan is not None:
        (_prog, _z_breath, _dcx, _dcy, _roll) = clip.dfl.sample_geometry(clip.film_plan, _prog_lin, _tsec)
    else:
        _prog, _z_breath, _dcx, _dcy, _roll = _prog_lin, 1.0, 0.0, 0.0, 0.0

    _move = clip.move
    _IW, _IH = clip.src_w, clip.src_h
    if _move.motion == 'push_in':
        _z = 1.0 + _move.z_delta * _prog
    elif _move.motion == 'pull_out':
        _z = _move.z_max - _move.z_delta * _prog
    else:
        _z = _move.z_fixed

    # Viewport size in source-image pixels (float).
    # The breathing zoom multiplies the primary move so even
    # a nominally static drift shot is never truly still.
    _z = _z * _z_breath
    _vw = _IW / _z
    _vh = _IH / _z

    if _move.motion in ('push_in', 'pull_out'):
        _cx = _move.ax * _IW
        _cy = _move.ay * _IH
    elif _move.motion == 'pan_r':
        _x0 = _vw / 2
        _x1 = _IW - _vw / 2
        _cx = _x0 + (_x1 - _x0) * _prog
        _cy = _move.ay * _IH
    elif _move.motion == 'pan_l':
        _x0 = _IW - _vw / 2
        _x1 = _vw / 2
        _cx = _x0 + (_x1 - _x0) * _prog
        _cy = _move.ay * _IH
    else:  # drift
        _xrng = max(0.0, _IW - _vw)
        _yrng = max(0.0, _IH - _vh)
        if clip.slot_idx % 2 == 0:
            _cx = _vw / 2 + _xrng * 0.5 * _prog
            _cy = _vh / 2 + _yrng * 0.3 * _prog
        else:
            _cx = _IW - _vw / 2 - _xrng * 0.5 * _prog
            _cy = _vh / 2 + _yrng * 0.3 * _prog

    # Handheld sway rides on top of the planned move; the
    # clamp keeps the rolled rect inside the source so no
    # black ever creeps into a corner.
    _cx += _dcx
    _cy += _dcy
    if clip.film_plan is not None:
        _cx, _cy, _vw, _vh = clip.dfl.clamp_view(_cx, _cy, _vw, _vh, _roll, _IW, _IH)
    else:
        _cx = max(_vw / 2, min(_cx, _IW - _vw / 2))
        _cy = max(_vh / 2, min(_cy, _IH - _vh / 2))

    return _prog, _tsec, _cx, _cy, _vw, _vh, _roll


def _resample_modes():
    """(AFFINE, BICUBIC) under both the Pillow 10+ and the legacy enum names."""
    from PIL import Image as _PIL_I

    # Pillow 10+ uses Image.Transform.AFFINE / Image.Resampling.BICUBIC
    try:
        return _PIL_I.Transform.AFFINE, _PIL_I.Resampling.BICUBIC
    except AttributeError:
        return _PIL_I.AFFINE, _PIL_I.BICUBIC  # type: ignore[attr-defined]


def _open_source(log, slot):
    """*slot*'s image as RGB, at least 1920×1080; None when PIL cannot open it."""
    from PIL import Image as _PIL_I

    try:
        _img = _PIL_I.open(slot.img_path).convert('RGB')
    except Exception as _ie:
        log('WARNING', 'Stage 6/KB', f'PIL open failed for slot {slot.index}: {_ie}')
        return None
    _IW, _IH = _img.size
    # A sub-1080p source never goes in silently (S-01): the per-frame
    # affine below bicubic-upsampled a 512×288 smoke still 3.75×
    # without a word. Pre-upscale ONCE with LANCZOS so the source is
    # at least 1920×1080 (aspect preserved) before the Ken Burns crop.
    if _IW < _SLIDE_W or _IH < _SLIDE_H:
        _up_f = max(_SLIDE_W / max(_IW, 1), _SLIDE_H / max(_IH, 1))
        _up_w = max(_SLIDE_W, int(round(_IW * _up_f)))
        _up_h = max(_SLIDE_H, int(round(_IH * _up_f)))
        log(
            'WARNING',
            'Stage 6/KB',
            f'slot {slot.index} source {_IW}x{_IH} smaller than {_SLIDE_W}x{_SLIDE_H} — upsampling {_up_f:.2f}x',
        )
        try:
            _LANCZOS_R = _PIL_I.Resampling.LANCZOS
        except AttributeError:
            _LANCZOS_R = _PIL_I.LANCZOS  # type: ignore[attr-defined]
        _img = _img.resize((_up_w, _up_h), _LANCZOS_R)
    return _img


def _film_look(log, slot, src_size):
    """(plan, overlay, ffmpeg filter) for the documentary look, or (None, None, '').

    Geometry rides the same affine sample the transform already does, so it is
    free; the pixel FX split between numpy (vignette/dust/leak) and the ffmpeg
    graph (halation/CA/breath/grain) by whichever is cheaper there.
    """
    from zyg_workflows import documentary_film_look as _dfl

    try:
        _fl_plan = _dfl.motion_plan(
            slot.index,
            slot.shot_type,
            slot.emotion,
            slot.focal_zone,
            slot.duration,
            slot.fps,
            src_size,
            (_SLIDE_W, _SLIDE_H),
        )
        return _fl_plan, _dfl.FrameOverlay(_fl_plan), _dfl.ffmpeg_filter(_fl_plan)
    except Exception as _fle:
        log('WARNING', 'Stage 6/KB', f'film look disabled for slot {slot.index}: {_fle}')
        return None, None, ''


def _pump_frames(clip, proc):
    """Write every frame of *clip* into *proc*'s stdin; True when the encode lands."""
    import numpy as np

    for _t in range(clip.frames):
        _prog, _tsec, _cx, _cy, _vw, _vh, _roll = view_at(clip, _t)

        # One AFFINE sample carries crop + scale + roll at the
        # same cost the old EXTENT crop had: float source
        # coordinates, bicubic, no integer quantisation.
        _frame = clip.img.transform(
            (_SLIDE_W, _SLIDE_H),
            clip.affine,
            clip.dfl.affine_matrix(_cx, _cy, _vw, _vh, _roll, _SLIDE_W, _SLIDE_H)
            if clip.film_plan is not None
            else (_vw / _SLIDE_W, 0.0, _cx - _vw / 2, 0.0, _vh / _SLIDE_H, _cy - _vh / 2),
            resample=clip.bicubic,
        )

        if clip.overlay is not None and clip.overlay.enabled:
            _arr = np.asarray(_frame)
            if not _arr.flags.writeable:
                _arr = _arr.copy()
            proc.stdin.write(clip.overlay.apply(_arr, _tsec, _prog).tobytes())
        else:
            proc.stdin.write(_frame.tobytes())

    proc.stdin.close()
    proc.wait(timeout=clip.wait_s)
    return proc.returncode == 0 and os.path.getsize(clip.out_path) > 1000


def render_slot(log, slot):
    """Render one Ken Burns clip to slot.out_path using PIL AFFINE+bicubic per-frame."""
    import subprocess as _sp_kb

    from zyg_workflows import documentary_film_look as _dfl

    _img = _open_source(log, slot)
    if _img is None:
        return False
    _IW, _IH = _img.size
    _move = plan_move(slot)
    _fl_plan, _fl_overlay, _fl_vf = _film_look(log, slot, (_IW, _IH))
    _affine, _bicubic = _resample_modes()
    _kb_cmd, _kb_cmd_cpu, _kb_wait_s = encode_commands(slot, _fl_vf)
    _clip = KenBurnsClip(
        img=_img,
        dfl=_dfl,
        slot_idx=slot.index,
        move=_move,
        film_plan=_fl_plan,
        overlay=_fl_overlay,
        frames=max(2, round(slot.duration * slot.fps)),
        fps=slot.fps,
        src_w=_IW,
        src_h=_IH,
        affine=_affine,
        bicubic=_bicubic,
        out_path=slot.out_path,
        wait_s=_kb_wait_s,
    )

    try:
        if _FORCE_CPU_POST_ENCODE:
            _proc = _sp_kb.Popen(_kb_cmd_cpu, stdin=_sp_kb.PIPE, stderr=_sp_kb.DEVNULL)
            return _pump_frames(_clip, _proc)
        with _NVENC_SEM:
            _proc = _sp_kb.Popen(_kb_cmd, stdin=_sp_kb.PIPE, stderr=_sp_kb.DEVNULL)
            return _pump_frames(_clip, _proc)
    except BrokenPipeError:
        try:
            _proc.wait()
        except Exception as _exc:  # noqa: BLE001 — _proc is unbound when Popen itself failed
            _zyg_log.debug('KB encoder not reaped after a broken pipe, init may have failed: %s', _exc)
        return False
    except Exception as _re:
        log('WARNING', 'Stage 6/KB', f'PIL render error slot {slot.index}: {_re}')
        try:
            _proc.kill()
        except Exception as _exc:  # noqa: BLE001 — _proc is unbound when Popen itself failed
            _zyg_log.debug('KB encoder not killed after a render error, it may leak: %s', _exc)
        return False
    finally:
        try:
            _img.close()
        except OSError as _exc:
            _zyg_log.debug('KB source image not closed for slot %s: %s', slot.index, _exc)


def slot_tasks(img_paths, plan, essay_meta, clip_map, kb_tmp_dir):
    """Split the slots into PIL render tasks and ready-made motion clips.

    Returns ({slot index: KenBurnsSlot}, {slot index: motion clip path}); a
    picture with a clip in *clip_map* never gets a Ken Burns task.
    """
    _kb_tasks: dict = {}  # slot_idx → KenBurnsSlot
    _kb_wan: dict = {}  # slot_idx → wan_path
    for _ki in range(len(img_paths)):
        _ip_ki = img_paths[_ki]
        _wan_c = clip_map.get(_ip_ki)
        if _wan_c:
            _kb_wan[_ki] = _wan_c
            continue
        _fz_ki = essay_meta[_ki].get('focal_zone', 'center') if _ki < len(essay_meta) else 'center'
        _kb_tasks[_ki] = KenBurnsSlot(
            index=_ki,
            img_path=_ip_ki,
            out_path=os.path.join(kb_tmp_dir, f'kb_{_ki:03d}.mp4'),
            duration=plan.durations[_ki],
            fps=_KB_FPS,
            shot_type=plan.shot_types[_ki] if _ki < len(plan.shot_types) else '',
            emotion=plan.emotions[_ki] if _ki < len(plan.emotions) else 'calm',
            focal_zone=_fz_ki,
        )
    return _kb_tasks, _kb_wan


def _log_film_look(kb_tasks, env, log, debug):
    """Report the look tier that actually runs, then one plan summary per slot."""
    try:
        from zyg_workflows import documentary_film_look as _dfl6

        _fl_tier = _dfl6.look_tier()
        if _dfl6.look_scale() > 0:
            # Report what actually runs, not the original design.
            # Chromatic aberration was measured and removed (it shifts
            # uniformly rather than radially, so it fringes frame
            # centre and reads as a render artifact), and grain is
            # default-OFF because no setting is both visible and
            # deliverable. Advertising both sent the last debugging
            # pass looking for effects that were never in the chain.
            log(
                'INFO',
                'Stage 6',
                f'Film look "{_fl_tier}": eased motion + handheld/roll/breath, '
                f'vignette{" + dust" if env.dust_on else ""} (numpy), '
                f'halation + grade-breath + micro-contrast (ffmpeg); '
                f'grain {"ON (temporal)" if env.grain_on else "off"}, '
                f'no chromatic aberration',
            )
            for _fk, _ft in sorted(kb_tasks.items()):
                debug(
                    '6/filmlook',
                    _dfl6.plan_summary(
                        _dfl6.motion_plan(
                            _fk, _ft.shot_type, _ft.emotion, _ft.focal_zone, _ft.duration, _ft.fps, (1, 1), (1, 1)
                        )
                    ),
                )
        else:
            log('INFO', 'Stage 6', 'Film look OFF (ZYG_DOC_FILMLOOK=off)')
    except Exception as _fle6:
        log('WARNING', 'Stage 6', f'film look probe failed: {_fle6}')


def _render_parallel(kb_tasks, env, log, debug):
    """Render every queued slot on a thread pool; {slot index: success flag}.

    Each slot is fully independent: own image, own output file, own FFmpeg
    subprocess. PIL's BICUBIC transform is a C extension that releases the GIL,
    so ThreadPoolExecutor gives genuine parallelism. Workers = min(CPU cores,
    n tasks, cap) — the cap defaults to 8 (was 16) because each worker holds
    multiple 5120×2880 frame buffers and 16 workers' combined footprint
    contributed to the 2026-07-05 OOM kills.
    """
    import concurrent.futures as _kb_cf

    _kb_results: dict = {}  # slot_idx → bool (success)
    if not kb_tasks:
        return _kb_results
    _kb_n_workers = min(os.cpu_count() or 4, len(kb_tasks), max(1, env.worker_cap))
    _log_film_look(kb_tasks, env, log, debug)
    log('INFO', 'Stage 6', f'PIL Ken Burns: rendering {len(kb_tasks)} clips on {_kb_n_workers} threads…')

    def _kb_worker(args):
        _ki_w, _task = args
        # Stagger NVENC/ffmpeg startup across slots to avoid session collisions
        # when 16 workers finish PIL open and spawn encoders at once.
        import time as _time_kb

        _time_kb.sleep(_KB_THREAD_STAGGER_S * _ki_w)
        return _ki_w, render_slot(log, _task)

    with _kb_cf.ThreadPoolExecutor(max_workers=_kb_n_workers) as _kb_pool:
        for _ki_r, _ok_r in _kb_pool.map(_kb_worker, kb_tasks.items()):
            _kb_results[_ki_r] = _ok_r
    return _kb_results


def ordered_clips(n_imgs, img_paths, plan, kb_tasks, kb_wan, kb_results, log):
    """The slot-ordered ('pil'|'wan'|'static', path, duration) list, failures logged.

    A slot whose PIL render did not land falls back to its static image, so the
    slideshow keeps its timeline even when an encoder died.
    """
    _kb_clips: list = []  # ordered list of ('pil'|'wan'|'static', path, dur)
    _kb_pil_count = 0
    for _ki in range(n_imgs):
        if _ki in kb_wan:
            _kb_clips.append(('wan', kb_wan[_ki], plan.durations[_ki]))
        elif _ki in kb_tasks:
            if kb_results.get(_ki, False):
                _kb_clips.append(('pil', kb_tasks[_ki].out_path, plan.durations[_ki]))
                _kb_pil_count += 1
            else:
                log('WARNING', 'Stage 6', f'PIL KB render failed slot {_ki} — static fallback')
                _kb_clips.append(('static', img_paths[_ki], plan.durations[_ki]))

    log(
        'INFO',
        'Stage 6',
        f'PIL Ken Burns: rendered {_kb_pil_count}/{n_imgs} clips '
        f'({sum(1 for c in _kb_clips if c[0] == "wan")} WAN, '
        f'{sum(1 for c in _kb_clips if c[0] == "static")} static fallback)',
    )
    return _kb_clips


def render_ken_burns_slots(img_paths, plan, essay_meta, clip_map, out_dir, env, log, debug):
    """Pre-render every image slot; (clip list, the temp dir the renders live in).

    The temp dir is the caller's to remove — the stage does it in the `finally`
    of the slideshow encode, so a failed encode still cleans up.
    """
    _kb_tmp_dir = os.path.join(out_dir, '_kb_tmp')
    os.makedirs(_kb_tmp_dir, exist_ok=True)
    _kb_tasks, _kb_wan = slot_tasks(img_paths, plan, essay_meta, clip_map, _kb_tmp_dir)
    _kb_results = _render_parallel(_kb_tasks, env, log, debug)
    _kb_clips = ordered_clips(len(img_paths), img_paths, plan, _kb_tasks, _kb_wan, _kb_results, log)
    return _kb_clips, _kb_tmp_dir
