# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Mesh generation (mesh_gen). 2026-09-30.

Question the sheet asks: can we make usable geometry from an image or a prompt?

"Usable" is the whole question, and it is NOT a picture question. A mesh that looks right on
a turntable can still be unusable: the Abel finding was a body that passed every visual review
and was dead downstream because the limbs intersected the trunk. So the 19 domain columns are
decided by MECHANICAL tests over the exported GLB — watertight, edge-manifold, normals out,
no self-intersecting triangle pair, quad share, triangle count against the ask, bounding box
in metres, UVs without overlap, the PBR maps that are actually present — and the operator is
asked only where no detector exists (does the invented back read as a back, is this a usable
human / creature / prop / cloth / hair). The defect-judge bench of 2026-09-27 is why: the best
local VLM scored 34/40 on a global "is this right" question and 2/8 on fused fingers, extra
digits and a second feather, which are exactly the failures a mesh generator makes.

The shape of the test
---------------------
One fixed CONTRACT subject built on the bank's seeds [11, 12, 13] answers the nine mesh
columns at once, because they are all read off the same GLB and a second build would only add
variance. Three more small ladders answer the rest: a 20k / 80k / 320k polygon ask
(poly_budget), the three input modes (from_image / from_multi / from_text), and one subject per
material family (human, creature, props, cloth, hair). `riggable` is NOT re-measured here — the
rigging step's `rigs` probe binds these same GLBs, and this column derives from that trial, so
the two sheets cannot disagree about one mesh.

What is blocked and why
-----------------------
Every fixture is declared, none is created by this task. The single-image and multi-view
fixtures and the planted-scale reference do not exist yet; each carries the exact command that
makes it and `verified: False`, so the columns they feed are written `untested — fixture
unverified` until an operator has looked at them. An image-conditioned row is only as good as
the picture it was handed: a wrong or cropped fixture would be scored against the model.

Rows
----
direct3d_s2  the only row that generates from an input (project_direct3d_s2_install); its
             licence must be read at file level before any output of it ships.
mpfb         headless Blender over the MPFB CC0 human bases — parameters, not a prompt, so the
             input-mode columns are na and the prompt bands come off the bank's `blender`
             exemption.
prop_lib     a library row: it builds nothing, it answers a query with an asset that already
             exists on disk, so the polygon ask and the input modes are na and the body /
             creature / cloth / hair subjects are outside the library's scope.
smpl         retired. SMPL is non-commercial and is not used; the row is kept so the sheet
             keeps its receipt.
"""

from __future__ import annotations

# ── check kinds this module adds ─────────────────────────────────────────────────────────────
# The geometry bank's `mesh_manifold` deliberately answers watertight AND winding as one bool.
# geom/anthro/integrity.py exists because that conflation hides three unrelated failure modes
# (a boundary hole, an edge in three faces, a pinch vertex, an inward shell), and a mesh_gen
# sheet has separate columns for `watertight`, `topology` and the normals half of `usable`.
# These kinds split them the way integrity.py does, and add the three surface measurements the
# bank has no column for.
CHECK_KINDS = {
    'mesh_watertight': 'no boundary edge: every undirected edge of every shell is used by exactly two faces (the closure half of trimesh.is_watertight, reported alone)',
    'mesh_edge_manifold': 'no edge is used by more than two faces; the count of such edges is <= `max` (default 0)',
    'mesh_vertex_manifold': 'every vertex link-graph is a single cycle or path — a pinch vertex where two cones meet fails, though every edge is 2-manifold (geom/anthro/integrity.py _check_vertex_manifold)',
    'normals_outward': 'every closed shell has positive signed volume with consistent winding, so its normals point out of the solid; share of inward shells <= `max` (default 0.0)',
    'quad_share_min': 'faces that are quads, before any triangulation, divided by all faces >= `min` (read from the source cage, not the triangulated GLB)',
    'ngon_share_max': 'faces with more than four vertices divided by all faces <= `max`',
    'tris_within_ask': 'total triangle count is within `tolerance` (a fraction, default 0.2) of the `ask` the row was given',
    'texture_file_present': 'the GLB embeds or references at least one raster image whose shortest side is >= `min_px`, and the image is not a single flat colour',
    'uv_overlap_max': 'share of UV-space face area that overlaps another face <= `max` (measured by rasterising the UV layout, not by trusting the exporter)',
}

FX = 'capability_tests/fixtures/geometry/mesh_gen'
CONTRACT_GLB_NOTE = (
    'the single build every mesh column is read off, so nine columns cost three builds instead of twenty-seven'
)

# The one subject the mesh contract is measured on: a hard-surface prop with a handle, a head
# and a leather binding — three shells, a known real-world length, quads in the source cage if
# the row has one, and nothing a generator can hide behind (no hair, no cloth, no fur).
CONTRACT = {
    'subject': 'boarding axe',
    'prompt': 'A boarding axe: straight ash haft, iron head with a spike opposite the blade, '
    'leather grip binding at the base. Plain grey background, whole object, upright.',
    'length_m': (0.60, 0.95),
    'shells': (2, 4),
}

COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'export': 'GLB, real-world scale in metres, +Y up, subject upright (project_body_plates_gltf_upaxis)',
    'sheet': '4-view turntable at 0/90/180/270 degrees, 1024x1024 per view, '
    'blender_scripts/render_asset_previews.py, identical lens and lighting for every row',
    'settings': "the row's shipped resolution / steps / sampler, unchanged, copied verbatim into the trial",
    'timeout_s': 900,
    'note': "identical to the geometry bank's COND_BUILD so a domain trial and a Builds trial of "
    'the same row are comparable; the FIRST repeat (seed 11) is what first_take reads',
}

ALL_ROWS = ['direct3d_s2', 'mpfb', 'prop_lib', 'smpl']
GEN_ROWS = ['direct3d_s2']
BUILD_ROWS = ['direct3d_s2', 'mpfb']
MESH_ROWS = ['direct3d_s2', 'mpfb', 'prop_lib']


def _p(pid, title, feeds, inputs, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs),
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


_CONTRACT_IN = {
    'prompt': CONTRACT['prompt'],
    'fixture': FX + '/contract_axe.png',
    'note': 'a text-in row is given the prompt verbatim; an image-in row is given the '
    'fixture PNG and never a paraphrase of the prompt',
}

PROBES = [
    # ── the mesh contract: nine columns off one build ──
    _p(
        'contract_usable',
        'The contract build needs no repair',
        ['usable'],
        _CONTRACT_IN,
        [
            {'check': 'mesh_watertight', 'when': 'glb'},
            {'check': 'mesh_edge_manifold', 'max': 0, 'when': 'glb'},
            {'check': 'mesh_vertex_manifold', 'when': 'glb'},
            {'check': 'normals_outward', 'max': 0.0, 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            {'check': 'mesh_shell_count', 'min': CONTRACT['shells'][0], 'max': CONTRACT['shells'][1], 'when': 'glb'},
            {'check': 'build_succeeds', 'when': 'report'},
        ],
        MESH_ROWS,
        state_note='"usable without repair" is the CONJUNCTION: closed, edge- and vertex-manifold, '
        'normals out, no intersecting triangle pair, the shells the subject has. A mesh '
        'that needs one pass of a repair tool is a no here, not a partial — the column '
        'asks about the output, not about the output plus a fixup.',
    ),
    _p(
        'contract_topology',
        'Topology is clean',
        ['topology'],
        _CONTRACT_IN,
        [
            {'check': 'mesh_edge_manifold', 'max': 0, 'when': 'glb'},
            {'check': 'ngon_share_max', 'max': 0.02, 'when': 'glb'},
            {'check': 'mesh_degenerate_max', 'max': 0.0, 'when': 'glb'},
        ],
        MESH_ROWS,
        state_note='non-manifold edge count must be exactly 0 (not "few"); ngons at most 2 % of the '
        'source cage. A GLB is triangles, so the ngon share is read off the cage the row '
        'exported FROM where it has one, and is na where it has none.',
    ),
    _p(
        'contract_quads',
        'Quad-dominant where it matters',
        ['quads'],
        _CONTRACT_IN,
        [{'check': 'quad_share_min', 'min': 0.8, 'when': 'glb'}],
        MESH_ROWS,
        state_note='0.8 is the bar on a body or a deformable row, because a triangle soup cannot be '
        'subdivided or edge-loop-selected for rigging. A marching-cubes / SDF generator '
        'will read 0.0 here and that is the honest number, not a bug in the test.',
    ),
    _p(
        'contract_watertight',
        'Watertight when it should be',
        ['watertight'],
        _CONTRACT_IN,
        [
            {'check': 'mesh_watertight', 'when': 'glb'},
            {'check': 'mesh_shell_count', 'min': CONTRACT['shells'][0], 'max': CONTRACT['shells'][1], 'when': 'glb'},
        ],
        MESH_ROWS,
        state_note='closure only, reported apart from manifoldness: a boundary hole and an edge in '
        'three faces are different defects with different repairs, and trimesh answers '
        'both with one bool (geom/anthro/integrity.py exists because of that).',
    ),
    _p(
        'contract_scale',
        'Real-world scale is right',
        ['scale'],
        _CONTRACT_IN,
        [
            {
                'check': 'bbox_dims_m',
                'axis': 'max',
                'min': CONTRACT['length_m'][0],
                'max': CONTRACT['length_m'][1],
                'when': 'glb',
            },
            {'check': 'glb_up_axis', 'when': 'glb'},
        ],
        MESH_ROWS,
        state_note='a boarding axe is 0.60-0.95 m on its longest axis — a ±10 % band would be '
        "tighter than the object really is, so the band is the object's own range. The "
        'up-axis check rides along because a Z-up export makes the height meaningless.',
    ),
    _p(
        'contract_uv',
        'UVs are usable',
        ['uv'],
        _CONTRACT_IN,
        [{'check': 'has_uv', 'overlap': 0.01, 'when': 'glb'}, {'check': 'uv_overlap_max', 'max': 0.01, 'when': 'glb'}],
        MESH_ROWS,
        state_note='overlap under 1 % of UV face area. Mirrored islands are overlap and count '
        'against the row: a mirrored island cannot carry a baked map or a decal.',
    ),
    _p(
        'contract_texture',
        'Textures come with it',
        ['texture_out'],
        _CONTRACT_IN,
        [
            {'check': 'texture_file_present', 'min_px': 512, 'when': 'glb'},
            {'check': 'pbr_maps_present', 'maps': ['basecolour'], 'when': 'glb'},
        ],
        MESH_ROWS,
        state_note='a flat single-colour image is not a texture and fails; 512 px is the floor '
        'below which nothing survives a close-up.',
    ),
    _p(
        'contract_pbr',
        'PBR materials',
        ['pbr'],
        _CONTRACT_IN,
        [
            {'check': 'pbr_maps_present', 'maps': ['roughness', 'metallic'], 'when': 'glb'},
            {'check': 'pbr_value_range', 'field': 'metallic', 'shell': 'head', 'min': 0.6, 'max': 1.0, 'when': 'glb'},
            {'check': 'pbr_value_range', 'field': 'roughness', 'shell': 'haft', 'min': 0.3, 'max': 1.0, 'when': 'glb'},
        ],
        MESH_ROWS,
        state_note='the iron head must read metallic and the ash haft must not: a row that writes '
        'one constant material over the whole object passes "maps present" and fails '
        'here, which is the distinction the column is for.',
    ),
    # ── the polygon ask ──
    _p(
        'poly_ladder',
        'Polygon count is controllable',
        ['poly_budget'],
        _CONTRACT_IN,
        [
            {'check': 'tris_within_ask', 'tolerance': 0.2, 'when': 'glb'},
            {'check': 'mesh_tris_min', 'min': 500, 'when': 'glb'},
            {
                'check': 'build_error',
                'terms': ['budget', 'polygon', 'triangle', 'face count', 'not supported'],
                'when': 'report',
            },
        ],
        MESH_ROWS,
        grid={'ask_tris': [20000, 80000, 320000]},
        state_note='three asks, ±20 % each. A row with no polygon lever must FAIL LOUDLY — the '
        'build_error check is what separates "cannot" (a named refusal, partial) from '
        '"ignored the ask silently" (a no). Silent is the expensive kind.',
    ),
    # ── what it takes ──
    _p(
        'in_image',
        'From a single image',
        ['from_image'],
        {
            'fixture': FX + '/in_single/axe_front.png',
            'note': 'one 1024x1024 PNG, subject upright and whole, background flat mid-grey',
        },
        [
            {'check': 'build_succeeds', 'when': 'report'},
            {'check': 'mesh_watertight', 'when': 'glb'},
            {
                'check': 'bbox_dims_m',
                'axis': 'max',
                'min': CONTRACT['length_m'][0],
                'max': CONTRACT['length_m'][1],
                'when': 'glb',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the object in this turntable sheet a boarding axe — a haft, a head with a blade and a spike opposite it? yes/no',
            },
        ],
        GEN_ROWS,
        state_note='the column asks whether the mode WORKS, so it takes a build that parses and a '
        "recognisable object, not a good one. Quality is the Builds band's question.",
    ),
    _p(
        'in_multi',
        'From several views',
        ['from_multi'],
        {
            'fixture': FX + '/in_multi/',
            'note': 'the same axe at 0/90/180/270 degrees, four 1024x1024 PNGs, one lens, one light rig',
        },
        [
            {'check': 'build_succeeds', 'when': 'report'},
            {'check': 'mesh_watertight', 'when': 'glb'},
            {
                'check': 'build_error',
                'terms': ['single image', 'one image', 'multi', 'not supported'],
                'when': 'report',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the object in this turntable sheet a boarding axe — a haft, a head with a blade and a spike opposite it? yes/no',
            },
        ],
        GEN_ROWS,
        state_note='a row that takes only one image must say so (build_error) rather than quietly '
        'using the first file; the four views are the same renders the 0-degree fixture '
        'came from, so from_image and from_multi are compared on one subject.',
    ),
    _p(
        'in_text',
        'From text alone',
        ['from_text'],
        {'prompt': CONTRACT['prompt'], 'note': 'the contract prompt verbatim, no image, no reference'},
        [
            {'check': 'build_succeeds', 'when': 'report'},
            {'check': 'mesh_watertight', 'when': 'glb'},
            {
                'check': 'build_error',
                'terms': ['image required', 'no image', 'text', 'not supported'],
                'when': 'report',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the object in this turntable sheet a boarding axe — a haft, a head with a blade and a spike opposite it? yes/no',
            },
        ],
        GEN_ROWS,
        state_note='an image-to-3D row is expected to refuse here; a named refusal is a partial and '
        'a silently empty or degenerate mesh is a no.',
    ),
    _p(
        'backside',
        'Invents a plausible back',
        ['backside'],
        {
            'fixture': FX + '/in_single/coat_front.png',
            'note': 'a front-only 1024x1024 PNG of a period coat on a stand — a subject whose back '
            'the input cannot show, so the back is entirely invented',
        },
        [
            {'check': 'mesh_watertight', 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Looking only at the 180-degree view: is the back of this coat a plausible back — seams, a hem and a collar that continue the front — rather than a smeared copy of the front, a flat plane or a melted surface? yes/no',
            },
        ],
        GEN_ROWS,
        state_note='no detector decides this; it is the operator question with the mechanical checks '
        'as a veto. A collapsed or hollow back usually also breaks watertight, and where '
        'it does the mechanical no stands whatever the operator says.',
    ),
    # ── the material families ──
    _p(
        'subj_human',
        'Human bodies',
        ['human'],
        {
            'prompt': 'A standing adult man in plain working clothes, arms at his sides, bare head, '
            'feet flat on the ground. Neutral pose, whole figure.',
            'fixture': FX + '/in_single/man_standing.png',
        },
        [
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            {'check': 'mesh_watertight', 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 1.60, 'max': 1.90, 'when': 'glb'},
            {'check': 'glb_up_axis', 'when': 'glb'},
            {'check': 'hand_landmarks', 'hands': 2, 'fingers': 5, 'views': ['0'], 'when': 'sheet'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a usable human body mesh — one head, two arms, two legs, no fused or missing limb, no surface passing through another? yes/no',
            },
        ],
        MESH_ROWS,
        state_note='self-intersection is the veto that matters on a body (the Abel finding: a mesh '
        'that passed every visual review and was unusable because the limbs intersected '
        'the trunk). MediaPipe hand_landmarker is the only finger detector that is '
        'honest here; the operator question is global because no local VLM sees a fused '
        'finger (defect judge bench 2026-09-27: 2/8).',
    ),
    _p(
        'subj_creature',
        'Non-human creatures',
        ['creature_mesh'],
        {
            'prompt': 'A standing wolf, side on, four legs planted, tail down, mouth closed. Whole '
            'animal, plain grey background.',
            'fixture': FX + '/in_single/wolf_side.png',
        },
        [
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            {'check': 'mesh_watertight', 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'max', 'min': 0.9, 'max': 1.6, 'when': 'glb'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a usable four-legged animal mesh — four separate legs, one head, one tail, no fused or extra limb? yes/no',
            },
        ],
        MESH_ROWS,
    ),
    _p(
        'subj_props',
        'Props and hard surfaces',
        ['props_mesh'],
        {
            'prompt': 'An oak barrel with five iron hoops, standing on its base, lid on. Whole object, '
            'plain grey background.',
            'fixture': FX + '/in_single/barrel.png',
        },
        [
            {'check': 'mesh_watertight', 'when': 'glb'},
            {'check': 'mesh_edge_manifold', 'max': 0, 'when': 'glb'},
            {'check': 'mesh_shell_count', 'min': 1, 'max': 8, 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 0.70, 'max': 1.00, 'when': 'glb'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a usable barrel mesh — staves that read as staves, hoops that stand off the body rather than being painted on, a flat base it would stand on? yes/no',
            },
        ],
        MESH_ROWS,
        state_note='the hoops are the test: a hoop that is a texture stripe and not geometry is the '
        'standing prop failure (prop_mesh/gate_proof.py G3b embedment catches the same '
        'defect class on a hatchet in a trunk).',
    ),
    _p(
        'subj_cloth',
        'Cloth and soft goods',
        ['cloth_mesh'],
        {
            'prompt': 'A wool cloak hanging from a wooden peg, deep vertical folds, hem clear of the '
            'floor. Whole garment, plain grey background.',
            'fixture': FX + '/in_single/cloak.png',
        },
        [
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            {'check': 'mesh_degenerate_max', 'max': 0.0, 'when': 'glb'},
            {'check': 'mesh_tris_min', 'min': 5000, 'when': 'glb'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this cloak read as cloth — folds that are geometry with depth, a hem that is an edge rather than a seam in a texture, no fold passing through another? yes/no',
            },
        ],
        MESH_ROWS,
        state_note='cloth is where self-intersection is normal in generated output and fatal '
        'downstream: a fold through a fold cannot be simulated or rigged.',
    ),
    _p(
        'subj_hair',
        'Hair',
        ['hair_mesh'],
        {
            'prompt': 'Long straight hair to the shoulders on a bare head, centre parting, no face '
            'detail needed. Whole head, plain grey background.',
            'fixture': FX + '/in_single/hair_long.png',
        },
        [
            {'check': 'mesh_shell_count', 'min': 2, 'max': 400, 'when': 'glb'},
            {'check': 'mesh_degenerate_max', 'max': 0.0, 'when': 'glb'},
            {'check': 'has_uv', 'overlap': 0.5, 'when': 'glb'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the hair separate geometry from the head — cards or strands you could shade and move on their own — rather than a solid helmet fused to the skull? yes/no',
            },
        ],
        MESH_ROWS,
        state_note='the shell count is the mechanical half: hair fused into the head skin is ONE '
        'shell and fails, which is the char2d finding that a hair hull can cover the '
        'face. UV overlap is allowed up to 50 % here because mirrored hair cards are '
        'normal practice, unlike on a body.',
    ),
]

RUN_ORDER = [
    # cheap and mechanical first, so a partial run still fills the mesh columns
    'contract_usable',
    'contract_topology',
    'contract_quads',
    'contract_watertight',
    'contract_scale',
    'contract_uv',
    'contract_texture',
    'contract_pbr',
    'poly_ladder',
    'in_text',
    'in_image',
    'in_multi',
    'subj_props',
    'subj_human',
    'subj_creature',
    'subj_cloth',
    'subj_hair',
    'backside',
    'SHARED: capacity, space, attributes, prompt bands',
    'SHARED: Builds (132 subjects x 3 seeds) — last, it is the bulk of the cost',
]

# ── per-row exemptions on the DOMAIN columns ────────────────────────────────────────────────
_MPFB_NA = {
    'from_image': 'MPFB is a parametric human generator driven by macro and morph parameters in a '
    'headless Blender script. It has no image input at all, so there is no mode to '
    'measure rather than a mode that fails.',
    'from_multi': 'No image input of any count: the row is driven by parameters, so several views '
    'are as inapplicable as one.',
    'from_text': 'No text input either. The subject id selects a parameter set; there is no '
    'wording for a text encoder to receive.',
    'props_mesh': 'MPFB builds human bases and their CC0 assets only. A barrel is outside what the '
    'generator can express, so asking it is asking a question with one possible '
    'answer and no information in it.',
    'creature_mesh': 'The MPFB morph space is human. A wolf cannot be reached from it at any '
    'parameter setting, so this is not a capability the row withholds.',
    'texture_out': 'The CC0 base bodies ship with the skin material the library was built with '
    '(blender_scripts/build_human_base_library.py); the row does not generate a '
    'texture, it copies one, and grading a copy as a generated texture would be a '
    'claim about the library rather than about this row.',
}
_LIB_NA = {
    'from_image': 'A library row takes a query and returns an asset that is already on disk. There '
    'is no image-conditioned generation to measure; the image-to-asset question '
    'belongs to a retrieval sheet, not to mesh generation.',
    'from_multi': 'Several views are still not an input to a lookup: the library is addressed by '
    'tags and a query string, never by pictures.',
    'poly_budget': 'The asset has the polygon count it was authored with. A lookup has no lever to '
    'hit a 20k / 80k / 320k ask, so the ladder measures the librarian, not the row.',
    'human': 'The prop mesh library holds props and hard surfaces by definition '
    '(project_prop_mesh_library); there is no body in it to return.',
    'creature_mesh': 'No creature assets in the prop mesh library; a query for a wolf returns '
    "nothing and that is the library's scope, not a failure of this row.",
    'cloth_mesh': 'No soft goods in the prop mesh library. Cloth is authored per character in the '
    'wardrobe path, not held as a prop.',
    'hair_mesh': 'No hair assets in the prop mesh library; hair is a character asset and lives '
    'with the character build.',
    'backside': 'A library asset was authored whole, from every side. Nothing is invented, so '
    'there is no invented back to judge.',
}
_D3S2_NA = {}

NA = {}  # every domain column of this step has a probe or a derive; nothing is step-wide na

TEST = {
    'step': 'mesh_gen',
    'version': '2026-09-30.1',
    'title': 'One contract build, three ladders, five material families',
    'purpose': (
        'Decide "usable geometry" mechanically off the exported GLB — closed, manifold, '
        'normals out, no self-intersection, quads, triangle count against the ask, metres, '
        'UVs, PBR maps — and ask the operator only where no detector exists (the invented '
        'back and the five material families).'
    ),
    'include_shared': 'geometry',
    'contract_build': dict(CONTRACT, note=CONTRACT_GLB_NOTE),
    'run_order': RUN_ORDER,
    'rows': {
        'direct3d_s2': {
            'transport': 'service',
            'model': 'Direct3D-S2 (project_direct3d_s2_install), called as a function in its own '
            'process; the row names its installed revision in the trial',
            'where': 'the installed Direct3D-S2 entry point, run out-of-process — never imported '
            'into the Flask GUI (torch in the GUI process has taken the dashboard down)',
            'na': _D3S2_NA,
        },
        'mpfb': {
            'transport': 'blender',
            'model': 'MPFB human bases, CC0 (project_human_base_install)',
            'where': 'blender -b --python blender_scripts/build_human_base_library.py, the parameter '
            'sets the base body library was built from',
            'na': _MPFB_NA,
            'budget': {
                'calls': 120,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 180,
                'gpu_minutes': 0,
                'operator_minutes': 60,
                'tokens_note': 'a headless Blender script takes parameters; no language model is called at any point',
                'note': (
                    'MPFB answers only the human and cloth/hair families and the mesh contract: about 40 builds x 3 '
                    'seeds = 120 runs at ~90 s of CPU Blender = ~180 min, capped at 20 of 24 cores '
                    '(feedback_cpu_core_cap), no GPU. Operator: ~120 blind decisions x 30 s = 60 min.'
                ),
            },
        },
        'prop_lib': {
            'transport': 'library',
            'model': 'the house prop mesh library (project_prop_mesh_library)',
            'where': 'prop_mesh/sheet_register.py + the prop mesh library on disk; a query in, '
            'ranked assets out, nothing generated',
            'na': _LIB_NA,
            'budget': {
                'calls': 400,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 12,
                'gpu_minutes': 0,
                'operator_minutes': 90,
                'tokens_note': 'a library lookup is a tag query against an index; no model and no tokens',
                'note': (
                    'A lookup is milliseconds and needs no seeds: ~400 queries (132 Builds subjects plus the '
                    'domain and capacity probes) at well under 2 s each = ~12 min, no GPU. The cost of this '
                    'row is almost entirely OPERATOR: ~180 blind looks at what the library returned x 30 s '
                    '= 90 min.'
                ),
            },
        },
        'smpl': {
            'transport': 'retired',
            'model': 'SMPL body family (SMPL / SMPL-X / SMPL+H)',
            'skip': 'Retired 2026-09-30: SMPL is licensed for non-commercial research only and is '
            'not used anywhere in the house (the body path is MPFB CC0 plus the Blender '
            'Studio CC0 bodies). The row is kept so the sheet keeps the receipt for why '
            'the obvious choice was not taken.',
            'budget': {
                'calls': 0,
                'tokens_in': 0,
                'tokens_out': 0,
                'minutes': 0,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'tokens_note': 'a retired row is never run, so it spends nothing at all',
                'note': 'Retired row: the runner skips it and writes the skip reason on every column. Zero cost by construction.',
            },
        },
    },
    'probes': PROBES,
    'derive': {
        'riggable': {
            'from': "the rigging step's `rigs` probe, run on the GLBs this step produced "
            '(the same files, not a re-build): the share that reach a bound '
            'armature with weights and no zero-weight vertex. Measured THERE and '
            'read here, so the two sheets cannot disagree about one mesh',
            'grade': 'measured',
            'unit': 'share of builds that bind',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': NA,
    'fixtures': [
        {
            'path': FX + '/contract_axe.png',
            'generated': 'One 1024x1024 PNG of the contract subject: render the house boarding-axe '
            'asset (prop_mesh/axe_render.py) at 0 degrees, three-point rig, background '
            'flattened to mid-grey, object upright and centred with a 5 per cent margin.',
            'verified': False,
            'blocks': ['usable', 'topology', 'quads', 'watertight', 'scale', 'uv', 'texture_out', 'pbr', 'poly_budget'],
            'how_to_verify': 'Open the PNG and confirm it shows ONE whole boarding axe, upright, '
            'unclipped, on a flat background, with the spike and the blade both '
            'visible — an image-conditioned row is only as good as the picture it was '
            'handed, so a cropped or ambiguous fixture would be scored against the '
            'model. Then set verified = True.',
        },
        {
            'path': FX + '/in_single/axe_front.png',
            'generated': 'The 0-degree view of the four-view set below, saved on its own.',
            'verified': False,
            'blocks': ['from_image'],
            'how_to_verify': 'Confirm it is the 0-degree frame of in_multi, unaltered, so from_image '
            'and from_multi differ only in how many views the row was given.',
        },
        {
            'path': FX + '/in_multi/',
            'generated': 'blender -b --python blender_scripts/render_asset_previews.py over the house '
            'boarding-axe asset: four 1024x1024 PNGs at 0/90/180/270 degrees, one lens, '
            'one three-point rig, written as 000.png 090.png 180.png 270.png.',
            'verified': False,
            'blocks': ['from_multi'],
            'how_to_verify': 'Confirm the four files exist, show the same object, and that the angles '
            'are the angles the filenames claim (a swapped 90/270 pair would silently '
            'reverse every mesh built from them).',
        },
        {
            'path': FX + '/in_single/coat_front.png',
            'generated': 'One 1024x1024 front render of the house period-coat wardrobe asset on a '
            'stand, back not visible, background flat mid-grey.',
            'verified': False,
            'blocks': ['backside'],
            'how_to_verify': 'Confirm NOTHING of the back is visible — no lapel turning away, no '
            'mirror, no shadow that shows the hem behind. If the back can be inferred '
            'from the input the probe measures copying, not invention.',
        },
        {
            'path': FX + '/in_single/man_standing.png',
            'generated': 'One 1024x1024 front render of the male CC0 base body from '
            'blender_scripts/build_human_base_library.py in plain working clothes, arms '
            'at the sides, whole figure, feet in frame, background flat mid-grey.',
            'verified': False,
            'blocks': ['human'],
            'how_to_verify': 'Confirm the ANKLES are inside the frame and both hands are unoccluded — '
            'the body-anchor finding of 2026-09-22 is that only 6 of 16 character '
            'anchors had ankles in frame, and a detector extrapolates joints past the '
            'frame edge rather than refusing.',
        },
        {
            'path': FX + '/in_single/wolf_side.png',
            'generated': 'One 1024x1024 side render of the CC0 quaternius_animals wolf '
            '(data/assets/mesh_packs/quaternius_animals), all four legs visible, '
            'background flat mid-grey.',
            'verified': False,
            'blocks': ['creature_mesh'],
            'how_to_verify': 'Confirm all four legs are separately visible and the tail is clear of '
            'the body, so a fused-leg output is attributable to the row.',
        },
        {
            'path': FX + '/in_single/barrel.png',
            'generated': 'One 1024x1024 render of the house oak-barrel prop, standing, five hoops '
            'visible, background flat mid-grey.',
            'verified': False,
            'blocks': ['props_mesh'],
            'how_to_verify': 'Confirm the hoops stand off the staves in the picture (a shadow line '
            'under each) — the probe asks whether the row makes them geometry, which '
            'only means something if the input shows them as geometry.',
        },
        {
            'path': FX + '/in_single/cloak.png',
            'generated': 'One 1024x1024 render of the house wool-cloak wardrobe asset hanging from a '
            'peg, deep folds, hem clear of the floor, background flat mid-grey.',
            'verified': False,
            'blocks': ['cloth_mesh'],
            'how_to_verify': 'Confirm the folds read as depth and not as a printed pattern, and that '
            'the hem is clear of the ground so a hem-through-floor output is the '
            "row's own defect.",
        },
        {
            'path': FX + '/in_single/hair_long.png',
            'generated': 'One 1024x1024 render of the MPFB long-hair CC0 asset on a bare base head, '
            'centre parting, background flat mid-grey.',
            'verified': False,
            'blocks': ['hair_mesh'],
            'how_to_verify': 'Confirm the hair is visibly separate from the scalp at the parting, so '
            "a fused helmet output is the row's defect and not the fixture's.",
        },
    ],
    'budget': {
        'calls': 690,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a mesh generator takes a prompt into its OWN text encoder and a Blender script takes parameters; no language-model tokens are spent on this step',
        'minutes': 1100,
        'gpu_minutes': 900,
        'operator_minutes': 230,
        'note': (
            'DOMAIN: the contract build 1 subject x 3 seeds = 3 GLBs answers nine columns; the polygon ladder '
            '3 asks x 3 = 9; the three input modes 3 x 3 = 9; the backside coat 3; five material families 5 x 3 '
            '= 15. That is 39 builds. SHARED BANK: the Builds band is 132 subjects x 3 seeds = 396 builds, and '
            'the capacity ladders, space, attribute and 53 prompt columns add roughly 250 more, so the bank is '
            '~650 builds — it is the bulk of this test and is LAST in run_order for exactly that reason. '
            '690 builds x ~90 s (generate + export + 4-view turntable) = ~1035 min, plus model load; call it '
            '1100 min wall and 900 min of that on the GPU (the turntable render is Blender on CPU). OPERATOR: '
            '~24 domain blind decisions plus ~430 bank decisions = ~455 x 30 s = ~230 min per generating row. '
            'The mpfb, prop_lib and smpl rows override this downward (Blender CPU, a lookup, and a retired row '
            'that costs nothing). No claude_cli or anthropic_api row on this step, so the shared Claude week is '
            'not touched.'
        ),
    },
    'notes': [
        'Nine of the nineteen domain columns are read off ONE build. That is deliberate: they are '
        'properties of a single exported GLB, and building nine times would measure seed variance '
        'rather than the nine properties.',
        '`quads` will read 0.0 on any SDF or marching-cubes row. That is the honest number and the '
        'reason the column exists — a triangle soup cannot be subdivided or edge-loop-selected, so '
        'it cannot be rigged, however good it looks.',
        '`riggable` is derived from the rigging step rather than probed here, so one mesh cannot be '
        'called riggable on this sheet and unbindable on that one.',
        'Every fixture is declared with the command that makes it and none is created by this test. '
        'All nine are verified = False, so on a first run the domain columns are written untested '
        '"fixture unverified" until an operator has looked at the set.',
    ],
}
