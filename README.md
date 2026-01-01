# drive-compare

Application locale (LAN) pour comparer les prix entre le drive Leclerc Seclin Lorival et Auchan Faches-Thumesnil.

## Fonctionnalités MVP

- Recherche produits + ajout panier local.
- Historique des paniers et comparaison.
- Jobs en base (COMPARE_BASKET, REFRESH_PRODUCT, REFRESH_BASKET, PUSH_BASKET).
- Worker Playwright (headless) avec scheduler quotidien à 05:00 (image Playwright officielle).
- SQLite en mode WAL.
- Sessions Playwright persistées dans `/sessions`.

## Pré-requis (Debian/Ubuntu/LXC Proxmox)

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

## Démarrage rapide

1. Créez le fichier `.env` (ou copiez `.env.example`) et ajustez au besoin `LECLERC_STORE_URL`.

```bash
cp .env.example .env
```

2. Initialisez la base (SQLite).

```bash
docker compose run --rm backend python backend/init_db.py
```

3. Lancez les services.

```bash
docker compose up --build
```

4. Accédez à l'UI:

- http://localhost:8000/

## Notes

- Le docker-compose.yml n'utilise plus de clé `version:` (obsolète avec compose v2).

- Le worker utilise Playwright headless, avec des stubs pour les retailers.
- Les erreurs Playwright génèrent une capture d’écran + trace dans `/logs`.
- Les comptes bots/main sont gérés via `.env` (aucun secret dans le code).
- Leclerc nécessite un `LECLERC_STORE_URL` pointant vers le drive cible (par défaut Seclin Lorival).

## Debug Leclerc

Pour déclencher une recherche Leclerc via l'IHM :

1. Démarrez les services (`docker compose up --build`).
2. Ouvrez l'UI: `http://localhost:8000/`.
3. Lancez une recherche "Recherche produit" (ex: `coca`, `lait`, `pâtes`).

Où récupérer les artefacts (volume `/logs`) :

- Réseau: `/logs/leclerc_network_*.jsonl` (document + XHR/Fetch).
- Pas de résultats: `/logs/leclerc_noresults_*.png` et `/logs/leclerc_noresults_*.html`.
- Erreurs Playwright: `/logs/leclerc_error_*.png` et `/logs/leclerc_error_*.html`.

Le store Leclerc est configurable via `LECLERC_STORE_URL` (ex: autre drive en changeant l'URL dans `.env`).

## Leclerc: protection anti-bot (DataDome)

Leclerc peut renvoyer une page de blocage DataDome (`Access blocked` / `captcha-delivery.com`).
Dans ce cas, la recherche échoue en `BLOCKED` avec la raison `DATADOME_BLOCKED` et des artefacts sont générés:

- `/logs/leclerc_blocked_*.html`
- `/logs/leclerc_blocked_*.png`

### Session Leclerc via GUI (mobile-first)

Le worker pilote **le même navigateur** que l'UI Leclerc (Chromium) via CDP. Flux humain-in-the-loop: le worker tente l'automatisation, signale un blocage au backend, l'utilisateur ouvre l'UI distante uniquement pour résoudre le captcha/login, puis le worker relance automatiquement via le même Chromium partagé.

Pour créer une session valide sur mobile (LAN):

1. Ouvrir DriveCompare sur mobile (`http://<IP>:8000`).
2. Lancer une recherche Leclerc.
3. Si DataDome bloque, l'app affiche un lien pour ouvrir `https://<IP>:5801` (HTTPS) dans le navigateur distant.
4. Tapez **Ouvrir Leclerc (HTTPS)** pour ouvrir le navigateur distant (tap utilisateur requis sur mobile).
5. Dans le navigateur distant:
   - Passer le captcha/login.
   - Sélectionner le magasin si demandé (l'URL par défaut est `LECLERC_STORE_URL`).
6. Revenir sur DriveCompare et cliquer **J'ai terminé** pour libérer le verrou, effacer l'URL bloquée et relancer la recherche automatiquement.

La session est persistée dans `./sessions/leclerc_profile` et réutilisée par le worker via CDP.
Si le verrou `GUI_ACTIVE` est actif, le worker refuse le job Leclerc pour éviter la corruption du profil.
L'état Leclerc est stocké en base (table `key_value`).

> Note: le presse-papier automatique peut nécessiter HTTPS côté navigateur distant. Sinon, utilisez le panneau clipboard si présent.

### Configuration leclerc-gui (Chromium)

Le service `leclerc-gui` expose une interface web sur `https://<IP>:5801` (HTTPS).
Il démarre en mode "app" sur `/leclerc/unblock`, qui affiche une page "kiosk" et redirige automatiquement vers la dernière URL bloquée
DataDome quand un blocage est détecté. Un port CDP interne est activé (9222) pour que le worker pilote le même navigateur.
Le worker partage le namespace réseau du service `leclerc-gui`, ce qui permet d'accéder au CDP via `http://127.0.0.1:9222`
même si Chromium écoute uniquement sur le loopback.
Pour éviter un accès libre sur le LAN, l'image `lscr.io/linuxserver/chromium` supporte:

- `CUSTOM_USER`
- `PASSWORD`

Laissez ces variables absentes si vous ne souhaitez pas activer l'authentification.
Voir `.env.example` pour les variables disponibles.

### Fix leclerc-gui 500 (permissions /config)

Si `https://<IP>:5801` renvoie `Internal Server Error`, les permissions du profil Chromium sont
probablement incorrectes. Exécutez:

```bash
mkdir -p sessions/leclerc_profile
sudo chown -R 1000:1000 sessions/leclerc_profile
```

Ou utilisez le script:

```bash
./tools/fix_permissions.sh
```

### Diagnostic CDP

Vérifier que Chromium écoute bien sur le port CDP (9222) dans le conteneur:

```bash
docker compose exec leclerc-gui ss -lntp | grep 9222
docker compose exec leclerc-gui curl -s http://127.0.0.1:9222/json/version
```

### Diagnostic Leclerc

- Vérifier le CDP dans le namespace partagé:

```bash
docker compose exec worker bash -lc 'python - <<PY
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2).read()[:120])
PY'
```

- Vérifier que l'UI Kasm est en HTTPS:
  - Ouvrir `https://<IP>:5801`

- Vérifier l'état backend:

```bash
curl -s http://127.0.0.1:8000/leclerc/unblock/status
```

### Dépannage

- Si DataDome réapparaît, refaire l'étape **Session Leclerc via GUI**.
- Si `https://<IP>:5801` n'est pas accessible, vérifiez:
  - que `leclerc-gui` est démarré (`docker compose ps`),
  - que le port 5801 est ouvert sur le LAN.

### Validité

Si Leclerc rebloque l'accès, relancez simplement la session via le GUI pour régénérer la session.

## How to test manually

1. Démarrez les services avec `docker compose up --build`.
2. Ouvrez l'UI: `http://<IP>:8000`.
3. Lancez une recherche Leclerc (ex: "coca 1.5L").
4. Vérifiez que le job passe en SUCCESS et qu'au moins un produit est listé.
5. En cas d'échec, inspectez les artefacts Playwright dans `./logs` (captures et HTML).

## Test POC Leclerc

1. Démarrez les services.

```bash
docker compose up -d --build
```

2. Ouvrez l'UI: `http://<IP>:8000`.

3. Lancez une recherche "coca" via le formulaire "Recherche produit".

4. Vérifiez les logs réseau:

```bash
ls -lah ./logs
```

Le fichier `leclerc_network_*.jsonl` est créé dans `./logs` (volume Docker).

## Sanity checks

```bash
docker compose build --no-cache worker
docker compose up -d --build
docker compose ps
docker compose logs -f worker
```

## Structure

```
.
├── backend/            # FastAPI + templates
├── worker/             # Worker Playwright + scheduler
├── data/               # SQLite (volume local)
├── logs/               # traces/screenhots
├── sessions/           # storage_state JSON + profil Leclerc (leclerc_profile)
└── docker-compose.yml
```
