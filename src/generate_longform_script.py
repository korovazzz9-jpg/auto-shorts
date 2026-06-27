"""Генерирует сценарий для длинного (3-4 мин) видео-компиляции из нескольких фактов —
открывает второй путь к монетизации (1000 подписчиков + 4000 часов обычных просмотров),
независимый от порога просмотров Shorts."""
import json
import os
import random

from anthropic import Anthropic

from config import CFG
from generate_script import TOPICS_POOL as THEMES
from recent_titles import get_recent_titles

SYSTEM_PROMPT = """You are a scriptwriter for {channel}, a YouTube channel about mind-blowing,
misconception-busting facts. Write the ENTIRE script in {language}. Write a long-form compilation
video script: 5 distinct facts on one theme, each with its own hook-fact-twist mini-arc (like a
chapter), stitched into one continuous narration with short transitions between facts ("But here's
where it gets stranger...", "Speaking of things that don't add up...", etc.) Total length
3.5-4.5 minutes (550-700 words).

Each individual fact must overturn a common intuitive assumption, same bar as the channel's
Shorts: not just an interesting detail, but something that breaks what people assume is true.
Avoid abstract/technical facts requiring specialist background (quantum mechanics, advanced math).

End with a stronger call to action than usual: ask viewers to subscribe for daily fact videos,
and comment which fact surprised them most.

Conversational, energetic, no filler, no "today I'll tell you about" intros.""".format(
    channel=CFG["channel_name"],
    language=CFG["script_language"],
)


def generate_longform_script() -> dict:
    theme = random.choice(THEMES)
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)

    try:
        past_titles = get_recent_titles()
    except Exception:
        past_titles = []

    avoid_block = ""
    if past_titles:
        avoid_block = (
            "Already-published video titles on this channel — don't reuse these specific facts:\n"
            + "\n".join(f"- {t}" for t in past_titles) + "\n\n"
        )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                avoid_block +
                f"Theme: {theme}. Write the 5-fact compilation script. Break it into 15-20 visual "
                "beats (roughly one every 12-15 seconds) and for each one write a short "
                "stock-footage search query (2-4 words, concrete, visual, in English).\n\n"
                "Requirements:\n"
                f"- title: a compelling compilation title in {CFG['script_language']} under 70 "
                "characters (e.g. '5 Facts That Will Change How You See [Theme]'), no "
                "'| topic facts' suffix.\n"
                f"- tags: 10-15 specific YouTube search tags in {CFG['script_language']}.\n"
                f"- hashtags: 3-5 hashtags in {CFG['script_language']} (lowercase, with # prefix).\n\n"
                "Respond strictly in JSON, no markdown wrapper: "
                '{"title": "title text", '
                '"script": "full voiceover script text", '
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
    data["theme"] = theme
    return data


if __name__ == "__main__":
    print(json.dumps(generate_longform_script(), ensure_ascii=False, indent=2))
