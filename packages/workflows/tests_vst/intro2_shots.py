#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Take 2 intro shots — three FIRST-PERSON Wan2.2 shots, 480p hunt + 720p winner.

Session-tree task zygomatic-ai-intro-take-2-first-person-o-78f727#3.

Take 1 (tests_vst/intro_shots.py) put the eagle in frame because every prompt
named it. Here nothing of the bird may ever be visible: the prompts describe a
flying camera only, and bird/wings/feathers/beak are banned in the negative and
checked by the VLM judge on five frames of every candidate.

Runs video_studio IN THIS PROCESS (the render worker is a thread here), so the
live kanban-server is never restarted.

    python tests_vst/intro2_shots.py shot --k 1 --seed 1001 --res 832x480
    python tests_vst/intro2_shots.py receipt --chosen 1:1001:832x480,...
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)

# wan_video_service budgets a ComfyUI submit with ZYG_WAN_TIMEOUT_S (default
# 900 s), which take 1 measured as too short for a 53-frame 720p clip
# (~1200 s). Must be set before video_studio is imported.
os.environ.setdefault('ZYG_WAN_TIMEOUT_S', '2100')

OUT = os.path.join(CREWS, 'output', 'video_studio', 'intro_zygomatic_ai_v2')
os.makedirs(OUT, exist_ok=True)
FRAMES_DIR = os.path.join(OUT, 'gate_frames')
os.makedirs(FRAMES_DIR, exist_ok=True)

START_STILL = os.path.join(OUT, 'still_v2_tornadoes.png')

NEG = (
    'eagle, bird, wings, feathers, beak, animal, creature, person, '
    'silhouette, foreground object, black smoke, dark smoke, fire, '
    'explosion, static, frozen, still image, text, letters, watermark, '
    'logo, buildings, roads, vehicles, blurry, low quality'
)

SHOTS = {
    1: dict(
        frames=53,
        scene_prompt=(
            'Point-of-view shot from a camera flying fast and straight ahead '
            'over a vast golden desert toward three distant pale sand-coloured '
            'dust devils spinning on the horizon; fast forward flight, the '
            'dunes rush past beneath, the horizon holds steady while the dust '
            'devils slowly grow closer, fine sand streaming low across the '
            'dunes, warm golden light, hazy horizon, smooth gliding flight, '
            'photoreal'
        ),
        camera_move='slow push in',
        camera_speed='a fast aggressive camera move',
        camera_height="a bird's-eye view far above",
    ),
    2: dict(
        frames=45,
        scene_prompt=(
            'Point-of-view shot from a camera flying over the desert that '
            'banks and turns to the left, panning left smoothly and steadily '
            'so the distant dust devils slide out of the frame on the right '
            'and empty rolling dunes are revealed, fine sand streaming across '
            'the dunes, warm golden light, photoreal'
        ),
        camera_move='slow pan left',
        camera_speed='a steady camera move',
        camera_height="a bird's-eye view far above",
    ),
    3: dict(
        frames=45,
        scene_prompt=(
            'Point-of-view shot from a camera flying over the desert that '
            'dives steeply toward the sand, tilting down and rushing downward '
            'fast, the rippled sand rushes up to fill the frame, then the dive '
            'slows and the view settles at a low hovering angle just above the '
            'rippled sand, fine grains blowing across the ground in sharp '
            'detail, warm golden light, photoreal'
        ),
        camera_move='slow tilt down',
        camera_speed='a fast aggressive camera move',
        camera_height='auto',
    ),
}

Q_BIRD = 'Is any bird, eagle, wing, feather, beak, animal or person visible anywhere in the picture?'
Q_SMOKE = 'Do any dark grey or black smoke plumes appear in the picture?'
Q_SPECIFIC = {
    1: (
        'Comparing the two pictures, are the distant dust devils larger and '
        'closer in the second picture than in the first?'
    ),
    3: ('Is the second picture looking down at the sand from much closer to the ground than the first picture?'),
}
PREAMBLE = (
    'You are judging single frames of an aerial desert video. Answer '
    'each question with yes or no about what is actually visible in '
    'the picture, then give a one-sentence reason.'
)


# ───────────────────────────────────────────────────────────── render params
def params_for(k: int, seed: int, res: str) -> dict:
    from zyg_workflows import video_studio as vs

    p = dict(vs.defaults())
    p.update(
        pathway='wan22',
        resolution=res,
        duration_s='1.7',
        fps=17,
        steps=20,
        guidance=5.0,
        seed_mode='fixed',
        variants=1,
        retries=0,
        motion_gate=True,
        black_gate=True,
        freeze_gate=True,
        prompt_mode='auto',
        negative_prompt=NEG,
        camera_rig='aerial drone shot',
        lens='shot on a 24mm wide lens',
        motion_amount='dynamic',
        weather='in a dust-filled haze',
        save_params=True,
        save_graph=True,
        keep_subclips=True,
        color_match=False,
        seed=seed,
    )
    p.update(SHOTS[k])
    if k > 1:
        p['start_from'] = 'last'
    return p


# ─────────────────────────────────────────────────────────── frame geometry
def _frames_all(path: str) -> list[np.ndarray]:
    cap = cv2.VideoCapture(path)
    got = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        got.append(fr)
    cap.release()
    return got


def _grey320(fr: np.ndarray) -> np.ndarray:
    hh = max(1, int(round(fr.shape[0] * 320 / fr.shape[1])))
    return cv2.cvtColor(cv2.resize(fr, (320, hh)), cv2.COLOR_BGR2GRAY)


def _affine(a: np.ndarray, b: np.ndarray):
    orb = cv2.ORB_create(nfeatures=4000)
    k1, d1 = orb.detectAndCompute(a, None)
    k2, d2 = orb.detectAndCompute(b, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return None, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    m = sorted(bf.match(d1, d2), key=lambda x: x.distance)[:400]
    if len(m) < 8:
        return None, len(m)
    src = np.float32([k1[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
    dst = np.float32([k2[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    return M, len(m)


def geometry(path: str) -> dict:
    """(s, tx, ty) of frame 0 → last frame, translation as a fraction of W/H.

    This endpoint fit is what the brief gates shot 1 and shot 2 on."""
    fr = _frames_all(path)
    if len(fr) < 2:
        return {'error': f'only {len(fr)} frame(s)'}
    a, b = _grey320(fr[0]), _grey320(fr[-1])
    gh, gw = a.shape
    M, nmatch = _affine(a, b)
    if M is None:
        return {'error': 'affine fit failed', 'matches': nmatch, 'n_frames': len(fr)}
    s = math.sqrt(max(1e-12, abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])))
    return {
        's': round(float(s), 4),
        'tx': round(float(M[0, 2]) / gw, 4),
        'ty': round(float(M[1, 2]) / gh, 4),
        'matches': nmatch,
        'n_frames': len(fr),
        'method': 'orb+estimateAffinePartial2D@320px',
    }


def geometry_chained(path: str) -> dict:
    """The same partial affine ACCUMULATED frame to frame — each pair stays
    inside its own overlap, so this stays honest on a push-in or a dive where
    the endpoint fit is degenerate. Recorded, never gated on."""
    fr = [_grey320(f) for f in _frames_all(path)]
    if len(fr) < 2:
        return {'error': f'only {len(fr)} frame(s)'}
    gh, gw = fr[0].shape
    s, tx, ty, used = 1.0, 0.0, 0.0, 0
    for a, b in zip(fr[:-1], fr[1:]):
        M, _n = _affine(a, b)
        if M is None:
            continue
        used += 1
        s *= math.sqrt(max(1e-12, abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])))
        tx += float(M[0, 2]) / gw
        ty += float(M[1, 2]) / gh
    return {'s': round(s, 4), 'tx': round(tx, 4), 'ty': round(ty, 4), 'pairs_used': used, 'pairs': len(fr) - 1}


def extract5(path: str, tag: str) -> list[str]:
    """Five frames at 0/25/50/75/100 percent, pulled with ffmpeg."""
    n = int(
        subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-count_frames',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=nb_read_frames',
                '-of',
                'csv=p=0',
                path,
            ],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .split(',')[0]
    )
    fps = 17.0
    out = []
    for pct in (0, 25, 50, 75, 100):
        idx = int(round(pct * (n - 1) / 100.0))
        p = os.path.join(FRAMES_DIR, f'{tag}_p{pct:03d}.png')
        subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-loglevel',
                'error',
                '-ss',
                f'{idx / fps:.4f}',
                '-i',
                path,
                '-frames:v',
                '1',
                '-update',
                '1',
                p,
            ],
            check=True,
        )
        if not os.path.isfile(p):
            raise SystemExit(f'frame extract failed: {p}')
        out.append(p)
    return out


def contact_sheet(frames: list[str], out_jpg: str) -> str:
    tiles = [cv2.resize(cv2.imread(p), (320, 180)) for p in frames]
    cv2.imwrite(out_jpg, np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_jpg


# ───────────────────────────────────────────────────────────────── VLM judge
def _gpu_free_mib() -> float:
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(r.stdout.strip().splitlines()[0].split()[0])
    except Exception:  # noqa: BLE001
        return 0.0


def vlm_judge(k: int, frames: list[str]) -> dict:
    """One worker call for every question of one candidate.

    `frame_indices` pins each question to a single picture, so the five
    bird/smoke answers are genuinely per-frame rather than one verdict over the
    whole set. The shot-specific comparison gets the [first, last] pair."""
    from zyg_workflows import vlm_inspector as vi

    items = []
    for i in range(len(frames)):
        items.append(
            {
                'id': f'bird_{i}',
                'question': Q_BIRD,
                'expected': 'no',
                'severity': 'major',
                'frames': 'all',
                'frame_indices': [i],
            }
        )
    for i in range(len(frames)):
        items.append(
            {
                'id': f'smoke_{i}',
                'question': Q_SMOKE,
                'expected': 'no',
                'severity': 'major',
                'frames': 'all',
                'frame_indices': [i],
            }
        )
    if k in Q_SPECIFIC:
        items.append(
            {
                'id': 'specific',
                'question': Q_SPECIFIC[k],
                'expected': 'yes',
                'severity': 'major',
                'frames': 'all',
                'frame_indices': [0, len(frames) - 1],
            }
        )
    free = _gpu_free_mib()
    tier, offload = ('resident', False) if free >= 12000 else ('boundary', True)
    print(f'  vlm: {free:.0f} MiB free → tier={tier} offload={offload}', flush=True)
    res = vi.inspect_frames(
        frames,
        items=items,
        preamble=PREAMBLE,
        tier=tier,
        offload=offload,
        frame_kind='all',
        log_fn=lambda m: print('  vlm|', str(m)[:200], flush=True),
    )
    if not res or res.get('skipped'):
        return {'skipped': True, 'reason': str((res or {}).get('reason'))}
    by_id = {}
    for v in res.get('verdicts') or []:
        by_id[str(v.get('id'))] = {
            'answer': str(v.get('answer') or 'unknown').lower(),
            'reason': str(v.get('reason') or '')[:200],
        }
    return {
        'skipped': False,
        'by_id': by_id,
        'tier': res.get('tier'),
        'model': res.get('model'),
        'seconds': res.get('seconds'),
    }


# ───────────────────────────────────────────────────────────────── the gates
def worker_gates(log: list[str]) -> dict:
    lines = [l for l in log if 'gate' in l]
    hits = {'motion': None, 'black': None, 'duplicate': None}
    for l in lines:
        if 'frozen-clip gate' in l:
            hits['motion'] = 'passed' in l
        if 'black-frame gate' in l:
            hits['black'] = 'passed' in l
        if 'duplicate-frame gate' in l:
            hits['duplicate'] = 'passed' in l
    return {
        'lines': lines,
        'motion': hits['motion'],
        'black': hits['black'],
        'duplicate': hits['duplicate'],
        'ok': all(v is True for v in hits.values()),
    }


def evaluate(k: int, path: str, log: list[str], tag: str) -> dict:
    frames = extract5(path, tag)
    judged = vlm_judge(k, frames)
    by = judged.get('by_id', {})
    bird = [by.get(f'bird_{i}', {}).get('answer', 'unknown') for i in range(len(frames))]
    smoke = [by.get(f'smoke_{i}', {}).get('answer', 'unknown') for i in range(len(frames))]
    wg = worker_gates(log)
    geo = geometry(path)
    chained = geometry_chained(path)

    if k == 1:
        sp_ans = by.get('specific', {}).get('answer', 'unknown')
        sp_ok = (sp_ans == 'yes') and float(geo.get('s', 0.0)) >= 1.04
        specific = {
            'rule': 'vlm dust devils closer = yes AND endpoint s>=1.04',
            'vlm': sp_ans,
            's': geo.get('s'),
            'ok': bool(sp_ok),
        }
    elif k == 2:
        sp_ok = float(geo.get('tx', 0.0)) >= 0.12
        specific = {
            'rule': 'endpoint tx>=+0.12W (a pan LEFT moves content RIGHT)',
            'tx': geo.get('tx'),
            'ok': bool(sp_ok),
        }
    else:
        sp_ans = by.get('specific', {}).get('answer', 'unknown')
        sp_ok = sp_ans == 'yes'
        specific = {
            'rule': 'vlm closer to the ground = yes (affine recorded only: the endpoint fit is degenerate on a dive)',
            'vlm': sp_ans,
            'ty_endpoint': geo.get('ty'),
            'ty_chained': chained.get('ty'),
            'ok': bool(sp_ok),
        }

    bird_ok = bool(bird) and all(a == 'no' for a in bird)
    smoke_ok = bool(smoke) and all(a == 'no' for a in smoke)
    failed = [
        n
        for n, v in (('vlm_bird', bird_ok), ('vlm_smoke', smoke_ok), ('worker', wg['ok']), ('specific', sp_ok))
        if not v
    ]
    return {
        'frames_judged': frames,
        'vlm': judged,
        'gates': {
            'vlm_bird': bird,
            'vlm_smoke': smoke,
            'vlm_bird_reasons': [by.get(f'bird_{i}', {}).get('reason') for i in range(len(frames))],
            'worker': wg,
            'specific': specific,
        },
        'geometry': geo,
        'geometry_chained': chained,
        'failed_gates': failed,
        'passed': not failed,
    }


# ──────────────────────────────────────────────────────────────── one render
def _run(k: int, seed: int, res: str, src: str) -> dict:
    from zyg_workflows import video_studio as vs

    p = params_for(k, seed, res)
    if k == 1:
        j = vs.start_render('still', f'intro2 shot1 seed {seed} {res}', src, p)
    else:
        j = vs.start_render_from_video(f'intro2-s{k - 1}', f'intro2 shot{k} seed {seed} {res}', src, p)
    jid = j['id']
    print(f'shot{k} seed{seed} {res} jid={jid} src={src}', flush=True)
    t0 = time.time()
    seen = 0
    while True:
        st = vs.job(jid)
        log = st.get('log', [])
        for line in log[seen:]:
            print('  |', line, flush=True)
        seen = len(log)
        if st.get('state') in ('done', 'error'):
            break
        if time.time() - t0 > 2400:
            raise SystemExit(f'shot{k} seed{seed} {res}: 40 min cap hit')
        time.sleep(30)
    st = vs.job(jid)
    rec = {
        'k': k,
        'jid': jid,
        'seed': seed,
        'res': res,
        'src': src,
        'state': st['state'],
        'error': st.get('error', ''),
        'wall_s': round(time.time() - t0, 1),
        'log': list(st.get('log', [])),
    }
    if st['state'] == 'done' and st.get('urls'):
        rel = st['urls'][0].split('path=', 1)[1]
        rec['path'] = os.path.join(CREWS, 'output', rel[4:] if rel.startswith('out/') else rel)
        pos = next((l.split('positive:', 1)[1].strip() for l in rec['log'] if 'positive:' in l), '')
        rec['positive'] = pos
        tag = f'shot{k}_{res}_seed{seed}'
        rec.update(evaluate(k, rec['path'], rec['log'], tag))
        rec['sheet'] = contact_sheet(rec['frames_judged'], os.path.join(OUT, f'sheet_{tag}.jpg'))
    return rec


def stage_shot(k: int, seed: int, res: str, src: str) -> None:
    if not src:
        src = START_STILL if k == 1 else os.path.join(OUT, f'shot{k - 1}.mp4')
    if not os.path.isfile(src):
        raise SystemExit(f'source missing: {src}')
    rec = _run(k, seed, res, src)
    with open(os.path.join(OUT, f'attempt_shot{k}_{res}_seed{seed}.json'), 'w') as f:
        json.dump(rec, f, indent=1)
    slim = {
        x: rec[x] for x in ('k', 'jid', 'seed', 'res', 'state', 'error', 'wall_s', 'failed_gates', 'passed') if x in rec
    }
    slim['gates'] = rec.get('gates', {})
    print('RESULT ' + json.dumps(slim), flush=True)
    print(('PASSED ' if rec.get('passed') else 'FAILED ') + f'shot{k} seed {seed} {res}', flush=True)


def stage_adopt(k: int, seed: int, res: str) -> None:
    """Copy a candidate to shot<k>.mp4 — the file the next shot continues from
    and the file the receipt ships."""
    rec = json.load(open(os.path.join(OUT, f'attempt_shot{k}_{res}_seed{seed}.json')))
    dst = os.path.join(OUT, f'shot{k}.mp4')
    shutil.copy2(rec['path'], dst)
    print(f'ADOPTED shot{k} seed {seed} {res} → {dst} (passed={rec.get("passed")})', flush=True)


# ─────────────────────────────────────────────────────────────────── receipt
def stage_receipt(chosen: list[str], notes: str) -> None:
    shots = []
    for spec in chosen:
        k, seed, res = spec.split(':')
        k, seed = int(k), int(seed)
        rec = json.load(open(os.path.join(OUT, f'attempt_shot{k}_{res}_seed{seed}.json')))
        fr = SHOTS[k]['frames']
        tried = sorted(os.path.basename(p) for p in glob.glob(os.path.join(OUT, f'attempt_shot{k}_*.json')))
        shots.append(
            {
                'k': k,
                'jid': rec['jid'],
                'seed': seed,
                'res': res,
                'path': os.path.join(OUT, f'shot{k}.mp4'),
                'render_path': rec.get('path', ''),
                'frames': fr,
                'fps': 17,
                'duration_s': round(fr / 17.0, 3),
                'gates': {
                    'vlm_bird': rec['gates']['vlm_bird'],
                    'vlm_smoke': rec['gates']['vlm_smoke'],
                    'worker': rec['gates']['worker'],
                    'specific': rec['gates']['specific'],
                },
                'vlm_bird_reasons': rec['gates'].get('vlm_bird_reasons', []),
                'geometry': rec.get('geometry', {}),
                'geometry_chained': rec.get('geometry_chained', {}),
                'failed_gates': rec.get('failed_gates', []),
                'passed': bool(rec.get('passed')),
                'wall_s': rec.get('wall_s'),
                'attempts': tried,
                'sheet': rec.get('sheet', ''),
                'positive': rec.get('positive', ''),
            }
        )
    out = {
        'start_still': START_STILL,
        'negative_prompt': NEG,
        'questions': {'vlm_bird': Q_BIRD, 'vlm_smoke': Q_SMOKE, 'specific': Q_SPECIFIC},
        'shots': shots,
        'notes': notes,
    }
    with open(os.path.join(OUT, 'shots_v2.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1)[:4000], flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=('shot', 'adopt', 'receipt'))
    ap.add_argument('--k', type=int, default=1)
    ap.add_argument('--seed', type=int, default=1001)
    ap.add_argument('--res', default='832x480')
    ap.add_argument('--src', default='')
    ap.add_argument('--chosen', default='')
    ap.add_argument('--notes', default='')
    a = ap.parse_args()
    if a.stage == 'shot':
        stage_shot(a.k, a.seed, a.res, a.src)
    elif a.stage == 'adopt':
        stage_adopt(a.k, a.seed, a.res)
    else:
        stage_receipt([s for s in a.chosen.split(',') if s], a.notes)


if __name__ == '__main__':
    main()
