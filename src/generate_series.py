"""Генерирует 3 связанных скрипта для недельной серии (Part 1/2/3) за один вызов Claude."""
import json
import os

from anthropic import Anthropic

from config import CFG
from generate_script import BASE_SYSTEM_PROMPT, TITLE_INSTRUCTION, TOPICS_POOL, BANNED_TOPICS
from recent_titles import add_title_to_cache, add_topic_to_cache, get_recent_titles
from topic_stats import get_topic_avg_views
import random


def _pick_series_topic() -> str:
    # Для серий предпочитаем богатые темы с историей/наукой
    SERIES_TOPICS = [
        "ancient history", "archaeological discoveries", "ancient civilizations",
        "shipwrecks and lost treasures", "historical mysteries",
        "the human body", "the animal kingdom", "the ocean", "space",
        "evolution", "natural wonders",
    ]
    try:
        avg_views = get_topic_avg_views()
    except Exception:
        avg_views = {}
    overall_avg = sum(avg_views.values()) / len(avg_views) if avg_views else 100
    weights = [max(avg_views.get(t, overall_avg), 1.0) for t in SERIES_TOPICS]
    return random.choices(SERIES_TOPICS, weights=weights, k=1)[0]


SERIES_LENGTH_INSTRUCTION = (
    "Each part's voiceover MUST be 30-40 seconds (85-110 words). "
    "Count words before responding — under 85 words is too short."
)

SERIES_CTA = {
    1: "end with 'Follow so you don't miss Part 2'",
    2: "end with 'Follow for the conclusion in Part 3'",
    3: "end with a satisfying payoff that rewards viewers who watched all 3 parts, "
       "then 'Follow for more series like this'",
}


def generate_series() -> dict:
    """Генерирует все 3 части серии. Возвращает dict с ключами part1/part2/part3 и topic."""
    topic = _pick_series_topic()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)

    try:
        past_titles = get_recent_titles()
    except Exception:
        past_titles = []

    avoid_block = ""
    if past_titles:
        avoid_block = (
            "Already-published titles — pick DIFFERENT facts:\n"
            + "\n".join(f"- {t}" for t in past_titles) + "\n\n"
        )

    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + SERIES_LENGTH_INSTRUCTION

    prompt = (
        avoid_block +
        f"Topic: {topic}.\n\n"
        "Create a 3-part YouTube Shorts series. Each part must be a standalone video that also "
        "works as part of a narrative arc across all 3 parts.\n\n"
        "Structure:\n"
        "- Part 1: Hook the viewer with the most surprising surface-level fact. "
        f"{SERIES_CTA[1]}.\n"
        "- Part 2: Go deeper — the mechanism, the why, the twist that most people miss. "
        f"{SERIES_CTA[2]}.\n"
        "- Part 3: The biggest payoff — the implication that changes how you see everything. "
        f"{SERIES_CTA[3]}.\n\n"
        "Requirements for EACH part:\n"
        f"- {TITLE_INSTRUCTION} — append ' | Part 1', ' | Part 2', ' | Part 3' to each title\n"
        f"- tags: 6-9 YouTube search tags in {CFG['script_language']}\n"
        f"- hashtags: 3-5 hashtags in {CFG['script_language']} (with # prefix)\n"
        "- video_queries: 3-5 stock footage search queries in English\n\n"
        "Respond strictly in JSON:\n"
        '{"topic": "topic name", '
        '"part1": {"title": "...", "script": "...", "tags": [], "hashtags": [], "video_queries": []}, '
        '"part2": {"title": "...", "script": "...", "tags": [], "hashtags": [], "video_queries": []}, '
        '"part3": {"title": "...", "script": "...", "tags": [], "hashtags": [], "video_queries": []}}'
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1])

    # Добавляем метаданные
    for part_key in ("part1", "part2", "part3"):
        part_num = int(part_key[-1])
        data[part_key]["topic"] = data["topic"]
        data[part_key]["part"] = part_num
        data[part_key]["total_parts"] = 3
        data[part_key]["hashtag_position"] = "end"
        data[part_key]["tags"] = data[part_key].get("tags", []) + [
            f"topic-{data['topic'].replace(' ', '_')}",
            f"series-part-{part_num}",
        ]
        add_title_to_cache(data[part_key]["title"])

    add_topic_to_cache(data["topic"])
    return data


if __name__ == "__main__":
    result = generate_series()
    print(json.dumps(result, ensure_ascii=False, indent=2))
