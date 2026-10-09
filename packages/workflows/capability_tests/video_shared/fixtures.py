# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every fixture file the bank names, the operator protocol, and the SHARED dict."""

from __future__ import annotations

from .settings import (
    CHECK_KINDS,
    COLOUR_HUES,
    DETECTORS,
    FIXED,
)
from .subjects import SUBJECTS
from .probes import PROBES
from .dispositions import (
    DERIVE,
    LOOKUP,
    NA,
    TRANSPORT_NA,
    TRANSPORT_NA_NOTE,
    WIRING,
)

# ── fixtures: every file the bank names, and how it comes into being ───────────────────
FIXTURES = {
    'fixtures/video/subjects/<id>.png': {
        'path': 'fixtures/video/subjects/<id>.png, one per SUBJECTS id (132 files)',
        'generated': (
            "the APPROVED subject render from the image bank: capability_tests/image_shared.py's subject "
            'probe for the same id, seed 11, its production model, at 832x480, exported as PNG with no '
            'post-processing. The sha256 of each file goes in the trial. Nothing is drawn by hand and '
            'nothing is fetched.'
        ),
        'verified': False,
        'blocks': [f'render_{s[0]}' for s in SUBJECTS],
        'how_to_verify': (
            'the operator opens the 132 stills as a contact sheet and answers, per still, "is this the '
            'subject named, and is it correct — no defect this test would then blame on the video '
            'row?" A still that fails is regenerated at the next seed, not accepted. The flag flips '
            'to True only when all 132 have passed, and the date and operator go in the manifest.'
        ),
    },
    'fixtures/video/named/<name>.png': {
        'path': 'fixtures/video/named/Maarten.png, Griet.png, Joost.png, Neeltje.png',
        'generated': (
            'four approved character renders from the same image bank, one seed each, front-on, neutral '
            'expression, 512x512, chosen so ArcFace cosine between any two of them is below 0.20 — which '
            'the verification step measures and records.'
        ),
        'verified': False,
        'blocks': ['cap_named', 'pd_unique_subjects'],
        'how_to_verify': (
            'run insightface buffalo_l over the four stills, print the 4x4 cosine matrix, and check '
            'every off-diagonal is < 0.20. Then the operator confirms each face is usable. Both the '
            "matrix and the operator's name go in the manifest."
        ),
    },
    'fixtures/video/verdicts/MANIFEST.json': {
        'path': 'fixtures/video/verdicts/MANIFEST.json plus 12 clips beside it',
        'generated': (
            '12 clips taken from our OWN past output (the run ledger names them) and copied in unchanged: 4 '
            'with a real defect, 5 clean, 3 unclear. The manifest records, per clip, the run it came from, '
            'the planted key (defect | clean | unclear) and one sentence saying where the defect is.'
        ),
        'verified': False,
        'blocks': [
            'pd_question_wording',
            'pd_leading',
            'pd_yes_bias',
            'pd_rubric_needed',
            'pd_abstain',
            'pd_batched_questions',
        ],
        'how_to_verify': (
            'the operator watches all 12 blind (filenames hidden, order shuffled) and writes their own '
            'verdict; a clip where the operator disagrees with the planted key is not a fixture and is '
            'either moved to "unclear" or dropped. We do not grade a model against a key we could not '
            'reproduce ourselves.'
        ),
    },
    'fixtures/video/broken/truncated.png': {
        'path': 'fixtures/video/broken/truncated.png',
        'generated': (
            'take fixtures/video/subjects/person_one.png and write back only the first 40 % of its bytes. '
            'The recipe is the fixture; the file is regenerated from the subject still whenever that '
            'still changes.'
        ),
        'verified': False,
        'blocks': ['failsafe'],
        'how_to_verify': 'PIL must raise on open, and the sha256 of the truncated file goes in the manifest.',
    },
    'fixtures/video/gpu_load/hold_8gb.json': {
        'path': 'fixtures/video/gpu_load/hold_8gb.json',
        'generated': (
            'a JSON recipe, not a binary: {"device": "cuda:0", "bytes": 8589934592, "shape": [4096, 4096], '
            '"dtype": "float16", "target_util": 0.4, "hold": "until released"} — allocate that much, loop a '
            'matmul to hold roughly that utilisation, release on signal. Written by hand; no download.'
        ),
        'verified': False,
        'blocks': ['degrades'],
        'how_to_verify': (
            'start it, read nvidia-smi twice 30 s apart, and check memory.used rose by 8 GiB ± 0.5 and '
            'utilisation sits at 40 % ± 10. Both readings go in the manifest.'
        ),
    },
}

OPERATOR_PROTOCOL = (
    'Every `operator` check in this bank is a BLIND decision, and the runner must make it blind before a human sees '
    'anything:\n'
    '1. Clips are exported to a review folder under an opaque id. The row, the model, the seed, the step and the '
    '   filename are NOT visible. A clip is never shown beside its own metadata.\n'
    '2. The order is SHUFFLED across rows and across seeds, so the operator cannot learn "this is the good model" '
    '   from position. Where a question compares two clips (a pair, a chain, a grid), the pair is kept together '
    '   because the question needs both, but which is A and which is B is randomised and recorded.\n'
    '3. The question is asked EXACTLY as written here. The operator answers yes or no. MAYBE IS NO — a defect you '
    '   have to argue about is a defect, and a clip nobody can call is what `untested` is for, not a generous yes.\n'
    '4. Answers are written once. There is no second pass after seeing the scores, and the answer file is written '
    '   before the sheet is assembled.\n'
    '5. Every answer goes in the trial with the clip id, so any cell can be traced to the clip and the question that '
    '   produced it.\n'
    'This is not a preference for humans over machines. It is the finding of our own defect-judge bench '
    '(2026-09-27): the local VLMs scored 34/40 on "is anything wrong with this image" and 2/8 on fused fingers, '
    'extra digits and a second feather. The questions in this bank are exactly the second kind.'
)

CONDITIONS_NOTE = (
    'What makes two rows comparable here: 81 frames, seeds 11/12/13, 30 steps, cfg 6.0, uni_pc/simple, one '
    'resolution per row, one negative prompt, one prompt per subject, byte-identical. What is NOT forced: fps, '
    "resolution and shift are each row's PRODUCTION default and are recorded into every trial. Forcing 16 fps onto "
    'InfiniteTalk or a shift of 5.0 onto a row tuned at 3.0 would measure a configuration nobody ships, and on Wan a '
    'shift change is a different test altogether [[project_wan_motion_debug]]. Two sheets whose recorded shift '
    'differs are two tests and the reader must be told; the test hash does not catch it, so the trial carries it.'
)

SHARED = {
    'version': '2026-09-30.1',
    'kind': 'video',
    'title': 'the default test every video and motion step runs identically',
    'fixed': FIXED,
    'conditions_note': CONDITIONS_NOTE,
    'detectors': DETECTORS,
    'colour_hues': COLOUR_HUES,
    'subjects': [{'id': s[0], 'label': s[1], 'prompt': s[2], 'motion': s[3], 'mechanical': s[4]} for s in SUBJECTS],
    'fixtures': FIXTURES,
    'operator_protocol': OPERATOR_PROTOCOL,
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': NA,
    'transport_na': TRANSPORT_NA,
    'transport_na_note': TRANSPORT_NA_NOTE,
    'CHECK_KINDS': CHECK_KINDS,
}
