"""
Análisis de video con Google Gemini (SDK google-genai).

Flujo:
1. Subir el video a la Files API de Gemini
2. Esperar a que Gemini lo procese
3. Enviar prompt pidiendo momentos emocionantes en JSON estructurado
4. Parsear y validar la respuesta
"""

import re
import json
import time
import mimetypes

from google import genai
from google.genai import types

from prompts import build_detect_moments_prompt

GEMINI_MODEL = "gemini-3.1-pro-preview"


def _upload_and_wait(client: genai.Client, video_path: str, status_callback) -> types.File:
    """Sube el video y espera a que Gemini lo tenga listo."""
    mime = mimetypes.guess_type(video_path)[0] or "video/mp4"

    status_callback("uploading_to_gemini")
    video_file = client.files.upload(
        file=video_path,
        config=types.UploadFileConfig(mime_type=mime),
    )

    status_callback("gemini_processing")
    max_wait = 600
    elapsed = 0
    poll_interval = 5

    while video_file.state.name == "PROCESSING":
        if elapsed >= max_wait:
            raise TimeoutError("Gemini tardó demasiado en procesar el video")
        time.sleep(poll_interval)
        elapsed += poll_interval
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"Gemini no pudo procesar el video: {video_file.state.name}")

    return video_file


def _parse_moments(text: str) -> list[dict]:
    """Extrae el JSON de la respuesta, tolerando markdown y texto extra."""
    # Strip markdown code fences
    clean = re.sub(r'```(?:json)?\s*', '', text).strip()
    clean = re.sub(r'```\s*$', '', clean).strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Greedy match to capture the full array
    match = re.search(r'\[[\s\S]*\]', clean)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No se pudo parsear la respuesta de Gemini:\n{text[:500]}")


def _validate_moments(moments: list[dict], video_duration: float, max_clips: int) -> list[dict]:
    """Filtra y corrige momentos inválidos."""
    valid = []
    for m in moments:
        start = float(m.get("start_sec", 0))
        end = float(m.get("end_sec", 0))
        desc = str(m.get("description", "Momento emocionante"))

        score = max(1, min(10, int(m.get("score", 5))))

        start = max(0.0, start)
        end = min(video_duration, end)
        if end <= start + 1:
            continue

        valid.append({"start_sec": round(start, 1), "end_sec": round(end, 1), "description": desc, "score": score})

    return valid[:max_clips]


def _merge_moments(pass1: list[dict], pass2: list[dict]) -> list[dict]:
    """Add pass2 moments that don't overlap with any pass1 clip."""
    merged = list(pass1)
    for m in pass2:
        overlaps = any(
            m["start_sec"] < ex["end_sec"] and ex["start_sec"] < m["end_sec"]
            for ex in pass1
        )
        if not overlaps:
            merged.append(m)
    return sorted(merged, key=lambda x: x["start_sec"])


def analyze_video(
    video_path: str,
    video_duration: float,
    api_key: str,
    status_callback,
    duration_min: int = 30,
    duration_max: int = 60,
    num_clips: str = "auto",
    custom_prompt: str = "",
) -> list[dict]:
    """
    Analiza el video con Gemini y retorna los momentos emocionantes.

    Returns:
        Lista de dicts: [{"start_sec": float, "end_sec": float, "description": str}]
    """
    max_clips = 20 if num_clips == "auto" else int(num_clips)
    prompt = build_detect_moments_prompt(duration_min, duration_max, num_clips, custom_prompt)

    client = genai.Client(api_key=api_key)
    video_file = _upload_and_wait(client, video_path, status_callback)

    try:
        # Pass 1: find all clips
        status_callback("gemini_analyzing")
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[video_file, prompt],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192,
            ),
        )
        moments = _validate_moments(_parse_moments(response.text), video_duration, max_clips)
        print(f"[pass1] Found: {len(moments)} clips")

        return moments

    finally:
        try:
            client.files.delete(name=video_file.name)
        except Exception:
            pass
