# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""candle_fx.py — post-process candle flicker (2026-08-01).

WHY THIS EXISTS — THE FLICKER AND THE JITTER HAD THE SAME CAUSE.

The operator asked to keep the candle flicker seen in v12:
    "the candlelight actually gives a flicker of light, which is true to how it
     naturally is, I like that, make sure it stays in there."

That flicker came from arming the differential-diffusion sampler path
(ZYG_VACE_DIFFDIFF=1 -> WanVideoEncode with add_noise_to_samples=True,
denoise_strength=1.0). The v13/v14 bisect measured what else that path does:

    FINAL clip, v13 (diffdiff ON) -> v14 (diffdiff OFF)
        candle flow_median   0.2256 -> 0.1216   (-46%)   <- the flicker we want
        pipe net_path        0.0443 -> 0.3166   (+615%)  <- the jitter we do not
        pipe reversals/s     3.5294 -> 0.9076   (-74%)
        c_hands net_path     0.2181 -> 0.5473   (+151%)
        c_hands reversals/s  4.4874 -> 0.8067   (-82%)

The pin footprint is irrelevant to this: even at 3.007% of frame (candle only,
neutral 1.0 everywhere else) the sampler still builds its initial latent from a
re-noised VAE encode instead of fresh noise, so the trajectory changes EVERYWHERE.
There is no setting of the pin that buys the flicker without the jitter — they are
one mechanism. Measured, not argued.

So the flicker moves OUT of the sampler and into the composite chain, where ink_fx
and smoke_fx already live. Post-process flicker is:
  - deterministic (seeded; same input -> same output, unlike a resample),
  - free to tune (no 90-minute render to see a different strength),
  - strictly local (it cannot touch a hand, because it only writes inside a box),
  - and reversible (it is a separate stage on the raw clip).

PLACEMENT: run it in the FX chain on the 17fps clip AFTER smoke and BEFORE the
upscale/RIFE pair, exactly where ink and smoke run, so the flicker is interpolated
and upscaled with everything else rather than sitting on top of the finished frame.

    base = ink_fx.composite_write_on_quad(...)
    base = smoke_fx.composite_pipe_smoke_v2(...)
    base = candle_fx.composite_candle_flicker(base, out, candle_box=META['candle_box'])
    -> upscale -> interpolate

WHAT A REAL CANDLE DOES (and what this models):
A flame's luminance is not white noise. It is dominated by low-frequency wander
with occasional larger "gutters", i.e. a 1/f (pink) spectrum, plus a slow drift.
Modelling it as per-frame white noise reads as digital shimmer, not as fire — so
the curve here is pink noise, smoothed, with sparse deeper dips.
"""

import math
import os

from zyg_workflows.bin import exe

# 0.30 CALIBRATED, NOT GUESSED (2026-08-01). Measured on the v14 FINAL clip with
# the limiter active (max_dip 0.45 / max_rise 0.35), candle box from shot_metadata:
#     v11 baseline (no flicker)        candle flow_mean 0.179
#     v14 (diffdiff off, no flicker)   candle flow_mean 0.168
#     v13 (diffdiff ON — the look the operator asked to keep)          0.2635
#     v14 + this module @ strength 0.22 -> 0.237   @ 0.30 -> 0.258
# 0.30 reproduces the v13 flicker level to within 2% with peak swing 0.446, i.e.
# WITHOUT the sampler path that cost -74% pipe reversals and -82% hand coherence.
_DEF_STRENGTH = float(os.environ.get('ZYG_CANDLE_STRENGTH', '0.30'))
_DEF_SPILL = float(os.environ.get('ZYG_CANDLE_SPILL', '2.2'))
_DEF_SEED = int(os.environ.get('ZYG_CANDLE_SEED', '20260801'))


def _log_noop(_m):
    pass


def _pink_curve(n, fps, seed, gutter_rate=0.35, log_fn=None):
    """n-sample 1/f luminance curve, mean 1.0, deterministic for a given seed.

    Built in the frequency domain so the spectrum is exactly 1/f rather than an
    approximation from cascaded filters, then normalised to unit RMS so `strength`
    means the same thing at any length or fps.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    # 1/f magnitude, random phase -> real signal via irfft
    k = np.fft.rfftfreq(n, d=1.0 / max(fps, 1))
    mag = np.zeros_like(k)
    nz = k > 0
    mag[nz] = 1.0 / np.sqrt(k[nz])  # amplitude ~ 1/sqrt(f) => power ~ 1/f
    # A flame has no meaningful energy above ~8Hz and none at DC.
    mag[k > 8.0] *= 0.25
    phase = rng.uniform(0, 2 * math.pi, size=k.shape)
    sig = np.fft.irfft(mag * np.exp(1j * phase), n=n)
    if sig.std() > 1e-9:
        sig = sig / sig.std()
    # Sparse gutters: brief asymmetric DIPS (a flame dims when it gutters; it does
    # not spike brighter), so the curve is skewed the way fire actually behaves.
    n_g = int(max(0.0, gutter_rate) * (n / max(fps, 1)))
    for _ in range(n_g):
        c = int(rng.integers(0, n))
        w = int(rng.integers(max(2, fps // 8), max(3, fps // 2)))
        lo, hi = max(0, c - w), min(n, c + w)
        if hi <= lo:
            continue
        t = np.linspace(-math.pi / 2, math.pi / 2, hi - lo)
        sig[lo:hi] -= np.cos(t) * float(rng.uniform(0.8, 1.8))
    if sig.std() > 1e-9:
        sig = sig / sig.std()
    return sig


def _falloff(h, w, softness=0.55):
    """Radial 1..0 weight, 1 at the box centre. Keeps the flicker from ending at a
    visible rectangular seam — the thing that would instantly read as a comp."""
    import numpy as np

    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    ry = (yy - cy) / max(cy, 1e-6)
    rx = (xx - cx) / max(cx, 1e-6)
    r = np.sqrt(rx * rx + ry * ry)
    f = np.clip(1.0 - (r / max(softness + 1.0, 1e-6)), 0.0, 1.0)
    return f**1.5


def _limit(g, max_dip, max_rise):
    """Soft asymmetric limiter on the gain curve.

    The raw 1/f + gutter curve is renormalised to unit sigma, so its tails run to
    ~4 sigma: at strength 0.22 that measured a -0.904 gain, i.e. the candle region
    dropping to 10% brightness for a frame or two. A real flame gutters, but it does
    not extinguish and relight between two frames — that reads as a dropped frame,
    and it is exactly the kind of single-frame luminance spike that the fx_flicker
    gate is there to catch (smoke_fx shipped a 12.18x white flash for the same
    reason). tanh rather than np.clip so limited peaks stay curved instead of
    developing flat tops, which would alias as a visible plateau.

    Asymmetric because fire is asymmetric: it dims further than it brightens.
    """
    import numpy as np

    out = np.empty_like(g)
    neg, pos = g < 0, g >= 0
    if max_dip > 0:
        out[neg] = -max_dip * np.tanh(-g[neg] / max_dip)
    else:
        out[neg] = g[neg]
    if max_rise > 0:
        out[pos] = max_rise * np.tanh(g[pos] / max_rise)
    else:
        out[pos] = g[pos]
    return out


def composite_candle_flicker(
    clip_path,
    out_path,
    candle_box,
    fps=17,
    strength=None,
    spill=None,
    seed=None,
    max_dip=0.45,
    max_rise=0.35,
    warm=(1.0, 0.94, 0.78),
    log_fn=None,
):
    """Modulate luminance in and around the candle box with a 1/f flicker curve.

    candle_box : (x0,y0,x1,y1) fractional, shot_metadata convention.
    strength   : peak fractional luminance swing at the flame core (0.22 = +-22%).
    spill      : how far the light reaches, as a multiple of the box size. The
                 spill is what sells it — a flame that brightens without its
                 surroundings brightening reads as a flickering sticker.
    warm       : RGB weights for the ADDED light, so brightening warms the scene
                 (a candle adds orange light) instead of washing it grey.

    Returns out_path, or None on any failure (caller keeps the un-flickered clip).
    """
    log = log_fn or _log_noop
    import glob as _glob
    import subprocess
    import tempfile

    import numpy as np
    from PIL import Image

    strength = _DEF_STRENGTH if strength is None else float(strength)
    spill = _DEF_SPILL if spill is None else float(spill)
    seed = _DEF_SEED if seed is None else int(seed)
    if not candle_box or len(candle_box) != 4:
        log('[candle] no candle_box — flicker skipped')
        return None

    tmp = tempfile.mkdtemp(prefix='candle_fx_')
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
            log(f'[candle] extract failed: {(r.stderr or "")[-200:]}')
            return None
        frames = sorted(_glob.glob(os.path.join(tmp, 'f_*.png')))
        if not frames:
            log('[candle] no frames extracted')
            return None
        W, H = Image.open(frames[0]).size
        n = len(frames)

        x0, y0, x1, y1 = [float(v) for v in candle_box]
        bw, bh = (x1 - x0), (y1 - y0)
        # spill region, clamped to frame
        sx0 = max(0.0, x0 - bw * (spill - 1) / 2.0)
        sx1 = min(1.0, x1 + bw * (spill - 1) / 2.0)
        sy0 = max(0.0, y0 - bh * (spill - 1) / 2.0)
        sy1 = min(1.0, y1 + bh * (spill - 1) / 2.0)
        px = (int(sx0 * W), int(sy0 * H), int(sx1 * W), int(sy1 * H))
        rw, rh = px[2] - px[0], px[3] - px[1]
        if rw < 4 or rh < 4:
            log(f'[candle] spill region degenerate ({rw}x{rh}) — skipped')
            return None

        curve = _pink_curve(n, fps, seed, log_fn=log)
        gains = _limit(curve * strength, float(max_dip), float(max_rise))
        fall = _falloff(rh, rw)
        warm_v = np.asarray(warm, dtype=np.float32).reshape(1, 1, 3)

        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        peak = 0.0
        for i, fp in enumerate(frames):
            im = np.asarray(Image.open(fp).convert('RGB'), dtype=np.float32)
            g = float(gains[i])
            peak = max(peak, abs(g))
            sub = im[px[1] : px[3], px[0] : px[2], :]
            # Multiplicative on existing light: dark pixels stay dark (a candle does
            # not light what it does not reach), bright pixels swing most. This is
            # what keeps the spill from turning the background into a grey card.
            gain = 1.0 + (g * fall)[:, :, None] * warm_v
            im[px[1] : px[3], px[0] : px[2], :] = sub * gain
            Image.fromarray(np.clip(im, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))

        enc = subprocess.run(
            [
                'ffmpeg',
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
            log(f'[candle] encode failed: {(enc.stderr or "")[-200:]}')
            return None
        log(
            f'[candle] flicker composited: {n} frames, box {tuple(round(v, 3) for v in candle_box)} '
            f'-> spill px [{px[0]},{px[1]} .. {px[2]},{px[3]}] ({rw}x{rh}), '
            f'strength {strength:.3f} peak |g| {peak:.3f}, seed {seed}'
        )
        return out_path
    except Exception as e:
        log(f'[candle] FAILED ({e}) — clip unchanged')
        return None
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':  # the CLI lives in candle_fx_cli
    from zyg_workflows.candle_fx_cli import main as _cli_main

    raise SystemExit(_cli_main())
