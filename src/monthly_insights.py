"""Месячный инсайт-репорт (2026-07-08): 1-го числа месяца скармливает Claude ПОЛНУЮ историю
видео из video_history_<channel>.json (не агрегаты — hook_stats/dropoff_stats/topic_stats
уже это делают на лету) и просит найти закономерности, которые плоские средние не ловят
(пересечения тема × хук × тон × длина и т.п.). Результат уходит в Telegram.

Zачем отдельно от weekly_report.py: там — узкие метрики по одному измерению за раз (только
hook, только topic, ...) на 50 последних видео. Тут — вся история разом (до HISTORY_MAX
записей из video_history.py), модель сама ищет пересечения, а не мы их вручную считаем.

Запуск: monthly-insights.yml, 1-е число месяца, оба канала.
"""
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from config import CFG
from notify import notify
from video_history import _load

load_dotenv()

MIN_ENTRIES_WITH_PERFORMANCE = 15  # меньше — рано искать закономерности, слишком шумно
MAX_ENTRIES = 300  # сколько последних (с метриками) отдаём модели — с запасом под лимит истории


def _entries_with_performance(channel: str) -> list[dict]:
    history = _load(channel)
    with_perf = [e for e in history if e.get("views") is not None]
    return with_perf[-MAX_ENTRIES:]


def _build_prompt(entries: list[dict]) -> str:
    # Урезаем до полей, реально нужных для поиска закономерностей — сам скрипт (script)
    # не нужен модели для этой задачи, только метаданные + метрики, экономит токены.
    compact = [
        {k: e.get(k) for k in (
            "title", "topic", "hook_template", "title_opener", "emotional_tone",
            "title_variant", "has_loop", "niche_styled", "niche_recreated", "topical",
            "length_seconds", "views", "retention_pct",
        )}
        for e in entries
    ]
    return (
        f"Here is the full publication history for a YouTube Shorts channel ({len(compact)} "
        "videos, each with generation metadata AND real performance):\n\n"
        + json.dumps(compact, ensure_ascii=False)
        + "\n\nFind patterns that a simple per-tag average would MISS — specifically "
        "INTERSECTIONS of 2-3 fields (e.g. 'topic X does great UNLESS paired with hook Y', "
        "'short length only helps for topic Z', 'niche_recreated videos underperform when "
        "topical=true'). Also flag anything surprising or counterintuitive. Do NOT just repeat "
        "single-field averages (those are already tracked elsewhere).\n\n"
        "Respond in Russian, as a Telegram message: 5-8 concrete, numbered insights, each "
        "1-2 sentences, citing the actual numbers/titles that support it. No preamble, no "
        "generic advice ('post consistently') — only patterns backed by THIS data. If the "
        "data is too thin for a genuine pattern, say so explicitly instead of inventing one. "
        "Keep the whole response under 3500 characters (Telegram limit)."
    )


def run(channel: str) -> None:
    entries = _entries_with_performance(channel)
    if len(entries) < MIN_ENTRIES_WITH_PERFORMANCE:
        print(f"  Только {len(entries)} видео с метриками (<{MIN_ENTRIES_WITH_PERFORMANCE}) — рано, пропускаем.")
        return

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": _build_prompt(entries)}],
    )
    insight_text = message.content[0].text.strip()
    print(insight_text)
    notify(f"🧠 [{CFG['channel_name']}] Месячные инсайты ({len(entries)} видео с данными):\n\n{insight_text}")


if __name__ == "__main__":
    from config import CHANNEL
    from notify import guard_main
    guard_main(f"monthly-insights {CHANNEL}", lambda: run(CHANNEL))
