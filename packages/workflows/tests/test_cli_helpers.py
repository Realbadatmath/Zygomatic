# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The helpers `arch_pack_ingest.cli.main` was split into still behave as the ladder did.

`main` was one 311-line def: a parser, then thirteen `if` branches, each of which loaded a
registry, diffed it against what is on disk and printed a line. The branches that talk to
Poly Haven, ambientCG, the Smithsonian and Kenney need the network and are not exercised
here; what is tested is every piece of the ladder that was pure logic and had never been
called in isolation — the parser's defaults, the byte formatter, the "what do we already
hold" set, the registry merge and the report arithmetic.
"""

from __future__ import annotations

import json

import pytest

from zyg_workflows.arch_pack_ingest import cli


def test_the_parser_keeps_every_mode_and_default_the_ladder_reads():
    """--plan/--fetch/--prepare/--report and the four knobs, with the documented defaults."""
    a = cli._build_parser().parse_args([])
    assert a.plan is False
    assert a.fetch is None
    assert a.prepare is None
    assert a.report is False
    assert a.gapfill is False
    assert a.limit == 300
    assert a.si_limit == 0
    assert a.res == '2k'
    assert a.all is False

    a = cli._build_parser().parse_args(['--fetch', 'smithsonian-mammals', '--si-limit', '7', '--res', '4k', '--all'])
    assert (a.fetch, a.si_limit, a.res, a.all) == ('smithsonian-mammals', 7, '4k', True)


def test_the_parser_refuses_a_source_nothing_can_fetch():
    """A --fetch the ladder has no branch for is rejected by argparse, not silently ignored."""
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(['--fetch', 'sketchfab'])


def test_human_scales_bytes_up_one_unit_at_a_time():
    """Sizes are printed in the largest unit under 1024, and TB is the last stop."""
    assert cli.human(0) == '0.0B'
    assert cli.human(1023) == '1023.0B'
    assert cli.human(1024) == '1.0KB'
    assert cli.human(1024 * 1024) == '1.0MB'
    assert cli.human(3 * 1024**3) == '3.0GB'
    assert cli.human(2 * 1024**4) == '2.0TB'


def test_held_dirs_names_the_subdirectories_and_tolerates_a_missing_root(tmp_path):
    """The "already held" set is the sub-directories only; an un-ingested pack is empty."""
    (tmp_path / 'brick_wall').mkdir()
    (tmp_path / 'wood_floor').mkdir()
    (tmp_path / 'registry.json').write_text('{}')
    assert cli._held_dirs(str(tmp_path)) == {'brick_wall', 'wood_floor'}
    assert cli._held_dirs(str(tmp_path / 'never_ingested')) == set()


def test_load_registry_reads_the_pack_registry_or_returns_an_empty_one(tmp_path):
    """A first run has no registry.json and must get {} rather than an error."""
    assert cli._load_registry(str(tmp_path)) == {}
    (tmp_path / 'registry.json').write_text(json.dumps({'a': {'bytes': 1}}))
    assert cli._load_registry(str(tmp_path)) == {'a': {'bytes': 1}}


def test_merge_registry_extends_the_held_rows_and_lets_the_fresh_row_win(tmp_path):
    """A resumed haul adds its new rows and overwrites the rows it re-fetched."""
    (tmp_path / 'registry.json').write_text(json.dumps({'held': {'bytes': 1}, 'retaken': {'bytes': 2}}))
    keep = cli._merge_registry(str(tmp_path), {'retaken': {'bytes': 99}, 'new': {'bytes': 3}})
    assert keep == {'held': {'bytes': 1}, 'retaken': {'bytes': 99}, 'new': {'bytes': 3}}
    # The merge is in memory only — writing is the caller's (write_provenance's) job.
    assert json.loads((tmp_path / 'registry.json').read_text())['retaken'] == {'bytes': 2}


def test_registry_totals_sums_per_file_rows_and_flat_rows_alike():
    """--report counts every row and adds the per-file bytes of the ones that have files."""
    reg = {
        'model_a': {'files': {'gltf': {'bytes': 10}, 'jpg': {'bytes': 5}}},
        'material_b': {'bytes': 7},
        'empty_c': {},
    }
    assert cli._registry_totals(reg) == (3, 22)
    assert cli._registry_totals({}) == (0, 0)
