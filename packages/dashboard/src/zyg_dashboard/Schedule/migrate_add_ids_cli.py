# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.migrate_add_ids`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.migrate_add_ids` still reaches it."""

import sys

from zyg_dashboard.Schedule.migrate_add_ids import (
    SCHEDULE_FILES,
    add_ids_to_entries,
)


def main():
    print('--- Migrating schedule files to add missing IDs ---')
    for schedule_file in SCHEDULE_FILES:
        updated, total = add_ids_to_entries(schedule_file)
        print(f'{schedule_file}: {updated} of {total} entries updated')
    print('--- Migration complete ---')


if __name__ == '__main__':
    sys.exit(main())
