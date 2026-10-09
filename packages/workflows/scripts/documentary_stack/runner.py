# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The harness entry point: runs every test in the original order and scores it."""

from .core import RESULTS, check
from .basics import (
    test_sub_digits,
    test_burn_subtitles_default,
    test_level_to,
    test_headroom_guards,
    test_llm_audit,
    test_guard,
    test_roster,
    test_music_bed,
    test_typography_checklist,
    test_combat_classifier,
    test_strip_written_subject,
    test_typography_repair,
)
from .inpaint_and_judges import (
    test_flux_inpaint_contract,
    test_flux_inpaint_live,
    test_repair_wiring,
    test_cpu_core_ceiling,
    test_typography_ocr_judge,
    test_typography_judge_order,
    test_strip_against_real_prompts,
)
from .gates_and_ladder import (
    test_gate_reachability,
    test_stage37_runs_with_persistent_worker,
    test_retry_ladder,
    test_inert_lever_guard,
)
from .staleness_and_receipts import (
    test_staleness_and_receipts,
    test_production_interpreter,
)
from .klein import (
    test_klein_pathway,
    test_bakeoff_inspection_tab,
    test_klein_training_path,
)
from .anachronism import (
    test_period_noun_rewrite,
    test_era_gate_offline,
    test_era_gate_wiring,
    test_thumbnail_and_family,
)


def main():
    for fn in (
        test_retry_ladder,
        test_sub_digits,
        test_burn_subtitles_default,
        test_level_to,
        test_headroom_guards,
        test_llm_audit,
        test_guard,
        test_roster,
        test_music_bed,
        test_typography_checklist,
        test_combat_classifier,
        test_strip_written_subject,
        test_typography_repair,
        test_flux_inpaint_contract,
        test_flux_inpaint_live,
        test_repair_wiring,
        test_cpu_core_ceiling,
        test_typography_ocr_judge,
        test_typography_judge_order,
        test_strip_against_real_prompts,
        test_gate_reachability,
        test_stage37_runs_with_persistent_worker,
        test_inert_lever_guard,
        test_staleness_and_receipts,
        test_production_interpreter,
        test_klein_pathway,
        test_bakeoff_inspection_tab,
        test_klein_training_path,
        test_period_noun_rewrite,
        test_era_gate_offline,
        test_era_gate_wiring,
        test_thumbnail_and_family,
    ):
        print(f'\n--- {fn.__name__} ---')
        try:
            fn()
        except Exception as exc:
            check(fn.__name__, False, f'raised {type(exc).__name__}: {exc}')
    p = sum(1 for _, r, _ in RESULTS if r is True)
    f = sum(1 for _, r, _ in RESULTS if r is False)
    s = sum(1 for _, r, _ in RESULTS if r is None)
    print(f'\n{"=" * 58}\nPASS {p}   FAIL {f}   SKIP {s}')
    for n, r, d in RESULTS:
        if r is False:
            print(f'  FAILED: {n} {d}')
    return 1 if f else 0
