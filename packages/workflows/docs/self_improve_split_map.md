<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# `self_improve` split map

`packages/workflows/src/zyg_workflows/self_improve.py` (3,251 lines) became the package
`packages/workflows/src/zyg_workflows/self_improve/`. The import path is unchanged —
`import zyg_workflows.self_improve` and every attribute access on it resolve exactly as
before. Each section was cut at the file's own `# ═══ N. TITLE ═══` banners and moved
**byte for byte**; no logic, constant, calibration value or provenance comment was edited.

| Module | Original lines | Section(s) | Lines |
|---|---|---|---|
| `base.py` | 100–172, 175–211 | preamble constants + JSON helpers, §1 geometry/normalisation | 133 |
| `chain.py` | 214–321, 324–442 | §2 chain detection, §3 keep/pin boxes | 247 |
| `measure.py` | 445–662, 665–680, 682–730 | §4 measurement, §5 facts, §6 QC spec resolution | 312 |
| `remedies.py` | 1329–1915 | §8 remedy KB + `_FallbackKB` | 607 |
| `signature.py` | 733–1326 | §7 `build_signature` | 627 |
| `planning.py` | 2151–2357 | §11 `plan_next_attempt` | 224 |
| `diagnosis.py` | 1918–1957, 1960–2148, 2804–2934 | §9 VLM narrative, §10 `diagnose`, `render_next_attempt_md` | 386 |
| `campaign_view.py` | 2634–2801 | §13 `campaign` | 189 |
| `verify.py` | 2360–2631 | §12 `verify_attempt` | 293 |
| `watch.py` | 2937–3149 | §14 `watch_active_run` | 233 |
| `cli.py` | 3152–3247 | §15 CLI | 116 |
| `__main__.py` | 3250–3251 | the `if __name__ == '__main__'` guard | 12 |
| `__init__.py` | 1–98 | module docstring, top import block, re-exports | 195 |

## Notes on the cut

* **`global _kb_singleton`** (original line 1735): `_kb_singleton`, `kb()` and every
  mutator stay together in `remedies.py`. Re-export by value would break the rebinding.
* **Two blocks were relocated** to make the import graph a DAG:
  * `render_next_attempt_md` (§13, lines 2804–2934) moved into `diagnosis.py` — §10
    calls it and §13 calls §10's `vlm_findings`; this breaks the only cycle. Its range
    is still verbatim.
  * `signature.py` is imported after `remedies.py` because `build_signature` calls `kb()`.
    `__init__.py` still *lists* the submodules in original section order; Python resolves
    the real load order from the imports.
* **`_DIR` is re-anchored**: the module now sits one directory deeper, so
  `base.py` uses `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` and still
  resolves to `…/src/zyg_workflows`. The `sys.path.insert` of the original lines 96–98
  happens in `base.py`, which is the first submodule imported.
* **`_zyg_log`** keeps its original name: each submodule that logs assigns
  `_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')` itself, so the
  logger name is identical to the old `getLogger(__name__)`.
* **`cli.py`'s docstring first line** is byte-identical to the original module
  docstring's first line, because `main()` uses
  `argparse.ArgumentParser(..., description=__doc__.split('\n')[0])`.

## Proof

* Every original line range above was asserted to be a literal substring of its new
  module **after** `ruff format` — all 16 ranges verbatim, and lines 100–3247 are fully
  covered apart from the blank separator lines between sections.
* Namespace diff against a pristine copy of the original module: all 75 original
  top-level names present, with identical `dis.get_instructions()` streams, `co_names`,
  `co_varnames`, defaults, annotations and docstrings (nested code-object reprs
  normalised for filename/lineno). The only value difference is `_DIR`, which points at
  the pristine copy's own directory in the baseline run and at
  `…/src/zyg_workflows` in the package — i.e. the re-anchoring is correct.
