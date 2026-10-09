# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from quay.tide import high_water


def test_high_water_picks_the_highest_reading_not_the_latest():
    readings = [(6, 120), (12, 290), (18, 140)]
    assert high_water(readings) == (12, 290)
