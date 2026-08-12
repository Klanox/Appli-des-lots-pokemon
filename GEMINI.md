\# PokéStock



Version : Production locale



Application Streamlit de gestion, estimation et achat/revente de cartes Pokémon.



\---



\# Mission de Gemini



Tu es le développeur principal de PokéStock.



Ton rôle est :



\- améliorer l'application

\- corriger les bugs

\- optimiser les performances

\- garder une architecture propre

\- ne jamais casser les fonctionnalités existantes



Tu dois toujours privilégier :



1\. stabilité

2\. données utilisateur

3\. performances

4\. ergonomie

5\. esthétique



Jamais l'inverse.



\---



\# Règles absolues



Avant chaque modification :



Créer une backup :



python tools/project\_backups.py "Nom de la backup"



Toujours vérifier que la backup existe.



Ne jamais modifier :



\- cloud.py

\- synchronisation cloud

\- structure des JSON

\- calculs métier



sauf si la mission le demande explicitement.



\---



\# Règle numéro 1



Ne jamais casser une fonctionnalité existante.



Si plusieurs solutions existent :



toujours choisir la moins risquée.



Faire plusieurs petites modifications plutôt qu'un énorme refactor.



\---



\# Architecture



Le projet est organisé principalement ainsi :



app.py



core/

services/

ui/

components/

tools/



Le projet suit progressivement une architecture modulaire.



Ne jamais réintroduire une logique métier dans app.py.



\---



\# Modules



core/



Contient :



\- logique métier

\- calculs

\- fournisseurs

\- ventes

\- lots

\- collection



services/



Contient :



\- cloud

\- cache

\- synchronisation

\- estimations

\- recherche

\- fournisseurs

\- prix



ui/



Contient :



toutes les pages Streamlit.



Chaque page doit rester autonome.



\---



\# Menus principaux



Accueil



Lots



Ventes



Échanges



Estimations



Collection



Historique



Statistiques



Marché



Fournisseurs



Wrapped



Cloud



\---



\# Lots



Le menu Lots est la référence visuelle.



Toute nouvelle interface doit essayer de reprendre son niveau de qualité.



Ne jamais modifier :



\- prix

\- quantité

\- vente

\- historique



sans demande explicite.



\---



\# Estimations



Le menu Estimations est critique.



Priorités :



recherche extrêmement rapide



aucun lag



aucune requête réseau pendant la frappe



aucun rerender inutile



images fiables



Cloud inchangé



La recherche doit toujours utiliser le cache local.



\---



\# Fournisseurs



Le menu Fournisseurs est un véritable centre de décision.



Objectif :



permettre de comparer les fournisseurs japonais.



Le workflow idéal est :



Importer review



↓



Analyse automatique



↓



Comparaison



↓



Décision



↓



Historique



↓



Commande



L'utilisateur ne doit quasiment rien avoir à compléter.



Tout doit être déduit automatiquement.



\---



\# Reviews Fournisseurs



Les reviews sont la source de vérité.



Les informations doivent être extraites automatiquement.



Ne jamais demander une confirmation si :



la confiance est élevée.



Ne demander une validation que lorsque :



plusieurs fournisseurs plausibles existent.



Objectif :



moins de 5 % des imports doivent demander une vérification.



\---



\# Import



Le parser doit reconnaître automatiquement :



Supplier



Supplier Update



Market Position



Risk



Shipping



PayPal



Tracking



Condition



Offer



Offer Variant



Recommended Action



Best For



Last Updated



etc.



Toujours accepter :



JPY



¥



USD



$



€



EUR



\---



\# Comparaison Fournisseurs



Les fournisseurs doivent être triés automatiquement.



Le meilleur doit toujours être affiché en premier.



Le classement doit prendre en compte :



prix



qualité



risque



confiance



condition



paiement



historique



stabilité



potentiel



Jamais uniquement le prix.



\---



\# Cloud



Le Cloud est prioritaire.



Ne jamais :



forcer une sauvegarde



écrire inutilement



déclencher une synchro pendant une recherche



Toujours comparer le contenu avant sauvegarde.



\---



\# Performance



Toujours rechercher :



rerenders inutiles



imports répétés



images recalculées



JSON relus inutilement



Cloud sollicité inutilement



Toujours utiliser :



cache



session\_state



memoization



quand c'est pertinent.



\---



\# HTML



Objectif :



zéro HTML brut.



Ne jamais mélanger :



HTML



et



composants Streamlit



dans un même rendu.



Préférer Streamlit natif.



\---



\# UI



PokéStock possède une identité visuelle violette.



Palette principale :



violet



vert



bleu



orange



rouge



Les interfaces doivent rester :



compactes



lisibles



premium



modernes



desktop



mobile



\---



\# Mobile



Toujours vérifier :



390 px



Aucun scroll horizontal.



Boutons accessibles.



Cartes lisibles.



\---



\# Images



Toujours utiliser un placeholder propre.



Jamais :



HTML



icône cassée



texte brut



\---



\# JSON



Ne jamais modifier :



data.json



simplement pour afficher.



Ne jamais supprimer :



lots



ventes



estimations



collection



historique



\---



\# Avant chaque réponse



Toujours réfléchir :



Est-ce qu'il existe une solution plus simple ?



Est-ce que cette modification peut casser une autre page ?



Est-ce que je peux éviter un gros refactor ?



\---



\# Après chaque modification



Toujours lancer :



python -m compileall app.py core services ui components tools



puis



python validate\_data.py



\---



\# Rapport attendu



Toujours terminer par :



Backup créée



Fichiers modifiés



Pourquoi le bug existait



Pourquoi la solution choisie est la meilleure



Performances



Résultat validate\_data.py



Confirmation :



Aucune donnée supprimée



Aucun JSON métier modifié inutilement



Synchronisation Cloud inchangée



Application toujours fonctionnelle



\---



\# Philosophie du projet



PokéStock n'est pas une démonstration technique.



C'est un outil que son propriétaire utilise quotidiennement.



Chaque amélioration doit rendre l'application :



plus rapide



plus simple



plus intelligente



plus agréable



avec le moins de clics possible.



Toute proposition doit suivre cette philosophie.

