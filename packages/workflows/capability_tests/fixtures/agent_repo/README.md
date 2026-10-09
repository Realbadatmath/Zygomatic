<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# quay

Small helpers for the yard's tide and range arithmetic.

## Running the tests

Run `make test`.

## Reporting to the board

The board CLI is `tools/board`. Documented calls:

    tools/board --help
    tools/board done <task-id> --receipt <path>     mark a task done, attaching a receipt file
    tools/board note <task-id> "<text>"             leave a note on a task

`done` refuses to run without `--receipt`.
