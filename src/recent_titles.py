"""Возвращает заголовки уже опубликованных видео, чтобы не повторять темы."""
from youtube_auth import get_client

MAX_TITLES = 100


def get_recent_titles() -> list[str]:
    youtube = get_client()

    channels_response = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = channels_response.get("items", [])
    if not items:
        return []
    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    titles = []
    page_token = None
    while len(titles) < MAX_TITLES:
        response = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        titles.extend(item["snippet"]["title"] for item in response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return titles[:MAX_TITLES]


if __name__ == "__main__":
    for t in get_recent_titles():
        print(t)
