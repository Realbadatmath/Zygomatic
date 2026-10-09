# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Full-text and image extraction, Wikimedia supplement, browser setup."""

from zyg_workflows.scholarly_research_agent.constants import (
    _IMG_BASE,
    _PAGE_LOAD_TIMEOUT,
    _PlaywrightAdapter,
    _hj,
    _sb_fetch,
    _up,
    _zyg_logging,
    os,
    random,
    re,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.scholarly_research_agent')


class _ExtractionMixin:
    # ── Full Text Extraction ──────────────────────────────────────────────────

    def _extract_full_text_html(self, url: str) -> str:
        """Extract article text from an HTML page.
        Tries the browser sandbox first (fast, safe), falls back to local Playwright."""
        if not url:
            return ''
        # ── Browser sandbox (preferred) ───────────────────────────────────────
        result = _sb_fetch(url)
        if result and result.get('ok') and result.get('text'):
            text = result['text']
            if len(text) > 200:
                return text[:50000]
        # ── Playwright fallback ───────────────────────────────────────────────
        try:
            from playwright.sync_api import sync_playwright

            _download_url = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
                ctx = browser.new_context(accept_downloads=True, user_agent=self._ua)
                page = ctx.new_page()

                # Intercept downloads — capture the URL instead of saving the file
                def _on_download(dl):
                    _download_url.append(dl.url)
                    dl.cancel()

                page.on('download', _on_download)

                try:
                    page.goto(url, timeout=30000, wait_until='domcontentloaded')
                except Exception as _ge:
                    # Playwright raises when a download fires — that's expected
                    if 'Download' not in str(_ge) and 'download' not in str(_ge):
                        raise

                # If a download was triggered, treat the intercepted URL as a PDF
                if _download_url:
                    dl_url = _download_url[0]
                    self._log('INFO', f'Download intercepted → extracting as PDF: {dl_url[:60]}')
                    browser.close()
                    return self._extract_full_text_pdf(dl_url)

                text = ''
                for selector in [
                    'article',
                    'main',
                    'div.content',
                    'div.article-body',
                    'div#content',
                    '.post-content',
                    '.entry-content',
                ]:
                    try:
                        el = page.query_selector(selector)
                        if el:
                            text = el.inner_text()
                            if len(text) > 500:
                                break
                    except Exception as _exc:
                        _zyg_log.debug('selector %s yielded no text: %s', selector, _exc)
                        continue
                if not text:
                    text = page.inner_text('body')
                browser.close()
                return text[:50000]
        except Exception as e:
            self._log('WARNING', f'HTML text extraction failed ({url[:60]}): {e}')
            return ''

    def _extract_full_text_pdf(self, url_or_path: str) -> str:
        """Download PDF if URL, then extract text. Tries fitz → pdfminer → pdfplumber → pypdf."""
        if not url_or_path:
            return ''
        pdf_path = url_or_path
        _tmp_pdf = None
        try:
            if url_or_path.startswith('http'):
                import tempfile

                _tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
                _tmp_pdf = _tmp.name
                _tmp.close()
                with open(_tmp_pdf, 'wb') as _fh:
                    _fh.write(_hj.request(url_or_path, timeout=60))
                pdf_path = _tmp_pdf

            # Attempt 1: PyMuPDF (fitz)
            try:
                import fitz

                doc = fitz.open(pdf_path)
                text = ''.join(page.get_text() for page in doc)[:50000]
                doc.close()
                if text.strip():
                    return text
            except ImportError as _exc:
                _zyg_log.debug('PyMuPDF not installed, trying pdfminer: %s', _exc)
            except Exception as _e:
                self._log('WARNING', f'fitz extraction failed: {_e}')

            # Attempt 2: pdfminer.six
            try:
                from pdfminer.high_level import extract_text as _pm_extract

                text = _pm_extract(pdf_path, maxpages=30)[:50000]
                if text and text.strip():
                    return text
            except ImportError as _exc:
                _zyg_log.debug('pdfminer.six not installed, trying pdfplumber: %s', _exc)
            except Exception as _e:
                self._log('WARNING', f'pdfminer extraction failed: {_e}')

            # Attempt 3: pdfplumber
            try:
                import pdfplumber

                with pdfplumber.open(pdf_path) as _doc:
                    text = ''
                    for page in _doc.pages[:30]:
                        text += page.extract_text() or ''
                        if len(text) > 50000:
                            break
                text = text[:50000]
                if text.strip():
                    return text
            except ImportError as _exc:
                _zyg_log.debug('pdfplumber not installed, trying pypdf: %s', _exc)
            except Exception as _e:
                self._log('WARNING', f'pdfplumber extraction failed: {_e}')

            # Attempt 4: pypdf
            try:
                import pypdf

                reader = pypdf.PdfReader(pdf_path)
                text = ''
                for page in reader.pages[:30]:
                    text += page.extract_text() or ''
                    if len(text) > 50000:
                        break
                text = text[:50000]
                if text.strip():
                    return text
            except ImportError as _exc:
                _zyg_log.debug('pypdf not installed, no pdf text extractor left: %s', _exc)
            except Exception as _e:
                self._log('WARNING', f'pypdf extraction failed: {_e}')

            self._log('WARNING', 'All PDF extraction methods failed — no text recovered')
            return ''
        except Exception as e:
            self._log('WARNING', f'PDF text extraction failed: {e}')
            return ''
        finally:
            if _tmp_pdf and os.path.exists(_tmp_pdf):
                try:
                    os.remove(_tmp_pdf)
                except OSError as _exc:
                    _zyg_log.debug('temp pdf %s cleanup skipped: %s', _tmp_pdf, _exc)

    # ── Image Extraction ──────────────────────────────────────────────────────

    def _extract_images_html(self, url: str) -> list:
        """Extract images from an HTML page using Playwright."""
        if not url:
            return []
        images = []
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
                page = browser.new_page(user_agent=self._ua)
                page.goto(url, timeout=30000, wait_until='domcontentloaded')
                imgs = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('img')).map(img => ({
                        src: img.src,
                        alt: img.alt,
                        width: img.naturalWidth || img.width,
                        height: img.naturalHeight || img.height,
                    })).filter(i => i.src && !i.src.startsWith('data:') && i.alt && i.width >= 200);
                }""")
                browser.close()
                img_dir = os.path.join(_IMG_BASE, self.pipeline_id)
                os.makedirs(img_dir, exist_ok=True)
                for img_data in imgs[:10]:
                    src = img_data.get('src', '')
                    alt = img_data.get('alt', '')
                    if not src or not src.startswith('http'):
                        continue
                    try:
                        fname = (
                            re.sub(r'[^\w.]', '_', src.split('/')[-1].split('?')[0])[:60] or f'img_{len(images)}.jpg'
                        )
                        save_path = os.path.join(img_dir, fname)
                        with open(save_path, 'wb') as _fh:
                            _fh.write(_hj.request(src, timeout=30))
                        if os.path.exists(save_path) and os.path.getsize(save_path) > 1000:
                            images.append({'path': save_path, 'caption': alt, 'source': 'essay'})
                    except Exception as _exc:
                        _zyg_log.warning('essay image %s could not be saved, skipped: %s', src, _exc)
                        continue
        except Exception as e:
            self._log('WARNING', f'HTML image extraction failed: {e}')
        return images

    def _extract_images_pdf(self, pdf_path: str) -> list:
        """Extract images from a PDF using PyMuPDF (fitz). Silently skips if unavailable."""
        if not pdf_path or not os.path.exists(pdf_path):
            return []
        images = []
        try:
            import fitz

            doc = fitz.open(pdf_path)
            img_dir = os.path.join(_IMG_BASE, self.pipeline_id)
            os.makedirs(img_dir, exist_ok=True)
            for page_num, page in enumerate(doc):
                for img_index, img in enumerate(page.get_images()):
                    if len(images) >= 10:
                        break
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image.get('image', b'')
                    width = base_image.get('width', 0)
                    height = base_image.get('height', 0)
                    if width < 100 or height < 100:
                        continue
                    if len(img_bytes) < 2000:
                        continue
                    ext = base_image.get('ext', 'png')
                    fname = f'p{page_num}_img{img_index}.{ext}'
                    save_path = os.path.join(img_dir, fname)
                    with open(save_path, 'wb') as _f:
                        _f.write(img_bytes)
                    images.append({'path': save_path, 'caption': f'Figure from page {page_num + 1}', 'source': 'essay'})
            doc.close()
        except ImportError as _exc:
            _zyg_log.debug('PyMuPDF not installed, no pdf image extraction: %s', _exc)
        except Exception as e:
            self._log('WARNING', f'PDF image extraction failed: {e}')
        return images

    def _supplement_wikimedia(self, topic: str, target_count: int) -> list:
        """Fetch images from Wikimedia Commons. Only accepts real image formats ffmpeg can read."""
        _VALID_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
        images = []
        img_dir = os.path.join(_IMG_BASE, self.pipeline_id)
        os.makedirs(img_dir, exist_ok=True)
        # Try multiple search queries to get enough images
        _queries = [topic, f'{topic} history', f'{topic} ancient', f'{topic} illustration']
        for _q in _queries:
            if len(images) >= target_count:
                break
            try:
                q_enc = _up.quote(_q)
                url = (
                    f'https://commons.wikimedia.org/w/api.php'
                    f'?action=query&list=search&srsearch={q_enc}'
                    f'&srnamespace=6&srlimit=20&format=json'
                )
                data = _hj.request_json(url, headers={'User-Agent': 'ScholarlyBot/1.0'}, timeout=15)
                for result in data.get('query', {}).get('search', []):
                    if len(images) >= target_count:
                        break
                    title = result.get('title', '')
                    if not title.startswith('File:'):
                        continue
                    file_name = title[5:]
                    ext = os.path.splitext(file_name.lower())[1]
                    if ext not in _VALID_EXTS:
                        continue  # skip .djvu, .pdf, .svg, .ogv, .tiff etc.
                    file_url = f'https://commons.wikimedia.org/wiki/Special:FilePath/{_up.quote(file_name)}'
                    try:
                        fname = re.sub(r'[^\w.]', '_', file_name)[:60]
                        save_path = os.path.join(img_dir, fname)
                        with open(save_path, 'wb') as _fh:
                            _fh.write(_hj.request(file_url, timeout=30))
                        if os.path.exists(save_path) and os.path.getsize(save_path) > 5000:
                            images.append({'path': save_path, 'caption': file_name, 'source': 'wikimedia'})
                    except Exception as _exc:
                        _zyg_log.warning('wikimedia image %s could not be saved, skipped: %s', file_name, _exc)
                        continue
            except Exception as e:
                self._log('WARNING', f'Wikimedia supplement query "{_q}" failed: {e}')
        return images

    # ── Browser setup (identical waterfall to WebResearchAgent) ───────────────

    def _setup_browser(self):
        """Playwright → Selenium waterfall. Sets self.driver and self._browser_engine."""
        # 1. Playwright
        try:
            from playwright.sync_api import sync_playwright

            self._log('INFO', 'Trying Playwright (Chromium) …')
            _pw = sync_playwright().start()
            _browser = _pw.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--disable-extensions',
                    '--lang=en-US',
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
            try:
                _bpid = _browser.process.pid
                if _bpid:
                    self._browser_pid = _bpid
            except Exception:
                self._browser_pid = None
            return
        except Exception as _e:
            self._log('WARNING', f'Playwright failed: {_e}')

        # 2. Selenium + Xvfb fallback
        try:
            from selenium import webdriver as _wd
            from selenium.webdriver.chrome.options import Options as _Opts
            from xvfbwrapper import Xvfb

            self._display = Xvfb(width=1280, height=900, colordepth=24)
            self._display.start()
            _opts = _Opts()
            _opts.add_argument('--no-sandbox')
            _opts.add_argument('--disable-dev-shm-usage')
            _opts.add_argument('--disable-gpu')
            _opts.add_argument(f'--user-agent={self._ua}')
            self.driver = _wd.Chrome(options=_opts)
            self.driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT)
            self._browser_engine = 'selenium'
            self._log('INFO', 'Selenium launched OK')
        except Exception as _e2:
            self._log('WARNING', f'Selenium fallback failed: {_e2}')
            self.driver = None

    def _teardown_browser(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as _exc:
                _zyg_log.debug('selenium driver quit skipped: %s', _exc)
            self.driver = None
        if self._display:
            try:
                self._display.stop()
            except Exception as _exc:
                _zyg_log.debug('virtual display stop skipped: %s', _exc)
            self._display = None

    def _add_text(self, source_name: str, text: str, label: str = ''):
        if not text or len(text.strip()) < 100:
            return
        self._texts.append(text.strip())
        self._papers_found.append(
            {
                'source': source_name,
                'label': label or source_name,
                'chars': len(text),
            }
        )
