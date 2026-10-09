# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ScholarlyResearchAgent class itself: construction, lifecycle, Postgres cache."""

from zyg_workflows.scholarly_research_agent.constants import (
    _DATA_DIR,
    _TOPIC_DISCIPLINES,
    _TOPIC_QUERIES,
    _USER_AGENTS,
    dict_row,
    os,
    pgdb,
    random,
    time,
)
from zyg_workflows.scholarly_research_agent.directive import _claude_extract_subject, _extract_keywords


class ScholarlyResearchAgent:
    """
    API-first scholarly research agent.
    Uses OpenAlex, Semantic Scholar, and CORE APIs with Postgres caching.
    Falls back to browser scraping if all APIs fail.
    """

    def __init__(self, topic: str, pipeline_id: str = '', log_fn=None, stop_event=None):
        self.topic = topic.lower().strip()
        self.pipeline_id = pipeline_id
        self._log_fn = log_fn or (lambda level, stage, msg: print(f'[{level}] {stage}: {msg}'))
        self.driver = None
        self._browser_engine = None
        self._shutdown = False
        self._stop_event = stop_event
        self._ua = random.choice(_USER_AGENTS)
        self._display = None
        self._texts = []
        self._sources_used = []
        self._papers_found = []

        self._disciplines = _TOPIC_DISCIPLINES.get(self.topic, ['education', 'humanities'])
        self._queries = _TOPIC_QUERIES.get(self.topic, [f'{self.topic} research essay'])

        # When the topic is a free-text user prompt (not a known topic keyword),
        # extract content words and build targeted search queries from them.
        # Priority: 1) Claude identifies the real subject phrase, 2) dumb word split fallback.
        self._directive_kw: list = []
        self._claude_subject: str = ''
        if self.topic not in _TOPIC_QUERIES:
            # ── Step 1: Ask Claude to identify the real subject ────────────
            # e.g. "documentary on works of Jacque Fresco" → "Jacque Fresco"
            self._claude_subject = _claude_extract_subject(self.topic)
            if self._claude_subject:
                subject = self._claude_subject
                self._directive_kw = subject.lower().split()
                self._queries = [
                    subject,  # exact phrase first
                    f'{subject} overview',
                    f'{subject} history',
                ]
                self._log(
                    'INFO', f'[SubjectExtract] Claude identified subject: "{subject}" → queries: {self._queries[0]!r}'
                )
            else:
                # ── Step 2: Fallback — dumb keyword split ──────────────────
                kw = _extract_keywords(self.topic)
                if kw:
                    self._directive_kw = kw
                    kw3 = ' '.join(kw[:3])
                    kw2 = ' '.join(kw[:2])
                    self._queries = [
                        f'{kw3} academic overview',
                        f'{kw3} research',
                        f'{kw2} detailed study',
                    ]
                    self._log('INFO', f'Free-text topic → extracted keywords: {kw[:5]} → queries: {self._queries[0]!r}')

        os.makedirs(_DATA_DIR, exist_ok=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _is_stopped(self):
        return self._shutdown or (self._stop_event is not None and self._stop_event.is_set())

    def _log(self, level, msg):
        self._log_fn(level, 'Stage 2 / Scholarly', msg)

    # ── Postgres DB ───────────────────────────────────────────────────────────

    def _db_connect(self):
        return pgdb.raw_connect()

    def _db_insert_papers(self, papers: list):
        try:
            conn = self._db_connect()
            now = time.strftime('%Y-%m-%dT%H:%M:%S')
            for p in papers:
                # Skip duplicates by doi or title
                doi = (p.get('doi') or '').strip()
                title = (p.get('title') or '').strip().lower()
                if doi:
                    exists = conn.execute('SELECT id FROM essays WHERE doi=%s', (doi,)).fetchone()
                else:
                    exists = conn.execute('SELECT id FROM essays WHERE lower(title)=%s', (title,)).fetchone()
                if exists:
                    continue
                # Postgres enforces the integer type SQLite ignored: the APIs hand
                # word_estimate over as '12' or 12.0 as often as 12.
                we = p.get('word_estimate', 0)
                try:
                    we = int(float(we or 0))
                except (TypeError, ValueError):
                    we = 0
                conn.execute(
                    """INSERT INTO essays
                       (topic, title, authors, source_api, abstract, full_text_url,
                        pdf_url, word_estimate, license, doi, date_fetched, used, images_json)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'[]')""",
                    (
                        self.topic,
                        p.get('title', ''),
                        p.get('authors', ''),
                        p.get('source_api', ''),
                        p.get('abstract', ''),
                        p.get('full_text_url', ''),
                        p.get('pdf_url', ''),
                        we,
                        p.get('license', ''),
                        doi,
                        now,
                    ),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            self._log('WARNING', f'DB insert failed: {e}')

    def _db_mark_used(self, essay_id: int):
        try:
            conn = self._db_connect()
            conn.execute(
                'UPDATE essays SET used=1, date_used=%s WHERE id=%s', (time.strftime('%Y-%m-%dT%H:%M:%S'), essay_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self._log('WARNING', f'DB mark_used failed: {e}')

    def _db_blacklist(self, essay_id: int, reason: str = 'too_short'):
        """Mark a paper as permanently unusable (used=2).

        reason values:
          'too_short'          — content is genuinely under 1500 words (permanent)
          'extraction_failure' — PDF library or network failed; reset to unused on next startup
          'content_unavailable'— no PDF and no abstract at all
        """
        try:
            conn = self._db_connect()
            conn.execute(
                'UPDATE essays SET used=2, blacklist_reason=%s, date_used=%s WHERE id=%s',
                (reason, time.strftime('%Y-%m-%dT%H:%M:%S'), essay_id),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self._log('WARNING', f'DB blacklist failed: {e}')

    def _db_reset_extraction_failures(self):
        """On startup, reset any essays that were blacklisted due to extraction failure back to unused.

        These are essays that had a viable word_estimate but couldn't be extracted — usually
        because a PDF library was missing.  They are perfectly valid candidates and should be
        retried now that the library may be available.
        """
        try:
            conn = self._db_connect()
            n = conn.execute(
                "SELECT COUNT(*) FROM essays WHERE used=2 AND blacklist_reason='extraction_failure'"
            ).fetchone()[0]
            if n:
                conn.execute(
                    "UPDATE essays SET used=0, blacklist_reason=NULL WHERE used=2 AND blacklist_reason='extraction_failure'"
                )
                conn.commit()
                self._log('INFO', f'Reset {n} extraction-failure essays back to unused')
            conn.close()
        except Exception as e:
            self._log('WARNING', f'DB reset_extraction_failures failed: {e}')

    def _db_get_unused(self, topic: str) -> list:
        # Exclude blacklisted (used=2) entries
        try:
            conn = self._db_connect()
            rows = (
                conn.cursor(row_factory=dict_row)
                .execute('SELECT * FROM essays WHERE topic=%s AND used=0 ORDER BY id DESC', (topic,))
                .fetchall()
            )
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            self._log('WARNING', f'DB get_unused failed: {e}')
            return []
