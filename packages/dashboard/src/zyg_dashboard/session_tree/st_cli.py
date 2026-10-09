#!/usr/bin/python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
st — the Session Tree CLI. The ONLY sanctioned way for a Claude agent to talk
to the Session Tree board on :7100. Output is terse plain text on purpose:
every line an agent reads is paid for again on every later tool call.

  st whoami                       who the server thinks you are (model, role)
  st status [TREE]                active trees + counts; with TREE: one line per task (no briefs)
  st next [TREE]                  the one task you should claim now (id + title only). A session the
                                  board SPAWNED was told its task in its prompt: claim that, skip next.
  st claim TREE N                 claim task N — prints the brief. Only claimed briefs are readable.
                                  If the slot is busy you are QUEUED instead (no brief yet): then run
  st await TREE N                 in the background — exits when the slot is yours and prints the brief
  st touch TREE N ["note"]        heartbeat + progress note (extends the lease)
  st release TREE N "why"         give the task back untouched
  st done TREE N --report FILE    submit the report (JSON) — the server checks it
  st fail TREE N "why"            honest failure
  st report-template              print the report JSON skeleton
  st rules                        print the rulebook

  creator only (Claude Fable):
  st create --file tree.json      create a tree (≤30 tasks; eta_minutes REQUIRED — your wall-time estimate, logged
                                  and compared with reality on the Metrics tab, never acted on). One tree runs at a time: if a tree is
                                  already active the new one is PLANNED (ranked by creation time) and
                                  activates by itself when the active tree archives. The board then
                                  SPAWNS one Opus executor per ready task (≤ max_executors live,
                                  one task per session) — nobody opens executor sessions by hand.
  st wait TREE [--until-archive]  block until a task FAILS/goes stale or TREE archives (run it in the background right after create,
                                  planned or not; the harness wakes you when it exits) then: st review TREE
  st review TREE                  read a FINISHED tree's reports once → write the results report + plan
  st suggest --file tree.json     file a MODULARIZATION tree for the operator to accept/reject (Modularization tab);
                                  same shape as create plus "rationale"; runs nothing until accepted
  st add TREE --file tasks.json   append tasks (active or planned tree); --eta N revises the tree ETA (logged)
  st report TREE N                read a finished/failed task's report on an active tree
  st reset TREE N [--brief FILE]  put a failed/stale task back to todo
  st close TREE ["note"] [--force] archive a tree by hand (a planned tree too — it never runs)
  st tree-template                print the tree JSON skeleton
"""

import os
import sys

# One handler per command lives next door in st_commands_cli, the board transport and the
# shared printers in st_client_cli (both extracted 2026-10-09 from this file's 463-line
# `main`). Both import forms are needed: `st` is a symlink to this file, so
# /usr/bin/python3 may run it as a plain script, with only its own directory on sys.path
# and no package for a relative import to resolve against.
try:
    from .st_client_cli import SID
    from .st_commands_cli import COMMANDS
except ImportError:  # run as a script, with no parent package
    from st_client_cli import SID  # type: ignore[no-redef]
    from st_commands_cli import COMMANDS  # type: ignore[no-redef]


def main(argv):
    """Run one ``st`` command and return its exit status.

    The three commands that need no identity — ``--help``, ``rules`` and the two
    templates — are answered first; everything else goes through the session-id gate and
    then :data:`st_commands_cli.COMMANDS`. An unknown command prints the help and
    returns 2.
    """
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]

    if cmd == 'rules':
        p = os.path.expanduser('~/.claude/skills/session-tree/SKILL.md')
        print(open(p).read() if os.path.exists(p) else 'rules file missing: ' + p)
        return 0
    if cmd in ('report-template', 'tree-template'):
        return COMMANDS[cmd](args)

    if not SID:
        print('REFUSED: CLAUDE_CODE_SESSION_ID is not set — st only works inside a Claude Code session')
        return 2

    handler = COMMANDS.get(cmd)
    if handler is None:
        print(f"unknown command '{cmd}'\n" + __doc__.strip())
        return 2
    return handler(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
