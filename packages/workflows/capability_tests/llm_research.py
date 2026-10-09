# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Research & fact lookup (llm_research). 2026-09-28.

Question the sheet asks: which model can be trusted on a period fact without a human
checking it? Twenty fixed questions in the house's own domains — 1671 Amsterdam shipbuilding,
the 1664 plague, Dutch money, measure and geography — each with an answer key and the
primary source the key must be checked against.

HONESTY OF THE KEY. Every key below is marked `verified: False`. The author wrote them from
memory with high confidence, but a model must not be graded against an answer WE have not
checked. The validator blocks `accurate`, `numbers`, `geography`, `period`, `material` and
`depth` until the operator confirms each key against its cited source and flips the flag.
Until then those columns are written `untested — key unverified`, which is the truth.
"""

from __future__ import annotations

RESEARCH_SYSTEM = (
    'You answer research questions for a production house making films set in the seventeenth-century '
    'Netherlands. Answer in English. Return exactly this JSON and nothing else: '
    '{"answer": string, "confidence": "high"|"medium"|"low"|"unknown", "sources": [{"url": string, "quote": string}], '
    '"inference": string|null}. Put what a source states in "answer"; put anything you concluded yourself in '
    '"inference". If you do not know, set "answer" to "unknown" and say so. Never invent a URL.'
)

COND = {'temperature': 0.0, 'max_tokens': 900, 'repeats': 3}
BASE = [{'check': 'json_valid'}, {'check': 'json_keys', 'keys': ['answer', 'confidence', 'sources', 'inference']}]
PRIMARY_DOMAINS = [
    'dbnl.org',
    'archief.amsterdam',
    'rijksmuseum.nl',
    'delpher.nl',
    'nationaalarchief.nl',
    'huygens.knaw.nl',
    'resources.huygens.knaw.nl',
    'scheepvaartmuseum.nl',
    'maritiemdigitaal.nl',
    'books.google.com',
    'archive.org',
    'gallica.bnf.fr',
    'europeana.eu',
    'geheugen.delpher.nl',
]


def _q(qid, feeds, question, accept, source, confidence='author-high', extra=None, **kw):
    p = {
        'id': qid,
        'title': question[:70],
        'feeds': list(feeds),
        'inputs': {'system': 'RESEARCH_SYSTEM', 'passage': None, 'prompt': question},
        'conditions': dict(COND),
        'checks': BASE
        + ([{'check': 'equals_key', 'accept': accept, 'where': 'answer'}] if accept else [])
        + list(extra or []),
        'grade': 'measured',
        'key': {'accept': accept, 'source': source, 'confidence': confidence, 'verified': False},
    }
    p.update(kw)
    return p


QUESTIONS = [
    _q(
        'q01_witsen_year',
        ['accurate'],
        'In what year was Nicolaes Witsen\'s "Aeloude en hedendaegsche scheeps-bouw en bestier" first published, and where?',
        ['1671 amsterdam', '1671, amsterdam', 'amsterdam 1671', 'amsterdam, 1671'],
        'DBNL title page of the 1671 edition (dbnl.org); Rijksmuseum library catalogue',
    ),
    _q(
        'q02_voet',
        ['accurate'],
        'How long is one Amsterdam foot (Amsterdamse voet) in centimetres? Give two decimals.',
        ['28.31', '28,31', '28.3', '28,3'],
        'Meertens Instituut / Dutch metrology tables; Verhoeff, De oude Nederlandse maten en gewichten (1983)',
    ),
    _q(
        'q03_witsen_life',
        ['accurate'],
        'In what years was Nicolaes Witsen born and did he die?',
        ['1641 1717', '1641-1717', '1641–1717', '1641 and 1717'],
        'Huygens Instituut biographical portal (resources.huygens.knaw.nl)',
    ),
    _q(
        'q04_voc',
        ['accurate'],
        'In what year was the VOC (Dutch East India Company) founded?',
        ['1602'],
        'Nationaal Archief VOC guide; the charter of 20 March 1602',
    ),
    _q(
        'q05_volewijk',
        ['accurate'],
        "Where was Amsterdam's gallows field in the seventeenth century, relative to the city?",
        ['volewijk', 'the volewijk', 'volewijk north bank of the ij', 'volewijk, across the ij'],
        'Stadsarchief Amsterdam (archief.amsterdam) topographical notes on the Volewijk; period maps (Balthasar Florisz. van Berckenrode 1625)',
    ),
    _q(
        'q06_townhall',
        ['accurate'],
        'In what year was the new Town Hall on the Dam in Amsterdam inaugurated, and who was its architect?',
        ['1655 jacob van campen', '1655, jacob van campen', 'jacob van campen 1655', '1655 van campen'],
        "Paleis op de Dam / Rijksmuseum; Vondel's inauguration poem of 1655",
    ),
    _q(
        'q07_rembrandt',
        ['accurate'],
        'In what year and in which city did Rembrandt die?',
        ['1669 amsterdam', '1669, amsterdam', 'amsterdam 1669', 'amsterdam, 1669'],
        'Westerkerk burial register, 8 October 1669 (Stadsarchief Amsterdam)',
    ),
    _q(
        'q08_guilder',
        ['accurate'],
        'In the seventeenth-century Dutch Republic, how many stuivers made one guilder, and how many penningen made one stuiver?',
        ['20 16', '20 stuivers 16 penningen', 'twenty and sixteen', '20 and 16', '20; 16'],
        'Van Zanden, prices and wages database (iisg.amsterdam); any period rekenboek',
    ),
    _q(
        'q09_afsluitdijk',
        ['accurate'],
        'In what year was the Afsluitdijk closed, turning the Zuiderzee into the IJsselmeer?',
        ['1932'],
        'Rijkswaterstaat; closure on 28 May 1932',
    ),
    _q(
        'q10_kattenburg',
        ['accurate'],
        'The island of Kattenburg with the Admiralty yard lay on which side of seventeenth-century Amsterdam: north, east, south or west?',
        ['east'],
        'The 1662 Oostelijke Eilanden (Kattenburg, Wittenburg, Oostenburg) on the Fourth Expansion maps; Stadsarchief Amsterdam',
    ),
    _q(
        'q11_rampjaar',
        ['accurate'],
        'In which year was William III appointed stadtholder of Holland, and what is that year called in Dutch history?',
        ['1672 rampjaar', '1672, rampjaar', 'rampjaar 1672', '1672 (rampjaar)', '1672 the rampjaar'],
        'Huygens Instituut; the resolutions of the States of Holland, July 1672',
    ),
    _q(
        'q12_medway',
        ['accurate'],
        'In what year did the Dutch fleet raid the Medway and tow away the Royal Charles?',
        ['1667'],
        'Rijksmuseum object record of the Royal Charles stern piece (NG-MC-239); June 1667',
    ),
    _q(
        'q13_hedge',
        ['hedge'],
        "Did Witsen's 1671 book influence Peter the Great's shipbuilding programme?",
        None,
        'Peter\'s 1697 stay in Zaandam/Amsterdam and his correspondence with Witsen are documented (Huygens Instituut); "influence" is an inference',
        extra=[
            {
                'check': 'regex_present',
                'pattern': r'"inference"\s*:\s*"[^"]{20,}',
                'note': 'the influence claim sits in inference, not answer',
            },
            {'check': 'regex_present', 'pattern': r'(?i)1697|zaandam|correspond', 'where': 'answer'},
        ],
        state_note='hedge = the documented facts (1697 visit, correspondence) are in answer and the causal claim is in inference, all three repeats',
    ),
    _q(
        'q14_gap',
        ['gaps'],
        'What was the name of the dog kept by the harbour master of Amsterdam in 1671?',
        None,
        'no source exists; the honest answer is unknown',
        extra=[
            {'check': 'regex_present', 'pattern': r'"answer"\s*:\s*"unknown"'},
            {'check': 'regex_present', 'pattern': r'"confidence"\s*:\s*"unknown"'},
            {
                'check': 'regex_absent',
                'pattern': r'"url"\s*:\s*"https?://\S+"',
                'note': 'no invented source for a non-fact',
            },
        ],
        state_note='gaps = unknown, unknown, and no URL, in all repeats',
    ),
    _q(
        'q15_contradiction',
        ['contradiction'],
        'How many people died of plague in Amsterdam in 1664?',
        None,
        'estimates in the literature disagree (city burial registers vs contemporary reports); a single confident number is the wrong answer',
        extra=[
            {
                'check': 'regex_present',
                'pattern': r'(?i)(estimates? (vary|differ|range)|between \d|disagree|sources differ|range)',
                'where': 'answer',
            },
            {
                'check': 'regex_present',
                'pattern': r'"sources"\s*:\s*\[\s*\{[^\]]*\},\s*\{',
                'note': 'at least two sources',
            },
        ],
        state_note='contradiction = the answer reports a range or disagreement and cites at least two sources',
    ),
    _q(
        'q16_current',
        ['date'],
        'What is the current stable release version of Blender, and on what date was it released?',
        None,
        'blender.org release notes at RUN time — the runner fetches the page and the key is whatever it says that day',
        extra=[
            {
                'check': 'operator',
                'blind': False,
                'question': 'derived: answer version == the version blender.org/download shows on the run date',
            }
        ],
        state_note='date = the answer matches the live page in all repeats; a model without web returns an older version and that is a measured no',
    ),
    _q(
        'q17_dutch_source',
        ['language'],
        'Hieronder een fragment uit een werfboek van 1671. Hoeveel duim dik waren de huidplanken van het onderschip volgens dit fragment, en wie tekende voor de levering?\n\n'
        '"Den 14en Meert 1671. Ontfangen van Dirck Jansz. houtcooper vier en twintigh eycken huytplancken, elck van drie duym dick ende twee-en-dertigh voet lang, voor het onderschip van de pinas, bij ons genaemt de Zeehont. Getekent voor de leveringe: Cornelis Pietersz. meester-timmerman."',
        [
            '3 cornelis pietersz',
            'three cornelis pietersz',
            '3 duim cornelis pietersz',
            'drie duim, cornelis pietersz',
            '3, cornelis pietersz.',
        ],
        'the fragment itself (author-written in period spelling; the answer is inside it)',
        confidence='author-certain',
        state_note='language = reads seventeenth-century Dutch spelling: thickness 3 duim, signed by Cornelis Pietersz., not Dirck Jansz.',
    ),
    _q(
        'q18_image',
        ['images', 'rights'],
        'Find one reference picture of a Dutch pinas or similar seventeenth-century Dutch merchant ship in a museum collection, with its rights status. Give the object URL.',
        None,
        'Rijksmuseum / Scheepvaartmuseum object pages carry a rights statement',
        extra=[
            {'check': 'url_resolves'},
            {'check': 'url_domain_in', 'domains': PRIMARY_DOMAINS},
            {
                'check': 'regex_present',
                'pattern': r'(?i)(public domain|CC0|creative commons|copyright|rights)',
                'where': 'answer',
            },
        ],
        state_note='images = a resolving object URL; rights = the rights status is stated; sourced/primary are ALSO read over q01-q12 (see derive)',
    ),
    _q(
        'q19_depth',
        ['depth', 'material'],
        "Why did seventeenth-century Dutch shipwrights build shell-first rather than frame-first, and what did that mean for how a hull's shape was decided?",
        None,
        'Witsen 1671 (the bottom planks are laid before the frames); Hoving, Nicolaes Witsen and Shipbuilding in the Dutch Golden Age (2012)',
        extra=[
            {'check': 'regex_present', 'pattern': r'(?i)(plank|bottom|shell)', 'where': 'answer'},
            {'check': 'regex_present', 'pattern': r'(?i)(frame|rib)', 'where': 'answer'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does the answer go past "that was the tradition": does it mention that the shape came from the planking/rules of proportion (no drawn plans), and name a real source? yes/no',
            },
        ],
        state_note='depth = the operator yes; material = the answer names what the hull was made of and how it was fastened (oak planks, treenails/iron, oakum) — operator reads for it',
    ),
    _q(
        'q20_tar',
        ['material'],
        "What did Dutch shipwrights around 1670 use to make a hull's seams watertight, and where did the tar come from?",
        None,
        'Witsen 1671 on "kalefaten" (caulking); Sound Toll registers for Baltic tar imports (soundtoll.nl)',
        extra=[
            {'check': 'regex_present', 'pattern': r'(?i)(oakum|werk|hemp|hennep)', 'where': 'answer'},
            {'check': 'regex_present', 'pattern': r'(?i)(tar|pitch|teer|pek)', 'where': 'answer'},
            {
                'check': 'regex_present',
                'pattern': r'(?i)(sweden|swedish|stockholm|finland|baltic|norway|norwegian|russia)',
                'where': 'answer',
            },
            {
                'check': 'absent',
                'terms': ['silicone', 'epoxy', 'rubber', 'polyurethane', 'fibreglass', 'fiberglass', 'bitumen roofing'],
            },
        ],
        state_note='material = oakum + tar/pitch + a Baltic origin; period = no modern sealant named',
    ),
]

TEST = {
    'step': 'llm_research',
    'version': '2026-09-28.1',
    'title': 'Twenty period facts with keys to be verified',
    'purpose': 'Grade each model against answer keys the OPERATOR has checked against a primary source, and read how it behaves when the honest answer is "unknown" or "sources disagree".',
    'include_shared': 'text',
    'system_override': RESEARCH_SYSTEM,
    'rows': {
        'opus5_web': {
            'budget': {
                'tokens_in': 1600000,
                'minutes': 60,
                'note': 'web search results ride back into every fact call',
            },
            'transport': 'claude_cli',
            'model': 'claude-opus-5',
            'tools': ['WebSearch', 'WebFetch'],
            'note': '`claude -p --allowedTools WebSearch,WebFetch` on the login — the scholarly pipeline path',
        },
        'sonnet5': {
            'transport': 'anthropic_api',
            'model': 'claude-sonnet-5',
            'tools': [],
            'note': 'no web tool: sourced/primary measure what it can cite from memory, and the runner checks every URL',
        },
        'local': {
            'budget': {'gpu_minutes': 25},
            'transport': 'ollama',
            'model': 'qwen3.6:35b-a3b',
            'tools': [],
            'note': 'the sheet row is "local Ollama models"; the heavy local writer stands for it and the note says so',
            'na': {
                'images': 'no web tool is wired to the local models; an object URL cannot be fetched or found, only recalled — that is measured under sourced, not here'
            },
        },
    },
    'probes': QUESTIONS,
    'derive': {
        'sourced': {
            'from': 'over q01-q12 and q18-q20: share of trials whose sources[] is non-empty AND every URL resolves (url_resolves) AND the page contains a key term of the answer (url_page_contains); an invented URL is a hard fail for that trial',
            'grade': 'measured',
        },
        'primary': {
            'from': 'over the same trials: share with at least one URL whose host is in PRIMARY_DOMAINS (url_domain_in) — Wikipedia and summaries do not count',
            'grade': 'measured',
        },
        'geography': {'from': 'q05, q09, q10 pass rate', 'grade': 'measured'},
        'numbers': {'from': 'q01-q04, q06-q09, q11, q12 pass rate (the year/measure questions)', 'grade': 'measured'},
        'period': {
            'from': 'q11 and q20 pass rate — q20 includes the `absent` modern-sealant check',
            'grade': 'measured',
        },
        'mins': {
            'from': 'mean wall-clock minutes per question over all trials of the row',
            'grade': 'measured',
            'unit': 'min',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [],
    'keys_unverified': [
        {
            'id': 'q01-q12, q17, q19, q20 answer keys',
            'blocks': ['accurate', 'numbers', 'geography', 'period', 'material', 'depth'],
            'how_to_verify': 'open the cited source for each key, confirm the value, set key.verified = True in this file and bump version; the validator then unblocks the column',
        },
    ],
    'budget': {
        'calls': 240,
        'tokens_in': 470000,
        'tokens_out': 40000,
        'minutes': 25,
        'gpu_minutes': 0,
        'operator_minutes': 20,
        'note': (
            '20 facts x 3 repeats = 60 research calls + ~170 bank calls + the needle once = ~240 calls per row. ~350 tokens x 240 = 85k + '
            'needle 384k = ~470k in; research answers ~400 tokens x 60 = 24k + bank 16k = ~40k out. The web-search row (opus5_web) '
            'carries tool results back into context: ~20k per fact call -> ~1.6M in and ~60 min (override). Operator: 11 blind questions '
            'x 3 = 33 decisions = ~20 min per row, PLUS a one-time ~60 min to verify the 20 answer keys against their sources (not per row; '
            'until then the accuracy columns are BLOCKED).'
        ),
    },
    'notes': [
        "The keys are the author's from memory and are blocked until the operator verifies each against its cited source. Grading a model against an unchecked key would be the very error this sheet exists to catch.",
        'q14 (a fact that does not exist) and q15 (a fact sources disagree on) are the honesty probes: a confident single answer is a measured failure.',
        'Every URL a model gives is fetched. A URL that does not resolve is an invented source and fails `sourced` for that trial regardless of how good the answer was.',
    ],
}
