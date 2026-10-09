# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calibrate a quick per-frame defect screen for the kids-music picture leg.

Scores every GENERATED frame already on disk (storyboard.json source_render
generated/generated_retry) on cheap pixel statistics and CLIP defect contrasts,
with two CLIP sizes, and writes contact sheets of the worst-ranked and of a
random sample (the null: the base defect rate) for judging by eye.

  python tools/kidsvideo_defect_bench.py score      -> scores.json
  python tools/kidsvideo_defect_bench.py sheets KEY -> sheet_<KEY>_top.jpg / _random.jpg
Output: output/kidsmusic/_frame_defect_bench/
"""

import glob
import json
import os
import random
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


CREWS = str(paths.ZYG_CREWS_ROOT)
OUT = os.path.join(CREWS, 'output/kidsmusic/_frame_defect_bench')

DEFECT_POS = ['a clean, well-drawn flat cartoon illustration for children']
DEFECT_NEG = {
    'anatomy': [
        'a deformed cartoon animal with extra legs, extra heads or missing limbs',
        'a distorted, melted, malformed cartoon face',
    ],
    'glitch': ['a glitchy corrupted image full of noise and artifacts', 'a blurry smeared unfinished picture'],
    'fused': ['two cartoon animals fused into one strange body', 'a messy jumble of overlapping broken shapes'],
}


def frames():
    rows = []
    for sb in sorted(glob.glob(os.path.join(CREWS, 'output/kidsmusic/*/storyboard.json'))):
        d = os.path.dirname(sb)
        try:
            slots = json.load(open(sb)).get('slots') or []
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('slot board unreadable, render skipped: %s', _exc)
            continue
        for s in slots:
            if s.get('source_render') in ('generated', 'generated_retry'):
                p = os.path.join(d, 'frames', f'f{s["i"]:03d}.png')
                if os.path.isfile(p):
                    rows.append({'path': p, 'job': os.path.basename(d), 'idea': s.get('idea', '')})
    return rows


def pixel_stats(path):
    with Image.open(path) as im:
        rgb = np.asarray(im.convert('RGB').resize((384, 216)), dtype=np.float32) / 255.0
    g = rgb.mean(axis=2)
    gx, gy = np.abs(np.diff(g, axis=1)), np.abs(np.diff(g, axis=0))
    # tiles 8x8 over the frame: share that are (near) flat
    th, tw = 216 // 8, 384 // 8
    tiles = g[: th * 8, : tw * 8].reshape(8, th, 8, tw).std(axis=(1, 3))
    lap = np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    q = (rgb * 15).round().astype(np.int32)
    ncol = len(np.unique(q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]))
    return {
        'std': float(g.std()),
        'edge': float((gx.mean() + gy.mean()) / 2),
        'flat_tiles': float((tiles < 0.02).mean()),
        'hf': float(lap.mean()),
        'dark': float((g < 0.04).mean()),
        'white': float((g > 0.97).mean()),
        'colours': int(ncol),
    }


def clip_scorer(name):
    import open_clip
    import torch

    if name == 'B32':
        model, _, pre = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
        tok = open_clip.get_tokenizer('ViT-B-32')
    else:
        model, _, pre = open_clip.create_model_and_transforms('ViT-L-14', pretrained='openai')
        tok = open_clip.get_tokenizer('ViT-L-14')
    model.eval().to('cuda')
    caps = DEFECT_POS + [c for k in DEFECT_NEG for c in DEFECT_NEG[k]]
    with torch.no_grad():
        x = model.encode_text(tok(caps).to('cuda'))
        x = x / x.norm(dim=-1, keepdim=True)

    def score(path):
        with Image.open(path) as im:
            t = pre(im.convert('RGB')).unsqueeze(0).to('cuda')
        with torch.no_grad():
            i = model.encode_image(t)
            i = i / i.norm(dim=-1, keepdim=True)
            logits = (100.0 * i @ x.T).squeeze(0)
        out, j = {}, 1
        for k, negs in DEFECT_NEG.items():
            sub = torch.cat([logits[:1], logits[j : j + len(negs)]]).softmax(-1)
            out[k] = float(1.0 - sub[0])  # probability mass on the defect captions
            j += len(negs)
        out['any'] = float(1.0 - logits.softmax(-1)[0])
        return out

    return score


def cmd_score():
    rows = frames()
    _zyg_log.info(f'{len(rows)} generated frames')
    for r in rows:
        r['px'] = pixel_stats(r['path'])
    for name in ('B32', 'L14'):
        sc = clip_scorer(name)
        t0 = time.time()
        for r in rows:
            r[name] = sc(r['path'])
        _zyg_log.info(f'{name}: {(time.time() - t0) / len(rows) * 1000:.1f} ms/frame')
        import torch

        del sc
        torch.cuda.empty_cache()
    json.dump(rows, open(os.path.join(OUT, 'scores.json'), 'w'), indent=0)


def sheet(items, dst, label):
    W, H, cols = 384, 216, 6
    rows = (len(items) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * W, rows * (H + 18)), (20, 20, 20))
    d = ImageDraw.Draw(canvas)
    for n, (p, txt) in enumerate(items):
        with Image.open(p) as im:
            canvas.paste(im.convert('RGB').resize((W, H)), ((n % cols) * W, (n // cols) * (H + 18)))
        d.text(((n % cols) * W + 4, (n // cols) * (H + 18) + H + 3), f'{n}: {txt}', fill=(255, 255, 0))
    canvas.save(dst, quality=85)


def cmd_sheets(key, k=36):
    rows = json.load(open(os.path.join(OUT, 'scores.json')))
    model, sub = key.split('.')  # e.g. L14.anatomy
    ranked = sorted(rows, key=lambda r: -r[model][sub])
    sheet(
        [(r['path'], f'{r[model][sub]:.2f} {r["job"][:6]}/{os.path.basename(r["path"])}') for r in ranked[:k]],
        os.path.join(OUT, f'sheet_{key}_top.jpg'),
        key,
    )
    rnd = random.Random(7).sample(rows, k)
    sheet(
        [(r['path'], f'{r[model][sub]:.2f} {r["job"][:6]}/{os.path.basename(r["path"])}') for r in rnd],
        os.path.join(OUT, 'sheet_random.jpg'),
        'random',
    )
    json.dump(
        [{'rank': i, 'path': r['path'], 'score': r[model][sub]} for i, r in enumerate(ranked[:k])],
        open(os.path.join(OUT, f'sheet_{key}_top.json'), 'w'),
        indent=1,
    )


if __name__ == '__main__':
    if sys.argv[1] == 'score':
        cmd_score()
    else:
        cmd_sheets(sys.argv[2])
