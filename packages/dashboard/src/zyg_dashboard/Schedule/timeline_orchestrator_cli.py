# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.timeline_orchestrator`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.timeline_orchestrator` still reaches it."""

import sys


def main():
    """Main function for testing the orchestrator"""
    # The library module does not import on a bare checkout (it is on tests/import_smoke_skip.txt),
    # so the CLI imports it only when it actually runs — the smoke test imports this module clean.
    from zyg_dashboard.Schedule.timeline_orchestrator import (
        TimelineOrchestrator,
        _ams_now,
    )

    orchestrator = TimelineOrchestrator()

    print('=== CrewAI Timeline Orchestrator ===')
    print(f'Current date: {_ams_now().strftime("%Y-%m-%d")}')

    # Test getting data for each timeline
    print('\n1. Testing timeline data retrieval:')
    for timeline_type in ['24h', '7d', '28d', '1y', 'history', 'add_entry']:
        data = orchestrator.get_timeline_data(timeline_type)
        if 'error' not in data:
            print(f'  ✓ {timeline_type}: Data retrieved successfully')
        else:
            print(f'  ✗ {timeline_type}: {data["error"]}')

    # Test adding a sample entry
    print('\n2. Testing entry addition:')
    sample_entry = orchestrator.add_entry.create_sample_entry('Claude_3')
    result = orchestrator.add_schedule_entry(sample_entry)
    print(f'  Add entry result: {result}')

    # Test validation
    print('\n3. Testing entry validation:')
    validation_result = orchestrator.validate_entry(sample_entry)
    print(f'  Validation result: {validation_result}')

    # Test available models
    print('\n4. Available AI models:')
    models = orchestrator.get_available_models()
    for model in models[:5]:  # Show first 5
        count = orchestrator.get_model_agent_count(model)
        print(f'  {model}: {count} agents')

    # Generate comprehensive summary
    print('\n5. Generating comprehensive summary:')
    summary = orchestrator.get_comprehensive_summary()
    print(f'  Summary generated with {len(summary)} sections')

    # Export data
    print('\n6. Testing data export:')
    export_result = orchestrator.export_schedule_data('test_export.json')
    print(f'  {export_result}')

    print('\n=== Orchestrator test completed ===')


if __name__ == '__main__':
    sys.exit(main())
