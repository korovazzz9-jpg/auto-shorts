"""Точка входа: тема -> сценарий -> стоковые клипы -> озвучка -> видео -> загрузка на YouTube + Instagram."""
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from config import CFG
from fetch_stock_video import fetch_clips
from generate_script import generate_script
from notify import notify
from publish import publish
from script_queue import pop_next
from tts import text_to_speech
from upload_captions import captions_fit_quota_today
from youtube_auth import get_authenticated_channel_title

load_dotenv()


def _alert(step: str, err: Exception) -> None:
    """Частичный сбой: видео залилось, но один из шагов отвалился. GitHub про это
    письмо НЕ шлёт (exit 0), поэтому сообщаем в Telegram сами."""
    msg = f"⚠️ [{CFG['channel_name']}] шаг «{step}» упал, но пайплайн продолжил:\n{err}"
    print(f"  {msg}")
    notify(msg)


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
    # Batch API preload (prepare_batch.py) экономит ~50% на этом вызове, если очередь заполнена.
    # Пустая очередь = сценарий генерится вживую, как раньше — отсутствие preload не ломает публикацию.
    data = pop_next()
    if data is not None:
        print(f"[{CFG['channel_name']}] 1/6 Сценарий из очереди (Batch API preload)...")
    else:
        print(f"[{CFG['channel_name']}] 1/6 Генерация сценария (вживую)...")
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
        video_path, thumb_path = build_video(audio_path, clip_paths, words, video_path, topic=data["topic"], title=data["title"], hook_text=data.get("hook_text"))

        print("5/6 Публикация...")
        publish(
            data=data,
            video_path=video_path,
            thumb_path=thumb_path,
            words=words,
            topic=data["topic"],
            alert=_alert,
            extra_tags=[
                f"topic-{data['topic'].replace(' ', '_')}",
                f"loop-{'yes' if data.get('has_loop') else 'no'}",
                f"hook-{data.get('hook_template', 'other')}",
                f"title-{data.get('title_variant', 'narrative')}",
                f"opener-{data.get('title_opener', 'other')}",
                f"tone-{data.get('emotional_tone', 'other')}",
            ],
            # 2026-07-04: кроме Вс (Pacific) — в Вс-день квоты выходят оба лонгформа,
            # субтитры Shorts + лонгформ в общие 10к не влезают (см. upload_captions).
            enable_captions=captions_fit_quota_today(),
            enable_pinterest=True,
        )

    print("Готово.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        # Жёсткий сбой — видео НЕ вышло. Сообщаем в Telegram и пробрасываем дальше,
        # чтобы GitHub Actions тоже пометил запуск красным.
        notify(f"🔴 [{CFG['channel_name']}] пайплайн УПАЛ, видео не вышло:\n{e}")
        raise
