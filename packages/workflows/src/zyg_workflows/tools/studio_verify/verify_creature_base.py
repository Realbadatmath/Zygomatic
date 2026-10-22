#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prove a Creature Studio base creature loads in the LIVE page.

    /usr/bin/python3 tools/studio_verify/verify_creature_base.py wolf_hd [--fur] [--shot out.png]

Opens ``$ZYG_KANBAN_URL/inspection.html#creatures`` in headless Chrome with a
fresh profile (so the operator's cache is not what is measured), pins the base
in localStorage, turns the 3D pane on, waits for the mesh + idle clip, and
prints one JSON line. Exit 0 only when: the mesh loaded from the versioned
arch-asset URL, a clip named exactly "Idle" is playing, the Head node moved
between two samples 1.5 s apart, no page errors, and (with --fur) the shell
fur attached (CRST3X.furShells > 0). The canvas itself is captured with
toDataURL — a screenshot clip of #crst-3d under html zoom .67 only shows the
overlay (measured 2026-09-19).
"""

from zyg_workflows import paths

URL = paths.ZYG_KANBAN_URL + '/inspection.html#creatures'


if __name__ == '__main__':  # the CLI lives in verify_creature_base_cli
    from zyg_workflows.tools.studio_verify.verify_creature_base_cli import main as _cli_main

    raise SystemExit(_cli_main())
