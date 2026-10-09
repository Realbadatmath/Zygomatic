# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Rigging & retarget (rigging). 2026-09-30.

Question the sheet asks: "Can we rig a mesh and move motion between bodies?" Two halves,
and the rows split along the seam: `unirig` and `blender_rig` MAKE a rig, `delta_retarget`
and `soma` MOVE motion onto one. Neither half can answer the other's questions, so the
per-row `na` map is as much of the test as the probes are — a sheet that shows UniRig a
green tick for "keeps ground contacts" would be lying about what was run.

The shape of the test
---------------------
One fixed body, one fixed clip, one fixed creature.

  THE BODY is data/assets/base_body_rig/male_realistic — the CC0 base at 1.6900 m with the
  31-bone cmu_mb skeleton, 11 674 vertices and 0 unweighted vertices, on disk and pinned.
  Every rig-making probe rigs THAT mesh, so two riggers are compared on identical geometry.

  THE CLIP is cmu/02_01, two seconds of walk. It was chosen because its own stance foot
  progression angle is 1 degree, which makes it a ruler: the A-pose toe-out leak the house
  found on 2026-09-24 (base-body rest thighs 8.7 deg off vertical, each Foot bone 19.6 deg
  lateral, so every retargeted walk played with a 40 deg V between the feet) shows up as
  pure error against a clip that walks straight. `foot_progression_angle_max` measures
  exactly that, and it is the reason `retarget` is not a yes/no question about "looks fine".

  THE CREATURE is pufferball_solid, the mesh the UniRig bench of 2026-09-05 already ran on.

What the columns are measured with
----------------------------------
Nothing here is a judgement about a render. A rig is geometry and constraints, so every
check is arithmetic over the armature and the deformed mesh: weights that sum to 1, a
vertex with no bone holding it, a bone chain that an IK target actually drags, five finger
chains of three phalanges, millimetres of foot slide during stance, degrees of toe-out,
triangles that intersect after a 45-degree bend. A BLIND operator question sits beside the
number only where the number cannot see the whole thing (does the bent limb still look like
a limb) and it can never rescue a trial the arithmetic failed.

Two columns are LOOKUPS with real receipts rather than probes, because re-running them
would measure nothing new:

  `benched`   $ZYG_CREATURE_DATASETS/d0e44ab002ad/mesh_rigged/rig_bench.json
              — 2026-09-05, Blender 4.3.2, seed 12345, 36.6 s, 4 cells (2 meshes x UniRig's
              predicted skin vs Blender's automatic weights). Its verdict on pufferball is
              `unirig_beats_auto: false` on BOTH bends. That is a receipt, not an opinion.
  `zero_pose` the standing fact: a SOMA capture does NOT start in a T-pose, which is why
              motion_capture.py prepends one (blender_scripts/proxy_actor.py:1114), and why
              align_rest turns the MPFB A-pose (arms 40-65 deg away from the CMU T-pose) to
              the BVH frame-1 pose before baking (proxy_actor.py:21, :97).

A rigger has no prompt. The four Prompt bands are `na` at step level with the reason.
"""

from __future__ import annotations

from zyg_workflows.paths import ZYG_CREATURE_DATASETS

FX = 'capability_tests/fixtures/rigging'
MANIFEST = FX + '/MANIFEST.json'
BASE_RIG = 'data/assets/base_body_rig/male_realistic/male_realistic.json'
#: The Gray Wolf's rigging bench, next to the creature dataset it was cut from.
MESH_RIGGED = ZYG_CREATURE_DATASETS + '/d0e44ab002ad/mesh_rigged'
BENCH = MESH_RIGGED + '/rig_bench.json'

# ── check kinds this module adds ────────────────────────────────────────────────────────
# All arithmetic over the armature and the deformed mesh, inside one headless Blender run.
CHECK_KINDS = {
    'rig_produced': 'the call returned an armature with >= `min_bones` deform bones, bound to the fixture mesh by an Armature modifier at index 0, and left no more than `max_extra_objects` unskinned objects in the file (UniRig leaves a stray unit icosphere — build_pufferball_actor.py:128)',
    'skin_weights_normalised': "every vertex's bone weights sum to 1.0 within `tolerance`, and the share of vertices carrying no weight at all is <= `max_unweighted`",
    'weight_floor': 'in the vertex region named by `region` (torso|limbs|head), the share of vertices whose LARGEST single bone weight is below `min` is <= `max_share` — a vertex smeared across five bones at 0.2 each belongs to nobody and shears when any of them moves',
    'bone_names_convention': 'the share of deform bones whose name matches one of `patterns` (regex) or appears in `allow` is >= `share`; a rig whose bones are bone_0 .. bone_n scores 0 on this check',
    'joint_count_range': 'the number of deform bones is between `min` and `max`',
    'ik_chain_solves': 'the chain named in `chain` carries an IK constraint with a target, and moving that target `delta_m` metres moves the chain tip by >= `share` of `delta_m` while the chain root moves less than `root_max_m`',
    'control_bones_present': 'at least `min` NON-deforming control bones exist, each with a custom shape or in a control bone-collection, and together they cover every group in `groups`',
    'hand_phalanx_count': 'each hand has exactly `fingers` finger chains of exactly `phalanges` deform bones each, parented head-to-tail, with a vertex group per bone',
    'face_bones_present': 'every role in `roles` (jaw|eye_l|eye_r|lid_upper|lid_lower|tongue) is present as a deform bone, and rotating it `test_deg` degrees moves at least `min_verts` mesh vertices by more than `min_mm`',
    'bend_deform_sane': 'after rotating the bone named in `bone` by `deg`, the area-outlier face fraction (faces whose area left the `area_window` ratio band) is <= `max_area_frac`, the mesh volume changes by <= `max_dvol_pct`, and self-intersecting triangles rise by no more than `max_selfint_over_rest` above the rest pose — the rig_bench measure: BVHTree self-overlap on the triangulated world-space deformed mesh, pairs sharing a vertex dropped',
    'foot_slide_max': 'over the retargeted clip, the horizontal travel of a foot during its OWN stance phase (the frames the fixture marks its toe as planted) is <= `max_mm`',
    'foot_progression_angle_max': "the angle between a foot's forward axis and the direction of travel, during that foot's stance phase, is <= `max_deg`; the fixture clip cmu/02_01 walks with a 1 deg progression angle of its own, so anything above that came out of the rig's rest pose (the A-pose toe-out leak, blender_scripts/proxy_actor.py:98-105)",
    'contact_pair_keep': 'every contact pair the fixture declares ((bone, target, frame range)) stays within `max_mm` for every frame of its range after the retarget',
    'proportion_measures_keep': "after retargeting onto the second body, every measurement in `measures` taken off the POSED actor is within `tolerance_m` of the same measurement on that actor's own rest body — the motion may move the actor, never stretch it",
    'glb_roundtrip_bones': 'export to GLB and re-import: bone count, bone names and bone parent hierarchy are identical, every vertex group survives with the same name, and every rest bone direction is within `max_deg` of the original',
}

# One fixed condition for every probe. Two repeats: a rig build is a deterministic-looking
# thing that is often not (UniRig is a network), and the second run is what tells them apart.
COND = {
    'repeats': 2,
    'blender': 'headless, flock /tmp/claude-1000/arch_ext_blender.lock, blender -b --factory-startup -noaudio — every Blender run in this house serialises on that lock',
    'body': 'data/assets/base_body_rig/male_realistic: CC0 base body, 1.6900 m, 11 674 vertices, 31-bone cmu_mb skeleton, 0 unweighted vertices (measured 2026-09-23)',
    'clip': 'cmu/02_01, frames 1-48 at 24 fps (2.0 s of walk); its own stance foot progression angle is 1 degree',
    'weld': 'the fixture mesh is welded at the distance the bench pinned for it (pufferball_solid 1e-4, mv 3e-3) before rigging — vertex quality, not mesh size, decides whether a rig solves at all (rig_bench.json params.weld_probe)',
    'timeout_s': 1800,
}

MAKERS = ['unirig', 'blender_rig']
MOVERS = ['delta_retarget', 'soma']
ALL_ROWS = MAKERS + MOVERS

# The convention a deform bone name has to meet. cmu_mb / Mixamo: a side prefix, a segment
# noun, an optional index. `bone_47` matches nothing here, which is the point.
NAME_PATTERNS = [
    r'^(Left|Right)?(Hips?|Spine\d?|Chest|Neck\d?|Head(End)?|Shoulder|Arm|ForeArm|Hand|'
    r'HandThumb\d|HandIndex\d|HandMiddle\d|HandRing\d|HandPinky\d|UpLeg|Leg|Foot|ToeBase|Toes?)$',
    r'^(mixamorig:)?(Left|Right)?[A-Z][A-Za-z]+\d?$',
]
NAME_ALLOW = ['Root', 'Hips', 'LHipJoint', 'RHipJoint', 'LowerBack', 'LeftFingerBase', 'RightFingerBase']


def _p(pid, title, feeds, fixture, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': fixture, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'rig_on_base',
        'A usable rig on the pinned base body',
        ['rigs'],
        BASE_RIG,
        [
            {'check': 'rig_produced', 'min_bones': 16, 'max_extra_objects': 0},
            {'check': 'skin_weights_normalised', 'tolerance': 0.01, 'max_unweighted': 0.0},
            {
                'check': 'bend_deform_sane',
                'bone': 'LeftUpLeg',
                'deg': 30.0,
                'area_window': [0.5, 2.0],
                'max_area_frac': 0.01,
                'max_dvol_pct': 4.0,
                'max_selfint_over_rest': 100,
            },
        ],
        MAKERS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            "All three or it is not a usable rig. 0 unweighted is not a stretch target: the house's own MPFB bone-heat pass already reaches it on this body, with the "
            '1092 eye vertices pinned to Head. The thresholds on the bend are the rig_bench numbers for a leg at 30 degrees (area fraction 0.0043 for UniRig, 0.0 for '
            "Blender's automatic weights; volume 0.31 % / -3.18 %)."
        ),
    ),
    _p(
        'weights_floor',
        'No vertex belongs to nobody',
        ['weights'],
        BASE_RIG,
        [
            {'check': 'weight_floor', 'region': 'torso', 'min': 0.3, 'max_share': 0.0},
            {'check': 'weight_floor', 'region': 'limbs', 'min': 0.3, 'max_share': 0.02},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This strip shows the same body at rest and with the left thigh rotated 30 degrees. Is the hip a fold rather than a crease, a collapse or a pinch? yes/no',
            },
        ],
        MAKERS,
        state_note=(
            'A vertex whose largest weight is under 0.3 is shared between four or more bones and shears whenever any of them moves — it passes a "weights sum to 1" check '
            'and fails in animation, which is why the floor is a separate column from `rigs`. The limbs are allowed 2 % for the wrist and ankle transitions.'
        ),
    ),
    _p(
        'naming',
        'Bone names a human and a retargeter can both read',
        ['naming_rig'],
        BASE_RIG,
        [{'check': 'bone_names_convention', 'patterns': NAME_PATTERNS, 'allow': NAME_ALLOW, 'share': 0.95}],
        MAKERS + ['soma'],
        state_rule={'yes': 0.95, 'partial': 0.5},
        state_note=(
            'The receipt this column exists for: UniRig names all 59 bones of the pufferball rig `bone_<n>` (measured 2026-09-15), so build_pufferball_actor.py has to '
            'derive every chain from the TOPOLOGY and then pin it with asserts. That is real cost, and it belongs on the sheet as a measured 0, not as a footnote.'
        ),
    ),
    _p(
        'ik_solves',
        'An IK chain that actually drags the limb',
        ['ik'],
        BASE_RIG,
        [
            {
                'check': 'ik_chain_solves',
                'chain': 'LeftUpLeg->LeftFoot',
                'delta_m': 0.10,
                'share': 0.9,
                'root_max_m': 0.005,
            },
            {
                'check': 'ik_chain_solves',
                'chain': 'LeftArm->LeftHand',
                'delta_m': 0.10,
                'share': 0.9,
                'root_max_m': 0.005,
            },
        ],
        ['blender_rig'],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='"An IK constraint exists" is not the question — a constraint with no target, or one whose chain length is wrong, exists and does nothing. Moving the target and measuring the tip is the question.',
    ),
    _p(
        'controls_exist',
        'Something an animator can grab',
        ['controls'],
        BASE_RIG,
        [
            {
                'check': 'control_bones_present',
                'min': 6,
                'groups': ['root', 'hips', 'foot_l', 'foot_r', 'hand_l', 'hand_r'],
            }
        ],
        ['blender_rig'],
        state_note='non-deforming bones with a custom shape, or a named control collection. The 31-bone cmu_mb skeleton is a DEFORM rig with no control layer, so the honest expected answer here is no — measured rather than assumed.',
    ),
    _p(
        'face_bones',
        'A face rig, or honestly none',
        ['face_rig'],
        BASE_RIG,
        [
            {
                'check': 'face_bones_present',
                'roles': ['jaw', 'eye_l', 'eye_r'],
                'test_deg': 10.0,
                'min_verts': 50,
                'min_mm': 1.0,
            }
        ],
        MAKERS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the cmu_mb skeleton ends at Head; the 1092 eye vertices are weighted to Head and do not move independently. Expect no on both rows and record it, because a downstream facial pass needs to know it must supply its own.',
    ),
    _p(
        'hand_phalanges',
        'Five fingers of three bones each',
        ['hand_rig'],
        BASE_RIG,
        [{'check': 'hand_phalanx_count', 'fingers': 5, 'phalanges': 3}],
        MAKERS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'The measured fact this column has to surface: the 31-bone cmu_mb rig on the base body has NO per-finger bones at all — LeftFingerBase is a single stub and '
            'the thumb is another. A hand that cannot be posed is a hand the gesture work has to rebuild, and it should be a red cell, not a silence.'
        ),
    ),
    _p(
        'walk_retarget',
        'Two seconds of walk, onto the rig, without sliding',
        ['retarget'],
        MANIFEST + '#walk02_01',
        [
            {'check': 'foot_slide_max', 'max_mm': 20},
            {'check': 'foot_progression_angle_max', 'max_deg': 8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This is a two-second walk played on a rigged body, seen from the front and from the side. Does it read as an ordinary walk — feet pointing where the body is going, no skating, no hips swinging past the feet? yes/no',
            },
        ],
        MOVERS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            '8 degrees is the line because the clip itself walks at 1 degree and the leak it is there to catch was ~20 degrees per foot. The delta retarget keeps whatever '
            'the rest pose says a bone does NOT do, so an A-pose with its feet turned out hands every walk a 40 degree V; aligning UpLeg/Leg/Foot turns 9.6/10.4/19.2 '
            'degrees out of the rest pose (proxy_actor.py ALIGN_BONES, 2026-09-24). This column measures whether that is still true.'
        ),
    ),
    _p(
        'abel_retarget',
        "An adult's walk on a child's body",
        ['proportion_retarget'],
        MANIFEST + '#abel_walk',
        [
            {
                'check': 'proportion_measures_keep',
                'tolerance_m': 0.01,
                'measures': ['stature', 'upper_arm_length', 'forearm_length', 'thigh_length', 'shank_length'],
            },
            {'check': 'foot_slide_max', 'max_mm': 25},
            {
                'check': 'operator',
                'blind': True,
                'question': "A child-sized body walks with an adult's motion. Are the limbs the child's own length throughout (no rubber-banding, no floating hands), whatever the stride looks like? yes/no",
            },
        ],
        ['delta_retarget'],
        state_note=(
            'Abel, bible height 1.520 m, against the 1.6900 m base. 10 mm of tolerance, because a retarget that lengthens a limb to reach a target is the failure mode '
            "here and it is visible far below a centimetre. Stride length is deliberately NOT checked: a child taking an adult's stride is the operator's call, not the rig's fault."
        ),
    ),
    _p(
        'contacts',
        'Ground and hand contacts survive the transfer',
        ['contact_keep'],
        MANIFEST + '#contacts',
        [{'check': 'contact_pair_keep', 'max_mm': 15}, {'check': 'foot_slide_max', 'max_mm': 20}],
        MOVERS,
        state_note='the fixture declares each contact as (bone, target, frame range) — planted toe to ground plane, and a hand to a rail through a climb. A retarget that is right everywhere except at the contacts is the one that costs an animator a day.',
    ),
    _p(
        'wolf_rig',
        'A body that is not a human',
        ['creature_rig'],
        MANIFEST + '#wolf',
        [
            {'check': 'rig_produced', 'min_bones': 20, 'max_extra_objects': 0},
            {'check': 'skin_weights_normalised', 'tolerance': 0.01, 'max_unweighted': 0.0},
            {
                'check': 'bend_deform_sane',
                'bone': 'hind_leg_root',
                'deg': 30.0,
                'area_window': [0.5, 2.0],
                'max_area_frac': 0.01,
                'max_dvol_pct': 4.0,
                'max_selfint_over_rest': 100,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "A four-legged animal is shown at rest and with one hind leg bent 30 degrees. Is the bent leg still a leg — bending at the animal's own joint, with the haunch keeping its shape? yes/no",
            },
        ],
        ['unirig'],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'This is the column UniRig exists for: one network for humanoids, quadrupeds, birds and things with no name (mesh_studio_ops/a_shape.py:737-740). The '
            "thresholds are the bench's own pufferball numbers so the two are readable together."
        ),
    ),
    _p(
        'glb_roundtrip',
        'Survives the export it will actually ship through',
        ['export_rig'],
        BASE_RIG,
        [{'check': 'glb_roundtrip_bones', 'max_deg': 1.0}, {'check': 'glb_up_axis'}],
        ALL_ROWS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'Bone count, names, hierarchy and rest directions identical after a GLB round trip, and the result +Y up with the subject standing ([[project_body_plates_gltf_upaxis]]) '
            '— a Z-up export is a fail, not something the next stage fixes up.'
        ),
    ),
]

NA_BANDS = {
    'reason': 'a rigger is handed a mesh and a skeleton, and a retargeter is handed a clip and a rig; neither takes an instruction in words, so there is no prompt to damage, shorten, clarify or steer on this step',
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

NA_NO_RIG = (
    'this row does not build a rig — it moves motion onto a rig somebody else built, '
    'so this property belongs to the rig it was handed, not to the retarget'
)
NA_NO_MOTION = (
    'this row builds a rest-pose rig and never sees a second pose in time; retarget '
    'is measured on the rows that actually transfer motion'
)
NA_HUMAN_ONLY = (
    'this row rigs the MPFB / cmu_mb human skeleton only, by construction — there '
    'is no non-human template for it to fit, so the question has no answer here'
)
NA_NO_SKIN = (
    'the SOMA capture path produces a joint track, not a skinned body; there is no '
    'mesh bound to weights anywhere in it for this question to be asked of'
)

TEST = {
    'step': 'rigging',
    'version': '2026-09-30.1',
    'title': 'One pinned base body, one straight-walking clip, one creature',
    'purpose': (
        'Measure rigging and retarget as geometry rather than as opinion: weights that sum to 1 with nobody left out, an IK target that drags its chain, five fingers of '
        'three bones, millimetres of foot slide and degrees of toe-out against a clip whose own progression angle is 1 degree.'
    ),
    'include_shared': ['video', 'geometry'],
    'rows': {
        'unirig': {
            'transport': 'service',
            'where': 'UniRig (VAST-AI/UniRig) via the mesh studio op rig_unirig (mesh_studio_ops/a_shape.py:737); code MIT, weights MIT on the HF model card, trained on Articulation-XL2.0; predicts a skeleton and skin weights for an arbitrary mesh',
            'model': 'VAST-AI/UniRig',
            'na': {
                'ik': 'UniRig predicts a deform skeleton and skin weights only; it emits no constraints at all, so there is no IK chain for this question to be asked of',
                'controls': 'UniRig predicts deform bones only — no control bones, no custom shapes, no bone collections; an animator control layer is not part of what it returns',
                'retarget': NA_NO_MOTION,
                'proportion_retarget': NA_NO_MOTION,
                'contact_keep': NA_NO_MOTION,
            },
        },
        'blender_rig': {
            'transport': 'blender',
            'where': 'the mesh studio rigging ops on the studio-ext seam — rig_mpfb / base_body_rig (blender_scripts/base_body_rig.py), headless blender -b under flock /tmp/claude-1000/arch_ext_blender.lock; the exact rig the CC0 base bodies were authored for',
            'model': 'MPFB / cmu_mb 31-bone skeleton, bone-heat weights',
            'na': {
                'creature_rig': NA_HUMAN_ONLY,
                'retarget': NA_NO_MOTION,
                'proportion_retarget': NA_NO_MOTION,
                'contact_keep': NA_NO_MOTION,
            },
        },
        'delta_retarget': {
            'transport': 'service',
            'where': 'the delta retarget in the movement studio — blender_scripts/proxy_actor.py (align_rest + ALIGN_BONES, then Copy Rotation in world space), driven through studio_ext_server/movement_rig.py',
            'model': 'house delta retarget (rest-pose delta + world-space copy rotation)',
            'na': {
                'rigs': NA_NO_RIG,
                'weights': NA_NO_RIG,
                'joint_count': NA_NO_RIG,
                'naming_rig': NA_NO_RIG,
                'ik': NA_NO_RIG,
                'controls': NA_NO_RIG,
                'face_rig': NA_NO_RIG,
                'hand_rig': NA_NO_RIG,
                'creature_rig': NA_NO_RIG,
            },
            'budget': {
                'calls': 420,
                'minutes': 330,
                'gpu_minutes': 120,
                'note': 'no rig is built and no network runs: a retarget is a Blender bake. ~30 s per clip x 420 = 210 min of CPU plus ~120 min of GPU for the preview renders the operator is shown.',
            },
        },
        'soma': {
            'transport': 'service',
            'where': 'the SOMA capture path — tools/gem_capture.py over GEM-X demo_soma, then soma_bvh_to_cmu_mb, wired as motion_capture.capture_from_video; BVH out is 78 joints, 6 channels each, offsets in cm, Zrotation Yrotation Xrotation',
            'model': 'GEM-X / SOMA 78-joint skeleton',
            'na': {
                'rigs': NA_NO_SKIN,
                'weights': NA_NO_SKIN,
                'ik': NA_NO_SKIN,
                'controls': NA_NO_SKIN,
                'face_rig': NA_NO_SKIN,
                'hand_rig': NA_NO_SKIN,
                'creature_rig': 'the SOMA body model is a human skeleton by construction; there is no non-human variant of it to capture with',
                'proportion_retarget': "the capture path emits one track in the captured subject's own proportions; moving it onto a differently-proportioned body is the delta retarget's job and is measured there",
            },
            'budget': {
                'calls': 420,
                'minutes': 215,
                'gpu_minutes': 200,
                'note': 'measured on a 4 s / 96-frame / 854x480 clip with a warm preprocess: demo_soma 20.5 s + export 7.6 s = ~28 s per clip, VRAM peak 1136 MiB. 420 clips x 28 s = 196 min, plus ~19 min of BVH-to-cmu_mb conversion on the CPU.',
            },
        },
    },
    'na_bands': NA_BANDS,
    'probes': PROBES,
    'derive': {
        'joint_count': {
            'from': (
                'the number of DEFORM bones in the produced (or captured) skeleton, counted off the armature in the same run, with the vertex-group count beside it. '
                'Receipts to read the new number against: the cmu_mb rig on the CC0 base bodies is 31 bones / 32 weight groups with 0 unweighted vertices '
                '(measured 2026-09-23); UniRig on pufferball_solid is 59 bones and 59 vertex groups (rig_bench.json, 2026-09-05); a SOMA BVH is 78 joints.'
            ),
            'grade': 'measured',
            'unit': 'count',
        },
    },
    'lookup': {
        'zero_pose': {
            'value': 'NOT a T-pose on the capture path, and not an A-pose on the MPFB side either — every rest pose in this house is a known, different thing, and each transfer names which.',
            'grade': 'receipt',
            'requires': [
                'blender_scripts/proxy_actor.py:1114 — "A capture does not start in a T-pose, so motion_capture.py prepends one"',
                'blender_scripts/proxy_actor.py:21 and :97 — align_rest turns the named bones to the BVH frame-1 T-pose before baking, because MPFB rests 40-65 degrees away from the CMU T-pose, which is too much to carry as an offset',
                'blender_scripts/proxy_actor.py:98-105 — the base body A-pose stands with its feet turned out: rest thighs 8.7 degrees off vertical, each Foot bone 19.6 degrees lateral (measured 2026-09-24)',
                "blender_scripts/proxy_actor.py:352 — align_rest's 58 degree turn to the BVH T-pose bakes into the ribcage",
                'GEM-X capture facts, 2026-09-20: the SOMA BVH is 78 joints, 6 channels per joint, offsets in cm, channel order Zrotation Yrotation Xrotation',
            ],
            'note': 'the column is scored yes for a row whose rest pose is DOCUMENTED and read by the code that consumes it, no for a row that assumes T-pose. The receipt above is what makes it a lookup rather than a probe: re-running it would measure the same four source lines.',
        },
        'benched': {
            'value': "UniRig: benched 2026-09-05 — and it did NOT beat Blender's automatic weights. blender_rig / delta_retarget / soma: no comparative bench of this kind exists yet.",
            'grade': 'receipt',
            'requires': [
                BENCH
                + " — generated 2026-09-05T18:23:09, Blender 4.3.2, seed 12345, 36.6 s total, 4 cells (pufferball_solid and mv, each with UniRig's predicted skin and Blender's automatic weights)",
                'its gate block: pufferball_solid `unirig_beats_auto: false` and `unirig_beats_auto_over_rest: false` — on the 45 degree tail bend UniRig had 8623 self-intersecting triangles against 8575, and an area-outlier fraction of 0.0138 against 0.0028',
                'its params block: self-intersection is BVHTree self-overlap on the triangulated world-space deformed mesh with vertex-sharing pairs dropped; the weld distance is probed per mesh (pufferball_solid 1e-4, mv 3e-3) and the note records that it is vertex quality, not mesh size',
                MESH_RIGGED + '/rig_bench.py — the bench script, next to its own receipt',
            ],
            'note': 'a row with no bench is a no on this column, not a blank. The point of the question is that "we installed it" and "somebody measured it against the alternative" are different states.',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': BASE_RIG,
            'verified': True,
            'note': 'on disk and pinned: the CC0 base body sidecar (schema zyg.base_body_rig/1) beside male_realistic.blend — 1.6900 m, 31 bones, 11 674 vertices, 0 unweighted, licence recorded in the file',
        },
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['retarget', 'proportion_retarget', 'contact_keep'],
            'generated': (
                'python3 -m zyg_workflows.tools.rigging_fixture --clip cmu/02_01 --frames 1:48 --body male_realistic --child abel '
                f'--wolf {MESH_RIGGED}/pufferball_solid_unirig.glb '
                '--out capability_tests/fixtures/rigging — writes MANIFEST.json with the clip, the two bodies, the welded wolf mesh and EMPTY '
                'stance_phases and contact_pairs lists'
            ),
            'how_to_verify': (
                'scrub the 48 frames of cmu/02_01 and mark, per foot, the first and last frame its toe is planted (stance_phases), then mark the contact pairs '
                "(bone, target, frame range) for the planted toe and for the hand on the rail in the climb. Measure the clip's own foot progression angle from "
                'those marks and confirm it is 1 degree +/- 1 before setting verified = true. Until then the three retarget columns ship untested "key unverified" '
                '— foot slide and toe-out cannot be measured against a stance phase nobody identified.'
            ),
        },
    ],
    'run_order': [
        'glb_roundtrip',
        'naming',
        'hand_phalanges',
        'face_bones',
        'controls_exist',
        'rig_on_base',
        'weights_floor',
        'ik_solves',
        'wolf_rig',
        'walk_retarget',
        'contacts',
        'abel_retarget',
        'SHARED:moves',
    ],
    'budget': {
        'calls': 426,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'rigging and retarget take a mesh, a skeleton and a clip; no language model is called on this step, so no tokens and no share of the Claude week are spent',
        'minutes': 832,
        'gpu_minutes': 800,
        'operator_minutes': 202,
        'note': (
            'Per row, for unirig (the dearest maker). DOMAIN: 12 probes x 2 repeats = 24 headless Blender runs, and a UniRig prediction is ~40 s on the GPU plus ~60 s of '
            'Blender around it, so ~40 min. SHARED BANK (video owns the Moves bands here): 132 subjects x 3 seeds = 396 clips, each rigged and driven and rendered at ~2 min '
            '= 792 min. Total ~832 min = ~14 h, 800 of them on the GPU; the subject bank is 95 % of it, which is why run_order puts it last and every domain column is '
            'filled inside the first 40 minutes. The geometry bank adds no renders of its own on this step — it owns the universal and space columns, which are read off '
            "the same exports. OPERATOR: 4 blind questions x 2 repeats = 8 decisions = 4 min, plus the bank's 396 blind subject decisions at 30 s = 198 min. Plus a "
            'ONE-OFF ~40 min marking the stance phases and contact pairs of cmu/02_01 (until then three columns are blocked). No claude_cli or anthropic_api row on this '
            'step: the shared Claude week is untouched.'
        ),
    },
    'notes': [
        (
            'The rows are two different trades and the `na` map says so: unirig and blender_rig answer The rig band, delta_retarget and soma answer the Retarget band, and each is '
            '`na` on the other with a written reason. Reading a green tick across the whole row would be reading a rig that was never built.'
        ),
        (
            '`controls`, `face_rig` and `hand_rig` are expected to come back NO on every row here, and they are still probes rather than na, because "nobody has built it yet" and '
            '"it cannot be built" are different facts and only the first one is true. The 31-bone cmu_mb skeleton has no finger bones at all — the gesture work rebuilds them, and '
            'that cost should be visible in this sheet rather than buried in that one.'
        ),
        (
            'foot_progression_angle_max is the only check here that came out of a defect rather than a specification. The operator saw a "weird, splay-footed gait" on 2026-09-24; '
            'the measurement behind it was rest thighs 8.7 degrees off vertical and Foot bones 19.6 degrees lateral against a clip that walks at 1 degree. A test that only asked '
            '"does the motion transfer" would have passed every one of those walks.'
        ),
        (
            'The bench receipt is deliberately a lookup and not a probe. Re-running rig_bench.py would produce the same four cells; what the sheet needs is that somebody already '
            "ran it, what it said (UniRig did not beat Blender's automatic weights on pufferball) and where the file is."
        ),
    ],
}
