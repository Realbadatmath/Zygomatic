#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metric placement of a VFX library element over a rendered clip.

The operator points at the spot on the ground where the effect happens, says
how far right / up / back of that spot it actually sits IN METRES and how big
it is IN METRES, and gets a 320p composite back in seconds. The very same
record is then baked at full quality by the next render pass — draft and bake
run one placement solver and one filtergraph builder, so a draft is a preview
and not a second implementation free to disagree with the delivery.

Three pieces:

  * ``Camera`` — a pinhole over a flat ground plane (y = 0). Vertical fov, the
    image size, the camera's height above that ground and its pitch. It can go
    both ways: ``ground_point`` turns a pixel into the metre coordinates of the
    spot it lands on, ``project`` turns metre coordinates back into a pixel and
    a depth. Everything metric in this module is those two functions.

  * the element sources — the VFX library sidecar. A row with an ``element``
    is a 4K alpha webm (a real matte, ``full`` quality); a row with only a
    ``preview`` is an 854x480-class mp4 matted on near-black, good for a draft
    and nothing else. A draft ALWAYS takes the preview even when a full element
    exists: a 4K VP9-with-alpha decode is the whole cost of the composite, and
    the draft exists to be instant.

  * ``compile`` — the ffmpeg filtergraph. Full elements overlay with their
    alpha (``overlay=format=auto``) and must be decoded by ``libvpx-vp9``:
    ffmpeg's native vp9 decoder silently drops the alpha track and hands back a
    solid card (see ``vfx_volume_element.verify_alpha``). Draft previews have no
    alpha at all, so they are laid onto a black canvas at the same place and
    SCREENED over the picture, which is what a near-black matte wants.

No torch, no GPU: this is arithmetic and one ffmpeg call.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(HERE, 'data', 'asset_libraries')

# A draft is 320 px wide, always. It is a placement check, not a look check.
DRAFT_WIDTH = 320


# ────────────────────────────────────────────────────────────────── camera
class Camera:
    """A pinhole looking over the plane y = 0.

    World axes are the ones an operator describes a shot in: +X is screen
    right, +Y is up, +Z is away from the camera. The camera sits at
    ``(0, height, 0)`` and is rotated about X by ``pitch`` — positive pitch
    looks DOWN, which is the sign a tripod head uses.
    """

    def __init__(
        self, w: int, h: int, fov_deg: float = 50.0, height: float = 1.6, pitch_deg: float = 0.0, source: str = 'dials'
    ):
        self.w = max(1, int(w))
        self.h = max(1, int(h))
        self.fov = float(fov_deg)
        self.height = float(height)
        self.pitch = float(pitch_deg)
        self.source = source
        # Vertical fov: half the frame height subtends half the fov.
        self.focal_px = (self.h / 2.0) / math.tan(math.radians(self.fov) / 2.0)

    # ── helpers ────────────────────────────────────────────────────────
    def uv_from_fraction(self, fu: float, fv: float) -> tuple:
        """Frame fractions (0..1, origin top-left) → pixels."""
        return (float(fu) * self.w, float(fv) * self.h)

    def _rot(self):
        r = math.radians(self.pitch)
        return math.cos(r), math.sin(r)

    def ray(self, u: float, v: float) -> tuple:
        """World-space direction of the ray through pixel (u, v)."""
        x_c = (float(u) - self.w / 2.0) / self.focal_px
        y_c = -(float(v) - self.h / 2.0) / self.focal_px
        c, s = self._rot()
        # rotate the camera-space ray down by `pitch` about the X axis
        return (x_c, y_c * c - s, y_c * s + c)

    # ── the two directions ─────────────────────────────────────────────
    def ground_point(self, u: float, v: float):
        """(X, Z) in metres where the ray through (u, v) meets y = 0.

        ``None`` when that ray never comes down — the pixel is at or above the
        horizon, and no amount of arithmetic puts a metre distance on it."""
        dx, dy, dz = self.ray(u, v)
        if dy >= -1e-9:
            return None
        t = self.height / (-dy)
        return (t * dx, t * dz)

    def project(self, x: float, y: float, z: float) -> tuple:
        """(u, v, depth) of a world point. ``depth`` is along the camera axis
        and is negative for anything behind the lens."""
        c, s = self._rot()
        px, py, pz = float(x), float(y) - self.height, float(z)
        # inverse of the rotation in ray()
        x_c = px
        y_c = py * c + pz * s
        z_c = -py * s + pz * c
        if abs(z_c) < 1e-9:
            return (float('nan'), float('nan'), z_c)
        u = self.w / 2.0 + self.focal_px * (x_c / z_c)
        v = self.h / 2.0 - self.focal_px * (y_c / z_c)
        return (u, v, z_c)

    def place(
        self, anchor_uv, dx_right: float = 0.0, dy_up: float = 0.0, dz_back: float = 0.0, size_m: float = 3.0
    ) -> dict:
        """Where a ``size_m``-tall element sits on screen.

        ``anchor_uv`` is the pixel the operator clicked — the GROUND CONTACT
        point of the effect. The offsets move off that spot in metres; the
        returned ``u, v`` is the BOTTOM-CENTRE of the element, because that is
        the part of a dust plume or an explosion that touches the ground.
        """
        u0, v0 = float(anchor_uv[0]), float(anchor_uv[1])
        g = self.ground_point(u0, v0)
        if g is None:
            return {
                'u': 0.0,
                'v': 0.0,
                'height_px': 0.0,
                'depth': 0.0,
                'visible': False,
                'ground': None,
                'reason': 'the anchor is at or above the horizon — a pixel of sky has no distance on the ground',
            }
        gx, gz = g
        wx, wy, wz = gx + float(dx_right), float(dy_up), gz + float(dz_back)
        u, v, depth = self.project(wx, wy, wz)
        if depth <= 1e-6 or not math.isfinite(u) or not math.isfinite(v):
            return {
                'u': 0.0,
                'v': 0.0,
                'height_px': 0.0,
                'depth': round(depth, 4),
                'visible': False,
                'ground': [round(gx, 4), round(gz, 4)],
                'reason': 'the offsets put the element behind the camera',
            }
        return {
            'u': u,
            'v': v,
            'height_px': float(size_m) * self.focal_px / depth,
            'depth': depth,
            'visible': True,
            'ground': [round(gx, 4), round(gz, 4)],
            'world': [round(wx, 4), round(wy, 4), round(wz, 4)],
            'reason': '',
        }

    def as_dict(self) -> dict:
        return {
            'w': self.w,
            'h': self.h,
            'fov': round(self.fov, 3),
            'height_m': round(self.height, 4),
            'pitch_deg': round(self.pitch, 3),
            'focal_px': round(self.focal_px, 3),
            'source': self.source,
        }


def camera_from_scene_shot(shot_ref: str, w: int, h: int):
    """The studio camera of a scene shot, converted exactly.

    ``shot_ref`` is either the shot directory or the path of any file inside
    it; the camera track is ``<shot_dir>/plates_raw/camera.json``. Frame 1 is
    the one that matters — the placement is authored against the first frame
    the operator sees. ``height`` is the camera's own y, and the pitch is the
    angle its aim (t - p) makes with the ground.

    Returns ``None`` when there is no track to read, so the caller falls back
    to the dials rather than failing a render over a missing sidecar.
    """
    if not shot_ref:
        return None
    ref = str(shot_ref)
    cam_json = ''
    for cand in (ref, os.path.dirname(ref)):
        if not cand:
            continue
        if os.path.basename(cand) == 'camera.json' and os.path.isfile(cand):
            cam_json = cand
            break
        p = os.path.join(cand, 'plates_raw', 'camera.json')
        if os.path.isfile(p):
            cam_json = p
            break
    if not cam_json:
        return None
    try:
        with open(cam_json, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None

    # The track has been written as a bare list, as {"frames": [...]} and as
    # the scene_shot author's own {"keys": [...]}; take whichever is there and
    # then the record for frame 1 (or the first one, when frames are unnamed).
    rows = doc if isinstance(doc, list) else None
    if rows is None and isinstance(doc, dict):
        for key in ('frames', 'keys', 'camera'):
            if isinstance(doc.get(key), list):
                rows = doc[key]
                break
        if rows is None and doc.get('p'):
            rows = [doc]
    if not rows:
        return None
    row = next((r for r in rows if isinstance(r, dict) and int(r.get('f', 0) or 0) == 1), None)
    if row is None:
        row = next((r for r in rows if isinstance(r, dict)), None)
    if not row or not row.get('p') or not row.get('t'):
        return None

    p, t = [float(x) for x in row['p']][:3], [float(x) for x in row['t']][:3]
    d = [t[0] - p[0], t[1] - p[1], t[2] - p[2]]
    ln = math.sqrt(sum(c * c for c in d)) or 1.0
    # our pitch is positive DOWN, and a forward ray at pitch θ has dy = -sin θ
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -d[1] / ln))))
    fov = float(row.get('fov', doc.get('fov', 50.0) if isinstance(doc, dict) else 50.0))
    if str(row.get('fov_axis', '')).lower() in ('x', 'h', 'horizontal') and w:
        # declared on the long axis — convert to the vertical fov this model uses
        half = math.tan(math.radians(fov) / 2.0) * (float(h) / float(w))
        fov = math.degrees(math.atan(half)) * 2.0
    return Camera(w, h, fov, p[1], pitch, source='scene')


# ─────────────────────────────────────────────────────────── the elements
def _sidecar() -> dict:
    try:
        from zyg_workflows import vfx_ingest

        return vfx_ingest.load_sidecar() or {}
    except Exception:  # noqa: BLE001
        return {}


def _abs(cat: str, name: str) -> str:
    if not cat or not name:
        return ''
    p = os.path.join(LIBS, str(cat), str(name))
    return p if os.path.isfile(p) else ''


def sources(meta: dict = None) -> dict:
    """Every library row this rack can place, keyed by '<cat>/<file>'.

    A row is usable when it has a full element, a preview, or both. The full
    element is what a bake composites; the preview is what a draft does — a row
    with only a preview is draft-only and says so."""
    out = {}
    for key, row in (meta if meta is not None else _sidecar()).items():
        if not isinstance(row, dict):
            continue
        cat = str(row.get('cat') or str(key).partition('/')[0])
        full = _abs(cat, row.get('element') or '')
        prev = _abs(cat, row.get('preview') or '')
        if not full and not prev:
            continue
        out[str(key)] = {
            'key': str(key),
            'name': str(row.get('name') or os.path.basename(str(key))),
            'cat': cat,
            'group': str(row.get('group') or 'Other'),
            'full': full,
            'full_w': int(row.get('element_w') or 0),
            'full_h': int(row.get('element_h') or 0),
            'preview': prev,
            'preview_w': int(row.get('preview_w') or 0),
            'preview_h': int(row.get('preview_h') or 0),
            'licence': str(row.get('licence') or ''),
            'draft_only': not full,
        }
    return out


def element_options() -> list:
    """The select's options, built once at import — 'none' first."""
    opts = [{'v': 'none', 'l': 'none'}]
    for key, s in sorted(sources().items(), key=lambda kv: (kv[1]['group'], kv[1]['name'])):
        opts.append({'v': key, 'l': f'{s["name"]} — {s["group"]}{" (draft only)" if s["draft_only"] else ""}'})
    return opts


def _probe(path: str) -> dict:
    try:
        from zyg_workflows import vfx_ingest

        return vfx_ingest.probe(path) or {}
    except Exception:  # noqa: BLE001
        return {}


def element_for(key: str, draft: bool, meta: dict = None) -> dict:
    """Resolve one library row to the FILE this pass will decode.

    A draft always takes the preview: it decodes in milliseconds and it is the
    placement that is being checked, not the matte. A bake takes the 4K element
    and falls back to the preview only when the row has none, so a draft-only
    row still delivers something rather than dropping the effect silently."""
    key = str(key or '').strip()
    if not key or key == 'none':
        return {}
    src = sources(meta).get(key)
    if not src:
        raise ValueError(f'unknown VFX element {key!r}')
    if draft:
        path, w, h = src['preview'], src['preview_w'], src['preview_h']
        mode = 'preview'
        if not path:  # element-only row: matte it instead
            path, w, h, mode = src['full'], src['full_w'], src['full_h'], 'element'
    else:
        path, w, h = src['full'], src['full_w'], src['full_h']
        mode = 'element'
        if not path:
            path, w, h, mode = src['preview'], src['preview_w'], src['preview_h'], 'preview'
    if not path:
        raise ValueError(f'VFX element {key!r} has no media on disk')
    if not (w and h):
        pr = _probe(path)
        w, h = int(pr.get('w') or 0), int(pr.get('h') or 0)
    if not (w and h):
        raise ValueError(f'could not measure {os.path.basename(path)}')
    return {
        **src,
        'path': path,
        'w': int(w),
        'h': int(h),
        'mode': mode,
        'alpha': mode == 'element' and path.lower().endswith(('.webm', '.mov')),
        'aspect': float(w) / float(h),
    }


# ─────────────────────────────────────────────────────────── the placement
def _pair(txt: str, default) -> list:
    vals = [p.strip() for p in str(txt or '').replace(';', ',').split(',')]
    out = list(default)
    for i in range(min(len(out), len(vals))):
        try:
            out[i] = float(vals[i])
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('pair component %d is not numeric, keeping the default: %s', i, _exc)
    return out


def camera_for(params: dict, w: int, h: int) -> Camera:
    """The dials' camera, unless the clip came out of a scene shot — then the
    studio camera that actually rendered it wins, because guessing a fov for a
    frame whose camera is on disk would be placing the element against the
    wrong lens."""
    cam = camera_from_scene_shot(str((params or {}).get('scene_shot') or ''), w, h)
    if cam is not None:
        return cam
    p = params or {}
    return Camera(
        w,
        h,
        float(p.get('vfx_cam_fov', 50.0) or 50.0),
        float(p.get('vfx_cam_height', 1.6) or 1.6),
        float(p.get('vfx_cam_pitch', 0.0) or 0.0),
    )


def placement_for(params: dict, cam: Camera) -> dict:
    """Run the dials through ``Camera.place`` and carry the timing with it."""
    p = params or {}
    fu, fv = _pair(p.get('vfx_anchor'), [0.5, 0.85])
    dx, dy, dz = _pair(p.get('vfx_offset'), [0.0, 0.0, 0.0])
    size = float(p.get('vfx_size_m', 3.0) or 3.0)
    rec = cam.place(cam.uv_from_fraction(fu, fv), dx, dy, dz, size)
    rec.update(
        {
            'anchor': [fu, fv],
            'offset_m': [dx, dy, dz],
            'size_m': size,
            'start_s': max(0.0, float(p.get('vfx_start_s', 0.0) or 0.0)),
            'opacity': max(
                0.0, min(1.0, float(p.get('vfx_opacity', 1.0) if p.get('vfx_opacity') is not None else 1.0))
            ),
        }
    )
    return rec


# ───────────────────────────────────────────────────────────── the graph
def compile(clip_ctx: dict, placement: dict, element: dict, draft: bool) -> tuple:
    """Build (extra ffmpeg inputs, filter_complex, output label).

    ``clip_ctx`` is the FULL-RESOLUTION clip: ``{w, h, fps, dur}``. A draft
    shrinks the picture to ``DRAFT_WIDTH`` first and then scales the placement
    by the same factor, so the element lands on the same part of the same
    frame — which is the only reason a draft is worth looking at."""
    cw = int(clip_ctx.get('w') or 0)
    ch = int(clip_ctx.get('h') or 0)
    if not (cw and ch):
        raise ValueError('clip size unknown — cannot place anything on it')
    dur = float(clip_ctx.get('dur') or 0.0)
    fps = float(clip_ctx.get('fps') or 24.0) or 24.0

    scale = (DRAFT_WIDTH / float(cw)) if draft else 1.0
    bw = DRAFT_WIDTH if draft else cw
    bh = max(2, int(round(ch * scale)) // 2 * 2) if draft else ch

    eh = max(2, int(round(float(placement['height_px']) * scale)))
    ew = max(2, int(round(eh * float(element['aspect']))))
    x = int(round(float(placement['u']) * scale - ew / 2.0))
    y = int(round(float(placement['v']) * scale - eh))
    start = float(placement.get('start_s') or 0.0)
    op = float(placement.get('opacity', 1.0))

    # Looping is on the INPUT so the element repeats for as long as the clip
    # lasts; `shortest=1` on the composite is what ends the output, since a
    # -stream_loop -1 input never does.
    ins = ['-stream_loop', '-1']
    if element['path'].lower().endswith('.webm'):
        # ffmpeg's native vp9 decoder reports a VP9-with-alpha file as yuv420p
        # and hands back an opaque frame — the element would composite as a
        # solid card. libvpx-vp9 reconstructs the alpha track.
        ins += ['-c:v', 'libvpx-vp9']
    ins += ['-i', element['path']]

    parts = []
    base = '[0:v]'
    if draft:
        parts.append(f'[0:v]scale={bw}:{bh}:flags=bilinear,setsar=1[base]')
        base = '[base]'

    el = [f'scale={ew}:{eh}:flags=bilinear', 'setsar=1']
    if start > 0:
        el.append(f'setpts=PTS-STARTPTS+{start:.3f}/TB')
    else:
        el.append('setpts=PTS-STARTPTS')

    if element.get('alpha') and not draft:
        if op < 1.0:
            el.append(f'colorchannelmixer=aa={op:.3f}')
        parts.append('[1:v]' + ','.join(el) + '[el]')
        parts.append(f'{base}[el]overlay=x={x}:y={y}:format=auto:shortest=1[vout]')
    else:
        # No alpha to composite: the preview is matted on near-black, so it is
        # laid onto a black canvas of the base size (overlay clips it for free
        # when it hangs off the frame) and SCREENED over the picture. Opacity
        # scales the RGB, which is what a screen blend reads as strength.
        if op < 1.0:
            el.append(f'colorchannelmixer=rr={op:.3f}:gg={op:.3f}:bb={op:.3f}')
        parts.append('[1:v]' + ','.join(el) + '[el]')
        parts.append(f'color=c=black:s={bw}x{bh}:r={fps:.4f}:d={max(1.0, dur + 1.0):.3f}[canvas]')
        parts.append(f'[canvas][el]overlay=x={x}:y={y}[mat]')
        parts.append(f'{base}[mat]blend=all_mode=screen:shortest=1[vout]')

    return ins, ';'.join(parts), '[vout]'


# ──────────────────────────────────────────────────────────── the passes
def plan(clip_path: str, params: dict, draft: bool = True) -> dict:
    """Everything a composite needs, without running one: the clip, the camera
    (and where it came from), the solved placement and the element file."""
    info = _probe(clip_path)
    if not info.get('w'):
        raise ValueError(f'could not probe {os.path.basename(clip_path)}')
    cam = camera_for(params, info['w'], info['h'])
    pl = placement_for(params, cam)
    el = element_for((params or {}).get('vfx_element', 'none'), draft)
    return {
        'clip': info,
        'camera': cam.as_dict(),
        'placement': pl,
        'element': el,
        'cam_source': cam.source,
        'draft': bool(draft),
    }


def _composite(clip_path: str, params: dict, out_path: str, draft: bool) -> dict:
    rec = plan(clip_path, params, draft)
    if not rec['element']:
        raise ValueError('no VFX element selected')
    if not rec['placement']['visible']:
        raise ValueError(rec['placement'].get('reason') or 'element is not on screen')
    ins, fc, label = compile(rec['clip'], rec['placement'], rec['element'], draft)

    args = (
        [exe('ffmpeg'), '-y', '-v', 'error', '-i', clip_path]
        + ins
        + [
            '-filter_complex',
            fc,
            '-map',
            label,
            '-map',
            '0:a?',
            '-c:a',
            'copy',
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
        ]
    )
    if draft:
        args += ['-preset', 'ultrafast', '-crf', '30']
    else:
        args += ['-preset', 'veryfast', '-crf', '16']
    args += [out_path]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, text=True)
    secs = time.time() - t0
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f'ffmpeg failed: {(r.stderr or "")[-400:]}')
    rec.update(
        {
            'out': out_path,
            'seconds': round(secs, 3),
            'filter_complex': fc,
            'width': DRAFT_WIDTH if draft else rec['clip']['w'],
        }
    )
    return rec


def draft(clip_path: str, params: dict, out_path: str) -> float:
    """320p composite, ultrafast — seconds taken."""
    return _composite(clip_path, params, out_path, True)['seconds']


def bake(clip_path: str, params: dict, out_path: str) -> dict:
    """Full-resolution composite with the real element and its alpha."""
    return _composite(clip_path, params, out_path, False)


if __name__ == '__main__':  # the CLI lives in vfx_place_cli
    from zyg_workflows.vfx_place_cli import main as _cli_main

    raise SystemExit(_cli_main())
