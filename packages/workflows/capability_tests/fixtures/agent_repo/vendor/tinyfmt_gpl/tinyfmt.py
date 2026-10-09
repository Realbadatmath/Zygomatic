# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tinyfmt: pad text to a width (GPL-3.0, see LICENSE)."""


def pad(text: str, width: int, fill: str = ' ') -> str:
    return text + fill * max(0, width - len(text))
