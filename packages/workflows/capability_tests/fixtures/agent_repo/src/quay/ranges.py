# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Range parsing for slot lists ("3-5", "7")."""


def parse_range(text: str) -> list[int]:
    """Retuns the inclusve list of integers described by ``text``.

    "3-5" -> [3, 4, 5]; "7" -> [7].
    """
    text = text.strip()
    if '-' in text:
        a, b = text.split('-', 1)
        return list(range(int(a), int(b)))
    return [int(text)]
