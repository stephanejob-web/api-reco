FROM python:3.11-slim

# Dépendances système (FFmpeg pour l'extraction de frames)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch CPU-only en premier (évite le wheel CUDA de 2 GB)
RUN pip install --no-cache-dir torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

# Puis les autres dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-téléchargement des modèles au build (pas besoin d'internet au runtime)
RUN python -c "from nudenet import NudeDetector; NudeDetector()"
RUN python -c "\
from huggingface_hub import hf_hub_download; \
hf_hub_download('Subh775/Threat-Detection-YOLOv8n', filename='weights/best.pt')"
RUN python -c "\
from transformers import ViTForImageClassification, ViTImageProcessor; \
ViTImageProcessor.from_pretrained('jaranohaal/vit-base-violence-detection'); \
ViTForImageClassification.from_pretrained('jaranohaal/vit-base-violence-detection')"

# Copie du code
COPY main.py .

# Dossier de travail (frames n'est plus nécessaire)
RUN mkdir -p uploads

EXPOSE 7842

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7842"]
