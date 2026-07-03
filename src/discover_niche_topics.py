"""Outlier-анализ по нише (2026-07-03): ищет видео-выбросы у ЧУЖИХ каналов в тех же
темах, что наш TOPICS_POOL, и превращает найденные топ-темы в мягкий бонус веса при
выборе следующей темы (_pick_topic() в generate_script.py). НЕ копирует контент/факты —
только сигнал "эта тема сейчас хорошо заходит в нише", как топ-темы у похожих каналов.

Зачем: индустриальные данные говорят, что каналы, ищущие видео-выбросы по нише (не
только свою статистику), растут в 2-3 раза быстрее — сигнал темы, не факта.

Метрика "выброс": views / max(channel_subscribers, 1) >= OUTLIER_RATIO — видео разошлось
СИЛЬНО шире, чем аудитория самого канала (значит подхвачено алгоритмом широко, не только
подписчиками). Отличается от просто "у большого канала много просмотров" (там это норма,
не выброс) — маленький канал с внезапным хитом это реально сигнал темы, а не размера.

Квота: search().list = 100 ед/запрос (дорого) — по одному запросу на тему из TOPICS_POOL
(14 тем = 1400 ед/канал за прогон), + дешёвые videos.list/channels.list (1 ед/50 штук).
Раз в неделю, штатный GitHub-cron (не публикация, не критично ко времени).

Запуск:
  python discover_niche_topics.py            # EN
  CHANNEL=es python discover_niche_topics.py # ES
"""
import json
import os
from datetime import date

from dotenv import load_dotenv

from config import CFG, CHANNEL
from generate_script import TOPICS_POOL
from youtube_auth import get_client

load_dotenv()

OUTLIER_RATIO = 5.0       # views / subscribers — порог "выброса"
MIN_VIEWS = 5000          # отсекаем шум крошечных каналов/видео
MAX_RESULTS_PER_QUERY = 10
NICHE_SIGNAL_FILE = os.path.join(os.path.dirname(__file__), "..", f"niche_signal_{CHANNEL}.json")


def _topic_query_term(topic: str) -> str:
    """Термин для поискового запроса на языке канала. EN: тема как есть (уже на английском
    в TOPICS_POOL). ES: испанский перевод из CFG['playlist_titles'] (естественная фраза,
    не ALL-CAPS одно слово, как в topic_cta_words), с убранным префиксом 'Datos de/del/en '.
    Без перевода — фолбэк на английскую тему (смешанный запрос хуже, чем пустой, но лучше,
    чем совсем ничего не найти)."""
    if CFG["lang_code"] != "es":
        return topic
    title = CFG.get("playlist_titles", {}).get(topic, "")
    if not title:
        return topic
    for prefix in ("Datos de ", "Datos del ", "Datos en "):
        if title.startswith(prefix):
            return title[len(prefix):]
    return title


def _search_topic(youtube, topic: str) -> list[dict]:
    """Ищет до MAX_RESULTS_PER_QUERY публичных видео по теме, отсортированных по
    просмотрам. Возвращает [{video_id, channel_id}]. Сбой одного запроса (сеть/квота)
    не должен рушить весь прогон — остальные темы всё равно проверятся."""
    query_term = _topic_query_term(topic)
    query = f"{query_term} facts shorts" if CFG["lang_code"] == "en" else f"{query_term} datos curiosos shorts"
    try:
        resp = youtube.search().list(
            q=query, part="snippet", type="video", order="viewCount",
            videoDuration="short", maxResults=MAX_RESULTS_PER_QUERY,
            relevanceLanguage=CFG["lang_code"],
        ).execute()
    except Exception as e:
        print(f"  search failed for '{topic}': {e}")
        return []
    return [
        {"video_id": i["id"]["videoId"], "channel_id": i["snippet"]["channelId"]}
        for i in resp.get("items", []) if i.get("id", {}).get("videoId")
    ]


def _fetch_stats(youtube, video_ids: list[str], channel_ids: list[str]) -> tuple[dict, dict]:
    """Батч-получение views (video) и subscriberCount (channel) — дёшево, 1 ед/50 штук."""
    views: dict[str, int] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="statistics", id=",".join(batch)).execute()
        for v in resp.get("items", []):
            views[v["id"]] = int(v["statistics"].get("viewCount", 0) or 0)

    subs: dict[str, int] = {}
    unique_channels = list(dict.fromkeys(channel_ids))
    for i in range(0, len(unique_channels), 50):
        batch = unique_channels[i:i + 50]
        resp = youtube.channels().list(part="statistics", id=",".join(batch)).execute()
        for c in resp.get("items", []):
            # Некоторые каналы скрывают подписчиков (hiddenSubscriberCount) — считаем как 0
            # (max(s,1) ниже не даст деления на ноль, а такой канал просто не попадёт в выброс
            # по хорошей причине: у нас нет базы для сравнения, лучше пропустить, чем угадывать).
            subs[c["id"]] = int(c["statistics"].get("subscriberCount", 0) or 0)
    return views, subs


def discover() -> dict[str, int]:
    """Возвращает {topic: outlier_count} — сколько видео-выбросов найдено в нише
    по каждой теме нашего TOPICS_POOL за этот прогон."""
    youtube = get_client()
    outlier_counts: dict[str, int] = {}

    for topic in TOPICS_POOL:
        results = _search_topic(youtube, topic)
        if not results:
            continue
        video_ids = [r["video_id"] for r in results]
        channel_ids = [r["channel_id"] for r in results]
        views, subs = _fetch_stats(youtube, video_ids, channel_ids)

        count = 0
        for r in results:
            v = views.get(r["video_id"], 0)
            s = subs.get(r["channel_id"], 0)
            if v >= MIN_VIEWS and s > 0 and v / s >= OUTLIER_RATIO:
                count += 1
        if count:
            outlier_counts[topic] = count
        print(f"  {topic}: {count} outlier(s) of {len(results)} searched")

    return outlier_counts


def main() -> None:
    counts = discover()
    with open(NICHE_SIGNAL_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"outlier_counts": counts, "updated": date.today().isoformat()},
            f, ensure_ascii=False, indent=2,
        )
    print(f"  niche_signal saved: {counts}")


if __name__ == "__main__":
    main()
