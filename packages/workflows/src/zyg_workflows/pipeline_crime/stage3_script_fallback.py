# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3 structured narration — the ~1350-word script built without any LLM.

Extracted from ``_crime_stage_3_script`` (606 lines). The text is the original
f-string, split at its own ``\\n\\n`` section seams into four parts so each one fits
in a test; concatenating them reproduces the old script byte for byte.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CrimeCaseFacts:
    """The ten case values the structured narration interpolates.

    Built by :meth:`from_selected` out of the Stage 1 case dict, so the narration
    parts take one argument instead of ten enclosing locals.
    """

    name: str
    category: str
    year: str
    state: str
    court: str
    summary: str
    why_narrate: str
    title: str
    location: str
    when_phrase: str

    @classmethod
    def from_selected(cls, selected: dict) -> 'CrimeCaseFacts':
        """Return the facts for ``selected``, with the original defaults.

        In: the Stage 1 case dict. Out: a ``CrimeCaseFacts`` where a missing name
        becomes 'the subject', a missing category 'serious offense', a missing
        title 'The Case of <name>', a missing state 'the United States', and a
        missing year the undated opening phrase.
        """
        _n = selected.get('name', 'the subject')
        _st = selected.get('state', '')
        _yr = str(selected.get('year', ''))
        return cls(
            name=_n,
            category=selected.get('crime_category', 'serious offense'),
            year=_yr,
            state=_st,
            court=selected.get('court', ''),
            summary=selected.get('summary', ''),
            why_narrate=selected.get('why_narrate', ''),
            title=selected.get('case_title', f'The Case of {_n}'),
            location=f'the state of {_st}' if _st else 'the United States',
            when_phrase=f'In {_yr}, ' if _yr else 'In a period that would become etched in history, ',
        )


def _narration_intro_and_background(facts: CrimeCaseFacts) -> str:
    """Return the introduction and the background/context sections.

    In: the case facts. Out: the opening ('Welcome to Crime Chronicles…') through
    the warning-signs paragraph, ending on a blank line.
    """
    return (
        # ── Introduction ─────────────────────────────────────────────
        f'Welcome to Crime Chronicles. '
        f"Today's episode examines one of the most significant criminal cases in American legal history. "
        f'The case is titled: {facts.title}. '
        f'What follows is a factual account drawn from court records, investigative reports, '
        f'and the public record. '
        f'No detail has been invented or embellished. Everything presented here is grounded in documented fact. '
        f'\n\n'
        f'In {facts.location}, the criminal justice system has seen many difficult and complex cases '
        f'over the decades. '
        f'Few, however, have drawn the level of public attention, legal scrutiny, and lasting societal impact '
        f'as the case we are about to examine today. '
        f'{facts.when_phrase}events began to unfold that would eventually lead to a courtroom reckoning '
        f'of extraordinary proportions. '
        f'The individual at the center of these proceedings is {facts.name}. '
        f'By the time the legal process concluded, this name would be known across the country — '
        f'and in many respects, around the world. '
        f'\n\n'
        # ── Background and context ────────────────────────────────────
        f'To understand this case fully, we must first consider the broader context in which these events occurred. '
        f'The charges brought before {facts.court if facts.court else "the court"} fell under the category '
        f'of {facts.category}. '
        f'Cases of this nature are among the most serious that prosecutors can bring before a jury. '
        f'They require extensive and painstaking investigation, the careful collection and preservation of evidence, '
        f'and a legal team fully prepared to present a case that meets the high standard of proof '
        f'required for a criminal conviction in a court of law. '
        f'The burden of proof — beyond a reasonable doubt — is the highest standard in the legal system, '
        f'and it exists for good reason: to protect the innocent while holding the guilty accountable. '
        f'\n\n'
        f'The community in {facts.location} had lived with a growing unease in the period leading up '
        f'to these events. '
        f'There were questions that had gone unanswered, concerns that had been raised and set aside. '
        f'In hindsight, the warning signs were present. '
        f'But it is often only in retrospect that such signs become clear. '
        f'At the time, few could have anticipated the full scale of what investigators would eventually uncover. '
        f'\n\n'
    )


def _narration_facts_and_investigation(facts: CrimeCaseFacts) -> str:
    """Return the established-facts, investigation and arrest sections.

    In: the case facts (the case summary is quoted verbatim). Out: the three
    sections, ending on a blank line.
    """
    return (
        # ── The facts ─────────────────────────────────────────────────
        f'The facts of the case, as established through investigation and confirmed at trial, are as follows. '
        f'{facts.summary} '
        f'\n\n'
        f'These are not allegations. These are the established facts of record. '
        f'The evidence that supported these findings was extensive and, in many respects, overwhelming. '
        f'Physical evidence, documentary evidence, and the testimony of witnesses all pointed '
        f'in the same direction. '
        f"The prosecution's case was not built on a single piece of evidence, "
        f'but on a comprehensive body of material that together formed an irrefutable account of events. '
        f'\n\n'
        # ── Investigation ─────────────────────────────────────────────
        f'The investigation itself was a landmark undertaking that tested the resources and resolve '
        f'of law enforcement at every level. '
        f'Agencies coordinated their efforts across jurisdictions, pooling expertise and sharing information '
        f'to ensure that the full picture could be assembled. '
        f'Lead investigators spent months — in some cases years — working through the evidence, '
        f'following every lead, and building the case piece by piece. '
        f'\n\n'
        f'Detectives conducted interviews with dozens of witnesses, many of whom were initially reluctant '
        f'to come forward. '
        f'Gaining the trust of key witnesses is often one of the most challenging aspects of a major investigation. '
        f'It requires patience, skill, and a deep understanding of human behavior. '
        f'The investigators on this case demonstrated all three in abundance. '
        f'\n\n'
        f'Forensic specialists examined the physical evidence with meticulous care. '
        f'Modern forensic science has transformed the ability of investigators to reconstruct events '
        f'and establish facts that would otherwise remain in doubt. '
        f'In this case, forensic analysis played a central role in confirming the sequence of events '
        f'and linking the evidence to the charges brought before the court. '
        f'The process was lengthy and, at times, deeply troubling for all involved. '
        f'Yet the determination of those pursuing the truth never wavered. '
        f'\n\n'
        # ── Arrest and charges ────────────────────────────────────────
        f'When {facts.name} was formally charged, the legal proceedings entered a new and critical phase. '
        f'The arraignment drew significant media attention, with reporters and cameras gathered '
        f'outside the courthouse to document every development. '
        f"Legal commentators debated the strength of the prosecution's case "
        f'and the potential defenses that might be mounted in response. '
        f'Members of the public followed developments closely, many of them personally affected '
        f'by what had occurred, all of them anxious for the process to run its course '
        f'and deliver a just and transparent outcome. '
        f'\n\n'
    )


def _narration_trial_and_verdict() -> str:
    """Return the trial, verdict and sentencing sections.

    In: nothing — these paragraphs interpolate no case values. Out: the three
    sections, ending on a blank line.
    """
    return (
        # ── Trial ─────────────────────────────────────────────────────
        'The trial itself was a masterclass in modern criminal procedure. '
        'Prosecutors laid out their case methodically, calling witnesses in a carefully considered order. '
        'Each witness contributed another layer to the account of what had occurred, '
        'building a narrative that was coherent, consistent, and corroborated at every turn. '
        'Expert witnesses — including forensic scientists, medical professionals, and specialists '
        'in their respective fields — helped the jury understand the technical dimensions of the evidence '
        'in terms that were clear and accessible. '
        '\n\n'
        'The defense, for their part, mounted challenges at every opportunity. '
        'They questioned the reliability of witness testimony, challenged the chain of custody '
        'of physical evidence, and offered alternative interpretations of the forensic data. '
        'This is, of course, the proper function of a defense team in an adversarial legal system: '
        "to test the prosecution's case, to hold it to the highest possible standard, "
        'and to ensure that every argument in favor of the accused has been fully explored. '
        "Despite their efforts, the prosecution's case held firm at every point of challenge. "
        '\n\n'
        'Throughout the proceedings, the presiding judge maintained strict and impartial control '
        'over the courtroom. '
        'Rulings on the admissibility of evidence shaped the narrative that the jury ultimately heard. '
        'Legal motions were filed, argued, and decided with deliberate and careful consideration. '
        'The process, though at times slow and painstaking, exemplified the foundational principle '
        'of the justice system: that justice must not only be done, but must be seen to be done. '
        '\n\n'
        # ── Verdict ───────────────────────────────────────────────────
        'After deliberating carefully on the totality of the evidence presented, '
        'the jury returned its verdict. '
        'The findings reflected the weight of the case that the prosecution had built '
        'over the course of the trial. '
        'For those who had followed the proceedings, the outcome came as little surprise. '
        'For the families of those directly affected by the offenses, '
        'the verdict represented a measure of closure — though it was understood by all '
        'that no legal outcome could fully undo the harm that had been caused. '
        '\n\n'
        'For the legal community, this case became a significant reference point — '
        'studied in law schools, cited in subsequent proceedings, and examined in scholarly work '
        'on criminal justice, procedure, and the nature of evidence. '
        'It contributed to ongoing discussions about how the justice system handles cases '
        'of this magnitude, and what improvements might be made to better serve '
        'both victims and the broader public interest. '
        '\n\n'
        # ── Sentencing ────────────────────────────────────────────────
        'At sentencing, the court gave careful consideration to the full scope of the offenses committed. '
        'The severity of the conduct, the impact on the victims and their families, '
        'and the broader implications for public safety all weighed heavily in the deliberation. '
        'Victim impact statements were heard — powerful, personal accounts that reminded '
        'the court and everyone present of the human reality behind the legal proceedings. '
        'The sentence handed down was commensurate with the gravity of the case '
        "and reflected the court's clear assessment of the offenses before it. "
        'It sent an unambiguous message about the standards that a civilised society expects '
        'and the consequences that must follow when those standards are violated. '
        '\n\n'
    )


def _narration_legacy_and_closing(facts: CrimeCaseFacts) -> str:
    """Return the legacy, public-record and closing sections.

    In: the case facts (``why_narrate`` and ``title`` are quoted). Out: the
    closing third of the script, ending on the subscribe line with no trailing
    blank line.
    """
    return (
        # ── Legacy and significance ────────────────────────────────────
        f'What makes this case particularly significant — beyond the immediate facts of the matter — '
        f'is its broader importance to the study and understanding of criminal justice. '
        f'{facts.why_narrate} '
        f'\n\n'
        f'Cases like this one serve as important and sobering reminders of the essential role '
        f'that institutions play in maintaining the fabric of a civilised and ordered society. '
        f'The courts, the investigators, the prosecutors and defense attorneys, '
        f'the forensic specialists and expert witnesses — all of them contributed '
        f'to a process specifically designed to deliver truth, accountability, and, where possible, justice. '
        f'That process is imperfect, as all human institutions are. '
        f'But it remains the best system that democratic societies have developed '
        f'for resolving disputes of the most serious and consequential kind. '
        f'\n\n'
        # ── Public record ─────────────────────────────────────────────
        f'The record of {facts.title} remains accessible to researchers, legal professionals, journalists, '
        f'and members of the public who wish to understand what occurred, '
        f'how the justice system responded, and what lessons might be drawn from the experience. '
        f'Court documents, trial transcripts, investigative reports, and related materials '
        f'have been preserved as part of the permanent public record. '
        f'They stand as a testament to the enduring importance of transparency, '
        f'accountability, and the rule of law in a democratic society. '
        f'\n\n'
        f'It is worth reflecting, as we conclude this account, on the individuals '
        f'whose lives were most directly affected by these events. '
        f'Behind every case of this kind are real people — victims, families, communities — '
        f'whose experiences deserve to be acknowledged with respect and solemnity. '
        f'The purpose of examining cases like this one is not to sensationalise or to exploit tragedy, '
        f'but to ensure that the public record is understood, that history is not forgotten, '
        f'and that the lessons of the past can inform a more just and careful future. '
        f'\n\n'
        # ── Closing ───────────────────────────────────────────────────
        f'This has been Crime Chronicles. '
        f'We present these cases to inform, to document, and to ensure '
        f'that the public record is properly understood and remembered. '
        f'The facts matter. The process matters. '
        f'And the people affected by these events matter most of all. '
        f'Thank you for watching. If you found this episode informative, '
        f'please consider subscribing to Crime Chronicles for more documented accounts '
        f'from the public record of American criminal justice.'
    )


def _build_structured_narration(selected: dict) -> str:
    """Build the full ~1350-word narration (~9.3 min at 145 wpm) from case data.

    In: the Stage 1 case dict. Out: the four narration parts concatenated in the
    original order — no LLM, no network.
    """
    facts = CrimeCaseFacts.from_selected(selected)
    return (
        _narration_intro_and_background(facts)
        + _narration_facts_and_investigation(facts)
        + _narration_trial_and_verdict()
        + _narration_legacy_and_closing(facts)
    )
