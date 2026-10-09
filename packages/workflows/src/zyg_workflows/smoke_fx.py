# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""smoke_fx.py — deterministic pipe-smoke compositing (2026-07-30, continuity rebuild 2026-07-31).

Why: Wan has ONE global text embedding — 'smoke rises from HIS pipe' cannot be bound to
the right character (benchmarked wrong-subject action failure; our v5 gave the boy the
smoke). The honest production answer is to generate the scene SMOKE-FREE and composite
the smoke procedurally, pinned at the pipe bowl: ownership, timing and continuity become
deterministic. Static camera + VACE-locked layout => a fixed pin, no rotoscoping.

    composite_pipe_smoke(clip, out, pin=(fx,fy), puffs=[(t0,dur,strength),...],
                         takeover_start=None, fps=17)

Each puff emits a rising, curling plume from the pin (multi-octave scrolling noise shaped
by a distance field along a buoyant path). takeover_start ramps a full-screen smoke fill
from that time to the end (scene-out). Pure numpy/PIL — commercially clean.

2026-07-31 CONTINUITY REBUILD — why: measured on the finished film, the SMOKE TAKEOVER was
the largest discontinuity in every version, bigger than anything the diffusion model itself
produced. Reproduced on scene20_v9/inked17.mp4 (clip's own mean frame difference 0.854 grey
levels): the compositor injected a 12.2x-mean spike at 19.47s and an 8.4x spike at 17.53s.
Four distinct causes, all fixed here:

  1. int()-QUANTISED NOISE SCROLL. `np.roll(b1, int(t * 2.0))` made the noise field a
     STAIRCASE — frozen for 5-8 frames, then a whole-base-cell jump (measured mean |dnoise|
     was 0.0 on most frames and 0.117-0.144 on step frames). Under takeover alpha ~0.5 that
     alone produced the 8.4x spike at 17.53s. The field is now sampled CONTINUOUSLY at
     fractional cell offsets with smootherstep interpolation, so it advects instead of
     stepping, and the whole plume field evolves in absolute time (nothing is re-randomised
     per emission).

  2. TERMINAL WHITE FLASH. `if t > (n/fps) - 0.6: alpha = max(alpha, 1.0)` moved alpha from
     0.9007 to 1.0 across the WHOLE frame in ONE frame step (measured d_alpha 0.0993 x the
     clip's measured 106-grey plate/smoke contrast = 10.5 grey = 12.2x mean: the single worst
     frame in the film). Gone — the coverage geometry now reaches full white-out by
     construction at exactly the last frame, along a monotone ease.

  3. HARD TAKEOVER GATE. `if t >= takeover_start` switched a coverage blob on instantly, and
     the radius then advanced linearly, so the mean alpha rate swung wildly as the disc grew
     and then saturated against the frame edges. The ramp is now a monotone C1 trapezoid ease
     (peak slope 1.22x its average, where a plain smoothstep peaks at 1.5x) and the coverage
     radius is SOLVED each frame so the mean alpha tracks that ease exactly — for any pin,
     aspect or dither. Near-constant mean-alpha rate is the whole ball game: the total travel
     is fixed at 1.0, so only the peak rate is negotiable.

  4. PER-EMISSION POP. Bowl puffs were cut dead at age 3.0s while their envelope was still
     at 0.889, they were combined with a hard np.maximum (which switches at plume crossings),
     and every emission restarted its sway phase from zero. Emissions now cross-fade in AND
     out (envelope is exactly 0 with zero slope at both ends of the life), combine through a
     smooth p-norm soft-max, and take their sway/turbulence from absolute time.

Plus a SLEW LIMITER derived from the clip's OWN statistics: the compositor measures the
footage's natural mean per-frame grey difference and refuses to add more than `slew_x` times
that per frame, scaling the whole alpha INCREMENT uniformly (a global gain, so no per-pixel
kink is introduced). The composite can therefore never again out-jump the footage it sits on,
whatever pins or draw times a future shot supplies.
"""

import glob
import os
import shutil
import subprocess
import tempfile

import numpy as np
from zyg_workflows.bin import exe
from PIL import Image

# combination exponent for overlapping emissions: a smooth p-norm soft-max. p=4 tracks the
# old np.maximum closely (two equal 0.18 plumes -> 0.214, not 0.33) so the established look
# survives, but it is differentiable everywhere, so crossing plumes no longer switch.
_PNORM = 4.0
_GREY = np.array([0.299, 0.587, 0.114], dtype=np.float32)
_SMOKE_RGB = np.array([170.0, 170.0, 174.0], dtype=np.float32)
# Grain amplitude of the takeover dissolve, in units of the soft edge band. The old code's
# `+ 1.1 * noise` over a unit-wide clip band gave a +/-0.16 alpha speckle; smootherstep is
# 1.875x steeper than that clip, so 0.6 here reproduces the original soft grain. Higher
# values (2.2 was tried) read as a blotchy disintegration wipe, not smoke.
_TAKE_NOISE = 0.6
_GRID_CACHE = {}


def _log_noop(_m):
    pass


def _smootherstep(x):
    """C2 0->1 ease (Perlin's 6t^5-15t^4+10t^3). Zero first AND second derivative at both
    ends — used everywhere a hard clip/where used to be, so nothing pops on or off."""
    x = np.clip(x, 0.0, 1.0)
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def _smootherstep_int(x):
    """Antiderivative of _smootherstep on [0,1] (equals 0.5 at x=1) — lets the trapezoid
    ease below be written in closed form."""
    return x**6 - 3.0 * x**5 + 2.5 * x**4


def _ease_trapezoid(u, k=0.18):
    """Monotone C1 ramp 0->1 whose SLOPE eases in over the first k, stays flat, then eases
    out over the last k. Peak slope is 1/(1-k) = 1.22x the average (a smoothstep peaks at
    1.5x, a raw linear ramp has a slope discontinuity at both ends). Minimising the PEAK
    rate for a fixed total travel is exactly what keeps the frame-difference flat."""
    u = float(min(max(u, 0.0), 1.0))
    k = float(min(max(k, 1e-3), 0.49))
    if u <= k:
        v = k * _smootherstep_int(u / k)
    elif u < 1.0 - k:
        v = k * 0.5 + (u - k)
    else:
        v = (1.0 - k) - k * _smootherstep_int((1.0 - u) / k)
    return v / (1.0 - k)


def _make_noise_bank(seed):
    """Static lattices sampled continuously later. Octaves rise at slightly different
    speeds and drift sideways on incommensurate periods, so the field never repeats and
    never needs re-seeding mid-shot."""
    g = np.random.default_rng(seed)
    return {
        # (lattice, rise px/s, sideways amplitude px, sideways period s, weight)
        # Lattices are deliberately FINE (13/6.5/3.3 px cells at 480p). A coarse lattice
        # plus smootherstep interpolation renders as visible squares once the takeover
        # dissolve is driven by it — measured as a blocky amoeba in the first rebuild.
        'detail': [
            (g.random((36, 64)).astype(np.float32), 11.5, 26.0, 13.7, 0.42),
            (g.random((72, 128)).astype(np.float32), 13.3, 17.0, 9.1, 0.34),
            (g.random((144, 256)).astype(np.float32), 15.4, 11.0, 6.3, 0.24),
        ],
        # room haze that drives the takeover DISSOLVE. Fine-grained but SLOW: this field sets
        # a threshold over a large part of the frame at once, so running it at plume speed
        # demanded ~12x the clip's mean frame difference per frame (measured) and pinned the
        # slew limiter open. It is the right split physically too — the plume rises fast off
        # the bowl, the room haze drifts.
        'haze': [
            (g.random((56, 96)).astype(np.float32), 1.2, 7.0, 17.3, 0.55),
            (g.random((112, 192)).astype(np.float32), 1.7, 4.0, 11.7, 0.45),
        ],
        # slow field, used ONLY to tint the smoke: once coverage reaches 1.0 the plate is
        # fully hidden and this field IS the picture, so its temporal derivative has to be
        # small or the white-out shimmers.
        'slow': (g.random((40, 68)).astype(np.float32), 3.2, 9.0, 21.3),
    }


def _sample_octave(base, W, H, off_y, off_x):
    """Bilinear-with-smootherstep-weights sample of a periodic lattice at FRACTIONAL offset.
    Separable: the row index depends only on y and the column index only on x, so the four
    corner gathers are np.ix_ views — as cheap as the old PIL resize, but continuous."""
    cy, cx = base.shape
    vy = np.arange(H, dtype=np.float32) * (cy / float(H)) + off_y
    vx = np.arange(W, dtype=np.float32) * (cx / float(W)) + off_x
    fy = np.floor(vy)
    fx = np.floor(vx)
    wy = _smootherstep(vy - fy)[:, None]
    wx = _smootherstep(vx - fx)[None, :]
    iy0 = fy.astype(np.int64) % cy
    ix0 = fx.astype(np.int64) % cx
    iy1 = (iy0 + 1) % cy
    ix1 = (ix0 + 1) % cx
    top = base[np.ix_(iy0, ix0)] * (1.0 - wx) + base[np.ix_(iy0, ix1)] * wx
    bot = base[np.ix_(iy1, ix0)] * (1.0 - wx) + base[np.ix_(iy1, ix1)] * wx
    return top * (1.0 - wy) + bot * wy


def _octave_stack(octaves, W, H, t, gain=1.0):
    f = None
    for base, rise, amp, period, weight in octaves:
        cy, cx = base.shape
        off_y = t * rise * (cy / float(H))
        off_x = np.sin(t * (2.0 * np.pi / period)) * amp * (cx / float(W))
        o = _sample_octave(base, W, H, off_y, off_x)
        f = o * weight if f is None else f + o * weight
    return np.clip(0.5 + (f - 0.5) * gain, 0.0, 1.0)


def _haze_field(bank, W, H, t):
    """Slow-drifting dissolve field for the takeover (see _make_noise_bank)."""
    return _octave_stack(bank['haze'], W, H, t, gain=1.25)


def _noise_fields(bank, W, H, t):
    """(detail, slow) in 0..1, both continuous and differentiable in t — the replacement for
    the old int()-quantised np.roll staircase."""
    det = _octave_stack(bank['detail'], W, H, t, gain=1.25)  # restore the old contrast
    sb, srise, samp, speriod = bank['slow']
    scy, scx = sb.shape
    slow = _sample_octave(
        sb, W, H, t * srise * (scy / float(H)), np.sin(t * (2.0 * np.pi / speriod)) * samp * (scx / float(W))
    )
    return det, slow


def _grids(W, H):
    if (W, H) not in _GRID_CACHE:
        yy, xx = np.mgrid[0:H, 0:W]
        _GRID_CACHE[(W, H)] = (xx.astype(np.float32), yy.astype(np.float32))
    return _GRID_CACHE[(W, H)]


def _emission_env(age, life, attack=0.45, release=1.7):
    """Cross-fade envelope for ONE emission: exactly 0 with zero slope at age 0 and at
    age == life. The old envelope was still at 0.889 when the puff was hard-dropped at
    age 3.0 — that step, repeated every 1.4s, was the per-emission pop."""
    if age <= 0.0 or age >= life:
        return 0.0
    release = min(release, max(life - attack, 1e-3))
    a = float(_smootherstep(age / attack))
    r = float(_smootherstep((life - age) / release))
    return a * r


def _plume_alpha(W, H, pin, t, age, strength, noise, life, phase=0.0):
    """Alpha field of one plume: starts at the pin, rises with slight sway, widens and fades
    as it ages. `age` is seconds since this emission started (shape/size), `t` is ABSOLUTE
    time (sway/turbulence) — so the air the plumes sit in keeps moving continuously instead
    of every emission restarting its sway from zero."""
    env = _emission_env(age, life)
    if env <= 0.0:
        return None
    xx, yy = _grids(W, H)
    px, py = pin[0] * W, pin[1] * H
    rise = age * H * 0.16
    dy = py - yy
    along = dy / max(rise + H * 0.05, 1e-3)
    along_clip = np.clip(along, 0.0, 1.15)
    width = W * (0.012 + 0.075 * along_clip) * (0.7 + 0.6 * float(_smootherstep(age / 2.5)))
    sway = np.sin(t * 1.7 + phase + along_clip * 1.9) * (W * 0.015)
    dx = np.abs(xx - (px + sway * along_clip))
    lateral = np.clip(1.0 - dx / np.maximum(width, 1e-3), 0.0, 1.0)
    # head and root tapers are smootherstep, not np.where: the old hard cuts were spatial
    # edges of ~0.2-0.27 alpha that MOVED upward with the plume head every frame.
    core = np.clip(1.0 - np.abs(along - 0.55) / 0.75, 0.0, 1.0)
    head = _smootherstep((1.15 - along) / 0.28)
    root = _smootherstep(dy / (H * 0.02) + 1.0)
    dens = np.clip(lateral * core * head * root * (0.55 + 0.8 * noise) - 0.18, 0.0, 1.0)
    return dens * (strength * env)


def _natural_frame_stats(clip_path, W, H):
    """The clip's OWN mean per-frame grey difference — the yardstick the composite is held
    to. Raw grey pipe, ~1s for a 20s 480p clip. Returns None on any failure (the caller
    then falls back to a conservative fixed budget rather than refusing to render)."""
    try:
        p = subprocess.Popen(
            [exe('ffmpeg'), '-v', 'error', '-i', clip_path, '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
            stdout=subprocess.PIPE,
        )
        fsz = W * H
        prev = None
        acc = []
        while True:
            buf = p.stdout.read(fsz)
            if len(buf) < fsz:
                break
            cur = np.frombuffer(buf, dtype=np.uint8).astype(np.float32)
            if prev is not None:
                acc.append(float(np.mean(np.abs(cur - prev))))
            prev = cur
        p.stdout.close()
        p.wait()
        if len(acc) < 8:
            return None
        return float(np.mean(acc))
    except Exception:
        return None


def _take_cover(dist, haze, reach, soft, amp):
    """Takeover coverage in 0..1 for a given radius. One expression, shared by the solver
    and the renderer, so the closed loop below is solving the field it actually draws."""
    return _smootherstep((reach - dist) / soft + (haze - 0.5) * (_TAKE_NOISE * amp))


def _take_density(e):
    """Global opacity of the takeover haze, 0.35 -> 1.0 (the old `0.3 + 0.7*tt`). Without
    it the dissolve is binary — pixels are either untouched or fully opaque grey, which
    reads as a disintegration wipe rather than a room filling with smoke."""
    return 0.35 + 0.65 * e


def _solve_reach(sub_dist, sub_haze, soft, amp, target, rmax, iters=18):
    """Closed loop: find the coverage radius whose MEAN coverage equals `target` right now,
    for this shot's actual pin geometry and this frame's actual haze.

    Why closed loop rather than a precomputed radius ramp: mean coverage is a strongly
    non-linear function of radius (the disc's area grows quadratically, then saturates
    against the frame edges) AND it depends on the live dither amplitude. Any open-loop
    radius schedule therefore advances the mean alpha at a wildly varying rate mid-takeover,
    which is precisely a frame-difference bump. Solving each frame makes d(mean alpha)/dt
    equal the ease curve's slope BY CONSTRUCTION — for any pin, any aspect, any dither.
    18 bisection steps on a 1/9-subsampled grid is ~5 ms/frame and only runs during takeover.
    """
    lo = -soft * 3.5
    hi = rmax
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if float(_take_cover(sub_dist, sub_haze, mid, soft, amp).mean()) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def composite_pipe_smoke_v2(
    clip_path,
    out_path,
    bowl_pin=None,
    mouth_pin=None,
    draw_times=None,
    takeover_start=None,
    fps=17,
    log_fn=None,
    slew_x=2.5,
):
    """TWO-LAYER pipe smoke (2026-07-30 ergonomics research): a thin CONTINUOUS wisp from
    the BOWL (strengthened around draws) + discrete EXHALE clouds from the MOUTH ~1s after
    each draw (2-4s dissipation). Real smoke never comes from the stem. Pins are MANDATORY
    shot-metadata values derived from the anchor (bowl centroid, lip centroid) — this
    function REFUSES to run without them (the mid-stem bug came from a hardcoded guess).
    draw_times: [t_seconds, ...] — a 20s clip should have at most ONE OR TWO draws
    (real cadence: 1-3s sips; constant puffing is an AI tell).
    slew_x: the composite may add at most slew_x x the clip's own mean frame difference per
    frame (2026-07-31; see module docstring)."""
    log = log_fn or _log_noop
    if not bowl_pin or not mouth_pin:
        log('[smoke2] REFUSING: bowl_pin/mouth_pin metadata missing — derive from anchor, never guess')
        return None
    draw_times = draw_times if draw_times is not None else []
    puffs = []
    # continuous bowl wisp = many weak overlapping plumes from the bowl
    # (implemented via the takeover-free plume model at low strength, re-emitted)
    tmp_probe = subprocess.run(
        [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', clip_path],
        capture_output=True,
        text=True,
    )
    try:
        dur = float(tmp_probe.stdout.strip())
    except Exception:
        dur = 20.0
    t = 0.0
    while t < dur - 1.0:
        near_draw = any(abs(t - d) < 2.0 for d in draw_times)
        puffs.append(('bowl', t, 0.35 if near_draw else 0.18))
        t += 1.4
    # exhale clouds from the mouth, 1s after each draw
    for d in draw_times:
        puffs.append(('mouth', d + 1.0, 0.8))
    return _composite_layers(
        clip_path, out_path, bowl_pin, mouth_pin, puffs, takeover_start, fps, log, seed=13, slew_x=slew_x
    )


def _composite_layers(clip_path, out_path, bowl_pin, mouth_pin, puffs, takeover_start, fps, log, seed=13, slew_x=2.5):
    tmp = tempfile.mkdtemp(prefix='smokefx2_')
    try:
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                clip_path,
                '-vsync',
                '0',
                os.path.join(tmp, 'f_%05d.png'),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log('[smoke2] extract failed')
            return None
        frames = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))
        n = len(frames)
        if n < 8:
            return None
        W, H = Image.open(frames[0]).size
        total_s = n / float(fps)
        bank = _make_noise_bank(seed)
        xx, yy = _grids(W, H)

        # --- the budget, measured from THIS clip -------------------------------------
        nat = _natural_frame_stats(clip_path, W, H)
        if nat is None or nat <= 1e-3:
            nat = 1.0
            log('[smoke2] natural frame-diff probe failed — using conservative default 1.0')
        budget = float(slew_x) * nat

        # --- takeover geometry, solved per frame against this shot --------------------
        # `soft` is WIDE on purpose: the established look is a room-filling gradient with
        # grain on top, NOT an expanding disc. The old code got that from
        # `(tt*1.7 - dist)*2.6`, i.e. an edge band 1/2.6 = 0.385 wide in normalised distance.
        # Narrowing it (0.11 was tried) turns the scene-out into a grey amoeba.
        soft = 0.385
        dist = np.sqrt(((xx / W) - bowl_pin[0]) ** 2 + ((yy / H) - bowl_pin[1]) ** 2)
        sub_dist = dist[::3, ::3]
        rmax = float(dist.max()) + soft * 2.5
        span = max(total_s - float(takeover_start), 1e-3) if takeover_start is not None else 0.0

        # 'mouth' emissions are big exhale clouds and live longer than the bowl wisp
        life_of = {'mouth': 4.6, 'bowl': 3.0}
        phases = {}
        for idx, (kind, t0, _s) in enumerate(puffs):
            phases[(kind, t0)] = idx * 2.399963  # golden-angle: deterministic, decorrelated

        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        prev_alpha = np.zeros((H, W), dtype=np.float32)
        prev_take = np.zeros((H, W), dtype=np.float32)
        limited = 0
        peak_pred = 0.0
        for i, fp in enumerate(frames):
            t = i / float(fps)
            img = np.asarray(Image.open(fp).convert('RGB'), dtype=np.float32)
            det = slow = None
            active = [(k, t0, s) for (k, t0, s) in puffs if 0.0 < (t - t0) < life_of.get(k, 3.0)]
            in_takeover = takeover_start is not None and t >= float(takeover_start)
            if active or in_takeover or prev_alpha.max() > 0.0:
                det, slow = _noise_fields(bank, W, H, t)

            # --- plume layer: smooth p-norm soft-max over cross-faded emissions -------
            acc = None
            for kind, t0, strength in active:
                a = _plume_alpha(
                    W,
                    H,
                    mouth_pin if kind == 'mouth' else bowl_pin,
                    t,
                    t - t0,
                    strength,
                    det,
                    life_of.get(kind, 3.0),
                    phases[(kind, t0)],
                )
                if a is None:
                    continue
                ap = a**_PNORM
                acc = ap if acc is None else acc + ap
            plume = (acc ** (1.0 / _PNORM)) if acc is not None else np.zeros((H, W), np.float32)

            # --- takeover layer: continuous, calibrated, globally monotone -----------
            # The GLOBAL progression e is strictly monotone with zero slope at both ends;
            # per-pixel the dissolve drifts with the haze (physically right, and it must be
            # allowed to, because ratcheting a strong dither with a running max makes every
            # pixel jump to its local noise maximum within a second — measured as both a
            # look and a rate regression). Full white-out is reached by construction: the
            # noise amplitude decays to 0 while reach grows past the far corner.
            take = prev_take
            if in_takeover:
                e = _ease_trapezoid((t - float(takeover_start)) / span)
                # noise amplitude eases IN as well as out: at e=0 mean coverage must be 0,
                # so dither at that instant would flash coverage on in one frame — that is
                # exactly the old `+ 1.1*noise - 0.45` onset pop.
                amp = float(_smootherstep(e / 0.18)) * (1.0 - e) ** 1.1
                haze = _haze_field(bank, W, H, t)
                dens = _take_density(e)
                # solve for the coverage that makes MEAN ALPHA equal the ease curve, then
                # apply the density envelope: mean(take) == e exactly, every frame.
                reach = _solve_reach(sub_dist, haze[::3, ::3], soft, amp, min(e / dens, 1.0), rmax)
                take = _take_cover(dist, haze, reach, soft, amp) * dens
                prev_take = take

            alpha_raw = 1.0 - (1.0 - plume) * (1.0 - take)

            # --- slew limiter: a GLOBAL gain on the increment, never a per-pixel clip --
            if slow is None:
                alpha = alpha_raw
            else:
                smoke_col = _SMOKE_RGB * (0.86 + 0.14 * slow[:, :, None])
                d_alpha = alpha_raw - prev_alpha
                contrast = np.abs(img @ _GREY - (smoke_col @ _GREY))
                pred = float(np.mean(np.abs(d_alpha) * contrast))
                peak_pred = max(peak_pred, pred)
                if pred > budget:
                    d_alpha *= budget / pred
                    limited += 1
                alpha = np.clip(prev_alpha + d_alpha, 0.0, 1.0)
                if alpha.max() > 0.01:
                    a3 = alpha[:, :, None]
                    img = img * (1.0 - a3) + smoke_col * a3
            prev_alpha = alpha
            Image.fromarray(np.clip(img, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
        enc = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-framerate',
                str(fps),
                '-i',
                os.path.join(outdir, 'o_%05d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '16',
                out_path,
            ],
            capture_output=True,
            text=True,
        )
        if enc.returncode != 0:
            log('[smoke2] encode failed')
            return None
        log(
            f'[smoke2] composite done ({len(puffs)} emissions); clip mean frame-diff '
            f'{nat:.3f}, budget {budget:.3f}/frame, peak composite delta {peak_pred:.3f}'
            f' ({peak_pred / max(nat, 1e-6):.2f}x clip mean), slew-limited on {limited} frame(s)'
        )
        return out_path
    except Exception as e:
        log(f'[smoke2] failed ({e})')
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def composite_pipe_smoke(
    clip_path, out_path, pin=(0.33, 0.52), puffs=None, takeover_start=None, fps=17, log_fn=None, slew_x=2.5
):
    """Composite pipe smoke over a (smoke-free) clip. puffs: [(t_start_s, dur_ignored,
    strength0..1), ...]. takeover_start: seconds — full-screen smoke ramp until the end.
    Returns out_path or None. 2026-07-31: single-pin legacy entry, now delegating to the
    continuity-fixed layered path so both entries share one (measured) smoothness guarantee.
    Emissions are tagged 'mouth' purely for its 4.6s life, which matches this entry's original
    fade-to-zero at age 4.6 — both pins are the caller's single pin, so the tag is otherwise
    inert."""
    log = log_fn or _log_noop
    lay = [('mouth', float(t0), float(s)) for (t0, _dur, s) in (puffs or [])]
    return _composite_layers(clip_path, out_path, pin, pin, lay, takeover_start, fps, log, seed=11, slew_x=slew_x)
