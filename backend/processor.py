"""
Pipeline de procesamiento de video para GolaClips.

1. Obtener duración del video (ffprobe)
2. Analizar con Gemini para detectar momentos emocionantes (timestamps + descripción)
3. Cortar clips con ffmpeg según los timestamps de Gemini
"""

import os
import json
import subprocess
from pathlib import Path

from gemini_analyzer import analyze_video

CLIPS_DIR = Path(__file__).parent / "clips"


def get_video_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def compress_video_for_analysis(video_path: str, output_path: str):
    """Scale video down to 720p for faster Gemini upload and analysis."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", "scale=-2:360",
            "-c:v", "libx264", "-preset", "fast", "-crf", "28",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            output_path,
        ],
        capture_output=True,
        check=True,
    )


def cut_clip(video_path: str, start: float, end: float, out_path: str):
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ],
        capture_output=True,
        check=True,
    )


def process_video(
    job_id: str,
    video_path: str,
    api_key: str,
    status_callback,
    duration_min: int = 30,
    duration_max: int = 60,
    num_clips: str = "auto",
    custom_prompt: str = "",
    openai_api_key: str = "",
) -> list[dict]:
    """
    Pipeline completo de procesamiento.

    Returns:
        Lista de clips: [{"filename": str, "start": float, "end": float, "description": str}]
    """
    from translator import translate_descriptions_to_spanish

    out_dir = CLIPS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = get_video_duration(video_path)

    # Compress to 720p so Gemini receives a smaller file (faster upload + analysis).
    # Clips will still be cut from the original high-quality video.
    status_callback("compressing")
    compressed_path = str(Path(video_path).parent / f"{Path(video_path).stem}_compressed.mp4")
    compress_video_for_analysis(video_path, compressed_path)

    try:
        moments = analyze_video(
            compressed_path,
            duration,
            api_key,
            status_callback,
            duration_min=duration_min,
            duration_max=duration_max,
            num_clips=num_clips,
            custom_prompt=custom_prompt,
        )
    finally:
        try:
            os.unlink(compressed_path)
        except OSError:
            pass

    # Translate descriptions to Spanish
    if openai_api_key and moments:
        moments = translate_descriptions_to_spanish(moments, openai_api_key)

    # Sort chronologically so clip_01 is always the first in the video
    moments.sort(key=lambda m: m["start_sec"])

    status_callback("cutting_clips")
    clips = []
    for i, moment in enumerate(moments):
        filename = f"clip_{i + 1:02d}.mp4"
        out_path = str(out_dir / filename)

        cut_clip(video_path, moment["start_sec"], moment["end_sec"], out_path)

        clips.append({
            "filename": filename,
            "start": moment["start_sec"],
            "end": moment["end_sec"],
            "description": moment["description"],
            "score": moment.get("score", 5),
        })

    return clips
