# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.debug_timeline_backend`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.debug_timeline_backend` still reaches it.
"""

import sys
from datetime import datetime

# Imported first: the library module's sys.path.append makes the Schedule directory importable.
from zyg_dashboard.debug_timeline_backend import print_timeline_data
from zyg_dashboard.Schedule.timeline_orchestrator_dual import DualTimelineOrchestrator
from zyg_workflows.ai_model_agent_mapping import model_to_agents


def main() -> int:
    """The command line that used to live in debug_timeline_backend.main()."""
    date = datetime.now().strftime('%Y-%m-%d')
    if len(sys.argv) > 1:
        date = sys.argv[1]
    print(f'Debugging timeline data for date: {date}')
    orchestrator = DualTimelineOrchestrator(
        cpu_schedule_file='schedule_data_CPU.json', gpu_schedule_file='schedule_data_GPU.json'
    )
    cpu_data = orchestrator.get_cpu_timeline_data('24h', date=date)
    gpu_data = orchestrator.get_gpu_timeline_data('24h', date=date)
    print_timeline_data(cpu_data, 'CPU')
    print_timeline_data(gpu_data, 'GPU')
    print('\n=== Model to Agents Mapping (first 5 models) ===')
    for i, (model, agents) in enumerate(model_to_agents.items()):
        if i >= 5:
            break
        print(f'{model}: {agents}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
