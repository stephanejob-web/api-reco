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
  ├── NudeNet        → nudité exposée sur 1+ frame  → rejected_porn
  └── Threat-Detection YOLOv8n → arme sur 2+ frames → rejected_violence
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
- Un maillot de bain ou des vêtements couvrants ne déclenchent **pas** ce détecteur

### Threat-Detection YOLOv8n (Subh775)
- **Rôle** : détection d'armes et menaces
- **Technologie** : YOLOv8 nano fine-tuné sur un dataset d'armes
- **Classes surveillées** : `Gun`, `grenade`, `explosion`
- **Seuil de confiance** : 0.30 (30%)
- **Précision** : mAP50 ≈ 81%, précision Gun ≈ 96.7%
- Déclenche uniquement si l'arme est détectée sur **au moins 2 frames** (évite les faux positifs)
- Modèle téléchargé automatiquement depuis HuggingFace au démarrage

---

## Stack technique

| Composant | Technologie |
|---|---|
| API | FastAPI + Uvicorn |
| Extraction frames | FFmpeg |
| Détection nudité | NudeNet + ONNX Runtime |
| Détection armes | Threat-Detection YOLOv8n + PyTorch |
| Runtime | Python 3.11 |
| Port | 7842 |

---

## Installation

### Option 1 — Docker (recommandée)

La méthode la plus simple. Aucune installation de Python ou FFmpeg requise — tout est dans le conteneur.

**Prérequis :** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installé et lancé.

```bash
# 1. Cloner le repo
git clone <url-du-repo>
cd api-reco

# 2. Builder et lancer le conteneur
docker compose up --build
```

Le premier build télécharge les modèles (~500 Mo au total). Les lancements suivants sont instantanés.

```bash
# Lancer sans rebuild (après le premier build)
docker compose up

# Lancer en arrière-plan
docker compose up -d

# Arrêter
docker compose down
```

---

### Option 2 — Installation manuelle (macOS)

#### Prérequis
- Python 3.11 (via pyenv)
- FFmpeg

```bash
# Installer FFmpeg
brew install ffmpeg

# Installer pyenv si nécessaire
curl https://pyenv.run | bash

# Installer Python 3.11
pyenv install 3.11.9
```

#### Setup

```bash
# Créer le virtualenv avec Python 3.11
~/.pyenv/versions/3.11.9/bin/python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

#### Lancer le serveur

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 7842
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

## Test avec Postman

1. Méthode : `POST`
2. URL : `http://localhost:7842/scan-video`
3. Body → `form-data` → clé `file`, type `File`
4. Sélectionner une vidéo et envoyer

### Documentation interactive

```
http://localhost:7842/docs
```

---

## Limites

- Durée maximale : **2 minutes**
- Détection d'armes limitée à `Gun`, `grenade`, `explosion` — les couteaux sont exclus (trop de faux positifs)
- Performances dépendantes du CPU (pas de GPU requis, mais le traitement est plus lent sur des machines peu puissantes)
