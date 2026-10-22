# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_runtime.py — authoritative pipeline runtime for the Live Tail clock.

2026-08-26.  The Live Tail's "⏱ Pipeline Runtime" used to be computed in the
browser as ``Date.now() - pipeline.started``, frozen only when the status
became one of four hard-coded values (``completed/done/error/failed``).  Every
other resting state kept the clock ticking forever, and the number therefore
accumulated instead of reporting a runtime:

* a creature job parked at ``awaiting_review`` (the review gate) — measured
  2026-08-26 at **20h11m and climbing** for a run whose real work was 4h00m;
* a job flipped to ``stopped`` because its worker died over a GUI restart;
* a ``rejected`` / ``cancelled`` run;
* any run that stopped and was later ``resumed`` — the idle span counted as
  runtime.  In that same creature run it was 4h26m during which no worker
  existed at all: the sheet parked for review at 18:07:40 with 5/16 cells
  passing, the operator iterated on it, and a fresh worker re-ran the sheet
  phase at 22:33:57.  The cause of an idle span varies (an operator gate, a
  re-run between attempts, a genuine crash); what they share is that no worker
  was running, so none of it is runtime.

The browser cannot fix this on its own: it only knows what it happened to see
while the page was open, so a freshly loaded page would freeze a long-parked job
at "now" and report the whole span.  The server owns the timestamps, so the
server computes the number and the page just renders it.

Definition used here — **active runtime**: the wall-clock span from ``started``
to the freeze point, minus recorded dead time.  Concretely:

1. *Freeze point* — for a live run it is now; otherwise it is the last moment
   the job can be shown to have been doing something (``ended``,
   ``review_requested``, ``worker.ended``, the newest ``stage_timeline`` /
   ``debug_events`` timestamp, ``updated_at``).
2. *Activity intervals* — closed ``stage_timeline`` spans plus the ``worker``
   segment.  An open-ended stage span counts only while a worker is genuinely
   live; a stage record left open by a crash has no known end, and the freeze
   point already covers that tail.
3. *Idle spans* — every resume boundary (``resumed`` / ``worker.started``)
   subtracts the span between it and the last activity recorded before it.
   Whatever is left out of the runtime is reported back as ``runtime_gaps``
   (with a reason) and totalled in ``runtime_gap_seconds``, so a wall clock
   that exceeds the runtime always says why.  ``record_pause()`` lets a resume
   path stamp the reason it knows at the time; without it the gap is still
   detected, just labelled generically.
4. Intervals are merged; gaps shorter than ``BRIDGE_GAP_S`` are bridged so a
   normal run still equals its wall clock (stage records leave sub-minute holes
   between stages, and nested stages overlap — merging also stops those being
   double-counted).

The module is deliberately dependency-free (stdlib only, no Flask, no GUI
globals) so it can be imported from any process and unit-tested standalone:
``python3 pipeline_runtime.py <state-file.json>`` prints the breakdown.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

try:  # tzdata is present on this box; the fallback keeps the module importable
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo('Europe/Amsterdam')
except Exception:  # pragma: no cover - only when tzdata is missing
    _TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


__all__ = [
    'compute_runtime',
    'runtime_fields',
    'format_runtime',
    'parse_ts',
    'record_pause',
    'pause_log_line',
    'card_times',
    'RUNNING_STATUSES',
    'BRIDGE_GAP_S',
    'STALE_AFTER_S',
]

# Statuses that mean "a worker should be doing work right now".  Everything
# else — including awaiting_review, paused, stopped, rejected, cancelled and
# every terminal state — freezes the clock.
RUNNING_STATUSES = frozenset({'running', 'in_progress', 'active', 'started', 'busy'})

# Holes shorter than this are bridged rather than treated as dead time: stage
# bookkeeping leaves sub-minute gaps between stages on a perfectly healthy run.
BRIDGE_GAP_S = 120.0

# A job dict that *claims* ``running`` but has recorded nothing for this long is
# a stale snapshot (a disk state file left behind by a GUI restart, which is how
# ``pipeline_*_state.json`` files end up reporting 453h).  Only applied when the
# caller did NOT pass ``running`` explicitly — a caller that checked for a live
# worker knows better than this heuristic.  Same default as the standalone-video
# staleness gate in kanban_video_status.py.
STALE_AFTER_S = float(os.environ.get('ZYG_RUNTIME_STALE_S', '1800'))

# Keys that carry a "the job was last seen alive at" timestamp.
_FREEZE_KEYS = (
    'ended',
    'ended_at',
    'finished_at',
    'completed_at',
    'review_requested',
    'stopped_at',
    'cancelled_at',
    'updated_at',
    'last_update',
    'resumed',
)

# Keys that mark the start of a fresh work segment after a dead gap.
_RESUME_KEYS = ('resumed', 'resumed_at', 'restarted_at')

# Stage names that record an operator gate rather than work.  A contact sheet
# left at "Awaiting Approval" over a weekend books a 30h stage span; that is a
# wait, not runtime, and counting it would contradict the way a creature parked
# at ``awaiting_review`` freezes its clock.  Word boundaries matter here —
# "Preview Render" must not read as a review gate.
_WAIT_STAGE_RE = re.compile(
    r'\bawaiting\b|\bsheet review\b|\breview gate\b|\bmanual review\b'
    r'|\boperator (?:review|approval)\b|\bpaused\b',
    re.IGNORECASE,
)


def _is_wait_stage(name) -> bool:
    return bool(_WAIT_STAGE_RE.search(str(name or '')))


def _now() -> datetime:
    if _TZ is not None:
        try:
            return datetime.now(_TZ)
        except Exception as _exc:
            _zyg_log.debug('local timezone clock unavailable, using UTC: %s', _exc)
    return datetime.now(timezone.utc)


def parse_ts(value):
    """Parse any timestamp this codebase writes into a tz-aware datetime.

    Accepts ISO-8601 with or without an offset (naive is read as UTC, matching
    ``_parse_iso_to_ams``), a ``datetime``, or an epoch float (the standalone
    VACE run logbook uses those).  Returns ``None`` when unparseable.
    """
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        if value <= 0:
            return None
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        norm = text.replace(' ', 'T', 1)
        if norm.endswith('Z'):
            norm = norm[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(norm)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _all_timestamps(job):
    """Every timestamp recorded on the job, tz-aware, unsorted."""
    out = []
    for key in _FREEZE_KEYS:
        t = parse_ts(job.get(key))
        if t is not None:
            out.append(t)
    worker = job.get('worker')
    if isinstance(worker, dict):
        for key in ('started', 'ended'):
            t = parse_ts(worker.get(key))
            if t is not None:
                out.append(t)
    for entry in job.get('runtime_pauses') or []:
        if not isinstance(entry, dict):
            continue
        for key in ('from', 'to'):
            t = parse_ts(entry.get(key))
            if t is not None:
                out.append(t)
    for entry in job.get('stage_timeline') or []:
        if not isinstance(entry, dict):
            continue
        for key in ('started_at', 'ended_at', 'ts'):
            t = parse_ts(entry.get(key))
            if t is not None:
                out.append(t)
    for entry in job.get('debug_events') or []:
        if not isinstance(entry, dict):
            continue
        t = parse_ts(entry.get('ts'))
        if t is not None:
            out.append(t)
    return out


def _freeze_point(job, started, now):
    """Last moment the job can be shown to have been working, or None."""
    best = None
    for t in _all_timestamps(job):
        if t < started:
            continue
        if t > now:
            t = now  # clock skew between a state file and this process
        if best is None or t > best:
            best = t
    return best


def _activity_intervals(job, running, as_of, stamps=None):
    """Closed work spans: stage records + the worker segment.

    Returns ``(intervals, had_records)``.  ``had_records`` distinguishes "this
    job keeps no stage/worker bookkeeping" (fall back to the wall span) from
    "every recorded span was an operator wait" (runtime really is ~zero).
    """
    out = []
    had_records = False
    if stamps is None:
        stamps = _all_timestamps(job)
    for entry in job.get('stage_timeline') or []:
        if not isinstance(entry, dict):
            continue
        start = parse_ts(entry.get('started_at') or entry.get('ts'))
        if start is None:
            continue
        had_records = True
        if _is_wait_stage(entry.get('name')):
            continue  # operator gate — a wait, not runtime
        end = parse_ts(entry.get('ended_at'))
        if end is None:
            if running:
                end = as_of
            else:
                # Stage record left open by a crash: its true end is unknown, so
                # close it at the last thing the job recorded inside the span (a
                # debug event, the worker's exit).  Never at ``as_of`` blindly —
                # for a run that crashed and was resumed hours later that would
                # swallow the dead gap.  A gap that a resume proves was dead is
                # subtracted afterwards either way.
                later = [t for t in stamps if start < t <= as_of]
                if not later:
                    continue  # no evidence the stage did anything
                end = max(later)
        out.append((start, end))
    worker = job.get('worker')
    if isinstance(worker, dict):
        wstart = parse_ts(worker.get('started'))
        if wstart is not None:
            had_records = True
            wend = parse_ts(worker.get('ended'))
            if wend is None and running:
                wend = as_of
            if wend is not None:
                out.append((wstart, wend))
    return out, had_records


def _resume_gaps(job, started, as_of):
    """Spans a resume proves nothing was running: [last activity before R, R]."""
    resumes = []
    for key in _RESUME_KEYS:
        t = parse_ts(job.get(key))
        if t is not None:
            resumes.append(t)
    worker = job.get('worker')
    if isinstance(worker, dict):
        t = parse_ts(worker.get('started'))
        if t is not None:
            resumes.append(t)
    if not resumes:
        return []
    stamps = _all_timestamps(job)
    gaps = []
    for r in sorted(set(resumes)):
        if r <= started or r > as_of:
            continue
        prior = [t for t in stamps if t < r]
        gap_start = max(prior) if prior else started
        if gap_start < started:
            gap_start = started
        if (r - gap_start).total_seconds() > BRIDGE_GAP_S:
            gaps.append((gap_start, r))
    return gaps


def _recorded_pause_spans(job, started, as_of):
    """The idle spans a resume path stamped with ``record_pause()``."""
    out = []
    for pause in job.get('runtime_pauses') or []:
        if not isinstance(pause, dict):
            continue
        g0, g1 = parse_ts(pause.get('from')), parse_ts(pause.get('to'))
        if g0 is None or g1 is None or g1 <= g0:
            continue
        g0, g1 = max(g0, started), min(g1, as_of)
        if g1 > g0:
            out.append((g0, g1))
    return out


def _merge(intervals, bridge=BRIDGE_GAP_S):
    """Merge overlapping spans, bridging holes shorter than ``bridge``."""
    spans = sorted((s, e) for s, e in intervals if e > s)
    merged = []
    for start, end in spans:
        if merged and (start - merged[-1][1]).total_seconds() <= bridge:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _subtract(spans, gaps):
    out = list(spans)
    for g0, g1 in gaps:
        nxt = []
        for s, e in out:
            if g1 <= s or g0 >= e:
                nxt.append((s, e))
                continue
            if s < g0:
                nxt.append((s, g0))
            if e > g1:
                nxt.append((g1, e))
        out = nxt
    return out


def _gap_reason(job, g0, g1):
    """Why nothing was running during [g0, g1] — the honest label, not a guess.

    An explicit ``record_pause()`` stamp wins (the resume path knew the reason
    at the time).  Otherwise a wait stage spanning the gap names the gate.
    Everything else is reported as what it demonstrably is: no worker running.
    """
    for pause in job.get('runtime_pauses') or []:
        if not isinstance(pause, dict):
            continue
        end = parse_ts(pause.get('to'))
        if end is not None and g0 <= end <= g1 + timedelta(seconds=BRIDGE_GAP_S):
            return str(pause.get('reason') or 'paused')
    mid = g0 + (g1 - g0) / 2
    for entry in job.get('stage_timeline') or []:
        if not isinstance(entry, dict) or not _is_wait_stage(entry.get('name')):
            continue
        start = parse_ts(entry.get('started_at') or entry.get('ts'))
        end = parse_ts(entry.get('ended_at'))
        if start is not None and start <= mid and (end is None or mid <= end):
            return f'operator gate — {entry.get("name")}'
    return 'no worker running'


def _gaps(job, merged, started, as_of):
    """Everything inside the run's wall span that is NOT runtime.

    Derived from the same merged intervals the runtime is summed from, so
    ``runtime_seconds + runtime_gap_seconds == runtime_wall_seconds`` always
    holds — a wall clock longer than the runtime can never be unexplained.
    """
    raw, cursor = [], started
    for start, end in merged:
        if start > cursor:
            raw.append((cursor, start))
        if end > cursor:
            cursor = end
    if as_of > cursor:
        raw.append((cursor, as_of))
    out = []
    for g0, g1 in raw:
        seconds = (g1 - g0).total_seconds()
        if seconds <= BRIDGE_GAP_S:
            continue  # bookkeeping hole, already bridged into the runtime
        out.append(
            {
                'from': g0.isoformat(timespec='milliseconds'),
                'to': g1.isoformat(timespec='milliseconds'),
                'seconds': round(seconds, 1),
                'reason': _gap_reason(job, g0, g1),
            }
        )
    return out


def record_pause(job, resumed_at=None, reason=None, now=None):
    """Stamp the idle span a resume is ending onto ``job['runtime_pauses']``.

    Call this from a resume path, BEFORE the new worker starts recording
    anything, so the gap is flagged with the reason the caller actually knows
    (an operator review gate, an interrupted worker) instead of being labelled
    generically after the fact.  Returns the recorded span, or ``None`` when
    there is nothing worth recording (no start, no prior activity, or a gap
    shorter than ``BRIDGE_GAP_S``).  Idempotent: resuming twice from the same
    instant records one pause.  The caller owns logging and persistence.
    """
    job = job if isinstance(job, dict) else {}
    now = parse_ts(now) or _now()
    resumed = parse_ts(resumed_at) or now
    started = parse_ts(job.get('started') or job.get('started_iso'))
    if started is None or resumed <= started:
        return None
    prior = [t for t in _all_timestamps(job) if t < resumed]
    gap_start = max(prior) if prior else started
    seconds = (resumed - gap_start).total_seconds()
    if seconds <= BRIDGE_GAP_S:
        return None
    pauses = job.setdefault('runtime_pauses', [])
    if not isinstance(pauses, list):
        pauses = job['runtime_pauses'] = []
    stamp = resumed.isoformat(timespec='milliseconds')
    for existing in pauses:
        if isinstance(existing, dict) and existing.get('to') == stamp:
            return None  # already recorded this resume
    entry = {
        'from': gap_start.isoformat(timespec='milliseconds'),
        'to': stamp,
        'seconds': round(seconds, 1),
        'reason': str(reason or 'no worker running'),
    }
    pauses.append(entry)
    return entry


def pause_log_line(job, entry):
    """One-line, log-ready summary of a recorded pause."""
    if not entry:
        return ''
    return (
        f'runtime clock paused {format_runtime(entry.get("seconds"))} '
        f'({entry.get("reason")}) — {entry.get("from")} → {entry.get("to")}; '
        f'excluded from the pipeline runtime'
    )


def compute_runtime(job, running=None, now=None):
    """Runtime of one pipeline job.

    ``job`` is any of the job dicts this codebase keeps (``_workflow_jobs``,
    ``_creature_gen_jobs``, ``_char_gen_jobs``, a ``*_state.json`` snapshot…).
    ``running`` overrides the status sniff — pass the same truth the caller uses
    for its payload (e.g. a live-worker check), because a job dict can say
    ``running`` long after its worker died.

    Returns ``{'runtime_seconds', 'runtime_running', 'runtime_as_of',
    'runtime_wall_seconds'}``; ``runtime_seconds`` is ``None`` only when the job
    has no usable start timestamp.
    """
    job = job if isinstance(job, dict) else {}
    now = parse_ts(now) or _now()
    started = parse_ts(job.get('started') or job.get('started_iso') or job.get('created') or job.get('created_at'))
    if started is None:
        return {
            'runtime_seconds': None,
            'runtime_running': False,
            'runtime_as_of': None,
            'runtime_wall_seconds': None,
            'runtime_gap_seconds': 0.0,
            'runtime_gaps': [],
        }
    if started > now:
        started = now
    frozen_at = _freeze_point(job, started, now)
    if running is None:
        running = str(job.get('status') or '').strip().lower() in RUNNING_STATUSES
        if running and STALE_AFTER_S > 0:
            # Sniffed, not verified: a snapshot that has recorded nothing for
            # half an hour is stale, not running.
            last_seen = frozen_at or started
            if (now - last_seen).total_seconds() > STALE_AFTER_S:
                running = False
    running = bool(running)

    as_of = now if running else (frozen_at or started)
    if as_of < started:
        as_of = started

    intervals, had_records = _activity_intervals(job, running, as_of, stamps=_all_timestamps(job))
    spans = [(max(s, started), min(e, as_of)) for s, e in intervals]
    recorded = _recorded_pause_spans(job, started, as_of)
    if recorded:
        # A recorded pause is a POSITIVE statement that nothing ran in that
        # window, so its complement is a positive statement that something did.
        # That beats the derived model, which depends on evidence a resume can
        # destroy: ``job['worker']`` is a single slot overwritten on every
        # resume, so an earlier work segment vanishes from the record and would
        # otherwise be miscounted as idle. Derived activity is unioned in so a
        # partially-stamped job never loses spans it can still prove.
        spans = spans + [(started, as_of)]
    merged = _merge([(s, e) for s, e in spans if e > s])
    if not merged and not had_records:
        # No stage/worker bookkeeping at all — fall back to the plain wall span,
        # which is still bounded by the freeze point (so it stops accumulating).
        merged = [(started, as_of)] if as_of > started else []
    merged = _subtract(merged, recorded)
    merged = _subtract(merged, _resume_gaps(job, started, as_of))

    seconds = sum((e - s).total_seconds() for s, e in merged)
    gaps = _gaps(job, merged, started, as_of)
    return {
        'runtime_seconds': round(max(0.0, seconds), 1),
        'runtime_running': running,
        'runtime_as_of': as_of.isoformat(timespec='milliseconds'),
        'runtime_wall_seconds': round(max(0.0, (as_of - started).total_seconds()), 1),
        # Why the wall clock is longer than the runtime — never left unexplained.
        'runtime_gap_seconds': round(sum(g['seconds'] for g in gaps), 1),
        'runtime_gaps': gaps,
    }


def runtime_fields(job, running=None, now=None):
    """``compute_runtime`` result, ready to merge into an API payload."""
    return compute_runtime(job, running=running, now=now)


def _stage_span(entry, now, running=None):
    """``(started_at, ended_at, elapsed_s, running)`` for one stage_timeline row.

    A row treated as ``running`` is always measured to ``now`` and reports no
    end, even when it carries an ``ended_at``.  Re-entering a stage reopens the
    existing row, and a writer that forgets to clear the previous attempt's
    ``ended_at`` would otherwise freeze the card clock at the earlier finish —
    exactly the shape the live creature run had on 2026-08-26, where
    'Multi-Angle Sheet' was ``running`` since 15:41 with an ``ended_at`` of
    16:37 left over from the pass the review gate sent back.

    ``running`` overrides the row's own status.  A worker that closes a stage by
    moving on without closing its row leaves several rows claiming ``running``
    at once — that same run had three — and only the board knows which card it
    is actually showing as running.  Where a caller has that answer it wins, so
    a card can never render 'QUEUED' beside a ticking clock.
    """
    if not isinstance(entry, dict):
        return None, None, None, False
    if running is None:
        running = str(entry.get('status') or '').strip().lower() in RUNNING_STATUSES
    started = entry.get('started_at') or entry.get('ts')
    start_dt = parse_ts(started)
    if start_dt is None:
        return None, None, None, running
    if not isinstance(started, str):
        started = start_dt.isoformat()  # envfx writes epoch floats
    ended = None if running else entry.get('ended_at')
    end_dt = now if running else parse_ts(ended)
    if end_dt is None:
        # Open row on a job that is not running: a crash left it unclosed, so
        # its true end is unknown.  Report whatever the writer recorded rather
        # than counting the span up to now.
        recorded = entry.get('elapsed_s')
        elapsed = round(float(recorded), 1) if isinstance(recorded, (int, float)) else None
        return started, ended, elapsed, running
    return started, ended, round(max(0.0, (end_dt - start_dt).total_seconds()), 1), running


def card_times(job, cards, match=None, now=None):
    """Per-card ``started_at`` / ``elapsed_s`` for the Kanban card dialog.

    A board's ``cards`` payload carries a status per card and nothing else, so
    the card dialog's Started and Duration rows had nothing to read and rendered
    the browser's zero-initialised placeholders — "0s ago" and "0s" — for every
    card of every board, running or not (2026-08-26).  Both numbers already
    exist in the job's own ``stage_timeline``, whose rows every worker names
    after the card it drives.

    Computed here rather than in the browser for the same reason the pipeline
    runtime is: the page only knows what it happened to see while it was open,
    so a freshly loaded page cannot date a stage that started hours ago.

    ``cards`` is any iterable of card titles (a ``{title: status}`` map works).
    ``match(card, entry_name_lower) -> bool`` overrides the default
    case-insensitive exact title match; the documentary board joins its cards to
    stage names by fragment instead, and must pass the row it actually matched
    so a card cannot show one stage's status beside another stage's clock.
    Cards with no timeline row are left out, so the browser renders '—' instead
    of a fabricated zero.

    When a stage was run more than once the **last** matching row wins, so the
    card dates its current attempt rather than the one a review gate sent back.
    That matches how the boards already resolve status: ``tl_map`` is a dict
    keyed by stage name, so the newest row is the one they read.  Writers that
    reopen a row in place instead of appending a new one (``_char_stage_start``,
    ``_contact_sheet_stage_start``) keep the first attempt's ``started_at`` by
    design, and such a card reports its total time across attempts.
    """
    out = {}
    rows = [e for e in (job.get('stage_timeline') or []) if isinstance(e, dict)]
    if not rows:
        return out
    as_of = now or _now()
    # A ``{title: status}`` map also settles which card is really running; a bare
    # iterable of titles leaves that to each row's own status.
    board = cards if hasattr(cards, 'get') else None
    for card in cards:
        key = str(card)
        hit = None
        for entry in rows:
            name = str(entry.get('name') or '')
            if match(key, name.lower()) if match else name.strip().lower() == key.strip().lower():
                hit = entry
        if hit is None:
            continue
        live = None if board is None else (str(board.get(card) or '').strip().lower() == 'running')
        started, ended, elapsed, running = _stage_span(hit, as_of, running=live)
        start_dt = parse_ts(started)
        if start_dt is None:
            continue
        out[key] = {
            'started_at': started,
            'ended_at': ended,
            'elapsed_s': elapsed,
            'since_s': round(max(0.0, (as_of - start_dt).total_seconds()), 1),
            'running': running,
        }
    return out


def format_runtime(seconds):
    """``4h 00m 20s`` / ``12m 07s`` — the Live Tail's format, for logs/reports."""
    if seconds is None:
        return '—'
    total = int(max(0, round(seconds)))
    hh, mm, ss = total // 3600, (total % 3600) // 60, total % 60
    return f'{hh}h {mm:02d}m {ss:02d}s' if hh else f'{mm}m {ss:02d}s'


if __name__ == '__main__':  # the CLI lives in pipeline_runtime_cli
    from zyg_workflows.pipeline_runtime_cli import main as _cli_main

    raise SystemExit(_cli_main())
