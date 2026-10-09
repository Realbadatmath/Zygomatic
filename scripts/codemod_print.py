#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""codemod_print — rewrite library `print()` statements as `_zyg_log` calls.

The 2026-10-08 audit found 4,471 `print(` calls in library code beside 2,720 logger calls:
two logging systems in one repository. docs/conventions.md ('Logging') has one rule —
library code logs through `_zyg_log = logging.getLogger(__name__)`, and `print` belongs to
a CLI. This tool does the mechanical half of that migration on a list of files.

What is rewritten: a STATEMENT-level `print(...)` (an `ast.Expr` whose value calls the name
`print`) that is not inside a function named main/_main/cli/run_cli and not inside an
`if __name__ == '__main__':` block.

  print(x)                  ->  _zyg_log.info(x)
  print(f'a {b}')           ->  _zyg_log.info(f'a {b}')
  print('a' % b)            ->  _zyg_log.info('a' % b)        (% and .format stay as they are)
  print('a', b)             ->  _zyg_log.info(' '.join(str(a) for a in ('a', b)))
  print()                   ->  _zyg_log.info('')
  print(x, file=sys.stderr) ->  _zyg_log.warning(x)
  print(x, flush=True)      ->  _zyg_log.info(x)              (flush/end/sep defaults dropped)

What is left alone, and reported with a reason: a `sep` other than ' ' or an `end` other
than '\\n'/'' (the line gets `  # noqa: T201  codemod: custom sep/end` appended, once, only
if it carries no noqa yet), `print(*args)`, `print(**kw)`, a `file=` that is neither
sys.stdout nor sys.stderr, an unknown keyword, and any print whose source span contains a
comment (a multi-line print we cannot move without losing the comment).

When a file gets at least one rewrite and has no top-level `_zyg_log =`, the logger is
inserted after the last top-level import: `_zyg_log = <alias>.getLogger(__name__)`, reusing
an existing `import logging [as _zyg_logging]` or adding `import logging as _zyg_logging`
(the alias 689 modules already use). `__name__` is always the channel, including in the
modules that rebind it — the rebind *is* the channel.

Files on the CLI allowlist (`__main__.py`, `cli.py`, `*_cli.py`, `selftest.py`, `scripts/**`,
`prop_mesh/pufferball_look.py` — the same list the print_calls ratchet exempts) are skipped
whole; `--force` processes them anyway.

Usage:
  codemod_print.py --check FILE...    report what would change, write nothing (default)
  codemod_print.py --apply FILE...    rewrite the files in place

Run `ruff check --fix` and `ruff format` on the touched files afterwards: the codemod
preserves the original argument source verbatim and leaves the layout to the formatter.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

CLI_FUNCS = frozenset({'main', '_main', 'cli', 'run_cli'})
CLI_FILES = (
    '**/__main__.py',
    '**/cli.py',
    '**/*_cli.py',
    '**/selftest.py',
    '**/scripts/**',
    '**/prop_mesh/pufferball_look.py',
)
NOQA_TAIL = '  # noqa: T201  codemod: custom sep/end'
LOGGER_NAME = '_zyg_log'
LOGGING_ALIAS = '_zyg_logging'
STREAMS = frozenset({'stdout', 'stderr'})


# ── source model ─────────────────────────────────────────────────────────────


class Source:
    """A file's text addressed the way `ast` addresses it: 1-based lines, byte columns."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.data = text.encode('utf-8')
        starts = [0]
        for index, byte in enumerate(self.data):
            if byte == 0x0A:
                starts.append(index + 1)
        self.starts = starts

    def offset(self, lineno: int, col: int) -> int:
        """Byte offset of (lineno, col), the pair an AST node carries."""
        return self.starts[lineno - 1] + col

    def span(self, node: ast.AST) -> tuple[int, int]:
        """(start, end) byte offsets of a node's own source."""
        return (
            self.offset(node.lineno, node.col_offset),
            self.offset(node.end_lineno, node.end_col_offset),
        )

    def segment(self, node: ast.AST) -> str:
        start, end = self.span(node)
        return self.data[start:end].decode('utf-8')

    def line(self, lineno: int) -> str:
        start = self.starts[lineno - 1]
        end = self.starts[lineno] if lineno < len(self.starts) else len(self.data)
        return self.data[start:end].decode('utf-8')

    def line_end(self, lineno: int) -> int:
        """Byte offset of the end of a line's text, before its newline."""
        start = self.starts[lineno - 1]
        return start + len(self.line(lineno).rstrip('\r\n').encode('utf-8'))

    def comment_offsets(self) -> list[int]:
        """Byte offset of every comment token, so a print cannot swallow one."""
        out: list[int] = []
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(self.text).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return out
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            row, col = token.start
            byte_col = len(self.line(row)[:col].encode('utf-8'))
            out.append(self.offset(row, byte_col))
        return out


@dataclass
class Edit:
    """A byte-range replacement; edits never overlap and are applied back to front."""

    start: int
    end: int
    text: str


@dataclass
class FileReport:
    path: str
    rewritten: int = 0
    marked: int = 0
    left: list[tuple[int, str]] = field(default_factory=list)
    plan: list[tuple[int, str]] = field(default_factory=list)
    logger_added: bool = False
    skipped: str = ''
    changed: bool = False


# ── where a print is allowed to live ─────────────────────────────────────────


def is_cli_file(path: Path) -> bool:
    """True for the files whose prints are the user interface, not logging."""
    posix = path.as_posix()
    return any(fnmatch.fnmatch(posix, pattern) for pattern in CLI_FILES)


def is_main_guard(test: ast.expr) -> bool:
    """True for `__name__ == '__main__'` and its `in (...)` spelling, either way round."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    sides = [test.left, test.comparators[0]]
    names = {node.id for node in sides if isinstance(node, ast.Name)}
    if '__name__' not in names:
        return False
    if isinstance(test.ops[0], (ast.Eq, ast.Is)):
        return any(isinstance(node, ast.Constant) and node.value == '__main__' for node in sides)
    if isinstance(test.ops[0], ast.In):
        holder = test.comparators[0]
        if isinstance(holder, (ast.Tuple, ast.List, ast.Set)):
            return any(isinstance(item, ast.Constant) and item.value == '__main__' for item in holder.elts)
    return False


def is_print_call(value: ast.expr) -> bool:
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'print'


def collect_prints(tree: ast.Module) -> list[ast.Expr]:
    """Every statement-level print outside a CLI function and outside a `__main__` guard."""
    found: list[ast.Expr] = []

    def body(statements: list[ast.stmt], cli: bool) -> None:
        for statement in statements:
            visit(statement, cli)

    def visit(statement: ast.stmt, cli: bool) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body(statement.body, cli or statement.name in CLI_FUNCS)
            return
        if isinstance(statement, ast.If):
            body(statement.body, cli or is_main_guard(statement.test))
            body(statement.orelse, cli)
            return
        if isinstance(statement, ast.Expr):
            if is_print_call(statement.value) and not cli:
                found.append(statement)
            return
        for field_name in ('body', 'orelse', 'finalbody'):
            nested = getattr(statement, field_name, None)
            if isinstance(nested, list):
                body([node for node in nested if isinstance(node, ast.stmt)], cli)
        for handler in getattr(statement, 'handlers', []):
            body(handler.body, cli)
        for case in getattr(statement, 'cases', []):
            body(case.body, cli)

    body(tree.body, False)
    return found


# ── planning one rewrite ─────────────────────────────────────────────────────


def stream_name(value: ast.expr) -> str:
    """'stdout'/'stderr' for any spelling of the standard streams (`sys.stderr`, `_sys.stderr`)."""
    if isinstance(value, ast.Attribute) and value.attr in STREAMS:
        return value.attr
    if isinstance(value, ast.Name) and value.id in STREAMS:
        return value.id
    return ''


def plan_keywords(source: Source, call: ast.Call) -> tuple[str, str, bool]:
    """(level, reason, custom): the log level the keywords ask for, or why we must not touch it."""
    level = 'info'
    custom = False
    for keyword in call.keywords:
        if keyword.arg is None:
            return level, 'print(**kwargs)', False
        if keyword.arg == 'file':
            stream = stream_name(keyword.value)
            if stream == 'stderr':
                level = 'warning'
            elif stream != 'stdout':
                return level, f'file={source.segment(keyword.value).replace(" ", "")}', False
        elif keyword.arg == 'end':
            if not (isinstance(keyword.value, ast.Constant) and keyword.value.value in ('\n', '')):
                custom = True
        elif keyword.arg == 'sep':
            if not (isinstance(keyword.value, ast.Constant) and keyword.value.value == ' '):
                custom = True
        elif keyword.arg != 'flush':
            return level, f'{keyword.arg}=', False
    return level, '', custom


def plan_payload(source: Source, call: ast.Call) -> tuple[str, str]:
    """(expression, reason): the single expression the logger call receives."""
    if any(isinstance(argument, ast.Starred) for argument in call.args):
        return '', 'print(*args)'
    if not call.args:
        return "''", ''
    if len(call.args) == 1:
        return source.segment(call.args[0]), ''
    joined = ', '.join(source.segment(argument) for argument in call.args)
    return f"' '.join(str(a) for a in ({joined}))", ''


def plan_print(source: Source, statement: ast.Expr, comments: list[int]) -> tuple[Edit | None, str, bool]:
    """(edit, reason, custom): the replacement for one print, or why it stays."""
    call = cast(ast.Call, statement.value)  # collect_prints only yields print() calls
    start, end = source.span(statement)
    if any(start <= position < end for position in comments):
        return None, 'comment inside the print', False
    level, reason, custom = plan_keywords(source, call)
    if reason:
        return None, reason, False
    if custom:
        return None, 'custom sep/end', True
    payload, reason = plan_payload(source, call)
    if reason:
        return None, reason, False
    return Edit(start, end, f'{LOGGER_NAME}.{level}({payload})'), '', False


def noqa_edit(source: Source, statement: ast.Expr) -> Edit | None:
    """Append the T201 marker to a left-alone print, unless its lines already carry a noqa."""
    for lineno in range(statement.lineno, statement.end_lineno + 1):
        if '# noqa' in source.line(lineno):
            return None
    position = source.line_end(statement.end_lineno)
    return Edit(position, position, NOQA_TAIL)


# ── planning the module logger ───────────────────────────────────────────────


def has_logger(tree: ast.Module) -> bool:
    """True when the module already binds `_zyg_log` at the top level."""
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == LOGGER_NAME:
                    return True
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.target.id == LOGGER_NAME:
                return True
        elif isinstance(statement, ast.ImportFrom) and any(
            (alias.asname or alias.name) == LOGGER_NAME for alias in statement.names
        ):
            return True
    return False


def logging_alias(tree: ast.Module) -> str:
    """The name `logging` is bound to at the top level, or '' when it is not imported."""
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == 'logging':
                    return alias.asname or 'logging'
    return ''


def logger_anchor(tree: ast.Module) -> int:
    """The line after which the logger block goes: the last top-level import, else the header."""
    last_import = 0
    for statement in tree.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            last_import = max(last_import, statement.end_lineno)
    if last_import:
        return last_import
    first = tree.body[0] if tree.body else None
    if first is None:
        return 0
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first.end_lineno
    decorators = getattr(first, 'decorator_list', [])
    top = min([first.lineno] + [node.lineno for node in decorators])
    return top - 1


def logger_edit(source: Source, tree: ast.Module) -> Edit | None:
    """The insertion that gives the module its `_zyg_log`, or None when it has one."""
    if has_logger(tree):
        return None
    alias = logging_alias(tree)
    pieces = ['']
    if not alias:
        pieces += [f'import logging as {LOGGING_ALIAS}', '']
    pieces.append(f'{LOGGER_NAME} = {alias or LOGGING_ALIAS}.getLogger(__name__)')
    anchor = logger_anchor(tree)
    position = source.starts[anchor] if anchor < len(source.starts) else len(source.data)
    return Edit(position, position, '\n'.join(pieces) + '\n')


# ── one file ─────────────────────────────────────────────────────────────────


def apply_edits(source: Source, edits: list[Edit]) -> str:
    """Splice every edit into the source, back to front, so offsets stay valid."""
    data = source.data
    for edit in sorted(edits, key=lambda item: item.start, reverse=True):
        data = data[: edit.start] + edit.text.encode('utf-8') + data[edit.end :]
    return data.decode('utf-8')


def plan_file(path: Path, force: bool = False) -> tuple[FileReport, str]:
    """(report, new_text): what the codemod would do to one file."""
    report = FileReport(path=str(path))
    if not force and is_cli_file(path):
        report.skipped = 'CLI allowlist'
        return report, ''
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as problem:
        report.skipped = f'unreadable: {problem}'
        return report, ''
    try:
        tree = ast.parse(text)
    except SyntaxError as problem:
        report.skipped = f'syntax error: {problem}'
        return report, ''
    source = Source(text)
    comments = source.comment_offsets()
    edits: list[Edit] = []
    for statement in collect_prints(tree):
        edit, reason, custom = plan_print(source, statement, comments)
        if edit is not None:
            edits.append(edit)
            report.rewritten += 1
            report.plan.append((statement.lineno, edit.text.splitlines()[0]))
            continue
        report.left.append((statement.lineno, reason))
        if custom:
            marker = noqa_edit(source, statement)
            if marker is not None:
                edits.append(marker)
                report.marked += 1
    if report.rewritten:
        logger = logger_edit(source, tree)
        if logger is not None:
            edits.append(logger)
            report.logger_added = True
    if not edits:
        return report, ''
    report.changed = True
    return report, apply_edits(source, edits)


def describe(report: FileReport) -> None:
    """One block per file on stdout: the per-file summary the migration is steered by."""
    if report.skipped:
        print(f'{report.path}: skipped ({report.skipped})')
        return
    if not report.changed and not report.left:
        print(f'{report.path}: nothing to do')
        return
    logger = ', logger added' if report.logger_added else ''
    marks = f', marked {report.marked}' if report.marked else ''
    print(f'{report.path}: rewritten {report.rewritten}, left {len(report.left)}{marks}{logger}')
    for lineno, replacement in report.plan:
        print(f'  {lineno}: -> {replacement}')
    for lineno, reason in report.left:
        print(f'  {lineno}: left ({reason})')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='codemod_print.py',
        description='Rewrite statement-level print() in library code as _zyg_log calls.',
    )
    parser.add_argument('files', nargs='+', type=Path, help='the .py files to rewrite')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='report what would change, write nothing (default)')
    mode.add_argument('--apply', action='store_true', help='rewrite the files in place')
    parser.add_argument('--force', action='store_true', help='process CLI-allowlisted files too')
    args = parser.parse_args(argv)

    totals = {'files': 0, 'rewritten': 0, 'left': 0, 'marked': 0, 'loggers': 0}
    for path in args.files:
        report, new_text = plan_file(path, force=args.force)
        describe(report)
        totals['rewritten'] += report.rewritten
        totals['left'] += len(report.left)
        totals['marked'] += report.marked
        totals['loggers'] += int(report.logger_added)
        if not report.changed:
            continue
        totals['files'] += 1
        if args.apply:
            path.write_text(new_text, encoding='utf-8')
    verb = 'rewrote' if args.apply else 'would rewrite'
    print(
        f'{verb} {totals["rewritten"]} print statements in {totals["files"]} files; '
        f'left {totals["left"]} ({totals["marked"]} marked with a noqa), '
        f'added {totals["loggers"]} loggers'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
