# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for zyg_zero.nomologin_mail.

No real mailbox is ever opened: imaplib's two connection classes are replaced by a factory
that hands back a canned server, the Fernet keyfile by an in-memory fake, and the config
file by one under tmp_path.
"""

from __future__ import annotations

import email.utils
import imaplib
import json
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from zyg_zero import nomologin as nl
from zyg_zero import nomologin_mail as mod

_IMAP_ERROR = imaplib.IMAP4.error


# ── doubles ───────────────────────────────────────────────────────────────────────────
class _FakeFernet:
    """Reversible, keyless. The real one writes a 0600 keyfile under ~/nomologin."""

    def encrypt(self, raw: bytes) -> bytes:
        return b'enc:' + raw

    def decrypt(self, token: bytes) -> bytes:
        if not token.startswith(b'enc:'):
            raise ValueError('bad token')
        return token[4:]


class FakeBox:
    """Answers the only verbs _Box uses: login, select, search, fetch, close, logout."""

    def __init__(self) -> None:
        self.host = self.port = self.timeout = None
        self.user = self.password = None
        self.login_error = None
        self.select_error = None
        self.close_error = None
        self.logout_error = None
        self.search_map: dict[str, tuple] = {}
        self.messages: dict[str, tuple[str, bytes]] = {}
        self.flat: set[str] = set()
        self.uids: list[bytes] = []
        self.searches: list[str] = []
        self.fetches: list[tuple[str, str]] = []
        self.selected = None
        self.closed = False
        self.logged_out = False

    def login(self, user, password):
        self.user, self.password = user, password
        if self.login_error is not None:
            raise self.login_error
        return ('OK', [b'welcome'])

    def select(self, folder, readonly=False):
        if self.select_error is not None:
            raise self.select_error
        self.selected = (folder, readonly)
        return ('OK', [b'3'])

    def search(self, charset, *crit):
        key = ' '.join(c.decode() if isinstance(c, bytes) else str(c) for c in crit)
        self.searches.append(key)
        for prefix, result in self.search_map.items():
            if key.startswith(prefix):
                return result
        return ('OK', [b' '.join(self.uids)])

    def fetch(self, mid, parts):
        uid = mid.decode() if isinstance(mid, bytes) else str(mid)
        self.fetches.append((uid, parts))
        if uid in self.flat:
            return ('OK', [b'untagged junk, not a (header, body) pair'])
        item = self.messages.get(uid)
        if item is None:
            return ('NO', [None])
        flags, raw = item
        head = f'{uid} (FLAGS ({flags}) BODY[] {{{len(raw)}}}'.encode()
        return ('OK', [(head, raw), b')'])

    def close(self):
        if self.close_error is not None:
            raise self.close_error
        self.closed = True

    def logout(self):
        if self.logout_error is not None:
            raise self.logout_error
        self.logged_out = True


class _Factory:
    """Stands in for imaplib.IMAP4_SSL / imaplib.IMAP4 — an instance, so that the module's
    `except imaplib.IMAP4.error` still resolves to the real exception class."""

    error = _IMAP_ERROR

    def __init__(self, box: FakeBox, connect_error: BaseException | None = None) -> None:
        self.box = box
        self.connect_error = connect_error

    def __call__(self, host, port=993, timeout=None):
        if self.connect_error is not None:
            raise self.connect_error
        self.box.host, self.box.port, self.box.timeout = host, port, timeout
        return self.box


def _install(monkeypatch, box: FakeBox, *, ssl: bool = True, connect_error=None) -> FakeBox:
    monkeypatch.setattr(imaplib, 'IMAP4_SSL' if ssl else 'IMAP4', _Factory(box, connect_error))
    return box


# ── fixtures / helpers ────────────────────────────────────────────────────────────────
@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect the config file and the secret key away from ~/nomologin."""
    monkeypatch.setattr(mod, 'MAILFILE', str(tmp_path / 'root' / 'mail.json'))
    monkeypatch.setattr(nl, '_fernet', _FakeFernet)
    monkeypatch.setattr(nl, 'get_persona', lambda pid: {'id': pid})
    return tmp_path


def _configure(pid='ada', host='imap.example.com', user='ada@example.com', **kw):
    return mod.configure(pid, host, user, 'app-password', **kw)


def _when(kind):
    now = datetime.now(timezone.utc)
    return {
        'now': lambda: email.utils.format_datetime(now),
        'old': lambda: email.utils.format_datetime(now - timedelta(hours=3)),
        'broken': lambda: 'yesterday-ish',
    }[kind]()


def _plain(subject, text, *, frm='Security <sec@example.com>', when='now'):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = frm
    if when is not None:
        msg['Date'] = _when(when)
    msg.set_content(text)
    return msg.as_bytes()


def _rich():
    """text/plain + text/html alternative + an attachment + an inline image part."""
    msg = EmailMessage()
    msg['Subject'] = '=?utf-8?q?C=C3=B3digo?= de verificacion'
    msg['From'] = '=?utf-8?q?Seguridad?= <sec@example.com>'
    msg['Date'] = _when('now')
    msg.set_content('Your verification code is 483920.\nSee https://example.com/plain?ref=1 for help.\n')
    msg.add_alternative(
        '<html><head><style>b{color:red}</style><script>var x=1</script></head>'
        '<body><p>code&nbsp;483920</p><div>Order &amp; 10024599</div>'
        '<a href="https://example.com/verify?t=abc">Confirm</a><br/>'
        '<a href="https://example.com/unsubscribe">Out</a></body></html>',
        subtype='html',
    )
    msg.add_attachment(b'\x00pdf', maintype='application', subtype='pdf', filename='statement.pdf')
    msg.add_attachment(b'\x00png', maintype='image', subtype='png')
    return msg.as_bytes()


_BAD_CHARSET = (
    b'From: Sec <sec@example.com>\r\n'
    b'Subject: Codigo\r\n'
    b'Content-Type: text/plain; charset="definitely-not-a-charset"\r\n'
    b'\r\n'
    b'your code 778812\r\n'
)

_HTML_ONLY = (
    b'From: Sec <sec@example.com>\r\n'
    b'Subject: Confirm\r\n'
    b'Content-Type: text/html; charset="utf-8"\r\n'
    b'\r\n'
    b'<div>Your  passcode is 4455</div><p>bye</p>\r\n'
)

_EMPTY_PART = b'From: Sec <sec@example.com>\r\nSubject: Nothing\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\n'


# ── config ────────────────────────────────────────────────────────────────────────────
def test_configure_then_list_then_forget(store):
    out = _configure(port=1993, ssl=False, folder='Archive')
    assert out == {'ok': True, 'persona': 'ada', 'user': 'ada@example.com', 'host': 'imap.example.com'}

    cfg = mod.config_for('ada')
    assert cfg['port'] == 1993 and cfg['ssl'] is False and cfg['folder'] == 'Archive'
    assert cfg['pass'] == 'enc:app-password'

    listed = mod.configured()
    assert listed['ada']['user'] == 'ada@example.com'
    assert listed['ada']['host'] == 'imap.example.com'
    assert listed['ada']['added']

    assert mod.forget('ada') == {'ok': True, 'persona': 'ada'}
    assert mod.forget('ada') == {'ok': False, 'error': 'no mailbox configured for ada'}
    assert mod.configured() == {}
    with pytest.raises(mod.MailError, match='no mailbox configured for ada'):
        mod.config_for('ada')


@pytest.mark.parametrize(
    'host,user,password',
    [('', 'u', 'p'), ('h', '', 'p'), ('h', 'u', '')],
)
def test_configure_requires_host_user_password(store, host, user, password):
    with pytest.raises(mod.MailError, match='all required'):
        mod.configure('ada', host, user, password)


# ── connection ────────────────────────────────────────────────────────────────────────
def test_check_counts_total_and_unseen(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.search_map = {'ALL': ('OK', [b'1 2 3 4']), 'UNSEEN': ('OK', [b'3 4'])}

    assert mod.check('ada') == {'ok': True, 'user': 'ada@example.com', 'messages': 4, 'unseen': 2}
    assert box.host == 'imap.example.com' and box.port == 993
    assert box.timeout == mod.IMAP_TIMEOUT
    assert box.selected == ('INBOX', True)
    assert box.closed and box.logged_out


def test_check_on_an_empty_mailbox(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.search_map = {'ALL': ('OK', [b'']), 'UNSEEN': ('NO', [None])}
    assert mod.check('ada') == {'ok': True, 'user': 'ada@example.com', 'messages': 0, 'unseen': 0}


def test_check_without_a_mailbox_is_a_message(store):
    assert mod.check('nobody') == {
        'ok': False,
        'error': 'no mailbox configured for nobody — add one on the board first',
    }


@pytest.mark.parametrize(
    'host,user,hint',
    [
        ('imap.example.com', 'ada@example.com', ''),
        ('outlook.office365.com', 'ada@example.com', 'OAuth'),
        ('imap.gmail.com', 'ada@example.org', 'app password'),
    ],
)
def test_login_refused_carries_the_provider_hint(store, monkeypatch, host, user, hint):
    _configure(host=host, user=user)
    box = _install(monkeypatch, FakeBox())
    box.login_error = _IMAP_ERROR('AUTHENTICATIONFAILED')

    res = mod.check('ada')
    assert res['ok'] is False
    assert f'login refused for {user}' in res['error']
    assert 'AUTHENTICATIONFAILED' in res['error']
    if hint:
        assert hint in res['error']
    else:
        assert '—' not in res['error'].split('AUTHENTICATIONFAILED', 1)[1]


def test_unreachable_host_is_a_message(store, monkeypatch):
    _configure()
    _install(monkeypatch, FakeBox(), connect_error=OSError('connection refused'))
    res = mod.check('ada')
    assert res == {'ok': False, 'error': 'cannot reach imap.example.com:993 — connection refused'}


def test_plain_imap_and_an_unopenable_folder(store, monkeypatch):
    _configure(ssl=False, port=143, folder='Spam')
    box = _install(monkeypatch, FakeBox(), ssl=False)
    box.select_error = _IMAP_ERROR('NONEXISTENT')

    res = mod.check('ada')
    assert res == {'ok': False, 'error': 'cannot open folder Spam: NONEXISTENT'}
    assert box.port == 143


def test_a_closing_connection_that_errors_is_suppressed(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.search_map = {'ALL': ('OK', [b'1']), 'UNSEEN': ('OK', [b''])}
    box.close_error = _IMAP_ERROR('BYE already')
    box.logout_error = OSError('socket gone')

    assert mod.check('ada')['messages'] == 1
    assert not box.closed and not box.logged_out


# ── reading ───────────────────────────────────────────────────────────────────────────
def test_recent_is_newest_first_with_flags_and_decoded_headers(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.uids = [b'1', b'2', b'3']
    box.messages = {
        '1': ('', _plain('one', 'hello')),
        '2': ('\\Seen', _plain('=?utf-8?q?C=C3=B3digo?= 483920', 'hello')),
        '3': ('', _plain('three', 'hello', when='broken')),
    }

    out = mod.recent('ada')
    assert [m['uid'] for m in out] == ['3', '2', '1']
    assert out[1]['subject'] == 'Código 483920'
    assert out[1]['seen'] is True and out[0]['seen'] is False
    assert out[0]['iso'] is None  # unparseable Date
    assert out[2]['iso'] is not None
    assert box.searches == ['ALL']


def test_recent_honours_n_unread_and_the_hours_window(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.uids = [b'1', b'2', b'3']
    box.messages = {str(i): ('', _plain(f's{i}', 'x')) for i in (1, 2, 3)}

    assert [m['uid'] for m in mod.recent('ada', n=2)] == ['3', '2']
    assert [m['uid'] for m in mod.recent('ada', n=0)] == ['3']

    mod.recent('ada', unread=True)
    mod.recent('ada', hours=2)
    mod.recent('ada', unread=True, hours=2)
    assert box.searches[-3] == 'UNSEEN'
    assert box.searches[-2].startswith('SINCE ')
    assert box.searches[-1].startswith('SINCE ') and box.searches[-1].endswith(' UNSEEN')


@pytest.mark.parametrize('result', [('NO', [b'1']), ('OK', [b'']), ('OK', [None])])
def test_recent_returns_nothing_when_search_finds_nothing(store, monkeypatch, result):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.search_map = {'ALL': result}
    assert mod.recent('ada') == []


def test_recent_skips_messages_the_server_will_not_hand_over(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.uids = [b'1', b'2', b'3']
    box.flat = {'2'}  # fetched, but not as a (header, body) pair
    box.messages = {'1': ('', _plain('one', 'x'))}  # 3 is missing entirely -> NO
    assert [m['uid'] for m in mod.recent('ada')] == ['1']


def test_message_returns_body_urls_and_codes(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.messages = {'7': ('\\Seen', _rich())}

    out = mod.message('ada', 7)
    assert out['uid'] == '7' and out['seen'] is True
    assert out['subject'] == 'Código de verificacion'
    assert out['from'] == 'Seguridad <sec@example.com>'
    assert 'Your verification code is 483920.' in out['text']
    assert out['truncated'] is False and out['chars'] == len(out['text'])
    assert out['urls'][0] == 'https://example.com/verify?t=abc'
    assert 'https://example.com/plain?ref=1' in out['urls']
    assert out['codes'][0] == '483920'
    assert box.fetches == [('7', '(BODY.PEEK[])')]


def test_message_truncates_at_the_limit(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.messages = {'7': ('', _plain('long', 'x' * 500))}

    out = mod.message('ada', '7', limit=100)
    assert out['truncated'] is True and len(out['text']) == 100 and out['chars'] == 500


def test_message_for_an_unknown_uid_raises(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.flat = {'9'}
    with pytest.raises(mod.MailError, match='no message with uid 404'):
        mod.message('ada', '404')
    with pytest.raises(mod.MailError, match='no message with uid 9'):
        mod.message('ada', '9')


@pytest.mark.parametrize(
    'raw,wanted,codes',
    [
        (_HTML_ONLY, 'Your passcode is 4455', ['4455']),
        (_BAD_CHARSET, 'your code 778812', ['778812']),
        (_EMPTY_PART, '', []),
    ],
)
def test_message_bodies_that_need_the_fallbacks(store, monkeypatch, raw, wanted, codes):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.messages = {'1': ('', raw)}

    out = mod.message('ada', '1')
    assert wanted in out['text']
    assert out['codes'] == codes
    assert out['iso'] is None  # no Date header at all


# ── codes and links ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    'text,subject,expected',
    [
        ('Your verification code is 483920.', '', ['483920']),
        ('', 'Code: 1234', ['1234']),
        # the alnum rule is deliberately loose: it offers the word after the cue as a
        # candidate too, because several platforms send letter-digit codes
        ('483920 is your one-time password', '', ['483920', 'password']),
        ('Tu código es 55218', '', ['55218']),
        ('Ваш код: 904112', '', ['904112']),
        ('認証コード 220418', '', ['220418']),
        ('Order 10024599 shipped on 2026-10-22 for 1999', '', []),
        ('Use code ABC12DE to confirm', '', ['ABC12DE']),
        ('code 111222 and code 333444', '', ['111222', '333444']),
        ('code 111222 and verification 111222', '', ['111222']),
    ],
)
def test_find_codes(text, subject, expected):
    assert mod.find_codes(text, subject) == expected


def test_find_codes_returns_at_most_six():
    text = ' '.join(f'code {1000 + i}' for i in range(12))
    assert len(mod.find_codes(text)) == 6


def test_find_codes_on_nothing():
    assert mod.find_codes('') == []


def test_verification_links_keeps_only_the_plausible_ones():
    urls = [
        'https://example.com/verify?t=1',
        'https://example.com/pictures/cat.png',
        'https://example.com/confirm-device',
        'https://example.com/auth/magic',
        'https://example.com/unrelated',
    ]
    assert mod.verification_links(urls) == [
        'https://example.com/verify?t=1',
        'https://example.com/confirm-device',
        'https://example.com/auth/magic',
    ]
    assert mod.verification_links([]) == []
    assert len(mod.verification_links([f'https://e.com/verify/{i}' for i in range(20)])) == 10


def test_codes_scans_the_window_and_drops_stale_mail(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.uids = [b'1', b'2', b'3']
    box.messages = {
        '1': ('', _rich()),
        '2': ('', _plain('Newsletter', 'Nothing interesting at all.')),
        '3': ('', _plain('Old code 999111', 'Your code is 999111', when='old')),
    }

    out = mod.codes('ada', minutes=30)
    assert out['ok'] is True and out['window_minutes'] == 30
    assert out['scanned'] == 3  # three headers read
    assert [h['uid'] for h in out['hits']] == ['1']  # 2 has nothing, 3 is stale
    hit = out['hits'][0]
    assert hit['codes'] == ['483920']
    assert hit['links'] == ['https://example.com/verify?t=abc']
    assert hit['subject'] == 'Código de verificacion'
    assert 'expire fast' in out['note']
    assert box.searches[0].startswith('SINCE ')


def test_codes_keeps_a_message_whose_date_it_cannot_parse(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.messages = {'5': ('', _plain('Codigo', 'your code is 606060'))}
    monkeypatch.setattr(
        mod,
        'recent',
        lambda pid, n=20, hours=None: [{'uid': '5', 'from': 'a@b.c', 'subject': 's', 'date': 'd', 'iso': 'not-a-date'}],
    )

    out = mod.codes('ada', minutes=1)
    assert [h['codes'] for h in out['hits']] == [['606060']]


def test_codes_on_an_empty_window(store, monkeypatch):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.search_map = {'SINCE': ('OK', [b''])}
    assert mod.codes('ada') == {
        'ok': True,
        'window_minutes': 30.0,
        'scanned': 0,
        'hits': [],
        'note': 'codes expire fast — check the timestamp before using one',
    }


# ── open_link ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_browser(monkeypatch):
    calls = []

    def act(pid, verb, **kw):
        calls.append((pid, verb, kw))
        return {'ok': True, 'tab': kw.get('tab')}

    monkeypatch.setitem(sys.modules, 'zyg_zero.nomologin_browser', SimpleNamespace(act=act))
    return calls


def test_open_link_hands_the_url_to_the_personas_browser(store, fake_browser):
    assert mod.open_link('ada', 'https://example.com/verify?t=1', tab=2) == {'ok': True, 'tab': 2}
    assert fake_browser == [('ada', 'navigate', {'url': 'https://example.com/verify?t=1', 'tab': 2})]


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'ftp://example.com/x', ''])
def test_open_link_refuses_anything_that_is_not_http(store, fake_browser, url):
    with pytest.raises(mod.MailError, match='not a link'):
        mod.open_link('ada', url)
    assert fake_browser == []


# ── cli ───────────────────────────────────────────────────────────────────────────────
def _out(capsys):
    return json.loads(capsys.readouterr().out)


def test_main_configure_list_forget(store, capsys):
    argv = ['ada', 'configure', '--host', 'imap.example.com', '--user', 'ada@example.com', '--password', 'pw']
    assert mod.main(argv) == 0
    assert _out(capsys)['ok'] is True

    assert mod.main(['ada', 'list']) == 0
    assert _out(capsys)['ada']['host'] == 'imap.example.com'

    assert mod.main(['ada', 'forget']) == 0
    assert _out(capsys)['ok'] is True


def test_main_configure_without_credentials_fails(store, capsys):
    assert mod.main(['ada', 'configure']) == 1
    assert _out(capsys) == {'ok': False, 'error': 'host, user and password are all required'}


def test_main_check_recent_read_codes(store, monkeypatch, capsys):
    _configure()
    box = _install(monkeypatch, FakeBox())
    box.uids = [b'1']
    box.messages = {'1': ('', _rich())}

    assert mod.main(['ada']) == 0  # default action is check
    assert _out(capsys)['messages'] == 1

    assert mod.main(['ada', 'recent', '-n', '1', '--unread']) == 0
    assert [m['uid'] for m in _out(capsys)] == ['1']

    assert mod.main(['ada', 'read', '1']) == 0
    assert _out(capsys)['codes'] == ['483920']

    assert mod.main(['ada', 'codes', '--minutes', '45']) == 0
    assert _out(capsys)['window_minutes'] == 45.0


def test_main_read_without_a_uid_fails(store, monkeypatch, capsys):
    _configure()
    _install(monkeypatch, FakeBox())
    assert mod.main(['ada', 'read']) == 1
    assert _out(capsys) == {'ok': False, 'error': 'list index out of range'}


def test_main_unknown_action(store, capsys):
    assert mod.main(['ada', 'sendmail']) == 0
    assert _out(capsys) == {'ok': False, 'error': 'unknown action sendmail'}
