# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  # carries expansion_hub.py's original top import block verbatim; the siblings re-import from it

import ast
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import warnings
import logging as _zyg_logging

from zyg_dashboard import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.expansion_hub')

HERE = str(paths.PKG_DIR)  # the package the collector ships in
ROOT = os.path.dirname(os.path.dirname(HERE))  # the tree root above it
HOME = os.path.expanduser('~')
CREWS_DATA = str(paths.DATA_DIR)
CACHE_PATH = os.path.join(CREWS_DATA, 'runtime', 'expansion_cache.json')

# Training material generation is conditioned on. Not produced by the program: the
# operator curated it, and it is read at train time, so it is structural input.
TRAINING_ROOTS = [
    {
        'id': 'lora_datasets',
        'label': 'LoRA datasets',
        'root': os.path.join(HOME, 'lora-datasets'),
        'note': 'character / creature / style datasets fed to the LoRA trainers (musubi, kohya)',
    },
    {
        'id': 'voice_seeds',
        'label': 'TTS voice seeds',
        'root': os.path.join(CREWS_DATA, 'assets', 'voice_seeds'),
        'note': 'reference clips the voice cloners are conditioned on',
    },
]
# Files that live inside a pruned tree but are structural (prompts), listed by hand.
EXTRA_FILES = [
    os.path.join(CREWS_DATA, 'runtime', 'prompt_registry.json'),
]

# ── classification tables ────────────────────────────────────────────────────

CODE_EXT = {
    'mako',
    'py',
    'js',
    'mjs',
    'cjs',
    'ts',
    'tsx',
    'jsx',
    'vue',
    'html',
    'htm',
    'jinja',
    'jinja2',
    'j2',
    'css',
    'scss',
    'less',
    'sh',
    'bash',
    'zsh',
    'bat',
    'cmd',
    'ps1',
    'sql',
    'nft',
    'lua',
    'glsl',
    'wgsl',
    'c',
    'cc',
    'cpp',
    'h',
    'hpp',
    'rs',
    'go',
    'java',
    'kt',
    'rb',
    'php',
    'pl',
    'awk',
    'osl',
}
CONFIG_EXT = {
    'modelfile',
    'example',
    'docker',
    'json',
    'yaml',
    'yml',
    'toml',
    'ini',
    'cfg',
    'conf',
    'env',
    'service',
    'timer',
    'socket',
    'properties',
    'xml',
    'plist',
    'editorconfig',
    'flake8',
    'code-workspace',
    'cube',
}
DOCS_EXT = {'md', 'markdown', 'rst', 'txt', 'adoc', 'odt', 'pdf', 'docx', 'rtf'}
TABLE_EXT = {'csv', 'tsv'}
# Media / fonts count as structural only inside GUI asset folders (icons, themes, LUT
# tables, pose references); anywhere else they are generated or collected content.
ASSET_EXT = {
    'png',
    'jpg',
    'jpeg',
    'gif',
    'webp',
    'svg',
    'ico',
    'bmp',
    'ttf',
    'otf',
    'woff',
    'woff2',
    'cube',
    'mp4',
    'webm',
}
ASSET_DIRS = {
    'static',
    'assets',
    'icons',
    'img',
    'images',
    'fonts',
    'kanban_assets',
    'layouts and themes',
    'themes',
    'diagrams',
    'gradients',
    'cpu_gradients',
    'luts',
    'contact_sheet_poses',
    'avatars',
    'security_diagrams',
    'library',
}
# Binary-ish text we count but never read for lines.
NOLINE_EXT = {'odt', 'pdf', 'docx', 'rtf'}

SKIP_EXT = {
    'media': {
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp',
        'bmp',
        'tif',
        'tiff',
        'exr',
        'hdr',
        'svg',
        'ico',
        'psd',
        'mp4',
        'mov',
        'webm',
        'mkv',
        'avi',
        'wav',
        'mp3',
        'flac',
        'ogg',
        'm4a',
        'aac',
        'opus',
        'mid',
        'midi',
        'sf2',
        'sfz',
        'ttf',
        'otf',
        'woff',
        'woff2',
    },
    'weights': {
        'safetensors',
        'ckpt',
        'pt',
        'pth',
        'bin',
        'onnx',
        'pb',
        'nemo',
        'npy',
        'npz',
        'pkl',
        'pickle',
        'h5',
        'tflite',
        'gguf',
        'msgpack',
        'pte',
    },
    '3d': {
        'glb',
        'gltf',
        'obj',
        'mtl',
        'fbx',
        'stl',
        'dae',
        'blend',
        'blend1',
        'ifc',
        'dxf',
        'ply',
        'usd',
        'usdz',
        'usda',
        'usdc',
        'abc',
        'vdb',
        'bvh',
        'mdd',
    },
    'archives': {'zip', '7z', 'tar', 'gz', 'tgz', 'rar', 'bz2', 'xz', 'zst'},
    'runtime stores / logs': {
        'db',
        'sqlite',
        'sqlite3',
        'index',
        'faiss',
        'jsonl',
        'log',
        'lock',
        'pid',
        'out',
        'metadata',
        'url',
        'ariax',
        'tmp',
        'cache',
    },
    'compiled': {'pyc', 'pyo', 'so', 'dll', 'dylib', 'class', 'o', 'a', 'map', 'br'},
    'user documents': {'eml', 'msg', 'xlsx', 'xls', 'ods', 'doc', 'amr', 'jfif', 'eps', 'srt', 'vtt'},
}
_SKIP_BY_EXT = {e: r for r, s in SKIP_EXT.items() for e in s}

HARD_PRUNE = {
    '.git',
    '__pycache__',
    'node_modules',
    'venv',
    'site-packages',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    '.cache',
    'dist',
    '.tox',
    '.eggs',
    '.ipynb_checkpoints',
}
OUTPUT_PRUNE = {
    'output',
    'outputs',
    'logs',
    'console logs',
    'legacy_json_archive',
    'tmp',
    'temp',
    'cache',
    'uploads',
    'downloads',
    'storage',
    'renders',
    'exports',
    'results',
    'reports',
}
# App content: what the operator put INTO an app (case files, mail, transcripts, schematics).
CONTENT_PRUNE = {
    'projects',
    'outbox',
    'inbox',
    'emails',
    'mail',
    'sessions',
    'chats',
    'documents',
    'attachments',
    'schematics',
    'transcripts',
    'recordings',
}
DATA_PRUNE = {'data', 'weights', 'models', 'checkpoints', 'datasets', 'runtime', 'media', 'library'}
# Inside the crews data root only these hold structural material; the rest is produced or
# collected (≈320 GB, 340 k files measured 2026-10-04).
CREWS_DATA_KEEP = {'stack_lineage': None, 'char2d': {'briefs'}}

# Roots a unit may point at that are NOT the program: installed engines and infra.
THIRD_PARTY_ROOTS = ('ai-models', 'pg16', '.local', '.cache', '.config', '.venv', 'venv') + tuple(
    r for r in os.environ.get('ZYG_THIRD_PARTY_ROOTS', '').split(':') if r
)

PROMPT_NAME = re.compile(r'prompt|persona|instruction|sys_msg|system_msg|question|checklist', re.I)
_PROMPT_DIRS = {'prompts', 'personas', 'briefs', 'bibles', '_comfy_workflows'}

ROUTE_RE = re.compile(r'^\s*@\w+\.(?:route|get|post|put|delete|patch)\(', re.M)
DEF_RE = re.compile(r'^\s*(?:async\s+)?def\s+\w+', re.M)
CLASS_RE = re.compile(r'^\s*class\s+\w+', re.M)
MAIN_RE = re.compile(r"__name__\s*==\s*['\"]__main__['\"]")
JS_FN_RE = re.compile(r'\bfunction\b|=>')

SCAN_TTL_S = 90
_LAST = {'t': 0.0, 'payload': None}
