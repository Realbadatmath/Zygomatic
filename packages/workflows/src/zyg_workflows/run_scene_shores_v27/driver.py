# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``main()`` — the v27 scene driver.

Moved verbatim out of ``run_scene_shores_v27.py`` (lines 1110-1358).
"""


def main(*a, **k):
    """Kept as a delegate: the package __init__ re-exports this name. The body moved to driver_cli."""
    from zyg_workflows.run_scene_shores_v27.driver_cli import main as _m

    return _m(*a, **k)


if __name__ == '__main__':  # the CLI lives in driver_cli
    from zyg_workflows.run_scene_shores_v27.driver_cli import main as _cli_main

    raise SystemExit(_cli_main())
