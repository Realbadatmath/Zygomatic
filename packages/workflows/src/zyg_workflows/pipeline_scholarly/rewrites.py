"""pipeline_scholarly.rewrites — the anachronism tripwire, the bare-noun period rewrite and the render-safety rewrite.

Lines 303-810 of the original pipeline_scholarly.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

import re


# ── Anachronism vocabulary ───────────────────────────────────────────────────
# Present-day tells that must never appear in a historical episode's imagery.
# Used in two places: to reject an image PROMPT before it is rendered, and to
# describe the ban to the prompt-writing model. Deliberately literal — this is a
# tripwire, not a classifier, and a false positive only costs one re-ask.
_MODERN_PROMPT_TERMS = (
    'contemporary',
    'modern',
    'present-day',
    'present day',
    'modern-day',
    'nowadays',
    'today',
    "today's",
    '21st century',
    '21st-century',
    '20th century',
    '20th-century',
    'car',
    'cars',
    'automobile',
    'automobiles',
    'truck',
    'bus',
    'taxi',
    'traffic',
    'motorbike',
    'motorcycle',
    'scooter',
    'moped',
    'bicycle',
    'rickshaw',
    'smartphone',
    'phone',
    'mobile phone',
    'camera phone',
    'laptop',
    'computer',
    'television',
    'tv screen',
    'headphones',
    'wristwatch',
    # 'monitor' and 'trainers' are deliberately absent — both are ordinary verbs
    # and nouns in historical prose ("scouts monitor the pass", "the trainers
    # drilled the infantry") and would trip the wire on clean prompts.
    'jeans',
    't-shirt',
    'tshirt',
    'sneakers',
    'baseball cap',
    'hoodie',
    'business suit',
    'necktie',
    'sunglasses',
    'backpack',
    'skyscraper',
    'high-rise',
    'shopfront',
    'shop window',
    'storefront',
    'glass facade',
    'plate glass',
    'billboard',
    'neon sign',
    'streetlight',
    'street light',
    'electric light',
    'light bulb',
    'lightbulb',
    'power line',
    'telephone pole',
    'asphalt',
    'tarmac',
    'pavement marking',
    'road marking',
    'concrete building',
    'plastic',
    'aluminium',
    'aluminum',
    'stainless steel',
    'tourist',
    'tourists',
    'museum display',
    'museum case',
    'display case',
    'vitrine',
    'security camera',
    'traffic light',
)
# Words that legitimately appear in historical prompts and must not trip the
# tripwire on a substring match (e.g. "scarred" contains "car").
_MODERN_TERM_RE = re.compile(
    r'(?<![a-z])(' + '|'.join(re.escape(t) for t in _MODERN_PROMPT_TERMS) + r')(?![a-z])',
    re.IGNORECASE,
)


def _scan_modern_terms(text: str) -> list:
    """Return the present-day terms found in an image prompt (deduped, ordered)."""
    seen, out = set(), []
    for m in _MODERN_TERM_RE.finditer(text or ''):
        t = m.group(1).lower()
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── Bare-noun rewrite — the mirror image of _scan_modern_terms ──────────────
# The tripwire above rejects a prompt that SAYS "car". The Black Death episode
# (run 2f1ffabb) said none of those words and still shipped 19 anachronisms,
# because the renderer gives every UNQUALIFIED noun its modern default:
# "vessel" -> motor boat, "shoe" -> sneaker, "lantern" -> gas lamp, "shutters"
# -> louvres, "bracelet" -> wristwatch, and any head without a described
# hairstyle -> a 2020s haircut. The negative prompt cannot help on schnell
# (discarded at guidance 0, measured — see _flux_lever_guard).
#
# So the constructive counterpart: a bare noun is REPLACED by its period form.
# "Bare" means no period/material descriptor in the three words before it, so
# "leather turnshoes" and "wooden cog" are left alone and the pass is
# idempotent. The vocabulary is bucketed by era (antiquity / medieval / early
# modern / nineteenth) so a Republican-Rome episode is not handed a cog.
# Runs on every S and C prompt before render; testable in isolation.
_PERIOD_DESCRIPTOR_RE = re.compile(
    r'(?ix)(?<![a-z-])('
    r'wooden|wood|oak|timber|plank|clinker|oared|sailing|square-sailed|single-masted|masted|'
    r'wool|woolen|woollen|linen|hemp|leather|hide|fur|felt|homespun|hand-?woven|hand-?sewn|'
    r'coarse|rough-?spun|iron|iron-rimmed|bronze|brass|copper|tin|pewter|clay|terracotta|stone|'
    r'horn|bone|wax|tallow|rush|oil|medieval|mediaeval|ancient|roman|greek|period|'
    r'period-accurate|historical|tudor|georgian|victorian|regency|'
    r'\d+(?:st|nd|rd|th)[- ]century|stained|leaded|latticed?|shuttered|thatched|'
    r'hobnailed|buckled|cog|galley|longship|carrack|caravel|barge|kirtle|chemise|tunic|'
    r'doublet|jerkin|surcoat|cloak|hose|breeches|bodice|candle|candlelit|torch|torchlit|'
    r'rushlight|firelit|lamplit|parchment|vellum|papyrus|hand-?drawn|hand-?inked|engraved|'
    r'straw|canvas|sailcloth|reed|wattle|daub'
    r')(?![a-z])'
)
# A descriptor only qualifies the noun it is ATTACHED to. "a wool cloak and
# trousers" must still see "trousers" as bare, so the window stops at a
# conjunction, a preposition or punctuation.
_BARE_CTX_STOP = frozenset(
    (
        'and',
        'or',
        'with',
        'beside',
        'while',
        'as',
        'near',
        'behind',
        'before',
        'under',
        'over',
        'into',
        'onto',
        'at',
        'in',
        'on',
        'of',
        'from',
        'by',
        'to',
        'the',
        'a',
        'an',
        'his',
        'her',
        'their',
        'its',
    )
)


def _bare_context(before: str) -> str:
    """The words immediately qualifying the noun that follows `before`."""
    words = before.split()[-4:]
    ctx = []
    for w in reversed(words):
        core = w.strip(',;:.()"\'').lower()
        if core in _BARE_CTX_STOP and core not in ('the', 'a', 'an', 'his', 'her', 'their', 'its'):
            break
        ctx.append(w)
        if w.rstrip().endswith((',', ';', ':', '.')) or core in ('the', 'a', 'an', 'his', 'her', 'their', 'its'):
            break
    return ' '.join(reversed(ctx))


_ALL_BUCKETS = ('antiquity', 'medieval', 'early_modern', 'nineteenth', 'unknown')

# (noun regex with a trailing plural group, {bucket: (singular, plural)}).
# A None replacement DROPS the noun (a watch has no period form).
_PERIOD_NOUN_TABLE = [
    (
        r'(boat|vessel|ship|sailboat)(s?)',
        {
            'antiquity': ('wooden oared galley', 'wooden oared galleys'),
            'medieval': (
                'single-masted wooden sailing cog with a square sail',
                'single-masted wooden sailing cogs with square sails',
            ),
            'early_modern': ('wooden sailing ship with canvas sails', 'wooden sailing ships with canvas sails'),
            'nineteenth': ('wooden sailing vessel', 'wooden sailing vessels'),
            'unknown': ('wooden sailing vessel', 'wooden sailing vessels'),
        },
    ),
    (
        r'(shirt)(s?)',
        {
            'antiquity': ('linen tunic', 'linen tunics'),
            'medieval': ('linen chemise under a wool tunic', 'linen chemises under wool tunics'),
            'early_modern': ('linen shirt with a soft collar', 'linen shirts with soft collars'),
            'nineteenth': ('linen shirt with a high collar', 'linen shirts with high collars'),
            'unknown': ('hand-sewn linen shirt', 'hand-sewn linen shirts'),
        },
    ),
    (
        r'(shoe)(s?)',
        {
            'antiquity': ('leather sandal', 'leather sandals'),
            'medieval': ('leather turnshoe', 'leather turnshoes'),
            'early_modern': ('buckled leather shoe', 'buckled leather shoes'),
            'nineteenth': ('leather lace-up boot', 'leather lace-up boots'),
            'unknown': ('hand-made leather shoe', 'hand-made leather shoes'),
        },
    ),
    (r'(sneaker|trainer)(s?)', {b: ('leather turnshoe', 'leather turnshoes') for b in _ALL_BUCKETS}),
    (
        r'(lantern|streetlight|street light|lamp)(s?)',
        {
            'antiquity': ('clay oil lamp', 'clay oil lamps'),
            'medieval': ('torch', 'torches'),
            'early_modern': ('horn lantern with a candle inside', 'horn lanterns with candles inside'),
            'nineteenth': ('oil lamp', 'oil lamps'),
            'unknown': ('oil lamp', 'oil lamps'),
        },
    ),
    (r'(bracelet|wristwatch|wrist watch|bangle)(s?)', None),
    (r'(shutter)(s?)', {b: ('plank shutter', 'plank shutters') for b in _ALL_BUCKETS}),
    (
        r'(window)(s?)',
        {
            'antiquity': ('small unglazed window opening', 'small unglazed window openings'),
            'medieval': (
                'small shuttered window opening without glass',
                'small shuttered window openings without glass',
            ),
            'early_modern': ('small leaded window', 'small leaded windows'),
            'nineteenth': ('sash window with small panes', 'sash windows with small panes'),
            'unknown': ('small shuttered window', 'small shuttered windows'),
        },
    ),
    (
        r'(dress)(es)',
        {
            'antiquity': ('wool stola', 'wool stolae'),
            'medieval': ('ankle-length wool kirtle', 'ankle-length wool kirtles'),
            'early_modern': ('wool bodice and petticoat', 'wool bodices and petticoats'),
            'nineteenth': ('long wool dress with a fitted bodice', 'long wool dresses with fitted bodices'),
            'unknown': ('long hand-sewn wool dress', 'long hand-sewn wool dresses'),
        },
    ),
    (
        r'(dress)()(?!ed|ing|es|maker)',
        {
            'antiquity': ('wool stola', 'wool stolae'),
            'medieval': ('ankle-length wool kirtle', 'ankle-length wool kirtles'),
            'early_modern': ('wool bodice and petticoat', 'wool bodices and petticoats'),
            'nineteenth': ('long wool dress with a fitted bodice', 'long wool dresses with fitted bodices'),
            'unknown': ('long hand-sewn wool dress', 'long hand-sewn wool dresses'),
        },
    ),
    (
        r'(jacket|coat)(s?)',
        {
            'antiquity': ('wool cloak', 'wool cloaks'),
            'medieval': ('wool cloak', 'wool cloaks'),
            'early_modern': ('long wool coat', 'long wool coats'),
            'nineteenth': ('wool frock coat', 'wool frock coats'),
            'unknown': ('wool cloak', 'wool cloaks'),
        },
    ),
    (
        r'(trouser|pant)(s)',
        {
            'antiquity': ('wool braccae', 'wool braccae'),
            'medieval': ('wool hose', 'wool hose'),
            'early_modern': ('wool breeches', 'wool breeches'),
            'nineteenth': ('wool trousers', 'wool trousers'),
            'unknown': ('wool hose', 'wool hose'),
        },
    ),
    (
        r'(bottle)(s?)',
        {
            'antiquity': ('clay amphora', 'clay amphorae'),
            'medieval': ('leather flask', 'leather flasks'),
            'early_modern': ('stoneware bottle', 'stoneware bottles'),
            'nineteenth': ('glass bottle', 'glass bottles'),
            'unknown': ('stoneware bottle', 'stoneware bottles'),
        },
    ),
    (
        r'(cup|mug)(s?)',
        {
            'antiquity': ('clay cup', 'clay cups'),
            'medieval': ('wooden cup', 'wooden cups'),
            'early_modern': ('pewter tankard', 'pewter tankards'),
            'nineteenth': ('tin mug', 'tin mugs'),
            'unknown': ('wooden cup', 'wooden cups'),
        },
    ),
    (
        r'(cart|wagon)(s?)',
        {
            b: ('wooden cart with iron-rimmed wooden wheels', 'wooden carts with iron-rimmed wooden wheels')
            for b in _ALL_BUCKETS
        },
    ),
    (
        r'(fence)(s?)',
        {
            'antiquity': ('wooden fence', 'wooden fences'),
            'medieval': ('wattle fence', 'wattle fences'),
            'early_modern': ('wooden paling fence', 'wooden paling fences'),
            'nineteenth': ('wooden paling fence', 'wooden paling fences'),
            'unknown': ('wooden fence', 'wooden fences'),
        },
    ),
    (
        r'(bridge)(s?)',
        {
            'antiquity': ('stone arch bridge', 'stone arch bridges'),
            'medieval': ('stone arch bridge', 'stone arch bridges'),
            'early_modern': ('stone bridge', 'stone bridges'),
            'nineteenth': ('stone bridge', 'stone bridges'),
            'unknown': ('stone bridge', 'stone bridges'),
        },
    ),
]
_PERIOD_NOUN_RES = [(re.compile(r'(?<![a-z-])' + pat + r'(?![a-z])', re.I), tbl) for pat, tbl in _PERIOD_NOUN_TABLE]
_DROP_LEAD_RE = re.compile(
    r'(?i)\b(?:a|an|the|his|her|their|its|one|a single|a small|a thin|a gold|a golden|'
    r'a silver|a metal|a leather|a delicate|a slim)\s+$'
)
_DROP_TAIL_RE = re.compile(
    r'^\s*(?:on|around|at|circling|clasping)\s+(?:his|her|their|one|the|each)\s+'
    r'(?:left |right |slim |thin |bare )?(?:wrists?|necks?|arms?|fingers?)'
)


def _period_bucket(era: dict | None) -> str:
    """Era-lock dict -> 'antiquity' | 'medieval' | 'early_modern' | 'nineteenth' | 'unknown'."""
    try:
        from zyg_workflows import era_gate as _eg

        return _eg.period_bucket(era)
    except Exception:
        return 'unknown'


def _period_noun_rewrite(text: str, era: dict | None) -> tuple:
    """Replace bare (undescribed) nouns with their period form. -> (text, changes).

    changes: list of 'shoe->leather turnshoe' strings, empty when nothing was
    bare. Idempotent: a replacement always starts with a descriptor, so a second
    pass finds nothing. Modern-era episodes are returned untouched.
    """
    if not text or not (era or {}).get('is_historical', True):
        return text, []
    bucket = _period_bucket(era)
    changes = []
    out = text
    for rx, tbl in _PERIOD_NOUN_RES:
        pos = 0
        while True:
            m = rx.search(out, pos)
            if not m:
                break
            before = out[: m.start()]
            if _PERIOD_DESCRIPTOR_RE.search(_bare_context(before)) or before.rstrip().endswith('-'):
                pos = m.end()
                continue
            plural = m.group(2) if (m.lastindex or 0) >= 2 else ''
            if tbl is None:
                # drop the noun, a leading article/possessive, and a "on his wrist" tail
                head = _DROP_LEAD_RE.sub('', before)
                tail = _DROP_TAIL_RE.sub('', out[m.end() :])
                new = head.rstrip() + ' ' + tail.lstrip() if head.strip() and tail.strip() else head + tail
                new = re.sub(r'\s{2,}', ' ', new)
                new = re.sub(r'\s+([,.;])', r'\1', new)
                new = re.sub(r'(,\s*){2,}', ', ', new)
                changes.append(f'{m.group(0)}->(dropped)')
                out = new
                pos = max(0, len(head.rstrip()))
                continue
            sing, plur = tbl.get(bucket) or tbl['unknown']
            repl = plur if plural else sing
            if m.group(0)[:1].isupper():
                repl = repl[:1].upper() + repl[1:]
            changes.append(f'{m.group(0)}->{repl}')
            out = out[: m.start()] + repl + out[m.end() :]
            pos = m.start() + len(repl)
    if changes:
        out = re.sub(r'\s*,\s*$', '', out).rstrip()
    return out, changes


_PEOPLE_RE = re.compile(
    r'(?i)\b(man|men|woman|women|boy|boys|girl|girls|child|children|face|faces|figure|figures|'
    r'crowd|crowds|people|villagers?|peasants?|monks?|priests?|nuns?|friars?|physicians?|'
    r'doctors?|merchants?|soldiers?|knights?|sailors?|fishermen|mourners?|family|mother|father|'
    r'son|daughter|wife|husband|scholars?|kings?|queens?|lords?|ladies|lady|servants?|workers?|'
    r'labou?rers?|clerks?|scribes?|pilgrims?|beggars?|elders?|youths?|survivors?|gravediggers?)\b'
)
_HAIR_RE = re.compile(
    r'(?i)\b(hair|haired|hood|hooded|coif|veil|veiled|wimple|cap|capped|hat|hats|helmet|helm|'
    r'tonsure|tonsured|bald|balding|beard|bearded|headscarf|kerchief|turban|crown|circlet|'
    r'braid|braided|braids|plait|plaited|plaits|bonnet|wig|headdress|cowl|shaven|cropped|'
    r'mask|masked|beak|beaked|hidden face|face hidden|from behind|back to camera|silhouette[sd]?)\b'
)


def _period_hair_backstop(text: str, era: dict | None) -> tuple:
    """Append a period hair/head-covering clause when people appear with no hair described.

    Any head without a described hairstyle renders with a 2020s haircut. -> (text, added)
    """
    if not text or not (era or {}).get('is_historical', True):
        return text, False
    if not _PEOPLE_RE.search(text) or _HAIR_RE.search(text):
        return text, False
    try:
        from zyg_workflows import era_gate as _eg

        hair = _eg.PERIOD_VOCAB[_eg.period_bucket(era)]['hair']
    except Exception:
        hair = 'period-accurate hairstyles and head coverings'
    return text.rstrip(' .,;') + ', ' + hair, True


# ── Render-safety rewrite — disease on the skin, famine in the face ─────────
# Slot 15 of the Black Death run said "bubo... grotesque swelling" and rendered an
# eviscerated chest; slot 28 said "emaciated... ribs" and rendered bare bone
# through skin. The PROMPTS were clean by the gore audit; the renderer reads the
# medical nouns graphically. These are the nouns, mapped to what the writer
# should have said. Applied below 'extreme' only — that level unblocks gore on
# purpose and a person has to select it.
_GORE_NOUN_TABLE = [
    (
        r'(?i)\b(exposed|protruding|jutting|visible|showing)\s+(ribs?|bones?|skull|spine|ribcage)\b',
        'hollow cheeks and sunken eyes',
    ),
    (
        r'(?i)\b(ribs?|ribcage)\s+(showing|visible|jutting|protruding|pressing|standing out)'
        r'(\s+through\s+(?:the\s+)?skin)?\b',
        'hollow cheeks and sunken eyes',
    ),
    (
        r'(?i)\b(bone|bones)\s+(through|breaking through|piercing|pushing through)\s+(?:the\s+)?skin\b',
        'bruise-dark skin',
    ),
    (r'(?i)\bribs\b', 'gaunt hollow cheeks'),
    (
        r'(?i)\b(open|gaping|weeping|festering|oozing|suppurating)\s+(wounds?|sores?|lesions?)\b',
        'dark swelling under intact skin',
    ),
    (r'(?i)\b(entrails|intestines|viscera|innards)\b', 'a body slumped and still'),
    (r'(?i)\b(eviscerat\w*|disembowel\w*|flayed|torn open|ripped open)\b', 'collapsed and still'),
    (
        r'(?i)\b(?:a|an|the)?\s*(bubo|buboes)\b(?:\s+swelling)?(?!\s*[—–-]?\s*(?:a\s+)?dark)',
        'a dark egg-sized swelling under intact skin at the neck',
    ),
    (r'(?i)\bpus\b', 'sweat'),
]
_GORE_NOUN_RES = [(re.compile(pat), repl) for pat, repl in _GORE_NOUN_TABLE]


def _render_safety_rewrite(text: str, rank: int = 1) -> tuple:
    """Rewrite render-level gore nouns below the 'extreme' dial. -> (text, changes)."""
    if not text or rank >= 2:
        return text, []
    out, changes = text, []
    for rx, repl in _GORE_NOUN_RES:

        def _sub(m, _r=repl):
            changes.append(f'{m.group(0).strip()}->{_r}')
            return _r

        out = rx.sub(_sub, out)
    if changes:
        # article agreement after a substitution ("an open wound" -> "a dark ...")
        out = re.sub(r'\ban(?=\s+[^aeiouAEIOU\s])', 'a', out)
        out = re.sub(r'\ba(?=\s+[aeiouAEIOU])', 'an', out)
        out = re.sub(r'\s{2,}', ' ', out)
    return out, changes


# Live only on a real-CFG renderer (Qwen-Image); schnell discards it, measured.
_ERA_NEGATIVE = (
    'wristwatch, watch, bangle, painted nails, nail polish, sneakers, trainers, t-shirt, '
    'jeans, zipper, zip, hoodie, sundress, sunglasses, motor boat, outboard motor, engine, '
    'wheelhouse, electric light, light bulb, festoon lights, floodlight, spotlight, neon, '
    'telegraph pole, utility pole, power lines, wires, antenna, asphalt, tarmac, road markings, '
    'glass shopfront, printed sign, poster, logo, typeset text, modern haircut, undercut, '
    'plastic, concrete, steel, cars, bicycle, camera, phone, virus icons, biohazard symbol'
)
# Default for ZYG_SCHOLARLY_VLM_ERA — set from scripts/bench_era_gate.py.
_ERA_GATE_DEFAULT = '1'
