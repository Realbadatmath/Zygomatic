# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import re


class _PostProcessingMixin:
    """Timeline and key-people extraction over the combined research text."""

    # ── Post-processing ───────────────────────────────────────────────────────

    def _extract_timeline(self, combined_text):
        """Extract date→event pairs from combined research text."""
        timeline = []
        # Patterns: "In 1978", "On January 5, 1979", "By March 1980", etc.
        date_patterns = [
            r'(?:on\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}',
            r'\b(?:in\s+)?\d{4}\b',
            r'(?:on\s+)?\d{1,2}[/-]\d{1,2}[/-]\d{4}',
        ]
        sentences = re.split(r'(?<=[.!?])\s+', combined_text)
        for sent in sentences:
            for pat in date_patterns:
                m = re.search(pat, sent, re.IGNORECASE)
                if m and len(sent) > 30:
                    timeline.append({'date': m.group(0).strip(), 'event': sent.strip()[:200]})
                    break
        # Deduplicate and keep top 40
        seen = set()
        unique = []
        for t in timeline:
            key = t['date'].lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique[:40]

    def _extract_key_people(self, combined_text):
        """Extract names of prosecutors, defense attorneys, judges, victims."""
        people = {'prosecutors': [], 'defense': [], 'judges': [], 'victims': [], 'other': []}
        name_re = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b')

        role_keywords = {
            'prosecutors': ['prosecutor', 'district attorney', 'd.a.', 'state attorney', 'assistant u.s.'],
            'defense': ['defense attorney', 'defense counsel', 'represented by', 'defense lawyer'],
            'judges': ['judge', 'justice', 'presiding', 'honourable', 'the court'],
            'victims': ['victim', 'the deceased', 'who was killed', 'who was murdered', 'body of'],
        }

        sentences = re.split(r'(?<=[.!?])\s+', combined_text)
        for sent in sentences:
            sent_lower = sent.lower()
            for role, keywords in role_keywords.items():
                if any(kw in sent_lower for kw in keywords):
                    names = name_re.findall(sent)
                    for name in names:
                        if (
                            len(name.split()) >= 2
                            and name not in people[role]
                            and name != self.case_name
                            and name
                            not in ('The Court', 'Your Honor', 'United States', 'Supreme Court', 'District Court')
                        ):
                            people[role].append(name)
                            break  # one name per sentence

        # Deduplicate
        for role in people:
            people[role] = list(dict.fromkeys(people[role]))[:5]

        return people
