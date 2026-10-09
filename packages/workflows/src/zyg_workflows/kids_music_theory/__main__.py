# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``python -m zyg_workflows.kids_music_theory`` — the CLI self-test that was
the original module's ``if __name__ == '__main__'`` block (lines 2930-2933).
"""

from __future__ import annotations

import sys

from zyg_workflows.kids_music_theory.selftest import _selftest

sys.exit(_selftest())
