FROM python:3.11-slim

# Dépendances système (FFmpeg pour l'extraction de frames)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-téléchargement des modèles au build (pas besoin d'internet au runtime)
RUN python -c "from nudenet import NudeDetector; NudeDetector()"
RUN python -c "\
from huggingface_hub import hf_hub_download; \
hf_hub_download('Subh775/Threat-Detection-YOLOv8n', filename='weights/best.pt')"

# Copie du code
COPY main.py .

# Dossiers de travail
RUN mkdir -p uploads frames

EXPOSE 7842

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7842"]
