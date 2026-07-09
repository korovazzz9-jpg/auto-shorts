"""Генератор «random facts» сценария для вьетнамского TikTok-формата.

Отличается от generate_script (один глубокий факт, EN-структура): здесь 3-4 коротких
независимых факта подряд поверх залипательного (satisfying) фона. Под нативный формат
VN-ленты и сигналы алгоритма TikTok 2026 (watch-time/completion ~70%, re-watch loops,
глубина комментов). Фон НЕ тематический — берётся из fetch_satisfying_clips.

Структура: сильнейший факт в первые 3с → ещё 2-3 факта быстрым темпом → комментная
наживка последней фразой. Без хук-плашки и без петлевой фразы (визуальный loop делает
сам билдер, дублируя первый клип в конец)."""
import json
import os
import random

from anthropic import Anthropic

from config import CFG
from generate_script import TOPICS_POOL, _drop_corrupted, _parse_response

# Чуть больше фактов по желанию; 4 — золотая середина для ~30-40с при быстром темпе.
FACTS_PER_VIDEO = 4

# История прошлых VN-роликов (2026-07-06): VN генерится ЛОКАЛЬНО (test_local.py), канала
# для сверки нет — без памяти модель повторяла одни и те же факты (Клеопатра/пирамиды,
# осьминог с 3 сердцами, мёд в гробнице в 3 роликах подряд). Копим сюда, кормим как
# avoid-block. Файл в корне репо — переживает локальные прогоны.
_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "vi_facts_history.json")
_HISTORY_MAX = 40      # столько прошлых роликов помним
_AVOID_RECENT = 12     # столько последних показываем модели как «не повторять»


def _load_history() -> list[dict]:
    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_history(history: list[dict]) -> None:
    with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-_HISTORY_MAX:], f, ensure_ascii=False, indent=2)

SYSTEM_PROMPT = """You are a scriptwriter for {channel}, a Vietnamese TikTok channel of rapid-fire
mind-blowing facts shown over oddly-satisfying background footage. Write EVERYTHING in {language}.

Format: {n} SHORT, surprising, mostly-unrelated facts in a row ("random facts"), narrated as one
continuous voiceover. NOT one deep fact — a fast stream where each fact is a tiny self-contained
"wait, what?" moment. The viewer keeps watching to hear the next one.

Rules:
1. The FIRST fact is the strongest/weirdest — it must land in the first 3 seconds and stop the
   scroll. No intro, no "did you know", no warm-up. Open mid-shock.
2. Each fact: 1-2 short sentences max, with a concrete anchor (a number, place, or name) so it
   feels true. Each must overturn a common assumption, not just be trivia.
3. Fast, punchy pacing. No transitions longer than 2-3 words ("Còn nữa.", "Tiếp theo.").
4. Avoid abstract/technical facts needing specialist background (quantum physics, advanced math).
   Physics/quantum are off-limits as topics.
5. The LAST sentence is comment bait: provoke a reply (debate or self-recognition), e.g. ask which
   fact shocked them most, or make a confident claim people will rush to correct. This IS the last
   spoken line — no spoken "follow/like" CTA (the follow badge is shown on-screen).

Keep it tight — total spoken length ~30-40 seconds.""".format(
    channel=CFG["channel_name"],
    language=CFG["script_language"],
    n=FACTS_PER_VIDEO,
)


def _build_user_content(history: list[dict]) -> str:
    # Анти-повтор: показываем модели скрипты последних роликов и требуем ДРУГИЕ факты.
    avoid_block = ""
    recent = history[-_AVOID_RECENT:]
    if recent:
        past = "\n".join(f"- {h.get('title','')}: {h.get('script','')}" for h in recent)
        avoid_block = (
            "ALREADY-USED scripts on this channel (most recent). Do NOT reuse ANY of these facts "
            "or a paraphrase of them — pick completely different facts, and do NOT open the title "
            "with the same pattern as these:\n" + past + "\n\n"
        )
    return (
        avoid_block +
        f"Write a {FACTS_PER_VIDEO}-fact rapid-facts script. The facts can span different topics "
        f"(e.g. {', '.join(random.sample(TOPICS_POOL, 4))}) or share a loose theme — your choice, "
        "whichever gives the most surprising set. Do NOT write stock-footage queries: the background "
        "is generic satisfying footage, unrelated to the facts.\n\n"
        "Requirements:\n"
        f"- title: a punchy hook title in {CFG['script_language']}, under 60 characters. VARY the "
        "opening — do NOT start with 'Sự thật điên rồ mà bạn...' if recent titles above already did.\n"
        f"- thumb_text: 3-5 word thumbnail phrase in {CFG['script_language']} (the most intriguing "
        "idea), instantly readable.\n"
        f"- tags: 6-9 Vietnamese TikTok search tags (mix broad 'sự thật' type with specific ones).\n"
        f"- hashtags: 3-5 Vietnamese hashtags (lowercase, with #), include #suthat and a trending "
        "one like #xuhuong/#fyp, plus topic-specific ones. TikTok caps hashtags at 5 — never "
        "exceed 5. Do NOT include #shorts (that's YouTube).\n\n"
        "Respond strictly in JSON, no markdown wrapper: "
        '{"title": "...", "thumb_text": "...", '
        '"script": "the full continuous voiceover of all facts, ending with the comment-bait line", '
        '"tags": ["..."], "hashtags": ["#..."]}'
    )


def generate_rapid_facts() -> dict:
    history = _load_history()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    user_content = _build_user_content(history)

    # Ретрай битого JSON (2026-07-06): единственный генератор без него — реально упал на
    # «Expecting ',' delimiter». Тот же паттерн, что series/longform/generate_script.
    data, last_err = None, None
    for attempt in range(3):
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        try:
            candidate = _parse_response(message)
            if candidate.get("title") and candidate.get("script"):
                data = candidate
                break
            last_err = ValueError("нет title/script")
        except json.JSONDecodeError as e:
            last_err = e
        print(f"  Rapid-facts JSON parse failed (attempt {attempt + 1}/3): {last_err}; retrying...")
    if data is None:
        raise RuntimeError(f"Rapid-facts JSON невалиден после 3 попыток: {last_err}")

    # Фильтр битых хэштегов/тегов ДО любого дальнейшего использования (см. _drop_corrupted).
    if isinstance(data.get("hashtags"), list):
        data["hashtags"] = _drop_corrupted(data["hashtags"])
    if isinstance(data.get("tags"), list):
        data["tags"] = _drop_corrupted(data["tags"])

    # Совместимость с остальным пайплайном (build_video/test_local ждут эти поля).
    data["topic"] = "random facts"
    data["has_loop"] = False                 # петлевую фразу не дописываем; loop делает билдер визуально
    data["hashtag_position"] = "end"
    data.setdefault("video_queries", [])     # фон не тематический — берётся из fetch_satisfying_clips
    if not data.get("thumb_text", "").strip():
        data["thumb_text"] = " ".join(data["title"].split()[:4])

    # Запоминаем ролик, чтобы следующий не повторил его факты.
    history.append({"title": data["title"], "script": data["script"]})
    _save_history(history)
    return data


if __name__ == "__main__":
    print(json.dumps(generate_rapid_facts(), ensure_ascii=False, indent=2))
