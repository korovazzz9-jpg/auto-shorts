"""Загружает готовый mp4 на YouTube как Short."""
from googleapiclient.http import MediaFileUpload

from youtube_auth import get_client


def _sanitize_youtube_text(text: str, max_len: int) -> str:
    """Приводит текст к требованиям YouTube для title/description: убирает угловые скобки
    (< и > YouTube отклоняет как invalidDescription/invalidTitle — реальное падение обоих
    лонгформов 2026-07-05) и обрезает до max_len (лимит описания 5000, title 100). Обрезка
    по границе слова, чтобы не рвать слово/тег посередине."""
    cleaned = text.replace("<", "").replace(">", "")
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[:max_len]
    if " " in cut[-40:]:  # не рвём слово, если недалеко есть пробел
        cut = cut.rsplit(" ", 1)[0]
    return cut


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
    # Резервируем место под хештеги (2026-07-13, реальный прод-баг): раньше description+
    # hashtag_line склеивались в одну строку и обрезались ЦЕЛИКОМ по хвосту — у длинного
    # лонгформ-скрипта (4955/4990 символов) это молча снесло и ссылку на сестринский канал,
    # и все хештеги, т.к. они шли последними. Теперь хештеги гарантированно переживают —
    # обрезается только description, если места не хватает.
    reserved = len(hashtag_line) + 2 if hashtag_line else 0  # +2 = "\n\n"
    safe_description = _sanitize_youtube_text(description, max(4990 - reserved, 0))
    if hashtag_position == "end":
        full_description = f"{safe_description}\n\n{hashtag_line}" if hashtag_line else safe_description
    else:
        full_description = f"{hashtag_line}\n\n{safe_description}" if hashtag_line else safe_description
    body = {
        "snippet": {
            "title": _sanitize_youtube_text(title, 100),
            "description": _sanitize_youtube_text(full_description, 4990),
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
