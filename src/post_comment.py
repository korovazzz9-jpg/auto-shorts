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


def post_comment_reply(parent_id: str, text: str) -> str:
    """Отвечает на собственный закреп-коммент — образует мини-тред. Ветки комментов
    повышают engagement density (сильный сигнал ранжирования) и провоцируют людей
    влезать в обсуждение. Возвращает id ответа."""
    youtube = get_client()
    resp = youtube.comments().insert(
        part="snippet",
        body={"snippet": {"parentId": parent_id, "textOriginal": text}},
    ).execute()
    print(f"  Reply posted: {resp['id']}")
    return resp["id"]
