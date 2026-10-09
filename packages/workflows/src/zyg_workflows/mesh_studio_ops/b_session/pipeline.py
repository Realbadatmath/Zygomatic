# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — PIPELINE — the doors out of this studio into the rest of the house.

Section ``PIPELINE`` of the single-file ``b_session.py``, moved verbatim
(original lines 1124-1306); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _dock, b, e, s

# ══ PIPELINE ════════════════════════════════════════════════════════════════
# The doors out of this studio into the rest of the house. Registering and
# linking are how a mesh stops being a file in a folder and becomes an asset
# something else can name; the three 'send to' ops hand the open mesh to
# another studio without either of them copying it.

_dock(
    'pl_register_prop',
    'Register as prop',
    'Pipeline',
    'Enter the mesh in prop_mesh_library with its id, hash, triangle count, '
    'bounding box, licence and generator (if it has one). Registration is '
    'what makes a mesh addressable by name from a scene build, and the hash '
    'is what makes "the same prop" a checkable statement rather than a '
    'filename convention.',
    '<path d="M4.8 9.4l7.2-4.2 7.2 4.2v7.2L12 20.8l-7.2-4.2z"/><path d="M9.2 12.6l2.2 2.2 4-4.4"/>',
    [
        e('family', 'Family', 'misc', ('misc', 'pufferball', 'hurlbat', 'tree', 'furniture')),
        s('name', 'Name', ''),
        b('with_thumb', 'Render a thumbnail for the library', True),
        b('overwrite', 'Replace an existing entry with this id', False),
    ],
)

_dock(
    'pl_register_creature',
    'Register creature mesh',
    'Pipeline',
    'Register the mesh as the geometry of a creature in the creature '
    "library, against the creature's id rather than against a path. The "
    'creature keeps its sheet, its identity anchors and its judge verdicts; '
    'this is only the statement that this mesh is its body.',
    '<path d="M5.4 15.6c0-3.4 2.4-5.6 5.4-5.6s5.4 2.2 5.4 5.6"/>'
    '<path d="M16.2 13.4l3-1.6-1-3.2"/><circle cx="8.6" cy="7.6" r="2.6"/>'
    '<path d="M7 19.4h8.4"/>',
    [
        s('creature_id', 'Creature id', ''),
        e('slot', 'Slot', 'body', ('body', 'variant', 'lod', 'proxy')),
        b('run_judge', 'Run the creature judge before registering', True),
    ],
)

_dock(
    'pl_derive_body',
    'Derive body',
    'Pipeline',
    'Run geom.mesh_skeletons derive: take this mesh as a surface and produce '
    'the body representation the rest of the house animates — skeleton, '
    'segment map and the joint limits. Deriving is the step that turns a '
    'shape into something that can be posed, and it is re-runnable, so a '
    'changed mesh gets a changed body rather than a stale one.',
    '<circle cx="12" cy="4.6" r="1.6"/><path d="M12 6.2v5.2"/>'
    '<path d="M8 8.2h8"/><circle cx="8" cy="8.2" r="1.1"/>'
    '<circle cx="16" cy="8.2" r="1.1"/><path d="M12 11.4l-2.4 4.2-1 4.4"/>'
    '<path d="M12 11.4l2.4 4.2 1 4.4"/>',
    [
        e('skeleton', 'Skeleton', 'auto', ('auto', 'humanoid', 'quadruped', 'bird')),
        b('limits', 'Derive joint limits too', True),
        b('replace', 'Replace the existing derived body', False),
    ],
    needs='rig',
)

_dock(
    'pl_reissue',
    'Reissue',
    'Pipeline',
    'Rebuild everything downstream of this mesh — plates, sheets, thumbnails, '
    'derived bodies, registry entries — because the mesh changed. Always '
    'shows the dry run first: what would be rebuilt, what would be '
    'overwritten and what is out of date but not owned by this mesh. Nothing '
    'is written until the dry run is accepted.',
    '<path d="M19 9.4A7.4 7.4 0 006 7.6M5 14.6a7.4 7.4 0 0013 1.8"/><path d="M19 5.2v4.2h-4.2M5 18.8v-4.2h4.2"/>',
    [
        b('dry_run', 'Dry run — list without writing', True),
        e('scope', 'Scope', 'direct', ('direct', 'all downstream', 'plates only')),
        b('keep_old', 'Keep the old outputs beside the new', True),
    ],
    cls='act',
)

_dock(
    'pl_hash_verify',
    'Hash verify',
    'Pipeline',
    "Recompute the mesh's content hash and compare it with what the "
    'registry, the manifests and the downstream outputs recorded. A mismatch '
    'names which of them is stale and exactly one is true: the file on disk. '
    'This is the op that catches an asset edited outside the studio.',
    '<path d="M12 3.6l6.8 2.6v6c0 4-2.8 6.6-6.8 8.2-4-1.6-6.8-4.2-6.8-8.2v-6z"/><path d="M9 11.6h6M9 14.2h4"/>',
    [
        e('scope', 'Check', 'all', ('all', 'registry', 'manifests', 'outputs')),
        b('fix_records', 'Update the records that are stale', False),
        b('report', 'Write the comparison to the session log', True),
    ],
    cls='pix',
    needs='',
)

_dock(
    'pl_link_character',
    'Link to character',
    'Pipeline',
    "Bind the mesh to a character in the character bible as that character's "
    'body, so the identity anchors, the proportion lock and the wardrobe '
    'follow it. Linking is not copying: the character keeps owning who it '
    'is, and this mesh becomes the geometry that claim is checked against.',
    '<path d="M10 14a3.6 3.6 0 010-5l2.4-2.4a3.6 3.6 0 015.1 5.1l-1.2 1.2"/>'
    '<path d="M14 10a3.6 3.6 0 010 5l-2.4 2.4a3.6 3.6 0 01-5.1-5.1l1.2-1.2"/>',
    [
        s('character_id', 'Character id', ''),
        e('slot', 'As', 'body', ('body', 'head', 'variant', 'lod')),
        b('check_identity', 'Score identity before linking', True),
    ],
)

_dock(
    'pl_link_creature',
    'Link to creature',
    'Pipeline',
    "Bind the mesh to a creature record the same way, against the creature's "
    'sheet and its judge history. Kept separate from the character link on '
    'purpose: creatures have no anthropometric gate and no wardrobe, and '
    'sharing one link op would mean sharing the checks.',
    '<path d="M6.6 17.8c-1.6-1.2-2.4-3-2.4-5 0-3.4 2.6-6 5.8-6h3.6"/>'
    '<path d="M13.6 6.8l4-2.2-.6 3.6 3 1.4-3.2 2.2"/>'
    '<circle cx="9.4" cy="11.4" r="1.1"/><path d="M6.6 17.8h9.8"/>',
    [
        s('creature_id', 'Creature id', ''),
        e('slot', 'As', 'body', ('body', 'head', 'variant', 'lod')),
        b('check_sheet', 'Check it against the creature sheet', True),
    ],
)

_dock(
    'pl_send_character',
    'Send to Character Studio',
    'Pipeline',
    'Hand the open mesh to Character Studio and switch to it — for the '
    'identity work a mesh studio has no business doing: anchors, wardrobe, '
    'expression sets, the bible entry. The mesh is passed by id, so both '
    'studios are looking at the same file rather than at two copies of it.',
    '<circle cx="8.4" cy="7.2" r="2.8"/>'
    '<path d="M3.6 16.4a4.8 4.8 0 019.6 0"/>'
    '<path d="M13.8 12.2h6.6M17.6 9.4l2.8 2.8-2.8 2.8"/>',
    [b('keep_open', 'Keep it open here too', True), b('carry_measure', 'Carry the measure report with it', True)],
    needs='',
)

_dock(
    'pl_send_creature',
    'Send to Creature Studio',
    'Pipeline',
    'Hand the open mesh to Creature Studio and switch to it — for the sheet, '
    'the variants and the judge. The same door as the character one and a '
    'different room; a mesh that is both is a decision someone has to make '
    'rather than a state the studio should allow.',
    '<path d="M4.2 14.6c0-3 2.2-5.2 5-5.2s5 2.2 5 5.2"/>'
    '<circle cx="6.8" cy="7.4" r="2.2"/>'
    '<path d="M15.4 12.2h5.2M18 9.6l2.6 2.6-2.6 2.6"/>',
    [b('keep_open', 'Keep it open here too', True), b('run_judge', 'Run the judge on arrival', False)],
    needs='',
)

_dock(
    'pl_send_movement',
    'Send to Movement Studio',
    'Pipeline',
    'Hand the rigged mesh to Movement Studio, which owns motion. Mesh Studio '
    'rigs and tests one pose; the moment there is a second pose in time it is '
    "Movement Studio's file and Movement Studio's bar, and this is the door "
    'that keeps that boundary from being crossed by copy and paste.',
    '<path d="M4.4 18.6c2.6-4.6 5.2-4.6 7.8 0"/>'
    '<circle cx="8.3" cy="6.2" r="2"/><path d="M8.3 8.2v4.2"/>'
    '<path d="M5.8 10h5M15.6 12.4h5M18 9.8l2.6 2.6-2.6 2.6"/>',
    [
        b('require_rig', 'Refuse if the mesh is not rigged', True),
        b('carry_limits', 'Carry the joint limits with it', True),
    ],
    needs='rig',
)
