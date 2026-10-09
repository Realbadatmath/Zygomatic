# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Pixel gates (pixel_gates). 2026-09-30.

Question the sheet asks: "What can arithmetic catch that a vision model cannot?"
Verdict already on the sheet: the pixel gates catch exactly the two faults every VLM missed
— identity drift and a photographic patch in a painting. Its stated limitation is the one
this test is built around: "a gate only sees what it was pointed at. fill_check's miss was
not a threshold error but a band in the wrong place — a gate can be exactly right and still
look elsewhere."

Shape of the test. Every row is an ARITHMETIC gate: two pictures in, a number out. There is
no prompt, no question and no name it could return, so the whole recognition half of the
judge bank (the 132 `Sees:` subjects, the 132 `Names:` subjects, counting, space and
attributes) is `na` at STEP level with one written reason — running a subject bank against
a chroma distance would manufacture 264 empty cells. What is left is a GATE test: for each
fault we plant it in an approved Second Ledger still, keep the untouched twin beside it, and
measure both halves — the gate must FLAG the planted twin and LEAVE the clean twin alone. A
gate that flags everything is not a gate, so `false_alarm` (12 clean twins, zero flags) is
scored as hard as the catches, and `region` asks the sheet's own limitation as a number: did
the gate flag the place the fault is actually in (IoU >= 0.5 with the planted box)?

Two faults are planted on purpose where the previous take failed. `seams` is planted twice:
3 px INSIDE fill_check's +-4 px matte_raw band and 3 px OUTSIDE it, at matte_raw + 7 px,
which is exactly the take-4 defect the v4 docstring describes ("THE SEAM THE OTHER FOUR
NUMBERS CANNOT SEE"). The honest expected result on the outside twin is `no` for a gate that
has not moved its band, and the test says so rather than quietly using the inside twin only.
`gameable` plants noise matched to the plate's own per-channel statistics with the WRONG
content behind it: look_gate is expected to score `no` there, because a high AuraFace cosine
on an insane tile is the standing content-truth hole on this stack.

What is blocked. Nothing here has been rendered. The twelve planted twins and their clean
counterparts are declared with the exact PIL/OpenCV recipe that makes them and are
`verified: False`: until the operator has looked at the contact sheet once and confirmed
that the identity twin really sits near cosine 0.5 and the photographic patch really reads
photographic, the columns those twins feed are written `untested — key unverified`.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_HOME

# ── check kinds this module adds (the runner implements exactly these) ───────────────
CHECK_KINDS = {
    'gate_flags_planted': 'the gate run on the PLANTED twin reports a failure (non-zero exit, or its `verdict` field is fail) AND the same gate on the matched CLEAN twin reports a pass; both halves must hold or the trial is a fail — a gate that flags both is not measured as a catch',
    'gate_passes_clean': 'the gate run on a CLEAN twin reports a pass (no flag, exit 0); every flag on a clean twin is a false alarm and fails the trial',
    'gate_rejects_gamed': 'the gate run on the GAMED twin (per-channel mean, std and high-pass std matched to the clean plate, content deliberately wrong) reports a FAILURE; passing the gamed twin fails the trial, so the column reads with its caption — yes = cannot be gamed by texture',
    'report_contains': "the gate's JSON report has the key `field` and its value matches `pattern` (regex, case-insensitive); the number or term the decision was taken on is in the OUTPUT, not only in the source",
    'region_iou_min': "IoU between the region the gate flagged (the box or mask in its report field `field`) and the fixture key's planted `region` is >= `min`",
    'gate_frames_complete': "the gate run over the fixture clip's `frames` frames returns one verdict per frame with no error, and the set of flagged frame indices equals the fixture key's `frames_planted` exactly",
    'ladder_last_rung': "the ladder is run from the top rung down; the column records the LAST rung at which the trial's inner check still held (here: the gate still separated the planted twin from its clean twin), and the state rule is applied to whether that rung reaches `floor`",
}

# ── fixtures ─────────────────────────────────────────────────────────────────────────
#: The Second Ledger intro tree the twins are cut from; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')
LEDGER = LEDGER_INTRO + '/intro'
FX = 'capability_tests/fixtures/gates/pixel'
MAKER = FX + '/make_pixel_twins.py'
MANIFEST = FX + '/MANIFEST.json'
TWINS = FX + '/twins'
CLEAN = FX + '/clean'

# The twelve planted faults. Each is one PLANTED png (or clip) plus the untouched CLEAN
# twin it was made from, plus a `region` box in the MANIFEST. The sources are the approved
# Second Ledger masters (intro/final/README.md): intro/shots/p{1..5}/picture_v6.png,
# composed.png, bg.png, matte_raw.png. Nothing below is executed in this task.
RECIPE = (
    'python3 ' + MAKER + ' --out ' + FX + ' --all. The script is pure PIL + OpenCV + numpy over the '
    'approved masters under ' + LEDGER + '/shots/p{1..5}/ and writes MANIFEST.json with, per fault, the '
    'planted png, the clean twin it was copied from and the planted `region` box in pixels. The twelve: '
    '(1) identity — paste the Cornelis face crop from p3/picture_v6.png (box 467,177,746,520), resized to '
    'the Abel face box of p4/picture_v6.png (667,141,933,470), with a 9 px feathered alpha; '
    '(2) photo — paste the photographic Qwen hand crop from p4/_t12_hands_d0.70_s3.png (box '
    '860,830,1300,1050) over the same box of the approved p5/picture_v4.png page hand, 9 px feather; '
    '(3) seam_inside — on p1: take bg.png, and on the ring dist(matte_raw) in [0,4] px add a constant +14 '
    "levels to all channels (a hard rim INSIDE fill_check's +-4 px band); "
    '(4) seam_outside — the identical +14-level rim on the ring dist(matte_raw) in [7,11] px, i.e. 3 px '
    'OUTSIDE that band and inside the 4..24 px zone the v4 docstring calls "nobody\'s band"; '
    '(5) grain — on p2/bg.png, resample the fill region (dist(matte_raw) < 12) to 50 % and back with '
    'cv2.INTER_AREA / INTER_CUBIC, which halves the grain scale and leaves the mean untouched; '
    '(6) colour — on p3/picture_v6.png, convert the fill region to HSV and add 15 deg to H (uint8 +11 on '
    'the OpenCV 0..179 hue scale), wrapping; '
    '(7) texture — on p4/bg.png, Gaussian-blur the fill region with sigma 3 (the half-repainted Telea '
    'smudge the fill_check texture term was written for); '
    '(8) luma — on p5/bg.png, multiply the WHOLE plate by 1.12 in linear light and clip (a plate-level '
    'lift, so it also crosses the 18 px plate-law line); '
    '(9) blank_black — a 1920x1080 all-zero png; '
    '(10) corrupt_png — the first 40 % of the bytes of p1/picture_v6.png written to a .png (a truncated '
    'file, not a valid image); '
    '(11) gamed — on p1/bg.png, replace the fill region with Gaussian noise whose per-channel mean, std '
    "and sigma-3 high-pass std are matched to the CLEAN fill's, then paste a downscaled crop of "
    'p3/picture_v6.png (the wrong subject) at 12 % opacity so the content is wrong and the statistics are '
    'right; (12) video — 10 frames at 1920x1080 from p4/composed.png, with fault (6) applied to frame 6 '
    'only, muxed with ffmpeg -framerate 25 -c:v libx264 -crf 12. '
    'The CLEAN set is a byte copy of the untouched source of each of the twelve.'
)

# Fixed run conditions. An arithmetic gate has no temperature and no seed; the repeats are
# here to catch a gate that is not deterministic (it must be, and the derive column says so).
COND = {
    'repeats': 3,
    'temperature': None,
    'seed': 'n/a (deterministic arithmetic)',
    'resolution': 'the master resolution, 1920x1080; the runner never resizes',
    'image_format': 'png sRGB, 8 bit, read with cv2.IMREAD_COLOR as the gates do',
    'note': 'three identical runs per twin; a gate that differs between them fails `deterministic`',
}

ALL = ['look_gate', 'patch_gate', 'fill_check', 'plate_law']
LOOK, PATCH, FILL, PLATE = ['look_gate'], ['patch_gate'], ['fill_check'], ['plate_law']


def _p(pid, title, feeds, fault, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': MANIFEST + '#' + fault,
            'planted': TWINS + '/' + fault,
            'clean': CLEAN + '/' + fault,
            'prompt': None,
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


FLAG = [{'check': 'gate_flags_planted'}]

PROBES = [
    # ── What it catches (8) ──
    _p(
        'identity',
        'Catches a face at the wrong identity',
        ['identity'],
        'identity',
        FLAG,
        LOOK,
        state_note='the planted twin carries the Cornelis face on an Abel plate; look_gate must drop below its own identity band and the clean twin must stay above it',
    ),
    _p(
        'photo',
        'Catches a photographic patch in a painting',
        ['photo'],
        'photo',
        [
            {'check': 'gate_flags_planted'},
            {
                'check': 'report_contains',
                'field': 'dab',
                'pattern': r'^\d+(\.\d+)?$',
                'note': 'the chroma distance the decision was taken on must be in the report',
            },
        ],
        PATCH + FILL,
        state_note='the calibration this is measured against: every Qwen hand scored dab >= 5.74 and both painted controls passed (p4 v4 quill hand 4.38, approved p5 page hand 2.63) — so a planted photographic patch must land above the 4.5 hard bound',
    ),
    _p(
        'seams',
        'Catches a fill seam — inside AND outside its band',
        ['seams'],
        'seam',
        [
            {'check': 'gate_flags_planted', 'fixture': 'seam_inside'},
            {'check': 'gate_flags_planted', 'fixture': 'seam_outside'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Looking at the two plates at 1:1 with no labels, is a hard rim visible around the figure in each? yes/no',
            },
        ],
        FILL + PLATE,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'TWO twins, both must be caught for `yes`. seam_outside plants the identical rim at matte_raw + 7..11 px, '
            "which is the take-4 defect: fill_check's `seam` band is matte_raw +-4 px, the inpaint mask is the matte "
            "dilated 12 and the paste ramps 7..21 px out, so the real boundary lives at 4..24 px, in nobody's band. "
            'The honest expected result for a fill_check whose `line`/`seam_ratio_hole` terms are not enabled is NO on '
            'this column — half the twins caught, `partial`. That is the number this sheet exists to record.'
        ),
    ),
    _p(
        'grain',
        'Catches a grain-scale error',
        ['grain'],
        'grain',
        FLAG,
        PATCH + FILL,
        state_note='the fill grain is resampled to half scale with the mean untouched, so only a frequency term can see it: patch_gate `tex` and fill_check `texture`',
    ),
    _p(
        'colour_gate',
        'Catches a wrong colour',
        ['colour_gate'],
        'colour',
        FLAG,
        LOOK + PATCH + FILL,
        state_note='+15 deg of hue on the fill region: patch_gate reads it as LAB (a,b) distance, fill_check as a tone step, look_gate through its palette band',
    ),
    _p(
        'texture_gate',
        'Catches a texture mismatch',
        ['texture_gate'],
        'texture',
        FLAG,
        PATCH + FILL,
        state_note='sigma-3 blur over the fill — the half-repainted Telea smudge that sits at the right level with no hard rim, which is exactly why fill_check has a texture term at all',
    ),
    _p(
        'luma',
        'Catches a luminance mismatch',
        ['luma'],
        'luma',
        FLAG,
        FILL + PLATE,
        state_note='the whole plate lifted 12 %: fill_check reads it as `tone`, and because the lift crosses the 18 px line the plate law reads it as max|bg - painting| far above its 1-level bound',
    ),
    _p(
        'blank',
        'Catches a blank or corrupt frame',
        ['blank'],
        'blank',
        [
            {'check': 'gate_flags_planted', 'fixture': 'blank_black'},
            {'check': 'gate_flags_planted', 'fixture': 'corrupt_png'},
            {
                'check': 'report_contains',
                'field': 'error',
                'pattern': r'(cannot read|no skin|no face|decode)',
                'note': 'a refusal must be a written refusal, not a silent pass',
            },
        ],
        ALL,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='patch_gate already raises SystemExit("cannot read …") at patch_gate.py:95 and reports `no_skin` per box; the twin measures whether that refusal reaches the caller as a FLAG rather than as an exit 0',
    ),
    # ── How it behaves ──
    _p(
        'floor_stated',
        'States its floor in the output',
        ['floor_stated'],
        'photo',
        [
            {'check': 'report_contains', 'field': 'threshold', 'pattern': r'\d'},
            {'check': 'report_contains', 'field': 'score', 'pattern': r'\d'},
        ],
        ALL,
        state_note='the report must carry BOTH the measured number and the bound it was compared with, so a cell can be re-read a year later without opening the source',
    ),
    _p(
        'region',
        'Looks where the fault actually is',
        ['region'],
        'photo',
        [{'check': 'region_iou_min', 'field': 'flagged_region', 'min': 0.5}],
        PATCH + FILL + PLATE,
        state_note=(
            "the sheet's own limitation as a number. The planted `region` is in the MANIFEST; a gate that returns a "
            "whole-image verdict with no box scores no here, and that is the honest reading — fill_check's take-4 miss "
            'was a band in the wrong place, not a wrong threshold.'
        ),
    ),
    _p(
        'false_alarm',
        'Leaves a good take alone',
        ['false_alarm'],
        'clean_twelve',
        [{'check': 'gate_passes_clean'}],
        ALL,
        state_rule={'yes': 1.0, 'partial': 0.92},
        state_note='all twelve clean twins x 3 repeats = 36 runs, zero flags for `yes`. One false alarm in 36 is already `partial`: a gate the operator overrides is a gate nobody reads.',
    ),
    _p(
        'explains',
        'Explains itself to a human',
        ['explains'],
        'colour',
        [
            {
                'check': 'report_contains',
                'field': 'failed_term',
                'pattern': r'(dab|tex|tone|seam|texture|line|face|identity|palette|plate)',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Reading only the gate's report (no picture), can you say which measurement failed and by how much? yes/no",
            },
        ],
        ALL,
        state_note='naming the failing term is mechanical; whether the naming is usable is the blind operator question',
    ),
    _p(
        'gameable',
        'Cannot be gamed by texture',
        ['gameable'],
        'gamed',
        [
            {'check': 'gate_rejects_gamed'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this plate show the wrong subject behind the noise, i.e. is the content genuinely wrong? yes/no',
            },
        ],
        ALL,
        state_note=(
            'POLARITY, written out because the column caption is the authority: yes = CANNOT be gamed. The trial passes '
            'when the gate REJECTS the gamed twin. look_gate is expected to score NO — a high AuraFace cosine on an '
            'insane tile is the standing content-truth hole (the misaligned grid slice that scored 0.44 and entered a '
            'training set), and NCC shipped an inflated prop the same way. Recording that `no` is the point.'
        ),
    ),
    _p(
        'video_frames_gate',
        'Runs on video frames',
        ['video_frames_gate'],
        'video',
        [{'check': 'gate_frames_complete', 'frames': 10, 'frames_planted': [6]}],
        ALL,
        state_note='10 frames of the p4 hold with the hue fault on frame 6 only; a gate that completes but flags all ten or none scores no',
    ),
    # ── Capacity: the two rungs an arithmetic gate can answer ──
    _p(
        'cap_res_judge',
        'Resolution it can still resolve the fault at',
        ['cap_res_judge'],
        'colour',
        [
            {
                'check': 'ladder_last_rung',
                'floor': 512,
                'inner': 'gate_flags_planted on the colour twin and its clean counterpart at that rung',
            }
        ],
        ALL,
        conditions=dict(
            COND,
            ladder=[2048, 1536, 1080, 1024, 768, 512, 384, 256],
            resize='cv2.INTER_AREA on both twins together, aspect kept',
        ),
        state_note='the column records the smallest long edge at which the gate still separated the twins; `yes` when that reaches 512 px or below, since every crop the repair loop hands a gate is at least that',
    ),
    _p(
        'cap_images',
        'Images accepted in one call',
        ['cap_images'],
        'clean_twelve',
        [
            {
                'check': 'ladder_last_rung',
                'floor': 2,
                'inner': 'every candidate in the call gets its own verdict in the report and the verdicts equal the one-at-a-time verdicts',
            }
        ],
        ALL,
        conditions=dict(COND, ladder=[1, 2, 4, 8, 12], repeats=3),
        state_note='look_gate already takes `--cand a.png b.png …` and patch_gate takes repeated `--box`; the ladder measures how many before the report stops carrying one verdict per candidate',
    ),
]

# ── the whole recognition half of the judge bank, na once, at step level ─────────────
NA_BANDS = {
    'reason': (
        'an arithmetic gate compares pixel statistics; it does not recognise subjects. look_gate, patch_gate, '
        'fill_check and plate_law take two pictures and return a number — there is no question to ask them, no '
        'name they could return and no count they could give. Running the 132-subject bank against a chroma '
        'distance would manufacture empty cells, so every Sees, Names, counting, spatial and attribute column '
        'is na here with this reason. The two capacity rungs an arithmetic gate CAN answer (cap_res_judge, '
        'cap_images) are measured above.'
    ),
    'bands': [
        'Sees: People',
        'Sees: The body',
        'Sees: Food',
        'Sees: Damage & wear',
        'Sees: Text & number',
        'Sees: Objects',
        'Sees: Animals',
        'Sees: Nature & weather',
        'Sees: Built environment',
        'Sees: Clothing',
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
        'Capacity',
        'Counting & quantity',
        'Space & relation',
        'Attributes',
    ],
}

_LOOK_NA = {
    'photo': "look_gate measures identity against the character's styled cells and a palette band; the photographic-patch question is patch_gate's chroma/texture pair and is measured there",
    'seams': 'a whole-candidate identity cosine has no matte and no boundary band; the seam question belongs to fill_check and the plate law',
    'grain': 'look_gate carries no frequency term at all — its two numbers are an AuraFace cosine and a palette histogram distance',
    'texture_gate': "there is no texture statistic in look_gate; brushwork against continuous tone is patch_gate's tex ratio",
    'luma': 'the palette band is a chroma histogram; a uniform luminance lift moves it hardly at all, so claiming a catch here would be inventing one',
    'region': 'look_gate returns one cosine for the whole candidate and no box, so there is no flagged region to intersect with the planted one',
}
_PATCH_NA = {
    'identity': "patch_gate never loads an identity model; it compares a repaired region's skin against the SAME picture's face, so a wrong face that is internally consistent passes it by construction",
    'seams': 'patch_gate is given boxes, not a matte, and measures inside them; a boundary ring between fill and painting is outside everything it reads',
    'luma': 'the dab term is LAB (a, b) only — chroma with the lightness axis deliberately dropped — so a luminance lift is invisible to it by design',
}
_FILL_NA = {
    'identity': 'fill_check asks whether the BACKGROUND fill is a painting; it runs on the plate with the figure removed and has no identity model in it',
}
_PLATE_NA = {
    'identity': 'the plate law is a distance-transform bound on how far the fill may differ from the untouched painting; it holds no identity model',
    'photo': 'the law compares the plate against the painting it came from, not the plate against a face; a photographic patch that obeys the 12/18 bound passes it',
    'grain': 'the law bounds level difference beyond 18 px, not grain scale inside the hole; a halved grain inside the fill is by construction outside its remit',
    'colour_gate': 'a hue shift confined to the fill region sits inside the 12 px core the law leaves to fill_check; the law only speaks beyond 18 px',
    'texture_gate': 'the law has no frequency term; it is one max|bg - painting| over the far field',
}

TEST = {
    'step': 'pixel_gates',
    'version': '2026-09-30.1',
    'title': 'Twelve planted faults and their clean twins, through the four arithmetic gates',
    'purpose': (
        'Measure each pixel gate the only way an arithmetic gate can be measured: plant a known fault in an '
        'approved Second Ledger still, keep the untouched twin, and require the gate to flag one and pass the '
        'other — and require it to flag the right PLACE, which is where the take-4 fill_check miss actually was.'
    ),
    'include_shared': 'judge',
    'na_bands': NA_BANDS,
    'rows': {
        'look_gate': {
            'transport': 'builtin',
            'where': LEDGER + '/look_gate.py  (--char abel|cornelis --cand <png> --json out.json)',
            'model': "AuraFace identity cosine via id_score.embed against the character's styled Arcane cells, plus a palette band; the local VLM line is advisory only",
            'na': _LOOK_NA,
            'budget': {
                'calls': 165,
                'minutes': 26,
                'gpu_minutes': 20,
                'operator_minutes': 5,
                'note': 'look_gate is the only row that loads weights: AuraFace through the id_score worker (~40 s cold, ~1.5 s per candidate) plus one advisory qwen3.5:9b call per candidate. 165 runs x ~9 s = ~25 min, ~20 of them holding the GPU. The other three rows are numpy and cv2 only.',
            },
        },
        'patch_gate': {
            'transport': 'builtin',
            'where': LEDGER + '/patch_gate.py  (--image <png> --face x0,y0,x1,y1 --box … --json out.json)',
            'model': "LAB skin-chroma distance dab <= 4.5 (hard) and sigma-3 high-pass std ratio tex >= 0.80 (soft flag), on the HSV skin pixels only, against the picture's own painted face",
            'na': _PATCH_NA,
        },
        'fill_check': {
            'transport': 'builtin',
            'where': LEDGER
            + '/fill_check.py  (--picture <png> --bg <png> --matte-raw <png> --engine sdxl --json out.json)',
            'model': 'five numbers on the fill alone — face, tone, seam (Sobel on matte_raw +-4 px), texture (median |Laplacian| inside vs the ring) and the v4 `line` term (|Sobel_x| of a vertically blurred grey)',
            'na': _FILL_NA,
        },
        'plate_law': {
            'transport': 'builtin',
            'where': LEDGER
            + '/shots/p1/_t5b_ladder.py:plate_law  and the verifier at '
            + LEDGER
            + '/verify/_t5_common_v4.py:37-41',
            'model': 'the take-5 plate law: the fill stays inside 12 px of matte_raw, the untouched painting resumes beyond 18 px with a 6 px linear feather; max|bg - painting| beyond 18.5 px must be <= 1 level',
            'na': _PLATE_NA,
        },
    },
    'probes': PROBES,
    'derive': {
        'speed': {
            'from': 'wall clock per gate run on one 1920x1080 twin pair, model load excluded',
            'grade': 'measured',
            'unit': 's',
        },
        'throughput': {
            'from': 'twin pairs per hour, single stream, model load paid once',
            'grade': 'measured',
            'unit': 'count',
        },
        'first_take': {
            'from': "share of probes whose FIRST of three repeats already gave the trial's verdict",
            'grade': 'measured',
        },
        'retries': {
            'from': 'runs until a verdict stopped changing; expected 1 for arithmetic, and a value above 1 is a finding',
            'grade': 'measured',
            'unit': 'count',
        },
        'silent_fail': {
            'from': 'share of the twelve planted faults on which the gate exited 0 AND wrote no failing term — the fault passed and nothing in the output said so',
            'grade': 'measured',
        },
        'receipts': {
            'from': "the run leaves the per-twin JSON report, the sha256 of both twins and the gate's source revision next to the sheet",
            'grade': 'receipt',
        },
    },
    'lookup': {
        'threshold_set': {
            'grade': 'receipt',
            'source': 'the calibration each gate publishes in its own docstring, with the material it was set on',
            'value': (
                'patch_gate: dab <= 4.5 hard / tex >= 0.80 soft, set 2026-09-27 on the v5 pictures with the identity '
                "worker's face boxes — five rejected Qwen hands at dab 5.74-10.97 against two painted controls at "
                '4.38 and 2.63 (tree 301348). plate_law: fill <= 12 px, painting >= 18 px, 6 px feather, creator-'
                'measured on p2 at take 5 (fill_check passes unchanged, no edge visible at 1:1). fill_check: the v4 '
                'seam band matte_raw +-4 px with seam_ratio_hole and line_ratio added after the take-4 miss. '
                "look_gate: the identity band is the character's own styled Arcane cells, never the photoreal "
                'training tiles.'
            ),
            'requires': [
                LEDGER + '/patch_gate.py (docstring CALIBRATION block, 2026-09-27)',
                LEDGER + '/fill_check.py (docstring, v4 `line` paragraph)',
                LEDGER + '/verify/_make_tree5.py:14 (PLATE_LAW, take 5)',
                LEDGER + '/defect_bench/results/pixel_gates.json (the bench run the sheet was written from)',
            ],
            'note': 'a threshold set on OUR material is the whole claim of this column; the value above names the material for each row, and a row whose bound came from a paper rather than from these pictures would score no',
        },
    },
    'wiring': {
        'blocks_ship': {
            'grade': 'assumed',
            'from': (
                'read off the exit paths, never run: patch_gate.py:114 `sys.exit(main())` — exit 1 when any box '
                'breaks the hard dab bound; look_gate.py:266 `sys.exit(1)`; fill_check.py:262 `raise '
                'SystemExit(main())`; and the plate law is an `assert` in the take-5 verifier at '
                'verify/_t5_common_v4.py:41 ("plate differs from the painting beyond %d px of the matte"). All four '
                'therefore CAN block, and the shot rebuild scripts call them as subprocesses and read the code.'
            ),
            'note': 'assumed, not measured: this test never runs a ship. What is read is that a non-zero exit exists and that the caller checks it.',
        },
    },
    'na': {},
    'fixtures': [
        {
            'path': MAKER,
            'generated': RECIPE,
            'note': 'the generator is named here and its operations are written out; this task created no binaries',
        },
        {
            'path': MANIFEST,
            'generated': 'written by ' + MAKER + ' --all',
            'verified': False,
            'blocks': ['identity', 'photo', 'gameable', 'region'],
            'how_to_verify': (
                'run the maker, open ' + TWINS + '/contact.jpg once, and confirm per twin: the identity twin '
                'carries a face that is visibly not Abel and measures AuraFace cosine 0.45-0.55 against the '
                'Abel anchor (record the number in MANIFEST.identity.cosine); the photo twin reads '
                'photographic against the brushwork at 1:1; the gamed twin shows the WRONG subject; and each '
                "fault's `region` box, drawn on the twin, encloses the fault. Then set verified = true."
            ),
        },
        {
            'path': TWINS,
            'generated': 'python3 ' + MAKER + ' --all',
            'verified': False,
            'blocks': ['seams', 'grain', 'texture_gate'],
            'how_to_verify': (
                "at 1:1, confirm the two seam twins show a rim at the stated distances and that seam_outside's "
                "rim really sits outside matte_raw +-4 px (draw the band), that the grain twin's grain is "
                'visibly finer with the same tone, and that the texture twin reads as a smudge rather than as '
                'a step. Then set verified = true.'
            ),
        },
        {
            'path': CLEAN,
            'generated': 'python3 ' + MAKER + ' --clean',
            'verified': True,
            'note': 'byte copies of the approved masters under '
            + LEDGER
            + '/shots/p{1..5}/, already signed off in intro/final/README.md — no new judgement is being claimed',
        },
    ],
    'budget': {
        'calls': 165,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': "an arithmetic gate takes two pictures and returns a number; no language model is called on this step except look_gate's advisory VLM line, which is counted in that row's minutes and is never scored",
        'minutes': 3,
        'gpu_minutes': 0,
        'operator_minutes': 5,
        'note': (
            'Per row: 12 planted twins x 3 repeats = 36, the 12 clean twins x 3 = 36 (false_alarm), the gamed twin '
            'x 3 = 3, the 10-frame clip x 3 = 30 frame runs, the resolution ladder 8 rungs x 2 twins x 3 = 48, the '
            'cap_images ladder 5 rungs x 3 = 15 — 168 runs, called 165 because floor_stated, region and explains '
            're-read reports the fault probes already produced and cost nothing extra. At ~1 s per cv2 run that is '
            '~3 min for patch_gate, fill_check and plate_law. look_gate overrides to 26 min / 20 GPU min because it '
            "is the only row that loads weights. SHARED BANK: this step runs NONE of the judge bank's 132-subject "
            'renders — every recognition band is na at step level, so the bank contributes 0 extra calls here and '
            "only its universal columns, which are derived from this run's own telemetry. No claude_cli or "
            'anthropic_api row exists on this step, so the shared Claude week is untouched. Operator: 3 blind '
            'questions (seams, explains, gameable) x 3 repeats = 9 decisions at 30 s = ~5 min per row, PLUS a '
            'one-time ~25 min verifying the twelve twins on the contact sheet, until which the identity, photo, '
            'gameable, region, seams, grain and texture_gate columns are BLOCKED.'
        ),
    },
    'run_order': [
        'blank',
        'floor_stated',
        'explains',
        'colour_gate',
        'luma',
        'texture_gate',
        'grain',
        'seams',
        'photo',
        'identity',
        'region',
        'gameable',
        'false_alarm',
        'video_frames_gate',
        'cap_images',
        'cap_res_judge',
    ],
    'notes': [
        'Cheap and mechanical first: `blank` and `floor_stated` need no twin verification and will fill within a minute; '
        'the ladders are last because they are 63 of the 165 runs.',
        'The four rows are not four models — they are four gates with different remits, so most of the catch columns are '
        'na on three of them. The na reasons say WHICH gate owns each fault, so a fault that shipped lands on the gate '
        'that should have caught it rather than on the sheet in general.',
        "The sheet's own limitation is a scored column here (`region`). If a gate catches a fault while pointing "
        'somewhere else, that is recorded as a catch AND a region miss, which is exactly the shape of the take-4 defect.',
        "Nothing on this step touches the GPU except look_gate's AuraFace worker, so the whole test can run beside a "
        'render if look_gate is scheduled separately.',
    ],
}
