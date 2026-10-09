# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The pre-split script's ``__main__`` guard.

Reached as ``python scripts/scholarly_flux_ab_benchmark/`` (a directory with a
``__main__.py`` is runnable) or ``python -m scholarly_flux_ab_benchmark``; the
sys.path insert puts ``scripts/`` on the path so the first form can import the
package by name, the same shape ``test_char_gen_smoke_fast/__main__.py`` uses.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scholarly_flux_ab_benchmark import main  # noqa: E402  the sys.path insert above has to run first

if __name__ == '__main__':
    raise SystemExit(main())
