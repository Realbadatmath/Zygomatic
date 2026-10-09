# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Recipe probes for a scene-shot character take (2026-09-20).

    python3 tools/recipe_probe.py SHOT_DIR --engine vace|animate --plates plates25 --frames 25
        [--still PNG] [--ref PNG] [--lora-strength 1.0] [--lora NAME] [--tag NAME]
        [--vace-strength 0.7] [--vace-end 0.35] [--blend raw|mask] [--steps 20] [--seed 7]

Same code path as scene_shot_run.run_video_vace / run_video_animate, with the identity
seats (still / reference / LoRA) and the plate set exposed. Writes <shot>/video/<engine>_probe_<tag>/.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def probe_vace(a, shot, shot_dir, log):
    from zyg_workflows import movement_studio as MS
    from zyg_workflows import scene_shot_run as SSR
    from zyg_workflows import wan_vace_service as V
    from zyg_workflows.geom.pose_track import gpu_lock

    plates = os.path.join(shot_dir, a.plates)
    vid = shot.get('video') or {}
    actor = (shot.get('actors') or [{}])[0]
    char = SSR.resolve_character(str(actor.get('char_id') or ''))
    MS._PARAMS['scene_plateset']['options'] = MS._plateset_options()
    W, H = (int(v) for v in (shot.get('resolution') or [832, 480]))
    if a.res:
        W, H = (int(v) for v in a.res.lower().split('x'))
    # The picker only knows <shot>/plates; a probe subset (plates25) goes in through the
    # typed CONTROL PATH fields, which control_kwargs honours without the picker.
    p = MS.sanitize(
        {
            'control_dir': plates,
            'mask_dir': plates,
            'resolution': '%dx%d' % (W, H),
            'num_frames': a.frames,
            'steps': a.steps,
            'seed': a.seed,
            'shift': 5.0,
            'vace_end_percent': a.vace_end,
            'vace_strength': a.vace_strength,
            'interpolate': False,
        }
    )
    still = os.path.abspath(a.still) if a.still else MS.still_for(p, char['still'])
    kw = MS.render_kwargs(p, still_path=still, log_fn=log)
    kw.update(MS.control_kwargs(p, generate_fn=V.generate_vace_static_clip, log_fn=log))
    kw['num_frames'] = a.frames
    if a.res:
        kw['width'], kw['height'] = W, H
    kw['vace_strength'] = a.vace_strength
    kw['vace_end_percent'] = a.vace_end
    env = MS.env_overrides(p)
    env['ZYG_VACE_MASK_SEQ'] = '1'
    env['ZYG_VACE_CTRL_BLEND'] = a.blend or 'raw'
    lora_name = a.lora or char.get('lora')
    loras = [(lora_name, float(a.lora_strength))] if lora_name else []
    refs = [os.path.abspath(r) for r in a.ref] if a.ref else (char.get('refs') or [])[:1]
    prompt = a.prompt or str(vid.get('prompt') or char.get('binding') or '')
    if a.use_binding and char.get('binding'):
        prompt = str(char['binding']).strip().rstrip('.') + '. ' + prompt
    if a.neg:
        kw['extra_negative'] = a.neg
    if a.set_plate:
        kw['set_plate_path'] = os.path.abspath(a.set_plate)
        kw['set_strength'] = a.set_strength
        kw['set_end_percent'] = a.set_end
    if a.geom != '':
        env['ZYG_CHAR_GEOM_CTRL'] = a.geom
    take = os.path.join(shot_dir, 'video', 'vace_probe_%s' % a.tag)
    os.makedirs(take, exist_ok=True)
    prev = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    t0 = time.time()
    try:
        with gpu_lock(timeout_s=7200, log=log, stage='recipe_probe vace', ram_gb=12.0):
            clip = V.generate_vace_static_clip(
                still, prompt, take, loras=loras, ref_images_paths=refs, log_fn=log, **kw
            )
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    rec = {
        'engine': 'vace',
        'tag': a.tag,
        'clip': clip,
        'wall_s': round(time.time() - t0, 1),
        'still': still,
        'refs': refs,
        'loras': loras,
        'prompt': prompt,
        'render_kwargs': kw,
        'env': env,
        'plates': plates,
    }
    return take, rec


def probe_animate(a, shot, shot_dir, log):
    from zyg_workflows import wan_animate_service as WA
    from zyg_workflows.geom.pose_track import gpu_lock

    vid = shot.get('video') or {}
    actor = (shot.get('actors') or [{}])[0]
    prompt = a.prompt or str(vid.get('prompt') or '')
    t0 = time.time()
    kw = {}
    if a.lora:
        kw['lora'] = a.lora
        kw['lora_strength'] = float(a.lora_strength)
    with gpu_lock(timeout_s=7200, log=log, stage='recipe_probe animate', ram_gb=12.0):
        rec = WA.animate_from_plateset(
            shot_dir,
            str(actor.get('char_id') or ''),
            seed=a.seed,
            prompt=prompt,
            log_fn=log,
            frames=a.frames,
            steps=a.steps,
            reference=(os.path.abspath(a.ref[0]) if a.ref else None),
            plateset_dir=os.path.join(shot_dir, a.plates),
            **kw,
        )
    take = rec.get('take_dir')
    rec = {
        'engine': 'animate',
        'tag': a.tag,
        'clip': rec.get('mp4') or rec.get('output'),
        'wall_s': round(time.time() - t0, 1),
        'reference': rec.get('reference'),
        'n_chunks': rec.get('n_chunks'),
        'prompt': prompt,
        'lora': kw,
        'take_dir': take,
    }
    return take, rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('shot_dir')
    ap.add_argument('--engine', choices=('vace', 'animate'), required=True)
    ap.add_argument('--plates', default='plates')
    ap.add_argument('--frames', type=int, default=25)
    ap.add_argument('--still')
    ap.add_argument('--ref', action='append', default=[])
    ap.add_argument('--neg', default='')
    ap.add_argument('--set-plate', default='')
    ap.add_argument('--set-strength', type=float, default=1.0)
    ap.add_argument('--set-end', type=float, default=0.88)
    ap.add_argument('--geom', default='')
    ap.add_argument('--use-binding', action='store_true')
    ap.add_argument('--lora')
    ap.add_argument('--lora-strength', type=float, default=1.0)
    ap.add_argument('--vace-strength', type=float, default=0.7)
    ap.add_argument('--vace-end', type=float, default=0.35)
    ap.add_argument('--blend', default='')
    ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--prompt', default='')
    ap.add_argument('--tag', default='t')
    ap.add_argument('--res', default='')
    a = ap.parse_args()
    shot_dir = os.path.abspath(a.shot_dir)
    shot = json.load(open(os.path.join(shot_dir, 'shot.json')))
    lines = []

    def log(m):
        print(m, flush=True)
        lines.append(str(m))

    take, rec = (probe_vace if a.engine == 'vace' else probe_animate)(a, shot, shot_dir, log)
    if take:
        os.makedirs(take, exist_ok=True)
        with open(os.path.join(take, 'probe.json'), 'w') as fh:
            json.dump(rec, fh, indent=1, default=str)
        with open(os.path.join(take, 'probe.log'), 'w') as fh:
            fh.write('\n'.join(lines))
    print('PROBE DONE', json.dumps({k: rec.get(k) for k in ('engine', 'tag', 'clip', 'wall_s')}))


if __name__ == '__main__':
    main()
