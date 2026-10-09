# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""glossary_examples.terms_de_fr — the German and French glossaries, translate() and units()."""

from __future__ import annotations

import re

from zyg_workflows.arch_assistant_ext.glossary_examples.terms_nl import STOREY_M, _NL, _norm

# German -> the English studio term.
_DE = {
    'wand': 'wall',
    'mauer': 'wall',
    'aussenwand': 'external wall',
    'innenwand': 'internal wall',
    'geschoss': 'storey',
    'stockwerk': 'storey',
    'etage': 'storey',
    'obergeschoss': 'upper storey',
    'erdgeschoss': 'ground floor',
    'dach': 'roof',
    'flachdach': 'flat roof',
    'satteldach': 'gable roof',
    'walmdach': 'hip roof',
    'mansarddach': 'mansard roof',
    'dachfenster': 'skylight',
    'gaube': 'dormer',
    'fenster': 'window',
    'tur': 'door',
    'haustur': 'front door',
    'schiebetur': 'sliding door',
    'treppe': 'stair',
    'wendeltreppe': 'spiral stair',
    'gelander': 'railing',
    'balkon': 'balcony',
    'garten': 'garden',
    'brucke': 'bridge',
    'kirche': 'church',
    'turm': 'tower',
    'keller': 'basement',
    'dachboden': 'attic',
    'decke': 'ceiling',
    'boden': 'floor slab',
    'saule': 'column',
    'stutze': 'column',
    'balken': 'beam',
    'binder': 'truss',
    'fundament': 'footing',
    'schornstein': 'chimney',
    'kamin': 'chimney',
    'dachrinne': 'gutter',
    'fallrohr': 'downpipe',
    'aufzug': 'elevator',
    'fahrstuhl': 'elevator',
    'rolltreppe': 'escalator',
    'kuche': 'kitchen',
    'badezimmer': 'bathroom',
    'schlafzimmer': 'bedroom',
    'wohnzimmer': 'living room',
    'buro': 'office',
    'laden': 'shop',
    'schule': 'school',
    'lagerhalle': 'warehouse',
    'stadion': 'stadium',
    'tunnel': 'tunnel',
    'damm': 'dam',
    'schleuse': 'sluice',
    'deich': 'embankment',
    'teich': 'pond',
    'schwimmbad': 'pool',
    'brunnen': 'fountain',
    'spielplatz': 'playground',
    'auto': 'car',
    'lastwagen': 'truck',
    'lkw': 'truck',
    'boot': 'boat',
    'kran': 'crane',
    'gerust': 'scaffold',
    'zaun': 'fence',
    'hecke': 'hedge',
    'baum': 'tree',
    'strauch': 'shrub',
    'glas': 'glass',
    'beton': 'concrete',
    'ziegel': 'brick',
    'holz': 'timber',
    'stahl': 'steel',
    'stein': 'stone',
    'putz': 'plaster',
    'zink': 'zinc',
    'garage': 'garage',
    'halle': 'hall',
    'flur': 'corridor',
    'zimmer': 'room',
    'raum': 'room',
    'haus': 'house',
    'reihenhaus': 'row house',
    'hof': 'courtyard',
    'kanal': 'canal',
    'kai': 'quay',
    'mobel': 'furniture',
    'bett': 'bed',
    'stuhl': 'chair',
    'tisch': 'table',
    'schrank': 'wardrobe',
    'sofa': 'sofa',
    'hohe': 'height',
    'breite': 'width',
    'tiefe': 'depth',
    'lange': 'length',
    'dicke': 'thickness',
    'flache': 'area',
    'gitter': 'grid',
    'raster': 'grid',
    'windmuhle': 'windmill',
    'leuchtturm': 'lighthouse',
    'kuppel': 'dome',
    'gelande': 'terrain',
    'hugel': 'hill',
    'baustelle': 'construction site',
    'strasse': 'road',
    'gehweg': 'sidewalk',
    'laterne': 'lamp post',
    'bank': 'bench',
    'solaranlage': 'solar panel',
    'heizkorper': 'radiator',
    'aufzugsschacht': 'elevator shaft',
    'brustung': 'parapet',
    'gesims': 'cornice',
    'saulengang': 'colonnade',
    'pergola': 'pergola',
    # landscape
    'berg': 'mountain',
    'gebirge': 'mountain range',
    'tal': 'valley',
    'fluss': 'river',
    'bach': 'stream',
    'see': 'lake',
    'wasserfall': 'waterfall',
    'wald': 'forest',
    'klippe': 'cliff',
    'fels': 'rock',
    'dune': 'dune',
    'strand': 'beach',
    'meer': 'sea',
    'insel': 'island',
    'acker': 'field',
    'wiese': 'meadow',
    'moor': 'marsh',
    'weinberg': 'vineyard',
    'heide': 'heath',
    'landschaft': 'landscape',
    'kuste': 'coast',
    # ground and scale ('boden' stays 'floor slab', the building sense it already had)
    'erdboden': 'ground',
    'untergrund': 'ground',
    'hang': 'slope',
    'abhang': 'slope',
    'maßstab': 'scale',
    'massstab': 'scale',
    'eben': 'level',
    'waagerecht': 'level',
    'bergauf': 'uphill',
    'bergab': 'downhill',
    'schlucht': 'canyon',
    'hochebene': 'plateau',
    'plateau': 'plateau',
    'bergrucken': 'ridge',
    'grat': 'ridge',
    'schneegrenze': 'snow line',
    # v3: shaping the one ground
    'modellieren': 'sculpt',
    'formen': 'sculpt',
    'ausheben': 'dig out',
    'abtragen': 'dig out',
    'aufschütten': 'raise',
    'anschütten': 'raise',
    'einebnen': 'level',
    'planieren': 'level',
}

# French -> the English studio term.
_FR = {
    'mur': 'wall',
    'cloison': 'partition',
    'etage': 'storey',
    'niveau': 'storey',
    'rez-de-chaussee': 'ground floor',
    'toit': 'roof',
    'toiture': 'roof',
    'comble': 'attic',
    'grenier': 'attic',
    'fenetre': 'window',
    'lucarne': 'dormer',
    'porte': 'door',
    'porte-fenetre': 'french door',
    'escalier': 'stair',
    'balcon': 'balcony',
    'garde-corps': 'railing',
    'jardin': 'garden',
    'pont': 'bridge',
    'eglise': 'church',
    'tour': 'tower',
    'cave': 'basement',
    'plafond': 'ceiling',
    'plancher': 'floor slab',
    'dalle': 'floor slab',
    'colonne': 'column',
    'poteau': 'column',
    'poutre': 'beam',
    'ferme': 'truss',
    'semelle': 'footing',
    'cheminee': 'chimney',
    'gouttiere': 'gutter',
    'descente': 'downpipe',
    'ascenseur': 'elevator',
    'escalator': 'escalator',
    'cuisine': 'kitchen',
    'salle de bain': 'bathroom',
    'chambre': 'bedroom',
    'salon': 'living room',
    'bureau': 'office',
    'magasin': 'shop',
    'ecole': 'school',
    'entrepot': 'warehouse',
    'stade': 'stadium',
    'barrage': 'dam',
    'ecluse': 'sluice',
    'digue': 'embankment',
    'etang': 'pond',
    'piscine': 'pool',
    'fontaine': 'fountain',
    'aire de jeux': 'playground',
    'voiture': 'car',
    'camion': 'truck',
    'bateau': 'boat',
    'grue': 'crane',
    'echafaudage': 'scaffold',
    'cloture': 'fence',
    'haie': 'hedge',
    'arbre': 'tree',
    'verre': 'glass',
    'beton': 'concrete',
    'brique': 'brick',
    'bois': 'timber',
    'acier': 'steel',
    'pierre': 'stone',
    'enduit': 'plaster',
    'quai': 'quay',
    'canal': 'canal',
    'meuble': 'furniture',
    'lit': 'bed',
    'chaise': 'chair',
    'table': 'table',
    'armoire': 'wardrobe',
    'hauteur': 'height',
    'largeur': 'width',
    'profondeur': 'depth',
    'epaisseur': 'thickness',
    'surface': 'area',
    'volume': 'volume',
    'terrain': 'terrain',
    'colline': 'hill',
    'chantier': 'construction site',
    'route': 'road',
    'trottoir': 'sidewalk',
    'lampadaire': 'lamp post',
    'banc': 'bench',
    'terrasse': 'terrace',
    'verriere': 'curtain wall',
    'coupole': 'dome',
    'phare': 'lighthouse',
    'moulin': 'windmill',
    'auvent': 'canopy',
    'garage': 'garage',
    # landscape
    'montagne': 'mountain',
    'chaine de montagnes': 'mountain range',
    'vallee': 'valley',
    'riviere': 'river',
    'ruisseau': 'stream',
    'lac': 'lake',
    'cascade': 'waterfall',
    'foret': 'forest',
    'falaise': 'cliff',
    'rocher': 'rock',
    'dune': 'dune',
    'plage': 'beach',
    'mer': 'sea',
    'ile': 'island',
    'champ': 'field',
    'prairie': 'meadow',
    'marais': 'marsh',
    'vignoble': 'vineyard',
    'lande': 'heath',
    'paysage': 'landscape',
    'cote': 'coast',
    # ground and scale ('cote' = coast and 'colline' = hill are already above)
    'sol': 'ground',
    'pente': 'slope',
    'echelle': 'scale',
    'plat': 'level',
    'de niveau': 'level',
    'en amont': 'upstream',
    'en aval': 'downstream',
    'canyon': 'canyon',
    'gorge': 'canyon',
    'plateau': 'plateau',
    'coteau': 'hillside',
    'crete': 'ridge',
    'sommet': 'summit',
    'ligne de neige': 'snow line',
    # v3: shaping the one ground
    'sculpter': 'sculpt',
    'modeler': 'sculpt',
    'creuser': 'dig out',
    'excaver': 'dig out',
    'remblayer': 'raise',
    'surelever': 'raise',
    'niveler': 'level',
    'aplanir': 'level',
}

GLOSSARY: dict = {}
for _src, _lang in ((_NL, 'Dutch'), (_DE, 'German'), (_FR, 'French')):
    for _k, _v in _src.items():
        GLOSSARY.setdefault(_norm(_k), (_v, _lang))


def translate(word) -> str:
    """The English studio term for a Dutch/German/French word, or '' if unknown."""
    hit = GLOSSARY.get(_norm(word))
    if hit:
        return hit[0]
    n = _norm(word)
    for suffix in ('en', 'es', 'er', 's', 'e'):
        if len(n) > len(suffix) + 2 and n.endswith(suffix):
            hit = GLOSSARY.get(n[: -len(suffix)])
            if hit:
                return hit[0]
    return ''


def language_of(word) -> str:
    hit = GLOSSARY.get(_norm(word))
    return hit[1] if hit else ''


# ── units ────────────────────────────────────────────────────────────────────
_LEN_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(feet\b|foot\b|ft\b|inches\b|inch\b|in\b|yards\b|yard\b|yds\b|yd\b|'
    r"voet\b|duim\b|fuss\b|pied\b|pieds\b|'|\")",
    re.I,
)
_ST_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(floors\b|floor\b|storeys\b|storey\b|stories\b|story\b|'
    r'verdiepingen\b|verdieping\b|etages\b|etage\b|bouwlagen\b|'
    r'geschosse\b|geschoss\b|stockwerke\b|stockwerk\b|niveaux\b|niveau\b)',
    re.I,
)
_FT, _IN, _YD = 0.3048, 0.0254, 0.9144


def units(text) -> str:
    """Feet/inches/yards -> metres and floors/verdiepingen/etages -> storeys."""
    s = _norm(text)
    lens, total = [], 0.0
    for m in _LEN_RE.finditer(s):
        v = float(m.group(1).replace(',', '.'))
        u = m.group(2).lower()
        if u in ("'", 'ft', 'feet', 'foot', 'voet', 'fuss', 'pied', 'pieds'):
            met, lab = v * _FT, 'ft'
        elif u in ('"', 'in', 'inch', 'inches', 'duim'):
            met, lab = v * _IN, 'in'
        else:
            met, lab = v * _YD, 'yd'
        total += met
        lens.append(f'{v:g} {lab} = {met:.2f} m')
    st = []
    for m in _ST_RE.finditer(s):
        n = float(m.group(1).replace(',', '.'))
        st.append(f'{n:g} {m.group(2)} = {int(n)} storeys = {n * STOREY_M:.1f} m (at {STOREY_M:g} m per storey)')
    out = lens + st
    if not out:
        return ''
    if len(lens) > 1:
        out.append(f'the lengths together are {total:.2f} m')
    return '; '.join(out)
