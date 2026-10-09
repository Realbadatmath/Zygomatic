#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
CrewAI Command Line Interface
Simple CLI to control your agent hierarchy
"""

from crewai import Agent, Task, Crew, Process
from langchain_community.llms import Ollama


class CrewAICLI:
    def __init__(self):
        self.llm = Ollama(model='llama3')
        self.agents = {}
        self.crews = {}

    def setup_agents(self):
        """Initialize all agents in the hierarchy"""
        print('Setting up agent hierarchy...')

        # CEO Agent (Tier 5)
        self.agents['CEO'] = Agent(
            role='Chief Executive Officer',
            goal='Oversee all operations and make strategic decisions',
            backstory='Experienced CEO with deep understanding of business operations',
            verbose=True,
            allow_delegation=True,
            llm=self.llm,
        )

        # Department Heads (Tier 4)
        self.agents['CTO'] = Agent(
            role='Chief Technology Officer',
            goal='Manage all technical operations and innovation',
            backstory='Expert technologist with years of experience in software development',
            verbose=True,
            allow_delegation=True,
            llm=self.llm,
        )

        self.agents['CFO'] = Agent(
            role='Chief Financial Officer',
            goal='Manage financial operations and budgeting',
            backstory='Experienced financial executive with strong analytical skills',
            verbose=True,
            allow_delegation=True,
            llm=self.llm,
        )

        # Worker Agents (Tier 1-3)
        self.agents['Developer'] = Agent(
            role='Software Developer',
            goal='Write high-quality code and implement features',
            backstory='Skilled programmer with expertise in multiple languages',
            verbose=True,
            llm=self.llm,
        )

        self.agents['Analyst'] = Agent(
            role='Data Analyst',
            goal='Analyze data and provide insights',
            backstory='Expert in data analysis and business intelligence',
            verbose=True,
            llm=self.llm,
        )

        print('✓ Agents initialized successfully!')

    def create_task(self, agent_name, description):
        """Create a task for a specific agent"""
        if agent_name not in self.agents:
            print(f"❌ Agent '{agent_name}' not found!")
            return None

        return Task(
            description=description,
            agent=self.agents[agent_name],
            expected_output='Detailed response with actionable insights',
        )

    def run_single_agent_task(self):
        """Run a task with a single agent"""
        print('\n=== Single Agent Task ===')
        print('Available agents:')
        for i, agent_name in enumerate(self.agents.keys(), 1):
            print(f'{i}. {agent_name}')

        try:
            choice = int(input('\nSelect agent (number): ')) - 1
            agent_name = list(self.agents.keys())[choice]

            task_description = input('Enter task description: ')

            print(f'\n🔄 Running task with {agent_name}...')
            task = self.create_task(agent_name, task_description)

            if task:
                crew = Crew(agents=[self.agents[agent_name]], tasks=[task], verbose=True, process=Process.sequential)

                result = crew.kickoff()
                print(f'\n✅ Result from {agent_name}:')
                print(result)

        except (ValueError, IndexError):
            print('❌ Invalid selection!')

    def run_multi_agent_crew(self):
        """Run a task with multiple agents working together"""
        print('\n=== Multi-Agent Crew ===')
        print('Available agents:')
        for i, agent_name in enumerate(self.agents.keys(), 1):
            print(f'{i}. {agent_name}')

        print('\nSelect agents (comma-separated numbers, e.g., 1,3,4):')
        try:
            choices = input('Agent numbers: ').split(',')
            selected_agents = []

            for choice in choices:
                agent_idx = int(choice.strip()) - 1
                agent_name = list(self.agents.keys())[agent_idx]
                selected_agents.append(self.agents[agent_name])

            task_description = input('Enter overall task description: ')

            print('\n🔄 Running multi-agent task...')

            # Create tasks for each agent
            tasks = []
            for agent in selected_agents:
                task = Task(
                    description=f'Contribute to: {task_description}',
                    agent=agent,
                    expected_output='Your contribution to the overall task',
                )
                tasks.append(task)

            crew = Crew(agents=selected_agents, tasks=tasks, verbose=True, process=Process.sequential)

            result = crew.kickoff()
            print('\n✅ Multi-agent result:')
            print(result)

        except (ValueError, IndexError):
            print('❌ Invalid selection!')

    def show_agent_info(self):
        """Display information about all agents"""
        print('\n=== Agent Information ===')
        for name, agent in self.agents.items():
            print(f'\n🤖 {name}')
            print(f'   Role: {agent.role}')
            print(f'   Goal: {agent.goal}')
            print(f'   Backstory: {agent.backstory[:100]}...')

    def main_menu(self):
        """Main CLI menu"""
        while True:
            print('\n' + '=' * 50)
            print('🤖 CREWAI AGENT CONTROL INTERFACE')
            print('=' * 50)
            print('1. Show Agent Information')
            print('2. Run Single Agent Task')
            print('3. Run Multi-Agent Crew')
            print('4. Exit')
            print('-' * 50)

            choice = input('Select option (1-4): ').strip()

            if choice == '1':
                self.show_agent_info()
            elif choice == '2':
                self.run_single_agent_task()
            elif choice == '3':
                self.run_multi_agent_crew()
            elif choice == '4':
                print('👋 Goodbye!')
                break
            else:
                print('❌ Invalid option! Please select 1-4.')


def main():
    print('🚀 Initializing CrewAI CLI...')
    cli = CrewAICLI()
    cli.setup_agents()
    cli.main_menu()


if __name__ == '__main__':
    main()
