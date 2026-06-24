"""Генерирует .srt из таймингов слов и заливает как настоящие субтитры (CC track) на YouTube —
бонус к доступности и индексации в поиске, помимо уже горящих в кадре karaoke-субтитров.
Также автоматически загружает вьетнамский перевод (vi) — вторая по размеру аудитория канала."""
import io
import os

from anthropic import Anthropic
from googleapiclient.http import MediaIoBaseUpload

from config import CFG
from youtube_auth import get_client

_EXTRA_CAPTION_LANGS = ["vi"]  # языки, для которых автоматически генерируется перевод


def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def words_to_srt(words: list[dict], group_size: int = 6) -> str:
    """Группирует слова в строки субтитров (group_size слов на строку)."""
    lines = []
    for i in range(0, len(words), group_size):
        group = words[i:i + group_size]
        start = _format_timestamp(group[0]["start"])
        end = _format_timestamp(group[-1]["end"])
        text = " ".join(w["text"] for w in group)
        index = len(lines) + 1
        lines.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _translate_srt(srt_content: str, target_lang: str) -> str:
    """Переводит текст субтитров, сохраняя SRT-структуру (номера и тайминги)."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (
        f"Translate the subtitle text lines below into {target_lang}. "
        "Keep the SRT format exactly: preserve all index numbers, timestamps (lines with -->), "
        "and blank lines between entries. Only translate the text lines.\n\n"
        f"{srt_content}"
    )
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _upload_one(youtube, video_id: str, srt_content: str, lang: str, name: str) -> None:
    media = MediaIoBaseUpload(io.BytesIO(srt_content.encode("utf-8")), mimetype="application/octet-stream")
    youtube.captions().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "language": lang,
                "name": name,
                "isDraft": False,
            }
        },
        media_body=media,
    ).execute()


def upload_captions(video_id: str, words: list[dict]) -> None:
    srt_content = words_to_srt(words)
    youtube = get_client()

    _upload_one(youtube, video_id, srt_content, CFG["lang_code"], CFG["lang_code"].upper())
    print(f"  Captions uploaded ({CFG['lang_code']}) for video {video_id}")

    for lang in _EXTRA_CAPTION_LANGS:
        try:
            translated = _translate_srt(srt_content, lang)
            _upload_one(youtube, video_id, translated, lang, lang.upper())
            print(f"  Captions uploaded ({lang}) for video {video_id}")
        except Exception as e:
            print(f"  Could not upload {lang} captions: {e}")
