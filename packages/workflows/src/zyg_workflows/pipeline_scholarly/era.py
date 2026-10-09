"""pipeline_scholarly.era — the text-bearing-subject guard and the episode-era derivation.

Lines 813-1163 of the original pipeline_scholarly.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from zyg_workflows.runtime import _record_token_usage
from zyg_workflows.subscription_llm import MODEL_SMALL as _LLM_SMALL
from zyg_workflows.subscription_llm import anthropic_client as _llm_client
from zyg_workflows.subscription_llm import api_key_or_login as _llm_key
import json
import re
import logging as _zyg_logging

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── Text-bearing subjects ────────────────────────────────────────────────────
# FLUX cannot render script — it renders convincing-looking gibberish. Whenever a
# prompt OPENS on a written object the camera ends up presenting fake lettering to
# be read. Position is the signal: what a prompt names first is what it is about.
_TEXT_SUBJECT_WORDS = (
    'manuscript',
    'manuscripts',
    'map',
    'maps',
    'cartographic',
    'chart',
    'charts',
    'document',
    'documents',
    'dispatch',
    'dispatches',
    'scroll',
    'scrolls',
    'letter',
    'letters',
    'treaty',
    'treaties',
    'ledger',
    'ledgers',
    'register',
    'page',
    'pages',
    'parchment',
    'codex',
    'folio',
    'tablet',
    'decree',
    'proclamation',
    'chronicle',
    'deed',
    'deeds',
    'newspaper',
    'placard',
    'inscription',
    'inscriptions',
    'plaque',
    'epitaph',
    'headstone',
    'sign',
    'signage',
    'signboard',
    'banner',
    'banners',
    'scripture',
)
_TEXT_SUBJECT_RE = re.compile(
    r'(?<![a-z])(' + '|'.join(_TEXT_SUBJECT_WORDS) + r')(?![a-z])',
    re.IGNORECASE,
)
# How far into a prompt still counts as "what the shot is of". Measured against
# the previous episode's 32 prompts plus hand-labelled cases: 7 words is the
# subject noun phrase and gives zero false positives. Wider windows start
# catching background detail ("banners raised behind them") and the very pattern
# the instruction asks for ("a hand seals a folded dispatch"), which would append
# a reframing clause to prompts that are already right. A miss just leaves a
# document shot as it is today; a false positive actively degrades a good prompt.
_TEXT_SUBJ_WINDOW = 7
_TEXT_FRAMING_FIX = (
    ', document seen at a steep oblique angle and cropped by the frame edge, '
    'lettering far outside the focal plane and readable as texture only, '
    'the human action in sharp foreground focus'
)


def _derive_episode_era(
    directive: str, essay_title: str, script: str, topic: str, log=None, debug=None, pipeline_id: str = ''
) -> dict:
    """
    Decide ONE visual period for the whole episode, from the episode's own script.

    Returns {is_historical, period_label, period_start, period_end, anchors, source}.
    `anchors` is the 4-variant rotation (landscape / people / objects / architecture)
    that replaces the static topic→era table for historical episodes.

    Never raises and never blocks the run: falls back to a year-census heuristic
    over the script, and finally to the old topic bucket.
    """

    def _say(m, lvl='INFO'):
        if log:
            try:
                log(m, lvl)
            except Exception as _exc:  # noqa: BLE001 — the callback is the caller's, any shape
                _zyg_log.debug('era-lock log callback raised, this line is missing from the run log: %s', _exc)

    _blank = {
        'is_historical': False,
        'is_combat': None,
        'period_label': 'present day',
        'period_start': None,
        'period_end': None,
        'anchors': [],
        'source': 'topic-bucket',
    }

    # ── 1. Ask the model that already writes this episode's prose ────────────
    _ak = _llm_key()
    if _ak and (script or directive):
        try:
            _msg = (
                'You are the visual continuity supervisor for a documentary.\n'
                'Decide the ONE historical period its imagery must depict.\n\n'
                f'Title: {essay_title}\n'
                f'Directive: {directive}\n'
                f'Script (opening):\n"""{(script or "")[:6000]}"""\n\n'
                'Return ONLY a JSON object, no prose, with these keys:\n'
                '  is_combat      — true ONLY if this episode is substantially ABOUT\n'
                '                   warfare: battles, campaigns, sieges, armies, the\n'
                '                   conduct of fighting. A political revolution, a\n'
                '                   biography of a ruler, or a subject that merely\n'
                '                   MENTIONS a war is false. Ask whether a viewer\n'
                '                   would call this a war documentary.\n'
                '  is_historical  — true if the SUBJECT is set before ~1930, false if the\n'
                '                   subject is genuinely contemporary (modern science,\n'
                '                   current events, present-day medicine, technology).\n'
                '                   A historical subject stays true even when the script\n'
                '                   says its legacy matters "today".\n'
                '  period_label   — short human label, e.g. "Punjab and northwest India,\n'
                '                   1780-1849" or "Republican Rome, 100-44 BC"\n'
                '  period_start   — integer year the imagery may start (negative for BC)\n'
                '  period_end     — integer year the imagery must not pass\n'
                '  anchors        — array of EXACTLY 4 strings, each a comma-separated\n'
                '                   list of period-accurate visual details for this exact\n'
                '                   time and place, in this order:\n'
                '                     [0] landscape and setting\n'
                '                     [1] people, clothing, armour, weapons\n'
                '                     [2] objects, materials, tools, writing surfaces\n'
                '                     [3] architecture and construction\n'
                '                   Be specific to the period — an 1801 Punjabi court is\n'
                '                   not medieval Europe. Each string 12-25 words, written\n'
                '                   as positive image-prompt phrasing, never "no X".\n'
            )
            _r = _llm_client(_ak).messages.create(
                model=_LLM_SMALL,
                max_tokens=900,
                temperature=0.0,
                messages=[{'role': 'user', 'content': _msg}],
            )
            _raw = re.sub(r'```(?:json)?|```', '', _r.content[0].text).strip()
            try:
                _record_token_usage(
                    model=_LLM_SMALL,
                    prompt_tokens=_r.usage.input_tokens,
                    completion_tokens=_r.usage.output_tokens,
                    pipeline_id=pipeline_id,
                    stage='Stage 3.5',
                    pipeline_type='scholarly',
                )
            except Exception as _exc:  # noqa: BLE001 — the ledger must never fail an era lock
                _zyg_log.warning(
                    'era-lock token usage not recorded, this call is missing from the cost ledger: %s', _exc
                )
            _d = json.loads(_raw)
            _anchors = [str(a).strip() for a in (_d.get('anchors') or []) if str(a).strip()]
            if len(_anchors) == 4 and isinstance(_d.get('is_historical'), bool):
                return {
                    'is_historical': bool(_d['is_historical']),
                    'is_combat': bool(_d.get('is_combat')),
                    'period_label': str(_d.get('period_label') or '').strip() or 'unspecified period',
                    'period_start': _d.get('period_start'),
                    'period_end': _d.get('period_end'),
                    'anchors': _anchors if _d['is_historical'] else [],
                    'source': 'llm',
                }
            _say(f'Era lock: malformed LLM response ({len(_anchors)} anchors) — using heuristic', 'WARNING')
        except Exception as _era_e:
            if debug:
                try:
                    debug(f'Era lock: LLM derivation failed ({_era_e}) — using heuristic')
                except Exception as _exc:  # noqa: BLE001 — the callback is the caller's, any shape
                    _zyg_log.debug('era-lock debug callback raised, the heuristic fallback is unannounced: %s', _exc)

    # ── 2. Year census over the script ───────────────────────────────────────
    # Cheap, deterministic, and right far more often than the topic bucket: a
    # historical script is dense with its own dates.
    try:
        _years = [int(y) for y in re.findall(r'\b(1[0-9]{3}|20[0-2][0-9])\b', script or '')]
        _bc = len(re.findall(r'\b(?:BC|BCE)\b', script or ''))
        if _bc >= 2:
            return {
                'is_historical': True,
                'period_label': 'antiquity (BC era)',
                'period_start': None,
                'period_end': 0,
                'anchors': [],
                'source': 'heuristic-bc',
            }
        if len(_years) >= 4:
            _years.sort()
            _median = _years[len(_years) // 2]
            if _median < 1930:
                return {
                    'is_historical': True,
                    'period_label': f'{_years[0]}-{_years[-1]}',
                    'period_start': _years[0],
                    'period_end': _years[-1],
                    'anchors': [],
                    'source': 'heuristic-years',
                }
            return dict(_blank, source='heuristic-years')
    except (TypeError, ValueError) as _exc:
        # A script that is not text, or a four-digit match int() still refuses.
        # The topic bucket below is the remaining answer, which is the point of
        # having it — but a census that cannot run must say so.
        _zyg_log.warning('era-lock year census failed, falling through to the topic bucket: %s', _exc)

    # ── 3. Topic bucket (original behaviour) ─────────────────────────────────
    _modern_buckets = {'general', 'documentary', 'science', 'psychology', 'technology'}
    if topic in _modern_buckets:
        return _blank
    return {
        'is_historical': True,
        'period_label': f'{topic} era',
        'period_start': None,
        'period_end': None,
        'anchors': [],
        'source': 'topic-bucket',
    }


_WRITTEN_NOUNS = (
    r'maps?|charts?|documents?|newspapers?|pamphlets?|manuscripts?|scrolls?|'
    r'letters?|treaties|treaty|ledgers?|inscriptions?|banners?|placards?|'
    r'posters?|proclamations?|broadsheets?|petitions?|signs?(?! of\b)|signage|'
    r'shopfronts?|plaques?|books?|pages?|printing press(?:es)?|lead type'
)


def _strip_written_subject(prompt: str) -> str:
    """Rewrite an image prompt so no written surface is the thing being shot.

    Last-resort retry for a slot whose lettering survived two suppression
    passes. Appending "no readable lettering" to "a huge hand-drawn map of
    Europe spread across the table" asks FLUX to hold two contradictory ideas,
    and it keeps the map every time — measured on run 7033208f, where five of
    fourteen flagged slots never cleared.

    So remove the written object from the sentence and re-aim the camera. The
    STYLE SUFFIX is preserved untouched: it carries the period anchors, the
    shot type and the quality tags, and dropping those would trade a typography
    defect for an anachronism.
    """
    import re as _re_sw

    _parts = _re_sw.split(
        r', (?=rich warm tones|moonlit night scene|aerial bird|cool |high contrast|'
        r'soft |golden hour|silver blue|harsh|wide establishing|medium shot|'
        r'close-up|extreme|photorealistic)',
        prompt,
        maxsplit=1,
    )
    _head = _parts[0]
    _tail = (', ' + _parts[1]) if len(_parts) > 1 else ''
    # Drop the whole CLAUSE that names the written object, not just the noun.
    # Deleting the noun alone leaves its determiners behind — "stands before an
    # enormous wall-mounted , her face..." — which is a worse prompt than the
    # one it replaces.
    _lead = ''
    _m_lead = _re_sw.match(r'(?i)\s*(cinematic photograph|photograph)\s*', _head)
    if _m_lead:
        _lead = _m_lead.group(1)
        _head = _head[_m_lead.end() :]
    _doc_re = _re_sw.compile(r'(?i)\b(?:' + _WRITTEN_NOUNS + r')\b')
    _head_orig = _head
    _clauses = [c for c in _re_sw.split(r'\s*[;,]\s*', _head) if c.strip()]
    _kept = [c for c in _clauses if not _doc_re.search(c)]
    _dropped_first = bool(_clauses) and bool(_kept) and _kept[0] is not _clauses[0]
    _head = ', '.join(_kept).strip(' ,;')
    if len(_head.split()) < 8 or not _kept:
        # Dropping whole clauses is too blunt when the written thing is only a
        # phrase inside the one clause that carries the scene: "two clerks argue
        # across a ledger in a customs house" loses the clerks and the customs
        # house along with the ledger, and lands on the generic stub below.
        # Measured on 801 real prompts, that stub fired on 42 of them — and it
        # is a FIXED sentence, so every one of those slots would have rendered
        # the same picture.
        #
        # So try excising just the phrase. Only PREPOSITIONAL phrases, though:
        # "argue across a ledger in a customs house" -> "argue in a customs
        # house" reads fine, but cutting a direct object leaves the verb and its
        # participles stranded — "a scholar studies charts spread across a
        # table" became "a scholar in a tower spread across a table", which is
        # worse than the stub, not better. A prepositional phrase is the one
        # constituent that can be removed without repairing the grammar around
        # it.
        _pp = (
            r'(?:\b(?:a|an|the|his|her|its|their|two|three|several|some|many)\b\s+)?'
            r'(?:[\w-]+\s+){0,3}?(?:' + _WRITTEN_NOUNS + r')'
            r'(?:\s+(?:of|for|from|bearing|reading|showing)\s+'
            r'(?:[\w-]+\s+){0,3}?[\w-]+)?'
        )
        _prep = (
            r'(?:before|behind|beside|beneath|under|over|across|against|'
            r'around|through|among|amid|at|onto|upon|into|on|in|from|with)'
        )
        _try = _re_sw.sub(r'(?i)\s+' + _prep + r'\s+' + _pp + r'(?=\s|,|;|$)', '', _head_orig)
        _try = _re_sw.sub(r'\s{2,}', ' ', _try)
        _try = _re_sw.sub(r'\s+([,;])', r'\1', _try).strip(' ,;')
        if (
            _try != _head_orig
            and len(_try.split()) >= 8
            and not _doc_re.search(_try)
            # no stranded determiner, no two prepositions run together
            and not _re_sw.search(r'(?i)\b(an?|the|his|her|their)\s*(,|$)', _try)
            and not _re_sw.search(r'(?i)\b' + _prep + r'\s+' + _prep + r'\b', _try)
        ):
            _head = _try
            _kept = [_try]
            _dropped_first = False
    if len(_head.split()) < 8 or not _kept:
        # The scene was almost entirely the written object; rather than ship a
        # stub, photograph the people who would be around it — but keep the
        # SETTING, so two flagged slots in the same film do not render the same
        # picture. A fixed sentence here made every escalated slot identical.
        _where = ''
        _m_where = _re_sw.search(
            r'(?i)\b(?:in|inside|within|at|on board|aboard)\s+'
            r'((?:a|an|the)\s+)?((?:[\w-]+\s+){0,3}?'
            r'(?:hall|tower|room|chamber|library|study|scriptorium|workshop|'
            r'office|house|shop|street|square|market|church|cathedral|abbey|'
            r'monastery|tavern|inn|cellar|attic|courtyard|garden|field|camp|'
            r'ship|cabin|kitchen|parlour|parlor|lodge|barn|mill|forge|'
            r'printing house|newsroom|classroom|laboratory))',
            _head_orig,
        )
        if _m_where:
            _where = ' in ' + (_m_where.group(1) or 'a ').strip() + ' ' + _m_where.group(2).strip()
            # The setting can name a written thing too — "a dimly lit
            # rare-documents room" put 'documents' straight back into the
            # prompt this function exists to clear.
            if _doc_re.search(_where):
                _where = ''
        _head = (
            'the faces and hands of the people gathered'
            + (_where or ' around a table')
            + ', lit from one side, no written surface facing camera'
        )
    elif _dropped_first:
        # The opening clause carried the subject — restore a subject so the
        # prompt does not begin mid-description.
        _head = 'the people at the centre of the scene, ' + _head
    _head = ((_lead + ' ') if _lead else '') + _head
    return (
        _head + ', nothing in frame bears readable writing, no paper no map no sign '
        'no banner, camera on faces and hands instead' + _tail
    )
