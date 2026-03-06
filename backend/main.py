import os
import uuid
import threading
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from processor import process_video, CLIPS_DIR

load_dotenv()

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)

jobs: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("GEMINI_API_KEY"):
        print("⚠️  ADVERTENCIA: GEMINI_API_KEY no está configurada en .env")
    yield


app = FastAPI(title="GolaClips API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")


def run_processing(job_id: str, video_path: str, api_key: str, openai_api_key: str,
                   duration_min: int, duration_max: int, num_clips: str, custom_prompt: str):
    def update_status(status: str):
        jobs[job_id]["status"] = status

    try:
        clips = process_video(
            job_id, video_path, api_key, update_status,
            duration_min=duration_min,
            duration_max=duration_max,
            num_clips=num_clips,
            custom_prompt=custom_prompt,
            openai_api_key=openai_api_key,
        )
        jobs[job_id]["status"] = "done"
        jobs[job_id]["clips"] = clips
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
    finally:
        try:
            os.unlink(video_path)
        except OSError:
            pass


@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(...),
    duration_min: int = Form(30),
    duration_max: int = Form(60),
    num_clips: str = Form("auto"),
    custom_prompt: str = Form(""),
):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY no configurada.")

    openai_api_key = os.getenv("OPENAI_API_KEY", "")

    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.flv', '.ts', '.mts'}
    ext = Path(file.filename).suffix.lower() if file.filename else ''
    is_video = (file.content_type and file.content_type.startswith("video/")) or ext in VIDEO_EXTENSIONS
    if not is_video:
        raise HTTPException(status_code=400, detail="El archivo debe ser un video")

    job_id = uuid.uuid4().hex
    ext = Path(file.filename).suffix or ".mp4"
    video_path = UPLOADS_DIR / f"{job_id}{ext}"

    with open(video_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    jobs[job_id] = {"status": "queued", "clips": [], "error": None}

    t = threading.Thread(
        target=run_processing,
        args=(job_id, str(video_path), api_key, openai_api_key,
              duration_min, duration_max, num_clips, custom_prompt),
        daemon=True,
    )
    t.start()

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return jobs[job_id]


@app.get("/health")
async def health():
    return {"ok": True, "gemini_key_configured": bool(os.getenv("GEMINI_API_KEY"))}


# Serve frontend last so API routes take priority
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
