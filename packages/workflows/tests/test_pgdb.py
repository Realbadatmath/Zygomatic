# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pgdb smoke tests — run against zygomatic_test, never production.

Every case here opens a real connection and writes real rows, so the whole module is
``service``: it wants a PostgreSQL cluster up and a ``zygomatic_test`` database in it,
and ``scripts/run_tests.sh`` leaves it out of the portable suite for that reason.

The DSN is pinned here, before pgdb is imported, because pgdb reads the environment
lazily and its DEFAULT_DSN names the PRODUCTION database — a mistyped fixture must not
be able to reach it. It is derived from that default rather than written out, so a
cluster that lives somewhere other than the stock socket is configured in one place
(and $ZYG_PG_DSN, set by conftest or by a CI service container, still wins).
"""

import os

import pytest

from zyg_workflows import pgdb

pytestmark = pytest.mark.service

TEST_DSN = os.environ.get('ZYG_PG_DSN') or pgdb.DEFAULT_DSN.replace('/zygomatic?', '/zygomatic_test?')
assert '/zygomatic_test' in TEST_DSN, 'refusing to run the pgdb suite against %s' % TEST_DSN
os.environ['ZYG_PG_DSN'] = TEST_DSN

import time  # noqa: E402

SELFTEST = 'tools.pgdb_selftest'


def _sql(stmt: str, table: str = SELFTEST) -> str:
    """Fill `{t}` in `stmt` with the fixture's table name.

    A table name cannot travel as a bound parameter, so it is interpolated — but the only
    value that ever reaches here is the module constant SELFTEST (or the fixture that yields
    it), while every test VALUE below goes through a %s placeholder. One interpolation, in
    one place, instead of ten f-strings that read like query building.
    """
    return stmt.replace('{t}', table)


@pytest.fixture
def selftest():
    """An empty `tools.pgdb_selftest` table, dropped again afterwards."""
    pgdb.execute(_sql('CREATE TABLE IF NOT EXISTS {t} (k TEXT PRIMARY KEY, v INT)'))
    pgdb.execute(_sql('DELETE FROM {t}'))
    try:
        yield SELFTEST
    finally:
        pgdb.execute(_sql('DROP TABLE IF EXISTS {t}'))


def test_ping_true():
    assert pgdb.dsn() == TEST_DSN
    assert pgdb.ping() is True


def test_rows_tuples_scalar():
    assert pgdb.rows('select 1 as x') == [{'x': 1}]
    assert pgdb.tuples('select 2') == [(2,)]
    assert pgdb.scalar('select 3') == 3
    assert pgdb.scalar('select 1 where false') is None


def test_execute_roundtrip(selftest):
    assert pgdb.execute(_sql('INSERT INTO {t} (k, v) VALUES (%s, %s)', selftest), ('a', 1)) == 1
    assert pgdb.execute(_sql('UPDATE {t} SET v = %s WHERE k = %s', selftest), (2, 'a')) == 1
    assert pgdb.scalar(_sql('SELECT v FROM {t} WHERE k = %s', selftest), ('a',)) == 2
    assert pgdb.execute(_sql('DELETE FROM {t} WHERE k = %s', selftest), ('a',)) == 1
    assert pgdb.scalar(_sql('SELECT v FROM {t} WHERE k = %s', selftest), ('a',)) is None


def test_raw_connect_commit(selftest):
    conn = pgdb.raw_connect()
    try:
        conn.execute(_sql('INSERT INTO {t} (k, v) VALUES (%s, %s)', selftest), ('raw', 7))
        conn.commit()
    finally:
        conn.close()
    # A different (pooled) connection must see it, so the commit was real.
    assert pgdb.scalar(_sql('SELECT v FROM {t} WHERE k = %s', selftest), ('raw',)) == 7


def test_unreachable_fast():
    bogus = 'postgresql://zygomatic@/nope?host=/nonexistent/dir'
    t0 = time.perf_counter()
    assert pgdb.ping(bogus) is False
    first = time.perf_counter() - t0
    # Bounded by the pool's own open timeout (10 s), which psycopg_pool spends
    # retrying the socket; see the note in the task report.
    assert first < 12.0, first

    t0 = time.perf_counter()
    assert pgdb.ping(bogus) is False
    second = time.perf_counter() - t0
    # The DSN is marked down: no connect attempt at all.
    assert second < 0.05, second

    pgdb._down_until.pop(bogus, None)


def test_connect_rolls_back(selftest):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with pgdb.connect() as c:
            c.execute(_sql('INSERT INTO {t} (k, v) VALUES (%s, %s)', selftest), ('doomed', 1))
            raise Boom
    assert pgdb.scalar(_sql('SELECT v FROM {t} WHERE k = %s', selftest), ('doomed',)) is None
