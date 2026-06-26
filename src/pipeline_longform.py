"""Точка входа для еженедельного длинного видео-компиляции (3.5-4.5 мин, 5 фактов).
Не часть Shorts-расписания — отдельный workflow, раз в неделю. Не постится в Instagram
(там лимит длины Reels около 90 сек, не подходит)."""
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from config import CFG
from fetch_stock_video import fetch_clips
from generate_longform_script import generate_longform_script
from notify import notify
from playlists import add_video_to_playlist
from tts import text_to_speech
from upload_captions import upload_captions
from upload_youtube import upload_video as upload_to_youtube
from youtube_auth import get_authenticated_channel_title

load_dotenv()


def _alert(step: str, err: Exception) -> None:
    """Частичный сбой лонгформа — видео вышло, но шаг отвалился."""
    msg = f"⚠️ [{CFG['channel_name']}] лонгформ, шаг «{step}» упал, но продолжил:\n{err}"
    print(f"  {msg}")
    notify(msg)


def _verify_channel() -> None:
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(
            f"Канал не совпадает с CHANNEL={os.environ.get('CHANNEL', 'en')}: "
            f"токен авторизован на '{actual}', ожидался '{expected}'. Останавливаюсь."
        )


def run() -> None:
    _verify_channel()
    print("1/4 Генерация сценария-компиляции...")
    data = generate_longform_script()
    print(f"  Тема: {data['theme']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/4 Подбор стоковых видео...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/4 Озвучка и сборка видео...")
        words = text_to_speech(data["script"], audio_path)
        video_path, thumb_path = build_video(audio_path, clip_paths, words, video_path, topic=data["theme"], title=data["title"])

        print("4/4 Загрузка на YouTube...")
        video_id = upload_to_youtube(
            video_path,
            title=data["title"],
            description=data["script"],
            tags=data["tags"],
            hashtags=data["hashtags"],
            hashtag_position="end",
            thumbnail_path=thumb_path,
        )

        # Субтитры временно отключены (квота) — как и в Shorts/сериях. Вернуть после увеличения квоты:
        # try:
        #     upload_captions(video_id, words)
        # except Exception as e:
        #     _alert("captions", e)

        try:
            add_video_to_playlist(video_id, data["theme"])
        except Exception as e:
            _alert("playlist", e)

    url = f"https://youtube.com/watch?v={video_id}"
    notify(f"✅ [{CFG['channel_name']}] лонгформ опубликован:\n{data['title']}\n{url}")
    print(f"Готово: {url}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify(f"🔴 [{CFG['channel_name']}] лонгформ УПАЛ:\n{e}")
        raise
