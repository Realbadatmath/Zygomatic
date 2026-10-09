# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the tallies extracted out of `expansion_hub.aggregation.build`.

Every helper here is pure: it takes the swept file rows and returns a section
of the payload. No filesystem sweep, no services, no network.
"""

import os

from zyg_dashboard.expansion_hub import aggregation_sections as AS


def _f(**kw):
    """One swept file row with every key `_scan_tree` produces, overridable by keyword."""
    row = {
        'path': 'pkg/mod.py',
        'abs': '/repo/pkg/mod.py',
        'comp': 'core',
        'kind': 'code',
        'ext': 'py',
        'bytes': 100,
        'lines': 10,
        'blank': 1,
        'comment': 2,
        'defs': 3,
        'classes': 1,
        'routes': 0,
        'main': 0,
        'scripts': 0,
        'mtime': 1700000000,
        'units': None,
        'units_rule': None,
        'p_lits': 0,
        'p_chars': 0,
        'p_lines': 0,
    }
    row.update(kw)
    return row


def test_agg_sums_files_bytes_and_lines():
    assert AS._agg([_f(bytes=10, lines=1), _f(bytes=5, lines=4)]) == {'files': 2, 'bytes': 15, 'lines': 5}


def test_agg_of_nothing_is_all_zeroes():
    assert AS._agg([]) == {'files': 0, 'bytes': 0, 'lines': 0}


def test_kind_rows_skip_empty_kinds_and_carry_the_line_share():
    rows = AS._kind_rows([_f(kind='code', lines=30), _f(kind='docs', ext='md', lines=10)])
    assert [r['kind'] for r in rows] == ['code', 'docs']
    assert [r['share_lines'] for r in rows] == [75.0, 25.0]
    assert rows[0]['label'] and rows[0]['files'] == 1


def test_kind_rows_of_nothing_is_an_empty_table():
    assert AS._kind_rows([]) == []


def test_ext_rows_rank_by_lines_and_name_the_largest_file():
    rows = AS._ext_rows(
        [
            _f(ext='py', lines=10, path='a.py'),
            _f(ext='py', lines=30, path='b.py'),
            _f(ext='md', kind='docs', lines=5, path='c.md'),
        ]
    )
    assert [r['ext'] for r in rows] == ['py', 'md']
    py = rows[0]
    assert (py['min_lines'], py['median_lines'], py['max_lines']) == (10, 20, 30)
    assert py['largest'] == 'b.py'
    assert py['kind'] == 'code'


def test_language_groups_slice_by_extension_and_spot_tests():
    langs = AS._language_groups(
        [
            _f(ext='py', path='pkg/mod.py', abs='/repo/pkg/mod.py'),
            _f(ext='py', path=os.path.join('tests', 'test_mod.py'), abs='/repo/tests/test_mod.py'),
            _f(ext='ts', path='web/app.ts'),
            _f(ext='jinja', path='web/page.jinja'),
            _f(ext='scss', path='web/app.scss'),
        ]
    )
    assert len(langs.py) == 2
    assert [f['path'] for f in langs.tests] == [os.path.join('tests', 'test_mod.py')]
    assert len(langs.js) == len(langs.html) == len(langs.css) == 1


def test_structure_counts_add_up_the_python_facts():
    files = [
        _f(ext='py', path=os.path.join('pkg', 'bp_web.py'), abs='/repo/pkg/bp_web.py', defs=4, routes=2, main=1),
        _f(ext='py', path=os.path.join('tests', 'test_web.py'), abs='/repo/tests/test_web.py', lines=7, defs=1),
        _f(ext='sh', kind='config', path='run.sh'),
    ]
    counts = AS._structure_counts(files, AS._language_groups(files))
    assert counts['py_modules'] == 2
    assert counts['functions'] == 5
    assert counts['routes'] == 2
    assert counts['entry_points'] == 1
    assert counts['blueprints'] == 1
    assert counts['tests'] == 1
    assert counts['test_lines'] == 7
    assert counts['shell_scripts'] == 1


def test_prompt_group_reads_the_location_then_the_filename():
    assert AS._prompt_group(_f(path=os.path.join('_comfy_workflows', 'g.json'))) == 'ComfyUI workflow graphs'
    assert AS._prompt_group(_f(path=os.path.join('briefs', 'hero.md'))) == 'Character briefs'
    assert AS._prompt_group(_f(path='prompt_registry.json', abs='/repo/prompt_registry.json')) == 'Prompt registry'
    assert AS._prompt_group(_f(path='vlm_checklists.json', abs='/repo/vlm_checklists.json')) == 'VLM judge checklists'
    assert AS._prompt_group(_f(path='notes.txt', abs='/repo/notes.txt')) == 'Stand-alone prompt files'


def test_prompt_summary_groups_the_files_and_counts_the_in_code_literals():
    files = [
        _f(kind='prompt', ext='json', path=os.path.join('_comfy_workflows', 'g.json'), units=4, units_rule='nodes'),
        _f(kind='prompt', ext='md', path=os.path.join('briefs', 'hero.md'), units=1, units_rule='headings'),
        _f(ext='py', path='pkg/mod.py', p_lits=2, p_chars=300, p_lines=9),
    ]
    langs = AS._language_groups(files)
    out = AS._prompt_summary(files, langs.py)
    assert out['files'] == 2
    assert out['units'] == 5
    assert [g['group'] for g in out['groups']] == ['ComfyUI workflow graphs', 'Character briefs']
    assert out['in_code_files'] == 1
    assert (out['in_code_literals'], out['in_code_chars'], out['in_code_lines']) == (2, 300, 9)
    assert out['file_rows'][0]['rule'] == 'nodes'


def test_exclusion_rows_rank_by_count_and_drop_empty_skip_reasons():
    excluded_rows, skipped_rows = AS._exclusion_rows(
        [
            {'reason': 'build output', 'path': 'dist'},
            {'reason': 'build output', 'path': 'build'},
            {'reason': 'vcs', 'path': '.git'},
        ],
        {'too big': (3, 900), 'binary': (0, 0)},
    )
    assert [(r['reason'], r['count']) for r in excluded_rows] == [('build output', 2), ('vcs', 1)]
    assert excluded_rows[0]['paths'] == ['build', 'dist']
    assert skipped_rows == [{'reason': 'too big', 'files': 3, 'bytes': 900}]


def test_file_rows_use_the_short_browser_keys_in_order():
    (row,) = AS._file_rows([_f(path='pkg/mod.py', lines=10, blank=1, comment=2, defs=3)])
    assert list(row) == ['p', 'c', 'k', 'e', 'b', 'l', 'bl', 'cm', 'd', 'cl', 'r', 'm', 'u', 'pl']
    assert (row['p'], row['l'], row['bl'], row['cm'], row['d']) == ('pkg/mod.py', 10, 1, 2, 3)


def test_limitations_keep_the_fixed_caveats_and_append_this_scan_cost():
    out = AS._limitations(1234, 7)
    assert out[:-1] == list(AS._LIMITATIONS)
    assert 'walk 1234 ms' in out[-1]
    assert '7 files read this time' in out[-1]
