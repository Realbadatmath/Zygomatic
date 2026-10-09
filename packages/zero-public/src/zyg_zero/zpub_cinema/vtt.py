# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Subtitles to WebVTT, and WebVTT tidying."""

import os
import re
import shutil

from .constants import FFMPEG, SUB_DIR
from .probing import _run

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_cinema')


# ══ Subtitles → WebVTT ════════════════════════════════════════════════════════
_TIME_RE = re.compile(r'(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})')


def _read_text(path: str) -> str:
    """Read a subtitle file whatever it was saved as (never raises)."""
    try:
        raw = open(path, 'rb').read()
    except OSError:
        return ''
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    return raw.decode('utf-8', 'replace')


def srt_to_vtt(text: str) -> str:
    """Convert SubRip to WebVTT.

    <b>/<i>/<u> and <font color> survive (the browser renders them); ASS
    override blocks like {\\an8} do not and would otherwise print literally.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\{\\[^}]*\}', '', text)  # ASS override tags
    out = ['WEBVTT', '']
    for block in re.split(r'\n{2,}', text.strip()):
        lines = [ln for ln in block.split('\n') if ln.strip() != '']
        if not lines:
            continue
        # Drop the numeric cue index — VTT allows it but it confuses nothing to lose it.
        if lines[0].strip().isdigit() and len(lines) > 1:
            lines = lines[1:]
        if not lines or '-->' not in lines[0]:
            continue
        timing = _TIME_RE.sub(
            lambda m: (
                f'{int(m.group(1)):02d}:{int(m.group(2)):02d}:{int(m.group(3)):02d}.{m.group(4).ljust(3, "0")[:3]}'
            ),
            lines[0],
        )
        timing = timing.split('-->')
        if len(timing) != 2:
            continue
        start = timing[0].strip()
        # Strip SRT positioning coords (X1:… Y1:…) that VTT does not understand.
        end = re.split(r'\s+[A-Za-z]\d?:', timing[1].strip())[0].strip()
        out.append(f'{start} --> {end}')
        out.extend(lines[1:])
        out.append('')
    return '\n'.join(out)


_VTT_CUE_RE = re.compile(
    r'(?P<a>\d{1,3}:\d{2}:\d{2}\.\d{3}|\d{1,3}:\d{2}\.\d{3})\s*-->\s*'
    r'(?P<b>\d{1,3}:\d{2}:\d{2}\.\d{3}|\d{1,3}:\d{2}\.\d{3})(?P<rest>[^\n]*)'
)


def _vtt_seconds(stamp: str) -> float:
    parts = stamp.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return 0.0


def _vtt_stamp(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'


def shift_vtt(text: str, offset: float) -> str:
    """Rebase every cue by ``-offset`` seconds, dropping cues that end before 0.

    The transcoded stream restarts its clock at 0 for whatever timestamp the
    server actually seeked to, so a cue written for 01:23:45 of the film has to
    move to (01:23:45 - offset) to land on the right frame.
    """
    if not offset:
        return text
    out, drop_block = [], False
    for line in text.split('\n'):
        m = _VTT_CUE_RE.search(line)
        if not m:
            if drop_block:
                if line.strip() == '':
                    drop_block = False
                continue
            out.append(line)
            continue
        start = _vtt_seconds(m.group('a')) - offset
        end = _vtt_seconds(m.group('b')) - offset
        if end <= 0:
            # Cue is behind the new origin — drop it and the text under it.
            drop_block = True
            if out and out[-1].strip() != '' and not out[-1].startswith('WEBVTT'):
                out.pop()  # its cue identifier, if any
            continue
        drop_block = False
        out.append(f'{_vtt_stamp(max(0.0, start))} --> {_vtt_stamp(end)}{m.group("rest")}')
    return '\n'.join(out)


# ── WebVTT tidying ────────────────────────────────────────────────────────────
# Heavily typeset fansub ASS cannot be represented in WebVTT, and ffmpeg's
# conversion flattens every animation step into its own cue. Measured on one
# real episode's 'Dialogue' track: 38,048 cues, of which 34,579 were a SINGLE
# character (a per-glyph sign animation) and 1,638 were active simultaneously at
# the ED — the browser stacked them, so the picture was a wall of repeated text.
# The same three rules leave 539 cues, 396 of them real dialogue lines.
_VTT_TAG_RE = re.compile(r'<[^>]*>')
_ASS_BRACE_RE = re.compile(r'\{[^}]*\}')  # '{=112}Poisonous' — ASS override left behind
# An ASS vector drawing ('m 0 0 l 100 0 100 100 0 100') is a shape, not a line,
# but ffmpeg emits its path as cue TEXT: 103 of them across one 25-episode
# season. Matched narrowly — drawing letters and numbers only, at least four
# digits — so a real letter-free line like '200,000?' is kept.
_ASS_DRAW_RE = re.compile(r'^[\s\d.,\-mnlbspc]+$', re.I)
SUB_MIN_VISIBLE = 3  # a 1-2 character cue is animation debris, not a line
SUB_MAX_ACTIVE = 3  # dialogue is one or two lines; 13 is a typeset sign
SUB_MERGE_GAP = 0.2  # identical text this close is one cue, not two
SUB_CACHE_VER = 2  # bump to invalidate every cached .vtt


def _vtt_blocks(text: str):
    """Split a VTT into (header, [(start, end, rest, body)]) — never raises."""
    header, cues = 'WEBVTT', []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n')):
        block = block.strip('\n')
        if not block:
            continue
        if '-->' not in block:
            if block.upper().startswith('WEBVTT'):
                header = block
            continue  # NOTE/STYLE/REGION blocks
        lines = block.split('\n')
        tidx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if tidx is None:
            continue
        m = _VTT_CUE_RE.search(lines[tidx])
        if not m:
            continue
        body = '\n'.join(lines[tidx + 1 :]).strip('\n')  # cue ids are dropped
        cues.append([_vtt_seconds(m.group('a')), _vtt_seconds(m.group('b')), m.group('rest') or '', body])
    return header, cues


def tidy_vtt(text: str) -> str:
    """Drop animation debris, merge duplicates, and cap simultaneous cues."""
    header, cues = _vtt_blocks(text)
    if not cues:
        return text

    cleaned = []
    for start, end, rest, body in cues:
        body = _ASS_BRACE_RE.sub('', body).strip()
        visible = ' '.join(_VTT_TAG_RE.sub('', body).split())
        if len(visible) < SUB_MIN_VISIBLE or end <= start:
            continue
        if _ASS_DRAW_RE.match(visible) and len(re.findall(r'\d', visible)) >= 4:
            continue  # a drawn shape's path

        cleaned.append([start, end, rest, body, visible])

    # Identical text that overlaps (or nearly abuts) is one cue said once.
    cleaned.sort(key=lambda c: (c[4], c[0]))
    merged = []
    for c in cleaned:
        if merged and merged[-1][4] == c[4] and c[0] <= merged[-1][1] + SUB_MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], c[1])
        else:
            merged.append(c)

    # Keep the longest line when several want the screen at once: the full
    # sentence is the translation, the short fragments are the typeset sign.
    merged.sort(key=lambda c: (-len(c[4]), c[0]))
    kept: list[list] = []
    for c in merged:
        clash = sum(1 for k in kept if c[0] < k[1] and k[0] < c[1])
        if clash < SUB_MAX_ACTIVE:
            kept.append(c)
    kept.sort(key=lambda c: (c[0], c[1]))

    out = [header, '']
    for start, end, rest, body, _vis in kept:
        out.append(f'{_vtt_stamp(start)} --> {_vtt_stamp(end)}{rest}')
        out.append(body)
        out.append('')
    return '\n'.join(out)


def _ffmpeg_to_vtt(args_in: list[str], dest: str) -> bool:
    rc, _o, err = _run([FFMPEG, '-y', '-v', 'error', *args_in, '-f', 'webvtt', dest], timeout=300)
    ok = rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 16
    if not ok:
        _zyg_log.info(f'[Cinema] subtitle extract failed: {err[:200]}')
    return ok


def subtitle_vtt(item: dict, sub_id: str) -> str | None:
    """Return a cached WebVTT file for ``sub_id`` on ``item``, building it if needed."""
    sub = next((s for s in item.get('subs') or [] if s.get('id') == sub_id), None)
    if not sub or not sub.get('text'):
        return None
    dest = os.path.join(SUB_DIR, f'{item["id"]}_{sub_id}.v{SUB_CACHE_VER}.vtt')
    if os.path.isfile(dest) and os.path.getsize(dest) > 16:
        return dest

    def _finish(path: str | None) -> str | None:
        """Tidy whatever was produced, in place."""
        if not path or not os.path.isfile(path):
            return None
        try:
            raw = _read_text(path)
            fixed = tidy_vtt(raw)
            if fixed and fixed != raw:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(fixed)
        except OSError as exc:
            _zyg_log.info(f'[Cinema] vtt tidy failed: {exc}')
        return path

    if sub['kind'] == 'external':
        src = sub.get('path') or ''
        if not os.path.isfile(src):
            return None
        ext = os.path.splitext(src)[1].lower()
        if ext == '.vtt':
            try:
                shutil.copyfile(src, dest)
                return _finish(dest)
            except OSError:
                return None
        if ext == '.srt':
            body = srt_to_vtt(_read_text(src))
            if len(body) > 16:
                try:
                    with open(dest, 'w', encoding='utf-8') as f:
                        f.write(body)
                    return _finish(dest)
                except OSError:
                    return None
            return None
        # .ass/.ssa/.sub — let ffmpeg do the styling maths.
        return _finish(dest) if _ffmpeg_to_vtt(['-i', src], dest) else None

    # Embedded text stream.
    return _finish(dest) if _ffmpeg_to_vtt(['-i', item['path'], '-map', f'0:s:{sub.get("stream", 0)}'], dest) else None
