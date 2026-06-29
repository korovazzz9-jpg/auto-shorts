"""Связка Shorts → лонгформ: лонгформ-пайплайн записывает id своего последнего ролика,
daily/серии читают его и вставляют ссылку в описание + закреплённый коммент.

Цель — воронка: дешёвый Shorts-трафик уводится в длинные видео ради часов просмотра
(порог монетизации лонгформа = 4000 ч). Тема ролика не важна: ведём на «глубокий разбор»
как на формат, а не как на продолжение конкретной темы.

Состояние храним в том же файле, что и ротация форматов (longform_state_<channel>.json,
коммитится weekly-longform workflow) — read-modify-write, чтобы не затирать last_format_index.
"""
import json
import os

from config import CHANNEL

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", f"longform_state_{CHANNEL}.json")


def _load() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def set_last_longform(video_id: str) -> None:
    """Сохраняет id последнего лонгформа (read-modify-write — формат-ротацию не трогаем)."""
    state = _load()
    state["last_video_id"] = video_id
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_last_longform_url() -> str:
    """URL последнего лонгформа (watch?v= — это горизонтальное видео, не /shorts/).
    Пусто, если лонгформов ещё не было."""
    vid = _load().get("last_video_id")
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""
