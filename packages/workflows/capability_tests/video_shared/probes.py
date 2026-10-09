# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The probe factory and the 132 subject probes."""

from __future__ import annotations

from .settings import (
    COND_CLIP,
    NEGATIVE,
    SAMPLE5,
    STATE_3OF3,
)
from .subjects import SUBJECTS


# ── the probe factory ──────────────────────────────────────────────────────────────────
def _probe(pid, title, feeds, inputs, checks, cond=None, **kw):
    """One probe. `inputs` is verbatim and `conditions` is fixed; a runner may not paraphrase
    either. Every check carries `for`, naming which of the fed columns it scores."""
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': inputs,
        'conditions': dict(cond or COND_CLIP),
        'checks': checks,
        'grade': 'measured',
    }
    p.update(kw)
    return p


SUBJ_NOTE = (
    'ONE clip per seed answers BOTH columns, read differently. render_<id> is read at frame 0 and '
    'the LAST frame only — is the thing there, and is it right. move_<id> is read ACROSS the clip — '
    'does it stay itself while it moves. A check\'s `for` says which column it scores ("both" scores '
    'each). A column is yes only when every check marked for it (or both) passed at that seed, and '
    "the column's state is yes at 3/3 seeds, partial at 2/3, no below. The OPERATOR check decides "
    'defects: our own defect-judge bench (2026-09-27) scored 34/40 on "is anything wrong with this "'
    'but 2/8 on fused fingers, extra digits and a second feather, so no local VLM is allowed to '
    'answer these columns. The mechanical checks decide the things a detector really can settle '
    '(identity drift, person/animal count, hand landmarks, the OCR string, whether the clip moved '
    'at all and whether it boiled). Where both exist BOTH must pass.'
)

OP_RENDER = (
    'Frame 0 and the last frame of this clip are shown side by side. Is {label} present and '
    'correct in BOTH — nothing melted, no missing or extra limb, finger, leg, wheel or wing, '
    'no second copy of it, no part fused into another? yes/no'
)
OP_MOVE = (
    'Across the whole clip, does {label} stay one whole thing and move plausibly — no melting, '
    'no morphing into something else, no extra limbs appearing, no part detaching or '
    'duplicating, no sliding feet? yes/no'
)


def _subject_probe(sid, label, prompt, motion, mech):
    tags = [t for t in mech.split(',') if t]
    checks = [
        {'check': 'frames_exact', 'frames': 81, 'for': 'both'},
        {'check': 'operator', 'question': OP_RENDER.format(label=label), 'for': 'render'},
        {'check': 'operator', 'question': OP_MOVE.format(label=label), 'for': 'move'},
        {
            'check': 'flicker_max',
            'max': 30.0 if 'hi' in tags else 12.0,
            'for': 'move',
            'note': 'a legitimately high-motion subject gets the 30.0 ceiling' if 'hi' in tags else None,
        },
        {
            'check': 'motion_min',
            'min': 0.6,
            'for': 'move',
            'note': 'a clip that did not move is a no on move_, whatever it looks like',
        },
    ]
    for t in tags:
        if t == 'face':
            checks.append(
                {
                    'check': 'identity_cosine_min',
                    'a': 0,
                    'b': -1,
                    'min': 0.35,
                    'detector': 'insightface-buffalo_l',
                    'for': 'move',
                }
            )
        elif t.startswith('p') and t[1:].isdigit():
            checks.append(
                {
                    'check': 'detector_count',
                    'detector': 'yolov8n-coco',
                    'label': 'person',
                    'n': int(t[1:]),
                    'sample': SAMPLE5,
                    'share': 1.0,
                    'for': 'both',
                }
            )
        elif t.startswith('a') and t[1:].isdigit():
            checks.append(
                {
                    'check': 'detector_count',
                    'detector': 'yolov8n-coco',
                    'label': 'animal',
                    'n': int(t[1:]),
                    'sample': SAMPLE5,
                    'share': 1.0,
                    'for': 'both',
                    'note': 'animal = the COCO class named in the still prompt (bird, dog, cat, horse, cow, sheep)',
                }
            )
        elif t == 'h1f5':
            checks.append(
                {
                    'check': 'hand_landmarks_count',
                    'hands': 1,
                    'fingers': 5,
                    'sample': SAMPLE5,
                    'share': 0.8,
                    'for': 'both',
                }
            )
        elif t in ('h1', 'h2'):
            checks.append(
                {'check': 'hand_landmarks_count', 'hands': int(t[1]), 'sample': SAMPLE5, 'share': 0.8, 'for': 'both'}
            )
        elif t.startswith('ocr:'):
            checks.append(
                {
                    'check': 'ocr_equals',
                    'text': t[4:],
                    'detector': 'tesseract-5',
                    'sample': SAMPLE5,
                    'share': 0.8,
                    'for': 'render',
                }
            )
            checks.append({'check': 'ocr_stable', 'sample': SAMPLE5, 'for': 'move'})
        elif t == 'ocrs':
            checks.append(
                {
                    'check': 'ocr_stable',
                    'sample': SAMPLE5,
                    'for': 'move',
                    'note': 'the string is free; it must not churn from frame to frame',
                }
            )
        elif t == 'static':
            checks.append(
                {
                    'check': 'flow_region',
                    'region': label,
                    'min': 0.0,
                    'max': 0.5,
                    'detector': 'sam2-hiera-small',
                    'for': 'move',
                    'note': 'the CAMERA moves; this subject must not. Flow inside its own mask stays near zero.',
                }
            )
    checks = [{k: v for k, v in c.items() if v is not None} for c in checks]
    return _probe(
        'subj_' + sid,
        'subject: ' + label,
        [f'render_{sid}', f'move_{sid}'],
        {
            'prompt': prompt,
            'motion': motion,
            'negative': NEGATIVE,
            'image': f'fixtures/video/subjects/{sid}.png',
            'note': 'prompt/motion/image are used per FIXED["prompt_rule"] for the row\'s type (i2v, t2v, v2v)',
        },
        checks,
        state_rule=STATE_3OF3,
        state_note=SUBJ_NOTE,
    )


PROBES = [_subject_probe(*s) for s in SUBJECTS]
