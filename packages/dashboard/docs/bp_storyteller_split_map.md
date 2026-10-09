<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# `bp_storyteller` split map (2026-10-06)

`packages/dashboard/src/zyg_dashboard/bp_storyteller.py` (2,655 lines) became the package
`packages/dashboard/src/zyg_dashboard/bp_storyteller/` at the same import path. Every section
was moved **verbatim**; the original file was deleted. No importer changed —
`crewai_web_gui/registration.py` still does `from zyg_dashboard import bp_storyteller as
_bp_storyteller` / `app.register_blueprint(_bp_storyteller.bp)`, and
`bp_zero_public_store.py` still calls `_bps_cg.launch_character_generate_from_snapshot`.

| Module | Original lines | Lines | Contents |
| --- | --- | --- | --- |
| `__init__.py` | 1–85 (header, verbatim) | 158 | module comment, the original top + late import block, `bp = Blueprint('storyteller_internal', __name__)`, `_zyg_log`, `_dsl`; then the submodule imports in original section order and the re-export of every name the single file defined |
| `guards.py` | 87–261 | 199 | `_env_on`, `_CHARS_DATASET_ROOT`, `_CHAR_ID_RE`, `_CHAR_ID_WIDE_RE`, `_PREVIEW_SLOT_STEMS`, `_PREVIEW_REGEN_JOBS`, `_PREVIEW_REGEN_LOCK`, `_SWEEP_LOCK`, `_is_medusa_cid`, `_production_paused`, `_preview_provenance_map`, `_save_uploaded_char_photos`, `_restore_parked_char_photos`, `_char_lora_usable` |
| `chars.py` | 263–572 | 344 | `api_internal_creature_list`, `api_internal_storyteller_list_chars`, `api_internal_storyteller_analyze_character_photo` |
| `contact_sheet.py` | 574–1037 | 510 | contact-sheet start/status/approve/pause/resume, pipeline pause/resume/pause-state, contact-sheet image, list-contact-sheets |
| `generate_worker.py` | 1385–1905 | 573 | `_make_bg_generate(...)` — the character-generate background thread body |
| `generate_character.py` | 1040–1384, 1906–1954 | 453 | `api_internal_storyteller_generate_character`, `launch_character_generate_from_snapshot` |
| `char_admin.py` | 1956–2249 | 327 | voices, voice-sample, character-bible, character-status, `_retrain_*` helpers, retrain + retrain/status |
| `previews.py` | 2251–2655 | 446 | preview regenerate + status, gen-char-previews sweep, char-preview-status |

## The one structural deviation

`api_internal_storyteller_generate_character` was **879 lines in a single `def`** (1040–1918) —
over the 800-line module ceiling all by itself, so no verbatim module could hold it. Its nested
closure `_bg_generate` (1385–1905, 521 lines) was lifted into `generate_worker._make_bg_generate`
**at the same 4-space indentation**, so every line of the closure is byte-for-byte the original.
The nine parameters are exactly the closure's free variables as reported by `symtable`:
`info, char_id, params, model_family, kick_lora, _uploaded_image_paths, _photo_analysis,
_char_emit, _check_char_stop`.

The route now calls the factory immediately before the `threading.Thread(...)` line it already had.
The only semantic difference is `nonlocal info`: it now rebinds the factory's local instead of the
route's. That is unobservable — the route never reads `info` after creating the thread (its
`return jsonify(...)` uses `char_id`, `trigger_token`, `status`, `model_family`, `params`), and the
shared dict is still the same object, so every `info[...] = ...` mutation propagates as before.

## Notes

- `grep -n '^\s*global '` on the original: **no `global` statements**, so no mutable module state
  had to be kept together. The mutable registries (`_PREVIEW_REGEN_JOBS`, `_char_gen_jobs`, …) are
  only mutated in place, never rebound.
- Submodules take the header names from the package root
  (`from zyg_dashboard.bp_storyteller import ...`), which is already fully bound when `__init__`
  reaches the submodule imports. This preserves the module's "late import" contract exactly:
  `bp_claude_clip`, `bp_zero_public_store` and `crewai_web_gui` are still imported only after
  `bp` exists, and only from `__init__.py`.
- `_zyg_log` is re-created in each submodule by assignment as
  `_zyg_logging.getLogger('zyg_dashboard.bp_storyteller')`, so log records keep the original
  logger name.
- All 24 `@bp.route` registrations keep their original order (decorator text and function name
  compared pairwise against the pristine file).
