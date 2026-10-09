# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""(3) graded pin / differential diffusion (original lines 1199-1449).

Split out of wan_vace_service.py; the code below is unchanged.
"""

from zyg_workflows.wan_vace_service.base import Image, _env_flag, _env_float, _log_noop, math, os

# ---------------------------------------------------------------------------
# (3) GRADED PIN / DIFFERENTIAL DIFFUSION  —  ZYG_VACE_DIFFDIFF (default OFF)
#
# WHY: today the VACE mask is BINARY and there is no middle setting. White => the control
# frame is flat neutral grey => the model has no structural guidance at all => it invents,
# which is the measured jitter (Abel's hand reversing direction 5.8x/s). Black => the anchor
# pixels are re-asserted every frame => frozen. Nothing in between.
#
# The wrapper already ships the middle setting and we have never used it. WanVideoEncode
# (nodes.py:2234-2292) takes an optional `mask` and returns {"samples": latents,
# "noise_mask": mask}. When that LATENT reaches WanVideoSampler.samples, the sampler builds
#       masks = (1 - noise_mask) > (arange(steps)/steps)      [nodes_sampler.py:1721-1724]
# and at every step does
#       latent = image_latent * mask + latent * (1 - mask)    [nodes_sampler.py:2564-2572]
# i.e. a pixel whose noise_mask value is v is PINNED TO THE STILL for the first (1-v)
# fraction of the steps and completely FREE afterwards. v=0 is the old black (frozen for the
# whole denoise), v=1 is the old white (free from step 0) — and every value in between is the
# graded pin we have been missing.
#
# Crucially that assignment sits at loop indentation 20, i.e. it runs on the FUSED
# full-length latent AFTER the context-window loop (which lives at indentation 24-28) has
# already blended its windows. It therefore cannot introduce a window seam: it is
# seam-identical by construction.
#
# DEFAULTS: a pinned box gets ZYG_VACE_DIFFDIFF_LEVEL=0.65 — held through the first 35% of
# steps, which is where flow-matching lays down low-frequency geometry (limb layout, head
# position), then released for the last ~65% so the performance is still synthesized.
# Everything else gets ZYG_VACE_DIFFDIFF_NEUTRAL=1.0, i.e. diffdiff does NOTHING there.
#
# 2026-08-01 — THE PIN IS PER-REGION NOW AND ITS DEFAULT REGION LIST IS EMPTY.
# WHY: v12 applied level 0.65 to the whole CHARACTER mask (~82% of the frame) and it cost
# the shot. Measured v11 -> v12: Cornelis' face aliveness 0.70 -> 0.33 (operator, by eye:
# "doesn't move at all"), while Abel's hand jitter — the thing the pin was supposed to fix —
# barely moved (6.91 -> 6.55 reversals/s). One SIDE EFFECT was genuinely good: the candle
# region's flow rose 0.179 -> 0.305 with churn 0.082 -> 0.164, and the operator explicitly
# asked to keep that flicker ("true to how it naturally is ... make sure it stays in there").
# A whole-mask pin cannot deliver the candle without also freezing the faces, because the
# faces live inside the same mask. So the pin is now driven by an EXPLICIT REGION LIST:
#     pin_regions = [{'box': (0.444, 0.560, 0.538, 0.878), 'level': 0.65}]   # candle only
# Boxes are FRACTIONAL 0..1 (the shot_metadata.json convention — see pin_regions_from_meta,
# which reads them so drivers never hardcode geometry) or pixel when any coordinate exceeds
# 1. Every pixel outside every listed box gets the NEUTRAL level 1.0, where the sampler's
# (1 - noise_mask) > step/steps test is false at EVERY step — a no-op by construction, so
# nothing outside a listed box can change. Each box edge is feathered OUTWARD over
# ZYG_VACE_DIFFDIFF_FEATHER=8 px (linear ramp), so there is no hard seam and the box
# interior still measures exactly `level`.
#
# THE DEFAULT REGION LIST IS EMPTY: with no regions the caller emits NO diffdiff nodes at
# all and the graph is byte-identical to ZYG_VACE_DIFFDIFF=0. Nothing changes unless a
# caller opts in. The v12 whole-mask behaviour stays reachable FOR BISECTING ONLY, via
# pin_regions=PIN_WHOLE_MASK ('mask') or ZYG_VACE_DIFFDIFF_WHOLE_MASK=1; it then honours the
# old ZYG_VACE_DIFFDIFF_KEEP (1.0) for the black/set region. Do not ship it — see above.
# ---------------------------------------------------------------------------

PIN_WHOLE_MASK = 'mask'  # pin_regions sentinel: the v12 whole-character-mask pin (bisect)
_PIN_NEUTRAL = 1.0  # level at which differential diffusion is a no-op
_PIN_FEATHER_PX = 8.0  # outward feather on each region edge


def _resolve_pin_regions(pin_regions):
    """Normalise the pin_regions argument. -> list of regions, or PIN_WHOLE_MASK.

    None (the default) means "ask the environment": ZYG_VACE_DIFFDIFF_WHOLE_MASK=1 selects
    the v12 whole-mask pin for bisecting, anything else gives an EMPTY list = diffdiff off.
    An explicit argument always wins over the environment, so a driver that passes regions
    cannot be silently overridden by a stale env var in someone's shell."""
    if pin_regions is None:
        return PIN_WHOLE_MASK if _env_flag('ZYG_VACE_DIFFDIFF_WHOLE_MASK') else []
    if isinstance(pin_regions, str):
        return PIN_WHOLE_MASK if pin_regions.strip().lower() in ('mask', 'whole', 'whole_mask') else []
    return list(pin_regions)


def pin_regions_from_meta(meta, level=0.65, keys=('candle_box',), log_fn=None):
    """shot_metadata.json-style dict -> pin_regions, so drivers never hardcode boxes.

    2026-08-01. `meta` is the parsed dict (a path to the json is also accepted, because
    drivers hold both shapes). Each key in `keys` is expected to be a `*_box` entry holding
    four FRACTIONAL coordinates [x0, y0, x1, y1] — the same convention self_improve
    .keep_boxes_from_metadata and vlm_report already read. Missing, malformed or degenerate
    keys are skipped with a log line rather than raising: an empty list simply means
    "diffdiff off", which is the safe direction.

        pin_regions_from_meta(meta)                       -> [{'box': (...), 'level': 0.65}]
        pin_regions_from_meta(meta, 0.5, ('candle_box', 'page_box'))
    """
    log = log_fn or _log_noop
    out = []
    try:
        if isinstance(meta, str):
            import json as _json

            with open(meta, 'r', encoding='utf-8') as fh:
                meta = _json.load(fh)
        if not isinstance(meta, dict):
            log('[diffdiff] pin_regions_from_meta: no metadata dict — no regions')
            return []
        for k in keys or ():
            b = meta.get(k)
            if not (isinstance(b, (list, tuple)) and len(b) == 4):
                log(f'[diffdiff] meta key {k!r} missing or not 4 numbers — skipped')
                continue
            try:
                x0, y0, x1, y1 = (float(c) for c in b)
            except (TypeError, ValueError):
                log(f'[diffdiff] meta key {k!r} not numeric — skipped')
                continue
            if not (x1 > x0 and y1 > y0):
                log(f'[diffdiff] meta key {k!r} degenerate {list(b)} — skipped')
                continue
            out.append({'box': (x0, y0, x1, y1), 'level': float(level), 'name': k})
        log(
            '[diffdiff] pin regions from metadata: '
            + (', '.join(f'{r["name"]}@{r["level"]:.2f}' for r in out) or 'none')
        )
        return out
    except Exception as e:
        log(f'[diffdiff] pin_regions_from_meta FAILED ({e}) — no regions (diffdiff off)')
        return []


def _feather_ramp(n, lo, hi, f):
    """1-D coverage over n pixels: 1.0 on [lo, hi], linear down to 0 over f px OUTSIDE each
    edge (so the listed box keeps its exact level and only the surround is graded)."""
    import numpy as _np

    x = _np.arange(n, dtype=_np.float32) + 0.5
    if f <= 0:
        return ((x >= lo) & (x <= hi)).astype(_np.float32)
    return _np.minimum(_np.clip((x - (lo - f)) / f, 0.0, 1.0), _np.clip(((hi + f) - x) / f, 0.0, 1.0))


def build_graded_pin_mask(
    mask_path, out_path, level=None, keep=None, size=None, pin_regions=None, neutral=None, feather=None, log_fn=None
):
    """Differential-diffusion noise_mask PNG (see header). -> out_path, or None = pin OFF.

    REGION MODE — the documented path (2026-08-01). pin_regions is a list of
        {'box': (x0, y0, x1, y1), 'level': 0.65, 'name': 'candle_box'}
    ('level' and 'name' optional; a bare (x0,y0,x1,y1) tuple is also accepted). Boxes are
    fractional 0..1, or pixel when any coordinate exceeds 1. Listed boxes get their level,
    EVERYTHING ELSE gets `neutral` (1.0 = diffdiff no-op), each edge feathered outward over
    `feather` px. Overlapping boxes take the stronger pin. `mask_path` is not read at all
    when `size` is given — region mode needs no mask, which is also why it works while
    mask_path is a per-frame sequence directory.
    An EMPTY list returns None: that is how the caller keeps the emitted graph
    byte-identical to diffdiff-off. That is the default.

    WHOLE-MASK MODE — v12, BISECT ONLY. pin_regions=PIN_WHOLE_MASK re-runs the old
    value = keep + (level - keep) * m, so m=1 (generate) -> level and m=0 (keep) -> keep,
    with the mask's own feather bands interpolating. This is the setting that measured
    Cornelis 0.70 -> 0.33; do not ship it.

    Returns None on ANY failure — the caller then emits no diffdiff nodes (fail-safe)."""
    log = log_fn or _log_noop
    try:
        import numpy as _np

        regions = _resolve_pin_regions(pin_regions)
        lvl = float(_env_float('ZYG_VACE_DIFFDIFF_LEVEL', 0.65) if level is None else level)
        lvl = min(1.0, max(0.0, lvl))
        neu = float(_env_float('ZYG_VACE_DIFFDIFF_NEUTRAL', _PIN_NEUTRAL) if neutral is None else neutral)
        neu = min(1.0, max(0.0, neu))
        fth = max(0.0, float(_env_float('ZYG_VACE_DIFFDIFF_FEATHER', _PIN_FEATHER_PX) if feather is None else feather))

        # ---- WHOLE-MASK (v12) — kept only so the regression can be bisected -----------
        if regions == PIN_WHOLE_MASK:
            kp = float(_env_float('ZYG_VACE_DIFFDIFF_KEEP', 1.0) if keep is None else keep)
            kp = min(1.0, max(0.0, kp))
            im = Image.open(mask_path).convert('L')
            if size and im.size != tuple(size):
                im = im.resize((int(size[0]), int(size[1])), Image.LANCZOS)
            m = _np.asarray(im, dtype=_np.float32) / 255.0
            v = kp + (lvl - kp) * m
            arr = _np.clip(_np.rint(v * 255.0), 0, 255).astype('uint8')
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
            Image.fromarray(arr, mode='L').save(out_path)
            below = float((arr < int(round(neu * 255.0))).mean())
            log(
                f'[diffdiff] WHOLE-MASK pin (v12 bisect path) → {os.path.basename(out_path)} '
                f'generate={lvl:.2f} (pinned first {100 * (1 - lvl):.0f}% of steps) '
                f'keep={kp:.2f}; {100 * below:.1f}% of the frame is below neutral — this is '
                f'the setting that measured Cornelis 0.70 -> 0.33'
            )
            return out_path

        # ---- REGION MODE (documented path) -------------------------------------------
        if size:
            W, H = int(size[0]), int(size[1])
        else:
            with Image.open(mask_path) as _im:
                W, H = _im.size
        boxes = []
        for r in regions:
            try:
                if isinstance(r, dict):
                    box = r.get('box')
                    rl = float(r.get('level', lvl))
                    nm = str(r.get('name') or 'region')
                else:
                    box, rl, nm = r, lvl, 'region'
                x0, y0, x1, y1 = (float(c) for c in box)
            except Exception:
                log(f'[diffdiff] pin region {r!r} unusable — skipped')
                continue
            if max(x0, y0, x1, y1) <= 1.0:  # fractional (shot_metadata convention)
                x0, y0, x1, y1 = x0 * W, y0 * H, x1 * W, y1 * H
            x0, x1 = max(0.0, min(float(W), x0)), max(0.0, min(float(W), x1))
            y0, y1 = max(0.0, min(float(H), y0)), max(0.0, min(float(H), y1))
            if (x1 - x0) < 1.0 or (y1 - y0) < 1.0:
                log(f'[diffdiff] pin region {nm} is empty after clamping — skipped')
                continue
            boxes.append((nm, (x0, y0, x1, y1), min(1.0, max(0.0, rl))))
        if not boxes:
            log('[diffdiff] no usable pin regions — diffdiff stays OFF (graph unchanged)')
            return None

        v = _np.full((H, W), neu, dtype=_np.float32)
        cov = _np.zeros((H, W), dtype=_np.float32)
        for _nm, (x0, y0, x1, y1), rl in boxes:
            a = _feather_ramp(H, y0, y1, fth)[:, None] * _feather_ramp(W, x0, x1, fth)[None, :]
            vr = neu + (rl - neu) * a
            v = _np.minimum(v, vr) if rl <= neu else _np.maximum(v, vr)
            cov = _np.maximum(cov, a)
        arr = _np.clip(_np.rint(v * 255.0), 0, 255).astype('uint8')
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        Image.fromarray(arr, mode='L').save(out_path)

        # measured stats, logged every time: this mask IS the experiment, and v12 proved
        # that an unverified pin footprint costs a 90-minute render
        neu8 = int(round(neu * 255.0))
        below = float((arr < neu8).mean())
        outside = arr[cov <= 0.0]
        for nm, (x0, y0, x1, y1), rl in boxes:
            sub = arr[int(y0) : int(math.ceil(y1)), int(x0) : int(math.ceil(x1))]
            log(
                f'[diffdiff] region {nm}: px ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}) '
                f'level {rl:.2f} mean_inside {float(sub.mean()):.1f}/255 '
                f'(target {rl * 255.0:.0f}) area {100.0 * sub.size / float(W * H):.2f}% of frame'
            )
        log(
            f'[diffdiff] per-region pin → {os.path.basename(out_path)} {W}x{H} '
            f'neutral={neu:.2f} feather={fth:.0f}px | below-neutral '
            f'{100 * below:.2f}% of frame | mean_outside '
            f'{(float(outside.mean()) if outside.size else float(neu8)):.1f}/255'
        )
        return out_path
    except Exception as e:
        log(f'[diffdiff] graded pin build FAILED ({e}) — staying binary')
        return None
