"""Точка входа: тема -> сценарий -> стоковые клипы -> озвучка -> видео -> загрузка на YouTube."""
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from fetch_stock_video import fetch_clips
from generate_script import generate_script
from tts import text_to_speech
from upload_youtube import upload_video

load_dotenv()


def run() -> None:
    print("1/5 Генерация сценария...")
    data = generate_script()
    print(f"  Тема: {data['topic']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/5 Подбор стоковых видео под смысл сценария...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/5 Озвучка...")
        words = text_to_speech(data["script"], audio_path)

        print("4/5 Сборка видео...")
        build_video(audio_path, clip_paths, words, video_path)

        print("5/5 Загрузка на YouTube...")
        upload_video(
            video_path,
            title=data["title"],
            description=data["script"],
            tags=data["tags"],
        )

    print("Готово.")


if __name__ == "__main__":
    run()
