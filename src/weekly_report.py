"""Еженедельная retention-сводка (хук-шаблоны, петля, темы) в Telegram.
Не тратит Claude — только YouTube Analytics/Data API (переиспользует
_recent_videos/_retention из analytics_retention.py). Запуск:
  python weekly_report.py            # EN
  CHANNEL=es python weekly_report.py # ES
"""
import json
import os
from datetime import date

from dotenv import load_dotenv

from analytics_retention import _recent_videos, _retention
from config import CFG, CHANNEL
from notify import notify
from youtube_auth import get_analytics_client, get_client

load_dotenv()

HOOK_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", f"hook_stats_{CHANNEL}.json")
MIN_HOOK_SAMPLE = 5  # меньше видео на шаблон — рано делать выводы, файл не пишем


def _avg_by(videos: list[dict], key: str, min_pct: float = 0.0) -> list[tuple[str, float, int]]:
    """Средний % досмотра, сгруппированный по video[key]. Видео без данных (pct<=min_pct)
    исключены — иначе свежие ролики (лаг Analytics) занижают среднее нулями."""
    groups: dict[str, list[float]] = {}
    for v in videos:
        if v["pct"] > min_pct:
            groups.setdefault(v[key], []).append(v["pct"])
    return sorted(
        ((k, sum(p) / len(p), len(p)) for k, p in groups.items()),
        key=lambda kv: -kv[1],
    )


def _videos_with_retention() -> list[dict]:
    youtube = get_client()
    analytics = get_analytics_client()
    videos = _recent_videos(youtube)
    if not videos:
        return []
    start = min(v["published"] for v in videos)
    end = date.today().isoformat()
    ret = _retention(analytics, [v["id"] for v in videos], start, end)
    for v in videos:
        r = ret.get(v["id"], {})
        v["pct"] = float(r.get("pct", 0) or 0)
        v["views"] = int(r.get("views", 0) or 0)
    return videos


def save_hook_stats(videos: list[dict]) -> None:
    """Лучший по retention хук-шаблон недели → hook_stats_<channel>.json (коммитит
    weekly-report.yml). generate_script._hook_preference() читает его и мягко подсказывает
    модели предпочтительный шаблон — данные аналитики замыкаются обратно в генерацию."""
    hooks = [(k, avg, n) for k, avg, n in _avg_by(videos, "hook")
             if k not in ("—", "other") and n >= MIN_HOOK_SAMPLE]
    if not hooks:
        print(f"  hook_stats: <{MIN_HOOK_SAMPLE} видео на шаблон — данных мало, файл не трогаем.")
        return
    best_template, avg, n = hooks[0]
    with open(HOOK_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({"best_template": best_template, "avg_pct": round(avg, 1), "videos": n,
                   "updated": date.today().isoformat()}, f, ensure_ascii=False, indent=2)
    print(f"  hook_stats: {best_template} ({avg:.1f}%, n={n})")


def build_report(videos: list[dict]) -> str:
    if not videos:
        return f"📊 [{CFG['channel_name']}] Нет видео для отчёта."

    lines = [f"📊 Retention-сводка за неделю: {CFG['channel_name']}"]

    hooks = _avg_by(videos, "hook")
    if hooks:
        lines.append("\nХук-шаблоны:")
        for name, avg, n in hooks[:5]:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    loops = _avg_by(videos, "loop")
    loops = [(k, a, n) for k, a, n in loops if k in ("yes", "no")]
    if loops:
        lines.append("\nПетля:")
        for name, avg, n in loops:
            label = "с петлёй" if name == "yes" else "без петли"
            lines.append(f"  {avg:5.1f}%  ({n:2})  {label}")

    topics = _avg_by(videos, "topic")
    if topics:
        lines.append("\nТоп-3 темы:")
        for name, avg, n in topics[:3]:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    by_views = [v for v in videos if v.get("views", 0) > 0]
    if by_views:
        top = max(by_views, key=lambda v: v["views"])
        url = f"https://youtube.com/shorts/{top['id']}"
        lines.append(
            f"\n🧪 Топ по просмотрам: {top['title']} ({top['views']} views)\n{url}\n"
            f"Попробуй Test & Compare в YouTube Studio (заголовок/тумба) — это ручной шаг, "
            f"API для этого нет."
        )

    return "\n".join(lines)


if __name__ == "__main__":
    videos = _videos_with_retention()
    notify(build_report(videos))
    save_hook_stats(videos)
