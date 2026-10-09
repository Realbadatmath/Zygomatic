# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging as _zyg_logging
import random
import time

from zyg_workflows.web_research_agent.constants import (
    _CAPTCHA_SIGNALS,
    _COOKIE_BUTTON_TEXTS,
    _PAYWALL_SIGNALS,
    _after_load,
    _micro_pause,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')


class _PageHelpersMixin:
    """WebResearchAgent's page-interaction helpers, moved verbatim."""

    # ── Page interaction helpers ───────────────────────────────────────────────

    def _safe_get(self, url):
        """Navigate to URL, return True on success. Bails out if stop flagged."""
        if self._is_stopped():
            return False
        # Resolve protocol-relative and relative URLs before navigating
        if url and url.startswith('//'):
            url = 'https:' + url
        elif url and url.startswith('/') and self.driver is not None:
            try:
                import urllib.parse as _up_sg

                _base = _up_sg.urlparse(self.driver.current_url or '')
                if _base.netloc:
                    url = f'{_base.scheme}://{_base.netloc}{url}'
            except Exception as _exc:
                _zyg_log.debug('could not absolutise %s against the current page: %s', url, _exc)
        try:
            self.driver.get(url)
            _after_load()
            return True
        except Exception as e:
            self._log('WARNING', f'Page load failed: {url[:60]} — {e}')
            return False

    def _human_type(self, element, text):
        """Type text character by character with human-like timing."""
        element.clear()
        for char in text:
            element.send_keys(char)
            time.sleep(max(0.01, random.gauss(0.055, 0.025)))

    def _human_scroll(self, total_px=1500, steps=8):
        """Scroll down in human-like chunks."""
        step_px = total_px // steps
        for _ in range(steps):
            self.driver.execute_script(f'window.scrollBy(0, {step_px + random.randint(-30, 30)})')
            time.sleep(max(0.1, random.gauss(0.5, 0.15)))

    def _safe_click(self, element):
        """Hover then click — more human than direct click."""
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            ActionChains(self.driver).move_to_element(element).pause(random.gauss(0.6, 0.2)).click().perform()
            return True
        except Exception:
            try:
                element.click()
                return True
            except Exception:
                return False

    def _detect_captcha(self):
        src = self.driver.page_source.lower()
        return any(s in src for s in _CAPTCHA_SIGNALS)

    def _detect_paywall(self):
        src = self.driver.page_source.lower()
        return any(s in src for s in _PAYWALL_SIGNALS)

    def _accept_cookies(self):
        """Try to dismiss cookie/consent banners.
        Handles Google's specific consent IDs first, then generic text scan."""
        from selenium.webdriver.common.by import By

        # Google's consent wall uses known button IDs — hit these directly first
        _google_consent_ids = ['W0wltc', 'L2AGLb', 'Sz6FMc', 'zZois']
        for _cid in _google_consent_ids:
            try:
                _cbtn = self.driver.find_element(By.ID, _cid)
                if _cbtn.is_displayed():
                    self._safe_click(_cbtn)
                    _micro_pause()
                    return True
            except Exception as _exc:
                _zyg_log.debug('no consent button %s on this page: %s', _cid, _exc)
        # Generic text-based scan for all other sites
        try:
            buttons = self.driver.find_elements(
                By.XPATH, '//button | //a[contains(@class,"cookie")] | //div[@role="button"]'
            )
            for btn in buttons[:15]:
                try:
                    txt = btn.text.lower().strip()
                    if any(ct in txt for ct in _COOKIE_BUTTON_TEXTS):
                        self._safe_click(btn)
                        _micro_pause()
                        return True
                except Exception as _exc:
                    _zyg_log.debug('consent candidate button unusable, trying the next: %s', _exc)
        except Exception as _exc:
            _zyg_log.debug('consent button scan failed, assuming no wall: %s', _exc)
        return False

    def _extract_body_text(self, max_chars=12000):
        """Extract visible text from page, removing nav/header/footer noise."""
        from selenium.webdriver.common.by import By

        try:
            # Try semantic content containers first
            for sel in [
                'article',
                'main',
                '.article-body',
                '.story-body',
                '.entry-content',
                '#content',
                '.content',
                '#main-content',
            ]:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, sel)
                    txt = el.text.strip()
                    if len(txt) > 500:
                        return txt[:max_chars]
                except Exception as _exc:
                    _zyg_log.debug('content selector %s absent on this page: %s', sel, _exc)
            # Fallback: full body minus scripts/styles
            body = self.driver.find_element(By.TAG_NAME, 'body')
            return body.text[:max_chars]
        except Exception:
            return ''

    def _get_links(self, selector, attr='href', limit=10):
        """Get list of links matching CSS selector."""
        from selenium.webdriver.common.by import By

        links = []
        try:
            els = self.driver.find_elements(By.CSS_SELECTOR, selector)
            for el in els[:limit]:
                href = el.get_attribute(attr) or ''
                text = el.text.strip()
                if href.startswith('http'):
                    links.append((href, text))
        except Exception as _exc:
            _zyg_log.debug('link scan for %s failed, returning what was collected: %s', selector, _exc)
        return links

    def _add_text(self, source, text, label=''):
        """Add a text block to the research pool."""
        if text and len(text.strip()) > 200:
            block = f'\n\n=== SOURCE: {source.upper()}{" — " + label if label else ""} ===\n{text.strip()}'
            self._texts.append(block)
            self._log('INFO', f'{source}: +{len(text)} chars (total: {sum(len(t) for t in self._texts)})')
