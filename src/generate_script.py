"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

from anthropic import Anthropic

from config import CFG
from recent_titles import get_recent_titles
from topic_stats import get_topic_avg_views

TOPICS_POOL = [
    "space", "the ocean", "ancient history", "the human body",
    "the animal kingdom", "psychology", "future technology", "bizarre records",
    "volcanoes and earthquakes", "ancient civilizations",
    "cryptography", "evolution", "extreme weather", "archaeological discoveries",
]

MIN_TOPICS_WITH_DATA = 5  # не взвешивать, пока статистика не накопилась хотя бы по стольким темам


def _pick_topic() -> str:
    try:
        avg_views = get_topic_avg_views()
    except Exception:
        avg_views = {}

    if len(avg_views) < MIN_TOPICS_WITH_DATA:
        return random.choice(TOPICS_POOL)

    overall_avg = sum(avg_views.values()) / len(avg_views)
    # Темы без данных получают средний вес (чтобы не застревать на старых лидерах
    # и продолжать исследовать темы, которые ещё не пробовали).
    weights = [max(avg_views.get(t, overall_avg), 1.0) for t in TOPICS_POOL]
    return random.choices(TOPICS_POOL, weights=weights, k=1)[0]

BASE_SYSTEM_PROMPT = """You are a scriptwriter for short fact videos on YouTube Shorts (channel: {channel}).
Write the TITLE, SCRIPT and HASHTAGS in {language}, conversational, punchy, no filler. (Keep the
stock-footage search queries in English regardless — they are only used to search a stock video site.)

The fact MUST overturn a common intuitive assumption — something most people would confidently
believe is true (or would never think to question) until this fact breaks it. Not just "an
interesting detail about X," but "X is the opposite of what you'd assume." Body-related, historical,
or sensory facts with a clear before/after contrast in understanding work best. Avoid abstract or
purely technical facts that require specialist background to feel surprising (e.g. quantum
mechanics, relativity, advanced math) — the shock has to land for a general audience in one watch.

Structure, in order:
1. Hook: the first 3-5 words must be the most shocking or surprising part of the fact itself,
   not a setup. No "did you know" / "¿sabías que?" openers — open mid-thought, like you're cutting
   into the most interesting part of a conversation already in progress.
2. The fact, delivered fast, no filler words, no repeating the hook.
3. One unexpected twist or payoff line that makes the misconception's collapse explicit.
4. A one-line call to action blended naturally into the last sentence ({cta}). Keep it short and
   not salesy — one clause, not a separate begging sentence.

No "today I'll tell you about" style intros.""".format(
    channel=CFG["channel_name"],
    language=CFG["script_language"],
    cta=CFG["cta_instruction"],
)

# 30-45s is the sweet spot for YouTube's 2026 Shorts algorithm (absolute watch time, not
# just retention %) — shorter videos collapsed in reach even at high completion rates.
LENGTH_INSTRUCTION = (
    "Voiceover length should be 30-40 seconds (about 80-110 words) — long enough to build a "
    "real narrative arc (setup, escalation, twist), not just a rapid-fire fact."
)
TITLE_INSTRUCTION = (
    "title: a punchy narrative hook, under 60 characters. Do NOT append a '| topic facts' "
    "style keyword suffix — it should read like a real headline, not a listicle."
)


def generate_script() -> dict:
    topic = _pick_topic()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)

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

    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + LENGTH_INSTRUCTION

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
                f"- {TITLE_INSTRUCTION}\n"
                f"- tags: 6-9 specific YouTube search tags in {CFG['script_language']}, mixing "
                "broad ones (e.g. the channel's equivalent of 'facts'/'did you know') with specific "
                "long-tail ones tied to the exact fact (the specific phenomenon, place, or thing "
                "named in the script).\n"
                f"- hashtags: 3-5 hashtags in {CFG['script_language']} (lowercase, no spaces, with "
                "# prefix), mixing one broad discovery hashtag (#shorts and the language's "
                "equivalent of #facts) with 2-4 specific ones tied to the topic and fact.\n\n"
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
    data["hashtag_position"] = "end"
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
