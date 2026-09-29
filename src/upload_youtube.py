"""Загружает готовый mp4 на YouTube как Short."""
import datetime
import http.client
import time

import httplib2
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_auth import get_client

# Повтор загрузки (2026-09-29, аудит): videos.insert шёл одним request.execute() без повторов —
# любой 5xx или обрыв соединения ронял прогон уже ПОСЛЕ платной генерации и оставлял эпизод в
# статусе «publishing», а pipeline на следующем прогоне останавливался до ручной сверки.
# Resumable-сессия переживает повтор next_chunk(): библиотека сама спрашивает у YouTube, сколько
# байт уже принято, и докачивает хвост — дубля ролика повтор не создаёт.
RETRIABLE_STATUS = {500, 502, 503, 504}
# Тот же набор, что в официальном примере YouTube upload_video.py: OSError покрывает обрыв
# соединения, таймаут сокета и SSL, http.client.HTTPException — оборванный ответ.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, OSError, http.client.HTTPException)
UPLOAD_RETRIES = 5


MAX_TAGS_TOTAL = 460  # запас от жёсткого лимита YouTube 500 симв. (см. _sanitize_tags)


def _sanitize_tags(tags: list[str]) -> list[str]:
    """Обрезает список тегов под суммарный лимит YouTube (2026-07-14, реальное падение:
    invalidTags — «The request metadata specifies invalid video keywords»). YouTube считает
    сумму длин ВСЕХ тегов (многословные — в кавычках, +2 символа) не более 500; с ростом
    числа служебных тегов (topic-/hook-/tone-/color-/voice-/format-/sister_lang_tags) лимит
    стало реально достижимо превысить. Отбрасываем "<"/">" (как в тексте) и теги сверх
    бюджета — приоритет у тегов, добавленных РАНЬШЕ в списке, лишние просто не попадают в
    запрос вместо падения всей публикации. 2026-08-21: вызывающий код (publish.py) специально
    ставит служебные extra_tags РАНЬШЕ content_tags — телеметрия для weekly_report важнее SEO
    (см. комментарий в publish.py; было наоборот и молча резало niche-recreation/cta-/midcta-
    на большинстве видео)."""
    cleaned, total = [], 0
    for t in tags:
        t = str(t).replace("<", "").replace(">", "").strip()
        if not t:
            continue
        cost = len(t) + (2 if " " in t else 0)
        if total + cost > MAX_TAGS_TOTAL:
            continue
        cleaned.append(t)
        total += cost
    return cleaned


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
            "tags": _sanitize_tags(tags),
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
    response = resumable_upload(request)
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


def resumable_upload(request, retries: int = UPLOAD_RETRIES, sleep=time.sleep) -> dict:
    """Докачивает resumable-загрузку, повторяя next_chunk() на временных сбоях (5xx, обрыв
    сети) с паузой 2, 4, 8… с (не больше 60). 4xx — ошибка запроса (квота, invalidTitle), её
    повтор ничего не даст: пробрасывается сразу."""
    response, attempt = None, 0
    while response is None:
        try:
            _, response = request.next_chunk()
            continue
        except HttpError as exc:
            if exc.resp.status not in RETRIABLE_STATUS:
                raise
            error = exc
        except RETRIABLE_EXCEPTIONS as exc:
            error = exc
        attempt += 1
        if attempt > retries:
            raise error
        delay = min(60, 2 ** attempt)
        print(f"  YouTube upload: {type(error).__name__}, повтор {attempt}/{retries} через {delay} с")
        sleep(delay)
    return response


def find_recent_upload(title: str, since_iso: str, youtube=None, lookback: int = 15) -> str | None:
    """video_id ролика с таким заголовком, выложенного не раньше since_iso (минус 10 мин на
    расхождение часов), среди последних `lookback` загрузок канала; иначе None. Нужен сверке
    эпизода, застрявшего в «publishing»: вышел ли ролик на самом деле, хотя ответ потерялся."""
    youtube = youtube or get_client()
    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = youtube.playlistItems().list(part="snippet", playlistId=uploads_id,
                                         maxResults=lookback).execute().get("items", [])
    wanted = _sanitize_youtube_text(title, 100)
    since = datetime.datetime.fromisoformat(since_iso) - datetime.timedelta(minutes=10)
    for item in items:
        snippet = item.get("snippet", {})
        published = datetime.datetime.fromisoformat(snippet.get("publishedAt", "").replace("Z", "+00:00"))
        if snippet.get("title") == wanted and published >= since:
            return snippet["resourceId"]["videoId"]
    return None
