# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""func_len.py FILE [MAX] — print every function longer than MAX lines (default 300); exit 1 if any.

Used as a verify command by the refactoring tasks: `func_len.py src/x.py 300`.
"""

import ast
import sys


def main() -> int:
    path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    long_ones = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = node.end_lineno - node.lineno + 1
            if n > limit:
                long_ones.append((n, node.name, node.lineno))
    for n, name, line in sorted(long_ones, reverse=True):
        print(f'{n:6d}  {name}  (line {line})')
    return 1 if long_ones else 0


if __name__ == '__main__':
    sys.exit(main())
