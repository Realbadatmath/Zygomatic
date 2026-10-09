# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stage planner, the composite command and the subprocess helpers."""

from __future__ import annotations

from zyg_workflows.scene_shot_run.constants import (
    BLENDER,
    BLENDER_LOCK,
    STAGE_ORDER,
    _zyg_log,
    exe,
    glob,
    json,
    os,
    shutil,
    subprocess,
    time,
)

# ── the stage planner ────────────────────────────────────────────────────────
# Pure mtime arithmetic, no Blender and no GPU, so it is unit-testable: see
# tests/test_scene_shot_run.py.


def stage_io(shot_dir: str, shot: dict, engine: str) -> dict:
    """{stage: {'in': [paths], 'out': [paths], 'after': [stages]}} for one shot.

    ``in``  — files whose change invalidates the stage. A missing input is not an
              error here; the stage itself refuses.
    ``out`` — files the stage writes. ALL must exist and the OLDEST of them must
              be newer than every input, or the stage runs.
    ``after``— stages whose rerun invalidates this one even before any file has
              moved, so one pass can plan the whole cascade up front.
    """
    d = shot_dir
    drawing = str(shot.get('drawing') or '')
    blend = os.path.join(d, 'scene.blend')
    shot_json = os.path.join(d, 'shot.json')
    plates = os.path.join(d, 'plates', 'plateset.json')

    return {
        'validate': {'in': [shot_json], 'out': [os.path.join(d, 'shot.resolved.json')], 'after': []},
        'build': {'in': [shot_json] + ([drawing] if drawing else []), 'out': [blend], 'after': []},
        'draft': {'in': [blend, shot_json], 'out': [os.path.join(d, 'draft', 'draft.mp4')], 'after': ['build']},
        'plates': {
            'in': [blend, shot_json],
            'out': [os.path.join(d, 'plates_raw', 'camera.json'), plates],
            'after': ['build'],
        },
        'video': {'in': [plates], 'out': [engine_clip(d, engine) or _absent(d, engine)], 'after': ['plates']},
        'vfx': {'in': [blend, shot_json], 'out': [os.path.join(d, 'full', 'effects_alpha.mov')], 'after': ['build']},
        'composite': {
            'in': [engine_clip(d, engine) or _absent(d, engine), os.path.join(d, 'full', 'effects_alpha.mov')],
            'out': [os.path.join(d, 'final.mp4'), os.path.join(d, 'final_strip.png')],
            'after': ['video', 'vfx'],
        },
    }


def _absent(shot_dir, engine):
    """A path that is guaranteed not to exist, so 'no take yet' plans as 'run'."""
    return os.path.join(shot_dir, 'video', '%s_take0' % engine, '_no_take_yet')


def engine_clip(shot_dir: str, engine: str) -> str:
    """The newest existing take's clip for this engine, or ''.

    Take dirs are ``video/<engine>_take<N>``; the engines number them themselves
    and never overwrite a previous receipt, so 'newest' is by mtime of the clip.
    """
    name = 'vace_static.mp4' if engine == 'vace' else 'animate.mp4'
    hits = sorted(
        glob.glob(os.path.join(shot_dir, 'video', '%s_take*' % engine, name)), key=lambda p: os.path.getmtime(p)
    )
    if not hits:
        return ''
    # a post-processed clip (keyframe hold / character composite, 2026-09-20) sits next
    # to the raw engine clip as <engine>_final.mp4 and wins when present
    fin = os.path.join(os.path.dirname(hits[-1]), '%s_final.mp4' % engine)
    return fin if os.path.isfile(fin) else hits[-1]


def plan_stages(io: dict, order=STAGE_ORDER, force=(), skip=()) -> list:
    """Decide, in one pass and before anything runs, which stages will run.

    Returns [{'stage', 'run', 'reason'}] in ``order``. The cascade is explicit
    (``after``) rather than implied by mtimes that do not exist yet, so the plan
    printed at the start is the plan that executes.
    """
    force, skip = set(force), set(skip)
    plan, dirty = [], set()
    for name in order:
        spec = io.get(name) or {'in': [], 'out': [], 'after': []}
        outs = list(spec.get('out') or [])
        ins = list(spec.get('in') or [])
        upstream = sorted(set(spec.get('after') or []) & dirty)

        if name in skip:
            run, reason = False, 'skipped by flag'
        elif name in force:
            run, reason = True, 'forced'
        elif not outs:
            run, reason = True, 'no cached output'
        elif [p for p in outs if not os.path.exists(p)]:
            missing = [p for p in outs if not os.path.exists(p)][0]
            run, reason = True, 'missing output: %s' % os.path.basename(missing)
        elif upstream:
            run, reason = True, 'upstream rerun: %s' % ','.join(upstream)
        else:
            oldest_out = min(os.path.getmtime(p) for p in outs)
            newer = [p for p in ins if os.path.exists(p) and os.path.getmtime(p) > oldest_out]
            if newer:
                run, reason = True, 'input newer: %s' % os.path.basename(newer[0])
            else:
                run, reason = False, 'up to date'

        if run:
            dirty.add(name)
        plan.append({'stage': name, 'run': run, 'reason': reason})
    return plan


# ── the composite ────────────────────────────────────────────────────────────


def composite_cmd(engine_mp4: str, effects_mov: str, out_mp4: str, width: int, height: int, fps: int) -> list:
    """ffmpeg argv: the engine clip with the Cycles alpha element laid over it.

    setpts=N/(fps*TB) rather than the fps filter: the two inputs are the SAME
    frame sequence of the same shot and must stay frame-for-frame aligned, but
    they do not agree on container rate (VACE encodes at 17, Wan-Animate and the
    Blender element at the shot's 24). The fps filter would resample and change
    the frame COUNT; reassigning timestamps by frame index retimes 49 frames to
    49 frames at the shot rate, which is the only thing that keeps the element
    over the frame it was rendered for.
    """
    fc = (
        '[0:v]scale=%d:%d,setpts=N/(%d*TB),format=rgba[base];'
        '[1:v]scale=%d:%d,setpts=N/(%d*TB),format=rgba[fx];'
        '[base][fx]overlay=0:0:format=auto,format=yuv420p[v]' % (width, height, fps, width, height, fps)
    )
    return [
        exe('ffmpeg'),
        '-y',
        '-loglevel',
        'error',
        '-i',
        engine_mp4,
        '-i',
        effects_mov,
        '-filter_complex',
        fc,
        '-map',
        '[v]',
        '-r',
        str(int(fps)),
        '-c:v',
        'libx264',
        '-crf',
        '18',
        '-pix_fmt',
        'yuv420p',
        '-an',
        out_mp4,
    ]


def _decode(clip, out_dir):
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        [exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', clip, '-vsync', '0', os.path.join(out_dir, 'f_%05d.png')],
        check=True,
    )
    return sorted(glob.glob(os.path.join(out_dir, 'f_*.png')))


def contact_strip(rows, out_png, cell_w=320):
    """rows = [(label, [frame paths])]; columns are the frames. One PNG."""
    import cv2
    import numpy as np

    bands = []
    for label, frame_paths in rows:
        cells = []
        for p in frame_paths:
            im = cv2.imread(p, cv2.IMREAD_COLOR) if p and os.path.isfile(p) else None
            if im is None:
                im = np.zeros((int(cell_w * 9 / 16), cell_w, 3), np.uint8)
            h = max(1, int(round(im.shape[0] * cell_w / im.shape[1])))
            cells.append(cv2.resize(im, (cell_w, h), interpolation=cv2.INTER_AREA))
        h = max(c.shape[0] for c in cells)
        cells = [cv2.copyMakeBorder(c, 0, h - c.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)) for c in cells]
        band = np.hstack(cells)
        cv2.putText(band, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(band, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        bands.append(band)
    w = max(b.shape[1] for b in bands)
    bands = [cv2.copyMakeBorder(b, 0, 0, 0, w - b.shape[1], cv2.BORDER_CONSTANT, value=(0, 0, 0)) for b in bands]
    cv2.imwrite(out_png, np.vstack(bands))
    return out_png


# ── subprocess helpers ───────────────────────────────────────────────────────


def _last_json(text):
    for line in reversed((text or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                return json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('line is not json, skipped: %s', _exc)
                continue
    return {}


def blender_run(args, blend=None, timeout=3600):
    """`flock <blender lock> blender -b [blend] --python <script> -- <args>`.

    The flock is not optional: two headless Blenders at once SIGBUS the Bonsai
    add-on that arch_blender_build needs.
    """
    os.makedirs(os.path.dirname(BLENDER_LOCK), exist_ok=True)
    cmd = ['flock', BLENDER_LOCK, BLENDER, '-b']
    if blend:
        cmd.append(blend)
    cmd += ['--python', args[0], '--'] + list(args[1:])
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = _last_json(r.stdout)
    if r.returncode != 0 or not out.get('ok'):
        tail = (r.stdout or '')[-1500:] + '\n' + (r.stderr or '')[-1500:]
        raise RuntimeError(
            '%s failed: %s\n%s' % (os.path.basename(args[0]), out.get('error') or 'exit %d' % r.returncode, tail)
        )
    out['wall_s'] = round(time.time() - t0, 1)
    return out


def ffprobe(path):
    r = subprocess.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-count_frames',
            '-show_entries',
            'stream=nb_read_frames,width,height,r_frame_rate,codec_name',
            '-show_entries',
            'format=duration',
            '-of',
            'json',
            path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        j = json.loads(r.stdout)
        s = (j.get('streams') or [{}])[0]
        return {
            'frames': int(s.get('nb_read_frames') or 0),
            'width': int(s.get('width') or 0),
            'height': int(s.get('height') or 0),
            'fps': s.get('r_frame_rate'),
            'codec': s.get('codec_name'),
            'duration_s': round(float((j.get('format') or {}).get('duration') or 0), 6),
            'bytes': os.path.getsize(path),
        }
    except (ValueError, IndexError, OSError):
        return {'error': (r.stderr or '')[-200:]}
