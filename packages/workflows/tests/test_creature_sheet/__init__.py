#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this package is the former tests/test_creature_sheet.py: every name
# that module defined is re-exported here, so the import path is unchanged.

"""
Creature sheet workflow — fast wiring + logic tests (no GPU, no ComfyUI).

    .venv-test/bin/python -m pytest tests/test_creature_sheet.py -q

What is asserted here is what would silently break the run: the angle plan,
the per-cell judge question substitution, the structural checks, the review
gate state machine (parks at awaiting_review, resumes with phase='train'), the
kanban card names matching the API's card map, and that the API exposes the
approve/reject routes the review card documents.
"""

# The submodules are imported in the original section order of test_creature_sheet.py.
# common.py carries the original top import block, so re-exporting its names here is
# what keeps old attribute accesses (test_creature_sheet.os, .css, ...) resolving.
from .common import (
    importlib,
    json,
    os,
    re,
    pytest,
    Image,
    zyg_workflows,
    cid,
    cj,
    css,
    cts,
    paths,
    _PKG,
    _crews,
    _isolate_review_cards,
    _pure,
    csvc,
    needs_checklists,
    needs_imagehash,
)
from .test_plan_and_sheet import (
    test_angle_plan_shape,
    test_instructions_never_say_tilt,
    test_normalize_options,
    test_stage_keys_cover_every_stage,
    test_checklists_present_and_substituted,
    test_judge_offline_never_fails_a_cell,
    test_judge_private_dependencies_exist,
    _noise,
    test_structural_check,
    test_strip_and_sheet,
    test_identity_verdict_logic,
    test_identity_metric_if_cached,
    _fake_edit,
    test_build_sheet_reference_mode,
    test_build_sheet_scratch_mode,
    test_scratch_refuses_flux,
)
from .test_review_gate_and_wiring import (
    _Stages,
    _fake_build_sheet,
    test_review_gate_parks_then_resumes,
    test_no_review_gate_runs_through,
    test_in_process_run_is_never_clobbered_by_the_disk_snapshot,
    test_review_gate_is_reachable_by_an_operator,
    test_park_queues_one_operator_card_and_resolve_closes_it,
    test_review_card_push_never_loses_the_park,
    test_public_chain_carries_creature_options,
    test_letterbox_strip_and_native_reference,
    test_build_sheet_checkpoint_resume,
    test_stale_marking_and_external_pid,
    test_soft_flags_keep_strong_identity_tiles,
    test_split_flags_and_caption_mode,
)
from .test_body_plan_locks import (
    test_keep_sentence_and_side_instruction,
    test_checklist_body_plan_question_only_with_plan,
    test_locks_route_side_cells_and_invalidate,
    test_conform_pass_without_lock,
    test_brief_for_run_reuses_and_carries_locks,
    test_locked_copies_skip_view_flags_and_regen,
    _pair_locks,
    _panel_judge,
    BP_TAIL,
    test_pair_items_selects_templates_by_body_plan,
    test_anchor_agreement_flags_a_shorter_tail_on_one_lock,
    test_anchor_agreement_passes_matching_locks,
    test_anchor_agreement_skips_without_a_covered_part,
    test_anchor_agreement_ignores_errored_questions,
    test_anchor_agreement_all_errors_is_not_a_verdict,
    test_anchor_agreement_offline_judge_is_not_a_verdict,
    test_conform_variants_defaults_to_no_camera_move,
)
from .test_pufferball_regression import (
    _BP_FULL,
    _BRIEF,
    test_plan_clause_keeps_the_smallest_parts,
    test_plan_clause_runaway_cuts_on_a_part_boundary,
    test_validation_prompt_carries_every_body_part,
    test_body_slots_ask_for_ground_and_feet,
    test_preview_judge_arms_the_body_plan_question,
    test_render_previews_passes_plan_and_nonhuman_flag,
    test_nonhuman_negative_drops_person_only_anatomy,
    test_creature_negative_has_no_bare_hands_token,
    test_library_entry_exports_the_body_plan,
    test_klein_lora_runs_at_training_equivalent_strength,
    test_stale_base_model_benchmark_is_dropped_when_the_prompt_changes,
    test_stale_validation_frames_are_dropped_with_the_benchmark,
)
