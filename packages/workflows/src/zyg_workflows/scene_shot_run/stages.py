# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The seven stages — build, draft, plates, vfx, video, composite."""

from __future__ import annotations

from zyg_workflows.scene_shot_run.constants import (
    HERE,
    SCRIPTS,
    _log,
    exe,
    glob,
    json,
    os,
    resolve_character,
    shutil,
    subprocess,
    sys,
    time,
)
from zyg_workflows.scene_shot_run.planner import (
    _decode,
    blender_run,
    composite_cmd,
    contact_strip,
    engine_clip,
    ffprobe,
)

# The single binding of `tempfile`. `_hold_frame2_over_1` repeated this import
# function-locally in the pre-split module — the redefinition ruff reported as F811 — and
# now reads this one; `tempfile.mkdtemp(...)` resolves the same either way.
import tempfile

# ── the stages ───────────────────────────────────────────────────────────────


def run_build(shot_path, shot_dir):
    return blender_run([os.path.join(SCRIPTS, 'scene_build.py'), '--shot', shot_path], timeout=5400)


def run_draft(shot_path, shot_dir):
    return blender_run(
        [os.path.join(SCRIPTS, 'scene_render.py'), '--shot', shot_path, '--mode', 'draft'],
        blend=os.path.join(shot_dir, 'scene.blend'),
        timeout=3600,
    )


def run_plates(shot_path, shot_dir, log=_log):
    from zyg_workflows import scene_plates as SP

    raw = blender_run(
        [os.path.join(SCRIPTS, 'scene_plates_export.py'), '--shot', shot_path],
        blend=os.path.join(shot_dir, 'scene.blend'),
        timeout=5400,
    )
    t0 = time.time()
    ps = SP.build(shot_dir, log=log)
    return {'export': raw, 'plateset': ps, 'wall_s': round(raw['wall_s'] + time.time() - t0, 1)}


def run_vfx(shot_path, shot_dir):
    """Stage 6 — Cycles, GPU, geometry as holdout, ProRes 4444 with alpha out."""
    from zyg_workflows.geom.pose_track import gpu_lock

    with gpu_lock(timeout_s=7200, log=_log, stage='scene_shot_run vfx layer', ram_gb=8.0) as lk:
        out = blender_run(
            [os.path.join(SCRIPTS, 'scene_render.py'), '--shot', shot_path, '--mode', 'full', '--effects-only', '1'],
            blend=os.path.join(shot_dir, 'scene.blend'),
            timeout=7200,
        )
    out['gpu_lock_wait_s'] = round(float((lk or {}).get('wait_s') or 0), 1)
    return out


def _forced_4n1(n):
    return max(17, ((int(n) - 1) // 4) * 4 + 1)


def _clip_fps(clip):
    r = subprocess.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=r_frame_rate',
            '-of',
            'csv=p=0',
            clip,
        ],
        capture_output=True,
        text=True,
    )
    num, _, den = (r.stdout.strip().split(',')[0] or '24/1').partition('/')
    return float(num) / float(den or 1)


def _hold_frame2_over_1(clip, fps, log=_log):
    """Replace frame 1 of the clip with frame 2 (the kept keyframe composite is a paste,
    not a render; a one-frame hold at 24 fps is invisible and keeps the frame contract)."""
    import shutil

    tmp = tempfile.mkdtemp(prefix='hold1_')
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', clip, os.path.join(tmp, 'f_%05d.png')], check=True)
    fs = sorted(os.listdir(tmp))
    if len(fs) < 2:
        return clip
    shutil.copyfile(os.path.join(tmp, fs[1]), os.path.join(tmp, fs[0]))
    out = clip[:-4] + '_hold1.mp4'
    subprocess.run(
        [
            exe('ffmpeg'),
            '-v',
            'error',
            '-y',
            '-framerate',
            str(fps),
            '-i',
            os.path.join(tmp, 'f_%05d.png'),
            '-c:v',
            'libx264',
            '-crf',
            '14',
            '-pix_fmt',
            'yuv420p',
            out,
        ],
        check=True,
    )
    shutil.rmtree(tmp, ignore_errors=True)
    log('[keyframe] frame 1 replaced by frame 2 -> %s' % out)
    return out


def _chunk_plates(shot_dir, plates, start, n, first_frame_png, log=_log):
    """plates_chunk_<start>/: frames start..start+n-1 renumbered 1..n; frame 1 replaced by
    ``first_frame_png`` (kept, mask black) so VACE extends from it."""
    import shutil
    from PIL import Image

    out = os.path.join(shot_dir, 'plates_chunk_%03d' % start)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    with open(os.path.join(plates, 'plateset.json')) as fh:
        ps = json.load(fh)
    for key in ('ctrl', 'mask', 'pose', 'face', 'bg', 'depth'):
        pat = ps.get(key)
        if not pat:
            continue
        for k in range(n):
            src = os.path.join(plates, pat % (start + k))
            if os.path.isfile(src):
                os.symlink(os.path.realpath(src), os.path.join(out, pat % (k + 1)))
    for f in ('ctrl_00001.png', 'bg_00001.png', 'm_00001.png'):
        pth = os.path.join(out, f)
        if os.path.lexists(pth):
            os.remove(pth)
    shutil.copyfile(first_frame_png, os.path.join(out, 'ctrl_00001.png'))
    shutil.copyfile(first_frame_png, os.path.join(out, 'bg_00001.png'))
    Image.new('L', (int(ps['width']), int(ps['height'])), 0).save(os.path.join(out, 'm_00001.png'))
    ps.update({'frames': n, 'chunk_start': start, 'first_frame': first_frame_png})
    with open(os.path.join(out, 'plateset.json'), 'w') as fh:
        json.dump(ps, fh, indent=1)
    return out


def _explode(clip, dst):
    os.makedirs(dst, exist_ok=True)
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', clip, os.path.join(dst, 'f_%05d.png')], check=True)
    return sorted(os.path.join(dst, f) for f in os.listdir(dst) if f.startswith('f_'))


def _keyframe_plates(shot_dir, plates, keyframe, log=_log):
    """plates_kf/: the plate set with frame 1 replaced by the character keyframe (kept:
    mask black). Rebuilt when the keyframe or the plates are newer than it."""
    import shutil
    from PIL import Image

    out = os.path.join(shot_dir, 'plates_kf')
    kf_png = os.path.join(out, 'keyframe_still.png')
    ps_src = os.path.join(plates, 'plateset.json')
    fresh = (
        os.path.isfile(kf_png)
        and os.path.getmtime(kf_png) >= os.path.getmtime(keyframe)
        and os.path.getmtime(kf_png) >= os.path.getmtime(ps_src)
    )
    if not fresh:
        if os.path.isdir(out):
            shutil.rmtree(out)
        os.makedirs(out)
        for f in os.listdir(plates):
            if f != 'plateset.json':
                os.symlink(os.path.realpath(os.path.join(plates, f)), os.path.join(out, f))
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, 'tools', 'keyframe_still.py'), plates, keyframe, kf_png],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 or not os.path.isfile(kf_png):
            raise RuntimeError('keyframe_still.py failed: %s' % (r.stderr or r.stdout)[-800:])
        for f in ('ctrl_00001.png', 'bg_00001.png', 'm_00001.png'):
            pth = os.path.join(out, f)
            if os.path.islink(pth):
                os.remove(pth)
        shutil.copyfile(kf_png, os.path.join(out, 'ctrl_00001.png'))
        shutil.copyfile(kf_png, os.path.join(out, 'bg_00001.png'))
        with open(ps_src) as fh:
            ps = json.load(fh)
        Image.new('L', (int(ps['width']), int(ps['height'])), 0).save(os.path.join(out, 'm_00001.png'))
        ps['keyframe'] = keyframe
        with open(os.path.join(out, 'plateset.json'), 'w') as fh:
            json.dump(ps, fh, indent=1)
        log('[keyframe] frame 1 <- %s (kept, mask black) -> %s' % (keyframe, out))
    else:
        log('[keyframe] plates_kf up to date')
    return out


def run_video_vace(shot, shot_dir, log=_log):
    """The exact Movement-Studio scene_plateset path, driven with no server."""
    from zyg_workflows import movement_studio as MS
    from zyg_workflows import wan_vace_service as V
    from zyg_workflows.geom.pose_track import gpu_lock

    plates = os.path.join(shot_dir, 'plates')
    vid = shot.get('video') or {}
    actor = (shot.get('actors') or [{}])[0]
    char_id = str(actor.get('char_id') or '')
    char = resolve_character(char_id)
    if not char:
        raise RuntimeError('cannot resolve character %r' % char_id)

    # The picker's options are built once at import; a plate set exported since
    # then is on disk but not in the list, and sanitize() would drop it back to
    # 'none' and render from the still. Re-derive before sanitizing.
    MS._PARAMS['scene_plateset']['options'] = MS._plateset_options()

    W, H = (int(v) for v in (shot.get('resolution') or [832, 480]))
    # RECIPE OVERRIDES (2026-09-20, fixture_capture probes). video.keyframe = a character
    # PNG (any background): tools/keyframe_still.py cuts it out and composites it into the
    # frame-1 background at the actor matte; that frame goes in as a KEPT first frame
    # (mask black) so VACE extends from a frame that already shows the character. Without
    # it the still is the grey proxy and VACE animates the proxy. video.refs = list of
    # reference PNGs for VACE's ref seat (full body on white + canon face); video.negative,
    # video.vace_strength, video.vace_end_percent, video.lora_strength, video.geom_ctrl.
    keyframe = str(vid.get('keyframe') or '').strip()
    if keyframe:
        plates = _keyframe_plates(shot_dir, plates, keyframe, log)
    p = MS.sanitize(
        {
            'control_dir': plates,
            'mask_dir': plates,
            'resolution': '%dx%d' % (W, H),
            'num_frames': _forced_4n1(shot['frames']),
            'steps': int(vid.get('steps') or 20),
            'seed': int(vid.get('seed') or 7),
            'shift': 5.0,
            'vace_end_percent': float(vid.get('vace_end_percent') or 0.35),
            'vace_strength': float(vid.get('vace_strength') or 0.7),
            'negative_prompt': str(vid.get('negative') or ''),
            # NOT the dial default. The Movement Studio default is on,
            # and on a scene shot it is wrong: RIFE takes the 49 frames
            # the plates and the Cycles element were rendered for and
            # returns 67 interpolated ones at the shot's fps. Every
            # frame after the first then sits between two plates, so
            # the VFX element no longer lands on the frame it was
            # rendered for. A shot's frame count is a contract.
            'interpolate': False,
        }
    )
    still = os.path.join(plates, 'ctrl_00001.png') if keyframe else MS.still_for(p, os.path.join(plates, 'still.png'))
    kw = MS.render_kwargs(p, still_path=still, log_fn=log)
    kw.update(MS.control_kwargs(p, generate_fn=V.generate_vace_static_clip, log_fn=log))
    kw['vace_strength'] = float(p['vace_strength'])
    kw['vace_end_percent'] = float(p['vace_end_percent'])
    # video.render_resolution: VACE may render larger than the shot (more face pixels for
    # identity); the character composite resizes the clip back onto the plates.
    rr = str(vid.get('render_resolution') or '').strip().lower()
    if rr and 'x' in rr:
        kw['width'], kw['height'] = (int(v) for v in rr.split('x'))
        log('[vace] render resolution %s (shot %dx%d)' % (rr, W, H))
    env = MS.env_overrides(p)
    env['ZYG_VACE_MASK_SEQ'] = '1'
    env['ZYG_VACE_CTRL_BLEND'] = 'raw'
    if 'geom_ctrl' in vid:
        env['ZYG_CHAR_GEOM_CTRL'] = '1' if vid.get('geom_ctrl') else '0'
    lstr = float(vid.get('lora_strength') or p['lora_strength'])
    loras = [(char['lora'], lstr)] if char.get('lora') else []
    refs = [os.path.abspath(r) for r in (vid.get('refs') or []) if os.path.isfile(r)] or (char.get('refs') or [])[:1]
    prompt = str(vid.get('prompt') or char.get('binding') or '')
    if vid.get('use_binding') and char.get('binding'):
        prompt = str(char['binding']).strip().rstrip('.') + '. ' + prompt

    take = _next_take(shot_dir, 'vace')
    prev = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    t0 = time.time()
    chunk_n = int(vid.get('chunk_frames') or 0)
    try:
        with gpu_lock(timeout_s=7200, log=log, stage='scene_shot_run vace', ram_gb=12.0) as lk:
            if keyframe and chunk_n >= 5:
                # CHAINED EXTENSION (2026-09-20): one 97-frame pass drifted to a flat
                # cel-shaded figure while every 25-frame probe stayed photoreal; so render
                # chunk_frames at a time, each chunk extending from the previous chunk's
                # last generated frame (kept, mask black). Overlap = 1 frame.
                total = int(kw['num_frames'])
                plates_src = os.path.join(shot_dir, 'plates')
                first_png = os.path.join(plates, 'ctrl_00001.png')  # the keyframe composite
                ov = max(1, int(vid.get('chunk_overlap') or 5))
                # uniform stride: the last chunk must not end up with a 13-frame overlap and a
                # mid-chunk hand-off (take 9 drifted there). k chunks of n frames covering total
                # with equal overlaps >= ov.
                import math as _math

                if total > chunk_n:
                    k = int(_math.ceil((total - chunk_n) / float(chunk_n - ov))) + 1
                    stride = (total - chunk_n) / float(k - 1)
                    starts = [int(round(i * stride)) + 1 for i in range(k)]
                    starts[-1] = total - chunk_n + 1
                else:
                    starts = [1]
                log(
                    '[vace-chunk] plan: %d chunks of %d, starts %s (overlaps %s)'
                    % (
                        len(starts),
                        chunk_n,
                        starts,
                        [starts[i] + chunk_n - starts[i + 1] for i in range(len(starts) - 1)],
                    )
                )
                import shutil
                import numpy as _np
                from PIL import Image as _Image

                seq = os.path.join(take, 'assembled')
                if os.path.isdir(seq):
                    shutil.rmtree(seq)
                os.makedirs(seq)
                have = {}  # global frame index -> png path in seq
                prev_comp = None  # previous chunk: (start, composite_frames dir)
                ci = 0
                while True:
                    start = starts[ci]
                    n = min(chunk_n, total)
                    end = start + n - 1
                    if prev_comp is not None:
                        pstart, pcomp = prev_comp
                        first_png = os.path.join(pcomp, 'c_%05d.png' % (start - pstart + 1))
                    cdir = _chunk_plates(shot_dir, plates_src, start, n, first_png, log)
                    ckw = dict(kw)
                    ckw['num_frames'] = n
                    ckw['control_dir'] = cdir
                    ckw['mask_path'] = cdir
                    cout = os.path.join(take, 'chunk_%02d' % ci)
                    log('[vace-chunk] %d: frames %d..%d from %s' % (ci, start, end, os.path.basename(first_png)))
                    cclip = V.generate_vace_static_clip(
                        first_png, prompt, cout, loras=loras, ref_images_paths=refs, log_fn=log, **ckw
                    )
                    if not cclip:
                        raise RuntimeError('vace chunk %d failed' % ci)
                    fr = _explode(cclip, os.path.join(cout, 'frames'))
                    if len(fr) < n:
                        raise RuntimeError('vace chunk %d: %d frames, wanted %d' % (ci, len(fr), n))
                    ov_here = max(1, sum(1 for k in range(n) if (start + k) in have))
                    for k in range(n):
                        g = start + k
                        dst = os.path.join(seq, 'f_%05d.png' % g)
                        if g in have and k <= ov_here:
                            # OVERLAP CROSS-FADE (2026-09-20): a 1-frame hand-off popped 4-7x the
                            # median frame-to-frame change at every boundary (take 8). Blend the
                            # previous chunk's frames into the new chunk over `ov` frames.
                            w = k / float(ov_here)
                            if w <= 0.0:
                                continue
                            pa = _np.asarray(_Image.open(have[g]).convert('RGB'), dtype=_np.float32)
                            na = _np.asarray(_Image.open(fr[k]).convert('RGB'), dtype=_np.float32)
                            _Image.fromarray((pa * (1 - w) + na * w).astype('uint8')).save(dst)
                        elif g in have and k < 0:
                            continue
                        else:
                            shutil.copyfile(fr[k], dst)
                        have[g] = dst
                    # hand-off frames for the next chunk = this chunk composited on the plates
                    ccomp = os.path.join(cout, 'composite_frames')
                    r = subprocess.run(
                        [
                            '/usr/bin/python3',
                            os.path.join(HERE, 'tools', 'character_composite.py'),
                            cclip,
                            cdir,
                            os.path.join(cout, 'composite.mp4'),
                            '--fps',
                            str(shot.get('fps') or 24),
                            '--dilate',
                            str(int(vid.get('composite_dilate') or 40)),
                            '--feather',
                            str(int(vid.get('composite_feather') or 8)),
                            '--keep-frames',
                            ccomp,
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if r.returncode != 0 or not os.path.isfile(os.path.join(ccomp, 'c_%05d.png' % n)):
                        raise RuntimeError('chunk composite failed: %s' % (r.stderr or r.stdout)[-600:])
                    prev_comp = (start, ccomp)
                    ci += 1
                    if ci >= len(starts):
                        break
                missing = [g for g in range(1, total + 1) if g not in have]
                if missing:
                    raise RuntimeError('assembled sequence has gaps: %s' % missing[:10])
                clip = os.path.join(take, 'vace_static.mp4')
                subprocess.run(
                    [
                        exe('ffmpeg'),
                        '-v',
                        'error',
                        '-y',
                        '-framerate',
                        str(shot.get('fps') or 24),
                        '-i',
                        os.path.join(seq, 'f_%05d.png'),
                        '-c:v',
                        'libx264',
                        '-crf',
                        '14',
                        '-pix_fmt',
                        'yuv420p',
                        clip,
                    ],
                    check=True,
                )
                log('[vace-chunk] %d chunks (overlap %d) -> %d frames -> %s' % (ci, ov, total, clip))
            else:
                clip = V.generate_vace_static_clip(
                    still, prompt, take, loras=loras, ref_images_paths=refs, log_fn=log, **kw
                )
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if clip and keyframe and vid.get('hold_frame2_over_1', True):
        try:
            clip = _hold_frame2_over_1(clip, _clip_fps(clip), log)
        except Exception as exc:  # noqa: BLE001
            log('[keyframe] hold failed, keeping the raw clip: %r' % (exc,))
    if clip and vid.get('character_composite'):
        # VACE supplies the character pixels only; the set, lighting and VFX frame
        # contract stay Blender's (tools/character_composite.py, 2026-09-20).
        comp = os.path.join(take, 'character_composite.mp4')
        r = subprocess.run(
            [
                '/usr/bin/python3',
                os.path.join(HERE, 'tools', 'character_composite.py'),
                clip,
                os.path.join(shot_dir, 'plates'),
                comp,
                '--fps',
                str(shot.get('fps') or 24),
                '--dilate',
                str(int(vid.get('composite_dilate') or 40)),
                '--feather',
                str(int(vid.get('composite_feather') or 8)),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and os.path.isfile(comp):
            log('[composite] character over Blender plates -> %s %s' % (comp, r.stdout.strip()[-200:]))
            clip = comp
        else:
            log('[composite] FAILED, keeping the VACE clip: %s' % (r.stderr or r.stdout)[-600:])
    if clip and os.path.isfile(clip) and os.path.basename(clip) != 'vace_static.mp4':
        import shutil

        fin = os.path.join(take, 'vace_final.mp4')
        shutil.copyfile(clip, fin)
        clip = fin
        log('[vace] post-processed clip -> %s' % fin)
    return {
        'engine': 'vace',
        'take_dir': take,
        'clip': clip,
        'wall_s': round(time.time() - t0, 1),
        'gpu_lock_wait_s': round(float((lk or {}).get('wait_s') or 0), 1),
        'still': still,
        'prompt': prompt,
        'loras': loras,
        'ref_images_paths': refs,
        'render_kwargs': kw,
        'env': env,
    }


def run_video_animate(shot, shot_dir, log=_log):
    from zyg_workflows import wan_animate_service as WA
    from zyg_workflows.geom.pose_track import gpu_lock

    vid = shot.get('video') or {}
    actor = (shot.get('actors') or [{}])[0]
    char_id = str(actor.get('char_id') or '')
    t0 = time.time()
    with gpu_lock(timeout_s=7200, log=log, stage='scene_shot_run animate', ram_gb=12.0) as lk:
        rec = WA.animate_from_plateset(
            shot_dir,
            char_id,
            seed=int(vid.get('seed') or 7),
            prompt=str(vid.get('prompt') or ''),
            log_fn=log,
            frames=_forced_4n1(shot['frames']),
            steps=int(vid.get('steps') or 20),
        )
    return {
        'engine': 'animate',
        'take_dir': rec.get('take_dir'),
        'clip': rec.get('mp4') or rec.get('output'),
        'wall_s': round(time.time() - t0, 1),
        'gpu_lock_wait_s': round(float((lk or {}).get('wait_s') or 0), 1),
        'record': {k: rec.get(k) for k in ('n_chunks', 'reference', 'plateset')},
    }


def _next_take(shot_dir, engine):
    n = 1
    while os.path.exists(os.path.join(shot_dir, 'video', '%s_take%d' % (engine, n))):
        n += 1
    d = os.path.join(shot_dir, 'video', '%s_take%d' % (engine, n))
    os.makedirs(d, exist_ok=True)
    return d


def run_composite(shot, shot_dir, engine, log=_log):
    clip = engine_clip(shot_dir, engine)
    mov = os.path.join(shot_dir, 'full', 'effects_alpha.mov')
    if not clip:
        raise RuntimeError('no %s take to composite in %s/video' % (engine, shot_dir))
    if not os.path.isfile(mov):
        raise RuntimeError('no effects element: %s' % mov)
    W, H = (int(v) for v in (shot.get('resolution') or [832, 480]))
    fps = int(shot.get('fps') or 24)
    final = os.path.join(shot_dir, 'final.mp4')

    cmd = composite_cmd(clip, mov, final, W, H, fps)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(final):
        raise RuntimeError('composite failed: %s' % (r.stderr or '')[-600:])

    scratch = os.path.join(shot_dir, '_strip')
    eng_fr = _decode(clip, os.path.join(scratch, 'engine'))
    fin_fr = _decode(final, os.path.join(scratch, 'final'))
    n = len(fin_fr) or 1
    idx = sorted({0, max(0, n // 2 - 1), n - 1})
    pick = lambda seq, i: seq[i] if i < len(seq) else (seq[-1] if seq else '')  # noqa: E731
    draft_fr = sorted(glob.glob(os.path.join(shot_dir, 'draft', 'f_*.png')))
    ctrl_fr = sorted(glob.glob(os.path.join(shot_dir, 'plates', 'ctrl_*.png')))
    strip = contact_strip(
        [
            ('draft', [pick(draft_fr, i) for i in idx]),
            ('ctrl', [pick(ctrl_fr, i) for i in idx]),
            ('engine (%s)' % engine, [pick(eng_fr, i) for i in idx]),
            ('final', [pick(fin_fr, i) for i in idx]),
        ],
        os.path.join(shot_dir, 'final_strip.png'),
    )
    shutil.rmtree(scratch, ignore_errors=True)

    # The Video Studio placement tool reads <clip>.settings.json and takes the
    # shot's own camera track over any fov the operator dials in afterwards
    # (kanban_server.py _vfx_draft). 'clip.settings.json' is the name the rack
    # was specified with; 'final.settings.json' is the one that reader computes
    # for THIS clip, so both are written.
    for name in ('final.settings.json', 'clip.settings.json'):
        with open(os.path.join(shot_dir, name), 'w', encoding='utf-8') as fh:
            json.dump(
                {
                    'scene_shot': shot_dir,
                    'clip': final,
                    'engine': engine,
                    'prompt': (shot.get('video') or {}).get('prompt', ''),
                },
                fh,
                indent=1,
                sort_keys=True,
            )

    return {
        'final': final,
        'strip': strip,
        'cmd': cmd,
        'strip_frames': [i + 1 for i in idx],
        'wall_s': round(time.time() - t0, 1),
        'ffprobe': ffprobe(final),
    }
