# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The promoted roots in paths.py still default to the literal their module used.

Each ``paths.ZYG_*`` constant below used to be an ``os.environ.get`` inside the one or seven
modules that needed it. Promoting them is only safe if an unconfigured checkout still
resolves to the very same string, so every default is spelled out here independently of
paths.py — changing one of them has to be done twice, on purpose.

The lookup *semantics* are part of the behaviour too (an empty ``$NAME`` is a real value for
some roots and falls back to the default for others), so they are asserted as well.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pytest

from zyg_workflows import paths

HOME = Path.home()
#: The package's own directory: the roots that ship inside the package hang off it.
PKG = Path(os.path.abspath(paths.__file__)).parent
CREWS = HOME / 'Zygomatic Full' / 'agents' / 'crews'

#: constant name -> the string the call sites resolved to before the promotion.
DEFAULTS: dict[str, str] = {
    'ZYG_STORYTELLER_CHARS': str(HOME / 'lora-datasets' / 'storyteller_chars'),
    'ZYG_STORYTELLER_LORAS': str(HOME / 'lora-outputs' / 'storyteller_chars'),
    'ZYG_CREATURE_DATASETS': str(HOME / 'lora-datasets' / 'creatures'),
    'ZYG_CREATURE_OUTPUTS': str(HOME / 'lora-outputs' / 'creatures'),
    'ZYG_CREATURE_LORA_DIR': str(HOME / 'ai-models' / 'creature-loras'),
    'ZYG_ANIMAL_LORA_DIR': str(HOME / 'ai-models' / 'animal-loras'),
    'ZYG_MEDUSA_MODEL_DATASET_ROOT': str(HOME / 'lora-datasets' / 'medusa_models'),
    'ZYG_MEDUSA_MODEL_OUTPUT_ROOT': str(HOME / 'lora-outputs' / 'medusa_models'),
    'ZYG_MEDUSA_RUNTIME_DIR': str(CREWS / 'data' / 'runtime'),
    'ZYG_GNM_REPO': str(HOME / 'ai-models' / 'gnm'),
    'ZYG_ICT_REPO': str(HOME / 'ai-models' / 'ICT-FaceKit'),
    'ZYG_SAM3_HOME': str(HOME / 'models' / 'sam3'),
    'ZYG_SAM3_PYTHON': str(HOME / 'models' / 'vlm_judge' / '.venv' / 'bin' / 'python'),
    'ZYG_SAM2_NODE_DIR': str(HOME / 'ai-models' / 'comfyui' / 'custom_nodes' / 'ComfyUI-segment-anything-2'),
    'ZYG_VLM_HOME': str(HOME / 'models' / 'vlm_judge'),
    'ZYG_MP_MODEL_DIR': str(PKG / 'data' / 'models' / 'mediapipe'),
    'ZYG_VFX_ROOT': str(PKG / 'data' / 'runtime' / 'vfx_library'),
    'ZYG_INDEXTTS_DIR': str(HOME / 'models' / 'tts_indextts2'),
    'ZYG_VOICE_ANALYSIS_DIR': str(HOME / 'models' / 'voice_analysis'),
    'ZYG_ASR_PYTHON': str(HOME / '.venvs' / 'asr' / 'bin' / 'python'),
    'ZYG_SIMPLETUNER_DIR': str(HOME / 'SimpleTuner'),
    'ZYG_SERVER_PYTHON': str(CREWS.parent / '.venv' / 'bin' / 'python'),
    'ZYG_GPU_LOCK': str(HOME / '.zyg_gpu.lock'),
    'ZYG_LTX_COMFY_ROOT': str(HOME / 'ai-models' / 'comfyui-ltx'),
    'ZYG_LTX_COMFY_URL': 'http://127.0.0.1:8189',
    'ZYG_REMIX_BROLL_DIR': str(HOME / 'Zygomatic' / 'GameSim' / 'recordings'),
    'ZYG_REMEDY_KB': str(PKG / 'config' / 'remedy_kb.json'),
    'ZYG_REMEDY_KB_LEARNED': str(PKG / 'data' / 'runtime' / 'remedy_kb_learned.json'),
    'ZYG_REMEDY_KB_STATE': str(PKG / 'data' / 'runtime' / 'remedy_kb_state.json'),
    'ZYG_PLANS_DIR': str(PKG / 'data' / 'architecture' / 'plans'),
    'ZYG_METRICS_RUNTIME_DIR': str(PKG / 'data' / 'runtime'),
    'ZYG_ANSUR_IMPORT_DIR': str(Path(tempfile.gettempdir()) / 'zygomatic' / 'ansur_import'),
}

#: Roots whose call site passed a two-argument ``get``: an empty ``$NAME`` is a real value.
EMPTY_WINS = (
    'ZYG_STORYTELLER_CHARS',
    'ZYG_MEDUSA_RUNTIME_DIR',
    'ZYG_SAM3_HOME',
    'ZYG_VLM_HOME',
    'ZYG_MP_MODEL_DIR',
    'ZYG_GPU_LOCK',
)

#: Roots whose call site was ``get(NAME) or default`` (stripped first for the last one):
#: an empty ``$NAME`` falls back to the default.
EMPTY_FALLS_BACK = (
    'ZYG_SAM2_NODE_DIR',
    'ZYG_ASR_PYTHON',
    'ZYG_SIMPLETUNER_DIR',
    'ZYG_REMEDY_KB',
    'ZYG_PLANS_DIR',
    'ZYG_METRICS_RUNTIME_DIR',
    'ZYG_ANSUR_IMPORT_DIR',
)

#: The environment of an unconfigured checkout: nothing ZYG_*, no BIND_HOST override.
#: $TMPDIR is left alone — tempfile.gettempdir() has already cached its answer above.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith('ZYG_')}
CLEAN_ENV.pop('BIND_HOST', None)
CLEAN_ENV.pop('BLENDER_BIN', None)


def _resolve(overrides: dict[str, str]) -> dict[str, str]:
    """Re-import paths.py under the clean environment plus *overrides*.

    Returns the promoted constants as a dict, because ``importlib.reload`` mutates the one
    module object in place — a reference to it would not survive the restore below.
    """
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(CLEAN_ENV | overrides)
    try:
        importlib.reload(paths)
        return {name: getattr(paths, name) for name in DEFAULTS}
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(paths)


@pytest.fixture(scope='module')
def unconfigured() -> dict[str, str]:
    return _resolve({})


@pytest.mark.parametrize('name', sorted(DEFAULTS))
def test_default_matches_the_literal_the_module_used(unconfigured, name):
    assert unconfigured[name] == DEFAULTS[name]


@pytest.mark.parametrize('name', sorted(DEFAULTS))
def test_every_promoted_root_is_exported(name):
    assert name in paths.__all__


@pytest.mark.parametrize('name', EMPTY_WINS)
def test_empty_value_wins(name):
    assert _resolve({name: ''})[name] == ''


@pytest.mark.parametrize('name', EMPTY_FALLS_BACK)
def test_empty_value_falls_back_to_the_default(name):
    assert _resolve({name: ''})[name] == DEFAULTS[name]


@pytest.mark.parametrize('name', sorted(DEFAULTS))
def test_override_is_used_verbatim(name):
    assert _resolve({name: '/srv/override'})[name] == '/srv/override'
