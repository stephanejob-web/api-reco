# Guide de test — Mini-YouTube Content Scanner

---

## 1. Lancer le projet avec Docker

### Prérequis
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installé et **lancé**

### Étapes

```bash
# 1. Cloner le repo
git clone <url-du-repo>
cd api-reco

# 2. Builder et démarrer le conteneur
docker compose up --build
```

Le premier lancement télécharge les modèles d'IA (~500 Mo). C'est normal, ça prend quelques minutes.

Quand tu vois cette ligne, l'API est prête :

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:7842
```

### Commandes utiles

```bash
# Lancer en arrière-plan (sans bloquer le terminal)
docker compose up -d

# Voir les logs en temps réel
docker compose logs -f

# Arrêter le conteneur
docker compose down
```

---

## 2. Tester avec Postman

### Importer la collection

1. Ouvrir **Postman**
2. Cliquer sur **Import** (en haut à gauche)
3. Sélectionner le fichier **`postman_collection.json`** fourni dans ce repo
4. La collection **"Mini-YouTube Content Scanner"** apparaît dans le panneau de gauche

### Envoyer une requête

1. Dans la collection, cliquer sur **"Scan Video"**
2. Aller dans l'onglet **Body**
3. Cliquer sur le champ `file` → icône de dossier → sélectionner ta vidéo
4. Cliquer sur **Send**

### Lire la réponse

| Réponse | Signification |
|---|---|
| `{ "status": "approved" }` | Vidéo propre, peut être publiée |
| `{ "status": "rejected_porn" }` | Contenu pornographique détecté |
| `{ "status": "rejected_violence" }` | Arme détectée (pistolet, grenade...) |

### Erreurs possibles

| Code HTTP | Message | Cause |
|---|---|---|
| `400` | `video_too_long` | La vidéo dépasse 2 minutes |
| `422` | `Impossible de lire la vidéo` | Fichier corrompu ou format non supporté |

---

## 3. Tester avec curl (terminal)

```bash
curl -X POST http://localhost:7842/scan-video \
  -F "file=@/chemin/vers/ta/video.mp4"
```

---

## 4. Documentation interactive (Swagger)

L'API expose une interface de test directement dans le navigateur :

```
http://localhost:7842/docs
```

---

## 5. Contraintes à respecter

- Format vidéo : `mp4`, `avi`, `mov`, `mkv`
- Durée maximale : **2 minutes**
- Taille recommandée : < 500 Mo
