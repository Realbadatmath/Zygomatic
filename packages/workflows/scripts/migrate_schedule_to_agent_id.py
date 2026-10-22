# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

AGENT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'agent_configurations.json')
SCHEDULE_FILES = [
    os.path.join(os.path.dirname(__file__), 'Schedule', 'schedule_data_CPU.json'),
    os.path.join(os.path.dirname(__file__), 'Schedule', 'schedule_data_GPU.json'),
]


def load_agent_id_map():
    with open(AGENT_CONFIG_PATH, 'r') as f:
        agents = json.load(f)['agents']
    return {a['name']: a['id'] for a in agents.values()}


def migrate_schedule_file(path, agent_id_map):
    with open(path, 'r') as f:
        data = json.load(f)
    changed = False
    for _date, entries in data.items():
        for entry in entries:
            if 'agent' in entry and 'agent_id' not in entry:
                agent_name = entry['agent']
                agent_id = agent_id_map.get(agent_name)
                if agent_id:
                    entry['agent_id'] = agent_id
                    changed = True
    if changed:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        _zyg_log.info(f'Migrated {path}: updated agent names to agent IDs.')
    else:
        _zyg_log.info(f'No changes needed for {path}.')


def main():
    agent_id_map = load_agent_id_map()
    for path in SCHEDULE_FILES:
        if os.path.exists(path):
            migrate_schedule_file(path, agent_id_map)
        else:
            print(f'File not found: {path}')


if __name__ == '__main__':
    main()
