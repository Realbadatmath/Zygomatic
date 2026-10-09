# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""The candidate pool and the VLM defect screen (2026-09-15).

Moved verbatim out of the old single-file kids_video_service.py (lines 2348-2624).
"""

from __future__ import annotations

import json
import os
import re
import time

from zyg_workflows.kids_video_service.constants import (
    CARTOON_MIN,
    _OLLAMA,
    _zyg_log,
)
from zyg_workflows.kids_video_service.gates import (
    CARTOON_NEG,
    CARTOON_POS,
    _clip,
    reads_text,
)


# ── Candidate pool + defect screen (2026-09-15) ─────────────────────────────
#
# Every generated slot is rendered CANDIDATES times (a song that needs 50
# pictures renders 100), each candidate is screened the moment it exists, a
# candidate with an obvious defect is thrown out on the spot, the healthiest
# survivor goes in the song and the other healthy ones are kept in
# frames/excess/. Counting cards are drawn, not generated, and are not doubled —
# a drawn card has no defects to choose between.
#
# THE SCREEN, AND WHAT IT WAS CALIBRATED ON (tools/kidsvideo_defect_bench.py,
# tools/kidsvideo_vlm_defect_probe.py, output/kidsmusic/_frame_defect_bench/):
#  * CLIP defect captions were tried first and REJECTED. Over 1,112 generated
#    frames the L14 "extra legs / malformed face" contrast ranked rocking horses
#    and plain frogs on top (rockers read as legs); B32 ranked every smiling
#    shape on top. ~3 real defects in its top 36 vs 1-2 in a random 36: a
#    content detector, not a defect detector.
#  * Pixel statistics: no blank, black or corrupt frame exists in 1,112, so
#    there was nothing to calibrate a threshold on — not used.
#  * qwen3.5:9b (vision, Apache-2.0, already this leg's idea model), asked to
#    DESCRIBE — per character heads/eyes/legs/arms, a list of what is wrong, any
#    writing — with the verdict made HERE by rule. Asked a yes/no question it
#    caught 0/8 (it called a two-headed horse "whimsical"). Describe-then-judge
#    at 640 px: 6/11 defects caught (two heads, headless legs, faceless child,
#    children fused into a blob, object broken into blobs, garbled lettering),
#    0/50 false alarms, 0.84 s median. 896 px was worse (2/11, 2/50). Misses:
#    subtler anatomy (a frog fused into a snail, odd tails, a missing rocker
#    leg). So this throws out OBVIOUS defects, which is what it claims; it is
#    not a complete anatomy check. Three of the 11 defects were found BY the
#    model on frames judged clean by eye at thumbnail size.
CANDIDATES = max(1, int(os.environ.get('ZYG_KIDSVIDEO_CANDIDATES', '2')))
SCREEN_ON = os.environ.get('ZYG_KIDSVIDEO_SCREEN', '1').strip().lower() not in ('0', 'false', 'no', 'off')
SCREEN_LLM = os.environ.get('ZYG_KIDSVIDEO_SCREEN_LLM', 'qwen3.5:9b')
SCREEN_PX = int(os.environ.get('ZYG_KIDSVIDEO_SCREEN_PX', '640'))
SCREEN_CALIBRATION = (
    'qwen3.5:9b describe-then-judge @640 px: 6/11 defects caught, '
    '0/50 false alarms, 0.84 s median (output/kidsmusic/_frame_defect_bench)'
)
_SCREEN_PROMPT = (
    'Look carefully at this cartoon picture. For EVERY animal, person or character in it, count '
    'what you actually see. Then list anything physically wrong with the drawing: a second head, '
    'extra or missing limbs, two creatures merged into one body, body parts from another animal, '
    'a broken or melted face, garbled letters or writing, an object broken into blobs.\n'
    'Reply with JSON only, no markdown: {"characters": [{"what": "...", "heads": N, "eyes": N, '
    '"legs": N, "arms": N}], "wrong": ["..."], "writing": "any letters or words you see, or empty"}'
)
# 'person: 5 heads' was five children in a train's windows — a count over a group.
_PLURAL_RE = re.compile(r'(s|children|people|kids|group|family|crowd)\b', re.I)
# A 'wrong' entry that says nothing is wrong ("...but it is not an animal").
# Deliberately NOT a bare "no": "small child has no eyes" is a real hit.
_NEGATED_RE = re.compile(
    r'^\s*(none|nothing|n/?a)\b|\b(is|are|does|do) not\b|\bnothing (is )?wrong\b|'
    r'\bno (defects?|problems?|issues?|animals?|people|persons?|characters?|creatures?)\b|\b(looks|appears) (normal|correct|fine)\b',
    re.I,
)
# Live false alarms on a tractor song (job 7a9514bf0b42) that a PROMPT could not
# fix — telling the model what is "normal" cut calibration hits 6/11 → 2/11 — so
# they are filtered here: a character partly hidden behind something (the
# peekaboo motif asks for exactly that), and eyes/a face on a vehicle or object
# (these cartoons draw faces on tractors, trains and suns on purpose).
_COMPOSITION_RE = re.compile(
    r'\b(partially|partly|half)\s+(hidden|covered|obscured)\b|'
    r'\bhid(den|ing)\s+behind\b|\bpeek',
    re.I,
)
_FACED_OBJECT_RE = re.compile(
    r'\b(tractor|train|engine|car|truck|bus|boat|ship|plane|rocket|vehicle|digger|sun|moon|star|'
    r'cloud|house|ball|drum|block|flower|tree|shape|circle|square|triangle|heart)\b[^.;]*\b(eyes?|face|mouth|smile)\b',
    re.I,
)
# ONE OF A PAIR. "has (only) one eye" was a false alarm every time it came up — a
# bee (calibration), a tractor and a duck (live) — and patching that phrase alone
# was too narrow: the very next song rejected a healthy rabbit running in profile
# for "missing arm" (c29fcac02d69 f016). The class is the view, not the word: a
# side view hides one of every pair. So a claim that ONE of a paired part is
# missing or that only one is present is SOFT — it ranks the candidate below a
# clean twin but never throws it out — while a count of ZERO ("no eyes", "no
# legs") and an EXTRA ("three legs", "second head") stay hard. Measured on the
# 11/50 bench: hits and false alarms unchanged (6/11, 0/50); on 23 live receipts
# the only demotion is the rabbit. No real hit of this class is on record.
# NOT done: asking the describer which way each character faces ("view":
# front/side/back) so a side view could be dropped and a front view kept hard.
# Measured 2026-09-16: that one extra field cut bench recall 6/11 -> 2/11 (the
# "normal" clause did the same), and in a crowd the field alternated
# side/front/side/front down the list — a fill pattern, not an observation.
_PAIRED_PART = r'(eye|ear|arm|hand|leg|foot|wing|horn|antenna|paw|hoof|cheek|eyebrow|nostril)'
_PART_QUAL = (
    r'(?:a |an |its |his |her |their |the |one |left |right |front |back |hind |fore |'
    r'rear |upper |lower |visible )*'
)
# "one eye", "only one leg", "a single wing", "1 arm"
_ONE_OF_PAIR_RE = re.compile(r'\b(?:only|just)?\s*(?:one|1|a single)\s+' + _PART_QUAL + _PAIRED_PART + r'\b(?!s)', re.I)
# "missing arm", "missing a front leg", "has no left eye", "lacks an ear", "without a wing"
_MISSING_ONE_RE = re.compile(
    r'\b(?:missing|lacks|lacking|without|has no|no|lost|absent)\s+' + _PART_QUAL + _PAIRED_PART + r'\b(?!s)', re.I
)
# "one of its legs is missing", "left arm missing", "front leg not visible"
_ONE_MISSING_RE = re.compile(
    r'\b(?:one of (?:its|his|her|their|the) '
    + _PAIRED_PART
    + r's|(?:left|right|front|back|hind|one) '
    + _PAIRED_PART
    + r')\b[^.;,]*\b(?:missing|absent|gone|not (?:visible|drawn|present))',
    re.I,
)


def is_one_of_pair_claim(text):
    """True when a 'wrong' entry says one of a paired body part is missing or
    only one is present — what a side view shows of every healthy character."""
    return bool(_ONE_OF_PAIR_RE.search(text) or _MISSING_ONE_RE.search(text) or _ONE_MISSING_RE.search(text))


_SCREEN_RANK = {'healthy': 0, 'unmeasured': 1, 'soft': 2, 'defect': 9}
_VLM_FAILS = {'n': 0}


def vlm_defects(path, timeout=60):
    """(reasons, raw) from the describe-then-judge VLM look, or (None, error)
    when it could not run. Reasons empty = nothing obvious seen."""
    import base64
    import io
    import urllib.request as _ur
    from PIL import Image

    try:
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail((SCREEN_PX, SCREEN_PX))
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=88)
        body = {
            'model': SCREEN_LLM,
            'stream': False,
            'think': False,
            'keep_alive': '5m',
            # 900, not 300: on the duck song (f9c4f3e17c20) every crowded scene —
            # a tree full of birds, a circle of ducklings — ran out at 300 tokens
            # mid-JSON (done_reason=length) and 5/98 candidates went unscreened.
            'options': {'temperature': 0, 'num_predict': 900},
            'messages': [
                {'role': 'user', 'content': _SCREEN_PROMPT, 'images': [base64.b64encode(buf.getvalue()).decode()]}
            ],
        }
        # safe_urlopen takes a bare URL and this POST needs headers, so the same
        # scheme check is applied to the composed Request instead.
        req = _ur.Request(  # noqa: S310  scheme checked on the next line
            f'{_OLLAMA}/api/chat', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}
        )
        if req.type not in ('http', 'https'):
            raise ValueError(f'refusing to open a {req.type!r} URL: {_OLLAMA!r}')
        with _ur.urlopen(req, timeout=timeout) as r:  # noqa: S310  scheme validated above  # nosec B310
            txt = json.loads(r.read().decode('utf-8'))['message']['content']
        v = json.loads(txt[txt.index('{') : txt.rindex('}') + 1])
    except Exception as e:  # noqa: BLE001
        return None, f'{type(e).__name__}: {e}'[:120]
    if not isinstance(v, dict):
        return None, 'unparsed reply'
    return judge_description(v), v


def judge(v):
    """The rule half of the screen: (hard, soft) reasons for a described frame.

    hard — the frame is thrown out: a 2-3 head count on one character, a
    'wrong' entry the filters above do not explain, lettering the model read.
    soft — ranks the candidate below a clean twin, never rejects: a claim that
    ONE of a paired part is missing / only one shows (see is_one_of_pair_claim)."""
    hard, soft = [], []
    for ch in v.get('characters') or []:
        if not isinstance(ch, dict):
            continue
        try:
            h = int(ch.get('heads') or 0)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('head count not numeric, claim ignored: %s', _exc)
            continue
        if h in (2, 3) and not _PLURAL_RE.search(str(ch.get('what') or '')):
            hard.append(f'{ch.get("what")}: {h} heads')
    for w in v.get('wrong') or []:
        if not isinstance(w, str) or not w.strip():
            continue
        w = w.strip()[:80]
        if _NEGATED_RE.search(w) or _COMPOSITION_RE.search(w) or _FACED_OBJECT_RE.search(w):
            continue
        if is_one_of_pair_claim(w):
            soft.append(f'{w} (one of a pair — a side view hides one)')
        else:
            hard.append(w)
    wr = v.get('writing')
    if isinstance(wr, str) and sum(1 for c in wr if c.isalpha()) >= 3:
        hard.append(f'writing: {wr.strip()[:30]}')
    return hard, soft


def judge_description(v):
    """The hard reasons only — what throws a frame out."""
    return judge(v)[0]


def describe_compact(v):
    """What the model actually said, kept with the candidate so an audit can
    tell 'right call, wrong reason' from a miss without re-asking the model."""
    chars = []
    for ch in (v.get('characters') or [])[:8]:
        if isinstance(ch, dict):
            chars.append(
                {k: ch.get(k) for k in ('what', 'view', 'heads', 'eyes', 'legs', 'arms') if ch.get(k) not in (None, '')}
            )
    return {'characters': chars, 'wrong': [str(w)[:80] for w in (v.get('wrong') or []) if isinstance(w, str)][:8]}


def screen_frame(path):
    """Quick defect screen of one rendered candidate.

    verdict: 'defect' (VLM saw an obvious defect, or OCR read lettering) — thrown
    out; 'soft' (only below the cartoon contrast) — used if nothing better;
    'unmeasured' (the VLM could not run) — never counted as healthy or as a
    defect; 'healthy'."""
    t0 = time.time()
    rec = {'verdict': 'healthy', 'reasons': [], 'soft': [], 'cartoon': None, 'vlm': 'ran', 'described': None}
    if _VLM_FAILS['n'] < 3:
        why, raw = vlm_defects(path)
        if why is None:
            _VLM_FAILS['n'] += 1
            rec['vlm'] = f'unmeasured ({raw})'
        else:
            _VLM_FAILS['n'] = 0
            rec['reasons'] += why
            if isinstance(raw, dict):
                rec['soft'] += judge(raw)[1]
                rec['described'] = describe_compact(raw)
    else:
        rec['vlm'] = 'unmeasured (VLM failed 3 times in a row — not asked again this run)'
    # OCR lettering alone is SOFT: on the tractor song it read grass as "M\\L>LM"
    # and a face in a cab as "Ano", while the one real case ("Hello" in a speech
    # bubble) was read by the VLM too. Hard only when both agree, or the VLM
    # could not look.
    lettering = reads_text(path)
    if lettering:
        txt = f'lettering: {lettering[0]["text"][:24]}'
        vlm_writing = any(r.startswith('writing:') for r in rec['reasons'])
        if vlm_writing or rec['vlm'] != 'ran':
            rec['reasons'].append(txt)
        else:
            rec['soft'].append(txt + ' (OCR only)')
    contrast = _clip()
    if contrast is not None:
        try:
            rec['cartoon'] = round(contrast(path, CARTOON_POS, CARTOON_NEG), 4)
        except Exception:  # noqa: BLE001
            rec['cartoon'] = None
    if rec['cartoon'] is not None and rec['cartoon'] < CARTOON_MIN:
        rec['soft'].append(f'cartoon {rec["cartoon"]:.2f} < {CARTOON_MIN}')
    if rec['reasons']:
        rec['verdict'] = 'defect'
    elif rec['soft']:
        rec['verdict'] = 'soft'
    elif rec['vlm'] != 'ran':
        rec['verdict'] = 'unmeasured'
    rec['seconds'] = round(time.time() - t0, 2)
    return rec


def _reject_thumb(path, dst):
    """A full-size JPEG receipt of a thrown-out candidate (the PNG is deleted).
    Full size, because the first live audit had only 320 px receipts and could
    not re-screen them at the calibrated 640 px."""
    try:
        from PIL import Image

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with Image.open(path) as im:
            im.convert('RGB').save(dst, quality=88)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('reject receipt %s not written, the thrown-out candidate leaves no audit trail: %s', dst, _exc)
