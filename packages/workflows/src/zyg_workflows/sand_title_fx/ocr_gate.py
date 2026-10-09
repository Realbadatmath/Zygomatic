# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The OCR gate: PP-OCR reader, the local Qwen3-VL judge, and the two-reader verdict —
verbatim sections of the former sand_title_fx.py."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

import cv2
import numpy as np
from zyg_workflows.bin import exe
import logging as _zyg_logging
from zyg_workflows.sand_title_fx.constants import (
    CROP_PAD_FRAC,
    CROP_UPSCALE,
    _log,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sand_title_fx')


# ── OCR gate ────────────────────────────────────────────────────────────────
def normalise(text: str) -> str:
    """lowercase, punctuation stripped, whitespace collapsed."""
    t = re.sub(r'[^0-9a-z ]+', ' ', str(text or '').lower())
    return ' '.join(t.split())


def read_words(image_path: str) -> tuple[str, float]:
    """What the OCR engine reads in this frame, in reading order.

    Returns ``(text, conf)`` — ``('', 0.0)`` when nothing is read, and raises
    when the engine itself is unavailable, because an unavailable judge must
    never be mistaken for a clean pass."""
    from zyg_workflows import typography_ocr as tocr

    regs = tocr.read_lettering(image_path)
    if regs is None:
        raise RuntimeError(
            'typography_ocr engine unavailable — cannot gate the lettering (install rapidocr-onnxruntime)'
        )
    if not regs:
        return '', 0.0
    # bbox is 0-1000 normalised; group into lines ~6 % of the height apart.
    regs = sorted(regs, key=lambda r: (int(r['bbox'][1] / 60), r['bbox'][0]))
    text = ' '.join(r['text'] for r in regs)
    conf = min(float(r['conf']) for r in regs)
    return text, conf


def _regions(image_path):
    from zyg_workflows import typography_ocr as tocr

    regs = tocr.read_lettering(image_path)
    if regs is None:
        raise RuntimeError(
            'typography_ocr engine unavailable — cannot gate the lettering (install rapidocr-onnxruntime)'
        )
    return regs


def lettering_crop(image_path, out_png, mask=None):
    """The lettering, cropped out, doubled and contrast-equalised.

    PP-OCR reads the whole frame at a fixed input size, so a word that fills a
    quarter of a 1280x720 plate reaches the recogniser smaller than it looks.
    The crop is the union bbox of everything the detector found (or, when it
    found nothing at all, the bbox of the letter mask), padded 8 %, upscaled 2x
    LANCZOS and CLAHE-equalised on luma only — chroma is left alone so sand
    stays sand. Returns the path, or None when there is nothing to crop."""
    arr = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if arr is None:
        raise FileNotFoundError(image_path)
    H, W = arr.shape[:2]
    box = None
    regs = _regions(image_path)
    if regs:
        xs = [r['bbox'][0] for r in regs] + [r['bbox'][2] for r in regs]
        ys = [r['bbox'][1] for r in regs] + [r['bbox'][3] for r in regs]
        box = (min(xs) / 1000.0 * W, min(ys) / 1000.0 * H, max(xs) / 1000.0 * W, max(ys) / 1000.0 * H)
    elif mask is not None and mask.any():
        my, mx = np.nonzero(mask)
        box = (float(mx.min()), float(my.min()), float(mx.max()), float(my.max()))
    if box is None:
        return None
    x0, y0, x1, y1 = box
    px, py = CROP_PAD_FRAC * (x1 - x0), CROP_PAD_FRAC * (y1 - y0)
    x0, y0 = int(max(0, x0 - px)), int(max(0, y0 - py))
    x1, y1 = int(min(W, x1 + px)), int(min(H, y1 + py))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = cv2.resize(arr[y0:y1, x0:x1], None, fx=CROP_UPSCALE, fy=CROP_UPSCALE, interpolation=cv2.INTER_LANCZOS4)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    lch, ach, bch = cv2.split(lab)
    lch = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lch)
    crop = cv2.cvtColor(cv2.merge((lch, ach, bch)), cv2.COLOR_LAB2BGR)
    cv2.imwrite(out_png, crop)
    return out_png


def _prefix_gap(got, want):
    """Trailing characters of `want` that `got` is missing, or None.

    None whenever `got` is not a prefix of `want` at all — a wrong letter is
    not a short read, and must never be treated as one."""
    if got and want.startswith(got):
        return len(want) - len(got)
    return None


# ── reader B: the local Qwen3-VL judge ──────────────────────────────────────
#
# Asked for ANY visible lettering, and to QUOTE it. Never whether the words are
# 'legible' or 'prominent': that phrasing is measured at 0/6 recall on this
# project's frames, because the judge talks itself out of every positive.
VLM_PREAMBLE = (
    'This is a photograph of a desert floor. Words have been '
    'written in the sand. Answer only about what is ACTUALLY '
    'VISIBLE in this image.'
)
VLM_QUESTION = (
    'Does this image contain any visible lettering, writing or '
    'characters anywhere? Answer yes or no. Then, on the same '
    'line, QUOTE the lettering exactly as it is written, inside '
    'double quotes, letter by letter: copy every character you can '
    'see, keep lowercase letters lowercase, keep any dots, and do '
    'not correct, complete, translate or re-capitalise it.'
)
VLM_MIN_FREE_MIB = 12000.0
_QUOTE_RE = re.compile(r'["\u201c\u2018]([^"\u201d\u2019\n]{1,80})["\u201d\u2019]')


def _gpu_free_mib() -> float:
    try:
        r = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(re.findall(r'[\d.]+', r.stdout.strip().splitlines()[0])[0])
    except Exception:  # noqa: BLE001
        return 0.0


def _quotes(text):
    return [q.strip() for q in _QUOTE_RE.findall(str(text or '')) if q.strip()]


def vlm_read_lettering(image_path, log=None):
    """What the local Qwen3-VL judge says it can read. '' when it cannot run.

    Returns the quoted string; the empty string both when the judge is
    unavailable and when it quotes nothing, because neither is a pass on its
    own — the caller only ever uses this to confirm a read PP-OCR already
    almost made."""
    try:
        from zyg_workflows import vlm_inspector as vi
    except Exception as e:  # noqa: BLE001
        _log(log, f'vlm judge unimportable ({e})')
        return ''
    if not vi.available():
        _log(log, 'vlm judge unavailable (venv/worker missing or ZYG_VLM=0)')
        return ''
    free = _gpu_free_mib()
    tier, offload = ('resident', False) if free >= VLM_MIN_FREE_MIB else ('boundary', True)
    _log(log, f'vlm judge: {free:.0f} MiB free → tier={tier} offload={offload}')
    res = vi.inspect_frames(
        [image_path],
        items=[
            {'id': 'quote_lettering', 'question': VLM_QUESTION, 'expected': 'yes', 'severity': 'major', 'frames': 'all'}
        ],
        preamble=VLM_PREAMBLE,
        tier=tier,
        offload=offload,
        frame_kind='all',
        log_fn=lambda m: _log(log, str(m)[:200]),
    )
    if not res or res.get('skipped'):
        _log(log, f'vlm judge skipped ({(res or {}).get("reason")})')
        return ''
    v = (res.get('verdicts') or [None])[0] or {}
    reason = str(v.get('reason') or '')
    _log(log, f'vlm judge: answer={v.get("answer")} reason={reason[:160]!r}')
    if str(v.get('answer') or '').lower() != 'yes':
        return ''
    return reason


def vlm_confirms(image_path, want, log=None) -> tuple[bool, str]:
    """(confirmed, quote). The judge must QUOTE the words, not agree with them.

    A quoted span that normalises to the words is the only positive. When the
    reply carries no quotation marks at all the whole sentence is normalised
    and searched — but only then, so that a judge writing `it does not say
    "Zygomatic Ai"` can never be read as a confirmation."""
    reason = vlm_read_lettering(image_path, log=log)
    if not reason:
        return False, ''
    qs = _quotes(reason)
    for q in qs:
        if normalise(q) == want:
            return True, q
    if qs:
        return False, qs[0]
    flat = normalise(reason)
    if want in flat:
        return True, reason.strip()[:80]
    return False, reason.strip()[:80]


# ── the gate: two readers, exact wins either way ────────────────────────────
def judge_lettering(image_path, words, mask=None, log=None) -> dict:
    """Is this frame *exactly* the words asked for?

    Reader A is PP-OCR, twice: the whole frame, and the lettering cropped out
    and equalised. Either reading equal to the words is an exact pass on its
    own. Reader B (the local Qwen3-VL judge) is consulted ONLY when Reader A
    came back with a prefix of the words missing at most one trailing
    character — the one failure mode this path has, a thin final lowercase
    letter the recogniser drops — and only to quote what is written. A missing
    letter alone never passes: something must read the letter."""
    want = normalise(words)
    full_raw, conf = read_words(image_path)
    crop_raw = ''
    tmp = os.path.join(tempfile.mkdtemp(prefix='sandcrop_'), 'crop.png')
    try:
        if lettering_crop(image_path, tmp, mask=mask):
            crop_raw, _ = read_words(tmp)
    except Exception as e:  # noqa: BLE001
        _log(log, f'crop read failed ({e})')
    reads = {'ocr_full': full_raw, 'ocr_crop': crop_raw}
    exact_a = next((k for k, v in reads.items() if normalise(v) == want), None)
    gaps = [g for g in (_prefix_gap(normalise(v), want) for v in reads.values()) if g is not None]
    near = bool(gaps) and min(gaps) <= 1
    out = {
        'ocr_full': full_raw,
        'ocr_crop': crop_raw,
        'conf': round(conf, 3),
        'vlm_quote': None,
        'exact': False,
        'by': None,
    }
    if exact_a:
        out.update(exact=True, by=exact_a)
        _log(log, f'gate: EXACT by {exact_a} ({reads[exact_a]!r})')
        return out
    if not near:
        _log(log, f'gate: no ({full_raw!r} / {crop_raw!r}) — not even a prefix of {words!r}')
        return out
    ok, quote = vlm_confirms(image_path, want, log=log)
    out['vlm_quote'] = quote
    if ok:
        out.update(exact=True, by='vlm')
        _log(log, f'gate: EXACT by the vlm judge ({quote!r}) confirming {full_raw!r}')
    else:
        _log(log, f'gate: no — ocr {full_raw!r}/{crop_raw!r}, vlm quotes {quote!r}')
    return out
