# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JUDGE
from .subjects import (
    HOW_TO_VERIFY,
    MECHANICAL,
    NAME_Q,
    NEG,
    SEE_Q,
    SUBJECTS,
    SUBJECT_NEG_RULE,
    SUBJECT_PROMPT,
    SUBJ_DIR,
)


def _subject_fixture(sid):
    """The pos/neg fixture pair of one subject, declared but not created. Nothing here writes
    a binary; `generated` is the exact recipe the image bank runs."""
    label, _accept, clause = SUBJECTS[sid]
    return {
        'path': f'{SUBJ_DIR}/{sid}_pos.png',
        'negative_path': f'{SUBJ_DIR}/{sid}_neg.png',
        'generated': (
            "the image bank's operator-approved subject render (pos) and the same seed with the "
            'subject removed from the prompt (neg)'
        ),
        'prompt': SUBJECT_PROMPT.format(clause=clause),
        'negative_prompt': NEG.get(sid, SUBJECT_NEG_RULE),
        'label': label,
        'key': {'pos': {'answer': 'yes'}, 'neg': {'answer': 'no'}},
        'region': f'the subject bounding box of {sid}_pos.png, recorded by the operator in the same pass',
        'verified': False,
        'blocks': [f'see_{sid}', f'identify_{sid}'],
        'how_to_verify': HOW_TO_VERIFY,
    }


def _mech_check(sid):
    """The mechanical cross-check for this subject, or None when no detector decides it."""
    if sid not in MECHANICAL:
        return None
    kind, fields = MECHANICAL[sid]
    return dict(
        {'check': kind, 'transports': ['service', 'vlm_ollama', 'vlm_inspector'], 'on': 'the fixture, not the answer'},
        **fields,
    )


PROBES = []

# ── Sees: 132 probes, one subject each, positive AND negative ────────────────────────
for _sid, (_label, _accept, _clause) in SUBJECTS.items():
    _checks = [
        {
            'check': 'answer_yes_no',
            'transports': ['vlm_ollama', 'vlm_inspector'],
            'key': 'the fixture half the trial ran on (pos -> yes, neg -> no)',
        },
        {
            'check': 'detector_finds',
            'transports': ['service'],
            'conf': 0.35,
            'iou': 0.3,
            'note': 'a detector answers with a box over the subject region, not with a sentence',
        },
        {'check': 'recall_precision_min', 'recall': 0.9, 'precision': 0.9},
    ]
    _m = _mech_check(_sid)
    if _m:
        _checks.append(_m)
    PROBES.append(
        {
            'id': f'sees_{_sid}',
            'title': f'Sees: {_label}',
            'feeds': [f'see_{_sid}'],
            'inputs': {
                'task': SEE_Q.format(label=_label),
                'image': [f'{SUBJ_DIR}/{_sid}_pos.png', f'{SUBJ_DIR}/{_sid}_neg.png'],
                'fixture': _subject_fixture(_sid),
            },
            'conditions': dict(COND_JUDGE),
            'checks': _checks,
            'grade': 'measured',
            'state_rule': {'yes': 0.9, 'partial': 0.7},
            'state_note': (
                'pass rate = min(recall, precision) over the pos/neg pair x 3 repeats: yes at '
                'recall >= 0.9 AND precision >= 0.9, partial at >= 0.7 both. A judge that answers '
                'yes to everything scores 0.5 precision and lands on `no`. Where the subject is in '
                'MECHANICAL the detector reading decides and the model is scored against it; where '
                "it is not, the operator's blind pass on the contact sheet is the only key."
            ),
        }
    )

# ── Names: 132 probes, the same pair, nothing named in the question ──────────────────
for _sid, (_label, _accept, _clause) in SUBJECTS.items():
    PROBES.append(
        {
            'id': f'names_{_sid}',
            'title': f'Names: {_label}',
            'feeds': [f'identify_{_sid}'],
            'inputs': {
                'task': NAME_Q,
                'image': [f'{SUBJ_DIR}/{_sid}_pos.png', f'{SUBJ_DIR}/{_sid}_neg.png'],
                'fixture': _subject_fixture(_sid),
            },
            'conditions': dict(COND_JUDGE, max_tokens=120),
            'checks': [
                {
                    'check': 'names_label_present',
                    'transports': ['vlm_ollama', 'vlm_inspector'],
                    'accept': _accept.split('|'),
                },
                {
                    'check': 'open_vocab_label',
                    'transports': ['service'],
                    'conf': 0.35,
                    'label': _label,
                    'note': 'GroundingDINO takes the label as its prompt, so Names is measurable for an '
                    'open-vocabulary detector: it finds the label it was given. A closed-vocabulary '
                    'detector (hand_yolov8s, MediaPipe, ArcFace) returns classes, not names — those rows '
                    'declare `na` on the Names band with that reason.',
                },
                {'check': 'recall_precision_min', 'recall': 0.9, 'precision': 0.9},
            ],
            'grade': 'measured',
            'state_rule': {'yes': 0.9, 'partial': 0.7},
            'state_note': (
                'the subject is NOT named in the question — the label or one of its synonyms must '
                'appear unprompted on the positive picture and on none of the negative ones. '
                'Accepted synonyms: ' + _accept
            ),
        }
    )
