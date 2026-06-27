"""Возвращает заголовки уже опубликованных (и недавно сгенерированных) видео,
чтобы не повторять темы.

YouTube API не сразу возвращает только что загруженное видео в плейлисте uploads,
поэтому при нескольких запусках в один день второй запуск не видел первого и мог
повторить тему. Локальный кэш titles_cache.json обновляется сразу после генерации
заголовка и решает эту проблему."""
import json
import os

from youtube_auth import get_client

MAX_TITLES = 100
_CACHE_FILE = os.path.join(os.path.dirname(__file__), "titles_cache.json")
_CACHE_MAX = 200

# Темы последних видео — чтобы не выпускать два ролика подряд на одну тему.
_TOPICS_FILE = os.path.join(os.path.dirname(__file__), "topics_cache.json")
_TOPICS_MAX = 20


def add_topic_to_cache(topic: str) -> None:
    """Запоминает тему только что сгенерированного видео (до загрузки на YouTube —
    обходит лаг индексации API)."""
    try:
        with open(_TOPICS_FILE, encoding="utf-8") as f:
            topics = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        topics = []
    topics.insert(0, topic)
    with open(_TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics[:_TOPICS_MAX], f, ensure_ascii=False, indent=2)


def get_recent_topics(n: int = 2) -> list[str]:
    """Последние n тем (свежая первой) — их исключаем при выборе следующей темы."""
    try:
        with open(_TOPICS_FILE, encoding="utf-8") as f:
            return json.load(f)[:n]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _load_cache() -> list[str]:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_to_cache(title: str) -> None:
    titles = _load_cache()
    if title not in titles:
        titles.insert(0, title)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(titles[:_CACHE_MAX], f, ensure_ascii=False, indent=2)


def add_title_to_cache(title: str) -> None:
    """Вызывается сразу после генерации заголовка — до загрузки на YouTube."""
    _save_to_cache(title)


def get_recent_titles() -> list[str]:
    yt_titles: list[str] = []
    try:
        youtube = get_client()
        channels_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = channels_response.get("items", [])
        if items:
            uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            page_token = None
            while len(yt_titles) < MAX_TITLES:
                response = youtube.playlistItems().list(
                    part="snippet",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                ).execute()
                yt_titles.extend(item["snippet"]["title"] for item in response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
    except Exception:
        pass

    cache_titles = _load_cache()
    seen: set[str] = set()
    merged: list[str] = []
    for t in cache_titles + yt_titles:
        if t not in seen:
            seen.add(t)
            merged.append(t)

    return merged[:MAX_TITLES]


if __name__ == "__main__":
    for t in get_recent_titles():
        print(t)
