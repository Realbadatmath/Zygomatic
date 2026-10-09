#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The CrewAI controller: the Ollama LLM probe, the model-tier picker, the
``CrewAIController`` class and the single process-wide ``controller`` instance.

Moved verbatim out of crewai_web_gui.py (2026-10-06 round-2 split).

crewai is an OPTIONAL dependency here. Every ``from crewai import ...`` in this
module is either inside a ``try: ... except ImportError`` or inside the function
that needs the name, so importing this module — and therefore importing
``zyg_dashboard.crewai_web_gui`` — succeeds in an environment that has no crewai
installed. Without it ``OLLAMA_AVAILABLE`` is False and the controller hands out
MockAgent objects, exactly as it already did when the Ollama probe failed.

Import order matters: ``controller = CrewAIController()`` runs at import time and
reaches back into crewai_web_gui for ``_load_canonical_json`` and
``_get_all_tools``, so crewai_web_gui must import this module from the point in
the file where the class used to stand — after those two are defined.
"""

import logging as _zyg_logging

import requests
from zyg_workflows import runtime
from zyg_workflows.paths import ZYG_OLLAMA_URL

from zyg_dashboard.gui.telemetry import _backend_debug

_zyg_log = _zyg_logging.getLogger(__name__)

# Use crewai.LLM directly — it wraps LiteLLM and works with Ollama via 'ollama/model' prefix.
# We no longer depend on langchain_ollama at all.
try:
    from crewai import LLM as CrewAILLM

    # Agent/Crew/Process/Task are bound here only to keep the re-export surface intact:
    # bp_pipeline_api.py does `from zyg_dashboard.crewai_web_gui import Crew, Process, Task`,
    # and Agent is used by setup_agents below. Guarded, so crewai stays optional.
    from crewai import Agent, Crew, Process, Task

    from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL  # noqa: E402  kept at the old definition site

    # Verify Ollama is reachable. safe_urlopen, not urllib: _OLLAMA_BASE_URL is
    # env-overridable, and safe_urlopen is where the http(s)-only check lives.
    from zyg_workflows.net import safe_urlopen

    try:
        safe_urlopen(_OLLAMA_BASE_URL + '/api/tags', timeout=3).close()
        OLLAMA_AVAILABLE = True
    except Exception:
        OLLAMA_AVAILABLE = False
    Ollama = CrewAILLM  # keep name for compatibility with rest of file
except ImportError:
    CrewAILLM = None
    Agent = Crew = Process = Task = None
    Ollama = None
    OLLAMA_AVAILABLE = False
    _backend_debug('crewai.LLM not available. Using mock LLM.')
    from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL  # noqa: E402  kept at the old definition site


# Prefer the most capable model available; fall back down the list
# qwen2.5:72b REMOVED 2026-08-26 — Qwen Research licence (non-commercial only).
# It sat last here, so with qwen3.6:35b-a3b installed it was already unreachable.
_PREFERRED_MODELS = ['qwen3.6:35b-a3b', 'gpt-oss:20b', 'llama3:70b', 'mistral:7b']


def _pick_ollama_model():
    """Return the first model in the preference list that Ollama has available."""
    try:
        import requests as _req

        resp = _req.get(f'{ZYG_OLLAMA_URL.rstrip("/")}/api/tags', timeout=3)
        available = {m['name'] for m in resp.json().get('models', [])}
        for m in _PREFERRED_MODELS:
            if m in available:
                return m
        if available:
            return next(iter(available))
    except Exception as _exc:
        _zyg_log.debug('ollama model list unavailable, using the default model: %s', _exc)
    return 'gpt-oss:20b'  # final fallback name


# ---------------------------------------------------------------------------
# Model tier assignment — maps agent name substrings (lower) to Ollama model.
# Heavy reasoning → qwen3.6:35b-a3b (MoE, native tool-calling; replaced
# agent-untrained llama3:70b 2026-08-09). Everything else → gpt-oss:20b.
# ---------------------------------------------------------------------------
_HEAVY_REASONING_KEYWORDS = [
    'overseer',
    'research',
    'hook',
    'commentary',
    'winner',
    'feedback',
    'zero',
]


def _pick_model_for_agent(agent_name: str, available_models: set) -> str:
    """Return the best Ollama model for this agent based on its reasoning needs."""
    # Normalise: replace hyphens/underscores with spaces for consistent matching
    name_lower = agent_name.lower().replace('-', ' ').replace('_', ' ')
    needs_heavy = any(kw in name_lower for kw in _HEAVY_REASONING_KEYWORDS)
    if needs_heavy:
        for m in ('qwen3.6:35b-a3b', 'llama3:70b'):
            if m in available_models:
                return m
    # Fallback chain for light agents (gpt-oss:20b first — fastest for tool calls)
    for m in ['gpt-oss:20b', 'qwen3.6:35b-a3b', 'mistral:7b', 'llama3:70b']:
        if m in available_models:
            return m
    return next(iter(available_models)) if available_models else 'gpt-oss:20b'


class CrewAIController:
    def __init__(self):
        # Fetch available models once so setup_agents can assign per-agent
        self._available_models = set()
        self._llm_cache = {}  # model_name -> Ollama instance (reuse, don't recreate)
        self.llm = None  # default LLM (lightest available)
        if OLLAMA_AVAILABLE:
            try:
                self._available_models = self._fetch_available_models()
                default_model = _pick_ollama_model()
                self.llm = self._get_llm(default_model)
                _backend_debug(f'Ollama ready. Default model: {default_model}. Available: {self._available_models}')
            except Exception as e:
                _backend_debug(f'Could not initialize Ollama: {e}. Using mock LLM.')

        self.agents = {}
        self.agent_configs = {}
        self.agent_allowed_models = {}
        self.setup_agents()
        _backend_debug(f'Loaded {len(self.agent_configs)} agents: {list(self.agent_configs.keys())[:5]}...')

    def _fetch_available_models(self) -> set:
        try:
            r = requests.get(f'{ZYG_OLLAMA_URL.rstrip("/")}/api/tags', timeout=3)
            return {m['name'] for m in r.json().get('models', [])}
        except Exception:
            return set()

    _warned_no_crewai = False

    def _get_llm(self, model_name: str):
        """Return a cached crewai.LLM instance for an Ollama model, or None without crewai.

        Ollama answering on this box does not imply crewai is installed: the probe above
        only runs inside the import that binds CrewAILLM, but OLLAMA_AVAILABLE is read by
        callers that cannot know which branch set it. With no CrewAILLM there is nothing to
        bind, so the agents run unbound (MockAgent) instead of raising TypeError at import.
        """
        if CrewAILLM is None:
            if not CrewAIController._warned_no_crewai:
                CrewAIController._warned_no_crewai = True
                _zyg_log.warning('crewai not installed: agents run without an LLM binding')
            return None
        if model_name not in self._llm_cache:
            # crewai.LLM uses LiteLLM under the hood — prefix 'ollama/' tells it to route to Ollama
            ollama_model = f'ollama/{model_name}' if not model_name.startswith('ollama/') else model_name
            self._llm_cache[model_name] = CrewAILLM(
                model=ollama_model,
                base_url=_OLLAMA_BASE_URL,
            )
        return self._llm_cache[model_name]

    def setup_agents(self):
        """Load agents from data/agents.json, assign tier-appropriate LLMs per agent."""
        # From the modules that define them, not the crewai_web_gui package: this runs while
        # the package __init__ is still importing pages.py (which imports this module), and
        # _get_all_tools is bound onto the package only after pages finishes.
        from zyg_dashboard.crewai_web_gui.pages import _get_all_tools
        from zyg_dashboard.crewai_web_gui.security import _load_canonical_json

        try:
            data = _load_canonical_json('agents.json', 'agent_configurations.json', subkey='agents')
        except Exception as e:
            _backend_debug(f'Failed to load agents: {e}')
            return
        agents_config = data if isinstance(data, dict) else {}
        tool_map = _get_all_tools()
        heavy_count = light_count = mock_count = 0
        for name, config in agents_config.items():
            self.agent_allowed_models[name] = config.get('ai_models', [])
            agent_tools = [tool_map[t] for t in config.get('tools', []) if t in tool_map]

            llm = None
            if OLLAMA_AVAILABLE and self._available_models:
                model_name = _pick_model_for_agent(name, self._available_models)
                llm = self._get_llm(model_name)
            if llm is not None:
                self.agents[name] = Agent(
                    role=config['role'],
                    goal=config['goal'],
                    backstory=config['backstory'],
                    verbose=True,
                    allow_delegation=False,  # Overseer delegates; workers don't
                    llm=llm,
                    tools=agent_tools,
                )
                if 'qwen3.6' in model_name or 'llama3:70b' in model_name:
                    heavy_count += 1
                else:
                    light_count += 1
            else:
                self.agents[name] = type(
                    'MockAgent',
                    (),
                    {
                        'role': config['role'],
                        'goal': config['goal'],
                        'backstory': config['backstory'],
                        'tools': agent_tools,
                    },
                )()
                mock_count += 1
            self.agent_configs[name] = config

        _backend_debug(
            f'Agents: {heavy_count} heavy (qwen3.6:35b-a3b), {light_count} light (gpt-oss:20b), {mock_count} mock'
        )

    def get_agent_tree(self):
        """Return the agent hierarchy as a nested tree"""
        # Build a mapping of agent name to config
        agents = self.agent_configs
        # Find root agents (no supervisor or supervisor not in agents)
        roots = []
        children = {}
        for name, config in agents.items():
            sup = config.get('supervisor')
            if not sup or sup not in agents:
                roots.append(name)
            children.setdefault(sup, []).append(name)

        def build_tree(agent_name):
            node = {
                'name': agent_name,
                'role': agents[agent_name]['role'],
                'children': [build_tree(child) for child in children.get(agent_name, [])],
            }
            return node

        return [build_tree(root) for root in roots]

    def get_agent_network(self):
        """Return the agent hierarchy as a Cytoscape.js-compatible network graph"""
        agents = self.agent_configs
        nodes = []
        edges = []
        for name, config in agents.items():
            # Determine type for coloring
            if name == 'CEO':
                node_type = 'ceo'
            elif 'Overseer' in name or 'Director' in config.get('role', ''):
                node_type = 'department_head'
            elif config.get('tier', 0) == 1:
                node_type = 'tier1'
            elif config.get('tier', 0) == 2:
                node_type = 'tier2'
            elif config.get('tier', 0) == 3:
                node_type = 'tier3'
            else:
                node_type = 'specialist'
            nodes.append({'data': {'id': name, 'label': f'{name}\n({config["role"]})', 'type': node_type}})
            sup = config.get('supervisor')
            if sup and sup in agents:
                edges.append({'data': {'source': sup, 'target': name, 'type': 'supervision'}})
        return {'nodes': nodes, 'edges': edges}


class _ControlPlaneUnavailable(Exception):
    """Raised when control plane is unreachable so caller can fall back to orchestrator."""


# Global controller instance
controller = CrewAIController()
runtime.register(controller=controller)

# Wire real agents + configs into the AgentActivationControllerTool so it can
# spawn actual CrewAI crews when the Overseer calls "activate".
try:
    from crewai import Crew, Process, Task  # deferred: crewai is optional, ImportError lands in the except below
    from zyg_workflows.tools import infrastructure_tools as _infra_tools

    _infra_tools.register_agent_executor(
        agents_dict=controller.agents,
        configs_dict=controller.agent_configs,
        crew_cls=Crew,
        task_cls=Task,
        process_cls=Process,
    )
    _backend_debug(f'Agent executor registry populated: {len(controller.agents)} agents')
except Exception as _reg_err:
    _backend_debug(f'Could not register agent executor: {_reg_err}')
