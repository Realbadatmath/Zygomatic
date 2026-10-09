#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Take 2 title: matched clean sand plate, 'Zygomatic Ai', swirl, dust impacts.

Stages (run in order, each cached on disk):
    fin      -- finish shot3 the way the final will -> shot3_fin.mp4, end_plate.png
    plate    -- Qwen clean sand plate -> plate_clean.png -> plate_matched.png
    words    -- sand_title_fx.write_words_any -> words.png
    swirl    -- sand_title_fx.swirl_in -> title.mp4
    impacts  -- video_overlay.composite (draft then final) -> title_fx.mp4
    receipt  -- title_receipt.json

Run from $ZYG_CREWS_ROOT with the crews venv.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np
from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
OUT = os.path.join(CREWS, 'output/video_studio/intro_zygomatic_ai_v2')
CAND = os.path.join(OUT, 'plate_candidates')
TMP = os.path.join(OUT, '_tmp')

SHOT3 = os.path.join(OUT, 'shot3.mp4')
SHOT3_FIN = os.path.join(OUT, 'shot3_fin.mp4')
RAMPED = os.path.join(OUT, 'shot3_ramped.mp4')
END_PLATE = os.path.join(OUT, 'end_plate.png')
PLATE_CLEAN = os.path.join(OUT, 'plate_clean.png')
PLATE_MATCHED = os.path.join(OUT, 'plate_matched.png')
WORDS_PNG = os.path.join(OUT, 'words.png')
TITLE = os.path.join(OUT, 'title.mp4')
TITLE_FX = os.path.join(OUT, 'title_fx.mp4')
TITLE_FX_DRAFT = os.path.join(OUT, 'title_fx_draft.mp4')
DRAFT_JPG = os.path.join(OUT, 'title_fx_draft.jpg')
PUFF_JPG = os.path.join(OUT, 'title_fx_puffs.jpg')
RECEIPT = os.path.join(OUT, 'title_receipt.json')
STATE = os.path.join(OUT, '_title_state.json')

W, H = 1920, 1080
WORDS = 'Zygomatic Ai'
PLATE_SEEDS = [5, 15, 25]

PLATE_PROMPT = (
    'extreme low hovering angle just above a flat desert floor of golden '
    'rippled sand at golden hour, the sand ripples running away from the '
    'camera, fine sand grains blowing across the ground, warm low sun from '
    'the left, long soft shadows, photoreal, no text'
)
PLATE_NEG = 'text, letters, people, animals, birds, objects, rocks, plants, footprints, watermark'

Q_CLEAN = 'Is anything other than sand and sky visible?'
Q_PUFFS = 'Do the small dust puffs look sand-coloured rather than white or grey?'
PREAMBLE = (
    'You are inspecting a single rendered frame. Answer the question '
    'with yes or no about what is actually visible in the picture, '
    'then give a short reason.'
)

ELEMENT = os.path.join(CREWS, 'data/asset_libraries/vfx_volumes/grenadedustimpactvdb_4k.mov')
IMPACT_HEIGHTS = [0.10, 0.13, 0.16, 0.12, 0.11]
IMPACT_STARTS = [0.2, 0.55, 0.9, 1.3, 1.8]

ESRGAN_GRAPH = os.path.join(CREWS, '_comfy_workflows/image_esrgan_upscale.json')
VLM_MIN_FREE_MIB = 12000.0


def log(msg):
    print(msg, flush=True)


def _state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {}


def _save(key, val):
    s = _state()
    s[key] = val
    json.dump(s, open(STATE, 'w'), indent=2)
    return val


def _run(cmd, what, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise SystemExit(f'{what} failed rc={r.returncode}\n{r.stderr[-2000:]}')
    return r


# ── vlm ────────────────────────────────────────────────────────────────────
def _gpu_free_mib() -> float:
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(re.findall(r'[\d.]+', r.stdout.strip().splitlines()[0])[0])
    except Exception:  # noqa: BLE001
        return 0.0


def vlm_answer(paths, question, qid, expected):
    """Per-frame [(path, answer, reason)] from the local judge; [] if it cannot run."""
    from zyg_workflows import vlm_inspector as vi

    if not vi.available():
        log('vlm unavailable')
        return []
    free = _gpu_free_mib()
    tier, offload = ('resident', False) if free >= VLM_MIN_FREE_MIB else ('boundary', True)
    log(f'vlm: {free:.0f} MiB free -> tier={tier} offload={offload}')
    rows = []
    for p in list(paths):
        res = vi.inspect_frames(
            [p],
            items=[{'id': qid, 'question': question, 'expected': expected, 'severity': 'major', 'frames': 'all'}],
            preamble=PREAMBLE,
            tier=tier,
            offload=offload,
            frame_kind='all',
            log_fn=lambda m: log(str(m)[:200]),
        )
        if not res or res.get('skipped'):
            log(f'vlm skipped ({(res or {}).get("reason")})')
            rows.append((p, '', ''))
            continue
        v = (res.get('verdicts') or [None])[0] or {}
        ans = str(v.get('answer') or '').strip().lower()
        reason = str(v.get('reason') or '')[:300]
        log(f'vlm {qid} {os.path.basename(p)}: answer={ans!r} reason={reason[:140]!r}')
        rows.append((p, ans, reason))
    return rows


# ── stage: finish shot 3 ───────────────────────────────────────────────────
def stage_fin():
    from zyg_workflows import video_finish
    from zyg_workflows import video_assembly

    os.makedirs(TMP, exist_ok=True)
    rec = {}
    if not os.path.exists(SHOT3_FIN):
        rife = os.path.join(TMP, 'shot3_rife.mp4')
        up = os.path.join(TMP, 'shot3_up.mp4')
        if not os.path.exists(rife):
            rec['rife'] = video_finish.rife_2x(SHOT3, rife, out_fps=24, log=log)
            log(f'rife: {rec.get("rife")}')
        if not os.path.exists(up):
            rec['esrgan'] = video_finish.esrgan_clip(rife, up, scale=2, log=log)
            log(f'esrgan: {rec.get("esrgan")}')
        _run(
            [
                'ffmpeg',
                '-y',
                '-i',
                up,
                '-vf',
                f'scale={W}:{H}:flags=lanczos',
                '-c:v',
                'libx264',
                '-crf',
                '16',
                '-pix_fmt',
                'yuv420p',
                '-an',
                SHOT3_FIN,
            ],
            'lanczos 1080p',
        )
        log(f'finished -> {SHOT3_FIN}')

    if not os.path.exists(END_PLATE):
        shotlist = {
            'fps': 24,
            'size': [W, H],
            'audio': None,
            'shots': [{'path': SHOT3_FIN, 'speed_ramp': {'tail_s': 0.8, 'end_speed': 0.12}, 'overlay': None}],
        }
        rec['assembly'] = video_assembly.assemble(shotlist, RAMPED, log=log)
        log(f'ramped: {rec["assembly"]}')
        # last frame of the ramped clip
        _run(
            [
                'ffmpeg',
                '-y',
                '-sseof',
                '-0.2',
                '-i',
                RAMPED,
                '-update',
                '1',
                '-frames:v',
                '1',
                '-vf',
                f'scale={W}:{H}:flags=lanczos',
                END_PLATE,
            ],
            'end_plate extract',
        )
        img = cv2.imread(END_PLATE)
        if img is None or img.shape[:2] != (H, W):
            raise SystemExit(f'end_plate bad: {None if img is None else img.shape}')
        log(f'end_plate -> {END_PLATE} {img.shape}')
    return _save('fin', {k: v for k, v in rec.items()})


# ── stage: clean plate ─────────────────────────────────────────────────────
def _esrgan_x2(src_png, dst_png):
    from zyg_workflows import _comfy_client as c

    if not c.server_reachable():
        raise SystemExit('ComfyUI not reachable at 127.0.0.1:8188')
    graph = json.load(open(ESRGAN_GRAPH))
    name = c.stage_input_image(src_png)
    outs = c.submit(graph, {'10': {'image': name}}, timeout_s=900)
    if not outs:
        raise SystemExit('esrgan upscale produced no output')
    log(f'esrgan x2 -> {outs[0]}')
    return outs[0]


def stage_plate():
    os.makedirs(CAND, exist_ok=True)
    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_workflows import comfy_generation_service as cgs

    for s in PLATE_SEEDS:
        p = os.path.join(CAND, f'plate_{s}.png')
        if os.path.exists(p):
            log(f'plate seed {s}: cached')
            continue
        log(f'plate seed {s}: generating')
        ok, backend = cgs.generate_still(
            p,
            PLATE_PROMPT,
            width=1280,
            height=720,
            steps=20,
            cfg=3.5,
            seed=s,
            model_family='qwen',
            skip_qa=True,
            prompt_finalized=True,
            solo_subject=False,
            human_subject=False,
            extra_negative=PLATE_NEG,
            log_fn=lambda m: log(str(m)[:200]),
        )
        log(f'plate seed {s}: ok={ok} backend={backend}')
        if not ok:
            raise SystemExit(f'generate_still failed for seed {s}: {backend}')

    paths = [os.path.join(CAND, f'plate_{s}.png') for s in PLATE_SEEDS]
    rows = vlm_answer(paths, Q_CLEAN, 'plate_clean', 'no')
    ans = {p: (a, r) for p, a, r in rows}
    cands = []
    for s, p in zip(PLATE_SEEDS, paths):
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        lap = float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        a, r = ans.get(p, ('', ''))
        cands.append(
            {'seed': s, 'vlm_clean': a or 'unavailable', 'vlm_reason': r, 'laplacian': round(lap, 3), 'path': p}
        )
        log(f'plate seed {s}: clean={a!r} lap={lap:.1f}')
    passing = [c for c in cands if str(c['vlm_clean']).lower().startswith('no')]
    if not passing:
        raise SystemExit('no plate candidate passed the clean gate')
    best = max(passing, key=lambda c: c['laplacian'])
    log(f'chosen plate seed {best["seed"]} (lap {best["laplacian"]})')

    if not os.path.exists(PLATE_CLEAN):
        up = _esrgan_x2(best['path'], None)
        _run(
            ['ffmpeg', '-y', '-i', up, '-vf', f'scale={W}:{H}:flags=lanczos', '-frames:v', '1', PLATE_CLEAN],
            'plate lanczos 1080p',
        )
        log(f'plate_clean -> {PLATE_CLEAN}')

    before, after = colour_match()
    return _save(
        'plate',
        {
            'plate_seed': best['seed'],
            'candidates': [{k: v for k, v in c.items() if k != 'path'} for c in cands],
            'prompt': PLATE_PROMPT,
            'negative': PLATE_NEG,
            'match_rgb_before': before,
            'match_rgb_after': after,
        },
    )


def _hist_match_channel(src, ref):
    """Map src's per-channel CDF onto ref's (uint8 LUT)."""
    sh = np.bincount(src.ravel(), minlength=256).astype(np.float64)
    rh = np.bincount(ref.ravel(), minlength=256).astype(np.float64)
    scdf = np.cumsum(sh) / max(1.0, sh.sum())
    rcdf = np.cumsum(rh) / max(1.0, rh.sum())
    lut = np.searchsorted(rcdf, scdf).clip(0, 255).astype(np.uint8)
    return lut[src]


def colour_match(blend=0.70):
    src = cv2.imread(PLATE_CLEAN, cv2.IMREAD_COLOR)
    ref = cv2.imread(END_PLATE, cv2.IMREAD_COLOR)
    if src is None or ref is None:
        raise SystemExit('colour match needs plate_clean.png and end_plate.png')
    if ref.shape[:2] != src.shape[:2]:
        ref = cv2.resize(ref, (src.shape[1], src.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    matched = np.dstack([_hist_match_channel(src[..., i], ref[..., i]) for i in range(3)])
    out = np.clip(src.astype(np.float32) * (1.0 - blend) + matched.astype(np.float32) * blend, 0, 255).astype(np.uint8)
    cv2.imwrite(PLATE_MATCHED, out)

    def rgb(a):  # BGR array -> RGB means
        return [round(float(a[..., i].mean()), 3) for i in (2, 1, 0)]

    before = {'plate_clean': rgb(src), 'end_plate': rgb(ref)}
    after = {'plate_matched': rgb(out), 'end_plate': rgb(ref), 'blend': blend}
    log(f'colour match before={before} after={after}')
    return before, after


# ── stage: words ───────────────────────────────────────────────────────────
# The module's default emboss dials (relief 28, shadow 0.72, fill 0.88) are
# tuned for a mid-tone plate. This plate is a blown-out golden-hour floor with
# the sun in frame, and at those settings the reader drops the 'Ai' over the
# glare and calls the Z an E ('Eygomatic'). The letters are drawn from a font,
# so the spelling was never in doubt — only the contrast was. The mildest bump
# that the gate reads exactly is kept, and the receipt records it.
EMBOSS_DIALS = {'EMBOSS_RELIEF': 40.0, 'EMBOSS_SHADOW': 0.60, 'EMBOSS_FILL': 0.80}


def stage_words():
    from zyg_workflows import sand_title_fx as S

    rec = S.write_words_any(PLATE_MATCHED, WORDS, WORDS_PNG, seeds=8, log=log)
    log(f'words: method={rec.get("method")} exact={rec.get("exact")} ocr={rec.get("ocr_text")!r}')
    if not rec.get('exact'):
        log(f'gate refused the default emboss too — re-embossing with {EMBOSS_DIALS}')
        prev = {k: getattr(S, k) for k in EMBOSS_DIALS}
        for k, v in EMBOSS_DIALS.items():
            setattr(S, k, v)
        try:
            emb = S.emboss_words(PLATE_MATCHED, WORDS, WORDS_PNG)
        finally:
            for k, v in prev.items():
                setattr(S, k, v)
        emb['emboss_dials'] = dict(EMBOSS_DIALS)
        emb['emboss_dials_default'] = prev
        emb['qwen'] = rec.get('qwen') or {k: rec.get(k) for k in ('exact', 'ocr_full', 'ocr_crop', 'seed', 'tried')}
        rec = emb
        log(f'words: method={rec.get("method")} exact={rec.get("exact")} ocr={rec.get("ocr_text")!r}')
    if not rec.get('exact'):
        raise SystemExit(f'words not exact: {rec}')
    return _save('words', rec)


# ── stage: swirl ───────────────────────────────────────────────────────────
def stage_swirl():
    from zyg_workflows import sand_title_fx as S

    n = S.swirl_in(PLATE_MATCHED, WORDS_PNG, TITLE, fps=24, dur_s=1.5, hold_s=5.0, log=log)
    log(f'swirl -> {TITLE} frames={n}')
    return _save('title_frames', int(n))


# ── stage: impacts ─────────────────────────────────────────────────────────
def build_record():
    from zyg_workflows import sand_title_fx as S

    mask = S.letters_mask(PLATE_MATCHED, WORDS_PNG)
    ys, xs = np.nonzero(mask)
    if not len(ys):
        raise SystemExit('no lettering mask for the impact placement')
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bw, bh = float(x1 - x0), float(y1 - y0)
    off = 0.12 * bh
    pts = [
        (x0 + 0.20 * bw, y0 - off),  # above
        (x0 + 0.75 * bw, y0 - off),
        (x0 + 0.10 * bw, y1 + off),  # below
        (x0 + 0.50 * bw, y1 + off),
        (x0 + 0.90 * bw, y1 + off),
    ]
    layers = []
    for (px, py), hgt, st in zip(pts, IMPACT_HEIGHTS, IMPACT_STARTS):
        layers.append(
            {
                'element': ELEMENT,
                'x': round(px / W, 5),
                'y': round(py / H, 5),
                'anchor': 'bottom-center',
                'height': hgt,
                'start_s': st,
                'loop': False,
                'speed': 0.6,
                'saturation': 0.7,
                'warm': [0.92, 0.66, 0.40],
                'opacity': 0.85,
            }
        )
    rec = {'layers': layers, 'draft': {'width': 480, 'fps': 12}, 'letters_bbox': [x0, y0, x1, y1]}
    log(f'letters bbox={rec["letters_bbox"]} layers={len(layers)}')
    return rec


def stage_impacts():
    from zyg_workflows import video_overlay

    rec = build_record()
    record = {'layers': rec['layers'], 'draft': rec['draft']}

    if not os.path.exists(DRAFT_JPG):
        video_overlay.composite(TITLE, record, TITLE_FX_DRAFT, draft=True, log=log)
        _run(
            [
                'ffmpeg',
                '-y',
                '-ss',
                '1.0',
                '-i',
                TITLE_FX_DRAFT,
                '-update',
                '1',
                '-frames:v',
                '1',
                '-q:v',
                '2',
                DRAFT_JPG,
            ],
            'draft frame',
        )
        log(f'draft frame -> {DRAFT_JPG}')

    out = video_overlay.composite(TITLE, record, TITLE_FX, draft=False, log=log)
    log(f'final composite -> {TITLE_FX} ({out})')

    _run(
        ['ffmpeg', '-y', '-ss', '2.0', '-i', TITLE_FX, '-update', '1', '-frames:v', '1', '-q:v', '2', PUFF_JPG],
        'puff frame',
    )
    rows = vlm_answer([PUFF_JPG], Q_PUFFS, 'puffs_sand', 'yes')
    _p, ans, reason = rows[0] if rows else ('', '', '')
    log(f'vlm puffs: {ans!r}')
    _save('impacts', rec)
    return _save('vlm_puffs', {'answer': ans or 'unavailable', 'reason': reason, 'frame': PUFF_JPG})


# ── receipt ────────────────────────────────────────────────────────────────
def stage_receipt():
    s = _state()
    out = {
        'plate_seed': s.get('plate', {}).get('plate_seed'),
        'plate_candidates': s.get('plate', {}).get('candidates'),
        'plate_prompt': s.get('plate', {}).get('prompt'),
        'plate_negative': s.get('plate', {}).get('negative'),
        'match_rgb_before': s.get('plate', {}).get('match_rgb_before'),
        'match_rgb_after': s.get('plate', {}).get('match_rgb_after'),
        'words': s.get('words'),
        'title_frames': s.get('title_frames'),
        'impacts': s.get('impacts'),
        'vlm_puffs': s.get('vlm_puffs'),
        'finish': s.get('fin'),
        'outputs': {
            'shot3_fin': SHOT3_FIN,
            'end_plate': END_PLATE,
            'plate_clean': PLATE_CLEAN,
            'plate_matched': PLATE_MATCHED,
            'words': WORDS_PNG,
            'title': TITLE,
            'title_fx': TITLE_FX,
        },
    }
    json.dump(out, open(RECEIPT, 'w'), indent=2)
    log(f'receipt -> {RECEIPT}')
    return out


STAGES = {
    'fin': stage_fin,
    'plate': stage_plate,
    'words': stage_words,
    'swirl': stage_swirl,
    'impacts': stage_impacts,
    'receipt': stage_receipt,
}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    os.chdir(CREWS)
    sys.path.insert(0, CREWS)
    want = sys.argv[1:] or list(STAGES)
    if want == ['all']:
        want = list(STAGES)
    for st in want:
        if st not in STAGES:
            raise SystemExit(f'unknown stage {st}')
        log(f'=== {st} ===')
        STAGES[st]()
    log('OK')
