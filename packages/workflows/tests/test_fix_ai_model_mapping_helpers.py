# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `fix_ai_model_mapping`.

The script was 384 lines in one function: a 300-line dict literal, the module
template it renders and the counting loop, all behind an
`agent_configurations.json` that had to be in the working directory. These are
the three pure steps of `fix_ai_model_mapping_tables`, which is the first time
any of this logic has been checked without that file on disk.
"""

import ast

from zyg_workflows import fix_ai_model_mapping_tables as tables


def test_the_four_every_agent_rows_are_the_agent_list_it_was_given():
    """`table` substitutes the configuration's agent ids into the open rows."""
    agent_names = ['A-Agent', 'B-Agent']

    built = tables.table(agent_names)

    for model in ('Claude 3', 'Llama 3', 'GPT-4', 'LangChain Llamalend'):
        assert built[model] == ['A-Agent', 'B-Agent'], model
    # a fresh list per row, so a caller mutating one row cannot touch another
    built['Claude 3'].append('C-Agent')
    assert built['GPT-4'] == ['A-Agent', 'B-Agent']
    assert agent_names == ['A-Agent', 'B-Agent']


def test_the_hand_maintained_rosters_do_not_depend_on_the_agent_list():
    """Only the four open rows move with the configuration; the rest are fixed."""
    one = tables.table(['Only-Agent'])
    many = tables.table([f'Agent-{n}' for n in range(40)])

    assert one.keys() == many.keys()
    moved = [model for model in one if one[model] != many[model]]
    assert sorted(moved) == ['Claude 3', 'GPT-4', 'LangChain Llamalend', 'Llama 3']
    assert one['Clip'] == ['YouTube-Analytics-Agent']


def _module_assignments(source):
    """The literal value of every top-level `name = <literal>` in *source*."""
    tree = ast.parse(source)
    bound = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                bound[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass  # the tail's `agent_to_models = {}` seed, then its loop
    return bound


def test_the_rendered_module_is_valid_python_with_the_same_table():
    """`render_mapping_module` writes source whose `model_to_agents` round-trips."""
    mapping = {'Alpha': ['One-Agent', 'Two-Agent'], 'Beta': []}

    source = tables.render_mapping_module(mapping)

    assert source.startswith('# AI Model ↔ Agent Mapping for CrewAI Dashboard\n')
    bound = _module_assignments(source)
    assert bound['model_to_agents'] == mapping
    assert len(bound['CPU_MODELS']) == 14
    assert len(bound['GPU_MODELS']) == 19
    # the tail still carries the inversion loop that builds agent_to_models
    assert 'agent_to_models.setdefault(agent, []).append(model)' in source


def test_the_rendered_table_keeps_the_table_order_one_agent_per_line():
    """Row order and the one-agent-per-line layout are what the script emitted."""
    source = tables.render_mapping_module({'Zeta': ['Z-Agent'], 'Alpha': ['A-Agent']})

    body = source.split('model_to_agents = {\n', 1)[1].split('}\n', 1)[0]
    assert body == '    "Zeta": [\n        "Z-Agent",\n    ],\n    "Alpha": [\n        "A-Agent",\n    ],\n'


def test_the_two_family_counts_are_independent_and_ignore_unknown_rows():
    """`count_mapped_models` counts CPU and GPU membership separately."""
    counted = tables.count_mapped_models(
        {
            'Claude 3': ['any'],  # CPU_MODELS
            'Whisper': ['any'],  # CPU_MODELS
            'AnimateDiff': ['any'],  # GPU_MODELS
            'autosave_daemon': ['any'],  # neither list
        }
    )

    assert counted == (2, 1)


def test_the_real_table_counts_what_the_script_reported():
    """The shipped table maps these many of the two families — the printed totals."""
    cpu, gpu = tables.count_mapped_models(tables.table(['Some-Agent']))

    # The capitalised rows ('Realesrgan', 'Animatediff', …) are in neither
    # family list, which is why neither total is the length of its list.
    assert (cpu, gpu) == (9, 10)
    assert cpu < len(tables.CPU_MODELS)
    assert gpu < len(tables.GPU_MODELS)
