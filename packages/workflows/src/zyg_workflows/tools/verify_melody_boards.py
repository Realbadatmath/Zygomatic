#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof that the wired melody boards are the live composer board, and that the
excluded one is not.

Default mode: the eleven children's boards are deep clones of T.kidsmusic.
--cinematic: the thirteen cinematic boards are that same board MINUS the
Pictures column and MINUS the Lyrics card (cinematic is instrumental), and the
children's boards are untouched by that change.

Runs the real page (``$ZYG_KANBAN_URL/kanban.html``) in headless Chrome and
reads TEMPLATES / TEMPLATES_SDXL out of the loaded document, because the claim
being checked is about what the browser ends up with — a static grep of
kanban_main.js would pass on a file the page never loaded (stale ?v= cache
buster) and would say nothing about console errors.

wait_until='domcontentloaded', never 'networkidle': the board polls
/kanban/api/... every 500 ms, so the network is never idle and that wait would
time out on a perfectly healthy page.
"""

import os
import sys

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

URL = paths.ZYG_KANBAN_URL + '/kanban.html'
WIRED = [
    'playtime',
    'sleeptime',
    'storytime',
    'learning',
    'lullaby',
    'nursery',
    'counting',
    'singalong',
    'animals',
    'seasons',
    'bedtime',
]
CINE = [
    'cheerful',
    'sad',
    'heroic',
    'tavern',
    'storytime',
    'sonata',
    'suspense',
    'romance',
    'wonder',
    'mystery',
    'chase',
    'melancholy',
    'triumph',
]
# The Lyrics card plus the four cards of the Pictures column. Named rather than
# counted so the check fails loudly if one is ever renamed, instead of quietly
# accepting a different card of the same arity.
CINE_DROPPED = ['Lyrics', 'Storyboard', 'Illustrate', 'Measure Frames', 'Assemble Video']
CINE_COLS = ['brief', 'compose', 'render', 'produce', 'deliver']
FALLBACK_CHROME = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1208/chrome-linux/headless_shell')

CHECK_JS = """
(wired) => {
  const out = {ok: true, fail: []};
  const bad = (m) => { out.ok = false; out.fail.push(m); };
  // Both are top-level `const`s in kanban_main.js, so they live in the global
  // LEXICAL scope and are NOT properties of window — read them by bare name.
  const T = (typeof TEMPLATES !== 'undefined') ? TEMPLATES : null;
  const S = (typeof TEMPLATES_SDXL !== 'undefined') ? TEMPLATES_SDXL : null;
  if (!T || !S) { bad('TEMPLATES / TEMPLATES_SDXL missing'); return out; }

  const prompts = (b) => (b.columns || []).reduce(
    (a, c) => a.concat((c.cards || []).map(k => k.prompt)), []);
  const ref = prompts(T.kidsmusic);
  out.ref_cards = ref.length;
  out.ref_cols  = (T.kidsmusic.columns || []).length;
  if (out.ref_cols !== 6 || ref.length !== 12) {
    bad('kidsmusic reference is ' + out.ref_cols + ' cols / ' + ref.length
        + ' cards, expected 6/12');
  }

  for (const k of wired) {
    const key = 'mel_children_' + k;
    for (const [fam, TT] of [['FLUX', T], ['SDXL', S]]) {
      const b = TT[key];
      if (!b) { bad(fam + ' ' + key + ' missing'); continue; }
      const cols = (b.columns || []).length;
      const p = prompts(b);
      if (cols !== 6) bad(fam + ' ' + key + ' has ' + cols + ' columns');
      if (p.length !== 12) bad(fam + ' ' + key + ' has ' + p.length + ' cards');
      if (p.join('\\u0000') !== ref.join('\\u0000')) {
        bad(fam + ' ' + key + ' card prompts differ from kidsmusic');
      }
    }
    // the per-style edits actually landed
    const brief = (T[key].columns[0].cards || [])
      .find(c => c.prompt === 'Song Brief');
    if (!brief || !/<li>Style: /.test(brief.meta.description)) {
      bad(key + ' Song Brief does not name its style');
    }
    const sr = (T[key].columns.find(c => c.id === 'render').cards || [])
      .find(c => c.prompt === 'Score Render');
    if (!sr || sr.agent.indexOf('melody_sampler.py') !== 0) {
      bad(key + ' Score Render agent not rewritten');
    }
  }

  const empty = (key) => {
    const b = T[key];
    if (!b) { bad(key + ' missing'); return; }
    const cols = (b.columns || []).length;
    const n = prompts(b).length;
    if (cols !== 5 || n !== 0) bad(key + ' is ' + cols + '/' + n + ', expected 5/0');
  };
  empty('mel_children_dance');
  // mel_cinematic_sad used to be checked here as an empty board. It is a wired
  // cinematic board since 2026-09-06 — see --cinematic.

  const row = document.querySelector(
    '#kb-chgrp-melodies .kb-ch-item[data-key="mel_children_dance"]');
  if (!row) bad('dance flyout row not built');
  else if (!row.classList.contains('kb-ch-off')) bad('dance row lacks kb-ch-off');

  return out;
}
"""

# --cinematic. The expected card list is DERIVED from T.kidsmusic minus the
# dropped titles rather than hard-coded, so this stays a statement about the
# relationship ("same board, two parts cut") instead of a second copy of the
# board that has to be edited in step with the first one.
CINE_JS = """
(args) => {
  const [cine, dropped, wantCols, children] = args;
  const out = {ok: true, fail: []};
  const bad = (m) => { out.ok = false; out.fail.push(m); };
  const T = (typeof TEMPLATES !== 'undefined') ? TEMPLATES : null;
  const S = (typeof TEMPLATES_SDXL !== 'undefined') ? TEMPLATES_SDXL : null;
  if (!T || !S) { bad('TEMPLATES / TEMPLATES_SDXL missing'); return out; }

  const prompts = (b) => (b.columns || []).reduce(
    (a, c) => a.concat((c.cards || []).map(k => k.prompt)), []);
  const ref = prompts(T.kidsmusic);
  if ((T.kidsmusic.columns || []).length !== 6 || ref.length !== 12) {
    bad('kidsmusic reference is not 6 cols / 12 cards');
    return out;
  }
  const want = ref.filter(p => dropped.indexOf(p) < 0);
  out.want_cards = want.length;
  out.want_cols  = wantCols.length;

  for (const k of cine) {
    const key = 'mel_cinematic_' + k;
    for (const [fam, TT] of [['FLUX', T], ['SDXL', S]]) {
      const b = TT[key];
      if (!b) { bad(fam + ' ' + key + ' missing'); continue; }
      const ids = (b.columns || []).map(c => c.id);
      if (ids.join(',') !== wantCols.join(',')) {
        bad(fam + ' ' + key + ' columns are [' + ids.join(',') + ']');
      }
      const p = prompts(b);
      if (p.join('\\u0000') !== want.join('\\u0000')) {
        bad(fam + ' ' + key + ' cards are [' + p.join(', ') + ']');
      }
      for (const d of dropped) {
        if (p.indexOf(d) >= 0) bad(fam + ' ' + key + ' still carries ' + d);
      }
    }
    const b = T[key];
    if (!b) continue;
    if (b.name.indexOf('Cinematic \\u2014 ') !== 0) {
      bad(key + ' name is ' + JSON.stringify(b.name));
    }
    if (b.label.indexOf('[ MELODIES \\u203a CINEMATIC \\u203a ') !== 0) {
      bad(key + ' label is ' + JSON.stringify(b.label));
    }
    const brief = (b.columns[0].cards || []).find(c => c.prompt === 'Song Brief');
    if (!brief || !/<li>Style: .* \\u2014 instrumental; voices .+\\/.+\\/.+ \\+ .+<\\/li>/
        .test(brief.meta.description)) {
      bad(key + ' Song Brief does not name its style and four voices');
    }
    const ace = (b.columns.find(c => c.id === 'produce').cards || [])
      .find(c => c.prompt === 'Produced Track (ACE-Step)');
    if (!ace || ace.meta.description.indexOf(
          '<li>Instrumental caption \\u2014 no lyrics are passed; ') < 0) {
      bad(key + ' Produced Track is not marked instrumental');
    }
  }

  // The children's boards must be untouched by the cinematic change.
  for (const k of children) {
    const b = T['mel_children_' + k];
    if (!b) { bad('mel_children_' + k + ' missing'); continue; }
    const cols = (b.columns || []).length;
    const n = prompts(b).length;
    if (cols !== 6 || n !== 12) {
      bad('mel_children_' + k + ' is ' + cols + '/' + n + ', expected 6/12');
    }
  }
  return out;
}
"""


def _launch(pw):
    try:
        return pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
    except Exception as e:  # noqa: BLE001 — try the bundled one
        _zyg_log.info(f'google-chrome unusable ({e.__class__.__name__}); falling back to bundled headless_shell')
        return pw.chromium.launch(executable_path=FALLBACK_CHROME, headless=True)


def main():
    from playwright.sync_api import sync_playwright

    cine = '--cinematic' in sys.argv[1:]
    errors = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append('console.error: ' + m.text) if m.type == 'error' else None)
        page.goto(URL, wait_until='domcontentloaded', timeout=30000)
        # The flyout rows are built by _buildMelodyMenu() after init.
        # state='attached', not the default 'visible': the Melodies group is
        # collapsed until the operator clicks its chevron, so the rows are in
        # the DOM (which is all this checks) but never visible on load.
        page.wait_for_selector(
            '#kb-chgrp-melodies .kb-ch-item[data-key="mel_children_dance"]', state='attached', timeout=15000
        )
        res = page.evaluate(CINE_JS, [CINE, CINE_DROPPED, CINE_COLS, WIRED]) if cine else page.evaluate(CHECK_JS, WIRED)
        browser.close()

    fails = list(res.get('fail') or [])
    if errors:
        fails.append(f'{len(errors)} page error(s): ' + ' | '.join(errors[:5]))
    if fails:
        for f in fails:
            print('FAIL: ' + f)
        return 1
    if cine:
        print(
            f'PASS  {len(CINE)} cinematic boards = kidsmusic minus Pictures '
            f'and Lyrics ({res["want_cols"]} cols '
            f'[{",".join(CINE_COLS)}] / {res["want_cards"]} cards) in '
            f'TEMPLATES and TEMPLATES_SDXL, each naming its style + four '
            f'voices and its instrumental caption; the {len(WIRED)} children '
            f'boards still 6/12; 0 page errors'
        )
        return 0
    print(
        f'PASS  11 wired children boards = kidsmusic clone '
        f'({res["ref_cols"]} cols / {res["ref_cards"]} cards) in TEMPLATES '
        f'and TEMPLATES_SDXL; mel_children_dance 5/0 + kb-ch-off; '
        f'0 page errors'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
