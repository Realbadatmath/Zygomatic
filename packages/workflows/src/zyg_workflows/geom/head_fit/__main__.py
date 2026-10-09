# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Console entry point — ``python -m zyg_workflows.geom.head_fit <cmd>``."""

from zyg_workflows.geom.head_fit.bridge import _cli

if __name__ == '__main__':
    raise SystemExit(_cli())
