# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the vocabulary: verdicts, statuses, the digest boundary, the coverage floor.

Moved out of the old single-file report.py (lines 85-690).
"""

import os
import re
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

SCHEMA = 'geom.anthro.report/1'

ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'data',
    'assets',
    'anthro_reports',
)

# Verdicts and their process exit codes. HOUSE: 1 is reserved for "passed, but a human
# should look", so that a CI step can distinguish "nothing to see" from "shipped with a
# recorded stylization delta" without parsing the report.
PASS = 'PASS'  # noqa: S105  gate status constant, not a secret
WARN = 'PASS-WITH-WARNINGS'
FAIL = 'FAIL'
ERROR = 'ERROR'
EXIT_CODES = {PASS: 0, WARN: 1, FAIL: 2, ERROR: 3}

# Status vocabulary. gates.py is written in parallel with this module, so the spellings it
# might plausibly emit are all accepted; anything else lands in 'unknown', which is
# reported, not guessed at.
_STATUS_ALIASES = {
    'pass': PASS,
    'passed': PASS,
    'ok': PASS,
    'good': PASS,
    'true': PASS,
    'inside': PASS,
    'within': PASS,
    'clear': PASS,
    'warn': 'warn',
    'warning': 'warn',
    'advisory': 'warn',
    'review': 'warn',
    'borderline': 'warn',
    'unusual': 'warn',
    'marginal': 'warn',
    'fail': 'fail',
    'failed': 'fail',
    'false': 'fail',
    'violation': 'fail',
    'violated': 'fail',
    'outside': 'fail',
    'reject': 'fail',
    'rejected': 'fail',
    # An EXPLICITLY declared non-verdict is not the same thing as a missing status. The
    # gate author said "no judgement is possible here" and said why; that is information,
    # not an omission, so it does not become a warning on its own. A non-verdict on a
    # BLOCKING gate is escalated in _read_gate, because a blocking check that did not run
    # is a fact about the run.
    'skip': 'skip',
    'skipped': 'skip',
    'n/a': 'skip',
    'na': 'skip',
    'not_applicable': 'skip',
    'not-applicable': 'skip',
    'inapplicable': 'skip',
    'unmeasurable': 'skip',
    'not_implementable': 'skip',
    'not-implementable': 'skip',
    'refused': 'skip',
    # Informational rows: measured and printed, never gated. Their own bucket, because
    # calling them 'skip' would hide that a number was actually produced.
    'report': 'report',
    'reported': 'report',
    'info': 'report',
    'informational': 'report',
    'note': 'report',
    # A REQUIRED DECLARATION IS ABSENT. Its own bucket, and this is not pedantry: the gate
    # ran, reached a definite conclusion, and the conclusion is "the caller never declared
    # the band I was supposed to check against". Folding that into 'unknown' printed it as
    # '????', which reads as a renderer that could not parse the row — the opposite of the
    # truth, and it hid the one thing the operator has to act on, which is to go and
    # declare the missing value. It still counts towards the warning total: an absent
    # declaration is never a pass.
    'missing': 'missing',
    'not_declared': 'missing',
    'not-declared': 'missing',
    'undeclared': 'missing',
    'absent': 'missing',
    'not_provided': 'missing',
    'not_supplied': 'missing',
    # THE GATE ITSELF BROKE. Its own bucket, and this is the whole point of the bucket:
    # gates.py records a raising gate as ERROR and classifies it as BLOCKING for a
    # blocking gate, shielding it from the severity calibration on the explicit grounds
    # that a crash is not a band rejection. Folding it into 'unknown' — which counts only
    # towards the warning total — turned a FAIL into a pass-shaped verdict with an empty
    # blocking list. An error is a failure of the check, and a failed check is not a pass.
    'error': 'error',
    'errored': 'error',
    'crash': 'error',
    'crashed': 'error',
    'exception': 'error',
    'raised': 'error',
    'traceback': 'error',
    'broken': 'error',
    'internal_error': 'error',
    'internal-error': 'error',
    # THE GATE RAN AND THE ENGINE REFUSED THE VERDICT IT PRODUCED (W4-1). Wave 4 taught
    # gates.py to replace a gate's verdict when the form module's provenance tag outranks
    # the registry's: the gate executed, measured its subject and reached a finding, and
    # the ENGINE — not the gate — declined to ship that finding's status. That is a
    # different event from a raising gate, and gates.py now spells it with a status of its
    # own so the two are separable downstream.
    #
    # It lands in the SAME BUCKET as a crash, deliberately: it is a check that produced no
    # usable verdict, it is never a pass, and at a blocking severity it still fails the
    # body. Giving it a softer bucket would let a refusal buy a lighter outcome than the
    # verdict it replaced (t5_patellar_ligament's replaced verdict is a FAIL).
    # WHAT SEPARATES THE TWO IS THE ROW'S EXPLICIT `crashed` FLAG, NEVER THE STATUS — see
    # _crash_state(). Several spellings are accepted because this renderer must keep
    # working against an engine that spells the same event slightly differently; every one
    # of them is strictly the error bucket, so a spelling this table does not know cannot
    # be softer than one it does.
    'policy_error': 'error',
    'policy-error': 'error',
    'provenance_error': 'error',
    'provenance-error': 'error',
    'engine_error': 'error',
    'engine-error': 'error',
    'policy_refusal': 'error',
    'refused_by_policy': 'error',
    'verdict_replaced': 'error',
    'verdict_refused': 'error',
    'unshippable': 'error',
    # The status could not be READ — an absent field, an unparseable one, a row that is
    # not a mapping. Distinct from 'error', which is a definite statement that the gate
    # ran and threw. Neither is a pass.
    'unknown': 'unknown',
    'indeterminate': 'unknown',
    'none': 'unknown',
}
MISSING = 'missing'
# The gate-row status for "this gate raised". Spelled in lower case to match gates.py's
# ERROR constant; the module-level ERROR above is the VERDICT of the same name, and the
# two are deliberately different objects (a crashed gate makes the verdict FAIL, not
# ERROR — ERROR is reserved for this renderer being unable to produce a report at all).
GATE_ERROR = 'error'
# ---------------------------------------------------------------------------------
# THE CRASH FLAG (W4-1) — 'error' means two things and only the PRODUCER knows which
# ---------------------------------------------------------------------------------
# This module used to derive `crashed` as `status == GATE_ERROR`, which was true for as
# long as the only way to reach the error bucket was to raise. Wave 4 added a second way
# (the engine refusing a verdict on a provenance rule), and the derivation immediately
# started printing a falsehood on the most-read line of every report:
#     | GATES THAT CRASHED (checked nothing): t5_patellar_ligament, t5_subcostal_angle |
# plus a `gate_crashed` alarm saying "they did not run, so nothing they were supposed to
# check has been checked on this body", plus a row reading "THIS GATE RAISED. It checked
# nothing on this body." All three were false: both gates ran, both measured their subject,
# and t5_patellar_ligament's blocking finding — the patella-to-tuberosity distance drifting
# -15.54% at 120 degrees, i.e. THE LIGAMENT IS NOT MODELLED — was filed as an
# infrastructure crash instead of as the anatomical failure it is.
#
# THE CONTRACT, shared with geom.anthro.gates and implemented on both sides:
#   * the PRODUCER sets an explicit boolean `crashed` on the gate row. True means the gate
#     callable raised and checked nothing; False means it ran, checked its subject and
#     produced a finding, whatever status the engine then filed it under.
#   * this renderer READS that boolean. It never re-derives it from the status, in either
#     direction, because the status is exactly the thing that turned out to be ambiguous.
#   * a row that declares nothing is `None` — NOT KNOWN — and is reported as not known.
#     Guessing "it said error, so it must have raised" is the defect, and guessing the
#     other way would hide a real crash. An undeclared error row gets its own banner line
#     and its own alarm so the gap is visible instead of being filled in with a default.
# The flag is read from the row's own `crashed` first — the contract's location, and where
# run_gates writes it — then from `gate_crashed`, then from the same two names inside
# `detail`. The `detail` fallbacks are for an artefact written by the engine of 2026-08-06,
# which stated the same fact there because _result() routes its keyword arguments into
# `detail`; reading them keeps a stored report honest instead of turning it into a
# document full of "not declared". All four are the producer speaking explicitly, and none
# of them is an inference from the status.
_CRASH_KEYS = ('crashed', 'gate_crashed')
CRASHED = 'crashed'  # the gate raised: it checked nothing
RAN = 'ran'  # the gate ran and produced a finding
CRASH_UNDECLARED = 'undeclared'  # the producer did not say, and this module will not guess
_STATUS_ORDER = (GATE_ERROR, 'fail', 'warn', MISSING, 'unknown', 'report', 'skip', PASS)
# Every bucket normalize_status() may return. The counts block is seeded from this tuple
# and audited against it, so a status that acquires a new bucket without acquiring a
# column cannot hide inside counts.get(): it raises a policy alarm instead.
_COUNT_KEYS = (PASS, 'warn', 'fail', GATE_ERROR, 'skip', 'report', 'unknown', MISSING)
# Statuses that are never a pass and always count towards the warning total.
_NOT_A_PASS = (MISSING, 'unknown')
# Statuses that produced no verdict at all: the check did not run, or ran and broke.
# 'skip' is here too — an explicitly declared non-verdict is information rather than a
# warning on a low-severity gate, but on a BLOCKING gate it is still a check that did not
# happen, and it is escalated and named as one.
#
# 'report' WAS ADDED 2026-08-06 (re-review N1), and it was missing in a way that made a
# blocking gate INVISIBLE. A block-severity gate whose status rolled up to 'report' was not
# a pass, not a fail, not escalated, absent from doc['blocking'], absent from
# doc['unrun_blocking'] and absent from the "BLOCKING GATES THAT DID NOT RUN" banner —
# while the printed unrun_blocking_rule right below enumerated only "skip, missing or
# unknown", so the rule TEXT and the rule CODE disagreed and neither one named it. Live
# instance: t5_pronation_isolation on abel and cornelis; the same gate on the other three
# bodies became 'skip' and was handled correctly, which is what made the hole look like
# nothing. It is new this wave: BEFORE [] / AFTER ['t5_pronation_isolation'].
#
# A 'report' row is measured-and-printed, never gated. On a low-severity gate that is what
# it says it is and it keeps its own bucket. On a BLOCKING gate it is a declared blocking
# claim with no verdict behind it, so it escalates exactly like 'skip' and takes the same
# warning bucket. Whichever of the two fixes was chosen, the printed rule had to match the
# enforced one; both were changed together, and the self-test asserts the text names every
# member of this tuple.
_NO_VERDICT = ('skip', 'report', MISSING, 'unknown', GATE_ERROR)
# The members of _NO_VERDICT that the unrun_blocking_rule sentence must name. GATE_ERROR is
# excluded on purpose: a crash has its own bucket, its own alarm and its own rule
# (crash_rule), and it is a blocking FAILURE rather than an unrun check.
_UNRUN_BLOCKING_STATUSES = tuple(s for s in _NO_VERDICT if s != GATE_ERROR)
# The mark printed in the status column. A module constant so the self-test can assert
# that every bucket has an explicit rendering and nothing falls through silently.
_STATUS_MARK = {
    'fail': 'FAIL',
    GATE_ERROR: 'ERROR',
    'warn': 'warn',
    PASS: 'pass',
    'skip': 'n/a',
    'report': 'note',
    MISSING: 'MISSING',
    'unknown': '????',
}
# Verdict severity, worst last. Used to take the STRICTER of this renderer's verdict and
# the gate engine's when the two disagree: shipping the softer of two disagreeing verdicts
# is the exact failure this module exists to prevent.
_VERDICT_RANK = {PASS: 0, WARN: 1, FAIL: 2, ERROR: 3}
# The statuses geom.anthro.gates is known to emit, by CONSTANT NAME. The self-test imports
# gates.py and checks this list against the module for real, so a new engine status cannot
# appear without this renderer either rendering it explicitly or failing its own test.
_ENGINE_STATUS_CONSTANTS = (
    'PASS',
    'WARN',
    'FAIL',
    'REPORT',
    'UNMEASURABLE',
    'NOT_APPLICABLE',
    'NOT_IMPLEMENTABLE',
    'MISSING',
    'ERROR',
)
# The one status constant the W4-1 contract lets gates.py grow: the policy/provenance
# refusal, spelled distinctly from a genuine exception so the two are separable. It is
# OPTIONAL only in the sense that this renderer must work against an engine on either side
# of that change — when it IS present, the self-test asserts it lands in the error bucket
# and that a row carrying it is not reported as a crash. Anything else appearing in gates.py
# still breaks _selftest_status_coverage, which is the tripwire's whole job.
_ENGINE_STATUS_CONSTANTS_OPTIONAL = ('POLICY_ERROR',)

# HOUSE. A failure is only allowed to be downgraded to a warning when the gate declares a
# severity we recognise as low. Everything else — including a severity we have never seen
# — keeps its failure, because the alternative is that a typo in gates.py silently turns a
# blocking gate into a note.
_LOW_SEVERITIES = ('minor', 'advisory', 'info', 'informational', 'note', 'cosmetic', 'low', 'warn', 'warning', 'report')
_HIGH_SEVERITIES = ('critical', 'blocker', 'fatal', 'major', 'high', 'severe', 'error', 'block', 'blocking')

# Provenance classes, in RANK ORDER, best evidence first. CONTESTED is in the vocabulary so
# that a contested threshold can be NAMED and alarmed on; it is never a licence to ship one.
#
# CANON was added 2026-08-06 and it is not a synonym for HOUSE. HOUSE is our own policy,
# argued and owned. CANON is a number PRINTED IN AN ARTIST OR ANATOMY REFERENCE: it has no
# sample, no n and no sampling frame, and it ranks BELOW MEASURED. The rule the engine
# enforces (geom.anthro.gates.validate_registry) is that a CANON threshold may not carry
# blocking severity over any quantity ANSUR II / CDC / NHANES already answers. This
# renderer's job is to make a CANON row VISIBLE as one, and to alarm if one ever reaches
# this report carrying a blocking severity.
_PROV_CLASSES = ('MEASURED', 'CANON', 'HOUSE', 'CONTESTED', 'DERIVED', 'UNDECLARED')
_PROV_RANK = {'MEASURED': 0, 'CANON': 1, 'HOUSE': 2, 'DERIVED': 3, 'CONTESTED': 8, 'UNDECLARED': 9}

UNKNOWN = 'unknown'

# The detail key by which a gate declares "my evidence IS the finding, print it whatever
# my status is" (re-review N3). Spelled here rather than imported so this renderer keeps
# working on an artefact produced by an older engine; the self-test imports gates.py and
# asserts the two spellings are the same string, so they cannot drift silently.
_RECEIPT_KEY = 'evidence_is_the_finding'

# ---------------------------------------------------------------------------------
# CONTENT vs INSTRUMENTATION — the boundary the stable digest is taken across
# ---------------------------------------------------------------------------------
# `stable_sha256` exists so that two runs of the same mesh against the same pack produce
# the same digest, and a report can therefore be diffed for REAL CHANGE rather than for the
# clock. It used to exclude exactly two top-level keys — the `volatile` block and itself —
# which was true for as long as no per-run number lived anywhere else in the document.
#
# THE DEFECT (re-review NEW-4, pre-existing since wave 2, missed by both re-reviews): the
# wave-2 evidence-passthrough fix copies each gate's `detail` into gates[].evidence, and
# gates.py stamps per-gate WALL-CLOCK milliseconds into that detail. Nine rows on abel
# carry `gates[i].evidence.ms`. The digest therefore moved every single run:
# two runs with IDENTICAL statuses on all 60 gates gave 76889c274ec9 vs 086f727a6721, and
# the ONLY leaf differences outside `volatile` were `evidence.ms` (35.531 vs 31.987, ...).
# A field named `stable_sha256`, documented in this module and in README.md as clock-free,
# was a per-run nonce. Its consumer (geom/mesh_skeletons.py) stores it as the identity of a
# report.
#
# THE BOUNDARY, DECLARED:
#   CONTENT is everything that describes the body, the pack, the thresholds, the statuses
#   and the reasons. Two runs of the same mesh must reproduce it byte for byte, and any
#   difference in it is a difference a reader must be shown.
#   INSTRUMENTATION is anything that records WHEN this process ran or HOW LONG it took. It
#   is worth printing and worthless in a digest, because it differs every run by
#   construction.
#   `volatile` is the ONE block where instrumentation is allowed to live by name.
#   ANYWHERE ELSE, at ANY depth, a key from the vocabulary below is instrumentation and is
#   removed before hashing — not just the one key someone happened to find.
#
# The stripper is DELIBERATELY CONSERVATIVE (exact names and exact suffixes) because a
# stripper that guesses would eat content and leave a digest that is blind to real change.
# The residue detector below is deliberately WIDE, because a false alarm there is a loud
# complaint and a miss there is another silent nonce. That asymmetry is the point.
_INSTRUMENTATION_KEYS = frozenset(
    (
        'ms',
        'us',
        'ns',
        'msec',
        'msecs',
        'millis',
        'milliseconds',
        'micros',
        'microseconds',
        'elapsed',
        'elapsed_s',
        'elapsed_ms',
        'elapsed_us',
        'elapsed_sec',
        'elapsed_secs',
        'elapsed_seconds',
        'seconds',
        'secs',
        'duration',
        'duration_s',
        'duration_ms',
        'runtime',
        'runtime_s',
        'runtime_ms',
        'wall',
        'wall_s',
        'wall_ms',
        'wall_clock',
        'wallclock',
        'cpu_s',
        'cpu_ms',
        'cpu_time',
        'cpu_seconds',
        'took',
        'took_s',
        'took_ms',
        'started',
        'started_at',
        'start_time',
        'starttime',
        'finished',
        'finished_at',
        'end_time',
        'endtime',
        'generated',
        'generated_at',
        'timestamp',
        'timestamps',
        'time',
        'times',
        'now',
        'clock',
        'perf_counter',
        'monotonic',
        'process_time',
        'run_started',
        'run_finished',
        'timing',
        'timings',
        'latency',
        'latency_ms',
    )
)
_INSTRUMENTATION_SUFFIXES = (
    '_ms',
    '_us',
    '_ns',
    '_msec',
    '_elapsed',
    '_elapsed_s',
    '_elapsed_ms',
    '_seconds',
    '_secs',
    '_duration',
    '_runtime',
    '_timestamp',
    '_timestamps',
    '_time',
    '_times',
    '_timing',
    '_timings',
    '_wall_clock',
    '_wallclock',
    '_latency',
    # `superseded.volatile.gate_report_generated` and
    # `.measurement_generated` (geom/anthro/__main__.py) are the
    # live instances: a nested copy of a previous run's volatile
    # block, outside the top-level `volatile` that is excluded by
    # name.
    '_generated',
)
# NOT in the list, deliberately: '_at' and '_date'. `first_invalidated_at` is content (see
# _CLOCK_RESIDUE_CONTENT_KEYS) and `record.date` is a survey's publication date. A stripper
# that removed those would be hiding real change, which is the same defect as hiding the
# clock, with the sign reversed.
# WIDER than the stripper on purpose: this is the alarm, not the rule. Anything that
# survives the strip and still looks like a per-run clock — or like a per-run IDENTITY,
# which moves the digest for exactly the same reason — means someone added a timer or a
# nonce under a name the stripper does not know, and the digest can no longer claim to be
# stable. It says so instead of quietly going back to being a nonce (the exact regression
# NEW-4 was).
#
# W4-2: THE DECLARED RULE AND THE ENFORCED RULE HAD DRIFTED, and the enforced one was far
# narrower than the sentence above it. The enforcement was a 24-word segment list plus an
# ISO-datetime STRING test plus a 40-character key-length bail, and against that, injecting
# a per-run value at gates[].evidence left NINETEEN ordinary names as silent nonces: they
# were not stripped, not alarmed, and they moved the sha —
#     created_at  updated_at  measured_at      (epoch floats: the commonest name there is)
#     gen_sec  render_sec  cost_s  budget_s  secs_taken  sec  lap  tick  unix  when  at
#     stopwatch  host_uptime  pid  run_uuid
#     gate_evaluation_wall_clock_in_milliseconds   (44 chars: the length bail fired first)
# Three things close that, and all three are MEASURED against the five live bodies below
# rather than reasoned about:
#   * the '_at' / '_sec' / '_s' SUFFIXES join the alarm — and only the alarm. They are not
#     in the stripper, because `first_invalidated_at` is content and a stripper that ate it
#     would hide real change; the alarm's exemption list is the right instrument for that
#     one case and it already exists.
#   * a bare NUMBER in a unix-epoch range is residue whatever it is called, which catches
#     every name nobody thought of. Measured on the five bodies: the largest number
#     anywhere in a stripped document is 82260 (directed_edges), so the nearest live value
#     is four orders of magnitude below the seconds band. A per-run UUID is caught the same
#     way, by shape.
#   * the length bail is now about PROSE, not about length. doc['provenance'] is keyed by
#     the whole citation, which is what the bail was really for; a key that is shaped like
#     an identifier (no spaces) is tested at any length. Measured: the five bodies contain
#     exactly two identifier-shaped keys over 40 characters
#     (`null_rate_point_only_or_better_either_mode`,
#     `waist_circumference_omphalion_over_stature`) and neither trips the test.
#
# Matched on the WORD SEGMENTS of a key rather than as a substring. That restriction was
# MEASURED on the five live bodies, not guessed at — the first version of this detector
# fired on all five of them:
#   * substring matching flagged `monotonic_chain_helper` (a monotonicity check on a
#     landmark chain) because `time.monotonic` exists. The exact key 'monotonic' is already
#     in the stripper's vocabulary, so the wide test does not need the substring — and a
#     detector that cries wolf on a real body is a detector that gets switched off, after
#     which the next nonce ships unnoticed.
#   * doc['provenance'] is keyed BY THE SOURCE STRING, so its keys are whole paragraphs of
#     citation; one of them contains the words "rubber stamp". A field name is short. A
#     paragraph is a citation, and it is scanned as a VALUE, not as a field name.
# Segments split on any non-alphanumeric run, not just '_', so "elapsed ms" is caught as
# well as "elapsed_ms". The length bail applies to PROSE keys only (see above): measured on
# the five live bodies, every key over 40 characters that trips a clock segment is a
# citation paragraph, and every identifier-shaped key over 40 characters is content that
# does not trip it.
_CLOCK_RESIDUE_KEY_MAX_LEN = 40
_CLOCK_RESIDUE_SPLIT_RE = re.compile(r'[^A-Za-z0-9]+')
_CLOCK_RESIDUE_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$')
_CLOCK_RESIDUE_SEGMENTS = frozenset(
    (
        'ms',
        'us',
        'ns',
        'msec',
        'msecs',
        'millis',
        'micros',
        'elapsed',
        'duration',
        'runtime',
        'timestamp',
        'timestamps',
        'stamp',
        'stamped',
        'epoch',
        'latency',
        'seconds',
        'clock',
        'wallclock',
        'walltime',
        'time',
        'times',
        'timing',
        'timings',
        # W4-2. Ordinary names for the same thing, every one of them measured silent before:
        # bare clock words, the '_at'/'_sec'/'_s' family as whole segments, and the per-run
        # IDENTITY names, which are not clocks but move the digest identically and are
        # therefore the same defect. 'date' is deliberately NOT here: a survey's publication
        # date is content, and the ISO value test below already separates a date from a
        # date-with-a-time-of-day.
        'sec',
        'secs',
        's',
        'when',
        'lap',
        'tick',
        'ticks',
        'stopwatch',
        'uptime',
        'unix',
        'started',
        'finished',
        'ended',
        'took',
        'taken',
        'since',
        'pid',
        'ppid',
        'uuid',
        'guid',
        'nonce',
        'hostname',
        # 'at' IS NOT HERE, and this was MEASURED, not reasoned about. As a bare segment it
        # fires on SIX real content fields on every live body — at_drive_deg,
        # max_fans_at_a_vertex, gradient_max_at_wrist, group_mean_spread_mm_at_this_stature,
        # comparator_discriminates_at_this_joint, subject_owned_by_forearm_at_every_angle —
        # plus seven columella_at_+0.89xx operationalisation keys, because 'at' is an English
        # preposition and field names are written in English. Thirteen false alarms per report
        # is a detector somebody switches off, and then the next nonce ships. The '_at' SUFFIX
        # below carries the whole of the real case (created_at, updated_at, measured_at) with
        # none of that, and a field literally named `at` is caught by its VALUE.
    )
)
# The same family as suffixes, for names whose clock word is fused onto the end
# ('created_at' is already covered as a segment; 'elapsedsec' is not).
_CLOCK_RESIDUE_SUFFIXES = ('_at', '_sec', '_s', '_ts', '_epoch', '_uuid')
# A DATE is content (a survey's publication date, a subject's date of birth). A DATE WITH A
# TIME OF DAY on it is usually this run happening, and almost nothing in an anthropometric
# fact needs an hour and a minute.
_CLOCK_RESIDUE_VALUE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
# A per-run VALUE, caught by shape rather than by name — the half that does not depend on
# anybody having thought of the name. A unix epoch in seconds, milliseconds, microseconds
# or nanoseconds, and a UUID. The bands are narrow and were measured against the five live
# bodies: the largest number in any stripped document is 82260, so no real measurement is
# within four orders of magnitude of the lowest band.
_EPOCH_BANDS = (
    (1e9, 4e9, 'unix epoch seconds'),
    (1e12, 4e12, 'unix epoch milliseconds'),
    (1e15, 4e15, 'unix epoch microseconds'),
    (1e18, 4e18, 'unix epoch nanoseconds'),
)
_CLOCK_RESIDUE_UUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_CLOCK_RESIDUE_EPOCH_STR_RE = re.compile(r'^\d{10}(?:\.\d+)?$|^\d{13}$')
# THE ONE EXEMPTION, and the invariant that makes it safe. A recorded EVENT time can be
# content: `first_invalidated_at` (geom/anthro/__main__.py) is when a body BECAME
# ungateable, it is carried forward unchanged on every later run, and it is a fact about the
# body rather than about this process. Exempting it from the residue ALARM does not exempt
# it from the digest: it is not in the strip vocabulary, so it is hashed, and if it ever
# moves, the digest moves and the diff shows it.
#   INVARIANT (asserted in the self-test): this set and the strip vocabulary are DISJOINT.
#   A key that is both stripped from the hash and exempted from the alarm would be exactly
#   the invisible per-run nonce this whole boundary exists to prevent.
_CLOCK_RESIDUE_CONTENT_KEYS = frozenset(('first_invalidated_at',))
# Excluded from the digest at the top level: the instrumentation block, the digest itself,
# and the block that DESCRIBES the digest (which is derived from the strip and would
# otherwise re-import the presence of a timer as if it were content).
_DIGEST_EXCLUDED_TOP_LEVEL = ('volatile', 'stable_sha256', 'digest')

# ---------------------------------------------------------------------------------
# THE DOCUMENT-LEVEL COVERAGE FLOOR (re-review NEW-5)
# ---------------------------------------------------------------------------------
# HOUSE. Rule 4 — "a check that did not run is never a pass" — was enforced on every gate
# and on no body: every gate skipping at a non-blocking severity produced verdict=PASS,
# exit 0, and a counts line reading "pass 0". Nothing in the arithmetic asked whether the
# suite had actually run.
#
# A PASS therefore now requires BOTH:
#   * at least _MIN_VERDICTS_FOR_PASS gates that produced a verdict (pass / warn / fail).
#     One is the absolute floor and it needs no argument: zero verdicts is not a pass, it is
#     an empty suite wearing one.
#   * at least _MIN_VERDICT_FRACTION_FOR_PASS of the declared gates. Half is the weakest
#     non-trivial form of the claim "this pass rests on the suite rather than on its
#     silence": more of the declared checks reached a verdict than did not.
#
# WHAT "DECLARED" MEANS, AND WHY IT IS NOT "PRESENT" (W4-3). The rule printed in every
# report says "of the DECLARED gates" and the arithmetic computed n_verdicts / len(gates) —
# the gates present IN THIS DOCUMENT. A suite that emitted 3 of the 60 declared gates, all
# passing, therefore scored fraction=1.000, meets_floor=True, verdict=PASS, exit 0: the
# same hole this floor was built to close, reached by OMISSION instead of by skipping.
# The denominator is now the union of the roster the engine itself declares (the
# severity-calibration table carries one row per registered gate, and it is restricted to
# the tiers this run declares it ran) with the gates actually present. A union, because it
# may only ever grow: a document that omits declared gates is measured against the roster,
# and a document that contains gates the roster does not know is measured against itself.
# Where no roster can be found at all, the block says so in `roster_source` instead of
# quietly meaning the narrower thing again.
#
# HEADROOM, measured on our own five bodies (2026-08-06 artefacts, 60 declared gates each):
# 0.533 abel, 0.517 anny-neutral, 0.600 cornelis, 0.567 female, 0.583 male. anny-neutral is
# at 31 of 60 against a floor of 30 — it clears by ONE gate, not the two an earlier version
# of this comment claimed, and the earlier figures (0.550/0.533/0.617/0.583/0.600) were
# stale besides. Numbers in a comment go stale silently, so the live margin is COMPUTED per
# body and printed: see coverage['margin_gates'] and the banner line above the gate table.
# This floor is not free, and raising it is a decision about our own suite, not a formality.
#
# Below the floor the verdict is never PASS. It is not forced to FAIL either: this module
# already refuses to let unrun checks manufacture a failure (see unrun_blocking_rule), and
# a body that failed nothing has not failed. It becomes PASS-WITH-WARNINGS with an alarm
# that names the arithmetic.
_MIN_VERDICTS_FOR_PASS = 1
_MIN_VERDICT_FRACTION_FOR_PASS = 0.5
# The statuses that ARE a verdict. Everything else is in _NO_VERDICT and is, by this
# module's own rule, not a pass — so it cannot be evidence for one either.
_VERDICT_STATUSES = (PASS, 'warn', 'fail')

_STRIP_WIDTH = 34
_DEFAULT_WIDTH = 100
# How many evidence leaves the TEXT report prints per gate row. The JSON artefact carries
# the whole (bounded) tree; this is only about keeping one gate from filling a screen. When
# it bites, the row says so and names the artefact key rather than trailing off.
_EVIDENCE_ROWS = 14
