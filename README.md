# Mini-YouTube Content Scanner

API REST de modération automatique de vidéos. Elle analyse le contenu frame par frame et rejette les vidéos contenant de la pornographie ou des armes.

---

## À quoi ça sert

Dans une plateforme de partage vidéo type YouTube, chaque vidéo uploadée doit être vérifiée avant publication. Cette API joue le rôle de modérateur automatique : elle reçoit une vidéo, l'analyse et retourne un verdict.

**Cas d'usage :** intégrer cet endpoint dans le pipeline d'upload — si la vidéo est `approved`, elle est publiée ; sinon, elle est rejetée avant même d'atteindre les utilisateurs.

---

## Fonctionnement

```
Vidéo uploadée
      │
      ▼
Vérification durée (max 2 min)
      │
      ▼
Extraction de frames (1 frame / 2s via FFmpeg)
      │
      ▼
Pour chaque frame :
  ├── NudeNet  → nudité détectée ? → rejected_porn
  └── YOLOv8m → arme détectée ?   → rejected_violence
      │
      ▼
{ "status": "approved" }
```

---

## Modèles utilisés

### NudeNet 3.4.2
- **Rôle** : détection de contenu pornographique
- **Technologie** : réseau de neurones ONNX entraîné spécifiquement sur la nudité humaine
- **Labels surveillés** : `FEMALE_GENITALIA_EXPOSED`, `MALE_GENITALIA_EXPOSED`, `FEMALE_BREAST_EXPOSED`, `BUTTOCKS_EXPOSED`, `ANUS_EXPOSED`
- **Seuil de confiance** : 0.55 (55%)

### YOLOv8m (medium)
- **Rôle** : détection d'armes
- **Technologie** : You Only Look Once v8, variante medium — entraîné sur le dataset COCO (80 classes)
- **Classes surveillées** : `knife`, `scissors`
- **Seuil de confiance** : 0.5 (50%)
- **Précision** : mAP50 ≈ 50.2 sur COCO

> Le modèle `yolov8m.pt` (~50 Mo) est téléchargé automatiquement au premier démarrage.

---

## Stack technique

| Composant | Technologie |
|---|---|
| API | FastAPI + Uvicorn |
| Extraction frames | FFmpeg |
| Détection nudité | NudeNet + ONNX Runtime |
| Détection armes | Ultralytics YOLOv8m + PyTorch |
| Runtime | Python 3.11 |

---

## Installation

### Prérequis
- Python 3.11 (via pyenv)
- FFmpeg

```bash
# Installer FFmpeg (macOS)
brew install ffmpeg

# Installer pyenv si nécessaire
curl https://pyenv.run | bash

# Installer Python 3.11
pyenv install 3.11.9
```

### Setup

```bash
# Créer le virtualenv avec Python 3.11
~/.pyenv/versions/3.11.9/bin/python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

### Lancer le serveur

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Utilisation

### Endpoint

```
POST /scan-video
Content-Type: multipart/form-data
```

| Champ | Type | Description |
|---|---|---|
| `file` | File | Fichier vidéo (mp4, avi, mov...) |

### Réponses

```json
{ "status": "approved" }
```
```json
{ "status": "rejected_porn" }
```
```json
{ "status": "rejected_violence" }
```

### Codes d'erreur

| Code | Raison |
|---|---|
| 400 | Vidéo trop longue (> 2 minutes) |
| 422 | Fichier invalide ou illisible |

---

### Test avec Postman

1. Méthode : `POST`
2. URL : `http://localhost:8000/scan-video`
3. Body → `form-data` → clé `file`, type `File`
4. Sélectionner une vidéo et envoyer

### Documentation interactive

```
http://localhost:8000/docs
```

---

## Limites

- Durée maximale : **2 minutes**
- Détection d'armes limitée aux classes COCO (`knife`, `scissors`) — les armes à feu ne sont pas détectées par ce modèle
- Performances dépendantes du CPU (pas de GPU requis, mais le traitement est plus lent)
