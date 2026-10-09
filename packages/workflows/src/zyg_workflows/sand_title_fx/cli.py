# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Words written in the sand, proved by OCR, then swirled into being.

The CPU selftest, the GPU receipt and the command line — verbatim sections of the
former sand_title_fx.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image
import logging as _zyg_logging
from zyg_workflows.sand_title_fx.constants import (
    RECEIPT_DIR,
    FONT,
    _log,
)
from zyg_workflows.sand_title_fx.ocr_gate import (
    normalise,
    read_words,
)
from zyg_workflows.sand_title_fx.letters import (
    letters_mask,
    render_plate,
    write_words_in_sand,
)
from zyg_workflows.sand_title_fx.emboss import (
    _emboss_dilate,
    emboss_text_mask,
    emboss_words,
)
from zyg_workflows.sand_title_fx.reveal import (
    swirl_in,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sand_title_fx')


# ── selftest (CPU only) ─────────────────────────────────────────────────────
def _fake_plate(path, W=1280, H=720, seed=3):
    rng = np.random.default_rng(seed)
    base = np.array([116, 168, 196], np.float32)  # BGR tan
    arr = base + rng.normal(0, 6, (H, W, 1)).astype(np.float32)
    x = np.linspace(0, 40 * np.pi, W, dtype=np.float32)
    arr += np.sin(x)[None, :, None] * 4.0  # ripples
    cv2.imwrite(path, np.clip(arr, 0, 255).astype(np.uint8))
    return path


def _fake_words(plate_png, path, text='Zygomatic Ai'):
    from PIL import ImageDraw, ImageFont

    im = Image.open(plate_png).convert('RGB')
    W, H = im.size
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 132)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    x, y = (W - (x1 - x0)) // 2 - x0, (H - (y1 - y0)) // 2 - y0
    d.text((x + 4, y + 4), text, font=f, fill=(96, 74, 46))  # cast shadow
    d.text((x - 3, y - 3), text, font=f, fill=(226, 212, 176))  # sunlit edge
    d.text((x, y), text, font=f, fill=(150, 126, 84))  # sand body
    im.save(path)
    return path


def selftest() -> int:
    work = tempfile.mkdtemp(prefix='sandtitle_selftest_')
    plate = _fake_plate(os.path.join(work, 'plate.png'))
    words = _fake_words(plate, os.path.join(work, 'words.png'))

    raw, conf = read_words(words)
    got = normalise(raw)
    if got != 'zygomatic ai':
        raise RuntimeError(f'OCR gate read {raw!r} → {got!r}')
    print(f'ocr: {raw!r} conf {conf:.2f} → {got!r}')

    mp4 = os.path.join(work, 'swirl.mp4')
    n = swirl_in(plate, words, mp4, fps=24, dur_s=1.5, hold_s=0.0, relief_ramp=False)
    if n != 36:
        raise RuntimeError(f'expected 36 frames, got {n}')
    if os.path.getsize(mp4) <= 0:
        raise RuntimeError('empty mp4')

    frames = _read_frames(mp4)
    if len(frames) != 36:
        raise RuntimeError(f'mp4 holds {len(frames)} frames')
    p = cv2.imread(plate).astype(np.float32)
    w = cv2.imread(words).astype(np.float32)
    m = letters_mask(plate, words) > 0
    d_first = float(np.abs(frames[0].astype(np.float32) - p).mean())
    d_last = float(np.abs(frames[-1].astype(np.float32) - w)[m].mean())
    print(
        f'frames {len(frames)}  first|diff vs plate {d_first:.2f}  '
        f'last|diff vs words in mask {d_last:.2f}  mask {m.mean() * 100:.2f}%'
    )
    if not d_first < 6:
        raise RuntimeError(f'first frame already changed: {d_first:.2f}')
    if not d_last < 6:
        raise RuntimeError(f'last frame is not the words: {d_last:.2f}')

    # ---- the deterministic fallback --------------------------------------
    # It must spell (Reader A alone, no VLM), and it must touch NOTHING but
    # the letters: everything outside the 3x dilated mask stays the plate.
    emb = os.path.join(work, 'emboss.png')
    rec = emboss_words(plate, 'Zygomatic Ai', emb)
    got_e = normalise(rec['ocr_full'] or '')
    if got_e != 'zygomatic ai':
        raise RuntimeError(f'emboss OCR read {rec["ocr_full"]!r}')
    dil = _emboss_dilate(emboss_text_mask(1280, 720, 'Zygomatic Ai')) > 0
    e = cv2.imread(emb).astype(np.float32)
    outside = float(np.abs(e - p).mean(axis=2)[~dil].mean())
    print(
        f'emboss: ocr {rec["ocr_full"]!r} by {rec["read_by"]}  '
        f'bbox {rec["mask_bbox"]}  |diff| outside the dilated mask '
        f'{outside:.3f}'
    )
    if not rec['exact']:
        raise RuntimeError('the gate did not pass the embossed frame')
    if not outside < 2:
        raise RuntimeError(f'the emboss changed the plate outside the letters: {outside:.3f}')

    # ---- strength scales the relief --------------------------------------
    weak = os.path.join(work, 'emboss_weak.png')
    emboss_words(plate, 'Zygomatic Ai', weak, strength=0.0)
    d_weak = float(np.abs(cv2.imread(weak).astype(np.float32) - p).mean(axis=2)[dil].mean())
    d_full = float(np.abs(e - p).mean(axis=2)[dil].mean())
    print(f'strength: 0.0 -> |diff| {d_weak:.2f}, 1.0 -> |diff| {d_full:.2f} (inside the dilated mask)')
    if not d_weak < 4:
        raise RuntimeError(f'strength 0 still marks the plate: {d_weak:.2f}')
    if not d_full > 4 * d_weak:
        raise RuntimeError(f'strength 1 is only {d_full:.2f} against {d_weak:.2f} at strength 0')

    # ---- the relief ramp: the letters RISE, and the grain shows ----------
    # At 40 % of the run the words are still almost flat, so anything visible
    # inside the mask is the grain and the sand haze -- that is the gap take 2
    # had (nothing at all until the letters simply appeared).  At the end the
    # frame must BE the strength-1.0 emboss, not a crossfade towards it.
    rmp = os.path.join(work, 'swirl_ramp.mp4')
    n_r = swirl_in(plate, words, rmp, fps=24, dur_s=1.5, hold_s=0.0, words_text='Zygomatic Ai', relief_ramp=True)
    fr = _read_frames(rmp)
    if not len(fr) == n_r == 36:
        raise RuntimeError(f'relief ramp wrote {len(fr)}/{n_r} frames')
    i40 = int(round(0.4 * (n_r - 1)))
    d40 = float(np.abs(fr[i40].astype(np.float32) - p).mean(axis=2)[dil].mean())
    d_end = float(np.abs(fr[-1].astype(np.float32) - e).mean())
    print(
        f'relief ramp: {len(fr)} frames  |diff| vs plate in the dilated mask '
        f'at 40 % (frame {i40}) {d40:.2f}  last vs the strength-1.0 words '
        f'frame {d_end:.2f}'
    )
    if not d40 >= 10:
        raise RuntimeError(f'nothing visible at 40 % of the reveal: {d40:.2f}')
    if not d_end < 4:
        raise RuntimeError(f'the reveal does not land on the words: {d_end:.2f}')

    print('SELFTEST OK')
    return 0


def _read_frames(mp4):
    cap = cv2.VideoCapture(mp4)
    out = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        out.append(fr)
    cap.release()
    return out


# ── receipt (GPU) ───────────────────────────────────────────────────────────
def _mp4_frames(path):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return n


def receipt(words='Zygomatic Ai', seeds=6, hold_s=1.0, log=None, first_seed=31683 + 7919, reuse=True) -> dict:
    """The GPU receipt. Re-judges whatever is already on disk before it spends
    a single GPU second: the plate is only rendered when it is missing, and the
    words only when the frame already written fails the gate."""
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    plate = os.path.join(RECEIPT_DIR, 'plate.png')
    wpng = os.path.join(RECEIPT_DIR, 'words.png')
    mp4 = os.path.join(RECEIPT_DIR, 'swirl.mp4')
    path = os.path.join(RECEIPT_DIR, 'receipt.json')
    pre = None
    if reuse and os.path.isfile(plate) and os.path.isfile(wpng):
        old = {}
        try:
            with open(path) as fh:
                old = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('receipt %s unreadable, reuse precheck has no seed: %s', path, _exc)
        pre = (old.get('seed'), wpng)
    else:
        render_plate(plate, seed=5, log=log)
    rec = write_words_in_sand(plate, words, wpng, seeds=seeds, log=log, first_seed=first_seed, precheck=pre)
    if rec.get('reused') and os.path.isfile(mp4):
        rec['swirl_frames'] = _mp4_frames(mp4)
        _log(log, f'swirl kept: the winning words.png did not change ({rec["swirl_frames"]} frames)')
    else:
        rec['swirl_frames'] = swirl_in(plate, wpng, mp4, hold_s=hold_s, log=log)
    rec['plate'] = plate
    rec['words'] = wpng
    rec['swirl'] = mp4
    with open(path, 'w') as fh:
        json.dump(rec, fh, indent=2)
    _log(log, f'receipt → {path}')
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--src')
    ap.add_argument('--words')
    ap.add_argument('--out')
    ap.add_argument('--seeds', type=int, default=6)
    ap.add_argument('--hold', type=float, default=0.0)
    ap.add_argument('--only-write', action='store_true')
    ap.add_argument('--only-swirl', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--receipt', action='store_true')
    ap.add_argument('--first-seed', type=int, default=None)
    ap.add_argument('--no-reuse', action='store_true', help='receipt: re-render instead of re-judging what is on disk')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.receipt:
        rec = receipt(
            words=a.words or 'Zygomatic Ai',
            seeds=a.seeds,
            hold_s=a.hold or 1.0,
            reuse=not a.no_reuse,
            **({'first_seed': a.first_seed} if a.first_seed else {}),
        )
        print(json.dumps(rec, indent=2))
        return 0 if rec.get('exact') else 1
    if not (a.src and a.words and a.out):
        ap.error('--src, --words and --out are required')
    if a.only_swirl:
        n = swirl_in(a.src, a.words, a.out, hold_s=a.hold)
        print(json.dumps({'swirl_frames': n, 'out': a.out}))
        return 0
    rec = write_words_in_sand(
        a.src, a.words, a.out, seeds=a.seeds, **({'first_seed': a.first_seed} if a.first_seed else {})
    )
    if not a.only_write:
        rec['swirl_frames'] = swirl_in(a.src, a.out, os.path.splitext(a.out)[0] + '.mp4', hold_s=a.hold)
    print(json.dumps(rec, indent=2))
    return 0 if rec.get('exact') else 1


if __name__ == '__main__':
    sys.exit(main())
