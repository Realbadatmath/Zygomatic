# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.kids_music_service` — the entry point the old
kids_music_service.py carried as its `if __name__ == '__main__'` block.
"""

import sys

from zyg_workflows.kids_music_service.cli import _main

if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
