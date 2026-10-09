# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Subject classification and the documentary framework block."""


def _classify_subject_type(topic: str, crime_category: str = '') -> str:
    """Return a subject type key based on topic keywords.
    Returns one of: 'person', 'war', 'gold', 'history' (default).
    """
    t = (topic + ' ' + crime_category).lower()
    # History overrides — checked FIRST so e.g. "industrial revolution" / "scientific revolution"
    # never fall through to the war classifier on the word "revolution".
    _history_override_kw = (
        'industrial revolution',
        'industrial age',
        'industrial era',
        'scientific revolution',
        'agricultural revolution',
        'cultural revolution',
        'digital revolution',
        'technological revolution',
        'information revolution',
        'renaissance',
        'enlightenment',
        'reformation',
        'ancient',
        'medieval',
        'prehistoric',
        'archaeology',
        'dynasty',
        'civilization',
        'civilisation',
        'mesopotamia',
        'colonial',
        'colonialism',
        'history of',
    )
    for kw in _history_override_kw:
        if kw in t:
            return 'history'
    # Person signals
    _person_kw = (
        'serial killer',
        'murderer',
        'criminal',
        'gangster',
        'dictator',
        'president',
        'king',
        'queen',
        'emperor',
        'pharaoh',
        'warlord',
        'general',
        'leader',
        'biography',
        'life of',
        'story of',
        'portrait of',
        'profile of',
    )
    # War signals — use specific multi-word or clearly military terms to avoid over-triggering
    _war_kw = (
        'world war',
        'civil war',
        'cold war',
        'vietnam war',
        'korean war',
        'battle of',
        'invasion of',
        'siege of',
        'military coup',
        'genocide',
        'occupation',
        'wwi',
        'wwii',
        'nuclear bomb',
        'atom bomb',
        'armed conflict',
        'armed uprising',
        'armed rebellion',
        ' war ',
        ' war,',
        ' war.',
        'at war',
        'the war',
        'a war',
    )
    # Gold/resources/money signals
    _gold_kw = (
        'gold',
        'silver',
        'oil',
        'diamond',
        'mineral',
        'resource',
        'money',
        'bank',
        'currency',
        'economy',
        'trade',
        'drug',
        'cartel',
        'trafficking',
        'heist',
        'robbery',
        'fraud',
        'corruption',
        'mafia',
        'organized crime',
        'crypto',
        'finance',
        'wall street',
        'stock',
        'wealth',
        'poverty',
    )
    for kw in _person_kw:
        if kw in t:
            return 'person'
    for kw in _war_kw:
        if kw in t:
            return 'war'
    for kw in _gold_kw:
        if kw in t:
            return 'gold'
    return 'history'


def _build_framework_block(subject_type: str, topic: str) -> str:
    """Return a documentary framework context block for the given subject type.
    This is injected into Stage 3 prompts to guide narrative structure and depth.
    """
    _universal = (
        'DOCUMENTARY FRAMEWORK — answer these narrative dimensions as you write:\n'
        '• IDENTITY: What is it? What makes it unique? What misconceptions exist?\n'
        '• ORIGINS: Where did it come from? What conditions caused it to exist?\n'
        '• MECHANISM: How does it work? What hidden processes are involved?\n'
        '• HUMAN IMPACT: How does it affect ordinary people? Who suffers, who benefits?\n'
        '• CONFLICT: What controversies, struggles, dangers, and power clashes surround it?\n'
        '• SCALE: How large is the impact globally? What industries or nations are affected?\n'
        '• VISUAL/ATMOSPHERIC: What environments, sounds, and iconic images define it?\n'
        '• PHILOSOPHICAL: What does this reveal about humanity? What moral questions arise?\n'
        '• LESSONS: What patterns repeat? What can history teach us here?\n'
        '• FUTURE: What is happening today? What might happen next?\n'
    )
    if subject_type == 'person':
        return (
            'DOCUMENTARY FRAMEWORK — subject is a PERSON:\n'
            '• Who are they really? What childhood or trauma shaped them?\n'
            '• What motivated them — power, ideology, survival, obsession?\n'
            '• What made them powerful, famous, or dangerous?\n'
            '• What contradictions existed in their personality?\n'
            '• How did victims, allies, and opponents view them?\n'
            '• What private side did the public never see?\n'
            '• What myths or distortions surround their legacy?\n'
            '• What legacy, good or terrible, did they leave behind?\n'
            '• What does their story reveal about the society that produced them?\n'
        )
    elif subject_type == 'war':
        return (
            'DOCUMENTARY FRAMEWORK — subject is WAR/CONFLICT:\n'
            '• Why did the conflict begin? Who wanted it? What tensions preceded it?\n'
            '• What major turning points changed the course of the war?\n'
            '• What technologies, tactics, or strategies were used?\n'
            '• How did civilians experience the conflict — fear, loss, displacement?\n'
            '• What propaganda was spread, and what atrocities occurred?\n'
            '• Who profited from the war? What power structures were reinforced or broken?\n'
            '• What was the human cost — lives, communities, generations lost?\n'
            '• How did the conflict reshape borders, nations, and ideologies?\n'
            "• What parallels exist between this conflict and today's world?\n"
        )
    elif subject_type == 'gold':
        return (
            'DOCUMENTARY FRAMEWORK — subject is RESOURCES/POWER/CRIME:\n'
            '• Why is it valuable? What drives human obsession with it?\n'
            '• How was it discovered, extracted, or built?\n'
            '• Who controls it? What cartels, governments, or corporations hold power?\n'
            '• What economies, communities, or nations depend on it?\n'
            '• What crimes, wars, or exploitation were caused by it?\n'
            '• How has it shaped or corrupted civilizations?\n'
            '• What environmental, social, or human damage does it cause?\n'
            '• What happens when supply shifts — who wins, who loses?\n'
            '• What does the pursuit of this resource reveal about human greed?\n'
        )
    else:
        return _universal
