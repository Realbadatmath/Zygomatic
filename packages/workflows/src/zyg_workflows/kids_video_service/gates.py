# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""The lettering reading and the CLIP cartoon/joy gates.

Moved verbatim out of the old single-file kids_video_service.py (lines 2035-2062, 3133-3332).
"""

from __future__ import annotations

import os
import re

from zyg_workflows.kids_video_service.constants import (
    CARTOON_MIN,
    JOY_MIN,
    OCR_MIN_AREA,
    _log_noop,
    _zyg_log,
)


# Words that invite a caption.  A picture prompt that says the subject "says" or
# "sings" something is asking for a speech bubble with writing in it, and the
# negative prompt loses that argument — measured, twice in fifty-three frames.
_CAPTION_BAIT = re.compile(
    r'\b(says?|saying|sings?|singing|shouts?|calls? out|reads?|reading|writes?|'
    r'writing|sign|signs|banner|poster|label|title|word|words|message|note)\b',
    re.I,
)
_NO_TEXT = (
    'no text anywhere in the picture, no writing, no letters, no words, no sign, no banner, no speech bubble, no title'
)


def reads_text(path):
    """The lettering readings of one frame that survive `_looks_like_lettering`.

    Returns [] when the engine is unavailable — a check that cannot run must not
    make a frame look guilty.
    """
    try:
        from zyg_workflows import typography_ocr as TO

        if not TO.available():
            return []
        regs = TO.read_lettering(path, min_area_frac=OCR_MIN_AREA) or []
        return [r for r in regs if _looks_like_lettering(r['text'], r['conf'])]
    except Exception:  # noqa: BLE001
        return []


# ── Gates ────────────────────────────────────────────────────────────────────

# 'model' is held alongside the closure so `release_clip` can move it off the
# GPU when the frames have been scored; 'device' is read INSIDE the closure so a
# released model comes back on the next call rather than silently scoring on the
# CPU forever (or, worse, mixing a CPU model with CUDA tensors).
_CLIP = {'m': None, 'err': '', 'model': None, 'device': 'cpu'}

CARTOON_POS = [
    'a flat cartoon illustration for children',
    "a children's picture book drawing",
    'a simple colourful cartoon drawing',
]
CARTOON_NEG = ['a photograph', 'a photorealistic image of a real scene', 'a realistic 3d rendered image']
JOY_POS = ['a happy cheerful joyful scene', 'a bright playful friendly picture']
JOY_NEG = ['a sad gloomy picture', 'a scary dark frightening picture']


def _clip():
    """open_clip ViT-B-32 (MIT code, openai weights already cached on this box),
    returning a contrast function rather than a bare similarity.

    A raw image-text similarity has no scale: 0.31 means nothing on its own. A
    softmax ACROSS competing captions does — it answers "which of these does the
    picture look more like", which is the actual question.
    """
    if _CLIP['m'] is not None or _CLIP['err']:
        return _CLIP['m']
    try:
        import open_clip
        import torch
        from PIL import Image

        model, _, pre = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
        tok = open_clip.get_tokenizer('ViT-B-32')
        model.eval()
        _CLIP['model'] = model
        _CLIP['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
        model.to(_CLIP['device'])

        def contrast(path, pos, neg):
            want = 'cuda' if torch.cuda.is_available() else 'cpu'
            if _CLIP['device'] != want:  # released between songs — bring it back
                model.to(want)
                _CLIP['device'] = want
            dev = _CLIP['device']
            # `with`, because this runs twice per frame over fifty-odd frames and
            # a bare Image.open leaves the handle to the garbage collector.
            with Image.open(path) as _img:
                im = pre(_img.convert('RGB')).unsqueeze(0).to(dev)
            t = tok(list(pos) + list(neg)).to(dev)
            with torch.no_grad():
                i = model.encode_image(im)
                x = model.encode_text(t)
                i = i / i.norm(dim=-1, keepdim=True)
                x = x / x.norm(dim=-1, keepdim=True)
                p = (100.0 * i @ x.T).softmax(dim=-1).squeeze().tolist()
            return float(sum(p[: len(pos)]))

        _CLIP['m'] = contrast
    except Exception as e:  # noqa: BLE001
        _CLIP['err'] = f'{type(e).__name__}: {e}'
    return _CLIP['m']


_LETTERS_RE = re.compile(r'[A-Za-z]')
# The glyphs a WHEEL can impersonate. A reading made only of these is a circle,
# not a word: measured on 100 real frames, 'OOO' and 'GCGG' were coupling rods
# and driving wheels, while every genuine lettering artefact carried letters
# with strokes in them ('YOU ALLC ELL', 'Ulreo Soglnea Yoy Flog').
_ROUND_GLYPHS = set('OoQqCcGgDdUu0')


def _looks_like_lettering(txt, conf):
    """Is this OCR reading actually LETTERING, or is it a wheel?

    RapidOCR is a document reader and these are flat cartoon line drawings.  On
    the first illustrated song it flagged 21 of 47 frames, and every single one
    was false: train wheels read as ``8`` and ``00@0``, a farmhouse's four
    windows as ``田田日``, a coupling rod as ``0``.  One "reading" covered 20 % of
    the frame.  A warning that is wrong on 45 % of frames is not a gate, it is
    noise that teaches people to ignore the panel.

    So a reading counts as lettering only if it looks like written words: at
    least three latin letters, letters making up at least half of it, and the
    engine at least 60 % confident.  Validated both ways — against all 47 frames
    of that song (every one of the 21 false readings is rejected) and against a
    positive control with real words drawn into it (still caught).  Circles and
    rectangles produce digits and CJK lookalikes; they do not produce letters.
    """
    t = (txt or '').strip()
    if len(t) < 3 or float(conf or 0.0) < 0.60:
        return False
    letters = _LETTERS_RE.findall(t)
    if len(letters) < 3 or len(letters) < 0.5 * len(t):
        return False
    # All-round reading => a wheel, not a word.
    return not all(c in _ROUND_GLYPHS for c in letters)


def gate_frames(paths, log_fn=None):
    """Measure every frame: cartoon-not-photo, joyful-not-gloomy, and lettering.

    ``ok`` is None, never False, when a measurement could not run — 'did not
    look' and 'looked and refused' are different verdicts and this workflow has
    already been bitten once by conflating them.
    """
    log_fn = log_fn or _log_noop
    g = {'checks': {}, 'warnings': [], 'fails': [], 'ok': None}
    real = [p for p in paths if p and os.path.isfile(p)]
    g['checks']['frames'] = len(real)
    if not real:
        g['fails'].append('no frames on disk')
        g['ok'] = False
        return g

    contrast = _clip()
    if contrast is None:
        g['checks']['cartoon'] = {'ok': None, 'ran': False, 'reason': _CLIP['err']}
        g['warnings'].append(f'CLIP unavailable ({_CLIP["err"]}) — the cartoon and joy gates did not run')
    else:
        cart, joy = [], []
        for p in real:
            try:
                cart.append(contrast(p, CARTOON_POS, CARTOON_NEG))
                joy.append(contrast(p, JOY_POS, JOY_NEG))
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('CLIP contrast scoring of %s skipped, the gate sample shrinks: %s', p, _exc)
                continue
        if cart:
            bad = [i for i, v in enumerate(cart) if v < CARTOON_MIN]
            g['checks']['cartoon'] = {
                'ok': not bad,
                'ran': True,
                'threshold': CARTOON_MIN,
                'mean': round(sum(cart) / len(cart), 4),
                'min': round(min(cart), 4),
                'below': len(bad),
                'scores': [round(v, 4) for v in cart],
                # The null this threshold sits against, recorded WITH the
                # verdict so nobody has to take 0.75 on trust.
                'null': 'photoreal stills on this box measured 0.0007-0.34',
            }
            if bad:
                g['fails'].append(
                    f'{len(bad)} frame(s) below the cartoon threshold ({CARTOON_MIN}); worst {min(cart):.3f}'
                )
            jbad = [i for i, v in enumerate(joy) if v < JOY_MIN]
            g['checks']['joy'] = {
                'ok': not jbad,
                'ran': True,
                'threshold': JOY_MIN,
                'mean': round(sum(joy) / len(joy), 4),
                'min': round(min(joy), 4),
                'below': len(jbad),
            }
            if jbad:
                g['warnings'].append(f'{len(jbad)} frame(s) below the joy threshold ({JOY_MIN}); worst {min(joy):.3f}')
            log_fn(
                f'frames: cartoon {sum(cart) / len(cart):.3f} mean / '
                f'{min(cart):.3f} worst (threshold {CARTOON_MIN}), '
                f'joy {sum(joy) / len(joy):.3f} mean'
            )

    try:
        from zyg_workflows import typography_ocr as TO

        if TO.available():
            lettered, rejected = [], 0
            for p in real:
                regs = TO.read_lettering(p, min_area_frac=OCR_MIN_AREA) or []
                keep = reads_text(p)
                rejected += len(regs) - len(keep)
                if keep:
                    lettered.append((os.path.basename(p), keep[0]['text'][:24], keep[0]['area_frac']))
            g['checks']['lettering'] = {
                'ok': not lettered,
                'ran': True,
                'min_area_frac': OCR_MIN_AREA,
                'frames_with_text': len(lettered),
                'shape_reads_rejected': rejected,
                'rule': ('>=3 latin letters, >=50% of the reading, conf >=0.60 — see _looks_like_lettering'),
                'examples': [{'frame': a, 'reads': b, 'area_frac': c} for a, b, c in lettered[:5]],
            }
            if lettered:
                g['warnings'].append(
                    f'{len(lettered)} frame(s) carry readable lettering — a picture video for children should have none'
                )
        else:
            g['checks']['lettering'] = {'ok': None, 'ran': False, 'reason': 'OCR engine unavailable'}
    except Exception as e:  # noqa: BLE001
        g['checks']['lettering'] = {'ok': None, 'ran': False, 'reason': f'{type(e).__name__}'}

    # The verdict is the cartoon gate. Joy and lettering are warnings: a slightly
    # solemn frame or a stray squiggle is not a reason to withhold a video.
    c = g['checks'].get('cartoon') or {}
    g['ok'] = None if c.get('ok') is None else bool(c.get('ok'))
    return g
