#!/usr/bin/env python3
"""Gate for the `_run_scholarly_pipeline` split: no stage lost a name.

The split moves statements out of an 11k-line function into
`zyg_workflows.scholarly.stages_*`. The failure mode of such a move is not a
syntax error — it is a name that used to be a local of the monolith and is now
nothing at all, which only shows up when that branch runs, minutes into a GPU
job. Three checks, all static:

1. every name a stage function (or a `def`/`lambda` nested in one) reads as a
   global must be a module-level binding of its stage module, a builtin, or a
   module dunder — a leftover monolith local fails here;
2. every `ctx.<name>` the stage modules touch must be a declared field of
   `RunContext`, and a field that is read somewhere must be written somewhere;
3. the same global check for what is left of `_run_scholarly_pipeline` itself,
   so a name the move took away from the stages still inline is caught too.

Exit 0 and one `OK` line per check, or exit 1 with the offending name, the file
and the line.

Other splits
------------
Nothing above is scholarly-specific, so every name it hard-wired is an option
whose default is the scholarly value — a bare run is still the original gate.
Point the three checks at another split by naming its parts:

    python3 scripts/check_free_names.py --stage-dir src/zyg_workflows/storyteller \
        --monolith src/zyg_workflows/pipeline_storyteller.py \
        --func _run_storyteller_pipeline
"""

from __future__ import annotations

import argparse
import ast
import builtins
import os
import symtable
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, 'src', 'zyg_workflows')
STAGE_DIR = os.path.join(PKG, 'scholarly')
CONTEXT = os.path.join(STAGE_DIR, 'context.py')
MONOLITH = os.path.join(PKG, 'pipeline_scholarly.py')
MONOLITH_FUNC = '_run_scholarly_pipeline'
STAGE_GLOB = 'stages_'
STAGE_PREFIX = 'stage_'
CONTEXT_CLASS = 'RunContext'
CTX_VAR = 'ctx'

DUNDERS = {'__file__', '__name__', '__doc__', '__package__', '__spec__', '__loader__', '__builtins__'}
ALWAYS_OK = set(dir(builtins)) | DUNDERS


@dataclass(frozen=True)
class Split:
    """Which split the three checks run against — the scholarly one by default."""

    stage_dir: str = STAGE_DIR
    stage_glob: str = STAGE_GLOB
    context: str = CONTEXT
    context_class: str = CONTEXT_CLASS
    monolith: str = MONOLITH
    func: str = MONOLITH_FUNC
    ctx_var: str = CTX_VAR
    stage_prefix: str = STAGE_PREFIX


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _module_bindings(src, path):
    """Names bound at module level (assignments, imports, defs, classes)."""
    table = symtable.symtable(src, path, 'exec')
    return {s.get_name() for s in table.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}


def _blocks(block, path_name=''):
    """Yield (qualified_name, block) for `block` and every block below it."""
    name = f'{path_name}/{block.get_name()}' if path_name else block.get_name()
    yield name, block
    for child in block.get_children():
        yield from _blocks(child, name)


def _global_reads(table, select):
    """[(qualname, name, lineno)] for every global read under a selected top block."""
    out = []
    for top in table.get_children():
        if not select(top.get_name()):
            continue
        for qual, block in _blocks(top):
            for sym in block.get_symbols():
                if sym.is_global() and sym.is_referenced():
                    out.append((qual, sym.get_name(), block.get_lineno()))
    return out


def _context_fields(split):
    tree = ast.parse(_read(split.context), split.context)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == split.context_class:
            return {s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    raise SystemExit(f'{split.context}: class {split.context_class} not found')


def _ctx_attrs(src, path, ctx_var, within=''):
    """[(name, lineno, is_store)] for every `<ctx_var>.<name>` in the file.

    `within` narrows the walk to one function, which the monolith needs: `ctx`
    is the `RunContext` only inside `_run_scholarly_pipeline`, while elsewhere
    in the module it is an ordinary local (`_bare_context` builds a word list
    called `ctx`), and `ctx.append` is not a field of anything.
    """
    root = ast.parse(src, path)
    if within:
        root = next(
            (n for n in ast.walk(root) if isinstance(n, ast.FunctionDef) and n.name == within),
            None,
        )
        if root is None:
            raise SystemExit(f'{path}: def {within} not found')
    out = []
    for node in ast.walk(root):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == ctx_var:
            out.append((node.attr, node.lineno, isinstance(node.ctx, ast.Store)))
    return out


def _stage_modules(split):
    """Every stage module file: the flat `<stage_glob>*.py` and, for a stage module
    that became a package, every `*.py` directly inside the `<stage_glob>*/` directory."""
    out = []
    for n in os.listdir(split.stage_dir):
        if not n.startswith(split.stage_glob):
            continue
        path = os.path.join(split.stage_dir, n)
        if n.endswith('.py') and os.path.isfile(path):
            out.append(path)
        elif os.path.isdir(path):
            out += [
                os.path.join(path, sub)
                for sub in os.listdir(path)
                if sub.endswith('.py') and os.path.isfile(os.path.join(path, sub))
            ]
    return sorted(out)


def _defines(path, func):
    """True when *path* parses and holds a `def <func>` anywhere in it."""
    try:
        tree = ast.parse(_read(path), path)
    except (OSError, SyntaxError):
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name == func for n in ast.walk(tree))


def _monolith_path(path, func):
    """*path*, or — when the monolith has become a package — the module inside it
    that defines *func*. The same Pattern-A fallback `check_seal_hooks.py` makes,
    so `--monolith .../pipeline_scholarly.py` keeps naming the monolith after a
    later split turned that file into `pipeline_scholarly/`."""
    if os.path.exists(path):
        return path
    package = path[:-3] if path.endswith('.py') else path
    if os.path.isdir(package):
        for name in sorted(os.listdir(package)):
            if name.endswith('.py') and _defines(os.path.join(package, name), func):
                return os.path.join(package, name)
        raise SystemExit(f'{package}/: no module in the package defines def {func}')
    raise SystemExit(f'{path}: no such file, and no package of that name either')


def _ctor_keywords(split, monolith):
    """The keywords of the `<context_class>(...)` call in the monolith."""
    for node in ast.walk(ast.parse(_read(monolith), monolith)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == split.context_class:
            return node.keywords
    return []


def _resolve(path):
    """A relative path is relative to ROOT (the `packages/workflows` directory)."""
    return os.path.abspath(os.path.join(ROOT, path))


def _parse_args(argv):
    """The `Split` the command line asks for; every option defaults to scholarly."""
    parser = argparse.ArgumentParser(
        prog='check_free_names.py',
        description='Static gate for a monolith->stages split: no stage lost a name.',
    )
    parser.add_argument('--stage-dir', default=STAGE_DIR, help='directory holding the stage modules')
    parser.add_argument('--stage-glob', default=STAGE_GLOB, help="stage module filename prefix (default 'stages_')")
    parser.add_argument('--context', default=None, help='the context dataclass module (default <stage-dir>/context.py)')
    parser.add_argument('--context-class', default=CONTEXT_CLASS, help='name of the context dataclass')
    parser.add_argument('--monolith', default=MONOLITH, help='the file the stages were cut out of')
    parser.add_argument('--func', default=MONOLITH_FUNC, help='the function in the monolith the stages came from')
    parser.add_argument('--ctx-var', default=CTX_VAR, help='variable name whose attributes are the context fields')
    parser.add_argument('--stage-prefix', default=STAGE_PREFIX, help='function-name prefix marking a stage function')
    args = parser.parse_args(argv)

    stage_dir = _resolve(args.stage_dir)
    return Split(
        stage_dir=stage_dir,
        stage_glob=args.stage_glob,
        context=_resolve(args.context) if args.context else os.path.join(stage_dir, 'context.py'),
        context_class=args.context_class,
        monolith=_resolve(args.monolith),
        func=args.func,
        ctx_var=args.ctx_var,
        stage_prefix=args.stage_prefix,
    )


def main(argv=None):
    split = _parse_args(sys.argv[1:] if argv is None else argv)
    failures = []
    stage_files = _stage_modules(split)
    if not stage_files:
        print(f'FAIL no {split.stage_glob}*.py in {split.stage_dir}')
        return 1

    fields = _context_fields(split)
    read_fields, written_fields = set(), set()
    n_stages = 0

    for path in stage_files:
        src = _read(path)
        bound = _module_bindings(src, path) | ALWAYS_OK
        table = symtable.symtable(src, path, 'exec')
        n_stages += sum(1 for c in table.get_children() if c.get_name().startswith(split.stage_prefix))
        for qual, name, lineno in _global_reads(table, lambda n: n.startswith(split.stage_prefix)):
            if name not in bound:
                failures.append(f'{path}:{lineno}: {qual} reads undefined global {name!r}')
        for name, lineno, is_store in _ctx_attrs(src, path, split.ctx_var):
            if name not in fields:
                failures.append(f'{path}:{lineno}: {split.ctx_var}.{name} is not a {split.context_class} field')
            (written_fields if is_store else read_fields).add(name)

    if not n_stages:
        failures.append(f'no {split.stage_prefix}* functions found in the stage modules')
    print(f'{"OK  " if not failures else "FAIL"} {n_stages} stage functions in {len(stage_files)} module(s)')

    monolith = _monolith_path(split.monolith, split.func)
    mono_src = _read(monolith)

    # The monolith is a writer of the context too, not just its constructor:
    # every block of it that is not a stage yet hands its own locals over to
    # the stages below it (`ctx._flux_image_meta = _flux_image_meta`), and
    # publishes a nested helper a later stage calls. Those stores are what
    # makes the fields of a still-inline block non-orphans.
    for name, lineno, is_store in _ctx_attrs(mono_src, monolith, split.ctx_var, within=split.func):
        if name not in fields:
            failures.append(f'{monolith}:{lineno}: {split.ctx_var}.{name} is not a {split.context_class} field')
        (written_fields if is_store else read_fields).add(name)

    # A field read but never written is a crossing the move failed to carry.
    # (Fields the monolith's prologue fills are written at the RunContext call,
    # which this check sees through the keyword names below.)
    ctor = {kw.arg for kw in _ctor_keywords(split, monolith)}
    orphans = sorted(read_fields - written_fields - ctor)
    for name in orphans:
        failures.append(
            f'{split.context}: {split.ctx_var}.{name} is read but never written '
            f'nor passed to {split.context_class}(...)'
        )
    print(f'{"OK  " if not orphans else "FAIL"} {len(read_fields)} ctx fields read, all written or constructed')

    mono_bound = _module_bindings(mono_src, monolith) | ALWAYS_OK
    mono_table = symtable.symtable(mono_src, monolith, 'exec')
    mono_fail = 0
    for qual, name, lineno in _global_reads(mono_table, lambda n: n == split.func):
        if name not in mono_bound:
            failures.append(f'{monolith}:{lineno}: {qual} reads undefined global {name!r}')
            mono_fail += 1
    print(f'{"OK  " if not mono_fail else "FAIL"} {split.func} resolves every global it reads')

    for line in failures:
        print(f'FAIL {line}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
