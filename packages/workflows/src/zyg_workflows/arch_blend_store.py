# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_blend_store — the retention rule for data/architecture/blender (2026-09-17).

Every headless build writes a ~2 GB .blend and NOTHING ever reads one back: the
only reuse was `Drawing._bp_blend`, an in-memory tuple scoped to a single
request.  So a second tool call on an unchanged drawing paid for a whole rebuild,
and the folder kept every one of them.  On 2026-09-16 that was 481 builds across
85 document signatures — one signature alone holding 65 rebuilds at 1.96 GB.
Deleting them is an audit, and the audit had to be repeated the same day.  This
module is the rule that stops them being written.

Two halves, and the first is what actually fixes it:

  reuse   `find_clean(sig)` hands back a .blend already built from this exact
          document, so the second, third and fortieth call on an unchanged
          drawing cost no Blender at all.  A pass that SAVES into a .blend
          (`blender_run`) calls `mark_dirty` and that file is never offered
          again — the parametric drawing is the source of truth, and a .blend
          carrying bpy edits is no longer a build of it.

  sweep   `sweep()` runs after every write.  The newest build per signature
          survives, anything inside the grace window survives (it may be open in
          a second Blender right now), and a byte cap trims what is left,
          oldest first.

Everything is read from the environment at CALL time, so the ceilings can be
retuned without restarting the assistant:

  ZYG_ARCH_BLEND_CAP_GB       24    total .blend bytes kept
  ZYG_ARCH_BLEND_GRACE_MIN   120    never touch a file younger than this
  ZYG_ARCH_BLEND_KEEP_SIG      1    builds kept per document signature
  ZYG_ARCH_BLEND_SCRATCH_DAYS  7    age limit for _pass/_script/view scratch
  ZYG_ARCH_BLEND_REUSE         1    0 disables cross-request reuse

Sidecars are left alone on purpose: `.glb` is the GUI viewer's hand-off and the
`.json` is the document that built it — together 33 MB against 114 GB of .blend.
Only `.blend`, `.blend1` and the `.dirty` marker are ever deleted here.

stdlib only, and nothing here imports arch_assistant — blender_power imports
FROM arch_assistant, so a back-import would close the circle.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
BLEND_DIR = os.path.join(HERE, 'data', 'architecture', 'blender')
BUILDER = os.path.join(HERE, 'arch_blender_build', '__main__.py')

# `<slug>-<YYYYmmdd-HHMMSS>-<sha1(doc)[:12]>.blend`.  The older
# `arch_assistant.start_blender` naming has no signature field and the offline
# ray traces end in `-ray`; both fail this match on purpose and are then each
# their own group, which the cap prunes by age instead of by signature.
_NAME = re.compile(r'^(?P<slug>.+)-(?P<stamp>\d{8}-\d{6})-(?P<sig>[0-9a-f]{12})\.blend$')

_SCRATCH = (('_pass-', '.py'), ('_script-', '.py'), ('view-', '.png'))


def _env_int(name, dflt, lo, hi):
    try:
        v = int(os.environ.get(name) or dflt)
    except (TypeError, ValueError):
        return int(dflt)
    return max(lo, min(hi, v))


def cap_bytes():
    return _env_int('ZYG_ARCH_BLEND_CAP_GB', 24, 1, 1024) * (1 << 30)


def grace_s():
    return _env_int('ZYG_ARCH_BLEND_GRACE_MIN', 120, 1, 10080) * 60


def keep_per_sig():
    return _env_int('ZYG_ARCH_BLEND_KEEP_SIG', 1, 1, 50)


_STAMP = {}


def builder_stamp():
    """A token that changes when arch_blender_build.py changes.

    Folded into the document signature by the caller: the document is only half
    of what a .blend is made of, and reusing a build from before a builder edit
    would hand back geometry the current code would not produce.

    It hashes the CONTENT, not the mtime.  A touch, a chmod or a checkout that
    restores the same bytes would otherwise throw every stored build away for
    nothing, and at ~2 GB a build that is an expensive way to be wrong.  The
    hash is memoised against (mtime, size), so the file is read once per edit.
    """
    try:
        st = os.stat(BUILDER)
    except OSError:
        return '0'
    key = (int(st.st_mtime), st.st_size)
    if _STAMP.get('k') == key:
        return _STAMP['v']
    try:
        with open(BUILDER, 'rb') as fh:
            v = hashlib.sha1(fh.read(), usedforsecurity=False).hexdigest()[:12]
    except OSError:
        return '0'
    _STAMP['k'], _STAMP['v'] = key, v
    return v


def _dirty_path(blend):
    return blend[:-6] + '.dirty' if blend.endswith('.blend') else blend + '.dirty'


def mark_dirty(blend):
    """Record that a pass saved into this .blend, so it is never reused.

    Called after `save=True` — from then on the file is a Blender edit, not a
    build of the drawing, and `find_clean` must step over it.
    """
    try:
        with open(_dirty_path(blend), 'w', encoding='utf-8') as fh:
            fh.write(time.strftime('%Y-%m-%d %H:%M:%S') + '\n')
    except OSError as _exc:
        _zyg_log.warning('dirty marker write failed for %s — the file may be reused as clean: %s', blend, _exc)


def find_clean(sig):
    """The newest unmutated .blend already built from `sig`, or '' for none."""
    if not _env_int('ZYG_ARCH_BLEND_REUSE', 1, 0, 1):
        return ''
    best, best_mt = '', -1.0
    try:
        names = os.listdir(BLEND_DIR)
    except OSError:
        return ''
    for f in names:
        m = _NAME.match(f)
        if not m or m.group('sig') != sig:
            continue
        p = os.path.join(BLEND_DIR, f)
        if os.path.exists(_dirty_path(p)):
            continue
        try:
            mt = os.stat(p).st_mtime
        except OSError as _exc:
            _zyg_log.debug('blend stat skipped: %s', _exc)
            continue
        if mt > best_mt:
            best, best_mt = p, mt
    return best


def in_use():
    """Every .blend a running process has on its command line.

    The grace window already covers the ordinary case — a build takes minutes and
    a pass reads the file it just built — but this closes the gap for real: a
    second Blender opening an hours-old .blend (`blender -b <blend> --python`)
    would otherwise be racing the sweep.  Reading /proc is cheap beside a build,
    and a kernel without /proc simply falls back to the grace window.
    """
    out = set()
    try:
        pids = [d for d in os.listdir('/proc') if d.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            with open('/proc/%s/cmdline' % pid, 'rb') as fh:
                args = fh.read().split(b'\0')
        except (OSError, IOError) as _exc:
            _zyg_log.debug('proc cmdline read skipped for pid %s: %s', pid, _exc)
            continue
        for a in args:
            if a.endswith(b'.blend'):
                try:
                    out.add(os.path.abspath(a.decode('utf-8', 'replace')))
                except Exception as _exc:
                    _zyg_log.debug('blend path decode skipped: %s', _exc)
    return out


def _unlink(path):
    try:
        os.unlink(path)
        return True
    except OSError:
        return False


def sweep(protect=()):
    """Apply the retention rule to BLEND_DIR.  Returns (files, bytes_freed).

    Never raises: this runs on the back of a successful build and must not be
    able to turn one into an error.
    """
    try:
        return _sweep(protect)
    except Exception:
        return 0, 0


def _sweep(protect):
    now = time.time()
    grace, cap, keep_n = grace_s(), cap_bytes(), keep_per_sig()
    safe = {os.path.abspath(p) for p in protect if p} | in_use()
    try:
        names = os.listdir(BLEND_DIR)
    except OSError:
        return 0, 0

    blends, scratch = [], []
    for f in names:
        p = os.path.join(BLEND_DIR, f)
        try:
            st = os.stat(p)
        except OSError as _exc:
            _zyg_log.debug('blend stat skipped: %s', _exc)
            continue
        if not os.path.isfile(p):
            continue
        if f.endswith('.blend'):
            m = _NAME.match(f)
            sig = m.group('sig') if m else '\0' + f
            # A mutated build and a clean one are not interchangeable, so they do
            # not compete for the same slot: the clean one is what `find_clean`
            # reuses, the dirty one is the operator's Blender edit.  Keeping both
            # costs almost nothing (only blender_run ever dirties a file) and
            # stops an edit from evicting the build reuse depends on.
            blends.append((p, st.st_size, st.st_mtime, (sig, os.path.exists(_dirty_path(p)))))
        elif f.endswith('.blend1'):
            scratch.append((p, st.st_size, st.st_mtime))
        elif any(f.startswith(a) and f.endswith(b) for a, b in _SCRATCH):
            scratch.append((p, st.st_size, st.st_mtime))

    # newest first — the order every rule below reads in
    blends.sort(key=lambda x: -x[2])

    keep, per_sig = set(), {}
    for p, _size, mt, sig in blends:  # sig is (signature, dirty?)
        if os.path.abspath(p) in safe or now - mt < grace:
            keep.add(p)
            per_sig[sig] = per_sig.get(sig, 0) + 1
            continue
        if per_sig.get(sig, 0) < keep_n:
            keep.add(p)
            per_sig[sig] = per_sig.get(sig, 0) + 1

    # the cap is the backstop, not the main rule: it only bites when the
    # signature rule alone still leaves more than a folder's worth.
    run, capped = 0, set()
    for p, size, mt, _sig in blends:
        if p not in keep:
            continue
        if os.path.abspath(p) in safe or now - mt < grace:
            run += size
            capped.add(p)
            continue
        if run + size <= cap:
            run += size
            capped.add(p)

    n, freed = 0, 0
    for p, size, _mt, _sig in blends:
        if p in capped:
            continue
        if _unlink(p):
            n += 1
            freed += size
            _unlink(_dirty_path(p))

    cutoff = now - _env_int('ZYG_ARCH_BLEND_SCRATCH_DAYS', 7, 1, 365) * 86400
    for p, size, mt in scratch:
        if mt < cutoff and os.path.abspath(p) not in safe and _unlink(p):
            n += 1
            freed += size
    return n, freed


def stats():
    """What the folder holds right now — for the integrity panel and the CLI."""
    tot = cnt = 0
    sigs = set()
    try:
        names = os.listdir(BLEND_DIR)
    except OSError:
        return {'files': 0, 'bytes': 0, 'signatures': 0, 'cap_bytes': cap_bytes()}
    for f in names:
        if not f.endswith('.blend'):
            continue
        try:
            tot += os.stat(os.path.join(BLEND_DIR, f)).st_size
        except OSError as _exc:
            _zyg_log.debug('blend size stat skipped: %s', _exc)
            continue
        cnt += 1
        m = _NAME.match(f)
        sigs.add(m.group('sig') if m else f)
    return {'files': cnt, 'bytes': tot, 'signatures': len(sigs), 'cap_bytes': cap_bytes()}


if __name__ == '__main__':  # the CLI lives in arch_blend_store_cli
    from zyg_workflows.arch_blend_store_cli import main as _cli_main

    raise SystemExit(_cli_main())
