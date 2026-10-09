# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""documentary_film_look.py — makes documentary stills feel alive.

Stage 6 used to hand each FLUX still a single linear Ken Burns move: constant
velocity in, hard stop at the cut, nothing else changing. Mathematically smooth,
but it reads as a slideshow because nothing in a real photographed frame is ever
that still.

This module adds the two things that sell "photographed" over "rendered", split
by where each one is cheapest to compute:

  MOTION (geometry) — eased acceleration, handheld breathing, roll drift and a
      slow breathing zoom. All of it folds into the SAME single PIL affine
      sample the renderer already does per frame, so it is free.

  LIGHT (photographic) — vignette, drifting dust motes and light leaks in numpy
      (precomputed masks, per-frame scalars); halation, exposure/temperature
      breath and micro-contrast in the ffmpeg filter graph, where they run in C.

The split matters. ffmpeg's own `vignette` costs ~2.6 CPU-s per 5s of 1080p30;
the numpy equivalent here costs ~0.13. Everything else is cheaper in ffmpeg than
it would be in Python. Measured, not guessed.

Film grain is deliberately NOT part of the default look. It has to be applied
at the very last encode to survive at all, and measured there it costs 9x the
bitrate at any strength where it is actually visible. See final_grain_filter()
for the numbers; opt in with ZYG_DOC_FILMLOOK_GRAIN=1.

Tier via env ZYG_DOC_FILMLOOK: off | subtle | standard | rich  (default standard)
Dust can be forced off with ZYG_DOC_FILMLOOK_DUST=0.
"""

import math
import os

import numpy as np

__all__ = [
    'look_tier',
    'look_scale',
    'motion_plan',
    'sample_geometry',
    'clamp_view',
    'affine_matrix',
    'FrameOverlay',
    'ffmpeg_filter',
    'final_grain_filter',
    'plan_summary',
]

# ── Tiers ────────────────────────────────────────────────────────────────────
_TIER_SCALE = {'off': 0.0, 'subtle': 0.55, 'standard': 1.0, 'rich': 1.45}
_DEFAULT_TIER = 'standard'


def look_tier() -> str:
    t = (os.environ.get('ZYG_DOC_FILMLOOK') or _DEFAULT_TIER).strip().lower()
    return t if t in _TIER_SCALE else _DEFAULT_TIER


def look_scale() -> float:
    return _TIER_SCALE[look_tier()]


def _dust_enabled() -> bool:
    return (os.environ.get('ZYG_DOC_FILMLOOK_DUST') or '1').strip() not in ('0', 'false', 'no')


# ── Per-emotion look profile ─────────────────────────────────────────────────
# Keys mirror the emotion vocabulary Murch already assigns per slot, so the look
# tracks the emotional arc the pipeline computed rather than a global preset.
#   handheld  px of breathing sway at 1080p       roll      degrees of drift
#   grain     ffmpeg noise strength
#   halation  screen-blend opacity of the bloom   vig       vignette depth 0-1
#   warm      gamma_r/gamma_b bias (+warm/-cool)  breath    exposure breath amp
#   dust      dust-mote density multiplier
_EMOTION_LOOK = {
    'shock': dict(handheld=2.6, roll=0.30, grain=9, halation=0.10, vig=0.40, warm=-0.020, breath=0.012, dust=0.0),
    'tension': dict(handheld=1.8, roll=0.22, grain=7, halation=0.12, vig=0.36, warm=-0.012, breath=0.009, dust=0.3),
    'triumph': dict(handheld=0.7, roll=0.10, grain=4, halation=0.26, vig=0.24, warm=+0.030, breath=0.007, dust=0.5),
    'awe': dict(handheld=0.6, roll=0.12, grain=4, halation=0.30, vig=0.26, warm=+0.020, breath=0.006, dust=0.7),
    'unease': dict(handheld=1.5, roll=0.28, grain=7, halation=0.12, vig=0.38, warm=-0.020, breath=0.010, dust=0.5),
    'mystery': dict(handheld=0.9, roll=0.16, grain=6, halation=0.16, vig=0.44, warm=-0.010, breath=0.008, dust=1.0),
    'calm': dict(handheld=0.5, roll=0.08, grain=4, halation=0.18, vig=0.28, warm=+0.020, breath=0.006, dust=0.6),
    'grief': dict(handheld=0.6, roll=0.14, grain=5, halation=0.14, vig=0.42, warm=-0.030, breath=0.005, dust=0.8),
}
_LOOK_FALLBACK = _EMOTION_LOOK['calm']


# ── Easing ───────────────────────────────────────────────────────────────────
# A camera operator's move accelerates and settles. Linear progress is the main
# reason the old slideshow read as mechanical, and easing costs nothing.
def _ease_smooth(p):  # ease in AND out — the documentary default
    return p * p * (3.0 - 2.0 * p)


def _ease_out(p):  # starts moving immediately, settles — reactive shots
    return 1.0 - (1.0 - p) ** 3


def _ease_in(p):  # creeps, then commits — reveals
    return p * p * p


_EASINGS = {'smooth': _ease_smooth, 'out': _ease_out, 'in': _ease_in, 'linear': lambda p: p}


def motion_plan(slot_idx, shot_type, emotion, focal_zone, dur, fps, img_size, out_size):
    """Everything about how one slot moves and is graded. Deterministic in slot_idx."""
    scale = look_scale()
    emo = (emotion or 'calm').lower()
    look = dict(_EMOTION_LOOK.get(emo, _LOOK_FALLBACK))
    sl = (shot_type or '').lower()

    # Interiors and close work carry visible air; open sky and aerials do not.
    dust_mult = 1.0
    if any(k in sl for k in ('aerial', 'drone', 'overhead', 'bird')):
        dust_mult = 0.0
    elif any(k in sl for k in ('interior', 'close', 'intimate', 'macro')):
        dust_mult = 1.35
    elif any(k in sl for k in ('wide', 'establishing', 'landscape', 'panorama')):
        dust_mult = 0.45
    look['dust'] *= dust_mult

    for k in ('handheld', 'roll', 'grain', 'halation', 'vig', 'breath', 'dust'):
        look[k] *= scale
    look['warm'] *= scale

    # Easing choice follows the emotional register, not the shot geometry:
    # urgent beats start already moving, reveals creep in, everything else eases.
    if emo in ('shock', 'tension'):
        ease = 'out'
    elif emo in ('mystery', 'awe'):
        ease = 'in'
    else:
        ease = 'smooth'

    rng = np.random.RandomState(1000 + int(slot_idx))
    # Two incommensurate frequencies per axis so the sway never visibly repeats.
    plan = {
        'slot': int(slot_idx),
        'emotion': emo,
        'shot_type': sl,
        'ease': ease,
        'dur': float(dur),
        'fps': float(fps),
        'img_size': tuple(img_size),
        'out_size': tuple(out_size),
        'look': look,
        'hh_amp': float(look['handheld']),
        'hh_fx': (0.083 + 0.037 * rng.rand(), 0.191 + 0.061 * rng.rand()),
        'hh_fy': (0.071 + 0.041 * rng.rand(), 0.223 + 0.055 * rng.rand()),
        'hh_ph': tuple(rng.rand(4) * 6.2831853),
        # Roll direction alternates so consecutive shots never drift the same way.
        'roll_deg': float(look['roll']) * (1.0 if slot_idx % 2 == 0 else -1.0),
        'roll_ph': float(rng.rand() * 6.2831853),
        # Breathing zoom: a slow oscillation on top of the primary move, so even
        # a nominally static drift shot is never actually still.
        'breath_amp': 0.0035 * (0.6 + 0.8 * rng.rand()) * scale,
        'breath_per': 7.0 + 5.0 * rng.rand(),
        'seed': int(1000 + slot_idx),
    }
    return plan


def sample_geometry(plan, prog_linear, t_sec):
    """Per-frame geometry deltas.

    Returns (eased_prog, zoom_mult, dcx_px, dcy_px, roll_rad) where the offsets
    are in SOURCE-image pixels and multiply/add onto whatever the caller's own
    push/pan/drift math produced.
    """
    if look_scale() <= 0.0:
        # A true kill switch: linear progress and no deltas reproduces the
        # pre-film-look renderer exactly, so "off" is a clean A/B.
        return prog_linear, 1.0, 0.0, 0.0, 0.0

    eased = _EASINGS.get(plan['ease'], _ease_smooth)(prog_linear)

    a = plan['hh_amp']
    # Scale sway from output pixels to source pixels so it reads the same
    # regardless of how far the still has been upscaled.
    sx = plan['img_size'][0] / max(1.0, plan['out_size'][0])
    f1, f2 = plan['hh_fx']
    g1, g2 = plan['hh_fy']
    p = plan['hh_ph']
    two_pi = 6.2831853
    dcx = a * sx * (0.62 * math.sin(two_pi * f1 * t_sec + p[0]) + 0.38 * math.sin(two_pi * f2 * t_sec + p[1]))
    dcy = a * sx * (0.62 * math.sin(two_pi * g1 * t_sec + p[2]) + 0.38 * math.sin(two_pi * g2 * t_sec + p[3]))

    # Roll eases across the shot rather than oscillating — a settling camera.
    roll_rad = math.radians(plan['roll_deg']) * (eased - 0.5) * 2.0

    zoom_mult = 1.0 + plan['breath_amp'] * math.sin(two_pi * t_sec / max(0.5, plan['breath_per']) + plan['roll_ph'])

    return eased, zoom_mult, dcx, dcy, roll_rad


def clamp_view(cx, cy, vw, vh, roll_rad, iw, ih):
    """Keep the (possibly rolled) sampling rect inside the source image.

    A rolled rect needs a bigger axis-aligned footprint; if that no longer fits
    we tighten the viewport (zoom in slightly) rather than let PIL sample past
    the edge and smear black into the frame.
    """
    c = abs(math.cos(roll_rad))
    s = abs(math.sin(roll_rad))
    hw = (vw * c + vh * s) / 2.0
    hh = (vw * s + vh * c) / 2.0
    if hw > iw / 2.0 or hh > ih / 2.0:
        k = min(iw / (2.0 * hw), ih / (2.0 * hh))
        vw *= k
        vh *= k
        hw *= k
        hh *= k
    cx = max(hw, min(cx, iw - hw))
    cy = max(hh, min(cy, ih - hh))
    return cx, cy, vw, vh


def affine_matrix(cx, cy, vw, vh, roll_rad, out_w, out_h):
    """PIL AFFINE coefficients mapping OUTPUT pixel -> SOURCE pixel.

    Encodes crop + scale + roll in one bicubic sample, so adding rotation costs
    the renderer nothing over the EXTENT transform it did before.
    """
    sx = vw / float(out_w)
    sy = vh / float(out_h)
    co = math.cos(roll_rad)
    si = math.sin(roll_rad)
    a = co * sx
    b = -si * sy
    d = si * sx
    e = co * sy
    c = cx - (a * (out_w / 2.0) + b * (out_h / 2.0))
    f = cy - (d * (out_w / 2.0) + e * (out_h / 2.0))
    return (a, b, c, d, e, f)


# ── Photographic overlay (numpy, per frame) ──────────────────────────────────
class FrameOverlay:
    """Vignette + drifting dust + light leak, applied to the rendered RGB frame.

    Every mask is built once per clip; the per-frame work is one integer
    multiply-shift for the vignette (~6ms at 1080p) plus a handful of tiny
    sprite blits (~0.3ms). The light leak only touches its own bounding box.
    """

    def __init__(self, plan):
        self.enabled = look_scale() > 0.0
        if not self.enabled:
            return
        w, h = plan['out_size']
        self.w, self.h = w, h
        look = plan['look']
        rng = np.random.RandomState(plan['seed'])

        # Vignette — precomputed as uint16 gain so the per-frame op is integer.
        depth = float(look['vig'])
        if depth > 0.001:
            yy, xx = np.mgrid[0:h, 0:w]
            r = np.sqrt(((xx - w / 2.0) / (w / 2.0)) ** 2 + ((yy - h / 2.0) / (h / 2.0)) ** 2)
            fall = np.clip((r - 0.35) / 0.95, 0.0, 1.0) ** 1.7
            vig = np.clip(1.0 - depth * fall, 0.0, 1.0)
            self.vig = (vig * 256.0).astype(np.uint16)[..., None]
        else:
            self.vig = None

        # Dust motes — two parallax layers so the air has depth.
        self.dust = []
        density = float(look['dust'])
        if _dust_enabled() and density > 0.02:
            for _layer, (n_base, rad, spd, bright) in enumerate(((34, 2.0, 0.016, 26.0), (22, 4.0, 0.037, 17.0))):
                n = max(1, int(n_base * density))
                self.dust.append(
                    dict(
                        x=rng.rand(n),
                        y=rng.rand(n),
                        ph=rng.rand(n) * 6.2831853,
                        spd=spd * (0.6 + 0.8 * rng.rand(n)),
                        amp=bright * (0.6 + 0.8 * rng.rand(n)),
                        sprite=self._sprite(rad),
                    )
                )

        # Light leak — rich tier only; a soft warm bloom breathing at one corner.
        self.leak = None
        if look_tier() == 'rich':
            self.leak = self._leak(w, h, rng, plan)

    @staticmethod
    def _sprite(radius):
        k = int(max(3, round(radius * 4)) | 1)
        g = np.mgrid[0:k, 0:k].astype(np.float32) - (k - 1) / 2.0
        d2 = g[0] ** 2 + g[1] ** 2
        s = np.exp(-d2 / (2.0 * (radius * 0.55) ** 2))
        return (s / max(1e-6, s.max())).astype(np.float32)[..., None]

    @staticmethod
    def _leak(w, h, rng, plan):
        corner = plan['slot'] % 4
        cx = (0.08 if corner in (0, 3) else 0.92) * w
        cy = (0.10 if corner in (0, 1) else 0.90) * h
        yy, xx = np.mgrid[0:h, 0:w]
        sig = 0.42 * w
        m = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sig**2)))
        m[m < 0.02] = 0.0
        ys, xs = np.nonzero(m > 0.0)
        if ys.size == 0:
            return None
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        tint = np.array([1.0, 0.72, 0.42], dtype=np.float32)
        return dict(
            box=(y0, y1, x0, x1),
            mask=(m[y0:y1, x0:x1, None] * tint).astype(np.float32),
            per=11.0 + 7.0 * float(rng.rand()),
            ph=float(rng.rand() * 6.2831853),
            gain=14.0,
        )

    def apply(self, arr, t_sec, prog):
        """arr: HxWx3 uint8, modified and returned."""
        if not self.enabled:
            return arr

        if self.vig is not None:
            arr = ((arr.astype(np.uint16) * self.vig) >> 8).astype(np.uint8)

        for layer in self.dust:
            sp = layer['sprite']
            kh, kw = sp.shape[0], sp.shape[1]
            # Motes rise slowly and wander; wrap so the field never empties.
            ys = (layer['y'] - t_sec * layer['spd']) % 1.0
            xs = (layer['x'] + 0.012 * np.sin(layer['ph'] + t_sec * 0.6)) % 1.0
            flick = 0.65 + 0.35 * np.sin(layer['ph'] + t_sec * 1.7)
            for i in range(ys.size):
                y0 = int(ys[i] * (self.h - kh))
                x0 = int(xs[i] * (self.w - kw))
                reg = arr[y0 : y0 + kh, x0 : x0 + kw]
                if reg.shape[0] != kh or reg.shape[1] != kw:
                    continue
                add = sp * (layer['amp'][i] * flick[i])
                reg[:] = np.clip(reg.astype(np.float32) + add, 0, 255).astype(np.uint8)

        if self.leak is not None:
            y0, y1, x0, x1 = self.leak['box']
            amp = self.leak['gain'] * (0.5 + 0.5 * math.sin(6.2831853 * t_sec / self.leak['per'] + self.leak['ph']))
            if amp > 0.4:
                reg = arr[y0:y1, x0:x1]
                reg[:] = np.clip(reg.astype(np.float32) + self.leak['mask'] * amp, 0, 255).astype(np.uint8)
        return arr


# ── ffmpeg photographic chain ────────────────────────────────────────────────
def ffmpeg_filter(plan):
    """The -vf chain for one clip: halation, CA, exposure/temperature breath,
    micro-contrast and temporal grain. Returns '' when the look is off."""
    if look_scale() <= 0.0:
        return ''
    look = plan['look']
    parts = []

    hal = float(look['halation'])
    if hal > 0.01:
        # Bloom computed at quarter res: 16x fewer pixels through gblur, and the
        # result is a soft glow where the detail was never going to survive.
        #
        # format=gbrp is REQUIRED on both branches. blend works plane-wise, and
        # if the two inputs disagree on layout it silently blends R into B —
        # measured on a real plate that turned a warm interior magenta
        # (R 131->168, G 111->99, B 85->131) instead of blooming it.
        dark = -0.10 - 0.22 * hal
        parts.append(
            f'format=gbrp,split[fla][flb];'
            f'[flb]scale=iw/4:ih/4,gblur=sigma=6,scale=iw*4:ih*4,format=gbrp,'
            f'eq=brightness={dark:.3f}[flbl];'
            f'[fla][flbl]blend=all_mode=screen:all_opacity={min(0.45, hal):.3f}'
        )

    # NO chromatic aberration. A global rgbashift was tried and measured on real
    # plates: because it shifts uniformly rather than radially, it lays colour
    # fringes over the centre of frame too, and FLUX stills are dense with the
    # high-frequency detail (tilework, script, embroidery) that shows it worst.
    # It read as a rendering artifact, not a lens. Halation + vignette carry the
    # optical feel on their own.

    br = float(look['breath'])
    warm = float(look['warm'])
    if br > 0.001 or abs(warm) > 0.001:
        parts.append(
            'eq=eval=frame'
            f":brightness='{br:.4f}*sin(2*PI*t/6.5)'"
            f":saturation='{1.0 + 0.4 * warm:.3f}+{0.5 * br:.4f}*sin(2*PI*t/9)'"
            f":gamma_r='{1.0 + warm:.3f}+{0.6 * br:.4f}*sin(2*PI*t/13)'"
            f":gamma_b='{1.0 - warm:.3f}-{0.6 * br:.4f}*sin(2*PI*t/13)'"
        )

    # A touch of lens micro-contrast — reads as optics rather than render.
    parts.append('unsharp=3:3:0.35:3:3:0.0')

    # NO grain here. Grain applied per-clip has to survive four more encodes
    # (nvenc cq15 -> cq19 -> cq22 -> x264 crf18) and does not: measured on a
    # real clip, the FIRST nvenc pass alone cost 54% (sigma 2.35 -> 1.08) and
    # only ~30% reached the viewer. It now goes on at the colour-grade pass,
    # which is the last video encode (subtitles are delivered as a sidecar SRT
    # and copy the video without re-encoding). See final_grain_filter().

    return ','.join(parts)


def final_grain_filter(emotions=None) -> str:
    """Grain for the FINAL grade pass. OFF unless ZYG_DOC_FILMLOOK_GRAIN=1.

    Grain has to go on at the very end (any later encode destroys it), and this
    grade pass is the last one — subtitles ship as a sidecar SRT and copy the
    video. But measured through that final x264 crf18 encode, grain is
    pathologically expensive: it is high-entropy noise h264 cannot predict, so
    the bitrate tracks it almost linearly.

        alls=0   sigma 1.35    6.0 MB / 6s   (no grain)
        alls=6   sigma 1.60   10.4 MB / 6s   invisible, +73% bitrate
        alls=12  sigma 4.56   55.6 MB / 6s   visible, ~9x  -> ~6 GB per film
        alls=20  sigma 9.06  105.6 MB / 6s

    There is no setting that is both visible and deliverable, so the default is
    off and the other eight effects carry the look. Enable it only when
    delivering to a target where the bitrate is affordable.
    """
    if look_scale() <= 0.0:
        return ''
    if (os.environ.get('ZYG_DOC_FILMLOOK_GRAIN') or '0').strip() in ('0', 'false', 'no', ''):
        return ''
    vals = []
    for e in emotions or []:
        if isinstance(e, dict):  # tolerate emotion_curve-shaped entries
            e = e.get('emotion')
        if not isinstance(e, str):
            continue
        vals.append(float(_EMOTION_LOOK.get(e.lower(), _LOOK_FALLBACK)['grain']))
    base = (sum(vals) / len(vals)) if vals else float(_LOOK_FALLBACK['grain'])
    amt = max(1, int(round(base * look_scale())))
    # allf=t is the whole point: grain must resample every frame or it welds a
    # static dirt texture to the screen and looks MORE dead, not less.
    return f'noise=alls={amt}:allf=t+u'


def plan_summary(plan):
    """One-line human-readable description for the run log."""
    lk = plan['look']
    return (
        f'slot {plan["slot"]:02d} {plan["emotion"]}/{plan["ease"]} '
        f'hh={plan["hh_amp"]:.1f}px roll={plan["roll_deg"]:+.2f}° '
        f'breath={plan["breath_amp"] * 100:.2f}% vig={lk["vig"]:.2f} '
        f'grain={lk["grain"]:.0f} hal={lk["halation"]:.2f} '
        f'dust={lk["dust"]:.2f}'
    )
