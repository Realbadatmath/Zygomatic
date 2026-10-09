# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Frame interpolation & retiming (interp). 2026-09-30.

Question the sheet asks: can we smooth or retime a clip without smearing it?

One row, because there is one implementation. The module is called `rife_service.py` and
Stage 4.2 is called "RIFE temporal repair", but what runs on this box is ffmpeg's
`minterpolate`: `_try_rife` (rife_service.py:129) looks for a RIFE binary and model, logs
"RIFE binary/model not found — using minterpolate fallback" (:139) and hands off to
`_interpolate_one_minterpolate` (:215). The sheet's own note already says so; `naming` is the
column that records it, as wiring, with the lines.

The shape of the test turns on one constant. `_SHORT_CLIP_FRAMES = 200` (rife_service.py:49)
picks the filter, and the two branches are not two settings of one algorithm — they are
different algorithms:

    frames < 200   _MI_PARAMS_BLEND  (:60)  minterpolate=fps=N:mi_mode=blend,deflicker=mode=am:size=3
    frames >= 200  _MI_PARAMS_INTERP (:63)  minterpolate=fps=N:mi_mode=mci:...

`mi_mode=blend` does not interpolate at all: it cross-dissolves neighbouring frames. It cannot
smear, because it never estimates motion — it double-exposes instead, which is a different
artefact with the same cause. `mi_mode=mci` estimates motion vectors and can smear and halo in
the classic way. A test that ran only one of them would report half a capability, so EVERY
fixture exists twice — 10 s (120 frames, blend) and 30 s (360 frames, mci) — and every probe
runs on both. The cell records the two modes separately; the state is the WORSE of the two,
because production picks the mode from the clip length and the operator does not get to choose.

Fixtures are analytic lavfi wherever a truth is needed: a hard-edged pattern panning at exactly
96 px/s is a known displacement per frame, so "did it invent the in-between or duplicate a
frame" is arithmetic. The one fixture that cannot be synthesised is the hands clip — MediaPipe
must find the hands in the SOURCE before anything can be claimed about the interpolated copy —
so it is declared unverified and BLOCKS `hands_interp` until the operator picks the clip and
confirms the source frames.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/interp'

# Check kinds this module needs and capability_tests/__init__.CHECK_KINDS does not have.
CHECK_KINDS = {
    'duplicate_frames_max': "the share of decoded frames whose perceptual hash equals their predecessor's is <= `max`; on a clip whose every frame genuinely differs, a doubled frame rate that duplicates instead of interpolating shows here and nowhere else",
    'jerk_ratio_max': 'the standard deviation of the frame-to-frame mean absolute luma delta, divided by its mean, is <= `max` over the whole clip — a smooth pan has a near-constant delta, a stuttering one alternates large and small',
    'edge_sharpness_ratio': 'the mean Sobel gradient magnitude of the produced frames divided by the same measure on the source frames is >= `min`; a cross-dissolve halves it, and that is the mechanical half of the smear question',
    'edge_halo_max': "in a `ring_px` band immediately OUTSIDE the moving subject's edge, the mean gradient magnitude minus the same band measured on the nearest source frame is <= `max` (0-255 scale) — the ghost the motion estimate leaves behind an edge",
    'ghost_inside_max': 'inside the region `front` (a foreground object of known flat colour `colour`), the mean absolute deviation from that colour is <= `max` (0-255) in every frame of `sample` — a background object showing THROUGH the foreground is an occlusion failure and nothing else produces this signal',
    'fps_exact': 'both the container frame rate and the measured frame count divided by duration equal `fps` within `tol` (absolute, in fps); 23.976 must not silently become 24',
    'frames_outside_unchanged': 'every output frame whose timestamp falls outside the retimed window `[start_s, end_s]` is bit-identical (md5 of the decoded RGB) to the source frame at the same timestamp; a run that rewrites the whole clip fails this by construction, which is the honest answer when a section retime is not implemented',
}

# The two fixture lengths are the two code branches, not a taste. 12 fps in, 24 fps out.
SRC_FPS = 12
OUT_FPS = 24
SHORT_S, SHORT_FRAMES = 10, 120  # < _SHORT_CLIP_FRAMES=200  -> mi_mode=blend
LONG_S, LONG_FRAMES = 30, 360  # >= _SHORT_CLIP_FRAMES=200 -> mi_mode=mci
PAN_PX_S = 96  # exactly 8 px per source frame at 12 fps

MODES = {
    'blend': {
        'fixture_suffix': '_short',
        'frames': SHORT_FRAMES,
        'filter': 'minterpolate=fps=24:mi_mode=blend,deflicker=mode=am:size=3',
        'code': 'rife_service.py:60,233',
    },
    'mci': {
        'fixture_suffix': '_long',
        'frames': LONG_FRAMES,
        'filter': 'minterpolate=fps=24:mi_mode=mci:...',
        'code': 'rife_service.py:63,238',
    },
}


def _gen_pan(secs, out):
    """A hard-edged checker panning at exactly 96 px/s over a black field."""
    return (
        'ffmpeg -y -f lavfi -i "color=c=black:s=1280x720:r=12:d=%d" '
        '-f lavfi -i "testsrc2=s=2560x720:r=12:d=%d" '
        '-filter_complex "[1:v]format=gray[p];[0:v][p]overlay=x=\'-96*t\':y=0:shortest=1" '
        '-c:v libx264 -crf 12 -pix_fmt yuv420p -an %s' % (secs, secs, out)
    )


def _gen_text(secs, out):
    """The same pan, but the thing that moves is lettering with a known string."""
    return (
        'ffmpeg -y -f lavfi -i "color=c=0x101418:s=1280x720:r=12:d=%d" '
        "-vf \"drawtext=text='QUAY 1671':fontsize=96:fontcolor=white:"
        "x='1280-96*t':y=300,noise=alls=3:allf=t\" "
        '-c:v libx264 -crf 12 -pix_fmt yuv420p -an %s' % (secs, out)
    )


def _gen_cross(secs, out):
    """Two flat boxes crossing: the red one passes BEHIND the fixed green one."""
    return (
        'ffmpeg -y -f lavfi -i "color=c=0x101418:s=1280x720:r=12:d=%d,'
        "drawbox=x='100+96*t':y=300:w=120:h=120:c=0xd03020:t=fill,"
        'drawbox=x=600:y=260:w=160:h=200:c=0x20a050:t=fill" '
        '-c:v libx264 -crf 12 -pix_fmt yuv420p -an %s' % (secs, out)
    )


FIX = {
    'pan_short': (FX + '/pan_short.mp4', _gen_pan(SHORT_S, FX + '/pan_short.mp4')),
    'pan_long': (FX + '/pan_long.mp4', _gen_pan(LONG_S, FX + '/pan_long.mp4')),
    'text_short': (FX + '/text_short.mp4', _gen_text(SHORT_S, FX + '/text_short.mp4')),
    'text_long': (FX + '/text_long.mp4', _gen_text(LONG_S, FX + '/text_long.mp4')),
    'cross_short': (FX + '/cross_short.mp4', _gen_cross(SHORT_S, FX + '/cross_short.mp4')),
    'cross_long': (FX + '/cross_long.mp4', _gen_cross(LONG_S, FX + '/cross_long.mp4')),
}
FIX_HANDS = FX + '/hands_source.mp4'

# The green box the red one passes behind, and the window in which it does.
FRONT = {
    'front': [600, 260, 160, 200],
    'colour': [0x20, 0xA0, 0x50],
    'note': 'the red box (x = 100 + 96*t, w = 120) is wholly behind the green one between t = 5.0 s and t = 5.42 s and overlaps it from t = 4.0 s to t = 6.67 s',
}

COND = {
    'repeats': 2,
    'note': 'ffmpeg on a fixed input is deterministic; the second run is what proves it rather than what assumes it',
}
ROWS = ['minterpolate']


def _p(pid, title, feeds, checks, video, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': list(video),
            'video': list(video),
            'command': 'rife_service.interpolate_clips([{path: <fixture>}], out_dir) — production defaults, nothing overridden',
            'prompt': None,
        },
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': ROWS,
    }
    p.update(kw)
    return p


BOTH_PAN = {'fixture': ['pan_short (120 frames -> blend)', 'pan_long (360 frames -> mci)']}

PROBES = [
    _p(
        'smooth',
        'Removes stutter',
        ['smooth'],
        [
            {'check': 'frames_exact', 'frames': 240, 'fps': OUT_FPS, 'on': 'pan_short'},
            {'check': 'duplicate_frames_max', 'max': 0.02},
            {'check': 'jerk_ratio_max', 'max': 0.15},
            {'check': 'motion_min', 'min': 1.5},
        ],
        [FIX['pan_short'][0], FIX['pan_long'][0]],
        grid=BOTH_PAN,
        state_note=(
            'The pan moves 8 px per source frame; a real 12 -> 24 fps interpolation moves 4 px per output frame and the frame-to-frame delta is constant, so jerk_ratio is near 0. '
            'A doubled frame rate that duplicates frames alternates 0 and 8 px and shows a jerk_ratio near 1.0 and a duplicate share of 0.5. The two modes are reported separately and the state is the worse of them.'
        ),
        state_rule={'yes': 1.0, 'partial': 0.5},
    ),
    _p(
        'smear',
        'No smearing on fast motion',
        ['smear'],
        [
            {'check': 'edge_sharpness_ratio', 'min': 0.85},
            {
                'check': 'operator',
                'blind': True,
                'question': 'In this frame, is the moving pattern doubled, streaked or ghosted along its direction of travel? yes = it is smeared (a NO on this column)',
            },
        ],
        [FIX['pan_short'][0], FIX['pan_long'][0]],
        grid=BOTH_PAN,
        state_note=(
            'Both halves are needed and they fail for opposite reasons. mi_mode=blend cross-dissolves, so the pattern is double-exposed and edge_sharpness_ratio drops to roughly 0.5 while nothing "smears" in the motion-vector sense; '
            'mi_mode=mci can hold the sharpness and still tear. The operator question decides the column when the two disagree, because no local VLM judges a smear reliably (defect judge bench 2026-09-27: 2/8 on hard cases).'
        ),
    ),
    _p(
        'halo',
        'No halo around moving edges',
        ['halo'],
        [
            {'check': 'edge_halo_max', 'max': 8, 'ring_px': 6},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Along the leading edge of the moving pattern, is there a faint copy or glow that is not in the source frame? yes = there is a halo (a NO on this column)',
            },
        ],
        [FIX['pan_short'][0], FIX['pan_long'][0]],
        grid=BOTH_PAN,
    ),
    _p(
        'occlusion_i',
        'Handles occlusion',
        ['occlusion_i'],
        [
            {
                'check': 'ghost_inside_max',
                'max': 10,
                'front': FRONT['front'],
                'colour': FRONT['colour'],
                'sample': 'every output frame between t=4.0 s and t=6.67 s',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Where the two blocks overlap, does the block behind show through the block in front? yes = it shows through (a NO on this column)',
            },
        ],
        [FIX['cross_short'][0], FIX['cross_long'][0]],
        grid={'fixture': ['cross_short (120 frames -> blend)', 'cross_long (360 frames -> mci)']},
        state_note='the green box is a flat known colour, so a ghost of the red box behind it is a measurable deviation and needs no judge; blend mode is expected to fail this by construction, since a cross-dissolve of two frames necessarily mixes the occluded object in',
    ),
    _p(
        'hands_interp',
        'Hands survive interpolation',
        ['hands_interp'],
        [
            {'check': 'hand_landmarks_count', 'hands': 2, 'fingers': 5, 'share': 0.9},
            {
                'check': 'operator',
                'blind': True,
                'question': 'In this frame, do the hands have the right number of fingers, with no extra, fused or smeared digits? yes/no',
            },
        ],
        [FIX_HANDS],
        state_note=(
            'The source must pass FIRST: the runner measures hand_landmarks_count on the source frames and the column is the interpolated share MINUS nothing — if the source does not reach 0.9, the cell is `untested`, because the test would be measuring MediaPipe rather than the interpolator. '
            'This is the honest-judging rule for hands: the detector decides, the blind operator question is recorded beside it, and neither is dropped.'
        ),
    ),
    _p(
        'text_interp',
        'Lettering survives',
        ['text_interp'],
        [
            {'check': 'ocr_equals', 'text': 'QUAY 1671', 'sample': 'every 6th output frame'},
            {'check': 'ocr_stable', 'sample': 'every 6th output frame'},
        ],
        [FIX['text_short'][0], FIX['text_long'][0]],
        grid={'fixture': ['text_short (120 frames -> blend)', 'text_long (360 frames -> mci)']},
        state_note='the string is burned in by the fixture command, so the OCR truth is exact rather than transcribed; a blend-mode pass that double-exposes the lettering will fail ocr_equals even where a human could still read it, and that is the correct answer for a deliverable',
    ),
    _p(
        'fps_target',
        'Reaches an arbitrary target rate',
        ['fps_target'],
        [
            {'check': 'fps_exact', 'fps': 23.976, 'tol': 0.002},
            {'check': 'duration_s', 'min': LONG_S - 0.05, 'max': LONG_S + 0.05},
        ],
        [FIX['pan_long'][0]],
        state_note=(
            '23.976 is the awkward one on purpose: `minterpolate=fps=` takes a rational, but rife_service formats it with `int(target_fps)` (rife_service.py:238), so the wired path can only ask for a whole number. '
            'The probe runs the filter at 23.976 DIRECTLY as well, and the cell records both — what the filter can do and what the service asks it for.'
        ),
        grid={
            'called_via': [
                'rife_service.interpolate_clips (production path, int fps)',
                'the minterpolate filter at fps=24000/1001 directly',
            ]
        },
    ),
    _p(
        'slowmo',
        'Usable slow motion',
        ['slowmo'],
        [
            {'check': 'frames_exact', 'frames': 2880, 'fps': OUT_FPS},
            {'check': 'duplicate_frames_max', 'max': 0.05},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Played at quarter speed, does this move smoothly, or does it step and double-expose? yes = smooth',
            },
        ],
        [FIX['pan_long'][0]],
        state_note='the 30 s 12 fps pan taken to 24 fps at quarter speed is 120 s of output = 2880 frames; at quarter speed the interpolator must invent seven frames out of every eight, which is where mi_mode=mci stops being able to guess',
    ),
    _p(
        'retime',
        'Retimes a section, not the whole clip',
        ['retime'],
        [{'check': 'frames_outside_unchanged', 'start_s': 10.0, 'end_s': 15.0}],
        [FIX['pan_long'][0]],
        state_note=(
            'Expected result: `no`. `interpolate_clips` (rife_service.py:71-90) takes a list of whole clips and returns whole clips with a `rife_pass` field; there is no section argument anywhere on the path, so every frame is re-encoded and none outside the window can be bit-identical. '
            'This is written as a probe rather than an na because the sheet should carry a measured no with the receipt, not a shrug.'
        ),
    ),
]

CAP_NA = {
    'cap_people': 'an interpolator renders no people; it is handed frames that already contain them. The question belongs to the step that made the clip.',
    'cap_named': 'no subject is named to this row and none is generated; identity is neither given to it nor asked of it',
    'cap_faces': 'faces are not generated here; whether a face survives interpolation is a property of the motion estimate and is measured by smear, halo and occlusion_i',
    'cap_hands': 'hands are not generated here; hands surviving interpolation is exactly the hands_interp column, measured with MediaPipe',
    'cap_objects': 'the filter tracks blocks of pixels, not objects, and keeps no count of them; the occlusion behaviour that this question is reaching for is occlusion_i',
    'cap_words': 'no text is generated; whether burned-in lettering survives is the text_interp column, measured by OCR against a known string',
    'cap_digits': 'no digits are generated; the digits in the fixture are part of the text_interp OCR truth ("QUAY 1671")',
    'cap_animals': 'nothing is generated, so there is no count at which generation degrades',
    'cap_prompt_terms': 'this row takes no prompt at all — an ffmpeg filter graph and a frame count',
    'cap_shots': 'the filter is given one clip and never cuts; how shots cut together is the video_assembly step',
}

TEST = {
    'step': 'interp',
    'version': '2026-09-30.1',
    'title': 'Both minterpolate branches on analytic fixtures, at 120 and 360 frames',
    'purpose': 'Measure what the "RIFE" stage actually does — ffmpeg minterpolate in two different modes chosen by clip length — against pans and crossings whose per-frame truth is arithmetic, and record the naming as wiring rather than as a claim.',
    'include_shared': 'video',
    'implementation': {
        'wrapper': 'rife_service.interpolate_clips (Stage 4.2)',
        'filter': 'ffmpeg minterpolate',
        'mode_switch': '_SHORT_CLIP_FRAMES = 200 (rife_service.py:49)',
        'modes': MODES,
        'note': "the mode is chosen from the clip's frame count, so production does not get to pick it and neither does this test — both are measured and the state is the worse",
    },
    'rows': {
        'minterpolate': {
            'transport': 'ffmpeg',
            'where': 'rife_service.interpolate_clips -> _interpolate_one -> _try_rife (looks for a RIFE binary and model, not present on this box) -> _interpolate_one_minterpolate (rife_service.py:215); the filter strings are _MI_PARAMS_BLEND (:60) and _MI_PARAMS_INTERP (:63)',
            'na': CAP_NA,
        },
    },
    'na_bands': {
        'reason': 'this row takes an ffmpeg filter graph and a target frame rate; there is no prompt on the path, so every prompt question would be measuring something that does not exist',
        'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'factor_i': {
            'source': 'the wired call path: rife_service.py:238 formats the filter with `int(target_fps)` where target_fps is twice the source rate, and :233 takes the blend branch with fps unchanged',
            'revision': 'rife_service.py as of 2026-09-30; the cell records the file sha256',
            'requires': 'the produced clip\'s frame rate divided by the source\'s is read from ffprobe for each branch and must equal 2.0 (mci) and 1.0 (blend); the cell states "2x only as wired; the filter itself accepts any rational fps, see fps_target" and is a `no` for 4x',
            'grade': 'receipt',
        },
        'no_deps': {
            'source': 'the import list of rife_service.py and the binaries it execs',
            'revision': 'rife_service.py as of 2026-09-30, recorded by sha256 with the cell',
            'requires': 'the runner greps the module for subprocess targets and imports and asserts the set is {ffmpeg, ffprobe} plus the python standard library — no torch, no cupy, no model weights, no network. The RIFE branch (_try_rife, :129) is counted: it would need a binary and a model file, and the receipt records that neither resolves, which is why the fallback is the production path.',
            'grade': 'receipt',
        },
    },
    'wiring': {
        'naming': {
            'read': (
                'The module is named rife_service.py and its docstring calls Stage 4.2 "RIFE temporal repair", but no RIFE model runs on this box. '
                '`_try_rife` (rife_service.py:129) is documented as "Try RIFE neural interpolation first, fall back to minterpolate"; when the binary or the model is missing it logs '
                '"Stage 4.2: RIFE binary/model not found — using minterpolate fallback" (:139) and returns `_interpolate_one_minterpolate(clip_path, log_fn)` (:142). '
                'The `rife_pass` field the stage adds to each clip record is therefore always one of "2x_interp" or "blend" (:90) — both are minterpolate modes, neither is RIFE. '
                'So the column is `no`: the module does not do what its name says, and any sheet row that reads "RIFE" is reading a filename, not a model.'
            ),
            'files': [
                'rife_service.py:1-30',
                'rife_service.py:49-63',
                'rife_service.py:129-142',
                'rife_service.py:215-238',
            ],
            'grade': 'assumed',
        },
    },
    'na': {},
    'fixtures': (
        [
            {
                'path': p,
                'generated': g,
                'verified': True,
                'note': 'analytic: the pan is exactly 96 px/s, so the per-frame displacement truth is arithmetic',
            }
            for p, g in [FIX['pan_short'], FIX['pan_long']]
        ]
        + [
            {'path': p, 'generated': g, 'verified': True, 'note': 'the OCR truth is the burned-in string "QUAY 1671"'}
            for p, g in [FIX['text_short'], FIX['text_long']]
        ]
        + [
            {
                'path': p,
                'generated': g,
                'verified': True,
                'note': 'the green box is a flat known colour, so a ghost of the box behind it is measurable',
            }
            for p, g in [FIX['cross_short'], FIX['cross_long']]
        ]
        + [
            {
                'path': FIX_HANDS,
                'verified': False,
                'blocks': ['hands_interp'],
                'generated': (
                    'the operator copies the chosen clip here and conforms it to 12 fps: '
                    'ffmpeg -y -i <chosen.mp4> -t 10 -vf fps=12 -c:v libx264 -crf 12 -pix_fmt yuv420p -an ' + FIX_HANDS
                ),
                'how_to_verify': (
                    'pick a 10 s 12 fps house clip with two hands visible throughout (a rope-hauling or bread-kneading take from the Second Ledger rushes will do), put it here, then run MediaPipe '
                    'hand_landmarker over the SOURCE frames and confirm 2 hands with 21 landmarks each in at least 90 % of them. Only then set verified = true. If the source does not pass, the clip '
                    'is wrong for this test — measuring an interpolator through a detector that cannot see the source hands measures the detector.'
                ),
            }
        ]
    ),
    'budget': {
        'calls': 34,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'the row is an ffmpeg filter graph; no language model is called anywhere on this step and no tokens are spent',
        'minutes': 46,
        'gpu_minutes': 0,
        'operator_minutes': 9,
        'note': (
            '9 probes, 2 repeats each, most on two fixtures = 34 ffmpeg runs. minterpolate mi_mode=mci is the expensive one: measured house rule of thumb is roughly real-time per megapixel per mode, and 1280x720 '
            'at 12 -> 24 fps runs about 2x faster than real time, so the 30 s fixtures cost ~15 s each and the 10 s ones ~5 s. The outlier is slowmo: 2880 output frames of mci from 360 source frames is ~8 min a run, '
            'twice = 16 min. Everything else totals ~6 min of encoding. Decoding and measuring (phash per frame, Sobel, OCR every 6th frame, MediaPipe on the hands fixture) is the larger half: ~24 min. '
            'Total ~46 min, all CPU — minterpolate is not GPU-accelerated on this build and no model is loaded, hence gpu_minutes 0. Operator: 5 blind questions (smear, halo, occlusion_i, hands, slowmo) x 2 repeats, '
            'and smear/halo/occlusion_i run on two fixtures, so 16 decisions at 30 s = 8 min, plus ~1 min of shuffling = 9 min. SHARED BANK for this step: the video bank covers 39 of the 51 columns and its own budget '
            'note carries that cost; it renders no subject bank for interp. No claude_cli or anthropic_api row exists here, so the shared Claude week is untouched.'
        ),
    },
    'run_order': [
        'smooth',
        'fps_target',
        'text_interp',
        'halo',
        'smear',
        'occlusion_i',
        'retime',
        'hands_interp',
        'slowmo',
    ],
    'notes': [
        'Every probe runs on a 120-frame and a 360-frame fixture because rife_service.py:49 picks the filter from the frame count. Reporting one number for both would hide that a short clip is cross-dissolved and a long one is motion-interpolated.',
        'mi_mode=blend is expected to fail smear, occlusion_i and text_interp, and to pass halo (it estimates no motion, so it leaves no motion ghost). That pattern is the signature of a cross-dissolve, and the sheet should show it rather than average it away.',
        'retime is written as a probe with an expected `no` instead of an na: the path takes whole clips and has no section argument, and a measured no with the file lines is worth more to the next reader than "not applicable".',
        'No GPU is held by this step. If a real RIFE binary is ever installed, `naming` changes, `no_deps` changes, and this test is the thing that will say so — the fixtures and thresholds do not need to move.',
    ],
}
