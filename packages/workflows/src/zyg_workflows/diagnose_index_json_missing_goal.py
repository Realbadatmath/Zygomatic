#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Diagnose index.json for missing 'goal' field in agent entries.
"""

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def diagnose_missing_goal():
    index_path = os.path.join('agents', 'index.json')
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)

    missing_goal = []
    for overseer, agents in index_data.get('agents_by_overseer', {}).items():
        for agent in agents:
            if 'goal' not in agent:
                missing_goal.append((overseer, agent.get('name'), agent.get('file')))

    if missing_goal:
        _zyg_log.info(f"Agents missing 'goal' field in index.json: {len(missing_goal)}")
        for overseer, name, file in missing_goal:
            _zyg_log.info(f'  Overseer: {overseer}, Agent: {name}, File: {file}')
    else:
        _zyg_log.info("✅ All agent entries in index.json have a 'goal' field.")


if __name__ == '__main__':
    diagnose_missing_goal()
