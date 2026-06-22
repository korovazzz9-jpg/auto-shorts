"""Находит видео на канале с наибольшим числом просмотров за последние N часов."""
import datetime

from youtube_auth import get_client

LOOKBACK_HOURS = 26


def find_best_recent_video() -> dict | None:
    youtube = get_client()

    channels_response = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist_id = channels_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=LOOKBACK_HOURS)

    recent_video_ids = []
    page_token = None
    while True:
        playlist_response = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in playlist_response["items"]:
            published_at = datetime.datetime.fromisoformat(
                item["snippet"]["publishedAt"].replace("Z", "+00:00")
            )
            if published_at >= cutoff:
                recent_video_ids.append(item["snippet"]["resourceId"]["videoId"])

        page_token = playlist_response.get("nextPageToken")
        oldest_in_page = playlist_response["items"][-1]["snippet"]["publishedAt"] if playlist_response["items"] else None
        if not page_token or not oldest_in_page:
            break
        oldest_dt = datetime.datetime.fromisoformat(oldest_in_page.replace("Z", "+00:00"))
        if oldest_dt < cutoff:
            break

    if not recent_video_ids:
        return None

    videos_response = youtube.videos().list(
        part="statistics,snippet",
        id=",".join(recent_video_ids),
    ).execute()

    best = max(videos_response["items"], key=lambda v: int(v["statistics"].get("viewCount", 0)))
    return {
        "video_id": best["id"],
        "title": best["snippet"]["title"],
        "view_count": int(best["statistics"].get("viewCount", 0)),
        "url": f"https://youtube.com/shorts/{best['id']}",
    }


if __name__ == "__main__":
    print(find_best_recent_video())
