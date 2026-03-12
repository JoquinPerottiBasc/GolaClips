import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from processor import process_video, CLIPS_DIR, get_video_duration, cut_clip

load_dotenv()

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)

jobs: dict[str, dict] = {}

# max_workers=1 guarantees jobs are processed one at a time
_executor = ThreadPoolExecutor(max_workers=1)


class ExtendRequest(BaseModel):
    add_start: float = 0.0
    add_end: float = 0.0


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
        # Keep original video so clips can be re-cut (extend feature)
        try:
            original_ext = Path(video_path).suffix
            original_kept = UPLOADS_DIR / f"{job_id}_original{original_ext}"
            os.rename(video_path, str(original_kept))
            jobs[job_id]["original_video"] = str(original_kept)
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

    _executor.submit(run_processing, job_id, str(video_path), api_key,
                     openai_api_key, duration_min, duration_max, num_clips, custom_prompt)

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return jobs[job_id]


@app.post("/api/clips/{job_id}/{clip_filename}/extend")
async def extend_clip(job_id: str, clip_filename: str, body: ExtendRequest):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    original_video = jobs[job_id].get("original_video")
    if not original_video or not Path(original_video).exists():
        raise HTTPException(status_code=404, detail="Video original no disponible")

    clips = jobs[job_id].get("clips", [])
    clip = next((c for c in clips if c["filename"] == clip_filename), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip no encontrado")

    duration = await run_in_threadpool(get_video_duration, original_video)
    new_start = max(0.0, clip["start"] - body.add_start)
    new_end = min(duration, clip["end"] + body.add_end)

    out_path = str(CLIPS_DIR / job_id / clip_filename)
    await run_in_threadpool(cut_clip, original_video, new_start, new_end, out_path)

    clip["start"] = new_start
    clip["end"] = new_end

    return {"start": new_start, "end": new_end, "filename": clip_filename}


@app.get("/health")
async def health():
    return {"ok": True, "gemini_key_configured": bool(os.getenv("GEMINI_API_KEY"))}


# Serve frontend last so API routes take priority
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
