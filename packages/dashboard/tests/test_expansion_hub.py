#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > Expansion: the census counts structure, excludes what the program produces,
and says so.

    ../.venv/bin/python -m pytest tests/test_expansion_hub.py

The point of this tab is that an exclusion is a visible claim, so the tests pin that: the
generated trees (output, runtime, media libraries, venvs, backups, worktree/legacy copies)
are pruned AND listed with a reason, the hand-listed prompt file inside a pruned tree is
still counted, prompt literals come from the AST and not from grep, and a re-scan with
nothing changed keeps its data_version.
"""

import ast
import os
import sys

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

from zyg_workflows import paths as _paths  # noqa: E402

from zyg_dashboard import expansion_hub as ex  # noqa: E402

# The census reads the production tree (sibling apps, training roots, the crews data root);
# on a bare checkout its numbers mean nothing, so the module skips rather than asserts.
# `data/` alone is no evidence: importing the app auto-creates the empty data root, so the
# guard checks for things only a real installation has — assets under the data root and the
# first training root the census itself walks.
if not ((_paths.ZYG_CREWS_ROOT / 'data' / 'assets').is_dir() and os.path.isdir(ex.TRAINING_ROOTS[0]['root'])):
    pytest.skip('the expansion census needs the production installation under ZYG_CREWS_ROOT', allow_module_level=True)


@pytest.fixture(scope='module')
def payload():
    return ex.build()


# ── classification ───────────────────────────────────────────────────────────


def test_ext_special_names():
    assert ex._ext('Dockerfile.cpu') == 'dockerfile'
    assert ex._ext('docker-compose.cpu.yml') == 'compose'
    assert ex._ext('requirements-dev.txt') == 'requirements'
    assert ex._ext('.gitignore') == '.gitignore'
    assert ex._ext('a.b.PY') == 'py'


def test_kind_rules():
    assert ex._kind_of('/x/foo.py', 'py', []) == 'code'
    assert ex._kind_of('/x/cfg.yaml', 'yaml', []) == 'config'
    assert ex._kind_of('/x/README.md', 'md', []) == 'docs'
    # media is an asset only inside a GUI asset folder, generated content elsewhere
    assert ex._kind_of('/x/Static/icons/a.png', 'png', ['Static', 'icons']) == 'asset'
    assert ex._kind_of('/x/renders/a.png', 'png', ['renders']) is None
    # prompt material wins over its container format
    assert ex._kind_of('/x/prompts/system_prompt.txt', 'txt', ['prompts']) == 'prompt'
    assert ex._kind_of('/x/agents/crews/_comfy_workflows/g.json', 'json', ['_comfy_workflows']) == 'prompt'
    assert (
        ex._kind_of('/x/agents/crews/agents/CEO-Agent/a.json', 'json', ['agents', 'crews', 'agents', 'CEO-Agent'])
        == 'prompt'
    )


def test_backup_names_are_skipped():
    for n in ('a.py.bak-x-20260101', 'a.json.backup_20250714', 'a.py~', 'a.py.orig', 'cfg.v1-20260919'):
        assert ex._is_backup_name(n), n
    # 'backup_tool.py' carries a backup word inside a real name: the author left either
    # answer allowed, so this only pins down that the call itself does not raise. (It used
    # to read `assert not ... is False or True`, which is `True` whatever happens.)
    ex._is_backup_name('backup_tool.py')
    assert not ex._is_backup_name('metrics_hub.py')


def test_prune_reasons():
    assert ex._prune_reason('/r/.git', '.git', '/r', '/r')
    assert ex._prune_reason('/r/node_modules', 'node_modules', '/r', '/r')
    assert ex._prune_reason('/r/output', 'output', '/r', '/r')
    assert (
        ex._prune_reason('/r/x.identity_audit_fix_backups_2026', 'x.identity_audit_fix_backups_2026', '/r', '/r')
        == 'backup copy'
    )
    assert ex._prune_reason('/r/legacy', 'legacy', '/r', '/r').startswith('legacy copy')
    assert ex._prune_reason('/r/projects', 'projects', '/r', '/r') == 'user documents / app content'
    assert ex._prune_reason('/r/src', 'src', '/r', '/r') is None
    # agents/crews/data: only the allow-listed folders survive
    assert (
        ex._prune_reason(os.path.join(ex.CREWS_DATA, 'stack_lineage'), 'stack_lineage', ex.CREWS_DATA, ex.ROOT) is None
    )
    assert ex._prune_reason(os.path.join(ex.CREWS_DATA, 'asset_libraries'), 'asset_libraries', ex.CREWS_DATA, ex.ROOT)
    assert (
        ex._prune_reason(
            os.path.join(ex.CREWS_DATA, 'char2d', 'briefs'), 'briefs', os.path.join(ex.CREWS_DATA, 'char2d'), ex.ROOT
        )
        is None
    )
    assert ex._prune_reason(
        os.path.join(ex.CREWS_DATA, 'char2d', 'gestures'), 'gestures', os.path.join(ex.CREWS_DATA, 'char2d'), ex.ROOT
    )


# ── prompt literals by AST ───────────────────────────────────────────────────


def test_prompt_literals_ast():
    src = '''
SYSTEM_PROMPT = """You are a documentary scriptwriter.
Use only the facts below."""
other = "not a prompt but a long enough string to matter"
def f():
    msgs = [{"role": "system", "content": "Answer in Dutch, briefly please."}]
    call(prompt="draw a %s on a plate" % thing, temperature=0)
    negative_prompt = build()          # not a literal: not counted
QUESTIONS = {"a": "Is the hand holding five fingers only?", "b": 3}
'''
    count, chars, lines = ex._prompt_literals(src)
    assert count == 4  # SYSTEM_PROMPT, system message, prompt=, one bank string
    assert chars > 100
    assert lines >= 5


def test_prompt_literals_tolerate_bad_source():
    assert ex._prompt_literals('def (:\n') == (0, 0, 0)


def test_prompt_units_by_shape(tmp_path):
    assert ex._prompt_units('/x/p.txt', 'txt', 'hello')[0] == 1
    g = (
        '{"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red fox, photoreal", "clip": ["2", 0]}},'
        ' "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}}}'
    )
    assert ex._prompt_units('/x/_comfy_workflows/g.json', 'json', g)[0] == 1
    reg = '{"prompts": {"a": {}, "b": {}}}'
    assert ex._prompt_units('/x/prompt_registry.json', 'json', reg)[0] == 2


# ── the real tree ────────────────────────────────────────────────────────────


def test_payload_shape(payload):
    for k in (
        'data_version',
        'totals',
        'by_kind',
        'by_ext',
        'components',
        'folders',
        'files',
        'structure',
        'prompts',
        'training',
        'services',
        'excluded',
        'skipped',
        'rules',
        'notes',
        'limitations',
    ):
        assert k in payload, k
    t = payload['totals']
    assert t['files'] == len(payload['files'])
    assert t['lines'] == sum(f['l'] for f in payload['files'])
    assert t['py'] > 500 and t['json'] > 50
    assert payload['components'][0]['id'] == 'zygomatic_full'
    assert payload['components'][0]['root'] == ex.ROOT


def test_generated_trees_are_excluded_and_listed(payload):
    paths = {f['p'] for f in payload['files']}
    assert not any(p.startswith('output' + os.sep) for p in paths)
    assert not any(os.sep + 'data' + os.sep + 'output' + os.sep in p for p in paths)
    assert not any(os.sep + 'asset_libraries' + os.sep in p for p in paths)
    assert not any('node_modules' in p or '.venv' in p or '__pycache__' in p for p in paths)
    assert not any('.bak' in p for p in paths)
    # A generated tree only has to be listed when this checkout actually carries it: the
    # repo split left `output/`, `models/` and `orchestrator.worktrees/` outside the
    # package, so hard-coding them pinned one machine's layout. `data/runtime` always
    # exists by the time the fixture has run — ex.build() writes its line cache there —
    # so the loop below is never vacuous.
    listed = {p for row in payload['excluded'] for p in row['paths']}
    generated = [
        os.path.join(ex.ROOT, 'output'),
        os.path.join(ex.CREWS_DATA, 'output'),
        os.path.join(ex.CREWS_DATA, 'runtime'),
        os.path.join(ex.ROOT, 'orchestrator.worktrees'),
        os.path.join(ex.ROOT, 'models'),
    ]
    present = [p for p in generated if os.path.isdir(p)]
    assert os.path.join(ex.CREWS_DATA, 'runtime') in present
    for p in present:
        assert p in listed, f'{p} was pruned without being listed with a reason'


def test_hand_listed_prompt_file_survives_pruned_tree(payload):
    reg_abs = ex.EXTRA_FILES[0]
    if not os.path.exists(reg_abs):
        pytest.skip(f'hand-listed prompt file absent in this checkout: {reg_abs} (written at runtime)')
    reg = os.path.relpath(reg_abs, ex.ROOT)
    rows = [f for f in payload['files'] if f['p'] == reg]
    assert rows and rows[0]['k'] == 'prompt' and rows[0]['u'] >= 1


def test_prompt_sources_present(payload):
    groups = {g['group'] for g in payload['prompts']['groups']}
    assert {'ComfyUI workflow graphs', 'Agent persona configs', 'VLM judge checklists'} <= groups
    # The registry is runtime state, so it is only a prompt source once it has been written.
    if os.path.exists(ex.EXTRA_FILES[0]):
        assert 'Prompt registry' in groups
    assert payload['prompts']['in_code_literals'] > 100
    assert payload['prompts']['in_code_files'] > 20


def test_training_roots_counted_not_read(payload):
    tr = payload['training']
    ids = {r['id'] for r in tr['roots']}
    assert ids == {'lora_datasets', 'voice_seeds'}
    assert tr['totals']['files'] == sum(s['files'] for r in tr['roots'] for s in r.get('datasets', []))
    assert tr['totals']['datasets'] >= 5


@pytest.mark.service
def test_services_map_to_components(payload):
    # Needs this machine's installed systemd units: the mapping is read off the unit files'
    # WorkingDirectory/ExecStart, so on a checkout without crewai-gui/medusa/comfyui
    # installed — or with them pointing at a different tree than this one — it says nothing.
    units = {s['unit']: s for s in payload['services']}
    gui_wd = units['crewai-gui.service'].get('working_dir') or ''
    if not (gui_wd == ex.ROOT or gui_wd.startswith(ex.ROOT + os.sep)):
        pytest.skip(f'crewai-gui.service runs from {gui_wd!r}, not from this checkout ({ex.ROOT})')
    assert units['crewai-gui.service']['component'] == 'zygomatic_full'
    assert units['medusa.service']['component'] == 'medusa'
    assert units['comfyui.service']['component'] is None and units['comfyui.service']['third_party']
    assert units['zyg-cpu-cap.service']['component'] == 'launchers'


def test_rescan_keeps_version_when_nothing_changed(payload):
    again = ex.build()
    assert again['data_version'] == payload['data_version']
    assert again['scan']['files_read'] == 0


def test_module_is_stdlib_only():
    # expansion_hub is a package; every module of it is held to the claim, and a relative
    # import of a sibling (level > 0) is the package talking to itself, not a dependency.
    pkg_dir = os.path.dirname(ex.__file__)
    sources = [os.path.join(pkg_dir, name) for name in sorted(os.listdir(pkg_dir)) if name.endswith('.py')]
    mods = set()
    for source in sources:
        with open(source, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        mods |= {n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {
            n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and not n.level
        }
    # `logging`: the lint pass replaced this module's bare `except: pass` handlers with
    # `_zyg_log.debug(...)`, so it now imports logging. Still stdlib, so still stdlib-only.
    # `zyg_workflows`: the four-repo split moved binary lookup into the base library
    # (`from zyg_workflows.bin import exe`). It is pure stdlib itself, so the claim this
    # test defends — no heavy third-party import just to collect a metrics tab — holds.
    # `zyg_dashboard`: the package directory comes from zyg_dashboard.paths now that no module
    # rebinds __file__; that module is stdlib-only too.
    assert mods <= {
        'ast',
        'hashlib',
        'json',
        'logging',
        'os',
        're',
        'statistics',
        'subprocess',
        'sys',
        'time',
        'warnings',
        'zyg_dashboard',
        'zyg_workflows',
    }
