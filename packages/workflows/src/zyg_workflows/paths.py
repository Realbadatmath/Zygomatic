# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""paths.py — every filesystem root and service URL the workflows use, in one place.

Each constant is read from the environment and falls back to the value the production tree
uses today, so an unconfigured checkout behaves exactly like the legacy installation:

    ZYG_CREWS_ROOT  default  ~/Zygomatic Full/agents/crews   (the legacy production tree)

Nothing here touches the disk at import time except ``BLENDER_BIN``'s PATH lookup; the only
directory this module creates is the scratch directory handed out by :func:`tmp_dir`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def _path(name: str, default: Path) -> Path:
    """Return ``$name`` as a :class:`~pathlib.Path`, or *default* when it is unset or empty."""
    raw = os.environ.get(name, '').strip()
    return Path(raw).expanduser() if raw else default


def _text(name: str, default: str) -> str:
    """Return ``$name`` stripped, or *default* when it is unset or empty."""
    raw = os.environ.get(name, '').strip()
    return raw or default


# --- filesystem roots -------------------------------------------------------------------
ZYG_HOME = _path('ZYG_HOME', Path.home())
#: The legacy production tree. Everything the crews read and write hangs off it.
ZYG_CREWS_ROOT = _path('ZYG_CREWS_ROOT', ZYG_HOME / 'Zygomatic Full' / 'agents' / 'crews')
ZYG_DATA_ROOT = _path('ZYG_DATA_ROOT', ZYG_CREWS_ROOT / 'data')
ZYG_OUTPUT_ROOT = _path('ZYG_OUTPUT_ROOT', ZYG_CREWS_ROOT / 'output')

ZYG_MODELS_ROOT = _path('ZYG_MODELS_ROOT', ZYG_HOME / 'ai-models')
ZYG_COMFY_ROOT = _path('ZYG_COMFY_ROOT', ZYG_MODELS_ROOT / 'comfyui')
ZYG_FLUX_ROOT = _path('ZYG_FLUX_ROOT', ZYG_MODELS_ROOT / 'FLUX')
ZYG_REALESRGAN_ROOT = _path('ZYG_REALESRGAN_ROOT', ZYG_MODELS_ROOT / 'realesrgan')

#: ComfyUI's own directories. Each has its own variable — an installation that keeps the
#: weights or the output on another disk overrides one without moving the rest — and each
#: falls back under ZYG_COMFY_ROOT independently, never through one of its siblings.
ZYG_COMFY_INPUT = _path('ZYG_COMFY_INPUT', ZYG_COMFY_ROOT / 'input')
ZYG_COMFY_OUTPUT = _path('ZYG_COMFY_OUTPUT', ZYG_COMFY_ROOT / 'output')
ZYG_COMFY_MODELS_ROOT = _path('ZYG_COMFY_MODELS_ROOT', ZYG_COMFY_ROOT / 'models')
ZYG_COMFY_LORA_DIR = _path('ZYG_COMFY_LORA_DIR', ZYG_COMFY_ROOT / 'models' / 'loras')

ZYG_LORA_DATASETS = _path('ZYG_LORA_DATASETS', ZYG_HOME / 'lora-datasets')
ZYG_LORA_OUTPUTS = _path('ZYG_LORA_OUTPUTS', ZYG_HOME / 'lora-outputs')
ZYG_MODELS_DIR = _path('ZYG_MODELS_DIR', ZYG_HOME / 'models')

#: The legacy production tree outside this repository. These three roots and ZYG_CREWS_ROOT
#: above are the only places its layout is spelled out; every call site goes through them.
ZYG_LEGACY_ROOT = _path('ZYG_LEGACY_ROOT', ZYG_HOME / 'Zygomatic Full')
ZYG_LEGACY_MODELS = _path('ZYG_LEGACY_MODELS', ZYG_LEGACY_ROOT / 'models')
ZYG_LEGACY_VENV_PY = _path('ZYG_LEGACY_VENV_PY', ZYG_CREWS_ROOT.parent / '.venv' / 'bin' / 'python')

#: Blender executable; the PATH entry wins, the production install is the fallback.
BLENDER_BIN = _path('BLENDER_BIN', Path(shutil.which('blender') or '/usr/local/bin/blender'))

#: Scratch space. Use :func:`tmp_dir` rather than this constant so the directory exists.
ZYG_TMP_DIR = _path('ZYG_TMP_DIR', Path(tempfile.gettempdir()) / 'zygomatic')


def tmp_dir(sub: str = '') -> Path:
    """Return ``ZYG_TMP_DIR/sub``, created with mode ``0o700`` (owner only).

    ``ZYG_TMP_DIR`` itself is tightened too, so a world-readable directory left by an
    earlier run is corrected rather than reused as it is.
    """
    ZYG_TMP_DIR.mkdir(parents=True, exist_ok=True)
    ZYG_TMP_DIR.chmod(0o700)
    target = ZYG_TMP_DIR / sub if sub else ZYG_TMP_DIR
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    return target


# --- service endpoints ------------------------------------------------------------------
#: Loopback by default: no workflow service is meant to be reachable from the network.
BIND_HOST = _text('BIND_HOST', '127.0.0.1')

#: Default port per service, used to build the fallback URLs below.
COMFY_PORT = 8188
#: The second, LTX-only ComfyUI instance runs beside the first one.
LTX_COMFY_PORT = 8189
OLLAMA_PORT = 11434
KANBAN_PORT = 8899
DASHBOARD_PORT = 5000
PUBLIC_PORT = 5001
SESSION_TREE_PORT = 7100
REDIS_PORT = 6379

ZYG_COMFY_URL = _text('ZYG_COMFY_URL', f'http://{BIND_HOST}:{COMFY_PORT}')
ZYG_OLLAMA_URL = _text('ZYG_OLLAMA_URL', f'http://{BIND_HOST}:{OLLAMA_PORT}')
ZYG_KANBAN_URL = _text('ZYG_KANBAN_URL', f'http://{BIND_HOST}:{KANBAN_PORT}')
ZYG_DASHBOARD_URL = _text('ZYG_DASHBOARD_URL', f'http://{BIND_HOST}:{DASHBOARD_PORT}')
ZYG_PUBLIC_URL = _text('ZYG_PUBLIC_URL', f'http://{BIND_HOST}:{PUBLIC_PORT}')
ZYG_SESSION_TREE_URL = _text('ZYG_SESSION_TREE_URL', f'http://{BIND_HOST}:{SESSION_TREE_PORT}')
ZYG_REDIS_URL = _text('ZYG_REDIS_URL', f'redis://{BIND_HOST}:{REDIS_PORT}/0')

#: The LTX-only ComfyUI instance. Trailing slashes are stripped here, as the one call site
#: that built this URL has always done, so the constant is safe to concatenate a route onto.
ZYG_LTX_COMFY_URL = os.environ.get('ZYG_LTX_COMFY_URL', f'http://{BIND_HOST}:{LTX_COMFY_PORT}').rstrip('/')


# --- per-subsystem roots ----------------------------------------------------------------
# Roots, repositories, lock files and interpreters that each used to be read from the
# environment by the one or seven modules that needed them. One definition each, here.
#
# They are `str`, not `Path`, because every call site joins or realpath()s them as text, and
# each keeps the *exact* lookup its module used, because the spelling is the behaviour:
# `get(NAME, default)` lets an empty $NAME win, `get(NAME) or default` falls back on it, and
# `get(NAME, '').strip() or default` falls back on whitespace too. None of them expands `~`.

#: This package's own directory, and the data tree inside it — the fallback for the roots
#: that ship inside the package. ``_PKG_DIR`` stays as an alias for the uses just below.
PKG_DIR = Path(os.path.abspath(__file__)).parent
DATA_DIR = PKG_DIR / 'data'
_PKG_DIR = PKG_DIR

#: Storyteller characters: the dataset tree, and the LoRAs trained from it.
ZYG_STORYTELLER_CHARS = os.environ.get('ZYG_STORYTELLER_CHARS', str(ZYG_LORA_DATASETS / 'storyteller_chars'))
ZYG_STORYTELLER_LORAS = os.environ.get('ZYG_STORYTELLER_LORAS', str(ZYG_LORA_OUTPUTS / 'storyteller_chars'))

#: Creatures, animals and Medusa models: dataset trees, outputs and trained LoRAs.
ZYG_CREATURE_DATASETS = os.environ.get('ZYG_CREATURE_DATASETS', str(ZYG_LORA_DATASETS / 'creatures'))
ZYG_CREATURE_OUTPUTS = os.environ.get('ZYG_CREATURE_OUTPUTS', str(ZYG_LORA_OUTPUTS / 'creatures'))
ZYG_CREATURE_LORA_DIR = os.environ.get('ZYG_CREATURE_LORA_DIR', str(ZYG_MODELS_ROOT / 'creature-loras'))
ZYG_ANIMAL_LORA_DIR = os.environ.get('ZYG_ANIMAL_LORA_DIR', str(ZYG_MODELS_ROOT / 'animal-loras'))
ZYG_MEDUSA_MODEL_DATASET_ROOT = os.environ.get(
    'ZYG_MEDUSA_MODEL_DATASET_ROOT', str(ZYG_LORA_DATASETS / 'medusa_models')
)
ZYG_MEDUSA_MODEL_OUTPUT_ROOT = os.environ.get('ZYG_MEDUSA_MODEL_OUTPUT_ROOT', str(ZYG_LORA_OUTPUTS / 'medusa_models'))
#: Where the per-character ``medusa_<id>_state.json`` files live.
ZYG_MEDUSA_RUNTIME_DIR = os.environ.get('ZYG_MEDUSA_RUNTIME_DIR', str(ZYG_DATA_ROOT / 'runtime'))

#: Geometry and vision checkouts. The two repositories keep the ``rstrip`` their call sites
#: applied, so a trailing slash in the override cannot double up in a joined path.
ZYG_GNM_REPO = os.environ.get('ZYG_GNM_REPO', str(ZYG_MODELS_ROOT / 'gnm')).rstrip('/')
ZYG_ICT_REPO = os.environ.get('ZYG_ICT_REPO', str(ZYG_MODELS_ROOT / 'ICT-FaceKit')).rstrip('/')
ZYG_SAM3_HOME = os.environ.get('ZYG_SAM3_HOME', str(ZYG_MODELS_DIR / 'sam3'))
ZYG_SAM3_PYTHON = os.environ.get('ZYG_SAM3_PYTHON', str(ZYG_MODELS_DIR / 'vlm_judge' / '.venv' / 'bin' / 'python'))
ZYG_SAM2_NODE_DIR = os.environ.get('ZYG_SAM2_NODE_DIR') or str(
    ZYG_COMFY_ROOT / 'custom_nodes' / 'ComfyUI-segment-anything-2'
)
ZYG_VLM_HOME = os.environ.get('ZYG_VLM_HOME', str(ZYG_MODELS_DIR / 'vlm_judge'))
#: MediaPipe task files and the VFX library both ship inside the package.
ZYG_MP_MODEL_DIR = os.environ.get('ZYG_MP_MODEL_DIR', str(_PKG_DIR / 'data' / 'models' / 'mediapipe'))
ZYG_VFX_ROOT = os.environ.get('ZYG_VFX_ROOT', str(_PKG_DIR / 'data' / 'runtime' / 'vfx_library'))

#: Speech and voice: the IndexTTS-2 checkout, the voice-analysis models, and the
#: interpreter the out-of-process ASR runs on. That venv lives outside this
#: repository; ZYG_ASR_PYTHON names it.
ZYG_INDEXTTS_DIR = os.environ.get('ZYG_INDEXTTS_DIR', str(ZYG_MODELS_DIR / 'tts_indextts2'))
ZYG_VOICE_ANALYSIS_DIR = os.environ.get('ZYG_VOICE_ANALYSIS_DIR', str(ZYG_MODELS_DIR / 'voice_analysis'))
ZYG_ASR_PYTHON = os.environ.get('ZYG_ASR_PYTHON', '') or str(ZYG_HOME / '.venvs' / 'asr' / 'bin' / 'python')

#: Training and out-of-process interpreters, plus the lock that serialises the GPU.
ZYG_SIMPLETUNER_DIR = os.environ.get('ZYG_SIMPLETUNER_DIR', '') or str(ZYG_HOME / 'SimpleTuner')
ZYG_SERVER_PYTHON = os.environ.get('ZYG_SERVER_PYTHON', str(ZYG_CREWS_ROOT.parent / '.venv' / 'bin' / 'python'))
ZYG_GPU_LOCK = os.environ.get('ZYG_GPU_LOCK', str(ZYG_HOME / '.zyg_gpu.lock'))

#: The LTX ComfyUI installation (its URL is with the other endpoints above).
ZYG_LTX_COMFY_ROOT = os.environ.get('ZYG_LTX_COMFY_ROOT', str(ZYG_MODELS_ROOT / 'comfyui-ltx'))

#: Gameplay recordings the remix pipeline cuts its b-roll from.
ZYG_REMIX_BROLL_DIR = os.environ.get('ZYG_REMIX_BROLL_DIR', str(ZYG_HOME / 'Zygomatic' / 'GameSim' / 'recordings'))

#: State and reference data that ship inside the package: the remedy knowledge base (the
#: authored file, plus the two the pipeline learns into), the floor plans, and the runtime
#: directory the metrics writers share.
ZYG_REMEDY_KB = os.environ.get('ZYG_REMEDY_KB') or str(_PKG_DIR / 'config' / 'remedy_kb.json')
ZYG_REMEDY_KB_LEARNED = os.environ.get('ZYG_REMEDY_KB_LEARNED') or str(
    _PKG_DIR / 'data' / 'runtime' / 'remedy_kb_learned.json'
)
ZYG_REMEDY_KB_STATE = os.environ.get('ZYG_REMEDY_KB_STATE') or str(
    _PKG_DIR / 'data' / 'runtime' / 'remedy_kb_state.json'
)
ZYG_PLANS_DIR = os.environ.get('ZYG_PLANS_DIR') or str(_PKG_DIR / 'data' / 'architecture' / 'plans')
ZYG_METRICS_RUNTIME_DIR = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or str(_PKG_DIR / 'data' / 'runtime')

#: Scratch directory the ANSUR reference import stages into.
ZYG_ANSUR_IMPORT_DIR = os.environ.get('ZYG_ANSUR_IMPORT_DIR', '').strip() or str(ZYG_TMP_DIR / 'ansur_import')


#: The prefixes still hardcoded across the package — home-relative paths first, then host:port
#: pairs — mapped to the constant each is to be replaced by, with the number of call sites at
#: the time of writing. Rewriting those call sites is out of scope here; this is the map for it.
LEGACY_PREFIXES: dict[str, tuple[str, int]] = {
    '~/Zygomatic Full/agents': ('ZYG_CREWS_ROOT', 147),
    '~/ai-models/comfyui': ('ZYG_COMFY_ROOT', 57),
    '~/lora-datasets/storyteller_chars': ('ZYG_LORA_DATASETS', 51),
    '~/ai-models/FLUX': ('ZYG_FLUX_ROOT', 15),
    '~/lora-outputs/storyteller_chars': ('ZYG_LORA_OUTPUTS', 11),
    '~/lora-datasets/creatures': ('ZYG_LORA_DATASETS', 10),
    f'localhost:{OLLAMA_PORT}': ('ZYG_OLLAMA_URL', 33),
    f'127.0.0.1:{KANBAN_PORT}': ('ZYG_KANBAN_URL', 51),
    f'127.0.0.1:{COMFY_PORT}': ('ZYG_COMFY_URL', 18),
    f'127.0.0.1:{OLLAMA_PORT}': ('ZYG_OLLAMA_URL', 14),
}

__all__ = [
    'BIND_HOST',
    'BLENDER_BIN',
    'DATA_DIR',
    'LEGACY_PREFIXES',
    'PKG_DIR',
    'ZYG_ANIMAL_LORA_DIR',
    'ZYG_ANSUR_IMPORT_DIR',
    'ZYG_ASR_PYTHON',
    'ZYG_COMFY_INPUT',
    'ZYG_COMFY_LORA_DIR',
    'ZYG_COMFY_MODELS_ROOT',
    'ZYG_COMFY_OUTPUT',
    'ZYG_COMFY_ROOT',
    'ZYG_COMFY_URL',
    'ZYG_CREATURE_DATASETS',
    'ZYG_CREATURE_LORA_DIR',
    'ZYG_CREATURE_OUTPUTS',
    'ZYG_CREWS_ROOT',
    'ZYG_DASHBOARD_URL',
    'ZYG_DATA_ROOT',
    'ZYG_FLUX_ROOT',
    'ZYG_GNM_REPO',
    'ZYG_GPU_LOCK',
    'ZYG_HOME',
    'ZYG_ICT_REPO',
    'ZYG_INDEXTTS_DIR',
    'ZYG_KANBAN_URL',
    'ZYG_LEGACY_MODELS',
    'ZYG_LEGACY_ROOT',
    'ZYG_LEGACY_VENV_PY',
    'ZYG_LORA_DATASETS',
    'ZYG_LORA_OUTPUTS',
    'ZYG_LTX_COMFY_ROOT',
    'ZYG_LTX_COMFY_URL',
    'ZYG_MEDUSA_MODEL_DATASET_ROOT',
    'ZYG_MEDUSA_MODEL_OUTPUT_ROOT',
    'ZYG_MEDUSA_RUNTIME_DIR',
    'ZYG_METRICS_RUNTIME_DIR',
    'ZYG_MODELS_DIR',
    'ZYG_MODELS_ROOT',
    'ZYG_MP_MODEL_DIR',
    'ZYG_OLLAMA_URL',
    'ZYG_OUTPUT_ROOT',
    'ZYG_PLANS_DIR',
    'ZYG_PUBLIC_URL',
    'ZYG_REALESRGAN_ROOT',
    'ZYG_REDIS_URL',
    'ZYG_REMEDY_KB',
    'ZYG_REMEDY_KB_LEARNED',
    'ZYG_REMEDY_KB_STATE',
    'ZYG_REMIX_BROLL_DIR',
    'ZYG_SAM2_NODE_DIR',
    'ZYG_SAM3_HOME',
    'ZYG_SAM3_PYTHON',
    'ZYG_SERVER_PYTHON',
    'ZYG_SESSION_TREE_URL',
    'ZYG_SIMPLETUNER_DIR',
    'ZYG_STORYTELLER_CHARS',
    'ZYG_STORYTELLER_LORAS',
    'ZYG_TMP_DIR',
    'ZYG_VFX_ROOT',
    'ZYG_VLM_HOME',
    'ZYG_VOICE_ANALYSIS_DIR',
    'tmp_dir',
]
