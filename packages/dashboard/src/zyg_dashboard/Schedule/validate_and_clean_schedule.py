#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Validate and Clean Schedule Files
Uses AddEntryTimeline from add_entry_timeline.py to validate all entries in schedule_data_GPU.json and schedule_data_CPU.json.
Removes or logs invalid entries and saves cleaned files.
"""

import os
import json
from zyg_workflows.add_entry_timeline import AddEntryTimeline

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

SCHEDULE_FILES = [
    'schedule_data_GPU.json',
    'schedule_data_CPU.json',
]

for schedule_file in SCHEDULE_FILES:
    _zyg_log.info(f'\nValidating {schedule_file}...')
    path = os.path.join(os.path.dirname(__file__), schedule_file)
    if not os.path.exists(path):
        _zyg_log.info(f'  File not found: {path}')
        continue
    with open(path, 'r', encoding='utf-8') as f:
        schedule = json.load(f)
    cleaned_schedule = {}
    validator = AddEntryTimeline(schedule_file)
    total = 0
    valid = 0
    for date, entries in schedule.items():
        cleaned_entries = []
        for entry in entries:
            total += 1
            is_valid, msg = validator.validate_schedule_entry(entry)
            if is_valid:
                cleaned_entries.append(entry)
                valid += 1
            else:
                _zyg_log.info(f'  [INVALID] {date}: {msg} | Entry: {entry}')
        if cleaned_entries:
            cleaned_schedule[date] = cleaned_entries
    # Save cleaned schedule
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cleaned_schedule, f, indent=2)
    _zyg_log.info(f'  {valid}/{total} valid entries kept in {schedule_file}')
_zyg_log.info('\nValidation and cleaning complete.')
