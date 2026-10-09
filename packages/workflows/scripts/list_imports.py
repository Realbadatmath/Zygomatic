#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""List the third-party distributions that src/ actually imports, grouped by extra.

Walks every .py file under src/, collects the top-level module names it imports, drops the
standard library and our own packages, then maps module -> distribution name using
importlib.metadata.packages_distributions() and, as a fallback, a name match against the
production freeze file. The grouping (core/gpu/audio/3d/llm/dev) mirrors the extras in
pyproject.toml.

Usage:
    python scripts/list_imports.py [--freeze PATH] [--src PATH]
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO / 'src'
DEFAULT_FREEZE = REPO.parent / '.tools' / 'facts' / 'live_venv_freeze.txt'

# Our own packages and the local top-level modules that live inside src/ — never dependencies.
OWN_PACKAGES = {'zyg_workflows', 'zyg_dashboard', 'zyg_zero', 'zyg_nexus'}

GROUPS: dict[str, set[str]] = {
    'gpu': {
        'torch',
        'torchvision',
        'torchaudio',
        'diffusers',
        'transformers',
        'accelerate',
        'xformers',
        'safetensors',
        'bitsandbytes',
        'peft',
        'timm',
        'sentence-transformers',
        'facenet-pytorch',
        'keybert',
        'insightface',
        'basicsr',
        'realesrgan',
        'gfpgan',
        'facexlib',
        'ultralytics',
        'controlnet-aux',
        'compel',
        'vllm',
        'xgrammar',
        'nvidia-ml-py',
        'pynvml',
        'triton',
        'bpy',
    },
    'audio': {
        'pedalboard',
        'python-stretch',
        'rmvpe-onnx',
        'swift-f0',
        'soundfile',
        'librosa',
        'audioread',
        'pydub',
        'praat-parselmouth',
        'webrtcvad',
        'pyloudnorm',
        'noisereduce',
        'resampy',
        'openai-whisper',
        'faster-whisper',
        'whisperx',
        'TTS',
        'piper-tts',
        'demucs',
        'torchcrepe',
        'mido',
        'music21',
        'pretty-midi',
        'sounddevice',
        'av',
    },
    '3d': {
        'trimesh',
        'open3d',
        'pycolmap',
        'pyrender',
        'pygltflib',
        'rtree',
        'mapbox-earcut',
        'manifold3d',
        'shapely',
        'xatlas',
        'pymeshlab',
        'vedo',
    },
    'llm': {
        'anthropic',
        'openai',
        'ollama',
        'litellm',
        'langchain',
        'langchain-core',
        'google-generativeai',
        'mistralai',
        'groq',
        'tiktoken',
        'instructor',
        'mcp',
    },
    'dev': {
        'pytest',
        'pytest-timeout',
        'pytest-cov',
        'ruff',
        'bandit',
        'reuse',
        'import-linter',
        'pip-audit',
        'pre-commit',
        'mypy',
        'ipython',
        'jupyterlab',
        'notebook',
    },
}

# Module names whose distribution importlib cannot resolve in every venv, or that differ enough
# from the module name that a freeze-file name match would miss them.
MODULE_TO_DIST = {
    'PIL': 'pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'bs4': 'beautifulsoup4',
    'dateutil': 'python-dateutil',
    'dotenv': 'python-dotenv',
    'fitz': 'PyMuPDF',
    'jwt': 'PyJWT',
    'psycopg2': 'psycopg2-binary',
    'serial': 'pyserial',
    'skimage': 'scikit-image',
    'sklearn': 'scikit-learn',
    'OpenSSL': 'pyOpenSSL',
    'zmq': 'pyzmq',
    'git': 'GitPython',
    'docx': 'python-docx',
    'pptx': 'python-pptx',
    'magic': 'python-magic',
    'multipart': 'python-multipart',
    'pkg_resources': 'setuptools',
    'whisper': 'openai-whisper',
    'parselmouth': 'praat-parselmouth',
}

# Distributions that pip cannot install: they come from a vendored build or a host application.
NOT_ON_PYPI = {'bpy'}


def iter_python_files(src: Path):
    for path in sorted(src.rglob('*.py')):
        parts = set(path.parts)
        if parts & {'vendor', 'nomologin_node', '__pycache__'}:
            continue
        yield path


def top_level_imports(src: Path) -> tuple[set[str], list[str]]:
    """Return the set of top-level imported module names and the files that failed to parse."""
    modules: set[str] = set()
    unparsed: list[str] = []
    for path in iter_python_files(src):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'), filename=str(path))
        except SyntaxError:
            unparsed.append(str(path.relative_to(src)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import — local by construction
                    continue
                if node.module:
                    modules.add(node.module.split('.')[0])
    return modules, unparsed


def local_top_level(src: Path) -> set[str]:
    """Top-level names importable from src/ itself (packages and modules), plus our packages."""
    names = set(OWN_PACKAGES)
    for child in src.iterdir():
        if child.is_dir() and (child / '__init__.py').exists():
            names.add(child.name)
        elif child.suffix == '.py':
            names.add(child.stem)
    # Subpackages of our own packages are imported as bare names in a few legacy modules.
    for package in src.iterdir():
        if not package.is_dir():
            continue
        for child in package.iterdir():
            if child.is_dir() and (child / '__init__.py').exists():
                names.add(child.name)
            elif child.suffix == '.py':
                names.add(child.stem)
    return names


def load_freeze(freeze: Path) -> dict[str, str]:
    """Map normalised distribution name -> version from a pip freeze file."""
    pins: dict[str, str] = {}
    if not freeze.exists():
        return pins
    for line in freeze.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '==' not in line:
            continue
        name, _, version = line.partition('==')
        pins[normalise(name)] = version.strip()
    return pins


def normalise(name: str) -> str:
    return name.strip().lower().replace('_', '-').replace('.', '-')


def resolve(module: str, mapping: dict[str, list[str]], pins: dict[str, str]) -> str | None:
    """Map a module name to a distribution name, or None if nothing claims it."""
    if module in MODULE_TO_DIST:
        return MODULE_TO_DIST[module]
    for candidate in (module, module.replace('_', '-')):
        if candidate in mapping:
            return sorted(mapping[candidate])[0]
    for candidate in (normalise(module), normalise(module).replace('-', '')):
        if candidate in pins:
            return candidate
    return None


def group_of(dist: str) -> str:
    key = normalise(dist)
    for group, members in GROUPS.items():
        if key in {normalise(m) for m in members}:
            return group
    return 'core'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--src', type=Path, default=DEFAULT_SRC, help='source tree to walk')
    parser.add_argument('--freeze', type=Path, default=DEFAULT_FREEZE, help='pip freeze file of the live venv')
    args = parser.parse_args()

    modules, unparsed = top_level_imports(args.src)
    local = local_top_level(args.src)
    pins = load_freeze(args.freeze)
    mapping = metadata.packages_distributions()

    third_party = sorted(m for m in modules if m not in local and m not in sys.stdlib_module_names)

    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    unresolved: list[str] = []
    for module in third_party:
        dist = resolve(module, mapping, pins)
        if dist is None:
            unresolved.append(module)
            continue
        grouped[group_of(dist)][dist] = pins.get(normalise(dist), '')

    for group in ('core', 'gpu', 'audio', '3d', 'llm', 'dev'):
        dists = grouped.get(group, {})
        print(f'# {group} ({len(dists)})')
        for dist in sorted(dists, key=normalise):
            version = dists[dist] or '(not in freeze)'
            note = '  # NOT on PyPI — host application / vendored build' if normalise(dist) in NOT_ON_PYPI else ''
            print(f'{dist}  live={version}{note}')
        print()

    if unresolved:
        print(f'# unresolved — no distribution claims these modules ({len(unresolved)})')
        print(f'# optional/soft imports, host plugins or local scripts: {", ".join(unresolved)}')
        print()
    if unparsed:
        print(f'# files that failed to parse ({len(unparsed)}): {", ".join(unparsed)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
