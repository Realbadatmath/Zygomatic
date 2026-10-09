# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Logging shim, box arithmetic, the VRAM watcher and clip probing/decoding."""

import subprocess
import threading
import logging as _zyg_logging
from zyg_workflows.bin import exe

from zyg_workflows.vlm_report.constants import BOX_PAD, CONTEXT_STRIDE_FRAMES, NATIVE_FPS

_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_report')

# ── logging / small maths ────────────────────────────────────────────────────


def _mklog(log_fn):
    def _l(msg):
        try:
            if log_fn:
                log_fn(f'[vlm_report] {msg}')
            else:
                _zyg_log.info(f'[vlm_report] {msg}')
        except Exception as _exc:
            _zyg_log.debug('vlm_report log line not emitted: %s', _exc)

    return _l


def _c01(v):
    try:
        v = float(v)
    except Exception:
        return 0.0
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _pad_box(box, pad=BOX_PAD):
    x0, y0, x1, y1 = [float(v) for v in box]
    return (_c01(x0 - pad), _c01(y0 - pad), _c01(x1 + pad), _c01(y1 + pad))


def _box_ok(box):
    try:
        x0, y0, x1, y1 = [float(v) for v in box]
    except Exception:
        return False
    return x1 - x0 > 0.01 and y1 - y0 > 0.01


def _iou(a, b):
    if not (a and b):
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ub = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    den = ua + ub - inter
    return float(inter / den) if den > 0 else 0.0


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _union(boxes):
    boxes = [b for b in boxes if _box_ok(b)]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _median_box(boxes):
    boxes = [b for b in boxes if _box_ok(b)]
    if not boxes:
        return None
    import statistics as st

    return tuple(round(st.median([b[i] for b in boxes]), 4) for i in range(4))


def _stable_box(boxes):
    """Representative box for a set of per-frame detections.

    Consensus, then union. The median box is a robust centre; boxes that do not
    overlap it at all are outlier detections (a prop grounded onto the wrong
    object in one frame) and are dropped before the union is taken, because ONE
    stray box would otherwise stretch the region across half the frame. If the
    consensus union is still more than 3x the median, the object roams too far
    for a single box and the median is used instead — a union box over a hand
    that crosses the table is 4x the hand and dilutes every dense-flow average
    measured inside it, which is exactly how a frozen-hand defect could hide.
    """
    boxes = [b for b in boxes if _box_ok(b)]
    if not boxes:
        return None
    m = _median_box(boxes)
    if not m:
        return _union(boxes)
    consensus = [b for b in boxes if _iou(b, m) >= 0.2] or boxes
    u = _union(consensus)
    if not u:
        return m
    return u if _area(u) <= 3.0 * max(_area(m), 1e-6) else m


def _pick_candidate(cands, score_min, anchor=None, side=None, max_area=None):
    """Choose which grounded candidate represents a role in ONE frame.

    Returns (candidate, mode) where mode records HOW it was chosen so the report
    can distinguish "the detector found the pipe where the shot says it is"
    ('anchored') from "the detector found something the shot does not agree
    with" ('anchor_miss'). Returns (None, reason) when nothing survives.
    """
    pool = [c for c in (cands or []) if c.get('score', 0) >= score_min and _box_ok(c.get('box'))]
    if not pool:
        return None, 'no_candidate'
    if max_area is not None:
        shrunk = [c for c in pool if _area(c['box']) <= max_area]
        if not shrunk:
            return None, 'all_candidates_too_large'
        pool = shrunk
    if side:
        want_left = side == 'left'
        sided = [c for c in pool if ((c['box'][0] + c['box'][2]) / 2.0 < 0.5) == want_left]
        if not sided:
            return None, f'no_candidate_on_{side}'
        pool = sided
    if anchor and _box_ok(anchor):
        scored = sorted(pool, key=lambda c: -_iou(c['box'], anchor))
        if _iou(scored[0]['box'], anchor) > 0.0:
            return scored[0], 'anchored'
        acx, acy = (anchor[0] + anchor[2]) / 2.0, (anchor[1] + anchor[3]) / 2.0
        near = min(
            pool,
            key=lambda c: (
                ((c['box'][0] + c['box'][2]) / 2.0 - acx) ** 2 + ((c['box'][1] + c['box'][3]) / 2.0 - acy) ** 2
            ),
        )
        return near, 'anchor_miss'
    return pool[0], 'top-score'


# ── VRAM watcher ─────────────────────────────────────────────────────────────


class _VramWatch(object):
    """Peak GPU memory over the whole analysis, sampled out-of-process.

    nvidia-smi rather than torch: this process must never create a CUDA context
    (that alone costs hundreds of MB next to a render) merely to report a number.
    """

    def __init__(self, period=2.0):
        self.period = float(period)
        self.peak_mb = 0
        self._stop = threading.Event()
        self._t = None

    def _loop(self):
        while not self._stop.is_set():
            try:
                r = subprocess.run(
                    [exe('nvidia-smi'), '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                v = int(r.stdout.strip().splitlines()[0].strip())
                if v > self.peak_mb:
                    self.peak_mb = v
            except Exception as _exc:
                _zyg_log.debug('vram sample skipped: %s', _exc)
            self._stop.wait(self.period)

    def start(self):
        try:
            self._t = threading.Thread(target=self._loop, daemon=True)
            self._t.start()
        except Exception as _exc:
            _zyg_log.warning('VRAM sampler thread did not start, peak VRAM will read 0: %s', _exc)
        return self

    def stop(self):
        try:
            self._stop.set()
            if self._t:
                self._t.join(timeout=5)
        except Exception as _exc:
            _zyg_log.debug('vram sampler stop skipped: %s', _exc)
        return self.peak_mb


# ── clip helpers ─────────────────────────────────────────────────────────────


def _probe(clip_path):
    """(width, height, fps, duration_s) via ffprobe; safe defaults on failure."""
    w = h = 0
    fps = 0.0
    dur = 0.0
    try:
        r = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height,r_frame_rate',
                '-show_entries',
                'format=duration',
                '-of',
                'default=nw=1:nk=0',
                clip_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in (r.stdout or '').splitlines():
            k, _, v = line.partition('=')
            k, v = k.strip(), v.strip()
            if k == 'width':
                w = int(v)
            elif k == 'height':
                h = int(v)
            elif k == 'r_frame_rate' and '/' in v:
                a, b = v.split('/')
                fps = float(a) / float(b or 1)
            elif k == 'duration':
                dur = float(v)
    except Exception as _exc:
        _zyg_log.warning('clip probe failed, falling back to the default geometry and fps: %s', _exc)
    return w, h, (fps or 24.0), dur


def _default_times(meta, dur):
    """Sample times: the authored beats first, then coverage of the whole clip.

    Authored beats (draw_times, takeover_start) are where the scene is SUPPOSED
    to be doing something, so a defect there matters most; the evenly spaced
    additions exist so a defect outside a beat cannot hide.
    """
    ts = []
    for k in ('draw_times', 'beat_times'):
        for t in meta.get(k) or []:
            try:
                ts.append(float(t))
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('non-numeric %s time ignored: %s', k, _exc)
    for k in ('takeover_start',):
        try:
            if meta.get(k) is not None:
                ts.append(float(meta[k]))
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('non-numeric %s time ignored: %s', k, _exc)
    if dur > 0:
        ts += [dur * 0.06, dur * 0.45, dur * 0.97]
    out = []
    for t in sorted(ts):
        t = max(0.0, min(t, max(0.0, dur - 0.08) if dur else t))
        if all(abs(t - o) > 0.35 for o in out):
            out.append(round(t, 2))
    return out or [0.0]


def _seam_pairs(dur):
    """Context-window boundary time pairs, in SECONDS, from native geometry."""
    stride_s = CONTEXT_STRIDE_FRAMES / max(1e-6, NATIVE_FPS)
    bounds, t = [], 0.0
    while t < max(0.0, dur - 0.05):
        bounds.append(round(t, 3))
        t += stride_s
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def _decode_times(clip_path, times, log):
    """{t: RGB ndarray} decoded once and reused by every crop of every target."""
    out = {}
    try:
        from zyg_workflows import continuity_qc as CQ

        got, _fps = CQ._frames_at_times(clip_path, times)
        for t, _fi, rgb in got:
            out[round(float(t), 2)] = rgb
    except Exception as e:
        log(f'frame decode via continuity_qc failed ({e}) — falling back to cv2')
        try:
            import cv2

            cap = cv2.VideoCapture(clip_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            for t in times:
                fi = int(round(float(t) * fps))
                if total:
                    fi = max(0, min(fi, total - 1))
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, fr = cap.read()
                if ok:
                    out[round(float(t), 2)] = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            cap.release()
        except Exception as e2:
            log(f'cv2 decode also failed ({e2})')
    return out
