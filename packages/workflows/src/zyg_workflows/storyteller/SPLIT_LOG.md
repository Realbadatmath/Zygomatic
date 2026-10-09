# Splitting `_run_storyteller_pipeline` — log

`zyg_workflows.pipeline_storyteller._run_storyteller_pipeline` was one function
of 3,443 lines in a 3,791-line file. The chain moves each top-level
`# ── Stage N …` block into a `stage_<nn>_<slug>(ctx)` function in this package
and leaves the driver as the prologue, an ordered list of stage calls, and the
`try/except/finally` around the run. It follows the recipe of
`scholarly/SPLIT_LOG.md` and `scholarly/README.md` — read those first.

**Why this file is not a verbatim-move split.** The 2026-10-06 wave-1 attempt
failed as "impossible as briefed" because the file is one multi-thousand-line
function with no flat seams at module level. The seams are *inside* the
function: the nine ranges `scholarly_split.py markers` prints are a flat
statement sequence in the stage `try:` body, and that is what this chain cuts.

## Task A of 2 — done 2026-10-08

Moved **eight** of the nine markers into five modules. Stage 3.5 (the FLUX image
loop, marker 6) stays inline, so `_run_storyteller_pipeline` went
**3,443 → 1,641** lines and the file from **3,791 → 1,987**.

| fn | module | HEAD lines | marker |
|---|---|---|---|
| `stage_01_character_prep` | `stage_01_character_prep.py` | 534-914 | Stage 1: Character Prep |
| `stage_02_scene_budget` | `stages_02_story_script.py` | 916-1040 | Stage 2: Story Script (Claude) |
| `stage_02a_sonnet_story` | `stages_02_story_script.py` | 1044-1359 | Stage 2a: Sonnet — story arc, narration, visual concept |
| `stage_02b_render_prompts` | `stage_02b_render_prompts.py` | 1365-1622 | Stage 2b: Claude — visual_concept → FLUX prompt |
| `stage_03_tts` | `stages_03_05_tts_assembly.py` | 1624-1710 | Stage 3: TTS Narration |
| `stage_04_ken_burns` | `stages_03_05_tts_assembly.py` | 3097-3216 | Stage 4: Ken Burns + Assembly |
| `stage_05_final_assembly` | `stages_03_05_tts_assembly.py` | 3218-3332 | Stage 5: Final Assembly |
| `stage_05b_burn_subtitles` | `stage_05b_subtitles.py` | 3334-3777 | Stage 5b: Burn subtitles |

Line numbers are those of commit `770c30a`, which is what
`scholarly_split.py verify --ref HEAD` compares against. Every one of the eight
reports **`EQUAL`** — the moved bodies are AST-identical to the original, with
only the declared `n = ctx.n` / `ctx.n = n` glue dropped. Nothing else changed:
no statement reordered, no string literal touched, no `try`/`except`/`finally`
dropped.

### Stage 2b got its own module after all

The brief put stages 2, 2a and 2b in one `stages_02_story_script.py` with "if it
lands over 800 move stage_02b to its own module". The three ranges are 125 + 316
+ 258 lines and the glue, the header and the imports add ~50: **~790**, which is
inside the hard cap by ten lines and would be broken by the next comment anyone
adds. So 2b is `stage_02b_render_prompts.py` (305 lines) from the start and
`stages_02_story_script.py` is 503. No module in the package exceeds 503 lines.

### Stage 3.5 is still inline — the three glue lines that say so

Marker 6 (lines 1712-3095, 1,384 lines) is the one range task A left in the
driver, so the driver still needs five of the other stages' locals as **plain
locals** and publishes one of its own back onto the context:

```python
stage_01_character_prep(ctx)
lora_path = ctx.lora_path            # Stage 3.5 reads and then rebinds it
trigger_token = ctx.trigger_token
…
stage_02b_render_prompts(ctx)
n_scenes = ctx.n_scenes
scenes = ctx.scenes
…
# ── Stage 3.5: FLUX Image Generation  (still inline, 1,384 lines)
ctx.img_paths = img_paths            # what Stage 4 reads
stage_04_ken_burns(ctx)
```

Four unpacks and one store. Task B deletes all five when Stage 3.5 becomes a
stage. `character_params` and `era_str` are *not* unpacked: `names` lists them
as crossing out of stage 1 / into stage 2a, but nothing after line 1710 reads
either one (checked by hand — the grep is in the next section).

### Why `ImageGenState` exists but is empty

`context.py` declares it for task B. Stage 3.5's five nested `def`s rebind seven
of the loop's locals through `nonlocal` (lines 1830, 1838 and 2171 of `770c30a`:
`_flux_i2i_pipe`, `_use_dev_st`, `_st_lora_loaded`, `_st_lora_active`,
`_ipa_ready_st`, `_ipa_svc_st`, `_flux_model_path_st`), and **a `nonlocal`
cannot reach a field of a context object** — which is exactly why this range
cannot be moved the way the other eight were. Hoisting those helpers means
replacing the `nonlocal` rebinding with writes to fields on a small mutable
object passed in. It is left empty on purpose: the fields should be derived from
the move, not guessed ahead of it. They do not belong on
`StorytellerContext` — they never cross a *stage* boundary, they are the private
state of one loop. `scholarly` draws the same line between `RunContext` and
`RunGlue`.

### The four blind spots, all swept, all clean

The `names` report cannot see these; `scholarly/SPLIT_LOG.md` lists them and
each was checked by hand on this file:

1. **`locals()` / `vars()` / `globals()` / `eval()`** — grep finds **none** in
   the whole file.
2. **`__file__`** — **none**. No `__file__`-derived constant had to be
   re-anchored, so no `--extra` was needed on any `verify` run.
3. **`nonlocal`** — four sites, all at lines 1830-2171, i.e. all *inside* Stage
   3.5, which stays inline. None of the eight moved ranges declares one.
4. **"first use after the range is a store" hides a real crossing.** The sweep
   `loose = (in_stored & post_loaded) - crossing_out` printed five names across
   the eight ranges: `_cbs_st`, `_w`, `_sc`, `_si`, `_exc`. All five are false
   positives, each re-bound before every later read — `_cbs_st` by its own
   `from … import … as _cbs_st` at 2426, `_sc` by `for _sc in scenes` at 1478,
   `_si` by `for _si, scene in enumerate(scenes)` at 2420, `_w` by `for _w in
   _words` at 3373, `_exc` by its own `except … as _exc` (the known one).

A fifth sweep, not in the scholarly log, was worth running here: **every nested
`def` mapped to the range that defines it and the ranges that call it.** All
twelve are called only from inside their own range, so no stage publishes a
closure on the context and the `_build_image_prompt` problem scholarly hit does
not arise.

### Where a pure move was not possible

Nowhere. All eight ranges are `EQUAL`. The only edits outside the moved bodies:

* **Nine imports left `pipeline_storyteller.py`** with their only users:
  `_record_token_usage`, `_char_is_blender_dataset`,
  `_pick_char_preview_reference`, `_align_narration_word_timings`,
  `_render_kb_pil_shared`, `_synthesise_tts`, `_caveman_kw`, `_dsl`, `exe`
  (ruff F401). Checked first that nothing imports them *through* this module:
  the only name anything imports from `pipeline_storyteller` is
  `_run_storyteller_pipeline` (the dashboard's
  `crewai_web_gui/registration.py`).
* **`_seal` stayed, with a `# noqa: F401`.** The seal *call* moved to
  `stage_05b_subtitles.py`, so the driver no longer uses the binding — but
  `tests/test_storyteller_seal.py::test_pipeline_storyteller_imports` asserts
  `P._seal is provenance_seal` as its cheap "the hooked module still imports"
  proof. The comment above the import says so.
* **`_zyg_log` keeps the driver's logger name** in the three stage modules that
  log through it: `getLogger('zyg_workflows.pipeline_storyteller')`, not
  `getLogger(__name__)`, so a run's lines stay under one channel. Same choice
  `scholarly` made.
* **The `# ── Stage N …` banner is the first line of every stage body**, with
  the explanatory comments that followed it. The emitted ranges therefore start
  at the banner line (533, 915, 1041, 1360, 1623, 3096, 3217, 3333) rather than
  at the first statement; the intervening lines are comments only, so the
  statement set `verify` compares is unchanged.

### `tests/test_storyteller_seal.py`

The parametrized hook pair became
`('storyteller/stage_05b_subtitles.py', 'stage_05b_burn_subtitles')`, and the
expectation is now `f'OK {os.path.basename(module)}:{func}'` because
`check_seal_hooks.py` prints `path.name`. The second pair and both runtime
tests are untouched. Note that `check_seal_hooks.py`'s Pattern-A fallback does
*not* apply here: `pipeline_storyteller.py` still exists, so pointing the
checker at it would parse only the driver and report `MISSING`.

### Verification — all static

No pipeline was run; a storyteller episode is a multi-hour GPU job.

```sh
cd packages/workflows
uv run --no-sync python scripts/scholarly_split.py markers \
    src/zyg_workflows/pipeline_storyteller.py --func _run_storyteller_pipeline
uv run --no-sync python scripts/scholarly_split.py verify \
    src/zyg_workflows/pipeline_storyteller.py --func _run_storyteller_pipeline \
    --start 534 --end 914 --name stage_01_character_prep \
    --module src/zyg_workflows/storyteller/stage_01_character_prep.py --ref 770c30a
uv run --no-sync python scripts/check_free_names.py \
    --stage-dir src/zyg_workflows/storyteller \
    --monolith src/zyg_workflows/pipeline_storyteller.py \
    --func _run_storyteller_pipeline --stage-glob stage \
    --context-class StorytellerContext
uv run --no-sync ruff check src/zyg_workflows/storyteller src/zyg_workflows/pipeline_storyteller.py
uv run --no-sync pytest -q -m "not gpu and not service" tests/test_storyteller_seal.py
cd ../.. && python3 scripts/modcheck.py check
```

`check_free_names.py` needs **`--stage-glob stage`** (not its `stages_`
default), because four of the five modules here are named `stage_*` rather than
`stages_*`. With the default it finds no stage module and fails.

### What task B inherits

* **Stage 3.5, marker 6, lines 1712-3095 of `770c30a`** (now at the same place
  in a 1,641-line function). Five nested `def`s, seven `nonlocal` names, the
  `ImageGenState` stub waiting for them. It is a much smaller job than it looks:
  the in/out contract is already declared — `names` reports its crossings as
  `_animated_render`, `_check_stop`, `_log`, `_restyle_caption_prefix`,
  `_restyle_render`, `_save`, `_update_stage`, `char_id`, `job`, `model_family`,
  `n_scenes`, `out_dir`, `pipeline_id`, `pipeline_state`, `scenes`,
  `trigger_token`, `visual_style` in, `lora_path` in-and-rebound, and
  `img_paths` out.
* **The four unpacks and the one `ctx.img_paths` store** in the driver go with
  it, and the driver should land near 150 lines.
* **`src/zyg_workflows/settings.py` is stale.** It is generated by
  `scripts/gen_settings.py` and its per-flag file tuples still name
  `src/zyg_workflows/pipeline_storyteller.py` for flags whose
  `os.environ.get('ZYG_…')` read moved into this package —
  `ZYG_SDXL_COMFY_MIN_VRAM_GB`, `ZYG_ST_DUPE_CORR`, `ZYG_ST_EXTRA_PROMPT_MAX`,
  `ZYG_IMG2IMG_MIN_VRAM_GB`, `ZYG_LORA_PIPELINE_WAIT_S` and the rest. Task A
  deliberately did not regenerate it (parallel tasks would conflict); the
  tree's final gate task regenerates once.

## Task B of 2 — done 2026-10-08

Stage 3.5 (marker 6) is out. The driver went **1,987 → 590** lines and
`_run_storyteller_pipeline` is now the prologue, `ctx = StorytellerContext(…)`,
nine stage calls, `except`/`finally`. No module in the package exceeds 503
lines (Stage 3.5's largest is 439).

This is a **refactor, not a move**, so `scholarly_split.py verify` is not
applicable — it compares statement sets of one flat range against one function
body, and five closures became five functions with explicit parameters. The
proof is the two multiset diffs at the end of this section.

### The range

Line numbers below are those of commit `770c30a` + task A, i.e. the 1,987-line
driver this task started from. Stage 3.5 was **lines 584-1967** — 1,384 lines,
the entire body of the big `try:` — plus the `ctx.img_paths = img_paths` store
that followed it.

### Six modules, not the five the brief named

| module | lines | contents |
|---|---|---|
| `stage_035_image_gen.py` | 367 | `stage_035_image_generation(ctx)` — the whole skeleton |
| `stage_035_backend.py` | 360 | `prepare_flux_paths`, `wait_for_vram`, `load_flux_diffusers`, `select_backend`, `_STYLE_PREFIX_ST` |
| `stage_035_scene_loop.py` | 439 | `generate_scene(ctx, st, _si, scene)` — one iteration of the per-scene `for` |
| `stage_035_generate.py` | 302 | `generate_one(ctx, st, …)` |
| `stage_036_anatomy.py` | 116 | `stage_036_anatomy_repair(ctx, st)` |
| `stage_035_qa.py` | 101 | the three QA helpers |

The brief named five and put `generate_scene` in `stage_035_image_gen.py` ("the
per-scene loop if it fits") or implicitly in `stage_035_generate.py`. Neither
fits the 300-600 aim: `generate_one` is ~290 lines of body and the loop body is
~390, so one module holding both lands at ~720 — under the hard 800 cap but
well past the aim, and `stage_035_image_gen.py` with the loop inlined would be
~760. Hence the sixth module. **No `break`, `continue` or `return` crosses the
`generate_scene` boundary** (checked with an AST walk that ignores nested
`def`s/loops), so no `StageExit`-style sentinel was needed; the module's
docstring records both facts.

### Which closure became which function

Five nested `def`s were hoisted to module level. Every one keeps its body
statement-for-statement; the only change is that names it used to close over
arrive as `ctx`, `st` or a parameter.

| closure (driver lines) | became | module |
|---|---|---|
| `_st_load_flux_diffusers(load_ipadapter=True)` (701-798) | `load_flux_diffusers(ctx, st, *, load_ipadapter=True) -> bool` | `stage_035_backend.py` |
| `_st_mediapipe_hand_qa(image_path)` (927-963) | `mediapipe_hand_qa(ctx, st, image_path)` | `stage_035_qa.py` |
| `_st_scene_quality_ok(img_path)` (965-983) | `scene_quality_ok(ctx, st, img_path) -> bool` | `stage_035_qa.py` |
| `_st_scene_quality_reason(img_path)` (985-992) | `scene_quality_reason(ctx, st, img_path) -> str` | `stage_035_qa.py` |
| `_st_generate_one(prompt, path, init_img=None, *, …)` (1028-1290) | `generate_one(ctx, st, prompt, path, init_img=None, *, …)` | `stage_035_generate.py` |

The leading underscore is dropped (the brief allows the rename); the keyword-only
tail of `generate_one` (`seed_attempt`, `scene_index`, `shot_type`,
`scene_emotion`) is unchanged. `_run_pipe` inside `generate_one` stays a nested
`def` — it closes over that call's arguments, not over the loop's state.

Four straight-line spans also became functions, which is a split rather than a
hoist: `prepare_flux_paths(ctx, st) -> float` (629-654, returns the
`_min_vram_gb` it computes), `wait_for_vram(ctx, _min_vram_gb)` (656-699, with
its own try/except intact), `select_backend(ctx, st)` (800-923) and
`generate_scene(ctx, st, _si, scene)` (1294-1679). `stage_036_anatomy_repair`
(1681-1762) is the `if _st_image_meta:` HandFixer block, including its own
`_update_stage('Stage 3.6 — Anatomy Repair', 58)` and the `'stopped by user'`
re-raise.

### Which `nonlocal` became which field

`ImageGenState` in `context.py` was declared empty by task A; it now has 26
fields. The rule applied: **a name rebound inside a hoisted function lives on
`st`; a name only read may be a parameter or come off `ctx`/`st`.**

| old `nonlocal` (lines 1830 / 1838 / 2171 of `770c30a`) | field |
|---|---|
| `_flux_i2i_pipe` | `st._flux_i2i_pipe` |
| `_use_dev_st` | `st._use_dev_st` |
| `_ipa_ready_st` | `st._ipa_ready_st` |
| `_ipa_svc_st` | `st._ipa_svc_st` |
| `_ipa_ref_path` | `st._ipa_ref_path` |
| `_st_lora_loaded` | `st._st_lora_loaded` |
| `_char_ref_img` | `st._char_ref_img` |

Rebound across the hoist boundary but never `nonlocal` (they were rebound only
in the outer scope and read in the inner one, or vice versa):
`_st_lora_active`, `_flux_model_path_st`, `lora_path`, `_st_comfy_primary`,
`_st_use_flux_diffusers`, `_st_comfy_available`, `img_paths`, `_st_image_meta`.
Read-only handles and products that more than one module needs:
`_torch_st`, `_FluxPipeline`, `_flux_dev_path_st`, `_flux_schnell_path`,
`_style_prefix_st`, `_qc_style_st`, `_hand_qc_style_skip`, `_st_blender_ds`,
`_st_drift_ref_ok`, `_ssh_st`, `_hand_qa_fn`.

Every rebound field is read as `st.X` **inline, never unpacked into a local**,
so a stale read is impossible. The never-rebound ones are unpacked at the top of
each function for readability, exactly as the other eight stages unpack `ctx`.

Two decisions worth recording:

* **`lora_path` is on `st`, not on `ctx`.** Stage 3.5 rebinds it (lines 815 and
  832) and in the monolith that rebinding never reached Stage 4 — it was a
  block local. Putting it on `ctx` would have leaked it forward. `st` is
  initialised with `lora_path=ctx.lora_path` and the four task-A unpacks in the
  driver are gone.
* **`st._hand_qa_fn = functools.partial(mediapipe_hand_qa, ctx, st)`, bound
  once.** `_st_mediapipe_hand_qa` was passed into `scene_still_helpers` as
  `hand_qa_fn=`; grepped first to confirm it is only ever *called*
  (`hand_qa_fn(img_path)`) and never used as a dict key or compared, then bound
  a single partial so every call site shares one object, as the closure did.
* `_hand_qc_style_skip` is a one-element list because the original was a lazily
  initialised one-shot flag read and written from two scopes.

### The module graph is acyclic

`image_gen → {backend, qa, scene_loop, anatomy}`, `scene_loop → {generate,
qa}`, `generate → {backend}` (the Comfy-failure path calls
`load_flux_diffusers(ctx, st, load_ipadapter=False)`). Every one of the six
imports helpers and constants from `pipeline_storyteller` at module level and
the driver imports them lazily inside the function — the package rule from
`__init__.py`. Verified with a live import of all six.

### The proof — two AST multiset diffs

`git show HEAD:./src/zyg_workflows/pipeline_storyteller.py` lines 584-1967,
`textwrap.dedent`-ed and parsed, against the six new modules parsed:

1. **String literals** — original **561**, new **563**. MISSING **4**: the four
   hoisted closures' own docstrings, same text, re-indented from a 12-space to a
   4-space continuation and therefore skipped by the new side's docstring
   filter. EXTRA **6**: `'zyg_workflows.pipeline_storyteller'`, the `getLogger`
   channel, once per module. **Zero behavioural differences** — no prompt, no
   log line, no path, no flag name changed.
2. **Call names** (dotted, with the `st.` / `ctx.` receiver prefix stripped and
   the five renames above applied) — original **384**, new **397**. **MISSING
   0** — every call the monolith made is still made. EXTRA **13**, exactly the
   hoist scaffolding: `ImageGenState` ×1, `_zyg_logging.getLogger` ×6,
   `functools.partial` ×1, and one call each to `generate_scene`,
   `prepare_flux_paths`, `select_backend`, `stage_036_anatomy_repair`,
   `wait_for_vram`.

Plus the static gates: `ruff check` clean (F821 included — `ruff.toml` selects
`F`), `py_compile` on all seven files, `check_free_names.py` (`OK 10 stage
functions in 11 module(s)`, `OK 53 ctx fields read, all written or
constructed`, `OK _run_storyteller_pipeline resolves every global it reads`),
`check_seal_hooks.py` still `OK stage_05b_subtitles.py:stage_05b_burn_subtitles`,
`tests/test_storyteller_seal.py` 5 passed 1 skipped, and `modcheck.py check`
clean. **No pipeline was run** — a storyteller episode is a multi-hour GPU job
and there is no behavioural test.

### One deliberate behavioural nuance

In the monolith, if the big `try:` raised *before* `import torch as _torch_st`,
the post-`with` cleanup's `_torch_st.cuda.empty_cache()` raised **NameError**.
`st._torch_st` now defaults to `None`, so the same line raises
**AttributeError**. Both are caught by the same `except Exception as _ue` and
produce the same f-string log line; only the interpolated exception text
differs. Nothing branches on the type.

### `settings.py` is still stale — five more flags

Task A's note stands and this task adds to it. Env reads that changed file:
`ZYG_SDXL_COMFY_MIN_VRAM_GB` and `ZYG_IMG2IMG_MIN_VRAM_GB` →
`stage_035_backend.py`, `ZYG_ST_IPADAPTER_DIFFUSERS` →
`stage_035_backend.py`, `ZYG_ST_PORTRAIT_FRAME_FALLBACK` →
`stage_035_scene_loop.py`, `ZYG_ST_IDQC_REQUIRE_ANCHOR` →
`stage_035_image_gen.py`. Not regenerated here, for the same reason: the
tree's final gate task runs `gen_settings.py` once.
