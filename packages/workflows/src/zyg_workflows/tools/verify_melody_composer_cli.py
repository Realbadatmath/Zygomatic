# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.verify_melody_composer`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.verify_melody_composer` still reaches it.
"""

import json
import sys

from zyg_workflows.tools.verify_melody_composer import (
    STUB_FETCH,
    URL,
    _launch,
    cinematic,
)


def main():
    from playwright.sync_api import sync_playwright

    fails = []
    errors = []

    def eq(what, got, want):
        if got != want:
            fails.append(f'{what} is {got!r}, expected {want!r}')

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('dialog', lambda d: d.dismiss())
        page.goto(URL, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_selector('#view-music', state='attached', timeout=15000)
        page.evaluate('kmComposerPanel()')
        page.wait_for_selector('#km-style', state='attached', timeout=15000)

        opts = page.eval_on_selector('#km-style', 'e => Array.from(e.options).map(o => [o.value, o.text])')
        if len(opts) != 12:
            fails.append(f'#km-style has {len(opts)} options, expected 12 (blank + 11 styles)')
        if opts and opts[0][0] != '':
            fails.append(f'first option is {opts[0][0]!r}, expected the blank one')
        dance = [o for o in opts if 'dance' in (o[0] + o[1]).lower()]
        if dance:
            fails.append(f'excluded style still offered: {dance}')
        eq('#km-style default', page.input_value('#km-style'), 'playtime')

        page.select_option('#km-style', 'lullaby')
        eq('#km-mood after lullaby', page.input_value('#km-mood'), 'lullaby')
        eq('#km-age after lullaby', page.input_value('#km-age'), 'toddler')
        eq('#km-meter after lullaby', page.input_value('#km-meter'), '6/8')
        eq('#km-sec after lullaby', page.input_value('#km-sec'), '80')
        hint = page.inner_text('#km-stylehint')
        if 'voices' not in hint or 'lyrics:' not in hint:
            fails.append(f'#km-stylehint reads {hint!r}')

        page.select_option('#km-style', 'counting')
        eq('#km-form after counting', page.input_value('#km-form'), 'AAAA')

        page.evaluate(STUB_FETCH)
        page.fill('#km-theme', 'counting the ducks on the pond')
        page.click('#km-go')
        page.wait_for_function('() => window.__last !== null', timeout=10000)
        last = page.evaluate('() => ({u: String(window.__last.u), body: window.__last.o.body})')
        if '/inspect/api/kidsmusic/start' not in last['u']:
            fails.append(f'posted to {last["u"]!r}')
        song = json.loads(last['body']).get('song', {})
        eq('payload song.style', song.get('style'), 'counting')
        eq('payload song.form', song.get('form'), 'AAAA')

        browser.close()

    if errors:
        fails.append(f'{len(errors)} page error(s): ' + ' | '.join(errors[:5]))
    if fails:
        for f in fails:
            print('FAIL: ' + f)
        return 1
    print(
        'PASS  #km-style offers 12 options (blank + 11 styles, no Dance), '
        'defaults to playtime; lullaby fills mood/age/metre/seconds '
        '= lullaby/toddler/6-8/80; counting fills form AAAA; '
        'the start payload carries song.style="counting"; 0 page errors'
    )
    return 0


def cli() -> int:
    """The `--cinematic` dispatch that used to live under `if __name__` in verify_melody_composer."""
    return cinematic() if '--cinematic' in sys.argv[1:] else main()


if __name__ == '__main__':
    sys.exit(cli())
