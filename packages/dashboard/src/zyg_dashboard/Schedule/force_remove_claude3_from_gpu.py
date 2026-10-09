# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

path = 'Schedule/agent_model_bar_mapping.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

changed = 0
for _agent, info in data.items():
    models = info.get('models', [])
    new_models = [m for m in models if m.get('model') != '1017' and 'claude' not in m.get('bar_id', '').lower()]
    if len(new_models) != len(models):
        changed += 1
    info['models'] = new_models

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

_zyg_log.info(f'Removed Claude 3 from {changed} agents in GPU mapping.')
