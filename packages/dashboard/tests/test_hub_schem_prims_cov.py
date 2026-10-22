# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for the Creator's parametric primitives.

Every op is a pure function of a params dict — no I/O, no globals — so these
tests only build small shapes and assert on the emitted block lists.
"""

import math

import pytest
from zyg_dashboard.hub import schem_prims as mod


def _cells(blocks):
    return {(b['x'], b['y'], b['z']) for b in blocks}


# ── _blk ────────────────────────────────────────────────────────────────
def test_blk_coerces_to_int_and_omits_empty_state():
    b = mod._blk(1.9, -2.5, 3.2, 'stone', 'wall')
    assert (b['x'], b['y'], b['z']) == (1, -2, 3)
    assert b['mat'] == 'stone' and b['kind'] == 'wall'
    assert 'state' not in b


def test_blk_keeps_a_truthy_state():
    b = mod._blk(0, 0, 0, 'stairs', 'trim', {'facing': 'north'})
    assert b['state'] == {'facing': 'north'}


# ── _rect_cells / _ring_clockwise ───────────────────────────────────────
def test_rect_cells_solid_is_the_full_grid():
    assert set(mod._rect_cells(0, 2, 0, 2, hollow=False)) == {(x, z) for x in range(3) for z in range(3)}


def test_rect_cells_hollow_drops_the_interior_and_sorts_bounds():
    # reversed bounds are normalised, so the shell is the same either way
    assert set(mod._rect_cells(2, 0, 2, 0)) == set(mod._rect_cells(0, 2, 0, 2))
    assert (1, 1) not in set(mod._rect_cells(0, 2, 0, 2))


def test_ring_clockwise_walks_one_closed_adjacent_circuit():
    cells = mod._ring_clockwise(0, 2, 0, 2)
    assert len(cells) == 8
    assert (1, 1) not in cells
    closed = cells + [cells[0]]
    for (ax, az), (bx, bz) in zip(closed, closed[1:]):
        assert abs(ax - bx) + abs(az - bz) == 1


def test_ring_clockwise_degenerate_single_cell():
    assert mod._ring_clockwise(4, 4, 7, 7) == [(4, 7)]


# ── _pattern_mat ────────────────────────────────────────────────────────
def test_pattern_mat_without_materials_is_none():
    assert mod._pattern_mat('bands', 0, 65, 0, []) is None
    assert mod._pattern_mat('bands', 0, 65, 0, None) is None


@pytest.mark.parametrize(
    ('pattern', 'x', 'y', 'z', 'expected'),
    [
        (None, 0, 65, 0, 'a'),
        ('solid', 5, 70, 5, 'a'),
        ('bands', 0, 63, 0, 'a'),
        ('bands', 0, 64, 0, 'b'),
        ('bands', 0, 65, 0, 'c'),
        ('checker', 0, 65, 0, 'a'),
        ('checker', 1, 65, 0, 'b'),
        ('checker', 1, 65, 1, 'c'),
        ('checker', 2, 65, 1, 'a'),
        ('gradient', 0, 64, 0, 'a'),
        ('gradient', 0, 69, 0, 'b'),
        ('gradient', 0, 99, 0, 'c'),
        ('unknown-pattern', 3, 71, 4, 'a'),
    ],
)
def test_pattern_mat_table(pattern, x, y, z, expected):
    assert mod._pattern_mat(pattern, x, y, z, ['a', 'b', 'c']) == expected


def test_pattern_mat_single_material_ignores_the_pattern():
    assert mod._pattern_mat('checker', 1, 65, 0, ['only']) == 'only'


def test_pattern_mat_noise_is_deterministic_and_in_range():
    mats = ['a', 'b', 'c']
    picks = {mod._pattern_mat('noise', x, 65, z, mats) for x in range(-4, 5) for z in range(-4, 5)}
    assert picks <= set(mats)
    assert mod._pattern_mat('noise', -3, 66, 7, mats) == mod._pattern_mat('noise', -3, 66, 7, mats)
    assert len(picks) > 1  # the hash really does spread


# ── op_box ──────────────────────────────────────────────────────────────
def test_op_box_hollow_shell_has_no_interior_and_one_circuit_per_floor():
    out = mod.op_box({'x0': 0, 'x1': 3, 'z0': 0, 'z1': 3, 'y0': 65, 'y1': 66})
    assert len(out) == 2 * 12  # 12 perimeter cells, two floors
    assert all(b['kind'] == 'wall' and b['mat'] == 'stone_bricks' for b in out)
    assert not any((b['x'], b['z']) in {(1, 1), (1, 2), (2, 1), (2, 2)} for b in out)
    assert {b['y'] for b in out} == {65, 66}


def test_op_box_solid_fills_every_cell_and_normalises_reversed_y():
    out = mod.op_box({'x0': 0, 'x1': 2, 'z0': 0, 'z1': 2, 'y0': 66, 'y1': 65, 'hollow': False})
    assert len(out) == 2 * 9
    assert (1, 65, 1) in _cells(out)


def test_op_box_corner_mat_wins_on_the_four_corners():
    out = mod.op_box(
        {
            'x0': 0,
            'x1': 3,
            'z0': 0,
            'z1': 3,
            'y0': 65,
            'y1': 65,
            'mat': 'bricks',
            'corner_mat': 'log',
            'kind': 'frame',
        }
    )
    corners = {(b['x'], b['z']) for b in out if b['mat'] == 'log'}
    assert corners == {(0, 0), (0, 3), (3, 0), (3, 3)}
    assert all(b['kind'] == 'frame' for b in out)


def test_op_box_pattern_alternates_materials_per_course():
    out = mod.op_box(
        {
            'x0': 0,
            'x1': 2,
            'z0': 0,
            'z1': 2,
            'y0': 65,
            'y1': 66,
            'mats': ['a', 'b'],
            'pattern': 'bands',
        }
    )
    assert {b['mat'] for b in out if b['y'] == 65} == {'b'}
    assert {b['mat'] for b in out if b['y'] == 66} == {'a'}


def test_op_box_skips_cells_whose_material_is_falsy():
    assert mod.op_box({'x0': 0, 'x1': 2, 'z0': 0, 'z1': 2, 'y0': 65, 'y1': 65, 'mats': [None]}) == []


def test_op_box_single_cell_footprint():
    out = mod.op_box({'x0': 5, 'x1': 5, 'z0': 5, 'z1': 5, 'y0': 65, 'y1': 65})
    assert _cells(out) == {(5, 65, 5)}


# ── op_fill / op_erase ──────────────────────────────────────────────────
def test_op_fill_is_a_solid_cuboid_with_sorted_bounds():
    out = mod.op_fill({'x0': 2, 'x1': 0, 'y0': 66, 'y1': 65, 'z0': 1, 'z1': 0, 'mat': 'dirt'})
    assert len(out) == 3 * 2 * 2
    assert all(b['kind'] == 'fill' and b['mat'] == 'dirt' for b in out)
    assert (0, 65, 0) in _cells(out)


def test_op_fill_degenerate_single_cell_and_custom_kind():
    out = mod.op_fill({'x0': 1, 'x1': 1, 'y0': 2, 'y1': 2, 'z0': 3, 'z1': 3, 'kind': 'floor'})
    assert len(out) == 1
    assert out[0]['kind'] == 'floor' and out[0]['mat'] == 'stone_bricks'


def test_op_erase_paints_the_air_sentinel():
    out = mod.op_erase({'x0': 0, 'x1': 1, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0, 'mat': 'ignored'})
    assert len(out) == 2
    assert all(b['mat'] == mod.AIR and b['kind'] == 'erase' for b in out)


# ── op_cylinder ─────────────────────────────────────────────────────────
def test_op_cylinder_hollow_ring_is_annular_and_clips_the_corners():
    out = mod.op_cylinder({'cx': 0, 'cz': 0, 'r': 3, 'y0': 65, 'y1': 66})
    cells = {(b['x'], b['z']) for b in out}
    assert (0, 0) not in cells  # hollow: the centre is skipped
    assert (3, 3) not in cells  # outside the radius: clipped
    assert (3, 0) in cells
    assert all(math.dist(c, (0, 0)) <= 3.5 for c in cells)
    assert {b['y'] for b in out} == {65, 66}


def test_op_cylinder_solid_is_a_filled_disc_stack():
    out = mod.op_cylinder({'cx': 0, 'cz': 0, 'r': 2, 'y0': 65, 'y1': 65, 'hollow': False})
    cells = {(b['x'], b['z']) for b in out}
    assert (0, 0) in cells
    assert (1, 1) in cells


def test_op_cylinder_radius_is_clamped_to_one_and_y_is_sorted():
    out = mod.op_cylinder({'cx': 4, 'cz': 4, 'r': 0, 'y0': 66, 'y1': 65, 'hollow': False})
    assert {b['y'] for b in out} == {65, 66}
    assert (4, 65, 4) in _cells(out)


def test_op_cylinder_lays_each_ring_in_angular_order():
    out = mod.op_cylinder({'cx': 0, 'cz': 0, 'r': 3, 'y0': 65, 'y1': 65})
    angles = [math.atan2(b['z'], b['x']) for b in out]
    assert angles == sorted(angles)


def test_op_cylinder_skips_cells_whose_material_is_falsy():
    assert mod.op_cylinder({'cx': 0, 'cz': 0, 'r': 2, 'y0': 65, 'y1': 65, 'mats': [None]}) == []


# ── op_pyramid ──────────────────────────────────────────────────────────
def test_op_pyramid_solid_tiers_inset_by_one_per_level():
    out = mod.op_pyramid({'cx': 0, 'cz': 0, 'half': 2, 'y0': 65})
    by_level = {}
    for b in out:
        by_level.setdefault(b['y'], 0)
        by_level[b['y']] += 1
    assert by_level == {65: 25, 66: 9, 67: 1}
    assert all(b['kind'] == 'core' for b in out)
    assert {b['mat'] for b in out} == {'sandstone'}


def test_op_pyramid_hollow_keeps_only_each_tiers_rim():
    out = mod.op_pyramid({'cx': 0, 'cz': 0, 'half': 2, 'y0': 65, 'hollow': True})
    assert (0, 65, 0) not in _cells(out)  # carved out
    assert (0, 67, 0) in _cells(out)  # the apex tier has h == 0 and stays
    assert (2, 65, 0) in _cells(out)


def test_op_pyramid_cycles_materials_per_tier_and_clamps_half():
    # half is clamped to 1, so even a degenerate request keeps a base and an apex
    out = mod.op_pyramid({'cx': 0, 'cz': 0, 'half': 0, 'mats': ['a', 'b']})
    assert {b['mat'] for b in out if b['y'] == 65} == {'a'}
    assert [(b['y'], b['mat']) for b in out if b['y'] == 66] == [(66, 'b')]
    assert len([b for b in out if b['y'] == 65]) == 9


# ── op_gable_roof ───────────────────────────────────────────────────────
def test_op_gable_roof_rises_to_a_single_ridge_course():
    out = mod.op_gable_roof({'x0': 0, 'x1': 4, 'z0': 0, 'z1': 1, 'y0': 70, 'overhang': 0})
    per_course = {}
    for b in out:
        per_course.setdefault(b['y'], set()).add(b['x'])
    assert per_course[70] == {0, 4}
    assert per_course[71] == {1, 3}
    assert per_course[72] == {2}  # the ridge is one block wide
    assert all(b['kind'] == 'roof' and b['mat'] == 'spruce_planks' for b in out)


def test_op_gable_roof_overhang_extends_past_the_gable_ends():
    out = mod.op_gable_roof({'x0': 0, 'x1': 2, 'z0': 0, 'z1': 0, 'y0': 70})
    assert {b['z'] for b in out} == {-1, 0, 1}


def test_op_gable_roof_odd_span_keeps_two_ridge_slopes():
    out = mod.op_gable_roof({'x0': 0, 'x1': 3, 'z0': 0, 'z1': 0, 'y0': 70, 'overhang': 0})
    assert {(b['x'], b['y']) for b in out} == {(0, 70), (3, 70), (1, 71), (2, 71)}


def test_op_gable_roof_flat_footprint_is_one_course():
    out = mod.op_gable_roof({'x0': 5, 'x1': 5, 'z0': 2, 'z1': 2, 'y0': 70, 'overhang': 0})
    assert _cells(out) == {(5, 70, 2)}


# ── op_stair_ring ───────────────────────────────────────────────────────
def test_op_stair_ring_climbs_at_most_one_block_per_cell():
    out = mod.op_stair_ring({'x0': 0, 'x1': 6, 'z0': 0, 'z1': 6, 'ybase': 65, 'ytop': 70})
    tops = {}
    for b in out:
        key = (b['x'], b['z'])
        tops[key] = max(tops.get(key, b['y']), b['y'])
    cells = mod._ring_clockwise(1, 5, 1, 5)
    heights = [tops[c] for c in cells]
    assert heights[0] == 65 and heights[-1] == 70
    assert all(abs(b - a) <= 1 for a, b in zip(heights, heights[1:]))
    assert all(b['kind'] == 'stair' and b['mat'] == 'cobblestone' for b in out)


def test_op_stair_ring_is_emitted_layer_by_layer():
    out = mod.op_stair_ring({'x0': 0, 'x1': 6, 'z0': 0, 'z1': 6, 'ybase': 65, 'ytop': 70})
    ys = [b['y'] for b in out]
    assert ys == sorted(ys)


def test_op_stair_ring_with_no_room_after_the_inset_emits_nothing():
    assert mod.op_stair_ring({'x0': 0, 'x1': 1, 'z0': 0, 'z1': 1, 'ybase': 65, 'ytop': 70}) == []


def test_op_stair_ring_single_cell_ring_still_rises():
    out = mod.op_stair_ring({'x0': 0, 'x1': 2, 'z0': 0, 'z1': 2, 'ybase': 65, 'ytop': 67, 'mat': 'oak_stairs'})
    assert _cells(out) == {(1, 65, 1)}
    assert out[0]['mat'] == 'oak_stairs'


# ── op_battlements ──────────────────────────────────────────────────────
def test_op_battlements_alternates_merlons_around_the_wall_top():
    out = mod.op_battlements({'x0': 0, 'x1': 3, 'z0': 0, 'z1': 3, 'y': 71})
    assert {b['y'] for b in out} == {71}
    assert all((b['x'] + b['z']) % 2 == 0 for b in out)
    assert all(b['kind'] == 'battlement' and b['mat'] == 'chiseled_stone_bricks' for b in out)
    assert 0 < len(out) < len(mod._ring_clockwise(0, 3, 0, 3))


def test_op_battlements_every_one_is_a_solid_crown():
    ring = mod._ring_clockwise(0, 3, 0, 3)
    out = mod.op_battlements({'x0': 0, 'x1': 3, 'z0': 0, 'z1': 3, 'y': 71, 'every': 0, 'mat': 'bricks'})
    assert len(out) == len(ring)
    assert all(b['mat'] == 'bricks' for b in out)


# ── op_stairs_line / op_slab_deck ───────────────────────────────────────
def test_op_stairs_line_states_every_block():
    out = mod.op_stairs_line({'x0': 0, 'x1': 2, 'z0': 0, 'z1': 1, 'y': 71})
    assert len(out) == 6
    assert all(b['state'] == {'facing': 'north', 'half': 'bottom'} for b in out)
    assert all(b['kind'] == 'trim' and b['mat'] == 'stone_brick_stairs' for b in out)


def test_op_stairs_line_honours_facing_and_half():
    out = mod.op_stairs_line({'x0': 0, 'x1': 0, 'z0': 0, 'z1': 0, 'y': 71, 'facing': 'east', 'half': 'top'})
    assert out[0]['state'] == {'facing': 'east', 'half': 'top'}


def test_op_slab_deck_covers_the_footprint():
    out = mod.op_slab_deck({'x0': 0, 'x1': 1, 'z0': 0, 'z1': 2, 'y': 71, 'type': 'top', 'mat': 'oak_slab'})
    assert len(out) == 6
    assert all(b['state'] == {'type': 'top'} and b['kind'] == 'deck' for b in out)
    assert all(b['mat'] == 'oak_slab' for b in out)


def test_op_slab_deck_defaults():
    out = mod.op_slab_deck({'x0': 0, 'x1': 0, 'z0': 0, 'z1': 0, 'y': 71})
    assert out[0]['mat'] == 'stone_brick_slab' and out[0]['state'] == {'type': 'bottom'}


# ── op_door / op_windows / op_voxels ────────────────────────────────────
def test_op_door_emits_both_halves():
    out = mod.op_door({'x': 0, 'y': 65, 'z': -3})
    assert [b['y'] for b in out] == [65, 66]
    assert [b['state']['half'] for b in out] == ['lower', 'upper']
    assert all(b['mat'] == 'oak_door' and b['kind'] == 'door' for b in out)
    assert all(b['state']['facing'] == 'south' and b['state']['hinge'] == 'left' for b in out)


def test_op_door_honours_facing_and_hinge():
    out = mod.op_door({'x': 1, 'y': 65, 'z': 2, 'mat': 'iron_door', 'facing': 'west', 'hinge': 'right'})
    assert all(b['state']['facing'] == 'west' and b['state']['hinge'] == 'right' for b in out)
    assert all(b['mat'] == 'iron_door' for b in out)


def test_op_windows_crosses_cells_with_heights():
    out = mod.op_windows({'cells': [[-3, -6], [3, -6]], 'ys': [67, 68]})
    assert _cells(out) == {(-3, 67, -6), (-3, 68, -6), (3, 67, -6), (3, 68, -6)}
    assert all(b['kind'] == 'window' and b['mat'] == 'glass' for b in out)


def test_op_windows_falls_back_to_a_single_height():
    out = mod.op_windows({'cells': [[0, 0]], 'y': 70, 'mat': 'glass_pane'})
    assert _cells(out) == {(0, 70, 0)}
    assert out[0]['mat'] == 'glass_pane'


def test_op_windows_default_height_and_no_cells():
    assert mod.op_windows({}) == []
    assert mod.op_windows({'cells': [[1, 2]]})[0]['y'] == 67


def test_op_voxels_passes_raw_cells_through():
    out = mod.op_voxels(
        {
            'blocks': [
                {'x': 0, 'y': 65, 'z': 0},
                {'x': 1, 'y': 65, 'z': 0, 'mat': 'glass', 'kind': 'window', 'state': {'facing': 'north'}},
                {'x': 2, 'y': 65, 'z': 0, 'state': {}},
            ]
        }
    )
    assert out[0]['mat'] == 'stone_bricks' and out[0]['kind'] == 'voxel' and 'state' not in out[0]
    assert out[1]['mat'] == 'glass' and out[1]['state'] == {'facing': 'north'}
    assert 'state' not in out[2]  # an empty state is dropped


def test_op_voxels_without_blocks():
    assert mod.op_voxels({}) == []


# ── the OPS registry ────────────────────────────────────────────────────
def test_ops_registry_matches_the_schema():
    assert set(mod.OPS) == set(mod.OP_SCHEMA)
    assert all(callable(fn) for fn in mod.OPS.values())


# ── bake ────────────────────────────────────────────────────────────────
def test_bake_of_nothing_is_empty():
    assert mod.bake(None) == []
    assert mod.bake([]) == []


def test_bake_skips_unknown_and_muted_ops():
    recipe = [
        {'op': 'no_such_op', 'params': {}},
        {'op': 'fill', 'muted': True, 'params': {'x0': 0, 'x1': 0, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0}},
        {'op': 'door', 'params': {'x': 0, 'y': 65, 'z': 0}},
    ]
    assert len(mod.bake(recipe)) == 2


def test_bake_lets_a_later_op_overwrite_a_cell_in_place():
    recipe = [
        {'op': 'fill', 'params': {'x0': 0, 'x1': 1, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0, 'mat': 'dirt'}},
        {'op': 'fill', 'params': {'x0': 1, 'x1': 1, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0, 'mat': 'gold_block'}},
    ]
    out = mod.bake(recipe)
    assert [(b['x'], b['mat']) for b in out] == [(0, 'dirt'), (1, 'gold_block')]


def test_bake_erase_removes_earlier_cells_and_repaint_moves_to_the_end():
    recipe = [
        {'op': 'fill', 'params': {'x0': 0, 'x1': 2, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0, 'mat': 'dirt'}},
        {'op': 'erase', 'params': {'x0': 0, 'x1': 0, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0}},
    ]
    out = mod.bake(recipe)
    assert _cells(out) == {(1, 65, 0), (2, 65, 0)}

    recipe.append(
        {'op': 'fill', 'params': {'x0': 0, 'x1': 0, 'y0': 65, 'y1': 65, 'z0': 0, 'z1': 0, 'mat': 'oak_planks'}}
    )
    out = mod.bake(recipe)
    assert [(b['x'], b['mat']) for b in out] == [(1, 'dirt'), (2, 'dirt'), (0, 'oak_planks')]


def test_bake_erasing_an_empty_cell_is_harmless():
    recipe = [{'op': 'erase', 'params': {'x0': 9, 'x1': 9, 'y0': 65, 'y1': 65, 'z0': 9, 'z1': 9}}]
    assert mod.bake(recipe) == []


def test_bake_defaults_missing_params_to_an_empty_dict():
    # no 'params' key at all: the op is still called, with {}
    assert mod.bake([{'op': 'windows'}, {'op': 'voxels'}]) == []


def test_bake_wraps_an_op_failure_with_the_op_name():
    with pytest.raises(ValueError, match=r"op 'fill' failed:"):
        mod.bake([{'op': 'fill', 'params': {'x0': 0}}])


def test_bake_is_deterministic():
    recipe = [
        {'op': 'box', 'params': {'x0': 0, 'x1': 3, 'z0': 0, 'z1': 3, 'y0': 65, 'y1': 67, 'pattern': 'noise'}},
        {'op': 'door', 'params': {'x': 0, 'y': 65, 'z': 1}},
    ]
    assert mod.bake(recipe) == mod.bake(recipe)


def test_bake_a_whole_recipe_of_every_op():
    recipe = [
        {'op': name, 'params': params}
        for name, params in [
            ('box', {'x0': 0, 'x1': 4, 'z0': 0, 'z1': 4, 'y0': 65, 'y1': 68}),
            ('fill', {'x0': 0, 'x1': 4, 'y0': 64, 'y1': 64, 'z0': 0, 'z1': 4}),
            ('cylinder', {'cx': 10, 'cz': 10, 'r': 2, 'y0': 65, 'y1': 67}),
            ('pyramid', {'cx': 20, 'cz': 20, 'half': 2, 'y0': 65}),
            ('gable_roof', {'x0': 0, 'x1': 4, 'z0': 0, 'z1': 4, 'y0': 69}),
            ('stair_ring', {'x0': 0, 'x1': 4, 'z0': 0, 'z1': 4, 'ybase': 65, 'ytop': 68}),
            ('battlements', {'x0': 0, 'x1': 4, 'z0': 0, 'z1': 4, 'y': 69}),
            ('stairs_line', {'x0': 0, 'x1': 4, 'z0': 0, 'z1': 0, 'y': 69}),
            ('slab_deck', {'x0': 1, 'x1': 3, 'z0': 1, 'z1': 3, 'y': 69}),
            ('door', {'x': 2, 'y': 65, 'z': 0}),
            ('windows', {'cells': [[0, 2], [4, 2]], 'ys': [66]}),
            ('voxels', {'blocks': [{'x': 30, 'y': 65, 'z': 30}]}),
            ('erase', {'x0': 2, 'x1': 2, 'y0': 65, 'y1': 66, 'z0': 0, 'z1': 0}),
        ]
    ]
    out = mod.bake(recipe)
    assert len(out) == len(_cells(out))  # one block per cell
    assert not any(b['mat'] == mod.AIR for b in out)
    assert (2, 65, 0) not in _cells(out)  # the doorway was carved back out


# ── describe ────────────────────────────────────────────────────────────
def test_describe_hides_internal_ops_and_names_each_entry():
    cat = mod.describe()
    assert 'voxels' not in cat
    assert set(cat) == {name for name, meta in mod.OP_SCHEMA.items() if not meta.get('hidden')}
    for name, meta in cat.items():
        assert meta['name'] == name
        assert meta['label'] and meta['params']


def test_describe_params_are_well_formed_and_the_defaults_bake():
    for name, meta in mod.describe().items():
        params = {spec['k']: spec['d'] for spec in meta['params']}
        for spec in meta['params']:
            assert spec['t']
            if spec['t'] == 'enum':
                assert spec['d'] in spec['opts']
        assert mod.OPS[name](params), name
