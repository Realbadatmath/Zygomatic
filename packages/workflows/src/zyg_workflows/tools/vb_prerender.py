#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Warm the voice bridge's say-cache with every sentence the assistant can speak.

The assistant only ever says two kinds of fixed sentence:

1. `voice_brain.PHRASES` — the brain's own replies ("Opening Video Studio",
   "Done", "I did not catch that", ...).
2. The `say:` of every action registered by a client file in `voice_ext/*.js`
   ("Render started.", "Tempo set.", ...). Those live in JavaScript, so they are
   read out of the source rather than imported.

Both are rendered through the tts extension module's own `ROUTES['prerender']`,
imported as a module — NOT over HTTP: the pre-render is run before kanban_server
has ever been restarted with the voice bridge mounted, so there is no endpoint to
call yet, and going through one would only add a hop to code that is already in
this process.

One phrase per prerender call, so the table can report a real per-phrase time and
a real cached/rendered verdict; the route's own aggregate counters are summed at
the end as a cross-check.

    tools/vb_prerender.py                # warm everything that is missing
    tools/vb_prerender.py --clear        # drop the cache first, then warm it all
    tools/vb_prerender.py --list         # print the phrase list and exit
"""

import glob
import logging as _zyg_logging
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREWS = os.path.dirname(_HERE)
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

from zyg_workflows import voice_brain  # noqa: E402
import zyg_workflows.voice_ext.tts as TTS  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


# `say: '...'` and `say: "..."`. Template literals are deliberately not matched:
# a backticked say carries ${...} and is not a fixed sentence.
_SAY_RES = (re.compile(r"say:\s*'([^']*)'"), re.compile(r'say:\s*"([^"]*)"'))


def _is_fragment(text: str, tail: str) -> bool:
    """Whether a matched literal is half of a concatenation rather than a whole
    sentence — `say: 'Opening ' + name`. Such a fragment is never spoken on its
    own, so rendering it would burn a model load on audio nobody hears.

    Two signals, both cheap: the text keeps an edge space (you do not write
    `'Opening '` unless something follows it), or the source continues with `+`.
    """
    if text != text.strip():
        return True
    return tail.lstrip().startswith('+')


def js_says(root: str) -> list:
    """Every fixed `say:` sentence registered by the client files, in file then
    source order. Missing files are simply absent — the studio files land task by
    task, and this tool takes whatever is there on the day it runs."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, 'voice_ext', '*.js'))):
        try:
            with open(path, encoding='utf-8') as f:
                src = f.read()
        except OSError as _exc:
            _zyg_log.debug('source file unreadable, skipped: %s', _exc)
            continue
        for rx in _SAY_RES:
            for m in rx.finditer(src):
                text = m.group(1)
                if not text.strip() or _is_fragment(text, src[m.end() : m.end() + 24]):
                    continue
                out.append((os.path.basename(path), text))
    return out


def collect(root: str) -> list:
    """[(source, phrase)] — brain phrases first, de-duplicated, order kept."""
    rows = [('voice_brain.PHRASES', str(p)) for p in voice_brain.PHRASES]
    rows += js_says(root)
    seen, out = set(), []
    for src, text in rows:
        text = (text or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append((src, text))
    return out


def clear_cache() -> int:
    """Remove every cached wav. Used after the voice or the preset changed: the
    key includes the knob set, so stale entries are never served — they are just
    dead bytes, and the operator asking for --clear wants them gone."""
    n = 0
    for path in glob.glob(os.path.join(TTS.SAY_DIR, '*.wav')):
        try:
            os.remove(path)
            n += 1
        except OSError as _exc:
            _zyg_log.debug('cache file removal skipped: %s', _exc)
    return n


if __name__ == '__main__':  # the CLI lives in vb_prerender_cli
    from zyg_workflows.tools.vb_prerender_cli import main as _cli_main

    raise SystemExit(_cli_main())
