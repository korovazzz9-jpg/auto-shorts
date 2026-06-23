"""Проверяет, было ли на канал залито видео за последние N минут. Используется
watchdog-воркфлоу: если нет — значит запланированный запуск pipeline.py не сработал
(например, GitHub Actions пропустил scheduled trigger), и его нужно повторить.

Exit code 0 — свежее видео есть, всё ок.
Exit code 1 — свежего видео нет, нужен повторный запуск.
"""
import datetime
import sys

from youtube_auth import get_client

LOOKBACK_MINUTES = 25


def has_recent_upload() -> bool:
    youtube = get_client()
    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    response = youtube.playlistItems().list(
        part="snippet", playlistId=uploads_id, maxResults=1
    ).execute()

    items = response.get("items", [])
    if not items:
        return False

    published_at = datetime.datetime.fromisoformat(
        items[0]["snippet"]["publishedAt"].replace("Z", "+00:00")
    )
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=LOOKBACK_MINUTES)
    return published_at >= cutoff


if __name__ == "__main__":
    if has_recent_upload():
        print("OK: recent upload found.")
        sys.exit(0)
    else:
        print("MISSING: no upload in the lookback window.")
        sys.exit(1)
