# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging as _zyg_logging
import os
import random

from zyg_workflows.web_research_agent.constants import _PAGE_LOAD_TIMEOUT
from zyg_workflows.web_research_agent.playwright_adapter import _PlaywrightAdapter

_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')


class _BrowserSetupMixin:
    """WebResearchAgent's browser-setup section, moved verbatim out of the 1,400-line file."""

    # ── Browser setup ─────────────────────────────────────────────────────────

    def _setup_browser(self):
        """Browser waterfall: Playwright → Selenium (undetected_chromedriver).
        Sets self.driver to whichever succeeds first; sets self._browser_engine."""
        # ── 1. Playwright ──────────────────────────────────────────────────────
        try:
            from playwright.sync_api import sync_playwright

            self._log('INFO', 'Trying Playwright (Chromium)...')
            _pw = sync_playwright().start()
            _browser = _pw.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    f'--window-size={random.randint(1280, 1920)},{random.randint(800, 1080)}',
                ],
            )
            _ctx = _browser.new_context(
                user_agent=self._ua,
                locale='en-US',
                viewport={'width': random.randint(1280, 1920), 'height': random.randint(800, 1080)},
                java_script_enabled=True,
            )
            _ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            _page = _ctx.new_page()
            _page.set_default_timeout(_PAGE_LOAD_TIMEOUT * 1000)
            self.driver = _PlaywrightAdapter(_page, _browser, _pw)
            self._browser_engine = 'playwright'
            self._log('INFO', 'Playwright launched OK')
            # Register browser PID so _kill_all_subprocs() can terminate it on stop
            try:
                _bpid = _browser.process.pid
                if _bpid:
                    self._browser_pid = _bpid
                    self._log_fn('INFO', 'Stage 2 / Browser', f'Browser PID registered: {_bpid}')
            except Exception:
                self._browser_pid = None
            return
        except Exception as _pw_err:
            self._log('WARNING', f'Playwright unavailable ({_pw_err}) — falling back to Selenium')

        # ── 2. Selenium / undetected_chromedriver ─────────────────────────────
        import subprocess as _sp_disp
        import tempfile
        import undetected_chromedriver as uc

        _chrome_version = 146
        try:
            _cv = _sp_disp.run(['google-chrome', '--version'], capture_output=True, text=True, timeout=5)
            _chrome_version = int(_cv.stdout.strip().split()[-1].split('.')[0])
        except Exception as _exc:
            _zyg_log.warning('chrome version probe failed, assuming v%s for the driver: %s', _chrome_version, _exc)

        self._log('INFO', f'Launching Selenium/Chrome v{_chrome_version} (UA: {self._ua[:40]}...)')

        opts = uc.ChromeOptions()

        _display = os.environ.get('DISPLAY', '')
        _has_display = False
        if _display:
            try:
                _test = _sp_disp.run(['xdpyinfo', '-display', _display], capture_output=True, timeout=3)
                _has_display = _test.returncode == 0
            except Exception as _exc:
                _zyg_log.debug('display %s probe failed, going headless: %s', _display, _exc)

        if _has_display:
            os.environ['DISPLAY'] = _display
            self._log('INFO', f'Using visible display {_display}')
        else:
            opts.add_argument('--headless=new')
            self._log('INFO', 'No accessible display — running headless')

        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_argument(f'--user-agent={self._ua}')
        opts.add_argument(f'--window-size={random.randint(1280, 1920)},{random.randint(800, 1080)}')
        opts.add_argument('--disable-infobars')
        opts.add_argument('--disable-extensions')
        opts.add_argument('--no-first-run')
        opts.add_argument('--disable-default-apps')
        opts.add_argument('--disable-popup-blocking')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--lang=en-US,en;q=0.9')
        opts.add_argument('--disable-notifications')

        _profile_dir = tempfile.mkdtemp(prefix='zyg_chrome_')
        opts.add_argument(f'--user-data-dir={_profile_dir}')

        self.driver = uc.Chrome(options=opts, version_main=_chrome_version, use_subprocess=True)
        self.driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT)
        self.driver.implicitly_wait(5)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self._browser_engine = 'selenium'
        self._log('INFO', 'Selenium/Chrome launched OK')
        try:
            self._browser_pid = self.driver.service.process.pid
            self._log_fn('INFO', 'Stage 2 / Browser', f'Browser PID registered: {self._browser_pid}')
        except Exception:
            self._browser_pid = None

    def _teardown_browser(self):
        self._shutdown = True
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
        except Exception as _exc:
            _zyg_log.warning('browser teardown failed, a chrome process may be left running: %s', _exc)
