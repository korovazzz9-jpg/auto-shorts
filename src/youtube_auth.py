"""Общая авторизация YouTube Data API для скриптов загрузки и чтения статистики."""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # нужен для загрузки caption-треков
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def get_client():
    return build("youtube", "v3", credentials=_credentials())


def get_analytics_client():
    """YouTube Analytics API v2 — для retention-метрик (avg view duration / % досмотра)."""
    return build("youtubeAnalytics", "v2", credentials=_credentials())


def get_authenticated_channel_title() -> str:
    response = get_client().channels().list(part="snippet", mine=True).execute()
    return response["items"][0]["snippet"]["title"]
