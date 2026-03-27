import math
import os
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import asynccontextmanager

import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from processor import process_video, CLIPS_DIR, get_video_duration, cut_clip
import database
import storage
from auth import get_current_user

load_dotenv()

# Plan definitions: credits in minutes, expiry in days
PLAN_CREDITS = {"free": 30, "pro": 200}
PLAN_EXPIRY_DAYS = {"free": 3, "pro": 30}

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)

jobs: dict[str, dict] = {}

# max_workers=1 guarantees jobs are processed one at a time
_executor = ThreadPoolExecutor(max_workers=1)


class ExtendRequest(BaseModel):
    add_start: float = 0.0
    add_end: float = 0.0


async def _cleanup_expired_loop():
    """Delete expired clips from R2 and DB every 24 hours."""
    while True:
        await asyncio.sleep(86400)
        try:
            r2_keys = database.delete_expired_jobs()
            if r2_keys:
                storage.delete_objects(r2_keys)
                print(f"Cleaned up {len(r2_keys)} expired clips from R2")
        except Exception as e:
            print(f"Cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        print("WARNING: STRIPE_SECRET_KEY not configured")
    if not os.getenv("GEMINI_API_KEY"):
        print("WARNING: GEMINI_API_KEY not configured in .env")
    if not os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON"):
        print("WARNING: FIREBASE_SERVICE_ACCOUNT_JSON not configured — auth will fail")
    if not storage.is_configured():
        print("WARNING: R2 not configured — clips won't be stored in cloud")
    database.init_db()
    cleanup_task = asyncio.create_task(_cleanup_expired_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(title="GolaClips API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")


def run_processing(job_id: str, video_path: str, api_key: str, openai_api_key: str,
                   duration_min: int, duration_max: int, num_clips: str, custom_prompt: str,
                   user_id: int = None, add_watermark: bool = False, credits_used: int = 0):
    def update_status(status: str):
        jobs[job_id]["status"] = status
        if user_id is not None:
            try:
                database.update_job_status(job_id, status)
            except Exception:
                pass

    try:
        clips = process_video(
            job_id, video_path, api_key, update_status,
            duration_min=duration_min,
            duration_max=duration_max,
            num_clips=num_clips,
            custom_prompt=custom_prompt,
            openai_api_key=openai_api_key,
            add_watermark=add_watermark,
        )

        # Upload each clip to R2 and persist to DB
        for clip in clips:
            r2_key = f"clips/{job_id}/{clip['filename']}"
            local_path = str(CLIPS_DIR / job_id / clip["filename"])
            # Always set a local URL so active jobs work immediately
            clip["url"] = f"/clips/{job_id}/{clip['filename']}"
            if clip.get("thumbnail"):
                clip["thumb_url"] = f"/clips/{job_id}/{clip['thumbnail']}"

            if user_id is not None:
                try:
                    storage.upload_clip(local_path, r2_key)
                    # Upload thumbnail to R2 too
                    if clip.get("thumbnail"):
                        thumb_local = str(CLIPS_DIR / job_id / clip["thumbnail"])
                        thumb_r2_key = f"clips/{job_id}/{clip['thumbnail']}"
                        storage.upload_clip(thumb_local, thumb_r2_key)
                    database.insert_clip(
                        job_id=job_id,
                        filename=clip["filename"],
                        r2_key=r2_key,
                        start_sec=clip["start"],
                        end_sec=clip["end"],
                        score=clip.get("score", 5),
                        description=clip.get("description", ""),
                    )
                except Exception as e:
                    print(f"R2/DB error for {clip['filename']}: {e}")

        jobs[job_id]["status"] = "done"
        jobs[job_id]["clips"] = clips

        if user_id is not None:
            try:
                database.update_job_status(job_id, "done")
            except Exception:
                pass

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        if user_id is not None:
            try:
                database.update_job_status(job_id, "error", str(e))
            except Exception:
                pass
            # Refund credits on processing failure
            if credits_used:
                try:
                    database.refund_credits(user_id, credits_used)
                except Exception:
                    pass
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
    current_user: dict = Depends(get_current_user),
):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY no configurada.")

    openai_api_key = os.getenv("OPENAI_API_KEY", "")

    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".ts", ".mts"}
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    is_video = (file.content_type and file.content_type.startswith("video/")) or ext in VIDEO_EXTENSIONS
    if not is_video:
        raise HTTPException(status_code=400, detail="El archivo debe ser un video")

    job_id = uuid.uuid4().hex
    ext = Path(file.filename).suffix or ".mp4"
    video_path = UPLOADS_DIR / f"{job_id}{ext}"

    with open(video_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    # Calculate cost in minutes (rounded up)
    video_duration_secs = get_video_duration(str(video_path))
    credits_needed = math.ceil(video_duration_secs / 60)

    # Check and auto-reset monthly credits if due
    user_info = await run_in_threadpool(database.check_and_reset_if_needed, current_user["id"])
    credits_remaining = user_info.get("credits_remaining", 0)
    user_plan = user_info.get("plan") or "free"

    if credits_remaining < credits_needed:
        video_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=402,
            detail=(
                f"No tenés suficientes créditos. "
                f"Este video requiere {credits_needed} crédito{'s' if credits_needed != 1 else ''} "
                f"y tenés {credits_remaining} restantes este mes."
            )
        )

    # Deduct credits upfront — refunded on error
    await run_in_threadpool(database.deduct_credits, current_user["id"], credits_needed)

    user_id = current_user["id"]
    expiry_days = PLAN_EXPIRY_DAYS.get(user_plan, 3)
    add_watermark = (user_plan == "free")

    jobs[job_id] = {"status": "queued", "clips": [], "error": None, "add_watermark": add_watermark}

    await run_in_threadpool(
        database.create_job, job_id, user_id, file.filename or "video",
        credits_needed, expiry_days
    )

    _executor.submit(
        run_processing, job_id, str(video_path), api_key, openai_api_key,
        duration_min, duration_max, num_clips, custom_prompt,
        user_id, add_watermark, credits_needed
    )

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    # Active job in memory — return it directly
    if job_id in jobs:
        data = dict(jobs[job_id])
        for clip in data.get("clips", []):
            if "url" not in clip:
                clip["url"] = f"/clips/{job_id}/{clip['filename']}"
        return data

    # Fallback: look up in SQLite (e.g. after server restart)
    job = await run_in_threadpool(database.get_job_with_clips, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    clips = []
    for c in job.get("clips", []):
        clip_url = storage.get_presigned_url(c["r2_key"]) if c.get("r2_key") else ""
        if not clip_url:
            clip_url = f"/clips/{job_id}/{c['filename']}"
        thumb_name = c["filename"].replace(".mp4", ".jpg")
        thumb_r2_key = c["r2_key"].replace(".mp4", ".jpg") if c.get("r2_key") else ""
        thumb_url = storage.get_presigned_url(thumb_r2_key) if thumb_r2_key else ""
        if not thumb_url:
            thumb_url = f"/clips/{job_id}/{thumb_name}"
        clips.append({
            "filename": c["filename"],
            "url": clip_url,
            "thumb_url": thumb_url,
            "start": c["start_sec"],
            "end": c["end_sec"],
            "score": c["score"],
            "description": c["description"],
        })

    return {
        "status": job["status"],
        "clips": clips,
        "error": job.get("error"),
    }


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
    add_watermark = jobs[job_id].get("add_watermark", False)
    await run_in_threadpool(cut_clip, original_video, new_start, new_end, out_path, add_watermark)

    clip["start"] = new_start
    clip["end"] = new_end

    return {"start": new_start, "end": new_end, "filename": clip_filename}


@app.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "avatar_url": current_user["avatar_url"],
    }


@app.get("/api/me/history")
async def get_history(current_user: dict = Depends(get_current_user)):
    jobs_from_db = await run_in_threadpool(database.get_user_history, current_user["id"])
    result = []
    for job in jobs_from_db:
        clips = []
        for c in job.get("clips", []):
            clip_url = storage.get_presigned_url(c["r2_key"]) if c.get("r2_key") else ""
            if not clip_url:
                clip_url = f"/clips/{job['id']}/{c['filename']}"
            thumb_name = c["filename"].replace(".mp4", ".jpg")
            thumb_r2_key = c["r2_key"].replace(".mp4", ".jpg") if c.get("r2_key") else ""
            thumb_url = storage.get_presigned_url(thumb_r2_key) if thumb_r2_key else ""
            if not thumb_url:
                thumb_url = f"/clips/{job['id']}/{thumb_name}"
            clips.append({
                "filename": c["filename"],
                "url": clip_url,
                "thumb_url": thumb_url,
                "start": c["start_sec"],
                "end": c["end_sec"],
                "score": c["score"],
                "description": c["description"],
            })
        result.append({
            "job_id": job["id"],
            "original_filename": job["original_filename"],
            "created_at": job["created_at"],
            "expires_at": job["expires_at"],
            "clips": clips,
        })
    return result


@app.get("/api/me/credits")
async def get_credits(current_user: dict = Depends(get_current_user)):
    """Return current plan and credits remaining this month."""
    data = await run_in_threadpool(database.get_user_plan_credits, current_user["id"])
    reset_date = data.get("credits_reset_date")
    if reset_date and not isinstance(reset_date, str):
        reset_date = reset_date.isoformat()
    return {
        "plan": data.get("plan", "free"),
        "credits_remaining": data.get("credits_remaining", 0),
        "credits_total": data.get("credits_total", PLAN_CREDITS.get(data.get("plan", "free"), 30)),
        "credits_reset_date": reset_date,
    }


@app.get("/api/upload/quote")
async def quote_video(duration_seconds: float, current_user: dict = Depends(get_current_user)):
    """Return how many credits this video costs and whether the user can afford it."""
    credits_needed = math.ceil(duration_seconds / 60)
    data = await run_in_threadpool(database.get_user_plan_credits, current_user["id"])
    plan = data.get("plan", "free")
    credits_remaining = data.get("credits_remaining", 0)
    credits_total = data.get("credits_total", PLAN_CREDITS.get(plan, 30))

    return {
        "duration_seconds": duration_seconds,
        "credits_needed": credits_needed,
        "plan": plan,
        "credits_remaining": credits_remaining,
        "credits_total": credits_total,
        "can_afford": credits_remaining >= credits_needed,
    }


@app.post("/api/stripe/checkout")
async def create_checkout(body: dict, current_user: dict = Depends(get_current_user)):
    """Placeholder — Stripe subscription integration coming soon."""
    raise HTTPException(status_code=501, detail="Pagos por suscripción próximamente.")


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """Placeholder — Stripe webhook integration coming soon."""
    return {"ok": True}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "gemini_key_configured": bool(os.getenv("GEMINI_API_KEY")),
        "firebase_configured": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")),
        "r2_configured": storage.is_configured(),
    }


# Serve frontend last so API routes take priority
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
