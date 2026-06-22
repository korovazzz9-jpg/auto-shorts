"""Точка входа: тема -> сценарий -> озвучка -> видео -> загрузка на YouTube."""
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from generate_script import generate_script
from tts import text_to_speech
from upload_youtube import upload_video

load_dotenv()


def run() -> None:
    print("1/4 Генерация сценария...")
    data = generate_script()
    print(f"  Тема: {data['topic']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/4 Озвучка...")
        text_to_speech(data["script"], audio_path)

        print("3/4 Сборка видео...")
        build_video(audio_path, data["title"], data["script"], video_path)

        print("4/4 Загрузка на YouTube...")
        upload_video(
            video_path,
            title=data["title"],
            description=data["script"],
            tags=data["tags"],
        )

    print("Готово.")


if __name__ == "__main__":
    run()
