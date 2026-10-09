# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import json
import uuid

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

SCHEDULE_FILES = [
    'schedule_data_CPU.json',
    'schedule_data_GPU.json',
    'schedule_data_ACTIVE.json',
    'schedule_data.json',
]


def add_ids_to_entries(schedule_file):
    path = os.path.join(os.path.dirname(__file__), schedule_file)
    if not os.path.exists(path):
        _zyg_log.info(f'File not found: {path}')
        return 0, 0
    with open(path, 'r', encoding='utf-8') as f:
        try:
            schedule = json.load(f)
        except Exception as e:
            _zyg_log.info(f'Error reading {path}: {e}')
            return 0, 0
    updated = 0
    total = 0
    for _date, entries in schedule.items():
        for entry in entries:
            total += 1
            if 'id' not in entry:
                entry['id'] = str(uuid.uuid4())
                updated += 1
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(schedule, f, indent=2)
    return updated, total


def main():
    print('--- Migrating schedule files to add missing IDs ---')
    for schedule_file in SCHEDULE_FILES:
        updated, total = add_ids_to_entries(schedule_file)
        print(f'{schedule_file}: {updated} of {total} entries updated')
    print('--- Migration complete ---')


if __name__ == '__main__':
    main()
