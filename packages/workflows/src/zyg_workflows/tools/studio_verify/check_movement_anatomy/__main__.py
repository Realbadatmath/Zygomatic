# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``python -m zyg_workflows.tools.studio_verify.check_movement_anatomy`` — the original ``__main__`` guard."""

import sys

from zyg_workflows.tools.studio_verify.check_movement_anatomy import main

if __name__ == '__main__':
    sys.exit(main())
