# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Voice catalog for the Storyteller wizard (preview + dropdown population).

Ids keep their historical Azure-style spelling — they are opaque identifiers
that tts_service maps to a gender-matched reference wav in the voice seed pool."""

from __future__ import annotations

# V2 sample phrase (comparison line, same for every voice).
VOICE_PREVIEW_SENTENCE = 'The horizon glowed softly at dawn, and every word was meant to sound clear and natural.'
# V1 sample phrase (user-provided; used when warming local Azure samples).
VOICE_SAMPLE_V1 = "I did , then I didn't , now I don't . what a wonderfull life."

# id, label, gender (female|male|neutral), age_min, age_max, group label
_STORYTELLER_VOICES: list[dict] = [
    # Female — US
    {
        'id': 'en-US-AriaNeural',
        'label': 'Aria',
        'tag': 'US, neutral',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-JennyNeural',
        'label': 'Jenny',
        'tag': 'US, newscast',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-MichelleNeural',
        'label': 'Michelle',
        'tag': 'US, relaxed',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-MonicaNeural',
        'label': 'Monica',
        'tag': 'US, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-NancyNeural',
        'label': 'Nancy',
        'tag': 'US, relaxed',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-SaraNeural',
        'label': 'Sara',
        'tag': 'US, professional',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-AmberNeural',
        'label': 'Amber',
        'tag': 'US, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-AshleyNeural',
        'label': 'Ashley',
        'tag': 'US, friendly',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-ElizabethNeural',
        'label': 'Elizabeth',
        'tag': 'US, professional',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-EmmaNeural',
        'label': 'Emma',
        'tag': 'US, clear',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-JaneNeural',
        'label': 'Jane',
        'tag': 'US, calm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-NinaNeural',
        'label': 'Nina',
        'tag': 'US, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-AnaNeural',
        'label': 'Ana',
        'tag': 'US, young girl',
        'gender': 'female',
        'age_min': 0,
        'age_max': 15,
        'group': 'Female — US',
    },
    {
        'id': 'en-US-CoraNeural',
        'label': 'Cora',
        'tag': 'US, young girl',
        'gender': 'female',
        'age_min': 0,
        'age_max': 15,
        'group': 'Female — US',
    },
    # Female — UK
    {
        'id': 'en-GB-SoniaNeural',
        'label': 'Sonia',
        'tag': 'UK, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — UK',
    },
    {
        'id': 'en-GB-LibbyNeural',
        'label': 'Libby',
        'tag': 'UK, relaxed',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — UK',
    },
    {
        'id': 'en-GB-MaisieNeural',
        'label': 'Maisie',
        'tag': 'UK, young',
        'gender': 'female',
        'age_min': 13,
        'age_max': 17,
        'group': 'Female — UK',
    },
    {
        'id': 'en-GB-BellaNeural',
        'label': 'Bella',
        'tag': 'UK, soft',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — UK',
    },
    {
        'id': 'en-GB-OliviaNeural',
        'label': 'Olivia',
        'tag': 'UK, bright',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — UK',
    },
    {
        'id': 'en-GB-AbbiNeural',
        'label': 'Abbi',
        'tag': 'UK, cheerful',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — UK',
    },
    {
        'id': 'en-GB-HollieNeural',
        'label': 'Hollie',
        'tag': 'UK, friendly',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — UK',
    },
    # Female — AU / CA / IN / IE / NZ / SG / ZA
    {
        'id': 'en-AU-NatashaNeural',
        'label': 'Natasha',
        'tag': 'AU, professional',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-AU-AnnetteNeural',
        'label': 'Annette',
        'tag': 'AU, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-AU-CarlyNeural',
        'label': 'Carly',
        'tag': 'AU, friendly',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-AU-ElsieNeural',
        'label': 'Elsie',
        'tag': 'AU, calm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-AU-FreyaNeural',
        'label': 'Freya',
        'tag': 'AU, expressive',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-AU-JoanneNeural',
        'label': 'Joanne',
        'tag': 'AU, professional',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-AU-KimNeural',
        'label': 'Kim',
        'tag': 'AU, clear',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — AU',
    },
    {
        'id': 'en-CA-ClaraNeural',
        'label': 'Clara',
        'tag': 'CA, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — Canada',
    },
    {
        'id': 'en-CA-LilyNeural',
        'label': 'Lily',
        'tag': 'CA, gentle',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — Canada',
    },
    {
        'id': 'en-IN-NeerjaNeural',
        'label': 'Neerja',
        'tag': 'IN, professional',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — India',
    },
    {
        'id': 'en-IE-EmilyNeural',
        'label': 'Emily',
        'tag': 'IE, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — Ireland',
    },
    {
        'id': 'en-NZ-MollyNeural',
        'label': 'Molly',
        'tag': 'NZ, friendly',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — New Zealand',
    },
    {
        'id': 'en-SG-LunaNeural',
        'label': 'Luna',
        'tag': 'SG, clear',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — Singapore',
    },
    {
        'id': 'en-ZA-LeahNeural',
        'label': 'Leah',
        'tag': 'ZA, warm',
        'gender': 'female',
        'age_min': 18,
        'age_max': 120,
        'group': 'Female — South Africa',
    },
    # Male — US
    {
        'id': 'en-US-GuyNeural',
        'label': 'Guy',
        'tag': 'US, newscast',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-ChristopherNeural',
        'label': 'Christopher',
        'tag': 'US, authoritative',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-EricNeural',
        'label': 'Eric',
        'tag': 'US, relaxed',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-DavisNeural',
        'label': 'Davis',
        'tag': 'US, professional',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-RogerNeural',
        'label': 'Roger',
        'tag': 'US, newscast',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-SteffanNeural',
        'label': 'Steffan',
        'tag': 'US, professional',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-JasonNeural',
        'label': 'Jason',
        'tag': 'US, newscast',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-TonyNeural',
        'label': 'Tony',
        'tag': 'US, upbeat',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-AndrewNeural',
        'label': 'Andrew',
        'tag': 'US, warm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-BrandonNeural',
        'label': 'Brandon',
        'tag': 'US, friendly',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — US',
    },
    {
        'id': 'en-US-JacobNeural',
        'label': 'Jacob',
        'tag': 'US, young boy',
        'gender': 'male',
        'age_min': 0,
        'age_max': 15,
        'group': 'Male — US',
    },
    # Male — UK
    {
        'id': 'en-GB-RyanNeural',
        'label': 'Ryan',
        'tag': 'UK, deep',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    {
        'id': 'en-GB-ThomasNeural',
        'label': 'Thomas',
        'tag': 'UK, documentary',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    {
        'id': 'en-GB-AlfieNeural',
        'label': 'Alfie',
        'tag': 'UK, warm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    {
        'id': 'en-GB-ElliotNeural',
        'label': 'Elliot',
        'tag': 'UK, calm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    {
        'id': 'en-GB-EthanNeural',
        'label': 'Ethan',
        'tag': 'UK, clear',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    {
        'id': 'en-GB-NoahNeural',
        'label': 'Noah',
        'tag': 'UK, friendly',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    {
        'id': 'en-GB-OliverNeural',
        'label': 'Oliver',
        'tag': 'UK, bright',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — UK',
    },
    # Male — AU / CA / IN / IE / NZ / SG / ZA
    {
        'id': 'en-AU-WilliamNeural',
        'label': 'William',
        'tag': 'AU, professional',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — AU',
    },
    {
        'id': 'en-AU-DuncanNeural',
        'label': 'Duncan',
        'tag': 'AU, calm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — AU',
    },
    {
        'id': 'en-AU-DarrenNeural',
        'label': 'Darren',
        'tag': 'AU, friendly',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — AU',
    },
    {
        'id': 'en-AU-KenNeural',
        'label': 'Ken',
        'tag': 'AU, warm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — AU',
    },
    {
        'id': 'en-AU-NeilNeural',
        'label': 'Neil',
        'tag': 'AU, clear',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — AU',
    },
    {
        'id': 'en-CA-LiamNeural',
        'label': 'Liam',
        'tag': 'CA, warm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — Canada',
    },
    {
        'id': 'en-IN-PrabhatNeural',
        'label': 'Prabhat',
        'tag': 'IN, professional',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — India',
    },
    {
        'id': 'en-IE-ConnorNeural',
        'label': 'Connor',
        'tag': 'IE, warm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — Ireland',
    },
    {
        'id': 'en-NZ-MitchellNeural',
        'label': 'Mitchell',
        'tag': 'NZ, clear',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — New Zealand',
    },
    {
        'id': 'en-SG-WayneNeural',
        'label': 'Wayne',
        'tag': 'SG, professional',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — Singapore',
    },
    {
        'id': 'en-ZA-LukeNeural',
        'label': 'Luke',
        'tag': 'ZA, warm',
        'gender': 'male',
        'age_min': 18,
        'age_max': 120,
        'group': 'Male — South Africa',
    },
    # Narrator (any character)
    {
        'id': 'en-US-BrianNeural',
        'label': 'Brian',
        'tag': 'US, narrator',
        'gender': 'neutral',
        'age_min': 0,
        'age_max': 120,
        'group': 'Narrator (any character)',
        'narrator_eligible': True,
    },
]


def _narrator_eligible(v: dict) -> bool:
    if 'narrator_eligible' in v:
        return bool(v['narrator_eligible'])
    if v.get('id') == 'en-US-BrianNeural':
        return True
    return int(v.get('age_min', 0)) >= 18


def all_voice_ids() -> set[str]:
    return {v['id'] for v in _STORYTELLER_VOICES}


# 2026-07-31: server-side validation of a submitted voice, and the gender-correct
# Seed-pool pick in tts_service._voice_gender, both need id -> gender /
# age-band lookups. These accessors are the supported way to read that:
# _STORYTELLER_VOICES stays private and its data (ids, labels, genders, age bands)
# is unchanged. Every lookup normalises/strips the id and returns a neutral value
# for unknown ids rather than raising, so call sites stay branch-light.
_VOICE_BY_ID: dict[str, dict] = {v['id']: v for v in _STORYTELLER_VOICES}


def get_voice(voice_id: str) -> dict | None:
    """Full catalog entry (a copy) for voice_id, or None when it is not listed."""
    v = _VOICE_BY_ID.get((voice_id or '').strip())
    return dict(v) if v else None


def is_valid_voice_id(voice_id: str) -> bool:
    """True when voice_id is a catalog voice (use to reject submitted values)."""
    return (voice_id or '').strip() in _VOICE_BY_ID


def voice_gender(voice_id: str) -> str:
    """'female' | 'male' | 'neutral' for voice_id; '' when it is not in the catalog."""
    v = _VOICE_BY_ID.get((voice_id or '').strip())
    return str(v.get('gender') or '') if v else ''


def voice_gender_map() -> dict[str, str]:
    """{voice_id: 'female'|'male'|'neutral'} for the whole catalog."""
    return {vid: str(v.get('gender') or '') for vid, v in _VOICE_BY_ID.items()}


def voice_age_band(voice_id: str) -> tuple[int, int] | None:
    """(age_min, age_max) for voice_id, or None when it is not in the catalog."""
    v = _VOICE_BY_ID.get((voice_id or '').strip())
    if not v:
        return None
    return int(v.get('age_min', 0)), int(v.get('age_max', 120))


def voice_age_bands() -> dict[str, tuple[int, int]]:
    """{voice_id: (age_min, age_max)} for the whole catalog."""
    return {vid: (int(v.get('age_min', 0)), int(v.get('age_max', 120))) for vid, v in _VOICE_BY_ID.items()}


def voice_allows_age(voice_id: str, age) -> bool:
    """True when age falls inside the voice's age band.

    Unknown voice id or unparseable age → False (fail closed: an unlisted voice
    must never validate). Pass age=None only when you have no age to check, in
    which case the caller should skip this test entirely.
    """
    band = voice_age_band(voice_id)
    if band is None:
        return False
    try:
        a = int(age)
    except (TypeError, ValueError):
        return False
    return band[0] <= a <= band[1]


def list_storyteller_voices(*, kind: str = 'character') -> list[dict]:
    """Return voice entries. kind: 'character' (all) or 'narrator' (adult narrators)."""
    out: list[dict] = []
    for v in _STORYTELLER_VOICES:
        if kind == 'narrator':
            if _narrator_eligible(v):
                out.append(dict(v))
        else:
            out.append(dict(v))
    return out


def grouped_storyteller_voices(*, kind: str = 'character') -> list[dict]:
    """Return [{group, voices: [...]}] preserving catalog order."""
    rows = list_storyteller_voices(kind=kind)
    groups: list[dict] = []
    seen: dict[str, dict] = {}
    for v in rows:
        g = v['group']
        if g not in seen:
            seen[g] = {'group': g, 'voices': []}
            groups.append(seen[g])
        seen[g]['voices'].append(v)
    return groups


# 2026-07-31: explicit public surface (the private list stays out of it).
__all__ = [
    'VOICE_PREVIEW_SENTENCE',
    'VOICE_SAMPLE_V1',
    'all_voice_ids',
    'get_voice',
    'grouped_storyteller_voices',
    'is_valid_voice_id',
    'list_storyteller_voices',
    'voice_age_band',
    'voice_age_bands',
    'voice_allows_age',
    'voice_gender',
    'voice_gender_map',
]
