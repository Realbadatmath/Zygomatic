# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from generate_agent_configurations().

Every one of these behaviours used to live inside the 312-line function and was
only reachable by running the whole generator against agents/index.json.
"""

from zyg_workflows.generate_complete_agent_config import (
    _agent_entry,
    _agents_config,
    _capabilities_for,
    _complete_config,
)


def test_a_role_collects_the_capabilities_of_every_token_it_contains():
    caps = _capabilities_for('3D Animation Supervisor')
    assert caps == ['Animation', 'Creative Design', '3D Modeling', 'Rendering']


def test_capability_order_follows_the_rule_table_not_the_role_text():
    # '2D' appears before 'Marketing' in the role, but the table tests Marketing first
    assert _capabilities_for('2D Marketing') == [
        'Marketing',
        'Campaign Management',
        '2D Animation',
        'Design',
    ]


def test_a_role_matching_no_token_falls_back_to_the_default_capabilities():
    assert _capabilities_for('Butler') == ['Task Execution', 'Collaboration']


def test_the_capability_default_is_a_fresh_list_each_call():
    first = _capabilities_for('Butler')
    first.append('Mutated')
    assert _capabilities_for('Butler') == ['Task Execution', 'Collaboration']


def test_a_mapped_agent_keeps_its_department_tier_and_models():
    entry = _agent_entry({'name': 'CEO-Agent', 'role': 'Chief Executive', 'id': 'a1'}, 'Executive-Overseer')
    assert entry['department'] == 'Executive'
    assert entry['tier'] == 'Executive'
    assert entry['ai_models'] == ['Claude 3', 'Llama 3', 'Crewai Openagents']
    assert entry['id'] == 'a1'
    assert entry['status'] == 'active'


def test_an_unmapped_agent_takes_its_department_from_the_overseer_key():
    entry = _agent_entry({'name': 'Nobody-Agent', 'role': 'Voice Acting', 'id': 'a2'}, 'Animation-Overseer')
    assert entry['department'] == 'Animation'
    assert entry['tier'] == 'Specialist'
    assert entry['ai_models'] == ['Claude 3', 'Llama 3']
    assert entry['capabilities'] == ['Voice Synthesis', 'Audio Processing']


def test_the_default_model_list_is_not_shared_between_entries():
    first = _agent_entry({'name': 'Nobody-Agent', 'role': 'Butler', 'id': 'a3'}, 'X-Overseer')
    first['ai_models'].append('Mutated')
    second = _agent_entry({'name': 'Noone-Agent', 'role': 'Butler', 'id': 'a4'}, 'X-Overseer')
    assert second['ai_models'] == ['Claude 3', 'Llama 3']


def test_goal_and_backstory_are_derived_from_the_lowercased_role():
    entry = _agent_entry({'name': 'X-Agent', 'role': 'Scene Editing', 'id': 'a5'}, 'Y-Overseer')
    assert entry['goal'] == ('Execute scene editing tasks efficiently and contribute to overall project success')
    assert entry['backstory'].startswith('Specialized agent with expertise in scene editing.')


def test_the_index_is_walked_in_file_order_and_keyed_by_agent_name():
    index = {
        'agents_by_overseer': {
            'Animation-Overseer': [
                {'name': 'A-Agent', 'role': 'Animation', 'id': '1'},
                {'name': 'B-Agent', 'role': 'Marketing', 'id': '2'},
            ],
            'Business-Support-Overseer': [{'name': 'C-Agent', 'role': 'Support', 'id': '3'}],
        }
    }
    config = _agents_config(index)
    assert list(config) == ['A-Agent', 'B-Agent', 'C-Agent']
    # an unmapped name keeps the overseer key verbatim, hyphen and all
    assert config['C-Agent']['department'] == 'Business-Support'


def test_a_name_listed_twice_keeps_its_last_entry():
    index = {
        'agents_by_overseer': {
            'One-Overseer': [{'name': 'Dup-Agent', 'role': 'Animation', 'id': 'first'}],
            'Two-Overseer': [{'name': 'Dup-Agent', 'role': 'Animation', 'id': 'second'}],
        }
    }
    config = _agents_config(index)
    assert list(config) == ['Dup-Agent']
    assert config['Dup-Agent']['id'] == 'second'


def test_the_file_level_wrapper_counts_the_agents_and_pins_the_version():
    wrapped = _complete_config({'A-Agent': {}, 'B-Agent': {}})
    assert set(wrapped) == {'agents', 'metadata'}
    assert wrapped['metadata']['total_agents'] == 2
    assert wrapped['metadata']['version'] == '1.0'
    assert wrapped['metadata']['last_updated'] == '2025-07-13'
