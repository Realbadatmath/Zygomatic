# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — exit codes, the gate entry-point list, and the two gate exceptions.

Moved verbatim from geom/anthro/__main__.py (lines 85-111) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.
"""

EXIT_OK = 0
EXIT_WARN = 1
EXIT_FAIL = 2
EXIT_ERROR = 3

# Entry point names gates.py might reasonably use, most specific first. The adapter tries
# them in order and reports every one it tried when none works.
_GATE_ENTRYPOINTS = (
    'gate_character',
    'run_gates',
    'check_character',
    'evaluate_character',
    'gate_mesh',
    'evaluate',
    'check',
    'run',
    'gate',
    'gates',
)


class GatesAbsent(Exception):
    """gates.py does not exist yet. Distinct from 'exists but would not run'."""


class GatesUnusable(Exception):
    """gates.py exists and no entry point could be called. Never falls back."""
