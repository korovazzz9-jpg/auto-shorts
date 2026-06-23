"""Точка входа: тема -> сценарий -> стоковые клипы -> озвучка -> видео -> загрузка на YouTube + Instagram."""
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from cloudinary_upload import delete_video, upload_video as upload_to_cloudinary
from fetch_stock_video import fetch_clips
from generate_script import generate_script
from tts import text_to_speech
from upload_instagram import upload_reel
from upload_youtube import upload_video as upload_to_youtube

load_dotenv()


def run() -> None:
    print("1/6 Генерация сценария...")
    data = generate_script()
    print(f"  Тема: {data['topic']} | Вариант: {data['variant']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/6 Подбор стоковых видео под смысл сценария...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/6 Озвучка...")
        words = text_to_speech(data["script"], audio_path)

        print("4/6 Сборка видео...")
        build_video(audio_path, clip_paths, words, video_path)

        print("5/6 Загрузка на YouTube...")
        upload_to_youtube(
            video_path,
            title=data["title"],
            description=data["script"],
            tags=data["tags"] + [f"abtest-{data['variant']}"],
            hashtags=data["hashtags"],
            hashtag_position=data["hashtag_position"],
        )

        print("6/6 Загрузка в Instagram...")
        hosted = None
        try:
            hosted = upload_to_cloudinary(video_path)
            caption = f"{data['title']}\n\n{data['script']}\n\n{' '.join(data['hashtags'])}"
            upload_reel(hosted["url"], caption)
        except Exception as e:
            print(f"  Instagram-загрузка не удалась, пропускаю: {e}")
        finally:
            if hosted:
                try:
                    delete_video(hosted["public_id"])
                except Exception as e:
                    print(f"  Не удалось удалить временный файл из Cloudinary: {e}")

    print("Готово.")


if __name__ == "__main__":
    run()
