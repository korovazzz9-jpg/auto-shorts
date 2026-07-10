"""Разовый скрипт: генерирует и заливает трейлер канала (не часть автопайплайна).
Запустить вручную: CHANNEL=es python src/make_trailer.py (или без CHANNEL для английского).
После загрузки видео нужно вручную назначить его трейлером канала в YouTube Studio
(Настройка канала -> Главная страница -> "Для непостоянных зрителей" -> выбрать видео)."""
import json
import os
import tempfile

from anthropic import Anthropic
from dotenv import load_dotenv

from build_video import build_video
from config import CFG
from fetch_stock_video import fetch_clips
from tts import text_to_speech
from upload_youtube import upload_video
from youtube_auth import get_authenticated_channel_title

load_dotenv()

SYSTEM_PROMPT = """You are writing a 25-30 second channel trailer script for {channel_name}, a YouTube
Shorts channel that posts mind-blowing, misconception-busting facts multiple times a day.

The trailer is shown to people who land on the channel page but haven't subscribed yet. It should:
1. Open with a punchy hook that demonstrates the channel's vibe (you can reference a genuinely
   surprising fact as an example, or just hit hard with energy and pacing).
2. Explain in one sentence what the channel does and how often it posts.
3. End with a clear, energetic call to subscribe.

Conversational, fast-paced, no filler. Not a list of facts -- a pitch for the channel itself.

Write entirely in {script_language}."""


def _verify_channel() -> None:
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(
            f"Канал не совпадает с CHANNEL={os.environ.get('CHANNEL', 'en')}: "
            f"токен авторизован на '{actual}', ожидался '{expected}'. Останавливаюсь."
        )


def generate_trailer_script() -> dict:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    system_prompt = SYSTEM_PROMPT.format(
        channel_name=CFG["channel_name"], script_language=CFG["script_language"]
    )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                "Write the trailer script. Also break it into 5-7 visual beats and for each one "
                "write a short stock-footage search query (2-4 words, energetic/dynamic visuals, "
                "in English -- the query itself stays in English regardless of script language, "
                "since that's what the stock footage site indexes best).\n\n"
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
    _verify_channel()
    print(f"[{CFG['channel_name']}] 1/4 Генерация сценария трейлера...")
    data = generate_trailer_script()
    print(f"  Заголовок: {data['title']}")
    print(f"  Сценарий: {data['script']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/4 Подбор стоковых видео...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/4 Озвучка и сборка видео...")
        words, _voice = text_to_speech(data["script"], audio_path)
        video_path, _thumb, _color = build_video(audio_path, clip_paths, words, video_path)

        print("4/4 Загрузка на YouTube...")
        video_id = upload_video(
            video_path,
            title=f"{data['title']} | Channel Trailer",
            description=data["script"],
            tags=[CFG["channel_name"], "channel trailer", "facts"],
            hashtags=["#shorts"],
            hashtag_position="end",
        )
        print(f"\nГотово: https://youtube.com/shorts/{video_id}")
        print("Теперь зайдите в YouTube Studio -> Настройка канала -> Главная страница ->")
        print("\"Для непостоянных зрителей\" -> выберите это видео как трейлер вручную.")


if __name__ == "__main__":
    main()
