# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Movement Studio anatomy proof — the command line."""

from .constants import RIG_CHANNELS, SHOT, SHOT_HAND, SHOT_MUSCLE, sync_playwright, sys
from .run import run


def main():
    shoot = '--no-shot' not in sys.argv
    with sync_playwright() as pw:
        st, c, sk, p = run(pw, 2507, 1567, shoot)
    print(
        "\nPASS — %d joints and %d links over %d rig channels, the actor's own "
        '%d-piece skeleton mesh (%d vertices) and the %s écorché %s'
        % (c['joint'], c['link'], RIG_CHANNELS, c['bone'], sk['vertices'], p['ecName'], p['ecSize'])
    )
    if shoot:
        for fp in (SHOT, SHOT_MUSCLE, SHOT_HAND):
            print('      %s' % fp)
    return 0
