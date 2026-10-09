# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""capability_tests — the DEFAULT test behind each Metrics > Capabilities sheet. 2026-09-28.

Why this package exists
-----------------------
A capability sheet (capabilities_hub.py) asks 118-126 questions of every model in a step
and, on 2026-09-28, 0.6 % of the cells carry an answer. The questions are fixed
(capabilities_questions.py); what was missing is the TEST — the exact inputs, settings,
scoring rule and thresholds that turn a question into a measured cell. Without a stored
test, two models are never compared under the same circumstances, and a new model would be
"tested" by whoever happened to be at the keyboard, with whatever prompt came to mind.

One module per step, `capability_tests/<step>.py`, exposes `TEST`: the default test for
that step. `capabilities_tests.py` (one level up) loads it, merges the shared text bank,
validates it against the step's questionnaire and prints its content hash. A sheet written
from a run records that hash; sheets with different hashes are different tests and must
never be read side by side as if they were one.

The contract — what "forces an honest answer"
---------------------------------------------
1. EVERY column the step asks (DOMAIN + BANKS + UNIVERSAL) has exactly ONE disposition:
     probe    a fixed trial whose scoring rule produces the state   → grade measured
     derive   computed from the run's own telemetry or ledger       → grade measured/receipt
     lookup   a documented fact with a pinned source and revision   → grade vendor/receipt
     wiring   read off the code path, never run                     → grade assumed (visible)
     na       not applicable to this row/step, with a written reason
   The validator REFUSES a test that leaves a column without a disposition, or gives it two.
   "I did not think of that question" is therefore impossible; "not applicable, because…" is
   allowed and shows on the sheet as `na` with its reason.
2. Inputs are stored VERBATIM here — prompts, system prompt, temperature, seeds, repeats,
   token caps, fixture files. A runner may not paraphrase, shorten or "improve" them. A new
   model is tested with byte-identical inputs to the last one.
3. Scoring is MECHANICAL wherever a machine can decide (JSON parses, word count in range,
   banned term absent, answer equals key). Where a human must decide, the check is marked
   `operator` and is BLIND: outputs are anonymised and shuffled before the operator sees
   them, and the question the operator answers is written here, not improvised.
4. Thresholds live in the test (`state_rule`), never in the runner: pass rate ≥ yes → yes,
   ≥ partial → partial, else no. Repeats are fixed; the FIRST repeat is what `first_take`
   reads ([[feedback_first_take_not_retries]]).
5. A model that answers is scored. An EMPTY or malformed answer is a `no` on every column
   that trial feeds — it is what the model did under the test. A TRANSPORT failure
   (connection refused, timeout, quota refusal) is `untested` with the error as the note:
   the model was not heard, so nothing is claimed about it either way.
6. A run never writes grade `assumed`. `wiring` cells are written by the validator from
   this file, marked assumed, so they can be told apart from anything a model produced.
7. Every raw output goes into the sheet's Inspect document (`trials`), so any cell can be
   checked against the text that produced it. A cell without its trial is not written.
8. A fixture whose answer key is not `verified` blocks the columns it feeds: they are
   written `untested` with the note "key unverified" until the operator flips the flag.
   We do not grade a model against an answer we have not checked ourselves.

Check vocabulary (`CHECK_KINDS`)
--------------------------------
Every probe's `checks` use only these kinds, so the runner is a table of small functions
and a test cannot smuggle in a rule the runner does not implement. Add a kind here first.
"""

from __future__ import annotations

CHECK_KINDS = {
    # ── output form ──
    'json_valid': 'json.loads succeeds on the whole output (no fences, no prose)',
    'json_keys': 'top-level keys == `keys` exactly',
    'json_schema': 'output validates against `schema` (types, required, nested)',
    'starts_clean': 'first non-blank line does not start with a term in `banned` (preamble)',
    'ends_clean': 'last non-blank line does not contain a term in `banned` (sign-off)',
    'line_count': 'non-blank lines between `min` and `max`',
    'lines_alternate': 'every line starts with one of `speakers` and no speaker speaks twice in a row',
    # ── quantity ──
    'word_count': 'words between `min` and `max`',
    'sentence_max_words': 'no sentence longer than `max` words',
    'max_word_len': 'no word longer than `max` letters',
    'digits_absent': 'no digit characters anywhere',
    'clip_tokens_max': 'CLIP tokens (tokenizer pinned in `tokenizer`) <= `max`',
    # ── content ──
    'present': 'every term in `terms` occurs (case-insensitive, word boundary)',
    'present_any': 'at least one term in `terms` occurs',
    'absent': 'no term in `terms` occurs',
    'regex_present': '`pattern` matches at least once',
    'regex_absent': '`pattern` never matches',
    'proper_nouns_allowlist': 'every capitalised mid-sentence word is in `allow` (or a common English/Dutch word)',
    'equals_key': "normalised answer is in the key's `accept` set (lowercase, articles stripped, number words → digits)",
    'language': 'stopword ratio for `lang` (nl|en) >= `min` (default 0.6)',
    'operator': 'BLIND human decision: `question`, answered yes/no per trial',
    # ── across runs ──
    'identical_runs': 'all repeats of the trial are byte-identical after whitespace strip',
    'similarity_min': 'difflib ratio to `to` (a trial id) >= `min`',
    'similarity_max': 'difflib ratio to `to` >= `max` fails (outputs must differ)',
    'pairwise_similarity_max': 'every pair of repeats has ratio < `max`',
    'same_as_key_across': 'equals_key holds for every variant listed in `variants`',
    # ── agents & files ──
    'file_exists': '`path` exists in the sandbox after the task',
    'file_absent': '`path` does not exist after the task',
    'file_absent_term': 'no file under the sandbox contains `term`',
    'pytest_passed': "the runner's OWN pytest call passes after the task",
    'diff_touches_only': 'git diff touches only paths matching `paths`',
    'transcript_contains': 'the agent transcript contains `pattern` (regex)',
    'transcript_absent': 'the agent transcript never matches `pattern`',
    'report_matches_reality': "the agent's final JSON report fields equal what the runner measured",
    'log_contains': 'fixture tool log `path` contains `pattern`',
    # ── research ──
    'url_resolves': 'every cited URL answers 200 within 20 s',
    'url_domain_in': 'at least one cited URL has a host in `domains`',
    'url_page_contains': 'a cited page contains `term` (case-insensitive)',
    # ── subtitles ──
    'wer_max': 'word error rate against the verified transcript <= `max`',
    'timing_abs_ms': 'for the verified words, |cue start - truth| <= `max` for >= `share` of them',
    'cue_rule': 'every cue obeys `min_dur`, `max_dur`, `gap`, `max_lines`, `max_cpl`, `max_cps` (whichever are set)',
    'cue_no_cross': 'no cue spans a timestamp in `cuts` by more than `tolerance` s',
    'parses_as': 'file parses as `format` (srt|vtt) with a strict parser',
    'ocr_matches': 'OCR of burned frames at `sample` cue midpoints equals the sidecar text (>= `share`)',
}

DISPOSITIONS = ('probe', 'derive', 'lookup', 'wiring', 'na')

# Grades a disposition may write. Anything else is a validator error.
DISPOSITION_GRADES = {
    'probe': ('measured',),
    'derive': ('measured', 'receipt', 'vendor', 'assumed'),  # takes the LOWEST grade of its inputs
    'lookup': ('vendor', 'receipt'),
    'wiring': ('assumed',),
    'na': (),
}

# Default thresholds on pass rate. A probe may override with its own `state_rule`.
STATE_RULE = {'yes': 0.8, 'partial': 0.4}

# Transports a row can be driven through. The runner implements exactly these.
TRANSPORTS = {
    'ollama': 'POST /api/generate via llm_audit.ollama_generate (logged); options carry temperature and seed',
    'anthropic_api': 'anthropic SDK messages.create with ANTHROPIC_API_KEY; llm_audit.install() wraps it',
    'claude_cli': 'headless `claude -p --model <m>` on the operator LOGIN via subscription_llm.SubscriptionClient; no temperature, no seed',
    'github_models': 'OpenAI-compatible chat completions against GitHub Models with the registry token',
    'builtin': 'a deterministic in-house builder; called as a function, no prompt',
    'pipeline': 'a house pipeline stage; called on a fixture file, no prompt',
}

# Transports added 2026-09-30 for the non-text steps. A shared bank (`<kind>_shared.py`) or a
# step module may add its own in a module-level `TRANSPORTS` dict; the validator unions them
# and lists the additions in its summary so the runner author sees what must be implemented.
TRANSPORTS.update(
    {
        'comfy': 'a ComfyUI workflow JSON (the row names the file) queued through the house comfy client on a fixed seed; NEVER imported into the GUI process',
        'service': 'a house python service module called as a function on a fixture (the row names module and function)',
        'blender': 'headless `blender -b --python <script>` on a fixture .blend/.glb; the script is the fixed input',
        'ffmpeg': 'an ffmpeg filter graph on a fixture file; the command line is the fixed input',
        'vlm_ollama': 'an image plus a question through ollama /api/generate (images field); temperature and seed in options',
        'vlm_inspector': 'vlm_inspector.py resident/boundary model (Qwen3-VL); the question text is the fixed input',
        'library': 'a lookup in a house asset library (query in, ranked items out); no generation',
        'retired': 'a row kept for its historical receipt (retired, superseded, removed, never used); the runner skips it and writes untested "retired" on every column — the row carries `skip` with the reason',
    }
)

# The kinds a step may `include_shared`: `capability_tests/<kind>_shared.py` exposes SHARED with
# probes/derive/lookup/wiring/na/transport_na over the columns every step of that kind asks
# (the subject banks, capacity, counting/spatial/attributes, the prompt bands, universal).
# A step may include several, in order; the first that owns a column wins.
SHARED_KINDS = ('text', 'image', 'video', 'audio', 'judge', 'geometry')

# BUDGET (2026-09-30) — every TEST carries what it is expected to COST before anyone runs it,
# per row, so the operator can schedule it against the shared Claude meter and the GPU:
#   calls            model calls / renders / pipeline runs per row, repeats included      (int > 0)
#   tokens_in        prompt tokens per row over the whole test; 0 for a non-language row   (int >= 0)
#   tokens_out       completion tokens per row; 0 for a non-language row                   (int >= 0)
#   tokens_note      REQUIRED when tokens_in and tokens_out are both 0: why no tokens      (>= 20 chars)
#   minutes          wall-clock per row, model load included, operator excluded            (number > 0)
#   gpu_minutes      of those, minutes the GPU is held; 0 for off-box rows                 (number >= 0)
#   operator_minutes blind operator decisions per row, at ~30 s each                       (number >= 0)
#   note             the arithmetic, written out (calls × tokens per call, and so on)     (>= 40 chars)
# `rows[rid]['budget']` overrides any field for one row (a Claude row spends the shared week,
# an ollama row spends the GPU). The loader adds `budget.per_row` and `budget.total` (summed
# over the rows) and the hub shows them in the sheet's "Default test" lane. The budget is an
# ESTIMATE and is excluded from the test hash: revising it does not make a different test.
BUDGET_NUMERIC = ('calls', 'tokens_in', 'tokens_out', 'minutes', 'gpu_minutes', 'operator_minutes')
BUDGET_REQUIRED = BUDGET_NUMERIC + ('note',)


def steps_with_tests():
    """Every step id that has a `capability_tests/<step>.py` module — discovered from the
    directory so adding a step never means editing this file (30 executors, one file)."""
    import os
    from zyg_dashboard.capabilities_hub import STEP_IDS

    here = os.path.dirname(os.path.abspath(__file__))
    return tuple(s for s in STEP_IDS if os.path.exists(os.path.join(here, s + '.py')))


STEPS_WITH_TESTS = steps_with_tests()
