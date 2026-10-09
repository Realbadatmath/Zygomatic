# Splitting `_run_scholarly_pipeline` — log

`zyg_workflows.pipeline_scholarly._run_scholarly_pipeline` was one function of
11,327 lines (12,707-line file). The chain of tasks moves each top-level
`# ── Stage N …` block into a `stage_<nn>_<slug>(ctx)` function in this package
and leaves the monolith as the prologue, an ordered list of stage calls, and
the `try/except/finally` around the run.

**Read this before extracting the next stages.** Four findings below (the stage
count, the crossings no name analysis sees, the byte-offset bug, and the two
glue styles) cost most of the first two tasks' budgets and are not in any brief.

The chain is **complete**. After task 3 no marker was left and
`_run_scholarly_pipeline` was 623 lines; task 4 moved the run scaffold — the
prologue's eleven closures and the three exit paths — into `stages_55_73.py` and
left the function at **259** lines: the prologue, the `RunContext`, twenty-one
stage calls and the `try/except/except/finally`. See "Task 4 of 4" for that move
and for the portability/`exe`/suppression sweeps, and `README.md` next to this
file for how the result runs.

One piece of structural debt survives the chain: `stage_11c_flux_image_loop` in
`stages_37_54.py` is 3,558 lines of one `if`/`try` and is under no `func_len`
gate. "Task 3 of 4" explains why it could not be split by marker.

## Task 1 of 4 — done 2026-10-05

Moved: the first **nine** top-level stages, into `stages_01_18.py` (3,090 lines).
`_run_scholarly_pipeline` went from **11,327 → 8,411** lines; the file from
12,707 → 9,773.

| fn | original lines | marker |
|---|---|---|
| `stage_01_topic_setup` | 1647-1663 | Stage 1: Topic Setup |
| `stage_02_academic_research` | 1664-1798 | Stage 2: Academic Research |
| `stage_03_script_preparation` | 1799-2890 | Stage 3: Script Preparation (Editing Pass) |
| `stage_04_fact_check` | 2891-2984 | Stage 3 fact-check: Haiku flags unverifiable claims |
| `stage_05_visual_intent_tagging` | 2985-3726 | Stage 3b: Visual Intent Tagging |
| `stage_06_turning_points_and_emotions` | 3727-3818 | Stage 3.1 pre-step: combined Haiku call |
| `stage_07_emotion_curve` | 3819-4028 | Stage 3.1: Emotion Curve Extraction (Murch hierarchy) |
| `stage_08_tts_pre_image_pass` | 4029-4426 | Stage 4 (pre-image pass): TTS + word timings |
| `stage_09_time_locked_scene_descriptions` | 4427-4623 | Stage 3.5a: Time-Locked Scene Descriptions |

Line numbers are those of commit `7fdeed4`, which is what
`scholarly_split.py verify --ref HEAD` compares against.

### The stage count is 19, not 73

The brief for task 1 says the monolith carries "73 `# … Stage N …` comment
markers" and splits them 1-18 / 19-36 / 37-54 / 55-73 over four modules. The
file carries **27** such comments, and only **19** of them are stage
boundaries — the other 8 sit inside the Stage 3.5 image loop at indents 20-24
and are not a flat statement sequence, so they cannot be cut out on their own.
`scholarly_split.py markers` prints the 19 and is the source of truth.

So "stages 1-18" is not a quarter of the work, it is 18 of 19 stages. This task
moved the first 9 (2,977 of the 11,327 lines, the amount its `func_len` limit of
9,000 asks for) and the **remaining ten are listed below for the next tasks**;
the module names `stages_19_36.py` etc. no longer match anything. Suggested
split of what is left, by `markers` run on the current file:

| marker | lines (current file) | size |
|---|---|---|
| Stage 3.5: FLUX Image Generation | 1696-2894 | 1,198 |
| Stage 3.5 Pre-generation: single Claude Sonnet batch call | 2895-7802 | 4,904 |
| Stage 3.7: Hand QC | 7803-7937 | 116 |
| Stage 4: TTS Narration (rhythm refresh) | 7938-7985 | 45 |
| Stage 5: LTX-2.5 Motion | 7986-8039 | 49 |
| Stage 6: Video Assembly | 8040-8848 | 808 |
| Stage 6a: music bed | 8849-9178 | 315 |
| Stage 6a: Cinematic color grade | 9179-9216 | 37 |
| Stage 6b: Book intro — disabled | 9217-9310 | 93 |
| Stage 6c: Burn subtitles | 9311-9513 | 201 |

The 4,904-line "Pre-generation" marker is the real remaining problem: it is one
marker holding the whole image loop (and the 8 nested markers). It needs its
own task and probably its own sub-split along the `def`s inside it.

## Task 2 of 4 — done 2026-10-05

Moved: the **nine** remaining top-level stages — marker 10 and markers 12-19,
i.e. everything but the Pre-generation block — into `stages_19_36.py`
(3,136 lines). `_run_scholarly_pipeline` went from **8,411 → 5,557** lines; the
file from 9,773 → 6,913.

| fn | lines before this task | HEAD lines | marker |
|---|---|---|---|
| `stage_10_flux_image_generation` | 1696-2894 | 4624-5822 | Stage 3.5: FLUX Image Generation |
| `stage_12_hand_qc` | 7803-7937 | 10731-10865 | Stage 3.7: Hand QC |
| `stage_13_tts_rhythm_refresh` | 7938-7985 | 10866-10913 | Stage 4: TTS Narration (rhythm refresh) |
| `stage_14_ltx_motion` | 7986-8039 | 10914-10967 | Stage 5: LTX-2.5 Motion |
| `stage_15_video_assembly` | 8040-8848 | 10968-11776 | Stage 6: Video Assembly |
| `stage_16_music_bed` | 8849-9178 | 11777-12106 | Stage 6a: music bed |
| `stage_17_colour_grade` | 9179-9216 | 12107-12144 | Stage 6a: Cinematic color grade |
| `stage_18_book_intro` | 9217-9310 | 12145-12238 | Stage 6b: Book intro — disabled |
| `stage_19_burn_subtitles` | 9311-9513 | 12239-12441 | Stage 6c: Burn subtitles |

**The module name is a misnomer and stays one.** `stages_19_36.py` holds
markers 10 and 12-19; the brief's four-module naming assumed 73 stages. Keeping
the name the brief chain names is worth less confusion than renaming a file two
later tasks will reference, so the docstring says what is really inside.

The numbering **skips 11**: marker 11 is the still-inline Pre-generation block,
and the stage numbers are positions in the run, not in the file.

### The glue style changed — plain locals, byte-identical body

Task 1 rewrote each crossing local to `ctx.<name>` throughout the moved range.
That cannot work here. These nine ranges define **twenty nested `def`s** (the
Ken-Burns renderer, the music-bed builder, `_build_image_prompt`, …) and

* a closure cannot capture an attribute, so `ctx.topic` inside a nested `def`
  is not the same binding the original closed over, and
* `rewrite()` walks the AST but `symtable`'s free-variable view is per scope:
  names read only inside a nested scope are not in the top-level range's name
  report at all, so a `ctx.`-rewritten range comes out *half*-rewritten.

So `emit()` grew `in_names` / `out_names` / `guarded_in` and the stages look
like:

```python
def stage_nn_slug(ctx):
    job = ctx.job             # head: what crosses in
    <the range, verbatim>
    ctx.final_video_path = …  # tail: what crosses out
```

The body is byte-identical to the monolith's (modulo `ruff format`'s dedent),
and every name — top level or nested — resolves to the same object it resolved
to before. Prefer this style for marker 11 too; it has 50+ nested `def`s.

### `UNSET`: the crossing whose local may be legitimately unbound

Stage 3.7 (`stage_12_hand_qc`) calls `_sch_typography_pass()` and
`_sch_hand_qc_pass()` inside `except NameError:` — that is a live feature
detect for "the FLUX stage never ran, so there is no closure to call". A
`RunContext` field defaulting to `None` turns that `NameError` into a
`TypeError` and the gate receipt changes. `context.py` therefore has an
`UNSET` sentinel (`_Unset`), those two fields default to it, and the glue is

```python
if ctx._sch_hand_qc_pass is not UNSET:
    _sch_hand_qc_pass = ctx._sch_hand_qc_pass
```

so the local stays genuinely unbound when the field was never written. This is
the only reason `stage_12_hand_qc` reports `DIFFER` (see below).

### Where a pure move was not possible

* **Four reads inside the nested `_build_image_prompt` became `ctx.` reads.**
  That `def` lives in marker 10 and so moved into `stage_10`, but it is only
  ever *called* from the still-inline marker 11, at a point where
  `_prebuilt_prompts` and `_sch_qwen_stills` already have their final values.
  As a closure of `stage_10` it cannot see the monolith's locals, so
  `stages_19_36.py` reads `ctx._prebuilt_prompts` / `ctx._sch_qwen_stills`
  (the nested `def` closes over `stage_10`'s `ctx` parameter) and the monolith
  **mirrors** each of the four assignment sites:
  `ctx._prebuilt_prompts = _prebuilt_prompts` after both of its assignments,
  `ctx._sch_qwen_stills = _sch_qwen_stills` after both of its assignments.
  Two more mirrors publish the two `UNSET` closures. Six mirror lines total,
  each on the line after the assignment it mirrors. They all disappear when
  marker 11 becomes a stage.
* **Seventeen values are unpacked back out of the context** right after
  `stage_10_flux_image_generation(ctx)`, because marker 11 is still inline and
  reads them (and closes over them) as plain locals:
  `_DEFAULT_FLUX_PROMPT`, `_FLUX_NEGATIVE`, `_FLUX_PROMPT_TEMPLATES`,
  `_STYLE_SUFFIXES`, `_build_image_prompt`, `_era_lock`,
  `_essay_title_for_prompt`, `_fallback_subject`, `_flux_images_dir`,
  `_flux_model_path`, `_is_modern_topic`, `_n_flux_images`,
  `_narration_sentences`, `_sch_family_early`, `_sch_family_label`,
  `_slot_word_bounds`, `_word_count_est`. Task 1's four unpacks shrank to two
  (`_sch_subject_type`, `narration_script`) because `_tag_sentence` and
  `visual_tags` are now read by a stage instead.
* **A five-line repack before `stage_12_hand_qc(ctx)`** hands marker 11's own
  products down: `_flux_generated_paths`, `_flux_image_meta`,
  `_murch_image_debug`, `_sch_fw`, `_sch_family_label`. Task 3 deletes it.
* **14 module-level imports left `pipeline_scholarly`** with their only users:
  `_urlsplit`, `requests`, `_bm_record_pipeline`, `_ffmpeg_popen_nvenc_first`,
  `_ffmpeg_run_nvenc_first`, `_cleanup_pipeline_output`,
  `_load_flux_seconds_per_image_estimate`, `_burn_subtitles`,
  `_make_book_intro`, `_register_prompt`, `_scp_output_to_windows`,
  `_ensure_comfy_offload_env`, `_apply_color_grade`, `_KB_THREAD_STAGGER_S`.
  Checked first that nothing imports them *through* this module: only
  `_run_scholarly_pipeline` (dashboard `crewai_web_gui.py`) and
  `_render_kb_pil_shared` (`pipeline_storyteller`) are.
* **One hardcoded path was kept verbatim**: `stage_10` still falls back to
  `/home/zygomatic/ai-models/FLUX/flux1-schnell`. Making it portable is a
  behaviour change and belongs to the portable-paths tasks, not to a pure move.

### `names` has three blind spots — grep for these by hand

1. **"first use after the range is a store" hides a real crossing.**
   `_sch_family_label` and `_book_intro_prepended` are *assigned* again below
   their producing range, so `names` does not list them as crossing out — but
   a branch above the re-assignment reads them. Both are real crossings.
2. **`except NameError:` makes "unbound" meaningful** — the `UNSET` case above.
3. **A nested `def` that moves but is called later** reads names that are
   assigned after its own range (the `_build_image_prompt` case). No
   scope-based analysis flags it; what finds it is `ruff check`'s F821 on the
   new module.

Task 1's list still holds: grep a new range for `locals(`, `vars(`, `globals(`,
`eval(` and `__file__` before trusting `names`. In these nine ranges there were
none (the two `locals().get('_bk_cg')` sites are inside marker 11).

### `check_free_names.py` gained the monolith as a context *writer*

Check 2 only scanned `stages_*.py` and the `RunContext(...)` keywords, so the
eight fields the mirrors and the repack write looked like unwritten orphans. It
now also walks the `ctx.<name>` nodes of `_run_scholarly_pipeline` itself.
`_ctx_attrs` took a `within=` argument for that: at module level in
`pipeline_scholarly` there is an unrelated local called `ctx` (`_bare_context`
builds a word list), and `ctx.append` is not a field of anything.

### What task 3 inherited

One marker, 4,925 lines, holding the image loop and the 8 nested sub-markers at
indents 20-24 — and the prediction, half right, that the 17 unpacks, the 6
mirrors and the 5-line repack would all go with it. The unpacks and the repack
did; the mirrors stayed, because `_build_image_prompt` is a closure of `stage_10`
and still has to reach `_prebuilt_prompts` / `_sch_qwen_stills` through `ctx`.

## Task 3 of 4 — done 2026-10-05

Moved: the last marker, the 4,925-line "Stage 3.5 Pre-generation" block, into
`stages_37_54.py` (5,087 lines) as **three** stages.
`_run_scholarly_pipeline` went from **5,557 → 623** lines; the file from
6,913 → 1,963. `scholarly_split.py markers` now prints **nothing**: the monolith
is the prologue, nineteen-plus-two stage calls and the `try/except/finally`.

| fn | lines before this task | HEAD lines | what it is |
|---|---|---|---|
| `stage_11_flux_prompt_batch` | 1719-2682 | 5827-6784 | `_batch_generate_flux_prompts` (945 lines) + the one Sonnet batch call |
| `stage_11b_flux_preflight` | 2684-3089 | 6791-7190 | pre-emptive record/replay exits, pre-FLUX Murch self-eval, checkpoint probe, stills-backend choice, FluxWorker claim |
| `stage_11c_flux_image_loop` | 3091-6631 | 7191-10729 | `if _flux_ready or _sch_comfy_only:` — the whole image loop |

### Why marker 11 became three stages and not one or six

Its top-level statement list has exactly two seams a pure move can cut at: after
the `if _prebuilt_prompts:` log (2682) and before `if _flux_ready or
_sch_comfy_only:` (3091). Everything after that seam is **one `If` holding one
`Try` of 3,521 lines**, so `stage_11c_flux_image_loop` is 3,558 lines and there
is no further cut that keeps "identical statements in identical order" — the next
one has to lift a prefix of a `try:` body out of its own `except`, which is a
restructure, not a move. `func_len` is run by the chain's `verify_cmd` on
`pipeline_scholarly.py` only, which is now clean at any limit ≥ 623; the stage
module is not under that gate. **Task 4 (or a follow-up tree) owns splitting
`stage_11c`**, and it is a much smaller job now: a standalone function with a
declared `ctx` in/out contract instead of a block in an 11k-line closure.

### `StageExit` is finally used

The record run and the replay-verify run both `return`ed straight out of the
monolith from inside marker 11 (old 6828 and 6888 at HEAD). Those two bare
`return`s are the only statements in the three ranges whose text changed:

```
-    return
+    return StageExit()
```

and the call site is

```python
_preempt_exit = stage_11b_flux_preflight(ctx)
if isinstance(_preempt_exit, StageExit):
    return _preempt_exit.value
```

`StageExit().value` is `None`, which is what the bare `return` returned, and the
return still happens inside the monolith's `try:`, so the `finally:` gate audit
and VRAM release run exactly as before.

### Two crossings `names` could not see, both found by hand

1. **`nonlocal _last_prompt, _prev_focal_zone`** (old 4839 of the pre-task-3
   file). `occurrences` only records a `Global`/`Nonlocal` at depth 0, so
   `_prev_focal_zone` — bound in range B, declared `nonlocal` by a nested `def`
   of range C — appeared in no report at all. With the plain-local glue it works
   (`_prev_focal_zone = ctx._prev_focal_zone` gives `stage_11c` the binding the
   `nonlocal` needs); without it the module does not even compile.
2. **`_sch_family_label`**, the blind spot task 2 already wrote down: range C
   assigns it at its own line 3119, so `names` calls it stage-local, but the
   `else:` arm of `if _flux_ready or _sch_comfy_only:` never reaches that
   assignment and the value `stage_10` produced has to survive. It is both an
   in- and an out-crossing of `stage_11c`.
   `_sch_gpu_lock_held` is the third of this shape and was found by the
   "stored here, loaded later, not flagged" sweep below.

The sweep worth re-running on any future range, because it is what caught
`_sch_gpu_lock_held`:

```python
loose = (in_stored & post_loaded) - set(rep['crossing_out'])
```

For A/B/C it printed `[]`, `['_exc', '_pi', '_sch_gpu_lock_held']`,
`['_exc', '_me']`. `_exc`, `_pi` and `_me` are false positives — every later use
is preceded by its own `except … as _exc` / `for _pi in …` rebinding.

### Where a pure move was not possible

* **The two `return`s above.** Nothing else: `verify` reports `EQUAL` for
  `stage_11_flux_prompt_batch` and `stage_11c_flux_image_loop`, and for
  `stage_11b_flux_preflight` the diff of the two normalised bodies is exactly the
  two `return` → `return StageExit()` lines (see "Proving the next move" for the
  diff recipe).
* **The six mirrors task 2 added did not disappear** as task 2 predicted. Four of
  them (`ctx._prebuilt_prompts`, `ctx._sch_qwen_stills`) are still needed, because
  `_build_image_prompt` is a closure of `stage_10` in `stages_19_36.py` and reads
  them off the context; they simply moved along into `stage_11`/`stage_11b` where
  `ctx` is now the stage's own parameter. The two that publish the `UNSET`
  closures moved into `stage_11c` for the same reason. What *did* disappear is the
  monolith's 17-line unpack after `stage_10`, its 2-line unpack after `stage_09`
  and its 5-line repack before `stage_12` — 24 lines of glue, gone.
* **`locals().get("_bk_cg", …)`** (two sites inside the image loop) moved
  verbatim. `_bk_cg` is assigned and read in the same range and at the same
  nesting, so `locals()` now returns `stage_11c`'s locals instead of the
  monolith's and answers the same question.
* **15 module-level imports left `pipeline_scholarly`** with their only users:
  `glob`, `typing.Any`, `_bench_replay_get`,
  `_update_flux_seconds_per_image_estimate`, `_log_prompt`, `MODEL_LARGE`,
  `_deep_unload_flux_pipeline_cache`,
  `_enforce_gpu_exclusivity_before_stage35`, `_wait_for_vram`,
  `_wait_ollama_unload`, `_dsl`, `_FLUX_LORA_PATH`, `_FLUX_LORA_SCALE`,
  `_STYLE_LORA_CONFIG`, `_STYLE_LORA_DIR`. Checked first that nothing imports
  them *through* this module: only `_run_scholarly_pipeline` (dashboard
  `crewai_web_gui.py`) and `_render_kb_pil_shared` (`pipeline_storyteller`) are.
* **The hardcoded `/home/zygomatic/ai-models/FLUX/flux1-schnell` fallback** that
  task 2 left in `stage_10` is still there, and `stages_37_54.py` adds no new
  one. Portability is a behaviour change and belongs to the portable-paths tasks.

### 12 new `RunContext` fields

`_preempt_dry` (run input) and `_flux_lever_guard` (prologue closure) are passed
at construction; the other ten are products of `stage_11b` read by `stage_11c`:
`_murch_turning_points`, `_prev_focal_zone`, `_flux_ready`, `_sch_backend` (the
`scholarly_stills_backend` *module*), `_sch_skip_local_flux`, `_sch_comfy_only`,
`_sch_use_comfy_images`, `_sch_gpu_lock_held`, `_sch_fw_active`,
`_fw_claimed_start`. 85 ctx fields are now read and all of them are written.

### One fix in `scripts/scholarly_split.py`

`rewrite()` returns `body` unchanged when `ctx_names` is empty — which is always,
in the plain-local style. Without the early return it calls `symtable` on
`emit`'s `if True:` wrapper, and symtable *refuses* a range holding a `nonlocal`
at module level (`SyntaxError: no binding for nonlocal '_last_prompt' found`), so
range C could not be emitted at all.

## Task 4 of 4 — done 2026-10-05

Nothing left to move by marker: tasks 1-3 took all nineteen. What task 4 moved is
the **run scaffold** — the part of `_run_scholarly_pipeline` that is not a stage —
into `stages_55_73.py` (528 lines, 5 functions), and then applied this tree's
portability, `exe` and suppression recipes to the whole package.

`_run_scholarly_pipeline` went **623 → 259** lines (file 1,972 → 1,599). The gate
is `func_len … 300` on the monolith and `func_len … 400` on the new module.

| fn | what it was | lines |
|---|---|---|
| `stage_55_run_glue` | the prologue's eleven nested helpers + the gate registry + the gate pre-registration loop | 124-397 |
| `stage_56_staleness_gate` | the "is this module older than the file on disk" verdict | 399-450 |
| `stage_71_on_user_stop` | the body of `except StopIteration:` | 452-472 |
| `stage_72_on_error` | the body of `except Exception as exc:` | 474-501 |
| `stage_73_finalise` | the body of `finally:` | 503-528 |

### The glue is a `RunGlue`, not a `RunContext`

`_log`, `_save`, `_debug`, `_done`, `_stage_start`, `_should_stop`,
`_assert_not_stopped`, `_gate_receipt`, `_flux_lever_guard` and the two gate
helpers behind them are **closures** over `job`, `pipeline_state`, `state_file`,
`_gate_receipts` and `_lever_guard_done`. They cannot become module-level
functions and they cannot read the names off a context, because they are built
before the context exists and the stages receive them as objects. So
`stage_55_run_glue` is a factory: one `def` per helper, exactly as nested as
before, returned on a `@dataclass RunGlue`. The driver unpacks it into the same
plain local names:

```python
_glue = stage_55_run_glue(job, pipeline_state, pipeline_id, state_file)
_log = _glue._log
_save = _glue._save
…
```

and then passes those same objects to `RunContext(...)`. Every statement that
stayed in the driver reads as it did when the helpers were nested, and a stage
still calls the very `_log` the monolith called. No new `RunContext` field: the
nine the stages use were already declared by task 1.

`RunGlue` is deliberately **not** `RunContext`. The context is the data that
crosses a *stage* boundary; the glue is the machinery the scaffold and the stages
share. Merging them would have put `state_file` and `_gate_receipts` — which no
stage touches — on the object `check_free_names.py` audits field by field.

### Where a pure move was not possible

* **`_pipeline_marker` became a parameter.** The `except`/`finally` bodies read
  `_pipeline_marker`, a plain local of the prologue that is never stored on
  `pipeline_state`. `stage_71_on_user_stop(glue, pipeline_marker)` and
  `stage_72_on_error(glue, pipeline_marker, exc)` take it explicitly. Fetching it
  off `pipeline_state` *looked* right and would have silently marked nothing.
* **The two Ollama eviction blocks merged** into one module-level
  `_evict_ollama_models(glue, why)`. The error path and the finally path carried
  the same ten statements with different log prefixes; the prefix is now the
  `why` argument. This is the one place in the whole chain where two monolith
  blocks became one function.
* **`_EVENT_KEEP_LEVELS` was deleted**, not moved. It was a module-level-looking
  constant built inside the prologue and read by nothing — `_trim_events` filters
  by count, not by level. `_trim_events` itself moved verbatim to module level.
* **Seven imports dropped out of `pipeline_scholarly.py`** with the blocks that
  used them: `safe_urlopen`, `_update_marker`, `_release_pipeline_vram`,
  `_OLLAMA_BASE_URL`, `_agent_log`, `_parse_iso_to_ams`, `_push_error_log` (ruff
  F401). Checked first that nothing imports them *through* this module — only
  `_run_scholarly_pipeline` and `_render_kb_pil_shared` are.

### The three recipes, applied to the package

Counts are of the files this task owns: `pipeline_scholarly.py` and
`scholarly/**`. All three sweeps are now at zero.

* **Portability — 6 home-path sites.** `stage_10`'s FLUX fallback (the one tasks 2
  and 3 both left behind, see above) is now
  `str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')`; the storyteller LoRA dataset is
  `paths.ZYG_LORA_DATASETS`; the Real-ESRGAN weights are
  `paths.ZYG_REALESRGAN_ROOT / …`; the two `vlm_judge` strings (a comment and a
  log line) are `paths.ZYG_MODELS_DIR / 'vlm_judge'`.
* **Portability — 13 host literals.** Every `http://localhost:11434` is
  `pipeline_config._OLLAMA_BASE_URL` (5 in `stages_01_18.py`, 1 in
  `stages_19_36.py`, 5 in `stages_37_54.py`, 2 in `stages_55_73.py`).
  `_OLLAMA_BASE_URL`, not `paths.ZYG_OLLAMA_URL` directly: it is already
  `= paths.ZYG_OLLAMA_URL` and going through the module keeps it monkeypatchable,
  which the scholarly tests rely on.
* **`exe` — 9 bare `argv[0]`.** `'ffmpeg'`/`'ffprobe'` → `exe('ffmpeg')` /
  `exe('ffprobe')` (1 in `pipeline_scholarly.py`, 1 in `stages_01_18.py`, 7 in
  `stages_19_36.py`).
* **Suppression — all 54.** HEAD's `pipeline_scholarly.py` carried exactly 54
  `_zyg_log.debug('suppressed %s: %s', …)` handlers. 46 were rewritten in place
  (10 still in `pipeline_scholarly.py`, 4 in `stages_01_18.py`, 8 in
  `stages_19_36.py`, 24 in `stages_37_54.py`); the other 8 were in the blocks
  this task moved and were rewritten as they landed in `stages_55_73.py`.

### What the suppression rewrite decided, so the next pass does not re-litigate

Each handler now says what failed *and* what the run loses, and `except Exception`
was narrowed wherever the exception set is knowable:

* **narrowed** when the body is pure Python or `os`: `OSError` for `rmtree` /
  `os.remove` / `os.stat`; `(TypeError, ValueError)` for timestamp parsing;
  `(KeyError, IndexError, TypeError, ValueError)` for the per-slot QA
  bookkeeping; `(AttributeError, KeyError, TypeError)` for the dashboard retry
  counter; `ImportError` where the whole `try` is a feature probe;
* **`NameError`** for the three `del _flux_pipe` / `del _cn_pipe` handlers — an
  unbound local raises `UnboundLocalError`, a `NameError` subclass, and that is
  the only thing those `try:`s can raise;
* **`except Exception` kept, with `# noqa: BLE001 — <reason>`**, wherever the body
  touches a third-party error tree: torch and diffusers (`.to('cpu')`,
  `empty_cache`, `mem_get_info`, LoRA unload), the Postgres-backed token-usage
  recorder, the nvidia-smi free-VRAM probe, the FLUX worker client, the optional
  audit sink and the pre-emptive bank. Narrowing those would turn a swallowed
  third-party error into a crashed GPU run;
* **level raised to `warning`** on four handlers whose failure the operator must
  see: the unwritten state file, the Real-ESRGAN that stayed on the GPU, the
  incomplete post-FLUX VRAM reclaim, and the FLUX worker pipe slot that was not
  released. Everything else stays `debug`.

### `README.md`

New, next to this log: how a run flows through the twenty-four functions, the
module-name-vs-stage-number trap, the two shared objects, the import direction,
the head/tail glue style, the five steps to add a stage, and the verification
block. It is the entry point; this log stays the history.

### What is left — read before the next scholarly task

* **`stage_11c_flux_image_loop` is 3,558 lines** of one `if`/`try` in
  `stages_37_54.py` and is **not** under any `func_len` gate. Task 3's log section
  explains why it could not be split by marker. It is the one real remaining
  structural debt of the chain.
* The `func_len` gate covers `pipeline_scholarly.py` (300) and `stages_55_73.py`
  (400) only. `stages_01_18.py`, `stages_19_36.py` and `stages_37_54.py` have
  never been under it.
* No stage was *run*. Every proof in this chain is static: `compileall`, `ruff`,
  `check_free_names.py`, `func_len.py`, `scan.sh`, and the normalised-body diff
  below. A scholarly pipeline run is a multi-hour GPU job and no task in the
  chain had the budget or the hardware claim for one.

## How the move is done

`ctx` is a `RunContext` (`context.py`), built in the prologue just before the
`try:` with the 22 locals the stages read from there, and carrying the 16 the
stages produce. 38 fields in total, all declared and all exercised.

Three things, and only these three, change in a moved statement:

1. **a local that crosses a stage boundary becomes `ctx.<name>`.**
2. **a local a nested `def`/`lambda` of the stage closes over is re-bound to a
   plain local at the top of the stage** (`topic = ctx.topic`), because a
   closure cannot capture an attribute. Four sites:
   `stage_05` re-binds `_debug`, `pipeline_id`, `topic` (read by the nested
   `_tag_sentence` and `_llm_scene_batch`), `stage_08` re-binds `_debug` (read
   by three lambdas). All four are read-only inside their stage, so the local
   and the field cannot drift apart.
3. **`__file__` became `_PKG_DIR`.** `os.path.dirname(__file__)` meant the
   `zyg_workflows` package directory; from this sub-package it would mean
   `zyg_workflows/scholarly`. Two sites: the
   `scholarly_research_agent.py` load in `stage_02` and the
   `m03_elder_gravel.wav` voice seed in `stage_08`.

### Where a pure move was not possible

* **`locals().get('_selected_essay_id')`, old line 2693.** Stage 3 read a Stage 2
  local *by string*, which no name analysis sees. It is now
  `ctx._selected_essay_id`, and `_selected_essay_id` is a `RunContext` field
  defaulting to `None` — the same thing `locals().get` returned when Stage 2's
  conditional assignment had not run. This is the one statement whose text
  changed beyond the three rules above.
* **Two nested `def`s are published on the context.** `_ollama_model_loaded`
  (old 2994-3000) and `_tag_sentence` (old 3444-3453) are defined inside
  Stage 3b and called by Stage 3.1 and by the still-inline code after Stage 9.
  They stay nested `def`s exactly where they were, with one added line after
  each — `ctx._tag_sentence = _tag_sentence` — rather than being hoisted to
  module level with a `ctx` parameter: hoisting would have had to rewrite their
  call sites and their closure, and the brief's "identical statements" wins.
* **Four locals are unpacked back out of the context** after the last stage
  call, because stages 10+ are still inline and read them as locals:
  `_sch_subject_type`, `_tag_sentence`, `narration_script`, `visual_tags`.
  The last task of the chain deletes those four lines when the last reader
  becomes a stage. Nothing else crosses: the aggregate `names` report for
  1647-4623 lists exactly these four as `crossing_out`, and `tts_duration` /
  `_final_word_timings` / `essay_text` are *not* among them because the
  rhythm-refresh stage re-reads them unconditionally out of `pipeline_state`.
* **`_zyg_log` keeps the monolith's logger name.** The stage module does
  `getLogger('zyg_workflows.pipeline_scholarly')`, not `getLogger(__name__)`,
  so the `suppressed …` debug lines of a run stay under one name.
* **Docstrings of nested helpers are re-indented.** The block indent went from
  8 to 4 and `ruff format` re-indents a docstring with its `def`. Three
  docstrings in `stage_03` / `stage_05` differ from the original by leading
  whitespace on their continuation lines. No non-docstring string constant
  differs by a single byte — checked, see below.
* **Eight imports left `pipeline_scholarly`.** `traceback`,
  `_align_narration_word_timings`, `_build_framework_block`,
  `_classify_subject_type`, `_tts_shared`, `_LLM_SCRIPT`, `_MURCH_MODEL`,
  `_murch_ollama_text` were used only by the moved statements; the stage module
  imports them from their own modules. Nothing outside imports them *through*
  `pipeline_scholarly` (only `_run_scholarly_pipeline` and
  `_render_kb_pil_shared` are imported from it, by the dashboard GUI and by
  `pipeline_storyteller`), so they were removed rather than `noqa`'d.

### Import direction

`pipeline_scholarly` imports the stage module **inside** `_run_scholarly_pipeline`;
the stage module imports `_SCHOLARLY_SEC_PER_WORD`,
`_research_title_matches_directive`, `_scholarly_n_images` and
`_title_from_directive` out of `pipeline_scholarly` at module level. Only one
of the two directions can be at module level or the cycle closes. Keep it this
way for the next modules.

## Two bugs fixed in `scripts/scholarly_split.py`

* **`col_offset` counts UTF-8 bytes, not characters.** `rewrite` sliced the line
  as a `str`, so every line holding an emoji or an em-dash — which is most of
  the logging in this pipeline — came out corrupted
  (`{pipctx.pipeline_id]}`). It now slices the encoded line.
* **`cut` dedents by a fixed column count, which eats the indentation inside
  triple-quoted strings** and so changes what the code does. Use the new `emit`
  instead: it keeps every line at its original column and makes the stage
  function's body indent 8, which `ruff format` then normalises to 4. There are
  113 multi-line string nodes in stages 1-9 alone.

## Proving the next move

```sh
T=/home/zygomatic/repos/.tools/venv/bin
$T/python scripts/scholarly_split.py markers src/zyg_workflows/pipeline_scholarly.py
$T/python scripts/scholarly_split.py names   src/zyg_workflows/pipeline_scholarly.py --start A --end B
$T/python scripts/scholarly_split.py verify  src/zyg_workflows/pipeline_scholarly.py \
    --start A --end B --name stage_NN_slug \
    --module src/zyg_workflows/scholarly/stages_01_18.py \
    --extra '_PKG_DIR=os.path.dirname(__file__)'
$T/python scripts/check_free_names.py
$T/python -m compileall -q src/zyg_workflows
```

`verify` reads the original from git, normalises `ctx.` back to bare names,
drops the `x = ctx.x` glue and dedents docstrings, and compares the two ASTs.
Nothing weaker than that is a proof that a move of this size changed nothing:
`compileall` and `ruff` both pass happily on a stage that silently lost a name,
and `check_free_names.py` only covers the names, not the order or the shape of
the statements.

`--extra` must spell the original expression **exactly**: the two `__file__`
sites do not share a spelling, so stages 1-7 and 9 want
`_PKG_DIR=os.path.dirname(__file__)` and `stage_08` wants
`_PKG_DIR=os.path.dirname(os.path.abspath(__file__))`. With those, **eight of
the nine report `EQUAL`.**

`stage_03_script_preparation` reports `DIFFER`, at exactly one statement, and
that is the `locals().get('_selected_essay_id')` rewrite described above —
`verify` has no `--extra` form for it, because `visit_Attribute` turns
`ctx._selected_essay_id` into a fresh `Name` that `visit_Name` never sees. The
diff to inspect by hand is:

```
-    _sel_id = pipeline_state.get('research_meta', {}).get('selected_essay_id') or locals().get('_selected_essay_id')
+    _sel_id = pipeline_state.get('research_meta', {}).get('selected_essay_id') or _selected_essay_id
```

One statement, one line, and nothing else in stage 3 differs. Confirm it that
way after any further edit to that stage rather than trusting the `DIFFER`.

Task 2's nine stages need no `--extra` and report **eight `EQUAL`**.
`stage_12_hand_qc` reports `DIFFER` for the two `if ctx.x is not UNSET:` glue
statements, which `_Normalise` has no rule for — it drops `x = ctx.x` but not an
`if` wrapped around one. Diffing the two normalised bodies by hand shows
exactly those two added statements and nothing else:

```
+if _sch_typography_pass is not UNSET:
+if _sch_hand_qc_pass is not UNSET:
```

The `glue dropped:` list `verify` prints is itself worth reading: it is the
set of crossings the stage declares, so a crossing you forgot shows up as a
name missing from it.

Grep a new range by hand for `locals(`, `vars(`, `globals(`, `eval(`, `nonlocal`
and `__file__` before trusting `names` — those are the crossings it cannot see.
(`nonlocal` joined that list in task 3; it is how `_prev_focal_zone` crosses.)

Task 3's three stages verify against these HEAD ranges — note they are **not** the
working-tree line numbers, `verify` filters the statements of the `HEAD` file:

```sh
$T/python scripts/scholarly_split.py verify src/zyg_workflows/pipeline_scholarly.py \
    --start 5827 --end 6784  --name stage_11_flux_prompt_batch  --module $M   # EQUAL
$T/python scripts/scholarly_split.py verify src/zyg_workflows/pipeline_scholarly.py \
    --start 6791 --end 7190  --name stage_11b_flux_preflight    --module $M   # DIFFER
$T/python scripts/scholarly_split.py verify src/zyg_workflows/pipeline_scholarly.py \
    --start 7191 --end 10729 --name stage_11c_flux_image_loop   --module $M   # EQUAL
```

`stage_11b_flux_preflight`'s `DIFFER` is the two `StageExit()` returns and
nothing else. `verify` prints a yes/no, so when it says `DIFFER` the thing to run
is the diff of the two normalised bodies, not a re-read of the range:

```python
import ast, difflib, subprocess, sys

sys.path.insert(0, 'scripts')
import scholarly_split as S

old = S._monolith(subprocess.run(['git', 'show', 'HEAD:' + P], capture_output=True, text=True, check=True).stdout)
old_body = [s for s in S._body_try(old).body if START <= s.lineno <= END]
new_fn = next(n for n in ast.parse(open(M).read()).body if getattr(n, 'name', '') == NAME)


def norm(nodes):
    tr = S._Normalise({})
    return ast.unparse(
        ast.fix_missing_locations(tr.visit(ast.parse(ast.unparse(ast.Module(body=list(nodes), type_ignores=[])))))
    ).splitlines()


print('\n'.join(difflib.unified_diff(norm(old_body), norm(new_fn.body), lineterm='', n=1)))
```

## Tasks 5-8 (2026-10) — `stage_11c_flux_image_loop` taken apart

The 2026-10-06 wave-1 attempt to split `stages_37_54.py` was reported
*impossible as briefed*: the file is one multi-thousand-line function with no
flat statement seam, and the recipe above only knows how to move whole
statements. The 2026-10 wave therefore changed the mandate from **move** to
**refactor**: nested closures may be hoisted to module-level functions with
explicit parameters, a `nonlocal` rebind may become a field on a dataclass that
is passed in, and a `return`/`break`/`continue` leaving a hoisted block may
become a sentinel the caller acts on. Nothing else: no statement changes what it
does, no side effect moves relative to another, no string literal changes, no
`try`/`except`/`finally` is dropped.

### The modules

| module | origin lines in `stages_37_54.py`@`0ed89dc` | contents |
| --- | --- | --- |
| `stages_37_54_flux_setup.py` | 599-613, 615-969, 971-987 | `setup_flux_prelude`, `setup_flux_pipes`, `setup_gates` |
| `stages_37_54_flux_loop.py` | 1018-1312, 1314-1582 | `run_slot_loop`, `finish_flux_stage` |

`stage_11c_flux_image_loop` went 1,128 lines → a 156-line skeleton, and the file
1,661 → 693 lines. The skeleton is: the 14-line `ctx` glue head, the
`if _flux_ready or _sch_comfy_only:` test and the GPU-lock claim (verbatim), the
four calls, and then the **unchanged** `except Exception as _flux_err:` /
`finally:` / `else:` / `ctx`-tail.

### Why the error path stayed behind

`except Exception as _flux_err` logs the failure and falls back to Wikimedia
images; `finally` releases the GPU lock — but only if the FluxWorker did not
take it over. That ordering *is* the stage's contract with the rest of the run,
and it reads six locals the moved blocks rebind. Moving it would have put a lock
release behind one more call boundary for no gain, so it stayed verbatim and the
six names are carried to it instead:

* `_flux_generated_paths`, `_flux_image_meta`, `_sch_family_label`,
  `_sch_fw_active`, `_flux_pipe` — fields of `FluxLoopState` (`fs`);
* `_sch_gpu_lock_held` — *not* an `fs` field (the file is not owned by this
  task), so it travels on `ctx._sch_gpu_lock_held`. Verified by grep that no
  stage after `stage_11c` reads that field, so adding a writer is inert.

Each is mirrored **at its rebinding site** by a chained assignment
(`_flux_pipe = fs._flux_pipe = …`), not collected at the end, so a mid-flight
exception still leaves the error path a true view. The skeleton then refreshes
its own locals in a nested `finally:` — the four calls were one frame in the
monolith, and a `finally` is the only place that sees "wherever that frame got
to".

### Non-mechanical spots

* **`setup_flux_prelude` is a third function and not part of `setup_flux_pipes`.**
  Origin lines 599-613 sit *between* the outer `try:` (598, which has only a
  `finally`) and the inner `try:` (614, which owns the `except Exception as
  _flux_err`). A failed `import torch` or a refused GPU-exclusivity check was
  never swallowed as "FLUX generation failed"; folding the prelude in would have
  started swallowing it. It takes no `fs` — `fs` does not exist yet — and
  returns the three names that cross: `(_torch_flux, _sch_family_label,
  _FluxPipeline)`.
* **`_FluxPipeline` crosses as `UNSET`, then as an explicit parameter.** On the
  Comfy-only path diffusers is never imported and `from_pretrained` is never
  reached, so the name was legitimately unbound. It is not a `FluxLoopState`
  field (that file is not owned here), so the prelude returns `UNSET` for it and
  `setup_flux_pipes(fs, ctx, _FluxPipeline)` takes it as its third argument.
* **`_flux_pipe=UNSET` in the skeleton's `FluxLoopState(...)`** is what the
  monolith's `del _flux_pipe` / `except NameError` pair tested. `fs` is built in
  the skeleton rather than returned by `FluxLoopState.capture` at the end of the
  setup precisely because the error path reads it: a GPU lock handed to the
  FluxWorker half-way through the setup must not then be released twice.
* **`capture` is applied in place, field by field.**
  `FluxLoopState.capture(locals())` returns a *new* instance, but `fs` must be
  the object the skeleton already holds, so `setup_flux_pipes` ends with
  `_captured = capture(locals())` and copies every field that is not in
  `_GATE_FIELDS` onto `fs` — the gate fields are `init_gate_state`'s and must
  keep their values. Side effect, deliberate and the only reorder in the task:
  `capture`'s "left at default" debug line now fires *before* the lazy
  `stages_37_54_flux_qa` import in `setup_gates` instead of after it. Both are
  pure.
* **`import gc as _gc_flux` became a module-level alias** in both new modules.
  The statement sat mid-block and both halves need the name; `gc` is interpreter
  state, so importing it earlier has no observable effect.
* **Four dead rebinds dropped.** `_era_ladder_qualifier`,
  `_mediapipe_qa_score`, `_record_slot_review`, `_vlm_render_gate` and the
  local re-binds at origin 998-1012 existed only to re-point names inside the
  frame that no longer exists; grep proved nothing remaining reads them and the
  bindings have no side effects.
* **`controlnet_service` keeps a `# noqa: F401`** in `setup_flux_pipes`: its
  reader is `finish_flux_stage`, which reaches it as `fs._cns`.
* **No `nonlocal` is left in any `stages_37_54*.py`** — the whole point of `fs`.

### Import direction, again

The new stage modules import helpers and constants from `stages_37_54` at module
level; `stages_37_54` imports *them* lazily, inside
`stage_11c_flux_image_loop`. Reversing either direction is an import cycle.
`stages_37_54_flux_qa` is still imported inside `setup_gates` for the same
reason it was imported inside the monolith: it is only reachable from the two
closures published on `ctx`, which run long after the stage returns.

### What proved it

No pipeline was run — the proof is static:

```sh
wc -l src/zyg_workflows/scholarly/stages_37_54*.py   # every one <= 800
! grep -n nonlocal src/zyg_workflows/scholarly/stages_37_54*.py
uv run --no-sync python -m py_compile src/zyg_workflows/scholarly/stages_37_54*.py
uv run --no-sync ruff check src/zyg_workflows/scholarly
uv run --no-sync python scripts/check_free_names.py
uv run --no-sync pytest -q -m "not gpu and not service" tests/test_scholarly_motion.py
(cd ../.. && python3 scripts/modcheck.py check)
```

`check_free_names.py` is necessary but *not sufficient* here: its first check
only walks top-level blocks whose name starts with `stage_`, so a global lost
out of `setup_flux_pipes` or `run_slot_loop` would not have been seen. Both new
modules were additionally walked with `symtable` by hand, looking for a free
name that resolves to no module global and no builtin — zero in each.

`src/zyg_workflows/settings.py` is generated and its per-setting file tuples now
point at `stages_37_54.py` for `ZYG_…` reads that live in the new modules. It is
*deliberately* not regenerated here; the wave's gate task regenerates it once.
