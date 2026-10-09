# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The library this tab browses, the spec payload and the import-time selfcheck."""

from ._defs import SECTIONS


# ── the library this tab browses ──────────────────────────────────────────
# The Sfx Studio lists every audio category.  Music Studio lists the MUSICAL
# ones, and nothing else: the instruments library it was built for, the music
# cues, and the two categories its own saves land in (a tab that can save into
# Merged but cannot see Merged could not reopen its own recipe).
CATEGORIES = ['instruments', 'soundtracks', 'merged', 'recorded']
DEFAULT_CATEGORY = 'instruments'


def spec():
    """Everything the page needs to draw the bars, in one payload.

    `places` is the screen edge each section is drawn on.  It is answered from
    here rather than assumed by the page for the reason video_studio.py gives:
    the file that owns the roster is the file that should own where it lands,
    so moving a section between bars is one word here and no page edit."""
    return {
        'sections': SECTIONS,
        'categories': CATEGORIES,
        'default_category': DEFAULT_CATEGORY,
        'counts': {
            'total': sum(len(s['tools']) for s in SECTIONS),
            'live': sum(1 for s in SECTIONS for t in s['tools'] if t['live']),
            'placeholder': sum(1 for s in SECTIONS for t in s['tools'] if not t['live']),
            'left': sum(len(s['tools']) for s in SECTIONS if s['place'] == 'left'),
            'dock': sum(len(s['tools']) for s in SECTIONS if s['place'] == 'dock'),
            'side': sum(len(s['tools']) for s in SECTIONS if s['place'] == 'side'),
        },
    }


def _selfcheck():
    """Two things a registry of this size gets wrong silently: a duplicated id
    (the second tool is then unclickable, because the delegated handler finds
    the first) and two tools drawn with the SAME picture (measured on the
    Architecture rail — Solo and Mute were identical, and on screen that is one
    button, not two).  Both are assertions, not warnings: a duplicate must
    fail the import, not print into a log nobody reads."""
    ids, svgs = {}, {}
    for s in SECTIONS:
        for t in s['tools']:
            if t['id'] in ids:
                raise AssertionError(f'duplicate tool id {t["id"]!r} ({ids[t["id"]]} and {s["id"]})')
            ids[t['id']] = s['id']
            key = ''.join(t['svg'].split())
            if key in svgs:
                raise AssertionError(f'{t["id"]!r} is drawn exactly like {svgs[key]!r} — two tools, one picture')
            svgs[key] = t['id']
            if s['place'] not in ('left', 'dock', 'side'):
                raise AssertionError(f'{t["id"]!r}: unknown place {s["place"]!r}')
    return len(ids)


_selfcheck()
