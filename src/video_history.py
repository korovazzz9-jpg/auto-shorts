"""Плоский лог полной истории видео (2026-07-06) — flat JSON, НЕ SQLite: читается git diff'ом,
не нужна отдельная БД. Дополняет агрегаты (hook_stats/dropoff_stats/topic_stats), которые
теряют гранулярность по отдельному видео — тут хранится КАЖДОЕ видео целиком (метаданные
генерации + позже производительность), чтобы искать пересечения (тема × хук × тон × длина),
которые плоские средние поймать не могут.

Две фазы записи:
1. record_publish() — publish.py вызывает сразу после успешной публикации: метаданные
   генерации (тема, хук-шаблон, опенер, тон, длина, было ли niche-styled/-recreated/topical).
2. enrich_with_performance() — weekly_report.py вызывает раз в неделю, дозаполняет
   views/retention_pct для записей без метрик (Analytics отдаёт данные с лагом ~48ч,
   поэтому у записи первую неделю их не будет).

Файл коммитится тем же persist-шагом, что queue_<channel>.json (daily.yml/daily-es.yml).
"""
import json
import os
from datetime import datetime, timezone

HISTORY_MAX = 500  # ~4 месяца при 4 видео/день — держим файл разумного размера для git diff


def _path(channel: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", f"video_history_{channel}.json")


def _load(channel: str) -> list[dict]:
    try:
        with open(_path(channel), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(channel: str, history: list[dict]) -> None:
    with open(_path(channel), "w", encoding="utf-8") as f:
        json.dump(history[-HISTORY_MAX:], f, ensure_ascii=False, indent=2)


def record_publish(channel: str, video_id: str, **fields) -> None:
    """Пишет запись сразу после публикации. fields — любые метаданные генерации, например
    topic/hook_template/title_opener/emotional_tone/title_variant/has_loop/niche_styled/
    niche_recreated/topical/length_seconds/format. Не бросает исключения наружу — вызывающий
    код (publish.py) уже обернул это в try/except, но дублируем на всякий случай здесь же
    не нужно: логирование истории не должно быть точкой отказа публикации."""
    history = _load(channel)
    entry = {"video_id": video_id, "published_at": datetime.now(timezone.utc).isoformat(), **fields}
    history.append(entry)
    _save(channel, history)


def enrich_with_performance(channel: str, stats_by_id: dict[str, dict]) -> int:
    """Дозаполняет views/retention_pct для записей БЕЗ них (не трогает уже заполненные —
    метрики через неделю-две стабилизируются, повторный overwrite не нужен). stats_by_id —
    {video_id: {"views":..., "pct":...}}. Возвращает число обновлённых записей (для лога
    в weekly_report.py)."""
    history = _load(channel)
    updated = 0
    for entry in history:
        if entry.get("views") is not None:
            continue
        stats = stats_by_id.get(entry["video_id"])
        if not stats:
            continue
        entry["views"] = stats.get("views")
        entry["retention_pct"] = stats.get("pct")
        updated += 1
    if updated:
        _save(channel, history)
    return updated
