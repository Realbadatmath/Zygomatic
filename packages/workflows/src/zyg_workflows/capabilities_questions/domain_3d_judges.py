# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DOMAIN sheets for 3d/scene/architecture and judges & gates, plus the EXTRA additions."""

from __future__ import annotations

from zyg_workflows.capabilities_questions.core import DOMAIN, q


# ═══════════════════════════════════════════════════════ 3d, scene & architecture
DOMAIN['mesh_gen'] = [
    q('usable', 'Mesh is usable without repair', '', '', True, 'The mesh'),
    q('topology', 'Topology is clean', '', '', True, 'The mesh'),
    q('quads', 'Quad-dominant where it matters', '', '', True, 'The mesh'),
    q('poly_budget', 'Polygon count is controllable', '', 'count', True, 'The mesh'),
    q('scale', 'Real-world scale is right', '', '', True, 'The mesh'),
    q('uv', 'UVs are usable', '', '', True, 'The mesh'),
    q('texture_out', 'Textures come with it', '', '', True, 'The mesh'),
    q('pbr', 'PBR materials', '', '', True, 'The mesh'),
    q('watertight', 'Watertight when it should be', '', '', True, 'The mesh'),
    q('from_image', 'From a single image', '', '', True, 'What it takes'),
    q('from_multi', 'From several views', '', '', True, 'What it takes'),
    q('from_text', 'From text alone', '', '', True, 'What it takes'),
    q('backside', 'Invents a plausible back', '', '', True, 'What it takes'),
    q('human', 'Human bodies', '', '', True, 'Subjects'),
    q('creature_mesh', 'Non-human creatures', '', '', True, 'Subjects'),
    q('props_mesh', 'Props and hard surfaces', '', '', True, 'Subjects'),
    q('cloth_mesh', 'Cloth and soft goods', '', '', True, 'Subjects'),
    q('hair_mesh', 'Hair', '', '', True, 'Subjects'),
    q('riggable', 'The result can be rigged', '', '', True, 'Subjects'),
]

DOMAIN['mesh_qc'] = [
    q('anatomy', 'Anatomy is checked', '', '', True, 'Checks'),
    q('proportions', 'Proportions are checked', '', '', True, 'Checks'),
    q('phalanx', 'Finger bone counts are checked', '', '', True, 'Checks'),
    q('manifold', 'Mesh is manifold', '', '', True, 'Checks'),
    q('selfint', 'No self-intersection', '', '', True, 'Checks'),
    q('normals', 'Normals point outward', '', '', True, 'Checks'),
    q('degenerate', 'No degenerate faces', '', '', True, 'Checks'),
    q('uv_overlap', 'No UV overlap', '', '', True, 'Checks'),
    q('scale_check', 'Scale is checked', '', '', True, 'Checks'),
    q('export', 'Exports with correct orientation', 'the GLB up-axis is a real defect class', '', True, 'Export'),
    q('units', 'Units survive export', '', '', True, 'Export'),
    q('material_export', 'Materials survive export', '', '', True, 'Export'),
    q('automated', 'Runs automatically on every mesh', '', '', True, 'Export'),
    q('blocks', 'Can block a bad mesh from shipping', '', '', True, 'Export'),
    q('explains_mesh', 'Names what is wrong', '', '', True, 'Export'),
]

DOMAIN['grooms'] = [
    q('realism', 'Reads as photoreal', '', '', True, 'Look'),
    q('hair_strand', 'Strand hair', '', '', True, 'Look'),
    q('hair_style', 'A named hairstyle is reachable', '', '', True, 'Look'),
    q('hair_colour', 'Hair colour is directable', '', '', True, 'Look'),
    q('facial_hair', 'Beards and brows', '', '', True, 'Look'),
    q('eyes_real', 'Eyes read as real', '', '', True, 'Look'),
    q('iris', 'Iris colour and detail', '', '', True, 'Look'),
    q('sclera', 'Sclera is not flat white', '', '', True, 'Look'),
    q('skin_sss', 'Skin has subsurface', '', '', True, 'Look'),
    q('skin_pores', 'Pores and micro-detail', '', '', True, 'Look'),
    q('freckles', 'Freckles without mottling', '', '', True, 'Look'),
    q('waxy', 'Not waxy', 'the recorded failure mode', '', True, 'Look'),
    q('heritage', 'Skin tone decoupled from heritage', '', '', True, 'Look'),
    q('order', 'Pipeline order is known', 'previews must run last', '', True, 'Practicalities'),
    q('render_time', 'Minutes per render', '', 'min', False, 'Practicalities'),
    q('variation', 'Different characters look different', '', '', True, 'Practicalities'),
    q('hair_motion', 'Hair moves with the head', '', '', True, 'Practicalities'),
]

DOMAIN['arch'] = [
    q('unattended', 'Finishes a build unattended', '', 'ratio', True, 'The build'),
    q('correct', 'The building is architecturally right', '', '', True, 'The build'),
    q('one_call', 'Planning happens in one call', '', '', True, 'The build'),
    q('model_rule', 'Model choice is fixed and followed', '', '', True, 'The build'),
    q('brief_follow', 'Follows the brief', '', '', True, 'The build'),
    q('scale_arch', 'Scale and dimensions are right', '', '', True, 'Correctness'),
    q('structure_arch', 'Structure stands up', '', '', True, 'Correctness'),
    q('openings', 'Doors and windows make sense', '', '', True, 'Correctness'),
    q('circulation', 'You can walk through it', '', '', True, 'Correctness'),
    q('roof', 'Roof geometry is right', '', '', True, 'Correctness'),
    q('ground_seam', 'Building meets the ground cleanly', '', '', True, 'Correctness'),
    q('period_arch', 'Period-correct', '', '', True, 'Correctness'),
    q('materials_arch', 'Materials are right', '', '', True, 'Correctness'),
    q('landscape', 'Landscape and surroundings', '', '', True, 'Scope'),
    q('interior', 'Interiors', '', '', True, 'Scope'),
    q('floorplan', 'Floor plans', '', '', True, 'Scope'),
    q('drawings', 'Produces drawings', '', '', True, 'Scope'),
    q('exports_arch', 'Exports IFC / DXF / STL / GLB', '', 'text', True, 'Scope'),
    q('reference_model', 'Can work from a reference model', '', '', True, 'Scope'),
    q('gates_arch', 'Quality gates catch its mistakes', '', '', True, 'Scope'),
    q('tokens', 'Tokens per build', '', 'tokens', False, 'Scope'),
]

DOMAIN['render3d'] = [
    q('realism', 'Reads as finished', '', '', True, 'The picture'),
    q('materials_render', 'Materials read correctly', '', '', True, 'The picture'),
    q('lighting_render', 'Lighting is controllable', '', '', True, 'The picture'),
    q('shadows', 'Shadows are correct', '', '', True, 'The picture'),
    q('glass', 'Glass and transparency', '', '', True, 'The picture'),
    q('dof', 'Depth of field', '', '', True, 'The picture'),
    q('noise_render', 'Converges without noise', '', '', True, 'The picture'),
    q('consistency', 'Same look across a sheet', '', '', True, 'Production'),
    q('camera_render', 'Camera is scriptable', '', '', True, 'Production'),
    q('turntable', 'Turntables and angle sheets', '', '', True, 'Production'),
    q('passes', 'Renders separate passes', '', '', True, 'Production'),
    q('alpha_out', 'Alpha survives export', '', '', True, 'Production'),
    q('automation', 'Runs without a human in Blender', '', '', True, 'Production'),
    q('headless', 'Runs headless', '', '', True, 'Production'),
    q('min_frame', 'Minutes per frame', '', 'min', False, 'Production'),
]

# ═══════════════════════════════════════════════════════════════ judges & gates
DOMAIN['pixel_gates'] = [
    q('identity', 'Catches identity drift', '', '', True, 'What it catches'),
    q('photo', 'Catches a photographic patch', '', 'number', True, 'What it catches'),
    q('seams', 'Catches a fill seam', '', '', True, 'What it catches'),
    q('grain', 'Catches a grain-scale error', '', '', True, 'What it catches'),
    q('colour_gate', 'Catches a wrong colour', '', '', True, 'What it catches'),
    q('texture_gate', 'Catches a texture mismatch', '', '', True, 'What it catches'),
    q('luma', 'Catches a luminance mismatch', '', '', True, 'What it catches'),
    q('blank', 'Catches a blank or corrupt frame', '', '', True, 'What it catches'),
    q('threshold_set', 'Its threshold was set on our material', '', '', True, 'How it behaves'),
    q('floor_stated', 'States its floor in the output', '', '', True, 'How it behaves'),
    q(
        'region',
        'Looks where the fault actually is',
        'a gate can be right and look elsewhere',
        '',
        True,
        'How it behaves',
    ),
    q('false_alarm', 'Leaves a good take alone', '', '', True, 'How it behaves'),
    q('explains', 'Explains itself to a human', '', '', True, 'How it behaves'),
    q('gameable', 'Cannot be gamed by texture', 'NCC was, and shipped an inflated prop', '', True, 'How it behaves'),
    q('blocks_ship', 'Can block a ship', '', '', True, 'How it behaves'),
    q('video_frames_gate', 'Runs on video frames', '', '', True, 'How it behaves'),
]

DOMAIN['detectors'] = [
    q('finds', 'Finds the region', '', 'ratio', True, 'Detection'),
    q('judges', 'Judges what it found', '', '', True, 'Detection'),
    q('box_tight', 'Boxes are tight', '', '', True, 'Detection'),
    q('mask_quality', 'Masks are clean', '', '', True, 'Detection'),
    q('small_object', 'Finds small objects', '', '', True, 'Detection'),
    q('occluded_find', 'Finds occluded objects', '', '', True, 'Detection'),
    q('open_vocab', 'Open vocabulary', 'finds a thing it was not trained on', '', True, 'Detection'),
    q('painted_find', 'Works on painted, not photographic, frames', '', '', True, 'Detection'),
    q('track_frames', 'Tracks across frames', '', '', True, 'Detection'),
    q('false_pos', 'Few false positives', '', '', True, 'Detection'),
    q('conf_useful', 'Confidence means something', '', '', True, 'Detection'),
    q('hands_det', 'Hands', '', '', True, 'Targets'),
    q('faces_det', 'Faces', '', '', True, 'Targets'),
    q('people_det', 'People', '', '', True, 'Targets'),
    q('props_det', 'Named props', '', '', True, 'Targets'),
    q('text_det', 'Text in frame', '', '', True, 'Targets'),
    q('creature_det', 'Non-human subjects', '', '', True, 'Targets'),
]

DOMAIN['identity_gates'] = [
    q('identity', 'Same person', '', 'number', True, 'Person'),
    q('content', 'The tile is sane', 'a high score can sit on corrupt content', '', True, 'Person'),
    q('angle_aware', 'Thresholds vary by angle', 'frontal strict, profile lenient, back exempt', '', True, 'Person'),
    q('multi_face', 'Rejects more than one face', '', '', True, 'Person'),
    q('face_cut', 'Rejects a face on the tile edge', '', '', True, 'Person'),
    q('mislabel', 'Rejects a mislabelled angle', '', '', True, 'Person'),
    q('child_gate', 'Works on a child face', '', '', True, 'Person'),
    q('styled', 'Works on a restyled face', '', '', True, 'Person'),
    q('props', 'Props stay the same size and shape', '', '', True, 'World'),
    q('action', 'The right actor owns the action', 'a comparative gate passed when anybody smoked', '', True, 'World'),
    q('sets', 'The set is not re-derived between windows', '', '', True, 'World'),
    q('costume_gate', 'Costume stays the same', '', '', True, 'World'),
    q('lighting_gate', 'Lighting stays consistent', '', '', True, 'World'),
    q('window_seam_gate', 'Checks the context-window seams', '', '', True, 'World'),
    q('gameable_gate', 'Cannot be gamed by texture', '', '', True, 'World'),
    q('blocks_ship', 'Can block a ship', '', '', True, 'World'),
]

DOMAIN['text_judges'] = [
    q('decompose', 'Decomposed into per-slot questions', '', '', True, 'Method'),
    q('global', 'Works as one global question', '', 'ratio', True, 'Method'),
    q('word_lock', 'A word-level lock is enough', '', 'count', True, 'Method'),
    q('crop_based', 'Asks about a crop, not the frame', '', '', True, 'Method'),
    q('prompt_derived', 'Questions derive from the prompt', '', '', True, 'Method'),
    q('recall', 'Catches the anachronisms present', '', 'ratio', True, 'Anachronism'),
    q('false', 'Leaves correct frames alone', '', '', True, 'Anachronism'),
    q('vehicles', 'Catches modern vehicles', '', '', True, 'Anachronism'),
    q('wires', 'Catches wires, poles and cables', '', '', True, 'Anachronism'),
    q('clothing_era', 'Catches modern clothing', '', '', True, 'Anachronism'),
    q('hair_era', 'Catches a modern haircut', '', '', True, 'Anachronism'),
    q('objects_era', 'Catches modern small objects', '', '', True, 'Anachronism'),
    q('reads_text', 'Reads lettering in frame', '', '', True, 'Lettering'),
    q('spelling', 'Catches misspelling', '', '', True, 'Lettering'),
    q('script_era', 'Catches a wrong script or typeface', '', '', True, 'Lettering'),
    q('language_frame', 'Catches the wrong language', '', '', True, 'Lettering'),
    q('numerals_frame', 'Catches wrong numerals', '', '', True, 'Lettering'),
]

DOMAIN['audio_judges'] = [
    q('delivery', 'Catches a delivery fault', '', '', True, 'What it catches'),
    q('wrong_voice', 'Catches the wrong voice', '', '', True, 'What it catches'),
    q('semantic', 'Catches the wrong CONTENT', '', '', True, 'What it catches'),
    q('age_wrong', 'Catches a wrong age', '', '', True, 'What it catches'),
    q('sex_wrong', 'Catches a wrong sex', '', '', True, 'What it catches'),
    q('clipping_j', 'Catches clipping', '', '', True, 'What it catches'),
    q('silence_j', 'Catches dead air', '', '', True, 'What it catches'),
    q('truncation', 'Catches a truncated line', '', '', True, 'What it catches'),
    q('artefact_j', 'Catches synthesis artefacts', '', '', True, 'What it catches'),
    q('mispronounce', 'Catches a mispronounced name', '', '', True, 'What it catches'),
    q('drift_j', 'Catches timbre drift mid-render', '', '', True, 'What it catches'),
    q('music_key', 'Catches a wrong key or tempo', '', '', True, 'What it catches'),
    q('lyrics_j', 'Catches a wrong lyric', '', '', True, 'What it catches'),
    q('calibrated', 'Calibrated on our own material', '', '', True, 'How it behaves'),
    q('refuses', 'Refuses when it cannot measure', '', '', True, 'How it behaves'),
    q('false_alarm_a', 'Leaves a good take alone', '', '', True, 'How it behaves'),
    q('blocks_ship', 'Can block a ship', '', '', True, 'How it behaves'),
]

# Questions appended AFTER a step's already-recorded columns, for steps whose sheet was
# generated from a bench (vlm_judges) — the generated columns keep their place and their
# measured answers, and these say what that bench did NOT ask.
EXTRA = {}

EXTRA['vlm_judges'] = [
    q('fused_finger', 'Fused fingers', '', '', True, 'Defect classes not benched'),
    q('limb_count', 'Wrong number of limbs', '', '', True, 'Defect classes not benched'),
    q('face_melt', 'A melted or ghost face', '', '', True, 'Defect classes not benched'),
    q('eye_mismatch', 'Mismatched eyes', '', '', True, 'Defect classes not benched'),
    q('teeth_judge', 'Bad teeth', '', '', True, 'Defect classes not benched'),
    q('anachronism_judge', 'An anachronistic object', '', '', True, 'Defect classes not benched'),
    q('text_judge', 'Misspelled lettering in frame', '', '', True, 'Defect classes not benched'),
    q('seam_judge', 'A composite or fill seam', '', '', True, 'Defect classes not benched'),
    q('perspective_judge', 'Broken perspective', '', '', True, 'Defect classes not benched'),
    q('light_judge', 'Inconsistent lighting', '', '', True, 'Defect classes not benched'),
    q('scale_judge', 'An object at the wrong scale', '', '', True, 'Defect classes not benched'),
    q('dupe_person', 'A duplicated person', '', '', True, 'Defect classes not benched'),
    q('crowd_judge', 'Broken background people', '', '', True, 'Defect classes not benched'),
    q('costume_judge', 'A wrong costume detail', '', '', True, 'Defect classes not benched'),
    q('video_frames', 'Works on video frames', 'every number here is from stills', '', True, 'Untested conditions'),
    q('temporal_judge', 'Sees a fault that only exists over time', '', '', True, 'Untested conditions'),
    q('photoreal_src', 'Works on photographic material', '', '', True, 'Untested conditions'),
    q('other_style', 'Works outside this art style', '', '', True, 'Untested conditions'),
    q(
        'two_phrasing',
        'Scored on two phrasings, OR-ed',
        'how the pipeline would really use it',
        '',
        True,
        'Untested conditions',
    ),
    q(
        'explains_judge',
        'Its explanation is worth reading',
        'the bench scores yes/no only',
        '',
        True,
        'Untested conditions',
    ),
    q('localise', 'Points at WHERE the fault is', '', '', True, 'Untested conditions'),
    q('severity', 'Rates how bad it is', '', '', True, 'Untested conditions'),
    q(
        'frontier',
        'Benched against a paid judge',
        'only local models were in this run',
        '',
        True,
        'Untested conditions',
    ),
    q('reject_only', 'Used reject-only, never to grant a pass', '', '', True, 'Untested conditions'),
]
