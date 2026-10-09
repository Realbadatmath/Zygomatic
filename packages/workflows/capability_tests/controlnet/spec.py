# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The row condition notes and the TEST dict the sheet runner reads.

Moved verbatim out of the old single-file controlnet.py (lines 599-1021).
"""

from __future__ import annotations

from capability_tests.controlnet.constants import (
    BEAUTY,
    BROKEN,
    GARBAGE,
    MAPS,
    MASK,
    TRUTH,
)
from capability_tests.controlnet.probes import PROBES


# ── rows ───────────────────────────────────────────────────────────────────────────────────
SINGLE_DEPTH = (
    'controlnet-depth-sdxl.safetensors is a SINGLE-CONDITION checkpoint trained on depth maps: '
    'there is no other conditioning head in the file to feed this channel into. The row is not '
    'weak here, it has no such mode — the union row is where this channel is asked.'
)
SINGLE_POSE = (
    'controlnet-openpose-sdxl.safetensors is a SINGLE-CONDITION checkpoint trained on pose skeletons: '
    'there is no other conditioning head in the file to feed this channel into. The row is not weak '
    'here, it has no such mode — the union row is where this channel is asked.'
)
NOT_CN_HEAD = (
    'Inpaint and reference are not ControlNet conditioning heads in this architecture: inpaint needs '
    'an inpainting model with a mask input and reference needs an image adapter. The qwen_cn and '
    'klein_ref rows are where those two channels are asked.'
)
INPAINT_ONLY = (
    'This row IS the inpaint control (the InstantX inpaint ControlNet inside '
    'hand_fixer_qwen_inpaint.json): it takes an image and a mask, not a depth, pose, edge, normal, '
    'segmentation or scribble plate. There is no such input on the node to feed.'
)
REF_DEPTH_ONLY = (
    'klein_refcontrol.json carries the FLUX.2 klein refcontrol DEPTH LoRA: its two inputs are a '
    'reference image and a depth plate. No pose, edge, normal, segmentation, scribble or mask '
    'input exists on this path to feed.'
)
NO_COMBINE = (
    'Combining needs two conditioning inputs that can be stacked in one workflow. This row exposes a '
    'single conditioning input in its production path, so there is no second control to combine with '
    'it; the sdxl pair and the union row are where this column is answered.'
)

TEST = {
    'step': 'controlnet',
    'version': '2026-09-30.1',
    'title': 'One mannequin plate, re-extracted from the render and compared with itself',
    'purpose': (
        'Measure whether conditioning constrains the render, mechanically, against a control set that '
        'has a ground truth: the mannequin pass plates from geom/conditioning.py and the cascade pose '
        "from geom/char_control.py. The sheet's standing NO on controls taken from old pictures is a "
        'probe here, run beside the good control on the same prompt and the same seeds, so the gap '
        'between them is the measurement.'
    ),
    'include_shared': 'image',
    'rows': {
        'depth_sdxl': {
            'transport': 'comfy',
            'model': 'controlnet-depth-sdxl.safetensors',
            'where': 'the SDXL depth ControlNet in the ComfyUI store, driven on sdxl_txt2img.json '
            'with a ControlNetApplyAdvanced node',
            'na': {
                'pose_ok': SINGLE_DEPTH,
                'edge_ok': SINGLE_DEPTH,
                'normal_ok': SINGLE_DEPTH,
                'seg_ok': SINGLE_DEPTH,
                'scribble_ok': SINGLE_DEPTH,
                'inpaint_ok': NOT_CN_HEAD,
                'ref_ok': NOT_CN_HEAD,
            },
        },
        'openpose_sdxl': {
            'transport': 'comfy',
            'model': 'controlnet-openpose-sdxl.safetensors',
            'where': 'the SDXL pose ControlNet in the ComfyUI store, driven on sdxl_txt2img.json '
            'with a ControlNetApplyAdvanced node',
            'na': {
                'depth_ok': SINGLE_POSE,
                'edge_ok': SINGLE_POSE,
                'normal_ok': SINGLE_POSE,
                'seg_ok': SINGLE_POSE,
                'scribble_ok': SINGLE_POSE,
                'inpaint_ok': NOT_CN_HEAD,
                'ref_ok': NOT_CN_HEAD,
            },
            'note': 'the row whose NAME is the licence question: the checkpoint was trained on '
            'OpenPose-convention skeletons, but the house never loads an OpenPose model '
            'to make one. extractor_clean is where that is written down',
        },
        'union_flux': {
            'transport': 'comfy',
            'model': 'ControlNet Union Pro (FLUX) — models.json 2009, in_use, 6 GB',
            'where': 'the Union Pro FLUX ControlNet in the ComfyUI store, driven on the house FLUX '
            'txt2img graph with one ControlNetApplyAdvanced node per mode',
            'na': {'inpaint_ok': NOT_CN_HEAD, 'ref_ok': NOT_CN_HEAD},
            'budget': {
                'minutes': 210,
                'gpu_minutes': 205,
                'note': 'FLUX sampling runs about 2x SDXL per 1024 render, so the same 718 '
                'renders cost roughly 210 minutes of wall clock on this row',
            },
            'note': 'the only row asked for all six plate channels. Where a mode does not exist in '
            'the checkpoint the workflow cannot be built, the probe is a transport failure '
            'and the runner writes untested with that error — this test does not guess which '
            'heads Union Pro ships',
        },
        'qwen_cn': {
            'transport': 'comfy',
            'model': 'InstantX Qwen-Image inpaint ControlNet',
            'where': '_comfy_workflows/hand_fixer_qwen_inpaint.json',
            'na': {
                'depth_ok': INPAINT_ONLY,
                'pose_ok': INPAINT_ONLY,
                'edge_ok': INPAINT_ONLY,
                'normal_ok': INPAINT_ONLY,
                'seg_ok': INPAINT_ONLY,
                'scribble_ok': INPAINT_ONLY,
                'ref_ok': INPAINT_ONLY,
                'combine': NO_COMBINE,
                'constrains': 'The constrains probe scores a render against a depth or pose plate '
                'this row has no input for. What "follows the control" means here is '
                'the mask, and that is inpaint_ok — measured with '
                'mask_outside_unchanged rather than with a re-extracted channel.',
                'garbage_in': 'The poor control this column is about is an extracted depth or pose '
                'plate, and this row takes neither. The equivalent question for an '
                'inpaint control is a poor mask, which the inpaint sheet asks as '
                'mask_source and mask_soft.',
            },
            'budget': {
                'minutes': 60,
                'gpu_minutes': 57,
                'note': 'this row runs one domain probe (cn_inpaint_ok, 3 renders) plus the '
                'shared bank; the bank is what costs the hour of Qwen sampling',
            },
        },
        'klein_ref': {
            'transport': 'comfy',
            'model': 'FLUX.2 klein refcontrol depth LoRA',
            'where': '_comfy_workflows/klein_refcontrol.json',
            'na': {
                'pose_ok': REF_DEPTH_ONLY,
                'edge_ok': REF_DEPTH_ONLY,
                'normal_ok': REF_DEPTH_ONLY,
                'seg_ok': REF_DEPTH_ONLY,
                'scribble_ok': REF_DEPTH_ONLY,
                'inpaint_ok': REF_DEPTH_ONLY,
                'combine': NO_COMBINE,
            },
            'budget': {
                'minutes': 210,
                'gpu_minutes': 205,
                'note': 'FLUX.2 klein at 1024: about 2x SDXL per render over the same 718 '
                'renders, so roughly 210 minutes on this row',
            },
            'note': 'a LoRA, which puts it squarely inside the 2026-09-23 finding: every claim about '
            'this row recorded before convert_lora.py has to be re-run, not re-read. '
            'cn_extract_quality and cn_constrains are what re-run it',
        },
    },
    'probes': PROBES,
    'derive': {
        'res_match': {
            'from': (
                "the trial's own record: the control map width and height against the render width and "
                'height, and the resampling the workflow applied between them. yes when every trial fed '
                'the map at the render resolution with no resample; partial when the map was resampled '
                'but the factor and filter are recorded; no when a trial resampled silently or the sizes '
                'were recorded as unknown.'
            ),
            'grade': 'measured',
            'unit': 'wxh',
            'note': 'A derive, not a probe: the answer is already in the queue record and rendering pictures to '
            'find it out would cost GPU minutes for a number the workflow JSON states. The mannequin '
            'plates are written at 1024 square so that the no-resample case is the default and any '
            "resample is the row's own doing.",
        },
    },
    'lookup': {
        'extractor_clean': {
            'grade': 'receipt',
            'answer': {
                'depth_sdxl': 'CLEAN. The production control is RENDERED depth from geom/conditioning.py — the Z '
                'pass of the pass set, no estimator model in the chain at all, so there is no '
                'preprocessor licence to clear. Where a depth map must come from a photograph '
                'instead, the pinned checkpoint is Depth-Anything-V2-SMALL (Apache-2.0); the Base '
                'and Large checkpoints are CC-BY-NC-4.0 and are OUT under house rules, which cost '
                "a day's work on 2026-08-03 to establish.",
                'openpose_sdxl': 'CLEAN, and this is the row where that is worth reading carefully. The '
                'CHECKPOINT was trained against OpenPose-convention skeletons, but the house '
                'never runs the CMU OpenPose implementation (non-commercial) to make one, and '
                "DWPose is banned here for its dataset. The plate is the house cascade's "
                '33-point skeleton DRAWN in the OpenPose colour convention '
                '(geom/char_control.py: "From the cascade, not from an NC OpenPose model"); '
                'scoring the render re-extracts joints with MediaPipe pose_landmarker '
                '(Apache-2.0). A colour convention is not a licence.',
                'union_flux': 'CLEAN for the channels this test feeds it: all six plates are rendered '
                '(geom/conditioning.py for depth, normal, lineart and segmentation from the Z, '
                'normal and IndexOB passes; geom/char_control.py for pose). The union SDXL '
                'sibling xinsir/controlnet-union-sdxl-1.0 is Apache-2.0 and is the model those '
                'four maps were written for; the licence of the FLUX Union Pro weights themselves '
                'is a weights question and belongs to weights_pinned, not to this column.',
                'qwen_cn': 'CLEAN. The preprocessor is a MASK, produced by the house hand_qc path from the '
                "render's own landmarks — no third-party extractor model is loaded.",
                'klein_ref': 'CLEAN. Both inputs are house-produced: the reference is a render and the depth '
                'plate is the rendered Z pass. No estimator.',
            },
            'requires': [
                'geom/conditioning.py lines 1-40 — the four rendered maps and the Depth-Anything-V2 licence '
                'split (Base/Large CC-BY-NC-4.0, out; Small Apache-2.0, pinned 2026-08-03)',
                "geom/char_control.py lines 16-20 and 42-44 — the pose plate is the cascade's 33-point "
                'skeleton in the OpenPose colour convention, explicitly not from an NC OpenPose model',
                'the source_url and revision of each preprocessor the operator must paste in before this cell '
                "is graded: https://github.com/DepthAnything/Depth-Anything-V2 (the Small checkpoint's own "
                'model card, with the commit), https://ai.google.dev/edge/mediapipe/solutions/vision/'
                'pose_landmarker (the pinned .task file and its revision), and '
                'https://huggingface.co/xinsir/controlnet-union-sdxl-1.0 for the four rendered-map conventions',
            ],
            'note': 'A LOOKUP, not a probe: a licence is read, not rendered. It is graded `receipt` rather than '
            '`vendor` because the operative facts are in-house code paths — which extractor each row '
            'actually uses — with the vendor licences underneath them. The cell is not graded until the '
            'three source_urls above carry their revision, and this test does not fill them in from '
            'memory: data/models.json records name, slug, vram and in_use for entries 2006-2009 and no '
            'licence field at all, so there is nothing in the registry to copy.',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': MAPS['depth'],
            'verified': False,
            'blocks': ['constrains', 'depth_ok', 'combine', 'strength', 'end_step', 'extract_quality', 'overpower'],
            'generated': (
                'python3 -m zyg_workflows.geom.conditioning <the mannequin pass set dir> -o '
                'capability_tests/fixtures/image/controlnet/ — writes depth.png, normal.png, lineart.png '
                'and segment.png together; rename each to mannequin_<name>.png. The pass set is the '
                'standing mannequin the project_ledger_permanent_route work already renders'
            ),
            'how_to_verify': (
                'The operator lays the plate beside mannequin_beauty.png and confirms in writing: one '
                'standing figure, whole body inside the frame, near = white, the background not '
                'crushing the figure into one value. Until then constrains and extract_quality are '
                'written untested "key unverified" — a control we have not checked cannot be the ruler '
                'everything else is measured with.'
            ),
        },
        {
            'path': MAPS['normal'],
            'verified': False,
            'blocks': ['normal_ok'],
            'generated': 'the same geom.conditioning run; normal.png renamed. Camera-space, (n*0.5+0.5)*255',
            'how_to_verify': 'The operator confirms the plate is in the normalBAE convention (a figure facing the '
            'camera reads mid-blue) and shows the same figure as the beauty render.',
        },
        {
            'path': MAPS['edge'],
            'verified': False,
            'blocks': ['edge_ok'],
            'generated': 'the same geom.conditioning run; lineart.png renamed — edges from depth and normal '
            'discontinuity, not image gradients',
            'how_to_verify': 'The operator confirms the lines follow where the surface turns or steps and do not '
            'trace surface texture.',
        },
        {
            'path': MAPS['seg'],
            'verified': False,
            'blocks': ['seg_ok'],
            'generated': 'the same geom.conditioning run; segment.png renamed — one flat colour per object index '
            'from the IndexOB pass',
            'how_to_verify': 'The operator confirms each region is one flat colour and that the regions correspond '
            'to the parts named in mannequin_truth.json.',
        },
        {
            'path': MAPS['pose'],
            'verified': False,
            'blocks': ['pose_ok', 'constrains', 'combine'],
            'generated': (
                'python3 -m zyg_workflows.geom.char_control <the same mannequin pass set dir> — writes the 33-point '
                'skeleton in the OpenPose colour convention from the cascade; rename pose.png to '
                'mannequin_pose.png. NOT from an OpenPose model'
            ),
            'how_to_verify': (
                "The operator confirms the skeleton's limbs match the beauty render's limbs and "
                'that the joint coordinates in mannequin_truth.json are the ones drawn. A pose plate '
                'whose joints disagree with the truth file would make pose_keypoint_error_max measure '
                'the plate rather than the render.'
            ),
        },
        {
            'path': MAPS['scribble'],
            'verified': False,
            'blocks': ['scribble_ok'],
            'generated': (
                'python3 -c "from PIL import Image; import PIL.ImageFilter as F; '
                "im=Image.open('capability_tests/fixtures/image/controlnet/mannequin_lineart.png')"
                '.resize((128,128), Image.BILINEAR).resize((1024,1024), Image.BILINEAR)'
                '.point(lambda v: 255 if v > 90 else 0); '
                "im.save('capability_tests/fixtures/image/controlnet/mannequin_scribble.png')\" — the "
                'lineart coarsened to a sketch by a round trip through 128 px and a hard threshold'
            ),
            'how_to_verify': 'The operator confirms the result reads as a loose sketch of the same figure — the '
            'limbs still identifiable, the fine lines gone.',
        },
        {
            'path': BEAUTY,
            'verified': False,
            'blocks': ['ref_ok', 'extract_quality'],
            'generated': 'the beauty pass of the same mannequin pass set, saved as PNG at 1024 square',
            'how_to_verify': 'The operator confirms it is the same frame every plate was extracted from — the '
            'comparison in extract_quality is meaningless otherwise.',
        },
        {
            'path': TRUTH,
            'verified': False,
            'blocks': ['extract_quality', 'constrains'],
            'generated': (
                'written by the same geom.conditioning / geom.char_control run: the normalised Z buffer '
                'of the frame and the 33 joint positions in pixel coordinates, as JSON. This is the '
                "renderer's own record, not a measurement of the plates"
            ),
            'how_to_verify': (
                'The operator spot-checks five joints against the beauty render by eye and confirms '
                'the Z range covers the figure and not the background. This file is the GROUND TRUTH '
                'of the whole sheet; it blocks the two columns that use it as a ruler.'
            ),
        },
        {
            'path': GARBAGE,
            'verified': False,
            'blocks': ['garbage_in'],
            'generated': (
                'python3 -c "import arcane_restyle as A; A.extract_depth(\'<one of the pre-rebuild '
                "ledger_intro stills>', 'capability_tests/fixtures/image/controlnet/"
                'garbage_depth.png\')" — a depth map ESTIMATED by Depth-Anything-V2-Small from one of '
                'the old low-quality pictures the project_ledger_permanent_route work replaced. The '
                'still must be one of the originals, not a rebuild'
            ),
            'how_to_verify': (
                'The operator confirms two things in writing: the source still is one of the '
                'pre-rebuild pictures, and the estimated plate is visibly wrong about the figure '
                '(a dark recess read as far, limbs merged into the background). A plate that turned '
                'out fine would make this probe measure nothing and the receipt on the sheet says '
                'the opposite, so the mismatch would need explaining before the run.'
            ),
        },
        {
            'path': BROKEN,
            'verified': False,
            'blocks': ['inpaint_ok'],
            'generated': (
                'python3 -c "import hand_qc_service as H; H.export_defect_fixture(source='
                "'capability_tests/fixtures/image/controlnet/mannequin_beauty.png', out="
                "'capability_tests/fixtures/image/controlnet/mannequin_broken_hand.png')\" — the beauty "
                'render with one hand replaced by a six-fingered render of the same crop, so the defect '
                'is real and localised rather than painted in'
            ),
            'how_to_verify': 'The operator confirms MediaPipe hand_landmarker does NOT find five clean fingertips '
            'on the source, i.e. the fixture really carries the defect the probe is meant to fix.',
        },
        {
            'path': MASK,
            'verified': False,
            'blocks': ['inpaint_ok'],
            'generated': (
                'python3 -c "import hand_qc_service as H; H.export_hand_mask('
                "'capability_tests/fixtures/image/controlnet/mannequin_broken_hand.png', "
                "'capability_tests/fixtures/image/controlnet/mannequin_hand_mask.png')\" — the hand mask "
                'the production hand_fixer path would build for that frame, at the same 1024 square'
            ),
            'how_to_verify': 'The operator confirms the mask covers the hand and a little of the wrist and nothing '
            'else — a generous mask would let a passing row repaint the arm and still score.',
        },
    ],
    'budget': {
        'calls': 718,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'No language model is called: every row is a ComfyUI workflow and every prompt in this '
        'file is a fixed string stored here, not text a model is asked to write.',
        'minutes': 150,
        'gpu_minutes': 145,
        'operator_minutes': 60,
        'note': (
            '76 domain renders per row: constrains 3, garbage_in 3, strength 5 rungs x 3 = 15, end_step 5 x 3 '
            '= 15, combine 3, depth_ok 3, pose_ok 3, edge_ok 3, normal_ok 3, seg_ok 3, scribble_ok 3, '
            'inpaint_ok 3, ref_ok 3, overpower 3 styled + 3 unstyled = 6 — and extract_quality adds NO '
            'renders at all (it compares the plates with the truth file, 3 CPU passes). A row that is na on '
            'five channels pays about 61 of those. THE SHARED IMAGE BANK IS THE BULK: 214 probes x 3 seeds = '
            '642 renders per row, 89 % of the total. 718 renders at about 12 s of SDXL sampling = 144 GPU '
            'minutes plus roughly 5 minutes of ControlNet and checkpoint loading = 150 wall; the three FLUX '
            'rows override to 210. Operator: 45 domain blind decisions (3 each on twelve probes, 6 on '
            'strength and end_step laid out as ladders, 6 on garbage_in which asks two questions, 3 on '
            "inpaint) plus the bank's own share, at 30 s each = about 60 minutes. No Claude or API meter "
            'is touched by this test.'
        ),
    },
    'run_order': [
        'cn_extract_quality',
        'res_match (a record read, no render)',
        'cn_constrains',
        'cn_garbage_in',
        'cn_strength',
        'cn_end_step',
        'cn_combine',
        'cn_depth_ok',
        'cn_pose_ok',
        'cn_edge_ok',
        'cn_normal_ok',
        'cn_seg_ok',
        'cn_scribble_ok',
        'cn_inpaint_ok',
        'cn_ref_ok',
        'cn_overpower',
        'the shared image bank last',
    ],
    'notes': [
        'RUN ORDER IS LOAD-BEARING. cn_extract_quality costs no sampler and decides whether the ruler is '
        'straight; res_match is read out of the queue record. Both run before a single picture is made. The '
        '642-render shared bank goes last so a partial run still fills the seventeen columns this sheet exists '
        'for.',
        'The prompt never describes the pose. If it did, a row could score on constrains by obeying the text '
        'encoder and ignoring the control, and the whole sheet would be measuring prompt fidelity — which is '
        "the t2i sheet's job.",
        "garbage_in is the sheet's existing measured NO, kept as a probe so it stays reproducible. It runs the "
        'SAME prompt and seeds as cn_constrains with only the control swapped, so the two states are directly '
        'comparable and the difference is attributable to the control alone.',
        'No local VLM judges any picture here. On the 2026-09-27 defect bench the best local model scored 34/40 '
        'on a global question and 2/8 on the hard cases, and "are these five fingers" is a hard case: it goes to '
        'MediaPipe hand_landmarker and to a blind operator, never to a VLM.',
        'A ControlNet that only nudges is the failure mode this test is built to catch, and the two ladders are '
        'where it shows: a flat strength ladder is the conditioning form of the 2026-09-23 never-applied defect, '
        'and the measured span goes in the note so the operator can see how flat.',
    ],
}
