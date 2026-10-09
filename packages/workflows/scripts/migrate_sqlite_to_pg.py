#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Copy the three live SQLite stores into Postgres, idempotently.

WHAT: reads `data/runtime/run_ledger.sqlite3` (stages, fallbacks, gates),
`data/runtime/identity_bank.sqlite3` (chars, checks) and
`data/runtime/scholarly_essays.db` (essays) and inserts every row into the
Postgres tables of the same name, preserving `id`. `ON CONFLICT (id) DO NOTHING`
makes a second run a no-op, so this can be run while the old SQLite writers are
still live and again after they stop.

WHY: on 2026-10-02 the run ledger, the identity bank and the scholarly essay
store moved off per-file SQLite databases onto one Postgres 16 instance. The
schema is owned by Alembic (`alembic/`, revision 0001) — this script only moves
rows, it never creates or alters a table.

Not copied: `data/content_index.db` and `data/existing_clips.db`. Both hold 0
rows, so there is nothing to migrate and they have no Postgres target.

Run it with the venv interpreter, which has psycopg:

    cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
    ../.venv/bin/python scripts/migrate_sqlite_to_pg.py
    ../.venv/bin/python scripts/migrate_sqlite_to_pg.py --verify
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

from zyg_workflows import paths

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import pgdb  # noqa: E402

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(CREWS, 'data', 'runtime')
_VENV_PY = str(paths.ZYG_CREWS_ROOT.parent / '.venv' / 'bin' / 'python')

# (sqlite path relative to the crews directory, table names in copy order).
# Tables are listed parent-first so a future foreign key cannot be violated.
SOURCES: list[tuple[str, tuple[str, ...]]] = [
    (os.path.join(RUNTIME, 'run_ledger.sqlite3'), ('stages', 'fallbacks', 'gates')),
    (os.path.join(RUNTIME, 'identity_bank.sqlite3'), ('chars', 'checks')),
    (os.path.join(RUNTIME, 'scholarly_essays.db'), ('essays',)),
]

BATCH = 500

_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _ident(name: str) -> str:
    """Return *name* quoted for use as a table or column identifier.

    A table or column name cannot travel as a bound parameter, so it has to be interpolated
    into the statement text. Every name that reaches here comes either from the SOURCES
    constant above or from the sqlite/Postgres catalog of the database being copied — never
    from a caller or an argument — and this check makes that structural rather than assumed:
    anything that is not a bare word is refused instead of quoted. Row VALUES, which can be
    arbitrary, always travel as %s placeholders.
    """
    if not _IDENT_RE.match(name):
        raise ValueError(f'refusing to use {name!r} as a SQL identifier')
    return f'"{name}"'


def open_ro(path: str) -> sqlite3.Connection:
    """Open a SQLite file read-only (WAL content is still read through)."""
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def sqlite_columns(sc: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in sc.execute(f'PRAGMA table_info("{table}")')]


def pg_columns(pc, table: str) -> dict[str, str]:
    """Target column name -> information_schema data_type, in table order."""
    with pc.cursor() as cur:
        cur.execute(
            'SELECT column_name, data_type FROM information_schema.columns '
            "WHERE table_schema='public' AND table_name=%s "
            'ORDER BY ordinal_position',
            (table,),
        )
        return {name: dtype for name, dtype in cur.fetchall()}


class Coercions:
    """Counts values a target type could not accept, so they became NULL."""

    def __init__(self) -> None:
        self.n = 0

    def failed(self) -> None:
        self.n += 1


def coerce(value, dtype: str, tally: Coercions):
    """Coerce one SQLite value to the TARGET column's type.

    SQLite affinity is advisory: an INTEGER column can hold `'n/a'`, and a REAL
    column can hold `''`. Postgres will not take those, so a value the target
    type cannot represent becomes NULL and is counted.
    """
    if value is None:
        return None
    if dtype in ('integer', 'bigint', 'smallint'):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            tally.failed()
            return None
    if dtype in ('double precision', 'real', 'numeric'):
        try:
            return float(value)
        except (TypeError, ValueError):
            tally.failed()
            return None
    if dtype == 'bytea':
        try:
            return bytes(value)
        except (TypeError, ValueError):
            tally.failed()
            return None
    return str(value)


def read_table(sc: sqlite3.Connection, table: str, cols: list[str], dtypes: dict[str, str]):
    """Every source row as a coerced tuple, in `cols` order."""
    tally = Coercions()
    quoted = ', '.join(_ident(c) for c in cols)
    out = [
        tuple(coerce(v, dtypes[c], tally) for c, v in zip(cols, row))
        for row in sc.execute(f'SELECT {quoted} FROM {_ident(table)}')  # noqa: S608  identifiers via _ident()
    ]
    return out, tally.n


def pg_count(pc, table: str) -> int:
    with pc.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM {_ident(table)}')  # noqa: S608  identifier via _ident()
        return cur.fetchone()[0]


def pg_ids(pc, table: str) -> set:
    with pc.cursor() as cur:
        cur.execute(f'SELECT id FROM {_ident(table)}')  # noqa: S608  identifier via _ident()
        return {r[0] for r in cur.fetchall()}


def reset_sequence(pc, table: str) -> None:
    """Point the id sequence past the highest copied id."""
    # The sequence name travels as a %s value; only the table name is interpolated, via _ident().
    sql = (
        "SELECT setval(pg_get_serial_sequence(%s, 'id'), "  # noqa: S608  identifier via _ident()
        f'GREATEST((SELECT COALESCE(MAX(id), 0) FROM {_ident(table)}), 1), true)'
    )
    with pc.cursor() as cur:
        cur.execute(sql, (table,))


ROW_FMT = '{:<12} {:>12} {:>12} {:>12} {:>12} {:>12}'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            'Copy the live SQLite stores (run ledger, identity bank, scholarly '
            'essays) into Postgres, preserving ids. Idempotent: a second run '
            'inserts 0 rows.'
        ),
        epilog=(f'Run it with the venv interpreter, which has psycopg: {_VENV_PY} scripts/migrate_sqlite_to_pg.py'),
    )
    ap.add_argument('--dsn', default=None, help='target DSN (default: pgdb.dsn())')
    ap.add_argument(
        '--source-suffix',
        default='',
        help='appended to every SQLite path, e.g. .pre-postgres-20261002',
    )
    ap.add_argument('--verify', action='store_true', help='compare only, zero writes')
    ap.add_argument('--dry-run', action='store_true', help='read and coerce, report, zero writes')
    args = ap.parse_args(argv)

    dsn = args.dsn or pgdb.dsn()
    pc = pgdb.raw_connect(dsn)
    try:
        if args.verify:
            return verify(pc, args.source_suffix)
        return migrate(pc, args.source_suffix, args.dry_run)
    finally:
        pc.close()


def migrate(pc, suffix: str, dry_run: bool) -> int:
    print(('DRY RUN — ' if dry_run else '') + f'target {pc.info.dbname}')
    print(ROW_FMT.format('table', 'sqlite_rows', 'pg_before', 'inserted', 'pg_after', 'coercions'))
    print('-' * 78)
    for path, tables in SOURCES:
        path += suffix
        if not os.path.exists(path):
            print(f'MISSING {path} — skipped')
            continue
        sc = open_ro(path)
        try:
            for table in tables:
                dtypes = pg_columns(pc, table)
                if not dtypes:
                    print(f'{table:<12} no such Postgres table — skipped')
                    continue
                src = sqlite_columns(sc, table)
                cols = [c for c in dtypes if c in src]
                for missing in [c for c in src if c not in dtypes]:
                    print(f'WARNING {table}.{missing} has no target column — dropped')
                rows, coercions = read_table(sc, table, cols, dtypes)
                before = pg_count(pc, table)
                if not dry_run and rows:
                    quoted = ', '.join(_ident(c) for c in cols)
                    marks = ', '.join(['%s'] * len(cols))
                    # Identifiers via _ident(); every row value travels as one of the %s marks.
                    insert = f'INSERT INTO {_ident(table)} ({quoted})'  # noqa: S608  identifiers via _ident()
                    sql = f'{insert} VALUES ({marks}) ON CONFLICT (id) DO NOTHING'
                    with pc.cursor() as cur:
                        for i in range(0, len(rows), BATCH):
                            cur.executemany(sql, rows[i : i + BATCH])
                    pc.commit()
                after = pg_count(pc, table)
                inserted = after - before
                if not dry_run:
                    reset_sequence(pc, table)
                    pc.commit()
                print(ROW_FMT.format(table, len(rows), before, inserted, after, coercions))
        finally:
            sc.close()
    return 0


def verify(pc, suffix: str) -> int:
    print(f'VERIFY against {pc.info.dbname} (zero writes)')
    bad = 0
    for path, tables in SOURCES:
        path += suffix
        if not os.path.exists(path):
            print(f'MISSING {path} — cannot verify')
            bad += 1
            continue
        sc = open_ro(path)
        try:
            for table in tables:
                sql = f'SELECT id FROM {_ident(table)}'  # noqa: S608  identifier via _ident()
                src_ids = {r[0] for r in sc.execute(sql)}
                dst_ids = pg_ids(pc, table)
                missing = src_ids - dst_ids
                ok = len(dst_ids) >= len(src_ids) and not missing
                detail = f'sqlite={len(src_ids)} pg={len(dst_ids)}'
                if missing:
                    sample = sorted(missing)[:5]
                    detail += f' missing_ids={len(missing)} e.g. {sample}'
                print(f'{"OK" if ok else "MISMATCH":<9} {table:<12} {detail}')
                if not ok:
                    bad += 1
        finally:
            sc.close()
    print(f'FAIL — {bad} mismatch' if bad else 'ALL OK')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
