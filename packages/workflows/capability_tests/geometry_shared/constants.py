# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.constants — the geometry check vocabulary, the one fixed build condition, and the extras helpers.

Verbatim from the former geometry_shared.py, lines 70-197.
"""

from __future__ import annotations

# ── check kinds this bank adds ────────────────────────────────────────────────────────────
# Every kind is decided by a small function over the exported GLB, the turntable sheet, or a
# detector. Added here so the validator unions them and the runner author sees the list.
#
# Every check also carries `when`, which says WHAT the function is handed, so a render-only row
# skips a check it cannot answer rather than failing it:
#   when='glb'     the exported GLB     (a render3d row that ships no GLB skips these)
#   when='sheet'   the 4-view turntable sheet
#   when='prompt'  the prompt text as sent
#   when='report'  the tool's own stdout / error / exit code
# A skipped check is recorded as skipped in the trial, never counted as a pass.
CHECK_KINDS = {
    # ── the mesh itself (trimesh over the exported GLB) ──
    'mesh_manifold': 'every shell is watertight and edge-manifold (trimesh is_watertight and is_winding_consistent)',
    'mesh_no_self_intersection': 'no triangle pair intersects (trimesh broadphase then exact test); share of intersecting tris <= `max` (default 0.0)',
    'mesh_shell_count': 'count of connected components between `min` and `max` (split on unreferenced vertices)',
    'mesh_tris_max': 'total triangle count <= `max`',
    'mesh_tris_min': 'total triangle count >= `min` (a plane pretending to be a subject fails)',
    'mesh_degenerate_max': 'share of zero-area / duplicate-vertex triangles <= `max`',
    'glb_up_axis': 'the tallest bbox axis is +Y and the subject is upright (project_body_plates_gltf_upaxis)',
    'glb_hash_identical': 'sha256 of the exported GLB is identical across the repeats named in `across`',
    # ── dimensions and placement (all in metres, +Y up) ──
    'bbox_dims_m': 'bbox extent on `axis` (y|x|z|max) between `min` and `max` metres',
    'bbox_aspect': 'bbox `axis` divided by bbox `over` between `min` and `max`',
    'bbox_relation': 'shell `a` stands in `relation` (left_of|right_of|in_front_of|behind|above|below|inside|touching|apart) to shell `b`, from their bounding boxes, with `tolerance` metres slack',
    'bbox_facing': "the subject's front (its -Z face by the export contract) points within `tolerance` degrees of `heading`",
    'shell_volume_ratio': 'volume of shell `a` divided by shell `b` between `min` and `max`',
    # ── surface and materials ──
    'has_uv': 'every shell carries a UV layer with no more than `overlap` share of overlapping faces (default 0.2)',
    'material_count_min': 'the GLB declares at least `min` distinct materials',
    'material_names_present': 'every term in `terms` occurs in some material name (case-insensitive, substring)',
    'material_basecolour': 'the material on shell `shell` has a base colour within `tolerance` CIEDE2000 of `colour` (a named CSS colour or hex)',
    'pbr_maps_present': 'every map in `maps` (basecolour|normal|roughness|metallic|ao) is present and non-constant',
    'pbr_value_range': 'the `field` (roughness|metallic) on shell `shell` is between `min` and `max`',
    'mesh_part_names': 'every term in `terms` names either a shell or a material (the part is addressable, not baked in)',
    # ── comparing two builds ──
    'mesh_similarity_min': 'chamfer distance from the build named in `to` <= `max_cd` metres AND shell count unchanged (the edit landed without redoing the model)',
    'mesh_similarity_max': 'chamfer distance from `to` >= `min_cd` metres (the two builds must actually differ)',
    'pairwise_mesh_distinct': 'every pair of repeats has chamfer distance >= `min_cd` metres',
    # ── detectors over the 4-view turntable sheet ──
    'person_count': 'a person detector finds exactly `n` people in `view` (default all four views agree)',
    'hand_landmarks': 'MediaPipe hand_landmarker finds `hands` hands and `fingers` extended fingers per hand in the named views',
    'face_identity_min': 'ArcFace cosine between the faces in `views` >= `min` (one person across views) or <= `max` when `distinct` is set (different people)',
    'sheet_ocr_equals': 'tesseract OCR of the sheet, normalised (case, spacing), equals `text`',
    'sheet_ocr_present': 'OCR of the sheet contains every term in `terms`',
    'sheet_ocr_absent': 'OCR of the sheet contains no term in `terms`',
    'clock_reads': 'OCR plus hand-angle measurement on the clock face reads `time` within `tolerance` minutes',
    'sheet_cells_clean': "in an N-view sheet, at least `share` of cells pass the sheet's own per-cell checks",
    # ── the row, not the build ──
    'library_has': 'the asset library answers the subject query with at least `min` items whose tags cover `terms` (a LIBRARY row builds nothing)',
    'build_error': 'the tool reported a refusal or an error naming `terms` (a loud failure, not a silent bad build)',
    'build_succeeds': 'the tool produced a parsable GLB at all (no exception, non-empty mesh)',
    'settings_recorded': 'the trial carries every field in `fields` verbatim (prompt, seed, steps, resolution, tool revision)',
}

# ── the one fixed build condition ─────────────────────────────────────────────────────────
# Identical for every subject and every row. The row's own production settings are recorded
# into the trial rather than overridden, because a mesh generator's step count is part of what
# the sheet is measuring; what must NOT vary between two models is the prompt, the seeds, the
# export and the sheet.
COND_BUILD = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'export': 'GLB, real-world scale in metres, +Y up, subject upright, no scene root transform baked out',
    'sheet': '4-view turntable at 0/90/180/270 degrees, 1024x1024 per view, three-point rig, '
    'blender_scripts/render_asset_previews.py, identical lens and lighting for every row',
    'settings': "the row's shipped resolution / steps / sampler, unchanged, copied verbatim into the trial",
    'timeout_s': 900,
}

COND_NOTE = (
    'Seeds [11, 12, 13] and three repeats on every build; the FIRST repeat (seed 11) is what '
    'first_take reads. Prompts are verbatim and under 40 words — an image-conditioned row is '
    'given the fixture PNG instead, never a paraphrase of the prompt. A build that times out at '
    '900 s is a no on its columns; a tool that will not start is untested with the error.'
)

FIXED_SETTINGS = {
    'seeds': [11, 12, 13],
    'export': COND_BUILD['export'],
    'sheet': COND_BUILD['sheet'],
    'prompt_budget': 'every build prompt is under 40 words. Image prompts elsewhere in the house '
    'must stay under 60 words because SDXL truncates at 77 CLIP tokens silently; '
    'geometry prompts are held tighter so the same text fits any text encoder.',
    'up_axis': 'project_body_plates_gltf_upaxis — +Y up, standing. A Z-up export is a fail, not a fixup.',
    'operator_sees': 'the 4-view turntable sheet only, anonymised and shuffled.',
}

OPERATOR_PROTOCOL = [
    'The operator sees only turntable sheets, saved as A.png, B.png, C.png ... in shuffled order '
    'with no model name, no seed, no prompt and no ladder step anywhere in the image or filename; '
    'the letter-to-row map is written to disk before the sheets are shown and revealed only after '
    'every answer is saved.',
    'One written yes/no question per subject, the wording fixed in this bank and never improvised. '
    'A maybe is a no. The operator may not go back and change an answer once the next sheet is open.',
    'The mechanical checks run first and are a VETO: a build that fails manifold, '
    'self-intersection, shell count, bbox or up-axis is already a no and its sheet is still shown '
    'blind, so the operator is never told which builds machines rejected.',
]

CONDITIONS_NOTE = COND_NOTE


# ── extras: the mechanical check beside the operator, where a detector exists ──────────────
def _people(n):
    return [{'check': 'person_count', 'n': n, 'when': 'sheet'}]


def _hands(hands, fingers):
    return [{'check': 'hand_landmarks', 'hands': hands, 'fingers': fingers, 'views': ['0', '90'], 'when': 'sheet'}]


def _ocr(text):
    return [{'check': 'sheet_ocr_equals', 'text': text, 'when': 'sheet'}]


def _ocr_has(*terms):
    return [{'check': 'sheet_ocr_present', 'terms': list(terms), 'when': 'sheet'}]


def _mat(*terms):
    return [{'check': 'material_names_present', 'terms': list(terms), 'when': 'glb'}]


def _maps(*maps):
    return [{'check': 'pbr_maps_present', 'maps': list(maps), 'when': 'glb'}]
