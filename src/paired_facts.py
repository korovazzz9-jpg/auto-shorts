"""Video pairs / намеренные противоречия (2026-07-08): дёшево поднимает session watch time —
видео A формулирует опровержимый/дополняемый claim («Bananas are technically berries»), видео B
(через 1-10 дней) находит РЕАЛЬНОЕ противоречие/дополнение к нему и ссылается на A; A дозаписывается
ссылкой на B после публикации. Тот же принцип, что `longform_link.py` (read-modify-write JSON
state, коммитится persist-шагом воркфлоу), но между двумя Shorts.

Только для LIVE-генерации (мимо batch-очереди) — тот же паттерн, что «On this day»: очередь
генерится заранее и не знает, есть ли открытая пара на момент публикации.
"""
import json
import os
import time

PAIR_PROBABILITY = 0.15   # ЛЕГАСИ (2026-07-18): рандомный старт пар заменён расписанием Пн-Чт
                          # в прайм-слот (pipeline.py, CFG pair_slot_hour_utc) — не используется
MIN_AGE_HOURS = 18        # часть B не раньше чем через столько часов после A
MAX_AGE_DAYS = 10         # пары старше — считаем просроченными (тема остыла), не резолвим
MAX_OPEN_PAIRS = 20       # на всякий случай не даём файлу расти бесконечно при накоплении отказов


def _path(channel: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", f"paired_facts_{channel}.json")


def _load(channel: str) -> list[dict]:
    try:
        with open(_path(channel), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(channel: str, pairs: list[dict]) -> None:
    with open(_path(channel), "w", encoding="utf-8") as f:
        json.dump(pairs[-MAX_OPEN_PAIRS:], f, ensure_ascii=False, indent=2)


def find_pending_pair(channel: str) -> dict | None:
    """Самая старая ЕЩЁ ОТКРЫТАЯ пара, готовая на резолюцию (не младше MIN_AGE_HOURS, не
    старше MAX_AGE_DAYS — просроченные не резолвим, тема могла устареть/повториться)."""
    now = time.time()
    for p in _load(channel):
        if p.get("status") != "awaiting_b":
            continue
        age_h = (now - p.get("created_at", 0)) / 3600
        if MIN_AGE_HOURS <= age_h <= MAX_AGE_DAYS * 24:
            return p
    return None


def start_pair(channel: str, video_id: str, title: str, claim: str, topic: str) -> None:
    """Сохраняет новую незакрытую пару после публикации части A."""
    pairs = _load(channel)
    pairs.append({
        "id": f"{video_id}-{int(time.time())}",
        "topic": topic,
        "part_a_video_id": video_id,
        "part_a_title": title,
        "claim": claim,
        "part_b_video_id": None,
        "status": "awaiting_b",
        "created_at": time.time(),
    })
    _save(channel, pairs)


def resolve_pair(channel: str, pair_id: str, video_id: str) -> str | None:
    """Отмечает пару закрытой после публикации части B. Возвращает part_a_video_id для
    обратной ссылки (backlink-коммент на A), None если пара не найдена (гонка/файл поменялся)."""
    pairs = _load(channel)
    for p in pairs:
        if p.get("id") == pair_id:
            p["status"] = "resolved"
            p["part_b_video_id"] = video_id
            _save(channel, pairs)
            return p["part_a_video_id"]
    return None
