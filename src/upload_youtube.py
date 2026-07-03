"""Загружает готовый mp4 на YouTube как Short."""
from googleapiclient.http import MediaFileUpload

from youtube_auth import get_client


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    hashtags: list[str],
    hashtag_position: str = "start",
    thumbnail_path: str | None = None,
    default_language: str | None = None,
) -> str:
    youtube = get_client()
    hashtag_line = " ".join(hashtags)
    if hashtag_position == "end":
        full_description = f"{description}\n\n{hashtag_line}"
    else:
        full_description = f"{hashtag_line}\n\n{description}"
    body = {
        "snippet": {
            "title": title[:100],
            "description": full_description,
            "tags": tags,
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    # defaultLanguage обязателен, чтобы потом можно было прикрепить локализации метаданных
    # (localize_metadata.py) — без него videos.update(part=localizations) отклоняется API.
    if default_language:
        body["snippet"]["defaultLanguage"] = default_language
        body["snippet"]["defaultAudioLanguage"] = default_language
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response["id"]
    print(f"Uploaded: https://youtube.com/shorts/{video_id}")

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            print("  Thumbnail set.")
        except Exception as e:
            print(f"  Thumbnail upload failed: {e}")

    return video_id
