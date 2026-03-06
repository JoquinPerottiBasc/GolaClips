def build_short_pass_prompt(existing_moments: list[dict], video_duration: float) -> str:
    """Prompt for the second pass: find short clips in gaps left by pass 1."""
    covered = "\n".join(
        f"- {m['start_sec']}s to {m['end_sec']}s" for m in existing_moments
    )
    return f"""You are analyzing an action sports video recorded with a GoPro or action camera.

A first analysis already found these clips — do NOT return them or anything overlapping:
{covered}

Your job: find SHORT moments (5 to 30 seconds) anywhere in the video that were NOT covered above.
Be generous — include anything briefly interesting, funny, or worth watching that was missed.

Return ONLY a raw JSON array, nothing else:
[
  {{
    "start_sec": 0.0,
    "end_sec": 0.0,
    "score": 0,
    "description": "description in English"
  }}
]

Rules:
- Only return clips that do NOT overlap with the existing clips listed above
- Each clip between 5 and 30 seconds
- No overlapping clips with each other
- Sorted by start_sec
- Score 1-10
- If nothing new is found, return an empty array: []
"""


def build_detect_moments_prompt(
    duration_min: int,
    duration_max: int,
    num_clips: str,
    custom_prompt: str,
) -> str:
    actual_max = duration_max + 10

    if num_clips != "auto":
        n = int(num_clips)
        count_rule = f"- Return exactly {n} clips (or fewer only if there genuinely aren't enough)"
    else:
        count_rule = "- No limit on number of clips — find everything worth watching"

    custom_section = ""
    if custom_prompt and custom_prompt.strip():
        custom_section = f"\nAlso prioritize: {custom_prompt.strip()}\n"

    return f"""You are analyzing an action sports video recorded with a GoPro or action camera.
{custom_section}
Your job is to find every moment worth watching. Be extremely generous — when in doubt, include it. A false positive is always better than a missed highlight.

Look for anything compelling, including:
- Action: jumps, tricks, crashes, falls, near-misses, high speed sections
- Funny or unexpected: mistakes, reactions, surprising situations
- Beautiful: stunning landscapes, dramatic scenery, impressive locations
- Atmosphere: golden hour light, interesting terrain, unique perspectives
- Audio: engine roars, impact sounds, rider reactions, anything that adds energy
- Your own judgment: anything you personally find impressive, beautiful or entertaining

Return ONLY a raw JSON array, no markdown, no explanation, nothing else:
[
  {{
    "start_sec": 0.0,
    "end_sec": 0.0,
    "score": 0,
    "description": "description in English"
  }}
]

Rules:
{count_rule}
- Each clip between 5 and {actual_max} seconds
- No overlapping clips
- Sorted by start_sec
- Score 1-10
- Start each clip slightly before the action, end slightly after
"""
