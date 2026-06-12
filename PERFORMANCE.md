# Pokestock - Performance P3

Ce document resume la phase P3 d'optimisation performance.

## Activation des logs performance

Les logs sont desactives par defaut.

Ils peuvent etre actives de trois facons :

- ajouter `?perf=1` dans l'URL ;
- activer `Logs performance console` dans la sidebar ;
- lancer l'app avec la variable `POKESTOCK_PERF=1`.

Quand le mode est actif, la console affiche des lignes comme :

```text
[PERF] page Vente / Echange: 0.400s
[PERF] rerun summary: 0.429s / cards_sales_available=148, cards_sales_rendered=64
```

Les compteurs principaux :

- `ld` : nombre de chargements de donnees ;
- `gst` / `gst_call` : calcul des statistiques globales ;
- `cards_sales_rendered` : cartes réellement affichees dans Vente / Echange ;
- `cards_sales_available` : cartes disponibles avant limite d'affichage ;
- `images_proxy` : images preparees par le proxy ;
- `images_proxy_cache_hit` : images reutilisees depuis le cache local de session ;
- `images_collection` : images Collection rendues.

## Optimisations realisees

### P3-C - Donnees et statistiques

- La page Estimations ne reecrit plus `lot_estimations.json` au simple affichage.
- Le cache cartes disque est utilise au demarrage sans forcer d'appel reseau TCGDex.
- La page Statistiques evite plusieurs recalculs inutiles et conserve les memes formules.

### P3-D - Images

- Ajout d'un cache de session pour `proxy_img`.
- Les images locales ne sont plus relues/reconverties inutilement pendant le meme rerun.
- La validation d'URL image ne fait plus de requete reseau pendant le rendu normal.
- La Collection garde la priorite des images manuelles, puis images resolues, images existantes, cache strict, puis placeholder.
- La securite Raichu GX reste stricte : une image de Raichu normal ne doit pas remplacer Raichu GX.

### P3-E - Vente / Echange

- La page Vente / Echange affiche progressivement les cartes quand aucun filtre n'est actif.
- Par defaut :
  - 64 cartes sur PC ;
  - 36 cartes sur mobile.
- Le bouton `Afficher plus` permet d'afficher la suite.
- La recherche et le filtre par lot restent complets : une carte recherchee n'est pas masquee par la limite.
- Certains calculs repetes dans la boucle de cartes sont reutilises pendant le rerun.

## Temps observes apres optimisation

Mesures indicatives avec les logs `[PERF]`, sur les donnees actuelles :

| Page | Temps observe |
| --- | ---: |
| Accueil | environ 0.04s |
| Lots | environ 0.04s |
| Vente / Echange sans recherche | environ 0.40s avec 64 cartes rendues sur 148 disponibles |
| Vente / Echange avec recherche | environ 0.07s a 0.09s |
| Collection | environ 0.04s |
| Statistiques | environ 0.48s a 0.92s selon cache/rendu graphique |
| Estimations | a surveiller si beaucoup d'estimations sont ouvertes |
| Historique | a surveiller si le nombre de ventes augmente fortement |

Ces valeurs sont des reperes, pas des garanties fixes : Streamlit peut varier selon le cache, le navigateur et la machine.

## Fichiers principaux concernes

- `services/perf_service.py` : instrumentation performance optionnelle ;
- `ui/pages/sales.py` : affichage progressif Vente / Echange ;
- `ui/pages/statistics.py` : mesures et optimisation Statistiques ;
- `services/estimations_service.py` : chargement Estimations sans ecriture inutile ;
- `app.py` : cache images, cache TCGDex au demarrage, integration des timers.

## Zones a surveiller plus tard

- Vente / Echange si le stock depasse plusieurs centaines de cartes disponibles.
- Historique si le nombre de ventes devient tres grand.
- Estimations si les previews Vinted ou images externes deviennent lentes.
- Images locales tres lourdes dans `card_images/`.
- Widgets Streamlit crees en masse dans les pages metier.

## Optimisations a eviter sans precaution

- Modifier les formules de benefice, cout, CA ou stock.
- Changer le format de `data.json`.
- Recalculer ou migrer les ventes existantes sans backup.
- Faire des appels reseau pendant le rendu normal des pages.
- Supprimer les fallbacks d'image ou les placeholders.
- Charger toutes les cartes d'un coup sur mobile.
