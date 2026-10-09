# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bigfmt: text layout helpers (MIT, see LICENSE). Larger than tinyfmt on purpose."""


def pad(text: str, width: int, fill: str = ' ', align: str = 'left') -> str:
    """Pad ``text`` to ``width`` with ``fill``; align left, right or centre."""
    gap = max(0, width - len(text))
    if align == 'right':
        return fill * gap + text
    if align in ('centre', 'center'):
        left = gap // 2
        return fill * left + text + fill * (gap - left)
    return text + fill * gap


def truncate(text: str, width: int, marker: str = '…') -> str:
    """Cut ``text`` to ``width`` characters, ending with ``marker`` when cut."""
    if len(text) <= width:
        return text
    return text[: max(0, width - len(marker))] + marker


def columns(rows: list[list[str]], gap: int = 2) -> str:
    """Lay ``rows`` out in aligned columns."""
    if not rows:
        return ''
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return '\n'.join((' ' * gap).join(pad(str(c), widths[i]) for i, c in enumerate(r)) for r in rows)
