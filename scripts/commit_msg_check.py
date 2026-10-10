#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""commit_msg_check — the commit-message gate, run by pre-commit's `commit-msg` stage.

Rules, checked against the message file git hands the hook (argv[1]):

(a) the subject (first non-comment line) is 10..72 characters, carries no trailing '.' and
    does not consist of a bare label ('fix', 'wip', 'update') as its first word;
(b) a blank line follows the subject, then a body of at least one non-empty line that says
    what changed and why;
(c) no attribution trailer: `Co-Authored-By`, `Signed-off-by: ... Claude` and `Generated with`
    are refused; authorship is stated once in the README's "How it is built" section
    (operator rule, 2026-10-08);
(d) machine-written subjects are exempt entirely: 'Merge ', 'Revert ', 'fixup! ', 'squash! '.

Lines starting with '#' are git's own comments and are ignored throughout.

    python3 scripts/commit_msg_check.py .git/COMMIT_EDITMSG   # one line per violation, rc 1
    python3 scripts/commit_msg_check.py --selftest            # rules against inline samples
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SUBJECT_MIN = 10
SUBJECT_MAX = 72

#: Subjects git or an interactive rebase writes itself; they are never rewritten by hand.
EXEMPT_PREFIXES = ('Merge ', 'Revert ', 'fixup! ', 'squash! ')

#: Bare labels that say nothing about the change.
BARE_LABELS = frozenset({'fix', 'wip', 'update'})

TRAILER_RE = re.compile(r'^(Co-Authored-By|Signed-off-by: .*Claude|Generated with)', re.IGNORECASE)


def check_message(message: str) -> list[str]:
    """Return one human-readable line per violation; an empty list means the message passes."""
    lines = message.splitlines()
    body_of_file = [line for line in lines if not line.startswith('#')]

    subject_at = next((i for i, line in enumerate(body_of_file) if line.strip()), None)
    if subject_at is None:
        return ['commit message is empty']

    subject = body_of_file[subject_at].strip()
    if subject.startswith(EXEMPT_PREFIXES):
        return []

    violations: list[str] = []
    if len(subject) < SUBJECT_MIN:
        violations.append(f'subject is {len(subject)} characters, the minimum is {SUBJECT_MIN}: {subject!r}')
    if len(subject) > SUBJECT_MAX:
        violations.append(f'subject is {len(subject)} characters, the maximum is {SUBJECT_MAX}: {subject!r}')
    if subject.endswith('.'):
        violations.append('subject ends with a period; drop it')
    first_word = subject.split()[0].strip(':,').lower()
    if first_word in BARE_LABELS:
        violations.append(f'subject opens with the bare label {first_word!r}; say what changed instead')

    rest = body_of_file[subject_at + 1 :]
    if not rest or rest[0].strip():
        violations.append('no blank line between the subject and the body')
    if not any(line.strip() for line in rest):
        violations.append('commit message has no body; add at least one line saying what changed and why')

    for line in body_of_file:
        if TRAILER_RE.match(line.strip()):
            violations.append(
                f'no attribution trailers; authorship is stated in README "How it is built": {line.strip()!r}'
            )

    return violations


SAMPLES: tuple[tuple[str, str, bool], ...] = (
    (
        'good: subject, blank line, body',
        'scripts: add the commit-message gate\n\nThe hook keeps the history readable.\n',
        True,
    ),
    (
        'good: git comments are ignored',
        '# Please enter the commit message.\nscripts: add the commit-message gate\n\n# comment\nWhy: readability.\n',
        True,
    ),
    (
        'bad: 73-character subject',
        f'{"workflows: " + "a" * 62}\n\nA body that is long enough.\n',
        False,
    ),
    (
        'good: 72-character subject',
        f'{"workflows: " + "a" * 61}\n\nA body that is long enough.\n',
        True,
    ),
    ('bad: missing body', 'scripts: add the commit-message gate\n', False),
    (
        'bad: no blank line after the subject',
        'scripts: add the commit-message gate\nThe body starts too early.\n',
        False,
    ),
    (
        'bad: Co-Authored-By trailer',
        'scripts: add the commit-message gate\n\nWhy: readability.\n\nCo-Authored-By: Someone <a@b.c>\n',
        False,
    ),
    (
        'bad: Generated with trailer',
        'scripts: add the commit-message gate\n\nWhy: readability.\n\nGenerated with a tool\n',
        False,
    ),
    (
        'bad: Signed-off-by naming Claude',
        'scripts: add the commit-message gate\n\nWhy: readability.\n\nSigned-off-by: Claude <a@b.c>\n',
        False,
    ),
    ('bad: subject shorter than ten characters', 'fix it\n\nA real body.\n', False),
    ('bad: bare label subject', 'update the thing a little\n\nA real body.\n', False),
    ('bad: trailing period', 'scripts: add the commit-message gate.\n\nA real body.\n', False),
    ('good: merge message needs no body', 'Merge branch main into topic\n', True),
    ('good: fixup! message needs no body', 'fixup! scripts: add the gate\n', True),
    ('bad: empty message', '# nothing but comments\n', False),
)


def selftest() -> int:
    """Run every inline sample through check_message and report each mismatch."""
    failures = 0
    for label, message, should_pass in SAMPLES:
        violations = check_message(message)
        passed = not violations
        if passed != should_pass:
            failures += 1
            want = 'pass' if should_pass else 'fail'
            print(f'SELFTEST MISMATCH [{label}]: expected {want}, got {violations or "pass"}', file=sys.stderr)
    print(f'selftest: {len(SAMPLES) - failures}/{len(SAMPLES)} samples behaved as expected')
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(f'usage: {Path(sys.argv[0]).name} (<commit-message-file> | --selftest)', file=sys.stderr)
        return 2
    if argv[0] == '--selftest':
        return selftest()

    path = Path(argv[0])
    try:
        message = path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        print(f'cannot read the commit message file {path}: {exc}', file=sys.stderr)
        return 2

    violations = check_message(message)
    for violation in violations:
        print(f'commit message: {violation}', file=sys.stderr)
    if violations:
        print('commit message: subject <=72 chars, blank line, a body, no attribution trailers', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
