# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages split out of ``relief_subdiv.measurement.measure``.

Only the pure stages are covered — the report envelope, the three whitelists and
the two row formatters — all of which take plain dicts. ``prepare_cage_body``,
``level_meshes``, ``level_null_record``, ``body_pools`` and ``probe_all_states``
build or subdivide a cage and are left to the module's own ``measure`` run.
``print_cut_table`` is exercised against a hand-built level record, since the
table it prints is the only place ``_fmt`` is read from.
"""

import logging

from zyg_workflows.geom.relief_subdiv.constants import SCHEMA
from zyg_workflows.geom.relief_subdiv.measurement import _fmt, _row
from zyg_workflows.geom.relief_subdiv import measurement_stages as MST


# ── _row ──────────────────────────────────────────────────────────────────────


def test_a_resolved_probe_row_reads_the_record_for_its_resolution_mode():
    rec = {
        'status': 'ok',
        'resolution_verdict': 'resolved',
        'resolution_mode': 'ridge',
        'resolves_relief': True,
        'by_mode': {
            'ridge': {'longest_run': 7, 'peak_relief_mm': 1.25, 'peak_contrast': 3.5},
            'point': {'longest_run': 1, 'peak_relief_mm': 0.1, 'peak_contrast': 0.2},
        },
    }
    assert _row(rec) == ('resolved', 7, 1.25, 3.5, True)


def test_a_probe_that_did_not_run_is_a_stub_row_rather_than_a_crash():
    assert _row({'status': 'no_pool'}) == ('no_pool', 0, None, None, False)
    # a record with no status at all still yields a row
    assert _row({}) == ('EMPTY', 0, None, None, False)


def test_a_resolved_row_with_no_by_mode_block_falls_back_to_zero_and_none():
    rec = {'status': 'ok', 'resolution_verdict': 'point_only', 'resolution_mode': 'point'}
    assert _row(rec) == ('point_only', 0, None, None, False)


def test_resolves_is_the_records_own_flag_not_inferred_from_the_verdict():
    rec = {
        'status': 'ok',
        'resolution_verdict': 'resolved',
        'resolution_mode': 'ridge',
        'resolves_relief': False,
        'by_mode': {'ridge': {'longest_run': 4}},
    }
    assert _row(rec)[4] is False


# ── _fmt ──────────────────────────────────────────────────────────────────────


def test_a_row_formats_to_a_fixed_width_cell():
    cell = _fmt(('resolved', 7, 1.25, 3.5, True))
    assert cell == 'resolved   /7     1.25 c3.5   '
    assert len(cell) == 30


def test_a_missing_peak_or_contrast_prints_a_dash():
    assert _fmt(('EMPTY', 0, None, None, False)) == 'EMPTY      /0        - c-     '


def test_a_single_digit_run_always_gives_the_same_width_whatever_the_verdict():
    widths = {
        len(_fmt(t))
        for t in (
            ('resolved', 7, 1.25, 3.5, True),
            ('EMPTY', 0, None, None, False),
            ('point_only', 9, 0.0, 99.75, False),
        )
    }
    assert widths == {30}


def test_the_run_is_unpadded_so_a_long_run_widens_the_cell():
    # print_cut_table pads every cell to 26 of its own, which absorbs this
    assert len(_fmt(('resolved', 123, 1.0, 2.0, True))) == 32


# ── report_header ─────────────────────────────────────────────────────────────


def test_the_report_envelope_records_the_schema_the_settings_and_the_build():
    out = MST.report_header(2.5, ('base', 'sub'), ('level',))
    assert out['schema'] == SCHEMA
    assert out['scale'] == 2.5
    assert out['states'] == ['base', 'sub']
    assert out['cut_kinds'] == ['level']
    assert out['bodies'] == {}
    # the provenance block is what tells a stale artefact apart from a current one
    assert out['produced_by']
    assert out['date']


def test_the_envelope_copies_its_sequences_so_the_caller_cannot_mutate_the_report():
    states = ['base', 'sub']
    out = MST.report_header(1.0, states, ('level',))
    states.append('cage2sub')
    assert out['states'] == ['base', 'sub']


def test_the_scale_is_stored_as_a_float_whatever_was_passed():
    assert isinstance(MST.report_header(1, (), ())['scale'], float)


# ── cuts_record ───────────────────────────────────────────────────────────────


def test_a_cut_record_keeps_the_whitelisted_keys_for_both_modes():
    cuts = {
        'ridge': {
            'min_frac_stature': 1e-4,
            'min_contrast': 2.0,
            'min_run': 5,
            'min_run_any_sign': 7,
            'source': 'level',
            'null_rate_resolved': 0.01,
            'null_rate_point_only_or_better': 0.05,
            'null_rate_measured_at': {'min_run': 5},
            'scratch': 'dropped',
        },
        'point': {'min_frac_stature': 2e-4, 'min_contrast': 1.0, 'min_run': 1, 'noise': 'dropped'},
    }
    rec = MST.cuts_record(cuts)
    assert set(rec) == {'ridge', 'point'}
    assert 'scratch' not in rec['ridge']
    assert 'noise' not in rec['point']
    assert rec['ridge']['min_run_any_sign'] == 7
    assert rec['point'] == {'min_frac_stature': 2e-4, 'min_contrast': 1.0, 'min_run': 1}


def test_the_rate_and_the_cut_it_was_measured_at_are_kept_together():
    # a chance rate without the cut it was measured at is the defect cuts_for was fixed for
    cuts = {
        'ridge': {'null_rate_resolved': 0.02, 'null_rate_measured_at': {'min_run': 5, 'min_contrast': 2.0}},
        'point': {},
    }
    rec = MST.cuts_record(cuts)
    assert rec['ridge']['null_rate_resolved'] == 0.02
    assert rec['ridge']['null_rate_measured_at'] == {'min_run': 5, 'min_contrast': 2.0}


def test_a_mode_with_none_of_the_whitelisted_keys_is_an_empty_record_not_an_error():
    assert MST.cuts_record({'ridge': {}, 'point': {'junk': 1}}) == {'ridge': {}, 'point': {}}


# ── _relief_report ────────────────────────────────────────────────────────────


def test_the_relief_report_is_whitelisted_down_to_its_recorded_fields():
    rep = {
        'displaced_vertices': 1234,
        'max_displacement_mm': 2.5,
        'rms_displacement_mm': 0.4,
        'mirror': {'max_asymmetry_mm': 0.0},
        'amplitude_audit': {'below_null_by_amplitude': ['chin'], 'other': 'dropped'},
        'bone_frame_cage_failures': 0,
        'mirror_map_used': 'fast',
        'seconds': 12.0,
        'huge_debug_array': list(range(1000)),
        'features': [
            {'name': 'chin', 'claim': 'c', 'status': 'ok', 'n_seeds_total': 9, 'internal': 'dropped'},
        ],
    }
    out = MST._relief_report(rep)
    assert 'huge_debug_array' not in out
    assert out['amplitude_audit'] == ['chin']
    assert out['features'] == [
        {
            'name': 'chin',
            'claim': 'c',
            'status': 'ok',
            'n_seeds_total': 9,
            'n_vertices_touched': None,
            'delivered_amp_mm': None,
            'delivered_amp_frac_stature': None,
            'refused_anchor_points': None,
        }
    ]


def test_an_empty_relief_report_yields_every_key_as_none():
    out = MST._relief_report({})
    assert out['displaced_vertices'] is None
    assert out['amplitude_audit'] is None
    assert out['features'] == []


# ── cage_body_record ──────────────────────────────────────────────────────────


def _cage_body(**over):
    kw = {
        'who': 'female',
        'params': {},
        'v0': None,
        'faces0': None,
        'bones': None,
        'weights': None,
        'stature_m': 1.6,
        'mate0': None,
        'v0_relief': None,
        'cage_report': {
            'displaced_vertices': 10,
            'max_displacement_mm': 1.0,
            'amplitude_audit': {'below_null_by_amplitude': []},
            'mirror': {'ok': True},
        },
        'fast_mirror_check': {'cage': True, 'level1': True},
    }
    kw.update(over)
    return MST.CageBody(**kw)


def test_the_body_section_carries_the_cage_stature_and_an_empty_levels_map():
    rec = MST.cage_body_record(_cage_body())
    assert rec['stature_cage_m'] == 1.6
    assert rec['levels'] == {}
    assert rec['fast_mirror_map_verification'] == {'cage': True, 'level1': True}
    assert rec['cage_relief_report']['displaced_vertices'] == 10
    assert rec['cage_relief_report']['amplitude_audit'] == []


def test_a_body_whose_cage_relief_reported_nothing_still_yields_the_section():
    rec = MST.cage_body_record(_cage_body(cage_report={}))
    assert rec['cage_relief_report'] == {
        'displaced_vertices': None,
        'max_displacement_mm': None,
        'amplitude_audit': None,
        'mirror': None,
    }


# ── print_cut_table ───────────────────────────────────────────────────────────


def _level_record(states, kind, rows_per_state):
    return {'states': {'%s@%s' % (st, kind): {'rows': rows} for st, rows in zip(states, rows_per_state)}}


def test_the_table_has_a_column_per_state_and_marks_what_the_last_one_resolves(caplog):
    pools = [('chin', object()), ('nasion', object())]
    states = ('base', 'sub')
    base_rows = {
        'chin': {'verdict': 'EMPTY', 'run': 0, 'peak_relief_mm': None, 'peak_contrast': None, 'resolves': False},
        'nasion': {'verdict': 'EMPTY', 'run': 0, 'peak_relief_mm': None, 'peak_contrast': None, 'resolves': False},
    }
    sub_rows = {
        'chin': {'verdict': 'resolved', 'run': 7, 'peak_relief_mm': 1.25, 'peak_contrast': 3.5, 'resolves': True},
        'nasion': {'verdict': 'point_only', 'run': 2, 'peak_relief_mm': 0.4, 'peak_contrast': 1.1, 'resolves': False},
    }
    lrec = _level_record(states, 'level', [base_rows, sub_rows])
    cuts = {'ridge': {'min_frac_stature': 1.5e-4, 'min_contrast': 2.0, 'min_run': 5}}

    with caplog.at_level(logging.INFO, logger=MST.__name__):
        MST.print_cut_table(lrec, pools, states, 'level', cuts)
    lines = [ln for ln in '\n'.join(caplog.messages).splitlines() if ln.strip()]

    # the header quotes the ridge-mode cut the rows were scored at
    assert 'per-landmark, level cut' in lines[0]
    assert 'min_run 5 for mode ridge' in lines[0]
    assert 'base' in lines[1] and 'sub' in lines[1]
    chin, nasion = lines[2], lines[3]
    assert chin.strip().startswith('chin')
    assert chin.rstrip().endswith('RESOLVES')
    assert nasion.strip().startswith('nasion')
    assert not nasion.rstrip().endswith('RESOLVES')
    assert '1.25 c3.5' in chin
