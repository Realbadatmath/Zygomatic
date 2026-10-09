# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""brief_prep.py — Composition, part 1: the UI spec, brief normalisation and the plan skeleton.

Moved verbatim out of ``kids_music_theory.py`` (original lines 1771-2211).
"""

from __future__ import annotations


from zyg_workflows.kids_music_theory.vocabulary import AGE_BANDS, LYRIC_LINE_CAP, MODES, MOODS, NAME_TO_PC, PARENT_OF

from zyg_workflows.kids_music_theory.styles import (
    EXCLUDED_STYLES,
    SONG_SECONDS,
    SONG_SECONDS_DEFAULT,
    SONG_SECONDS_HARD,
    STYLES,
    STYLE_FAMILY,
)

from zyg_workflows.kids_music_theory.cinematic import (
    CINEMATIC_FAMILY,
    CINEMATIC_STYLES,
    DEFAULT_THEME,
    LYRICS_MODES,
    STYLE_FAMILIES,
    style_lookup,
)

from zyg_workflows.kids_music_theory.singers import DEFAULT_SINGER, SINGERS

from zyg_workflows.kids_music_theory.forms import FORMS, METERS, PROGRESSIONS

from zyg_workflows.kids_music_theory.pitch import _index_pcs, _note_name


# ── Composition ──────────────────────────────────────────────────────────────


def ui_spec():
    """The option vocabulary every UI builds itself from — ONE definition.

    Both bp_kidsmusic.km_spec and kanban_server._km_spec used to build this
    dict independently and had already drifted (one carried `syllables`, the
    other did not, and neither carried a singer). A panel that offers an option
    the composer does not implement is a defect the composer cannot catch, so
    the vocabulary now has a single owner and both routes call this.
    """
    return {
        'age_bands': [
            {
                'key': k,
                'label': v['label'],
                'range': f'{_note_name(v["lo"])}-{_note_name(v["hi"])}',
                'bpm': list(v['bpm']),
                'max_span': v['max_span'],
                'syllables': list(v['syllables']),
                # A panel that offers "Instrumental (cinematic)" in a
                # list of ages needs to know it is not one — no singer
                # picker, no lyric box, no syllable talk.
                'instrumental': bool(v.get('instrumental')),
            }
            for k, v in AGE_BANDS.items()
        ],
        'families': [{'key': k, 'label': v['label']} for k, v in STYLE_FAMILIES.items()],
        'moods': [
            {'key': k, 'label': v['label'], 'meters': v['meters'], 'modes': v['modes'], 'bpm': list(v['bpm'])}
            for k, v in MOODS.items()
        ],
        'meters': [{'key': k, 'label': v['label']} for k, v in METERS.items()],
        'modes': [{'key': k, 'label': v['label']} for k, v in MODES.items()],
        'forms': [{'key': k, 'label': v['label']} for k, v in FORMS.items()],
        'styles': [
            {
                'key': k,
                'label': v['label'],
                'shelf': v['shelf'],
                'mood': v['mood'],
                'moods': list(v['moods']),
                'age_band': v['age_band'],
                'form': v['form'],
                'meter': v['meter'],
                'seconds': v['seconds'],
                'lyrics_mode': v['lyrics_mode'],
                'voices': dict(v['voices']),
            }
            for k, v in STYLES.items()
        ],
        # A SEPARATE LIST, not more rows in `styles`. The two families do not
        # share a shape — these have no lyrics_mode, no age_band and no mood to
        # choose from, and they do have an `extra` part — so a panel that tried
        # to render them in one table would have to branch on every cell anyway.
        'cinematic_styles': [
            {
                'key': k,
                'label': v['label'],
                'shelf': v['shelf'],
                'mode': v['mode'],
                'meter': v['meter'],
                'bpm': list(v['bpm']),
                'form': v['form'],
                'seconds': v['seconds'],
                'voices': dict(v['voices']),
                'extra': dict(v['extra']),
            }
            for k, v in CINEMATIC_STYLES.items()
        ],
        # Said out loud, for the same reason `singer_note` is: an absent option
        # looks like a bug unless the panel can name the decision.
        'styles_excluded': dict(EXCLUDED_STYLES),
        'lyrics_modes': [{'key': k, 'label': v} for k, v in LYRICS_MODES.items()],
        'singers': [
            {
                'key': k,
                'label': v['label'] + (f' · {v["voice"]}' if v.get('voice') else ''),
                'voice': v.get('voice'),
                'ace_seed': v.get('ace_seed'),
                'band_hz': list(v['band']),
                'measured_hz': list(v['measured']),
            }
            for k, v in SINGERS.items()
        ],
        'singer_default': DEFAULT_SINGER,
        # Said out loud in the panel, because "no teen option" looks like an
        # oversight otherwise. It is a measurement.
        'singer_note': (
            'The songs are for children and are sung by adults. A teen '
            "option is not offered: the children's-choir caption did not "
            'separate from adult female (n=3), and voice_qc cannot '
            'separate teen male from adult female on F0 and vocal-tract '
            'length.'
        ),
        'tonics': ['C', 'D', 'Eb', 'E', 'F', 'G', 'A', 'Bb'],
        'seconds': {
            'min': int(SONG_SECONDS_HARD[0]),
            'max': int(SONG_SECONDS_HARD[1]),
            'default': int(SONG_SECONDS_DEFAULT),
            'band': [int(SONG_SECONDS[0]), int(SONG_SECONDS[1])],
            'band_note': (
                "Children's songs are produced between "
                f'{int(SONG_SECONDS[0])} and {int(SONG_SECONDS[1])} s '
                '(operator, 2026-10-02). A shorter explicit value '
                'still renders.'
            ),
        },
    }


def lyric_hint_for(brief):
    """The one sentence appended to the lyric prompt's Rules, and to the picture
    planner's prompt — ONE owner, because two callers resolving it separately is
    how they drift apart.

    An explicit ``brief['lyric_hint']`` wins over the style's, which is the same
    rule every other style default follows. The explicit case is what lets a
    SERIES pin its point of view ("every line is about Jack himself") on top of a
    musical format it shares with every other storytime song; without it a series
    would need a style of its own, and a style is a format, not a character.
    """
    own = str((brief or {}).get('lyric_hint') or '').strip()
    if own:
        return own
    S = STYLES.get((brief or {}).get('style')) if isinstance((brief or {}).get('style'), str) else None
    return str((S or {}).get('lyric_hint') or '').strip()


def _normalise_brief(brief):
    """Fill a partial brief with musically coherent defaults.

    Order matters: mood decides which modes and meters are on the table, the age
    band clamps tempo, and an explicitly requested value always wins over both.
    """
    b = dict(brief or {})

    # The style layer supplies the DEFAULTS below; every explicit operator value
    # still wins, exactly as it already did over a mood's defaults. An unknown
    # style is not an error here (km_start rejects it at the door) — it is simply
    # no style, recorded as None so the caller can see it was dropped.
    # Which family the style key is looked up in. 'children' by default, so a
    # brief that predates the cinematic family resolves exactly as it always did.
    _fam_req = b.get('family') if b.get('family') in STYLE_FAMILIES else 'children'
    _fam, _entry = style_lookup(b.get('style'), _fam_req)
    S = _entry if _fam == 'children' else None
    CS = _entry if _fam == 'cinematic' else None

    if CS:
        # NOT NEGOTIABLE, unlike everything else a style sets. The band is the
        # instrument's range and the mood is the SoundFont fallback patch; a
        # cinematic cue composed against a toddler's larynx is not a cue, and
        # there is no operator intent that makes it one.
        age, mood = 'cinematic', 'cinematic'
    else:
        age = b.get('age_band') if b.get('age_band') in AGE_BANDS else (S['age_band'] if S else 'preschool')
        if S:
            # Inside the style's own list an explicit mood is honoured; outside
            # it the style wins — "Lullaby" with mood=marching is not a lullaby.
            mood = b.get('mood') if b.get('mood') in S['moods'] else S['mood']
        else:
            mood = b.get('mood') if b.get('mood') in MOODS else 'happy'
    band, mo = AGE_BANDS[age], MOODS[mood]

    # A cinematic style names its own mode and metre — the single 'cinematic'
    # mood is too wide to default from (it lists four modes and four metres so
    # that thirteen cues fit inside it). An explicit valid value still wins.
    mode = b.get('mode') if b.get('mode') in MODES else (CS['mode'] if CS else mo['modes'][0])
    meter = (
        b.get('meter')
        if b.get('meter') in METERS
        else (CS['meter'] if CS else ((S['meter'] if S and S['meter'] else None) or mo['meters'][0]))
    )
    # A 'facts' lyric ("Train has a conductor / Train has wheels / ...") wants
    # one repeated phrase, not a verse/bridge contrast — default the form to
    # AAAA unless the caller explicitly asked for something else. 'counting'
    # ("one … two … three …") is the same shape for the same reason.
    lyrics_mode = b.get('lyrics_mode') if b.get('lyrics_mode') in LYRICS_MODES else (S['lyrics_mode'] if S else 'theme')
    default_form = (
        CS['form'] if CS else (S['form'] if S else ('AAAA' if lyrics_mode in ('facts', 'counting') else 'AABA'))
    )
    form = b.get('form') if b.get('form') in FORMS else default_form

    tonic = str(b.get('tonic') or '').strip()
    tonic_pc = NAME_TO_PC.get(tonic, None)
    if tonic_pc is None:
        # Default keys keep the melody's tessitura inside the band's range with
        # the fewest black notes for anyone playing along: C, D, F or G.
        # `.get`, not `[]`: this table was keyed on the three SUNG bands, so the
        # 'cinematic' band added later raised KeyError for any brief that did
        # not name a tonic — which is every brief the selftest builds. D is the
        # cinematic default because the family's leads are orchestral: D major
        # and D minor are the open-string keys for violin, viola and cello, and
        # D sits mid-staff for flute, oboe and horn in F.
        tonic = {'toddler': 'C', 'preschool': 'D', 'early': 'F', 'cinematic': 'D'}.get(age, 'C')
        tonic_pc = NAME_TO_PC[tonic]

    lo_bpm, hi_bpm = mo['bpm']
    blo, bhi = band['bpm']
    lo_bpm, hi_bpm = max(lo_bpm, blo), min(hi_bpm, bhi)
    if lo_bpm > hi_bpm:  # mood and band disagree (lullaby
        lo_bpm, hi_bpm = mo['bpm']  # for early school) — mood wins
    if CS:
        # The STYLE owns the tempo window here, not the mood: 'cinematic' spans
        # 50-176 bpm so that Sad and Chase can both live in it, which makes its
        # midpoint (113) meaningless for either.
        lo_bpm, hi_bpm = CS['bpm']
    try:
        bpm = float(b.get('bpm') or 0) or 0.0
    except (TypeError, ValueError):
        bpm = 0.0
    if not (40.0 <= bpm <= 200.0):
        bpm = (lo_bpm + hi_bpm) / 2.0
    if CS:
        # An explicit tempo INSIDE the window wins; one outside it is clamped
        # rather than honoured. A 60 bpm Chase is not a slow chase, it is a
        # different cue wearing the label.
        bpm = min(float(hi_bpm), max(float(lo_bpm), bpm))

    try:
        seconds = float(b.get('seconds') or 0) or 0.0
    except (TypeError, ValueError):
        seconds = 0.0
    # The default is the BAND's middle for a children's song with no style and no
    # length of its own; a cinematic cue keeps its own (it is not children's music).
    _def_secs = float(CS['seconds'] if CS else (S['seconds'] if S else SONG_SECONDS_DEFAULT))
    seconds = max(SONG_SECONDS_HARD[0], min(SONG_SECONDS_HARD[1], seconds or _def_secs))

    # Who sings it. An unknown value is NOT silently defaulted here — km_start
    # rejects it at the door — but a brief that reaches the composer without one
    # (the CLI, a stored plan) gets the documented default rather than a crash.
    singer = b.get('singer') if b.get('singer') in SINGERS else DEFAULT_SINGER

    # 64, not 32. run() asks for 42 lines at the advertised 180 s maximum, so a
    # 32-line cap silently truncated the lyric and lyrics_block then emitted bare
    # [verse] tags with no words under them — which is what went to ACE-Step.
    # The truncation is now recorded rather than being invisible.
    _raw_lines = [str(x)[:160] for x in (b.get('lyrics_lines') or [])]
    _lines = _raw_lines[:LYRIC_LINE_CAP]

    b.update(
        {
            'theme': str(b.get('theme') or DEFAULT_THEME).strip()[:200],
            'age_band': age,
            'mood': mood,
            'mode': mode,
            'meter': meter,
            'form': form,
            'tonic': tonic,
            'tonic_pc': tonic_pc,
            'bpm': round(bpm),
            'seconds': seconds,
            'sung': bool(b.get('sung', True)),
            'singer': singer,
            'title': str(b.get('title') or '').strip()[:120],
            'lyrics_lines': _lines,
            'lyrics_truncated': max(0, len(_raw_lines) - len(_lines)),
            'lyrics_mode': lyrics_mode,
            'subject': str(b.get('subject') or '').strip()[:80],
        }
    )
    # Style keys are added ONLY when a style resolved. A brief without `style`
    # must come out of here byte-identical to what it produced before the style
    # layer existed — everything downstream reads this dict by key, and a new
    # key that is always present is a new thing every caller has to ignore.
    if S:
        b['family'] = STYLE_FAMILY
        b['shelf'] = S['shelf']
        b['voices'] = dict(S['voices'])
        b['style_perc'] = bool(S['perc'])
    elif CS:
        b['family'] = CINEMATIC_FAMILY
        b['shelf'] = CS['shelf']
        b['voices'] = dict(CS['voices'])
        b['extra'] = dict(CS['extra'])
        b['style_perc'] = False
        # SAID OUT LOUD RATHER THAN SILENTLY OBEYED. A caller that asked for a
        # sung cinematic cue has a bug — there is no lyric leg in this family —
        # and a brief that just came back with sung=False would hide it.
        if bool((brief or {}).get('sung', False)):
            b['sung_forced_off'] = True
        b['sung'] = False
    elif 'style' in b:
        b['style'] = None
    return b


def _lines_per_section(band):
    """How many 2-bar lines a section is built from.

    Two for a sung band — a child's phrase is as long as a child's breath. Four
    for the cinematic band, because nobody is breathing: the orchestral cue's
    unit is the EIGHT-bar period, and a cue cut into 4-bar sections states its
    idea and answers it before it has finished being an idea.
    """
    return 4 if band.get('long_phrases') else 2


def _plan_sections(brief):
    """How many sections fit the requested duration, and in what order."""
    meter = brief['meter']
    bar_beats = METERS[meter]['beats']
    bpm = brief['bpm']
    sec_per_bar = bar_beats * 60.0 / bpm
    section_bars = 2 * _lines_per_section(AGE_BANDS[brief['age_band']])
    intro_bars = 2 if brief['seconds'] >= 35 else 0
    outro_bars = 2 if brief['seconds'] >= 35 else 1
    body_seconds = max(8.0, brief['seconds'] - (intro_bars + outro_bars) * sec_per_bar)
    n_sections = max(2, int(round(body_seconds / (section_bars * sec_per_bar))))
    pattern = FORMS[brief['form']]['pattern']
    order = [pattern[i % len(pattern)] for i in range(n_sections)]
    # A song must not end on its bridge — swap the tail back to the home section.
    if order[-1] not in ('A',) and 'A' in order:
        order[-1] = 'A'
    return order, intro_bars, outro_bars


def _progressions_for(mode, name):
    parent = PARENT_OF[mode]
    home = PROGRESSIONS.get(parent, PROGRESSIONS['major'])
    away = PROGRESSIONS.get(parent + '_b', PROGRESSIONS['major_b'])
    return away if name in ('B', 'C') else home


def _syllable_targets(brief, n_sections):
    """Note budget per 2-bar line — one line per 2 bars, `_lines_per_section`
    lines per section.

    Named for syllables because that is what constrains a SUNG line, but it is a
    note budget in both families: the cinematic band has no lyric, so the `if
    not lines` branch is the only one it ever takes and the band's `syllables`
    pair is read purely as "notes per two bars".
    """
    band = AGE_BANDS[brief['age_band']]
    lo, hi = band['syllables']
    per_section = _lines_per_section(band)
    lines = brief.get('lyrics_lines') or []
    out = []
    for i in range(n_sections * per_section):
        if i < len(lines):
            out.append(max(2, count_syllables(lines[i])))
        else:
            out.append(0)  # free — the rhythm search is unconstrained
    if not lines:
        # No lyrics: still give the rhythm a note budget, or every line reaches
        # for the busiest cells it is allowed and the tune turns into a study.
        mid = (lo + hi) / 2.0
        out = [int(round(mid + (0.8 if i % 2 else -0.8))) for i in range(n_sections * per_section)]
    return out


_VOWELS = 'aeiouy'


def count_syllables(word_or_line):
    """Cheap English syllable count — good enough to BUDGET a line against a
    rhythm.  It is never used to claim a lyric scans; the fitted note count is
    reported so a human can see where it missed."""
    total = 0
    for w in str(word_or_line).lower().replace('-', ' ').split():
        w = ''.join(ch for ch in w if ch.isalpha() or ch == "'")
        if not w:
            continue
        n, prev = 0, False
        for ch in w:
            v = ch in _VOWELS
            if v and not prev:
                n += 1
            prev = v
        if w.endswith('e') and n > 1 and not w.endswith(('le', 'ye')):
            n -= 1
        total += max(1, n)
    return total


def _narrow_band_for_singer(band, brief):
    """Intersect the age band with the singer's comfortable sung window.

    The age band answers "what can a child of this age reach?".  Nobody in the
    room is a child: the record is made by an adult, and the child sings ALONG
    with it.  A D-major pentatonic drawn inside preschool's C4-D5 settles around
    A4 with D5 on top, which is exactly the octave in which every female voice
    crosses its first passaggio — so the take either belts or flips.  The two
    constraints are both real, so the melody lives in their INTERSECTION rather
    than in whichever one was written down first.

    Returns `(band, tessitura)`. The band is a copy when it was narrowed and the
    original dict otherwise, so an instrumental or male brief is byte-identical
    to what it composed before this existed.
    """
    lo, hi = band['lo'], band['hi']
    win = None
    # `instrumental` is checked as well as the family because the cinematic
    # AGE BAND is an instrument's range, and a brief can reach it without the
    # cinematic style that would have set sung=False (the CLI, the selftest).
    # Nothing sings there, so no singer's comfort applies.
    if brief.get('sung') and brief.get('family', 'children') == 'children' and not band.get('instrumental'):
        win = SINGERS.get(brief.get('singer') or '', {}).get('sung_window')
    if not win:
        return band, {
            'lo': lo,
            'hi': hi,
            'source': 'age_band',
            'window_note': f'{band["label"]} band, no singer window applied',
        }
    lo, hi = max(lo, int(win[0])), min(hi, int(win[1]))
    # A window this narrow does not hold every key. C major pentatonic inside
    # D4-B4 is D-E-G-A: four notes and no tonic, and the note loop needs a tonic
    # to cadence on. Refuse the narrowing in that case rather than composing an
    # unfinishable tune — the age band is still musically legal, it is only the
    # adult's comfort that is given up, and the plan says which it got.
    _n = len(MODES[brief['mode']]['steps'])
    _win = _index_pcs(brief['tonic_pc'], brief['mode'], lo, hi, 48)
    if len(_win) < 5 or not any(i % _n == 0 for i, _, _ in _win):
        return band, {
            'lo': band['lo'],
            'hi': band['hi'],
            'source': 'age_band',
            'window_note': (
                f'{_note_name(lo)}-{_note_name(hi)} holds only '
                f'{len(_win)} scale note(s) of {brief["tonic"]} '
                f'{brief["mode"]} — singer window not applied'
            ),
        }
    singer = SINGERS[brief['singer']]
    band = dict(band)
    band['lo'], band['hi'] = lo, hi
    band['max_span'] = min(band.get('max_span', hi - lo), hi - lo)
    band['label'] = f'{band["label"]} (sung {singer["label"].lower()})'
    return band, {
        'lo': lo,
        'hi': hi,
        'source': 'singer',
        'window_note': (
            f'{_note_name(lo)}-{_note_name(hi)}: '
            f'{singer["label"].lower()} sung window '
            f'{_note_name(int(win[0]))}-{_note_name(int(win[1]))} '
            f'intersected with the {brief["age_band"]} age band'
        ),
    }
