#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin_mail.py — read a persona's own mailbox.

What it is for: the mail a platform sends to an account you already run. Sign-in codes when
a platform re-challenges a session, "confirm this device", and the weekly analytics digests
that several platforms only ever send by email. Reading it on the board beats hunting
through a webmail tab per persona.

Read-only by construction. There is no send, no reply, no delete, and no move — the only
IMAP verbs used are SEARCH and FETCH (BODY.PEEK, so reading here does not mark a message
seen in your real inbox). If a mailbox needs cleaning out, that is webmail's job.

**Verification links are handed to the persona's BROWSER, never fetched here.** A confirm
link is usually bound to the session or the exit IP that asked for it, so opening it from
this process — on this machine's address, outside the persona's cookie jar — is the one
sure way to make it fail. `open_link()` passes it to nomologin_browser instead, which puts
it in the tab it belongs to.

Credentials use the same Fernet keyfile as the TOTP seeds (~/nomologin/secrets.key, 0600).

Provider note, learned the hard way in an earlier mail client: **basic-auth IMAP is dead for
Microsoft personal accounts** — an @outlook/@hotmail/@msn mailbox needs OAuth, which this
module does not do. Gmail needs an app password with 2FA on, not the account password.
Most other providers still take an app password over IMAPS.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import logging as _zyg_logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_zero import nomologin as nl  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


MAILFILE = os.path.join(nl.ROOT, 'mail.json')

# A mailbox on a slow provider through a proxied exit is not fast. This is well under the
# board's own patience so a hung IMAP server surfaces as a message, not a spinning card.
IMAP_TIMEOUT = float(os.environ.get('ZYG_NOMOLOGIN_IMAP_TIMEOUT', '30'))

# Bodies are truncated before they ever reach a model. A marketing email is 200 KB of
# table markup and none of it is the code.
BODY_LIMIT = 8000


class MailError(RuntimeError):
    """Readable failures — a wrong password is a message, not a traceback."""


# ── config ────────────────────────────────────────────────────────────────────────────
def _store() -> dict:
    return nl._read_json(MAILFILE, {})


def configure(
    pid: str, host: str, user: str, password: str, port: int = 993, ssl: bool = True, folder: str = 'INBOX'
) -> dict:
    """Attach a mailbox to a persona. The password is encrypted at rest with the same key
    as the TOTP seeds; the file is 0600 like secrets.json."""
    nl.get_persona(pid)
    if not host or not user or not password:
        raise MailError('host, user and password are all required')
    f = nl._fernet()
    store = _store()
    store[pid] = {
        'host': host,
        'port': int(port),
        'user': user,
        'ssl': bool(ssl),
        'folder': folder,
        'pass': f.encrypt(password.encode()).decode(),
        'added': nl._iso(nl._now()),
    }
    nl._write_json(MAILFILE, store, mode=0o600)
    return {'ok': True, 'persona': pid, 'user': user, 'host': host}


def forget(pid: str) -> dict:
    store = _store()
    if store.pop(pid, None) is None:
        return {'ok': False, 'error': f'no mailbox configured for {pid}'}
    nl._write_json(MAILFILE, store, mode=0o600)
    return {'ok': True, 'persona': pid}


def config_for(pid: str) -> dict:
    cfg = _store().get(pid)
    if not cfg:
        raise MailError(f'no mailbox configured for {pid} — add one on the board first')
    return cfg


def configured() -> dict:
    """Which personas have mail, without decrypting anything."""
    return {pid: {'user': c.get('user'), 'host': c.get('host'), 'added': c.get('added')} for pid, c in _store().items()}


# ── connection ────────────────────────────────────────────────────────────────────────
class _Box:
    """A connection scoped to a `with`. IMAP servers cap concurrent sessions hard, and a
    leaked one locks the mailbox out of its next check."""

    def __init__(self, pid: str):
        self.cfg = config_for(pid)
        self.pid = pid
        self.imap: imaplib.IMAP4 | None = None

    def __enter__(self) -> imaplib.IMAP4:
        cfg = self.cfg
        try:
            if cfg.get('ssl', True):
                self.imap = imaplib.IMAP4_SSL(cfg['host'], cfg['port'], timeout=IMAP_TIMEOUT)
            else:
                self.imap = imaplib.IMAP4(cfg['host'], cfg['port'], timeout=IMAP_TIMEOUT)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise MailError(f'cannot reach {cfg["host"]}:{cfg["port"]} — {exc}') from exc
        try:
            password = nl._fernet().decrypt(cfg['pass'].encode()).decode()
            self.imap.login(cfg['user'], password)
        except imaplib.IMAP4.error as exc:
            detail = str(exc)
            hint = ''
            if re.search(r'outlook|hotmail|msn|live\.', cfg['host'] + cfg['user'], re.I):
                hint = (
                    ' — Microsoft personal accounts no longer accept basic-auth IMAP; '
                    'this needs OAuth, which this module does not do'
                )
            elif 'gmail' in cfg['host'].lower():
                hint = ' — Gmail needs an app password (2FA on), not the account password'
            raise MailError(f'login refused for {cfg["user"]}: {detail}{hint}') from exc
        try:
            self.imap.select(cfg.get('folder', 'INBOX'), readonly=True)
        except imaplib.IMAP4.error as exc:
            raise MailError(f'cannot open folder {cfg.get("folder")}: {exc}') from exc
        return self.imap

    def __exit__(self, *exc) -> None:
        if self.imap is not None:
            try:
                self.imap.close()
            except (imaplib.IMAP4.error, OSError) as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            try:
                self.imap.logout()
            except (imaplib.IMAP4.error, OSError) as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def check(pid: str) -> dict:
    """Connect and count. What the board's Test button calls."""
    try:
        with _Box(pid) as m:
            typ, data = m.search(None, 'ALL')
            total = len(data[0].split()) if typ == 'OK' and data[0] else 0
            typ, data = m.search(None, 'UNSEEN')
            unseen = len(data[0].split()) if typ == 'OK' and data[0] else 0
        cfg = config_for(pid)
        return {'ok': True, 'user': cfg['user'], 'messages': total, 'unseen': unseen}
    except MailError as exc:
        return {'ok': False, 'error': str(exc)}


# ── reading ───────────────────────────────────────────────────────────────────────────
def _decode(raw: str | None) -> str:
    """MIME-encoded headers, in whatever charset. A Cyrillic or Chinese subject is normal
    here — the seeding list spans 24 language groups."""
    if not raw:
        return ''
    out = []
    for text, enc in email.header.decode_header(raw):
        if isinstance(text, bytes):
            out.append(text.decode(enc or 'utf-8', 'replace'))
        else:
            out.append(text)
    return re.sub(r'\s+', ' ', ''.join(out)).strip()


def _strip_html(html: str) -> str:
    html = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html)
    html = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>', '\n', html)
    html = re.sub(r'(?s)<[^>]+>', ' ', html)
    for ent, ch in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'")):
        html = html.replace(ent, ch)
    return re.sub(r'[ \t]{2,}', ' ', re.sub(r'\n{3,}', '\n\n', html)).strip()


def _body(msg: email.message.Message) -> tuple[str, list[str]]:
    """Plain text preferred; HTML stripped as the fallback. Returns the text and every URL
    found, links from the HTML source included — a confirm button's href is the whole point
    and it does not survive tag-stripping."""
    text_parts, html_parts = [], []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get_filename():
            continue
        ctype = part.get_content_type()
        if ctype not in ('text/plain', 'text/html'):
            continue
        try:
            payload = part.get_payload(decode=True)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or 'utf-8'
        try:
            decoded = payload.decode(charset, 'replace')
        except LookupError:
            decoded = payload.decode('utf-8', 'replace')
        (text_parts if ctype == 'text/plain' else html_parts).append(decoded)

    html = '\n'.join(html_parts)
    body = '\n'.join(text_parts).strip() or _strip_html(html)
    urls = re.findall(r'href=["\']?(https?://[^"\'>\s]+)', html, re.I)
    urls += re.findall(r'(?<![\w"\'=])(https?://[^\s<>"\')]+)', body)
    seen, ordered = set(), []
    for u in urls:
        u = u.rstrip('.,;)')
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return body, ordered


def _summary(msg: email.message.Message, uid: str, seen: bool) -> dict:
    date = _decode(msg.get('Date'))
    try:
        when = email.utils.parsedate_to_datetime(msg.get('Date'))
        iso = when.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        iso = None
    return {
        'uid': uid,
        'from': _decode(msg.get('From')),
        'subject': _decode(msg.get('Subject')),
        'date': date,
        'iso': iso,
        'seen': seen,
    }


def recent(pid: str, n: int = 20, unread: bool = False, hours: float | None = None) -> list[dict]:
    """Newest first. Headers only — the body costs a second fetch and most of the time the
    subject line is the whole answer."""
    crit = ['UNSEEN'] if unread else ['ALL']
    if hours:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%d-%b-%Y')
        crit = ['SINCE', since] + (['UNSEEN'] if unread else [])
    out = []
    with _Box(pid) as m:
        # Criteria go as bytes: imaplib forces str args through an ascii codec, which
        # breaks the moment a term is not ascii. (The same trap caught an earlier mail client.)
        typ, data = m.search(None, *[c.encode() for c in crit])
        if typ != 'OK' or not data[0]:
            return []
        ids = data[0].split()[-max(1, n) :]
        for mid in reversed(ids):
            typ, fetched = m.fetch(mid, '(FLAGS BODY.PEEK[HEADER])')
            if typ != 'OK' or not fetched or not isinstance(fetched[0], tuple):
                continue
            flags = fetched[0][0].decode('latin-1', 'replace')
            msg = email.message_from_bytes(fetched[0][1])
            out.append(_summary(msg, mid.decode(), '\\Seen' in flags))
    return out


def message(pid: str, uid: str, limit: int = BODY_LIMIT) -> dict:
    """One message, whole. BODY.PEEK so reading it here does not mark it read for you."""
    with _Box(pid) as m:
        typ, fetched = m.fetch(str(uid).encode(), '(BODY.PEEK[])')
        if typ != 'OK' or not fetched or not isinstance(fetched[0], tuple):
            raise MailError(f'no message with uid {uid}')
        msg = email.message_from_bytes(fetched[0][1])
    body, urls = _body(msg)
    out = _summary(msg, str(uid), True)
    out.update(
        chars=len(body),
        truncated=len(body) > limit,
        text=body[:limit],
        urls=urls[:40],
        codes=find_codes(body, out.get('subject', '')),
    )
    return out


# ── the useful bit: codes and confirm links ───────────────────────────────────────────
# Kept deliberately narrow. A bare 6-digit run appears in order numbers, prices and dates;
# what marks a sign-in code is the words around it, in whatever language the platform sends.
_CODE_WORDS = (
    r'code|codice|c[oó]digo|kode|kod|c[ée]digo|verification|verificatie|verifica|'
    r'verify|bevestig|confirm|confirma|best[aä]tig|security|beveiliging|one[- ]?time|'
    r'einmal|otp|pin|passcode|token|autentica|auth|anmeld|connexion|iniciar|'
    r'код|проверк|パスコード|認証|验证|驗證|인증'
)
_CODE_RE = re.compile(
    r'(?:(?:' + _CODE_WORDS + r')[^\n\d]{0,60}?\b(\d{4,8})\b)'
    r'|(?:\b(\d{4,8})\b[^\n\d]{0,40}?(?:' + _CODE_WORDS + r'))',
    re.I | re.U,
)
_ALNUM_RE = re.compile(r'(?:' + _CODE_WORDS + r')[^\n]{0,40}?\b([A-Z0-9]{5,8})\b', re.I | re.U)

_LINK_WORDS = re.compile(
    r'verify|verif|confirm|activate|activation|valid|magic|signin|sign-in|login|'
    r'auth|token|bevestig|bestatig|best%C3%A4tig|confirma|aktiv',
    re.I,
)


def find_codes(text: str, subject: str = '') -> list[str]:
    """Every plausible code, most likely first. Returns candidates, not a verdict — the
    operator or the assistant picks, because guessing wrong and typing it into a live login
    form burns an attempt."""
    found: list[str] = []
    for blob in (subject, text):
        for m in _CODE_RE.finditer(blob or ''):
            code = m.group(1) or m.group(2)
            if code and code not in found:
                found.append(code)
        for m in _ALNUM_RE.finditer(blob or ''):
            code = m.group(1)
            if code and not code.isdigit() and code not in found:
                found.append(code)
    return found[:6]


def verification_links(urls: list[str]) -> list[str]:
    return [u for u in urls if _LINK_WORDS.search(u)][:10]


def codes(pid: str, minutes: float = 30.0, n: int = 12) -> dict:
    """Scan the newest mail for sign-in codes and confirm links.

    The window is short by default and stated in the result. A code from two hours ago has
    almost certainly expired, and handing a stale one to a login form looks exactly like a
    failed attempt to the platform.
    """
    hours = max(minutes / 60.0, 1 / 60.0)
    heads = recent(pid, n=n, hours=hours)
    cutoff = time.time() - minutes * 60
    hits = []
    for h in heads:
        if h.get('iso'):
            try:
                if datetime.fromisoformat(h['iso']).timestamp() < cutoff:
                    continue
            except ValueError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        full = message(pid, h['uid'])
        cs = full.get('codes') or []
        links = verification_links(full.get('urls') or [])
        if cs or links:
            hits.append(
                {
                    'uid': h['uid'],
                    'from': h['from'],
                    'subject': h['subject'],
                    'date': h['date'],
                    'codes': cs,
                    'links': links,
                }
            )
    return {
        'ok': True,
        'window_minutes': minutes,
        'scanned': len(heads),
        'hits': hits,
        'note': 'codes expire fast — check the timestamp before using one',
    }


def open_link(pid: str, url: str, tab: str | int | None = None) -> dict:
    """Open a confirm link in the PERSONA'S browser, which is the only place it works.

    These links are routinely bound to the session or the exit IP that requested them.
    Fetching one from this process would hit it from this machine's address, outside the
    persona's cookie jar — which either fails outright or, worse, confirms against the
    wrong session.
    """
    from zyg_zero import nomologin_browser as nb

    if not url.startswith(('http://', 'https://')):
        raise MailError(f'not a link: {url[:80]}')
    return nb.act(pid, 'navigate', url=url, tab=tab)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="read a persona's mailbox (read-only)")
    ap.add_argument('persona')
    ap.add_argument(
        'action', nargs='?', default='check', help='check | recent | codes | read <uid> | configure | forget | list'
    )
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--host'), ap.add_argument('--user'), ap.add_argument('--password')
    ap.add_argument('--port', type=int, default=993)
    ap.add_argument('--minutes', type=float, default=30.0)
    ap.add_argument('-n', type=int, default=20)
    ap.add_argument('--unread', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.action == 'list':
            out = configured()
        elif a.action == 'configure':
            out = configure(a.persona, a.host, a.user, a.password, a.port)
        elif a.action == 'forget':
            out = forget(a.persona)
        elif a.action == 'check':
            out = check(a.persona)
        elif a.action == 'recent':
            out = recent(a.persona, a.n, a.unread)
        elif a.action == 'codes':
            out = codes(a.persona, a.minutes)
        elif a.action == 'read':
            out = message(a.persona, a.rest[0])
        else:
            out = {'ok': False, 'error': f'unknown action {a.action}'}
    except (MailError, IndexError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False)[:20000])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
