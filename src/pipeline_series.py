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
from playlists import add_video_to_playlist_by_id, create_playlist
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


def _determine_part() -> int:
    """Номер части определяем по ПРОГРЕССУ серии (`next_part` в state), а НЕ по дню недели.
    Так устойчиво к тому, во сколько и в какой день cron запустил воркфлоу (раньше `date +%u`
    давал Part 1 и в Вс, и в Пн → две первые части подряд). Ручной override: SERIES_PART=1/2/3."""
    requested = os.environ.get("SERIES_PART", "").strip()
    if requested in ("1", "2", "3"):
        return int(requested)
    st = _load_state()
    np = st.get("next_part")
    return np if isinstance(np, int) and 2 <= np <= 3 else 1


def _series_extra_comment(part: int, state: dict) -> str:
    """Текст в закреп-коммент серии: ссылка на плейлист (зритель с любой части найдёт
    остальные по порядку) + для Part 3 прямые ссылки на уже вышедшие Part 1/2."""
    lines = []
    pid = state.get("playlist_id")
    if pid:
        cta = CFG.get("series_playlist_cta", "Watch the full series in order 👉")
        lines.append(f"{cta} https://www.youtube.com/playlist?list={pid}")
    if part == 3:  # части 1/2 уже вышли — даём прямые ссылки
        for n in (1, 2):
            vid = state.get(f"part{n}_video_id")
            if vid:
                lines.append(f"Part {n} 👉 https://youtube.com/shorts/{vid}")
    return "\n".join(lines)


def run() -> None:
    # Проверяем канал
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(f"Wrong channel: got '{actual}', expected '{expected}'")

    part = _determine_part()

    # Part 1 — генерируем все 3 части и сохраняем; Part 2/3 — читаем готовый state.
    if part == 1:
        print(f"[{CFG['channel_name']}] Series Part 1 — generating all 3 scripts...")
        state = generate_series()
        _save_state(state)
        print(f"  Topic: {state['topic']}")
    else:
        state = _load_state()
        if not state or f"part{part}" not in state:
            raise RuntimeError(f"series_state без part{part} — сначала нужен Part 1")
        print(f"[{CFG['channel_name']}] Series Part {part} — topic: {state['topic']}")

    part_key = f"part{part}"
    data = state[part_key]

    print(f"  Title: {data['title']}")

    # Серия: один плейлист на цикл (создаём в Part 1) — навигация между частями.
    if part == 1 and not state.get("playlist_id"):
        try:
            series_title = data["title"].split("|")[0].strip()
            state["playlist_id"] = create_playlist(series_title)
            print(f"  Создан плейлист серии: {state['playlist_id']}")
        except Exception as e:
            _alert("create playlist", e)

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
        video_id = publish(
            data=data,
            video_path=video_path,
            thumb_path=thumb_path,
            words=words,
            topic=data.get("topic", state.get("topic", "")),
            alert=lambda step, e: _alert(f"{step} (Part {part})", e),
            extra_comment=_series_extra_comment(part, state),  # плейлист + ссылки на части
            enable_captions=False,  # временно (квота), как и в обычном пайплайне
            enable_pinterest=False,  # Pinterest только для обычных Shorts
        )

    # Добавляем часть в плейлист серии и запоминаем её id (для ссылок в Part 3 и навигации).
    if state.get("playlist_id"):
        try:
            add_video_to_playlist_by_id(video_id, state["playlist_id"])
        except Exception as e:
            _alert("add to playlist", e)
    state[f"part{part}_video_id"] = video_id

    # Прогресс серии: помечаем следующую часть. Воркфлоу закоммитит обновлённый state,
    # и следующий запуск опубликует именно её (а после Part 3 → next_part=4 → новый цикл).
    state["next_part"] = part + 1
    _save_state(state)
    print(f"Done — Part {part}/3 published. next_part={part + 1}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify(f"🔴 [{CFG['channel_name']}] серия УПАЛА, Part не вышел:\n{e}")
        raise
