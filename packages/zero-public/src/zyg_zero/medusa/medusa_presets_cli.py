# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.medusa.medusa_presets`, moved out of the library module so that
library code never prints; `python -m zyg_zero.medusa.medusa_presets` still reaches it.
"""

import os
import sys

from zyg_zero import settings


def main() -> int:
    # The library module does not import on a bare checkout (it is on tests/import_smoke_skip.txt),
    # so the CLI imports it only when it actually runs — the smoke test imports this module clean.
    from zyg_zero.medusa.medusa_presets import (
        CREWS_API,
        GUARDED_PATH,
        PORT,
        PRESETS_DIR,
        app,
    )

    os.makedirs(PRESETS_DIR, exist_ok=True)
    print(f'Medusa Presets  →  http://{settings.ZYG_LAN_HOST}:{PORT}  (guard: {CREWS_API}{GUARDED_PATH})')
    app.run(host=settings.ZYG_BIND_HOST, port=PORT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
