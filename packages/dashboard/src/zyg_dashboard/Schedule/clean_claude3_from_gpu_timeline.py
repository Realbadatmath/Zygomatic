# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import glob

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

files = glob.glob('Schedule/schedule_data_GPU*.json')
total_removed = 0

for file in files:
    with open(file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    before = len(data.get('entries', []))
    data['entries'] = [
        e
        for e in data.get('entries', [])
        if e.get('ai_model') != '1017' and 'claude' not in str(e.get('bar_id', '')).lower()
    ]
    after = len(data['entries'])
    removed = before - after
    total_removed += removed
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    _zyg_log.info(f'Cleaned {removed} Claude 3 entries from {file}')

_zyg_log.info(f'Total Claude 3 entries removed: {total_removed}')
