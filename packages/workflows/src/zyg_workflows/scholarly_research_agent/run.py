# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The main run() waterfall and the output builders."""

from zyg_workflows.scholarly_research_agent import run_stages as _ST
from zyg_workflows.scholarly_research_agent.constants import (
    _VF_RESOLVER,
    time,
)


class _RunMixin:
    # ── Main run method ───────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute API-first research flow. Falls back to browser scraping if needed.
        Returns a structured research bundle with full essay text and images.
        """
        start_time = time.time()
        self._log('INFO', f'Starting scholarly research for topic: {self.topic}')

        # Reset any essays that were previously blacklisted due to extraction failures
        self._db_reset_extraction_failures()

        # ── Steps 1-3: DB cache, live web research, then the three APIs ───────
        found = _ST.discover_candidates(self)
        if found.bail:
            return self._build_output({}, start_time)
        if not found.selected:
            self._log('WARNING', 'No paper selected — using minimal fallback')
            return self._build_output({}, start_time)

        # ── Step 4: Extract full text — keep trying until ≥500 words ──────────
        picked = _ST.extract_best_text(self, found)
        full_text = picked.full_text
        word_count = picked.word_count
        selected = picked.selected
        selected_id = picked.selected_id

        if word_count < 500 and not found.web_full_text:
            self._log(
                'WARNING', f'Could not find essay ≥500 words after {picked.attempt} attempts — best: {word_count} words'
            )
            # ── Wikipedia fallback: fetch full Wikipedia article for topic ────
            full_text, word_count, selected = _ST.wikipedia_fallback(self, full_text, word_count, selected)

        # ── Step 5: Extract images ────────────────────────────────────────────
        # All image downloaders disabled — pipeline generates its own images via FLUX.
        essay_images = []

        # Clean up temp PDF
        _ST.discard_temp_pdf(picked.tmp_pdf)

        # Mark as used
        if selected_id:
            self._db_mark_used(selected_id)

        # Build papers_found for reporting
        self._papers_found = _ST.papers_found_rows(found.all_papers)
        self._sources_used = _ST.sources_used_labels(found.all_papers)

        # Cap essay at 4000 words max for single-episode format
        full_text, word_count, _capped = _ST.cap_essay(full_text, word_count)
        if _capped:
            self._log('INFO', f'Essay capped at {word_count} words (was over {_ST.MAX_WORDS})')

        elapsed = round(time.time() - start_time, 1)
        self._log('INFO', f'Scholarly research complete: {word_count} words in {elapsed}s')

        _visual_framework = _VF_RESOLVER.resolve(self.topic, full_text) if _VF_RESOLVER is not None else None

        return {
            'case_name': f'Scholarly — {self.topic.title()}',
            'topic': self.topic,
            'research_text': full_text,
            'abstract': selected.get('abstract', ''),
            'title': selected.get('title', ''),
            'authors': selected.get('authors', ''),
            'word_count': word_count,
            'images': essay_images,
            'episode_split': False,  # capped at 4000 — never split now
            'total_chars': len(full_text),
            'sources_used': self._sources_used,
            'papers_found': self._papers_found,
            'elapsed_s': elapsed,
            'mode': 'scholarly',
            'selected_essay_id': selected_id,
            'visual_framework': _visual_framework,
        }

    def _build_output(self, case: dict, start_time: float) -> dict:
        combined = '\n'.join(self._texts)
        total_chars = len(combined)
        elapsed = round(time.time() - start_time, 1)

        self._log(
            'INFO',
            f'Scholarly research complete: {total_chars} chars from {len(self._sources_used)} sources in {elapsed}s',
        )

        _visual_framework = _VF_RESOLVER.resolve(self.topic, combined) if _VF_RESOLVER is not None else None

        return {
            'case_name': f'Scholarly — {self.topic.title()}',
            'topic': self.topic,
            'research_text': combined,
            'abstract': '',
            'title': self.topic.title(),
            'authors': '',
            'word_count': len(combined.split()),
            'images': [],
            'episode_split': len(combined.split()) > 10000,
            'total_chars': total_chars,
            'sources_used': self._sources_used,
            'papers_found': self._papers_found,
            'elapsed_s': elapsed,
            'mode': 'scholarly',
            'selected_essay_id': None,
            'visual_framework': _visual_framework,
        }
