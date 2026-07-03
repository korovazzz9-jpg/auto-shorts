"""Точка входа для еженедельного длинного видео-компиляции (3.5-4.5 мин, 5 фактов).
Не часть Shorts-расписания — отдельный workflow, раз в неделю. Не постится в Instagram
(там лимит длины Reels около 90 сек, не подходит)."""
import os
import random
import tempfile

from dotenv import load_dotenv

from build_longform_video import build_longform_video
from config import CFG
from fetch_stock_video import fetch_clips
from generate_longform_script import generate_longform_script
from notify import notify
from playlists import add_video_to_playlist
from post_comment import post_channel_comment, post_comment_reply
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


def _longform_tts(script: str, audio_path: str) -> list:
    """Лонгформ-озвучка: novita (MiniMax) если включено и есть ключ, иначе edge-tts.
    Фолбэк на edge-tts при любой ошибке novita — лонгформ не должен падать из-за TTS."""
    if CFG.get("longform_use_novita") and os.environ.get("NOVITA_KEY"):
        try:
            from tts_novita import text_to_speech_novita
            words = text_to_speech_novita(script, audio_path)
            print(f"  TTS: novita/{CFG.get('novita_voice')} — {words[-1]['end']:.1f}s")
            return words
        except Exception as e:
            print(f"  novita TTS упал, фолбэк на edge-tts: {e}")
            notify(f"⚠️ [{CFG['channel_name']}] лонгформ: novita TTS упал, edge-tts фолбэк:\n{e}")
    return text_to_speech(script, audio_path)


def _verify_channel() -> None:
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(
            f"Канал не совпадает с CHANNEL={os.environ.get('CHANNEL', 'en')}: "
            f"токен авторизован на '{actual}', ожидался '{expected}'. Останавливаюсь."
        )


def _chapter_lines(script: str, chapters: list, words: list[dict]) -> str:
    """Главы (key moments) для описания: маппит sentence_index из генерации на РЕАЛЬНЫЕ
    тайминги TTS (кумулятивный счётчик слов по предложениям → words[i]["start"]). Дрейф
    ±2-3с не критичен — главам не нужна покадровая точность.

    Требования YouTube: первая метка 0:00, минимум 3 главы, каждая ≥10 сек — иначе главы
    не подхватятся, поэтому невалидное просто отбрасываем (пустая строка = глав нет,
    описание как раньше). Любая кривизна данных от модели не должна ронять публикацию."""
    import re
    if not isinstance(chapters, list) or not words:
        return ""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s]
    # Стартовый индекс слова для каждого предложения (кумулятивно).
    starts, cum = [], 0
    for s in sentences:
        starts.append(cum)
        cum += len(s.split())

    entries = []
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        title = str(ch.get("title") or "").strip()
        idx = ch.get("sentence_index")
        if not title or not isinstance(idx, int) or idx < 0 or idx >= len(sentences):
            continue
        word_i = min(starts[idx], len(words) - 1)
        entries.append((words[word_i]["start"], title[:60]))

    entries.sort(key=lambda e: e[0])
    if not entries:
        return ""
    entries[0] = (0.0, entries[0][1])  # первая глава обязана начинаться с 0:00

    # Отбрасываем главы ближе 10с к предыдущей (требование YouTube).
    filtered = [entries[0]]
    for t, title in entries[1:]:
        if t - filtered[-1][0] >= 10.0:
            filtered.append((t, title))
    if len(filtered) < 3:
        return ""

    label = "Chapters:" if CFG["lang_code"] == "en" else "Capítulos:"
    lines = [label]
    for t, title in filtered:
        m, s = int(t) // 60, int(t) % 60
        lines.append(f"{m}:{s:02d} {title}")
    return "\n".join(lines)


def run() -> None:
    _verify_channel()
    print("1/4 Генерация сценария-компиляции...")
    data = generate_longform_script()
    print(f"  Формат: {data.get('longform_format', '?')} | Тема: {data['theme']} | Заголовок: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("2/4 Подбор стоковых видео (горизонтальные 16:9)...")
        clip_paths = fetch_clips(data["video_queries"], tmp, landscape=True)

        print("3/4 Озвучка и сборка видео (горизонтальный лонгформ)...")
        words = _longform_tts(data["script"], audio_path)
        video_path, thumb_path = build_longform_video(audio_path, clip_paths, words, video_path, topic=data["theme"], title=data["title"], thumb_text=data.get("thumb_text"))

        print("4/4 Загрузка на YouTube...")
        description = data["script"]
        search_summary = str(data.get("search_summary", "")).strip()
        if search_summary:  # ключевые слова для YouTube Search — скрипт их почти не содержит
            description = f"{search_summary}\n\n{description}"
        # Главы (key moments, 2026-07-03): бесплатный SEO-бонус — YouTube показывает главы
        # в поиске. Тайминги — из реальной озвучки, не оценка. Пусто = глав нет, как раньше.
        chapters_block = _chapter_lines(data["script"], data.get("chapters", []), words)
        if chapters_block:
            description += f"\n\n{chapters_block}"
        # Кросс-промо EN↔ES — та же логика, что в publish.py для Shorts.
        sister_handle = CFG.get("sister_channel_handle", "")
        sister_ctas = CFG.get("sister_desc_ctas", [])
        if sister_handle and sister_ctas:
            description += f"\n\n{random.choice(sister_ctas)} https://www.youtube.com/@{sister_handle}"
        tags = list(data["tags"]) + list(CFG.get("sister_lang_tags", []))
        video_id = upload_to_youtube(
            video_path,
            title=data["title"],
            description=description,
            tags=tags,
            hashtags=data["hashtags"],
            hashtag_position="end",
            thumbnail_path=thumb_path,
            default_language=CFG["lang_code"],  # нужен для локализаций метаданных
        )

        # Локализация метаданных на язык сестринского канала — как в publish.py.
        try:
            from localize_metadata import add_sister_localization
            add_sister_localization(video_id, data["title"], description)
        except Exception as e:
            _alert("localization", e)

        # Субтитры включены (2026-07-03) — квота больше не проблема (videos.insert в своём бакете).
        try:
            upload_captions(video_id, words)
        except Exception as e:
            _alert("captions", e)

        try:
            add_video_to_playlist(video_id, data["theme"])
        except Exception as e:
            _alert("playlist", e)

    # Закреп-коммент: вопрос-провокация (engagement density) + подписка. Зритель, досмотревший
    # длинный разбор, — самый горячий кандидат в подписчики (subs+часы = порог монетизации).
    try:
        channel_url = f"https://www.youtube.com/@{CFG['channel_handle']}" if CFG.get("channel_handle") else ""
        comment = CFG.get("longform_comment", "").format(channel_url=channel_url).strip()
        if comment:
            comment_id = post_channel_comment(video_id, comment)
            replies = CFG.get("first_comment_replies", [])
            reply = random.choice(replies) if replies else ""
            if reply:
                try:
                    post_comment_reply(comment_id, reply)
                except Exception as e:
                    _alert("comment reply", e)
    except Exception as e:
        _alert("comment", e)

    # Запоминаем id для воронки Shorts→лонгформ (daily/серии вставят ссылку в описание+коммент).
    # Файл коммитит weekly-longform workflow тем же шагом, что и формат-ротацию.
    try:
        from longform_link import set_last_longform
        set_last_longform(video_id, theme=data["theme"])
    except Exception as e:
        _alert("last-longform-link", e)

    url = f"https://youtube.com/watch?v={video_id}"
    # End Screen (Subscribe + похожее видео) доступен только вручную в Studio — API его не
    # даёт. Раз лонгформ выходит 1 раз/неделю — это 2 минуты в Studio, бесплатно и конвертит
    # самого «горячего» зрителя канала (досмотревшего разбор) в подписчика.
    notify(
        f"✅ [{CFG['channel_name']}] лонгформ опубликован:\n{data['title']}\n{url}\n\n"
        f"📌 Не забудь добавить End Screen (Subscribe + похожее видео) вручную в YouTube Studio."
    )
    print(f"Готово: {url}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify(f"🔴 [{CFG['channel_name']}] лонгформ УПАЛ:\n{e}")
        raise
