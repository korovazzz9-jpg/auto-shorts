"""Группирует видео в плейлисты по теме — увеличивает время сессии зрителя на канале."""
from config import CFG
from youtube_auth import get_client

TOPIC_PLAYLIST_TITLES = CFG["playlist_titles"]

_playlist_cache: dict[str, str] = {}


def _find_existing_playlist(youtube, title: str) -> str | None:
    response = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
    for item in response.get("items", []):
        if item["snippet"]["title"] == title:
            return item["id"]
    return None


def _create_playlist(youtube, title: str) -> str:
    response = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": f"{title} — {CFG['channel_name']}"},
            "status": {"privacyStatus": "public"},
        },
    ).execute()
    return response["id"]


def get_or_create_playlist(topic: str) -> str | None:
    title = TOPIC_PLAYLIST_TITLES.get(topic)
    if not title:
        return None
    if title in _playlist_cache:
        return _playlist_cache[title]

    youtube = get_client()
    playlist_id = _find_existing_playlist(youtube, title) or _create_playlist(youtube, title)
    _playlist_cache[title] = playlist_id
    return playlist_id


def add_video_to_playlist(video_id: str, topic: str) -> str | None:
    """Returns playlist_id if successful, else None."""
    playlist_id = get_or_create_playlist(topic)
    if not playlist_id:
        print(f"  Нет плейлиста для темы '{topic}', пропускаю.")
        return None

    youtube = get_client()
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()
    print(f"  Added to playlist '{TOPIC_PLAYLIST_TITLES[topic]}'")
    return playlist_id
