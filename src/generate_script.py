"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

from anthropic import Anthropic

from recent_titles import get_recent_titles

TOPICS_POOL = [
    "space", "the ocean", "ancient history", "the human body",
    "the animal kingdom", "psychology", "future technology", "bizarre records",
    "volcanoes and earthquakes", "ancient civilizations",
    "cryptography", "evolution", "extreme weather", "archaeological discoveries",
]

BASE_SYSTEM_PROMPT = """You are a scriptwriter for short fact videos on YouTube Shorts (channel: 60SecFacts).
Write in English, conversational, punchy, no filler.

The fact MUST overturn a common intuitive assumption — something most people would confidently
believe is true (or would never think to question) until this fact breaks it. Not just "an
interesting detail about X," but "X is the opposite of what you'd assume." Body-related, historical,
or sensory facts with a clear before/after contrast in understanding work best. Avoid abstract or
purely technical facts that require specialist background to feel surprising (e.g. quantum
mechanics, relativity, advanced math) — the shock has to land for a general audience in one watch.

Structure, in order:
1. Hook: the first 3-5 words must be the most shocking or surprising part of the fact itself,
   not a setup. No "did you know" or "here's a fact" — open mid-thought, like you're cutting
   into the most interesting part of a conversation already in progress.
2. The fact, delivered fast, no filler words, no repeating the hook.
3. One unexpected twist or payoff line that makes the misconception's collapse explicit (e.g.
   "X thought... turns out...", "It's not Y, it's actually Z").
4. A one-line call to action blended naturally into the last sentence, e.g. asking viewers to
   comment whether they knew this, or to follow for more. Keep it short and not salesy — one
   clause, not a separate begging sentence.

No intros like "today I'll tell you about"."""

# A/B-тест двух форматов после того, как короткий SEO-формат показал заметно меньше
# просмотров, чем исходный длинный нарративный стиль на первых видео канала.
VARIANTS = {
    "long_narrative": {
        "length_instruction": (
            "Voiceover length should be 30-40 seconds (about 80-110 words) — long enough to "
            "build a real narrative arc (setup, escalation, twist), not just a rapid-fire fact."
        ),
        "title_instruction": (
            "title: a punchy narrative hook, under 60 characters. Do NOT append a '| topic facts' "
            "style keyword suffix — it should read like a real headline, not a listicle."
        ),
        "hashtag_position": "end",
        "tag_count": "6-9",
    },
    "short_seo": {
        "length_instruction": (
            "Voiceover length should be 15-25 seconds (about 40-65 words) — short enough that "
            "viewers rewatch it."
        ),
        "title_instruction": (
            "title: include a specific keyword phrase someone would actually type into YouTube "
            "search (e.g. 'ocean facts', 'space facts you didn't know') naturally woven into a "
            "catchy title under 60 characters."
        ),
        "hashtag_position": "start",
        "tag_count": "10-15",
    },
}


def generate_script() -> dict:
    topic = random.choice(TOPICS_POOL)
    variant_name = random.choice(list(VARIANTS.keys()))
    variant = VARIANTS[variant_name]
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        past_titles = get_recent_titles()
    except Exception:
        past_titles = []

    avoid_block = ""
    if past_titles:
        avoid_block = (
            "Already-published video titles on this channel — pick a DIFFERENT specific fact, "
            "not a variation of any of these:\n" + "\n".join(f"- {t}" for t in past_titles) + "\n\n"
        )

    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + variant["length_instruction"]

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                avoid_block +
                f"Topic: {topic}. Come up with one specific, lesser-known fact on this topic "
                "and write a script for it. Also break the script into visual beats (roughly one "
                "every 4-5 seconds of the script) and for each one write a short stock-footage "
                "search query (2-4 words, concrete, visual, in English, the kind you'd type into "
                "a stock video site search box, matching what's being said at that point).\n\n"
                "Requirements:\n"
                f"- {variant['title_instruction']}\n"
                f"- tags: {variant['tag_count']} specific YouTube search tags, mixing broad ones "
                "(e.g. 'facts', 'did you know', '" + topic + "') with specific long-tail ones tied "
                "to the exact fact (e.g. the specific phenomenon, place, or thing named in the "
                "script).\n"
                "- hashtags: 3-5 hashtags (lowercase, no spaces, with # prefix), mixing one broad "
                "discovery hashtag (#shorts, #facts) with 2-4 specific ones tied to the topic and "
                "fact.\n\n"
                "Respond strictly in JSON, no markdown wrapper: "
                '{"title": "title text", '
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
    data["variant"] = variant_name
    data["hashtag_position"] = variant["hashtag_position"]
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
