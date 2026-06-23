"""Считает средние просмотры по темам (на основе скрытого тега topic-<тема>, который
пайплайн добавляет к каждому видео) — нужно для взвешенного выбора темы в generate_script.py."""
import re

from youtube_auth import get_client

TOPIC_TAG_RE = re.compile(r"^topic-(.+)$")


def get_topic_avg_views() -> dict[str, float]:
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
            views = int(video["statistics"].get("viewCount", 0))
            views_by_topic.setdefault(topic, []).append(views)

    return {topic: sum(views) / len(views) for topic, views in views_by_topic.items()}


if __name__ == "__main__":
    for topic, avg in sorted(get_topic_avg_views().items(), key=lambda kv: -kv[1]):
        print(f"{avg:8.1f}  {topic}")
