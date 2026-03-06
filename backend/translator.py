import json
from openai import OpenAI


def translate_descriptions_to_spanish(clips: list[dict], api_key: str) -> list[dict]:
    """Translate clip descriptions to Spanish using OpenAI."""
    if not api_key or not clips:
        return clips

    descriptions = [c.get("description", "") for c in clips]
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": (
                    "Translate these action sports clip descriptions to Spanish. "
                    "Keep them short and exciting. "
                    "Return ONLY a JSON array of translated strings in the same order, no extra text:\n"
                    + json.dumps(descriptions)
                ),
            }
        ],
        temperature=0.3,
    )

    import re
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()
    raw = re.sub(r'```\s*$', '', raw).strip()
    translated = json.loads(raw)

    for i, clip in enumerate(clips):
        if i < len(translated):
            clip["description"] = translated[i]

    return clips
