#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix Agent Configurations
This script adds missing 'goal' and 'backstory' fields to all agent configuration files
to make them compatible with the CrewAI dashboard.
"""

import json
import os
import glob

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def generate_goal_from_role(role):
    """Generate a goal based on the agent's role"""
    role_lower = role.lower()

    if 'overseer' in role_lower or 'director' in role_lower:
        return f'Oversee and coordinate {role.split("-")[0]} operations to ensure optimal performance and strategic alignment'
    elif 'agent' in role_lower:
        return f'Execute {role.split("-")[0]} tasks efficiently and collaborate with team members to achieve departmental objectives'
    elif 'specialist' in role_lower:
        return f'Provide specialized expertise in {role.split("-")[0]} to support team goals and maintain high quality standards'
    elif 'manager' in role_lower:
        return f'Manage {role.split("-")[0]} resources and processes to maximize efficiency and team productivity'
    else:
        return f'Contribute to {role.split("-")[0]} success through dedicated work and collaboration with team members'


def generate_backstory_from_role(role):
    """Generate a backstory based on the agent's role"""
    role_lower = role.lower()

    if 'overseer' in role_lower or 'director' in role_lower:
        return f'An experienced leader with deep expertise in {role.split("-")[0]} management, known for strategic thinking and team development'
    elif 'agent' in role_lower:
        return f'A skilled professional with proven track record in {role.split("-")[0]} execution, valued for reliability and innovation'
    elif 'specialist' in role_lower:
        return f'An expert in {role.split("-")[0]} with specialized knowledge and attention to detail, trusted for technical excellence'
    elif 'manager' in role_lower:
        return f'A results-driven manager with strong leadership in {role.split("-")[0]} operations, known for efficiency and team building'
    else:
        return f'A dedicated professional with solid experience in {role.split("-")[0]} work, committed to quality and continuous improvement'


def fix_agent_config_file(file_path):
    """Fix a single agent configuration file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Check if goal and backstory are missing
        needs_update = False

        if 'goal' not in config:
            config['goal'] = generate_goal_from_role(config.get('role', ''))
            needs_update = True

        if 'backstory' not in config:
            config['backstory'] = generate_backstory_from_role(config.get('role', ''))
            needs_update = True

        # Add other missing fields that might be expected
        if 'department' not in config:
            # Extract department from file path
            path_parts = file_path.split(os.sep)
            if 'agents' in path_parts:
                agents_index = path_parts.index('agents')
                if agents_index + 1 < len(path_parts):
                    config['department'] = path_parts[agents_index + 1]
            needs_update = True

        if 'tier' not in config:
            # Determine tier based on role
            role = config.get('role', '').lower()
            if 'overseer' in role or 'director' in role:
                config['tier'] = 4
            elif 'manager' in role or 'lead' in role:
                config['tier'] = 3
            elif 'specialist' in role or 'senior' in role:
                config['tier'] = 2
            else:
                config['tier'] = 1
            needs_update = True

        if 'supervisor' not in config:
            config['supervisor'] = None
            needs_update = True

        if 'subordinates' not in config:
            config['subordinates'] = []
            needs_update = True

        if 'ai_models' not in config:
            config['ai_models'] = []
            needs_update = True

        if 'gpu_schedule' not in config:
            config['gpu_schedule'] = None
            needs_update = True

        if 'tools' not in config:
            config['tools'] = []
            needs_update = True

        if 'skills' not in config:
            config['skills'] = []
            needs_update = True

        if 'max_concurrent_tasks' not in config:
            config['max_concurrent_tasks'] = 1
            needs_update = True

        if 'current_tasks' not in config:
            config['current_tasks'] = 0
            needs_update = True

        if 'primary_task' not in config:
            config['primary_task'] = config.get('tasks', [''])[0] if config.get('tasks') else ''
            needs_update = True

        # Save the updated configuration
        if needs_update:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True

        return False

    except Exception as e:
        _zyg_log.info(f'Error processing {file_path}: {e}')
        return False


def fix_all_agent_configs():
    """Fix all agent configuration files"""
    agents_dir = 'agents'
    fixed_count = 0
    total_count = 0

    _zyg_log.info('🔧 Fixing agent configuration files...')

    # Find all JSON files in the agents directory
    json_files = glob.glob(os.path.join(agents_dir, '**/*.json'), recursive=True)

    for file_path in json_files:
        total_count += 1
        if fix_agent_config_file(file_path):
            fixed_count += 1
            _zyg_log.info(f'✅ Fixed: {file_path}')

    _zyg_log.info('\n📊 SUMMARY:')
    _zyg_log.info(f'Total files processed: {total_count}')
    _zyg_log.info(f'Files updated: {fixed_count}')
    _zyg_log.info(f'Files already correct: {total_count - fixed_count}')

    return fixed_count


def verify_fixes():
    """Verify that all required fields are present"""
    agents_dir = 'agents'
    missing_fields = []

    _zyg_log.info('\n🔍 Verifying fixes...')

    json_files = glob.glob(os.path.join(agents_dir, '**/*.json'), recursive=True)

    for file_path in json_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            required_fields = [
                'goal',
                'backstory',
                'department',
                'tier',
                'supervisor',
                'subordinates',
                'ai_models',
                'gpu_schedule',
                'tools',
                'skills',
                'max_concurrent_tasks',
                'current_tasks',
                'primary_task',
            ]

            for field in required_fields:
                if field not in config:
                    missing_fields.append(f'{file_path}: {field}')

        except Exception as e:
            missing_fields.append(f'{file_path}: Error reading file - {e}')

    if missing_fields:
        _zyg_log.info('❌ Missing fields found:')
        for field in missing_fields:
            _zyg_log.info(f'  {field}')
    else:
        _zyg_log.info('✅ All required fields are present!')


if __name__ == '__main__':
    fix_all_agent_configs()
    verify_fixes()
