# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Labeled probe: can qwen3.5:9b (ollama, vision) flag OBVIOUS defects in
kids-music frames quickly, without flagging clean ones?

Positives = frames judged defective by eye on the CLIP ranking sheets
(output/kidsmusic/_frame_defect_bench/sheet_*.jpg). Negatives = the random
sheet's frames judged clean. Writes vlm_probe.json beside the sheets.
"""

import base64
import io
import json
import os
import random
import re
import time
from PIL import Image

from zyg_workflows import http_json
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


CREWS = str(paths.ZYG_CREWS_ROOT)
OUT = os.path.join(CREWS, 'output/kidsmusic/_frame_defect_bench')
CHAT_URL = paths.ZYG_OLLAMA_URL + '/api/chat'
MODEL = os.environ.get('PROBE_MODEL', 'qwen3.5:9b')
PX = int(os.environ.get('PROBE_PX', '640'))

POS = {  # job prefix/frame: what is wrong
    '988cc9/f033': 'rocking horse with two heads',
    '1da0a2/f021': 'frog and snail fused into one body',
    'a8b795/f009': 'horse with a doodle growing from its head, broken legs',
    '3f2b40/f028': 'rocking horse with a squirrel tail and odd head',
    'aee923/f017': 'red ball broken by a white blob',
    '0fc294/f017': 'garbled lettering "wlot" above the dog',
    '82b8bc/f031': 'bee with a brown beetle shell body',
    '5e42a3/f025': 'rocking horse missing a front leg',
    # Found by the VLM on the random "clean" set, confirmed by eye at full size:
    '6aea4e/f021': 'children fused into a yellow blob, ship split in two',
    '6aea4e/f014': 'floating pair of legs, headless shirt-and-shorts child',
    '19387e/f032': 'faceless ghost child silhouette',
}

PROMPT = (
    "This picture was generated for a children's picture-book video. It was meant to show: "
    '"{idea}".\nLook for OBVIOUS generation defects that a parent would notice at once: an animal '
    'or person with two heads, extra or missing legs, arms or eyes; two creatures fused into one '
    'body; a melted, broken or doubled face; body parts that do not belong to the creature; '
    'scrambled letters or words; an object broken into shapeless blobs.\nNOT defects: the simple '
    'flat cartoon style, faces drawn on objects or shapes, a character peeking out from behind '
    'something, empty backgrounds, a picture that shows the idea loosely.\n'
    'Reply with JSON only: {{"defect": true or false, "what": "<the defect in a few words, or empty>"}}'
)


def find(key):
    job, fr = key.split('/')
    d = next(x for x in os.listdir(os.path.join(CREWS, 'output/kidsmusic')) if x.startswith(job))
    p = os.path.join(CREWS, 'output/kidsmusic', d, 'frames', fr + '.png')
    sb = json.load(open(os.path.join(CREWS, 'output/kidsmusic', d, 'storyboard.json')))
    idea = next((s.get('idea') for s in sb['slots'] if s['i'] == int(fr[1:])), '')
    return p, idea


PROMPT2 = (
    'Look carefully at this cartoon picture. For EVERY animal, person or character in it, count what '
    'you actually see. Then list anything physically wrong with the drawing: a second head, extra or '
    'missing limbs, two creatures merged into one body, body parts from another animal, a broken or '
    'melted face, garbled letters or writing, an object broken into blobs.\n'
    'Reply with JSON only, no markdown: {"characters": [{"what": "...", "heads": N, "eyes": N, '
    '"legs": N, "arms": N}], "wrong": ["..."], "writing": "any letters or words you see, or empty"}'
)


_PLURAL = re.compile(r'(s|children|people|kids|group|family|crowd)\b', re.I)
_NEGATED = re.compile(
    r'^\s*(none|nothing|n/?a)\b|\b(is|are|does|do) not\b|\bnothing (is )?wrong\b|\bno (defects?|problems?|issues?)\b|\b(looks|appears) (normal|correct|fine)\b',
    re.I,
)


def verdict2(v):
    if not isinstance(v, dict):
        return None, 'unparsed'
    why = []
    for c in v.get('characters') or []:
        try:
            h = int(c.get('heads') or 0)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('non-numeric head count ignored: %s', _exc)
            continue
        # 'person: 5 heads' was five children in a train's windows — a count
        # over a group, not a five-headed person.
        if h in (2, 3) and not _PLURAL.search(str(c.get('what') or '')):
            why.append(f'{c.get("what")}: {h} heads')
    why += [w for w in (v.get('wrong') or []) if isinstance(w, str) and w.strip() and not _NEGATED.search(w)]
    if isinstance(v.get('writing'), str) and len([ch for ch in v['writing'] if ch.isalpha()]) >= 3:
        why.append(f'writing: {v["writing"][:30]}')
    return bool(why), '; '.join(why)


def ask(path, idea):
    if os.environ.get('PROBE_VARIANT') == '2':
        return ask2(path, idea)
    return ask1(path, idea)


def ask2(path, idea):
    with Image.open(path) as im:
        im = im.convert('RGB')
        im.thumbnail((PX, PX))
        b = io.BytesIO()
        im.save(b, 'JPEG', quality=88)
    body = {
        'model': MODEL,
        'stream': False,
        'think': False,
        'keep_alive': '10m',
        'options': {'temperature': 0, 'num_predict': 300},
        'messages': [{'role': 'user', 'content': PROMPT2, 'images': [base64.b64encode(b.getvalue()).decode()]}],
    }
    t0 = time.time()
    txt = http_json.post_json(CHAT_URL, body, timeout=180)['message']['content']
    try:
        v = json.loads(txt[txt.index('{') : txt.rindex('}') + 1])
    except ValueError:
        v = None
    d, why = verdict2(v)
    return {'defect': d, 'what': why, 'raw': v}, round(time.time() - t0, 2)


def ask1(path, idea):
    with Image.open(path) as im:
        im = im.convert('RGB')
        im.thumbnail((PX, PX))
        b = io.BytesIO()
        im.save(b, 'JPEG', quality=88)
    body = {
        'model': MODEL,
        'stream': False,
        'think': False,
        'format': 'json',
        'keep_alive': '10m',
        'options': {'temperature': 0, 'num_predict': 80},
        'messages': [
            {'role': 'user', 'content': PROMPT.format(idea=idea), 'images': [base64.b64encode(b.getvalue()).decode()]}
        ],
    }
    t0 = time.time()
    r = http_json.post_json(CHAT_URL, body, timeout=180)
    txt = r['message']['content']
    try:
        v = json.loads(txt)
    except ValueError:
        v = {'defect': None, 'what': txt[:80]}
    return v, round(time.time() - t0, 2)


def main():
    rows = json.load(open(os.path.join(OUT, 'scores.json')))
    rnd = random.Random(7).sample(rows, 36)
    neg = []
    for i, r in enumerate(rnd):
        key = f'{r["job"][:6]}/{os.path.basename(r["path"])[:-4]}'
        if i in (1, 12) or key in POS:  # 1 = peekaboo bush-face (ambiguous), 12 = frog-snail
            continue
        neg.append(key)
    extra = random.Random(11).sample(rows, 40)
    for r in extra:
        key = f'{r["job"][:6]}/{os.path.basename(r["path"])[:-4]}'
        if key not in POS and key not in neg and len(neg) < 50:
            neg.append(key)
    out = []
    ask(*find(neg[0]))  # warm the model; not scored
    for label, keys in (('defect', list(POS)), ('clean', neg)):
        for k in keys:
            p, idea = find(k)
            v, s = ask(p, idea)
            out.append({'key': k, 'label': label, 'idea': idea, 'vlm': v, 'seconds': s, 'truth': POS.get(k, '')})
            print(label, k, v, s, flush=True)
    tp = sum(1 for o in out if o['label'] == 'defect' and o['vlm'].get('defect') is True)
    fp = sum(1 for o in out if o['label'] == 'clean' and o['vlm'].get('defect') is True)
    npos = sum(1 for o in out if o['label'] == 'defect')
    nneg = len(out) - npos
    summ = {
        'model': MODEL,
        'px': PX,
        'hits': f'{tp}/{npos}',
        'false_alarms': f'{fp}/{nneg}',
        'median_s': sorted(o['seconds'] for o in out)[len(out) // 2],
    }
    print(summ)
    json.dump(
        {'summary': summ, 'rows': out},
        open(
            os.path.join(OUT, f'vlm_probe_v{os.environ.get("PROBE_VARIANT", "1")}_{MODEL.replace(":", "_")}_{PX}.json'),
            'w',
        ),
        indent=1,
    )


if __name__ == '__main__':
    main()
