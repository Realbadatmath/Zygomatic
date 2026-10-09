# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — LoRA training (lora_train). 2026-09-30.

Question the sheet asks: does a trained LoRA actually change the render, and by how much?

The sheet's own verdict is the reason this test exists: until 2026-09-23 ComfyUI never applied
ANY LoRA in this stack, so every LoRA result recorded before that date measures a render with
no LoRA in it. A second silent failure sits on the same path — SimpleTuner exports only
lora_A/lora_B, alpha is unrecoverable from the file, and ComfyUI falls back to
`scale = 1.0`, applying every unstamped adapter at 1/(alpha/rank) = 2x its trained strength at
the standing rank 64 / alpha 32 (lora_trainer_service.stamp_lora_alpha, diagnosed on the
Nicols qwen LoRA: the plain file at strength 1.0 renders smeared garbage, the stamped file at
the same strength renders the character). BOTH failures look exactly like "the model is bad at
training". So the first two probes here are not about training quality at all: `lt_applied`
asks whether the lever is connected, and `lt_alpha` asks whether it is connected at the right
gain. Every other column on this sheet is unreadable until those two say yes.

The shape of the test
---------------------
FOUR fixed datasets, one per LoRA kind, 24 images each, cut from sheets the house already
approved (character / style / object / creature). Fixed steps, rank, alpha and lr per trainer,
read off lora_trainer_service's own config writer so the test exercises the production trainer
path. Every LoRA is then rendered through the row's production workflow at a fixed seed, and
every measurement is a COMPARISON: against the same render with no LoRA (`lt_applied`,
`lt_bleed`), against the dataset's own faces (`lt_likeness`, ArcFace), against the dataset's
dominant pose (`lt_overfit`, MediaPipe), or against the same run resumed (`lt_resume`, sha256).

HEAVY, and the budget says so out loud. One training run is 30-60 GPU minutes and this test
asks for ~8.5 of them per row, before the shared image bank's 396 subject renders. `run_order`
puts every non-GPU probe first (alpha, storage, licence, caption are a safetensors read and
three file reads), so a run stopped after ten minutes has still filled four columns.

WHAT IS HONESTLY BLOCKED / na
    The four datasets do NOT exist yet. They are declared with the exact command that cuts
    them from the approved sheets and `verified: False`, so every column that needs a training
    run is BLOCKED until the operator has looked at the 24 images and at the dataset mean face
    that `lt_likeness` is scored against. We do not grade a trainer against a dataset nobody
    checked.

    kohya is NOT INSTALLED on this box (no kohya_ss / sd-scripts tree; the only mention in the
    whole of crews is a key-name comment in stamp_lora_alpha). Its row is therefore ARTEFACT
    ONLY: the *_sdxl_kohya.safetensors files in the ComfyUI store can be applied, read for
    alpha, laddered for strength, measured for bleed and stacked — but no training run can be
    started, so every column that needs one is `na` with that reason. The row stays because
    those LoRAs are in production and the sheet must keep their receipt.

    `lt_style_lora` and `lt_creature_lora` have no mechanical judge for "is this the Arcane
    look" or "is this still a wolf and not a dog". They are BLIND operator questions beside
    what a detector can say (GroundingDINO presence, and for the character kinds ArcFace).
    The defect-judge bench of 2026-09-27 (best local model 34/40 global, 2/8 on the hard
    cases) is why no VLM is asked.
"""

from __future__ import annotations

from zyg_workflows.paths import (
    ZYG_COMFY_LORA_DIR,
    ZYG_CREATURE_DATASETS,
    ZYG_SIMPLETUNER_DIR,
    ZYG_STORYTELLER_CHARS,
)

#: The LoRAs ComfyUI loads, as text — every call site below joins a file name onto it.
LORA_DIR = str(ZYG_COMFY_LORA_DIR)

# ── check kinds this module adds (the runner is a table of these) ───────────────────────
CHECK_KINDS = {
    'safetensors_key_present': 'for every LoRA down-weight key in the exported file (`.lora_A.weight`, `.lora.down.weight` or `.lora_down.weight`), a sibling `<prefix>.alpha` tensor exists; the share of covered modules must be `share` (1.0 = all of them, which is what a half-stamped mixed export fails)',
    'safetensors_alpha_matches_trained': "every `.alpha` tensor in the exported file equals `lora_alpha` in the run's own simpletuner_config.json (and the file metadata carries lora_rank / lora_alpha as strings) — a stamp with the wrong number is worse than none",
    'identity_cosine_to_set_min': 'ArcFace (buffalo_l) cosine between the largest face in the render and the MEAN embedding of the faces in `ref_set` (a dataset directory) >= `min`; a render with no face found is a no, not an untested',
    'image_distance_monotonic': '`metric` (lpips|pixel) distance from the no-LoRA control render rises with every rung of `rungs` by at least `step_min`, in order, on >= `share` of the seeds — the check that tells a working strength lever from a connected-but-flat one',
    'pose_distance_min': "mean L2 distance between the MediaPipe pose_landmarker 33-point skeleton of the render (normalised to torso length) and the dataset's dominant pose (the medoid of the same landmarks over `ref_set`) >= `min` — a LoRA that can only reproduce the dataset pose fails",
    'file_sha256_equals': 'sha256 of the file at `path` equals sha256 of the file at `to` (byte-identical artefact after an interrupted-and-resumed run)',
    'metric_rises_with_rung': '`metric` (identity_cosine|lpips) measured at each rung of `rungs` is non-decreasing within `tolerance`, and the last rung beats the first by >= `gain_min` — the ladder shape, not a single number',
}

# ── the four datasets, one per LoRA kind ───────────────────────────────────────────────
FX = 'capability_tests/fixtures/lora_train'
DS_CHAR = FX + '/char_cornelis_24'
DS_STYLE = FX + '/style_arcane_24'
DS_OBJECT = FX + '/object_lantern_24'
DS_CREATURE = FX + '/creature_wolf_24'
DS_BLUR = FX + '/char_cornelis_24_blurred4'
DS_08 = FX + '/char_cornelis_08'
DS_16 = FX + '/char_cornelis_16'

# The approved sheets the datasets are cut from. Both are on disk today; the character sheet
# is the one train_klein_char.py drives, the creature sheet is the Gray Wolf.
SRC_CHAR = ZYG_STORYTELLER_CHARS + '/0015c8a3f2e3'
SRC_CREATURE = ZYG_CREATURE_DATASETS + '/0246a7387b5b'

# Trained scale and schedule, read off lora_trainer_service's own config writers on 2026-09-30.
# Fixed here so two trainers are compared at the same scale and not at whatever the env held.
TRAIN = {
    'lora_rank': 64,
    'lora_alpha': 32,
    'learning_rate': '1e-4',
    'lr_scheduler': 'cosine',
    'optimizer': 'adamw_bf16',
    'mixed_precision': 'bf16',
    'max_train_steps': 1200,
    'train_batch_size': 1,
    'gradient_accumulation_steps': 1,
    'gradient_checkpointing': 'true',
    'caption_dropout_probability': 0.10,
    'resolution_type': 'pixel_area',
    'seed': 42,
    'note': (
        'rank 64 / alpha 32 is the standing house scale (2026-07-18, down from 128/64 which '
        'produced 418 MB LoRAs and memorised whole images on ~48-image sets). 1200 steps is '
        '_QUICK_STEPS; the epoch scaler is PINNED OFF for this test (max_steps=1200 passed '
        'explicitly) so a 24-image dataset cannot silently become 900-1800 steps and make two '
        'rows incomparable. caption_dropout 0.10 and pixel_area 1024 are production.'
    ),
}

# The render the measurements are made on: the row's production workflow, one fixed seed, one
# fixed prompt per dataset kind, LoRA at 0.8 unless a probe says otherwise.
RENDER = {
    'strength': 0.8,
    'seeds': [11, 12, 13],
    'size': [1024, 1024],
    'negative': 'see image_shared.NEGATIVE — the one negative every image step uses',
    'control': 'the SAME prompt, seed and checkpoint with NO LoRA loaded at all (not strength 0.0: the node still runs)',
    'note': 'the control render is the whole instrument. Without it `lt_applied` cannot tell a bad LoRA from an unloaded one, which is exactly the mistake the 2026-09-23 diagnosis found.',
}

PROMPTS = {
    'char': 'Cornelis, a shipwright of fifty, standing on the Kattenburg quay at dusk, 1671, full figure, 35mm',
    'char_newpose': 'Cornelis seated on an upturned barrel, both arms raised above his head, seen from the side, 1671',
    'style': 'a wooden treadwheel harbour crane on a quay under a grey sky, 1671',
    'object': 'a single tin lantern standing on a plank table in a dark loft, one candle inside it',
    'creature': 'a grey wolf standing in profile on open winter ground, whole animal in frame, daylight',
    'unrelated': 'a bowl of pears and a pewter jug on a linen cloth, daylight from a window, no people',
}

COND = {
    'repeats': 3,
    'seeds': RENDER['seeds'],
    'strength': RENDER['strength'],
    'note': 'three seeds, one render each, per arm of the comparison',
}

ARTEFACT_ROWS = ['simpletuner_flux', 'simpletuner_sdxl', 'simpletuner_klein', 'kohya']
TRAINING_ROWS = ['simpletuner_flux', 'simpletuner_sdxl', 'simpletuner_klein']


def _p(pid, title, feeds, checks, rows, fixture, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': fixture, 'prompt': None, 'train': dict(TRAIN), 'render': dict(RENDER)},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'lt_applied',
        'The LoRA reaches the render at all',
        ['applied'],
        [
            {'check': 'image_distance', 'metric': 'lpips', 'to': 'lt_applied.control', 'min': 0.15},
            {
                'check': 'operator',
                'blind': True,
                'question': 'These two pictures came from the same prompt and the same seed. Are they pictures of DIFFERENT people? yes/no (no = the LoRA changed nothing)',
            },
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        conditions={**COND, 'arms': ['lora at 0.8', 'no lora node in the graph']},
        state_rule={'yes': 1.0, 'partial': 0.34},
        state_note=(
            'all three seeds must move. THIS IS THE STANDING BUG COLUMN: ComfyUI applied no LoRA in this '
            'stack until 2026-09-23, and an lpips of ~0 against the control is what that looked like. '
            'The operator arm exists because a LoRA can move lpips by changing the light and nothing else.'
        ),
    ),
    _p(
        'lt_alpha',
        'Alpha survives export',
        ['alpha'],
        [
            {'check': 'safetensors_key_present', 'key_suffix': '.alpha', 'share': 1.0},
            {'check': 'safetensors_alpha_matches_trained', 'expect': TRAIN['lora_alpha']},
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        conditions={'repeats': 1, 'note': 'a file read; repeating it cannot change the answer'},
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'share must be 1.0, not "any alpha present". SimpleTuner\'s flux2 writer MIXES key forms — '
            'diffusers `.lora.down.weight` on the double blocks, PEFT `.lora_A.weight` on the single ones — '
            'and the first stamper treated "any .alpha" as done, so half the modules loaded at 2x forever '
            'and the half-stamped file looked finished to every later check.'
        ),
    ),
    _p(
        'lt_likeness',
        'Produces the trained likeness',
        ['likeness'],
        [
            {'check': 'identity_cosine_to_set_min', 'ref_set': DS_CHAR, 'min': 0.45},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Beside this reference sheet of the character: is the person in this picture the same person? yes/no',
            },
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        state_note=(
            'ArcFace against the MEAN of the 24 dataset faces, not against one still, so a lucky angle cannot '
            'carry the cell. 0.45 is the house identity-QC bar for a generated still against a reference set; '
            'the operator arm decides everything ArcFace does not see (age, build, costume, the wrong man with '
            'the right face geometry).'
        ),
    ),
    _p(
        'lt_strength',
        'Strength lever behaves',
        ['strength'],
        [
            {
                'check': 'image_distance_monotonic',
                'metric': 'lpips',
                'rungs': [0.4, 0.6, 0.8, 1.0],
                'step_min': 0.02,
                'share': 0.67,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this picture burnt — blown highlights, plastic skin, melted detail, or the subject duplicated? yes/no (yes fails, and the rung it happened on is the usable ceiling)',
            },
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        conditions={**COND, 'rungs': [0.4, 0.6, 0.8, 1.0], 'repeats': 3},
        state_note=(
            '4 rungs x 3 seeds = 12 renders + the control. The ladder must RISE: a lever that is connected but '
            'flat (every rung equidistant from the control) is the unstamped-alpha signature, because the file '
            'is already at 2x by 0.5 and saturates. Read this cell only after lt_alpha.'
        ),
    ),
    _p(
        'lt_char',
        'Trains a character',
        ['char_lora'],
        [
            {'check': 'file_exists', 'path': '<the row export>/pytorch_lora_weights.safetensors'},
            {'check': 'identity_cosine_to_set_min', 'ref_set': DS_CHAR, 'min': 0.45},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the person in this picture the character on the reference sheet, at the right age and build? yes/no',
            },
        ],
        TRAINING_ROWS,
        DS_CHAR,
        state_note='one full training run on the 24-still character set, then three renders. The export check is first because a run that OOMs at step 900 leaves a checkpoint and no export, and that is a no, not an untested.',
    ),
    _p(
        'lt_style',
        'Trains a style',
        ['style_lora'],
        [
            {'check': 'image_distance', 'metric': 'lpips', 'to': 'lt_style.control', 'min': 0.25},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Beside these four reference frames of the Arcane look: is this picture in that same painterly style — the brush texture, the palette, the edge treatment? yes/no',
            },
            {'check': 'open_vocab_present', 'terms': ['wooden crane', 'quay'], 'min_score': 0.3},
        ],
        TRAINING_ROWS,
        DS_STYLE,
        state_note=(
            'the subject is deliberately NOT in the style dataset (a crane, where the frames are people), so a '
            'style LoRA that has memorised its subjects fails the GroundingDINO arm while passing the look arm. '
            'No mechanical judge of "is this the Arcane look" exists on this box, so that half is blind operator.'
        ),
    ),
    _p(
        'lt_object',
        'Trains an object or prop',
        ['object_lora'],
        [
            {'check': 'open_vocab_count', 'query': 'lantern', 'count': 1, 'min_score': 0.35},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Beside these reference photographs of one particular tin lantern: is the lantern in this picture that same object — same shape, same panes, same handle? yes/no',
            },
        ],
        TRAINING_ROWS,
        DS_OBJECT,
        state_note='an object LoRA has the easiest mechanical arm (the thing is either there once or it is not) and the hardest operator arm (a generic lantern passes the detector and fails the question).',
    ),
    _p(
        'lt_creature',
        'Trains a non-human body plan',
        ['creature_lora'],
        [
            {
                'check': 'detector_count',
                'class': 'dog',
                'count': 1,
                'note': 'YOLOv8x-COCO has no wolf class; it reads a wolf as `dog`. The check is "one four-legged canid, whole, not two and not none" — the species question belongs to the operator.',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Beside these reference frames of the grey wolf: is this a wolf rather than a dog, with four legs, one tail and one head? yes/no',
            },
        ],
        TRAINING_ROWS,
        DS_CREATURE,
        state_note="the body-plan column. A creature LoRA fails here by adding a fifth leg or a second tail, and no local VLM sees either reliably (defect bench 2026-09-27: 2/8 on the hard cases), so the count question is the operator's.",
    ),
    _p(
        'lt_overfit',
        'Does not overfit to the dataset pose',
        ['overfit'],
        [
            {'check': 'pose_distance_min', 'ref_set': DS_CHAR, 'min': 0.35},
            {'check': 'identity_cosine_to_set_min', 'ref_set': DS_CHAR, 'min': 0.45},
            {
                'check': 'operator',
                'blind': True,
                'question': 'The prompt asked for: seated on a barrel, both arms raised above the head, seen from the side. Is the figure in this picture doing that? yes/no',
            },
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        state_note=(
            'a NEW pose the dataset does not contain. Both arms must move: a LoRA that holds identity by '
            'reproducing the dataset pose passes ArcFace and fails pose_distance, which is the whole point of '
            'measuring the two together rather than asking "does it look overfit".'
        ),
    ),
    _p(
        'lt_bleed',
        'Does not bleed into unrelated prompts',
        ['bleed'],
        [
            {'check': 'image_distance', 'metric': 'lpips', 'to': 'lt_bleed.control', 'max': 0.18},
            {
                'check': 'detector_count',
                'class': 'person',
                'count': 0,
                'note': 'the prompt names no people; a character LoRA at 0.8 that puts its face on a still life is the loudest bleed there is',
            },
            {'check': 'open_vocab_present', 'terms': ['pears', 'jug'], 'min_score': 0.3},
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        state_note=(
            'the inverse of lt_applied and measured against the same kind of control: the picture must stay '
            'SIMILAR with the LoRA loaded. 0.18 sits above the seed-to-seed floor of the base model and below '
            "the 0.25 a style LoRA moves a frame by. Read with the shared bank: the bank's 132 subjects are "
            'rendered on this row WITH the LoRA at 0.8, so the bank is bleed measured 396 times.'
        ),
    ),
    _p(
        'lt_stack',
        'Stacks with another LoRA',
        ['stackable'],
        [
            {'check': 'image_distance', 'metric': 'lpips', 'to': 'lt_stack.char_only', 'min': 0.10},
            {'check': 'identity_cosine_to_set_min', 'ref_set': DS_CHAR, 'min': 0.40},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this picture BOTH the character on the reference sheet AND in the Arcane painterly style? yes/no (either one missing is a no)',
            },
        ],
        ARTEFACT_ROWS,
        DS_CHAR,
        conditions={
            **COND,
            'strength': 0.7,
            'arms': ['char 0.7 + style 0.7', 'char 0.7 only', 'style 0.7 only'],
            'repeats': 3,
        },
        state_note='both at 0.7, because two adapters at 0.8 burn even when stacking works. The identity bar is loosened to 0.40: a style LoRA legitimately costs some ArcFace cosine, and refusing to allow that would score every successful stack as a failure.',
    ),
    _p(
        'lt_dataset_size',
        'Images needed',
        ['dataset_size'],
        [
            {
                'check': 'metric_rises_with_rung',
                'metric': 'identity_cosine',
                'rungs': [8, 16, 24],
                'tolerance': 0.03,
                'gain_min': 0.08,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Beside the reference sheet: is the person in this picture the same person? yes/no (the smallest rung where this is yes on all three seeds is the answer the sheet wants)',
            },
        ],
        TRAINING_ROWS,
        DS_08,
        conditions={
            **COND,
            'rungs': [8, 16, 24],
            'datasets': [DS_08, DS_16, DS_CHAR],
            'repeats': 3,
            'note': 'the 24 rung IS the lt_char run and is not trained twice',
        },
        state_note='the ladders are nested subsets (the 8 are the first 8 of the 16, which are the first 16 of the 24), so the rungs differ by dataset size and by nothing else. Two extra training runs per row.',
    ),
    _p(
        'lt_dataset_quality',
        'Survives an imperfect dataset',
        ['dataset_quality'],
        [
            {'check': 'identity_cosine_to_set_min', 'ref_set': DS_CHAR, 'min': 0.45},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this picture soft, smeared or out of focus compared with the clean-dataset picture beside it? yes/no (yes = the blur was learned, which fails)',
            },
        ],
        TRAINING_ROWS,
        DS_BLUR,
        state_note=(
            'the same 24 stills with 4 of them Gaussian-blurred (sigma 2.0 at 1024) — a realistic bad harvest, '
            'not a destroyed set. Scored against the CLEAN dataset mean, so learning the blur shows up as a '
            'likeness that holds while the render goes soft, which is why the operator arm asks about softness '
            'and not about identity.'
        ),
    ),
    _p(
        'lt_resume',
        'Training resumes after a stop',
        ['resume_train'],
        [
            {'check': 'file_exists', 'path': '<the row export>/pytorch_lora_weights.safetensors'},
            {'check': 'file_sha256_equals', 'path': '<the resumed export>', 'to': '<the uninterrupted lt_char export>'},
            {
                'check': 'safetensors_key_present',
                'key_suffix': '.alpha',
                'share': 1.0,
                'note': 'the alpha stamp runs at the end of a run; a resumed run that skips it is a different kind of failure from one that does not resume',
            },
        ],
        TRAINING_ROWS,
        DS_CHAR,
        conditions={
            'repeats': 1,
            'kill_at_step': 600,
            'seed': TRAIN['seed'],
            'note': 'SIGTERM the trainer at step 600 of 1200 (the checkpoint interval is min(250, steps//4) = 250, so 500 is the last checkpoint), then start again with the same char_id and settings',
        },
        state_rule={'yes': 1.0, 'partial': 0.34},
        state_note=(
            'sha256 equality is the strict form and may legitimately fail on a non-deterministic optimiser; '
            'when it does, the cell is `partial` on the strength of the export existing and being stamped, and '
            'the note records the hash pair. It is written as the strict check anyway because "it resumed" '
            'without a byte comparison is the claim that hid the half-stamped file.'
        ),
    ),
]

DERIVE = {
    'time': {
        'from': (
            "wall minutes from the trainer's own status file: lora_trainer_service writes start_time and step, "
            'and _progress_fields derives the rate; take (last step ts - start ts) for the lt_char run at 1200 '
            'steps on 24 images, and report minutes AND seconds-per-step so a different step count can be read '
            'off it. Excludes the dataset build and the VAE cache pass, which are reported beside it.'
        ),
        'grade': 'measured',
        'unit': 'count',
    },
    'storage': {
        'from': (
            'MB of the exported safetensors, plus the checkpoint directory the run leaves behind. Measured on '
            'disk, not predicted: at rank 64 the SDXL exports in the ComfyUI store are ~186 MB '
            '(abel_arcane_sdxl_kohya 186117640 B, zygchar_0015c8a3f2e3 185962648 B), and rank 128 produced '
            '418 MB, so the cell must say which rank it measured.'
        ),
        'grade': 'measured',
        'unit': 'count',
    },
}

LOOKUP = {
    'caption': {
        'source': "the dataset's own .txt sidecars plus lora_trainer_service's caption writer and --caption_dropout_probability",
        'revision': 'lora_trainer_service.py as of 2026-09-30; the Gray Wolf set at '
        + SRC_CREATURE
        + '/contact_sheet is the layout receipt (ref_NN.png beside ref_NN.txt)',
        'requires': ['lora_trainer_service.py', SRC_CREATURE + '/contact_sheet'],
        'grade': 'receipt',
        'value': {
            'sidecar': 'one <image>.txt per image, same stem',
            'form': 'trigger-token first, then the description ("character reference sheet" is the default tail the writer will overwrite)',
            'dropout': 0.10,
            'note': 'caption_dropout 0.10 (raised from 0.05 on 2026-07-18) exists because trigger-first captions otherwise make the LoRA depend on the exact trigger phrasing.',
        },
        'state_note': 'YES — the recipe is fixed in code and visible on disk as sidecars. This is a receipt, not a measurement: it says what captioning WAS used, not that it is the best available.',
    },
    'trainer_licence': {
        'source': f'{ZYG_SIMPLETUNER_DIR}/LICENSE (verified on disk 2026-09-30, file level, not a web claim)',
        'revision': 'GNU AFFERO GENERAL PUBLIC LICENSE Version 3, 19 November 2007',
        'requires': [ZYG_SIMPLETUNER_DIR + '/LICENSE'],
        'grade': 'receipt',
        'value': {
            'licence': 'AGPL-3.0',
            'clause': (
                '"The GNU Affero General Public License is designed specifically to ensure that ... the '
                'modified source code becomes available to the community. It requires the operator of a '
                'network server to provide the source code of the modified version running there to the '
                'users of that server."'
            ),
            'reading': (
                'AGPL-3 reaches the TRAINER, not the weights it produces: a LoRA is not a derivative '
                'work of the training script. The obligation bites only if SimpleTuner itself — modified '
                '— were exposed over a network to users. It is not: it runs as a local subprocess out of '
                f'{ZYG_SIMPLETUNER_DIR} and nothing in crews serves it. So the trained LoRAs ship '
                'and the trainer does not.'
            ),
        },
        'state_note': 'The cell is the licence and the clause, not a yes/no. The sheet\'s hint ("AGPL trainers cannot ship") is about shipping the TRAINER; it must not be read as "the LoRAs cannot ship".',
    },
}

# ── rows ───────────────────────────────────────────────────────────────────────────────
KOHYA_WHY = (
    'kohya (sd-scripts) is NOT INSTALLED on this box — there is no kohya_ss or sd-scripts tree and the only '
    'mention anywhere in crews is a key-name comment in lora_trainer_service.stamp_lora_alpha. The '
    '*_sdxl_kohya.safetensors files in the ComfyUI store were trained elsewhere, so this row can be measured '
    'as an ARTEFACT but no training run can be started for it, which is what this column needs.'
)
KOHYA_NA = {
    c: KOHYA_WHY
    for c in (
        'style_lora',
        'char_lora',
        'object_lora',
        'creature_lora',
        'overfit',
        'dataset_size',
        'dataset_quality',
        'resume_train',
        'time',
    )
}
KOHYA_NA.update(
    {
        'caption': 'the kohya LoRAs were trained off this box before any dataset receipt existed; no captions, sidecars or dropout setting are recoverable from the .safetensors, so the captioning strategy cannot be stated rather than guessed.',
        'trainer_licence': 'the house licence policy is file-level verification — quote the clause from the LICENSE on disk. kohya/sd-scripts is not on disk here, so its licence would have to be asserted from memory of a web page, which is exactly what the policy forbids. Install it and this becomes a lookup.',
    }
)

TEST = {
    'step': 'lora_train',
    'version': '2026-09-30.1',
    'title': 'Four fixed datasets, one control render, and the two silent failures first',
    'purpose': (
        'Measure whether a trained LoRA reaches the render, at the gain it was trained at, and what it can '
        "learn — every column as a comparison against the same render with no LoRA, the dataset's own faces, "
        'or the same run resumed, so a disconnected lever can never read as a bad trainer again.'
    ),
    'include_shared': 'image',
    'train': TRAIN,
    'render': RENDER,
    'prompts': PROMPTS,
    'rows': {
        'simpletuner_flux': {
            'transport': 'service',
            'where': f'lora_trainer_service.LoraTrainerService.start_training(model_family="flux") -> SimpleTuner at {ZYG_SIMPLETUNER_DIR}',
            'model': 'SimpleTuner FLUX LoRA train (models.json 2011, vram_required_mb 30000) on FLUX.1-dev, base_model_precision int8-quanto',
        },
        'simpletuner_sdxl': {
            'transport': 'service',
            'where': 'lora_trainer_service.LoraTrainerService.start_training(model_family="sdxl")',
            'model': 'SimpleTuner SDXL LoRA train (models.json 2012, vram_required_mb 18000); trains against the stabilityai/stable-diffusion-xl-base-1.0 diffusers layout, renders through the Juggernaut-XL v9 production checkpoint',
            'budget': {
                'calls': 80,
                'minutes': 290,
                'gpu_minutes': 275,
                'note': 'the cheapest trainer: SDXL at 18 GB runs ~1.2 s/step, so 1200 steps is ~24 min + ~6 min load and VAE cache = ~30 min a run x 8.5 runs = 255 min, + 66 measurement renders at ~10 s = 11 min.',
            },
        },
        'simpletuner_klein': {
            'transport': 'service',
            'where': 'lora_trainer_service.LoraTrainerService.start_training(model_family="klein") -> _write_st_config_klein, SimpleTuner --model_family flux2 --model_flavour klein-4b',
            'model': 'SimpleTuner klein LoRA train (models.json 2025, ~24 GB) on FLUX.2 [klein] base 4B bf16 — the FLUX.1-dev exit for stills and LoRA training (2026-08-25)',
            'budget': {
                'calls': 80,
                'minutes': 380,
                'gpu_minutes': 365,
                'note': '4B bf16 at ~1.8 s/step: 1200 steps ~36 min + ~6 min load = ~42 min a run x 8.5 = 357 min, + 66 renders at ~12 s = 13 min. This is the row whose MIXED key forms lt_alpha exists to catch.',
            },
        },
        'kohya': {
            'transport': 'service',
            'where': f'no trainer on this box — the row is the existing artefacts in {LORA_DIR}/*_sdxl_kohya.safetensors, applied through the SDXL production workflow',
            'model': 'Kohya-trained SDXL LoRAs: zygchar_0015c8a3f2e3_sdxl_kohya.safetensors (the character pair whose dataset IS on disk at '
            + SRC_CHAR
            + ', so lt_likeness has a reference set), abel_arcane_sdxl_kohya.safetensors, cornelis_arcane_sdxl_kohya.safetensors',
            'na': KOHYA_NA,
            'budget': {
                'calls': 34,
                'minutes': 22,
                'gpu_minutes': 18,
                'operator_minutes': 12,
                'note': 'no training runs at all: 3 safetensors reads + ~31 SDXL renders (applied A/B 6, strength ladder 12, likeness 3, bleed 6, stack 9 minus the shared controls) at ~10 s = ~6 min + ~10 min checkpoint and LoRA load churn. 24 blind decisions x 30 s = 12 min.',
            },
        },
    },
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': DS_CHAR,
            'verified': False,
            'blocks': [
                'likeness',
                'char_lora',
                'overfit',
                'dataset_size',
                'dataset_quality',
                'stackable',
                'applied',
                'strength',
                'bleed',
            ],
            'generated': (
                'mkdir -p '
                + DS_CHAR
                + ', then copy the first 24 APPROVED cells of '
                + SRC_CHAR
                + '/contact_sheet/cells (approval flag in '
                + SRC_CHAR
                + '/character_bible.json) into '
                + DS_CHAR
                + ' as 000.png..023.png, longest side 1024, and write one 000.txt..023.txt sidecar '
                "each in the production form (trigger token first, then the bible's description) exactly as "
                "lora_trainer_service's caption writer does. Then write MANIFEST.json holding the 24 source "
                'cell paths and their sha256.'
            ),
            'how_to_verify': (
                'look at all 24 stills: every one must be the same person, in focus, face visible, no '
                'duplicate of another cell, no other person in frame. Then compute the ArcFace mean '
                "embedding over the 24 and check each still's cosine to it is >= 0.55 (a still below that "
                'is a different face and poisons every likeness cell). Record the mean in MANIFEST.json '
                'and set verified = true.'
            ),
        },
        {
            'path': DS_STYLE,
            'verified': False,
            'blocks': ['style_lora', 'stackable'],
            'generated': (
                '24 frames of the Arcane look cut from the approved arcane restyle output (the '
                'arcane_prev_v5 / training_arcane_sdxl sets under ' + SRC_CHAR + ' are the approved source), '
                'resized to 1024 longest side with one .txt sidecar each naming the style token and NOT the '
                'subject — a style dataset that names its people trains a character.'
            ),
            'how_to_verify': (
                'confirm the 24 frames show at least 6 DIFFERENT subjects (a style set with one subject is a '
                'character set) and that the four reference frames the operator is shown for lt_style are '
                'four of these 24, chosen and written into MANIFEST.json before any run.'
            ),
        },
        {
            'path': DS_OBJECT,
            'verified': False,
            'blocks': ['object_lora'],
            'generated': (
                '24 pictures of ONE tin lantern: the approved lantern prop cells from the asset library '
                '(asset_library_service props query "tin lantern", the approved variant only), 8 angles x 3 '
                'lighting states, 1024 longest side, one .txt sidecar each naming the object token.'
            ),
            'how_to_verify': 'confirm all 24 are the SAME lantern (same number of panes, same handle, same dents) and that no two are the same render at a different crop; set verified = true.',
        },
        {
            'path': DS_CREATURE,
            'verified': False,
            'blocks': ['creature_lora'],
            'generated': (
                'cp the 24 ref_NN.png + ref_NN.txt pairs from ' + SRC_CREATURE + '/contact_sheet (Gray Wolf, '
                'Canis lupus — already in SimpleTuner layout, sidecars and aspect-ratio bucket metadata '
                'included) into ' + DS_CREATURE + ', renaming to 000..023 and keeping each caption byte-exact.'
            ),
            'how_to_verify': 'count legs, tails and heads on all 24 by eye — the body-plan column is worthless if the dataset itself carries a five-legged frame. Set verified = true.',
        },
        {
            'path': DS_BLUR,
            'verified': False,
            'blocks': ['dataset_quality'],
            'generated': (
                'cp -r ' + DS_CHAR + ' ' + DS_BLUR + ' then Gaussian-blur exactly 004.png, 009.png, 014.png and '
                '019.png with sigma 2.0 at 1024 (Pillow ImageFilter.GaussianBlur(2.0)), leaving the other 20 '
                'and all 24 sidecars untouched.'
            ),
            'how_to_verify': 'confirm exactly 4 of 24 are blurred and they are those four; the clean dataset must be verified first, since this one inherits its answer key.',
        },
        {
            'path': DS_08,
            'verified': False,
            'blocks': ['dataset_size'],
            'generated': 'the first 8 stills of '
            + DS_CHAR
            + ' with their sidecars — a nested subset, so the rungs differ by size and nothing else',
            'how_to_verify': 'confirm it is exactly 000..007 of the verified 24, byte-identical (sha256 against the parent MANIFEST.json).',
        },
        {
            'path': DS_16,
            'verified': False,
            'blocks': ['dataset_size'],
            'generated': 'the first 16 stills of ' + DS_CHAR + ' with their sidecars',
            'how_to_verify': 'confirm it is exactly 000..015 of the verified 24, byte-identical.',
        },
        {
            'path': LORA_DIR + '/zygchar_0015c8a3f2e3_sdxl_kohya.safetensors',
            'verified': True,
            'generated': "already on disk — the kohya row's artefact, and the one kohya LoRA whose dataset is also on disk ("
            + SRC_CHAR
            + "), which is why it and not abel_arcane is the row's likeness subject",
        },
        {
            'path': ZYG_SIMPLETUNER_DIR + '/LICENSE',
            'verified': True,
            'generated': 'already on disk — the AGPL-3 text trainer_licence quotes its clause from',
        },
    ],
    'budget': {
        'calls': 80,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a LoRA trainer takes images, captions and numeric hyperparameters; no language model is called anywhere on this step, so no tokens are spent and the shared Claude week is not touched',
        'minutes': 560,
        'gpu_minutes': 540,
        'operator_minutes': 24,
        'note': (
            'Per row, defaulting to simpletuner_flux (the most expensive trainer; the other three override). '
            'TRAINING RUNS, which are the whole cost: lt_char 1 + lt_style 1 + lt_object 1 + lt_creature 1 + '
            'dataset_size rungs 8 and 16 = 2 (the 24 rung IS lt_char) + dataset_quality 1 + lt_resume 1.5 (a run '
            'killed at step 600 plus a full resumed run) = 8.5 runs. FLUX at int8-quanto, 1024 pixel_area, batch 1 '
            'with gradient checkpointing is ~2.5 s/step, so 1200 steps = 50 min, + ~10 min for the VAE/text-encoder '
            'cache pass and model load = ~60 min a run; 8.5 x 60 = 510 GPU min. MEASUREMENT RENDERS: applied A/B '
            "2x3=6, strength 4 rungs x3=12, likeness 3, bleed 2x3=6, stack 3 arms x3=9, overfit 3, the four kinds' "
            'operator sheets 4x3=12, dataset_size 3x3=9, dataset_quality 3, controls 3 = ~66 renders at ~20 s = 22 '
            'GPU min. Plus 8 safetensors/status reads (CPU seconds). 80 calls, ~540 GPU min, ~560 min wall — call '
            'it a NINE-HOUR row, and four rows is two days of GPU before the bank. OPERATOR: 48 blind decisions '
            '(applied 3, likeness 3, strength 12, four kinds 12, overfit 3, stack 3, dataset_size 9, quality 3) x '
            '30 s = 24 min. SHARED IMAGE BANK for this step, on top and per row: the bank renders 132 subjects x 3 '
            "seeds = 396 pictures, and on a lora_train row they are rendered WITH that row's trained character "
            'LoRA at 0.8 (which is what makes the bank meaningful here — it is `bleed` measured 396 times), ~132 '
            "GPU min at 20 s on FLUX and ~66 min at 10 s on SDXL, plus the bank's ~82 capacity/prompt/attribute "
            "probes at ~3 renders each = ~246 more renders, ~82 GPU min. The bank's operator cost is the real "
            'number to look at before scheduling: ~500 blind decisions x 30 s = ~250 min A ROW. Tree total for the '
            'four rows: ~1250 GPU min of training + ~600 GPU min of bank renders + ~17 operator hours. '
            'NOT included and one-time: cutting and verifying the seven datasets (~90 min of operator time), '
            'without which nine of the fourteen domain columns stay BLOCKED.'
        ),
    },
    'run_order': [
        'lt_alpha',
        'storage',
        'trainer_licence',
        'caption',
        'lt_applied',
        'lt_bleed',
        'lt_strength',
        'lt_likeness',
        'lt_char',
        'time',
        'lt_overfit',
        'lt_stack',
        'lt_style',
        'lt_object',
        'lt_creature',
        'lt_dataset_quality',
        'lt_dataset_size',
        'lt_resume',
    ],
    'notes': [
        'READ lt_alpha AND lt_applied BEFORE ANY OTHER CELL ON THIS SHEET. Both are silent failures that look exactly like a bad trainer: no LoRA applied at all (stack-wide until 2026-09-23) and alpha lost on export (every unstamped adapter at 2x). A sheet whose lt_applied is no is a sheet of renders with no LoRA in them.',
        'kohya is an artefact row, not a retired one. The LoRAs are in production; the trainer is simply not on this box, so nine columns are na with that reason and seven are measured on the files. Installing sd-scripts turns those nine into probes with no other change.',
        'run_order is built so the first four entries need no GPU at all: a safetensors read, a stat, and two file reads. After those, lt_applied and lt_bleed reuse one pair of renders, so the two columns that decide whether the sheet is readable cost ~12 renders and no training run.',
        'The shared bank is not decoration on this step. Its 132 subjects rendered through the trained LoRA are the widest bleed measurement the house can make, and the answer to "what did this character LoRA cost the base model\'s ability to draw a hand" is in the bank\'s Render: The body band, not in lt_bleed.',
        'SeedVR2 is deliberately not a row here and RealESRGAN is not either — this step trains adapters. The finishing upscaler lives on the upscale sheet.',
    ],
}
