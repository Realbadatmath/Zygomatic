#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""path_parity.py — prove that a refactor left every path-valued constant alone.

The 2026-10 package splits left 240 ``__file__ = …`` / ``__name__ = …`` rebinds behind: each
one makes a moved module claim the identity of the single file it came from, so that every
``__file__``-derived constant and every ``getLogger(__name__)`` channel keeps its old value.
Deleting a rebind is only safe if nothing observable moves with it, and "nothing observable"
is exactly what this tool pins down.

Usage::

    # before the change
    path_parity.py dump --modules zyg_workflows.paths,zyg_dashboard.paths --out base.json
    # after the change
    path_parity.py dump --modules zyg_workflows.paths,zyg_dashboard.paths --out cur.json
    path_parity.py compare base.json cur.json          # exit 0 and 'PARITY …', or exit 1

What a dump records, per module:

* every module-level attribute whose value is a ``str`` or :class:`os.PathLike` containing
  ``/`` — the path constants, under their own name;
* for a Flask application object: its ``root_path``, ``static_folder`` and
  ``template_folder``, under ``<attr>.root_path`` and friends, because those three are
  derived from the importing module's ``__name__`` and never look like paths themselves;
* ``cls.__module__`` for every class defined in the module (``__qualname__`` without a dot),
  under ``<attr>.__module__`` — a ``__name__`` rebind renames all of them;
* ``__import_error__`` when the module does not import, so a refactor that breaks an import
  is a difference rather than a crash.

The dunders are recorded too: ``__file__`` is a path constant like any other, and a dump that
hides the very value a rebind forged would be proving nothing. A removed rebind therefore
shows up as a difference on purpose — read it, then re-dump the base with the rebind gone if
the new value is the intended one.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

#: Dashboard modules that may only be imported after the package that registers the
#: blueprint registry — the blueprint contract. Importing ``zyg_dashboard.bp_safety`` on its
#: own raises; importing ``zyg_dashboard.crewai_web_gui`` first makes it work.
_PRELUDE: dict[str, tuple[str, ...]] = {
    'zyg_dashboard.crewai_web_gui': ('zyg_dashboard.crewai_web_gui',),
    'zyg_dashboard.bp_': ('zyg_dashboard.crewai_web_gui',),
    'zyg_dashboard.gui.': ('zyg_dashboard.crewai_web_gui',),
}

#: The three Flask attributes a module's ``__name__`` decides.
_FLASK_ATTRS = ('root_path', 'static_folder', 'template_folder')

_IMPORT_ERROR = '__import_error__'


def _prelude_for(module: str) -> tuple[str, ...]:
    """Return the modules that must be imported before *module*, longest prefix first."""
    for prefix in sorted(_PRELUDE, key=len, reverse=True):
        if module == prefix.rstrip('.') or module.startswith(prefix):
            return _PRELUDE[prefix]
    return ()


def _as_path_str(value: Any) -> str | None:
    """Return *value* as a path string when it looks like a path, else ``None``.

    "Looks like a path" is: a ``str`` or an :class:`os.PathLike` whose text contains ``/``.
    A bare name (``'static'``) is not a path; an absolute or relative one always is.
    """
    if isinstance(value, str):
        text = value
    elif isinstance(value, os.PathLike):
        try:
            text = os.fspath(value)
        except TypeError:
            return None
        if not isinstance(text, str):
            text = text.decode('utf-8', 'replace')
    else:
        return None
    return text if '/' in text else None


def _is_flask_app(value: Any) -> bool:
    """Return True for an object carrying Flask's three ``__name__``-derived attributes."""
    return not isinstance(value, type) and all(hasattr(value, name) for name in _FLASK_ATTRS)


def _is_own_class(value: Any) -> bool:
    """Return True for a class defined at the top level of some module (no dotted qualname)."""
    return isinstance(value, type) and '.' not in getattr(value, '__qualname__', '.')


def _scan(mod: Any) -> dict[str, str]:
    """Return every path-valued, Flask-derived and class-``__module__`` value in *mod*.

    An attribute that cannot even be looked at is skipped: a module that imports Flask's
    ``request``/``session`` holds a werkzeug ``LocalProxy``, and every attribute access on
    one outside a request context raises :class:`RuntimeError`. None of those is a path.
    """
    values: dict[str, str] = {}
    for name, value in sorted(vars(mod).items()):
        # suppress: an attribute that raises when it is read is never a path constant.
        with contextlib.suppress(Exception):
            path = _as_path_str(value)
            if path is not None:
                values[name] = path
            elif _is_own_class(value):
                values[f'{name}.__module__'] = str(value.__module__)
            elif _is_flask_app(value):
                for attr in _FLASK_ATTRS:
                    values[f'{name}.{attr}'] = repr(getattr(value, attr))
    return values


def dump(modules: list[str], out: Path) -> dict[str, dict[str, str]]:
    """Import each module in *modules*, scan it, and write the result as JSON to *out*."""
    recorded: dict[str, dict[str, str]] = {}
    for module in modules:
        for prelude in _prelude_for(module):
            if prelude != module:
                try:
                    importlib.import_module(prelude)
                except Exception as exc:  # noqa: BLE001 - the real import reports it below
                    print(f'prelude {prelude} failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        try:
            mod = importlib.import_module(module)
        # A broken import is data, not a crash: SystemExit from a module body included.
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            recorded[module] = {_IMPORT_ERROR: f'{type(exc).__name__}: {exc}'}
            continue
        recorded[module] = _scan(mod)
    payload = {'modules': recorded}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return recorded


def _load(path: Path) -> dict[str, dict[str, str]]:
    """Read a dump written by :func:`dump` and return its ``modules`` mapping."""
    data = json.loads(path.read_text(encoding='utf-8'))
    modules = data.get('modules')
    if not isinstance(modules, dict):
        raise SystemExit(f'{path}: not a path_parity dump (no "modules" object)')
    return modules


def _skipped(attr: str, ignore_dunders: bool, ignore_classes: bool) -> bool:
    """True when *attr* is a key the caller asked compare to leave out of the diff."""
    if ignore_dunders and attr.startswith('__') and attr.endswith('__'):
        return True  # the forged __file__/__cached__ a deleted rebind legitimately restores
    if ignore_dunders and attr.rsplit('.', 1)[-1] in ('ORIGINAL_FILE', '_ORIGINAL_FILE'):
        return True  # the private alias of a deleted _origin.py; removed with the rebinds
    return ignore_classes and attr.endswith('.__module__')


def compare(
    base: dict[str, dict[str, str]],
    cur: dict[str, dict[str, str]],
    only: list[str] | None,
    ignore_dunders: bool = False,
    ignore_classes: bool = False,
) -> list[str]:
    """Return one ``module.attr: old → new`` line per difference between *base* and *cur*.

    ``ignore_dunders`` drops ``__file__``-style keys (a removed ``__file__ = …`` rebind changes
    them by design); ``ignore_classes`` drops the ``<Class>.__module__`` entries (a removed
    ``__name__ = …`` rebind moves them to the real submodule, which the package re-exports).
    Every other value — the data paths, Flask folders, logger channels — must still match.
    """
    names = set(base) | set(cur)
    if only:
        names &= set(only)
    lines: list[str] = []
    for module in sorted(names):
        before = base.get(module)
        after = cur.get(module)
        if before is None or after is None:
            side = 'BASE' if before is None else 'CUR'
            lines.append(f'{module}: missing from {side}')
            continue
        for attr in sorted(set(before) | set(after)):
            if _skipped(attr, ignore_dunders, ignore_classes):
                continue
            old = before.get(attr, '<absent>')
            new = after.get(attr, '<absent>')
            if old != new:
                lines.append(f'{module}.{attr}: {old} \u2192 {new}')
    return lines


def _count(modules: dict[str, dict[str, str]], only: list[str] | None) -> tuple[int, int]:
    """Return ``(modules, values)`` counted over *modules*, restricted to *only*."""
    selected = {k: v for k, v in modules.items() if not only or k in set(only)}
    return len(selected), sum(len(v) for v in selected.values())


def _modules_arg(raw: str) -> list[str]:
    """Split a comma-separated ``--modules`` value into dotted names."""
    names = [part.strip() for part in raw.split(',') if part.strip()]
    if not names:
        raise argparse.ArgumentTypeError('no module names given')
    return names


def main(argv: list[str] | None = None) -> int:
    """Run ``dump`` or ``compare`` and return the process exit code."""
    parser = argparse.ArgumentParser(prog='path_parity.py', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('dump', help='import modules and record their path-valued attributes')
    d.add_argument('--modules', required=True, type=_modules_arg, help='comma-separated dotted module names')
    d.add_argument('--out', required=True, type=Path, help='where to write the JSON dump')

    c = sub.add_parser('compare', help='diff two dumps; exit 1 on any difference')
    c.add_argument('base', type=Path, help='the dump taken before the change')
    c.add_argument('cur', type=Path, help='the dump taken after the change')
    c.add_argument('--modules', type=_modules_arg, default=None, help='compare only these modules')
    c.add_argument(
        '--ignore-dunders',
        action='store_true',
        help='skip __file__-style keys (a removed __file__ rebind changes them by design)',
    )
    c.add_argument(
        '--ignore-classes',
        action='store_true',
        help='skip <Class>.__module__ keys (a removed __name__ rebind moves them to the real submodule)',
    )

    args = parser.parse_args(argv)

    if args.cmd == 'dump':
        recorded = dump(args.modules, args.out)
        n_mod, n_val = _count(recorded, None)
        broken = sorted(m for m, v in recorded.items() if _IMPORT_ERROR in v)
        print(f'DUMP {n_mod} modules, {n_val} values -> {args.out}')
        for module in broken:
            print(f'  import error: {module}: {recorded[module][_IMPORT_ERROR]}', file=sys.stderr)
        return 0

    base = _load(args.base)
    cur = _load(args.cur)
    lines = compare(base, cur, args.modules, args.ignore_dunders, args.ignore_classes)
    if lines:
        for line in lines:
            print(line)
        print(f'DIFFERENT {len(lines)} values differ')
        return 1
    n_mod, n_val = _count(cur, args.modules)
    print(f'PARITY {n_mod} modules, {n_val} values')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
