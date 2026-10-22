# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.Schedule.timeline_orchestrator_dual`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.Schedule.timeline_orchestrator_dual` still reaches it."""

import sys

from zyg_dashboard.Schedule.timeline_orchestrator_dual import DualTimelineOrchestrator


def main():
    """Main function for testing"""
    orchestrator = DualTimelineOrchestrator()

    # Test CPU timeline
    print('Testing CPU timeline...')
    cpu_data = orchestrator.get_cpu_timeline_data('24h')
    print(f'CPU 24h data: {cpu_data}')

    # Test GPU timeline
    print('\nTesting GPU timeline...')
    gpu_data = orchestrator.get_gpu_timeline_data('24h')
    print(f'GPU 24h data: {gpu_data}')

    # Test combined timeline
    print('\nTesting combined timeline...')
    combined_data = orchestrator.get_combined_timeline_data('24h')
    print(f'Combined 24h data: {combined_data}')


if __name__ == '__main__':
    sys.exit(main())
