# DriveCompare (POC)

## Démarrage (clean)

```bash
cd ~/drivecompare
docker compose down --remove-orphans
mkdir -p data logs sessions
chmod -R 777 data logs sessions || true

docker compose up -d --build --force-recreate

# Diagnostic rapide
./tools/doctor.sh
```

## Accès UI déblocage Leclerc (noVNC)

- Ouvre **http://<IP_DU_SERVEUR>:5800**
- Le navigateur doit afficher la page `.../leclerc/unblock`
- Si Leclerc te bloque (DataDome), résous le challenge dans ce navigateur.
- Puis clique "J'ai débloqué" sur la page d'unblock.

## Recherche Leclerc (POC)
- UI : http://<IP_DU_SERVEUR>:8000/leclerc
- API : GET /api/leclerc/search?q=coca (optionnel: &limit=20)
- La recherche passe par le worker CDP, donc l'onglet Leclerc doit être débloqué.

## Notes

- Le CDP est exposé **uniquement sur le réseau Docker** (pas publié sur l’hôte).
- Le profil Chromium est stocké dans un volume Docker `leclerc_config` pour éviter les problèmes de droits en LXC.
