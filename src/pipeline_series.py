"""Пайплайн для недельной серии (Part 1/2/3).

Понедельник (SERIES_PART=1): генерирует все 3 скрипта, сохраняет в series_state.json, публикует Part 1.
Вторник  (SERIES_PART=2): читает series_state.json, публикует Part 2.
Среда    (SERIES_PART=3): читает series_state.json, публикует Part 3.
"""
import json
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from config import CFG, CHANNEL
from fetch_stock_video import fetch_clips
from generate_series import generate_series
from notify import notify
from publish import publish
from tts import text_to_speech
from youtube_auth import get_authenticated_channel_title

load_dotenv()

# Per-channel: EN и ES не должны затирать состояние друг друга. Файл коммитится в репо
# в Part 1 (Пн) и читается через checkout в Part 2/3 — надёжнее, чем actions/cache (TTL 7 дней).
SERIES_STATE_FILE = os.path.join(os.path.dirname(__file__), f"series_state_{CHANNEL}.json")


def _alert(step: str, err: Exception) -> None:
    """Частичный сбой в серии — видео вышло, но шаг отвалился. GitHub письмо не шлёт."""
    msg = f"⚠️ [{CFG['channel_name']}] серия, шаг «{step}» упал, но продолжил:\n{err}"
    print(f"  {msg}")
    notify(msg)


def _load_state() -> dict:
    if os.path.exists(SERIES_STATE_FILE):
        with open(SERIES_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    with open(SERIES_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run() -> None:
    part = int(os.environ.get("SERIES_PART", "1"))

    # Проверяем канал
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(f"Wrong channel: got '{actual}', expected '{expected}'")

    # Part 1 — генерируем все 3 части и сохраняем
    if part == 1:
        print(f"[{CFG['channel_name']}] Series Part 1 — generating all 3 scripts...")
        state = generate_series()
        _save_state(state)
        print(f"  Topic: {state['topic']}")
    else:
        state = _load_state()
        if not state:
            raise RuntimeError("series_state.json not found — run Part 1 first")
        print(f"[{CFG['channel_name']}] Series Part {part} — topic: {state['topic']}")

    part_key = f"part{part}"
    data = state[part_key]

    print(f"  Title: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("Fetching stock clips...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("Synthesizing TTS...")
        words = text_to_speech(data["script"], audio_path)
        print(f"  Audio: {words[-1]['end']:.1f}s, {len(words)} words")

        print("Building video...")
        video_path, thumb_path = build_video(
            audio_path, clip_paths, words, video_path,
            topic=data.get("topic", state.get("topic")),
            part=part,
            total_parts=3,
            title=data["title"],
        )

        print("Publishing...")
        publish(
            data=data,
            video_path=video_path,
            thumb_path=thumb_path,
            words=words,
            topic=data.get("topic", state.get("topic", "")),
            alert=lambda step, e: _alert(f"{step} (Part {part})", e),
            enable_captions=False,  # временно (квота), как и в обычном пайплайне
            enable_pinterest=False,  # Pinterest только для обычных Shorts
        )

    print(f"Done — Part {part}/3 published.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify(f"🔴 [{CFG['channel_name']}] серия УПАЛА, Part не вышел:\n{e}")
        raise
