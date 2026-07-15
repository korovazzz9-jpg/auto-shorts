"""Считает средние просмотры по темам (на основе скрытого тега topic-<тема>, который
пайплайн добавляет к каждому видео) — нужно для взвешенного выбора темы в generate_script.py."""
import re

from youtube_auth import get_client

TOPIC_TAG_RE = re.compile(r"^topic-(.+)$")


def get_topic_avg_views(known_topics: set[str] | None = None) -> dict[str, float]:
    """known_topics (2026-07-15) — вернуть только темы из этого набора. Нужно, потому что в
    тегах живут не только темы из пула: `generate_series.py` тегирует `topic-<конкретная тема
    серии>` (LLM-строка вроде «Immortal Animals» / «The Ancient City That Voted to Destroy
    Itself» — по одной на серию, n=3 по числу частей), плюс остаются легаси-темы, удалённые
    из пула (psychology, bizarre records). Такой мусор не совпадает ни с одной темой пула, но
    у вызывающих он ПОРТИЛ `overall_avg` (по нему считается вес тем БЕЗ данных) и накручивал
    счётчик в гейте `MIN_TOPICS_WITH_DATA`. Без аргумента поведение прежнее — полная картина
    (нужна для диагностики через __main__)."""
    youtube = get_client()

    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = channels.get("items", [])
    if not items:
        return {}
    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page_token
        ).execute()
        video_ids.extend(item["snippet"]["resourceId"]["videoId"] for item in resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    views_by_topic: dict[str, list[int]] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="snippet,statistics", id=",".join(batch)).execute()
        for video in resp.get("items", []):
            tags = video["snippet"].get("tags", [])
            topic = None
            for tag in tags:
                match = TOPIC_TAG_RE.match(tag)
                if match:
                    topic = match.group(1).replace("_", " ")
                    break
            if not topic:
                continue
            if known_topics is not None and topic not in known_topics:
                continue
            views = int(video["statistics"].get("viewCount", 0))
            views_by_topic.setdefault(topic, []).append(views)

    return {topic: sum(views) / len(views) for topic, views in views_by_topic.items()}


if __name__ == "__main__":
    for topic, avg in sorted(get_topic_avg_views().items(), key=lambda kv: -kv[1]):
        print(f"{avg:8.1f}  {topic}")
