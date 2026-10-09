# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from quay.ranges import parse_range


def test_single():
    assert parse_range('7') == [7]


def test_span_is_inclusive():
    assert parse_range('3-5') == [3, 4, 5]
