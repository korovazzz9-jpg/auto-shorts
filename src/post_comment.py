"""Публикует первый комментарий от имени канала сразу после загрузки видео.
Комментарий со ссылкой на плейлист/канал повышает вовлечённость и даёт зрителям
навигацию к другим видео — YouTube учитывает комментарии при ранжировании."""
from youtube_auth import get_client


def post_channel_comment(video_id: str, text: str) -> str:
    """Публикует комментарий и возвращает его id."""
    youtube = get_client()
    resp = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": text}
                },
            }
        },
    ).execute()
    comment_id = resp["snippet"]["topLevelComment"]["id"]
    print(f"  Comment posted: {comment_id}")
    return comment_id
