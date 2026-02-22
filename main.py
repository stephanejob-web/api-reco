import os
import shutil
import subprocess
import glob
import tempfile
import filetype
from datetime import datetime, timezone
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from nudenet import NudeDetector
from ultralytics import YOLO
from huggingface_hub import hf_hub_download
from transformers import pipeline as hf_pipeline, ViTForImageClassification, ViTImageProcessor

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOADS_DIR = "uploads"
MAX_DURATION_SECONDS = 120
FRAME_INTERVAL_SECONDS = 2

NUDE_LABELS = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
}

# Classes du modèle spécialisé Threat-Detection
WEAPON_CLASSES = {"Gun", "grenade", "explosion"}

NUDE_SCORE_THRESHOLD = 0.40
WEAPON_SCORE_THRESHOLD = 0.30
GORE_SCORE_THRESHOLD = 0.75

ALLOWED_VIDEO_MIMES = {
    "video/mp4",
    "video/x-msvideo",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
}

# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="Mini-YouTube Content Scanner", version="2.0.0")

nude_detector = NudeDetector()

_weapon_model_path = hf_hub_download(
    repo_id="Subh775/Threat-Detection-YOLOv8n",
    filename="weights/best.pt",
)
weapon_model = YOLO(_weapon_model_path)

_gore_processor = ViTImageProcessor.from_pretrained("jaranohaal/vit-base-violence-detection")
_gore_model = ViTForImageClassification.from_pretrained("jaranohaal/vit-base-violence-detection")
gore_classifier = hf_pipeline(
    "image-classification",
    model=_gore_model,
    image_processor=_gore_processor,
    device=-1,  # CPU
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_video_duration(video_path: str) -> float:
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


def extract_frames(video_path: str, output_dir: str) -> list[str]:
    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps=1/{FRAME_INTERVAL_SECONDS}",
            "-q:v", "2", pattern,
        ],
        capture_output=True, timeout=120, check=True,
    )
    return sorted(glob.glob(os.path.join(output_dir, "frame_*.jpg")))


def has_nudity(frame_path: str) -> bool:
    detections = nude_detector.detect(frame_path)
    for d in detections:
        print(f"[NUDITY] {d.get('class')} conf={d.get('score', 0):.2f} frame={os.path.basename(frame_path)}")
    return any(
        d.get("class") in NUDE_LABELS and d.get("score", 0) >= NUDE_SCORE_THRESHOLD
        for d in detections
    )


def has_weapon(frame_path: str) -> bool:
    results = weapon_model(frame_path, verbose=False, conf=0.1)
    for result in results:
        for box in result.boxes:
            label = weapon_model.names[int(box.cls)]
            conf = float(box.conf)
            print(f"[WEAPON] {label} conf={conf:.2f} frame={os.path.basename(frame_path)}")
            if label in WEAPON_CLASSES and conf >= WEAPON_SCORE_THRESHOLD:
                return True
    return False


def has_gore(frame_path: str) -> bool:
    results = gore_classifier(frame_path)
    for result in results:
        label = result["label"]
        score = result["score"]
        print(f"[GORE] {label} conf={score:.2f} frame={os.path.basename(frame_path)}")
        if label == "violent" and score >= GORE_SCORE_THRESHOLD:
            return True
    return False


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.post("/scan-video")
async def scan_video(file: UploadFile = File(...)):
    """
    Reçoit une vidéo en form-data, l'analyse frame par frame et renvoie :
      {
        "status": "approved" | "rejected_porn" | "rejected_violence" | "rejected_gore",
        "scanned_at": "<ISO 8601 UTC>",
        "frames_analyzed": <int>
      }
    """
    # -- Validation MIME (magic bytes, avant écriture sur disque) ------------
    header = await file.read(261)
    await file.seek(0)
    kind = filetype.guess(header)
    if kind is None or kind.mime not in ALLOWED_VIDEO_MIMES:
        raise HTTPException(
            status_code=415,
            detail={
                "error": "unsupported_media_type",
                "message": "Format non supporté. Acceptés : mp4, avi, mov, mkv, webm.",
            },
        )

    # -- Sauvegarde de la vidéo ----------------------------------------------
    video_filename = (
        f"{os.path.splitext(file.filename)[0]}_{os.getpid()}"
        f"{os.path.splitext(file.filename)[1]}"
    )
    video_path = os.path.join(UPLOADS_DIR, video_filename)

    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # -- Durée -----------------------------------------------------------
        try:
            duration = get_video_duration(video_path)
        except (ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            raise HTTPException(status_code=422, detail=f"Impossible de lire la vidéo : {exc}")

        if int(duration) > MAX_DURATION_SECONDS:
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

        # -- Extraction des frames dans un répertoire temporaire isolé -------
        with tempfile.TemporaryDirectory() as tmp_frames_dir:
            try:
                frames = extract_frames(video_path, tmp_frames_dir)
            except subprocess.CalledProcessError as exc:
                raise HTTPException(status_code=422, detail=f"Erreur FFmpeg : {exc.stderr}")

            if not frames:
                raise HTTPException(status_code=422, detail="Aucune frame extraite.")

            status = "approved"
            weapon_hits = 0
            gore_hits = 0
            for frame_path in frames:
                if has_nudity(frame_path):
                    status = "rejected_porn"
                    break
                if has_weapon(frame_path):
                    weapon_hits += 1
                    if weapon_hits >= 2:
                        status = "rejected_violence"
                        break
                if has_gore(frame_path):
                    gore_hits += 1
                    if gore_hits >= 2:
                        status = "rejected_gore"
                        break

            frames_analyzed = len(frames)
        # nettoyage automatique à la sortie du `with`

    finally:
        if os.path.exists(video_path):
            os.remove(video_path)

    scanned_at = (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    return JSONResponse(content={
        "status": status,
        "scanned_at": scanned_at,
        "frames_analyzed": frames_analyzed,
    })


# ---------------------------------------------------------------------------
# Lancement direct
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7842, reload=False)
