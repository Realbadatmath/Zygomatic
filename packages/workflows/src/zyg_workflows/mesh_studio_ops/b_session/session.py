# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — SESSION — the op stack, the rollback, the replay and the door out.

Section ``SESSION`` of the single-file ``b_session.py``, moved verbatim
(original lines 1541-1748); every op is still ``ph=True`` and nothing here is
implemented. The banner comment below is the section's own documentation.
"""

from .base import _dock, b, e, i, s

# ══ SESSION ═════════════════════════════════════════════════════════════════
# The session itself: the op stack, what it can be rolled back to, what it can
# be replayed as, and the door out. Nothing here needs a mesh except the ones
# that operate on one, and everything here is recorded — a studio whose history
# is only in the viewport cannot explain how a mesh got the way it is.

_dock(
    'ss_undo',
    'Undo',
    'Session',
    'Step back one op on the stack. The stack is the list of parameterised '
    'ops applied to the source mesh, so undo removes an op rather than '
    'restoring a copy of the geometry — which is why it is cheap on a '
    'two-million-triangle mesh and why it can undo an op from the middle.',
    '<path d="M8.4 6.2L4.2 10.4l4.2 4.2"/><path d="M4.2 10.4h9.8a5.4 5.4 0 010 10.8H8.6"/>',
    [i('steps', 'Steps', 1, 1, 50, 1), b('keep_camera', 'Leave the camera where it is', True)],
    needs='',
)

_dock(
    'ss_redo',
    'Redo',
    'Session',
    'Step forward again through ops that were undone. The redo branch is '
    'kept until a new op is applied, at which point the undone tail is '
    'archived to the session log rather than dropped — the parameters of a '
    'thing you tried are worth more than the geometry it made.',
    '<path d="M15.6 6.2l4.2 4.2-4.2 4.2"/><path d="M19.8 10.4H10a5.4 5.4 0 000 10.8h5.4"/>',
    [i('steps', 'Steps', 1, 1, 50, 1), b('keep_camera', 'Leave the camera where it is', True)],
    needs='',
)

_dock(
    'ss_snapshot',
    'Snapshot',
    'Session',
    'Freeze the whole session — mesh, op stack, parameters, camera, pinned '
    'sources and view toggles — under a name. A snapshot is the thing to '
    'take before a big edit, and the thing compare A/B measures against '
    'afterwards.',
    '<path d="M4.6 8h3.2l1.4-2h5.6l1.4 2h3.2v10.4H4.6z"/><circle cx="12" cy="13" r="3.1"/><path d="M17.4 10.2h1.2"/>',
    [
        s('name', 'Name', ''),
        b('with_geometry', 'Include the baked geometry, not only the stack', False),
        b('with_thumb', 'Render a thumbnail for it', True),
    ],
    needs='',
)

_dock(
    'ss_restore',
    'Restore snapshot',
    'Session',
    'Put the session back to a snapshot, listing what will change before it '
    'does. Restoring never deletes: the state being left is snapshotted '
    'first under an automatic name, so restoring the wrong one costs a '
    'second restore rather than an afternoon.',
    '<path d="M5.4 12a6.6 6.6 0 1 0 2.2-4.9"/><path d="M4.6 5.8v3.6h3.6"/><path d="M12 8.8V12l2.4 1.6"/>',
    [
        e('which', 'Snapshot', 'latest', ('latest', 'pick from the list')),
        b('snapshot_first', 'Snapshot the current state first', True),
        b('restore_camera', 'Restore the camera too', True),
    ],
    needs='',
)

_dock(
    'ss_preset_save',
    'Save preset',
    'Session',
    'Save the parameters currently set across the bar as a named preset — '
    'not the mesh, only the knobs. The way a retopo recipe that worked on '
    'one character gets applied to the next eleven without being '
    'remembered by hand.',
    '<path d="M5.2 5.4h11l2.6 2.6v10.6H5.2z"/><path d="M8.4 5.4v4.4h6.2V5.4"/><path d="M8.4 18.6v-5h7.2v5"/>',
    [
        s('name', 'Preset name', ''),
        e('scope', 'What to save', 'section', ('this op', 'section', 'whole bar', 'view state')),
        b('overwrite', 'Overwrite an existing preset of that name', False),
    ],
    needs='',
)

_dock(
    'ss_preset_load',
    'Load preset',
    'Session',
    'Apply a saved preset to the bar. Shows which parameters it will change '
    'and which of them differ from what is set now, because a preset that '
    'quietly moves a knob you tuned is worse than no preset.',
    '<path d="M4.4 6.8h6l1.6 2h7.6v9.4H4.4z"/><path d="M12 11.2v5.2M9.8 14.2l2.2 2.2 2.2-2.2"/>',
    [
        e('preset', 'Preset', 'last used', ('last used', 'pick from the list')),
        b('preview_diff', 'Show what it would change first', True),
        b('only_missing', 'Only set parameters still at their default', False),
    ],
    needs='',
)

_dock(
    'ss_recipe',
    'Recipe',
    'Session',
    'Export the session as a recipe: the ordered list of ops and parameters '
    'that turns the source mesh into this one, as JSON that can be replayed '
    'on another mesh or checked into a brief. The difference between a mesh '
    'that was made and a mesh that can be remade.',
    '<path d="M6.4 4.2h11.2v15.6H6.4z"/><path d="M9.2 8h6M9.2 11.2h6M9.2 14.4h3.6"/>'
    '<path d="M6.4 4.2v15.6M8.2 4.2v15.6"/>',
    [
        e('format', 'Format', 'json', ('json', 'markdown', 'python')),
        b('include_defaults', 'Include parameters left at their default', False),
        b('include_source', 'Record the source mesh id and hash', True),
    ],
    needs='',
)

_dock(
    'ss_log',
    'Session log',
    'Session',
    'Everything this session did, in order, with timestamps, durations and '
    'what each op reported — including the ops that failed and the fits that '
    'were rejected. The log is the honest account; the op stack is only the '
    'part that survived.',
    '<path d="M4.8 5.6h14.4v13H4.8z"/><path d="M4.8 9h14.4"/>'
    '<path d="M7.6 12.2h8.8M7.6 15.4h6"/><circle cx="7.4" cy="7.3" r=".8"/>',
    [
        e('level', 'Show', 'all', ('all', 'ops only', 'warnings', 'errors')),
        b('durations', 'Show how long each op took', True),
        b('export', 'Write it beside the mesh', False),
    ],
    needs='',
)

_dock(
    'ss_reload',
    'Reload registry',
    'Session',
    'Re-read this registry from disk and redraw the bars. Adding an op to a '
    'part file and pressing this is the whole edit-test loop for the studio '
    'itself — no restart of the server, no reload of the page, and the open '
    'mesh and its stack are untouched.',
    '<path d="M18.6 8.6A7.2 7.2 0 005.6 7.2"/><path d="M5.4 15.6a7.2 7.2 0 0013 1.2"/>'
    '<path d="M18.6 4.6v4h-4M5.4 19.4v-4h4"/><circle cx="12" cy="12" r="1.4"/>',
    [
        b('keep_params', 'Keep the parameters currently set', True),
        b('report_changes', 'List the ops that appeared or vanished', True),
    ],
    needs='',
)

_dock(
    'ss_help',
    'Help',
    'Session',
    'What this studio is, what each bar means, what needs a mesh and what '
    'needs the GPU — and the list of what is deliberately absent, with the '
    'reason. Every op in this studio is a placeholder today and the help '
    'sheet says so at the top rather than in a footnote.',
    '<circle cx="12" cy="12" r="8.2"/>'
    '<path d="M9.6 9.6a2.5 2.5 0 114.2 2c-.9.8-1.8 1.2-1.8 2.4"/>'
    '<path d="M12 17.2h.1"/>',
    [
        e(
            'topic',
            'Topic',
            'overview',
            ('overview', 'bars and sections', 'what needs what', 'deliberately absent', 'keyboard'),
        ),
        b('inline', 'Open it beside the viewport instead of over it', True),
    ],
    needs='',
)

_dock(
    'ss_reset',
    'Reset all',
    'Session',
    'Put every parameter in the bar back to its default and clear the view '
    'toggles, leaving the mesh and the op stack alone. The op that gets used '
    'after an hour of experiments when it is no longer clear which of forty '
    'knobs is the one causing the wrong result.',
    '<path d="M12 4.6v5.2"/><circle cx="12" cy="13.6" r="6.4"/><path d="M7.6 9.2l1.6 1.6M16.4 9.2l-1.6 1.6"/>',
    [
        e('scope', 'Reset', 'parameters', ('parameters', 'view toggles', 'both')),
        b('keep_camera', 'Leave the camera alone', True),
        b('confirm', 'Ask first', True),
    ],
    needs='',
)

_dock(
    'ss_close',
    'Close mesh',
    'Session',
    'Close the open mesh and free its buffers. Unsaved stack entries are '
    'listed before anything is dropped and can be saved as a derived mesh, a '
    'snapshot or a recipe on the way out — closing is the last place a '
    "session's work can still be kept, and the studio says so.",
    '<path d="M14.6 4.6h4.8v14.8h-4.8"/><path d="M4.6 12h9.2M10.6 8.6L14 12l-3.4 3.4"/>',
    [
        b('save_stack', 'Offer to save the stack first', True),
        b('free_gpu', 'Free the GPU buffers too', True),
        b('keep_recent', 'Keep it in Recent', True),
    ],
    needs='',
)
