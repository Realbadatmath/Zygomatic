<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# data/entries

Each `entries/entry_NNN.txt` (NNN = 001…060) holds one yard ledger line in this form:

    name: <text>
    day: <integer>
    height_duim: <integer>
    wind: <one of north, north-east, east, south-east, south, south-west, west, north-west>

Convert each to `out/entry_NNN.json` with exactly the keys `name`, `day`, `height_duim`,
`wind` — `day` and `height_duim` as integers, the rest as strings. Verify each file with
`python3 -m json.tool out/entry_NNN.json` before moving on.

The runner generates the 60 entry files before a test run (day = NNN, height_duim =
(NNN × 37) mod 300, wind = the list above indexed by NNN mod 8, name = "entry NNN").
