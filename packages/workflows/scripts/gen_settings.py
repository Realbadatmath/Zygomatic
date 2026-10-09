#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gen_settings.py — build the ZYG_* settings registry from the source that reads it.

    python3 scripts/gen_settings.py            # (re)write the settings/flags_*.py data modules,
                                               # .env.example and docs/configuration.md
    python3 scripts/gen_settings.py --check    # exit 1 (and print a diff summary) if any of them is stale

The registry used to be a single ``src/zyg_workflows/settings.py``; it outgrew the 800-line
module ceiling and is now the ``settings`` package. Only its ``flags_*.py`` data modules are
generated — see FLAG_MODULES. core.py, registry.py and __init__.py are hand-written.

The scan walks ``src/zyg_workflows`` with the ast module and collects every
``os.environ.get('ZYG_…')``, ``os.getenv('ZYG_…')``, ``os.environ['ZYG_…']`` and bare
``environ.get('ZYG_…')`` with a constant name, together with the literal default when the
call gives one and the files that read it.

Generated text is piped through ``ruff format`` so what is written is already formatted and
``--check`` stays stable under the repository's format gate.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import warnings
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src' / 'zyg_workflows'
SETTINGS_PKG = SRC / 'settings'
ENV_EXAMPLE = ROOT / '.env.example'
DOC = ROOT / 'docs' / 'configuration.md'

#: The data modules of ``src/zyg_workflows/settings`` that this script owns: module stem, the
#: dict it binds, and the first flag name (inclusive) that belongs to it. ``settings.py`` grew
#: past the 800-line module ceiling and became a package, so the 799 entries are written as
#: four alphabetical chunks of ~430 lines instead of one 1,700-line literal. Each chunk keeps
#: the keys it already held, so a rescan that only moves a ``files=`` tuple touches nothing
#: else. The package's hand-written parts — core.py (Flag, _TRUE), registry.py (the assembled
#: FLAGS, get, check) and __init__.py (the re-exports) — carry no scanned data and are NOT
#: generated. Add a chunk here when one passes ~600 lines.
FLAG_MODULES: tuple[tuple[str, str, str], ...] = (
    ('flags_abort_contact', '_FLAGS_1', 'ZYG_ABORT_ON_PREVIEW'),
    ('flags_contact_kids', '_FLAGS_2', 'ZYG_CONTACT_SHEET_IDQC_REQUIRED'),
    ('flags_kids_remix', '_FLAGS_3', 'ZYG_KIDSMUSIC_LLM_BACKEND'),
    ('flags_remix_ytdlp', '_FLAGS_4', 'ZYG_REMIX_LLM_MODEL'),
)

DOC_BEGIN = '<!-- BEGIN GENERATED SETTINGS (scripts/gen_settings.py) -->'
DOC_END = '<!-- END GENERATED SETTINGS -->'

#: The roots and endpoints declared in ``src/zyg_workflows/paths.py``: name, default as the
#: module writes it, and what it points at. Kept here so .env.example and the documentation
#: list them next to the scanned flags.
PATH_VARS: tuple[tuple[str, str, str], ...] = (
    ('ZYG_HOME', '~', 'home directory every other root hangs off'),
    (
        'ZYG_CREWS_ROOT',
        '~/Zygomatic Full/agents/crews',
        'the legacy production tree — the default keeps the old installation working untouched',
    ),
    ('ZYG_DATA_ROOT', '$ZYG_CREWS_ROOT/data', 'crew databases, briefs, state'),
    ('ZYG_OUTPUT_ROOT', '$ZYG_CREWS_ROOT/output', 'renders and pipeline artefacts'),
    ('ZYG_MODELS_ROOT', '~/ai-models', 'checkpoints, LoRAs, upscalers'),
    ('ZYG_COMFY_ROOT', '$ZYG_MODELS_ROOT/comfyui', 'ComfyUI installation'),
    ('ZYG_COMFY_INPUT', '$ZYG_COMFY_ROOT/input', 'images staged for ComfyUI'),
    ('ZYG_COMFY_OUTPUT', '$ZYG_COMFY_ROOT/output', 'what ComfyUI writes'),
    ('ZYG_COMFY_MODELS_ROOT', '$ZYG_COMFY_ROOT/models', 'ComfyUI checkpoints'),
    ('ZYG_COMFY_LORA_DIR', '$ZYG_COMFY_ROOT/models/loras', 'LoRAs ComfyUI loads'),
    ('ZYG_FLUX_ROOT', '$ZYG_MODELS_ROOT/FLUX', 'FLUX weights'),
    ('ZYG_REALESRGAN_ROOT', '$ZYG_MODELS_ROOT/realesrgan', 'Real-ESRGAN weights'),
    ('ZYG_LORA_DATASETS', '~/lora-datasets', 'LoRA training sets'),
    ('ZYG_LORA_OUTPUTS', '~/lora-outputs', 'trained LoRA output'),
    ('ZYG_MODELS_DIR', '~/models', 'misc. local models'),
    ('BLENDER_BIN', "which('blender') or /usr/local/bin/blender", 'Blender executable'),
    ('ZYG_TMP_DIR', '$TMPDIR/zygomatic', 'scratch space; tmp_dir() creates it 0o700'),
    ('BIND_HOST', '127.0.0.1', 'interface the services bind to — loopback by design'),
    ('ZYG_COMFY_URL', 'http://127.0.0.1:8188', 'ComfyUI API'),
    ('ZYG_OLLAMA_URL', 'http://127.0.0.1:11434', 'Ollama API'),
    ('ZYG_KANBAN_URL', 'http://127.0.0.1:8899', 'kanban board'),
    ('ZYG_DASHBOARD_URL', 'http://127.0.0.1:5000', 'dashboard GUI'),
    ('ZYG_PUBLIC_URL', 'http://127.0.0.1:5001', 'public site'),
    ('ZYG_SESSION_TREE_URL', 'http://127.0.0.1:7100', 'session tree board'),
    ('ZYG_REDIS_URL', 'redis://127.0.0.1:6379/0', 'Redis instance'),
    # Per-subsystem roots, promoted out of the modules that each used to read them. They are
    # also in the flag table below, because paths.py reads them with a plain environ.get and
    # the scan sees that; this is where their default is written down.
    # `<package>` is src/zyg_workflows itself: those roots ship inside the distribution.
    ('ZYG_STORYTELLER_CHARS', '$ZYG_LORA_DATASETS/storyteller_chars', 'storyteller character datasets'),
    ('ZYG_STORYTELLER_LORAS', '$ZYG_LORA_OUTPUTS/storyteller_chars', 'LoRAs trained from them'),
    ('ZYG_CREATURE_DATASETS', '$ZYG_LORA_DATASETS/creatures', 'creature datasets'),
    ('ZYG_CREATURE_OUTPUTS', '$ZYG_LORA_OUTPUTS/creatures', 'creature LoRA output'),
    ('ZYG_CREATURE_LORA_DIR', '$ZYG_MODELS_ROOT/creature-loras', 'creature LoRAs the services load'),
    ('ZYG_ANIMAL_LORA_DIR', '$ZYG_MODELS_ROOT/animal-loras', 'animal LoRAs the services load'),
    ('ZYG_MEDUSA_MODEL_DATASET_ROOT', '$ZYG_LORA_DATASETS/medusa_models', 'Medusa model datasets'),
    ('ZYG_MEDUSA_MODEL_OUTPUT_ROOT', '$ZYG_LORA_OUTPUTS/medusa_models', 'Medusa model LoRA output'),
    ('ZYG_MEDUSA_RUNTIME_DIR', '$ZYG_DATA_ROOT/runtime', 'per-character `medusa_<id>_state.json`'),
    ('ZYG_GNM_REPO', '$ZYG_MODELS_ROOT/gnm', 'GNM head-geometry checkout'),
    ('ZYG_ICT_REPO', '$ZYG_MODELS_ROOT/ICT-FaceKit', 'ICT-FaceKit checkout'),
    ('ZYG_SAM3_HOME', '$ZYG_MODELS_DIR/sam3', 'SAM 3 checkout'),
    ('ZYG_SAM3_PYTHON', '$ZYG_MODELS_DIR/vlm_judge/.venv/bin/python', 'interpreter the SAM 3 worker runs on'),
    ('ZYG_SAM2_NODE_DIR', '$ZYG_COMFY_ROOT/custom_nodes/ComfyUI-segment-anything-2', 'SAM 2 ComfyUI node'),
    ('ZYG_VLM_HOME', '$ZYG_MODELS_DIR/vlm_judge', 'VLM judge installation'),
    ('ZYG_MP_MODEL_DIR', '<package>/data/models/mediapipe', 'MediaPipe task files, shipped with the package'),
    ('ZYG_VFX_ROOT', '<package>/data/runtime/vfx_library', 'VFX library the probes read and write'),
    ('ZYG_INDEXTTS_DIR', '$ZYG_MODELS_DIR/tts_indextts2', 'IndexTTS-2 checkout'),
    ('ZYG_VOICE_ANALYSIS_DIR', '$ZYG_MODELS_DIR/voice_analysis', 'voice-analysis models'),
    ('ZYG_ASR_PYTHON', '~/.venvs/asr/bin/python', 'interpreter the out-of-process ASR runs on'),
    ('ZYG_SIMPLETUNER_DIR', '~/SimpleTuner', 'SimpleTuner checkout the LoRA trainer drives'),
    ('ZYG_SERVER_PYTHON', '$ZYG_CREWS_ROOT/../.venv/bin/python', 'interpreter the head-fit worker runs on'),
    ('ZYG_GPU_LOCK', '~/.zyg_gpu.lock', 'lock file that serialises the GPU'),
    ('ZYG_LTX_COMFY_ROOT', '$ZYG_MODELS_ROOT/comfyui-ltx', 'the LTX-only ComfyUI installation'),
    ('ZYG_LTX_COMFY_URL', 'http://127.0.0.1:8189', 'its API'),
    ('ZYG_REMIX_BROLL_DIR', '~/Zygomatic/GameSim/recordings', 'self-recorded b-roll the remix pipeline cuts from'),
    ('ZYG_REMEDY_KB', '<package>/config/remedy_kb.json', 'authored remedy knowledge base'),
    ('ZYG_REMEDY_KB_LEARNED', '<package>/data/runtime/remedy_kb_learned.json', 'what the pipeline learns into it'),
    ('ZYG_REMEDY_KB_STATE', '<package>/data/runtime/remedy_kb_state.json', 'its bookkeeping'),
    ('ZYG_PLANS_DIR', '<package>/data/architecture/plans', 'floor-plan packs'),
    ('ZYG_METRICS_RUNTIME_DIR', '<package>/data/runtime', 'runtime directory the metrics writers share'),
    ('ZYG_ANSUR_IMPORT_DIR', '$ZYG_TMP_DIR/ansur_import', 'scratch for the ANSUR reference import'),
)

Scan = dict[str, tuple[object, list[str]]]


def _is_environ(node: ast.AST) -> bool:
    """True for ``os.environ`` and for a bare ``environ`` name."""
    if isinstance(node, ast.Attribute):
        return node.attr == 'environ' and isinstance(node.value, ast.Name) and node.value.id == 'os'
    return isinstance(node, ast.Name) and node.id == 'environ'


def _env_read(node: ast.AST) -> tuple[str, ast.AST | None] | None:
    """Return ``(name, default_node)`` when *node* reads a constant-named variable."""
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value, None
        return None
    if not (isinstance(node, ast.Call) and node.args):
        return None
    func = node.func
    reads_env = (
        (isinstance(func, ast.Attribute) and func.attr == 'get' and _is_environ(func.value))
        or (
            isinstance(func, ast.Attribute)
            and func.attr == 'getenv'
            and isinstance(func.value, ast.Name)
            and func.value.id == 'os'
        )
        or (isinstance(func, ast.Name) and func.id == 'getenv')
    )
    if not reads_env:
        return None
    name = node.args[0]
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        return None
    return name.value, node.args[1] if len(node.args) > 1 else None


#: A default that starts with somebody's home directory is stored home-relative, so the
#: registry carries no personal path; settings.get() expands the '~' back.
_HOME_PREFIX = re.compile(r'^/(?:home|Users)/[^/]+/')


def _literal(node: ast.AST | None) -> object:
    """The default as a Python scalar, or None when it is absent or not a literal."""
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError):
        return None
    if isinstance(value, str):
        return _HOME_PREFIX.sub('~/', value)
    return value if isinstance(value, (int, float, bool)) else None


def scan(src: Path = SRC) -> Scan:
    """Walk *src* and return ``{flag: (default, [files])}`` for every ZYG_* read."""
    found: Scan = {}
    # Parsing other modules' string literals re-raises their SyntaxWarnings; not our business here.
    warnings.simplefilter('ignore', SyntaxWarning)
    for path in sorted(src.rglob('*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'), filename=str(path))
        except SyntaxError as exc:
            print(f'skipped (does not parse): {path}: {exc}', file=sys.stderr)
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            read = _env_read(node)
            if read is None or not read[0].startswith('ZYG_'):
                continue
            name, default_node = read
            default, files = found.setdefault(name, (None, []))
            if default is None:
                default = _literal(default_node)
            if rel not in files:
                files.append(rel)
            found[name] = (default, files)
    return found


# --- rendering ---------------------------------------------------------------------------


def _ruff_format(source: str, filename: Path) -> str:
    """Pipe *source* through ``ruff format`` using the repository's configuration."""
    ruff = Path(sys.prefix) / 'bin' / 'ruff'
    if not ruff.exists():
        print('ruff not found next to this interpreter; writing unformatted output', file=sys.stderr)
        return source
    proc = subprocess.run(
        [str(ruff), 'format', '--stdin-filename', str(filename), '-'],
        input=source,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def _is_tmp_path(default: object) -> bool:
    """True for a default that is an absolute path under the temp directory."""
    parts = PurePosixPath(default).parts if isinstance(default, str) else ()
    return parts[:2] == ('/', 'tmp')


def render_hoisted(flags: Scan) -> str:
    """Module constants for temp-path defaults, so each carries its own suppression.

    A ``# nosec`` inside the ``FLAGS`` literal would be attributed by bandit to the whole
    multi-line statement and warn once per flag, so those few values get their own statement.
    """
    hoisted = [(name, default) for name, (default, _files) in sorted(flags.items()) if _is_tmp_path(default)]
    if not hoisted:
        return ''
    lines = [
        '# Defaults that point into the temp directory. They are recorded here, not used: the',
        '# registry opens nothing. Own statement each, so the suppression covers one line.',
    ]
    lines += [f'{_hoisted_name(name)} = {default!r}  # nosec B108  # noqa: S108' for name, default in hoisted]
    return '\n'.join(lines) + '\n\n'


def _hoisted_name(flag: str) -> str:
    return f'_DEFAULT_{flag}'


def _entry(name: str, default: object, files: list[str]) -> str:
    rendered = _hoisted_name(name) if _is_tmp_path(default) else repr(default)
    return f'    {name!r}: Flag({name!r}, {rendered}, {tuple(files)!r}),\n'


def _chunk_of(name: str) -> int:
    """Index into FLAG_MODULES of the chunk that owns flag *name*."""
    index = 0
    for position, (_stem, _var, start) in enumerate(FLAG_MODULES):
        if name >= start:
            index = position
    return index


def render_flag_modules(flags: Scan) -> list[tuple[Path, str]]:
    """The full text of every generated data module under ``src/zyg_workflows/settings``.

    One (path, text) pair per entry in FLAG_MODULES, in that order. Temp-path defaults are
    hoisted into the module that uses them, so each chunk stays self-contained and no
    suppression leaks across files.
    """
    chunks: list[list[tuple[str, object, list[str]]]] = [[] for _ in FLAG_MODULES]
    for name, (default, files) in sorted(flags.items()):
        chunks[_chunk_of(name)].append((name, default, files))

    written: list[tuple[Path, str]] = []
    for (stem, var, _start), chunk in zip(FLAG_MODULES, chunks, strict=True):
        path = SETTINGS_PKG / f'{stem}.py'
        entries = ''.join(_entry(name, default, files) for name, default, files in chunk)
        hoisted = render_hoisted({name: (default, files) for name, default, files in chunk})
        span = f'{chunk[0][0]} .. {chunk[-1][0]}' if chunk else 'no entries'
        source = f"""# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

\"\"\"FLAGS entries {span} — {len(chunk)} of {len(flags)}.

GENERATED by scripts/gen_settings.py from the source itself — do not edit by hand; run
``python3 scripts/gen_settings.py`` after adding or removing an environment read.
``gen_settings.py --check`` fails when this file no longer matches the source.
\"\"\"

from __future__ import annotations

from zyg_workflows.settings.core import Flag

{hoisted}{var}: dict[str, Flag] = {{
{entries}}}
"""
        written.append((path, _ruff_format(source, path)))
    return written


def _env_default(default: object) -> str:
    if default is None:
        return ''
    if isinstance(default, bool):
        return '1' if default else '0'
    return str(default)


def render_env_example(flags: Scan) -> str:
    """The full text of ``.env.example``."""
    lines = [
        '# .env.example — every environment variable zyg_workflows reads, with its default.',
        '# GENERATED by scripts/gen_settings.py — do not edit by hand.',
        '#',
        '# Nothing here needs to be set: each default is what the production tree uses today.',
        '# In particular ZYG_CREWS_ROOT defaults to the legacy tree (~/Zygomatic Full/agents/crews),',
        '# so an unconfigured checkout reads and writes exactly where the old installation does.',
        '# Uncomment a line to override it. A default written ~/… is relative to your home directory.',
        '',
        '# --- roots and service endpoints (src/zyg_workflows/paths.py) ---',
    ]
    lines += [f'# {name}={default}  # {note}' for name, default, note in PATH_VARS]
    lines += ['', f'# --- feature flags ({len(flags)}, scanned from src/zyg_workflows) ---']
    lines += [f'# {name}={_env_default(default)}' for name, (default, _files) in sorted(flags.items())]
    return '\n'.join(lines) + '\n'


def render_doc_block(flags: Scan) -> str:
    """The generated section of ``docs/configuration.md`` (without the markers)."""
    lines = [
        '',
        '## Roots and service endpoints',
        '',
        'Declared in `src/zyg_workflows/paths.py`. Every one is read from the environment and falls',
        'back to the value the production tree uses, so **an unconfigured checkout behaves like the',
        'legacy installation**: `ZYG_CREWS_ROOT` defaults to `~/Zygomatic Full/agents/crews`.',
        '',
        '| Variable | Default | Points at |',
        '| --- | --- | --- |',
    ]
    lines += [f'| `{name}` | `{default}` | {note} |' for name, default, note in PATH_VARS]
    lines += [
        '',
        'Scratch files go to `paths.tmp_dir(sub)`, which creates `$ZYG_TMP_DIR/sub` with mode `0700`.',
        '',
        '## Feature flags',
        '',
        f'{len(flags)} `ZYG_*` variables, scanned out of `src/zyg_workflows` by `scripts/gen_settings.py`',
        'and registered in `src/zyg_workflows/settings.py` as `FLAGS`. An empty default column means the',
        'call site passes no default (the flag is optional and the code handles its absence).',
        'Read one with `settings.get(name, cast)`; `settings.check()` warns about `ZYG_*` variables that',
        'are set but that nothing reads. Defaults that were absolute paths inside a home directory are',
        'stored home-relative (`~/…`) and expanded by `settings.get()`.',
        '',
        '| Flag | Default | Read in |',
        '| --- | --- | --- |',
    ]
    for name, (default, files) in sorted(flags.items()):
        shown = ', '.join(f'`{f}`' for f in files[:3])
        if len(files) > 3:
            shown += f' +{len(files) - 3} more'
        cell = '' if default is None else f'`{default}`'
        lines.append(f'| `{name}` | {cell} | {shown} |')
    lines.append('')
    return '\n'.join(lines)


def render_doc(flags: Scan) -> str:
    """``docs/configuration.md``: the generated block merged into whatever is already there."""
    block = render_doc_block(flags)
    existing = DOC.read_text(encoding='utf-8') if DOC.exists() else ''
    if DOC_BEGIN in existing and DOC_END in existing:
        head, rest = existing.split(DOC_BEGIN, 1)
        _stale, tail = rest.split(DOC_END, 1)
        return f'{head}{DOC_BEGIN}{block}{DOC_END}{tail}'
    if existing.strip():
        return f'{existing.rstrip()}\n\n{DOC_BEGIN}{block}{DOC_END}\n'
    # REUSE-IgnoreStart
    # These two lines are the header this script WRITES into docs/configuration.md, not this
    # file's own licence. Without the ignore markers `reuse lint` parses the trailing `-->` as
    # part of the expression and reports an invalid SPDX License Expression.
    header = (
        '<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->\n'
        '<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->\n'
        '\n'
        '# Configuration\n'
        '\n'
        'How a zygomatic-workflows checkout is configured: the filesystem roots, the service\n'
        'endpoints, and every `ZYG_*` feature flag. The tables below are generated — run\n'
        '`python3 scripts/gen_settings.py` to refresh them and `--check` to assert they are current.\n'
        '\n'
    )
    # REUSE-IgnoreEnd
    return f'{header}{DOC_BEGIN}{block}{DOC_END}\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='do not write; exit 1 if a generated file is stale')
    args = parser.parse_args()

    flags = scan()
    targets = [
        *render_flag_modules(flags),
        (ENV_EXAMPLE, render_env_example(flags)),
        (DOC, render_doc(flags)),
    ]

    if args.check:
        stale = [path for path, wanted in targets if not path.exists() or path.read_text(encoding='utf-8') != wanted]
        for path in stale:
            state = 'missing' if not path.exists() else 'stale'
            print(f'{state}: {path.relative_to(ROOT)}')
        if stale:
            print(f'{len(stale)} file(s) out of date — run: python3 scripts/gen_settings.py')
            return 1
        print(
            f'up to date: {len(flags)} flags in {SETTINGS_PKG.relative_to(ROOT)}/'
            f'{{{",".join(stem for stem, _var, _start in FLAG_MODULES)}}}.py, '
            '.env.example, docs/configuration.md'
        )
        return 0

    for path in (p for p, _ in targets):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path, wanted in targets:
        path.write_text(wanted, encoding='utf-8')
        print(f'wrote {path.relative_to(ROOT)}')
    print(f'{len(flags)} flags')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
