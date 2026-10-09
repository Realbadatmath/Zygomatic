#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vace_plate_receipt.py — does a per-frame geometry plate actually steer a VACE render?

WHY THIS EXISTS. Until 2026-09-02 no per-frame geometry sequence had ever reached a GPU
render: `generate_vace_static_clip` had no argument for an external folder of control
frames, and the only sequence it would build was `still*(1-m) + 127*m` — a CONSTANT where
generation happens. The 41-frame Abel depth track (2026-08-04, grey fraction 0.043%) had
never been consumed by any graph. S01 added `control_dir=`; this harness is the receipt
that says whether feeding it changes anything, and it is written so that "it did nothing"
is a result the file can carry.

THE ARMS. Identical seed, prompt, mask, LoRAs, size, steps. Only the control channel moves:

    neutral        control_dir=None, ZYG_CHAR_GEOM_CTRL=0   — the null: what doing nothing
                   scores. This is yesterday's production behaviour.
    correct        control_dir=<the character's own plate track>
    wrong_reversed the same track played backwards (the brief's named null)
    wrong_mirrored the same track mirrored left-right — a body whose limbs and screen
                   position disagree with the still. A time-reversal of a smoothstep lerp
                   is a weak null (same frames, different order); the mirror is the one
                   that would expose "the plate is ignored" as opposed to "the plate is
                   read but the trajectory does not matter".
    skel_on        control_dir=None, ZYG_CHAR_GEOM_CTRL=1 — the static-skeleton pair
                   against `neutral`. ZYG_CHAR_GEOM_CTRL has existed since 2026-08-05 and
                   has never produced a real character clip (the only job that reached it
                   found no character in the still).

THE GATE, stated before the numbers: the correct-plate arm must beat BOTH nulls on
identity AND on late-frame edge correlation. If it does not, the plate is not steering.
Nothing here tunes anything on a failure — that would be fitting the instrument.

FOUR-STATE LEDGER. Every measurement is found / not_found / unmeasurable / not_detectable.
`not_detectable` is not a failure of the run: a 41-frame clip has no frame 80, so the
frame-80 and frame-200 edge correlations behind the "prop fidelity ~0 by frame 80" finding
cannot be evaluated on it, and saying so is the honest answer rather than silently
substituting a different frame index.

RUN (always under the GPU lock — README rule 5):
    flock -w 7200 "${ZYG_GPU_LOCK:-$HOME/.zyg_gpu.lock}" -c \
      '"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" scripts/vace_plate_receipt.py \
        --char-id c3345deb5bde --correct-dir output/char_mesh/<id>/vace_ctrl --label "legacy phenotype (female macro)"'
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import logging as _zyg_logging

import numpy as np
from PIL import Image

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FOUND, NOT_FOUND, UNMEASURABLE, NOT_DETECTABLE = ('found', 'not_found', 'unmeasurable', 'not_detectable')


def log(m):
    print(m, flush=True)


# ── plates ───────────────────────────────────────────────────────────────────────────
def plate_frames(d):
    for pat in ('ctrl_*.png', 'c_*.png', 'frame_*.png', '*.png'):
        hits = sorted(glob.glob(os.path.join(d, pat)))
        if hits:
            return hits
    return []


def make_wrong(correct_dir, out_dir, mode):
    """A null plate track: the same geometry, deliberately wrong."""
    src = plate_frames(correct_dir)
    if not src:
        return None
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    order = list(reversed(src)) if mode == 'reversed' else src
    for i, p in enumerate(order):
        im = Image.open(p)
        if mode == 'mirrored':
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        im.save(os.path.join(out_dir, 'ctrl_%05d.png' % i))
    return out_dir


def mask_from_plates(correct_dir, size, out_png, dilate_px=18):
    """A hard binary mask from the union silhouette of the plate track.

    The generate region has to be where the character actually is, or the three arms
    differ in a region the plate never touches and the comparison measures nothing.
    Binary on purpose: preflight_mask_gates rejects a mid-grey band (soft_band > 0.06),
    and a ramp that runs off the frame is the right-edge seam."""
    import cv2

    W, H = int(size[0]), int(size[1])
    u = np.zeros((H, W), dtype=np.uint8)
    for p in plate_frames(correct_dir):
        a = np.asarray(Image.open(p).convert('L').resize((W, H), Image.LANCZOS))
        u = np.maximum(u, (a > 8).astype(np.uint8) * 255)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px * 2 + 1,) * 2)
    u = cv2.dilate(u, k)
    u = cv2.morphologyEx(u, cv2.MORPH_CLOSE, k)
    u[:3, :] = 0
    u[-3:, :] = 0
    u[:, :3] = 0
    u[:, -3:] = 0  # border must be pure black
    Image.fromarray(u, mode='L').save(out_png)
    return out_png, float((u > 127).mean())


# ── measurement ──────────────────────────────────────────────────────────────────────
def decode(clip, out_dir):
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-i', clip, '-vsync', '0', os.path.join(out_dir, 'f_%05d.png')],
        check=True,
    )
    return sorted(glob.glob(os.path.join(out_dir, 'f_*.png')))


def duration_s(clip):
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', clip],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _edges(path, mask):
    import cv2

    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return None
    if mask.shape != g.shape:
        mask = cv2.resize(mask, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
    e = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    return e[mask > 127]


def edge_corr(frames, mask_png, idx):
    """Pearson r of Sobel edge magnitude, frame `idx` against frame 0, inside the mask.

    This is the measure behind "prop fidelity ~0 by frame 80": the model re-inventing what
    the constant control hid, one context window at a time. r near 1 = the same structure
    is still there; r near 0 = it has been redrawn."""
    import cv2

    if idx >= len(frames):
        return {
            'state': NOT_DETECTABLE,
            'value': None,
            'note': f'clip has {len(frames)} frames; frame {idx} does not exist',
        }
    m = cv2.imread(mask_png, cv2.IMREAD_GRAYSCALE)
    a, b = _edges(frames[0], m), _edges(frames[idx], m)
    if a is None or b is None or a.size < 64:
        return {'state': UNMEASURABLE, 'value': None, 'note': 'frames or mask unreadable'}
    sa, sb = a.std(), b.std()
    if sa < 1e-6 or sb < 1e-6:
        return {'state': UNMEASURABLE, 'value': None, 'note': 'no edge variance inside the mask (a flat region)'}
    return {
        'state': FOUND,
        'value': round(float(np.corrcoef(a, b)[0, 1]), 4),
        'note': f'frame {idx} vs frame 0, {int((m > 127).sum())} px mask',
    }


def identity(clip, char_id, style, box_frac, times):
    from zyg_workflows import identity_bank as IB

    r = IB.check_clip(char_id, style, clip, box_frac, times=times, log_fn=log)
    if r.get('cosine') is None:
        return {'state': UNMEASURABLE, 'raw': r, 'note': r.get('reason') or r.get('error') or 'no measurable window'}
    return {
        'state': FOUND,
        'cosine': r['cosine'],
        'cosine_min': r.get('cosine_min'),
        'spread': r.get('spread'),
        'ok': r.get('ok'),
        'z': r.get('z'),
        'backend': r.get('backend'),
        'measured': r.get('measured'),
        'sampled': r.get('sampled'),
        'raw': r,
    }


def motion(clip, still, tag):
    try:
        from zyg_workflows import pipeline_debug as PD

        run = PD.DebugRun(os.path.dirname(clip), name='vace_plate_receipt')
        out = run.qc_clip(tag, clip, char_regions=[('subject', 0.15, 0.05, 0.85, 0.98)], still_path=still)
        return {'state': FOUND, 'checks': out.get('checks', [])}
    except Exception as e:
        return {'state': UNMEASURABLE, 'note': f'{type(e).__name__}: {e}'}


# ── the arms ─────────────────────────────────────────────────────────────────────────
def render_arm(V, name, still, prompt, root, kw, control_dir, char_geom, loras, refs):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    prev = os.environ.get('ZYG_CHAR_GEOM_CTRL')
    os.environ['ZYG_CHAR_GEOM_CTRL'] = '1' if char_geom else '0'
    t0 = time.time()
    try:
        clip = V.generate_vace_static_clip(
            still, prompt, d, loras=loras, ref_images_paths=refs, control_dir=control_dir, log_fn=log, **kw
        )
    finally:
        if prev is None:
            os.environ.pop('ZYG_CHAR_GEOM_CTRL', None)
        else:
            os.environ['ZYG_CHAR_GEOM_CTRL'] = prev
    return {
        'arm': name,
        'clip': clip,
        'dir': d,
        'control_dir': control_dir,
        'ZYG_CHAR_GEOM_CTRL': '1' if char_geom else '0',
        'wall_s': round(time.time() - t0, 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--char-id', required=True)
    ap.add_argument('--style', default='arcane')
    ap.add_argument('--still', default=None)
    ap.add_argument('--prompt', default=None)
    ap.add_argument('--correct-dir', required=True)
    ap.add_argument(
        '--wrong-dir', default=None, help='an explicit WRONG plate track; else reversed+mirrored are derived'
    )
    ap.add_argument('--mask', default=None, help='else derived from the plate silhouette')
    ap.add_argument('--label', default='', help='e.g. "legacy phenotype (female macro)"')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--frames', type=int, default=41)
    ap.add_argument('--steps', type=int, default=30)
    ap.add_argument('--width', type=int, default=480)
    ap.add_argument('--height', type=int, default=704)
    ap.add_argument('--lora', default=None)
    ap.add_argument('--lora-strength', type=float, default=1.0)
    ap.add_argument(
        '--vace-strength',
        type=float,
        default=None,
        help="VACE control strength; omit to keep generate_vace_static_clip's own default",
    )
    ap.add_argument('--out', default=None)
    ap.add_argument('--arms', default='neutral,correct,wrong_reversed,wrong_mirrored,skel_on')
    ap.add_argument(
        '--merge',
        action='store_true',
        help='keep arms already scored in <out>/ledger.json (a re-run of the '
        'arms an OOM or a crash took out, not a second experiment: the '
        'seed, mask and plates are the same file paths)',
    )
    a = ap.parse_args(argv)

    from zyg_workflows import wan_vace_service as V

    root = a.out or os.path.join('output', 'vace_receipts', time.strftime('%Y-%m-%d') + '_' + a.char_id)
    os.makedirs(root, exist_ok=True)
    W, H = a.width, a.height

    still = a.still
    if not still:
        cand = str(paths.ZYG_LORA_DATASETS / 'wan_chars' / a.char_id / 'images' / 'cell_24.png')
        still = cand if os.path.isfile(cand) else None
    if not still or not os.path.isfile(still):
        log('no still — pass --still')
        return 2

    lora = a.lora
    if lora is None:
        lr = str(paths.ZYG_COMFY_LORA_DIR)
        for c in (f'wan_chars/wan_char_{a.char_id}_t2v.safetensors', f'wan_chars/wan_char_{a.char_id}.safetensors'):
            if os.path.isfile(os.path.join(lr, c)):
                lora = c
                break
    loras = [(lora, a.lora_strength)] if lora else []

    refs = []
    try:
        from zyg_workflows import canon_service as CS

        vr = CS.build_vace_ref(a.char_id)
        if vr and os.path.isfile(vr):
            refs.append(vr)
    except Exception as e:
        log(f'[receipt] no canon ref ({e}) — refs stay empty for every arm alike')

    # WRONG tracks
    wrongs = {}
    if a.wrong_dir:
        wrongs['wrong_supplied'] = a.wrong_dir
    else:
        wrongs['wrong_reversed'] = make_wrong(a.correct_dir, os.path.join(root, '_plates_reversed'), 'reversed')
        wrongs['wrong_mirrored'] = make_wrong(a.correct_dir, os.path.join(root, '_plates_mirrored'), 'mirrored')

    mask = a.mask
    mask_white = None
    if not mask:
        mask, mask_white = mask_from_plates(a.correct_dir, (W, H), os.path.join(root, '_receipt_mask.png'))
        log(f'[receipt] mask from plate silhouette: white_frac {mask_white:.4f}')

    prompt = a.prompt or (
        'zygabel, a 16 year old teenage boy in 17th century attire, '
        'arcane oil painting style, painterly, he shifts his weight and '
        'turns his head slightly, breathing'
    )

    kw = dict(
        num_frames=a.frames,
        steps=a.steps,
        seed=a.seed,
        width=W,
        height=H,
        mask_path=mask,
        interpolate=False,
        context_windows=False,
    )
    if a.vace_strength is not None:
        kw['vace_strength'] = a.vace_strength

    plan = {
        'neutral': (None, False),
        'correct': (a.correct_dir, False),
        'skel_on': (None, True),
    }
    for k, v in wrongs.items():
        plan[k] = (v, False)

    want = [x.strip() for x in a.arms.split(',') if x.strip()]
    arms = []
    for name in want:
        if name not in plan:
            log(f'[receipt] unknown arm {name} — skipped')
            continue
        cdir, cgeom = plan[name]
        if name.startswith('wrong') and not cdir:
            log(f'[receipt] {name}: no plate track — skipped')
            continue
        log(f'\n=== ARM {name}  control_dir={cdir}  ZYG_CHAR_GEOM_CTRL={int(cgeom)} ===')
        arms.append(render_arm(V, name, still, prompt, root, kw, cdir, cgeom, loras, refs))

    # ── score ───────────────────────────────────────────────────────────────────────
    ledger = {
        'schema': 'vace_plate_receipt/1',
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'char_id': a.char_id,
        'style': a.style,
        'label': a.label,
        'still': still,
        'prompt': prompt,
        'seed': a.seed,
        'frames': a.frames,
        'steps': a.steps,
        'size': [W, H],
        'mask': mask,
        'mask_white_frac': mask_white,
        'vace_strength': a.vace_strength,
        'loras': loras,
        'refs': refs,
        'correct_dir': a.correct_dir,
        'wrong_dirs': wrongs,
        'arms': {},
    }

    try:
        from zyg_workflows import identity_bank as IB

        ledger['identity_bank'] = {
            'file': os.path.abspath(IB.__file__),
            'mtime': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(os.path.getmtime(IB.__file__))),
            'sha256': __import__('hashlib').sha256(open(IB.__file__, 'rb').read()).hexdigest(),
            'SPREAD_ALARM': IB.SPREAD_ALARM,
            'Z_FLOOR': IB.Z_FLOOR,
            'default_backend': IB.DEFAULT_BACKEND,
            'note': 'check_clip as it stood on disk when this ran (S03 is changing it)',
        }
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

    # MERGE. The CLIPS of an earlier pass are reused; its SCORES are not. identity_bank.py
    # is owned by S03 and is being edited while this runs (its mtime moved between the two
    # passes), so keeping the old numbers would put two versions of check_clip in one
    # table — the exact "flattered the incumbent" failure runtime_stamp exists to prevent.
    # Every arm in the final ledger is scored below, in this process, by one version.
    if a.merge and os.path.isfile(os.path.join(root, 'ledger.json')):
        try:
            old = json.load(open(os.path.join(root, 'ledger.json')))
            have = {x['arm'] for x in arms}
            kept = []
            for k, v in (old.get('arms') or {}).items():
                if k in have or not v.get('clip') or not os.path.isfile(str(v['clip'])):
                    continue
                arms.append(
                    {
                        'arm': k,
                        'clip': v['clip'],
                        'dir': v['dir'],
                        'control_dir': v.get('control_dir'),
                        'ZYG_CHAR_GEOM_CTRL': v.get('ZYG_CHAR_GEOM_CTRL'),
                        'wall_s': v.get('wall_s'),
                        'rendered_in': old.get('date'),
                    }
                )
                kept.append(k)
            ledger['merged_from'] = {
                'prior_date': old.get('date'),
                'clips_reused': sorted(kept),
                'why': 'the first pass lost ComfyUI to a host-RAM OOM part-way through',
                'scores': 'RE-MEASURED in this pass; no number is carried over',
            }
            log(f'[receipt] reusing {len(kept)} clip(s) from the earlier pass and re-scoring them here: {sorted(kept)}')
        except Exception as e:
            log(f'[receipt] merge failed ({e}) — this pass stands alone')

    for arm in arms:
        rec = dict(arm)
        clip = arm['clip']
        if not clip or not os.path.isfile(clip):
            rec['result'] = {'state': NOT_FOUND, 'note': 'the render produced no clip'}
            ledger['arms'][arm['arm']] = rec
            continue
        fr = decode(clip, os.path.join(arm['dir'], '_frames'))
        dur = duration_s(clip)
        rec['n_frames_decoded'] = len(fr)
        rec['duration_s'] = round(dur, 3)
        # check_clip's default times [2,6,9,13,16]s do not fit a 2.4s clip. Sample the
        # duration instead, and SAY that this is not the default sampling.
        times = [round(dur * f, 2) for f in (0.08, 0.28, 0.5, 0.72, 0.92)] if dur > 0.4 else [0]
        rec['identity_times_s'] = times
        rec['identity_times_note'] = (
            f'NOT check_clip defaults [2,6,9,13,16]s — a {a.frames}-frame clip is {dur:.2f}s long'
        )
        rec['identity'] = identity(clip, a.char_id, a.style, [0.15, 0.05, 0.85, 0.98], times)
        rec['edge_corr'] = {
            'frame_80': edge_corr(fr, mask, 80),
            'frame_200': edge_corr(fr, mask, 200),
            'frame_mid': edge_corr(fr, mask, max(1, len(fr) // 2)),
            'frame_last': edge_corr(fr, mask, max(1, len(fr) - 1)),
        }
        rec['motion'] = motion(clip, still, arm['arm'])
        stamp = os.path.join(arm['dir'], '_vace_control_stamp.json')
        if os.path.isfile(stamp):
            rec['control_stamp'] = json.load(open(stamp))
        ledger['arms'][arm['arm']] = rec

    # ── the gate ────────────────────────────────────────────────────────────────────
    def val(n, path):
        r = ledger['arms'].get(n, {})
        for k in path:
            r = (r or {}).get(k) if isinstance(r, dict) else None
        return r

    nulls = [n for n in ledger['arms'] if n == 'neutral' or n.startswith('wrong')]
    gate = {'nulls': nulls, 'checks': []}
    c_id = val('correct', ['identity', 'cosine'])
    c_ed = val('correct', ['edge_corr', 'frame_last', 'value'])
    for n in nulls:
        n_id = val(n, ['identity', 'cosine'])
        n_ed = val(n, ['edge_corr', 'frame_last', 'value'])
        gate['checks'].append(
            {
                'check': f'identity: correct > {n}',
                'state': FOUND if (c_id is not None and n_id is not None) else UNMEASURABLE,
                'correct': c_id,
                'null': n_id,
                'ok': bool(c_id is not None and n_id is not None and c_id > n_id),
            }
        )
        gate['checks'].append(
            {
                'check': f'edge_corr(last frame): correct > {n}',
                'state': FOUND if (c_ed is not None and n_ed is not None) else UNMEASURABLE,
                'correct': c_ed,
                'null': n_ed,
                'ok': bool(c_ed is not None and n_ed is not None and c_ed > n_ed),
            }
        )
    meas = [c for c in gate['checks'] if c['state'] == FOUND]
    gate['verdict'] = (
        'UNMEASURABLE — no arm pair could be compared'
        if not meas
        else 'PASS — the plate steers'
        if all(c['ok'] for c in meas)
        else 'FAIL — the plate is NOT steering. Do not tune; report it.'
    )
    gate['note'] = (
        'frame-80 / frame-200 edge correlation, the frames the "prop fidelity '
        '~0 by frame 80" finding is about, are not_detectable on a '
        f'{a.frames}-frame clip. The last-frame correlation is the analogue '
        'that this clip length can carry, and it is not the same measurement.'
    )
    ledger['gate'] = gate

    # skeleton pair (task 3): skel_on against neutral, same seed, no control_dir
    if 'skel_on' in ledger['arms'] and 'neutral' in ledger['arms']:
        ledger['static_skeleton_pair'] = {
            'off': {
                'identity': val('neutral', ['identity', 'cosine']),
                'edge_last': val('neutral', ['edge_corr', 'frame_last', 'value']),
            },
            'on': {
                'identity': val('skel_on', ['identity', 'cosine']),
                'edge_last': val('skel_on', ['edge_corr', 'frame_last', 'value']),
            },
            'note': 'ZYG_CHAR_GEOM_CTRL painted the still-detected skeleton into the '
            'control; first real character clip it has ever produced.',
        }

    lp = os.path.join(root, 'ledger.json')
    with open(lp, 'w') as fh:
        json.dump(ledger, fh, indent=1)
    write_md(ledger, os.path.join(root, 'RECEIPT.md'))
    log(f'\n[receipt] {lp}\n[receipt] {os.path.join(root, "RECEIPT.md")}')
    log('[receipt] GATE: ' + gate['verdict'])
    return 0


def write_md(L, path):
    def g(a, *ks):
        r = L['arms'].get(a, {})
        for k in ks:
            r = (r or {}).get(k) if isinstance(r, dict) else None
        return r

    o = []
    o.append('# VACE plate receipt — %s%s\n' % (L['char_id'], (' — ' + L['label']) if L['label'] else ''))
    o.append(
        '%s · seed %s · %s frames · %s steps · %sx%s · mask white_frac %s\n'
        % (L['date'], L['seed'], L['frames'], L['steps'], L['size'][0], L['size'][1], L.get('mask_white_frac'))
    )
    o.append(
        'Still: `%s`\nPrompt: %s\nLoRAs: %s\nCorrect plates: `%s`\n'
        % (L['still'], L['prompt'], L['loras'], L['correct_dir'])
    )
    o.append('\n## Arms (identical seed, prompt, mask, LoRAs, size, steps)\n')
    o.append(
        '| arm | control_dir | CHAR_GEOM | clip | identity cos | id state | edge r last | edge r frame80 | wall s |'
    )
    o.append('|---|---|---|---|---|---|---|---|---|')
    for n, r in L['arms'].items():
        o.append(
            '| %s | %s | %s | %s | %s | %s | %s | %s | %s |'
            % (
                n,
                os.path.basename(str(r.get('control_dir')) or '—'),
                r.get('ZYG_CHAR_GEOM_CTRL'),
                os.path.basename(str(r.get('clip'))) if r.get('clip') else 'NONE',
                g(n, 'identity', 'cosine'),
                g(n, 'identity', 'state'),
                g(n, 'edge_corr', 'frame_last', 'value'),
                g(n, 'edge_corr', 'frame_80', 'state'),
                r.get('wall_s'),
            )
        )
    o.append('\n## Gate\n\n**%s**\n' % L['gate']['verdict'])
    o.append('| check | correct | null | ok | state |')
    o.append('|---|---|---|---|---|')
    for c in L['gate']['checks']:
        o.append('| %s | %s | %s | %s | %s |' % (c['check'], c['correct'], c['null'], c['ok'], c['state']))
    o.append('\n%s\n' % L['gate']['note'])
    if 'static_skeleton_pair' in L:
        p = L['static_skeleton_pair']
        o.append('\n## Static skeleton (ZYG_CHAR_GEOM_CTRL) — task 3\n')
        o.append('| | identity cos | edge r last |')
        o.append('|---|---|---|')
        o.append('| off (neutral) | %s | %s |' % (p['off']['identity'], p['off']['edge_last']))
        o.append('| on (skel_on) | %s | %s |' % (p['on']['identity'], p['on']['edge_last']))
        o.append('\n%s\n' % p['note'])
    o.append('\n## Four-state ledger\n')
    for n, r in L['arms'].items():
        o.append('- **%s**: identity `%s`' % (n, g(n, 'identity', 'state')))
        for k, v in (r.get('edge_corr') or {}).items():
            o.append('  - edge_corr %s: `%s` %s' % (k, v.get('state'), v.get('note') or v.get('value')))
    o.append('\nLedger JSON beside this file. identity_bank as it stood: %s\n' % json.dumps(L.get('identity_bank', {})))
    open(path, 'w').write('\n'.join(o) + '\n')


if __name__ == '__main__':
    sys.exit(main())
