"""Связка Shorts → лонгформ: лонгформ-пайплайн записывает id своего последнего ролика
(и тему, которой он посвящён), daily/серии читают его и вставляют ссылку в описание +
закреплённый коммент.

Цель — воронка: дешёвый Shorts-трафик уводится в длинные видео ради часов просмотра
(порог монетизации лонгформа = 4000 ч). Приоритет — тематическое совпадение (Short про
"the ocean" ведёт на лонгформ про "the ocean", если такой уже выходил): совпадение темы
поднимает релевантность и CTR перехода. Если тематического лонгформа ещё не было —
фолбэк на последний лонгформ вообще (продаём формат «глубокий разбор» как таковой).

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


def set_last_longform(video_id: str, theme: str = "") -> None:
    """Сохраняет id последнего лонгформа + карту тема->id (read-modify-write — формат-ротацию
    не трогаем). theme использует тот же TOPICS_POOL, что и Shorts (generate_script.py),
    поэтому сравнение точным совпадением строки, без нечёткого мэтчинга."""
    state = _load()
    state["last_video_id"] = video_id
    if theme:
        by_topic = state.setdefault("by_topic", {})
        by_topic[theme] = video_id
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_last_longform_url(topic: str = "") -> str:
    """URL лонгформа для воронки (watch?v= — горизонтальное видео, не /shorts/).
    Если для topic уже выходил лонгформ на ту же тему — ссылка на него (релевантнее,
    выше CTR перехода). Иначе — последний лонгформ вообще. Пусто, если лонгформов не было."""
    state = _load()
    vid = None
    if topic:
        vid = state.get("by_topic", {}).get(topic)
    if not vid:
        vid = state.get("last_video_id")
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""
