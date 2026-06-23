"""Генерирует .srt из таймингов слов и заливает как настоящие субтитры (CC track) на YouTube —
бонус к доступности и индексации в поиске, помимо уже горящих в кадре karaoke-субтитров."""
import io

from googleapiclient.http import MediaIoBaseUpload

from youtube_auth import get_client


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


def upload_captions(video_id: str, words: list[dict]) -> None:
    srt_content = words_to_srt(words)
    youtube = get_client()
    media = MediaIoBaseUpload(io.BytesIO(srt_content.encode("utf-8")), mimetype="application/octet-stream")
    youtube.captions().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "language": "en",
                "name": "English",
                "isDraft": False,
            }
        },
        media_body=media,
    ).execute()
    print(f"  Captions uploaded for video {video_id}")
