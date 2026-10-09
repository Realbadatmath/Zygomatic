# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tide readings: (hour, height_in_duim) pairs."""

import math  # noqa: F401  planted fixture flaw: TODO.md asks the agent under test to drop it


def high_water(readings: list[tuple[int, int]]) -> tuple[int, int]:
    """Return the (hour, height) reading with the greatest height."""
    return max(readings)
