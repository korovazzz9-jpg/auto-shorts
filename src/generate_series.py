"""Генерирует 3 связанных скрипта для недельной серии (Part 1/2/3) за один вызов Claude."""
import json
import os

from anthropic import Anthropic

from config import CFG
from generate_script import BASE_SYSTEM_PROMPT, HOOK_TEMPLATES, TOPICS_POOL, BANNED_TOPICS, extract_first_json, _title_instruction_narrative
from recent_titles import add_title_to_cache, add_topic_to_cache, get_recent_titles
from topic_stats import get_topic_avg_views
import random


# Для серий предпочитаем богатые темы с историей/наукой
SERIES_TOPICS = [
    "ancient history", "archaeological discoveries", "ancient civilizations",
    "shipwrecks and lost treasures", "historical mysteries",
    "the human body", "the animal kingdom", "the ocean", "space",
    "evolution", "natural wonders",
]

_WINNER_MIN_VIEWS = 100  # ниже — просмотры ещё не накопились, «победитель» случаен


def _winner_topic_last_week() -> str | None:
    """Тема лучшего Short'а за 7 дней (2026-07-05): серия «копает глубже» то, что аудитория
    УЖЕ подтвердила просмотрами, вместо взвешенной лотереи. None при любой проблеме/нехватке
    данных — вызывающий код падает на старый взвешенный рандом."""
    try:
        import datetime as dt
        import re
        from youtube_auth import get_client
        yt = get_client()
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        resp = yt.playlistItems().list(part="snippet", playlistId=uploads, maxResults=50).execute()
        ids = [i["snippet"]["resourceId"]["videoId"] for i in resp.get("items", [])]
        if not ids:
            return None
        vids = yt.videos().list(part="snippet,statistics", id=",".join(ids[:50])).execute()
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
        best, best_views = None, _WINNER_MIN_VIEWS - 1
        for v in vids.get("items", []):
            if v["snippet"]["publishedAt"] < cutoff:
                continue
            tags = v["snippet"].get("tags", [])
            if any(t.startswith("series-part-") for t in tags):
                continue  # прошлые серии не считаем — иначе серия зациклится на своей же теме
            topic = next((re.sub(r"^topic-", "", t).replace("_", " ")
                          for t in tags if t.startswith("topic-")), None)
            views = int(v["statistics"].get("viewCount", 0))
            if topic and views > best_views:
                best, best_views = topic, views
        return best
    except Exception:
        return None


def _pick_series_topic() -> str:
    # Победитель недели (2026-07-05) — если его тема подходит для серии, берём её.
    winner = _winner_topic_last_week()
    if winner in SERIES_TOPICS:
        print(f"  Series topic = победитель недели: {winner}")
        return winner

    try:
        # Только темы из SERIES_TOPICS — иначе overall_avg ниже (вес тем БЕЗ данных) считался
        # бы вместе с мусорными topic-тегами: темами самих серий и легаси-темами вне пула.
        avg_views = get_topic_avg_views(set(SERIES_TOPICS))
    except Exception:
        avg_views = {}
    overall_avg = sum(avg_views.values()) / len(avg_views) if avg_views else 100
    weights = [max(avg_views.get(t, overall_avg), 1.0) for t in SERIES_TOPICS]
    return random.choices(SERIES_TOPICS, weights=weights, k=1)[0]


SERIES_LENGTH_INSTRUCTION = (
    "Each part's voiceover MUST be 30-40 seconds (85-110 words). "
    "Count words before responding — under 85 words is too short."
)

# Клиффхэнгер (2026-07-04): вместо генерик «follow for Part 2» — конкретный тизер
# содержания следующей части (curiosity gap про реальную деталь), потом follow-CTA.
SERIES_CTA = {
    1: "end with a ONE-sentence cliffhanger teaser naming a SPECIFIC detail Part 2 will "
       "reveal (a real curiosity gap about the story, e.g. 'Part 2: why all 30 of them "
       "vanished overnight'), then 'Follow so you don't miss Part 2'",
    2: "end with a ONE-sentence cliffhanger teaser naming a SPECIFIC detail Part 3 will "
       "reveal, then 'Follow for the conclusion in Part 3'",
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
        f"- {_title_instruction_narrative()} — append ' | Part 1', ' | Part 2', ' | Part 3' to each title\n"
        f"- hook_text: a SHORT on-screen hook (3-6 words) for that part, a DIFFERENT angle from "
        "the spoken first sentence (eye and ear give two separate hooks in the first 2 seconds) "
        f"and NOT a copy of the title. Punchy, in {CFG['script_language']}, no ending period.\n"
        f"- hook_template: which opening template that part's spoken hook uses — exactly one of "
        f"[{', '.join(HOOK_TEMPLATES)}] (use 'other' if none fits)\n"
        f"- tags: 6-9 YouTube search tags in {CFG['script_language']}\n"
        f"- hashtags: 3-5 hashtags in {CFG['script_language']} (with # prefix)\n"
        "- video_queries: 3-5 stock footage search queries in English\n"
        "- search_summary: ONE plain, keyword-dense sentence (max 20 words) stating that part's "
        "fact directly for YouTube SEARCH — opposite style from the hook (no info gap, name the "
        f"subject plainly). NOT spoken, NOT shown on screen. In {CFG['script_language']}.\n"
        f"- comment_question: ONE provocative question about that part's specific fact, in "
        f"{CFG['script_language']}, for the pinned comment — must reference the concrete "
        "subject, make viewers argue or confess, NOT a generic 'did you know?'. Max 15 words.\n"
        f"- source_note: origin of that part's fact (institution/journal + year), max 8 words, "
        f"in {CFG['script_language']}, no URL. ONLY if genuinely known; else \"\".\n\n"
        "Respond strictly in JSON:\n"
        '{"topic": "topic name", '
        '"part1": {"title": "...", "hook_text": "...", "hook_template": "...", "script": "...", "search_summary": "...", "comment_question": "...", "source_note": "...", "tags": [], "hashtags": [], "video_queries": []}, '
        '"part2": {"title": "...", "hook_text": "...", "hook_template": "...", "script": "...", "search_summary": "...", "comment_question": "...", "source_note": "...", "tags": [], "hashtags": [], "video_queries": []}, '
        '"part3": {"title": "...", "hook_text": "...", "hook_template": "...", "script": "...", "search_summary": "...", "comment_question": "...", "source_note": "...", "tags": [], "hashtags": [], "video_queries": []}}'
    )

    # 3-частный JSON — самый большой пейлоад пайплайна, иногда модель возвращает битый
    # JSON (пропущенная запятая/кавычка в тексте). Ретраим парсинг, иначе весь Part 1
    # падает → series_state не сохраняется → Part 2/3 недели тоже не выходят.
    data = None
    last_err = None
    for attempt in range(3):
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
        try:
            # extract_first_json (2026-07-13): модель изредка отдаёт два JSON подряд —
            # старый срез до ПОСЛЕДНЕЙ "}" падал «Extra data» на всех ретраях.
            candidate = extract_first_json(raw)
            # Структуру проверяем ЗДЕСЬ же: валидный JSON без part2/title раньше падал
            # KeyError уже ПОСЛЕ цикла ретраев — серия недели терялась без второй попытки.
            if "topic" not in candidate:
                raise ValueError("в JSON нет поля topic")
            for pk in ("part1", "part2", "part3"):
                p = candidate.get(pk)
                if not isinstance(p, dict) or not p.get("title") or not p.get("script"):
                    raise ValueError(f"{pk} отсутствует или неполный (нет title/script)")
            data = candidate
            break
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f"  Series JSON parse/structure failed (attempt {attempt + 1}/3): {e}; retrying...")
    if data is None:
        raise RuntimeError(f"Series JSON невалиден после 3 попыток: {last_err}")

    # Добавляем метаданные
    for part_key in ("part1", "part2", "part3"):
        part_num = int(part_key[-1])
        part = data[part_key]
        part["topic"] = data["topic"]
        part["part"] = part_num
        part["total_parts"] = 3
        part["hashtag_position"] = "end"
        tags = part.get("tags")
        if not isinstance(tags, list):  # модель изредка отдаёт строку — не конкатенируется
            tags = []
        part["tags"] = tags + [
            f"topic-{data['topic'].replace(' ', '_')}",
            f"series-part-{part_num}",
        ]
        # #2/#4 хук-шаблон + двойной хук (та же логика, что в generate_script).
        ht = str(part.get("hook_template", "")).strip().lower()
        part["hook_template"] = ht if ht in HOOK_TEMPLATES else "other"
        if not str(part.get("hook_text", "")).strip():
            part["hook_text"] = part["title"]
        add_title_to_cache(part["title"])

    add_topic_to_cache(data["topic"])
    return data


if __name__ == "__main__":
    result = generate_series()
    print(json.dumps(result, ensure_ascii=False, indent=2))
