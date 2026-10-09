# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers carved out of ``_script_cleaners``/``_regex_clean``.

Every pattern in stage 3's text cleaner used to be compiled inside a closure of
a 419-line factory, so nothing below was reachable without running the whole
scholarly pipeline. These tests pin the behaviour of the pure pieces — the
cover-page scan, the spaced-heading normaliser, the intro-marker search, the
garbled/address/prose predicates, the Layer B sentence gate, the empty-result
safety net and the LLM preamble stripper — with plain strings: no GPU, no
network, no services.
"""

from zyg_workflows.scholarly.stages_01_18.stage_03_cleaners import _script_cleaners
from zyg_workflows.scholarly.stages_01_18.stage_03_cleaners_regex import (
    _drop_address_fragments,
    _find_intro_pos,
    _first_prose_line,
    _is_address_fragment,
    _is_garbled,
    _is_prose_header_line,
    _is_prose_sentence,
    _keep_prose_sentences,
    _normalize_spaced_headings,
    _regex_clean,
    _strip_citation_header,
    _strip_llm_preamble,
    _wiped_out_content,
)

PROSE = 'The Roman legions crossed the Danube that spring, and the frontier held for a decade.'


# ── the factory contract stage_03.py depends on ──────────────────────────────
def test_script_cleaners_returns_the_three_cleaners_in_order():
    header, clean, preamble = _script_cleaners()
    assert (header, clean, preamble) == (_strip_citation_header, _regex_clean, _strip_llm_preamble)


# ── _is_prose_header_line / _first_prose_line ────────────────────────────────
def test_a_long_lowercase_sentence_is_a_prose_header_line():
    assert _is_prose_header_line(PROSE) is True


def test_an_author_list_is_not_a_prose_header_line():
    assert _is_prose_header_line('Smith, J. and Jones, K. (2017) Something About Nothing.') is False


def test_a_short_capitalised_line_is_not_a_prose_header_line():
    assert _is_prose_header_line('Introduction') is False


def test_first_prose_line_skips_blanks_cover_pages_and_journal_banners():
    lines = [
        '',
        'FACULTAD de FILOSOFIA',
        'TUTOR: Dr. Someone',
        'Contents lists available at ScienceDirect',
        PROSE,
    ]
    assert _first_prose_line(lines) == 4


def test_first_prose_line_returns_zero_when_nothing_reads_as_prose():
    assert _first_prose_line(['UNIVERSIDAD DE GRANADA', 'AUTOR: X']) == 0


def test_strip_citation_header_drops_the_cover_page_and_keeps_the_prose():
    raw = 'UNIVERSIDAD DE GRANADA\nAUTOR: X\n' + PROSE
    assert _strip_citation_header(raw) == PROSE


def test_strip_citation_header_returns_the_text_unchanged_when_it_starts_in_prose():
    assert _strip_citation_header(PROSE) == PROSE


# ── _normalize_spaced_headings ───────────────────────────────────────────────
def test_spaced_letter_headings_collapse_to_one_word():
    out = _normalize_spaced_headings('A B S T R A C T\nA R T I C L E I N F O\nK E Y W O R D S')
    assert out == 'ABSTRACT\nARTICLEINFO\nKEYWORDS'


def test_normalize_spaced_headings_leaves_ordinary_prose_alone():
    assert _normalize_spaced_headings(PROSE) == PROSE


# ── _find_intro_pos ──────────────────────────────────────────────────────────
def test_find_intro_pos_points_at_a_numbered_introduction_header():
    text = 'Front matter junk.\n1. Introduction\n' + PROSE
    assert _find_intro_pos(text) == text.index('. Introduction')


def test_find_intro_pos_falls_back_to_the_first_long_prose_paragraph():
    long_prose = (
        'The settlement was established in the fourth century and abandoned after the flood, '
        'and the monks rebuilt it from the stone of the old quarry on the hill.'
    )
    text = 'X Y Z\n\n' + long_prose
    assert _find_intro_pos(text) == text.find(long_prose)


def test_find_intro_pos_is_negative_when_there_is_no_prose_and_no_marker():
    assert _find_intro_pos('A B\n\nC D') == -1


# ── _is_garbled ──────────────────────────────────────────────────────────────
def test_a_shouting_pdf_artefact_line_is_garbled():
    assert _is_garbled('N O T I T I A D I G N I T A T U M 1 2 3') is True


def test_a_line_under_twelve_characters_is_never_garbled():
    assert _is_garbled('ABCDEFGHIJ') is False


def test_a_normal_sentence_is_not_garbled():
    assert _is_garbled(PROSE) is False


# ── _is_address_fragment / _drop_address_fragments ───────────────────────────
def test_a_postal_code_without_a_verb_is_an_address_fragment():
    assert _is_address_fragment('Posgrado 04510, Mexico City') is True


def test_a_postal_code_with_a_verb_is_kept_as_prose():
    assert _is_address_fragment('In 1945, Berlin 10115 was taken by the advancing armies.') is False


def test_a_sentence_without_a_postal_code_is_never_an_address_fragment():
    assert _is_address_fragment('The gate stood open.') is False


def test_drop_address_fragments_works_per_paragraph():
    text = 'Departamento 28040 Madrid. ' + PROSE + '\n\nPlain second paragraph.'
    out = _drop_address_fragments(text)
    assert out == PROSE + '\n\nPlain second paragraph.'


def test_drop_address_fragments_removes_paragraphs_that_become_empty():
    assert _drop_address_fragments('Instituto 04510 Mexico.\n\n' + PROSE) == PROSE


# ── _is_prose_sentence (Layer B) ─────────────────────────────────────────────
def test_a_five_word_fragment_is_always_dropped():
    assert _is_prose_sentence('Rojo-Garibaldi, C. Rangoni, D.L.') is False


def test_a_short_segment_with_a_prose_verb_is_kept():
    assert _is_prose_sentence('Alexander the Great conquered Persia in 334 BC.') is True


def test_a_short_segment_without_a_prose_verb_is_dropped():
    assert _is_prose_sentence('University of Granada, Granada, Spain, Europe') is False


def test_a_long_segment_needs_three_english_function_words():
    italian = (
        'Istituto per la Microelettronica e Microsistemi Consiglio Nazionale delle Ricerche '
        'Catania Italia Zona Industriale Ottava Strada Cinque Edificio'
    )
    assert len(italian.split()) >= 15
    assert _is_prose_sentence(italian) is False
    assert _is_prose_sentence(PROSE + ' It was the frontier of the empire for many long years.') is True


def test_a_segment_that_is_mostly_punctuation_is_dropped():
    assert _is_prose_sentence('1. 2. 3. 4. 5. 6. 7. 8.') is False


# ── _keep_prose_sentences ────────────────────────────────────────────────────
def test_keep_prose_sentences_rebuilds_only_the_paragraphs_with_prose():
    text = 'A. B. C.\n\n' + PROSE + ' Bare label.\n\n   \n'
    assert _keep_prose_sentences(text) == PROSE


# ── _wiped_out_content (the TTS safety net) ──────────────────────────────────
def test_wiped_out_content_is_true_when_almost_everything_went():
    assert _wiped_out_content('three words left', 'word ' * 400) is True


def test_wiped_out_content_is_false_when_enough_survived():
    assert _wiped_out_content('word ' * 60, 'word ' * 400) is False


def test_wiped_out_content_is_false_without_an_original():
    assert _wiped_out_content('', '') is False


# ── the orchestrator still behaves like the old closure ──────────────────────
def test_regex_clean_strips_a_journal_front_page_and_keeps_the_narrative():
    # Long enough that the surviving narrative clears the 50-word safety floor.
    body = (
        'The settlement was established in the fourth century and was abandoned after the flood. '
        'It was rebuilt by the monks, and their records survived in the archive of the abbey. '
        'The chroniclers wrote that the harvest failed twice, and the grain was brought from the islands. '
        'A new wall was built along the river, and the gate was closed at night for many years. '
        'The road to the north was repaired by the merchants, and they used it for six centuries. '
    )
    raw = (
        'Contents lists available at ScienceDirect\n'
        'journal homepage: www.cell.com/heliyon\n'
        'Heliyon 7 (2021) e06580\n'
        'A B S T R A C T\n'
        'We studied the thing and found it.\n'
        'Keywords: alpha, beta\n\n'
        '1. Introduction\n' + body
    )
    out = _regex_clean(raw)
    assert 'ScienceDirect' not in out
    assert 'Keywords' not in out
    assert 'rebuilt by the monks' in out
    assert out == body.strip()


def test_regex_clean_returns_the_original_when_cleaning_wipes_it_out():
    original = 'Чтение этого текста не на английском языке. ' * 20
    assert _regex_clean(original) == original.strip()


# ── _strip_llm_preamble ──────────────────────────────────────────────────────
def test_strip_llm_preamble_removes_the_lead_in():
    assert _strip_llm_preamble('Here is the cleaned essay:\nThe narration begins.') == 'The narration begins.'


def test_strip_llm_preamble_leaves_a_bare_body_alone():
    assert _strip_llm_preamble(PROSE) == PROSE
