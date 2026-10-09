# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Static parity proof for an arch_assistant_ext split: every top-level name the
original module bound must still be bound by the new package's __init__.py.

The two paths below are this task's (blender_power); a later extension split
copies this file and edits them.
"""

import ast
import os
import subprocess
import sys

p = 'packages/workflows/src/zyg_workflows/arch_assistant_ext/blender_power.py'
root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel']).decode().strip()


def show(ref):
    return subprocess.run(['git', 'show', f'{ref}:{p}'], cwd=root, capture_output=True, text=True)


r = show('HEAD')
if r.returncode != 0:
    h = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', p], cwd=root).decode().strip()
    r = show(h + '^')
assert r.returncode == 0, 'original not found in git'
old = ast.parse(r.stdout)


def bound(tree):
    s = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            s.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                s.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        s.add(x.id)
    return s


new = ast.parse(
    open(os.path.join(root, 'packages/workflows/src/zyg_workflows/arch_assistant_ext/blender_power/__init__.py')).read()
)
missing = sorted(bound(old) - bound(new) - {'annotations'})
print('original top-level names:', len(bound(old)), 'missing in package __init__:', missing or 'none')
sys.exit(1 if missing else 0)
