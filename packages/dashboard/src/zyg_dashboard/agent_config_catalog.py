#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The CrewAI agent roster, one builder per department.

Extracted on 2026-10-09 from ``agent_config.AgentManager.load_agent_configurations``,
which was 325 lines of straight-line dataclass literals and therefore impossible to
assert anything about. The agent records and the ``AgentTier``/``GPUSchedule``/
``AgentConfig`` shapes live here; ``agent_config`` re-exports them so every existing
name still resolves at its old import path.

``DEPARTMENT_BUILDERS`` is the ordered list the manager walks; the order is the
insertion order ``self.agents`` had before the split and must stay that way.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class AgentTier(Enum):
    """Escalation level of an agent, from GPU worker up to the executive."""

    TIER_1 = 1  # Worker agents (GPU intensive)
    TIER_2 = 2  # Specialist agents
    TIER_3 = 3  # Coordinator agents
    TIER_4 = 4  # Department heads
    TIER_5 = 5  # Executive level


@dataclass
class GPUSchedule:
    """A tier-1 agent's claim on the GPU: share, time slots, priority and duration."""

    max_gpu_percent: int
    preferred_time_slots: List[str]
    priority_level: int
    estimated_duration_hours: float


@dataclass
class AgentConfig:
    """One agent: its crew identity, its place in the hierarchy and its capabilities."""

    name: str
    role: str
    goal: str
    backstory: str
    tier: AgentTier
    department: str
    supervisor: Optional[str]
    subordinates: List[str]
    gpu_schedule: Optional[GPUSchedule]
    tools: List[str]
    skills: List[str]
    max_concurrent_tasks: int


def executive_agents() -> Dict[str, AgentConfig]:
    """The CEO (tier 5) and the CTO (tier 4) — no GPU, strategy only."""
    return {
        'CEO': AgentConfig(
            name='CEO',
            role='Chief Executive Officer',
            goal='Oversee all operations, make strategic decisions, and ensure company success',
            backstory='Experienced CEO with 20+ years in business leadership, specializing in AI-driven companies and digital transformation',
            tier=AgentTier.TIER_5,
            department='Executive',
            supervisor=None,
            subordinates=['CTO', 'CFO', 'COO'],
            gpu_schedule=None,
            tools=['strategic_planning', 'decision_making', 'performance_analysis'],
            skills=['leadership', 'strategy', 'business_development', 'stakeholder_management'],
            max_concurrent_tasks=5,
        ),
        'CTO': AgentConfig(
            name='CTO',
            role='Chief Technology Officer',
            goal='Manage all technical operations, innovation, and technology strategy',
            backstory='Expert technologist with deep knowledge in AI, machine learning, and software architecture',
            tier=AgentTier.TIER_4,
            department='Technology',
            supervisor='CEO',
            subordinates=['Animation-Media-Overseer', 'Content-Production-Overseer'],
            gpu_schedule=None,
            tools=['technical_planning', 'architecture_design', 'innovation_management'],
            skills=['technology_strategy', 'ai_ml', 'software_architecture', 'team_leadership'],
            max_concurrent_tasks=8,
        ),
    }


def animation_media_agents() -> Dict[str, AgentConfig]:
    """The Animation-Media overseer and its four GPU-intensive tier-1 artists."""
    return {
        'Animation-Media-Overseer': AgentConfig(
            name='Animation-Media-Overseer',
            role='Animation and Media Production Director',
            goal='Oversee all animation and media production workflows',
            backstory='Experienced animation director with expertise in 2D/3D animation, AI-generated content, and media production',
            tier=AgentTier.TIER_4,
            department='Animation-Media',
            supervisor='CTO',
            subordinates=['2D-Series-Agent', '3D-Series-Agent', 'AI-Persona-Agent', 'Character-Art-Agent'],
            gpu_schedule=None,
            tools=['production_management', 'quality_control', 'workflow_optimization'],
            skills=['animation_production', 'media_management', 'team_coordination', 'quality_assurance'],
            max_concurrent_tasks=10,
        ),
        '2D-Series-Agent': AgentConfig(
            name='2D-Series-Agent',
            role='2D Animation Specialist',
            goal='Create high-quality 2D animations and series content',
            backstory='Expert 2D animator with skills in character animation, scene composition, and visual storytelling',
            tier=AgentTier.TIER_1,
            department='Animation-Media',
            supervisor='Animation-Media-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=80,
                preferred_time_slots=['09:00-12:00', '14:00-17:00'],
                priority_level=1,
                estimated_duration_hours=4.0,
            ),
            tools=['2d_animation_software', 'character_design', 'scene_composition'],
            skills=['2d_animation', 'character_design', 'visual_storytelling', 'animation_timing'],
            max_concurrent_tasks=2,
        ),
        '3D-Series-Agent': AgentConfig(
            name='3D-Series-Agent',
            role='3D Animation Specialist',
            goal='Create high-quality 3D animations and series content',
            backstory='Expert 3D animator with skills in modeling, rigging, animation, and rendering',
            tier=AgentTier.TIER_1,
            department='Animation-Media',
            supervisor='Animation-Media-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=90,
                preferred_time_slots=['10:00-13:00', '15:00-18:00'],
                priority_level=1,
                estimated_duration_hours=6.0,
            ),
            tools=['3d_animation_software', 'modeling_tools', 'rendering_engine'],
            skills=['3d_animation', 'modeling', 'rigging', 'rendering'],
            max_concurrent_tasks=1,
        ),
        'AI-Persona-Agent': AgentConfig(
            name='AI-Persona-Agent',
            role='AI Persona Creator',
            goal='Create and manage AI personas for interactive content',
            backstory='Specialist in AI personality development and character creation for interactive media',
            tier=AgentTier.TIER_1,
            department='Animation-Media',
            supervisor='Animation-Media-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=70,
                preferred_time_slots=['08:00-11:00', '13:00-16:00'],
                priority_level=2,
                estimated_duration_hours=3.0,
            ),
            tools=['ai_personality_engine', 'character_development', 'interaction_design'],
            skills=['ai_personality', 'character_development', 'interactive_media', 'user_experience'],
            max_concurrent_tasks=3,
        ),
        'Character-Art-Agent': AgentConfig(
            name='Character-Art-Agent',
            role='Character Artist',
            goal='Create compelling character designs and artwork',
            backstory='Expert character artist with skills in concept art, character design, and visual development',
            tier=AgentTier.TIER_1,
            department='Animation-Media',
            supervisor='Animation-Media-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=60,
                preferred_time_slots=['09:00-12:00', '14:00-17:00'],
                priority_level=2,
                estimated_duration_hours=3.5,
            ),
            tools=['digital_art_software', 'concept_art_tools', 'character_design_kit'],
            skills=['character_design', 'concept_art', 'visual_development', 'artistic_style'],
            max_concurrent_tasks=2,
        ),
    }


def content_production_agents() -> Dict[str, AgentConfig]:
    """The Content-Production overseer, the script writer, the editor and the renderer."""
    return {
        'Content-Production-Overseer': AgentConfig(
            name='Content-Production-Overseer',
            role='Content Production Director',
            goal='Oversee all content production workflows and quality control',
            backstory='Experienced content director with expertise in video production, editing, and content strategy',
            tier=AgentTier.TIER_4,
            department='Content-Production',
            supervisor='CTO',
            subordinates=['Script-Agent', 'Scene-Editor-Agent', 'Render-Agent', 'Upload-Agent'],
            gpu_schedule=None,
            tools=['production_management', 'quality_control', 'workflow_optimization'],
            skills=['content_production', 'video_editing', 'project_management', 'quality_assurance'],
            max_concurrent_tasks=8,
        ),
        'Script-Agent': AgentConfig(
            name='Script-Agent',
            role='Script Writer and Editor',
            goal='Create compelling scripts and storylines for content production',
            backstory='Expert scriptwriter with experience in various genres and formats',
            tier=AgentTier.TIER_1,
            department='Content-Production',
            supervisor='Content-Production-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=20,
                preferred_time_slots=['08:00-11:00', '13:00-16:00'],
                priority_level=3,
                estimated_duration_hours=2.5,
            ),
            tools=['script_writing_software', 'story_development', 'format_templates'],
            skills=['scriptwriting', 'storytelling', 'character_development', 'dialogue_writing'],
            max_concurrent_tasks=4,
        ),
        'Scene-Editor-Agent': AgentConfig(
            name='Scene-Editor-Agent',
            role='Scene Editor and Compositor',
            goal='Edit and composite scenes for final production',
            backstory='Expert video editor with skills in scene composition, color grading, and visual effects',
            tier=AgentTier.TIER_1,
            department='Content-Production',
            supervisor='Content-Production-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=85,
                preferred_time_slots=['10:00-13:00', '15:00-18:00'],
                priority_level=1,
                estimated_duration_hours=5.0,
            ),
            tools=['video_editing_software', 'compositing_tools', 'color_grading'],
            skills=['video_editing', 'compositing', 'color_grading', 'visual_effects'],
            max_concurrent_tasks=1,
        ),
        'Render-Agent': AgentConfig(
            name='Render-Agent',
            role='Rendering Specialist',
            goal='Handle all rendering tasks and optimize render pipelines',
            backstory='Expert in rendering optimization and pipeline management',
            tier=AgentTier.TIER_1,
            department='Content-Production',
            supervisor='Content-Production-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=95,
                preferred_time_slots=['00:00-06:00', '18:00-24:00'],
                priority_level=1,
                estimated_duration_hours=8.0,
            ),
            tools=['rendering_software', 'pipeline_optimization', 'batch_processing'],
            skills=['rendering', 'pipeline_optimization', 'batch_processing', 'hardware_optimization'],
            max_concurrent_tasks=1,
        ),
    }


def affiliate_marketing_agents() -> Dict[str, AgentConfig]:
    """The Affiliate-Marketing overseer with its partnership and SEO specialists."""
    return {
        'Affiliate-Marketing-Overseer': AgentConfig(
            name='Affiliate-Marketing-Overseer',
            role='Affiliate Marketing Director',
            goal='Oversee all affiliate marketing campaigns and strategies',
            backstory='Experienced marketing director with expertise in affiliate programs and digital marketing',
            tier=AgentTier.TIER_4,
            department='Affiliate-Marketing',
            supervisor='CEO',
            subordinates=['Affiliate-Marketing-Agent', 'Campaign-Builder-Agent', 'SEO-Agent'],
            gpu_schedule=None,
            tools=['campaign_management', 'analytics_platform', 'strategy_planning'],
            skills=['affiliate_marketing', 'digital_marketing', 'campaign_management', 'analytics'],
            max_concurrent_tasks=6,
        ),
        'Affiliate-Marketing-Agent': AgentConfig(
            name='Affiliate-Marketing-Agent',
            role='Affiliate Marketing Specialist',
            goal='Manage affiliate partnerships and optimize conversion rates',
            backstory='Expert in affiliate marketing with skills in partnership management and conversion optimization',
            tier=AgentTier.TIER_1,
            department='Affiliate-Marketing',
            supervisor='Affiliate-Marketing-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=30,
                preferred_time_slots=['09:00-12:00', '14:00-17:00'],
                priority_level=2,
                estimated_duration_hours=3.0,
            ),
            tools=['affiliate_platform', 'analytics_tools', 'conversion_tracking'],
            skills=['affiliate_marketing', 'partnership_management', 'conversion_optimization', 'analytics'],
            max_concurrent_tasks=3,
        ),
        'SEO-Agent': AgentConfig(
            name='SEO-Agent',
            role='SEO Specialist',
            goal='Optimize content for search engines and improve organic traffic',
            backstory='Expert SEO specialist with skills in keyword research, content optimization, and technical SEO',
            tier=AgentTier.TIER_1,
            department='Affiliate-Marketing',
            supervisor='Affiliate-Marketing-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=25,
                preferred_time_slots=['08:00-11:00', '13:00-16:00'],
                priority_level=2,
                estimated_duration_hours=2.5,
            ),
            tools=['seo_analysis_tools', 'keyword_research', 'content_optimization'],
            skills=['seo', 'keyword_research', 'content_optimization', 'technical_seo'],
            max_concurrent_tasks=4,
        ),
    }


def business_support_agents() -> Dict[str, AgentConfig]:
    """The Business-Support overseer with the financial and customer-support agents."""
    return {
        'Business-Support-Overseer': AgentConfig(
            name='Business-Support-Overseer',
            role='Business Support Director',
            goal='Oversee all business support operations and administrative functions',
            backstory='Experienced business operations director with expertise in finance, legal, and administrative management',
            tier=AgentTier.TIER_4,
            department='Business-Support',
            supervisor='CEO',
            subordinates=['Financial-Agent', 'Legal-Agent', 'Customer-Support-Agent'],
            gpu_schedule=None,
            tools=['operations_management', 'process_optimization', 'compliance_tracking'],
            skills=['business_operations', 'process_management', 'compliance', 'team_leadership'],
            max_concurrent_tasks=5,
        ),
        'Financial-Agent': AgentConfig(
            name='Financial-Agent',
            role='Financial Specialist',
            goal='Manage financial operations, budgeting, and financial reporting',
            backstory='Expert financial analyst with skills in accounting, budgeting, and financial planning',
            tier=AgentTier.TIER_1,
            department='Business-Support',
            supervisor='Business-Support-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=15,
                preferred_time_slots=['09:00-12:00', '14:00-17:00'],
                priority_level=3,
                estimated_duration_hours=2.0,
            ),
            tools=['accounting_software', 'financial_analysis', 'budgeting_tools'],
            skills=['financial_analysis', 'accounting', 'budgeting', 'financial_reporting'],
            max_concurrent_tasks=5,
        ),
        'Customer-Support-Agent': AgentConfig(
            name='Customer-Support-Agent',
            role='Customer Support Specialist',
            goal='Provide excellent customer support and handle inquiries',
            backstory='Experienced customer service professional with skills in problem-solving and communication',
            tier=AgentTier.TIER_1,
            department='Business-Support',
            supervisor='Business-Support-Overseer',
            subordinates=[],
            gpu_schedule=GPUSchedule(
                max_gpu_percent=10, preferred_time_slots=['08:00-17:00'], priority_level=4, estimated_duration_hours=1.5
            ),
            tools=['support_ticket_system', 'knowledge_base', 'communication_platform'],
            skills=['customer_service', 'problem_solving', 'communication', 'product_knowledge'],
            max_concurrent_tasks=8,
        ),
    }


# The order the manager walks: it is the insertion order self.agents had before the
# 2026-10-09 split, so get_tier_1_agents() and get_agent_hierarchy() still enumerate
# the roster exactly as they did.
# Add more agents here...
# (This is a sample of key agents - the full implementation would include all 79 agents)
DEPARTMENT_BUILDERS = (
    executive_agents,
    animation_media_agents,
    content_production_agents,
    affiliate_marketing_agents,
    business_support_agents,
)


def department_structures() -> Dict[str, Dict]:
    """The head and roster of every department, keyed by department name.

    Some rosters name agents the builders above do not define yet (Upload-Agent,
    Campaign-Builder-Agent, Legal-Agent); ``get_department_agents`` filters those out.
    """
    return {
        'Executive': {'head': 'CEO', 'agents': ['CEO']},
        'Technology': {'head': 'CTO', 'agents': ['CTO', 'Animation-Media-Overseer', 'Content-Production-Overseer']},
        'Animation-Media': {
            'head': 'Animation-Media-Overseer',
            'agents': ['2D-Series-Agent', '3D-Series-Agent', 'AI-Persona-Agent', 'Character-Art-Agent'],
        },
        'Content-Production': {
            'head': 'Content-Production-Overseer',
            'agents': ['Script-Agent', 'Scene-Editor-Agent', 'Render-Agent', 'Upload-Agent'],
        },
        'Affiliate-Marketing': {
            'head': 'Affiliate-Marketing-Overseer',
            'agents': ['Affiliate-Marketing-Agent', 'Campaign-Builder-Agent', 'SEO-Agent'],
        },
        'Business-Support': {
            'head': 'Business-Support-Overseer',
            'agents': ['Financial-Agent', 'Legal-Agent', 'Customer-Support-Agent'],
        },
    }
