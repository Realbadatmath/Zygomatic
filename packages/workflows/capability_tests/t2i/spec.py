# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LOOKUP, DERIVE and the TEST dict the sheet runner reads.

Moved verbatim out of the old single-file t2i.py (lines 814-1121).
"""

from __future__ import annotations

from capability_tests.image_shared import NEGATIVE
from zyg_workflows.paths import ZYG_COMFY_LORA_DIR

from capability_tests.t2i.constants import (
    LORA_PAIRING,
    NO_LORA_REASON,
    STYLE_LABELS,
)
from capability_tests.t2i.probes import PROBES


LOOKUP = {
    'res_native': {
        'requires': [
            'the publisher stated training resolution for the weights this row loads, '
            'with the model card URL and the date it was read',
            'the width and height in the EmptyLatentImage / EmptyFlux2LatentImage / '
            'EmptySD3LatentImage node of the row own workflow JSON under '
            '_comfy_workflows/ (node 30 in all four graphs on this sheet)',
        ],
        'rule': 'the native square the row was trained at, and beside it the size the HOUSE '
        'actually queues. Both, because they can differ and the second is what the '
        'sheet is for. All four t2i graphs ship 1024x1024 at node 30 (read '
        '2026-09-30); a publisher figure that disagrees is the finding.',
        'grade': 'vendor',
        'grade_note': 'vendor, not receipt: the training resolution is the publisher word and '
        'nothing on this machine can check it. The queued size beside it IS a '
        'receipt, and the trial keeps them apart.',
    },
    'lora_pairing': {
        'requires': [
            f'the listing of {ZYG_COMFY_LORA_DIR} with each '
            'file base architecture, taken from the adapter own metadata or its '
            'training receipt rather than from its filename',
            'for each adapter, the checkpoint it was TRAINED against, from the trainer '
            'record (lora_trainer_service.py output / lora_attest.py attestation)',
        ],
        'rule': 'which base checkpoint each trained adapter belongs to, for the row own base. A '
        'row with no adapter trained for it gets "none on this machine", which is an '
        'ANSWER and not a gap. The table below is the state of the store on 2026-09-30 '
        'and is the starting point, not the receipt: the run must re-read the folder and '
        'take each pairing from the adapter own record, because a kohya file for '
        'sd_xl_base_1.0 LOADS on Juggernaut and DynaVisionXL without complaint and the '
        'filename cannot tell the reader that it does not belong there.',
        'table': LORA_PAIRING,
        'grade': 'receipt',
    },
}

DERIVE = {
    'first_take': {
        'from': [
            'the FIRST repeat (seed 11) of every subject probe in the image bank',
            'the FIRST repeat (seed 11) of every domain probe in this module',
        ],
        'rule': 'the share of cells whose whole mechanical-and-operator key passes on seed 11 '
        'alone, over the 132 bank subjects AND the 24 domain probes, reported as two '
        'numbers and their combined share. The house standard is the first take and not '
        'the best of three, so this is read off repeat one and nothing else.',
        'grade': 'measured',
        'note': 'This OVERRIDES the image bank derive of the same name, which counts the 132 '
        'subjects only. On this step the domain probes are the sheet headline question '
        '("a usable first take from a prompt alone") and leaving them out of the number '
        'would make first_take mean "can it draw a barrel" rather than "can it follow a '
        'brief". The two numbers are kept apart in the trial so a t2i first_take can '
        'still be compared with an i2i one.',
    },
}

_FLUX_DEV_WEIGHT = (
    '_comfy_workflows/flux_txt2img.json loads unet_name flux1-dev.safetensors at node 10, and '
    'that file is NOT in the ComfyUI store on this machine (unet/, diffusion_models/ and '
    'checkpoints/ read 2026-09-30 hold flux1-schnell but no flux1-dev). Every cell on this row '
    'will therefore come back as a TRANSPORT failure — untested, with the ComfyUI loader error '
    'as the note — until the weight is fetched. That is not a `no`: the model was never heard. '
    'FLUX.1-dev is also non-commercial, so `licence` is expected to be the answer that matters '
    'on this row whatever the pictures look like.'
)

TEST = {
    'step': 't2i',
    'version': '2026-09-30.1',
    'title': 'One prompt set, seven checkpoints, first take only',
    'purpose': (
        'Measure which checkpoint gives a usable first take from a prompt alone: how '
        'much of a long brief lands, whether the negative and the LoRA levers are '
        'connected, whether hands, faces, eyes, limbs, teeth, crowds and props survive, '
        'and what the style and resolution levers really do — at byte-identical '
        'settings across every row.'
    ),
    'include_shared': 'image',
    'negative': NEGATIVE,
    'style_labels': STYLE_LABELS,
    'lora_pairing': LORA_PAIRING,
    'rows': {
        'flux_dev': {
            'transport': 'comfy',
            'where': '_comfy_workflows/flux_txt2img.json',
            'model': 'flux1-dev.safetensors + t5xxl_fp8_e4m3fn + clip_l + flux_ae',
            'note': _FLUX_DEV_WEIGHT,
            'na': {'lora_effect': NO_LORA_REASON},
            'budget': {
                'minutes': 360,
                'gpu_minutes': 355,
                'note': 'FLUX.1-dev at 25 XlabsSampler steps and 1024x1024 is '
                '~25 s a render on this card, so ~850 renders is ~6 h of '
                'GPU. Schedule it alone and overnight. If the weight is '
                'still missing the whole row costs one failed load and '
                'nothing else — check that first.',
            },
        },
        'flux_schnell': {
            'transport': 'comfy',
            'where': '_comfy_workflows/flux_txt2img.json with unet_name flux1-schnell.safetensors at node 10',
            'model': 'flux1-schnell.safetensors (in diffusion_models/, unet/ and checkpoints/ on 2026-09-30)',
            'note': 'A distilled 4-step model driven through the dev graph: node 31 '
            'steps and true_gs are the dev defaults (25, 3.5) and are WRONG '
            'for schnell. The run must record what it actually queued, and '
            'the steps ladder uses schnell own 1/2/4/8 rungs.',
            'na': {'lora_effect': NO_LORA_REASON},
            'budget': {
                'minutes': 70,
                'gpu_minutes': 68,
                'note': '~4 s a render at 4 steps: ~850 renders is a little '
                'over an hour. The cheapest row on the sheet and the '
                'right one to run first, to shake the runner out.',
            },
        },
        'klein': {
            'transport': 'comfy',
            'where': '_comfy_workflows/klein_txt2img.json',
            'model': 'flux-2-klein-base-4b.safetensors + qwen_3_4b CLIP + flux2-vae (FLUX.2 klein 4B, Apache-2.0)',
            'note': 'The licence-clean FLUX on this box: klein 4B is Apache-2.0 while the '
            'FLUX.2 9B and dev weights are non-commercial and denied by the '
            'licence gate (project_klein_pathway). Graph: 20 Flux2Scheduler steps, '
            'cfg 5.0 through CFGGuider, euler, seed at node 32 RandomNoise.',
            'na': {
                'lora_effect': 'The only klein adapter in the store is '
                'flux2_klein_4b_refcontrol_depth.safetensors, a depth reference-control '
                'adapter that needs a depth reference image to do anything at all. An '
                'A/B at 0.8 without one would measure the reference path and report it '
                'as the LoRA lever, which is worse than leaving the cell empty. No '
                'style or character LoRA trained for klein 4B exists on this machine '
                '(loras/ read 2026-09-30), so there is nothing here to A/B.'
            },
            'budget': {
                'minutes': 130,
                'gpu_minutes': 127,
                'note': '4B at 20 steps and 1024x1024 is ~8 s a render: ~850 renders is a little over two hours.',
            },
        },
        'sdxl_jugg': {
            'transport': 'comfy',
            'where': '_comfy_workflows/sdxl_txt2img.json',
            'model': 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors (the ckpt_name the graph ships at node 10)',
            'note': 'The house production SDXL. Graph: 30 steps, cfg 6.0, dpmpp_2m, '
            'karras, seed at node 31. Note for lora_effect: the adapter is an '
            'sd_xl_base_1.0 kohya file and will load here without complaint — '
            'the lever is what is measured, the mismatch is what lora_pairing '
            'reports.',
        },
        'sdxl_base': {
            'transport': 'comfy',
            'where': '_comfy_workflows/sdxl_txt2img.json with ckpt_name sd_xl_base_1.0.safetensors at node 10',
            'model': 'sd_xl_base_1.0.safetensors',
            'note': 'The reference row for the whole image family: the base every '
            'house kohya LoRA was trained against, and the row the bank '
            'subject fixtures for i2i / inpaint / controlnet / upscale / '
            'identity are generated from. Run this row before any image-IN '
            'step is scheduled.',
        },
        'qwen_image': {
            'transport': 'comfy',
            'where': '_comfy_workflows/qwen_txt2img.json',
            'model': 'qwen_image_2512_fp8_e4m3fn.safetensors + qwen_2.5_vl_7b_fp8 CLIP + qwen_image_vae (Apache-2.0)',
            'note': 'Graph: 20 steps, cfg 2.5, euler, simple, AuraFlow shift 3.1 at '
            'node 26, seed at node 31. The only row on this sheet whose text '
            'encoder is a VL model rather than CLIP, so it is the one row '
            'where the 89-word `prompt` probe is not truncated — read its '
            '`prompt` cell against the SDXL rows knowing that.',
            'na': {
                'lora_effect': 'The two qwen adapters in the store (qwen_edit_2509_multiple_angles, '
                'qwen_edit_skin) are EDIT adapters for qwen_image_edit and have no '
                'text-to-image path; loading one over qwen_image_2512 would measure '
                'a mismatch, not the lever. No t2i LoRA trained for qwen_image '
                'exists on this machine (loras/ read 2026-09-30).'
            },
            'budget': {
                'minutes': 290,
                'gpu_minutes': 286,
                'note': 'A 20B fp8 unet at 20 steps is ~20 s a render on this '
                'card: ~850 renders is a little under five hours. '
                'Second only to flux_dev; schedule it overnight.',
            },
        },
        'dynavision': {
            'transport': 'comfy',
            'where': '_comfy_workflows/sdxl_txt2img.json with ckpt_name DynaVisionXL.safetensors at node 10',
            'model': 'DynaVisionXL.safetensors',
            'note': 'A stylised SDXL merge, in the store but with no production call '
            'site found — `wired` is expected to be a no and the lookup must '
            'name the file that would have to change. Its `style` and '
            '`photoreal` pair is the interesting cell: a merge that only ever '
            'renders its own look has no style lever.',
        },
    },
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': {},
    'na': {},
    'fixtures': [],
    'run_order': [
        't_seed_stable',
        't_text_in_frame',
        't_counts_together',
        't_relations_together',
        't_objects',
        't_composition',
        't_depth',
        't_negative_removes',
        't_lora_effect',
        't_steps',
        't_aspect',
        't_res_high',
        't_hands',
        't_limbs',
        't_faces',
        't_eyes',
        't_teeth',
        't_crowds',
        't_light',
        't_style',
        't_photoreal',
        't_style_consistency',
        't_period_look',
        't_long_prompt',
        'BANK: the four Prompt bands, Counting, Space, Attributes, the four universal probes',
        'BANK: the Capacity ladders',
        'BANK: the 132 subject renders (396 frames) — LAST',
    ],
    'run_order_note': (
        'Cheap and wholly mechanical first, so a run that is stopped early still fills cells that '
        'need no operator. t_seed_stable is first of all: it is 3 renders and it decides whether '
        'the A/B cells below it (negatives, lora_effect, steps) can be read at all. The levers '
        'come next, then the resolution ladders, then the anatomy and style columns that need the '
        'operator, then the 89-word prompt probe (the most expensive operator question on the '
        'step, six blind decisions a frame). The bank 396 subject renders are LAST because they '
        'are two thirds of the GPU time and none of the domain cells depend on them — except '
        'first_take, which reports the two halves separately for exactly this reason.'
    ),
    'budget': {
        'calls': 850,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': (
            'No language model is called on this step: a comfy row is a workflow JSON '
            'queued against the ComfyUI server and the prompt is a fixed string in '
            'this file, not a completion. The only token-shaped cost is the CLIP / T5 '
            '/ Qwen-VL text encode inside the render, which is paid in the render '
            'seconds already counted under minutes.'
        ),
        'minutes': 150,
        'gpu_minutes': 145,
        'operator_minutes': 325,
        'note': (
            'Per row: 94 DOMAIN renders (19 probes x 3 seeds = 57, plus t_negative_removes '
            '2 variants x 3 = 6, t_lora_effect 2 x 3 = 6, t_aspect 3 ratios x 3 = 9, '
            't_style_consistency 4 subjects x 3 = 12, t_steps 4 rungs x 1 seed = 4) plus the '
            'SHARED IMAGE BANK: 132 subjects x 3 seeds = 396 renders, plus ~350 more across '
            'the four Prompt bands, Counting, Space, Attributes, the Capacity ladders and '
            'the four universal probes (u_deterministic 3, u_failsafe 1, u_degrades 12, '
            'u_offline 3). ~850 renders a row. At ~10 s a render (SDXL at 30 steps, '
            '1024x1024, this card) that is ~142 min of GPU, so 150 wall / 145 GPU as the '
            'default; flux_schnell (70), klein (130), qwen_image (290) and flux_dev (360) '
            'override it. ACROSS SEVEN ROWS THAT IS ~5950 RENDERS AND ~19 GPU HOURS — one '
            'GPU, one queue, so they serialise: this is a week of overnight runs, not an '
            'afternoon, and the operator should see that before scheduling. Operator: 396 '
            'subject decisions + ~100 domain decisions (26 written operator checks, most x 3 '
            'seeds, t_long_prompt alone 6 x 3 = 18) + ~150 across the bank prompt, space, '
            'attribute and capacity probes = ~650 blind yes/no at 30 s = ~325 min a row, '
            '~38 h over seven rows. No Claude week is spent: there is no claude_cli or '
            'anthropic_api row on this step. Tokens 0 — see tokens_note.'
        ),
    },
    'notes': [
        'first_take is the column this sheet exists for and it is a SHARE read off seed 11 only, '
        'across both the bank subjects and the 24 domain probes. The house already believes in '
        'first-take-not-retries, which is what the sheet own next_tests asked for; this test '
        'scores exactly that and keeps the two halves apart in the trial.',
        'flux_dev cannot run until flux1-dev.safetensors is in the ComfyUI store. The row is kept '
        'and NOT marked retired: a missing weight is a transport failure (untested with the '
        'loader error), and calling it retired would throw away a sheet row over a download.',
        'lora_effect is na on four of seven rows and the reason is the same each time: no '
        'text-to-image adapter trained for that base exists on this machine. The three SDXL rows '
        'all use abel_arcane_v2_sdxl_kohya at 0.8, which LORA_PAIRING pairs with sd_xl_base_1.0 '
        'only — so sdxl_jugg and dynavision are deliberately being driven off-model, because the '
        'column asks whether the lever is connected and not whether the adapter suits the base.',
        'Three thresholds are FIXED here rather than derived, and changing any of them is a '
        'different test: lora_effect LPIPS >= 0.15 (the lever moved the picture), '
        'style_consistency pairwise CLIP distance <= 0.22 (four subjects, one hand), and '
        'res_high fingertip separation 18 px at 1536 against 12 px at 1024 (the threshold scales '
        'with the frame or it is looser than the probes below it).',
        'Four cells are OPERATOR-LED and say so on the cell rather than in a footnote: light (no '
        'shadow-direction detector exists), eyes (no symmetry detector, and the InsightFace '
        'landmarks would invent one), teeth (a smear is invisible to every detector here) and '
        'depth (the box gradient is real and is not depth). The 2026-09-27 defect bench is why: '
        '34/40 on the global question, 2/8 on the hard cases.',
        'The 89-word `prompt` probe is the only prompt on this step past the bank 60-word rule, '
        'and on the three SDXL rows the 77-token CLIP encoder will cut its tail without a word. '
        'That IS the column ("follows a long prompt") and the trial records the token count and '
        'the fact the cut landed on, so the cell can be read beside pd_max_soft, pd_truncation_loud '
        'and pd_clip77 in the bank. qwen_image is the one row whose VL encoder reads all of it.',
        'This step is where the bank subject_fixtures come from: row sdxl_base, seed 11, the '
        'frames the operator passed. Until that row is run and those 132 files exist and are '
        'verified, every render_* column on i2i, inpaint, controlnet, upscale and identity stays '
        'blocked. sdxl_base is therefore the row to schedule first after flux_schnell.',
    ],
}
