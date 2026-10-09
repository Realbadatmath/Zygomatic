#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""check_seal_hooks.py — assert that a delivery function still seals what it writes.

    python3 scripts/check_seal_hooks.py FILE FUNC [FUNC...]

A content credential that is wired once and silently dropped in a refactor is worse than
none at all: the deliverable looks the same and the claim is gone. This parses *FILE* with
``ast`` and requires each named function to call the seal somewhere in its body —

    provenance_seal.seal(...) / _seal.seal(...) / _seal.seal_derived(...)   (hook sites)
    seal(...) / seal_derived(...) / _seal(...)                              (inside the module itself)

Prints one ``OK file:func`` or ``MISSING file:func`` line per function and exits 1 if any
function is missing its call or does not exist in the file at all. Nested definitions are
searched, so a hook inside a closure counts.

Since 2026-10-06 a module may have become a package: when *FILE* does not exist but the
same path without its suffix is a directory, every ``*.py`` directly inside it is parsed
and the functions are looked up across all of them. The printed name stays *FILE*'s own
basename, so a split is invisible to the caller.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: The attribute names a seal call can carry, and the module aliases it hangs off.
SEAL_ATTRS = frozenset({'seal', 'seal_derived'})
SEAL_MODULES = frozenset({'provenance_seal', '_seal'})
#: Direct calls, for provenance_seal.py's own functions delegating to the shared body.
SEAL_NAMES = frozenset({'seal', 'seal_derived', '_seal'})


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    """Every function in the module by name, nested definitions included."""
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, node)
    return found


def _is_seal_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in SEAL_ATTRS and isinstance(func.value, ast.Name) and func.value.id in SEAL_MODULES
    return isinstance(func, ast.Name) and func.id in SEAL_NAMES


def seals(func: ast.AST) -> bool:
    """True when *func* calls the seal anywhere inside it."""
    return any(_is_seal_call(node) for node in ast.walk(func))


def _sources(path: Path) -> list[Path]:
    """The files to parse for *path* — itself, or the package it has become."""
    package = path.with_suffix('')
    if not path.exists() and package.is_dir():
        return sorted(p for p in package.glob('*.py'))
    return [path]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    path = Path(argv[0])
    functions: dict[str, list[ast.AST]] = {}
    for source in _sources(path):
        try:
            tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
        except (OSError, SyntaxError) as exc:
            print(f'cannot parse {source}: {exc}', file=sys.stderr)
            return 1
        for name, func in _functions(tree).items():
            functions.setdefault(name, []).append(func)
    missing = 0
    for name in argv[1:]:
        found = functions.get(name)
        if not found:
            print(f'MISSING {path.name}:{name} (no such function)')
            missing += 1
        elif any(seals(func) for func in found):
            print(f'OK {path.name}:{name}')
        else:
            print(f'MISSING {path.name}:{name}')
            missing += 1
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
