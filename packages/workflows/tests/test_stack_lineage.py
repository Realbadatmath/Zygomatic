#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > Lineage: the store validates, and the board derives what it promises.

    ../.venv/bin/python -m pytest tests/test_stack_lineage.py

The point of this tab is that it cannot say a nicer thing than the record does, so the
tests pin exactly that: the real store passes its own validator, "what the upgrade fixed"
is read off the PREDECESSOR's issue list rather than written on the upgrade, an entity
with no issues is reported as undocumented rather than as clean, and the honesty fields
(state, grade, evidence) are mandatory.
"""

import os
import sys

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

from zyg_workflows import stack_lineage_hub as lin  # noqa: E402


@pytest.fixture(scope='module')
def payload():
    return lin.build(fresh=True)


# ── the shipped store ────────────────────────────────────────────────────────


def test_real_store_is_valid():
    """Duplicate ids, links to nothing, bad enums/dates, an issue with no evidence."""
    assert lin.validate() == []


def test_store_is_not_empty(payload):
    assert payload['totals']['entities'] > 50
    assert payload['totals']['lanes'] >= 5
    assert payload['success'] is True


def test_every_issue_names_its_evidence_and_grade(payload):
    for lane in payload['lanes']:
        for e in lane['entities']:
            for iss in e['issues']:
                assert iss.get('evidence'), f'{e["id"]}: issue with no evidence'
                assert iss.get('grade') in lin.GRADES, f'{e["id"]}: {iss.get("grade")!r}'
                assert iss.get('state') in lin.STATES, f'{e["id"]}: {iss.get("state")!r}'


def test_live_engines_are_present(payload):
    """A smoke check that the store describes THIS stack, not a sample one."""
    ids = {e['id']: e for lane in payload['lanes'] for e in lane['entities']}
    for want in ('ltx25_distilled', 'hidream_o1', 'indextts2', 'ace_step_15_turbo', 'postgres16'):
        assert want in ids, want
        assert ids[want]['status'] == 'live', want


# ── derivation ───────────────────────────────────────────────────────────────


def _store(tmp_path, lanes):
    import json

    d = tmp_path / 'stack_lineage'
    d.mkdir(exist_ok=True)
    for name, body in lanes.items():
        (d / (name + '.json')).write_text(json.dumps(body), encoding='utf-8')
    lin.STORE = str(d)
    lin._CACHE.update(mtime=0.0, data=None)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    real = lin.STORE
    yield lambda lanes: _store(tmp_path, lanes)
    lin.STORE = real
    lin._CACHE.update(mtime=0.0, data=None)


def _ent(eid, **kw):
    base = {
        'id': eid,
        'name': eid.upper(),
        'kind': 'model',
        'role': 'r',
        'status': 'live',
        'licence': 'MIT',
        'summary': 's',
        'issues': [],
        'sources': [],
    }
    base.update(kw)
    return base


def _iss(text, state='open', grade='measured', **kw):
    out = {'text': text, 'state': state, 'grade': grade, 'evidence': 'memo'}
    out.update(kw)
    return out


def test_what_an_upgrade_fixed_is_read_off_its_predecessor(fake):
    """The successor's card must NOT be able to claim a fix the predecessor does not record."""
    fake(
        {
            'l': {
                'lane': 'l',
                'label': 'L',
                'entities': [
                    _ent(
                        'old',
                        status='retired',
                        replaced_by=['new'],
                        issues=[_iss('was slow', state='solved', fixed='2026-01-02', by='new')],
                    ),
                    _ent('new', replaced=['old']),
                ],
            }
        }
    )
    d = lin.build(fresh=True)
    new = [e for e in d['lanes'][0]['entities'] if e['id'] == 'new'][0]
    old = [e for e in d['lanes'][0]['entities'] if e['id'] == 'old'][0]
    assert [s['text'] for s in new['solved_for']] == ['was slow']
    assert new['solved_for'][0]['entity'] == 'old'
    assert old['solved_for'] == []  # the predecessor fixed nothing for anyone


def test_open_and_unmeasured_both_count_as_still_wrong(fake):
    fake(
        {
            'l': {
                'lane': 'l',
                'label': 'L',
                'entities': [
                    _ent('a', issues=[_iss('x'), _iss('y', state='unmeasured'), _iss('z', state='accepted')]),
                ],
            }
        }
    )
    d = lin.build(fresh=True)
    a = d['lanes'][0]['entities'][0]
    assert a['open_count'] == 2
    assert d['totals']['open'] == 2 and d['totals']['carried'] == 1
    assert len(d['open_issues']) == 2


def test_an_entity_with_no_issues_is_undocumented_not_clean(fake):
    fake({'l': {'lane': 'l', 'label': 'L', 'entities': [_ent('a'), _ent('b', issues=[_iss('x')])]}})
    d = lin.build(fresh=True)
    assert d['totals']['undocumented'] == 1 and d['totals']['documented'] == 1
    assert 'nothing recorded' in ' '.join(d['notes']).lower()


def test_in_stack_counts_only_what_can_still_be_called(fake):
    fake(
        {
            'l': {
                'lane': 'l',
                'label': 'L',
                'entities': [
                    _ent('a', status='live'),
                    _ent('b', status='gated_off'),
                    _ent('c', status='removed'),
                    _ent('d', status='rejected'),
                    _ent('e', status='retired'),
                ],
            }
        }
    )
    d = lin.build(fresh=True)
    assert d['totals']['in_stack'] == 2  # live + installed-but-off
    assert d['totals']['gone'] == 2  # retired + removed
    assert d['totals']['refused'] == 1


def test_open_issues_rank_in_stack_and_measured_first(fake):
    fake(
        {
            'l': {
                'lane': 'l',
                'label': 'L',
                'entities': [
                    _ent(
                        'gone',
                        status='rejected',
                        issues=[_iss('refused for this', grade='measured', found='2026-09-01')],
                    ),
                    _ent(
                        'here',
                        issues=[
                            _iss('reasoned', grade='assumed', found='2026-09-01'),
                            _iss('measured', grade='measured', found='2026-08-01'),
                        ],
                    ),
                ],
            }
        }
    )
    d = lin.build(fresh=True)
    assert [i['text'] for i in d['open_issues']] == ['measured', 'reasoned', 'refused for this']


def test_a_diamond_chain_keeps_only_the_long_walk(fake):
    fake(
        {
            'l': {
                'lane': 'l',
                'label': 'L',
                'entities': [
                    _ent('a', replaced_by=['b', 'c']),
                    _ent('b', replaced_by=['c']),
                    _ent('c'),
                ],
            }
        }
    )
    d = lin.build(fresh=True)
    assert [c['ids'] for c in d['lanes'][0]['chains']] == [['a', 'b', 'c']]


def test_validator_catches_the_mistakes_that_hide(fake):
    fake(
        {
            'l': {
                'lane': 'l',
                'label': 'L',
                'entities': [
                    _ent('a', replaced_by=['ghost'], issues=[{'text': 'no grade', 'state': 'open'}]),
                    _ent('a', status='nonsense'),
                    _ent('c', adopted='last tuesday'),
                    _ent('d', issues=[_iss('fixed by nobody', state='solved')]),
                ],
            }
        }
    )
    bad = ' | '.join(lin.validate())
    assert 'duplicate id' in bad
    assert "unknown id 'ghost'" in bad
    assert 'no evidence named' in bad
    assert 'nonsense' in bad
    assert 'not an ISO date' in bad
    assert 'neither a fix date nor a fixer' in bad


def test_data_version_moves_only_when_the_store_moves(fake):
    body = {'lane': 'l', 'label': 'L', 'entities': [_ent('a', issues=[_iss('x')])]}
    fake({'l': body})
    first = lin.build(fresh=True)['data_version']
    assert lin.build(fresh=True)['data_version'] == first
    body['entities'].append(_ent('b'))
    fake({'l': body})
    assert lin.build(fresh=True)['data_version'] != first


def test_section_ignores_the_day_range(payload):
    """A lineage is everything up to now, so ?days= must not change the answer."""
    a = lin.section_stack_lineage(days=7, fresh=True)
    b = lin.section_stack_lineage(days=0, fresh=True)
    assert a['data_version'] == b['data_version'] == payload['data_version']
