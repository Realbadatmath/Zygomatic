# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the department builders split out of ``load_agent_configurations``.

That method was 325 lines of straight-line dataclass literals; nothing about the
roster could be asserted without constructing an ``AgentManager``. Since the
2026-10-09 split each department is its own pure builder, so the roster, the
insertion order and every tier-1 GPU claim are checkable directly.

These tests import ``zyg_dashboard`` from the workflows test tree on purpose — the
task's ``verify_cmd`` runs all three new test files from ``packages/workflows``.
"""

import dataclasses

import pytest

from zyg_dashboard.agent_config_catalog import (
    DEPARTMENT_BUILDERS,
    AgentConfig,
    AgentTier,
    GPUSchedule,
    affiliate_marketing_agents,
    animation_media_agents,
    business_support_agents,
    content_production_agents,
    department_structures,
    executive_agents,
)


def _roster():
    """The merged roster, in exactly the order the manager builds it."""
    agents = {}
    for build in DEPARTMENT_BUILDERS:
        agents.update(build())
    return agents


# ── the individual builders ───────────────────────────────────────────────────


def test_executive_agents_are_the_ceo_and_the_cto():
    d = executive_agents()
    assert list(d) == ['CEO', 'CTO']
    assert d['CEO'].tier is AgentTier.TIER_5
    assert d['CEO'].supervisor is None
    assert d['CTO'].tier is AgentTier.TIER_4
    assert d['CTO'].supervisor == 'CEO'
    assert all(a.gpu_schedule is None for a in d.values()), 'the executive never takes the GPU'


def test_animation_media_agents_are_an_overseer_and_four_gpu_artists():
    d = animation_media_agents()
    assert list(d) == [
        'Animation-Media-Overseer',
        '2D-Series-Agent',
        '3D-Series-Agent',
        'AI-Persona-Agent',
        'Character-Art-Agent',
    ]
    assert d['Animation-Media-Overseer'].gpu_schedule is None
    workers = [k for k in d if k != 'Animation-Media-Overseer']
    for name in workers:
        assert d[name].tier is AgentTier.TIER_1, name
        assert isinstance(d[name].gpu_schedule, GPUSchedule), name
        assert d[name].supervisor == 'Animation-Media-Overseer', name


def test_content_production_agents_report_to_their_own_overseer():
    d = content_production_agents()
    assert list(d) == ['Content-Production-Overseer', 'Script-Agent', 'Scene-Editor-Agent', 'Render-Agent']
    # 'Upload-Agent' is claimed but was never defined — a pre-existing gap in the
    # roster this split preserves verbatim rather than quietly closing.
    assert d['Content-Production-Overseer'].subordinates == [
        'Script-Agent',
        'Scene-Editor-Agent',
        'Render-Agent',
        'Upload-Agent',
    ]
    assert d['Render-Agent'].gpu_schedule.max_gpu_percent > 0


def test_affiliate_and_business_support_builders():
    aff = affiliate_marketing_agents()
    biz = business_support_agents()
    assert list(aff) == ['Affiliate-Marketing-Overseer', 'Affiliate-Marketing-Agent', 'SEO-Agent']
    assert list(biz) == ['Business-Support-Overseer', 'Financial-Agent', 'Customer-Support-Agent']
    assert aff['Affiliate-Marketing-Overseer'].department == 'Affiliate-Marketing'
    assert biz['Business-Support-Overseer'].department == 'Business-Support'


def test_every_builder_returns_a_fresh_dict_of_agent_configs():
    """A shared literal would let one manager mutate another's roster."""
    for build in DEPARTMENT_BUILDERS:
        first, second = build(), build()
        assert first is not second
        assert list(first) == list(second)
        for name, agent in first.items():
            assert isinstance(agent, AgentConfig), name
            assert agent is not second[name], name


# ── the merged roster ─────────────────────────────────────────────────────────


def test_department_builders_preserve_the_original_insertion_order():
    assert [b.__name__ for b in DEPARTMENT_BUILDERS] == [
        'executive_agents',
        'animation_media_agents',
        'content_production_agents',
        'affiliate_marketing_agents',
        'business_support_agents',
    ]
    assert list(_roster())[:3] == ['CEO', 'CTO', 'Animation-Media-Overseer']


def test_the_roster_has_seventeen_agents_with_no_name_collisions():
    agents = _roster()
    assert len(agents) == 17
    built = sum(len(build()) for build in DEPARTMENT_BUILDERS)
    assert built == 17, 'a duplicate key would silently shrink the merged roster'


def test_every_agent_record_is_fully_populated():
    for name, agent in _roster().items():
        assert agent.name == name, f'{name} key and .name disagree'
        assert agent.role and agent.goal and agent.backstory, name
        assert isinstance(agent.tier, AgentTier), name
        assert agent.department, name
        assert isinstance(agent.subordinates, list), name
        assert agent.tools and agent.skills, name
        assert agent.max_concurrent_tasks >= 1, name


def test_only_tier_1_agents_claim_the_gpu():
    for name, agent in _roster().items():
        if agent.gpu_schedule is None:
            continue
        assert agent.tier is AgentTier.TIER_1, f'{name} is not tier 1 but claims the GPU'
        sched = agent.gpu_schedule
        assert 0 < sched.max_gpu_percent <= 100, name
        assert sched.preferred_time_slots, name
        assert sched.priority_level >= 1, name
        assert sched.estimated_duration_hours > 0, name


def test_every_supervisor_is_a_real_agent():
    agents = _roster()
    for name, agent in agents.items():
        if agent.supervisor is not None:
            assert agent.supervisor in agents, f'{name} reports to the unknown {agent.supervisor}'


def test_the_dangling_subordinate_names_are_exactly_the_five_known_ones():
    """The roster has always claimed five agents it never defines.

    Pinned deliberately: the split must not add to this set, and the day somebody
    defines one of them this test says so instead of letting the gap drift.
    """
    agents = _roster()
    claimed = {sub for agent in agents.values() for sub in agent.subordinates}
    assert sorted(claimed - set(agents)) == [
        'CFO',
        'COO',
        'Campaign-Builder-Agent',
        'Legal-Agent',
        'Upload-Agent',
    ]


# ── department_structures ─────────────────────────────────────────────────────


def test_department_structures_heads_and_rosters():
    ds = department_structures()
    assert list(ds) == [
        'Executive',
        'Technology',
        'Animation-Media',
        'Content-Production',
        'Affiliate-Marketing',
        'Business-Support',
    ]
    assert ds['Executive'] == {'head': 'CEO', 'agents': ['CEO']}
    assert ds['Technology'] == {
        'head': 'CTO',
        'agents': ['CTO', 'Animation-Media-Overseer', 'Content-Production-Overseer'],
    }
    assert ds['Animation-Media'] == {
        'head': 'Animation-Media-Overseer',
        'agents': ['2D-Series-Agent', '3D-Series-Agent', 'AI-Persona-Agent', 'Character-Art-Agent'],
    }
    for dept, rec in ds.items():
        assert set(rec) == {'head', 'agents'}, dept
        assert rec['head'] in _roster(), f'{dept} head {rec["head"]} is not an agent'


def test_every_department_head_is_the_supervisor_of_its_own_members():
    """Outside Executive/Technology a roster lists the head's reports, not the head."""
    agents = _roster()
    for dept, rec in department_structures().items():
        if dept in ('Executive', 'Technology'):
            continue
        assert rec['head'] not in rec['agents'], dept
        for name in rec['agents']:
            if name not in agents:
                continue  # one of the five never-defined names
            assert agents[name].supervisor == rec['head'], f'{name} does not report to {rec["head"]}'


def test_the_department_rosters_name_only_defined_agents_or_the_known_gaps():
    agents = _roster()
    missing = sorted({name for rec in department_structures().values() for name in rec['agents']} - set(agents))
    assert missing == ['Campaign-Builder-Agent', 'Legal-Agent', 'Upload-Agent']


def test_department_structures_returns_a_fresh_mutable_record_each_call():
    first = department_structures()
    first['Executive']['agents'].append('INTRUDER')
    assert department_structures()['Executive']['agents'] == ['CEO']


# ── the manager still behaves as before the split ─────────────────────────────


def test_agent_manager_loads_the_roster_through_the_builders():
    agent_config = pytest.importorskip('zyg_dashboard.agent_config')
    manager = agent_config.AgentManager()
    assert list(manager.agents) == list(_roster())
    assert manager.departments == department_structures()
    # the old names are still importable from the old module
    assert agent_config.AgentTier is AgentTier
    assert agent_config.GPUSchedule is GPUSchedule
    assert agent_config.AgentConfig is AgentConfig


def test_agent_manager_queries_match_the_catalog():
    agent_config = pytest.importorskip('zyg_dashboard.agent_config')
    manager = agent_config.AgentManager()
    roster = _roster()
    expected_tier_1 = [n for n, a in roster.items() if a.tier is AgentTier.TIER_1]
    assert [a.name for a in manager.get_tier_1_agents()] == expected_tier_1
    assert len(expected_tier_1) == 11
    assert [a.name for a in manager.get_department_agents('Animation-Media')] == department_structures()[
        'Animation-Media'
    ]['agents']
    assert manager.get_department_agents('No-Such-Department') == []
    assert manager.get_agent('No-Such-Agent') is None
    assert dataclasses.asdict(manager.get_agent('CEO')) == dataclasses.asdict(roster['CEO'])


def test_agent_hierarchy_flattens_the_gpu_schedule():
    agent_config = pytest.importorskip('zyg_dashboard.agent_config')
    hierarchy = agent_config.AgentManager().get_agent_hierarchy()
    assert list(hierarchy) == list(_roster())
    assert hierarchy['CEO']['tier'] == 5
    assert hierarchy['CEO']['gpu_schedule'] is None
    render = hierarchy['Render-Agent']['gpu_schedule']
    assert set(render) == {
        'max_gpu_percent',
        'preferred_time_slots',
        'priority_level',
        'estimated_duration_hours',
    }
