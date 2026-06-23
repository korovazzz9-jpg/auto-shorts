"""Разовый скрипт: генерирует и заливает трейлер канала (не часть автопайплайна).
Запустить вручную: python src/make_trailer.py
После загрузки видео нужно вручную назначить его трейлером канала в YouTube Studio
(Настройка канала -> Главная страница -> "Для непостоянных зрителей" -> выбрать видео)."""
import json
import os
import tempfile

from anthropic import Anthropic
from dotenv import load_dotenv

from build_video import build_video
from fetch_stock_video import fetch_clips
from tts import text_to_speech
from upload_youtube import upload_video

load_dotenv()

SYSTEM_PROMPT = """You are writing a 25-30 second channel trailer script for 60SecFacts, a YouTube
Shorts channel that posts mind-blowing, misconception-busting facts multiple times a day.

The trailer is shown to people who land on the channel page but haven't subscribed yet. It should:
1. Open with a punchy hook that demonstrates the channel's vibe (you can reference a genuinely
   surprising fact as an example, or just hit hard with energy and pacing).
2. Explain in one sentence what the channel does and how often it posts.
3. End with a clear, energetic call to subscribe.

Conversational, fast-paced, no filler. Not a list of facts -- a pitch for the channel itself."""


def generate_trailer_script() -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Write the trailer script. Also break it into 5-7 visual beats and for each one "
                "write a short stock-footage search query (2-4 words, energetic/dynamic visuals, "
                "in English).\n\n"
                "Respond strictly in JSON, no markdown wrapper: "
                '{"title": "trailer title under 60 characters", '
                '"script": "trailer voiceover text", '
                '"video_queries": ["query1", "query2", ...]}'
            ),
        }],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    return json.loads(raw[start:end + 1])


def main() -> None:
    print("1/4 Генерация сценария трейлера...")
    data = generate_trailer_script()
    print(f"  Заголовок: {data['title']}")
    print(f"  Сценарий: {data['script']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/4 Подбор стоковых видео...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/4 Озвучка и сборка видео...")
        words = text_to_speech(data["script"], audio_path)
        build_video(audio_path, clip_paths, words, video_path)

        print("4/4 Загрузка на YouTube...")
        video_id = upload_video(
            video_path,
            title=f"{data['title']} | Channel Trailer",
            description=data["script"],
            tags=["60SecFacts", "channel trailer", "facts", "did you know"],
            hashtags=["#shorts", "#facts"],
            hashtag_position="end",
        )
        print(f"\nГотово: https://youtube.com/shorts/{video_id}")
        print("Теперь зайдите в YouTube Studio -> Настройка канала -> Главная страница ->")
        print("\"Для непостоянных зрителей\" -> выберите это видео как трейлер вручную.")


if __name__ == "__main__":
    main()
