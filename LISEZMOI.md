# Builds Fellowship

Site d'une page qui résume les builds du top 30 de chaque héros (Fellowship Logs),
mis à jour automatiquement chaque nuit par GitHub.

## Contenu
- `comparer_builds.py` : interroge l'API Fellowship Logs et écrit `resultats/builds_<héros>.json`
- `build_site.py` + `modele_site.html` : transforment ces fichiers en `docs/index.html`
- `.github/workflows/mise-a-jour.yml` : enchaîne les deux chaque nuit et publie le site

## Mise en route (une seule fois)
1. Crée un compte sur github.com puis un dépôt (bouton « New »), par exemple `fellowship-builds`.
   Public : le site est gratuit sur GitHub Pages. Les identifiants de l'API ne sont jamais dans les fichiers.
2. « Add file » > « Upload files » : dépose tout le contenu de ce dossier
   (y compris le dossier `.github` et `docs/index.html`), puis « Commit changes ».
3. Settings > Secrets and variables > Actions > « New repository secret » :
   - `FELLOWSHIP_CLIENT_ID` = ton client id
   - `FELLOWSHIP_CLIENT_SECRET` = ton client secret
4. Settings > Pages : Source « Deploy from a branch », branche `main`, dossier `/docs`, « Save ».
   Le site apparaît à l'adresse `https://<ton-pseudo>.github.io/fellowship-builds/`.
5. Onglet Actions > « Mise a jour du site » > « Run workflow » pour un premier lancement.

## Bon à savoir
- Le premier lancement est long (12 héros × 7 donjons × 30 joueurs, avec des pauses pour respecter
  le quota de l'API). Les suivants vont beaucoup plus vite : les combats déjà lus restent en cache.
- Si un lancement dépasse le temps maximum (6 h), relance-le : il repart du cache.
- Pour changer la fréquence, modifie la ligne `cron` du fichier `.github/workflows/mise-a-jour.yml`.
- Générer le site à la main : `python build_site.py resultats/builds_*.json -o docs/index.html`
