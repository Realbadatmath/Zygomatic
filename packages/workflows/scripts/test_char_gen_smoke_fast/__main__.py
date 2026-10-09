# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``python -m test_char_gen_smoke_fast`` — the original ``__main__`` guard."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_char_gen_smoke_fast  # noqa: E402,F401  the proof runs at import
