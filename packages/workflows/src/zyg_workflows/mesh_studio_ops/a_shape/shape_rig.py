# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""a_shape.shape_rig — the Shape and Rig sections.

Moved verbatim from mesh_studio_ops/a_shape.py lines 815-1302 (2026-10 split).
"""

from zyg_workflows.mesh_studio import b, e, f, i, s
from zyg_workflows.mesh_studio_ops.a_shape.library_import import _side

# ══ SHAPE ═══════════════════════════════════════════════════════════════════
# The body itself, driven by morph targets rather than by moving vertices. This
# is the section that talks to Character Studio: a body opened from the bible
# arrives with these values already set, and changing one here is changing the
# character, which is why each is scored against the identity lock.

_side(
    'sh_height',
    'Height',
    'Shape',
    'Set stature through the height macro rather than by scaling — the limbs '
    'and torso re-proportion the way a taller body actually is, instead of a '
    'small body photographed closer. Scaling and this are not the same '
    'operation and confusing them is why some characters read as dolls.',
    '<path d="M12 4.2v15.6"/><path d="M8.6 6.4L12 3.2l3.4 3.2"/><path d="M8.6 17.6L12 20.8l3.4-3.2"/>',
    [
        f('height_m', 'Height (m)', 1.75, 0.6, 2.4, 0.005),
        b('keep_head', 'Keep head size absolute', False),
        b('rescale_rig', 'Re-fit the rig', True),
    ],
)

_side(
    'sh_head_ratio',
    'Head ratio',
    'Shape',
    'How many head-heights tall the figure is — the single strongest cue for '
    'age and register. Around 7.5 reads as an adult, 6 as a teenager, 4 as a '
    'toddler and 3 as a cartoon; moving this moves how the character reads '
    'more than any other slider here.',
    '<circle cx="12" cy="6" r="2.6"/><path d="M12 8.6v11.4"/><path d="M4.6 6h3.4M4.6 20h3.4M6.3 6v14"/>',
    [f('heads', 'Heads tall', 7.5, 2.5, 9.0, 0.05), b('from_body', 'Resize the body, not the head', True)],
)

_side(
    'sh_limb_length',
    'Limb length',
    'Shape',
    'Lengthen or shorten arms and legs against a fixed total height, '
    'separately or together. Long-legged and long-armed are different '
    'silhouettes and different reaches, and a rig retargeted from motion '
    'capture cares about both.',
    '<path d="M8.4 4.4l-2.6 6.2 2 6.4"/><path d="M15.6 4.4l2.6 6.2-2 6.4"/>'
    '<circle cx="12" cy="4" r="1.6"/><path d="M7.8 17l1.6 3M16.2 17l-1.6 3"/>',
    [
        f('arms', 'Arms', 0.0, -50.0, 50.0, 1.0),
        f('legs', 'Legs', 0.0, -50.0, 50.0, 1.0),
        b('link', 'Move both together', False),
        b('keep_height', 'Keep total height', True),
    ],
)

_side(
    'sh_torso_length',
    'Torso length',
    'Shape',
    'The length of the trunk between hips and shoulders, independent of the '
    'limbs. Short torso with long legs and the reverse are both common and '
    'both are lost when a body is only ever scaled as a whole.',
    '<path d="M8.6 6.6h6.8l-1 10.8H9.6z"/><path d="M12 6.6v10.8"/>'
    '<path d="M5.4 6.6v10.8"/><path d="M4.2 6.6h2.4M4.2 17.4h2.4"/>',
    [
        f('v', 'Longer / shorter', 0.0, -50.0, 50.0, 1.0),
        b('keep_height', 'Keep total height', True),
        b('move_waist', 'Move the waist line with it', True),
    ],
)

_side(
    'sh_shoulder_width',
    'Shoulder width',
    'Shape',
    'Widen or narrow the shoulder girdle. Together with hip width this is '
    'the whole of the V-versus-A silhouette, and it is read from further '
    'away than any facial feature.',
    '<path d="M4.6 9.4c2.6-2.4 12.2-2.4 14.8 0"/>'
    '<circle cx="12" cy="5.6" r="2.2"/>'
    '<path d="M7 9.4l1 9.8M17 9.4l-1 9.8"/>',
    [f('v', 'Wider / narrower', 0.0, -50.0, 50.0, 1.0), b('with_clavicle', 'Move the clavicle bones too', True)],
)

_side(
    'sh_hip_width',
    'Hip width',
    'Shape',
    'Widen or narrow the pelvis. Changes where the legs hang from, so it '
    'changes the stance and the walk — a rigged body needs its weights '
    'checked at the hip after a large move here.',
    '<path d="M7.4 7.2l-1.2 6.4c2 2.4 9.6 2.4 11.6 0l-1.2-6.4"/><path d="M9 15.6l-.8 4.2M15 15.6l.8 4.2"/>',
    [f('v', 'Wider / narrower', 0.0, -50.0, 50.0, 1.0), b('with_pelvis', 'Move the pelvis bones too', True)],
)

_side(
    'sh_muscle',
    'Muscle',
    'Shape',
    'Muscle mass on the same skeleton — definition and bulk on the limbs, '
    'chest and back. Separate from fat on purpose: a body can be lean and '
    'muscular, heavy and soft, or both at once, and one slider for "build" '
    'cannot express that.',
    '<path d="M4.8 14.6c2.4-4.4 5.4-5.6 8.2-3.8"/>'
    '<path d="M13 10.8c3.4-.6 5.8 1.4 6.2 4.6-2.8 2.6-7.2 2.4-9.6-.4"/>'
    '<path d="M6.6 9.2l2.2 2.6"/>',
    [
        f('v', 'Muscle', 50.0, 0.0, 100.0, 1.0),
        f('definition', 'Definition', 50.0, 0.0, 100.0, 1.0),
        b('upper_only', 'Upper body only', False),
    ],
)

_side(
    'sh_fat',
    'Fat',
    'Shape',
    'Body fat distributed the way it actually distributes — belly, hips and '
    'face fill before the forearms do. Independent of muscle, and of weight: '
    'the studio stores the two morphs rather than a single number that '
    'cannot be undone into them.',
    '<ellipse cx="12" cy="13.8" rx="6.4" ry="5.4"/>'
    '<circle cx="12" cy="5.8" r="2.4"/>'
    '<path d="M7.4 11.2c2.8 1.6 6.4 1.6 9.2 0"/>',
    [
        f('v', 'Body fat', 40.0, 0.0, 100.0, 1.0),
        e('distribution', 'Distribution', 'even', ('even', 'belly', 'hips', 'upper')),
        b('face', 'Include the face', True),
    ],
)

_side(
    'sh_age_morph',
    'Age morph',
    'Shape',
    'Move the body along the age axis — proportion, muscle tone, posture and '
    'skin slackness together, because they move together in life. Below '
    'about 18 the head ratio is driven from here as well, so age and head '
    'ratio do not have to be kept in agreement by hand.',
    '<path d="M6.4 18.6c0-3.4 2.6-5.4 5.6-5.4s5.6 2 5.6 5.4"/>'
    '<circle cx="12" cy="8.2" r="3.4"/>'
    '<path d="M3.6 20.4h16.8"/><path d="M8.4 5.2l-1.6-1.6M15.6 5.2l1.6-1.6"/>',
    [
        f('years', 'Age (years)', 30.0, 1.0, 90.0, 1.0),
        b('drive_head_ratio', 'Drive the head ratio', True),
        b('posture', 'Include posture', True),
    ],
)

_side(
    'sh_gender_morph',
    'Gender morph',
    'Shape',
    'A continuous axis between the two base bodies rather than a switch — '
    'shoulder-to-hip ratio, chest, jaw and brow shift together along it. '
    'Continuous because most characters worth building are not at either '
    'end of it.',
    '<circle cx="9.4" cy="9.4" r="3.8"/><path d="M12.1 12.1l5.4 5.4"/>'
    '<path d="M17.5 12.7v4.8h-4.8"/><path d="M9.4 13.2v6.2M6.6 16.6h5.6"/>',
    [
        f('v', 'Feminine ↔ masculine', 50.0, 0.0, 100.0, 1.0),
        b('face_too', 'Include the face', True),
        b('voice_hint', 'Write the hint for the voice pick', False),
    ],
)

_side(
    'sh_symmetry',
    'Symmetry',
    'Shape',
    'Enforce, relax or measure left-right symmetry. Perfect symmetry reads '
    'as synthetic, so the useful setting is rarely 100: this reports the '
    'current asymmetry and lets you move towards or away from it.',
    '<path d="M12 3.6v16.8"/><path d="M4.6 12h4.2M15.2 12h4.2"/>'
    '<path d="M8.6 7.4L5.2 12l3.4 4.6"/><path d="M15.4 7.4l3.4 4.6-3.4 4.6"/>',
    [
        f('amount', 'Symmetry', 92.0, 0.0, 100.0, 1.0),
        e('direction', 'Source side', '+X', ('+X', '-X', 'average')),
        b('measure_only', 'Measure, do not change', False),
        b('include_rig', 'Symmetrise the rig too', True),
    ],
)

_side(
    'sh_morph_load',
    'Morph target load',
    'Shape',
    'Load a saved set of morph values — a face, a build, a whole character '
    'body — onto the open mesh. Sets are portable across bodies that share '
    'the same base, which is what makes a family of characters possible '
    'without modelling each one.',
    '<path d="M12 4.4v9.2"/><path d="M8.4 10.4l3.6 3.6 3.6-3.6"/>'
    '<path d="M4.8 16.2v2.6a1.4 1.4 0 001.4 1.4h11.6a1.4 1.4 0 001.4-1.4v-2.6"/>',
    [
        s('set_id', 'Morph set', '', 'Saved set id or path'),
        f('blend', 'Blend in at', 100.0, 0.0, 100.0, 1.0),
        b('face_only', 'Face channels only', False),
        b('body_only', 'Body channels only', False),
    ],
)

_side(
    'sh_morph_save',
    'Morph target save',
    'Shape',
    'Save the current morph values as a named set, with a thumbnail and the '
    'base it was authored against. Saves the numbers, not the geometry, so a '
    'set stays a few kilobytes and still reproduces the body exactly.',
    '<path d="M12 13.6V4.4"/><path d="M8.4 7.6L12 4l3.6 3.6"/>'
    '<path d="M4.8 16.2v2.6a1.4 1.4 0 001.4 1.4h11.6a1.4 1.4 0 001.4-1.4v-2.6"/>',
    [
        s('name', 'Name', ''),
        b('thumb', 'Render a thumbnail', True),
        b('overwrite', 'Overwrite if it exists', False),
        s('tags', 'Tags', '', 'Comma separated'),
    ],
)

_side(
    'sh_preset',
    'Proportion preset',
    'Shape',
    'Jump the whole section to a coherent set of proportions — realistic '
    'adult, heroic, stylised, chibi, or one of the animation house ratios. A '
    'starting point that is internally consistent, not a lock: every slider '
    'above stays editable afterwards.',
    '<path d="M5.2 19.4V9.8l3.6-2.6 3.6 2.6v9.6"/>'
    '<path d="M12.4 19.4V6.4l3.4-2.4 3 2.4v13"/><path d="M3.4 19.4h17.2"/>',
    [
        e(
            'preset',
            'Preset',
            'realistic adult',
            (
                'realistic adult',
                'realistic child',
                'heroic',
                'stylised 6-head',
                'chibi 3-head',
                'fashion 8-head',
                'toon',
            ),
        ),
        f('strength', 'Apply at', 100.0, 0.0, 100.0, 1.0),
        b('keep_identity', 'Keep the face identity', True),
    ],
)


# ══ RIG ═════════════════════════════════════════════════════════════════════
# The skeleton. Mesh Studio rigs a mesh and tests ONE pose; the moment there is
# a second pose in time it is Movement Studio's file (see MISSING in
# mesh_studio.py). Ops that read or edit bones carry needs='rig' so the page
# greys them on an unrigged mesh instead of failing on click.

_side(
    'rig_unirig',
    'Auto-rig (UniRig)',
    'Rig',
    'Predict a skeleton and skin weights for an arbitrary mesh with UniRig — '
    'one network for humanoids, quadrupeds, birds and things with no name. '
    'The general-purpose answer when the mesh is not a human base and there '
    'is no template to fit.',
    '<path d="M12 3.6v5.2M12 8.8l-4.6 3.4M12 8.8l4.6 3.4"/>'
    '<path d="M7.4 12.2v5M16.6 12.2v5"/><circle cx="12" cy="3.6" r="1.5"/>'
    '<circle cx="7.4" cy="17.2" r="1.5"/><circle cx="16.6" cy="17.2" r="1.5"/>',
    [
        e('kind', 'Body plan', 'auto', ('auto', 'humanoid', 'quadruped', 'bird', 'insect', 'other')),
        i('max_bones', 'Max bones', 64, 8, 256, 1),
        b('weights', 'Also predict skin weights', True),
        b('symmetrise', 'Symmetrise the result', True),
    ],
    needs='gpu',
)

_side(
    'rig_mpfb',
    'MPFB rig',
    'Rig',
    'Attach the MPFB skeleton to an MPFB-derived body — the exact rig the '
    'base was authored for, with its helper groups and its weights already '
    'correct. Always better than predicting a rig when the body came from '
    'the human base library, because it is not a prediction.',
    '<circle cx="12" cy="4.8" r="2"/><path d="M12 6.8v6.4"/>'
    '<path d="M7.6 9.4h8.8"/><path d="M12 13.2l-2.8 6.2M12 13.2l2.8 6.2"/>'
    '<path d="M7.6 9.4l-1.4 4.2M16.4 9.4l1.4 4.2"/>',
    [
        e('variant', 'Rig variant', 'default', ('default', 'game engine', 'cmu compatible', 'face bones')),
        b('helpers', 'Use the MPFB helper groups', True),
        b('finger_bones', 'Include finger bones', True),
    ],
)

_side(
    'rig_auto_weights',
    'Blender auto weights',
    'Rig',
    'Bind the mesh to an existing skeleton with heat-map bone envelopes — '
    "Blender's automatic weights. Fast and adequate on a clean, watertight, "
    'single-shell mesh; it is the interior geometry and the self-intersections '
    'that make it produce a shoulder that tears.',
    '<path d="M12 4.4v6.2"/><path d="M12 10.6l-3.8 3.2v5.8"/>'
    '<path d="M12 10.6l3.8 3.2v5.8"/>'
    '<path d="M5.6 12.6a12 12 0 0112.8 0"/>',
    [
        e('method', 'Method', 'heat', ('heat', 'envelope', 'geodesic voxel')),
        f('falloff', 'Falloff', 1.0, 0.1, 4.0, 0.05),
        b('clear_first', 'Clear existing weights', True),
        b('mark_failures', 'List the vertices that got no weight', True),
    ],
    needs='rig',
)

_side(
    'rig_humanoid',
    'Humanoid template',
    'Rig',
    'Fit a standard humanoid skeleton — the Mixamo-style bone names and '
    'hierarchy every engine and every motion library expects — by placing a '
    'dozen landmarks and letting the rest solve. Names matter more than '
    'placement here: a retarget matches on them.',
    '<circle cx="12" cy="4.4" r="1.8"/><path d="M12 6.2v7"/>'
    '<path d="M6.8 8.6l5.2 1.2 5.2-1.2"/>'
    '<path d="M12 13.2l-3 2.8-.6 3.6M12 13.2l3 2.8.6 3.6"/>'
    '<path d="M6.8 8.6l-1 4M17.2 8.6l1 4"/>',
    [
        e('naming', 'Bone naming', 'mixamo', ('mixamo', 'unreal', 'unity', 'blender rigify')),
        b('fingers', 'Finger chains', True),
        b('toes', 'Toe bones', False),
        b('twist', 'Twist bones in forearm and thigh', True),
    ],
)

_side(
    'rig_quadruped',
    'Quadruped rig',
    'Rig',
    'Fit a four-legged skeleton — spine, two shoulder girdles, digitigrade '
    'or plantigrade hind legs, tail chain. The leg plan is the decision that '
    'matters: a dog and a bear stand on different parts of the same bones.',
    '<path d="M4.8 9.6h14.4"/><circle cx="20.2" cy="8.4" r="1.6"/>'
    '<path d="M6.6 9.6v5.4l-.8 4M9.8 9.6v5.4l.8 4"/>'
    '<path d="M15 9.6v5.4l-.8 4M18 9.6v5.4l.8 4"/>'
    '<path d="M4.8 9.6L2.4 6.2"/>',
    [
        e('stance', 'Stance', 'digitigrade', ('plantigrade', 'digitigrade', 'unguligrade')),
        i('spine_bones', 'Spine bones', 5, 3, 12, 1),
        i('tail_bones', 'Tail bones', 6, 0, 24, 1),
        b('ears', 'Ear bones', False),
    ],
)

_side(
    'rig_bone_list',
    'Bone list',
    'Rig',
    'The skeleton as a tree: every bone, its parent, its length, how many '
    'vertices it actually moves and whether anything is weighted to it at '
    'all. The first place to look when a rig behaves oddly — a bone with '
    'zero influence is usually the answer.',
    '<path d="M5 6.2h3.4M5 12h3.4M5 17.8h3.4"/>'
    '<path d="M11.6 6.2h7.4M11.6 12h7.4M11.6 17.8h7.4"/>'
    '<circle cx="10" cy="6.2" r="1.2"/><circle cx="10" cy="12" r="1.2"/>'
    '<circle cx="10" cy="17.8" r="1.2"/>',
    [
        b('show_empty', 'Show bones with no weights', True),
        b('show_lengths', 'Show bone lengths', True),
        e('sort', 'Order', 'hierarchy', ('hierarchy', 'name', 'influence')),
    ],
    cls='pix',
    needs='rig',
)

_side(
    'rig_bone_add',
    'Add bone',
    'Rig',
    'Add a bone under a chosen parent, positioned from the viewport or from '
    'typed head and tail coordinates. For the props a character holds, a jaw '
    'that the base rig omitted, or a helper the retarget needs.',
    '<path d="M8.4 15.6l4.6-4.6"/><circle cx="7" cy="17" r="2"/>'
    '<circle cx="14.4" cy="9.6" r="2"/>'
    '<path d="M18.6 4.4v5.2M16 7h5.2"/>',
    [
        s('name', 'Bone name', ''),
        s('parent', 'Parent bone', ''),
        f('length_mm', 'Length (mm)', 100.0, 1.0, 2000.0, 1.0),
        b('connected', 'Connect to the parent tail', True),
    ],
    needs='rig',
)

_side(
    'rig_bone_remove',
    'Remove bone',
    'Rig',
    'Delete a bone and decide where its influence goes — to its parent, to '
    'its children, or nowhere. Deleting without reassigning is how a mesh '
    'ends up with unweighted vertices that collapse to the origin on the '
    'first pose.',
    '<path d="M8.4 15.6l4.6-4.6"/><circle cx="7" cy="17" r="2"/>'
    '<circle cx="14.4" cy="9.6" r="2"/><path d="M16 7h5.2"/>',
    [
        s('name', 'Bone name', ''),
        e('reassign', 'Send its weights to', 'parent', ('parent', 'children', 'nearest', 'nowhere')),
        b('children_too', 'Delete its children as well', False),
    ],
    needs='rig',
)

_side(
    'rig_pose_test',
    'Pose test',
    'Rig',
    'Drive the rig through a fixed set of stress poses — T, A, arms crossed, '
    'deep squat, shoulder raise, fist — and show where the surface tears, '
    'creases or self-intersects. One pose at a time, no timeline: this is a '
    'test of the bind, not an animation.',
    '<circle cx="12" cy="4.6" r="2"/><path d="M12 6.6v6"/>'
    '<path d="M4.8 8.2l7.2 2 7.2-2"/><path d="M12 12.6l-3.4 6.8"/>'
    '<path d="M12 12.6l3.4 6.8"/><path d="M17.6 3.4l2.2 2.2-2.2 2.2"/>',
    [
        e('pose', 'Pose', 'A-pose', ('T-pose', 'A-pose', 'arms crossed', 'deep squat', 'shoulder raise', 'fist')),
        f('amount', 'Amount', 100.0, 0.0, 100.0, 1.0),
        b('highlight', 'Highlight tearing and self-intersection', True),
        b('both_sides', 'Test both sides', True),
    ],
    cls='pix',
    needs='rig',
)

_side(
    'rig_retarget_bvh',
    'Retarget CMU BVH',
    'Rig',
    'Map the CMU motion-capture skeleton onto this rig — the bone '
    'correspondence, the rest-pose offsets and the scale — and verify it on '
    'a single frame. The mapping is saved with the mesh; Movement Studio is '
    'what plays the clip afterwards.',
    '<path d="M5.6 5.6v12.8"/><circle cx="5.6" cy="4" r="1.5"/>'
    '<path d="M18.4 5.6v12.8"/><circle cx="18.4" cy="4" r="1.5"/>'
    '<path d="M8.4 9.4h7.2M15.6 9.4l-2-2M15.6 9.4l-2 2"/>'
    '<path d="M15.6 14.6H8.4M8.4 14.6l2-2M8.4 14.6l2 2"/>',
    [
        s('clip', 'BVH clip', '', 'CMU subject/trial or a path'),
        e('mapping', 'Mapping', 'auto', ('auto', 'mixamo names', 'manual')),
        i('frame', 'Verify on frame', 1, 1, 100000, 1),
        b('scale_to_rig', 'Scale the clip to this rig', True),
        b('save_mapping', 'Save the mapping with the mesh', True),
    ],
    needs='rig',
)

_side(
    'rig_root_motion',
    'Root motion',
    'Rig',
    'Declare how the character travels: a root bone that carries the '
    'translation, or motion baked into the hips. Engines need the first, '
    'most captured data ships as the second, and getting it wrong is the '
    'character that moonwalks.',
    '<path d="M12 6.2v8.2"/><circle cx="12" cy="4.4" r="1.6"/>'
    '<path d="M8.6 14.4h6.8"/>'
    '<path d="M4.6 19.4h14.8M19.4 19.4l-2.4-2M19.4 19.4l-2.4 2"/>',
    [
        e('mode', 'Mode', 'root bone', ('root bone', 'in hips', 'none')),
        b('lock_xy', 'Lock horizontal drift', False),
        b('lock_z', 'Lock vertical drift', True),
        s('root_name', 'Root bone name', 'root'),
    ],
    needs='rig',
)

_side(
    'rig_rest_pose',
    'Rest pose',
    'Rig',
    'Read, set or re-bake the rest pose — the pose the weights were computed '
    'against. Re-baking a posed mesh as the new rest is legitimate and '
    'occasionally necessary; doing it by accident is why a rig returns to a '
    'crouch when it is reset.',
    '<circle cx="12" cy="4.8" r="1.9"/><path d="M12 6.7v6.1"/>'
    '<path d="M5.4 9h13.2"/><path d="M12 12.8l-2.4 6.6M12 12.8l2.4 6.6"/>'
    '<path d="M3.4 21h17.2"/>',
    [
        e('action', 'Action', 'show', ('show', 'set to T-pose', 'set to A-pose', 'bake current pose as rest')),
        b('keep_weights', 'Recompute weights against the new rest', True),
    ],
    needs='rig',
)
