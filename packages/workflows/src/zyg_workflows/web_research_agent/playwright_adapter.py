# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')

# ── Playwright adapter — makes Playwright look like a Selenium WebDriver ─────
# All research methods use self.driver which is either this adapter or real
# Selenium, so zero research code needs to change.


class _PlaywrightElement:
    """Wraps a Playwright ElementHandle to match the Selenium WebElement API."""

    def __init__(self, el):
        self._el = el

    @property
    def text(self):
        try:
            return self._el.inner_text() or ''
        except Exception:
            return ''

    def get_attribute(self, name):
        try:
            return self._el.get_attribute(name)
        except Exception:
            return None

    def is_displayed(self):
        try:
            return self._el.is_visible()
        except Exception:
            return False

    def click(self):
        try:
            self._el.click()
        except Exception as _exc:
            _zyg_log.debug('element click did not land: %s', _exc)

    def clear(self):
        try:
            self._el.fill('')
        except Exception as _exc:
            _zyg_log.debug('element clear did not land: %s', _exc)

    def send_keys(self, text):
        # Map common Selenium special keys to Playwright key names
        _KEY_MAP = {
            '\ue006': 'Enter',
            '\ue007': 'Enter',
            '\n': 'Enter',
            '\ue003': 'Backspace',
            '\ue008': 'Shift',
            '\ue00d': 'Enter',
        }
        if text in _KEY_MAP:
            try:
                self._el.press(_KEY_MAP[text])
            except Exception as _exc:
                _zyg_log.debug('key press %r did not land: %s', _KEY_MAP[text], _exc)
        else:
            try:
                self._el.type(str(text), delay=55)
            except Exception as _exc:
                _zyg_log.debug('typing into the element did not land: %s', _exc)


class _PlaywrightAdapter:
    """Wraps a Playwright sync page to match the Selenium WebDriver API."""

    def __init__(self, page, browser, pw_ctx):
        self._page = page
        self._browser = browser
        self._pw = pw_ctx
        self._timeout = 30000  # ms

    # ── Core driver interface ─────────────────────────────────────────────────

    @property
    def page_source(self):
        try:
            return self._page.content()
        except Exception:
            return ''

    @property
    def title(self):
        try:
            return self._page.title()
        except Exception:
            return ''

    @property
    def current_url(self):
        try:
            return self._page.url
        except Exception:
            return ''

    def get(self, url):
        # Resolve relative URLs against Wikipedia base (Playwright requires full URLs)
        if url.startswith('/wiki/') or (url.startswith('/') and not url.startswith('//')):
            current = self._page.url or ''
            import urllib.parse as _up_pw

            base = _up_pw.urlparse(current)
            url = f'{base.scheme}://{base.netloc}{url}' if base.netloc else f'https://en.wikipedia.org{url}'
        self._page.goto(url, timeout=self._timeout, wait_until='domcontentloaded')

    def set_page_load_timeout(self, seconds):
        self._timeout = int(seconds) * 1000

    def implicitly_wait(self, seconds):
        pass  # Playwright uses explicit waits; nothing needed here

    def execute_script(self, script, *args):
        try:
            return self._page.evaluate(script)
        except Exception:
            return None

    def quit(self):
        try:
            self._browser.close()
        except Exception as _exc:
            _zyg_log.debug('playwright browser was already closed: %s', _exc)
        try:
            self._pw.stop()
        except Exception as _exc:
            _zyg_log.debug('playwright driver was already stopped: %s', _exc)

    # ── Element lookup ────────────────────────────────────────────────────────

    def _to_playwright_selector(self, by, value):
        """Convert Selenium By + value to a Playwright CSS/xpath selector."""
        from selenium.webdriver.common.by import By as _By

        if by == _By.ID:
            return f'#{value}'
        if by == _By.NAME:
            return f'[name="{value}"]'
        if by == _By.TAG_NAME:
            return value
        if by == _By.CLASS_NAME:
            return f'.{value}'
        if by == _By.XPATH:
            return f'xpath={value}'
        return value  # CSS_SELECTOR

    def find_elements(self, by, value):
        try:
            sel = self._to_playwright_selector(by, value)
            return [_PlaywrightElement(e) for e in self._page.query_selector_all(sel)]
        except Exception:
            return []

    def find_element(self, by, value):
        sel = self._to_playwright_selector(by, value)
        el = self._page.query_selector(sel)
        if el is None:
            from selenium.common.exceptions import NoSuchElementException

            raise NoSuchElementException(f'No element: {sel}')
        return _PlaywrightElement(el)
