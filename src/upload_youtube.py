"""Загружает готовый mp4 на YouTube как Short."""
from googleapiclient.http import MediaFileUpload

from youtube_auth import get_client


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    hashtags: list[str],
) -> str:
    youtube = get_client()
    hashtag_line = " ".join(hashtags)
    body = {
        "snippet": {
            "title": title[:100],
            "description": f"{hashtag_line}\n\n{description}",
            "tags": tags,
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response["id"]
    print(f"Uploaded: https://youtube.com/shorts/{video_id}")
    return video_id
