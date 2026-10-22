# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for zyg_dashboard.approval_queue_settings — the Approval Queue settings file.

Every test redirects the module's own PATH constant at tmp_path and empties the process-wide
cache first, so nothing is read from or written to the repo's data/runtime directory.
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from zyg_dashboard import approval_queue_settings as aqs


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the module at a settings file inside tmp_path and clear its cache."""
    path = tmp_path / 'runtime' / 'approval_queue_settings.json'
    monkeypatch.setattr(aqs, 'PATH', str(path))
    monkeypatch.setitem(aqs._CACHE, 'mtime', None)
    monkeypatch.setitem(aqs._CACHE, 'data', {})
    return path


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding='utf-8')


# ---------------------------------------------------------------- the environment defaults


def test_env_num_without_the_variable_keeps_the_default(monkeypatch):
    monkeypatch.delenv('ZYG_MELODY_PER_DAY', raising=False)
    assert aqs._env_num('ZYG_MELODY_PER_DAY', 5) == 5


@pytest.mark.parametrize(
    ('raw', 'default', 'expected'),
    [
        ('7', 5, 7),
        ('7.9', 5, 7),  # an int default truncates through float()
        ('  3  ', 9, 3),
        ('2.5', 1.0, 2.5),  # a float default keeps the fraction
        ('', 5, 5),  # blank is "unset"
        ('   ', 5, 5),
    ],
)
def test_env_num_reads_the_variable(monkeypatch, raw, default, expected):
    monkeypatch.setenv('ZYG_TEST_NUM', raw)
    got = aqs._env_num('ZYG_TEST_NUM', default)
    assert got == expected
    assert isinstance(got, type(default))


def test_env_num_warns_and_falls_back_when_the_value_is_not_numeric(monkeypatch, caplog):
    monkeypatch.setenv('ZYG_TEST_NUM', 'half past nine')
    with caplog.at_level(logging.WARNING, logger=aqs.__name__):
        assert aqs._env_num('ZYG_TEST_NUM', 4) == 4
    assert 'not numeric' in caplog.text


# ---------------------------------------------------------------- the schema shape


def test_the_field_builder_fills_every_key():
    f = aqs._f('k', 'Label', 'number', 3, 1, 9, 2, help_='why')
    assert f == {
        'key': 'k',
        'label': 'Label',
        'type': 'number',
        'default': 3,
        'min': 1,
        'max': 9,
        'step': 2,
        'options': [],
        'help': 'why',
    }


@pytest.mark.parametrize('wf', sorted(aqs.SCHEMA))
def test_every_schema_field_is_well_formed(wf):
    for f in aqs.SCHEMA[wf]:
        assert f['type'] in ('number', 'bool', 'select')
        assert f['key'] and f['label']
        if f['type'] == 'select':
            assert [o[0] for o in f['options']]


def test_field_lookup_finds_a_known_key_and_misses_an_unknown_one():
    assert aqs._field('melody', 'per_day')['label'] == 'Songs per day'
    assert aqs._field('melody', 'free_ram_gb') is None
    assert aqs._field('no_such_workflow', 'per_day') is None


# ---------------------------------------------------------------- coercion


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('1', True),
        ('true', True),
        (' TRUE ', True),
        ('yes', True),
        ('on', True),
        ('0', False),
        ('off', False),
        ('', False),
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (None, False),
    ],
)
def test_coerce_bool(raw, expected):
    f = aqs._field('melody', 'use_bank_first')
    assert aqs._coerce(f, raw) is expected


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        (3, 3),
        ('3', 3),
        (3.0, 3),  # a whole float on an int-defaulted field comes back int
        ('11.0', 11),
    ],
)
def test_coerce_number_in_range(raw, expected):
    f = aqs._field('documentary', 'topics_per_batch')
    got = aqs._coerce(f, raw)
    assert got == expected
    assert isinstance(got, int)


def test_coerce_number_keeps_a_fraction():
    f = aqs._field('documentary', 'cadence_days')
    assert aqs._coerce(f, '2.5') == 2.5


@pytest.mark.parametrize(
    ('wf', 'key', 'raw', 'message'),
    [
        ('documentary', 'topics_per_batch', 'six', 'not a number'),
        ('documentary', 'topics_per_batch', None, 'not a number'),
        ('documentary', 'topics_per_batch', 0, 'below 1'),
        ('documentary', 'topics_per_batch', 13, 'above 12'),
        ('documentary', 'batch_hour', -1, 'below 0'),
        ('documentary', 'batch_hour', 24, 'above 23'),
    ],
)
def test_coerce_number_rejects_bad_values(wf, key, raw, message):
    f = aqs._field(wf, key)
    with pytest.raises(ValueError, match=message):
        aqs._coerce(f, raw)


def test_coerce_select_accepts_the_options_and_rejects_the_rest():
    f = aqs._field('preempt', 'live_when_exhausted')
    assert aqs._coerce(f, 'never') == 'never'
    with pytest.raises(ValueError, match='must be one of'):
        aqs._coerce(f, 'sometimes')


def test_coerce_rejects_an_unknown_field_type():
    f = aqs._f('weird', 'Weird', 'colour', 'red')
    with pytest.raises(ValueError, match='unknown field type'):
        aqs._coerce(f, 'red')


# ---------------------------------------------------------------- loading the file


def test_load_returns_nothing_when_the_file_is_missing(store):
    assert aqs._load() == {}
    assert aqs._CACHE['mtime'] is None


def test_load_reads_the_file_and_then_serves_the_cache(store):
    _write(store, {'melody': {'per_day': 8}})
    assert aqs._load() == {'melody': {'per_day': 8}}
    mtime = aqs._CACHE['mtime']
    assert mtime is not None
    # A second call with an unchanged mtime must not re-read: rewrite the bytes, keep the mtime.
    store.write_text(json.dumps({'melody': {'per_day': 99}}), encoding='utf-8')
    os.utime(store, (mtime, mtime))
    assert aqs._load() == {'melody': {'per_day': 8}}


@pytest.mark.parametrize('payload', ['{not json', '', 'null', '[1, 2, 3]', '"a string"'])
def test_load_recovers_from_a_corrupt_or_non_mapping_file(store, payload):
    _write(store, payload)
    assert aqs._load() == {}


# ---------------------------------------------------------------- get / all_values / fields


def test_get_returns_the_default_when_nothing_was_saved(store):
    assert aqs.get('documentary', 'topics_per_batch') == 6
    assert aqs.get('documentary', 'use_bank_first') is True
    assert aqs.get('storyteller', 'max_per_day') == 22


def test_get_returns_the_saved_value_coerced(store):
    _write(store, {'documentary': {'topics_per_batch': '9', 'use_bank_first': 'no'}})
    assert aqs.get('documentary', 'topics_per_batch') == 9
    assert aqs.get('documentary', 'use_bank_first') is False


def test_get_ignores_a_workflow_section_that_is_not_a_mapping(store):
    _write(store, {'documentary': None})
    assert aqs.get('documentary', 'topics_per_batch') == 6


def test_get_warns_and_uses_the_default_for_an_invalid_saved_value(store, caplog):
    _write(store, {'documentary': {'topics_per_batch': 400}})
    with caplog.at_level(logging.WARNING, logger=aqs.__name__):
        assert aqs.get('documentary', 'topics_per_batch') == 6
    assert 'is invalid, using the default' in caplog.text


@pytest.mark.parametrize(
    ('wf', 'key'),
    [
        ('documentary', 'min_free_ram_gb'),  # the retired RAM gate field
        ('melody', 'nope'),
        ('no_such_workflow', 'per_day'),
    ],
)
def test_get_raises_key_error_for_a_field_outside_the_schema(store, wf, key):
    with pytest.raises(KeyError):
        aqs.get(wf, key)


def test_all_values_covers_the_whole_card(store):
    assert aqs.all_values('melody') == {'per_day': 5, 'hour': 9, 'use_bank_first': True}
    assert aqs.all_values('no_such_workflow') == {}


def test_fields_is_the_ui_shape(store):
    _write(store, {'preempt': {'concurrency': 30}})
    rows = aqs.fields('preempt')
    assert [r['key'] for r in rows] == [f['key'] for f in aqs.SCHEMA['preempt']]
    by_key = {r['key']: r for r in rows}
    assert by_key['concurrency']['value'] == 30
    assert by_key['concurrency']['default'] == 20
    assert by_key['live_when_exhausted']['options'][0][0] == 'auto'
    assert set(rows[0]) == {'key', 'label', 'type', 'min', 'max', 'step', 'options', 'help', 'value', 'default'}
    assert aqs.fields('no_such_workflow') == []


# ---------------------------------------------------------------- update


def test_update_writes_the_file_and_returns_the_new_values(store):
    out = aqs.update('melody', {'per_day': '12', 'use_bank_first': 'off'})
    assert out == {'per_day': 12, 'hour': 9, 'use_bank_first': False}
    assert json.loads(store.read_text(encoding='utf-8')) == {'melody': {'per_day': 12, 'use_bank_first': False}}
    assert not (store.parent / (store.name + '.tmp')).exists()


def test_update_merges_into_the_existing_sections(store):
    aqs.update('melody', {'per_day': 7})
    aqs.update('documentary', {'batch_hour': 21})
    aqs.update('melody', {'hour': 4})
    saved = json.loads(store.read_text(encoding='utf-8'))
    assert saved == {'melody': {'per_day': 7, 'hour': 4}, 'documentary': {'batch_hour': 21}}
    assert aqs.get('melody', 'per_day') == 7


def test_update_with_no_changes_is_a_no_op_that_still_reports(store):
    assert aqs.update('jackmona', None) == {'hour': 3}
    assert json.loads(store.read_text(encoding='utf-8')) == {'jackmona': {}}


def test_update_rejects_an_unknown_workflow(store):
    with pytest.raises(KeyError):
        aqs.update('no_such_workflow', {'per_day': 1})
    assert not store.exists()


@pytest.mark.parametrize(
    ('changes', 'message'),
    [
        ({'per_day': 99}, 'above 20'),
        ({'nope': 1}, 'unknown setting nope'),
        ({'per_day': 'lots'}, 'not a number'),
    ],
)
def test_update_validates_before_it_saves(store, changes, message):
    with pytest.raises(ValueError, match=message):
        aqs.update('melody', changes)
    assert not store.exists()


def test_update_validates_every_change_before_saving_any(store):
    aqs.update('melody', {'per_day': 3})
    with pytest.raises(ValueError, match='above 23'):
        aqs.update('melody', {'per_day': 6, 'hour': 99})
    assert json.loads(store.read_text(encoding='utf-8')) == {'melody': {'per_day': 3}}


def test_update_creates_the_runtime_directory(store):
    assert not store.parent.exists()
    aqs.update('storyteller', {'max_per_day': 10})
    assert store.parent.is_dir()
    assert aqs.all_values('storyteller') == {'max_per_day': 10}
