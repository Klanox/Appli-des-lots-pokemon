"""COPIE FIGEE des anciennes regles de mots-cles (avant le 15/10/2026) : voir generator.py. Ne pas modifier."""
"""Regles d'enrichissement des annonces Vinted (mots recherches par les acheteurs).

Ce fichier est de la CONFIGURATION DE CODE (pas un JSON metier) : pour ajouter un cas,
ajouter une ligne dans LISTING_KEYWORD_RULES. Rien n'est ecrit dans les donnees : titre et
description sont recalcules a chaque affichage par services/vinted_listing_service.py.

Champs d'une regle :
  id            nom court (pour les tests et le rapport)
  set_ids       identifiants d'extension du catalogue (partie avant le dernier « - » de l'id
                de la carte, ex. « sv04.5 » pour « sv04.5-171 »)
  set_names     noms francais d'extension (repli quand la carte n'a pas d'id)
  number_prefix prefixe litteral du numero (« TG » pour « TG11 ») ; None = numero purement numerique
  number_min / number_max
                bornes INCLUSES sur la partie numerique du numero ; None = pas de borne
  words         mots ajoutes, dans cet ordre (le premier est le plus important : il est le dernier
                a sauter quand le titre depasse la limite)
  source        d'ou vient la regle (documentation)
  enabled       False pour desactiver une regle sans la supprimer

Les regles utilisent le numero imprime ou le prefixe litteral du numero : elles ne dependent
pas de la rarete, qui est vide dans les donnees actuelles (voir RARITY_SHINY_MARKERS).
"""

# Limite de longueur d'un titre Vinted.
MAX_TITLE_LENGTH = 100

# Ordre des reductions quand « Carte Pokémon - ... + mots » depasse MAX_TITLE_LENGTH.
# On ne coupe jamais en plein mot : on essaie chaque variante entiere, dans cet ordre, et on
# garde la premiere qui tient ; si aucune ne tient, le titre reste celui d'avant (sans ajout) et
# les mots ne figurent que dans la description.
#   1. « Carte Pokémon » + tous les mots
#   2. « Pokémon » (sans « Carte ») + tous les mots
#   3. « Carte Pokémon » + premier mot seulement
#   4. « Pokémon » + premier mot seulement
#   5. titre inchange
TITLE_FALLBACK_ORDER = (
    ("Carte Pokémon", "all"),
    ("Pokémon", "all"),
    ("Carte Pokémon", "first"),
    ("Pokémon", "first"),
)

# Quand la rarete du catalogue contient un de ces marqueurs, la carte est shiny (prioritaire sur la table).
RARITY_SHINY_MARKERS = ("shiny", "chromatique")
RARITY_SHINY_WORDS = ("Shiny", "Chromatique")

LISTING_KEYWORD_RULES = (
    {
        "id": "destinees-de-paldea-shiny",
        "set_ids": ("sv04.5",),
        "set_names": ("Destinées de Paldea",),
        "number_prefix": None,
        "number_min": 92,
        "number_max": 223,
        "words": ("Shiny", "Chromatique"),
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
        "words": ("Shiny", "Chromatique"),
        "source": "numerotation « SV » = Shiny Vault de l'extension",
        "enabled": True,
    },
    {
        "id": "trainer-gallery",
        "set_ids": ("swsh9", "swsh10", "swsh11", "swsh12"),
        "set_names": ("Stars Étincelantes", "Astres Radieux", "Origine Perdue", "Tempête Argentée"),
        "number_prefix": "TG",
        "number_min": None,
        "number_max": None,
        "words": ("Trainer Gallery",),
        "source": "numerotation « TG » = Trainer Gallery",
        "enabled": True,
    },
    {
        "id": "galarian-gallery",
        "set_ids": ("swsh12.5",),
        "set_names": ("Zénith Suprême",),
        "number_prefix": "GG",
        "number_min": None,
        "number_max": None,
        "words": ("Galarian Gallery",),
        "source": "numerotation « GG » = Galarian Gallery",
        "enabled": True,
    },
    {
        "id": "generations-radiant-collection",
        "set_ids": ("g1",),
        "set_names": ("Générations",),
        "number_prefix": "RC",
        "number_min": None,
        "number_max": None,
        "words": ("Radiant Collection",),
        "source": "numerotation « RC » = Radiant Collection",
        "enabled": True,
    },
)
