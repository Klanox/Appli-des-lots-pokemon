# Mise en ligne mobile

Objectif : utiliser l'app sur téléphone et PC avec les mêmes données.

## 1. Supabase

1. Crée un projet Supabase gratuit.
2. Va dans SQL Editor.
3. Colle le contenu de `supabase_setup.sql`.
4. Clique sur Run.
5. Va dans Project Settings > API.
6. Garde sous la main :
   - Project URL
   - service_role key

## 2. Secrets Streamlit

Dans Streamlit Community Cloud, ajoute ces secrets :

```toml
SUPABASE_URL = "https://TON-PROJET.supabase.co"
SUPABASE_KEY = "TA-CLE-SERVICE-ROLE"
APP_PASSWORD = "un-mot-de-passe-a-toi"
```

En local, tu peux aussi créer `.streamlit/secrets.toml` avec le même contenu.

Important : ne mets jamais `.streamlit/secrets.toml` sur GitHub.

## 3. Déploiement

1. Mets le dossier sur GitHub.
2. Crée une app sur Streamlit Community Cloud.
3. Choisis `app.py`.
4. Ajoute les secrets ci-dessus.
5. Lance l'app.

## 4. Premier envoi des données

Depuis ton PC, ouvre l'app avec les secrets Supabase configurés.
Dans la barre de gauche, clique sur :

`☁️ Envoyer les données locales vers le cloud`

Après ça, téléphone et PC liront la même base.

## 5. URL mobile

Utilise l'adresse de l'app avec :

`?mobile=1&page=vente`

Exemple :

`https://ton-app.streamlit.app/?mobile=1&page=vente`

Ajoute cette page à l'écran d'accueil du téléphone.
