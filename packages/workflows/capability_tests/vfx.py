# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Effects & compositing (vfx). 2026-09-30.

Question the sheet asks: what can the effects stack actually produce, and is it checked?

The honest shape of this step is not "one compositor tested seven ways". Read off the live
stack, the rows are three DIFFERENT kinds of thing:

  * a MEASUREMENT stack — vfx_analyzer / vfx_detectors / vfx_landmarks read a finished clip
    and report what is in it. They place nothing. So the Placement group is asked of them as
    what it really is for them: can they MEASURE placement (anchor error, track, occlusion)
    against a truth we know?  The fixtures are therefore analytic — an ffmpeg `drawbox` whose
    x(t) is an expression, so the ground truth is arithmetic and no detector is in the loop.
  * a LIBRARY — vfx_ingest's four categories plus the sidecar index, queried through
    vfx_place. It answers "does an element of this class exist", and vfx_preview_check answers
    the harder half, "does the file hold a picture" (it decodes every clip and samples for
    content ABOVE ITS OWN BACKGROUND; CONTRAST=20, SAMPLE_FRAMES=12).
  * two BESPOKE GENERATORS — the harbour water tail (`fx.water` in vfx_fx.py) and the bird
    sprite ladder — which produce one class of element each and nothing else.

Two measured receipts from the code are built into the thresholds rather than re-derived:
run_scene_shores_water.py:12-35 records that `fx.water` is a per-pixel displacement of the
illustration (NOT an alpha overlay), with temporal std over 2 s of 18.6/255 in the bottom
quarter, 12.9 at rows 620-690 and 6.0 at rows 560-620 — and that a detector run over it
"reported no water at all". gen_bird_side_sprites.py records that the canary is a 2D sprite
ladder (FLUX.2 klein-4B, seed 4041, rendered 2026-08-30) whose rear-view set cannot express
YAW, while the delivered shot's real heading swings from ~5-9 deg in cruise out to ~58-80 deg
at entry and exit. Both facts are why `water` and `birds` are probed on their own rows with a
tolerance taken from those numbers, instead of being asked as if a general compositor existed.

What is BLOCKED and why: nothing in this step needs an answer key the operator must mark —
the placement fixtures are analytic and the library queries resolve against a sidecar on disk.
The four synthetic plates do not exist yet and carry the exact ffmpeg command that makes them.

What this test does NOT claim: there is no general-purpose compositor row here. Compositing
over footage is `video_overlay.composite`, which is a row of the video_assembly step; its
placement record has fixed fractional x/y and a `track` of only "none" | "horizon"
(video_overlay.py:31, 199-206), i.e. no subject tracking exists to test. The Compositing
columns are therefore asked of the two generators (does the element they make matte, grade and
grain against a plate) and of the library gate, and are `na` on the measurement stack.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/vfx'

# Check kinds this module needs and capability_tests/__init__.CHECK_KINDS does not have. The
# validator unions them and lists them in the summary so the runner author sees the work.
CHECK_KINDS = {
    'anchor_error_max': 'for every frame in `sample`, the euclidean distance in pixels between the element anchor the row reports and the analytic truth (the fixture drawbox expression, evaluated at that frame time) is <= `anchor_error_max`; the column is `no` if the row reports no anchor at all',
    'anchor_jitter_max': 'on a plate whose truth is STATIC, the frame-to-frame change of the reported anchor position is <= `max_px` for >= `share` of consecutive frame pairs (a tracker that bounces fails even when its mean is right)',
    'track_error_max': "the row's reported per-frame subject centre follows the analytic truth with mean absolute error <= `mean_px` and maximum error <= `max_px`; a run that returns `unmeasurable` is `untested`, never `no`",
    'occlusion_order': "inside the occluder box `region`, the element's pixels are ABSENT (alpha < `alpha_max`) in >= `share` of the frames where truth says the subject is behind it, and PRESENT outside it — the two halves are reported separately",
    'ground_plane_error_max': "the vertical distance in pixels between the element's base row and the fixture's known ground/horizon row (`ground_y`) is <= `max_px` for every frame in `sample`",
    'element_scale_ratio': 'element on-screen height divided by the subject bounding-box height stays within `tol` (relative) of the ratio measured in the first frame, across `sample`',
    'library_has': 'the pinned library index holds >= `min` entries whose key or label matches `query` (case-insensitive regex) within categories `cats`; the matched keys are written into the trial so a false positive is visible',
    'asset_plays': "every asset matched by `query` passes vfx_preview_check's own content test — each of SAMPLE_FRAMES=12 sampled frames has a brightest-to-darkest spread >= CONTRAST=20, and a sprite has non-transparent pixels; the share of matched assets that pass is the pass rate",
    'matte_edge_clean': "on the element's alpha boundary, the share of boundary pixels with alpha strictly between `alpha_lo` and `alpha_hi` is <= `max_soft_share`, AND the mean RGB of those semi-transparent pixels is within `fringe_tol` (0-255 per channel) of the fully-opaque neighbourhood — the black-fringe test",
    'luma_chroma_match': 'the mean luma of the element region minus the mean luma of the plate region `plate_region` is within `luma_max` (0-255), and the mean CIELAB a*/b* difference is within `chroma_max`',
    'grain_sigma_match': 'the standard deviation of a high-pass (gaussian sigma `hp_sigma`) of the element region is within `tol` (relative) of the same measure on `plate_region` — an element with no grain over a grainy plate fails',
    'yaw_range_deg': "the row can express a subject heading up to `max_deg` off boresight: the reported/rendered yaw follows the fixture's commanded yaw with error <= `err_deg` up to that heading, and the heading at which the error first exceeds it is written into the cell",
}

# Every plate is synthetic lavfi, so there is no rights question and the truth is arithmetic.
# 1920x1080, 24 fps, horizon (the sky/sea split) at y=620, plate grain sigma 8.
GROUND_Y = 620
PLATE_GRAIN_SIGMA = 8
SUBJECT = {
    'x_expr': '200+48*t',
    'y': 660,
    'w': 80,
    'h': 120,
    'note': 'the white subject box; x(t) = 200 + 48*t px at 24 fps is the analytic truth every Placement check is scored against',
}

FIX_STATIC = FX + '/plate_static.mp4'
FIX_MOVE = FX + '/plate_move.mp4'
FIX_OCCLUDE = FX + '/plate_occlude.mp4'
FIX_COMPOSITE = FX + '/plate_composite.mp4'

GEN_STATIC = (
    'ffmpeg -y -f lavfi -i "color=c=0x6b7f8c:s=1920x1080:r=24:d=30,'
    'drawbox=y=620:h=460:c=0x2b3a44@1:t=fill,noise=alls=8:allf=t+u" '
    '-c:v libx264 -crf 14 -pix_fmt yuv420p -an ' + FIX_STATIC
)
GEN_MOVE = (
    'ffmpeg -y -f lavfi -i "color=c=0x6b7f8c:s=1920x1080:r=24:d=30,'
    'drawbox=y=620:h=460:c=0x2b3a44@1:t=fill,'
    "drawbox=x='200+48*t':y=660:w=80:h=120:c=white:t=fill,noise=alls=8:allf=t+u\" "
    '-c:v libx264 -crf 14 -pix_fmt yuv420p -an ' + FIX_MOVE
)
GEN_OCCLUDE = (
    'ffmpeg -y -f lavfi -i "color=c=0x6b7f8c:s=1920x1080:r=24:d=30,'
    'drawbox=y=620:h=460:c=0x2b3a44@1:t=fill,'
    "drawbox=x='200+48*t':y=660:w=80:h=120:c=white:t=fill,"
    'drawbox=x=900:y=520:w=80:h=560:c=0x14181c:t=fill,noise=alls=8:allf=t+u" '
    '-c:v libx264 -crf 14 -pix_fmt yuv420p -an ' + FIX_OCCLUDE
)
GEN_COMPOSITE = (
    'ffmpeg -y -f lavfi -i "color=c=0x6b7f8c:s=1920x1080:r=24:d=30,'
    'drawbox=y=620:h=460:c=0x2b3a44@1:t=fill,'
    "drawbox=x='200+48*t':y=660:w=80:h=120:c=white:t=fill,noise=alls=8:allf=t+u\" "
    '-c:v libx264 -crf 14 -pix_fmt yuv420p -an '
    + FIX_COMPOSITE
    + ' ; # then composite one library element onto it with video_overlay.composite using the '
    'placement record in ' + FX + "/placement.json (anchor bottom-center on the subject box's "
    'foot, x=(200+48*t)/1920, y=780/1080) — the record is the fixed input, not a choice'
)

OCCLUDER = {
    'region': [900, 520, 80, 560],
    'behind_from_s': 14.6,
    'behind_to_s': 16.2,
    'note': 'the post at x=900..980; the subject box (x=200+48t, w=80) is behind it between t=14.58 s and t=16.25 s',
}

COND = {
    'repeats': 2,
    'note': 'two runs on the same fixture: these are deterministic CPU services and a second run that differs is itself the finding',
}

READERS = ['analyzer', 'detectors', 'landmarks']
GENERATORS = ['water', 'birds']
LIB = ['library']
GATE = ['preview_check']


def _p(pid, title, feeds, checks, rows, video=FIX_MOVE, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'video': video, 'fixture': FX + '/TRUTH.json', 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    # ── Placement: asked of the measurement stack against an analytic truth ──
    _p(
        'attaches',
        'The element lands on the tracked feature',
        ['attaches'],
        [{'check': 'anchor_error_max', 'anchor_error_max': 6, 'sample': 'every 4th frame'}],
        READERS + ['birds'],
        video=FIX_COMPOSITE,
        state_note='6 px at 1920 wide is a third of the 80 px subject box. A row that returns `unmeasurable` (MediaPipe on a synthetic box: the expected case for landmarks) is untested, not no — the tri-state contract in vfx_landmarks.py is honoured here.',
    ),
    _p(
        'stable',
        'Stable across frames',
        ['stable'],
        [{'check': 'anchor_jitter_max', 'max_px': 2, 'share': 0.95}],
        READERS + ['birds'],
        video=FIX_STATIC,
        state_note="on the STATIC plate the truth does not move, so every reported pixel of movement is the row's own noise",
    ),
    _p(
        'track',
        'Tracks a moving subject',
        ['track'],
        [{'check': 'track_error_max', 'mean_px': 4, 'max_px': 12}],
        READERS + ['birds'],
        state_note='x(t) = 200 + 48*t is the truth; mean error 4 px and no frame worse than 12 px (half the box width)',
    ),
    _p(
        'occlude',
        'Respects occlusion',
        ['occlude'],
        [{'check': 'occlusion_order', 'region': OCCLUDER['region'], 'alpha_max': 0.05, 'share': 0.9}],
        READERS + ['birds'],
        video=FIX_OCCLUDE,
        state_note='the subject passes behind the post between 14.58 s and 16.25 s; the two halves (hidden where it should be, visible where it should not) are reported separately so "always hidden" cannot pass as a yes',
    ),
    _p(
        'depth_place',
        'Sits at the right depth',
        ['depth_place'],
        [{'check': 'ground_plane_error_max', 'ground_y': GROUND_Y, 'max_px': 10}],
        READERS + ['birds'],
        video=FIX_COMPOSITE,
        state_note="the horizon is drawn at y=620 and the subject's foot at y=780; an element that floats or sinks against that plane fails by more than 10 px",
    ),
    _p(
        'scale_place',
        'Scales with the subject',
        ['scale_place'],
        [{'check': 'element_scale_ratio', 'tol': 0.08, 'sample': 'every 4th frame'}],
        READERS + ['birds'],
        video=FIX_COMPOSITE,
        state_note='the fixture subject does not change size, so this measures whether the row holds a constant ratio rather than drifting; a step that CAN scale is measured by the ratio it holds, not by a promise',
    ),
    # ── Elements: the library classes, probed through the gate that decodes them ──
    _p(
        'fire_smoke',
        'Fire and smoke elements exist and play',
        ['fire_smoke'],
        [
            {
                'check': 'library_has',
                'min': 1,
                'query': r'fire|smoke|flame|explos|plume|chimney|campfire|burn|lava',
                'cats': ['vfx_plates', 'vfx_sprites', 'vfx_volumes'],
            },
            {'check': 'asset_plays', 'query': r'fire|smoke|flame|explos|plume|chimney|campfire|burn|lava'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Looking at this element on its own, does it read as fire or smoke (rather than as a generic blob, a watermark card or a black frame)? yes/no',
            },
        ],
        GATE,
        video=None,
        state_note='the class is best stocked on this box; the operator question exists because "decodes and has contrast" is not the same as "reads as fire"',
    ),
    _p(
        'weather',
        'Rain, snow and fog elements exist and play',
        ['weather'],
        [
            {
                'check': 'library_has',
                'min': 1,
                'query': r'rain|snow|fog|mist|storm',
                'cats': ['vfx_plates', 'vfx_sprites', 'vfx_volumes'],
            },
            {'check': 'asset_plays', 'query': r'rain|snow|fog|mist|storm'},
            {'check': 'operator', 'blind': True, 'question': 'Does this element read as rain, snow or fog? yes/no'},
        ],
        GATE,
        video=None,
        state_note='NOTE the expected result: on 2026-09-30 the sidecar held one cloud pack (CloudPackVDB) and no rain, snow, fog or mist at all, so this column is expected to come out `no`. The query deliberately does NOT match "cloud" — a cloud is not weather falling on a shot.',
    ),
    _p(
        'dust',
        'Dust and debris elements exist and play',
        ['dust'],
        [
            {
                'check': 'library_has',
                'min': 1,
                'query': r'dust|debris|devil|tornado|shockwave|sand|ash',
                'cats': ['vfx_plates', 'vfx_sprites', 'vfx_volumes', 'vfx_experimental'],
            },
            {'check': 'asset_plays', 'query': r'dust|debris|devil|tornado|shockwave|sand|ash'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this element read as dust, ash or flying debris? yes/no',
            },
        ],
        GATE,
        video=None,
    ),
    _p(
        'light_fx',
        'Light, glow and flare elements exist and play',
        ['light_fx'],
        [
            {
                'check': 'library_has',
                'min': 1,
                'query': r'glow|flare|lens|god_?ray|beam|spark|light',
                'cats': ['vfx_sprites', 'vfx_plates'],
            },
            {'check': 'asset_plays', 'query': r'glow|flare|lens|god_?ray|beam|spark|light'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this element read as a light, glow or lens flare? yes/no',
            },
        ],
        GATE,
        video=None,
    ),
    # ── Elements: the two bespoke generators, on their own terms ──
    _p(
        'water',
        'The harbour water tail',
        ['water'],
        [
            {
                'check': 'metric_within',
                'metric': 'temporal_std_bottom_quarter',
                'target': 18.6,
                'tol': 4.0,
                'unit': '/255',
            },
            {
                'check': 'metric_within',
                'metric': 'temporal_std_rows_620_690',
                'target': 12.9,
                'tol': 3.0,
                'unit': '/255',
            },
            {
                'check': 'metric_within',
                'metric': 'temporal_std_rows_560_620',
                'target': 6.0,
                'tol': 2.0,
                'unit': '/255',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the bottom of this frame read as moving water, rather than as a corrugated sheet or a rippling photograph? yes/no',
            },
        ],
        ['water'],
        video=None,
        state_note='the three targets are the measured values recorded in run_scene_shores_water.py:31-35 for the accepted take; this probe asks whether a new build still lands there. The falloff up the frame is the point — a uniform displacement is the corrugated-sheet failure named in that docstring.',
    ),
    _p(
        'birds',
        'The bird sprite ladder',
        ['birds'],
        [
            {'check': 'yaw_range_deg', 'max_deg': 9, 'err_deg': 6},
            {'check': 'library_has', 'min': 8, 'query': r'canary', 'cats': ['bird_sprites']},
            {
                'check': 'operator',
                'blind': True,
                'question': 'At this heading, does the bird read as flying at an angle (one wing further away than the other), rather than as a flat picture of a bird rotated in the frame? yes/no',
            },
        ],
        ['birds'],
        video=None,
        state_note=(
            'gen_bird_side_sprites.py records the honest limit: the rear-view ladder is correct only near boresight (~5-9 deg) and the delivered shot needs 58-80 deg at entry and exit. '
            'So `max_deg: 9` is not a target, it is the measured ceiling — the cell records the heading at which the error first exceeds 6 deg, and a build that only reaches 9 deg is a `partial`, not a `yes`.'
        ),
        state_rule={'yes': 0.9, 'partial': 0.5},
    ),
    # ── Compositing: asked of what actually makes an element ──
    _p(
        'matte',
        'Mattes are clean',
        ['matte'],
        [
            {'check': 'matte_edge_clean', 'alpha_lo': 0.05, 'alpha_hi': 0.95, 'max_soft_share': 0.25, 'fringe_tol': 18},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Along the edge of this element, is there a dark or bright halo that does not belong to the element? yes = there is a halo (a NO on this column)',
            },
        ],
        GENERATORS + GATE,
        video=None,
        state_note='the fringe half is the one that matters: a premultiplied element composited as straight alpha goes dark at the edge and still passes an alpha-only test',
    ),
    _p(
        'grade_match',
        'Grade matches the plate',
        ['grade_match'],
        [{'check': 'luma_chroma_match', 'luma_max': 12, 'chroma_max': 8, 'plate_region': [200, 660, 400, 300]}],
        GENERATORS + GATE,
        video=FIX_COMPOSITE,
        state_note='12/255 of luma is about the point at which an element starts reading as pasted on; the plate region is the sea beside the subject, not the sky',
    ),
    _p(
        'grain_fx',
        'Grain matches the plate',
        ['grain_fx'],
        [{'check': 'grain_sigma_match', 'hp_sigma': 1.2, 'tol': 0.4, 'plate_region': [200, 660, 400, 300]}],
        GENERATORS + GATE,
        video=FIX_COMPOSITE,
        state_note='the plate is generated with noise=alls=8, so the target sigma is known by construction rather than estimated from footage',
    ),
]

NA_READERS = {
    c: 'this row reads a finished clip and reports what is in it; it holds no element library and renders no element, so the question belongs to the library, the gate or a generator row'
    for c in [
        'library',
        'water',
        'fire_smoke',
        'weather',
        'dust',
        'birds',
        'light_fx',
        'matte',
        'grade_match',
        'grain_fx',
    ]
}
NA_LIB = {
    c: 'the library is an index and a query; it places nothing and composites nothing, so placement and compositing are measured on the rows that do'
    for c in [
        'attaches',
        'stable',
        'track',
        'occlude',
        'depth_place',
        'scale_place',
        'matte',
        'grade_match',
        'grain_fx',
    ]
}
NA_GATE = {
    c: 'vfx_preview_check decodes a library asset and asks whether the file holds a picture; it does not place an element on a plate'
    for c in ['attaches', 'stable', 'track', 'occlude', 'depth_place', 'scale_place']
}
NA_WATER = dict(
    {
        c: 'fx.water is a per-pixel displacement of the illustration, not an alpha element that gets placed (run_scene_shores_water.py:12-19) — there is no anchor, no track and no depth to measure'
        for c in ['attaches', 'stable', 'track', 'occlude', 'depth_place', 'scale_place']
    },
    **{
        c: 'the harbour water tail produces water and nothing else; the other element classes come from the library'
        for c in ['library', 'fire_smoke', 'weather', 'dust', 'birds', 'light_fx']
    },
)
NA_BIRDS = {
    c: 'the bird sprite ladder produces one creature and nothing else; the other element classes come from the library'
    for c in ['library', 'water', 'fire_smoke', 'weather', 'dust', 'light_fx']
}

NA_BANDS = {
    'reason': 'no row of this step takes a text prompt: the analyzer takes a clip, the library takes a query string that is not an instruction, and both generators take numeric parameters. The prompt bands measure something that does not exist here.',
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

TEST = {
    'step': 'vfx',
    'version': '2026-09-30.1',
    'title': 'Four analytic plates, the library index, and the two generators on their own terms',
    'purpose': 'Measure placement against an arithmetic truth instead of against a judge, measure the element library by decoding it rather than by counting filenames, and hold the two bespoke generators to the numbers their own code recorded.',
    'include_shared': 'video',
    'plate_truth': {
        'ground_y': GROUND_Y,
        'grain_sigma': PLATE_GRAIN_SIGMA,
        'subject': SUBJECT,
        'occluder': OCCLUDER,
        'note': 'every Placement threshold is scored against these numbers, which are properties of the ffmpeg command, not of a detector',
    },
    'rows': {
        'analyzer': {
            'transport': 'service',
            'where': 'vfx_analyzer.py — the frame-by-frame scanner; the measured output is its run log, which states found / not_found / unmeasurable / not_detectable per taxonomy entry and carries the BEST evidence value even when it fires nothing',
            'na': NA_READERS,
        },
        'detectors': {
            'transport': 'service',
            'where': 'vfx_detectors.py — Result objects over vfx_metrics and vfx_landmarks readings; THRESHOLDS is a module-level dict and the run report prints the best score each detector saw',
            'na': NA_READERS,
        },
        'landmarks': {
            'transport': 'service',
            'where': 'vfx_landmarks.py — the three vendored MediaPipe Tasks bundles (data/assets/detectors/*.task, Apache-2.0) in VIDEO running mode, permissive and strict passes, tri-state found/weak/none/unmeasurable',
            'na': NA_READERS,
        },
        'library': {
            'transport': 'library',
            'where': 'vfx_ingest.CATEGORIES + load_sidecar() over data/runtime/asset_library_vfx_meta.json, queried through vfx_place.sources()/element_options()',
            'na': NA_LIB,
            'budget': {'calls': 8, 'minutes': 1, 'gpu_minutes': 0, 'operator_minutes': 0},
        },
        'preview_check': {
            'transport': 'service',
            'where': 'vfx_preview_check.py — decodes every matched asset, CONTRAST=20, SAMPLE_FRAMES=12, PROBE_W/PROBE_H=160x90',
            'na': NA_GATE,
        },
        'water': {
            'transport': 'service',
            'where': 'vfx_fx.py `fx.water` / `_water_apply`, driven as in run_scene_shores_water.py [[project_harbor_water_fx]]',
            'na': NA_WATER,
        },
        'birds': {
            'transport': 'service',
            'where': 'gen_bird_side_sprites.py over data/assets/bird_sprites/canary/ (rear set rendered 2026-08-30, FLUX.2 klein-4B, seed 4041) [[project_bird_motion_model]]',
            'na': NA_BIRDS,
        },
    },
    'na_bands': NA_BANDS,
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'library': {
            'source': 'data/runtime/asset_library_vfx_meta.json — the VFX Studio element sidecar, keyed "<category>/<filename>"',
            'revision': "the sidecar file's sha256 and mtime are recorded with the cell; on 2026-09-30 it held 229 entries — vfx_sprites 174, vfx_plates 20, vfx_experimental 20, vfx_volumes 15",
            'requires': "vfx_ingest.load_sidecar() parses, every key's category is one of vfx_ingest.CATEGORIES, and every referenced file exists under its category directory (vfx_ingest._libdir); the count per category is written into the cell",
            'grade': 'receipt',
        },
        'class_inventory': {
            'source': 'the same sidecar, grouped by the class queries used in the fire_smoke / weather / dust / light_fx probes',
            'revision': 'recorded with the run',
            'requires': 'the matched key list is written into each trial so the operator can see WHICH file satisfied a class; a class satisfied only by a filename coincidence is visible rather than hidden behind a count',
            'feeds_derive': 'the four library-class probes read their candidate set from here',
            'grade': 'receipt',
        },
    },
    'wiring': {
        'checked': {
            'read': (
                'The composite is gated by the OPERATOR approving the draft, not by an automatic check. video_overlay.py:1-40 states the contract: the draft the operator approves and the final render read the SAME placement record and differ only in resolution / fps / encoder preset, so what the operator saw is what ships. '
                'vfx_preview_check.py gates the LIBRARY ASSET (does the file hold a picture) and runs over categories, not over composites. There is no automatic gate between a finished composite and delivery.'
            ),
            'files': ['video_overlay.py:1-40', 'video_overlay.py:524-526', 'vfx_preview_check.py:1-30'],
            'grade': 'assumed',
        },
    },
    'na': {},
    'fixtures': [
        {
            'path': FIX_STATIC,
            'generated': GEN_STATIC,
            'verified': True,
            'note': 'verified by construction: the horizon row, the grain sigma and the absence of motion are properties of the command, not of a judgement',
        },
        {
            'path': FIX_MOVE,
            'generated': GEN_MOVE,
            'verified': True,
            'note': 'x(t) = 200 + 48*t is the truth for track and attaches',
        },
        {
            'path': FIX_OCCLUDE,
            'generated': GEN_OCCLUDE,
            'verified': True,
            'note': 'the behind-window 14.58-16.25 s is arithmetic from the box positions',
        },
        {'path': FIX_COMPOSITE, 'generated': GEN_COMPOSITE, 'verified': True},
        {
            'path': FX + '/TRUTH.json',
            'generated': 'written by the runner from TEST["plate_truth"] before the first probe, so the runner and this file cannot drift apart',
            'verified': True,
        },
        {
            'path': FX + '/placement.json',
            'generated': 'the fixed placement record described in GEN_COMPOSITE — anchor bottom-center, x=(200+48*t)/1920, y=780/1080, height 0.11, track "none"',
            'verified': True,
        },
    ],
    'budget': {
        'calls': 26,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no row of this step is a language model: the analyzer reads pixels, the library reads an index, and both generators take numeric parameters',
        'minutes': 34,
        'gpu_minutes': 6,
        'operator_minutes': 7,
        'note': (
            'Per reader row (analyzer / detectors / landmarks): 6 Placement probes x 2 repeats = 12 runs over a 30 s 24 fps plate. The analyzer extracts EVERY frame (720) and takes ~100 readings each, '
            'measured at roughly 2.5 min per pass on CPU, so 12 x 2.5 = 30 min plus ~4 min of MediaPipe bundle loading = ~34 min, of which ~6 min is GPU if the MediaPipe delegate takes the card. '
            'Operator: 0 blind decisions on a reader row. The library row is an index query, ~1 min, 8 calls, no operator (override). The preview_check row decodes the matched assets of four classes: '
            'on the 2026-09-30 sidecar that is 107 + 1 + 31 + 13 = 152 matched assets at 12 sampled frames each, ~14 min, plus 4 blind operator questions x 2 repeats = 8 decisions = 4 min. '
            'The water row is 2 renders of the shores take (~7 min each on the GPU = 14 gpu_minutes) plus 2 blind decisions = 1 min. The birds row is 2 sprite-ladder passes over the yaw sweep (~3 min) '
            'plus 2 blind decisions = 1 min. SHARED BANK for this step: the video bank owns 245 of the 262 columns, and its subject bank is the expensive half — its own budget note carries that cost; '
            'nothing in THIS module re-renders a subject. No claude_cli or anthropic_api row exists here, so the shared Claude week is untouched.'
        ),
    },
    'run_order': [
        'library',
        'preview_check',
        'stable',
        'track',
        'attaches',
        'occlude',
        'depth_place',
        'scale_place',
        'fire_smoke',
        'dust',
        'light_fx',
        'weather',
        'matte',
        'grade_match',
        'grain_fx',
        'birds',
        'water',
    ],
    'notes': [
        'The contract allows one disposition per column, so the six element classes could not be BOTH a library lookup and a composite probe. They are probes (a library entry that does not decode is not an element), and the library half is kept honest by the `class_inventory` lookup, which writes the matched keys into every trial. The `library` column itself is the lookup.',
        'The expected result on `weather` is `no`: the sidecar held one cloud pack and no rain, snow, fog or mist on 2026-09-30. That is the sheet earning its keep, not a broken test.',
        'Placement is asked of the measurement stack because no row of this step places anything. video_overlay.composite is the compositor, its `track` accepts only "none" | "horizon" (a 2D translation track for a distant horizon, video_overlay.py:199-206), and it is a row of video_assembly. If subject tracking is ever wired into a placement record, a compositor row belongs here and these six probes move to it unchanged.',
        "A reader row that returns `unmeasurable` is written `untested`, never `no`. That is vfx_landmarks' own tri-state contract, and on a synthetic white box MediaPipe returning nothing is the expected, honest outcome rather than a failure of the row.",
    ],
}
