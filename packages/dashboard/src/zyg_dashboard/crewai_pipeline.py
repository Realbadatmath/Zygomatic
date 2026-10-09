# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
from crewai import Agent, Task, Crew

logging.basicConfig(level=logging.DEBUG)

# ── Pipeline DSL + caveman adapter (env-gated, soft-fail) ───────────────────
try:
    from zyg_workflows import pipeline_dsl_adapter as _dsl
except ImportError:
    _dsl = None


def _wrap(prompt: str) -> str:
    return _dsl.wrap_system(prompt, 'crewai') if _dsl is not None else prompt


# Use string model name for LLM (per LiteLLM/CrewAI requirements)
llm = 'ollama/llama3'

# Define agents
ceo_agent = Agent(
    name='CEO-Agent',
    role='Chief Executive Officer',
    goal=_wrap('Oversee the entire production pipeline and ensure high-quality output.'),
    backstory=_wrap('A visionary leader with years of experience in creative production and AI-driven workflows.'),
    llm=llm,
    description='Oversees all production and delegates tasks to department heads.',
)

media_head = Agent(
    name='Animation-Media-Overseer',
    role='Head of Animation/Media',
    goal=_wrap('Manage all animation and media production tasks efficiently.'),
    backstory=_wrap('An expert in animation and media, known for coordinating large creative teams.'),
    llm=llm,
    description='Manages animation and media production, coordinates with series agents.',
)

worker_agent = Agent(
    name='Scene Renderer Agent',
    role='Renders animation scenes using custom tools.',
    goal=_wrap('Render high-quality animation scenes on schedule.'),
    backstory=_wrap('A technical specialist in 3D rendering and animation pipelines.'),
    llm=llm,
    description='Handles scene rendering for animation projects.',
)

# Define tasks
scene_task = Task(
    description='Render the opening scene for the new 3D series.',
    expected_output='A rendered video file of the opening scene.',
    agent=worker_agent,
)

media_task = Task(
    description='Oversee the rendering of the opening scene for the new 3D series.',
    expected_output='Confirmation that the opening scene was rendered and reviewed.',
    agent=media_head,
    sub_tasks=[scene_task],
)

ceo_task = Task(
    description='Delegate the production of the new 3D series opening scene to the Animation/Media Overseer.',
    expected_output='A report on the successful delegation and completion of the opening scene production.',
    agent=ceo_agent,
    sub_tasks=[media_task],
)

# Create the crew and run the pipeline
crew = Crew(tasks=[ceo_task])

if __name__ == '__main__':
    try:
        result = crew.kickoff()
        print('\nPipeline Result:')
        print(result)
    except Exception as e:
        import traceback

        print(f'\nAn error occurred: {e}')
        traceback.print_exc()
