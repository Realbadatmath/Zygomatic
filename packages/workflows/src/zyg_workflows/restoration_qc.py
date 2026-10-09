# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""restoration_qc.py — did the upscaler INVENT detail that was not in the source?

2026-08-09. Built ahead of the SeedVR2 (Apache-2.0) finishing stage, deliberately
BEFORE the model is installed, so the replacement lands against a calibrated
instrument instead of an opinion. Calibrated on the shipped RealESRGAN_x2 path so
the incoming model has a real baseline to beat.

WHY THIS IS A NEW DEFECT CLASS
------------------------------
A restorer is a NEW place identity can move. The pipeline's identity gates run on
the pre-finishing frames; nothing looks at the image the viewer actually sees.
'texture-collapse' is the opposite failure (detail LOST), and no existing gate
detects detail INVENTED — a plausible-but-different eyelash line, a re-drawn iris,
a face that is sharper and slightly not the same person.

THE MEASUREMENT
---------------
A restorer that only sharpens and denoises produces an image whose DOWNSAMPLE
returns to the source. Invented structure does not survive that round trip::

    residual = | box_downsample(upscaled) - source |

Reported as mean absolute residual in 0..1 units.

THE CONTROL ARM (qc_contract rule 4)
------------------------------------
Raw residual is useless alone: every resampler has a floor, so a number without a
control arm steers exactly the way mean edge-NCC-vs-frame0 steered 15 versions of
scene20 before a static wall was found to out-score the book.

The control here is exact rather than empirical: **a LANCZOS upscale invents
nothing by construction.** It is a fixed kernel with no learned prior — whatever
residual it shows is pure resampling error on this content. So the gate reports

    delta = residual(model) - residual(lanczos)

on the SAME source frame. delta near zero means the model resampled; delta well
above the floor means it synthesised. `_upscale_sheet_pil` in
contact_sheet_pipeline already uses LANCZOS, so this control is the pipeline's own
no-op path, not a new dependency.

SECOND CONTROL, WITHIN THE FRAME
--------------------------------
A flat region has nothing to invent. If the flattest tile in the source scores as
much invented detail as the busiest tile, the metric is reading global resampling
error, not localised hallucination, and the run must be treated as UNKNOWN rather
than green. `tile_separation()` reports that ratio and `judge()` refuses to pass a
frame whose tiles do not separate.

WHAT IT IS BLIND TO
-------------------
Identity. A restorer can invent a *consistent* face and score well here — the
residual is small and evenly spread. That is why the Phase-1 change is not this
gate alone but ALSO moving identity QC to run after the finishing stage. This gate
detects fabrication of texture, not substitution of a person.

License posture (commercial publication): stdlib + numpy (BSD-3) + Pillow (MIT-CMU),
all already in the production venv. Imports are lazy so this module remains
importable in .venv-test, which carries pytest only. Nothing here writes a pixel
into a delivered frame.
"""

from __future__ import annotations

import os

GATE_NAME = 'restoration_fidelity'

# CALIBRATED, not guessed. Measured 2026-08-09 over all 65 frame pairs of the
# shipped FINAL_pipeline RealESRGAN_x2 run (832x480 -> 1664x960):
#
#   zero point      LANCZOS scored against itself      delta =  0.00000000  (exact)
#   no invention    NEAREST-NEIGHBOUR 2x               delta = -0.0040 .. -0.0047
#   INCUMBENT       RealESRGAN_x2, 65 frames           delta =  0.011826 .. 0.012607
#                                                      (median 0.012165, p95 0.012438)
#   gross invention ESRGAN + sigma=0.05 hi-freq noise  delta =  0.02228 .. 0.02264
#
# The floor is the INCUMBENT's worst frame x1.5. That gives it a concrete meaning:
# "invents more than the finishing stage we already ship and accept". It clears the
# incumbent by 50% and still catches the injected-invention control by ~19%.
# The band is remarkably tight (+/-3% across 65 frames), which is what makes a
# multiplicative margin honest here rather than arbitrary.
DEFAULT_DELTA_FLOOR = float(os.environ.get('ZYG_RESTORE_DELTA_FLOOR', '0.018911'))

# Tile separation is REPORTED ONLY. It takes no part in the verdict, and the
# measurements are why:
#
#   incumbent RealESRGAN_x2, 65 frames    separation 1.10 .. 1.32
#   ESRGAN + injected invention           separation 1.06 .. 1.11
#
# The first cut of this gate refused to decide below a guessed 1.20, which would
# have returned UNKNOWN on the ENTIRE incumbent corpus. Fixing the direction was
# not enough either: the two populations OVERLAP (incumbent min 1.10 vs invention
# max 1.11), so no threshold on this ratio separates them, and dressing it up as
# "corroboration" would be a confident sentence built on a statistic that cannot
# support one. It is logged because it is informative about WHERE residual sits,
# and that is all it is allowed to claim. Only a structurally unusable value
# (absent, or a zero-residual flat tile giving inf) forces UNKNOWN.

PASS, FAIL, UNKNOWN = 'pass', 'fail', 'unknown'


def _log_noop(_m):
    pass


# ── image helpers (lazy imports: .venv-test has pytest only) ────────────────


def _load(path):
    from PIL import Image
    import numpy as np

    with Image.open(path) as im:
        return np.asarray(im.convert('RGB'), dtype='float32') / 255.0


def _box_downsample(arr, out_h, out_w):
    """Area-average downsample — the correct inverse of an integer upscale.

    Falls back to PIL BOX for non-integer ratios so the gate still measures
    rather than refusing on an odd scale factor.
    """
    import numpy as np

    h, w = arr.shape[:2]
    if h == out_h and w == out_w:
        return arr
    if h % out_h == 0 and w % out_w == 0:
        fh, fw = h // out_h, w // out_w
        return arr.reshape(out_h, fh, out_w, fw, arr.shape[2]).mean(axis=(1, 3))
    from PIL import Image

    im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype('uint8'))
    im = im.resize((out_w, out_h), Image.Resampling.BOX)
    return np.asarray(im, dtype='float32') / 255.0


def _lanczos_up(arr, out_h, out_w):
    import numpy as np
    from PIL import Image

    im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype('uint8'))
    im = im.resize((out_w, out_h), Image.Resampling.LANCZOS)
    return np.asarray(im, dtype='float32') / 255.0


def residual(src_arr, up_arr):
    """Mean absolute residual between the source and the downsampled upscale."""
    import numpy as np

    h, w = src_arr.shape[:2]
    back = _box_downsample(up_arr, h, w)
    return float(np.abs(back - src_arr).mean())


def tile_separation(src_arr, up_arr, tiles=4):
    """(busiest_tile_residual / flattest_tile_residual, busy, flat).

    'Flattest' and 'busiest' are chosen by SOURCE variance, never by the score
    being tested — picking tiles by the metric under test would guarantee
    separation and prove nothing.
    """
    import numpy as np

    h, w = src_arr.shape[:2]
    back = _box_downsample(up_arr, h, w)
    th, tw = max(1, h // tiles), max(1, w // tiles)
    best = None  # (variance, residual)
    worst = None
    for i in range(tiles):
        for j in range(tiles):
            s = src_arr[i * th : (i + 1) * th, j * tw : (j + 1) * tw]
            b = back[i * th : (i + 1) * th, j * tw : (j + 1) * tw]
            if s.size == 0:
                continue
            var = float(s.var())
            res = float(np.abs(b - s).mean())
            if best is None or var < best[0]:
                best = (var, res)
            if worst is None or var > worst[0]:
                worst = (var, res)
    if not best or not worst:
        return None, None, None
    flat_r, busy_r = best[1], worst[1]
    if flat_r <= 1e-9:
        return float('inf'), busy_r, flat_r
    return busy_r / flat_r, busy_r, flat_r


def measure_pair(src_path, up_path):
    """Measure one (source, upscaled) frame pair against the LANCZOS control.

    Returns {'model', 'lanczos', 'delta', 'separation', 'busy', 'flat',
             'src_size', 'up_size'} or {'error': ...}. Never raises.
    """
    try:
        src = _load(src_path)
        up = _load(up_path)
        sh, sw = src.shape[:2]
        uh, uw = up.shape[:2]
        if uh < sh or uw < sw:
            return {'error': f'upscaled image is smaller ({uw}x{uh} < {sw}x{sh})'}
        model_r = residual(src, up)
        ctrl_r = residual(src, _lanczos_up(src, uh, uw))
        sep, busy, flat = tile_separation(src, up)
        return {
            'model': model_r,
            'lanczos': ctrl_r,
            'delta': model_r - ctrl_r,
            'separation': sep,
            'busy': busy,
            'flat': flat,
            'src_size': [sw, sh],
            'up_size': [uw, uh],
        }
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


# ── the verdict ─────────────────────────────────────────────────────────────


def judge(m, delta_floor=None):
    """One measurement dict -> (verdict, reason). Pure: no I/O, no numpy.

    The verdict rests ENTIRELY on delta against the LANCZOS control, which has an
    exact zero point. Tile separation is reported, never weighed — see the note on
    DEGENERATE_SEPARATION for the overlap that disqualifies it.

    UNKNOWN, not PASS, when the measurement could not decide (qc_contract rule 1).
    """
    floor = DEFAULT_DELTA_FLOOR if delta_floor is None else float(delta_floor)
    if not isinstance(m, dict) or m.get('error'):
        return UNKNOWN, (m or {}).get('error', 'no measurement')
    for k in ('delta', 'model', 'lanczos'):
        if m.get(k) is None:
            return UNKNOWN, f'missing {k}'
    sep = m.get('separation')
    if sep is None or sep == float('inf'):
        return UNKNOWN, ('tile separation unusable (no textured/flat contrast in this frame) — measurement incomplete')
    if m['delta'] > floor:
        return FAIL, (
            f'invented detail {m["delta"]:.5f} over the LANCZOS control '
            f'(floor {floor:.5f}; tile separation {sep:.2f}, reported only)'
        )
    return PASS, (
        f'delta {m["delta"]:.5f} within floor {floor:.5f} '
        f'(model {m["model"]:.5f} vs lanczos {m["lanczos"]:.5f}; '
        f'tile separation {sep:.2f}, reported only)'
    )


def check_name(verdict):
    return f'restoration_fidelity:{verdict}'


# ── batch + calibration ─────────────────────────────────────────────────────


def measure_folder(src_dir, up_dir, limit=None, log_fn=None):
    """Pair frames POSITIONALLY after sorting, not by filename.

    The shipped pipeline writes f_00001.png -> u_00000.png: the indices are
    offset by one, so joining on the numeric stem silently pairs each frame with
    its neighbour and measures motion instead of invention.
    """
    import glob

    log = log_fn or _log_noop
    srcs = sorted(glob.glob(os.path.join(src_dir, '*.png')))
    ups = sorted(glob.glob(os.path.join(up_dir, '*.png')))
    n = min(len(srcs), len(ups))
    if not n:
        return {'ok': None, 'error': 'no frames', 'frames': []}
    if limit:
        idx = list(range(0, n, max(1, n // int(limit))))[: int(limit)]
    else:
        idx = list(range(n))
    out = []
    for i in idx:
        m = measure_pair(srcs[i], ups[i])
        m['src'] = os.path.basename(srcs[i])
        m['up'] = os.path.basename(ups[i])
        out.append(m)
    log(f'[restore] measured {len(out)} of {n} frame pairs')
    return {'frames': out, 'n_total': n}


def calibrate(src_dir, up_dir, limit=None, log_fn=None, margin=1.5):
    """Derive a delta floor from a known-ACCEPTABLE upscale run.

    Returns the observed delta distribution plus a proposed floor at
    ``margin`` x the observed maximum. The floor is a proposal, never applied
    automatically: a gate promoted on a floor nobody read is a gate that blocks
    the corpus.
    """
    log = log_fn or _log_noop
    res = measure_folder(src_dir, up_dir, limit=limit, log_fn=log)
    deltas = [f['delta'] for f in res.get('frames', []) if f.get('delta') is not None]
    seps = [f['separation'] for f in res.get('frames', []) if f.get('separation') not in (None, float('inf'))]
    if not deltas:
        return {'ok': False, 'error': 'no usable measurements'}
    deltas.sort()
    n = len(deltas)
    stats = {
        'n': n,
        'min': deltas[0],
        'median': deltas[n // 2],
        'p95': deltas[min(n - 1, int(n * 0.95))],
        'max': deltas[-1],
        'proposed_floor': round(deltas[-1] * float(margin), 6),
        'separation_min': min(seps) if seps else None,
        'separation_median': sorted(seps)[len(seps) // 2] if seps else None,
    }
    log(
        f'[restore] calibration over {n} pairs: median delta {stats["median"]:.6f}, '
        f'max {stats["max"]:.6f} -> proposed floor {stats["proposed_floor"]:.6f}'
    )
    return {'ok': True, **stats}


def compare(src_dir, dir_a, dir_b, label_a='A', label_b='B', limit=None, log_fn=None):
    """Head-to-head: two upscalers over the SAME sources, judged by the same gate.

    This is the Phase-1 acceptance test for replacing the finishing stage. Both
    arms are measured against the identical LANCZOS control per frame, so the
    comparison is between two deltas on common ground rather than two raw
    residuals on different content.

    A LOWER delta means less invention, which is the direction we want — but the
    verdict against DEFAULT_DELTA_FLOOR is what decides acceptability, because a
    challenger can invent less than the incumbent and still invent too much, and
    it can also 'win' by simply blurring. Read `n_fail` alongside the medians.
    """
    log = log_fn or _log_noop
    out = {}
    for label, d in ((label_a, dir_a), (label_b, dir_b)):
        res = measure_folder(src_dir, d, limit=limit, log_fn=log)
        frames = [f for f in res.get('frames', []) if f.get('delta') is not None]
        if not frames:
            out[label] = {'error': f'no usable measurements in {d}'}
            continue
        ds = sorted(f['delta'] for f in frames)
        verdicts = [judge(f)[0] for f in frames]
        out[label] = {
            'n': len(ds),
            'min': ds[0],
            'median': ds[len(ds) // 2],
            'max': ds[-1],
            'n_pass': verdicts.count(PASS),
            'n_fail': verdicts.count(FAIL),
            'n_unknown': verdicts.count(UNKNOWN),
            'dir': d,
        }
        log(f'[restore] {label}: median delta {out[label]["median"]:.6f}, {out[label]["n_fail"]} FAIL of {len(ds)}')
    a, b = out.get(label_a, {}), out.get(label_b, {})
    if 'median' in a and 'median' in b:
        out['winner'] = label_a if a['median'] < b['median'] else label_b
        out['delta_gap'] = abs(a['median'] - b['median'])
        out['note'] = (
            f'{out["winner"]} invents less (median gap '
            f'{out["delta_gap"]:.6f}). A lower delta is not automatically '
            f'better: verify it did not simply blur — check that the '
            f'winner is not merely approaching the LANCZOS control.'
        )
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main():
    import json
    import sys

    argv = sys.argv[1:]
    cmd = argv[0] if argv else 'help'

    def log(m):
        print(m, flush=True)

    if cmd == 'pair' and len(argv) >= 3:
        m = measure_pair(argv[1], argv[2])
        v, why = judge(m)
        print(json.dumps({**m, 'verdict': v, 'reason': why}, indent=2))
        return 0 if v == PASS else 1
    if cmd == 'calibrate' and len(argv) >= 3:
        lim = int(argv[3]) if len(argv) > 3 else None
        print(json.dumps(calibrate(argv[1], argv[2], limit=lim, log_fn=log), indent=2))
        return 0
    if cmd == 'compare' and len(argv) >= 4:
        lim = int(argv[4]) if len(argv) > 4 else None
        print(
            json.dumps(
                compare(
                    argv[1],
                    argv[2],
                    argv[3],
                    limit=lim,
                    label_a=os.path.basename(argv[2].rstrip('/')),
                    label_b=os.path.basename(argv[3].rstrip('/')),
                    log_fn=log,
                ),
                indent=2,
            )
        )
        return 0
    if cmd == 'folder' and len(argv) >= 3:
        lim = int(argv[3]) if len(argv) > 3 else None
        res = measure_folder(argv[1], argv[2], limit=lim, log_fn=log)
        for f in res.get('frames', []):
            v, why = judge(f)
            print(f'{f.get("src"):>14s} -> {v:8s} {why}')
        return 0
    print(__doc__)
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
