# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.studio_verify.check_movement_rig_teach_edit`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.tools.studio_verify.check_movement_rig_teach_edit` still reaches it.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

from zyg_workflows.tools.studio_verify.check_movement_rig_teach_edit import (
    BOOT_TIMEOUT_MS,
    SHOT_EDIT,
    SHOT_TEACH,
    SRC_MOTION,
    URL,
    VIEWPORT,
    leg_edit,
    leg_teach,
    poll,
)


def main():
    out = {'ok': True, 'viewport': '%dx%d' % (VIEWPORT['width'], VIEWPORT['height'])}
    errs = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            args=[
                '--use-angle=swiftshader',
                '--enable-unsafe-swiftshader',
                '--autoplay-policy=no-user-gesture-required',
            ],
        )
        pg = br.new_context(viewport=VIEWPORT).new_page()
        pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
        pg.goto(URL, wait_until='load', timeout=120_000)

        boot, waited_boot = poll(pg, lambda s: s.get('ready'), BOOT_TIMEOUT_MS, 'the tab never loaded a skeleton')
        out.update(
            {
                'boot_name': boot['cname'].strip(),
                'boot_actor': boot['actor'],
                'boot_motion': boot['motion'],
                'clips_before': len(boot['libIds']),
                'waited_boot_s': waited_boot // 1000,
            }
        )
        if not boot['actor'].startswith('base_'):
            raise RuntimeError('the tab did not open on the base body: actor %r' % boot['actor'])
        if boot['motion'] != SRC_MOTION:
            raise RuntimeError('the tab opened on %r, expected %r' % (boot['motion'], SRC_MOTION))

        leg_edit(pg, out)
        leg_teach(pg, out)
        br.close()

    out['pageerrors'] = [e for e in errs if 'favicon' not in e]
    out['screenshot_edit'] = SHOT_EDIT
    out['screenshot_edit_bytes'] = os.path.getsize(SHOT_EDIT)
    out['screenshot_teach'] = SHOT_TEACH
    out['screenshot_teach_bytes'] = os.path.getsize(SHOT_TEACH)
    print(json.dumps(out, indent=1))
    if out['pageerrors']:
        raise RuntimeError(out['pageerrors'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
