# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.make_movement_review`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.make_movement_review` still reaches it.
"""

import os
import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.make_movement_review import (
    BIND,
    FEMALE,
    HAND,
    LOOK,
    MALE,
    MIN_BYTES,
    MOVING,
    OUT,
    README,
    frame_of,
    open_tab,
    shoot,
)


def main():
    os.makedirs(OUT, exist_ok=True)
    made = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            args=[
                '--use-angle=swiftshader',
                '--enable-unsafe-swiftshader',
                '--autoplay-policy=no-user-gesture-required',
            ],
        )

        print('MALE base body')
        pg, errs, st = open_tab(br, 'male_realistic')
        frame = frame_of(pg)
        for row in MALE:
            made.append(shoot(pg, frame, *row))

        # 10: the hand, from the hand's own frame
        pg.evaluate("() => MVA.applyView('bones')")
        pg.evaluate(BIND)
        pg.evaluate(HAND)
        pg.wait_for_timeout(700)
        p = os.path.join(OUT, '10_bones_hand.png')
        pg.screenshot(path=p, clip=frame)
        made.append(p)
        print('  %-28s %-9s LeftHand palm/distal frame' % ('10_bones_hand', 'bones'))

        # 17: the clip playing, frozen at t = 1.2 s
        pg.evaluate("() => MVA.applyView('halfbare')")
        pg.evaluate(MOVING, 1.2)
        pg.evaluate(LOOK, [30, 0, 2.00, 0.00])
        pg.wait_for_timeout(700)
        moved = pg.evaluate('() => +MVR.mixer.time.toFixed(3)')
        p = os.path.join(OUT, '17_moving_halfbare.png')
        pg.screenshot(path=p, clip=frame)
        made.append(p)
        print('  %-28s %-9s az=30 at mixer.time=%.3f s' % ('17_moving_halfbare', 'halfbare', moved))
        if errs:
            raise RuntimeError('page errors (male):\n  ' + '\n  '.join(errs[:6]))
        pg.context.close()

        print('FEMALE base body')
        pg, errs, st = open_tab(br, 'female_realistic')
        if 'female' not in st['base']:
            raise RuntimeError('the female pin did not take: base=%r actor=%r' % (st['base'], st['actor']))
        frame = frame_of(pg)
        for row in FEMALE:
            made.append(shoot(pg, frame, *row))
        if errs:
            raise RuntimeError('page errors (female):\n  ' + '\n  '.join(errs[:6]))
        pg.context.close()
        br.close()

    with open(os.path.join(OUT, 'README.txt'), 'w') as fh:
        fh.write(README)

    print('\n%d pictures in %s' % (len(made), OUT))
    small = []
    for p in sorted(made):
        n = os.path.getsize(p)
        print('  %8d bytes  %s' % (n, os.path.basename(p)))
        if n < MIN_BYTES:
            small.append((os.path.basename(p), n))
    if len(made) != 17:
        raise RuntimeError('made %d pictures, not 17' % len(made))
    if small:
        raise RuntimeError('trivial pictures (< 40 KB): %s' % small)
    print('\nPASS — 17 pictures, all over %d KB, README.txt written' % (MIN_BYTES // 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
