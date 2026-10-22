# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pgdb — the one Postgres seam for the crews code.

WHAT: a pooled psycopg 3 connection factory plus four query helpers
(`rows`, `tuples`, `scalar`, `execute`) that every crews module uses instead of
opening its own connection. One `ConnectionPool` per DSN, kept for the life of
the process, so a hot caller pays no connect handshake.

WHY: on 2026-10-02 the run ledger, the identity bank, the scholarly essay store
and the tools indexes moved off per-file SQLite databases onto a single
Postgres 16 instance. SQLite gave one writer at a time and a lock storm whenever
the dashboard read while a pipeline wrote; Postgres gives real concurrency, and
one DSN replaces a handful of file paths.

WHERE: the server, its socket, the DSNs and the psql recipes are documented in
$ZYG_HOME/pg16/README_ZYG.md.

RULE: the schema is owned by `alembic/` in this directory. Modules never
CREATE TABLE / ALTER TABLE / CREATE INDEX — they add an Alembic revision and run
`../.venv/bin/python -m zyg_workflows.alembic upgrade head`.

Placeholders are psycopg's `%s`, never SQLite's `?`.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

import psycopg
import psycopg.rows
import psycopg_pool
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


DEFAULT_DSN = f'postgresql://zygomatic@/zygomatic?host={paths.ZYG_HOME / "pg16" / "run"}'

# How long to stay in "server is down" mode after a failed pool open. A dead
# server must cost a caller microseconds, not a fresh 10 s connect timeout on
# every call.
_DOWN_FOR_S = 15.0

# `_lock` guards the three dicts below and nothing else: it is never held across
# a pool open, which can take up to 10 s when the server is gone.
_lock = threading.Lock()
_pools: dict[str, psycopg_pool.ConnectionPool] = {}
_down_until: dict[str, float] = {}
# One lock per DSN, held only while that DSN's pool is being opened, so two
# threads racing for the same pool serialise while callers of other DSNs — and
# callers of an already-open pool — are never blocked.
_opening: dict[str, threading.Lock] = {}


class PgUnavailable(RuntimeError):
    """The Postgres server could not be reached."""


def dsn() -> str:
    """The DSN to use: $ZYG_PG_DSN when set, else the production database."""
    return os.environ.get('ZYG_PG_DSN') or DEFAULT_DSN


# Internal alias: the helpers below all take a `dsn=None` argument, which shadows
# the function above inside their bodies.
_dsn = dsn


def _check_down(dsn: str) -> None:
    """Fast-fail a DSN whose last open failed less than `_DOWN_FOR_S` ago."""
    if _down_until.get(dsn, 0.0) > time.time():
        raise PgUnavailable(f'Postgres unreachable at {dsn}: marked down')


def get_pool(dsn: str) -> psycopg_pool.ConnectionPool:
    """The process-wide pool for `dsn`, opened on first use.

    An already-open pool costs one dict look-up under `_lock`, and a DSN marked
    down costs the same — never a connect attempt. The open itself happens
    outside `_lock` under that DSN's own lock.
    """
    with _lock:
        pool = _pools.get(dsn)
        if pool is not None:
            return pool
        _check_down(dsn)
        opening = _opening.setdefault(dsn, threading.Lock())

    with opening:
        # A thread that was ahead of us may have opened the pool, or marked the
        # DSN down, while we waited for `opening`.
        with _lock:
            pool = _pools.get(dsn)
            if pool is not None:
                return pool
            _check_down(dsn)
        pool = psycopg_pool.ConnectionPool(
            dsn,
            min_size=1,
            max_size=6,
            open=False,
            check=psycopg_pool.ConnectionPool.check_connection,
            name='zyg-' + str(abs(hash(dsn)))[:6],
        )
        try:
            pool.open(wait=True, timeout=10)
        except Exception as e:
            with _lock:
                _down_until[dsn] = time.time() + _DOWN_FOR_S
            try:
                pool.close()
            except Exception as _exc:
                _zyg_log.debug('pool close after a failed connect skipped: %s', _exc)
            raise PgUnavailable(f'Postgres unreachable at {dsn}: {e}') from e
        with _lock:
            _pools[dsn] = pool
            _down_until.pop(dsn, None)
        return pool


def close_all() -> None:
    """Close and forget every pool, and clear the down-markers.

    For tests and for a clean process shutdown; the next call to `get_pool`
    opens a fresh pool.
    """
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
        _down_until.clear()
        _opening.clear()
    for pool in pools:
        try:
            pool.close()
        except Exception as _exc:
            _zyg_log.debug('pool close skipped: %s', _exc)


@contextmanager
def connect(dsn: str | None = None):
    """A pooled connection with tuple rows.

    Commits on a clean exit, rolls back on an exception, and returns the
    connection to the pool either way. Never call `.close()` on it.
    """
    with get_pool(dsn or _dsn()).connection() as conn:
        yield conn


def rows(sql: str, params=(), dsn: str | None = None) -> list[dict]:
    """Every row as a dict."""
    with connect(dsn) as c, c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def tuples(sql: str, params=(), dsn: str | None = None) -> list[tuple]:
    """Every row as a tuple."""
    with connect(dsn) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def scalar(sql: str, params=(), dsn: str | None = None):
    """First column of the first row, or None when there is no row."""
    r = tuples(sql, params, dsn)
    return r[0][0] if r else None


def execute(sql: str, params=(), dsn: str | None = None) -> int:
    """Run a statement and return its rowcount. Committed on return."""
    with connect(dsn) as c:
        cur = c.execute(sql, params)
        return cur.rowcount


def raw_connect(dsn: str | None = None) -> psycopg.Connection:
    """An UNPOOLED connection with tuple rows.

    For low-frequency callers that drive their own cursors and must
    `.commit()` / `.close()` themselves.
    """
    return psycopg.connect(dsn or _dsn())


def ping(dsn: str | None = None) -> bool:
    """True when the server answers `select 1`."""
    try:
        return scalar('select 1', (), dsn) == 1
    except Exception:
        return False


if __name__ == '__main__':  # the CLI lives in pgdb_cli
    from zyg_workflows.pgdb_cli import main as _cli_main

    raise SystemExit(_cli_main())
