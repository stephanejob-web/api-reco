import os
import shutil
import subprocess
import glob
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from nudenet import NudeDetector
from ultralytics import YOLO
from huggingface_hub import hf_hub_download

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOADS_DIR = "uploads"
FRAMES_DIR = "frames"
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

NUDE_SCORE_THRESHOLD = 0.55
WEAPON_SCORE_THRESHOLD = 0.30

# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)

app = FastAPI(title="Mini-YouTube Content Scanner", version="1.0.0")

nude_detector = NudeDetector()

_weapon_model_path = hf_hub_download(
    repo_id="Subh775/Threat-Detection-YOLOv8n",
    filename="weights/best.pt",
)
weapon_model = YOLO(_weapon_model_path)


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


def cleanup_frames(output_dir: str) -> None:
    for f in glob.glob(os.path.join(output_dir, "frame_*.jpg")):
        try:
            os.remove(f)
        except OSError:
            pass


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


# ---------------------------------------------------------------------------
# Endpoint
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

        try:
            frames = extract_frames(video_path, FRAMES_DIR)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=422, detail=f"Erreur FFmpeg : {exc.stderr}")

        if not frames:
            raise HTTPException(status_code=422, detail="Aucune frame extraite.")

        status = "approved"
        weapon_hits = 0
        for frame_path in frames:
            if has_nudity(frame_path):
                status = "rejected_porn"
                break
            if has_weapon(frame_path):
                weapon_hits += 1
                if weapon_hits >= 2:
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
    uvicorn.run("main:app", host="0.0.0.0", port=7842, reload=False)
