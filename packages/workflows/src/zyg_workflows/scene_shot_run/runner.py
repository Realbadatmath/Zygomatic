# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_shot_run.py — one shot.json in, one final.mp4 out.

This is the assembler for the Blender scene bridge: the operator's six questions
(where is the city, where is the camera, where are the VFX, where is the actor,
what does the video engine do with all that, and what does it look like cut
together) are answered by seven stages that already exist as separate tools.
This module is the only place that knows the ORDER, the caching rule and the
composite.

    "…/agents/.venv/bin/python" scene_shot_run.py \
        data/architecture/shots/<id>/shot.json \
        [--engine vace|animate] [--skip-video] [--draft-only] [--force STAGE,…]

STAGES — each idempotent, each skipped when its outputs are newer than its
inputs, each writing a line into ``<shot_dir>/receipt.json``:

  1 validate   scene_shot.load + validate + resolve_positions -> shot.resolved.json
  2 build      blender_scripts/scene_build.py                 -> scene.blend
  3 draft      blender_scripts/scene_render.py --mode draft   -> draft/draft.mp4
  4 plates     scene_plates_export.py then scene_plates.build -> plates_raw/, plates/
  5 video      VACE (movement_studio scene_plateset path) or Wan-Animate
               (wan_animate_service.animate_from_plateset)    -> video/<engine>_take<N>/
  6 vfx        scene_render.py --mode full --effects-only 1   -> full/effects_alpha.mov
  7 composite  ffmpeg: engine clip + the alpha element        -> final.mp4, final_strip.png

WHY THE VFX ARE A SEPARATE LAYER. The video engine resamples the actor region of
a Blender beauty plate; it has never seen the volumes, and asking it to keep them
would be asking it to re-invent a Cycles render. So the volumes are rendered ONCE
in Cycles with the geometry as a holdout, come out as ProRes 4444 with a real
alpha, and are laid over the engine's output. The honest cost of that choice is
recorded in the docs: the VFX are not lit by, and do not light, the engine's
picture.

Locks. Every headless Blender launch holds the flock on
``/tmp/claude-1000/arch_ext_blender.lock`` (two at once SIGBUS the Bonsai
add-on). The two stages that put a model or a path tracer on the GPU — 5 and 6 —
additionally hold ``geom.pose_track.gpu_lock``.
"""

from __future__ import annotations

from zyg_workflows.scene_shot_run.constants import (
    SCHEMA,
    STAGE_ORDER,
    _log,
    argparse,
    json,
    os,
    resolve_character,
    sys,
    time,
    traceback,
)
from zyg_workflows.scene_shot_run.planner import engine_clip, ffprobe, plan_stages, stage_io
from zyg_workflows.scene_shot_run.stages import (
    _forced_4n1,
    run_build,
    run_composite,
    run_draft,
    run_plates,
    run_vfx,
    run_video_animate,
    run_video_vace,
)

# ── receipt facts ────────────────────────────────────────────────────────────


def identity_facts(clip, char_id, log=_log):
    """Identity cosines, when the helper and a measurable face are both there."""
    try:
        from zyg_workflows import identity_bank as IB
    except Exception as exc:  # noqa: BLE001
        return {'state': 'unavailable', 'note': '%s: %s' % (type(exc).__name__, exc)}
    try:
        dur = float(ffprobe(clip).get('duration_s') or 0)
        times = [round(dur * f, 2) for f in (0.08, 0.5, 0.92)] if dur > 0.4 else [0]
        r = IB.check_clip(char_id, 'arcane', clip, [0.15, 0.05, 0.85, 0.98], times=times, log_fn=log)
        return {
            'state': 'measured' if r.get('cosine') is not None else 'unmeasurable',
            'cosine': r.get('cosine'),
            'cosine_min': r.get('cosine_min'),
            'ok': r.get('ok'),
            'backend': r.get('backend'),
            'times_s': times,
            'reason': r.get('reason') or r.get('error'),
        }
    except Exception as exc:  # noqa: BLE001
        return {'state': 'unmeasurable', 'note': '%s: %s' % (type(exc).__name__, exc)}


def licence_facts(loras, log=_log):
    """The publish verdict for the weights this shot actually used.

    Recorded, never enforced: this assembler makes a working file, and the
    publish boundary is zpub's to hold.
    """
    try:
        from zyg_workflows import licence_provenance as LP

        names = [w[0] if isinstance(w, (list, tuple)) else w for w in (loras or [])]
        d = LP.publish_decision(names, log_fn=log)
        return {
            'verdict': d['verdict'],
            'allowed': d['allowed'],
            'reason': d['reason'],
            'weights': names,
            'artifacts': [{'name': a.get('name'), 'status': a.get('status')} for a in d.get('artifacts') or []],
            'enforced': False,
        }
    except Exception as exc:  # noqa: BLE001
        return {'verdict': 'unknown', 'allowed': False, 'enforced': False, 'note': '%s: %s' % (type(exc).__name__, exc)}


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _sizes(shot_dir):
    out = {}
    for rel in (
        'final.mp4',
        'final_strip.png',
        'draft/draft.mp4',
        'scene.blend',
        'full/effects_alpha.mov',
        'shot.resolved.json',
    ):
        p = os.path.join(shot_dir, rel)
        if os.path.isfile(p):
            out[rel] = os.path.getsize(p)
    return out


# ── the run ──────────────────────────────────────────────────────────────────


def run(shot_path, engine='vace', skip_video=False, draft_only=False, force=(), log=_log):
    from zyg_workflows import scene_shot as SS

    shot_path = os.path.abspath(shot_path)
    shot = SS.load(shot_path)
    warnings = []
    SS.validate(shot, warnings)
    shot_dir = SS.shot_dir(shot)
    resolved = SS.resolve_positions(shot)

    skip = set()
    if draft_only:
        skip |= {'plates', 'video', 'vfx', 'composite'}
    elif skip_video:
        skip |= {'video', 'composite'}

    io = stage_io(shot_dir, shot, engine)
    plan = plan_stages(io, force=force, skip=skip)
    log('[run] %s | engine=%s' % (shot['id'], engine))
    for s in plan:
        log('[plan] %-10s %-4s %s' % (s['stage'], 'RUN' if s['run'] else 'skip', s['reason']))

    stages = []
    t_all = time.time()
    for step in plan:
        name = step['stage']
        rec = {'stage': name, 'ran': step['run'], 'reason': step['reason'], 'outputs': io[name]['out']}
        if not step['run']:
            stages.append(rec)
            continue
        log('\n=== stage %s (%s) ===' % (name, step['reason']))
        t0 = time.time()
        if name == 'validate':
            with open(os.path.join(shot_dir, 'shot.resolved.json'), 'w', encoding='utf-8') as fh:
                json.dump(resolved, fh, indent=1)
            rec['warnings'] = warnings
        elif name == 'build':
            rec['result'] = run_build(shot_path, shot_dir)
        elif name == 'draft':
            rec['result'] = run_draft(shot_path, shot_dir)
        elif name == 'plates':
            rec['result'] = run_plates(shot_path, shot_dir, log=log)
        elif name == 'video':
            rec['result'] = (
                run_video_vace(shot, shot_dir, log=log)
                if engine == 'vace'
                else run_video_animate(shot, shot_dir, log=log)
            )
            # the planned output was the PREVIOUS take (the engines pick the first
            # free take dir at call time); record the clip that was actually made
            rec['outputs'] = [rec['result']['clip']]
        elif name == 'vfx':
            rec['result'] = run_vfx(shot_path, shot_dir)
        elif name == 'composite':
            rec['result'] = run_composite(shot, shot_dir, engine, log=log)
        rec['wall_s'] = round(time.time() - t0, 1)
        stages.append(rec)
        log('=== stage %s done in %.1f s ===' % (name, rec['wall_s']))

    # ── receipt ──────────────────────────────────────────────────────────────
    clip = engine_clip(shot_dir, engine)
    actor = (shot.get('actors') or [{}])[0]
    loras = []
    for s in stages:
        loras = ((s.get('result') or {}).get('loras')) or loras
    if not loras:
        # the video stage was cached, so nothing in `stages` names the weights.
        # The take dir holds no receipt of its own, so ask the character the way
        # the engine call does — same char_id, same resolver, same LoRA name.
        char = resolve_character(str(actor.get('char_id') or '')) or {}
        loras = [(char['lora'], None)] if char.get('lora') else []

    final = os.path.join(shot_dir, 'final.mp4')
    receipt = {
        'schema': SCHEMA,
        'shot': shot['id'],
        'shot_dir': shot_dir,
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'engine': engine,
        'flags': {'skip_video': bool(skip_video), 'draft_only': bool(draft_only), 'force': sorted(force)},
        'wall_s': round(time.time() - t_all, 1),
        'stages': stages,
        'validate_warnings': warnings,
        'facts': {
            'fps': shot.get('fps'),
            'frames': shot.get('frames'),
            'resolution': shot.get('resolution'),
            'num_frames_4n1': _forced_4n1(shot.get('frames') or 1),
            'camera': (shot.get('camera') or {}).get('keys'),
            'camera_track': {
                k: v
                for k, v in _read_json(os.path.join(shot_dir, 'plates_raw', 'camera.json')).items()
                if k != 'frames'
            },
            'plateset': _read_json(os.path.join(shot_dir, 'plates', 'plateset.json')),
            'effects_bounds': _read_json(os.path.join(shot_dir, 'effects_bounds.json')),
        },
        'engine_clip': clip or None,
        'engine_clip_ffprobe': ffprobe(clip) if clip else None,
        'final': final if os.path.isfile(final) else None,
        'final_ffprobe': ffprobe(final) if os.path.isfile(final) else None,
        'final_strip': (
            os.path.join(shot_dir, 'final_strip.png')
            if os.path.isfile(os.path.join(shot_dir, 'final_strip.png'))
            else None
        ),
        'sizes': _sizes(shot_dir),
        'identity': (
            identity_facts(final, str(actor.get('char_id') or ''), log=log)
            if os.path.isfile(final) and actor.get('char_id')
            else {'state': 'not_run'}
        ),
        'licence': licence_facts(loras, log=log),
        'actors': [
            {'id': a.get('id'), 'char_id': a.get('char_id'), 'rendered': i == 0 and not skip_video}
            for i, a in enumerate(shot.get('actors') or [])
        ],
        'multi_actor_note': (
            "stage 5 renders actor index 0 only. The plate set carries every actor's "
            'matte and skeleton, so the loop is a change to this stage alone.'
        ),
    }
    with open(os.path.join(shot_dir, 'receipt.json'), 'w', encoding='utf-8') as fh:
        json.dump(receipt, fh, indent=1)
    log('\n[run] receipt: %s' % os.path.join(shot_dir, 'receipt.json'))
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(prog='scene_shot_run.py', description=__doc__)
    ap.add_argument('shot', help='a zyg.scene_shot/1 shot.json')
    ap.add_argument('--engine', default='vace', choices=('vace', 'animate'))
    ap.add_argument(
        '--skip-video', action='store_true', help='stages 1-4 and 6: everything but the video engine and the cut'
    )
    ap.add_argument('--draft-only', action='store_true', help="stop after the draft — the operator's check point")
    ap.add_argument('--force', default='', help='comma-separated stage names to rerun regardless of mtimes')
    a = ap.parse_args(argv)

    force = [s.strip() for s in a.force.split(',') if s.strip()]
    bad = [s for s in force if s not in STAGE_ORDER]
    if bad:
        raise SystemExit('unknown stage(s) in --force: %s (known: %s)' % (', '.join(bad), ', '.join(STAGE_ORDER)))
    r = run(a.shot, engine=a.engine, skip_video=a.skip_video, draft_only=a.draft_only, force=force)
    print(
        json.dumps(
            {'ok': True, 'shot': r['shot'], 'final': r['final'], 'receipt': os.path.join(r['shot_dir'], 'receipt.json')}
        ),
        flush=True,
    )
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}), flush=True)
        sys.exit(1)
