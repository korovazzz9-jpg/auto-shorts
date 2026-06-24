"""Точка входа: тема -> сценарий -> стоковые клипы -> озвучка -> видео -> загрузка на YouTube + Instagram."""
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from cloudinary_upload import delete_image, delete_video, upload_image, upload_video as upload_to_cloudinary
from config import CFG
from fetch_stock_video import fetch_clips
from generate_script import generate_script
from playlists import add_video_to_playlist
from post_comment import post_channel_comment
from tts import text_to_speech
from upload_captions import upload_captions
from upload_instagram import upload_reel
from upload_youtube import upload_video as upload_to_youtube
from youtube_auth import get_authenticated_channel_title

load_dotenv()


def _verify_channel() -> None:
    """Останавливает запуск, если YT_REFRESH_TOKEN в окружении указывает не на тот канал,
    что выбран через CHANNEL -- иначе контент на одном языке может улететь не на тот канал
    (бывает при ручном локальном запуске со старыми переменными окружения в сессии)."""
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(
            f"Канал не совпадает с CHANNEL={os.environ.get('CHANNEL', 'en')}: "
            f"токен авторизован на '{actual}', ожидался '{expected}'. Останавливаюсь."
        )


def run() -> None:
    _verify_channel()
    print(f"[{CFG['channel_name']}] 1/6 Генерация сценария...")
    data = generate_script()
    print(f"  Тема: {data['topic']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/6 Подбор стоковых видео под смысл сценария...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/6 Озвучка...")
        words = text_to_speech(data["script"], audio_path)

        print("4/6 Сборка видео...")
        video_path, thumb_path = build_video(audio_path, clip_paths, words, video_path, topic=data["topic"])

        print("5/6 Загрузка на YouTube...")
        video_id = upload_to_youtube(
            video_path,
            title=data["title"],
            description=data["script"],
            tags=data["tags"] + [f"topic-{data['topic'].replace(' ', '_')}"],
            hashtags=data["hashtags"],
            hashtag_position=data["hashtag_position"],
        )

        try:
            upload_captions(video_id, words)
        except Exception as e:
            print(f"  Не удалось загрузить субтитры: {e}")

        try:
            add_video_to_playlist(video_id, data["topic"])
        except Exception as e:
            print(f"  Не удалось добавить в плейлист: {e}")

        try:
            channel_url = f"https://www.youtube.com/@{CFG['channel_handle']}" if CFG.get("channel_handle") else ""
            comment = CFG.get("first_comment", "").format(channel_url=channel_url).strip()
            if comment:
                post_channel_comment(video_id, comment)
        except Exception as e:
            print(f"  Не удалось опубликовать комментарий: {e}")

        if CFG["post_to_instagram"]:
            print("6/6 Загрузка в Instagram...")
            hosted = None
            hosted_thumb = None
            try:
                hosted = upload_to_cloudinary(video_path)
                hosted_thumb = upload_image(thumb_path)
                caption = f"{data['title']}\n\n{data['script']}\n\n{' '.join(data['hashtags'])}"
                upload_reel(hosted["url"], caption, cover_url=hosted_thumb["url"])
            except Exception as e:
                print(f"  Instagram-загрузка не удалась, пропускаю: {e}")
            finally:
                if hosted:
                    try:
                        delete_video(hosted["public_id"])
                    except Exception as e:
                        print(f"  Не удалось удалить временный файл из Cloudinary: {e}")
                if hosted_thumb:
                    try:
                        delete_image(hosted_thumb["public_id"])
                    except Exception as e:
                        print(f"  Не удалось удалить thumbnail из Cloudinary: {e}")
        else:
            print("6/6 Instagram отключён для этого канала, пропускаю.")

    print("Готово.")


if __name__ == "__main__":
    run()
