<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# GATES.md — every design check the Architecture Studio assistant runs

Written 2026-09-16 by the `arch-quality-gates-1-clash-openings-walk` tree.

`design_check` calls `design_rules.run_checks(d)`, which calls the `DESIGN_CHECKS`
list of every loaded family in `arch_assistant_ext/`. Each check returns a list of

```python
{'sev': 'error' | 'warn' | 'info', 'code': '<family>_<rule>', 'text': '<id> <what> — <the fix, naming the tool>'}
```

Three rules hold for every row in this file:

1. **A check never raises.** Every family wraps its own checks and turns an
   exception into one `info` finding (`*_check_error`, `*_check_failed`,
   `*_rules_error`, `clash_error`, `walk_error`, `open_check_error`,
   `deck_check_failed`, `roof_check_failed`, `fac_check_failed`). A drawing the
   family cannot read is reported as *not checked*, never as clean.
2. **`error` blocks `done()`.** `warn` and `info` do not. The turn loop runs
   `design_check` before it will hand the job over.
3. **Every text names the tool call that fixes it.** That is the column below,
   and it is what makes the finding actionable to the model rather than to a human.

The **A/B proof** column names the test file and the check name that proves the
pair: the defect fires the code, and the corrected drawing is silent. Where one
test name is given it is the "fires" half and its sibling in the same file (same
letter, `/B` or "silent") is the "silent" half.

Codes marked `*` are folding/erroring `info` rows, not rules: they cap a family's
output (`*_more`) or report that the family could not read the drawing.

---

## building_program

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `program` | error / warn | a required item of the declared building programme is not built (error); an optional one is not (warn) | the item's own how-line — `program_status()` prints the tool call for each | `test_building_program.py` :: *missing required items are ERRORS on the gate* / *with every runnable how-line built, only the skipped items hold the gate* |

## circulation_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `circ_no_stair` | error | a storey with a slab that no stair reaches | `add_stair(cell, from_storey=0, to_storey=N, kind="u")` | `test_circulation_rules.py` :: *and no stair error with it* |
| `circ_deck_no_stair` | error | an occupied roof deck (pool, furniture — not bare plant) with no stair to it | `add_stair(cell, 0, storeys)` — it climbs to the deck and builds the head house | `test_circulation_rules.py` :: *the deck finding names the pool and the tower* / *the same pool with a stair to the deck is silent* |
| `circ_no_lift` | warn | a building of 3 storeys or more with no lift | `add_elevator(cell, from_storey=0, to_storey=N)` | `test_circulation_rules.py` :: *and no stair error with it* |
| `circ_lift_partial` | error | a shaft that serves only part of the slab range | `add_elevator(cell, 0, storeys)` | `test_circulation_rules.py` :: *a lift to storey 10 of a 20-storey tower is an error* |
| `circ_flight` | error | one stair record climbing more than one storey, or a flight over `MAX_FLIGHT` steps | `add_stair` draws one record per storey | `test_circulation_rules.py` :: *the 285-step stair is a flight-length error* / *per-storey records are never a flight-length error* |
| `circ_stair_guard` | error | a stair record with no rails | `add_stair(..., rails=1)`, or set `p.rails` on the record | `test_circulation_rules.py` :: *rails=0 on one record is a guarding error* / *add_stair draws rails, so guarding is silent* |
| `circ_landing_guard` | error | a stair landing with no wall, railing or parapet within `LANDING_TOL` of any of its four edges | draw a railing along the open edges | `test_circulation_rules.py` :: *the tool-built tower + lift reports nothing at all* (silent half; the guard family is exercised by `circ_stair_guard`) |
| `circ_head_house` | error | a stair arriving in the open on a deck | `add_stair(cell, 0, storeys)` builds the head house over it | `test_circulation_rules.py` :: *the head house finding says it arrives in the open* / *add_stair built the head house, so that is silent* |
| `circ_core_clash` | error | a stair and a lift shaft sharing the same plan on a storey | move one — `add_elevator` refuses this now | `test_circulation_rules.py` :: *the finding measures the 0.62 m the run drew* |
| `circ_stair_approach` | error | something standing in the `APPROACH_M` (1.2 m) of floor at the foot of a stair | move it or move the stair | `test_circulation_rules.py` :: *the approach finding names the stair, the partition and the 1.2 m* / *the east shaft does not: the foot is on the -X side only* |
| `circ_landing_floor` | error (+info) | a flight arriving over a void — nothing to land on | `cut_floor_opening` only over the flights | `test_circulation_rules.py` :: *a flight arriving over the void is a landing error* / *the same stair with the tools' opening is silent* |
| `circ_headroom` | error (+info) | a slab written across the headroom over a flight | move the slab or cut the opening | `test_circulation_rules.py` :: *a slab written over the flight is a headroom error* / *the tools' stair is silent* |
| `circ_enclosure` | sev-by-count (+info) | a stair with N of its 4 plan sides open to the floor | `add_room` around it, or accept (fire separation) | `test_circulation_rules.py` :: *the enclosure finding names the storey, the open sides and the fix* / *the tool-built tower + lift reports nothing at all* |
| `circ_overrun` | error (+info) | a shaft serving a deck but stopping under it — no `OVERRUN_MIN` motor-room overrun | `add_elevator(cell, 0, storeys)` draws it 1.5 m over the deck | `test_circulation_rules.py` :: *a 54.0 m shaft serving a 54.3 m deck is an overrun error* / *so the overrun check is silent on it* |
| `circ_shaft_in_water` | error (+info) | a core standing in pool water | `add_infinity_pool(cell_from, cell_to)` clear of it | `test_circulation_rules.py` :: *a lift shaft under the water is an error* / *a pool clear of both cores is silent* |
| `circ_lift_landing` | error (+info) | something in front of a shaft's doors on a served storey | move it — the finding names the shaft, the storey and the gap | `test_circulation_rules.py` :: *the landing finding names the shaft, the storey, the partition and the gap* / *the tool-built tower + lift reports nothing at all* |
| `circ_more` * | info | more than `MAX_FINDINGS` circulation findings — the rest are folded onto one line | — | `test_circulation_rules.py` :: *no check raises on a drawing with no envelope at all* |

## clash_rules

`clash_rules` does not hold a literal code list. It builds `clash_{subjectRole}_{objectRole}`
from `PAIRS` (clash_rules.py:150), and the value of that entry is **the role that
should move** — which is what the finding text tells the model to move. All eleven
are `error`.

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `clash_core_wall` | error | a wall or partition through a stair / lift shaft | move the **wall** (`move` / `delete`) | `test_clash_rules.py` :: *(a) a partition across the stair plan is a clash_core_wall* / *(a-C) a wall on the core edge is touching, not a clash* |
| `clash_core_column` | error | a column through a core | move the **column** | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* (the pair matrix is proved as a whole) |
| `clash_furniture_wall` | error | furniture straddling a wall | move the **furniture** | `test_clash_rules.py` :: *(b) a sofa straddling wall o2 is a clash_furniture_wall* |
| `clash_furniture_column` | error | furniture through a column | move the **furniture** | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* |
| `clash_furniture_core` | error | furniture in a stair or shaft plan | move the **furniture** | `test_clash_rules.py` :: *(e-B) the built room does not clash with the stair* |
| `clash_furniture_water` | error | a lounger / seat written into the pool water | move the **furniture** off the water | `test_clash_rules.py` :: *(c) a sun_lounger written into the water rect is a clash_furniture_water* / *(c-B) the loungers add_infinity_pool puts on the deck are silent* |
| `clash_column_water` | error | a column standing in the water | move the **column** | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* |
| `clash_tree_wall` | error | a tree crown through a wall | move the **tree** | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* |
| `clash_tree_column` | error | a tree through a column | move the **tree** | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* |
| `clash_tree_canopy` | error | a tree through a canopy / porte-cochère | move the **tree** | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* |
| `clash_wall_water` | error | a party wall standing in a pool basin — the tank/plate seam under a roof pool | `delete` the walls the finding names, or raise the pool | `test_tower_recipe.py` :: *clash_wall_water names the party walls under the pool tank* ; `test_tower_replay.py` :: *R9 clash_wall_water names the storey-19 party walls under the pool tank* |
| `clash_more` * | info | more than 8 findings for one role pair | — | `test_clash_rules.py` :: *(d) no role pair exceeds the 8-finding cap* |
| `clash_error` * | info | the clash check could not run — **nothing is claimed about interference** | — | — |

## deck_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `deck_pool_core` | error | a pool closer than `CORE_CLEAR` to a stair, shaft or head house — you cannot walk round the core | `add_infinity_pool(cell_from, cell_to)` further off | `test_deck_rules.py` :: *(a) the same pool drawn by hand at FD95..FM100 -> deck_pool_core* / *(a) ...the error gives the gap, names the core and names add_infinity_pool* |
| `deck_walkway` | error | under `WALK_MIN` (1.2 m) between the coping and a non-weir deck edge | `add_infinity_pool(cell_from, cell_to)` with fewer cells | `test_deck_rules.py` :: *(b) the same pool 1 m further west (1.50 m of walkway) -> silent* |
| `deck_weir_edge` | error | the infinity trough hanging past the facade, **or** set back more than `WEIR_INSET` from the deck edge | `add_infinity_pool(cell_from, cell_to)` reaching the edge, inside the plate | `test_deck_rules.py` :: *(c) a pool hanging 0.20 m past the facade -> deck_weir_edge naming the overhang* / *(c) the weir where add_infinity_pool puts it (0.57 m, INF_INSET) -> silent* |
| `deck_tank_clash` | error / warn | the pool's plant zone in the plan of a core (error); the basin cutting a corridor zone below (warn) | `move("<zone id>", dx_cells=…, dz_cells=…)`, or raise the pool | `test_deck_rules.py` :: *(i) the 2026-09-11 baseline is untouched* |
| `deck_lounger_placement` | warn | a seat in the weir strip between the pool and the deck edge, or facing away from the view | `move("<id>", dz_cells=…)` behind the pool; turn it to the weir `ry` | `test_deck_rules.py` :: *(f) a lounger 0.30 m off the water -> deck_lounger_placement* / *(f) the same lounger north of the pool, 1 m off the water, facing the south view -> silent* |
| `deck_plant_side` | error | rooftop plant on the view side of the pool, or under `PLANT_CLEAR` from it | `move(…)`, or `delete` + `add_rooftop_plant(group=…, kinds=[…])` — **which takes no side argument** | `test_deck_rules.py` :: *(d) north of the pool but only 0.6 m off the water -> deck_plant_side* / *(d) the same unit north of the pool, 3.6 m clear -> silent* |
| `deck_guard_all` | error | an occupied deck edge guarded over less than `GUARD_COVER` of its length | `add_parapet("<group>", height=1.1)` | `test_deck_rules.py` :: *(g) on the tower finish_rules already names the east and west deck edges* / *(g) ...and the south edge is silent* |
| `deck_headhouse_door` | error | a head house with no door — the stair arrives in a sealed box | `add_opening(group="<head house>", side=…, storey=…, kind="door")` | `test_deck_rules.py` :: *(e) the tower head house add_stair builds HAS a door -> silent* / *(e) add_opening puts a door back and the check falls silent again* |
| `deck_stair_arrival` | error | a stair landing on the deck with no deck under the landing | `add_slab` / `add_roof` over that cell, or `add_stair(cell, 0, N)` onto the deck | `test_deck_rules.py` :: *(i) ...one error: stair o247 arrives at 54.30 m over the lift void* / *(h) on the tower the top stair lands on roof o385 at 54.3 m -> silent* |
| `deck_more` * | info | more than `MAX_FINDINGS` deck findings; errors are never pushed out by warns | — | `test_deck_rules.py` :: *(j) errors are never pushed out of the cap by warns* |
| `deck_check_failed` * | info | a deck check could not read the drawing | — | `test_deck_rules.py` :: *(i) design_check carries the new codes through the registry* |

## design_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `floors` | error | storeys with walls but no floor slab | `add_slab` per storey — `draw_box` makes them by default; never `slabs=false` on a habitable building | `test_design_rules.py` :: *a 4-storey box drawn with slabs=false is a floors ERROR naming the storeys* / *old tower: floors present (no floors finding)* |
| `buried` | sev-by-kind | objects standing INSIDE a deck whose top is above them | `move(which=[…], dy_storeys=…)`, or delete and redraw without `base_height` | `test_design_rules.py` :: *old tower: pool + lounger buried in the roof is an ERROR naming o101* ; `test_landscape_composer.py` :: *ground_fault calls a sunk record BURIED* |
| `pool_water` | error | the water surface below the deck it sits on — invisible | `add_pool(raised=depth)` (or omit `raised`: auto), or `sunk=true` into a plant storey | `test_design_rules.py` :: *old tower: pool water below the deck is an ERROR* |
| `pool_basin` | warn | the basin hanging into the storey below with no `sunk=true` | `raised=<depth>`, or declare the plant storey | `test_water_leisure.py` :: *(g) add_pool with an infinity edge and no parapet says NO guard in its reply* |
| `pierce` | error | a column running through the plate it should carry | size it to the soffit, or use `add_canopy(columns=N, height=…)` which sizes them | `test_design_rules.py` :: *old tower: colonnade pierces the canopy (ERROR, 4 columns)* / *no pierce finding for the canopy-carried columns* |
| `crowding` | warn | tree pairs merging into one blob | space them a crown apart — `plant_trees` refuses a block too small for its count | `test_design_rules.py` :: *old tower: tree crowding is a WARN naming 6 pairs* |
| `placeholder` | warn | parametric placeholders (sphere-on-a-trunk trees, plain lamp poles) | `plant_trees(model="real")`, `add_street_furniture(model="real")`, `place_asset` | `test_design_rules.py` :: *old tower: placeholders named (7)* / *model="real" …* |
| `axis` | warn | anything on the entrance axis within `AXIS_LEN` | move it at least 6 m off the axis | `test_design_rules.py` :: *old tower: trees on the entrance axis (WARN)* |
| `toy` | warn | stylised low-poly game-kit models in a presentation | use the real, life-size PBR results of `search_assets` | — (kit classification; exercised through `placeholder`) |
| `indoors` | error | outdoor objects standing INSIDE a building on storey 0 — the rooftop set placed without `base_height` | pass `storey=N` or `base_height`, or move them out of the footprint | — (exercised by the tower replay's rooftop set) |
| `check_error` * | info | a registered check raised | — | — |

## envelope_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `envelope_poke` | error | an interior record leaving its group's plan envelope | draw it inside the plan (`direction_deg`) or shorten it | `test_envelope_rules.py` :: *a partition poking 2 m out of its envelope is an error* / *nothing pokes when it fits* |
| `envelope_exterior` | error | an exterior thing in the wrong place: a fire escape inside the plan, a fire escape or canopy touching no facade | `add_fire_escape(group=…, side="north")`; a canopy is carried by a wall | `test_envelope_rules.py` :: *a fire escape in the middle of the plan is an error* / *a canopy 5 m off the wall is an error* |
| `envelope_outside` | error | a record outside every building | move it inside the plan (the finding prints the cells) | `test_envelope_rules.py` :: *a partition 5 m outside the plan is an error* / `test_tower_replay.py` :: *no envelope error survives* |
| `env_facade_partition` | error if glazed else warn | an interior partition drawn on a facade line | move it off the facade; on a glazed storey the facade is the curtain wall | `test_envelope_rules.py` :: *on an opaque storey it is a warning, not an error* |
| `envelope_more` * | info | more than `MAX_FINDINGS` envelope findings | — | — |

## facade_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `fac_pattern` | error | a storey the pattern says is glass that is solid on a side, or vice versa | `add_curtain_wall(walls="<grp>", storeys=[st])` | `test_facade_rules.py` :: *(a) a glass storey gone solid on one side is fac_pattern* / *(a/B) putting the curtain wall back silences it* |
| `fac_bands` | warn | glazed storeys with no floor line on the facade | `add_facade_bands(group=…, kind="string_course", every_n_storeys=1)` | `test_facade_rules.py` :: *the warning names add_facade_bands* / *adding the bands silences it* |
| `fac_parapet_gap` | error | a parapet leaving part of a deck edge open | `add_parapet(group=…, height=1.1, cap=True)` | `test_facade_rules.py` :: *(c) deleting the east parapet is fac_parapet_gap* / *(c) a tower with NO parapet at all is silent (deck_rules owns that)* |
| `fac_wall_height` | error | one wall spanning many storeys, hiding the floors behind it | `set_height(which=[…], metres=<one storey>)` and draw the storeys above | `test_facade_rules.py` :: *(d) a 21.6 m wall beside 2.7 m walls is fac_wall_height* / *(d/B) removing the tall wall silences it* |
| `fac_balcony_place` | error | a balcony with no wall behind it, or on storey 0 | redraw with `add_balconies(walls=…, sides=[…])` | `test_facade_rules.py` :: *(e) a balcony on storey 0 is fac_balcony_place* / *(e) the finding says no wall is behind it* |
| `fac_balcony_align` | warn | balconies stepping sideways between storeys | `add_balconies(walls=…, sides=["<side>"], every_n_storeys=1)` — one call | `test_facade_rules.py` :: *(f) the warning names the side and the storeys* / *(f) balconies drawn in one call line up* |
| `fac_overhang` | warn | something projecting further from the facade than `OVERHANG_M` with nothing carrying it | `set_param(which=[…], key="d", value=<OVERHANG_M>)`, or put columns under it | `test_facade_rules.py` :: *(g) a 7.5 m canopy is a fac_overhang warning* / *(g) a 5 m porte-cochere is not an overhang* |
| `fac_more` * | info | more than `MAX_FINDINGS` facade findings | — | `test_facade_rules.py` :: *every finding has sev/code/text* |
| `fac_check_failed` * | info | facade_rules could not read the drawing — pattern, parapet and balconies **not checked** | — | — |

## finish_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `finish_preset` | error | `mat_*` flat presets left on a luxury job | `apply_finishes()` for all; `set_material(ids, "<id>")`; `set_finish("<grp>", floor_material="<id>")` | `test_finish_schedule.py` :: *apply_finishes reported the counts per kind and what it left alone* ; `test_tower_replay.py` :: *no finish error survives* |
| `finish_unknown_material` | error | a `mat` id that is not in `MATERIALS` at all | `search_materials(query="stone")` lists the library ids | — |
| `finish_deck_guard` | error | an occupied deck edge guarded over too little of its length, above a drop (1.1 m, not 1.0 m) | the finding prints the `add_parapet` / balustrade call | `test_finish_rules.py` :: *run_checks reports the deck-guarding error* ; `test_live_tower_0911.py` :: *with no shaft the guard error RETURNS* / *no finish_deck_guard: the lift shaft guards the roof void edges* |
| `finish_deck_bare` | warn | a luxury roof deck with no loungers, parasols or planters — it reads as a plant deck | `add_beach_set(cells=[four deck cells], storey=N)` | — |
| `finish_canopy_mixed` * | info | a canopy whose columns are a different material from its fascia | `add_canopy(..., material=…, column_material=…)` sets both | — |

## finish_schedule

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `finish_dark` | warn (+info fold) | a library material that renders black (luminance under `DARK_LUM`) | `set_finish("<grp>", floor_material="acg_Marble021")`, `apply_finishes()` | `test_finish_schedule.py` :: *the finding names the record, the luminance and ONE tool call* |

## floor_plans

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `credits` | info | assets in the drawing whose licences require attribution | `attributions()` prints them; every export writes them beside the file | `test_floor_plans.py` :: *design_check reports exactly one credits finding* / *a drawing that owes no credits gets NO credits file and no mention* |

## floor_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `floor_empty` | warn | a storey with a slab and nothing laid out on it | `layout_floor(cell_from, cell_to, use=…, storey=…)` | `test_floor_rules.py` :: *the warning folds all nineteen of them onto one line* / *an empty drawing is silent* |
| `part_head_gap` | warn | a partition that stops more than 0.10 m below the slab above (an open strip over the room — 2.5 m lobby partitions under a 2.7 m storey, job 5e7eb915e1f9); silent where no slab sits over the partition | `add_room(..., wall_h=<storey height>)` — the default now runs to the slab underside; or delete and redraw the short ones | `test_floor_rules.py` :: *part_head_gap: a 2.5 m partition under a 2.7 m storey fires (warn)* / *the same partition run to the slab is silent* |
| `floor_partition_core` | error | a partition drawn through a stair or shaft (the check that survives when `clash_rules` is not loaded) | move or delete the partition | `test_floor_rules.py` :: *without clash_rules the partition through the shaft is an error* |
| `floor_unit_door` | error | a unit with no door | `add_opening` on its corridor wall — `layout_floor` draws them | `test_floor_rules.py` :: *the finding names the unit by name and by id* / *every unit the tool drew has its door and its facade* |
| `floor_unit_narrow` | warn | a unit under the minimum width | re-lay the plate with a bigger `unit_w` | `test_floor_rules.py` :: *a 2.5 m unit is a floor_unit_narrow warning* / *the 6.67 m units of the corrected plate are not narrow* |
| `floor_unit_daylight` | error for `DAYLIGHT_ERROR_USES`, else warn | a landlocked unit with no facade (an error for residential, a warning for office) | re-lay the plate so every unit reaches a facade | `test_floor_rules.py` :: *the daylight finding names the unit and says why* / *a landlocked office is only a warning, not an error* |
| `floor_corridor_width` | error | a corridor under the `CORRIDOR_MIN` clear width | `layout_floor(..., corridor_w=1.8)` — `spec("corridor")` | `test_floor_rules.py` :: *the finding states the clear width and the 1.2 m it is under* / *the 1.8 m corridor of the corrected plate is not reported* |
| `floor_corridor_core` | error | the corridor sealed off from the lift or the stair (the check that survives when `walk_rules` is not loaded) | put a door through — `layout_floor` cuts the core doors | `test_floor_rules.py` :: *without walk_rules the sealed landing is a corridor_core error* / *both findings fold all nineteen storeys onto one line each* |
| `floor_repeat_mismatch` | warn | a repeated storey whose records no longer match its source | `repeat_floor(source_storey=…, from_storey=…, to_storey=…)` again | `test_floor_rules.py` :: *half of storey 7 removed is a floor_repeat_mismatch warning* |
| `floor_more` * | info | more than `MAX_FINDINGS` floor findings | — | — |
| `floor_rules_error` * | info | floor_rules could not read the floor plans — the typical-floor checks were **skipped** | — | `test_floor_rules.py` :: *DESIGN_CHECKS exports the one check* |

## object_specs

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `clearance` | sev-from-spec | two records inside each other's declared clearance ring | `move` one of them | `test_object_specs.py` :: *a wall inside the table ring is reported* |
| `undersize` | spec's `severity`, else warn | a record under its kind's dimensional minimum (0.9 m corridor, 1.0 m lift car, a stair too narrow to pass on) | redraw at the spec size — `spec("<kind>")` prints it | `test_object_specs.py` :: *an undersized lift car is an ERROR* / *run_checks now reports a spec finding* |
| `unsupported` | warn | a record standing on nothing | put a slab / deck under it, or set its `y` | `test_object_specs.py` :: *an unsupported object is reported* / *the same table ON a deck is not* ; `test_live_tower_0911.py` :: *no unsupported warning names a stair* |
| `spec_gap` * | info | kinds in the drawing with no spec yet — queued for the offline filler | nothing for you to do | — |

## opening_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `open_orphan` | error | an opening with no wall to sit in | `delete(which=["<id>"])`, or draw the wall | `test_opening_rules.py` :: *(a) the orphan door is an open_orphan ERROR* / *(e) without the cascade the same door IS an open_orphan* |
| `open_off_wall` | error | an opening off the centre of its host, or running past the host's end | `delete` it and `add_opening(group=…, side=…, storey=…, kind=…, width=<fits>)` | `test_opening_rules.py` :: *(b) a 6 m door in a 4 m partition is an open_off_wall ERROR* / *(b/B) back under the head, silent again* |
| `open_headroom` | error | a door under `DOOR_CLEAR` tall | `delete` it and `add_opening(..., height=2.1)` | `test_opening_rules.py` :: *a 2.1 m door is silent* |
| `open_overlap` | error | two holes cutting the same piece of wall | `delete(which=["<id>"])` one of them | `test_opening_rules.py` :: *a window cut across the entrance door is reported, once* / *(a) it also overlaps the entrance door* |
| `open_double_entrance` | error | two entrance doors on one face of a building | keep one — `delete(which=["<id>"])` | `test_opening_rules.py` :: *(c) two doors 3 m apart on the south face is open_double_entrance* |
| `open_nowhere` | warn | a door opening onto nothing — no ground, pad, path or road `STEP_OUT` outside it | `add_road` / `add_object(kind="path")` under the approach, or move the door | `test_opening_rules.py` :: *the warning names the facade and the tool that fixes it* |
| `open_check_error` * | info | check_openings raised | — | `test_opening_rules.py` :: *a check never raises: a broken drawing returns one info finding* |

## entrance_rules

Every `ent_*` code is an `error` except the two marked `warn`. The family emits
through `_cap(out, code, text, sev='error')` (entrance_rules.py:390), so the
default is error and the warns are explicit. The lobby rules only apply to a
`luxury` job or a building of `TALL_STOREYS` or more — a 12 x 9 m house is not
asked for a 10 m lobby.

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `ent_door_width` | error | a front door under `MIN_DOOR_W` on a tall building | `delete` it, then `add_opening(group=…, side=…, storey=0, kind="double_door", width=2.8)` | `test_entrance_rules.py` :: *a 0.9 m door into an 8-storey building is an error* / *a 2.8 m door is silent* |
| `ent_canopy_missing` | error | a luxury entrance with nothing over it | `add_canopy(group=…, side=…, storey=0, width=12, depth=5, height=4.2, columns=4, material="mat_glass")` | `test_entrance_rules.py` :: *a luxury entrance with no canopy is an error* / *a canopy over the door is silent* / *a plain building is not asked for a canopy* |
| `ent_canopy_low` | error | the canopy soffit under the door head + `HEAD_M` | `delete` it and `add_canopy(..., height=<head + HEAD_M + 0.5>)` | `test_entrance_rules.py` :: *a canopy soffit at 2.8 m over a 2.7 m door is an error* / *the 4.2 m soffit of the good build is silent* |
| `ent_canopy_narrow` | **warn** | a canopy narrower than the door + `CANOPY_MARGIN` — it must cover the step out of the car | `add_canopy(width=12)` | `test_entrance_rules.py` :: *a 4 m canopy over a 2.8 m door is a narrowness finding* / *the 12 m canopy of the good build is silent* |
| `ent_column_axis` | error | a column inside the `2 * AXIS_CLEAR_HALF` of clear passage the door needs | `delete(which=["<id>"])` — `add_canopy(columns=4)` carries the plate from its corners | `test_entrance_rules.py` :: *a column planted on the door axis 3 m out is an error* / *none of its columns stands on the door axis* |
| `ent_lamp_canopy` | error | a lamp post under the porte-cochère, or running through the canopy edge | `delete(which=["<id>"])`, or move it `LAMP_NEAR` clear | `test_entrance_rules.py` :: *a lamp standing under the canopy is an error* / *the good build has no lamp under its canopy* |
| `ent_lobby_behind` | error | the door not opening into the lobby — no lobby, or the lobby rect set back from the door | `add_room(cell_from, cell_to, storey=0, name="Lobby")` on the door axis, entrance side ON the facade (`door_side` omitted) | `test_entrance_rules.py` :: *a lobby that is not behind the door is an error* / *the good build opens straight into its lobby* |
| `ent_lobby_size` | error | a lobby under `LOBBY_ACROSS_M` across or `LOBBY_DEEP_M` deep — "a 10 x 3 m room is a corridor with a desk" | `add_room` over a block at least 8 x 6 cells | `test_entrance_rules.py` :: *the finding gives the size and the two minima* / *the 10 x 7 m lobby of the good build is silent* |
| `ent_lobby_fitout` | error | an empty luxury lobby — no reception desk, no seating | `furnish_lobby(cell_from, cell_to, storey=0, entrance_side=…)` | `test_entrance_rules.py` :: *a bare luxury lobby is an error* / *the furnished lobby is silent* |
| `ent_lobby_floor` | **warn** | the lobby floor left in a flat `mat_*` preset | `set_finish(group=…, floor_material="acg_Marble021")` | `test_entrance_rules.py` :: *a bare mat_ slab under a luxury lobby is a floor finding* / *a marble floor is silent* |
| `ent_door_clutter` | error | a second door in the same opening as the entrance | `delete(which=["<id>"])` | `test_entrance_rules.py` :: *a second door 0.8 m from the entrance is an error* / *a second door 4 m away is a second door, not a duplicate* |
| `ent_axis_blocked` | error | something standing on the door axis inside the lobby — a corridor wall across the way in | move or delete it; `build_entrance` lays the lobby on the door's own axis | `test_entrance_rules.py` :: *the finding says how far in it stands* / *an empty drawing is silent* |
| `ent_check_error` * | info | check_entrance_quality raised | — | — |

## roof_kit

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `roof_check_failed` * | info | `build_roof_deck`'s own post-build `design_check` could not run | — | — |

## sightline_rules

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `sightline` | error | a real line of sight from an eye at 1.6 m, 30 / 15 / 8 m out on the entrance axis, passing through a tree crown, hedge, garden wall or van | move the obstacle `OFF_AXIS` (6 m) off the axis, or lower the crown | `test_sightline_rules.py` :: *a low-crowned tree on the axis 10 m out is an ERROR that names it* / *...so the sightline check is silent about it* |
| `approach` | warn | nothing paved reaching the door | `add_road` / `add_path` up to it | `test_sightline_rules.py` :: *a door on bare ground is a WARN* ; `test_building_program.py` :: *real-model lamps satisfy the approach item* |

## slab_voids

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `void_missing` | error | a stair or shaft passing through a slab with no floor opening | `add_stair` cuts them as it draws; for an existing stair `cut_floor_opening("<grp>", storey, …)` | `test_tower_replay.py` :: *the 285-step stair is caught crossing the slabs* ; `test_circulation_rules.py` :: *circulation does NOT repeat the slab_voids crossing check* |
| `void_missing_more` | error | more floors crossed with no opening than the cap prints — one opening per storey crossed | `cut_floor_opening` per storey | `test_slab_voids.py` :: *design_check surfaces it* |

## walk_rules

`walk_rules` flood-fills a walkability raster and sets `f['code']` late, by where
the failed journey was (walk_rules.py:999-1032). The no-path findings are `error`;
only the pinch-point finding is a `warn`.

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `walk_entrance_core` | error | no path from the entrance door to a stair or lift on storey 0 | move the blocker the finding names, or put a door through it (`add_opening`) | `test_walk_rules.py` :: *...and it names the partition, not a wall with a door in it* |
| `walk_storey` | error | on a typical storey, no path out of the core to a room door or to the other core | move the blocker, or `add_opening` | `test_walk_rules.py` :: *layout_floor leaves the corridor sealed off from the core* / *removing it clears storey 5 again* |
| `walk_deck` | error | no path from the head house door to the pool or the loungers | move the blocker, or `add_opening` | `test_walk_rules.py` :: *...and it reports the pool AND the loungers* |
| `walk_narrow` | warn | the only route runs through a gap under `BODY_M` | widen it or move what narrows it | `test_walk_rules.py` :: *storey 0 is a width warning, not an error* / *every finding names a record and a tool* |
| `walk_more` * | info | more storeys with the same walking problem than the cap prints | — | `test_walk_rules.py` :: *storey 0 is a width warning, not an error* |
| `walk_error` * | info | the walk check could not run — **no walking claim is made** | — | — |

## water_leisure

| code | severity | what it catches | the tool call that fixes it | A/B proof |
|---|---|---|---|---|
| `inf_steps` | error | the entry steps on the infinity edge — a drop into the trough | `steps="<the deck side>"` | `test_water_leisure.py` :: *(g) steps on the weir side are refused, naming the deck side* / *(g) design_check has NO infinity finding on the ensemble* |
| `inf_guard` | error | an open roof edge along the weir — no glass balustrade `GUARD_H` OUTBOARD of the trough | `add_infinity_pool` builds it, or `add_parapet("<grp>", height=1.1, material="mat_glass")` | `test_water_leisure.py` :: *(g) ...design_check: inf_guard ERROR + pool_entry WARN* / *(g) design_check has NO infinity finding on the ensemble* |
| `inf_guard_low` | error | a guard along the weir under `GUARD_H` | `add_parapet(..., height=1.1)` | `test_water_leisure.py` :: *(g) ...and the reply names the treads* |
| `inf_view` | warn | the weir-side guard not glass — it blocks the view the pool is for | `set_material` to `mat_glass` | `test_water_leisure.py` :: *(g) design_check has NO infinity finding on the ensemble* |
| `pool_entry` | warn | a pool with no entry steps at all | `add_pool(..., steps="<deck side>")`, or `add_infinity_pool` builds them with a handrail | `test_water_leisure.py` :: *(g) ...design_check: inf_guard ERROR + pool_entry WARN* |
| `pool_depth` | warn | a swimming pool outside the 1.2-1.5 m uniform depth | `add_infinity_pool` / `add_pool(depth=1.4)` | `test_water_leisure.py` :: *(g) add_pool with an infinity edge and no parapet says NO guard in its reply* |
| `pool_narrow` | warn | an infinity pool under `POOL_MIN_SIDE` across its short side | give it more cells | `test_water_leisure.py` :: *(g) add_pool with an infinity edge and no parapet says NO guard in its reply* |
| `pool_tank` | warn | the basin hanging into the storey below with no plant zone under it — the balance tank, filtration and edge pumps live there | `add_infinity_pool` registers "pool tank + balance tank + plant" | `test_water_leisure.py` :: *(g) design_check has NO infinity finding on the ensemble* |

---

# Refusals by construction
- `place_plan` UNDOES itself and refuses when the placed plan adds a walkability or corridor ERROR on that storey (walk_rules / floor_rules before-vs-after), naming layout_floor for a plate with a drawn core; records of a plan that fall outside the plate are dropped (job 944061f70863, 2026-09-16).
- `repeat_floor` never copies a facade opening onto a storey whose facade twin is a curtain wall, and lifts a window's host to the facade twin of either kind (wall | curtain_wall) on an alternating facade (2026-09-16).
- `set_finish(wall_material=)` leaves a `mat_glass` wall alone — the door wall add_curtain_wall keeps is glazing (2026-09-16).

- `program_status(skip=[...])` refuses to waive a REQUIRED item (corridor, typical_floors, wc, bike_store, refuse_store, a user-named amenity…) — job 71e9d42e559f waived five of them to hand over 19 bare storeys as 'a massing model'; skip= is for recommended items only (2026-09-16).

A design check reports a mistake **after** it is drawn. A refusal stops it being
drawn at all, and names the argument that would have worked. These are the
tool-level refusals added on and after 2026-09-12 in the seven families the gates
work names. They are the reason the recipe and the macros reach 0 errors: the
same rule is enforced twice, once before the record exists and once after.

## stairs_vertical (2026-09-12) — a core may not be drawn into another core

| line | the refusal |
|---|---|
| 417 | `add_stair`: *a {plan} {k} stair at {here} overlaps lift shaft {id} at {there} by {ox} x {oz} m* |
| 420 | `add_stair`: *lift shaft {id} at {there} stands in the {APPROACH_M} m of floor a person needs at the foot of a {plan} {k} stair at {here} (its west/-X side)* |
| 425 | `add_stair`: *that is {n} stair records and the drawing may hold {MAX_OBJECTS} in total* |
| 532 | `add_elevator`: *a {W} x {D} m lift shaft at {here} overlaps lift shaft {id} at {there} by {ox} x {oz} m — **two shafts are two cores, not one*** |
| 540 | `add_elevator`: *a {W} x {D} m lift shaft at {here} overlaps {id} ({word} stair at {there}, plan x {x0}..{x1}) by {ox} x {oz} m* |
| 543 | `add_elevator`: *a {W} x {D} m lift shaft at {here} stands in the {APPROACH_M} m of floor at the foot of {id} ({word} stair at {there}) — nothing to step onto* |
| 548 | `add_elevator`: *that is {need} objects past the {MAX_OBJECTS} ceiling* |

These are the refusal half of `circ_core_clash` and `circ_stair_approach`. The
2026-09-11 pair at lines 392/394 (a stair crossing a facade — the refusal half of
`envelope_poke`) predates the cut-off and is listed for completeness.

## interior_rooms (2026-09-16)

| line | the refusal |
|---|---|
| 195 | `add_room`: *the block {from}..{to} crosses {core phrase} by {ox} x {oz} m on storey {st} — **a room may not be drawn over a stair or a lift***. Use a block clear of it. |
| 202 | `add_room`: *partitions=False leaves nothing to draw for room "{grp}"* |
| 217 | `add_room`: *the {side} side of "{grp}" is the {side} facade of "{group}" — the facade (glass on a glazed storey) is that wall and holds no room door; door_side must be one of {inner sides} (toward the core), or omit it* |
| 222 | `add_room`: *that is {n} objects past the {MAX_OBJECTS} ceiling* |

Line 195 is the refusal half of `clash_core_wall` / `floor_partition_core`;
line 217 is the refusal half of `env_facade_partition`.

## floor_layouts (2026-09-16)

| line | the refusal |
|---|---|
| 174 | `layout_floor`: *this floor is about {need} records and the drawing is at {len(d.objs)} of the {MAX_OBJECTS} ceiling* |

The object-ceiling refusal is what keeps `repeat_floor(2..19)` from filling the
drawing — it is paired with the older 380 (*{n} storeys x {m} records = {total},
and only {room} objects are left … Repeat {fits} storeys at a time, or lay the
floor out with zones=false*). The corridor/unit refusals at 135 and 146 are the
refusal half of `floor_corridor_width` and `floor_unit_narrow`.

## water_leisure (2026-09-16)

| line | the refusal |
|---|---|
| 82 | `add_pool` / `add_infinity_pool`: *that is {n} more objects and the drawing may hold {MAX_OBJECTS} in total* |

The siting refusals in this family (650: *the pool comes within {g} m of {core} …
{CORE_CLEAR} m of deck must go round a core you have to walk past*; 662: *leaves
{clear} m between its coping and the {side} deck edge — a walkway is {WALK_MIN} m
and only the weir side is exempt*; 281/300/303: *an infinity edge is the deck
edge*) are the refusal half of `deck_pool_core`, `deck_walkway` and
`deck_weir_edge`.

## core_kit — the whole family is new (2026-09-16)

`add_core(group, position, lifts, stair, stair_width, lobby_side)` lays the flight,
the shafts, the shared landing and the head house out **together**, so every
by-hand siting mistake becomes a refusal:

| line | the refusal |
|---|---|
| 163 | *add_core needs the stairs_vertical and envelope_rules families* |
| 168 | *name the building the core belongs to (group=…) — draw_box prints it; this drawing has …* |
| 173 | *no building called "{g}" — draw the shell first (draw_box(...)) and use the group name it prints* |
| 178 | *position must be …* |
| 181 | *lifts must be 1..{MAX_LIFTS}* |
| 184 | *stair must be …* |
| 189 | *"{g}" is {storeys} storey — a core climbs between floors; draw_box(..., storeys=N) with N >= 2 first* |
| 194 | *lobby_side must be auto, north, south, east or west* |
| 249 | *a {k} core with {n} lift(s) on the {pos} side needs a plate of at least {plate} (the strip is {total} m long: {n} x {lift_along} m of shaft, {APPROACH_M} m of approach and a {L} x {W} m stair plate)* |
| 273 | *a {L} x {W} m {k} stair and {n} x {lw} x {ld} m shafts could not be laid out clash-free on the {pos} side of "{g}" — try lifts=1, a narrower stair_width, or position="centre"* |
| 291 | *lift {i} of the core could not be placed at {cell} (cells tried: …) — {the inner refusal}* |
| 302 | *the stair of the core could not be placed at {cell} (cells tried: …) — {the inner refusal}* |

Lines 291 and 302 forward the `stairs_vertical` refusal verbatim, so the model
reads the real reason and not "it did not work".

## entrance_kit — the whole family is new (2026-09-16)

`build_entrance(group, side, style)` is **idempotent**: `_entrance_door()` re-uses
an existing `double_door` on that side/axis and `_canopy_over()` re-uses an
existing canopy, so calling it on a building that already has a hand-drawn door
does not cut a second hole (that would be `open_overlap`).

| line | the refusal |
|---|---|
| 346 | *envelope_rules is not loaded — build_entrance needs it to find the facade* |
| 349 | *pass group — the building name draw_box printed* |
| 352 | *side must be one of {SIDES}* |
| 362 | *no building called "{group}" — pass the group draw_box returned* |
| 383 | *the core leaves no strip {MIN_LOBBY_M} m wide and {MIN_LOBBY_M} m deep behind the {side} face of "{group}" for a lobby — put the entrance on another side, or move the core (add_core(group, position=…)) off this one* |

Line 383 is the refusal half of `ent_lobby_size` / `ent_lobby_behind`.

## roof_kit — the whole family is new (2026-09-16)

`build_roof_deck(group, view, pool, guard)` puts the 1.1 m guard on every deck edge
FIRST, then the pool in a band along the `view` facade, then the plant and the
loungers derived from the envelope.

| line | the refusal |
|---|---|
| 381 | *build_roof_deck needs the envelope_rules family* |
| 386 | *name the building the roof belongs to (group=…) — draw_box prints it; this drawing has …* |
| 391 | *no building called "{g}" — draw the shell first (draw_box(...))* |
| 394 | *"{g}" has no roof deck — draw_box(..., roof="flat") or add_roof first; a roof deck is what everything here stands on* |
| 398 | *view must be north, south, east or west — the side the water falls away towards* |
| 403 | *pool="{pool}" is not a kind of water here — pool must be …* |
| 408 | *guard="{guard}" is not a kind of guard here — guard must be …* |
| 413 | *the roof of "{g}" is already laid out facing {view} — delete what is there first, or change it with add_infinity_pool / add_rooftop_plant directly* |
| 434 | *the deck guard could not be built — {why}* |
| 465 | *{why}* (the pool band could not be derived) |
| 478 | *the pool over {c0}..{c1} was rejected by add_infinity_pool — {why}* |
| 483 | *add_infinity_pool drew no pool — {why}* |
| 495 | *the rooftop plant was rejected — {why}* |
| 499 | *add_rooftop_plant placed no units on "{g}" — {why}* |
| 539 | *the head house "{hg}" could not be given a door on its {side} side — {why}* |

Line 413 is why `build_roof_deck` is **not** idempotent the way `build_entrance`
is: it always builds a NEW pool, and refuses outright if `d.ext['roof_kit']`
already records a layout for that group. To re-run it, delete the deck records
first — which is exactly what `test_tower_replay.py` section 2 does.

---

## Where the gates are proved end to end

Two files run the whole gate stack on a real 20-storey tower and require **zero
errors from every family**:

- `tests_arch_ext/test_tower_recipe.py` — the 12-call recipe on a bare drawing,
  through `A.call_tool` only, saving `tests_arch_ext/fixtures/tower_recipe_20260916.json`.
- `tests_arch_ext/test_tower_replay.py` — the ledger's real job replayed, then
  finished with `add_core` / `build_entrance` / `build_roof_deck`. Its docstring
  carries the R1..R9 history of what the gates found.

One clash no macro settles is documented in both: `build_roof_deck` hangs the
pool's tank BELOW the deck into the top storey, where `layout_floor` has already
run its party walls (`clash_wall_water`). Neither family moves the other's
records, so the fix is `delete()` on the walls the finding itself names.

---

## The two gates that are not design checks (2026-09-10, 2026-09-23)

`done()` is refused by two more things before any `error` row above is read, and
both live in `arch_assistant.done_gate`, not in a family's `DESIGN_CHECKS`:

| gate | refuses until | why it exists |
|---|---|---|
| `present()` | the five judged views are of the CURRENT drawing (`present_sig`) | the author does not verify its own work: job 94f5813b explained an error away and it stayed in the drawing |
| `portfolio()` | the ~50-picture hand-over folder is of the CURRENT drawing (`d.ext['portfolio']['sig']`) | the operator's standing rule, 2026-09-23: *"after every drawing, make sure ai assistant delivers portfolio folder with 40+ images from projects"*. Five views are the ones the author chose to show; the portfolio is fifty it did not — right round it, a cut at six stations, a plan cut and two standpoints on **every** level — plus a surface audit of the materials and the curves |

Both gates are signature-pinned to the document, so a drawing changed after the
pictures were taken is photographed again rather than handed over on stale
evidence, and both give up after `GATE_MAX` refusals rather than trapping a job —
the drawing then goes over marked UNFINISHED with what is still open.

The portfolio's own camera plan, the audit thresholds and the folder it writes
are documented in `arch_ext/README.md` under **"THE PORTFOLIO"**; it is the same
plan for a reference asset and for a drawing, because a storey is a level.
