# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""geom.anthro.report — turn a gate result into something a human can act on.

This module exists because of three failure modes that a naive printout has, all of which
were observed in the research this package implements.

1. A verdict without a NUMBER is unusable. "crotch height out of band" does not tell you
   whether the mesh is 2 mm off or 44 mm off, and those two are a rounding error and a
   change of ancestry respectively. Every row here carries observed, band, and the signed
   distance to the nearer band edge — converted to millimetres of the subject's own
   stature wherever the ratio is stature-relative, because that is the unit the modeller
   actually moves a slider in.

2. Printing only the failures HIDES THE SHAPE OF THE BODY. Ten independent 90% bands admit
   at most 0.9^10 = 35% of real people, so a body can clear every marginal band and still
   be an extreme, uniformly-stylised outlier — nine ratios all sitting at p93 is a house
   style, not a coincidence, and it is invisible in a pass/fail list. That is why the
   PERCENTILE STRIP renders every ratio that has a reference band, passing or not: making
   the stylization delta visible as a number is the point of the exercise, not a
   by-product of it.

3. A threshold with no provenance is an aesthetic opinion wearing a lab coat. The footer
   forces every distinct source string into view and, more importantly, reports the gates
   whose provenance is UNDECLARED as a defect of the gate registry — silence about where a
   number came from is the exact mechanism by which the golden ratio and the "0.7 WHR"
   ideal end up in a pipeline.

Three rendering rules follow from the same principle and are worth stating because the code
cannot show them:

  * A MISSING FIELD IS NEVER A PASS. An absent status renders as 'unknown' and counts
    towards the warning total; it never silently becomes success. A gate that DECLARES
    status 'missing' is a different thing and gets its own row type: it ran, it reached a
    conclusion, and the conclusion is that a declaration the caller owes it was never
    made. That renders as MISSING with the gate's own explanation, not as '????'.
  * A CRASH IS A BLOCKING FAILURE, NOT AN 'UNKNOWN'. gates.py runs with strict=False in
    production precisely so that one raising gate is recorded rather than aborting the
    build, and it classifies that ERROR row as blocking for a blocking gate — deliberately
    shielding it from the rejection-rate calibration, because a gate that crashed did not
    reject an unusual body, it broke. This renderer used to fold 'error' into 'unknown',
    which counts only towards the warning total: a blocking gate that never ran shipped as
    PASS-WITH-WARNINGS with an empty blocking list. 'error' now has its own bucket, its own
    ERROR mark, its own count column, its own entry in doc['blocking'], and it drives the
    verdict to FAIL on any high or unrecognised severity. The whole value of this stack is
    that a PASS means the check ran and passed; a check that did not run is never a pass,
    at any surface — gate row, roll-up, counts, summary line, verdict banner.
  * AN UNRECOGNISED SEVERITY IS FATAL, not minor. Downgrading a failure requires an
    explicitly recognised low severity; every downgrade that does happen is listed in the
    output rather than applied quietly. The same rule runs the other way: a status that
    reached no verdict (skip, report, missing, unknown, error) on a high OR unrecognised
    severity gate is escalated and named, never absorbed — and "high severity" there means
    the severity the registry DECLARED or the severity that governed the run, whichever is
    higher. A rejection-rate calibration may soften a VERDICT the band produced; it has
    nothing to say about a check that produced no verdict at all.
  * A PASS IS A CLAIM ABOUT A SUITE THAT RAN. Rule 4 ("a check that did not run is never a
    pass") was enforced per gate and never per body, so a document in which every gate
    skipped at a non-blocking severity rendered PASS, exit 0, with "pass 0" in the counts.
    doc['coverage'] now carries the floor: a PASS requires a minimum number and a minimum
    fraction of the declared gates to have actually produced a verdict. Below the floor the
    document is not a pass, it is an unrun suite, and it says so.

This module owns no thresholds of its own. It reads gates.py's output as data and the
reference pack for percentiles, and it renders. The only policy it applies is the
status/severity arithmetic above, which is HOUSE and is declared as such in the footer.
"""

import hashlib
import json
import math
import os
import re
import sys
import textwrap
import time
import logging as _zyg_logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from zyg_workflows.geom.anthro.report.constants import (
    SCHEMA,
    ROOT,
    PASS,
    WARN,
    FAIL,
    ERROR,
    EXIT_CODES,
    _STATUS_ALIASES,
    MISSING,
    GATE_ERROR,
    _CRASH_KEYS,
    CRASHED,
    RAN,
    CRASH_UNDECLARED,
    _STATUS_ORDER,
    _COUNT_KEYS,
    _NOT_A_PASS,
    _NO_VERDICT,
    _UNRUN_BLOCKING_STATUSES,
    _STATUS_MARK,
    _VERDICT_RANK,
    _ENGINE_STATUS_CONSTANTS,
    _ENGINE_STATUS_CONSTANTS_OPTIONAL,
    _LOW_SEVERITIES,
    _HIGH_SEVERITIES,
    _PROV_CLASSES,
    _PROV_RANK,
    UNKNOWN,
    _RECEIPT_KEY,
    _INSTRUMENTATION_KEYS,
    _INSTRUMENTATION_SUFFIXES,
    _CLOCK_RESIDUE_KEY_MAX_LEN,
    _CLOCK_RESIDUE_SPLIT_RE,
    _CLOCK_RESIDUE_IDENTIFIER_RE,
    _CLOCK_RESIDUE_SEGMENTS,
    _CLOCK_RESIDUE_SUFFIXES,
    _CLOCK_RESIDUE_VALUE_RE,
    _EPOCH_BANDS,
    _CLOCK_RESIDUE_UUID_RE,
    _CLOCK_RESIDUE_EPOCH_STR_RE,
    _CLOCK_RESIDUE_CONTENT_KEYS,
    _DIGEST_EXCLUDED_TOP_LEVEL,
    _MIN_VERDICTS_FOR_PASS,
    _MIN_VERDICT_FRACTION_FOR_PASS,
    _VERDICT_STATUSES,
    _STRIP_WIDTH,
    _DEFAULT_WIDTH,
    _EVIDENCE_ROWS,
)
from zyg_workflows.geom.anthro.report.textfmt import (
    _is_num,
    _num,
    _fmt_num,
    _fmt_rate,
    _fmt_pct,
    _wrap,
    _jsonable,
)
from zyg_workflows.geom.anthro.report.gatedata import (
    _get,
    normalize_status,
    status_is_recognised,
    _crash_state,
    engine_statuses,
    _severity_class,
    _band_of,
    _fmt_band,
    _observed_of,
    _prov_class,
    _iter_gates,
    _rejection_rate,
)
from zyg_workflows.geom.anthro.report.evidence import (
    EVIDENCE_MAX_LIST,
    EVIDENCE_MAX_STR,
    EVIDENCE_MAX_DEPTH,
    EVIDENCE_MAX_FIELDS,
    _ev_scalar,
    _evidence_of,
    _flat_evidence,
    _EVIDENCE_QUALIFIER_TOKENS,
    _BAND_STRUCTURAL_KEYS,
    _DECISIVE_EVIDENCE_KEYS,
    _EV_TOKEN_RE,
    _EV_PATH_RE,
    _EV_IDENTIFIER_RE,
    _ev_tokens,
    _ev_stem,
    _decisive_evidence_vocabulary,
    _field_is_decisive,
    _rank_evidence,
    _read_gate,
)
from zyg_workflows.geom.anthro.report.strip import (
    _strip,
    ratio_rows,
    render_percentile_strip,
)
from zyg_workflows.geom.anthro.report.alarms import (
    _build_alarms,
)
from zyg_workflows.geom.anthro.report.document import (
    _age_alarm,
    _declared_roster,
    build,
)
from zyg_workflows.geom.anthro.report.digest import (
    _measurement_meta,
    _is_instrumentation_key,
    _digest_strip,
    _looks_like_a_clock_key,
    _looks_like_a_clock_value,
    _digest_residue,
    _volatile_content,
    _digest_scan,
    stable_sha,
    verdict,
    exit_code,
)
from zyg_workflows.geom.anthro.report.renderers import (
    _banner,
    render_gate_table,
    render_provenance,
    render_severity_calibration,
    render_alarms,
    render_text,
    _render_stylization,
    render_summary,
)
from zyg_workflows.geom.anthro.report.measurements import (
    render_measurements,
    render_reference,
    report_path,
    write_json,
    read_json,
)
from zyg_workflows.geom.anthro.report.fixture import (
    contract_fixture,
)
from zyg_workflows.geom.anthro.report.selftest_core import (
    _selftest,
    _selftest_crash,
)
from zyg_workflows.geom.anthro.report.selftest_rules import (
    _selftest_unrun_blocking_rule,
    _selftest_digest,
)
from zyg_workflows.geom.anthro.report.selftest_checks import (
    _selftest_coverage_floor,
    _selftest_receipt_row,
    _selftest_evidence_ranking,
    _selftest_status_coverage,
)

_zyg_log = _zyg_logging.getLogger(__name__)
