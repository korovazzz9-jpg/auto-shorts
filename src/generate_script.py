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
Write in English, conversational, punchy, no filler. Voiceover length should be 15-25 seconds
(about 40-65 words) — short enough that viewers rewatch it, which the algorithm rewards.

Structure, in order:
1. Hook: the first 3-5 words must be the most shocking or surprising part of the fact itself,
   not a setup. No "did you know" or "here's a fact" — open mid-thought, like you're cutting
   into the most interesting part of a conversation already in progress.
2. The fact, delivered fast, no filler words, no repeating the hook.
3. One unexpected twist or payoff line.
4. A one-line call to action blended naturally into the last sentence, e.g. asking viewers to
   comment whether they knew this, or to follow for more. Keep it short and not salesy — one
   clause, not a separate begging sentence.

No intros like "today I'll tell you about"."""


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
                "and write a script for it. Also break the script into 4-6 short visual beats "
                "(for fast cuts, roughly one every 4-5 seconds) and for each one write a short "
                "stock-footage search query (2-4 words, concrete, visual, in English, the kind "
                "you'd type into a stock video site search box, matching what's being said at "
                "that point).\n\n"
                "SEO requirements:\n"
                "- title: include a specific keyword phrase someone would actually type into "
                "YouTube search when looking for this kind of content (e.g. 'ocean facts', "
                "'space facts you didn't know', 'how X works') naturally woven into a catchy "
                "title under 60 characters — not just a vague hook with no searchable terms.\n"
                "- tags: 10-15 specific YouTube search tags, mixing broad ones (e.g. 'facts', "
                "'did you know', '" + topic + "') with specific long-tail ones tied to the exact "
                "fact (e.g. the specific phenomenon, place, or thing named in the script).\n"
                "- hashtags: 3-5 hashtags (lowercase, no spaces, with # prefix) to put in the "
                "description, mixing one broad discovery hashtag (#shorts, #facts) with 2-4 "
                "specific ones tied to the topic and fact.\n\n"
                "Respond strictly in JSON, no markdown wrapper: "
                '{"title": "short catchy SEO title under 60 characters", '
                '"script": "voiceover script text", '
                '"tags": ["tag1", "tag2", ...], '
                '"hashtags": ["#tag1", "#tag2", ...], '
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
