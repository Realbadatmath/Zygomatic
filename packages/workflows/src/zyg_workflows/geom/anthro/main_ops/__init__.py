# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — `python -m zyg_workflows.geom.anthro <cmd>`.

Everything heavy is imported inside the command that needs it. Loading the anny model
costs seconds and a CUDA context; `reference` and `selftest --fast` must not pay for it,
and gates.py is imported lazily because this module is written in parallel with it.

The exit code is the contract, not the text: 0 pass, 1 pass-with-warnings, 2 fail,
3 internal error. A warning is a distinct code from a pass because a body that clears
every band while sitting at p93 on nine ratios is a recorded stylization decision, and a
build system needs to be able to tell that apart from "nothing to see here".

One rule this file exists to enforce: when gates.py is ABSENT the CLI renders a documented
contract fixture and says so on every line of output. When gates.py is PRESENT but cannot
be called, that is an internal error (exit 3) — substituting a fixture for a gate run that
was supposed to happen would be a silent fallback, which is the failure mode this whole
package is built to avoid.

TWO DEFECTS THIS FILE CLOSED (2026-08-06), both of the same shape — a run that covered
less than it appears to have covered:

  F7. `check all` let the first un-gateable character's RuntimeError propagate out of the
  loop. With ZYG_ABS_PATTERN_V2=1 the sorted roster is abel, anny-neutral, cornelis,
  female, male; cornelis fails the cage-hash check, so the process died there and `female`
  and `male` were never attempted AND never mentioned — 3 of 5 characters ungated, from an
  exit code and a log that named two. The loop now continues past an un-gateable body and
  every run ends with an explicit roster: gated, failed, and SKIPPED with the reason. The
  exit code is computed once, over the WHOLE roster, in `_roster_exit_code()`, and an
  un-gateable character contributes 3 — the run did not establish anything about that body.

  THE STALE SUMMARY. A body that cannot be gated already had a summary stored in
  registry.json (and in the params block it embeds) from the last time it COULD be gated.
  Printing a refusal and leaving that record in place means the registry keeps presenting
  `PASS-WITH-WARNINGS` for a body nothing has currently checked — measured: cornelis and
  male both carried exactly that. So a refusal now SUPERSEDES the stored summary:
  `_stale_summary()` replaces it with a record that carries no verdict word at all, plus
  the reason, the timestamp, and the whole previous summary under `superseded_summary`.
  Nothing is deleted; the old record is demoted, visibly, and the repair command travels
  with it. `--keep-stale-summary` opts out and says loudly what it left behind.

  The direction is deliberately one-way. A successful `check` does NOT write the registry:
  this CLI may mark a stored verdict as not-current, never make one look better or newer
  than the run that produced it. Re-establishing a verdict is `mesh_skeletons gate`'s job,
  because that is what also re-writes the report beside the mesh and re-records the aux
  hashes for it.

A THIRD, SMALLER ONE (N4, 2026-08-06): "GATED, THEN NOT WRITTEN" IS NOT "NEVER GATED".
`--out` is documented as "output directory or file". It was a directory for `selftest`,
for `reference` and for `check all`, and a FILE — with no alternative — for `check <one
character>`; the documented directory there built the mesh, ran all sixty gates, printed
the whole report, and then raised IsADirectoryError inside the atomic rename. The generic
`except Exception` around the loop caught it, and the run signed off with `1 character(s)
requested, 0 gated, 1 SKIPPED (never gated)` about a body it had just gated and printed.
Fail-closed but false, and false in the direction that hides work that was actually done.

  * `--out` is now resolved ONCE, BEFORE the first mesh is built (`_resolve_out_paths`).
    A directory is supported as documented for one character as well as for many. The one
    combination that cannot be honoured — several characters into a single existing file —
    is refused up front with exit 3, having measured nothing and having said so.
  * The write has its OWN except clause and its own roster outcome, `GATED_UNWRITTEN`.
    The roster header now reads `N gated (M of them with NO ARTIFACT WRITTEN), K SKIPPED
    (never gated)`, the row carries the verdict the gates actually returned, and only a
    body whose gates did not run is described as never gated. The exit code does not move:
    a missing artifact is still 3, and `max()` keeps a FAIL verdict from being softened.
  * A write failure does NOT supersede the stored summary. Every string in
    `_stale_summary` says the body could not be gated, which would be a second false
    statement; instead `_unwritten_notes` reads what is still on disk and, if that record
    is MORE FAVOURABLE than the verdict this run produced, says so in those words.
"""

# ruff: noqa: F401

import argparse
import json
import os
import sys
import time
import traceback

from zyg_workflows.geom.anthro import report as RPT  # noqa: E402

from zyg_workflows.geom.anthro.main_ops.constants import (  # noqa: E402
    EXIT_OK,
    EXIT_WARN,
    EXIT_FAIL,
    EXIT_ERROR,
    _GATE_ENTRYPOINTS,
    GatesAbsent,
    GatesUnusable,
)
from zyg_workflows.geom.anthro.main_ops.characters import (  # noqa: E402
    _characters,
    _build,
    _measure,
    _age_years,
    _validate_ancestry,
    _resolve,
)
from zyg_workflows.geom.anthro.main_ops.gates_adapter import (  # noqa: E402
    _adapt_call,
    _subject,
    call_gates,
)
from zyg_workflows.geom.anthro.main_ops.roster import (  # noqa: E402
    GATED,
    SKIPPED,
    GATED_UNWRITTEN,
    _STALE_SCHEMA,
    _STALE_STATUS,
    _STALE_NOTE,
    _stale_summary,
    _stale_report_doc,
    _supersede_stale_summary,
    _unwritten_notes,
    _roster_exit_code,
    _render_roster,
    OutSpecError,
    _looks_like_dir,
    _resolve_out_paths,
)
from zyg_workflows.geom.anthro.main_ops.commands import (  # noqa: E402
    cmd_check,
    cmd_measure,
    cmd_reference,
    cmd_build_pack,
)
from zyg_workflows.geom.anthro.main_ops.selftest import (  # noqa: E402
    cmd_selftest,
    cmd_list,
)
from zyg_workflows.geom.anthro.main_ops.cli import (  # noqa: E402
    _COMMON_DEFAULTS,
    _Parser,
    _common,
    _parser,
    main,
)

__all__ = [
    'argparse',
    'json',
    'os',
    'sys',
    'time',
    'traceback',
    'RPT',
    'EXIT_OK',
    'EXIT_WARN',
    'EXIT_FAIL',
    'EXIT_ERROR',
    '_GATE_ENTRYPOINTS',
    'GatesAbsent',
    'GatesUnusable',
    '_characters',
    '_build',
    '_measure',
    '_age_years',
    '_validate_ancestry',
    '_resolve',
    '_adapt_call',
    '_subject',
    'call_gates',
    'GATED',
    'SKIPPED',
    'GATED_UNWRITTEN',
    '_STALE_SCHEMA',
    '_STALE_STATUS',
    '_STALE_NOTE',
    '_stale_summary',
    '_stale_report_doc',
    '_supersede_stale_summary',
    '_unwritten_notes',
    '_roster_exit_code',
    '_render_roster',
    'OutSpecError',
    '_looks_like_dir',
    '_resolve_out_paths',
    'cmd_check',
    'cmd_measure',
    'cmd_reference',
    'cmd_build_pack',
    'cmd_selftest',
    'cmd_list',
    '_COMMON_DEFAULTS',
    '_Parser',
    '_common',
    '_parser',
    'main',
]
