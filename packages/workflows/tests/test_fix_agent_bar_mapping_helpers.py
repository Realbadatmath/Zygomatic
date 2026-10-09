# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from ``AgentBarMappingFixer.__init__``."""

import os
from pathlib import Path

from zyg_workflows import fix_agent_bar_mapping_tables as tables
from zyg_workflows.fix_agent_bar_mapping import AgentBarMappingFixer


def test_tier_mapping_ranks_every_tier_name():
    """The tier table keeps the 1-5 ranking the old __init__ literal had."""
    mapping = tables.tier_mapping()
    assert mapping == {
        'Specialist': 1,
        'Management': 2,
        'Director': 3,
        'Overseer': 4,
        'Executive': 5,
    }


def test_tier_mapping_hands_out_a_private_copy():
    """Mutating one caller's tier table cannot be seen by the next caller."""
    first = tables.tier_mapping()
    first['Specialist'] = 99
    assert tables.tier_mapping()['Specialist'] == 1


def test_gpu_model_names_is_a_set_of_display_names():
    """The GPU set holds the gpu_ai_models.json display names, not identifiers."""
    names = tables.gpu_model_names()
    assert isinstance(names, set)
    assert 'Stable Diffusion 1.5 XL' in names
    assert 'Bark' in names
    assert 'Claude 3' not in names
    assert len(names) == 17


def test_gpu_model_names_hands_out_a_private_copy():
    """Discarding a name from one copy leaves the table intact."""
    first = tables.gpu_model_names()
    first.discard('Bark')
    assert 'Bark' in tables.gpu_model_names()


def test_agent_ai_model_mapping_lists_agents_per_model():
    """Each model key maps to the list of agent names that used it before the split."""
    mapping = tables.agent_ai_model_mapping()
    assert mapping['Tortoise TTS'] == [
        '2D-Voice-Agent',
        '3D-Voice-Agent',
        'YouTube-Audio-Agent',
    ]
    assert mapping['Fastapi'] == [
        'Affiliate-Marketing-Overseer',
        'Business-Support-Director-Agent',
        'Content-Production-Director-Agent',
        'YouTube-Content-Director-Agent',
    ]
    assert len(mapping) == 20


def test_agent_ai_model_mapping_copies_the_nested_lists():
    """Appending to one copy's list does not leak into the next copy."""
    first = tables.agent_ai_model_mapping()
    first['Tortoise TTS'].append('Intruder-Agent')
    assert 'Intruder-Agent' not in tables.agent_ai_model_mapping()['Tortoise TTS']


def test_resolve_dirs_makes_the_agents_dir_absolute_and_derives_the_index():
    """A relative agents dir is resolved against the cwd and gains index.json."""
    agents, schedule, index = tables.resolve_dirs('crewai_project/agents', 'Schedule')
    assert agents == Path(os.path.abspath('crewai_project/agents'))
    assert agents.is_absolute()
    assert index == agents / 'index.json'
    assert schedule == Path('Schedule')
    assert not schedule.is_absolute()


def test_resolve_dirs_keeps_an_absolute_agents_dir_unchanged(tmp_path):
    """An already absolute agents dir survives the abspath round trip."""
    agents, schedule, index = tables.resolve_dirs(str(tmp_path / 'agents'), str(tmp_path / 'sched'))
    assert agents == tmp_path / 'agents'
    assert schedule == tmp_path / 'sched'
    assert index == tmp_path / 'agents' / 'index.json'


def test_get_agent_models_still_reads_the_extracted_table():
    """The fixer's lookup over the moved table behaves as it did inline."""
    fixer = AgentBarMappingFixer()
    assert fixer.get_agent_models('Tortoise-Agent-That-Does-Not-Exist') == ['Claude 3', 'Llama 3']
    assert 'Tortoise TTS' in fixer.get_agent_models('2D-Voice-Agent')


def test_two_fixers_do_not_share_their_tables():
    """Each instance gets its own tables, exactly as the old literals did."""
    one = AgentBarMappingFixer()
    two = AgentBarMappingFixer()
    assert one.agent_ai_model_mapping is not two.agent_ai_model_mapping
    assert one.tier_mapping is not two.tier_mapping
    assert one.gpu_models is not two.gpu_models
    one.gpu_models.clear()
    assert two.gpu_models
