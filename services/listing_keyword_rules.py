"""Regles d'enrichissement des annonces Vinted (mots recherches par les acheteurs).

Ce fichier est de la CONFIGURATION DE CODE (pas un JSON metier) : pour ajouter un cas,
ajouter une ligne dans LISTING_KEYWORD_RULES. Rien n'est ecrit dans les donnees : titre et
description sont recalcules a chaque affichage par services/vinted_listing_service.py.

Les mots ajoutes sont des ABREVIATIONS COURTES, placees juste AVANT le numero de la carte, dans le
titre comme dans la description : « Courrousinge Shiny 171/091 ». Jamais de forme longue
(« Chromatique », « Illustration Rare », « Hyper Rare », « Full Art »).

Aucun mot n'est ajoute pour Trainer Gallery (TG), Galarian Gallery (GG), Radiant Collection (RC) ni
« SV » : le prefixe figure deja dans le numero (« TG11/TG30 »). Les cartes Shiny Vault (« SV ») recoivent
seulement « Shiny ».

Deux sources de mots :
  1. la table LISTING_KEYWORD_RULES ci-dessous (selon l'extension et le numero imprime) ;
  2. la RARETE de la carte (champ « rarity » de la carte, ou cache de rarete recupere depuis TCGdex par
     services/card_rarity_service.py) : voir RARITY_CLASS_WORDS et RARITY_AUTO_CLASSES.

Champs d'une regle de LISTING_KEYWORD_RULES :
  id            nom court (pour les tests et le rapport)
  set_ids       identifiants d'extension du catalogue (partie avant le dernier « - » de l'id
                de la carte, ex. « sv04.5 » pour « sv04.5-171 »)
  set_names     noms francais d'extension (repli quand la carte n'a pas d'id)
  number_prefix prefixe litteral du numero (« SV » pour « SV111 ») ; None = numero purement numerique
  number_min / number_max
                bornes INCLUSES sur la partie numerique du numero ; None = pas de borne
  words         mots ajoutes, dans cet ordre (le premier est le plus important : il est le dernier
                a sauter quand le titre depasse la limite)
  source        d'ou vient la regle (documentation)
  enabled       False pour desactiver une regle sans la supprimer
"""

# Limite de longueur d'un titre Vinted.
MAX_TITLE_LENGTH = 100

# Ordre des reductions quand le titre depasse MAX_TITLE_LENGTH. On ne coupe JAMAIS en plein mot : on essaie
# chaque variante entiere, dans cet ordre, et on garde la premiere qui tient.
#   1. « Carte Pokémon » + toutes les abreviations
#   2. « Pokémon » (sans « Carte ») + toutes les abreviations      <- on sacrifie d'abord « Carte »
#   3. « Carte Pokémon » + la premiere abreviation seulement
#   4. « Pokémon » + la premiere abreviation seulement
#   5. « Carte Pokémon » sans abreviation (les mots ne figurent alors que dans la description)
#   6. « Pokémon » sans abreviation
# Les abreviations sont donc ce qui saute EN DERNIER. Si rien ne tient (titre deja trop long sans mot ajoute),
# le titre reste celui d'avant, sans abreviation et sans coupure.
TITLE_FALLBACK_ORDER = (
    ("Carte Pokémon", "all"),
    ("Pokémon", "all"),
    ("Carte Pokémon", "first"),
    ("Pokémon", "first"),
    ("Carte Pokémon", "none"),
    ("Pokémon", "none"),
)

# Classe de rarete (voir services/card_rarity_service.classify_rarity) -> abreviation ajoutee.
RARITY_CLASS_WORDS = {
    "shiny": "Shiny",   # rarete « shiny » / « chromatique » du catalogue (hors plage de numeros de la table)
    "ar": "AR",         # « Illustration rare »
    "gold": "Gold",     # « Hyper rare »
    "sir": "Alt",       # « Illustration spéciale rare » (Special illustration rare), seulement si la rareté est certaine
    "fa": "FA",         # « Ultra Rare » des Pokémon ex / EX / V / GX et des Dresseurs / Supporters (accord du 15/10/2026)
}

# Classes appliquees automatiquement. « fa_review » est volontairement absent : une « Ultra Rare » VMAX, VSTAR ou
# de sous-type inconnu ne reçoit rien sans accord ; elle est listee dans le bilan de l'ecran « Rareté des cartes ».
RARITY_AUTO_CLASSES = ("shiny", "ar", "gold", "sir", "fa")

# Une carte n'a JAMAIS deux abreviations de rarete. Priorite quand plusieurs s'appliqueraient :
# Alt, Gold, AR, FA, puis « Shiny » seul s'il n'y en a aucune autre.
RARITY_WORD_PRIORITY = ("sir", "gold", "ar", "fa", "shiny")

# Rarete NON traitee (aucun mot ajoute), comptee ET listee dans le bilan de rarete :
#   Secret / Secrete et Alternate / Alternative (series Epee et Bouclier notamment).
RARITY_NOT_HANDLED_CLASSES = ("secret", "alternate")

LISTING_KEYWORD_RULES = (
    {
        "id": "destinees-de-paldea-shiny",
        "set_ids": ("sv04.5",),
        "set_names": ("Destinées de Paldea",),
        "number_prefix": None,
        "number_min": 92,
        "number_max": 223,
        "words": ("Shiny",),
        "source": "regle de l'utilisateur (15/10/2026) ; confirmee : 92-211 Shiny Rare, 212-223 Shiny Ultra Rare",
        "enabled": True,
    },
    {
        "id": "destinees-radieuses-shiny-vault",
        "set_ids": ("swsh4.5",),
        "set_names": ("Destinées Radieuses",),
        "number_prefix": "SV",
        "number_min": None,
        "number_max": None,
        "words": ("Shiny",),
        "source": "numerotation « SV » = Shiny Vault de l'extension ; seulement « Shiny », pas de mot « SV »",
        "enabled": True,
    },
    {
        "id": "destinees-occultes-shiny-vault",
        "set_ids": ("sm115",),
        "set_names": ("Destinées Occultes",),
        "number_prefix": "SV",
        "number_min": None,
        "number_max": None,
        "words": ("Shiny",),
        "source": "numerotation « SV » = Shiny Vault de l'extension (SV1-SV94) ; seulement « Shiny »",
        "enabled": True,
    },
)

# --------------------------------------------------------------------------- numero imprime : total

# Totaux des sous-ensembles a prefixe (le « total » imprime n'est pas celui de l'extension) :
#   « TG11/TG30 », « GG17/GG70 », « SV111/SV122 », « RC13/RC32 ».
# Une carte a prefixe qui n'est pas dans cette table (promos SWSH285, etc.) n'a pas de total : jamais invente.
SUBSET_TOTALS = (
    {"set_ids": ("swsh9",), "prefix": "TG", "total": 30, "source": "Trainer Gallery TG01-TG30 (Bulbapedia)"},
    {"set_ids": ("swsh10",), "prefix": "TG", "total": 30, "source": "Trainer Gallery TG01-TG30 (Bulbapedia)"},
    {"set_ids": ("swsh11",), "prefix": "TG", "total": 30, "source": "Trainer Gallery TG01-TG30 (Bulbapedia)"},
    {"set_ids": ("swsh12",), "prefix": "TG", "total": 30, "source": "Trainer Gallery TG01-TG30 (Bulbapedia)"},
    {"set_ids": ("swsh12.5",), "prefix": "GG", "total": 70, "source": "Galarian Gallery GG01-GG70 (Bulbapedia)"},
    {"set_ids": ("swsh4.5",), "prefix": "SV", "total": 122, "source": "Shiny Vault SV001-SV122 (Bulbapedia)"},
    {"set_ids": ("sm115",), "prefix": "SV", "total": 94, "source": "Shiny Vault SV1-SV94 (Bulbapedia)"},
    {"set_ids": ("g1",), "prefix": "RC", "total": 32, "source": "Radiant Collection RC1-RC32 (Bulbapedia)"},
)

# Blocs dont les cartes sont imprimees avec 3 chiffres (« 027/185 », « 171/091 ») : on complete avec des
# zeros le numero et le total. Reconnu par l'identifiant d'extension TCGdex (les promos « svp », « swshp »,
# « mep » n'en font pas partie). Les blocs plus anciens s'impriment sans zero : on n'y touche pas.
ZERO_PADDED_SET_ID_PATTERN = r"^(?:sv|swsh|me)\d|^cel25$"
ZERO_PAD_WIDTH = 3
