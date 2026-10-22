#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof that the Melody Studio composer has a Style field, that picking a style
fills the rest of the form from kids_music_theory's table, and that the style
key reaches the start payload.

With --cinematic it proves the second half of that claim: the Family select
switches the Style list to the thirteen cinematic styles, hides the four
controls a score has no use for (age band, singer, sung, illustrated video),
fills mode/length from the cinematic table, and posts family='cinematic' with
sung and want_video forced false — then switches back and finds the children's
composer intact.

Runs the real page (``$ZYG_KANBAN_URL/inspection.html#music``) in headless
Chrome, because the claim is about what the browser ends up with: a grep of
inspection.html would pass on a file the running server no longer serves, and
would say nothing about page errors.

wait_until='domcontentloaded', never 'networkidle' — the page keeps polling, so
the network is never idle and that wait would time out on a healthy page.

The POST is never really sent: window.fetch is replaced with a stub that records
the call and answers "not ok", so clicking Compose proves the payload without
starting a pipeline on the GPU.
"""

import json
import os

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

URL = paths.ZYG_KANBAN_URL + '/inspection.html#music'
FALLBACK_CHROME = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1208/chrome-linux/headless_shell')

STUB_FETCH = """
() => { window.__last = null;
        window.fetch = (u, o) => { window.__last = {u: u, o: o};
          return Promise.resolve({ok: false,
                                  json: () => Promise.resolve({error: 'test'})}); }; }
"""


def _launch(pw):
    try:
        return pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
    except Exception as e:  # noqa: BLE001 — try the bundled one
        _zyg_log.info(f'google-chrome unusable ({e.__class__.__name__}); falling back to bundled headless_shell')
        return pw.chromium.launch(executable_path=FALLBACK_CHROME, headless=True)


def cinematic():
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
        page.wait_for_selector('#km-family', state='attached', timeout=15000)

        eq('#km-family default', page.input_value('#km-family'), 'children')

        # ── the cinematic family ──────────────────────────────────────────
        page.select_option('#km-family', 'cinematic')
        opts = page.eval_on_selector('#km-style', 'e => Array.from(e.options).map(o => o.value)')
        if len(opts) != 13:
            fails.append(f'#km-style has {len(opts)} options on cinematic, expected 13: {opts}')
        if '' in opts:
            fails.append('cinematic still offers the blank "no style" option')

        hid = page.evaluate("() => Array.from(document.querySelectorAll('.km-childonly')).map(e => e.hidden)")
        if len(hid) != 4 or not all(hid):
            fails.append(f'.km-childonly hidden flags are {hid}, expected 4 x True (age, singer, sung, video)')
        eq('#km-sung checked on cinematic', page.evaluate("() => document.getElementById('km-sung').checked"), False)
        eq('#km-video checked on cinematic', page.evaluate("() => document.getElementById('km-video').checked"), False)

        page.select_option('#km-style', 'chase')
        eq('#km-mode after chase', page.input_value('#km-mode'), 'natural_minor')
        eq('#km-sec after chase', page.input_value('#km-sec'), '60')
        ph = page.get_attribute('#km-bpm', 'placeholder')
        if ph != 'auto (140\u2013168)':
            fails.append(f"#km-bpm placeholder is {ph!r}, expected 'auto (140\u2013168)'")
        hint = page.inner_text('#km-stylehint')
        if 'instrumental' not in hint or 'no pictures' not in hint or 'shelf' not in hint or 'voices' not in hint:
            fails.append(f'#km-stylehint reads {hint!r}')

        # ── the payload ───────────────────────────────────────────────────
        page.evaluate(STUB_FETCH)
        page.fill('#km-theme', 'a rooftop chase at night')
        page.click('#km-go')
        page.wait_for_function('() => window.__last !== null', timeout=10000)
        last = page.evaluate('() => ({u: String(window.__last.u), body: window.__last.o.body})')
        if '/inspect/api/kidsmusic/start' not in last['u']:
            fails.append(f'posted to {last["u"]!r}')
        song = json.loads(last['body']).get('song', {})
        eq('payload song.family', song.get('family'), 'cinematic')
        eq('payload song.style', song.get('style'), 'chase')
        eq('payload song.sung', song.get('sung'), False)
        eq('payload song.want_video', song.get('want_video'), False)
        if 'singer' in song:
            fails.append(f'payload still carries singer={song["singer"]!r}')

        # ── and back ──────────────────────────────────────────────────────
        page.select_option('#km-family', 'children')
        back = page.eval_on_selector('#km-style', 'e => Array.from(e.options).map(o => o.value)')
        # 12 = the blank "classic composer" option + the 11 children's styles.
        # The blank is kept on the way back deliberately: the default run of
        # this script asserts 12 at first paint, and the hand-set composer is
        # only reachable through it.
        if len(back) != 12 or len([o for o in back if o]) != 11:
            fails.append(
                f'#km-style back on children has {len(back)} options '
                f'({len([o for o in back if o])} styles), expected '
                f'12 (blank + 11): {back}'
            )
        eq('#km-style back on children', page.input_value('#km-style'), 'playtime')
        hid2 = page.evaluate("() => Array.from(document.querySelectorAll('.km-childonly')).map(e => e.hidden)")
        if len(hid2) != 4 or any(hid2):
            fails.append(f'.km-childonly hidden flags back on children are {hid2}, expected 4 x False')
        eq('#km-sung checked back on children', page.evaluate("() => document.getElementById('km-sung').checked"), True)
        eq('#km-age back on children', page.input_value('#km-age'), 'preschool')

        browser.close()

    if errors:
        fails.append(f'{len(errors)} page error(s): ' + ' | '.join(errors[:5]))
    if fails:
        for f in fails:
            _zyg_log.info('FAIL: ' + f)
        return 1
    _zyg_log.info(
        'PASS  #km-family switches the composer to Cinematic: 13 styles and no '
        'blank, the 4 child-only controls hidden with Sung and Illustrated '
        'video unchecked, chase fills mode/seconds = natural_minor/60 and the '
        'bpm placeholder "auto (140-168)", the hint says instrumental / no '
        'pictures / shelf / voices; the start payload carries '
        'family="cinematic", style="chase", sung=false, want_video=false and '
        'no singer; switching back restores 12 options (blank + 11 styles) on '
        'playtime with all 4 child-only controls visible and Sung re-checked; '
        '0 page errors'
    )
    return 0


if __name__ == '__main__':  # the CLI lives in verify_melody_composer_cli
    from zyg_workflows.tools.verify_melody_composer_cli import cli as _cli_main

    raise SystemExit(_cli_main())
