# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Region finding (detectors). 2026-09-30.

Question the sheet asks: can we reliably find the region a judge should look at? The sheet's
own verdict note states the separation this step exists to enforce — *finding is solved,
judging is not* — so this test is built so that a row can score well on `finds` and still
land on `no` or `na` for `judges`. That is the honest shape of the answer, not a gap in it.

The shape of the test
---------------------
ONE fixture set of 30 frames drawn from operator-approved house renders (20 photographic,
10 from the Arcane restyle runs so `painted_find` is a measured drop and not a guess), plus
a 20-frame consecutive clip for tracking, 10 empty backgrounds for `false_pos` and the 10
known-bad hands for `judges`. Every target in every frame carries a box the OPERATOR drew.
Nothing in here is a sentence a model wrote: a detector answers with a box, a mask or a
confidence, and every one of the 17 domain columns is scored mechanically against the
operator's box. There is not one `operator` check in this module — where a machine can
decide, the contract says it must, and here a machine always can.

What is blocked and why
-----------------------
All 17 domain columns are BLOCKED. Not one of them can be measured until the operator has
drawn the boxes (MANIFEST.json), the 8 polygon masks, and confirmed the 10 empty frames are
empty and the 10 bad hands are bad. A recall number against boxes nobody checked would be
the exact error this sheet exists to catch, so the fixtures are declared `verified: False`
and the runner writes `untested — key unverified` until each flag is flipped. The one-time
cost of that pass is written out in the budget note.

The `judges` receipt
--------------------
hand_yolov8s carries a 'bad hand' class and the standing receipt is that hand_qc scored
EVERY known-bad hand clean. So `judges` is a real probe on that row with ten known-bad
hands and an expected result of `no` — a measured negative is worth more than an `na`,
because it is the reason the row is not trusted as a judge. Every other row is `na`: a box
is not a verdict.

Closed vocabulary
-----------------
The judge bank scores a `service` row on the 132 Sees subjects with `detector_finds` and on
the 132 Names subjects with `open_vocab_label`, and its own note says a closed-vocabulary
detector must declare `na` on the Names band. This module does that for the five closed rows
and keeps GroundingDINO in, because the label IS its prompt. For SAM2 and DINOv2 both bands
are `na`: SAM2 segments what it is handed and DINOv2 returns a 384-d vector, so the bank's
check cannot be run at all — that is a different thing from running it and finding nothing.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_HOME

#: The Second Ledger intro tree the defect bench lives in; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')

# ── check kinds this module adds to capability_tests.__init__.CHECK_KINDS ─────────────
# A detector answers with a box, a mask or a number. Each line says what is measured,
# against what, and which threshold field carries it.
CHECK_KINDS = {
    'detector_recall_min': 'over the frames of the fixture subset that contain the target class: recall = frames where the transport returned a detection at confidence >= `conf` whose box IoU with the operator-verified box is >= `iou`, divided by those frames; passes when recall >= `min`',
    'detector_box_iou_min': 'over the frames where the class was found: mean IoU between the highest-confidence detection and the operator-verified box; passes when the mean is >= `min`',
    'detector_mask_iou_min': 'IoU between the returned per-pixel mask and the operator-drawn polygon mask of the same object; passes when the mean over the mask subset is >= `min`',
    'detector_false_positive_max': 'mean number of detections at confidence >= `conf` per frame over the empty-background subset (no target class present); passes when it is <= `max`',
    'detector_recall_drop_max': 'detector_recall_min on the painted subset subtracted from detector_recall_min on the photographic subset of the SAME subjects; passes when the drop is <= `max`',
    'confidence_auc_min': 'ROC AUC of the returned confidence used as a score for "this detection is correct" (correct := box IoU >= `iou` with an operator-verified box, or mask IoU >= `iou` for a mask row); passes when AUC >= `min`',
    'track_identity_kept': 'over `frames` consecutive frames: the share in which the propagated instance still overlaps the operator-verified box of the SAME object at IoU >= `iou`; passes at >= `min`',
    'embed_cosine_kept': 'cosine between the embedding of the object crop in the first frame and in each of the next `frames` frames, taken on the operator-verified boxes; passes when the minimum over those frames is >= `min`',
    'detector_flags_class': 'the share of the fixture subset on which the transport returns a detection of class `class` at confidence >= `conf`; the probe records that share and `expect` says which state the receipt predicts, so a measured negative is visible rather than hidden as na',
}

FX = 'capability_tests/fixtures/detectors'
MANIFEST = FX + '/MANIFEST.json'
MASKS = FX + '/masks'
BAD_HANDS = FX + '/bad_hands'
EMPTY = FX + '/empty'

# The fixture set, verbatim. The MANIFEST holds the frame ids and the boxes; this table is
# the contract the MANIFEST must satisfy, so a rebuilt set is the same test or a new one.
FRAME_SET = {
    'count': 30,
    'photo': '20 photographic frames from operator-approved documentary and scholarly stills, 1024 px long side',
    'painted': 'the SAME 20 subjects restyled through arcane_restyle.py, of which 10 are kept — painted_find is a drop between two halves of one subject list, never a comparison of two different pictures',
    'per_class_min': {'hands': 10, 'faces': 10, 'people': 12, 'props': 12, 'text': 6, 'creature': 4},
    'small': 'six of the 30 carry a target whose operator-verified box is <= 24 px on its long side',
    'occluded': 'six of the 30 carry a target the operator marked as at least 50 % occluded',
    'clip': 'MANIFEST.clip: one run of 20 consecutive frames from a single house shot, one named object boxed in every frame',
    'masks': 'MANIFEST.masks: 8 of the 30 frames carry an operator-drawn polygon mask of one target',
    'empty': '10 empty backgrounds (bare quay, plank wall, sky, water, cobbles) containing none of the six target classes',
    'bad_hands': '10 frames from the known-bad hand set the 2026-07-24 HandFixer rebuild worked from — six fingers, fused fingers, reversed joints',
    'note': (
        'One set, one operator pass, every column read off the same detector calls: the runner calls each row '
        'once per frame per repeat and scores finds, box_tight, small_object, occluded_find, painted_find, '
        'conf_useful and the six Targets columns from THOSE calls. Nothing is rendered by this test.'
    ),
}

# device policy is continuity_qc.py's, quoted: CUDA only when nvidia-smi reports >= 8 GB free
COND = {
    'repeats': 3,
    'conf': 0.35,
    'device': "auto — CUDA only when nvidia-smi reports >= 8 GB free (continuity_qc.py's GPU floor rule: a QC pass must never OOM a live render), otherwise CPU",
    'seed': 'n/a (deterministic service)',
    'resolution': 'the frame as stored, 1024 px long side; no runner-side resize',
    'note': (
        '3 repeats on a deterministic service is not waste: the device policy can put the same frame on CUDA '
        'once and on the CPU twice, and a row whose boxes then move is a row whose numbers cannot be '
        'reproduced. That is what `deterministic` reads.'
    ),
}

DOMAIN = (
    'finds',
    'judges',
    'box_tight',
    'mask_quality',
    'small_object',
    'occluded_find',
    'open_vocab',
    'painted_find',
    'track_frames',
    'false_pos',
    'conf_useful',
    'hands_det',
    'faces_det',
    'people_det',
    'props_det',
    'text_det',
    'creature_det',
)

BOXERS = ['hand_yolo', 'mediapipe_hand', 'groundingdino', 'arcface']

# Which rows can answer each column. Every other row gets a written `na` built from the two
# tables below, so the sheet says WHY rather than showing a measured zero that means nothing.
CAN = {
    'finds': BOXERS,
    'judges': ['hand_yolo'],
    'box_tight': BOXERS,
    'mask_quality': ['sam2'],
    'small_object': BOXERS,
    'occluded_find': BOXERS,
    'open_vocab': ['groundingdino'],
    'painted_find': BOXERS,
    'track_frames': ['sam2', 'dinov2'],
    'false_pos': BOXERS,
    'conf_useful': BOXERS + ['sam2'],
    'hands_det': ['hand_yolo', 'mediapipe_hand', 'groundingdino'],
    'faces_det': ['groundingdino', 'arcface'],
    'people_det': ['groundingdino'],
    'props_det': ['groundingdino'],
    'text_det': ['groundingdino'],
    'creature_det': ['groundingdino'],
}

ROW_IS = {
    'hand_yolo': 'hand_yolov8s is a single-class box detector (class: hand, plus the bad-hand class the receipt says never fires)',
    'mediapipe_hand': 'the MediaPipe hand_landmarker bundle returns a hand box and 21 landmarks per hand and knows no other class',
    'groundingdino': 'GroundingDINO SwinT-OGC returns boxes for the phrase it is given',
    'sam2': "SAM2.1 hiera base_plus segments what it is prompted with and propagates that mask; continuity_qc.py hands it GroundingDINO's boxes, so it never searches a frame itself",
    'dinov2': 'DINOv2 ViT-S/14 is an EMBEDDER: one 384-d appearance vector per crop, never a box, a class or a count',
    'arcface': 'the ArcFace antelopev2 pack detects faces with SCRFD and embeds them, and knows no other class',
}

COL_NEEDS = {
    'finds': 'this column asks for recall of a named target against an operator-verified box',
    'judges': 'this column asks for a verdict on what was found, and a box is not a verdict',
    'box_tight': 'this column asks how tightly a returned BOX fits the operator-verified box',
    'mask_quality': 'this column asks for the IoU of a returned per-pixel MASK',
    'small_object': 'this column asks for recall on a target whose verified box is 24 px on its long side',
    'occluded_find': 'this column asks for recall on a target the operator marked at least 50 % occluded',
    'open_vocab': "this column asks whether an arbitrary phrase can be used as the detector's prompt",
    'painted_find': 'this column asks how far recall falls between the photographic and the painted half of one subject list',
    'track_frames': 'this column asks whether one instance keeps its identity over twenty consecutive frames',
    'false_pos': 'this column counts the detections returned on frames that contain no target at all',
    'conf_useful': 'this column asks whether a returned confidence separates correct detections from wrong ones',
    'hands_det': 'this column asks for recall on the HAND targets of the fixture set',
    'faces_det': 'this column asks for recall on the FACE targets of the fixture set',
    'people_det': 'this column asks for recall on the PERSON targets of the fixture set',
    'props_det': 'this column asks for recall on the named PROP targets of the fixture set',
    'text_det': 'this column asks for recall on the TEXT-in-frame targets of the fixture set',
    'creature_det': 'this column asks for recall on the non-human CREATURE targets of the fixture set',
}


def _row_na(rid):
    return {c: f'{ROW_IS[rid]}, and {COL_NEEDS[c]}.' for c in DOMAIN if rid not in CAN[c]}


def _p(pid, title, feeds, checks, subset, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'rows': list(CAN[feeds[0]]),
        'inputs': {'fixture': MANIFEST, 'subset': subset, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
    }
    p.update(kw)
    return p


def _target(col, cls, subset_note):
    return _p(
        f'target_{cls}',
        f'Recall on the {cls} targets',
        [col],
        [{'check': 'detector_recall_min', 'min': 0.9, 'iou': 0.5, 'conf': 0.35}],
        subset_note,
        state_note=(
            f'recall over the frames of the set that carry a verified {cls} box; a row whose class list '
            f'does not contain {cls} is `na` with the reason on its own cell, not a measured zero'
        ),
    )


PROBES = [
    _p(
        'finds',
        'Finds the region',
        ['finds'],
        [{'check': 'detector_recall_min', 'min': 0.9, 'iou': 0.5, 'conf': 0.35}],
        'all 30 frames, each row scored only on the classes it has',
        state_note=(
            "the sheet's own note is that finding is the solved half: yes at recall >= 0.9 against the "
            'operator-verified boxes, partial at >= 0.7. A row that returns nothing scores 0 and lands on no.'
        ),
    ),
    _p(
        'judges',
        'The bad-hand class as a judge',
        ['judges'],
        [{'check': 'detector_flags_class', 'class': 'bad hand', 'conf': 0.35, 'expect': 'no'}],
        'the 10 known-bad hands in ' + BAD_HANDS,
        inputs={'fixture': BAD_HANDS, 'subset': 'all 10', 'prompt': None},
        state_note=(
            'the standing receipt is that hand_qc scored EVERY known-bad hand clean, so the expected state '
            'here is `no` and this probe exists to record that as a measurement rather than hide it as na. '
            'A flag rate >= 0.9 would be a change worth investigating, not a pass to be assumed.'
        ),
    ),
    _p(
        'box_tight',
        'Boxes are tight',
        ['box_tight'],
        [{'check': 'detector_box_iou_min', 'min': 0.7}],
        'the frames of the set where the row found its class',
        state_note='mean IoU >= 0.7 against the operator box is yes; 0.7 is the house figure the brief pins',
    ),
    _p(
        'mask_quality',
        'Masks are clean',
        ['mask_quality'],
        [{'check': 'detector_mask_iou_min', 'min': 0.8}],
        'the 8 frames of MANIFEST.masks',
        inputs={'fixture': MASKS, 'subset': 'the 8 operator-drawn polygon masks', 'prompt': None},
        state_note="SAM2 is prompted with the operator box of the same object, so the number is the mask's quality and not GroundingDINO's recall",
    ),
    _p(
        'small_object',
        'Finds small objects',
        ['small_object'],
        [{'check': 'detector_recall_min', 'min': 0.9, 'iou': 0.4, 'conf': 0.35}],
        'the 6 frames whose target box is <= 24 px on its long side',
        state_note='the IoU floor is 0.4 here and not 0.5: at 24 px a two-pixel edge error costs more IoU than it costs usefulness, and the column asks whether the thing was FOUND',
    ),
    _p(
        'occluded_find',
        'Finds occluded objects',
        ['occluded_find'],
        [{'check': 'detector_recall_min', 'min': 0.9, 'iou': 0.5, 'conf': 0.35}],
        'the 6 frames whose target the operator marked at least 50 % occluded',
        state_note='the verified box is the box of the WHOLE object, occluded part included, so a detector that boxes only the visible sliver loses IoU and that is the intended reading',
    ),
    _p(
        'open_vocab',
        'Open vocabulary',
        ['open_vocab'],
        [
            {
                'check': 'detector_recall_min',
                'min': 0.9,
                'iou': 0.5,
                'conf': 0.35,
                'phrases': ['a lantern', 'a barrel', 'a quill'],
            }
        ],
        'the frames of the set carrying a lantern, a barrel or a quill',
        state_note=(
            'the label IS the prompt for GroundingDINO, so the three phrases are given verbatim and each is '
            'scored on the frames whose verified boxes carry that object. Every other row is na: a closed '
            'vocabulary cannot be handed a phrase.'
        ),
    ),
    _p(
        'painted_find',
        'Works on painted frames',
        ['painted_find'],
        [{'check': 'detector_recall_drop_max', 'max': 0.1, 'iou': 0.5, 'conf': 0.35}],
        'the 10 painted frames against the same 10 subjects photographic',
        state_note='the drop is measured on ONE subject list restyled, so a difference is the style and not the content; <= 0.1 is yes',
    ),
    _p(
        'track_sam2',
        'Keeps one instance over twenty frames (mask propagation)',
        ['track_frames'],
        [{'check': 'track_identity_kept', 'frames': 20, 'iou': 0.5, 'min': 0.9}],
        'MANIFEST.clip, frames 1-20',
        rows=['sam2'],
        state_note='SAM2 is prompted once on frame 1 with the operator box and propagates; the share of the remaining 19 frames still on the right object is the number',
    ),
    _p(
        'track_dino',
        'Keeps one instance over twenty frames (appearance cosine)',
        ['track_frames'],
        [{'check': 'embed_cosine_kept', 'frames': 20, 'min': 0.85}],
        'MANIFEST.clip, frames 1-20',
        rows=['dinov2'],
        state_note=(
            'DINOv2 cannot track — it is the appearance half of the same question, and continuity_qc.py uses '
            'it exactly this way across the 57-frame context seams. The column therefore carries two '
            'different measurements on two rows and each state_note says which.'
        ),
    ),
    _p(
        'false_pos',
        'Few false positives',
        ['false_pos'],
        [{'check': 'detector_false_positive_max', 'max': 0, 'conf': 0.35}],
        'the 10 empty backgrounds',
        inputs={'fixture': EMPTY, 'subset': 'all 10', 'prompt': None},
        state_note='zero detections at conf >= 0.35 on a frame with nothing in it; the threshold is written 0 so any later relaxation is a visible edit',
    ),
    _p(
        'conf_useful',
        'Confidence means something',
        ['conf_useful'],
        [{'check': 'confidence_auc_min', 'min': 0.7, 'iou': 0.5}],
        'every detection returned over the 30 frames, correct or not',
        state_note=(
            'AUC over all detections of the row, correct := IoU >= 0.5 with a verified box. For sam2 the '
            'score is its predicted-IoU head and correctness is mask IoU >= 0.8 — the same question asked of '
            'the number that row actually returns.'
        ),
    ),
    _target('hands_det', 'hand', 'the >= 10 frames carrying a verified hand box'),
    _target('faces_det', 'face', 'the >= 10 frames carrying a verified face box'),
    _target('people_det', 'person', 'the >= 12 frames carrying a verified person box'),
    _target('props_det', 'prop', 'the >= 12 frames carrying a verified named-prop box'),
    _target('text_det', 'text', 'the >= 6 frames carrying a verified text box'),
    _target('creature_det', 'creature', 'the >= 4 frames carrying a verified non-human box'),
]

NAMES_BANDS = [
    'Names: People',
    'Names: The body',
    'Names: Food',
    'Names: Damage & wear',
    'Names: Text & number',
    'Names: Objects',
    'Names: Animals',
    'Names: Nature & weather',
    'Names: Built environment',
    'Names: Clothing',
]
SEES_BANDS = [b.replace('Names:', 'Sees:') for b in NAMES_BANDS]

CLOSED_NAMES = {
    'reason': (
        'the judge bank scores Names with `open_vocab_label` — the detector is handed the subject '
        'label as its prompt and must return it. A closed-vocabulary detector returns class ids, '
        "never a name, so there is no name for this row to be right or wrong about. The bank's own "
        'note on that check names this row as one that must declare the band na.'
    ),
    'bands': list(NAMES_BANDS),
}
NO_DETECTION = {
    'reason': (
        "the bank's recognition checks need a detection or a sentence, and this row returns "
        'neither: SAM2.1 returns a mask for a box it is given and DINOv2 returns a 384-d vector for '
        'a crop it is given. The check cannot be RUN here, which is a different thing from running '
        'it and finding nothing — so these bands are na rather than a measured zero.'
    ),
    'bands': SEES_BANDS + NAMES_BANDS,
}

TEST = {
    'step': 'detectors',
    'version': '2026-09-30.1',
    'title': 'One 30-frame fixture set with operator-drawn boxes',
    'purpose': (
        'Measure the found region against boxes the operator drew, mechanically and with no VLM anywhere in '
        'the scoring path, so the sheet can say which detector finds what — and keep `judges` as a measured '
        'negative rather than an omission.'
    ),
    'include_shared': 'judge',
    'frame_set': FRAME_SET,
    'rows': {
        'hand_yolo': {
            'transport': 'service',
            'where': f'the defect bench run_yolo.py ({LEDGER_INTRO}/intro/defect_bench/run_yolo.py) driving hand_yolov8s through ultralytics',
            'model': 'hand_yolov8s (ultralytics)',
            'na': _row_na('hand_yolo'),
            'na_bands': CLOSED_NAMES,
            'budget': {
                'minutes': 15,
                'note': 'ultralytics on one 1024 px frame is ~0.12 s on the GPU tier and ~0.5 s on CPU; the whole set and the bank fit in a quarter of an hour',
            },
            'note': 'AGPL-3.0 at file level — see the licence lookup; the row is kept because it is what the defect bench measured',
        },
        'mediapipe_hand': {
            'transport': 'service',
            'where': 'anatomy_qc.detect_hand_boxes_strict (MediaPipe hand_landmarker, CPU, zero VRAM)',
            'model': 'MediaPipe hand_landmarker',
            'na': _row_na('mediapipe_hand'),
            'na_bands': CLOSED_NAMES,
            'budget': {
                'minutes': 12,
                'gpu_minutes': 0,
                'note': 'anatomy_qc is CPU by design (zero VRAM) at roughly 0.2 s per frame, so the whole set is minutes and holds no GPU at all',
            },
            'note': 'Apache-2.0, and the row that replaced the AGPL hand path (ZYG_HANDS_BACKEND in hand_qc_service.py)',
        },
        'groundingdino': {
            'transport': 'service',
            'where': 'continuity_qc.py (GroundingDINO SwinT-OGC, ~3.8 s/frame measured on CPU at 1024x1024)',
            'model': 'GroundingDINO SwinT-OGC',
            'na': _row_na('groundingdino'),
            'budget': {
                'calls': 2580,
                'minutes': 150,
                'note': 'the only open-vocabulary row: it also runs the 3 open_vocab phrases over the set (3 x 30 x 3 = 270 extra calls) and it is the slow one at ~3.8 s/frame',
            },
            'note': 'open vocabulary: the label is the prompt, which is why this row alone keeps the Names band',
        },
        'sam2': {
            'transport': 'service',
            'where': 'continuity_qc.py (SAM2.1 hiera base_plus, ~2.4 s/frame/object measured on CPU at 1024x1024)',
            'model': 'SAM2.1 hiera base_plus',
            'na': _row_na('sam2'),
            'na_bands': NO_DETECTION,
            'budget': {
                'calls': 400,
                'minutes': 95,
                'note': 'only the mask subset (8 frames) and the 20-frame clip are its own work, but at 2.4 s/frame/object with the recognition bands na the row is an hour and a half',
            },
            'note': "promptable segmentation: it is handed a box and returns a mask, so `finds` is GroundingDINO's number and is na here",
        },
        'dinov2': {
            'transport': 'service',
            'where': 'continuity_qc.py (DINOv2 ViT-S/14, facebook/dinov2-small, VBench appearance protocol)',
            'model': 'DINOv2 ViT-S/14',
            'na': _row_na('dinov2'),
            'na_bands': NO_DETECTION,
            'budget': {
                'calls': 60,
                'minutes': 25,
                'note': "one embedding per box per frame of the 20-frame clip x 3 repeats is the row's entire work; everything else is na",
            },
            'note': 'an embedder. Every finding and boxing column is na with that reason written on the cell',
        },
        'arcface': {
            'transport': 'service',
            'where': 'identity_qc_service.py (insightface antelopev2: SCRFD detection + ArcFace embedding)',
            'model': 'ArcFace antelopev2 (insightface)',
            'na': _row_na('arcface'),
            'na_bands': CLOSED_NAMES,
            'budget': {
                'minutes': 15,
                'note': 'SCRFD plus the embedding is ~0.3 s per frame on the GPU tier, so the set and the bank are a quarter of an hour',
            },
            'note': 'the antelopev2 pack is NON-COMMERCIAL — quoted in the licence lookup; the row is in the sheet so that limit is on the record',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'licence': {
            'grade': 'vendor',
            'unit': 'text',
            'from': 'the per-row licence, quoted, because this step mixes three incompatible ones and a single sheet-wide answer would be wrong',
            'requires': [
                'hand_yolo: ultralytics is AGPL-3.0. The licence is at FILE level — importing it into a house module makes that module AGPL, which is why anatomy_qc.py was written to replace it (its own docstring says so). Pin: the LICENSE file of the installed ultralytics distribution, with its version.',
                "mediapipe_hand: Apache-2.0 (google-ai-edge/mediapipe), model bundles included. Pin: the bundle's model card and the repository LICENSE at the revision installed.",
                'groundingdino: Apache-2.0. Pin: the IDEA-Research/GroundingDINO LICENSE plus the sha256 of groundingdino_swint_ogc.pth as it sits at GDINO_WEIGHTS.',
                'sam2: Apache-2.0. Pin: the facebookresearch/sam2 LICENSE plus the sha256 of sam2.1_hiera_base_plus.safetensors at SAM2_WEIGHTS.',
                'dinov2: Apache-2.0. Pin: the facebookresearch/dinov2 LICENSE plus the facebook/dinov2-small revision hash actually pulled.',
                "arcface: the insightface CODE is MIT but the antelopev2 MODEL PACK is not: insightface distributes its pretrained packs for NON-COMMERCIAL research use, and the pack page states it in those words. Quote that sentence verbatim into the cell. Commercial delivery of anything this row gated needs the operator's decision, not a test's.",
            ],
            'note': (
                'the column is a lookup and not a probe because a licence is read, never measured; it overrides '
                "the bank's sheet-wide entry precisely because the answer differs per row here and one of the "
                'six is AGPL and another is non-commercial.'
            ),
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'generated': (
                'the operator copies the 30 frames named in FRAME_SET out of approved house runs into '
                + FX
                + "/frames/, draws one box per target class per frame in the sheet's box editor, and the "
                'editor writes this MANIFEST (frames, boxes, classes, the small and occluded marks, clip, masks)'
            ),
            'blocks': [
                'finds',
                'box_tight',
                'small_object',
                'occluded_find',
                'open_vocab',
                'painted_find',
                'conf_useful',
                'hands_det',
                'faces_det',
                'people_det',
                'props_det',
                'text_det',
                'creature_det',
            ],
            'how_to_verify': (
                'per frame: confirm every target of the six classes carries a box, that the box is the '
                'whole object (occluded part included), and that the small and occluded marks are right; '
                'then set verified = true. No VLM draws or checks a box here — the 2026-09-27 defect bench '
                'is why. Budget ~90 minutes for the 30 frames.'
            ),
        },
        {
            'path': MASKS,
            'verified': False,
            'generated': 'the operator draws a polygon mask of one target in 8 of the 30 frames and the editor writes them here as PNG alpha masks',
            'blocks': ['mask_quality', 'track_frames'],
            'how_to_verify': 'open each mask over its frame at 100 % and confirm the edge follows the object rather than the box; ~40 minutes for 8',
        },
        {
            'path': BAD_HANDS,
            'verified': False,
            'generated': (
                'copy the 10 frames listed in MANIFEST.bad_hands out of the runs the 2026-07-24 HandFixer '
                'rebuild worked from (six fingers, fused fingers, reversed joints) into this folder'
            ),
            'blocks': ['judges'],
            'how_to_verify': 'confirm in writing, per frame, which named defect it shows; a frame nobody can name a defect in is dropped from the set rather than counted as bad',
        },
        {
            'path': EMPTY,
            'verified': False,
            'generated': 'copy 10 approved house frames with no hand, face, person, prop, text or creature in them (bare quay, plank wall, sky, water, cobbles) into this folder',
            'blocks': ['false_pos'],
            'how_to_verify': 'look at each of the 10 once and confirm none of the six target classes appears anywhere in it, edges included; ~5 minutes',
        },
    ],
    'run_order': [
        'mediapipe_hand and arcface first: CPU, minutes, and they fail loudly if the fixture set is malformed',
        "hand_yolo next, including the `judges` probe on the 10 bad hands — 10 frames, and it settles the sheet's sharpest question",
        'then false_pos and the clip probes (track_sam2, track_dino): small subsets, and they need no new fixtures',
        'then the 30-frame pass for finds, box_tight, small_object, occluded_find, painted_find, conf_useful and the six Targets columns',
        'groundingdino last of the detectors: slowest per frame and the only row carrying the open_vocab phrases',
        "the judge bank's 132-subject pos/neg set LAST — it is the large majority of the calls and a partial run has already filled every domain column without it",
    ],
    'budget': {
        'calls': 2310,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a detector takes pixels and a threshold and returns boxes, masks or a vector; no language-model tokens are spent on any row of this step',
        'minutes': 45,
        'gpu_minutes': 0,
        'operator_minutes': 35,
        'note': (
            'Per row: one detector call per frame per repeat over the 30-frame set = 90, the 10 empties x 3 = 30, '
            'the 10 bad hands x 3 = 30, the 20-frame clip x 3 = 60 -> ~210 domain calls, and finds, box_tight, '
            'small_object, occluded_find, painted_find, conf_useful and all six Targets columns are read off '
            'THOSE 90 calls rather than repeating them. The judge bank adds the large part: 349 probes x 3 '
            'repeats x the pos/neg pair is ~2100 calls per row, which is why run_order puts it last. '
            'gpu_minutes is 0 on purpose: continuity_qc.py takes CUDA only when nvidia-smi reports >= 8 GB free '
            'and every number in its docstring (GroundingDINO ~3.8 s/frame, SAM2 ~2.4 s/frame/object) was '
            'measured on CPU, so the honest default is that this test holds no GPU; a row that does get the '
            'CUDA tier finishes sooner, not differently. Minutes are overridden per row (groundingdino 150, '
            'sam2 95, dinov2 25, the rest 12-15). No Claude or ollama call appears anywhere in this step, so '
            'nothing here touches the shared weekly meter. Operator: ~35 min of blind bank decisions per row, '
            'PLUS a ONE-TIME pass of about 2h15 (30 frames of boxes ~90 min, 8 polygon masks ~40 min, the 10 '
            'bad hands ~10 min, the 10 empties ~5 min) — until that pass is done ALL 17 domain columns are '
            'blocked and the runner writes untested "key unverified".'
        ),
    },
    'notes': [
        'Not one `operator` check is in this module. Every domain column is decided by a box, a mask or an AUC against '
        "what the operator drew ONCE, which is the contract's preference and the whole reason this step is separate "
        'from vlm_judges: finding is mechanically checkable and judging is not.',
        'The sheet\'s verdict note — "finding is solved, judging is not" — is a prediction this test can refute. '
        '`judges` is a probe with an expected `no` on hand_yolo and a written na on the other five, so the sheet '
        'shows the reason rather than an empty column.',
        'track_frames carries two different measurements on two rows (SAM2 mask propagation, DINOv2 appearance '
        'cosine) because that is how continuity_qc.py uses them together. Two probes, one column, each with its own '
        'state_note — reading the cell without the note would be reading two things as one.',
        'The licence column is deliberately a per-row lookup: ultralytics is AGPL-3.0 at file level and the ArcFace '
        'antelopev2 pack is non-commercial. A sheet-wide "Apache-2.0" would be true of three rows and dangerously '
        'wrong about two.',
    ],
}
