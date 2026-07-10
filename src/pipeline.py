"""Точка входа: тема -> сценарий -> стоковые клипы -> озвучка -> видео -> загрузка на YouTube + Instagram."""
import os
import random
import tempfile
from datetime import datetime, timezone

from dotenv import load_dotenv

from build_video import build_video
from config import CFG, CHANNEL
from fetch_stock_video import fetch_clips
from generate_script import generate_script
from notify import notify
from paired_facts import PAIR_PROBABILITY, find_pending_pair, resolve_pair, start_pair
from post_comment import post_channel_comment
from publish import publish
from script_queue import pop_next
from tts import text_to_speech
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
    # «On this day» (2026-07-05): раз в неделю (Чт, первый слот дня) — топикал-факт с привязкой
    # к сегодняшней дате. Мимо очереди: batch-заготовки генерятся заранее и дату не знают.
    now = datetime.now(timezone.utc)
    topical = now.weekday() == 3 and now.hour == CFG.get("topical_slot_hour", -1)

    # Video pairs (2026-07-08, см. paired_facts.py): если есть открытая пара, готовая на
    # резолюцию — пробуем закрыть её; иначе с малой вероятностью пробуем НАЧАТЬ новую. Оба
    # случая требуют LIVE-генерации мимо очереди (batch-заготовки не знают о парах), тот же
    # паттерн, что «On this day».
    pending_pair = None if topical else find_pending_pair(CHANNEL)
    pair_start_mode = not topical and not pending_pair and random.random() < PAIR_PROBABILITY

    # Batch API preload (prepare_batch.py) экономит ~50% на этом вызове, если очередь заполнена.
    # Пустая очередь = сценарий генерится вживую, как раньше — отсутствие preload не ломает публикацию.
    force_live = topical or pending_pair or pair_start_mode
    data = None if force_live else pop_next()
    if data is not None:
        print(f"[{CFG['channel_name']}] 1/6 Сценарий из очереди (Batch API preload)...")
    else:
        label = ("топикал «On this day», мимо очереди" if topical else
                  "резолюция пары, мимо очереди" if pending_pair else
                  "старт пары, мимо очереди" if pair_start_mode else "вживую")
        print(f"[{CFG['channel_name']}] 1/6 Генерация сценария ({label})...")
        data = generate_script(
            on_this_day=topical,
            pair_start=pair_start_mode,
            pair_resolve_claim=pending_pair["claim"] if pending_pair else None,
        )
    print(f"  Тема: {data['topic']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/6 Подбор стоковых видео под смысл сценария...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("3/6 Озвучка...")
        words, voice = text_to_speech(data["script"], audio_path)

        print("4/6 Сборка видео...")
        # Пара, часть A (2026-07-10): видео реально откроет пару (claim непустой) → финальный
        # CTA-бейдж заменяется тизером «у факта будет продолжение — подпишись» (см.
        # pair_cta_phrases в config). Только визуально: озвучка/петля не трогаются.
        pair_tease = bool(pair_start_mode and str(data.get("pairable_claim", "")).strip())
        video_path, thumb_path, caption_color = build_video(audio_path, clip_paths, words, video_path, topic=data["topic"], title=data["title"], hook_text=data.get("hook_text"), pair_tease=pair_tease)

        print("5/6 Публикация...")
        extra_tags = [
            f"topic-{data['topic'].replace(' ', '_')}",
            f"loop-{'yes' if data.get('has_loop') else 'no'}",
            f"hook-{data.get('hook_template', 'other')}",
            f"title-{data.get('title_variant', 'narrative')}",
            f"opener-{data.get('title_opener', 'other')}",
            f"tone-{data.get('emotional_tone', 'other')}",
            f"color-{caption_color}",
            f"voice-{voice}",
        ]
        if data.get("topical"):
            extra_tags.append("topical-onthisday")
        if data.get("niche_styled"):
            extra_tags.append("niche-styled")
        if data.get("niche_recreated"):
            extra_tags.append("niche-recreation")
        # Пара считается закрытой ТОЛЬКО если модель реально нашла честное противоречие
        # (pair_resolved). При отказе (pair_resolved=False) generate_script вернул ОБЫЧНЫЙ
        # факт на тему, не связанный с claim части A — тогда это НЕ pair-b: ни тега, ни
        # callback-коммента на A (иначе под несвязанным видео висела бы ложная ссылка
        # «помнишь, мы говорили…» — 2026-07-08, баг найден на ревью).
        pair_resolved = bool(pending_pair and data.get("pair_resolved"))
        if pair_resolved:
            extra_tags.append("pair-b")
        elif pair_start_mode and data.get("pairable_claim"):
            extra_tags.append("pair-a")

        # Video pairs (2026-07-08): если это резолюция пары, B ссылается на A в закреп-комменте
        # (шаблонный пул, не модель — тот же принцип, что first_comment_subscribe_ctas: избежать
        # дословно одинакового текста под каждым видео).
        pair_extra_comment = ""
        if pair_resolved:
            callback_pool = CFG.get("pair_callback_ctas", [])
            if callback_pool:
                a_url = f"https://youtube.com/shorts/{pending_pair['part_a_video_id']}"
                pair_extra_comment = f"{random.choice(callback_pool)} {a_url}"

        video_id = publish(
            data=data,
            video_path=video_path,
            thumb_path=thumb_path,
            words=words,
            topic=data["topic"],
            alert=_alert,
            extra_tags=extra_tags,
            extra_comment=pair_extra_comment,
            voice=voice,
            caption_color=caption_color,
            # 2026-07-04: одна дорожка (язык канала) — 550 ед/видео, влезает даже в Вс
            # с двумя лонгформами. Вс-пропуск снят вместе с удалением переводных дорожек.
            enable_captions=True,
            enable_pinterest=True,
        )

        # Video pairs: закрываем открытую пару / открываем новую (после публикации — нужен
        # video_id). Резолюция ТОЛЬКО если модель реально нашла честное противоречие
        # (pair_resolved=True) — иначе оставляем пару открытой для следующей попытки.
        if pair_resolved:
            part_a_id = resolve_pair(CHANNEL, pending_pair["id"], video_id)
            if part_a_id:
                try:
                    backlink_pool = CFG.get("pair_backlink_ctas", [])
                    if backlink_pool:
                        b_url = f"https://youtube.com/shorts/{video_id}"
                        post_channel_comment(part_a_id, f"{random.choice(backlink_pool)} {b_url}")
                except Exception as e:
                    _alert("pair backlink", e)
        elif pair_start_mode and data.get("pairable_claim"):
            try:
                start_pair(CHANNEL, video_id, data["title"], data["pairable_claim"], data["topic"])
            except Exception as e:
                _alert("pair start", e)

    print("Готово.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        # Жёсткий сбой — видео НЕ вышло. Сообщаем в Telegram и пробрасываем дальше,
        # чтобы GitHub Actions тоже пометил запуск красным.
        notify(f"🔴 [{CFG['channel_name']}] пайплайн УПАЛ, видео не вышло:\n{e}")
        raise
