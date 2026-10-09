#!/usr/bin/env python3
"""Line-range surgery helper for splitting `_run_scholarly_pipeline`.

The scholarly monolith (`src/zyg_workflows/pipeline_scholarly.py`) is one
11k-line function whose body is a single `try:` block carrying `# ── Stage N …`
comment markers.  Splitting it into `zyg_workflows.scholarly.stages_*` is a
pure move: identical statements, identical order, locals that cross a stage
boundary promoted to fields of one `RunContext`.

This tool does the mechanical parts of that move so every task in the chain
cuts the same way:

    markers    list the top-level stage markers with their statement ranges
    names      report, for a line range, which names cross in / cross out
    emit       emit a range as a whole `def stage_nn_slug(ctx):` verbatim
    cut        emit a range as a dedented body with `n` → `ctx.n`
    verify     prove an extracted stage is AST-equal to the committed original

Canonical stage numbering: the markers printed by `markers` (which are the
only ranges that are a flat statement sequence and therefore extractable) in
file order, 1-based.  `markers` is the single source of truth — never count
marker comments by hand, nested ones inside loops are not stage boundaries.

Prefer `emit` over `cut`.  `cut` dedents the range by a fixed column count,
which also eats the indentation *inside* triple-quoted strings and so changes
what the code does; `emit` keeps every line at its original column and makes
the stage function's body indent 8 instead, so the move cannot touch a string
literal (`ruff format` normalises the indent afterwards).

Two crossings the `names` report cannot see, because they are not `Name`
nodes — grep the range for them by hand before trusting the report:
  * `locals()` / `vars()` / `eval` lookups of a local by string (there is one:
    `locals().get('_selected_essay_id')` in Stage 3, fed by Stage 2);
  * `__file__`, which in a stage module resolves to the stage module, not to
    `pipeline_scholarly.py` — rewrite those to an explicit package constant.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import symtable
import sys
import textwrap

MARKER_RE = re.compile(r'^(?P<indent> *)# ─+ *(?P<title>Stage [^─]*?) *─*$')
FUNC = '_run_scholarly_pipeline'


def _load(path):
    src = open(path, encoding='utf-8').read()
    return src, src.splitlines(keepends=True)


def _monolith(src, func=FUNC):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return node
    raise SystemExit(f'function {func} not found')


def _body_try(fn):
    """The single `try:` that holds every stage of the monolith."""
    tries = [s for s in fn.body if isinstance(s, ast.Try)]
    return max(tries, key=lambda s: s.end_lineno - s.lineno)


def find_markers(path, func=FUNC):
    """Return [(no, marker_lineno, title, first_stmt_lineno, end_lineno)].

    A marker counts when it sits at the indentation of the stage `try:` body
    and is followed by a statement of that body.  The range of stage *i* runs
    from its own marker line to the line before the marker of stage *i+1*
    (the last stage ends at the last statement of the try body).
    """
    src, lines = _load(path)
    fn = _monolith(src, func)
    block = _body_try(fn)
    stmts = block.body
    indent = ' ' * (stmts[0].col_offset)
    starts = {s.lineno: s for s in stmts}
    hits = []
    for i, raw in enumerate(lines, start=1):
        if not (block.lineno < i < block.body[-1].end_lineno):
            continue
        m = MARKER_RE.match(raw.rstrip('\n'))
        if not m or m.group('indent') != indent:
            continue
        nxt = next((ln for ln in sorted(starts) if ln > i), None)
        if nxt is None:
            continue
        hits.append((i, m.group('title').strip(), nxt))
    out = []
    for n, (mline, title, first) in enumerate(hits, start=1):
        end = hits[n][0] - 1 if n < len(hits) else stmts[-1].end_lineno
        out.append((n, mline, title, first, end))
    return out


def _range_stmts(path, start, end, func=FUNC):
    src, _ = _load(path)
    fn = _monolith(src, func)
    block = _body_try(fn)
    return [s for s in block.body if start <= s.lineno <= end], block, src


def _as_load(node):
    """A copy of an assignment target seen as a read (for `x += 1`)."""
    clone = ast.Name(id=node.id, ctx=ast.Load()) if isinstance(node, ast.Name) else node
    return ast.copy_location(clone, node) if isinstance(node, ast.Name) else node


_SCOPE = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _bindings(scope_node):
    """Names bound directly in `scope_node`'s own scope."""
    out = set()
    if isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope_node.args
        for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
            if arg is not None:
                out.add(arg.arg)
    for gen in getattr(scope_node, 'generators', []):
        for sub in ast.walk(gen.target):
            if isinstance(sub, ast.Name):
                out.add(sub.id)

    def body_of(node):
        if isinstance(node, ast.Lambda):
            return [node.body]
        if isinstance(node, _SCOPE[4:]):
            return [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        return list(node.body)

    stack = list(body_of(scope_node))
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(node.name)
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        stack.extend(ast.iter_child_nodes(node))
    return out


def occurrences(nodes):
    """Yield (name, kind, lineno, col) for every use seen from the *enclosing
    function's own* scope.

    `kind` is 'store' or 'load'.  A name that belongs to a nested scope (a
    nested `def`, a `lambda`, a comprehension target) is not reported at all;
    a load inside a nested scope that is *free* there is reported as a load,
    because the nested scope closes over the enclosing function to get it.
    """
    out = []

    def children(node):
        """`ast.iter_child_nodes` reordered into Python's evaluation order.

        The default field order of the binding statements puts the target
        before the value, which would make `x = x + 1` or `x += 1` look like a
        fresh binding instead of a read followed by one.
        """
        if isinstance(node, ast.Assign):
            return [node.value, *node.targets]
        if isinstance(node, ast.AnnAssign):
            return [c for c in (node.annotation, node.value, node.target) if c is not None]
        if isinstance(node, ast.AugAssign):
            return [_as_load(node.target), node.value, node.target]
        if isinstance(node, (ast.For, ast.AsyncFor)):
            return [node.iter, node.target, *node.body, *node.orelse]
        if isinstance(node, ast.NamedExpr):
            return [node.value, node.target]
        return list(ast.iter_child_nodes(node))

    def walk(node, depth, bound):
        for child in children(node):
            if isinstance(child, _SCOPE):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if depth == 0:
                        out.append((child.name, 'store', child.lineno, child.col_offset))
                    for deco in child.decorator_list:
                        walk(ast.Expr(value=deco), depth, bound)
                walk(child, depth + 1, bound | _bindings(child))
                continue
            if isinstance(child, ast.Name):
                if isinstance(child.ctx, (ast.Store, ast.Del)):
                    if depth == 0:
                        out.append((child.id, 'store', child.lineno, child.col_offset))
                elif child.id not in bound:
                    out.append((child.id, 'load', child.lineno, child.col_offset))
            elif isinstance(child, ast.ExceptHandler) and child.name and depth == 0:
                out.append((child.name, 'store', child.lineno, child.col_offset))
            elif isinstance(child, (ast.Import, ast.ImportFrom)) and depth == 0:
                for alias in child.names:
                    bound_name = (alias.asname or alias.name).split('.')[0]
                    out.append((bound_name, 'store', child.lineno, child.col_offset))
            elif isinstance(child, (ast.Global, ast.Nonlocal)) and depth == 0:
                for name in child.names:
                    out.append((name, 'store', child.lineno, child.col_offset))
            walk(child, depth, bound)

    for top in nodes:
        walk(ast.Module(body=[top], type_ignores=[]), 0, frozenset())
    return out


def _names(nodes):
    uses = occurrences(nodes)
    return (
        {n for n, k, _, _ in uses if k == 'load'},
        {n for n, k, _, _ in uses if k == 'store'},
    )


def _first_use(nodes, names):
    """For each name, the kind ('load'/'store') of its first occurrence."""
    seen: dict[str, str] = {}
    for name, kind, _, _ in occurrences(nodes):
        if name in names and name not in seen:
            seen[name] = kind
    return seen


def _module_scope_names(src):
    """Module-level bindings (globals) of the monolith's file."""
    tree = ast.parse(src)
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add((alias.asname or alias.name).split('.')[0])
        else:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    out.add(sub.id)
    return out


def report_names(path, start, end, func=FUNC):
    """Which locals cross into the range, and which cross out of it."""
    picked, block, src = _range_stmts(path, start, end, func)
    if not picked:
        raise SystemExit('empty range')
    before = [s for s in block.body if s.end_lineno < picked[0].lineno]
    after = [s for s in block.body if s.lineno > picked[-1].end_lineno]
    fn = _monolith(src, func)
    prologue = [s for s in fn.body if s.end_lineno < block.lineno]
    handlers = list(block.handlers) + list(block.finalbody) + list(block.orelse)

    in_loaded, in_stored = _names(picked)
    _, pre_stored = _names(prologue + before)
    post_loaded, _ = _names(after + handlers)
    args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    globals_ = _module_scope_names(src)
    builtins_ = set(dir(__builtins__ if isinstance(__builtins__, dict) else __builtins__))

    first_after = _first_use(after, in_stored)
    first_in_handlers = _first_use(handlers, in_stored)
    crossing_out = sorted(
        n for n in in_stored & post_loaded if first_after.get(n) == 'load' or first_in_handlers.get(n) == 'load'
    )
    crossing_in = sorted((in_loaded & (pre_stored | args)) - in_stored)
    reassigned_in = sorted(
        n for n in in_loaded & in_stored & (pre_stored | args) if _first_use(picked, {n}).get(n) == 'load'
    )
    local_only = sorted(in_stored - set(crossing_out))
    unknown = sorted(in_loaded - in_stored - pre_stored - args - globals_ - builtins_)
    return {
        'crossing_in': crossing_in,
        'reassigned_in': reassigned_in,
        'crossing_out': crossing_out,
        'local_only': local_only,
        'unknown': unknown,
        'ctx_fields': sorted(set(crossing_in) | set(reassigned_in) | set(crossing_out)),
    }


def _nested_locals(src_block):
    """Names that are local to some nested scope of `src_block` (do not rewrite)."""
    table = symtable.symtable(src_block, '<range>', 'exec')
    out = set()

    def walk(tbl, top):
        for child in tbl.get_children():
            if not top:
                pass
            for sym in child.get_symbols():
                if sym.is_parameter() or sym.is_assigned():
                    out.add(sym.get_name())
            walk(child, False)

    walk(table, True)
    return out


def cut(path, start, end, ctx_names, indent_from=8, ctx='ctx'):
    """Return the range dedented to a function body with `n` → `ctx.n`."""
    _, lines = _load(path)
    chunk = lines[start - 1 : end]
    dedented = []
    for raw in chunk:
        if raw.strip() and not raw.startswith(' ' * indent_from):
            raise SystemExit(f'line {start + len(dedented)} is outside the block indent')
        dedented.append(raw[indent_from:] if raw.strip() else raw.lstrip(' '))
    body = ''.join(dedented)
    return rewrite(body, ctx_names, ctx=ctx)


def emit(
    path,
    start,
    end,
    name,
    ctx_names,
    inserts=(),
    ctx='ctx',
    subs=(),
    in_names=(),
    out_names=(),
    guarded_in=(),
):
    """Return a whole `def name(ctx):` holding lines `start..end` verbatim.

    No line is re-indented, so no triple-quoted string changes; the function's
    body indent is simply the block indent the lines already have (8 in the
    monolith).  `ruff format` normalises that to 4 afterwards.

    `inserts` is a sequence of (after_lineno, text) — used to publish a nested
    `def` a later stage needs, e.g. `(3453, 'ctx._tag_sentence = _tag_sentence')`.
    `subs` is a sequence of (from_lineno, to_lineno, new_text) span rewrites,
    applied before the `ctx.` pass, for the crossings `rewrite` cannot see
    (`locals()` lookups by string, `__file__`).  Spans shift the line numbers
    of `inserts`, so pass `inserts` targets that sit before every sub, or none.

    `in_names` / `out_names` generate the glue of the *plain-local* style of
    move, which leaves the body byte-identical instead of rewriting names:

        def stage(ctx):
            job = ctx.job            # in_names  — what crosses in
            <the range, verbatim>
            ctx.out = out            # out_names — what crosses out

    Prefer it to `ctx_names` whenever the range holds nested `def`s: `rewrite`
    cannot touch a free name inside a nested scope (a closure cannot capture an
    attribute), so a `ctx.`-rewritten range with closures is half-rewritten.
    `verify` drops both glue forms, so the comparison still works.
    `guarded_in` is for an in-crossing whose local may legitimately be
    *unbound* because a reader catches `NameError`; it emits
    `if ctx.n is not UNSET: n = ctx.n` and needs `UNSET` in the stage module.
    """
    _, lines = _load(path)
    chunk = list(lines[start - 1 : end])
    for first, last, text in sorted(subs, reverse=True):
        chunk[first - start : last - start + 1] = [text]
    body = rewrite('if True:\n' + ''.join(chunk), ctx_names, ctx=ctx)
    out = body.splitlines(keepends=True)[1:]
    for lineno, text in sorted(inserts, reverse=True):
        indent = ' ' * (len(out[0]) - len(out[0].lstrip(' ')))
        out.insert(lineno - start + 1, f'{indent}{text}\n')
    pad = ' ' * (len(out[0]) - len(out[0].lstrip(' ')))
    head = [f'{pad}{n} = {ctx}.{n}\n' for n in in_names]
    head += [f'{pad}if {ctx}.{n} is not UNSET:\n{pad}    {n} = {ctx}.{n}\n' for n in guarded_in]
    tail = [f'{pad}{ctx}.{n} = {n}\n' for n in out_names]
    return f'def {name}({ctx}):\n' + ''.join(head) + ''.join(out) + ''.join(tail)


def rewrite(body, ctx_names, ctx='ctx'):
    """Replace free `Name` occurrences of `ctx_names` with `ctx.<name>`.

    Uses `ast` positions, so attribute accesses (`x.name`), keyword-argument
    labels (`f(name=1)`) and string contents are never touched.  Names that a
    nested scope inside the body owns are left alone and reported on stderr.
    """
    ctx_names = set(ctx_names)
    if not ctx_names:
        # Nothing to rewrite — and the plain-local style (`emit`'s in_names /
        # out_names) always comes here with an empty set. Returning early also
        # avoids `symtable` below, which refuses a range holding a `nonlocal`
        # because the `if True:` wrapper `emit` parses it under is module level.
        return body
    tree = ast.parse(body)
    shadowed = _nested_locals(body) & ctx_names
    if shadowed:
        print(f'[cut] shadowed in a nested scope, NOT rewritten: {sorted(shadowed)}', file=sys.stderr)
    targets = ctx_names - shadowed

    nested = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            for sub in ast.walk(node):
                if sub is not node:
                    nested.add(id(sub))

    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in targets and id(node) not in nested:
            edits.append((node.lineno, node.col_offset, node.end_col_offset, node.id))
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and targets & set(node.names):
            print(f'[cut] global/nonlocal names collide with ctx: {node.names}', file=sys.stderr)

    lines = body.splitlines(keepends=True)
    for lineno, col, end_col, name in sorted(edits, key=lambda e: (-e[0], -e[1])):
        # `col_offset` counts UTF-8 *bytes*, not characters, and these lines are
        # full of emoji and em-dashes — slicing the str by it corrupts the line.
        raw = lines[lineno - 1].encode('utf-8')
        lines[lineno - 1] = (raw[:col] + f'{ctx}.{name}'.encode('utf-8') + raw[end_col:]).decode('utf-8')
    return ''.join(lines)


class _Normalise(ast.NodeTransformer):
    """Undo, in a copy of the tree, exactly the edits a pure move may make.

    `ctx.n` → `n`, the `n = ctx.n` / `ctx.n = n` glue dropped, and docstrings
    dedented (the move changes the block indent, and `ruff format` re-indents
    a docstring with it). What survives is comparable to the original.
    """

    def __init__(self, extra=()):
        self.extra = dict(extra)
        self.dropped = []

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == 'ctx':
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        replacement = self.extra.get(ast.unparse(node))
        return ast.copy_location(ast.parse(replacement, mode='eval').body, node) if replacement else node

    def visit_Name(self, node):
        replacement = self.extra.get(node.id)
        return ast.copy_location(ast.parse(replacement, mode='eval').body, node) if replacement else node

    def visit_Assign(self, node):
        self.generic_visit(node)
        t = node.targets
        if len(t) == 1 and isinstance(t[0], ast.Name) and isinstance(node.value, ast.Name) and t[0].id == node.value.id:
            self.dropped.append(t[0].id)
            return None
        return node

    def _dedent_doc(self, node):
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            head, sep, rest = first.value.value.partition('\n')
            first.value.value = head + sep + textwrap.dedent(rest)
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        return self._dedent_doc(node)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def verify(path, start, end, module, name, ref='HEAD', func=FUNC, extra=()):
    """True if `module`'s `name` is a pure move of `path` lines `start..end`.

    The original is read from git (`ref`), so the comparison still works after
    the range has been cut out of the working tree. `extra` is a mapping of
    unparsed-expression (or bare name) → replacement source, for the crossings
    that are not `ctx.` rewrites — pass it what you passed `emit`'s `subs`,
    e.g. `{'_PKG_DIR': 'os.path.dirname(__file__)'}`.
    """
    rel = os.path.relpath(os.path.abspath(path), _git_root(path))
    old_src = subprocess.run(
        ['git', '-C', _git_root(path), 'show', f'{ref}:{rel}'], capture_output=True, text=True, check=True
    ).stdout
    old_fn = _monolith(old_src, func)
    old_body = [s for s in _body_try(old_fn).body if start <= s.lineno <= end]
    new_src, _ = _load(module)
    new_fn = next((n for n in ast.parse(new_src).body if getattr(n, 'name', '') == name), None)
    if new_fn is None:
        raise SystemExit(f'{module}: function {name} not found')

    def norm(nodes):
        tr = _Normalise(extra)
        mod = tr.visit(ast.parse(ast.unparse(ast.Module(body=list(nodes), type_ignores=[]))))
        return ast.dump(ast.fix_missing_locations(mod), include_attributes=False), tr.dropped

    a, _ = norm(old_body)
    b, dropped = norm(new_fn.body)
    return a == b, len(old_body), dropped


def _git_root(path):
    return subprocess.run(
        ['git', '-C', os.path.dirname(os.path.abspath(path)), 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('file')
    common.add_argument('--func', default=FUNC)

    sub.add_parser('markers', parents=[common])

    p_names = sub.add_parser('names', parents=[common])
    p_names.add_argument('--start', type=int, required=True)
    p_names.add_argument('--end', type=int, required=True)

    p_emit = sub.add_parser('emit', parents=[common])
    p_emit.add_argument('--start', type=int, required=True)
    p_emit.add_argument('--end', type=int, required=True)
    p_emit.add_argument('--name', required=True)
    p_emit.add_argument('--ctx-names', default='', help='comma-separated, or @file with one name per line')
    p_emit.add_argument('--in-names', default='', help='glue `n = ctx.n` at the top of the stage')
    p_emit.add_argument('--out-names', default='', help='glue `ctx.n = n` at the bottom of the stage')
    p_emit.add_argument('--guarded-in-names', default='', help='glue `if ctx.n is not UNSET: n = ctx.n`')

    p_verify = sub.add_parser('verify', parents=[common])
    p_verify.add_argument('--start', type=int, required=True)
    p_verify.add_argument('--end', type=int, required=True)
    p_verify.add_argument('--module', required=True, help='the stage module the range was moved into')
    p_verify.add_argument('--name', required=True)
    p_verify.add_argument('--ref', default='HEAD')
    p_verify.add_argument(
        '--extra',
        action='append',
        default=[],
        metavar='EXPR=SOURCE',
        help='non-ctx rewrite to undo, e.g. _PKG_DIR=os.path.dirname(__file__)',
    )

    p_cut = sub.add_parser('cut', parents=[common])
    p_cut.add_argument('--start', type=int, required=True)
    p_cut.add_argument('--end', type=int, required=True)
    p_cut.add_argument('--ctx-names', required=True, help='comma-separated, or @file with one name per line')
    p_cut.add_argument('--indent', type=int, default=8)

    args = ap.parse_args(argv)

    if args.cmd == 'markers':
        for no, mline, title, first, end in find_markers(args.file, args.func):
            print(f'{no:3d}  marker@{mline:<6d} stmts {first}-{end}  ({end - first + 1:5d} lines)  {title}')
        return 0

    if args.cmd == 'names':
        rep = report_names(args.file, args.start, args.end, args.func)
        for key in ('crossing_in', 'reassigned_in', 'crossing_out', 'local_only', 'unknown', 'ctx_fields'):
            print(f'# {key} ({len(rep[key])})')
            for name in rep[key]:
                print(f'  {name}')
        return 0

    def _ctx_names(spec):
        raw = open(spec[1:], encoding='utf-8').read().split() if spec.startswith('@') else spec.split(',')
        return [n for n in raw if n]

    if args.cmd == 'emit':
        sys.stdout.write(
            emit(
                args.file,
                args.start,
                args.end,
                args.name,
                _ctx_names(args.ctx_names),
                in_names=_ctx_names(args.in_names),
                out_names=_ctx_names(args.out_names),
                guarded_in=_ctx_names(args.guarded_in_names),
            )
        )
        return 0

    if args.cmd == 'verify':
        extra = dict(e.split('=', 1) for e in args.extra)
        ok, n, dropped = verify(
            args.file, args.start, args.end, args.module, args.name, ref=args.ref, func=args.func, extra=extra
        )
        print(
            f'{"EQUAL  " if ok else "DIFFER "} {args.name}  '
            f'({n} statements, lines {args.start}-{args.end}, glue dropped: {sorted(set(dropped)) or "none"})'
        )
        return 0 if ok else 1

    if args.cmd == 'cut':
        sys.stdout.write(cut(args.file, args.start, args.end, _ctx_names(args.ctx_names), indent_from=args.indent))
        return 0

    return 1


if __name__ == '__main__':
    raise SystemExit(main())
