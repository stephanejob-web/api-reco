import os
import shutil
import subprocess
import glob
import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from nudenet import NudeDetector
from ultralytics import YOLO

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOADS_DIR = "uploads"
FRAMES_DIR = "frames"
MAX_DURATION_SECONDS = 120          # 2 minutes
FRAME_INTERVAL_SECONDS = 5

# NudeNet labels considérés comme problématiques
NUDE_LABELS = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
}

# Classes COCO (YOLOv8) considérées comme violentes
VIOLENCE_CLASSES = {"knife", "scissors"}

# Seuils de confiance
NUDE_SCORE_THRESHOLD = 0.6
YOLO_SCORE_THRESHOLD = 0.5
RED_PIXEL_RATIO_THRESHOLD = 0.02   # 2 % de pixels rouges → suspicion de sang

# ---------------------------------------------------------------------------
# Initialisation (modèles chargés une seule fois au démarrage)
# ---------------------------------------------------------------------------
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)

app = FastAPI(title="Mini-YouTube Content Scanner", version="1.0.0")

nude_detector = NudeDetector()
yolo_model = YOLO("yolov8n.pt")   # téléchargé automatiquement (~6 Mo)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_video_duration(video_path: str) -> float:
    """Retourne la durée en secondes via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True, text=True, timeout=30,
    )
    raw = result.stdout.strip()
    if not raw:
        raise ValueError("Impossible de lire la durée de la vidéo.")
    return float(raw)


def extract_frames(video_path: str, output_dir: str, interval: int = FRAME_INTERVAL_SECONDS) -> list[str]:
    """Extrait une frame toutes les `interval` secondes via FFmpeg."""
    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-q:v", "2", pattern,
        ],
        capture_output=True, timeout=120, check=True,
    )
    return sorted(glob.glob(os.path.join(output_dir, "frame_*.jpg")))


def cleanup_frames(output_dir: str) -> None:
    """Supprime toutes les frames extraites."""
    for f in glob.glob(os.path.join(output_dir, "frame_*.jpg")):
        try:
            os.remove(f)
        except OSError:
            pass


def has_nudity(frame_path: str) -> bool:
    """Détecte la nudité avec NudeNet."""
    detections = nude_detector.detect(frame_path)
    return any(
        d.get("class") in NUDE_LABELS and d.get("score", 0) >= NUDE_SCORE_THRESHOLD
        for d in detections
    )


def has_violence(frame_path: str) -> bool:
    """Détecte armes / violence avec YOLOv8."""
    results = yolo_model(frame_path, verbose=False, conf=YOLO_SCORE_THRESHOLD)
    for result in results:
        for box in result.boxes:
            label = yolo_model.names[int(box.cls)]
            if label in VIOLENCE_CLASSES:
                return True
    return False


def has_blood(frame_path: str) -> bool:
    """Détecte les zones rouges (sang potentiel) avec OpenCV."""
    img = cv2.imread(frame_path)
    if img is None:
        return False
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0,   70, 50]), np.array([10,  255, 255]))
    mask2 = cv2.inRange(hsv, np.array([160, 70, 50]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(mask1, mask2)
    total = img.shape[0] * img.shape[1]
    return (cv2.countNonZero(red_mask) / total) >= RED_PIXEL_RATIO_THRESHOLD


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------

@app.post("/scan-video")
async def scan_video(file: UploadFile = File(...)):
    """
    Reçoit une vidéo en form-data, l'analyse frame par frame et renvoie :
      { "status": "approved" | "rejected_porn" | "rejected_violence" }
    """
    video_filename = (
        f"{os.path.splitext(file.filename)[0]}_{os.getpid()}"
        f"{os.path.splitext(file.filename)[1]}"
    )
    video_path = os.path.join(UPLOADS_DIR, video_filename)

    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # 1. Vérification de la durée
        try:
            duration = get_video_duration(video_path)
        except (ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            raise HTTPException(status_code=422, detail=f"Impossible de lire la vidéo : {exc}")

        if duration > MAX_DURATION_SECONDS:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "video_too_long",
                    "message": (
                        f"La vidéo dépasse 2 minutes ({duration:.1f}s). "
                        f"Maximum autorisé : {MAX_DURATION_SECONDS}s."
                    ),
                },
            )

        # 2. Extraction des frames via FFmpeg
        try:
            frames = extract_frames(video_path, FRAMES_DIR)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=422, detail=f"Erreur FFmpeg : {exc.stderr}")

        if not frames:
            raise HTTPException(status_code=422, detail="Aucune frame extraite.")

        # 3. Analyse frame par frame — arrêt au premier problème
        status = "approved"
        for frame_path in frames:
            if has_nudity(frame_path):
                status = "rejected_porn"
                break
            if has_violence(frame_path) or has_blood(frame_path):
                status = "rejected_violence"
                break

    finally:
        cleanup_frames(FRAMES_DIR)
        if os.path.exists(video_path):
            os.remove(video_path)

    return JSONResponse(content={"status": status})


# ---------------------------------------------------------------------------
# Lancement direct
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
