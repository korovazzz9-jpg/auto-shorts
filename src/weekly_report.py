"""Еженедельная retention-сводка (хук-шаблоны, петля, темы) в Telegram.
Не тратит Claude — только YouTube Analytics/Data API (переиспользует
_recent_videos/_retention из analytics_retention.py). Запуск:
  python weekly_report.py            # EN
  CHANNEL=es python weekly_report.py # ES
"""
from datetime import date

from dotenv import load_dotenv

from analytics_retention import _recent_videos, _retention
from config import CFG
from notify import notify
from youtube_auth import get_analytics_client, get_client

load_dotenv()


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


def build_report() -> str:
    youtube = get_client()
    analytics = get_analytics_client()
    videos = _recent_videos(youtube)
    if not videos:
        return f"📊 [{CFG['channel_name']}] Нет видео для отчёта."

    start = min(v["published"] for v in videos)
    end = date.today().isoformat()
    ret = _retention(analytics, [v["id"] for v in videos], start, end)
    for v in videos:
        r = ret.get(v["id"], {})
        v["pct"] = float(r.get("pct", 0) or 0)
        v["views"] = int(r.get("views", 0) or 0)

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

    return "\n".join(lines)


if __name__ == "__main__":
    notify(build_report())
