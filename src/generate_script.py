"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

from anthropic import Anthropic

TOPICS_POOL = [
    "space", "the ocean", "ancient history", "the human body",
    "the animal kingdom", "psychology", "future technology", "bizarre records",
    "volcanoes and earthquakes", "ancient civilizations", "quantum physics",
    "cryptography", "evolution", "extreme weather", "archaeological discoveries",
]

SYSTEM_PROMPT = """You are a scriptwriter for short fact videos on YouTube Shorts (channel: 60SecFacts).
Write in English, conversational, punchy, no filler. Voiceover length should be 35-45 seconds
(about 90-120 words). Structure: a strong hook in the first sentence, the fact itself, an
unexpected twist or takeaway at the end. No intros like "today I'll tell you about"."""


def generate_script() -> dict:
    topic = random.choice(TOPICS_POOL)
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Topic: {topic}. Come up with one specific, lesser-known fact on this topic "
                "and write a script for it. Also break the script into 7-9 short visual beats "
                "(for fast cuts, roughly one every 4-5 seconds) and for each one write a short "
                "stock-footage search query (2-4 words, concrete, visual, in English, the kind "
                "you'd type into a stock video site search box, matching what's being said at "
                "that point). Respond strictly in JSON, no markdown wrapper: "
                '{"title": "short catchy title under 60 characters", '
                '"script": "voiceover script text", '
                '"tags": ["tag1", "tag2", ...], '
                '"video_queries": ["query1", "query2", ...]}'
            ),
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1])
    data["topic"] = topic
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
